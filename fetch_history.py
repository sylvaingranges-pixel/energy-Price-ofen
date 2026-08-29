#!/usr/bin/env python3
"""Constitue l'archive des trimestres clos, dans data/.

L'application lit ces fichiers en même origine : ils sont servis tels quels par
Netlify, GitHub Pages ou serve.py, sans configuration particulière. Les
trimestres archivés ne sollicitent plus l'API — plus rapide pour vos visiteurs,
et le quota de l'API est préservé.

    python3 fetch_history.py 2020 2026      # de 2020 à 2026
    python3 fetch_history.py 2025           # une seule année
    python3 fetch_history.py --force 2025   # réécrit même si déjà présent
    python3 fetch_history.py --tech "Solar,Wind onshore" 2024 2026

Seuls les trimestres **terminés** sont écrits : le trimestre en cours reste
servi en direct, l'archive ne devient donc jamais périmée.

Aucune dépendance : bibliothèque standard uniquement.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

API = "https://api.energy-charts.info"
FX = "https://api.frankfurter.dev/v1"
FX_FALLBACK = "https://api.frankfurter.app"
ZH = ZoneInfo("Europe/Zurich")
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")

RETRYABLE = {429, 500, 502, 503, 504}
_last_call = [0.0]


def get_json(url, attempts=5, min_gap=0.5):
    """GET avec espacement et reprise sur limite de débit, comme le fait l'application."""
    for i in range(attempts):
        gap = _last_call[0] + min_gap - time.monotonic()
        if gap > 0:
            time.sleep(gap)
        _last_call[0] = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pv-reference-price-archive/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code not in RETRYABLE or i == attempts - 1:
                raise
            retry_after = e.headers.get("Retry-After") if e.headers else None
            wait = float(retry_after) if (retry_after or "").strip().isdigit() else min(2.0 * (2.2 ** i), 60)
            print(f"    HTTP {e.code} — nouvelle tentative dans {wait:.0f} s", file=sys.stderr)
            time.sleep(wait)
        except urllib.error.URLError:
            if i == attempts - 1:
                raise
            time.sleep(min(2.0 * (2.2 ** i), 60))
    raise RuntimeError("inatteignable")


def quarter_bounds(year, q):
    first = date(year, (q - 1) * 3 + 1, 1)
    last = date(year + (q == 4), (q * 3) % 12 + 1, 1) - timedelta(days=1)
    return first, last


def zurich_unix(d):
    """Instant unix de minuit, heure suisse — les journées de 23 h et 25 h comprises."""
    return int(datetime(d.year, d.month, d.day, tzinfo=ZH).timestamp())


def encode_times(times):
    """Une grille régulière se décrit par trois nombres plutôt que par 8832.

    C'est la moitié du poids du fichier. Si la grille a un trou, on retombe sur
    la liste complète — la justesse passe avant la compacité.
    """
    if len(times) >= 2:
        step = times[1] - times[0]
        if step > 0 and all(times[i] - times[i - 1] == step for i in range(1, len(times))):
            return {"t0": times[0], "step": step, "n": len(times)}
    return {"t": times}


def trim(times, values, start, end):
    """Ne garde que [start, end[ et écarte les valeurs manquantes."""
    t, v = [], []
    for ts, val in zip(times, values):
        if start <= ts < end and val is not None:
            t.append(ts)
            v.append(val)
    return t, v


def fetch_quarter(year, q, techs):
    first, last = quarter_bounds(year, q)
    start_ts, end_ts = zurich_unix(first), zurich_unix(last + timedelta(days=1))
    a, b = first.isoformat(), (last + timedelta(days=1)).isoformat()

    print(f"  {year}-Q{q}  {a} → {last.isoformat()}")

    print("    prix…", file=sys.stderr)
    praw = get_json(f"{API}/price?bzn=CH&start={a}&end={b}")
    pt, pv = trim(praw["unix_seconds"], praw.get("price") or praw.get("data"), start_ts, end_ts)
    if not pt:
        raise RuntimeError("aucun prix renvoyé")

    print("    production…", file=sys.stderr)
    qraw = get_json(f"{API}/public_power?country=ch&start={a}&end={b}")
    available = {p["name"]: p["data"] for p in qraw.get("production_types", [])}
    missing = [t for t in techs if t not in available]
    if missing:
        raise RuntimeError(f"technologies absentes : {', '.join(missing)} "
                           f"(disponibles : {', '.join(sorted(available))})")

    # Une seule grille temporelle pour toutes les technologies : on aligne d'abord,
    # puis on ne garde que les instants où chaque série demandée a une valeur.
    keep = [i for i, ts in enumerate(qraw["unix_seconds"])
            if start_ts <= ts < end_ts and all(available[t][i] is not None for t in techs)]
    qt = [qraw["unix_seconds"][i] for i in keep]
    series = {t: [round(available[t][i], 1) for i in keep] for t in techs}
    if not qt:
        raise RuntimeError("aucune production renvoyée")

    print("    taux de change…", file=sys.stderr)
    fx = fetch_fx(first, last)

    return {
        "quarter": f"{year}-Q{q}",
        "from": a,
        "to": last.isoformat(),
        "generated": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "price": {**encode_times(pt), "v": [round(x, 2) for x in pv], "unit": praw.get("unit", "EUR/MWh")},
        "power": {**encode_times(qt), "techs": series, "unit": "MW"},
        "fx": fx,
        "license": praw.get("license_info", "CC BY 4.0 — energy-charts.info, Fraunhofer ISE"),
    }


def fetch_fx(first, last):
    """Taux EUR→CHF par jour civil, reportés sur les jours sans cotation (BCE)."""
    padded = (first - timedelta(days=10)).isoformat()
    raw = None
    for base in (f"{FX}/{padded}..{last.isoformat()}", f"{FX_FALLBACK}/{padded}..{last.isoformat()}"):
        try:
            raw = get_json(f"{base}?base=EUR&symbols=CHF", attempts=3)
            break
        except Exception:
            continue
    if not raw or "rates" not in raw:
        print("    (taux indisponibles — le fichier s'en passera)", file=sys.stderr)
        return {}

    quoted = sorted((d, o["CHF"]) for d, o in raw["rates"].items() if o.get("CHF"))
    if not quoted:
        return {}
    out, i, cur = {}, 0, quoted[0][1]
    d = first
    while d <= last:
        iso = d.isoformat()
        while i < len(quoted) and quoted[i][0] <= iso:
            cur = quoted[i][1]
            i += 1
        out[iso] = round(cur, 5)
        d += timedelta(days=1)
    return out


def closed_quarters(y0, y1):
    """Trimestres entièrement terminés — le trimestre courant reste servi en direct."""
    today = datetime.now(ZH).date()
    for y in range(y0, y1 + 1):
        for q in (1, 2, 3, 4):
            if quarter_bounds(y, q)[1] < today:
                yield y, q


def main():
    ap = argparse.ArgumentParser(description="Archive les trimestres clos dans data/.")
    ap.add_argument("years", nargs="+", type=int, metavar="ANNÉE",
                    help="une année, ou une première et une dernière")
    ap.add_argument("--tech", default="Solar",
                    help="technologies à archiver, séparées par des virgules (défaut : Solar)")
    ap.add_argument("--force", action="store_true", help="réécrit les fichiers déjà présents")
    args = ap.parse_args()

    y0, y1 = (args.years * 2)[:2] if len(args.years) == 1 else (min(args.years), max(args.years))
    techs = [t.strip() for t in args.tech.split(",") if t.strip()]
    os.makedirs(DATA, exist_ok=True)

    index_path = os.path.join(DATA, "index.json")
    index = {"quarters": {}}
    if os.path.exists(index_path):
        try:
            index = json.load(open(index_path, encoding="utf-8"))
            index.setdefault("quarters", {})
        except Exception:
            pass

    todo = list(closed_quarters(y0, y1))
    if not todo:
        sys.exit(f"Aucun trimestre terminé entre {y0} et {y1}.")

    print(f"{len(todo)} trimestre(s) à examiner — technologies : {', '.join(techs)}\n")
    written = skipped = failed = 0
    for y, q in todo:
        key = f"{y}-Q{q}"
        entry = index["quarters"].get(key)
        if entry and not args.force and os.path.exists(os.path.join(DATA, entry.get("file", ""))) \
                and all(t in entry.get("techs", []) for t in techs):
            print(f"  {key}  déjà archivé")
            skipped += 1
            continue
        try:
            data = fetch_quarter(y, q, techs)
        except Exception as e:
            print(f"  {key}  ÉCHEC : {e}", file=sys.stderr)
            failed += 1
            continue
        name = f"{key}.json"
        with open(os.path.join(DATA, name), "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        size = os.path.getsize(os.path.join(DATA, name))
        index["quarters"][key] = {
            "file": name, "from": data["from"], "to": data["to"],
            "complete": True, "techs": techs, "bytes": size,
        }
        print(f"    → data/{name}  ({size / 1024:.0f} Ko)")
        written += 1

    index["generated"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    index["bzn"] = "CH"
    index["source"] = "energy-charts.info (Fraunhofer ISE), CC BY 4.0"
    index["quarters"] = dict(sorted(index["quarters"].items()))
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)

    total = sum(e.get("bytes", 0) for e in index["quarters"].values())
    print(f"\n{written} écrit(s), {skipped} déjà présent(s), {failed} en échec.")
    print(f"Archive : {len(index['quarters'])} trimestre(s), {total / 1048576:.1f} Mo dans data/.")
    if written:
        print("Pensez à committer data/ pour que l'archive parte en ligne avec le site.")


if __name__ == "__main__":
    main()
