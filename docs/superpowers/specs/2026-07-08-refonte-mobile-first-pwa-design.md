# Refonte mobile-first + PWA — Design

**Date :** 08/07/2026
**Chantier :** B (piste produit). Rails frères : A (bioclim, déjà en prod, classé) ; C (signalements « champignon trouvé », à cadrer ensuite).
**Statut :** design validé, prêt pour le plan d'implémentation.

## 1. Objectif

Rendre Sporia **mobile-first** et **installable** (PWA), tout en **modularisant** le front aujourd'hui monolithique (`web/index.html` 903 l. + `web/app.js` 1296 l.) et en sortant des CDN runtime.

C'est une refonte de la **couche présentation uniquement**. Les modèles (SDM habitat, fructification) et les contrats d'API ne changent pas.

## 2. Hors périmètre (non-goals)

- Aucun changement des modèles ni des endpoints API.
- Le bouton « champignon trouvé » et son backend (chantier C) ne sont **pas** construits ici ; on réserve seulement son emplacement dans le layout.
- Pas de mise en cache hors-ligne des **données** (prévisions, tuiles) : PWA **coquille seule** (décision explicite pour éviter la péremption trompeuse).
- Pas d'étape de build runtime (pas de Node/npm sur le serveur).

## 3. Décisions de cadrage (actées)

| Sujet | Décision |
|---|---|
| Ampleur | Structurant : mobile-first + modularisation + assets self-hostés + PWA |
| Build | **Sans build** : Tailwind CLI standalone → CSS figé commité ; modules ES natifs |
| Navigation mobile | **A** — barre d'onglets bas (Carte / Guide / Spots / Profil) + bottom-sheet |
| Aperçu fiche au clic | **P2** — commune + « N favorables » + pastilles espèces ; glisser pour le détail |
| PWA | **Coquille seule** — installable, s'ouvre hors-ligne, données en ligne |
| HTML | **Partials Jinja2** (FastAPI `Jinja2Templates`) |

## 4. Architecture & structure de fichiers

Refonte de la couche présentation ; API et modèles inchangés.

```
src/sporia/web/
  app.py                    # + Jinja2Templates, routes /, /sw.js, montage statique
  templates/                # (nouveau) partials Jinja2
    index.html              # base : <head> + {% include %} des écrans
    partials/
      landing.html
      login.html   paywall.html
      app.html              # coquille carte : map + tabbar + sheets
      guide.html   spots.html   profil.html
      modals.html           # species-modal, cgu-modal…
web/                        # servi en statique par FastAPI
  css/
    tailwind.css            # généré par Tailwind CLI, COMMITÉ
    app.css                 # animations + extras extraits du <style> inline
  js/                       # modules ES natifs (découpage de app.js)
    main.js                 # point d'entrée <script type="module">
    api.js  state.js  map.js  point-sheet.js  nav.js
    guide.js  spots.js  profil.js  layers.js  auth.js  landing.js
  vendor/
    leaflet.js  leaflet.css   inter/*.woff2      # ex-CDN self-hostés
  icons/                    # icônes PWA (192, 512, maskable, apple-touch)
  manifest.webmanifest
  sw.js                     # service worker (cache coquille)
tailwind.config.js           # + tailwind.input.css (sources CLI)
tools/                       # binaire Tailwind CLI standalone (non commité)
```

Principes :
- **Sans build runtime** : le Tailwind CLI régénère `web/css/tailwind.css` à la demande (quand les classes changent) ; le CSS est commité. Déploiement inchangé (`git pull`).
- **Jinja2** : `index.html` reste une page unique (comportement multi-écrans conservé), composée de partials via `{% include %}`. FastAPI rend `/` via `Jinja2Templates`.
- **Modules ES** : `app.js` éclaté par responsabilité, chargé via `import`/`export` natifs. Pas de bundler.
- **Service worker** servi à `/sw.js` (scope racine → couvre toute l'app).
- **Self-hosting** : Leaflet + fonts Inter en `web/vendor/` → plus aucun CDN externe.

## 5. Layout mobile-first & composants

Principe **mobile-first adaptatif** : un seul jeu de composants qui se reflow par breakpoint (pas deux UIs).

### Onglet Carte (cœur)
- Carte plein écran.
- **Pill de recherche** flottante en haut (recherche commune + géoloc).
- **Bouton « Calques »** (haut-droite) → sheet compact : sélecteur de calque (favorabilité / T° / pluie / forêt / sol / radar) + légende + liste « Radar à champignons » (espèces de l'utilisateur). Remplace le milieu de la sidebar desktop.
- **Bouton géoloc** (bas-droite).
- **Bottom-sheet fiche au clic** (`point-sheet.js`) : 3 points d'ancrage — **peek** (P2 : commune + « N favorables » + pastilles), **mi-hauteur**, **plein** (détail complet : 4 stats météo, forêt/essence, sol/pH, relief, liste espèces avec pastilles pH/hôte, lien guide).
- **Emplacement réservé** (bas, près des onglets) pour le futur bouton « champignon trouvé » (chantier C) — non construit ici.

### Onglets Guide / Spots / Profil
- Vues plein écran défilables.
- **Profil** regroupe : compte, « Mes champignons » (sélection d'espèces), abonnement, bouton « Installer l'app », déconnexion.

### Desktop (≥ 768 px)
Mêmes composants, reflow : barre d'onglets → rail/nav ; bottom-sheet → panneau latéral ancré ; sheet Calques → panneau persistant. Proche de l'expérience actuelle, sans code dupliqué.

## 6. Flux de données (contrats inchangés)

- `main.js` amorce : vérif session (`/api/me`) → charge catalogue + préférences → init carte → active la nav par onglets.
- `api.js` centralise tous les `fetch` (`credentials: "include"`, parsing, gestion d'erreur uniforme).
- `state.js` = source de vérité unique (point courant, spots, sélection d'espèces, calque actif, online/offline).
- Clic carte → `point-sheet.loadPoint(lat,lon)` → `api.get(/api/point)` → rend l'aperçu P2 ; glisser → rend le détail ; `fetchForestDetail` enrichit l'essence en différé (déjà non bloquant).

## 7. Hors-ligne & gestion d'erreur

- Détection `navigator.onLine` + échec `fetch` → bandeau « hors-ligne » ; les sheets affichent « données indisponibles hors-ligne » au lieu de planter.
- Le SW sert la coquille en cache → l'app **s'ouvre** hors-ligne (UI visible, données en attente réseau).
- Détail forêt WMS : garde le libellé « famille » si le réseau tombe (comportement actuel conservé).

## 8. PWA (coquille seule)

- `manifest.webmanifest` : `name` Sporia, `short_name` Sporia, `display: standalone`, `theme_color` `#c2620e`, `background_color`, `start_url: "/"`, `orientation: portrait`, icônes 192/512 + maskable.
- `sw.js` :
  - **install** → precache des assets statiques (`css/`, `js/`, `vendor/`, `icons/`) + copie de `/`.
  - **`/`** : *network-first* (HTML frais en ligne, repli cache hors-ligne).
  - **assets statiques** : *cache-first*.
  - **`/api/*` et tuiles carte** : *network-only* (coquille seule, pas de cache de données).
  - **versionnage** : nom de cache versionné ; purge des anciens au `activate`.
- **Installation** : capture `beforeinstallprompt` → bouton « Installer l'app » (Profil). iOS (pas d'event) → instructions « Partager → Sur l'écran d'accueil ».

## 9. Phasage de migration (commits verts incrémentaux)

Phases 1-3 = refactor à comportement préservé ; 4-5 = nouvelle UX.

- **Phase 0 — Filet** : baseline du HTML rendu actuel + suite pytest verte (garde anti-régression pour 1-3).
- **Phase 1 — Assets self-hostés + Tailwind CLI** : remplacer les 3 CDN par du self-hosté ; générer `tailwind.css` ; extraire le `<style>` inline en `app.css`. Visuellement identique.
- **Phase 2 — Jinja2** : découper `index.html` en partials, rendu via `Jinja2Templates`. Rendu identique au baseline.
- **Phase 3 — Modules ES** : éclater `app.js` par responsabilité (idéalement un commit par module). Comportement identique.
- **Phase 4 — Layout mobile-first** : barre d'onglets + bottom-sheet (P2) + bouton/sheet Calques + reflow desktop. Par composant.
- **Phase 5 — PWA** : manifest + service worker + icônes + prompt d'installation + bandeau hors-ligne.

## 10. Tests

- **Backend (pytest)** : suite existante conservée verte. Ajouts —
  - `/` rend sans erreur Jinja (200, contenu attendu).
  - `/manifest.webmanifest`, `/sw.js` et assets clés servis (200 + content-type correct).
  - la precache-list du SW ne référence que des fichiers existants.
- **Front** : pas de framework JS aujourd'hui ; **checklist QA mobile manuelle** (DevTools responsive + vrai téléphone) plutôt que d'introduire Playwright (YAGNI ; ajout possible plus tard).
- **Done-gate PWA** : audit **Lighthouse** (manifest valide, SW, icônes, installable).

## 11. Notes annexes

- `config.yaml` (racine) est du **legacy** streamlit-authenticator : l'auth passe désormais par le store SQLite (`data/sporia.db`, identité = email). À nettoyer dans un futur passage (hors périmètre de ce chantier).
- Compte de test local créé pour la QA : `dev@sporia.local` (rôle admin, local uniquement, `data/sporia.db` gitignored).
