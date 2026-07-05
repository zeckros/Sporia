# Sporia — SDM habitat : jeu de variables par guilde (espèces d'habitat ouvert) — Design

## Contexte

Le modèle servi est un produit de deux modèles indépendants par espèce : le **« où »**
(SDM d'habitat, `scripts/train_sdm.py` → `sdm_<latin>.npy`) et le **« quand »**
(fructification, `scripts/train_fruiting.py`). Ce chantier ne touche que le **« où »**.

Diagnostic (importances + métriques du dernier retrain, `data/cache/_retrain_sdm.log` et
`src/sporia/data/species_metrics.yaml`) : les 3 espèces d'**habitat ouvert** modélisent mal
leur habitat —

- Calocybe gambosa : AUC 0.659, **Boyce −0.19** (exclue du service), 190 présences ;
- Agaricus campestris : AUC 0.667, Boyce 0.32, 317 présences ;
- Macrolepiota procera : AUC 0.618, Boyce 0.40, **1277 présences** (donc pas un problème de volume).

Trois causes :
1. **Généralisme** : ces espèces poussent en prairie / lisière / clairière / bord de route
   (niche large, peu déterministe). Macrolepiota à 1277 présences plafonne à AUC 0.62 → plafond
   de niche réel, pas de manque de données.
2. **Signal « prairie » dilué** : `lc_grass` n'apparaît dans le top d'aucune des trois ; les
   importances sont étalées (max ~0.06). Le jeu de ~35 variables est **forestier** (forest_density,
   host_*, edge_density, twi…) et noie les axes pertinents.
3. **Sur-apprentissage** : Calocybe (190 présences, ~35 variables, CV spatiale) obtient un Boyce
   négatif — le modèle s'accroche à des motifs sol/climat qui ne généralisent pas dans l'espace.

Les couches « milieu ouvert » existent déjà bakées (`lc_grass`, `lc_crop`, `lc_shrub`,
`lc_wetland`, `soc`, `cec`, `dist_water`). Le levier n'est donc **pas** d'ajouter des variables,
mais de **sélectionner un jeu restreint et pertinent par guilde** — retirer le bruit forestier et
réduire le sur-apprentissage.

## Décisions

- **Périmètre resserré** : uniquement les 3 espèces d'habitat ouvert (Calocybe, Agaricus,
  Macrolepiota). Les ectomycorhiziennes et le saprophyte (Pleurotus) restent **inchangés** →
  aucune régression sur cèpes/girolles/pleurote.
- **Mécanisme = sélection de variables par guilde** (feature selection). Fond target-group
  **inchangé** (il se re-filtre automatiquement sur les colonnes de l'espèce), RandomForest et ses
  hyperparamètres **inchangés** — on isole l'effet de la sélection de variables.
- **Structure = champ `guild` déclaratif dans `species.yaml`** (data-driven, extensible), plutôt
  qu'un set codé en dur. Remplace la logique `NO_HOST` actuelle.
- **Hors périmètre** (écartés explicitement) : fond adapté par guilde ; passage à gradient boosting
  monotone ; ajout de sources d'occurrences ; toute retouche des espèces ecto/sapro.

## Unité 1 — Schéma `guild` dans `species.yaml`

Ajouter un champ `guild` à chacune des 13 entrées de
`src/sporia/data/species.yaml` :

- `ecto` (ectomycorhizienne forestière) : Boletus aereus, Cantharellus cibarius, Boletus edulis,
  Craterellus cornucopioides, Craterellus tubaeformis, Hydnum repandum, Lactarius deliciosus,
  Imleria badia, Lepista nuda, Morchella esculenta.
- `open` (milieu ouvert) : Calocybe gambosa, Agaricus campestris, Macrolepiota procera.
- `sapro` (saprophyte sur bois) : Pleurotus ostreatus.

`src/sporia/domain/species.py` charge déjà l'entrée YAML telle quelle → `guild` arrive dans
`MUSHROOMS` sans code de parsing dédié (simple chaîne, pas dans `_PAIR_FIELDS`).

## Unité 2 — Logique de guilde dans `scripts/train_sdm.py`

Remplacer le set `NO_HOST` et `species_feats(feats, species)` par une logique de guilde :

- Une table `guild_of(latin) -> str` lisant `MUSHROOMS` (défaut `ecto` si champ absent, pour
  robustesse).
- `species_feats(feats, latin)` :
  - `ecto` → jeu complet actuel (host_* inclus) — inchangé ;
  - `open`/`sapro` → host_* retiré (= comportement `NO_HOST` d'aujourd'hui) ;
  - `open` → **en plus**, restreindre au **jeu « milieu ouvert »** (Unité 3).
- Rétrocompatibilité : le comportement `NO_HOST` (drop host_*) est reproduit à l'identique pour
  `sapro` (Pleurotus) — aucun changement pour lui.

## Unité 3 — Jeu de variables « milieu ouvert »

Défini comme un ensemble de variables **conservées** (intersecté avec les variables réellement
disponibles au chargement, pour rester robuste si une couche manque) :

- **GARDER** : `ph`, `clay`, `sand`, `silt` (texture) · `soc`, `cec` (fertilité) · `dist_water`
  (humidité) · `altitude`, `slope`, `northness` (relief) · `lc_grass`, `lc_crop`, `lc_shrub`,
  `lc_wetland`, `lc_tree`, `lc_built` (occupation du sol) · toutes les `clim_*` (climat).
- **RETIRER** (implicitement, en n'étant pas dans la liste GARDER) : `forest_density`, `host_*`,
  `edge_density`, `twi`, `tpi`, `slope_dem` — structure et hydrologie *forestières*, bruit pour une
  prairie.

Résultat : ~16 variables ciblées au lieu de ~35 → moins de sur-apprentissage (clé pour Calocybe)
et modèle forcé sur les axes pertinents. Le signal « évite la forêt » reste porté par `lc_tree`
(association négative).

**Knob documenté (hors V1)** : `soc`/`cec` ont ~31 % de NaN — c'est déjà le cas dans le modèle
actuel (donc pas de régression de couverture), mais si Calocybe perd trop de présences valides
après restriction, les retirer du jeu ouvert est l'ajustement de repli.

## Unité 4 — Validation & acceptation

- Réentraîner le SDM des 3 espèces `open` : `python scripts/train_sdm.py --all --predict`
  (ou par espèce), qui écrit `sdm_<latin>.npy` et logue Boyce/AUC (CV spatiale par blocs).
  **Sauvegarder** les `sdm_<latin>.npy` des 3 espèces avant écrasement (réversibilité).
- Comparer Boyce/AUC **avant/après** par espèce.
- Cibles :
  - Calocybe → Boyce **≥ 0.10** (redevient servie ; aujourd'hui exclue à −0.19) ;
  - Agaricus / Macrolepiota → Boyce **en hausse** (départ 0.32 / 0.40).
- **Filet de sécurité honnête** : si une espèce ne franchit pas 0.10, `is_reliable_habitat`
  (`domain/metrics.py`, seuil 0.10) la laisse **non-servie** et `confidence_tier` l'étiquette
  « modérée » — aucune sur-promesse. Macrolepiota (généraliste) a un plafond réel : gain
  possiblement modeste, assumé.
- Ré-émettre `src/sporia/data/species_metrics.yaml` via `python scripts/report_metrics.py
  --emit-yaml` (fusion préservante déjà en place : conserve `fruiting_*`/`radar_*`).

## Tests

- **Unitaire** sur le mapping guilde→variables : `species_feats` sur une espèce `open` renvoie le
  jeu restreint **sans** `forest_density`/`host_*`/`edge_density`/`twi` ; sur une espèce `ecto`
  renvoie le jeu complet (avec host_* et forest_density). Sur `sapro`, host_* retiré mais
  forest_density conservé.
- **Non-régression** : le `guild_of` par défaut (`ecto`) garantit que toute espèce sans champ
  `guild` garde le comportement actuel.

## Réversibilité & indépendance

- Ne touche que 3 cartes `sdm_*.npy` (sauvegardées) + `species.yaml` (tracké) + `train_sdm.py`.
- Indépendant du chantier fructification (« quand ») en cours (lot météo-pure) : les deux modèles
  sont séparés et se combinent seulement au moment du blend servi.
