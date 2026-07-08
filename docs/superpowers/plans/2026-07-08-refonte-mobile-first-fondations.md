# Refonte mobile-first — Plan 1 : Fondations de service

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sortir le front des CDN runtime et poser une base de service modulaire (assets self-hostés + Tailwind CLI + CSP durcie + templates Jinja2), **sans aucun changement de comportement ni de visuel**.

**Architecture :** Refonte de la couche de service uniquement. FastAPI continue de servir `web/` en statique (`/static`) et rend `/` via Jinja2 au lieu d'un `FileResponse` brut. Tailwind passe du CDN JIT à un CSS statique généré par la CLI standalone et commité. Leaflet et la police Inter sont vendorés. Aucun modèle ni contrat d'API ne change.

**Tech Stack :** FastAPI/Starlette, Jinja2 3.1, Tailwind CSS v3.4 (CLI standalone), Leaflet 1.9.4, pytest, ruff (pre-commit).

## Global Constraints

- **Sans build runtime** : aucun Node/npm requis sur le serveur. Tailwind est généré par la CLI standalone en dev ; le CSS produit (`web/css/tailwind.css`) est **commité**. Le déploiement reste `git pull`.
- **Zéro CDN externe au runtime** après ce plan (tout self-hosté).
- **Parité comportement + visuel** obligatoire de bout en bout (ce plan est un refactor).
- Python 3.13, venv en `venv/Scripts/python.exe`. Tests : `pytest`. Hooks pre-commit actifs (trailing-whitespace, end-of-file, ruff check/format) — les commits doivent passer les hooks.
- Messages de commit **sans** ligne `Co-Authored-By`.
- Branche de travail : `chantier-mobile-first-pwa` (déjà créée).
- Versions épinglées : Tailwind CLI **v3.4.17**, Leaflet **1.9.4**.
- Le front est servi par : route `GET /` + montages `app.mount("/static", web/)` et `app.mount("/overlays", …)`. Les URLs d'assets dans le HTML sont **absolues** (`/static/...`).

---

### Task 1 : Filet anti-régression (baseline de service)

**Files:**
- Test: `tests/test_frontend_serving.py` (create)

**Interfaces:**
- Consumes: `from sporia.web.app import app` ; `starlette.testclient.TestClient`.
- Produces: fichier de tests `tests/test_frontend_serving.py` avec `test_index_html_served`, `test_static_bundle_served` — repris/étendu par les tâches suivantes.

- [ ] **Step 1 : Écrire les tests de service actuels**

```python
# tests/test_frontend_serving.py
"""Garde anti-régression du service front : / rend le HTML de l'app, assets statiques servis."""

from __future__ import annotations

from starlette.testclient import TestClient

from sporia.web.app import app

client = TestClient(app)


def test_index_html_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # marqueurs structurants présents aujourd'hui (cf. index.html)
    assert 'id="app-screen"' in r.text
    assert 'id="map"' in r.text


def test_static_bundle_served():
    # /static est monté sur web/ → le JS applicatif est accessible
    r = client.get("/static/app.js")
    assert r.status_code == 200
```

- [ ] **Step 2 : Lancer les tests, vérifier qu'ils passent (état actuel)**

Run: `venv/Scripts/python.exe -m pytest tests/test_frontend_serving.py -v`
Expected: 2 PASSED (le service actuel fonctionne — c'est la baseline).

- [ ] **Step 3 : Confirmer la suite complète verte**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: toute la suite passe (noter le nombre de tests comme référence).

- [ ] **Step 4 : Commit**

```bash
git add tests/test_frontend_serving.py
git commit -m "test(front): filet anti-regression du service (/ + statique)"
```

---

### Task 2 : Chaîne Tailwind CLI (config + génération du CSS commité)

**Files:**
- Create: `tailwind.config.js`
- Create: `web/css/tailwind.input.css`
- Create: `scripts/build-css.sh`
- Create: `web/css/tailwind.css` (généré, commité)
- Modify: `.gitignore` (ignorer le binaire CLI)

**Interfaces:**
- Consumes: rien.
- Produces: `web/css/tailwind.css` (utilitaires Tailwind), disponible à `/static/css/tailwind.css`. `scripts/build-css.sh` régénère ce fichier.

- [ ] **Step 1 : Écrire `tailwind.config.js`** (thème repris verbatim de l'ancien script inline)

```javascript
// tailwind.config.js — thème repris de l'ancien <script>tailwind.config</script> d'index.html.
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./web/index.html", "./web/js/**/*.js"],
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "system-ui", "sans-serif"] },
      colors: { brand: { 50: "#fdf3e7", 100: "#fbe2c4", 500: "#c2620e", 600: "#9a4c0b", 700: "#7c3d09" } },
      boxShadow: {
        soft: "0 2px 14px rgba(15,23,42,.06)",
        card: "0 8px 28px rgba(15,23,42,.10)",
        lg2: "0 24px 70px rgba(15,23,42,.22)",
      },
    },
  },
  plugins: [],
};
```

- [ ] **Step 2 : Écrire `web/css/tailwind.input.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 3 : Écrire `scripts/build-css.sh`** (récupère la CLI standalone si absente, puis génère)

```bash
#!/usr/bin/env bash
# Génère web/css/tailwind.css via la CLI Tailwind standalone (aucun Node requis).
set -euo pipefail
CLI="tools/tailwindcss"
VER="v3.4.17"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) BIN="tailwindcss-windows-x64.exe"; CLI="tools/tailwindcss.exe";;
  Darwin) BIN="tailwindcss-macos-x64";;
  *) BIN="tailwindcss-linux-x64";;
esac
mkdir -p tools web/css
if [ ! -f "$CLI" ]; then
  echo "Téléchargement Tailwind CLI $VER ($BIN)…"
  curl -sL "https://github.com/tailwindlabs/tailwindcss/releases/download/${VER}/${BIN}" -o "$CLI"
  chmod +x "$CLI"
fi
"$CLI" -c tailwind.config.js -i web/css/tailwind.input.css -o web/css/tailwind.css --minify
echo "OK → web/css/tailwind.css"
```

- [ ] **Step 4 : Ignorer le binaire CLI**

Ajouter dans `.gitignore` :

```
# Tailwind CLI standalone (binaire, non versionné)
tools/
```

- [ ] **Step 5 : Générer le CSS**

Run: `bash scripts/build-css.sh`
Expected: `OK → web/css/tailwind.css` et le fichier existe (`ls -l web/css/tailwind.css` → taille non nulle).

- [ ] **Step 6 : Commit** (config + input + script + CSS généré, PAS le binaire)

```bash
git add tailwind.config.js web/css/tailwind.input.css scripts/build-css.sh web/css/tailwind.css .gitignore
git commit -m "build(css): chaine Tailwind CLI standalone + CSS statique commite"
```

---

### Task 3 : Vendoriser Leaflet + la police Inter

**Files:**
- Create: `web/vendor/leaflet/leaflet.js`, `web/vendor/leaflet/leaflet.css`, `web/vendor/leaflet/images/*`
- Create: `web/vendor/inter/*.woff2`
- Create: `web/css/fonts.css`

**Interfaces:**
- Consumes: rien.
- Produces: assets locaux à `/static/vendor/leaflet/leaflet.{js,css}`, `/static/vendor/inter/*.woff2`, et `/static/css/fonts.css` (déclarations `@font-face`).

- [ ] **Step 1 : Télécharger Leaflet 1.9.4 (JS + CSS + images des marqueurs)**

```bash
mkdir -p web/vendor/leaflet/images
curl -sL https://unpkg.com/leaflet@1.9.4/dist/leaflet.js  -o web/vendor/leaflet/leaflet.js
curl -sL https://unpkg.com/leaflet@1.9.4/dist/leaflet.css -o web/vendor/leaflet/leaflet.css
for img in marker-icon.png marker-icon-2x.png marker-shadow.png layers.png layers-2x.png; do
  curl -sL "https://unpkg.com/leaflet@1.9.4/dist/images/$img" -o "web/vendor/leaflet/images/$img"
done
```

Note : `leaflet.css` référence `images/*.png` en relatif → servis à `/static/vendor/leaflet/images/*` (cohérent avec l'emplacement du CSS). Aucune modification du CSS Leaflet nécessaire.

- [ ] **Step 2 : Télécharger les woff2 Inter (poids utilisés : 400,500,600,700,800,900)**

```bash
mkdir -p web/vendor/inter
# Fichiers woff2 Inter (dépôt officiel rsms/inter, v4). Un fichier variable suffit :
curl -sL "https://raw.githubusercontent.com/rsms/inter/v4.0/docs/font-files/InterVariable.woff2" -o web/vendor/inter/InterVariable.woff2
```

- [ ] **Step 3 : Écrire `web/css/fonts.css`** (remplace Google Fonts)

```css
/* Inter self-hostée (remplace fonts.googleapis.com). Police variable → tous les poids. */
@font-face {
  font-family: "Inter";
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url("/static/vendor/inter/InterVariable.woff2") format("woff2");
}
```

- [ ] **Step 4 : Vérifier que les fichiers sont servis**

Run: `venv/Scripts/python.exe -m pytest tests/test_frontend_serving.py -v` (toujours vert)
puis contrôle manuel : démarrer `venv/Scripts/python.exe -m uvicorn sporia.web.app:app --port 8000` et vérifier `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/static/vendor/leaflet/leaflet.js` → `200`.

- [ ] **Step 5 : Commit**

```bash
git add web/vendor web/css/fonts.css
git commit -m "assets(vendor): self-host Leaflet 1.9.4 + police Inter (ex-CDN)"
```

---

### Task 4 : Basculer `index.html` du CDN vers le local

**Files:**
- Modify: `web/index.html` (`<head>`, lignes 8-85 : liens/scripts CDN + config inline + `<style>`)
- Create: `web/css/app.css` (le bloc `<style>` extrait)

**Interfaces:**
- Consumes: `web/css/tailwind.css` (Task 2), `web/vendor/*` + `web/css/fonts.css` (Task 3).
- Produces: `index.html` sans aucune référence CDN ; `web/css/app.css` (styles custom).

- [ ] **Step 1 : Extraire le bloc `<style>` d'`index.html` (lignes 23-85) dans `web/css/app.css`**

Couper **verbatim** tout le contenu entre `<style>` et `</style>` (règles `html,body`, `#map`, `.leaflet-*`, `.nice-scroll`, `@media (max-width:767px)`, animations `.rain-drop`/`.bob`/`.mush-logo`/…, `@media (prefers-reduced-motion)`) et le coller dans `web/css/app.css`. Supprimer le bloc `<style>…</style>` d'`index.html`.

- [ ] **Step 2 : Remplacer le `<head>` (lignes 8-22) par les références locales**

Remplacer les balises CDN (`cdn.tailwindcss.com`, `unpkg` Leaflet, Google Fonts) **et** le `<script>tailwind.config=…</script>` par :

```html
  <link rel="stylesheet" href="/static/css/fonts.css" />
  <link rel="stylesheet" href="/static/css/tailwind.css" />
  <link rel="stylesheet" href="/static/css/app.css" />
  <link rel="stylesheet" href="/static/vendor/leaflet/leaflet.css" />
  <script src="/static/vendor/leaflet/leaflet.js"></script>
```

(Pas de `defer` : Leaflet doit rester disponible quand `app.js`, script classique en fin de `<body>`, s'exécute — on préserve la sémantique de chargement actuelle. Le `<script>tailwind.config</script>` inline disparaît : la config vit dans `tailwind.config.js`. Le `<style>` inline disparaît : extrait en `app.css`.)

- [ ] **Step 3 : Vérifier le service + la parité visuelle**

Run: `venv/Scripts/python.exe -m pytest tests/test_frontend_serving.py -v`
Expected: 2 PASSED.
Contrôle manuel : `uvicorn … --port 8000`, ouvrir http://localhost:8000, se connecter (`dev@sporia.local` / `sporia-dev`), vérifier que la carte, la sidebar, le thème terracotta et les animations du hero sont **identiques** à avant. Vérifier l'onglet Réseau : aucune requête vers `cdn.tailwindcss.com` / `unpkg.com` / `fonts.googleapis.com`.

- [ ] **Step 4 : Commit**

```bash
git add web/index.html web/css/app.css
git commit -m "front(assets): index.html sur assets locaux (fin des CDN runtime)"
```

---

### Task 5 : Durcir la Content-Security-Policy

**Files:**
- Modify: `src/sporia/web/security.py:13-21` (constante `CSP` + commentaire)
- Modify: `tests/test_security_headers.py` (assertions CDN absents)

**Interfaces:**
- Consumes: rien (les assets sont désormais en `'self'`).
- Produces: CSP sans hôte externe.

- [ ] **Step 1 : Écrire le test qui exige l'absence des hôtes CDN**

Ajouter dans `tests/test_security_headers.py` :

```python
def test_csp_has_no_external_cdn():
    r = TestClient(app).get("/")
    csp = r.headers["Content-Security-Policy"]
    for host in ("cdn.tailwindcss.com", "unpkg.com", "fonts.googleapis.com", "fonts.gstatic.com"):
        assert host not in csp, f"CSP ne doit plus référencer {host}"
    assert "default-src 'self'" in csp
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `venv/Scripts/python.exe -m pytest tests/test_security_headers.py::test_csp_has_no_external_cdn -v`
Expected: FAIL (la CSP contient encore les hôtes CDN).

- [ ] **Step 3 : Réécrire la constante `CSP`** dans `src/sporia/web/security.py`

```python
# CSP : tout en self après self-hosting (Tailwind CLI + Leaflet + Inter vendorés).
# 'unsafe-inline' conservé pour script + style tant que subsistent des scripts/handlers
# inline et les styles inline injectés par Leaflet (el.style). Le retrait de 'unsafe-inline'
# sur script-src est prévu au Plan 2 (modules ES : plus d'inline). Données rendues échappées.
CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
)
```

- [ ] **Step 4 : Lancer les tests de sécurité**

Run: `venv/Scripts/python.exe -m pytest tests/test_security_headers.py -v`
Expected: tous PASSED (le nouveau test + les existants).

- [ ] **Step 5 : Commit**

```bash
git add src/sporia/web/security.py tests/test_security_headers.py
git commit -m "security(csp): retrait des hotes CDN externes (self-hosting)"
```

---

### Task 6 : Rendre `/` via Jinja2 (base template)

**Files:**
- Modify: `pyproject.toml` (dépendance `jinja2`)
- Modify: `src/sporia/web/app.py` (import Jinja2Templates, route `/` et `verify-email`)
- Rename: `web/index.html` → `src/sporia/web/templates/index.html`
- Modify: `tailwind.config.js` (glob `content` inclut les templates) + regénérer `web/css/tailwind.css`

**Interfaces:**
- Consumes: `web/css/*`, `web/vendor/*`, `web/app.js` (URLs `/static/...` inchangées).
- Produces: `templates = Jinja2Templates(directory=<web>/templates)` ; `GET /` renvoie `templates.TemplateResponse("index.html", {"request": request})`.

- [ ] **Step 1 : Déclarer la dépendance Jinja2**

Dans `pyproject.toml`, ajouter à la liste `dependencies` (après `itsdangerous`) :

```toml
    "jinja2>=3.1",
```

- [ ] **Step 2 : Déplacer le template**

```bash
mkdir -p src/sporia/web/templates
git mv web/index.html src/sporia/web/templates/index.html
```

(Les URLs d'assets dans le HTML sont absolues `/static/...` → toujours servies par le montage `web/`. Le déplacement du HTML ne les casse pas.)

- [ ] **Step 3 : Câbler Jinja2 dans `app.py`**

Ajouter l'import (près des autres imports FastAPI, l'actuelle ligne 19 fournit déjà `FileResponse, Response`) :

```python
from pathlib import Path

from fastapi.templating import Jinja2Templates
```

Déclarer les templates après la création de `app` (vers la ligne 78) :

```python
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
```

Remplacer la route `/` (fin de fichier, actuelle `def index()`) par :

```python
@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(
        "index.html", {"request": request},
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )
```

Remplacer aussi le `FileResponse` de la route `verify-email` (ligne ~226) par un rendu du même template :

```python
    return templates.TemplateResponse(
        "index.html", {"request": request}, headers={"Cache-Control": "no-cache"}
    )
```

(La signature de la fonction `verify-email` doit accepter `request: Request` — l'ajouter si absent.)

- [ ] **Step 4 : Mettre à jour le glob Tailwind + regénérer**

Dans `tailwind.config.js`, remplacer `content` par :

```javascript
  content: ["./src/sporia/web/templates/**/*.html", "./web/js/**/*.js", "./web/app.js"],
```

Run: `bash scripts/build-css.sh`
Expected: `OK → web/css/tailwind.css`.

- [ ] **Step 5 : Lancer les tests**

Run: `venv/Scripts/python.exe -m pytest tests/test_frontend_serving.py tests/test_security_headers.py -v`
Expected: tous PASSED (`/` rend le même HTML via Jinja, marqueurs présents).

- [ ] **Step 6 : Commit**

```bash
git add pyproject.toml src/sporia/web/app.py src/sporia/web/templates/index.html tailwind.config.js web/css/tailwind.css
git commit -m "front(jinja): rend / via Jinja2Templates (template deplace)"
```

---

### Task 7 : Découper `index.html` en partials Jinja2

**Files:**
- Modify: `src/sporia/web/templates/index.html` (remplace les blocs par des `{% include %}`)
- Create: `src/sporia/web/templates/partials/{landing,login,paywall,app,guide,spots,profil,modals}.html`

**Interfaces:**
- Consumes: le template de base (Task 6).
- Produces: rendu HTML **équivalent** à la baseline (mêmes marqueurs, même structure).

- [ ] **Step 1 : Extraire chaque écran dans un partial**

Découper `index.html` aux frontières des écrans (repères actuels) et déplacer **verbatim** chaque bloc dans son partial :

| Partial | Bloc source (id racine) |
|---|---|
| `partials/landing.html` | `<div id="landing-screen">…</div>` |
| `partials/login.html` | `<div id="login-screen">…</div>` |
| `partials/paywall.html` | `<div id="paywall-screen">…</div>` |
| `partials/app.html` | `<div id="app-screen">…</div>` (sidebar, carte, vues guide/spots) |
| `partials/guide.html` | sous-bloc `#view-guide` si séparable, sinon inclus dans `app.html` |
| `partials/spots.html` | sous-bloc `#view-spots` si séparable, sinon inclus dans `app.html` |
| `partials/profil.html` | bloc compte/préférences si séparable |
| `partials/modals.html` | `#species-modal`, `#cgu-modal` et autres modales |

Règle : ne déplacer que des blocs à balises **équilibrées** (une div racine complète). Un écran non trivial à isoler proprement reste dans `app.html` (YAGNI — on ne force pas un découpage bancal).

- [ ] **Step 2 : Remplacer les blocs par des includes dans `index.html`**

Le `<body>` de `index.html` devient (dans l'ordre d'origine) :

```html
<body class="h-full">
  {% include "partials/landing.html" %}
  {% include "partials/login.html" %}
  {% include "partials/paywall.html" %}
  {% include "partials/app.html" %}
  {% include "partials/modals.html" %}
  <script src="/static/app.js"></script>
</body>
```

(Conserver la balise `<script>` de `app.js` telle quelle — le passage aux modules ES est au Plan 2. Adapter la liste d'includes aux partials réellement créés au Step 1.)

- [ ] **Step 3 : Étendre le filet — équivalence de rendu**

Ajouter dans `tests/test_frontend_serving.py` :

```python
def test_index_composes_all_screens():
    r = client.get("/")
    assert r.status_code == 200
    # chaque écran (partial) est bien inclus dans le rendu final
    for marker in ('id="landing-screen"', 'id="login-screen"',
                   'id="paywall-screen"', 'id="app-screen"', 'id="species-modal"'):
        assert marker in r.text
```

- [ ] **Step 4 : Lancer les tests + contrôle visuel**

Run: `venv/Scripts/python.exe -m pytest tests/test_frontend_serving.py -v`
Expected: 3 PASSED.
Contrôle manuel : `uvicorn … --port 8000`, parcourir landing → login → app → guide → spots → modales : comportement et visuel **identiques**.

- [ ] **Step 5 : Regénérer le CSS (le glob couvre déjà `templates/**`)**

Run: `bash scripts/build-css.sh`
Expected: `OK` (aucune classe perdue ; diff de `web/css/tailwind.css` faible ou nul).

- [ ] **Step 6 : Commit**

```bash
git add src/sporia/web/templates web/css/tailwind.css tests/test_frontend_serving.py
git commit -m "front(jinja): decoupe index.html en partials {% include %}"
```

---

## Self-Review (fait à l'écriture)

**Couverture du spec (§ Plan 1 = phases 0-2) :**
- Assets self-hostés (Tailwind CLI + Leaflet + Inter) → Tasks 2,3,4. ✓
- Sans build runtime / CSS commité → Task 2 (CLI standalone, `web/css/tailwind.css` commité). ✓
- CSP durcie (fin des CDN) → Task 5. ✓
- Partials Jinja2 → Tasks 6,7. ✓
- Parité comportement/visuel → contrôles manuels Tasks 4,7 + tests de service Tasks 1,5,6,7. ✓
- Phases 3 (modules ES), 4 (layout mobile), 5 (PWA) → **hors de ce plan**, couvertes par le Plan 2.

**Placeholders :** aucun TODO/TBD ; tout le code neuf est fourni ; les tâches de déplacement citent les blocs/lignes source exacts.

**Cohérence des types/chemins :** `web/css/tailwind.css`, `/static/...`, `templates = Jinja2Templates(...)`, `templates.TemplateResponse("index.html", …)` cohérents entre Tasks 2→7. Glob Tailwind mis à jour en Task 6 (templates) après le déplacement du HTML.

## Suite (Plan 2, à écrire après atterrissage du Plan 1)

Phases 3-5 contre le code modularisé : split `app.js` en modules ES (`api/state/map/point-sheet/layers/guide/spots/auth/nav/notifications/main`), retrait de `'unsafe-inline'` script-src, layout mobile-first (onglets bas + bottom-sheet P2 + sheet Calques + reflow desktop), PWA (manifest + service worker `/sw.js` + prompt d'installation + bandeau hors-ligne).
