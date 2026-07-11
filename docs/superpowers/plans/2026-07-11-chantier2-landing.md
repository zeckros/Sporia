# Chantier 2 — Landing en DA « Girolle × Cèpe » — Implementation Plan

> **For agentic workers:** exécution pilotée par le contrôleur (écran bespoke visuel) + revue d'intégrité par sous-agent + QA visuelle humaine. Steps en `- [ ]`.

**Goal:** Refondre `web/.../partials/landing.html` dans la DA (fond sous-bois, collage de champignons détourés réels, typo Clash/Fraunces/Space Mono, grain, mise en page déstructurée) **sans casser aucun hook JS**, en s'appuyant sur la fondation du Chantier 1.

**Architecture:** La landing reste **un seul partial** `landing.html`, avec **exactement les mêmes IDs / classes / data-attributs** consommés par `main.js`. On self-hoste des photos détourées dans `web/img/shrooms/` (fichiers réels servis, pas de base64). On régénère `web/css/tailwind.css` (nouvelles classes DA utilisées). L'auth n'est PAS touchée ici (unification = Chantier 3) : les points d'entrée `.open-login`, `#register-form`, `#access-form` restent en place.

**Tech Stack:** FastAPI/Jinja2 partials, Tailwind CLI standalone (tokens DA du Chantier 1), CSS commité, pytest.

## Global Constraints

- **Contrat de préservation (hooks consommés par `main.js`) — obligatoire, ne rien renommer/supprimer :**
  - Conteneur d'écran : `id="landing-screen"`.
  - Classes : `.open-login`, `.back-landing`, `.open-cgu`.
  - Prix : au moins un élément `[data-price-label]`.
  - Navigation : puces `[data-dot]` + sections avec `id` `hero`, `apercu`, `sec-fiche`, `sec-spots`, `sec-mobile`, `contact`.
  - Inscription : `id="register-form"` + champs `#reg-name`, `#reg-email`, `#reg-pass`, `#reg-msg`.
  - Bêta/contact : `id="access-form"` + champs `#ac-name`, `#ac-email`, `#ac-message`, honeypot `#ac-hp`, `#access-msg`.
- **DA :** fond Sous-bois `#191510` / texte Os `#efe6d3` ; accents Girolle `#f2a93b` (signature, gros titres/CTA), Cèpe `#b9793f`, Lactaire `#d9772e` ; Mycène `#c6f24e` réservé data/radar. Familles `font-display` (Clash), `font-serif` (Fraunces italique, accents), `font-mono` (Space Mono, labels) ; texte courant Inter. Utilitaires `.da-grain`, ombres dures.
- **A11y :** Girolle réservé aux gros titres/CTA (pas le petit texte) ; contraste AA ; `prefers-reduced-motion` respecté.
- **0 CDN** ; **sans build** (régénération via `bash scripts/build-css.sh`) ; cache-bust `?v=` bumpé ensemble ; commits **sans** `Co-Authored-By` ; hook eof → 2e tentative.
- Tests via `venv/Scripts/python.exe -m pytest`. Suite complète verte.

---

### Task 1 : Self-hoster les photos de champignons de la landing

**Files:**
- Create: `web/img/shrooms/*.png` (copies optimisées depuis `ressources/*-removebg-preview.png`)
- Test: `tests/test_landing_da.py` (nouveau)

- [ ] **Step 1 — test qui échoue :** créer `tests/test_landing_da.py` asservissant que 3 photos self-hostées sont servies :

```python
"""Chantier 2 : landing en DA — assets self-hostés + hooks préservés."""
from __future__ import annotations

from starlette.testclient import TestClient

from sporia.web.app import app

client = TestClient(app)


def test_landing_shroom_assets_served():
    for p in (
        "/static/img/shrooms/girolle.png",
        "/static/img/shrooms/cepe.png",
        "/static/img/shrooms/pied-bleu.png",
    ):
        assert client.get(p).status_code == 200, p
```

- [ ] **Step 2 — lancer, échoue :** `venv/Scripts/python.exe -m pytest tests/test_landing_da.py -q` → FAIL (404).

- [ ] **Step 3 — copier/optimiser les photos** (downscale ~640px pour alléger la page) via `venv/Scripts/python.exe` + PIL. Fichiers cibles a minima : `girolle.png` (Cantharellus…), `cepe.png` (image-removebg = grand cèpe), `pied-bleu.png` (champignon-pied-bleu…), `coulemelle.png`, `lactaires.png` (Deux-lactaires…), `trompette.png` (Craterellus…), `pdm.png` (Hedgehog…). Sources exactes dans `ressources/` (voir noms `*-removebg-preview.png`).

- [ ] **Step 4 — lancer, passe :** même commande → PASS.

- [ ] **Step 5 — commit :** `git add web/img/shrooms tests/test_landing_da.py && git commit -m "feat(landing): self-host des photos de champignons détourées pour le collage DA"`

---

### Task 2 : Réécrire `landing.html` dans la DA (contrôleur) + régénérer le CSS

**Files:**
- Modify: `src/sporia/web/templates/partials/landing.html` (réécriture visuelle intégrale)
- Modify: `web/css/tailwind.css` (régénéré)
- Test: `tests/test_landing_da.py` (ajout d'un test « contrat de préservation »)

- [ ] **Step 1 — test qui échoue** : ajouter à `tests/test_landing_da.py` :

```python
def test_landing_preserves_hooks_and_applies_da():
    html = client.get("/").text
    # contrat de préservation (hooks consommés par main.js)
    for marker in (
        'id="landing-screen"', 'open-login', 'data-price-label',
        'id="register-form"', 'id="reg-email"', 'id="reg-pass"',
        'id="access-form"', 'id="ac-email"', 'id="ac-message"', 'id="ac-hp"',
        'id="hero"', 'id="contact"', 'data-dot',
    ):
        assert marker in html, f"hook manquant: {marker}"
    # DA appliquée : au moins une classe/police DA sur la landing
    assert ("font-display" in html) or ("bg-sousbois" in html) or ("da-grain" in html)
```

- [ ] **Step 2 — lancer, échoue** (le marqueur DA manque tant que la landing n'est pas refondue).

- [ ] **Step 3 — réécrire `landing.html`** (contrôleur) : hero collage (photos self-hostées, grain, titre Clash + accent Fraunces girolle, CTA), sections `apercu`/`sec-fiche`/`sec-spots`/`sec-mobile` en DA, section `contact` (inscription + bêta) restylée, footer. **Conserver tous les hooks du contrat** (mêmes IDs/classes/data-attrs). Utiliser les classes des tokens Chantier 1 (`bg-sousbois`, `text-os`, `text-girolle`, `font-display`, `font-serif`, `font-mono`, `da-grain`…) + valeurs arbitraires Tailwind si besoin.

- [ ] **Step 4 — régénérer le CSS** : `bash scripts/build-css.sh` → `OK → web/css/tailwind.css`.

- [ ] **Step 5 — lancer, passe** : `venv/Scripts/python.exe -m pytest tests/test_landing_da.py -q` → PASS.

- [ ] **Step 6 — commit** (2e tentative si hook eof touche `tailwind.css`) : `git add src/sporia/web/templates/partials/landing.html web/css/tailwind.css tests/test_landing_da.py && git commit -m "feat(landing): refonte visuelle en DA Girolle x Cepe (hooks preserves)"`

---

### Task 3 : Cache-bust + suite complète verte + QA

**Files:**
- Modify: `src/sporia/web/templates/index.html` (bump `?v=` des 3 assets ensemble)

- [ ] **Step 1** — bumper `?v=` (relever les valeurs réelles, incrémenter les 3 ensemble).
- [ ] **Step 2** — `venv/Scripts/python.exe -m pytest -q` → toute la suite verte (dont `test_landing_da.py`, `test_frontend_serving.py`, `test_security_headers.py`).
- [ ] **Step 3** — commit : `git add src/sporia/web/templates/index.html && git commit -m "chore(landing): cache-bust apres refonte DA"`.
- [ ] **Step 4** — **QA visuelle humaine** (hard refresh, mobile + desktop) : hero, sections, formulaires inscription/bêta fonctionnels, nav dots, CGU, « Se connecter ».

## Self-Review

- Contrat de préservation listé et testé (Task 2 step 1) → risque « hook cassé » couvert. ✓
- DA appliquée + assertion de présence (Task 2). ✓
- Assets self-hostés (Task 1), 0 CDN, CSS régénéré (Task 2), cache-bust (Task 3). ✓
- Auth non touchée (Chantier 3) : `.open-login`/`#register-form`/`#access-form` conservés tels quels. ✓
- Écart assumé au « code complet dans le plan » : le HTML de la landing est **bespoke visuel**, écrit par le contrôleur avec les maquettes DA validées comme référence ; le gate est le test de préservation + la QA humaine (pytest ne voit pas le rendu).
