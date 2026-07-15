# Chantier 3 — Auth unifié en DA — Implementation Plan

> Exécution contrôleur (bespoke) + revue d'intégrité sous-agent + QA humaine.

**Goal:** Fusionner l'écran de connexion, l'inscription et l'entrée bêta en **un seul écran d'auth** (`#login-screen`) avec **bascule Connexion ↔ Créer un compte**, en DA sombre. **Retirer** le formulaire d'inscription de la landing (qui ne garde que la bêta + « j'ai déjà un compte »). Endpoints backend inchangés.

**Architecture:** `partials/login.html` devient l'écran d'auth unifié : panneau gauche DA + panneau droit avec sélecteur segmenté (2 modes) montrant `#login-form` OU `#register-form` (déplacé depuis la landing, mêmes IDs), plus un lien « Devenir bêta-testeur ». `partials/landing.html` : on **supprime** le bloc `#register-form` et on recentre la section `#contact` sur la bêta. `web/js/main.js` : ajout d'une bascule de mode + d'un lien vers la bêta ; handlers existants inchangés (ils se lient par ID, où que vive le markup).

## Global Constraints

- **Contrat de préservation (hooks `main.js`), ne rien renommer :**
  - Écran : `id="login-screen"`.
  - Connexion : `id="login-form"`, `#login-user`, `#login-pass`, `#login-error`, `#forgot-link`.
  - Inscription (DÉPLACÉE dans login.html) : `id="register-form"`, `#reg-name`, `#reg-email`, `#reg-pass`, `#reg-msg`.
  - Retour accueil : `.back-landing`.
  - Bêta (RESTE dans landing) : `id="access-form"` + `#ac-name/#ac-email/#ac-message/#ac-hp/#access-msg`.
  - Landing : `.open-login`, `.open-cgu`, `[data-dot]` + sections, `[data-price-label]` (déplacé vers le panneau inscription de l'auth — doit rester présent dans le rendu de `/`).
- **DA :** sous-bois/os, girolle (signature), Clash/Fraunces/Space Mono, Inter texte. A11y AA (girolle = gros titres/CTA).
- **Backend inchangé** : `/api/login`, `/api/register`, `/api/access-request`, `/api/password/forgot`.
- 0 CDN ; sans build (`bash scripts/build-css.sh`) ; cache-bust bumpé ensemble ; commits sans `Co-Authored-By` ; hook eof → 2e tentative ; tests via `venv/Scripts/python.exe -m pytest`.

---

### Task 1 : Réécrire `login.html` en écran d'auth unifié (DA)

**Files:** Modify `src/sporia/web/templates/partials/login.html` ; Test `tests/test_auth_unifie.py` (nouveau).

- [ ] Test qui échoue : `GET /` contient `id="login-screen"`, `id="login-form"`, `id="register-form"` (désormais dans login.html), un sélecteur de mode (`data-auth-mode="login"` et `data-auth-mode="register"`), et une police DA (`font-display`).
- [ ] Réécrire `login.html` (contrôleur) : conteneur `#login-screen` (bg sous-bois, DA), panneau gauche DA (marque + une photo de champignon self-hostée + accroche), panneau droit : sélecteur segmenté 2 boutons `[data-auth-mode="login"]` / `[data-auth-mode="register"]`, puis `#login-form` (login-user/pass/error + forgot-link) et `#register-form` (reg-name/email/pass/msg + `[data-price-label]`), + lien `.goto-beta` « Devenir bêta-testeur — gratuit », + `.back-landing`. Un des deux formulaires masqué selon le mode (classe `hidden` togglée par JS).
- [ ] `bash scripts/build-css.sh`.
- [ ] Test passe.
- [ ] Commit `feat(auth): ecran d'auth unifie en DA (connexion + inscription + lien beta)`.

### Task 2 : Retirer l'inscription de la landing + JS bascule

**Files:** Modify `partials/landing.html` (supprimer bloc `#register-form`, recentrer `#contact` sur la bêta) ; Modify `web/js/main.js` (bascule de mode + `.goto-beta` + `showLoginPage` en mode login par défaut).

- [ ] Test qui échoue : `tests/test_auth_unifie.py` — après bascule, la landing ne contient plus deux `id="register-form"` (unicité), et `main.js` expose la logique de bascule (présence de `data-auth-mode` géré). (Vérif simple : `GET /` ne contient qu'**une** occurrence de `id="register-form"`.)
- [ ] `landing.html` : supprimer le `<form id="register-form">` et l'intro « Créer un compte » ; la section `#contact` devient « Devenir bêta-testeur » (garde `#access-form` + `.open-login` « j'ai déjà un compte »). Garder `id="contact"`, `[data-dot]`.
- [ ] `main.js` : ajouter `setAuthMode(mode)` (toggle `hidden` sur `#login-form`/`#register-form` + état actif des boutons `[data-auth-mode]`), câbler les 2 boutons, faire que `showLoginPage()` force le mode `login` + focus `#login-user` ; ajouter handler `.goto-beta` → `showLanding()` puis scroll vers `#contact`.
- [ ] `bash scripts/build-css.sh` si classes ajoutées ; bump cache-bust `main.js`(+css) dans `index.html`.
- [ ] Suite complète verte.
- [ ] Commit `feat(auth): landing recentree beta + bascule connexion/inscription (main.js)`.

### Task 3 : Cache-bust + suite + QA

- [ ] Bump `?v=` (relever réel, incrémenter les 3 ensemble).
- [ ] `venv/Scripts/python.exe -m pytest -q` vert.
- [ ] Commit ; QA humaine (bascule, connexion, inscription, lien bêta, retour accueil, mobile+desktop).

## Self-Review
- Contrat de préservation testé (unicité `register-form`, présence des IDs). ✓
- Backend inchangé ; handlers se lient par ID quel que soit le partial. ✓
- Inscription déplacée (pas dupliquée) ; bêta reste en landing ; `data-price-label` déplacé mais présent dans `/`. ✓
- Bespoke visuel : gate = test de préservation + QA humaine.
