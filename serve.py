#!/usr/bin/env python3
"""Serveur local pour l'application « Prix de reprise PV ».

Sert les fichiers du dossier et relaie /api/... vers api.energy-charts.info,
ce qui évite tout problème de CORS quand la page n'est pas ouverte en file://.

    python3 serve.py            # http://localhost:8765
    python3 serve.py 9000       # autre port
    python3 serve.py --no-open  # sans ouvrir le navigateur

Aucune dépendance : bibliothèque standard uniquement.
"""

import http.server
import os
import socketserver
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

UPSTREAM = "https://api.energy-charts.info"
ALLOWED_PATHS = ("/price", "/public_power", "/total_power", "/installed_power", "/cbpf", "/signal")
ROOT = os.path.dirname(os.path.abspath(__file__))
TIMEOUT = 60


class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    # -- relais ------------------------------------------------------------
    def do_GET(self):
        if self.path.startswith("/api/"):
            self.proxy()
        else:
            super().do_GET()

    def proxy(self):
        target = self.path[len("/api"):] or "/"
        path_only = urllib.parse.urlparse(target).path
        if path_only not in ALLOWED_PATHS:
            self.send_error(403, "Chemin non autorise par le relais")
            return

        url = UPSTREAM + target
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "pv-reference-price-local/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                body = r.read()
                ctype = r.headers.get("Content-Type", "application/json")
                status = r.status
        except urllib.error.HTTPError as e:
            body = e.read() or str(e).encode()
            ctype = e.headers.get("Content-Type", "text/plain") if e.headers else "text/plain"
            status = e.code
        except Exception as e:                       # DNS, TLS, timeout…
            body = f"Relais: impossible de joindre {url} ({e})".encode()
            ctype = "text/plain; charset=utf-8"
            status = 502

        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # -- confort -----------------------------------------------------------
    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    args = [a for a in sys.argv[1:] if a != "--no-open"]
    port = int(args[0]) if args else 8765
    open_browser = "--no-open" not in sys.argv

    try:
        httpd = Server(("127.0.0.1", port), Handler)
    except OSError as e:
        sys.exit(f"Impossible d'ouvrir le port {port} : {e}\nEssayez : python3 serve.py {port + 1}")

    url = f"http://localhost:{port}/index.html"
    print(f"\n  Prix de reprise PV — serveur local\n  {url}\n  (Ctrl+C pour arreter)\n")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Arret.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
