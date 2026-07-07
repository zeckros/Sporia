# SDM transfrontalier + forêt-EU — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entraîner le SDM d'habitat sur un domaine élargi (occurrences GBIF tous-pays dans la bbox), avec une couche forêt-EU grossière (CGLS) comme hôte de substitution pour les ectomycorhiziennes, tout en servant la France seule — et garder le meilleur modèle par espèce (FR-only fin vs transfrontalier).

**Architecture:** Une nouvelle couche `fteu_*` bakée depuis CGLS Forest-Type (motif WorldCover). La logique de sélection de variables (domaine `sporia.domain.species`) gagne un mode `cross_border` qui, pour les ecto, remplace `host_*` (France-only) par `fteu_*`. `train_sdm.py` gagne un flag `--cross-border` (fetch sans filtre pays, présences non masquées France, fond transfrontalier) et un cap d'équilibrage spatial `--max-pres`. Validation opérationnelle par le Boyce stabilisé (chantier précédent).

**Tech Stack:** Python 3.13, rasterio (/vsicurl COG), numpy, scikit-learn, GBIF API, pytest, ruff.

## Global Constraints

- Interpréteur `venv/Scripts/python.exe` ; commandes depuis la racine du repo.
- ruff sur les `src/` modifiés (`select ["E","F","I","UP","B"]`, `line-length 100`) ; `scripts/` porte du lint préexistant (ne pas ajouter de NOUVELLE erreur).
- pytest ; tests sur données synthétiques uniquement (pas de réseau, pas de `data/`).
- Commits **sans** `Co-Authored-By`. Pré-commit `ruff format` (src+tests) : re-stage si un commit est reformaté.
- Prédiction/service **France seule** (`np.where(france)`) — jamais modifié.
- Rétrocompat : `cross_border=False` et absence de `fteu_*` ⇒ comportement actuel (les tests existants restent verts).
- Source forêt-EU (spike validé) : `/vsicurl/https://zenodo.org/records/3939050/files/PROBAV_LC100_global_v3.0.1_2019-nrt_Forest-Type-layer_EPSG-4326.tif?download=1` ; encodage : 1=conifère persistant, 2=feuillu persistant, 3=conifère caduc, 4=feuillu caduc, 5=mixte, 0=non-forêt, 255=nodata.

---

### Task 1 : Bake forêt-EU (`scripts/bake_foresttype_eu.py`)

**Files:**
- Create: `scripts/bake_foresttype_eu.py`
- Test: `tests/test_foresttype_bake.py`

**Interfaces:**
- Produces: `foresttype_fractions(codes, gidx, n_cells, groups) -> dict[str, np.ndarray]` (pur, testable) ; le script produit `data/cache/fteu_broadleaf.npy`, `fteu_needleleaf.npy`, `fteu_mixed.npy`.

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/test_foresttype_bake.py` :

```python
"""Agrégation forêt-type (classe CGLS → fraction par cellule)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from bake_foresttype_eu import CLASS_GROUPS, foresttype_fractions  # noqa: E402


def test_fractions_single_cell():
    # 6 pixels dans la cellule 0 : {2,4}=feuillu(2), {1,3}=conifère(2), {5}=mixte(1), 0=non-forêt(1)
    codes = np.array([2, 4, 1, 3, 5, 0])
    gidx = np.zeros(6, dtype=int)
    out = foresttype_fractions(codes, gidx, n_cells=2, groups=CLASS_GROUPS)
    assert out["fteu_broadleaf"][0] == 2 / 6
    assert out["fteu_needleleaf"][0] == 2 / 6
    assert out["fteu_mixed"][0] == 1 / 6
    # cellule 1 sans pixel → NaN
    assert np.isnan(out["fteu_broadleaf"][1])


def test_class_groups_partition_forest():
    # feuillu {2,4}, conifère {1,3}, mixte {5} — disjoints, couvrent les classes forêt
    assert CLASS_GROUPS["fteu_broadleaf"] == {2, 4}
    assert CLASS_GROUPS["fteu_needleleaf"] == {1, 3}
    assert CLASS_GROUPS["fteu_mixed"] == {5}
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `venv/Scripts/python.exe -m pytest tests/test_foresttype_bake.py -q`
Expected : FAIL — `ModuleNotFoundError: No module named 'bake_foresttype_eu'`.

- [ ] **Step 3 : Écrire `scripts/bake_foresttype_eu.py`**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bake d'une couche FORÊT-TYPE européenne (feuillu/conifère/mixte) sur la grille Sporia,
depuis CGLS-LC100 Forest-Type (COG global, streamé en /vsicurl comme bake_landcover.py).
Donne un HÔTE GROSSIER pan-européen (≠ host_* BD Forêt, France-only) pour entraîner les
espèces ectomycorhiziennes sur le domaine transfrontalier.

Sorties : data/cache/fteu_broadleaf.npy, fteu_needleleaf.npy, fteu_mixed.npy (fraction ∈
[0,1] par cellule 0.01°, NaN hors données). Repris par train_sdm.py (hook fteu_*.npy).

Usage : python scripts/bake_foresttype_eu.py [--ov 1] [--force]
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path

import numpy as np

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,=1")

GRID_H, GRID_W, RES = 1051, 1601, 0.01
LON0, LAT0 = -5.5, 51.5
BBOX = (-5.5, 10.5, 41.0, 51.5)
CACHE = Path("data/cache")
URL = ("/vsicurl/https://zenodo.org/records/3939050/files/"
       "PROBAV_LC100_global_v3.0.1_2019-nrt_Forest-Type-layer_EPSG-4326.tif?download=1")
NODATA = 255
CLASS_GROUPS = {"fteu_broadleaf": {2, 4}, "fteu_needleleaf": {1, 3}, "fteu_mixed": {5}}


def accumulate_counts(codes, gidx, total, counts, groups):
    """Accumule EN PLACE le nb de pixels par cellule (total) et par groupe de classes
    (counts[nom]). Appelable par bandes → mémoire bornée. codes/gidx : 1D des pixels valides."""
    np.add.at(total, gidx, 1.0)
    for name, group in groups.items():
        sel = gidx[np.isin(codes, list(group))]
        if sel.size:
            np.add.at(counts[name], sel, 1.0)


def fractions_from_counts(total, counts):
    """total/counts (accumulés) → {nom: fraction (n_cells,), NaN si cellule vide}."""
    have = total > 0
    out = {}
    for name, cnt in counts.items():
        frac = np.full(total.shape, np.nan, np.float32)
        frac[have] = (cnt[have] / total[have]).astype(np.float32)
        out[name] = frac
    return out


def foresttype_fractions(codes, gidx, n_cells, groups):
    """Convenience (un seul lot) : accumulate_counts frais + fractions_from_counts. Utilisé
    par les tests ; le bake accumule par bandes."""
    total = np.zeros(n_cells, np.float64)
    counts = {name: np.zeros(n_cells, np.float64) for name in groups}
    accumulate_counts(codes, gidx, total, counts, groups)
    return fractions_from_counts(total, counts)


def cell_rc(lon, lat):
    col = np.round((lon - LON0) / RES).astype(np.int32)
    row = np.round((LAT0 - lat) / RES).astype(np.int32)
    return row, col


def main():
    import rasterio
    from rasterio.windows import from_bounds

    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    targets = {n: CACHE / f"{n}.npy" for n in CLASS_GROUPS}
    if not a.force and all(p.exists() for p in targets.values()):
        print("fteu_*.npy déjà présents (--force pour re-baker).")
        return

    from rasterio.windows import Window

    ncell = GRID_H * GRID_W
    total = np.zeros(ncell, np.float64)
    counts = {name: np.zeros(ncell, np.float64) for name in CLASS_GROUPS}
    print(f"Forêt-type CGLS — lecture fenêtre bbox par bandes depuis {URL[:60]}…", flush=True)
    with rasterio.open(URL) as ds:
        win = from_bounds(BBOX[0], BBOX[2], BBOX[1], BBOX[3], ds.transform)
        row_off, col_off = int(win.row_off), int(win.col_off)
        wh, ww = int(win.height), int(win.width)
        STRIP = 512  # lignes source par bande → mémoire bornée (~ww×STRIP pixels)
        for r0 in range(0, wh, STRIP):
            r1 = min(r0 + STRIP, wh)
            sub = Window(col_off, row_off + r0, ww, r1 - r0)
            arr = ds.read(1, window=sub)  # (r1-r0, ww) uint8, pleine résolution ~100 m
            wt = ds.window_transform(sub)
            lon = wt.c + (np.arange(ww) + 0.5) * wt.a
            lat = wt.f + (np.arange(r1 - r0) + 0.5) * wt.e
            LON, LAT = np.meshgrid(lon, lat)
            row, col = cell_rc(LON.ravel(), LAT.ravel())
            flat = arr.ravel()
            inb = ((row >= 0) & (row < GRID_H) & (col >= 0) & (col < GRID_W) & (flat != NODATA))
            accumulate_counts(flat[inb], row[inb] * GRID_W + col[inb], total, counts, CLASS_GROUPS)
            print(f"  bande {r0}-{r1}/{wh}", flush=True)
    fr = fractions_from_counts(total, counts)
    for name, frac in fr.items():
        np.save(targets[name], frac.reshape(GRID_H, GRID_W))
        finite = np.isfinite(frac)
        print(f"  {name} → {targets[name].name}  couverture {100*finite.mean():.0f}%, "
              f"moyenne {np.nanmean(frac):.3f}", flush=True)
    print("Fait. train_sdm.py reprendra fteu_*.npy (hook).")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4 : Lancer les tests unitaires, vérifier le succès**

Run : `venv/Scripts/python.exe -m pytest tests/test_foresttype_bake.py -q`
Expected : PASS (2 tests).

- [ ] **Step 5 : Bake réel (opérationnel, ~150-200 Mo streamés)**

Run : `PYTHONUTF8=1 venv/Scripts/python.exe scripts/bake_foresttype_eu.py`
Expected : 3 lignes `fteu_broadleaf/needleleaf/mixed → … couverture ~XX%`. Vérifier que les 3 `.npy` existent et ont une couverture non nulle à l'étranger :
```bash
venv/Scripts/python.exe -c "import numpy as np; a=np.load('data/cache/fteu_needleleaf.npy'); r,c=int((51.5-48.0)/0.01),int((7.85+5.5)/0.01); print('Fribourg-DE conifère frac =', a[r,c])"
```
Attendu : une valeur finie > 0 (Forêt-Noire = conifères) — confirme la couverture transfrontière.

- [ ] **Step 6 : Lint + commit**

Run : `venv/Scripts/python.exe -m ruff check tests/test_foresttype_bake.py` → `All checks passed!`
```bash
git add scripts/bake_foresttype_eu.py tests/test_foresttype_bake.py
git commit -m "feat(sdm): bake forêt-type européen (CGLS) → fteu_broadleaf/needleleaf/mixed"
```

---

### Task 2 : Mode `cross_border` de la sélection de variables (`src/sporia/domain/species.py`)

**Files:**
- Modify: `src/sporia/domain/species.py`
- Test: `tests/test_species.py`

**Interfaces:**
- Consumes: `guild_of(latin)` (existant).
- Produces: `habitat_feature_subset(feats, latin, cross_border=False) -> list[str]` — signature étendue (3e paramètre optionnel).

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à `tests/test_species.py` :

```python
_FEATS_FTEU = ["forest_density", "ph", "clim_bio1", "lc_grass", "host_chene", "host_hetre",
               "fteu_broadleaf", "fteu_needleleaf", "fteu_mixed"]


def test_ecto_cross_border_swaps_host_for_fteu():
    out = habitat_feature_subset(_FEATS_FTEU, "Boletus edulis", cross_border=True)
    assert not any(f.startswith("host_") for f in out)          # host fin retiré
    for f in ["fteu_broadleaf", "fteu_needleleaf", "fteu_mixed"]:
        assert f in out                                         # forêt-EU ajoutée
    assert "forest_density" in out and "clim_bio1" in out       # reste inchangé


def test_ecto_fr_only_keeps_host_drops_fteu():
    out = habitat_feature_subset(_FEATS_FTEU, "Boletus edulis", cross_border=False)
    assert "host_chene" in out                                  # host fin gardé
    assert not any(f.startswith("fteu_") for f in out)          # fteu_* exclu


def test_open_ignores_fteu_and_cross_border():
    a = habitat_feature_subset(_FEATS_FTEU, "Calocybe gambosa", cross_border=False)
    b = habitat_feature_subset(_FEATS_FTEU, "Calocybe gambosa", cross_border=True)
    assert a == b                                               # open : cross_border sans effet
    assert not any(f.startswith(("host_", "fteu_")) for f in a)
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `venv/Scripts/python.exe -m pytest tests/test_species.py -q`
Expected : FAIL — `habitat_feature_subset() got an unexpected keyword argument 'cross_border'`.

- [ ] **Step 3 : Étendre `habitat_feature_subset`**

Dans `src/sporia/domain/species.py`, remplacer la fonction par :

```python
def habitat_feature_subset(feats: list[str], latin: str, cross_border: bool = False) -> list[str]:
    """Sous-ensemble de variables d'habitat propre à la guilde (ordre de `feats` préservé).
    'ecto' → jeu complet (host_* fin, sans fteu_*) ; en `cross_border`, host_* fin (France-only)
    est REMPLACÉ par les couches forêt-EU grossières fteu_* (pan-européennes). 'sapro'/'open' →
    host_* retiré ; 'open' → en plus restreint au jeu « milieu ouvert ». fteu_* n'est utilisé
    QUE par les ecto en cross_border."""
    g = guild_of(latin)
    no_fteu = [f for f in feats if not f.startswith("fteu_")]
    if g == "ecto":
        if cross_border:
            base = [f for f in no_fteu if not f.startswith("host_")]
            return base + [f for f in feats if f.startswith("fteu_")]
        return no_fteu
    out = [f for f in no_fteu if not f.startswith("host_")]
    if g == "open":
        out = [f for f in out if _keep_open(f)]
    return out
```

- [ ] **Step 4 : Lancer les tests (nouveaux + non-régression)**

Run : `venv/Scripts/python.exe -m pytest tests/test_species.py -q`
Expected : PASS — dont les tests existants (`test_ecto_keeps_everything` etc. : sans `fteu_*` dans leurs feats, `no_fteu == feats`, comportement inchangé).

- [ ] **Step 5 : Lint + commit**

Run : `venv/Scripts/python.exe -m ruff check src/sporia/domain/species.py`
```bash
git add src/sporia/domain/species.py tests/test_species.py
git commit -m "feat(sdm): habitat_feature_subset(cross_border) — host_* fin remplacé par forêt-EU (ecto)"
```

---

### Task 3 : Amincissement spatial (`src/sporia/domain/sdm_eval.py`)

**Files:**
- Modify: `src/sporia/domain/sdm_eval.py`
- Test: `tests/test_sdm_eval.py`

**Interfaces:**
- Produces: `spatial_thin(rows, cols, max_n, block=25, seed=0) -> tuple[np.ndarray, np.ndarray]` — sous-échantillonne à ≤ `max_n` cellules en préservant l'étalement spatial (round-robin entre blocs).

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à `tests/test_sdm_eval.py` :

```python
from sporia.domain.sdm_eval import spatial_thin


def test_spatial_thin_noop_when_small():
    r = np.arange(10); c = np.arange(10)
    tr, tc = spatial_thin(r, c, max_n=20)
    assert len(tr) == 10 and list(tr) == list(r)


def test_spatial_thin_caps_and_spreads():
    # 4 blocs spatiaux distincts de 25 cellules chacun (100 total)
    rows = np.concatenate([np.full(25, b * 50) for b in range(4)])
    cols = np.concatenate([np.arange(25) for _ in range(4)])
    tr, tc = spatial_thin(rows, cols, max_n=20, block=25)
    assert len(tr) == 20
    blocks_hit = {int(r) // 50 for r in tr}
    assert blocks_hit == {0, 1, 2, 3}  # étalé : les 4 blocs représentés
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `venv/Scripts/python.exe -m pytest tests/test_sdm_eval.py -q`
Expected : FAIL — `ImportError: cannot import name 'spatial_thin'`.

- [ ] **Step 3 : Implémenter `spatial_thin`**

Ajouter à `src/sporia/domain/sdm_eval.py` :

```python
def spatial_thin(rows, cols, max_n: int, block: int = 25, seed: int = 0):
    """Sous-échantillonne (rows, cols) à ≤ max_n cellules en préservant l'étalement spatial :
    regroupe les cellules par bloc de `block`×`block` (~0.25° à 0.01°) puis tire en round-robin
    entre blocs (chaque bloc mélangé). Renvoie (rows, cols) inchangés si len ≤ max_n."""
    from collections import defaultdict

    rows = np.asarray(rows)
    cols = np.asarray(cols)
    if len(rows) <= max_n:
        return rows, cols
    rng = np.random.default_rng(seed)
    buckets = defaultdict(list)
    for i, (r, c) in enumerate(zip(rows // block, cols // block)):
        buckets[(int(r), int(c))].append(i)
    lists = [rng.permutation(v).tolist() for v in buckets.values()]
    order = []
    while len(order) < max_n and any(lists):
        for lst in lists:
            if lst:
                order.append(lst.pop())
                if len(order) >= max_n:
                    break
        lists = [lst for lst in lists if lst]
    idx = np.array(order[:max_n], int)
    return rows[idx], cols[idx]
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run : `venv/Scripts/python.exe -m pytest tests/test_sdm_eval.py -q`
Expected : PASS.

- [ ] **Step 5 : Lint + commit**

Run : `venv/Scripts/python.exe -m ruff check src/sporia/domain/sdm_eval.py`
```bash
git add src/sporia/domain/sdm_eval.py tests/test_sdm_eval.py
git commit -m "feat(sdm): spatial_thin — amincissement spatial des présences (cap d'équilibrage)"
```

---

### Task 4 : Machinerie `--cross-border` + cap (`scripts/train_sdm.py`)

**Files:**
- Modify: `scripts/train_sdm.py`

**Interfaces:**
- Consumes: `habitat_feature_subset(feats, latin, cross_border)` (Task 2), `spatial_thin(...)` (Task 3).
- Produces: flags CLI `--cross-border`, `--max-pres N` ; `fetch_occurrences(..., country="FR")` param.

- [ ] **Step 1 : `fetch_occurrences` — paramètre `country`**

Dans `scripts/train_sdm.py`, modifier la signature et la construction des params GBIF :

```python
def fetch_occurrences(taxon_key, max_n=20000, min_year=2000, max_unc=5000, label=None, country="FR"):
    lons, lats, off, total = [], [], 0, None
    while off < max_n:
        params = {"taxonKey": taxon_key, "hasCoordinate": "true",
                  "hasGeospatialIssue": "false", "limit": 300, "offset": off}
        if country:
            params["country"] = country
        j = requests.get(GBIF_OCC, params=params, timeout=60).json()
        ...
```
(le reste inchangé : le filtre bbox `if BBOX[0] <= lo <= BBOX[1] and BBOX[2] <= la <= BBOX[3]` restreint déjà au domaine baké).

- [ ] **Step 2 : `load_layers` — hook `fteu_*.npy`**

Dans `load_layers`, à côté des hooks `lc_*`/`host_*`, ajouter le chargement des `fteu_*.npy` :

```python
    for f in sorted(Path("data/cache").glob("fteu_*.npy")):       # hook forêt-type européen
        try:
            arr = np.load(f)
            if arr.shape == (GRID_H, GRID_W):
                layers[f.stem] = arr.astype(np.float32)
                feats.append(f.stem)
                print(f"  + couche forêt-EU {f.stem}")
        except Exception:
            pass
```

- [ ] **Step 3 : `species_feats`, `build_background`, `run_one`, `main` — câblage `--cross-border`/`--max-pres`**

- `species_feats(feats, species, cross_border=False)` : `return habitat_feature_subset(feats, species, cross_border)`.
- `build_background(layers, feats, france, mode, n_bg, country="FR")` : passer `country` à `fetch_occurrences(FUNGI_KINGDOM_KEY, ..., country=country)` ; quand `country is None`, utiliser le cache `_BG_CACHE_XB = Path("data/cache")/"sdm_bg_target_xborder_cells.npy"` au lieu de `_BG_CACHE`.
- `run_one(species, layers, feats, france, bg, predict, repeats=25, cross_border=False, max_pres=None, verbose=True)` :
  - `sfeats = species_feats(feats, species, cross_border)`
  - présences : `fetch_occurrences(match_key(species), country=None if cross_border else "FR")`
  - filtre : `okp = np.isfinite(Xp).all(axis=1)` ; `if not cross_border: okp &= france[np.clip(pr,0,GRID_H-1), np.clip(pc,0,GRID_W-1)]`
  - après `pr,pc,Xp = pr[okp],pc[okp],Xp[okp]`, si `max_pres` : `pr, pc = spatial_thin(pr, pc, max_pres)` puis re-`sample` `Xp = sample(layers, sfeats, pr, pc)` (ou thinner avant sample). Importer `from sporia.domain.sdm_eval import spatial_thin`.
- `main` : `ap.add_argument("--cross-border", action="store_true")` ; `ap.add_argument("--max-pres", type=int, default=None, help="cap d'équilibrage spatial des présences")` ; construire `bg` avec `country=None if a.cross_border else "FR"` ; passer `cross_border=a.cross_border, max_pres=a.max_pres` aux appels `run_one`.

- [ ] **Step 4 : Smoke (le filtre pays est bien levé)**

Run :
```bash
PYTHONUTF8=1 venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'scripts'); import train_sdm as t; k=t.match_key('Calocybe gambosa'); \
fr=len(t.fetch_occurrences(k, max_n=2000, country='FR')[0]); xb=len(t.fetch_occurrences(k, max_n=2000, country=None)[0]); \
print('FR', fr, 'bbox tous-pays', xb, 'OK' if xb>fr else 'ECHEC')"
```
Expected : `bbox tous-pays` nettement > `FR`, `OK`.

- [ ] **Step 5 : Lint (pas de NOUVELLE erreur) + commit**

Run : `venv/Scripts/python.exe -m ruff check scripts/train_sdm.py` (comparer le compte à avant ; pas de nouvelle).
```bash
git add scripts/train_sdm.py
git commit -m "feat(sdm): --cross-border (fetch tous-pays, fond transfrontalier) + --max-pres (cap spatial)"
```

---

### Task 5 : Courbe N + A/B par espèce (opérationnel)

Tâche **opérationnelle** (pas de TDD) : nécessite Tasks 1-4 + le bake réel (Task 1 Step 5). Aucune modif de code. Utilise le Boyce STABILISÉ (chantier précédent).

**Files:**
- Produces (régénérés) : `data/cache/sdm_*.npy`, `data/cache/_retrain_sdm.log`
- Modify : `src/sporia/data/species_metrics.yaml` (ré-émis)

- [ ] **Step 1 : Sauvegardes**

```bash
mkdir -p data/cache/_sdm_backup_pre_xborder
cp -n data/cache/sdm_*.npy data/cache/_sdm_backup_pre_xborder/
cp src/sporia/data/species_metrics.yaml src/sporia/data/species_metrics.yaml.bak_pre_xborder
```

- [ ] **Step 2 : Courbe d'apprentissage → fixer N**

Sur une espèce riche (Macrolepiota, ~17k in-bbox), mesurer le Boyce stable à plusieurs N :
```bash
for N in 500 1000 2000 4000; do
  PYTHONUTF8=1 venv/Scripts/python.exe scripts/train_sdm.py "Macrolepiota procera" --cross-border --repeats 25 --max-pres $N 2>&1 | grep -E "présence=|Boyce"
done
```
Repérer le **plateau du Boyce stable** (là où `Boyce ± BoyceSE` cesse de monter au-delà de la SE). Fixer `N_STAR` à cette valeur (pari 1000-2000). Documenter les 4 points.

- [ ] **Step 3 : A/B par espèce (garde-le-meilleur)**

Pour chaque espèce cible (les 4 sans-hôte + les ecto), entraîner en transfrontalier et comparer au FR-only committé :
```bash
PYTHONUTF8=1 venv/Scripts/python.exe scripts/train_sdm.py --all --predict --cross-border --repeats 25 --max-pres <N_STAR> > data/cache/_retrain_sdm.log 2>&1
```
Puis, par espèce, comparer le `Boyce ± BoyceSE` du log transfrontalier à la valeur FR-only de `species_metrics.yaml.bak_pre_xborder`. **Règle garde-le-meilleur** : si `(boyce_xb − se_xb) > (boyce_fr − se_fr)`, garder la carte transfrontalière ; sinon restaurer `sdm_<latin>.npy` depuis `_sdm_backup_pre_xborder`. Consigner le verdict + le gain de présences par espèce.

- [ ] **Step 4 : Ré-émettre les métriques (des cartes retenues)**

Reconstruire un log récap ne contenant que les valeurs retenues par espèce (transfrontalier OU FR-only), puis :
```bash
PYTHONUTF8=1 venv/Scripts/python.exe scripts/report_metrics.py --emit-yaml
```
Vérifier `boyce`/`auc`/`boyce_se` à jour et `fruiting_*`/`radar_*` préservés. Cas d'intérêt : **Calocybe** franchit-elle `(boyce − se) ≥ 0.10` (redevient servie) ?

- [ ] **Step 5 : Commit des métriques**

```bash
git add src/sporia/data/species_metrics.yaml
git commit -m "chore(sdm): métriques après transfrontalier (A/B garde-le-meilleur par espèce)"
```

---

## Validation finale (après les 5 tasks)

- `venv/Scripts/python.exe -m pytest -q` : toute la suite passe.
- `data/cache/fteu_*.npy` existent et couvrent l'étranger.
- Par espèce, la carte servie est la meilleure des deux (FR-fin vs transfrontalier-grossier) au Boyce stable ; la prédiction reste France seule.
- Verdict documenté : quelles ecto gagnent avec l'hôte grossier + données ; Calocybe est-elle servie.
