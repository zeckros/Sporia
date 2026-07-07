# Sporia — SDM habitat transfrontalier + type de forêt européen — Design

## Contexte

Le SDM d'habitat s'entraîne sur des occurrences GBIF **France seulement**. Les espèces
pauvres en données en pâtissent (Calocybe gambosa : 190 présences FR, Boyce stable −0.043,
non servie). Objectif : entraîner sur un **domaine élargi** (pays voisins), tout en **servant
uniquement la France**, et **équilibrer** les effectifs entre espèces.

Faits mesurés :
- La grille/bbox `(-5.5..10.5 lon, 41..51.5 lat)` couvre déjà de larges pans de BE / ouest-DE /
  CH / nord-IT / NE-ES. Les rasters climat (WorldClim), relief (Copernicus DEM), occupation du
  sol (WorldCover), sol (SoilGrids) **couvrent déjà toute la bbox**.
- Occurrences **dans la bbox, tous pays** vs France seule : Calocybe 538 → **5 389 (×10)**,
  Agaricus 842 → **4 524 (×5.4)**, Macrolepiota 2 454 → **16 858 (×6.9)**.
- **Seule `host_*` (essence BD Forêt) est France-only** (NaN à l'étranger, couches grossières
  *et* fines confondues). Donc les espèces à arbre-hôte (ectomycorhiziennes) ne peuvent pas
  utiliser la donnée transfrontalière : leurs cellules étrangères s'auto-filtrent faute d'hôte.
- **Spike validé** : la couche **CGLS-LC100 Forest-Type** (Zenodo, record 3939050) est
  streamable en COG `/vsicurl` (blocs 256×256, uint8, globale 362880×141120), avec les classes
  1=conifère persistant, 3=conifère caduc, 2/4=feuillu, 5=mixte — et des **données valides des
  deux côtés de la frontière** (fenêtre Vosges/Forêt-Noire : conifères + feuillus + mixte). Elle
  fournit donc un **hôte grossier pan-européen** pour débloquer les ecto en transfrontalier.

## Décisions

- **Transfrontalier in-bbox (approche A)** : retirer le filtre `country=FR` du fetch GBIF (garder
  le filtre bbox), entraîner sur les présences bbox tous-pays, **servir la France seule**
  (prédiction `np.where(france)` inchangée). Étendre la bbox au-delà = chantier ultérieur (YAGNI).
- **Couche forêt-EU** : baker `fteu_broadleaf` / `fteu_needleleaf` depuis CGLS Forest-Type
  (fractions par cellule 0.01°, toute la bbox) → hôte grossier disponible à l'étranger.
- **Jeux de variables par guilde en transfrontalier** :
  - sans hôte (open + sapro) → jeu « milieu ouvert » (déjà transfrontalier) ;
  - ecto → **remplacer `host_*` fin (France-only) par `fteu_broadleaf/needleleaf` (grossier,
    pan-européen)**.
- **A/B par espèce — garder le meilleur, aucune régression forcée** : pour chaque espèce,
  comparer au **Boyce stable ± SE** le modèle transfrontalier (plus de données) vs le modèle
  actuel FR-only (host fin pour les ecto). On sert le meilleur des deux par espèce.
- **Cap d'équilibrage à N dérivé empiriquement** : N n'est PAS hardcodé. Une **courbe
  d'apprentissage** sur une espèce riche fixe N au plateau du Boyce stable (pari 1000-2000).
  Amincissement **spatial** (pas aléatoire) pour préserver la couverture environnementale.
- **S'appuie sur le Boyce stabilisé** (chantier précédent) : sans lui, le gain serait noyé
  dans le bruit.

## Unité 1 — Bake forêt-EU (`scripts/bake_foresttype_eu.py`)

Nouveau script (motif `bake_landcover.py` : `/vsicurl`, lecture fenêtrée, agrégation en fraction
de classe par cellule 0.01°). Source : CGLS-LC100 Forest-Type (URL Zenodo confirmée). Fenêtre =
bbox. **3 sorties** (aucune classe forêt perdue) : `data/cache/fteu_broadleaf.npy` (fraction des
classes 2+4), `fteu_needleleaf.npy` (1+3), `fteu_mixed.npy` (5) ; `NaN` hors données. Repris par
`train_sdm` via un hook dédié (comme `lc_*`/`clim_*`).
Volume streamé ~150-200 Mo (fenêtre France-bbox à 100 m, pas d'overviews → lecture pleine
résolution de la fenêtre puis décimation, comme WorldCover).

## Unité 2 — Machinerie transfrontalière (`scripts/train_sdm.py`)

- `fetch_occurrences(..., country="FR")` : paramètre `country` ; `None` → requête GBIF sans
  filtre pays (le filtre bbox déjà présent restreint au domaine).
- Flag CLI `--cross-border` : fetch présences (`run_one`) et fond (`build_background`) avec
  `country=None` ; filtre présences `isfinite(Xp)` **sans** masque France ; fond target-group
  transfrontalier en cache séparé `sdm_bg_target_xborder_cells.npy`. Prédiction inchangée
  (France seule).

## Unité 3 — Jeu de variables ecto transfrontalier (`sporia.domain.species`)

`habitat_feature_subset(feats, latin, cross_border=False)` : nouveau paramètre. En mode
`cross_border` pour une espèce `ecto`, **retirer `host_*`** et **ajouter `fteu_broadleaf`,
`fteu_needleleaf`, `fteu_mixed`**. `open`/`sapro` inchangés (déjà transfrontaliers). `train_sdm` passe
`cross_border=a.cross_border`. (Fonction pure, testable.)

## Unité 4 — Cap d'équilibrage à N empirique (`scripts/train_sdm.py`)

- Amincissement spatial des présences à `N` cellules max (sous-échantillon régulier dans
  l'espace, pas aléatoire), paramètre `--max-pres` (défaut = valeur du plateau, cf. courbe).
- **Courbe d'apprentissage** (opérationnel, avant de figer N) : sur une espèce riche
  (Macrolepiota, transfrontalier), mesurer le Boyce stable à N = 500/1000/2000/4000 ; fixer N au
  plateau. Documenter la courbe.

## Unité 5 — A/B par espèce + validation (opérationnel)

- Sauvegardes (`sdm_*.npy`, `species_metrics.yaml`) avant.
- Pour chaque espèce cible : entraîner en `--cross-border --predict --repeats 25` (avec le jeu
  guilde adapté + cap N) ; comparer le **Boyce stable ± SE** au modèle FR-only committé.
  **Garder le meilleur** (si transfrontalier ≤ FR à la SE près, on garde FR). Consigner le
  gain de présences et le verdict par espèce.
- Ré-émettre `species_metrics.yaml`. Question tranchée : Calocybe franchit-elle le seuil ? les
  ecto gagnent-elles avec l'hôte grossier + plus de données, ou l'hôte fin FR reste-t-il
  meilleur ?

## Tests

- `bake_foresttype_eu` : test unitaire de l'**agrégation** (fonction pure classe→fraction sur un
  petit tableau synthétique : feuillu={2,4}, conifère={1,3}, mixte={5}, nodata ignoré).
- `habitat_feature_subset(cross_border=True)` : ecto → `host_*` retirés, `fteu_*` ajoutés ;
  open/sapro inchangés ; `cross_border=False` → comportement actuel.
- `fetch_occurrences(country=None)` : smoke (compte bbox tous-pays > compte FR).
- Le reste (bake réel, courbe, A/B) est **opérationnel**, validé par le Boyce stable.

## Réversibilité & indépendance

- Nouveaux fichiers : `scripts/bake_foresttype_eu.py`, `data/cache/fteu_*.npy` (non versionné).
- Modifie `scripts/train_sdm.py` et `sporia/domain/species.py` (paramètre `cross_border`).
- **A/B garde-le-meilleur** ⇒ aucune espèce dégradée ; la prédiction reste **France seule**.
- Cartes/metrics sauvegardées avant ré-estimation.
