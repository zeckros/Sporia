# Chantier 1 — Fondation DA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poser le socle de la DA « Girolle × Cèpe » (polices self-hostées + design-tokens Tailwind + variables/utilitaires CSS) sans changer l'apparence des écrans existants.

**Architecture:** Les polices DA rejoignent Inter dans `web/css/fonts.css` (déjà chargé) et `web/vendor/`. Les couleurs et familles de polices deviennent des tokens dans `tailwind.config.js` ; les mêmes couleurs sont aussi exposées en variables CSS + quelques classes utilitaires (grain, ombre dure) dans `web/css/app.css`. On régénère `web/css/tailwind.css` via la CLI standalone déjà en place. Aucune rupture visuelle attendue : ce chantier ne fait qu'*ajouter* des moyens, pas les appliquer.

**Tech Stack:** FastAPI/Starlette (service statique `/static` → `web/`), Tailwind CSS v3.4.17 (CLI standalone `tools/tailwindcss.exe`, CSS commité), pytest + Starlette TestClient.

## Global Constraints

- Palette DA (valeurs exactes) : Sous-bois `#191510` · Os `#efe6d3` · Girolle `#f2a93b` · Cèpe `#b9793f` · Lactaire `#d9772e` · Mycène `#c6f24e`.
- Polices : « Clash Display » (display), « Fraunces » (accent, italique), « Space Mono » (data), « Inter » conservé (texte courant). Fichiers woff2 sources dans `brand/fonts/`.
- CSP **0 CDN** : polices servies en `'self'` uniquement (CSP a déjà `font-src 'self'`, ne rien y changer).
- Sans build runtime : régénérer le CSS avec `bash scripts/build-css.sh` (jamais introduire Node en prod).
- Les tests existants restent verts (`tests/test_frontend_serving.py`, `tests/test_security_headers.py`).
- Environnement : commandes Python via `venv/Scripts/python.exe`. Commits **sans** ligne `Co-Authored-By`.
- Aucune rupture visuelle des écrans actuels dans ce chantier.

---

### Task 1 : Self-hoster les polices DA + @font-face

**Files:**
- Create: `web/vendor/clash/ClashDisplay-Bold.woff2` (copie)
- Create: `web/vendor/fraunces/Fraunces-Italic.woff2` (copie)
- Create: `web/vendor/spacemono/SpaceMono-Regular.woff2` (copie)
- Modify: `web/css/fonts.css` (ajout de 3 `@font-face` à la suite de celui d'Inter)
- Test: `tests/test_da_foundation.py` (nouveau)

**Interfaces:**
- Consumes: rien (les woff2 existent déjà dans `brand/fonts/`).
- Produces: familles CSS `"Clash Display"`, `"Fraunces"`, `"Space Mono"` disponibles ; assets servis sous `/static/vendor/{clash,fraunces,spacemono}/`.

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/test_da_foundation.py` :

```python
"""Fondation DA : polices self-hostées + tokens/utilitaires disponibles."""
from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from sporia.web.app import app

client = TestClient(app)


def test_da_fonts_served():
    for path in (
        "/static/vendor/clash/ClashDisplay-Bold.woff2",
        "/static/vendor/fraunces/Fraunces-Italic.woff2",
        "/static/vendor/spacemono/SpaceMono-Regular.woff2",
    ):
        assert client.get(path).status_code == 200, path


def test_da_fontfaces_declared():
    css = client.get("/static/css/fonts.css").text
    for family in ("Clash Display", "Fraunces", "Space Mono"):
        assert family in css, family
```

- [ ] **Step 2 : Lancer le test — il échoue**

Run: `venv/Scripts/python.exe -m pytest tests/test_da_foundation.py -q`
Expected: FAIL (404 sur les woff2 / familles absentes de fonts.css).

- [ ] **Step 3 : Copier les fichiers de polices**

```bash
mkdir -p web/vendor/clash web/vendor/fraunces web/vendor/spacemono
cp "brand/fonts/clash/ClashDisplay_Complete/Fonts/WEB/fonts/ClashDisplay-Bold.woff2" web/vendor/clash/ClashDisplay-Bold.woff2
cp "brand/fonts/fraunces/fraunces-v38-latin-italic.woff2" web/vendor/fraunces/Fraunces-Italic.woff2
cp "brand/fonts/spacemono/space-mono-v17-latin-regular.woff2" web/vendor/spacemono/SpaceMono-Regular.woff2
```

- [ ] **Step 4 : Ajouter les @font-face dans `web/css/fonts.css`**

Ajouter à la fin du fichier (après le `@font-face` d'Inter) :

```css

/* --- Polices DA « Girolle × Cèpe » (self-hostées) --- */
@font-face {
  font-family: "Clash Display";
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url("/static/vendor/clash/ClashDisplay-Bold.woff2") format("woff2");
}
@font-face {
  font-family: "Fraunces";
  font-style: italic;
  font-weight: 100 900;
  font-display: swap;
  src: url("/static/vendor/fraunces/Fraunces-Italic.woff2") format("woff2");
}
@font-face {
  font-family: "Space Mono";
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url("/static/vendor/spacemono/SpaceMono-Regular.woff2") format("woff2");
}
```

- [ ] **Step 5 : Lancer le test — il passe**

Run: `venv/Scripts/python.exe -m pytest tests/test_da_foundation.py -q`
Expected: PASS (2 tests).

- [ ] **Step 6 : Commit**

```bash
git add web/vendor/clash web/vendor/fraunces web/vendor/spacemono web/css/fonts.css tests/test_da_foundation.py
git commit -m "feat(da): self-host des polices Clash Display / Fraunces / Space Mono + @font-face"
```

---

### Task 2 : Tokens DA dans `tailwind.config.js` + régénération du CSS

**Files:**
- Modify: `tailwind.config.js` (bloc `theme.extend` : `colors` + `fontFamily`)
- Modify: `web/css/tailwind.css` (régénéré par la CLI, ne pas éditer à la main)
- Test: `tests/test_da_foundation.py` (ajout d'un test)

**Interfaces:**
- Consumes: familles `@font-face` de la Task 1.
- Produces: classes utilitaires DA disponibles quand utilisées plus tard (`bg-girolle`, `text-mycene`, `bg-sousbois`, `font-display`, `font-serif`, `font-mono`, etc.).

- [ ] **Step 1 : Écrire le test qui échoue**

Ajouter à `tests/test_da_foundation.py` :

```python
def test_da_tokens_in_tailwind_config():
    cfg = Path("tailwind.config.js").read_text(encoding="utf-8").lower()
    assert "girolle" in cfg and "#f2a93b" in cfg
    assert "sousbois" in cfg and "#191510" in cfg
    assert "clash display" in cfg
```

- [ ] **Step 2 : Lancer le test — il échoue**

Run: `venv/Scripts/python.exe -m pytest tests/test_da_foundation.py::test_da_tokens_in_tailwind_config -q`
Expected: FAIL (tokens absents).

- [ ] **Step 3 : Étendre `tailwind.config.js`**

Dans `theme.extend`, remplacer le bloc existant :

```js
    extend: {
      fontFamily: { sans: ["Inter", "system-ui", "sans-serif"] },
      colors: { brand: { 50: "#fdf3e7", 100: "#fbe2c4", 500: "#c2620e", 600: "#9a4c0b", 700: "#7c3d09" } },
```

par :

```js
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        display: ["Clash Display", "Archivo Black", "system-ui", "sans-serif"],
        serif: ["Fraunces", "Iowan Old Style", "Georgia", "serif"],
        mono: ["Space Mono", "ui-monospace", "monospace"],
      },
      colors: {
        brand: { 50: "#fdf3e7", 100: "#fbe2c4", 500: "#c2620e", 600: "#9a4c0b", 700: "#7c3d09" },
        sousbois: "#191510",
        os: "#efe6d3",
        girolle: "#f2a93b",
        cepe: "#b9793f",
        lactaire: "#d9772e",
        mycene: "#c6f24e",
      },
```

(laisser le reste de `theme.extend` — `boxShadow` — inchangé.)

- [ ] **Step 4 : Régénérer le CSS Tailwind**

Run: `bash scripts/build-css.sh`
Expected: `OK → web/css/tailwind.css` (aucune erreur).

- [ ] **Step 5 : Lancer le test — il passe**

Run: `venv/Scripts/python.exe -m pytest tests/test_da_foundation.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6 : Commit**

```bash
git add tailwind.config.js web/css/tailwind.css tests/test_da_foundation.py
git commit -m "feat(da): tokens couleurs + familles de polices DA dans la config Tailwind"
```

> Note : si le hook pre-commit modifie `web/css/tailwind.css` après le staging, refaire `git add web/css/tailwind.css` puis relancer le commit (motif connu du hook eof).

---

### Task 3 : Variables CSS + utilitaires DA dans `app.css` + cache-bust + suite verte

**Files:**
- Modify: `web/css/app.css` (bloc `:root` de variables DA + classes `.da-grain`, `.da-shadow`, `.da-card`)
- Modify: `src/sporia/web/templates/index.html` (bump `?v=` de `tailwind.css`, `app.css`, `main.js`)
- Test: `tests/test_da_foundation.py` (ajout d'un test) + suite complète

**Interfaces:**
- Consumes: rien de nouveau.
- Produces: variables CSS `--sousbois/--os/--girolle/--cepe/--lactaire/--mycene` et classes `.da-grain` (texture riso), `.da-shadow` (ombre dure), `.da-card` (bord franc) réutilisables par les chantiers suivants.

- [ ] **Step 1 : Écrire le test qui échoue**

Ajouter à `tests/test_da_foundation.py` :

```python
def test_da_css_variables_and_utilities():
    css = Path("web/css/app.css").read_text(encoding="utf-8")
    assert "#191510" in css and "#f2a93b" in css  # variables DA
    assert ".da-grain" in css and ".da-shadow" in css
```

- [ ] **Step 2 : Lancer le test — il échoue**

Run: `venv/Scripts/python.exe -m pytest tests/test_da_foundation.py::test_da_css_variables_and_utilities -q`
Expected: FAIL.

- [ ] **Step 3 : Ajouter variables + utilitaires en tête de `web/css/app.css`**

Insérer tout en haut du fichier (avant la ligne `html,body{...}`) :

```css
/* --- Fondation DA « Girolle × Cèpe » : tokens + utilitaires --- */
:root {
  --sousbois: #191510;
  --os: #efe6d3;
  --girolle: #f2a93b;
  --cepe: #b9793f;
  --lactaire: #d9772e;
  --mycene: #c6f24e;
}
.da-grain {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: .5;
  mix-blend-mode: soft-light;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='150' height='150'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}
.da-shadow { box-shadow: 6px 6px 0 var(--sousbois); }
.da-card { border: 2px solid var(--sousbois); border-radius: 4px; }
@media (prefers-reduced-motion: reduce) { .da-grain { display: none; } }
```

- [ ] **Step 4 : Bump du cache-bust dans `src/sporia/web/templates/index.html`**

Incrémenter les 3 versions ensemble (par ex. si l'actuel est `tailwind.css?v=67`, `app.css?v=55`, `main.js?v=67`, passer chacun à la valeur suivante — augmenter le numéro, cohérent) :

```
/static/css/tailwind.css?v=68
/static/css/app.css?v=68
/static/js/main.js?v=68
```

(Ouvrir le fichier, relever les valeurs `?v=` réelles, incrémenter chacune.)

- [ ] **Step 5 : Lancer la suite complète — tout vert**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: PASS (tous les tests, dont `test_da_foundation.py`, `test_frontend_serving.py`, `test_security_headers.py`).

- [ ] **Step 6 : Commit**

```bash
git add web/css/app.css src/sporia/web/templates/index.html tests/test_da_foundation.py
git commit -m "feat(da): variables CSS + utilitaires (grain, ombre dure, carte) + cache-bust"
```

---

## Self-Review

- **Couverture du spec (section « Architecture »)** : tokens Tailwind → Task 2 ✓ ; polices self-hostées + @font-face → Task 1 ✓ ; CSP 0 CDN → inchangée (déjà `font-src 'self'`), vérifiée par `test_security_headers` en Task 3 ✓ ; utilitaires (grain, ombre) + régénération `tailwind.css` → Task 3 + Task 2 ✓ ; cache-bust → Task 3 ✓.
- **Pas de rupture visuelle** : aucune classe DA n'est appliquée à un écran existant dans ce chantier — uniquement ajout de moyens. ✓
- **Placeholders** : aucun ; tout le code (test + CSS + config) est fourni.
- **Cohérence des noms** : familles `"Clash Display"/"Fraunces"/"Space Mono"` identiques entre fonts.css (Task 1) et tailwind.config `fontFamily` (Task 2) ; hex identiques entre config (Task 2) et variables CSS (Task 3).
- **Hors scope** confirmé : pas de logo, pas d'application de la DA aux écrans (chantiers 2-5).
