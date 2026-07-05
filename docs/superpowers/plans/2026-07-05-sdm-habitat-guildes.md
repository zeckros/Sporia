# SDM habitat par guilde — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner aux 3 espèces d'habitat ouvert (Calocybe, Agaricus, Macrolepiota) un jeu de variables d'habitat restreint et pertinent, pour réduire leur sur-apprentissage et améliorer leur SDM, sans toucher aux autres espèces.

**Architecture:** Un champ déclaratif `guild` dans `species.yaml` (ecto/open/sapro). La logique pure « guilde → sous-ensemble de variables » vit dans `sporia.domain.species` (importable, testée). `scripts/train_sdm.py` délègue à cette logique (remplace le set codé en dur `NO_HOST`). Le fond target-group et le RandomForest sont inchangés ; seule la sélection de variables change, et seulement pour la guilde `open`.

**Tech Stack:** Python 3.13, scikit-learn (RandomForest), PyYAML, pytest, ruff.

## Global Constraints

- Interpréteur : `venv/Scripts/python.exe` ; toutes les commandes se lancent depuis la racine du repo.
- Lint : `ruff` doit passer sur les fichiers `src/` modifiés (config : `select = ["E","F","I","UP","B"]`, `line-length = 100`).
- Tests : `pytest` ; les tests n'utilisent QUE des données synthétiques (pas le dossier `data/`), cf. `tests/conftest.py`.
- Commits : **sans** ligne `Co-Authored-By` (préférence utilisateur). Commits fréquents, une petite étape verte à la fois.
- Comportement inchangé pour les guildes `ecto` et `sapro` : seule `open` reçoit le jeu restreint. Défaut `ecto` si le champ `guild` manque (non-régression).

---

### Task 1 : Champ `guild` dans species.yaml + `guild_of()`

**Files:**
- Modify: `src/sporia/data/species.yaml` (ajouter `guild` aux 14 entrées)
- Modify: `src/sporia/domain/species.py` (ajouter `guild_of` + constantes)
- Test: `tests/test_species.py`

**Interfaces:**
- Produces: `guild_of(latin: str) -> str` (valeurs `"ecto" | "open" | "sapro"`, défaut `"ecto"`).

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à la fin de `tests/test_species.py` :

```python
from sporia.domain.species import guild_of

_OPEN = ["Calocybe gambosa", "Agaricus campestris", "Macrolepiota procera"]


def test_guild_assignments():
    assert guild_of("Boletus edulis") == "ecto"
    for sp in _OPEN:
        assert guild_of(sp) == "open"
    assert guild_of("Pleurotus ostreatus") == "sapro"


def test_guild_default_unknown():
    assert guild_of("Inconnu inconnu") == "ecto"


def test_every_species_has_guild():
    for m in MUSHROOMS:
        assert m.get("guild") in {"ecto", "open", "sapro"}, m["latin"]
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run : `venv/Scripts/python.exe -m pytest tests/test_species.py -q`
Expected : FAIL — `ImportError: cannot import name 'guild_of'` (et/ou `test_every_species_has_guild` KO).

- [ ] **Step 3 : Ajouter le champ `guild` aux 14 espèces de `species.yaml`**

Dans chaque entrée de `src/sporia/data/species.yaml`, insérer `guild: "<valeur>"` (par ex. juste après `color`). Valeurs :

- `open` : `Calocybe gambosa`, `Agaricus campestris`, `Macrolepiota procera`.
- `sapro` : `Pleurotus ostreatus`.
- `ecto` : les 10 autres (`Morchella esculenta`, `Boletus aereus`, `Cantharellus cibarius`, `Boletus edulis`, `Craterellus cornucopioides`, `Craterellus tubaeformis`, `Hydnum repandum`, `Lactarius deliciosus`, `Imleria badia`, `Lepista nuda`).

Exemple (Calocybe) :

```yaml
- {nom: "Mousseron de la St-Georges", latin: "Calocybe gambosa", color: "#ca8a04", guild: "open", months: [4,5], t_min: 10, t_max: 17, rain_lag: [4,12], rain_min: 12, ph_opt: [6.3,7.8], soil_pref: "Sols neutres à calcaires", habitat: "Prés, lisières, ronds de sorcière (« mousseron de printemps »)"}
```

- [ ] **Step 4 : Ajouter `guild_of` dans `src/sporia/domain/species.py`**

Après la ligne `MUSHROOMS: list[dict] = _load()`, ajouter :

```python
_GUILD_DEFAULT = "ecto"


def guild_of(latin: str) -> str:
    """Guilde de l'espèce ('ecto' | 'open' | 'sapro'), 'ecto' par défaut si absente
    (rétrocompatibilité : une espèce sans champ `guild` garde le comportement complet)."""
    for m in MUSHROOMS:
        if m["latin"] == latin:
            return m.get("guild", _GUILD_DEFAULT)
    return _GUILD_DEFAULT
```

- [ ] **Step 5 : Lancer les tests, vérifier le succès**

Run : `venv/Scripts/python.exe -m pytest tests/test_species.py -q`
Expected : PASS (dont `test_species_count` toujours à 14).

- [ ] **Step 6 : Lint**

Run : `venv/Scripts/python.exe -m ruff check src/sporia/domain/species.py`
Expected : `All checks passed!`

- [ ] **Step 7 : Commit**

```bash
git add src/sporia/data/species.yaml src/sporia/domain/species.py tests/test_species.py
git commit -m "feat(sdm): champ guild par espèce + guild_of()"
```

---

### Task 2 : `habitat_feature_subset()` — sélection de variables par guilde

**Files:**
- Modify: `src/sporia/domain/species.py`
- Test: `tests/test_species.py`

**Interfaces:**
- Consumes: `guild_of(latin)` (Task 1).
- Produces: `habitat_feature_subset(feats: list[str], latin: str) -> list[str]` — sous-liste de `feats` (ordre préservé) selon la guilde.

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à `tests/test_species.py` :

```python
from sporia.domain.species import habitat_feature_subset

_FEATS = ["forest_density", "ph", "clay", "sand", "silt", "altitude", "slope",
          "northness", "twi", "tpi", "dist_water", "slope_dem", "soc", "cec",
          "edge_density", "clim_bio1", "lc_grass", "lc_tree",
          "host_chene", "host_hetre"]


def test_ecto_keeps_everything():
    assert habitat_feature_subset(_FEATS, "Boletus edulis") == _FEATS


def test_sapro_drops_host_only():
    out = habitat_feature_subset(_FEATS, "Pleurotus ostreatus")
    assert "forest_density" in out                      # structure forestière conservée
    assert not any(f.startswith("host_") for f in out)  # host_* retiré


def test_open_lean_set():
    out = habitat_feature_subset(_FEATS, "Calocybe gambosa")
    for f in ["forest_density", "twi", "tpi", "slope_dem", "edge_density",
              "host_chene", "host_hetre"]:
        assert f not in out, f
    for f in ["ph", "clay", "sand", "silt", "soc", "cec", "dist_water",
              "altitude", "slope", "northness", "clim_bio1", "lc_grass", "lc_tree"]:
        assert f in out, f


def test_open_preserves_order():
    out = habitat_feature_subset(_FEATS, "Agaricus campestris")
    assert out == [f for f in _FEATS if f in out]
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run : `venv/Scripts/python.exe -m pytest tests/test_species.py -q`
Expected : FAIL — `ImportError: cannot import name 'habitat_feature_subset'`.

- [ ] **Step 3 : Implémenter `habitat_feature_subset` dans `domain/species.py`**

Ajouter après `guild_of` :

```python
# Variables conservées pour la guilde « open » (en plus de tout `lc_*` et `clim_*`).
# Retire implicitement forest_density, host_*, edge_density, twi, tpi, slope_dem, lat/lon :
# structure et hydrologie forestières = bruit + sur-apprentissage pour une prairie.
_OPEN_HABITAT_KEEP = frozenset({
    "ph", "clay", "sand", "silt",        # texture du sol
    "soc", "cec",                         # fertilité
    "dist_water",                         # humidité (proximité de l'eau)
    "altitude", "slope", "northness",     # relief
})


def _keep_open(feat: str) -> bool:
    return feat in _OPEN_HABITAT_KEEP or feat.startswith("lc_") or feat.startswith("clim_")


def habitat_feature_subset(feats: list[str], latin: str) -> list[str]:
    """Sous-ensemble de variables d'habitat propre à la guilde (ordre de `feats` préservé).
    'ecto' → jeu complet. 'sapro'/'open' → host_* retiré. 'open' → en plus, restreint au
    jeu « milieu ouvert » (_keep_open)."""
    g = guild_of(latin)
    if g == "ecto":
        return list(feats)
    out = [f for f in feats if not f.startswith("host_")]
    if g == "open":
        out = [f for f in out if _keep_open(f)]
    return out
```

- [ ] **Step 4 : Lancer les tests, vérifier le succès**

Run : `venv/Scripts/python.exe -m pytest tests/test_species.py -q`
Expected : PASS.

- [ ] **Step 5 : Lint**

Run : `venv/Scripts/python.exe -m ruff check src/sporia/domain/species.py`
Expected : `All checks passed!`

- [ ] **Step 6 : Commit**

```bash
git add src/sporia/domain/species.py tests/test_species.py
git commit -m "feat(sdm): habitat_feature_subset() — jeu de variables par guilde"
```

---

### Task 3 : Câbler `train_sdm.py` sur la logique de domaine

**Files:**
- Modify: `scripts/train_sdm.py` (import + `species_feats` délègue ; suppression de `NO_HOST`)

**Interfaces:**
- Consumes: `habitat_feature_subset(feats, latin)` (Task 2).
- Produces: `species_feats(feats, species)` inchangé en signature (appelé par `run_one`), délègue désormais au domaine.

- [ ] **Step 1 : Ajouter l'import du domaine**

Dans `scripts/train_sdm.py`, à côté des autres imports `from sporia...` (vers la ligne 34-37), ajouter :

```python
from sporia.domain.species import habitat_feature_subset  # noqa: E402
```

- [ ] **Step 2 : Remplacer `NO_HOST` + `species_feats`**

Supprimer le bloc `NO_HOST = { ... }` (avec son commentaire d'en-tête « Variables PAR GUILDE… ») et remplacer la fonction `species_feats` par :

```python
def species_feats(feats, species):
    """Sous-ensemble de variables propre à la guilde de l'espèce (cf. domain.species —
    'open' reçoit un jeu restreint « milieu ouvert », 'sapro'/'open' perdent host_*)."""
    return habitat_feature_subset(feats, species)
```

- [ ] **Step 3 : Smoke test — le script délègue bien**

Run :
```bash
venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'scripts'); import train_sdm as t; \
feats=['forest_density','ph','clim_bio1','lc_grass','host_chene']; \
print('open :', t.species_feats(feats,'Calocybe gambosa')); \
print('ecto :', t.species_feats(feats,'Boletus edulis'))"
```
Expected :
```
open : ['ph', 'clim_bio1', 'lc_grass']
ecto : ['forest_density', 'ph', 'clim_bio1', 'lc_grass', 'host_chene']
```

- [ ] **Step 4 : Lint**

Run : `venv/Scripts/python.exe -m ruff check scripts/train_sdm.py`
Expected : `All checks passed!` (ou uniquement des avertissements préexistants sans rapport ; ne PAS introduire de nouvelle erreur).

- [ ] **Step 5 : Commit**

```bash
git add scripts/train_sdm.py
git commit -m "refactor(sdm): species_feats délègue à la logique de guilde du domaine"
```

---

### Task 4 : Réentraînement + validation des 3 espèces `open`

Tâche **opérationnelle** (pas de TDD : c'est un entraînement + comparaison de métriques sur données réelles ; le SDM n'utilise que GBIF + couches statiques, **aucun quota météo d'archive**).

**Files:**
- Produces (régénérés) : `data/cache/sdm_*.npy`, `data/cache/_retrain_sdm.log`
- Modify : `src/sporia/data/species_metrics.yaml` (ré-émis)

- [ ] **Step 1 : Sauvegarder les cartes SDM actuelles (réversibilité)**

```bash
mkdir -p data/cache/_sdm_backup_pre_guild
cp -n data/cache/sdm_*.npy data/cache/_sdm_backup_pre_guild/
```

- [ ] **Step 2 : Noter le Boyce AVANT (référence)**

Les valeurs de référence (dernier retrain) : Calocybe **−0.19**, Agaricus **0.32**, Macrolepiota **0.40** (source : `src/sporia/data/species_metrics.yaml`). Les garder sous les yeux pour la comparaison.

- [ ] **Step 3 : Réentraîner tout le SDM (régénère aussi le log de récap)**

Run :
```bash
PYTHONUTF8=1 venv/Scripts/python.exe scripts/train_sdm.py --all --predict > data/cache/_retrain_sdm.log 2>&1; echo "EXIT=$?"
```
Note : `--all` régénère les 13 cartes ; les `ecto`/`sapro` sont déterministes (RandomForest `random_state=0`, fond target-group en cache) → inchangées. Seules les 3 `open` changent.

- [ ] **Step 4 : Lire le Boyce APRÈS et comparer**

Run :
```bash
grep -A2 -E "Calocybe|Agaricus campestris|Macrolepiota" data/cache/_retrain_sdm.log | grep -E "Boyce|présence"
```
Critères d'acceptation :
- **Calocybe** : Boyce **≥ 0.10** (cible : redevient servie ; départ −0.19).
- **Agaricus / Macrolepiota** : Boyce **≥** la valeur de départ (0.32 / 0.40).
- Si une espèce ne franchit pas 0.10, c'est un résultat **acceptable et honnête** : `is_reliable_habitat` la laisse non-servie et `confidence_tier` l'étiquette « modérée ». Documenter la valeur obtenue ; ne PAS forcer.

- [ ] **Step 5 : Ré-émettre les métriques**

Run :
```bash
PYTHONUTF8=1 venv/Scripts/python.exe scripts/report_metrics.py --emit-yaml
```
Vérifier que `src/sporia/data/species_metrics.yaml` contient les nouveaux Boyce des 3 espèces et **conserve** les clés `fruiting_*`/`radar_*`.

Prérequis : `report_metrics.emit_yaml` doit être en version **fusion-préservante** (elle relit le YAML existant et ne réécrit que `boyce`/`auc`, en gardant `fruiting_*`/`radar_*`). Cette version est déjà présente dans l'arbre de travail (issue du chantier « quand »). Si ce n'est pas le cas, ne pas lancer l'émission telle quelle : elle écraserait les métriques de fructification.

- [ ] **Step 6 : Vérifier la non-régression des `ecto`**

Run :
```bash
grep -E "Boletus edulis|Cantharellus|Imleria" data/cache/_retrain_sdm.log | grep Boyce
```
Expected : Boyce des ecto ~identiques aux valeurs connues (Imleria ~0.73, Cantharellus ~0.55, Boletus edulis ~0.39). Un écart notable signalerait un effet de bord à investiguer.

- [ ] **Step 7 : Commit**

```bash
git add src/sporia/data/species_metrics.yaml
git commit -m "chore(sdm): métriques habitat réémises après jeu de variables par guilde"
```

Note : les `sdm_*.npy` et logs sont dans `data/cache/` (non versionné) — le déploiement de ces cartes vers la prod se fait par le processus habituel (scp), hors périmètre de ce plan.

---

## Notes de validation finale (après les 4 tasks)

- `venv/Scripts/python.exe -m pytest -q` : toute la suite passe.
- La suite existante `tests/test_served_species.py` / `tests/test_metrics.py` reflète `is_reliable_habitat` — si Calocybe passe le seuil, elle devient servie (comportement attendu, pas une régression).
