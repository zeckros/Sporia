# Sporia — SDM habitat transfrontalier (entraînement domaine élargi) — Design

## Contexte

Le SDM d'habitat s'entraîne sur des occurrences GBIF **France seulement** (`train_sdm.py`,
`fetch_occurrences(..., country="FR")` + filtre présences par masque France). Les espèces
**pauvres en données** en pâtissent — surtout Calocybe gambosa (190 présences FR exploitables,
Boyce stable −0.043, non servie).

Diagnostic (mesuré) :
- La grille/bbox actuelle `(-5.5..10.5 lon, 41..51.5 lat)` couvre déjà de larges pans des
  voisins (Belgique, ouest de l'Allemagne, Suisse, nord de l'Italie, NE de l'Espagne).
- Les rasters de prédicteurs **climat (WorldClim), relief (Copernicus DEM), occupation du sol
  (CGLS), densité forêt, et sol (SoilGrids)** couvrent **déjà toute la bbox** (valeurs valides
  à Bruxelles, Genève, Turin, Fribourg-DE…). Seul `host_*` (essence BD Forêt, inventaire
  forestier **français**) est NaN hors de France.
- Occurrences **dans la bbox, tous pays** vs France seule : Calocybe 538 → **5 389 (×10)**,
  Agaricus 842 → **4 524 (×5.4)**, Macrolepiota 2 454 → **16 858 (×6.9)**.

Conclusion : ×5-10 de données transfrontalières sont récupérables **sans étendre aucun raster**
(les rasters couvrent déjà la bbox). Le jeu de variables disponible à l'étranger = climat + sol
+ occupation + relief (+ densité forêt), **sans `host_*`** — c'est-à-dire le jeu « milieu
ouvert » de la guilde. Le transfrontalier est donc *feature-cohérent* pour les espèces **sans
arbre-hôte** (habitat ouvert + saprophytes), qui sont justement les plus pauvres en données.

## Décisions

- **Approche A — in-bbox transfrontalier** : retirer le filtre `country=FR` du fetch GBIF (garder
  le filtre bbox), entraîner sur les présences bbox tous-pays, **servir la France seule**
  (prédiction inchangée). ×5-10 de données, quasi gratuit. Étendre la bbox plus loin (est-DE,
  sud-ES/IT, GB) = chantier ultérieur (YAGNI tant que A n'a pas plafonné).
- **Auto-filtrage par le jeu de variables** : `host_*` étant NaN hors des forêts françaises, une
  espèce qui l'utilise (ectomycorhizienne) voit ses cellules étrangères **écartées
  automatiquement** par le filtre « prédicteurs valides » → elle reste de facto FR-only. Aucune
  logique par guilde à ajouter : seules les espèces **sans `host_*`** gagnent réellement les
  données transfrontalières.
- **Cible = espèces faibles sans arbre-hôte** : les 3 d'habitat ouvert (Calocybe, Agaricus,
  Macrolepiota, guilde `open`) **et** le saprophyte Pleurotus ostreatus (guilde `sapro`,
  n'utilise pas `host_*`, Boyce stable 0.230). On applique `--cross-border` à ces espèces.
  Nuance Pleurotus : son jeu `sapro` garde des couches de structure forestière
  (`edge_density`, `twi`) ; si l'une est France-only (NaN à l'étranger), ses cellules
  étrangères s'auto-filtrent et le gain sera faible — **mesuré** en validation (Unité 4), pas
  supposé. Le jeu `open` (Calocybe/Agaricus/Macrolepiota) est, lui, entièrement transfrontalier.
- **Fond target-group transfrontalier** : le fond doit venir du **même domaine** que les
  présences (bbox tous-pays), sinon le modèle apprend « France vs étranger » (densité
  d'échantillonnage) au lieu de l'habitat. Cache séparé.
- **Différé (repli documenté, hors périmètre)** : (a) les **trous SoilGrids à l'étranger**
  (NaN épars) réduisent les cellules exploitables ; si ça limite trop le gain, chercher des
  **données de sol européennes** plus complètes. (b) Les espèces faibles **à arbre-hôte**
  (ex. Lactarius deliciosus, sortie du service) ne peuvent pas profiter de A ; il leur faudrait
  un **équivalent européen du type de forêt** — chantier ultérieur.

## Unité 1 — Fetch sans filtre pays (`scripts/train_sdm.py`)

`fetch_occurrences(taxon_key, ..., country="FR")` gagne le paramètre `country` : si `None`,
la requête GBIF **omet** `country` (le filtre bbox `BBOX[0] <= lo <= BBOX[1] and BBOX[2] <= la
<= BBOX[3]` déjà présent restreint au domaine baké). Comportement par défaut (`"FR"`) inchangé.

## Unité 2 — Domaine de présences & fond transfrontaliers

- **Flag CLI `--cross-border`** sur `train_sdm.py`.
- **Présences** : `run_one` fetch avec `country=None` quand le flag est actif ; le filtre de
  présences passe de `isfinite(Xp) & france[...]` à **`isfinite(Xp)` seul** (on garde les
  cellules à prédicteurs valides, on lève la contrainte France).
- **Fond** : `build_background` fetch le target-group (règne Fungi) avec `country=None` et le
  met en cache dans un fichier **séparé** `sdm_bg_target_xborder_cells.npy` (pour ne pas
  écraser/mélanger avec le fond FR `sdm_bg_target_cells.npy`).
- **Prédiction inchangée** : `rows, cols = np.where(france)` → carte servie France seule.

## Unité 3 — Câblage `main()`

`--cross-border` propage `country=None` au fetch de présences (`run_one`) et au fetch de fond
(`build_background`), et lève le masque France sur les présences. Combinable avec `--predict`,
`--repeats`, et une espèce nommée ou une petite liste. On l'invoque sur les 4 espèces sans hôte
(Calocybe, Agaricus, Macrolepiota, Pleurotus) — les autres, si on les passait, s'auto-filtrent.

## Unité 4 — Validation (le payoff)

Réentraîner chaque espèce cible en `--cross-border --predict --repeats 25` ; comparer le
**Boyce stable ± SE** aux valeurs FR-only committées (`species_metrics.yaml` : Calocybe −0.043,
Agaricus 0.262, Macrolepiota 0.519, Pleurotus 0.230). Sauvegardes des `sdm_*.npy` et du yaml
avant. Décision par espèce, à métrique fiable :
- Calocybe : la borne prudente `boyce − se` franchit-elle enfin **0.10** (redevient servie) ?
- Autres : Boyce stable en hausse (au-delà de la SE) ?
Ré-émettre `species_metrics.yaml` après. Noter le nb de présences exploitables gagné par espèce
(mesure directe du bénéfice transfrontalier), et si les trous SoilGrids limitent (bcp de cellules
étrangères écartées faute de sol).

## Tests

- **Smoke** : `fetch_occurrences(k, country=None)` renvoie nettement plus d'occurrences (bbox
  tous-pays) que `country="FR"` pour une espèce test — vérifie que le filtre pays est bien levé.
- Le reste est **opérationnel** (comme la ré-estimation du chantier stabilisation) : la
  validation par le Boyce stable avant/après est la preuve.

## Réversibilité & indépendance

- Touche `scripts/train_sdm.py` (fetch + run_one + build_background + main) et, en ré-émission,
  `species_metrics.yaml` + les `sdm_*.npy` des espèces cibles (sauvegardés).
- N'affecte **aucune** espèce à arbre-hôte (auto-filtrage) ni la prédiction/service (France seule).
- S'appuie sur la métrique **Boyce stabilisée** (chantier précédent) pour mesurer le gain — sans
  elle, le bénéfice serait noyé dans le bruit.
