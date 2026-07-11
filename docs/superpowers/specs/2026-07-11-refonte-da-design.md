# Refonte graphique complète de Sporia — DA « Girolle × Cèpe »

**Date :** 2026-07-11
**Branche :** `chantier-refonte-da`
**Statut :** spec d'ensemble (validée en brainstorming) — exécution chantier par chantier.

## But

Appliquer la direction artistique **« Girolle × Cèpe »** (riso naturaliste, collage de champignons
comestibles détourés, palette chaude sur fond sous-bois, typo massive) à **tout le site** :
landing, authentification, shell de l'application, carte et guide. Objectif : une identité forte,
différenciante (anti « app nature vert-sauge »), cohérente du marketing jusqu'à l'outil.

Réf. DA : voir mémoire `sporia-brand-DA` + dossier `brand/` (palette, polices, gabarits, photos
détourées dans `ressources/`).

## Décisions validées (brainstorming)

1. **Périmètre = tout** (landing + auth + app + carte), exécuté dans un **ordre sain** (fondation
   d'abord), pas en se limitant à une partie.
2. **Intensité app-carte = « DA marquée, carte claire par défaut + toggle carte sombre ».** Le shell
   (header, volets, onglets, fiche, modales) prend la DA ; la **carte reste claire par défaut** ;
   un **bouton bascule** passe le fond de tuiles en **sombre (CARTO dark)**. Les deux états soignés.
3. **Auth unifié = un seul écran**, avec **bascule Connexion ↔ Créer un compte**, et
   **« Devenir bêta-testeur — gratuit »** en **lien secondaire** (ouvre le formulaire bêta). Supprime
   le doublon actuel (`login-screen` séparé de la section « contact » de la landing).

## Palette & typo (rappel)

- **Couleurs DA :** Sous-bois `#191510` · Os `#EFE6D3` · Girolle `#F2A93B` (signature) ·
  Cèpe `#B9793F` · Lactaire `#D9772E` · Mycène `#C6F24E` (data/radar).
- **Couleurs sémantiques fonctionnelles** (indépendantes de l'accent, conservées) : vert « propice »,
  ambre « limitant », rouge erreur.
- **Polices :** Clash Display (display), Fraunces italique (accent), Space Mono (data/labels),
  **Inter conservé** pour le texte courant / UI (lisibilité).

## Architecture — fondation partagée puis écrans

Tout repose sur des **design-tokens** communs, posés en premier :

- **`tailwind.config.js`** : ajout des couleurs DA (namespace dédié, ex. `sousbois/os/girolle/cepe/
  lactaire/mycene`) sans casser les couleurs `brand`/sémantiques existantes utilisées par les tests.
- **Polices self-hostées** dans `web/vendor/` (woff2 déjà récupérés dans `brand/fonts/`), déclarées en
  `@font-face`, familles exposées via la config Tailwind (`fontFamily.display/serif/mono`).
- **CSP** (`src/sporia/web/security.py`) : les polices self-hostées restent en `'self'` → **0 CDN**
  conservé (tests `test_security_headers` toujours verts).
- **Utilitaires DA** (CSS commité) : grain (feTurbulence data-URI), cartes bord-franc + ombre dure,
  boutons, étiquettes mono, titres. Régénération de `web/css/tailwind.css` via `scripts/build-css.sh`.

## Découpage en chantiers (ordre d'exécution)

Chaque chantier = **palier vert** : petite série de commits, suite de tests verte, QA visuelle, avant
de passer au suivant. Chacun aura son propre plan d'implémentation détaillé (writing-plans).

1. **Fondation DA** — tokens Tailwind + polices self-hostées + CSP + utilitaires/composants de base.
   Pas de rupture visuelle attendue ; met en place le substrat. Régénère `tailwind.css`.
2. **Landing** — appliquer la DA (hero collage, sections, positionnement) en réutilisant le travail
   maquetté (photos détourées, palette, typo, grain, mise en page déstructurée).
3. **Auth unifié** — fusionner `login-screen` + inscription + bêta en **un seul écran** (bascule
   Connexion/Créer un compte, bêta en lien) ; brancher sur les endpoints existants inchangés
   (`/api/login`, `/api/register`, `/api/access-request`) ; retirer le doublon.
4. **Shell app** — header, menu compte, volets/overlays, onglets bas, bottom-sheet/fiche au clic,
   légendes, popover espèces, modales (Mes champignons, CGU, Demandes d'accès), **guide espèces** —
   tous en DA, **carte claire**.
5. **Toggle carte sombre** — bouton de bascule + couche de tuiles **CARTO dark** + recalibrage de la
   lisibilité des overlays radar/couleurs de légende sur fond sombre. Persistance du choix (localStorage).

## Contraintes & garde-fous

- **Ne rien casser** : auth (login par **email**), billing/paywall Stripe, PWA (`/sw.js`,
  `/manifest.webmanifest`, service worker), géolocalisation. Les **146 tests** restent verts ; on
  **adapte** les tests qui vérifient des marqueurs/classes (`test_frontend_serving`,
  `test_security_headers`) plutôt que de les contourner.
- **Sans build runtime** : Tailwind CLI standalone (déjà en place) régénère le CSS commité ; aucun
  Node requis en prod ; déploiement reste `git pull` + `pip install -e .` si besoin.
- **Accessibilité** : viser contraste AA. **Girolle sur sous-bois** insuffisant pour du petit texte →
  réservé aux **gros titres / accents / CTA** ; texte courant en **os** sur sous-bois. Focus visible,
  `prefers-reduced-motion` respecté (grain/animations coupés).
- **Cache-bust** : bumper `?v=` de `tailwind.css` / `app.css` / `main.js` à chaque régénération, tous
  ensemble.
- **Git** : travail sur `chantier-refonte-da`, merges intermédiaires possibles, mise en prod (Oracle)
  après QA visuelle globale. Commits sans `Co-Authored-By`.

## Hors scope (YAGNI)

- **Nouveau logo** : non — passe logo dédiée ultérieure ; on décline le picto actuel dans la DA.
- **Data / modèle / pipeline** : inchangés.
- **Nouvelles fonctionnalités** (ex. signalement « champignon trouvé ») : hors sujet.

## Tests / validation

- Suite `pytest` verte à chaque palier (adaptation des asserts front si nécessaire).
- QA visuelle humaine par écran (hard refresh, mobile + desktop) avant merge.
- Vérif CSP sans CDN, `GET /` 200 + assets 200, PWA servie, login/paywall fonctionnels.
