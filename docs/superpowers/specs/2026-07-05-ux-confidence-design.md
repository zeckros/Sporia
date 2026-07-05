# Sporia — Chantier 4.5/5 : UX polish (badge de confiance) — Design

## Contexte

Dernier sous-projet du chantier 4. Les précédents (4.1 Comptes, 4.2 Stripe, 4.3 Gating, 4.4
Légal/RGPD) sont FAITS/mergés. Le SDM connaît la **fiabilité de sa carte d'habitat par espèce**
(indice de Boyce, dans `data/species_metrics.yaml`, exposé par `domain/metrics.py`), mais l'UI ne
la montre pas : l'utilisateur ne sait pas quelles prédictions sont solides.

## Décisions

- **Périmètre resserré** : un **badge de confiance** par espèce, dérivé du Boyce habitat, affiché
  dans le sélecteur « Mes champignons ». C'est le gain UX concret, testable et à faible risque.
- **CSP `unsafe-inline` — reporté (documenté, pas de code)** : le durcissement suppose d'abandonner
  le CDN Tailwind (config en page) + les scripts inline au profit d'un **build Tailwind** vers un
  CSS statique et de nonces — un chantier frontend-build à part entière, disproportionné et risqué
  ici. On documente la raison ; la protection réelle contre l'injection reste l'échappement des
  données utilisateur (déjà en place) + les autres en-têtes (déjà en place).
- **Pas de refonte visuelle spéculative** (subjective, risque de régression sur une UI qui marche).

## Unité — Badge de confiance

### 1. `domain/metrics.py`

`confidence_tier(latin: str) -> str` : mappe le Boyce habitat en trois paliers —
`"élevée"` (Boyce ≥ 0.50), `"bonne"` (≥ 0.35), `"modérée"` (sinon, y compris Boyce absent).
Toutes les espèces **servies** ont un Boyce ≥ seuil (0.10), donc au minimum `"modérée"`.

### 2. Catalogue — `web/app.py`

`_catalog()` ajoute à chaque entrée un champ `"confidence": metrics.confidence_tier(m["latin"])`
(en plus de `latin`/`nom`/`color`). Le catalogue est déjà renvoyé par `GET /api/preferences`
(`res.all`) — aucune nouvelle route.

### 3. Frontend — `web/app.js`

Dans le rendu du sélecteur « Mes champignons » (`#species-list`), afficher après le nom un petit
**badge** coloré selon `s.confidence` : élevée = vert, bonne = ambre, modérée = gris. Une légende
d'une ligne explique « fiabilité de la carte d'habitat ». Aucune logique métier côté client (le
palier vient du serveur).

## Tests (pytest)

- `tests/test_confidence.py` :
  - `confidence_tier("Imleria badia")` (Boyce 0.727) → `"élevée"` ;
  - `confidence_tier("Boletus edulis")` (0.389) → `"bonne"` ;
  - `confidence_tier("Agaricus campestris")` (0.320) → `"modérée"` ;
  - `confidence_tier("Espèce inconnue")` → `"modérée"` (fallback sans Boyce).
  - Câblage catalogue : monkeypatch `core.fruiting_models` → `["Imleria badia"]`, `app._catalog()`
    renvoie une entrée avec `confidence == "élevée"`.

Frontend non testé unitairement (convention projet) → vérif manuelle (badges visibles, couleurs).

## Fichiers concernés

- **Créés** : `tests/test_confidence.py`.
- **Modifiés** : `src/sporia/domain/metrics.py` (+`confidence_tier`), `src/sporia/web/app.py`
  (`_catalog` + champ confidence), `web/app.js` (badge + légende), `src/sporia/web/security.py`
  (commentaire mis à jour renvoyant à la note CSP), `ORACLE_DEPLOY.md` (note « CSP durci = chantier
  build Tailwind, reporté »).

## Vérification

1. `pytest` + `ruff` verts.
2. Manuel : « Mes champignons » montre un badge par espèce (élevée/bonne/modérée) avec la bonne
   couleur ; la légende est présente.

## Hors périmètre

Durcissement CSP complet (chantier build Tailwind, reporté) · refonte visuelle · badge sur d'autres
écrans que le sélecteur (radar/point — extension future triviale via le même champ).
