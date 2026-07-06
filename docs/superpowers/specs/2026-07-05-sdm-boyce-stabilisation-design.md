# Sporia — Stabilisation de la métrique Boyce du SDM habitat — Design

## Contexte

La fiabilité de la carte d'habitat par espèce est mesurée par l'**indice de Boyce** (CV
spatiale par blocs, `scripts/train_sdm.py::run_one` → `data/species_metrics.yaml`), et cette
valeur pilote le service : `is_reliable_habitat` (seuil 0.10) décide quelles espèces sont
servies, `confidence_tier` affiche un palier de confiance.

Problème constaté : le Boyce est **inutilisable en l'état**. Entre deux retrains, une espèce
au jeu de variables *inchangé* voyait son Boyce bouger de ±0.4 (ex. Boletus edulis
0.389 → 0.817).

Diagnostic empirique (script jetable, Boletus edulis, **données strictement identiques**,
10 découpages CV aléatoires) :

| Métrique | moyenne | écart-type | min → max | étendue |
|---|---|---|---|---|
| AUC      | 0.693 | **0.009** | 0.677 → 0.702 | 0.025 |
| Boyce    | 0.689 | **0.179** | 0.321 → 0.941 | 0.620 |

Cause identifiée sans ambiguïté : `run_one` reporte le Boyce d'**un seul** découpage CV, et
le Boyce d'un découpage a un écart-type de ~0.18. Ce n'est ni un problème de reproductibilité
des entrées, ni une dérive de données — c'est la **variance de partition** du Boyce. L'AUC,
métrique de rang globale, est déjà stable (±0.009).

## Décisions

- **Méthode = CV répétée** : moyenner le Boyce sur N découpages CV aléatoires (l'écart-type de
  la moyenne chute en √N), et **reporter l'incertitude** (erreur-type).
- **+ Boyce continu** (fenêtre glissante, Hirzel 2006) en remplacement des 10 casiers fixes :
  réduit la variance par tirage → moins de répétitions pour la même précision.
- **Usage = validation ET gating de service** : la métrique stable pilote `is_reliable_habitat`
  et `confidence_tier`.
- **Gating prudent** : on sert une espèce seulement si **(boyce − boyce_se) ≥ 0.10** ; les
  paliers de confiance suivent la même borne prudente. Protège contre la sur-promesse des
  espèces limites/bruitées.
- **Structure = dans `train_sdm.py`** (là où les métriques CV sont déjà calculées), pas de
  script séparé.
- **Hors périmètre** (écarté, chantier ultérieur) : ajouter des occurrences (transfrontalier,
  sociétés mycologiques). Il *dépend* de ce chantier : sans Boyce stable, on ne peut pas
  mesurer si plus de données aide. `eval_radar` (Boyce fructification/radar) n'est pas touché.

## Unité 1 — Boyce continu (`scripts/train_sdm.py`)

`boyce_index_continuous(pres, bg, window=0.1, res=100)` — ajoutée à côté de `boyce_index`
(conservée pour compat / `eval_radar`). Une fenêtre de largeur `window` (fraction de la plage
de suitabilité) glisse sur [0,1] en `res` pas ; pour chaque position on calcule
`F = (part des présences dans la fenêtre) / (part du fond dans la fenêtre)` ; le Boyce continu
est la corrélation de Spearman entre le centre des fenêtres et `F`, sur les fenêtres où le
dénominateur > 0. `nan` si < 3 fenêtres valides (comme `boyce_index`). C'est ce Boyce qui
devient la métrique reportée.

## Unité 2 — CV répétée (`scripts/train_sdm.py`)

`repeated_cv_metrics(X, y, groups, repeats=25, k=5, n_estimators=200, seed=0)` → renvoie
`(auc_mean, boyce_mean, boyce_se)` :
- répète `repeats` fois : assigne aléatoirement (rng dérivé de `seed`) chaque groupe (bloc
  spatial) à l'un des `k` folds ; pour chaque fold entraîne un RandomForest
  (`n_estimators`, `min_samples_leaf=3`, `class_weight="balanced_subsample"`, `random_state=0`)
  et calcule AUC (si 2 classes au test) + `boyce_index_continuous` ; moyenne sur les folds → un
  `(auc, boyce)` par répétition ;
- `auc_mean` / `boyce_mean` = moyenne sur les répétitions ; `boyce_se = std(boyces) / √repeats`.

`run_one` remplace sa boucle `GroupKFold` actuelle par un appel à `repeated_cv_metrics` ; ajoute
l'argument CLI `--repeats` (défaut 25). Les **folds de CV** utilisent des forêts plus légères
(`n_estimators=200`) ; le **modèle final servi** reste inchangé (`n_estimators=500` +
calibration isotonic). `run_one` renvoie et logue `(n_presence, auc_mean, boyce_mean, boyce_se)`.

Runtime : ~30-60 min pour `--all` (14 espèces × 25 répétitions × 5 folds), sans quota réseau —
opération occasionnelle assumée.

## Unité 3 — Récap + persistance (`train_sdm.py` + `report_metrics.py`)

- Le tableau `RÉCAPITULATIF` de `train_sdm --all` imprime une colonne `BoyceSE` en plus de
  `présence / AUC / Boyce`.
- `report_metrics.py::parse_habitat` capture la 4ᵉ (Boyce) et 5ᵉ (SE) valeur ; `emit_yaml` écrit
  `{boyce, auc, boyce_se}` par espèce. La fusion préservante déjà en place conserve
  `fruiting_*`/`radar_*`. Champ `boyce_se` absent d'une ancienne entrée → toléré.

## Unité 4 — Gating prudent (`src/sporia/domain/metrics.py`)

- Charger `boyce_se` par espèce (défaut 0.0 si absent → comportement actuel préservé).
- `is_reliable_habitat(latin, threshold=0.10)` : `True` si `(boyce − boyce_se) ≥ threshold`.
- `confidence_tier(latin)` : paliers sur `(boyce − boyce_se)` — « élevée » ≥ 0.50,
  « bonne » ≥ 0.35, sinon « modérée » (y compris Boyce absent).

## Unité 5 — Ré-estimation + re-validation guilde (opérationnel)

Après le code : `python scripts/train_sdm.py --all --predict --repeats 25 >
data/cache/_retrain_sdm.log` puis `python scripts/report_metrics.py --emit-yaml`. Sauvegarder
`species_metrics.yaml` et les `sdm_*.npy` avant écrasement. On obtient enfin des Boyce fiables
± erreur-type. **Puis trancher la question guilde** : comparer, à métrique stable, le Boyce des
3 espèces `open` avec le jeu restreint vs le jeu complet — décision claire sur le maintien du
changement guilde (impossible avec le snapshot bruité).

## Tests

- `boyce_index_continuous` (données synthétiques) : séparation parfaite (présences toutes hautes,
  fond tout bas) → ≈ 1 ; recouvrement total (mêmes distributions) → ≈ 0 ou `nan` ;
  cas monotone modéré → valeur intermédiaire positive. Un cas comparant à `boyce_index` binné
  pour montrer la cohérence d'ordre.
- `repeated_cv_metrics` (X/y/groupes synthétiques séparables) : renvoie `(auc, boyce, se)` finis ;
  déterministe à `seed` fixe (deux appels identiques → mêmes valeurs) ; `se` décroît quand
  `repeats` augmente (ex. se(repeats=40) < se(repeats=5)).
- `metrics.py` (borne prudente = `boyce − boyce_se`) :
  - `boyce=0.12, boyce_se=0.05` → borne 0.07 < 0.10 → **non servie** ;
  - `boyce=0.50, boyce_se=0.03` → borne 0.47 → servie, tier **« bonne »** (0.47 ≥ 0.35, < 0.50) ;
  - `boyce=0.60, boyce_se=0.05` → borne 0.55 ≥ 0.50 → tier **« élevée »** ;
  - `boyce_se` absent (ancienne entrée) → borne = boyce → gating identique à aujourd'hui.

## Réversibilité & indépendance

- Touche `scripts/train_sdm.py`, `scripts/report_metrics.py`, `src/sporia/domain/metrics.py`,
  et (ré-émission) `src/sporia/data/species_metrics.yaml`. Sauvegardes avant ré-estimation.
- Indépendant du chantier fructification (« quand ») : `eval_radar` et son Boyce
  fruiting/radar ne sont pas modifiés.
- Le champ `guild` (chantier précédent) reste ; ce chantier fournit l'instrument pour trancher
  s'il apporte quelque chose.
