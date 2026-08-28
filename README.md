# Prix de reprise du solaire injecté — Suisse

Petite application web **autonome** (un seul fichier HTML, aucune dépendance, aucun build) qui estime en
direct le **prix de marché de référence** photovoltaïque au sens de l'art. 15 OEneR — celui que l'OFEN ne
publie qu'a posteriori, une fois le trimestre terminé.

Le principe : récupérer les prix spot day-ahead suisses et la courbe de production PV nationale sur
[energy-charts.info](https://www.energy-charts.info) (Fraunhofer ISE), puis calculer la moyenne des prix
**pondérée par la production** :

```
PMR = Σ (prix_t × production_t × Δt) ÷ Σ (production_t × Δt)
```

C'est exactement la définition retenue par l'OFEN, appliquée à des données disponibles le jour même.

## Utilisation

### 1. Ouvrir le fichier directement

Double-cliquez sur `index.html`. Si votre navigateur autorise l'appel à `api.energy-charts.info` depuis un
fichier local, tout fonctionne immédiatement.

### 2. Passer par le serveur local (recommandé)

La plupart des navigateurs bloquent les requêtes réseau depuis `file://` (politique CORS). Dans ce cas :

```sh
python3 serve.py
```

Le navigateur s'ouvre sur <http://localhost:8765>. `serve.py` sert la page et relaie `/api/...` vers
energy-charts, ce qui supprime le problème. Aucune dépendance : bibliothèque standard Python 3 uniquement.

```sh
python3 serve.py 9000      # autre port
python3 serve.py --no-open # sans ouvrir le navigateur
```

### 3. Déployer sur Netlify (recommandé pour une mise en ligne)

Le dépôt contient déjà `netlify.toml` et `_redirects`. Ils demandent à Netlify de **relayer `/api/…` vers
energy-charts côté serveur** :

```
/api/*  https://api.energy-charts.info/:splat  200
```

Le `200` est essentiel : c'est un proxy, pas une redirection. Le navigateur n'appelle qu'une seule origine —
la vôtre — et la question du CORS disparaît. C'est exactement ce que fait `serve.py` en local.

Déployez le **dossier** (ou branchez le dépôt), pas le seul `index.html` : un fichier isolé n'emporte pas les
règles de relais. Si le site est déjà en ligne sans elles, il suffit de redéployer avec les deux fichiers à la
racine.

Le même principe vaut pour Vercel — créez un `vercel.json` :

```json
{ "rewrites": [{ "source": "/api/:path*", "destination": "https://api.energy-charts.info/:path*" }] }
```

### 4. Publier sur GitHub Pages

Activez Pages sur la branche voulue (Settings → Pages → Source : la branche, dossier `/`). Contrairement à
Netlify, **Pages ne sait pas relayer** : `netlify.toml` et `_redirects` y sont ignorés, et `serve.py` n'y
tourne pas. Deux cas :

- si `api.energy-charts.info` autorise les appels navigateur, tout fonctionne sans rien faire ;
- sinon le navigateur bloque l'appel (CORS). L'application le dit explicitement et propose, en un clic, de
  repasser par un **relais public** (`allorigins.win` ou `codetabs.com`). Le choix est mémorisé.

Un relais public est un service tiers : vos requêtes y transitent. Elles ne contiennent que la période
demandée, mais si cela vous gêne — ou si le relais est lent — utilisez `serve.py` en local, ou déployez le
relais sur une plateforme que vous contrôlez (Cloudflare Workers, Netlify, Vercel) et renseignez son adresse
dans « Relais personnalisé » : le champ accepte un gabarit avec `{url}`, par exemple
`https://mon-relais.example/?url={url}`.

## Ce que fait l'application

**Entrées**

- **Trimestre** — année + Q1/Q2/Q3/Q4. Si le trimestre est en cours, la période s'arrête automatiquement
  au jour d'aujourd'hui : c'est le cas d'usage « anticiper le prix avant sa publication ».
- **Dates libres** — n'importe quelle période, du jour à l'année.
- **Pondération** — solaire par défaut ; la liste s'aligne sur les technologies réellement renvoyées par
  l'API (éolien, hydraulique, biomasse…).
- **Monnaie** — CHF au taux BCE journalier (récupéré sur [frankfurter.dev](https://frankfurter.dev),
  report du dernier jour ouvré), CHF à taux fixe, ou EUR brut.

**Sorties**

- Le prix de référence en Rp./kWh et en CHF/MWh.
- Le prix moyen de base sur la même période et le **facteur de valeur** (pondéré ÷ base) : la mesure de la
  cannibalisation de midi.
- L'évolution journalière et la **courbe cumulée**, qui converge vers le chiffre trimestriel définitif —
  utile pour voir si le trimestre est déjà « joué » ou encore ouvert.
- Le profil moyen de la journée : prix horaire et production horaire, l'un au-dessus de l'autre.
- Récapitulatif mensuel, détail journalier, export CSV des deux.
- Part de la production tombant sous un prix négatif, et taux de couverture des données.

Le calcul respecte l'heure suisse (`Europe/Zurich`), y compris les journées de 23 h et 25 h aux changements
d'heure, et aligne en escalier des séries de pas différents (prix horaire ou au quart d'heure, production
au quart d'heure).

## Précision

C'est une **estimation**, pas la valeur officielle :

- l'OFEN pondère par l'injection mesurée des installations à courbe de charge de la technologie ; cette page
  utilise la production nationale agrégée. Le profil est très proche, l'assiette n'est pas identique ;
- le taux de change retenu par l'OFEN peut différer du taux BCE journalier utilisé ici ;
- les toutes dernières heures publiées peuvent être révisées.

Attendez-vous à un écart de quelques pourcents. La valeur qui fait foi reste celle publiée par l'OFEN, au
plus tard 10 jours ouvrés après la fin du trimestre
([opendata.swiss](https://opendata.swiss/fr/dataset/referenz-marktpreise-gemass-art-15-enfv)).

## Sous le capot

| Fichier        | Rôle |
|----------------|------|
| `index.html`   | Toute l'application : interface, calcul, graphiques SVG écrits à la main. |
| `serve.py`     | Serveur local optionnel + relais vers energy-charts. |
| `netlify.toml` | Dossier publié + règle de relais `/api/…` pour Netlify. |
| `_redirects`   | La même règle, au format accepté par un déploiement glisser-déposer. |

Requêtes utilisées (découpées en tranches de 35 jours, mises en cache dans le navigateur) :

```
GET https://api.energy-charts.info/price?bzn=CH&start=YYYY-MM-DD&end=YYYY-MM-DD
GET https://api.energy-charts.info/public_power?country=ch&start=YYYY-MM-DD&end=YYYY-MM-DD
```

Les tranches sont **alignées sur les trimestres civils** : un trimestre se récupère en une requête par
série, et les bornes fixes rendent le cache réutilisable d'une sélection à l'autre. Le cache est court pour
la période en cours (30 min) et long pour les périodes closes (30 jours) ; il se vide depuis le panneau
« Source des données & options avancées ».

**Limite de débit.** L'API refuse les rafales avec un `HTTP 429`. L'application espace ses appels d'environ
400 ms et retente jusqu'à trois fois en reculant progressivement, en respectant l'en-tête `Retry-After`
quand le serveur en fournit un. Pendant l'attente, le bandeau l'indique au lieu d'échouer. Si le refus
persiste, patientez une minute et relancez : les tranches déjà obtenues restent en cache et ne sont pas
redemandées.

## Données

Prix et production : [energy-charts.info](https://www.energy-charts.info), Fraunhofer ISE — CC BY 4.0.
Taux de change : [frankfurter.dev](https://frankfurter.dev), taux de référence BCE.
