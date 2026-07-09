# Refonte mobile-first — Plan 2 : Modules ES + UX mobile + PWA

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Sur la base modularisée du Plan 1, éclater `web/app.js` en modules ES natifs (Phase 3, à comportement préservé), puis construire l'UX mobile-first (Phase 4 : onglets bas + bottom-sheet + sheet Calques) et rendre l'app installable (Phase 5 : PWA coquille seule).

**Architecture :** Modules ES natifs (`<script type="module">`, aucun bundler). Layout mobile-first adaptatif (mêmes composants reflow par breakpoint). PWA coquille seule (service worker cache le shell ; données réseau-only).

**Tech Stack :** Vanilla JS (ES modules), Tailwind (CSS déjà généré, Plan 1), Leaflet 1.9.4, FastAPI/Jinja2, Web App Manifest + Service Worker.

## Global Constraints

- **Prérequis** : le Plan 1 est atterri (branche `chantier-mobile-first-pwa` @ `b318e305b`) : assets self-hostés, Tailwind CLI, CSP durcie, `/` en Jinja2 + partials. Plan 2 continue sur la MÊME branche.
- **Phase 3 = refactor à comportement préservé** (le filet `tests/test_frontend_serving.py` + la suite doivent rester verts ; parité visuelle).
- **Phases 4-5 = UX nouvelle** : nécessite une **QA visuelle humaine** avant merge en prod (les décisions de design sont déjà validées : nav = onglets bas, aperçu fiche = P2, PWA = coquille seule).
- Sans build runtime ; déploiement `git pull`. Modules servis à `/static/js/...` (mount `web/` sur `/static`).
- Tests via `venv/Scripts/python.exe -m pytest`. Hooks pre-commit actifs. Commits **sans** `Co-Authored-By`. Après avoir déplacé des classes dans du JS/HTML, régénérer `web/css/tailwind.css` (`bash scripts/build-css.sh`) — le glob inclut déjà `./web/js/**/*.js` et `./web/app.js` (à retirer quand app.js disparaît).

---

## Phase 3 — Éclatement de `app.js` en modules ES (comportement préservé)

Cible de découpage (frontières relevées dans `web/app.js`, ~70 fonctions) :

| Module `web/js/…` | Contenu (fonctions / constantes) | Exporte |
|---|---|---|
| `api.js` | objet `API` (wrapper fetch, `credentials:"include"`) | `API` |
| `state.js` | objet `state` + constantes `MONTHS,CMAP,LEVEL,FACTOR_CLR,LAYER_DEFS,LAYER_KEYS,LAYER_NAMES,CONF_BADGE,FOREST_TFV,FR_MONTHS` | `state`, constantes |
| `util.js` | `escapeHtml,valFmt,fmtNum,pct,monthNum` | idem |
| `auth.js` | `boot,routeAfterAuth,showLanding,setupLandingNav,showLoginPage,showPaywall,applyPriceLabel,subscribe,openPortal,deleteAccount` | idem |
| `map.js` | `initMap,_setOverlay,computeSelectedDates,refreshWeatherLayer,refreshRadar,refreshSoil,refreshSoilMoisture,refreshAltitude,refreshAspect,setActiveLayer,geolocateMe,radarActiveSpecies` | idem |
| `layers.js` | `updateRadarSpecies,legendFor,updateLegend,updateActiveLayerName,_grad,_swatch` | idem |
| `point-sheet.js` | `loadPoint,showPointCard,positionPointCard,hidePointCard,factorLevel,miniStat,phBadge,hostDot,forestLineHtml,familyLabel,fetchForestDetail` | idem |
| `guide.js` | `renderGuide,monthStrip,chip` | idem |
| `spots.js` | `loadSpots,spotIcon,renderSpotMarkers,saveSpot,renameSpot,deleteSpot` | idem |
| `prefs.js` | `loadPreferences,openSpeciesModal,closeSpeciesModal,setAllSpeciesChecks,updateSpeciesCount,saveSpecies,confidenceBadge` | idem |
| `nav.js` | `setTab,applySidebar,toggleSidebar,wireControls,searchCity,doCitySearch` | idem |
| `notifications.js` | `toggleNotifPanel,updateNotifications` | idem |
| `main.js` | point d'entrée : imports + `DOMContentLoaded`→`boot()` + câblage global (`wireControls`, listeners actuellement en top-level dans app.js) | — |

**Méthode par tâche (une par module, ordre : util/api/state d'abord car dépendances feuilles, puis les autres, `main.js` en dernier) :**
1. Créer `web/js/<module>.js` ; y **déplacer verbatim** les fonctions/constantes listées depuis `app.js`.
2. Ajouter les `export` sur les symboles utilisés ailleurs ; ajouter en tête les `import { … } from "./<dep>.js"` nécessaires (au minimum `state` depuis `state.js`, `API` depuis `api.js`).
3. Retirer ces symboles d'`app.js` (qui rétrécit à chaque tâche).
4. Tant que `app.js` coexiste : le charger reste possible, mais dès la 1re tâche, basculer le `<script src="/static/app.js">` (dans `src/sporia/web/templates/index.html`) en `<script type="module" src="/static/js/main.js"></script>`, et faire de `main.js` l'agrégateur qui importe tout. (Alternative plus sûre : garder app.js jusqu'à la dernière tâche et n'y basculer qu'à la fin — au choix de l'exécutant, documenté.)
5. Vérifier : `pytest tests/test_frontend_serving.py` vert ; smoke runtime (`GET /` 200, assets 200) ; **QA manuelle** : login `dev@sporia.local`/`sporia-dev`, la carte, la fiche au clic, le guide, les spots, la sélection d'espèces fonctionnent comme avant. Régénérer le CSS si des classes ont bougé.
6. Commit (un par module).

**Attention interfaces circulaires :** certaines fonctions se rappellent entre modules (ex. `loadPoint`→`renderGuide`, `setActiveLayer`→`updateLegend`). Les modules ES gèrent les cycles si on importe des *fonctions* (hoisted) et non des valeurs exécutées à l'import. Garder tout l'état mutable dans `state.js` (source unique) pour éviter les cycles de données.

**Fin de Phase 3 :** retirer `./web/app.js` du glob `content` de `tailwind.config.js` (remplacé par `./web/js/**/*.js`, déjà présent) ; supprimer `web/app.js` ; régénérer le CSS ; commit.

---

## Phase 4 — Layout mobile-first (UX nouvelle — QA visuelle humaine requise)

Designs validés au brainstorming : **nav = barre d'onglets bas** (Carte / Guide / Spots / Profil), **fiche au clic = bottom-sheet** avec aperçu **P2** (commune + « N favorables » + pastilles espèces) → glisser pour le détail, **bouton Calques** (haut-droite) → sheet (calque + légende + radar espèces), pill de recherche + géoloc. Desktop ≥768px : mêmes composants reflow (onglets→rail, sheet→panneau latéral). Réf. maquettes : `.superpowers/brainstorm/1409-*/content/{mobile-nav,point-sheet,app-layout}.html`.

Tâches (à détailler à l'exécution, contre le code modularisé) :
- **T-P4.1** Composant `bottom-sheet.js` réutilisable : 3 ancrages (peek/mi/plein), glissable (pointer events), accessible. Test unitaire du calcul d'ancrage.
- **T-P4.2** Barre d'onglets bas (`nav.js` étendu / `tabbar.js`) + bascule des vues Carte/Guide/Spots/Profil (safe-area insets). Regrouper le compte + « Mes champignons » + abonnement + « Installer l'app » + déconnexion dans **Profil**.
- **T-P4.3** Migrer la fiche au clic (`point-sheet.js`) du `#point-card` flottant vers le bottom-sheet ; aperçu P2 ; détail au déploiement.
- **T-P4.4** Bouton **Calques** + sheet (sélecteur de calque + légende + radar espèces), remplace le milieu de la sidebar sur mobile.
- **T-P4.5** Pill de recherche + géoloc en overlay carte.
- **T-P4.6** Reflow desktop ≥768px (rail + panneau latéral) ; vérifier parité desktop.
- **T-P4.7** Emplacement réservé (non construit) pour le futur bouton « champignon trouvé » (chantier C).
- QA : DevTools responsive + vrai téléphone ; parité desktop.

---

## Phase 5 — PWA coquille seule

- **T-P5.1** `web/manifest.webmanifest` (name Sporia, display standalone, theme_color `#c2620e`, background, start_url `/`, orientation portrait) + icônes `web/icons/` (192/512/maskable/apple-touch) ; lier dans `<head>` du template.
- **T-P5.2** `web/sw.js` : install→precache assets statiques (`css/js/vendor/icons`) + `/` ; `/`=network-first ; assets=cache-first ; `/api/*` + tuiles=network-only ; cache versionné + purge à l'`activate`. Route FastAPI `GET /sw.js` (scope racine) + `GET /manifest.webmanifest`.
- **T-P5.3** Enregistrement du SW + `beforeinstallprompt` → bouton « Installer l'app » (Profil) ; instructions iOS. Bandeau hors-ligne (`navigator.onLine` + échec fetch).
- **Done-gate** : audit Lighthouse PWA (installable) ; tests backend : `/manifest.webmanifest` + `/sw.js` servis (200 + content-type) ; precache-list ne référence que des fichiers existants.

---

## Notes

- Après Phase 5, exécuter **superpowers:finishing-a-development-branch** pour la branche entière (Plan 1 + Plan 2). Le **merge en `main` (prod)** est un choix réservé à l'utilisateur (QA visuelle + déploiement Oracle Cloud).
- Compte de test local : `dev@sporia.local` / `sporia-dev` (admin, `data/sporia.db`, local).
- Phase 3 est mécanique/à comportement préservé (exécutable en autonomie) ; Phases 4-5 produisent l'UX visible → validation humaine avant prod.
