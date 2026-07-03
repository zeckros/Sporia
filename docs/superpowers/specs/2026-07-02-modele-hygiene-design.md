# Sporia — Chantier 3/5 : Modèle — Hygiène & métriques reproductibles — Design

## Contexte

La revue fine du modèle (ce chantier) a montré qu'il est **déjà très abouti**, contredisant
plusieurs craintes de la revue initiale :

- **Fructification** (le « quand ») : AUC 0.84, **Boyce 0.91** — excellent.
- **Habitat SDM** (le « où ») : AUC 0.69, Boyce 0.46 — correct, et **entraîné avec le vrai
  climat** (WorldClim baké le 13/06, jour de l'entraînement des `sdm_*.npy`) → la faiblesse
  « lat/lon dominent » est **déjà corrigée en prod**.
- Jeu de prédicteurs **complet** (log d'entraînement) : sol (pH/argile/limon/sable, soc, cec),
  relief (altitude/pente/northness, twi, tpi, dist_water, slope_dem, edge_density), **8 var.
  climatiques WorldClim**, **6 classes d'occupation du sol** (grass/crop/shrub/tree/built/wetland
  ESA WorldCover, déjà auto-utilisées par `train_sdm.py`), arbres-hôtes par guilde.

**Il n'y a donc pas de prédicteur évident à ajouter** — notamment l'occupation du sol (prairies/
cultures) est déjà là. Les espèces faibles sont les **généralistes de milieux ouverts** (Mousseron
Boyce **−0.19**, Rosé 0.32, Coulemelle 0.40 malgré 1277 présences), faibles parce que leur écologie
est **intrinsèquement diffuse** + biais d'observation urbain — pas par manque de données.

**Décision (avec l'utilisateur)** : chantier d'**hygiène honnête**, pas de ré-entraînement/refonte
(gains incertains). On protège l'utilisateur des cartes trompeuses et on rend les métriques
reproductibles. **Hors périmètre** : ré-entraînement des espèces difficiles, changement du feature
set, badge « faible confiance » dans l'UI (**décalé au chantier #4 UX** — le `species_metrics.yaml`
produit ici fournira la donnée le moment venu).

## Périmètre & unités

### 1. Métriques versionnées : `species_metrics.yaml`

- **Créer** `src/sporia/data/species_metrics.yaml` (versionné) : par latin, le **Boyce et l'AUC
  habitat** issus du dernier entraînement. Snapshot committé → suivi qualité dans le temps.
- **Générer** ce fichier depuis les logs de retrain (`data/cache/_retrain_sdm.log`) via une petite
  fonction dans `scripts/report_metrics.py` (option `--emit-yaml` ou fonction dédiée). Les logs
  sont gitignorés ; le YAML, lui, est committé.
- Valeurs actuelles (extraites du log) : p.ex. `Calocybe gambosa: {boyce: -0.188, auc: 0.659}`,
  `Boletus edulis: {boyce: 0.389, auc: 0.685}`, `Imleria badia: {boyce: 0.727, auc: 0.733}`, etc.

### 2. Exclusion pilotée par les données (le vrai gain)

- **Créer** `src/sporia/domain/metrics.py` : charge `species_metrics.yaml` et expose
  `habitat_boyce() -> dict[str, float]` et `hidden_species(threshold: float = 0.10) -> set[str]`
  = { latin dont le Boyce habitat est **absent, None, ou < threshold** }.
  Seuil `0.10` : exclut Morille (pas de modèle) et **Mousseron (−0.19)**, garde Rosé/Coulemelle
  (>0.3). Seuil documenté et ajustable.
- **Remplacer** les deux sets en dur par cette source unique :
  - `enrich/fruiting_live.py` : `_HIDDEN_FRUITING` (ligne 49) devient
    `_HIDDEN_FRUITING = hidden_species()` (import depuis `sporia.domain.metrics`).
  - `overlays/fruiting.py` : `EXCLUDED_FROM_MODELING` (ligne 15) redondant → le supprimer et
    faire `fruiting_models()` = `fruiting_live.available_models()` (qui applique déjà `_HIDDEN_FRUITING`).
- Résultat : **Mousseron n'est plus servi** (comme la morille) ; si un futur retrain change les
  Boyce, la liste servie s'ajuste automatiquement.

### 3. Fix `report_metrics.py`

- Le script **plante** en fin d'exécution (`UnicodeEncodeError` sur `≤`/caractères non-cp1252 vers
  stdout Windows). **Forcer l'encodage UTF-8** de stdout (`sys.stdout.reconfigure(encoding="utf-8")`
  en tête de `main()`), pour que le récap tourne proprement et puisse émettre le YAML.

### 4. Tests

- `tests/test_metrics.py` : `hidden_species()` — Mousseron (Boyce −0.19) **dans** le set ; une
  espèce à Boyce ≥ 0.10 (p.ex. Bolet bai) **hors** du set ; `habitat_boyce()` charge le YAML.
- `tests/test_served_species.py` : `overlays.fruiting.fruiting_models()` (ou l'API `/api/fruiting-models`)
  **ne contient pas** `Calocybe gambosa` ni `Morchella esculenta`, et contient bien une espèce
  forte (p.ex. `Imleria badia`).

## Fichiers concernés

- Créés : `src/sporia/data/species_metrics.yaml`, `src/sporia/domain/metrics.py`,
  `tests/test_metrics.py`, `tests/test_served_species.py`.
- Modifiés : `scripts/report_metrics.py` (fix UTF-8 + émission YAML),
  `src/sporia/enrich/fruiting_live.py` (`_HIDDEN_FRUITING` piloté par métriques),
  `src/sporia/overlays/fruiting.py` (retrait de `EXCLUDED_FROM_MODELING` redondant).

## Vérification

1. `pytest` + `ruff` verts ; nouveaux tests passent.
2. `Calocybe gambosa` et `Morchella esculenta` **absents** des espèces servies ; espèces fortes présentes.
3. Iso-comportement pour les espèces conservées : la carte radar/point d'une espèce forte (p.ex.
   Boletus edulis) reste identique (on ne change que la LISTE servie, pas le calcul).
4. `python scripts/report_metrics.py` tourne **sans crash** et régénère `species_metrics.yaml`.
5. `git diff` de `species_metrics.yaml` = source de vérité lisible des Boyce/AUC par espèce.

## Hors périmètre

Ré-entraînement des généralistes de milieux ouverts (gains incertains) · ajout/refonte de
prédicteurs (feature set déjà complet) · badge « faible confiance » dans l'UI (→ chantier #4 UX,
alimenté par `species_metrics.yaml`) · tuning du GBM / du modèle de fructification (déjà excellent).
