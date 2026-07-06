# Stabilisation de la métrique Boyce du SDM — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre le Boyce du SDM fiable (moyenne sur CV répétée + Boyce continu + erreur-type) et l'utiliser pour un gating de service prudent (boyce − erreur-type).

**Architecture:** Les fonctions pures d'évaluation (Boyce continu, CV répétée) vont dans un module importable `sporia.domain.sdm_eval` (testable comme le reste du domaine) ; `scripts/train_sdm.py` les importe et remplace sa boucle CV. `report_metrics.py` propage l'erreur-type jusqu'à `species_metrics.yaml`. `domain/metrics.py` gate sur la borne prudente. Puis une ré-estimation opérationnelle re-valide le chantier guilde.

**Tech Stack:** Python 3.13, numpy, scipy (spearmanr), scikit-learn (RandomForest), PyYAML, pytest, ruff.

## Global Constraints

- Interpréteur `venv/Scripts/python.exe` ; commandes depuis la racine du repo.
- ruff doit passer sur les fichiers `src/` modifiés (`select = ["E","F","I","UP","B"]`, `line-length = 100`) ; `scripts/` porte du lint préexistant (ne pas ajouter de NOUVELLE erreur).
- pytest ; tests sur données synthétiques uniquement.
- Commits **sans** ligne `Co-Authored-By`.
- Rétrocompat obligatoire : `boyce_se` absent d'une entrée `species_metrics.yaml` ⇒ borne prudente = `boyce` ⇒ gating identique à aujourd'hui (les tests existants de `tests/test_metrics.py` doivent rester verts).
- Imports lourds (scipy, sklearn) faits DANS les fonctions de `sdm_eval` (pas au niveau module), pour qu'`import sporia` reste léger.

---

### Task 1 : Boyce continu (`sporia.domain.sdm_eval`)

**Files:**
- Create: `src/sporia/domain/sdm_eval.py`
- Test: `tests/test_sdm_eval.py`

**Interfaces:**
- Produces: `boyce_index_continuous(pres, bg, window=0.1, res=100) -> float` (nan si < 3 fenêtres exploitables).

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `tests/test_sdm_eval.py` :

```python
"""Métriques d'évaluation SDM : Boyce continu (fenêtre glissante) + CV répétée."""

from __future__ import annotations

import numpy as np

from sporia.domain.sdm_eval import boyce_index_continuous


def test_continuous_boyce_perfect_separation():
    rng = np.random.default_rng(0)
    pres = np.clip(rng.normal(0.75, 0.12, 500), 0, 1)
    bg = np.clip(rng.normal(0.25, 0.12, 500), 0, 1)
    assert boyce_index_continuous(pres, bg) > 0.8


def test_continuous_boyce_no_separation():
    rng = np.random.default_rng(1)
    same = lambda: np.clip(rng.normal(0.5, 0.15, 500), 0, 1)
    val = boyce_index_continuous(same(), same())
    assert np.isnan(val) or abs(val) < 0.5


def test_continuous_boyce_empty_returns_nan():
    assert np.isnan(boyce_index_continuous(np.array([]), np.array([0.5])))
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `venv/Scripts/python.exe -m pytest tests/test_sdm_eval.py -q`
Expected : FAIL — `ModuleNotFoundError: No module named 'sporia.domain.sdm_eval'`.

- [ ] **Step 3 : Implémenter `boyce_index_continuous`**

Créer `src/sporia/domain/sdm_eval.py` :

```python
"""Métriques d'évaluation du SDM d'habitat, pures et testables (utilisées par
scripts/train_sdm.py). Les dépendances lourdes (scipy, scikit-learn) sont importées
DANS les fonctions pour garder `import sporia` léger."""

from __future__ import annotations

import numpy as np


def boyce_index_continuous(pres, bg, window: float = 0.1, res: int = 100) -> float:
    """Indice de Boyce CONTINU (Hirzel 2006) : une fenêtre de largeur `window` (fraction
    de [0,1]) glisse sur `res` positions ; pour chacune, ratio P/E = (part des présences
    dans la fenêtre) / (part du fond dans la fenêtre) ; l'indice est la corrélation de
    Spearman entre le centre des fenêtres et le ratio, sur les fenêtres où le fond est
    présent. Moins sensible au découpage que la version à casiers fixes. nan si < 3
    fenêtres exploitables ou entrée vide."""
    from scipy.stats import spearmanr

    pres = np.asarray(pres, float)
    bg = np.asarray(bg, float)
    pres = pres[np.isfinite(pres)]
    bg = bg[np.isfinite(bg)]
    if len(pres) == 0 or len(bg) == 0:
        return float("nan")
    half = window / 2.0
    centers = np.linspace(half, 1.0 - half, res)
    mids, ratios = [], []
    for c in centers:
        lo, hi = c - half, c + half
        P = float(np.mean((pres >= lo) & (pres <= hi)))
        E = float(np.mean((bg >= lo) & (bg <= hi)))
        if E > 0:
            mids.append(c)
            ratios.append(P / E)
    if len(ratios) < 3:
        return float("nan")
    return float(spearmanr(mids, ratios).correlation)
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run : `venv/Scripts/python.exe -m pytest tests/test_sdm_eval.py -q`
Expected : PASS (3 tests).

- [ ] **Step 5 : Lint**

Run : `venv/Scripts/python.exe -m ruff check src/sporia/domain/sdm_eval.py tests/test_sdm_eval.py`
Expected : `All checks passed!`

- [ ] **Step 6 : Commit**

```bash
git add src/sporia/domain/sdm_eval.py tests/test_sdm_eval.py
git commit -m "feat(sdm): boyce_index_continuous (Boyce à fenêtre glissante)"
```

---

### Task 2 : CV répétée (`sporia.domain.sdm_eval`)

**Files:**
- Modify: `src/sporia/domain/sdm_eval.py`
- Test: `tests/test_sdm_eval.py`

**Interfaces:**
- Consumes: `boyce_index_continuous` (Task 1).
- Produces: `repeated_cv_metrics(X, y, groups, repeats=25, k=5, n_estimators=200, seed=0) -> tuple[float, float, float]` renvoyant `(auc_mean, boyce_mean, boyce_se)`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à `tests/test_sdm_eval.py` :

```python
from sporia.domain.sdm_eval import repeated_cv_metrics


def _separable_dataset(n_groups=40, per_group=20, seed=0):
    rng = np.random.default_rng(seed)
    X, y, g = [], [], []
    for gi in range(n_groups):
        pos = gi % 2  # la moitié des blocs "présence", l'autre "fond"
        for _ in range(per_group):
            center = 0.7 if pos else 0.3
            X.append([rng.normal(center, 0.2), rng.normal(center, 0.2)])
            y.append(pos)
            g.append(gi)
    return np.array(X), np.array(y), np.array(g)


def test_repeated_cv_returns_three_finite_floats():
    X, y, g = _separable_dataset()
    auc, boyce, se = repeated_cv_metrics(X, y, g, repeats=6, n_estimators=60)
    assert np.isfinite(auc) and np.isfinite(boyce) and np.isfinite(se)
    assert auc > 0.7  # données clairement séparables


def test_repeated_cv_is_deterministic():
    X, y, g = _separable_dataset()
    a = repeated_cv_metrics(X, y, g, repeats=6, n_estimators=60)
    b = repeated_cv_metrics(X, y, g, repeats=6, n_estimators=60)
    assert a == b


def test_repeated_cv_se_shrinks_with_more_repeats():
    X, y, g = _separable_dataset(n_groups=60)
    _, _, se_few = repeated_cv_metrics(X, y, g, repeats=4, n_estimators=60)
    _, _, se_many = repeated_cv_metrics(X, y, g, repeats=40, n_estimators=60)
    assert se_many < se_few
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `venv/Scripts/python.exe -m pytest tests/test_sdm_eval.py -q`
Expected : FAIL — `ImportError: cannot import name 'repeated_cv_metrics'`.

- [ ] **Step 3 : Implémenter `repeated_cv_metrics`**

Ajouter à `src/sporia/domain/sdm_eval.py` :

```python
def repeated_cv_metrics(X, y, groups, repeats: int = 25, k: int = 5,
                        n_estimators: int = 200, seed: int = 0):
    """Métriques de CV spatiale STABILISÉES. Répète `repeats` fois : assigne
    aléatoirement chaque groupe (bloc spatial) à l'un des `k` folds ; par fold, entraîne
    un RandomForest et mesure AUC + Boyce continu ; moyenne sur les folds → un couple
    (auc, boyce) par répétition. Renvoie (auc_mean, boyce_mean, boyce_se) où
    boyce_se = std(boyce_par_répétition) / sqrt(nb de répétitions). Déterministe à `seed`
    fixe. NaN si aucune répétition exploitable."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import roc_auc_score

    X = np.asarray(X, float)
    y = np.asarray(y)
    groups = np.asarray(groups)
    uniq = np.unique(groups)
    aucs_rep, boyce_rep = [], []
    for rep in range(repeats):
        rng = np.random.default_rng(seed + rep)
        fold_of = {int(g): int(rng.integers(k)) for g in uniq}
        fold = np.array([fold_of[int(g)] for g in groups])
        aucs, boyces = [], []
        for f in range(k):
            te = fold == f
            tr = ~te
            if te.sum() == 0 or tr.sum() == 0 or len(np.unique(y[tr])) < 2:
                continue
            clf = RandomForestClassifier(
                n_estimators=n_estimators, min_samples_leaf=3, n_jobs=-1,
                class_weight="balanced_subsample", random_state=0,
            ).fit(X[tr], y[tr])
            p = clf.predict_proba(X[te])[:, 1]
            if len(np.unique(y[te])) == 2:
                aucs.append(roc_auc_score(y[te], p))
            boyces.append(boyce_index_continuous(p[y[te] == 1], p[y[te] == 0]))
        if aucs:
            aucs_rep.append(float(np.nanmean(aucs)))
        if boyces:
            boyce_rep.append(float(np.nanmean(boyces)))
    auc_mean = float(np.nanmean(aucs_rep)) if aucs_rep else float("nan")
    boyce_mean = float(np.nanmean(boyce_rep)) if boyce_rep else float("nan")
    boyce_se = (float(np.nanstd(boyce_rep) / np.sqrt(len(boyce_rep)))
                if len(boyce_rep) > 1 else float("nan"))
    return auc_mean, boyce_mean, boyce_se
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run : `venv/Scripts/python.exe -m pytest tests/test_sdm_eval.py -q`
Expected : PASS (6 tests). Si `test_repeated_cv_se_shrinks_with_more_repeats` est instable, augmenter `n_groups` — l'effet √n exige assez de blocs.

- [ ] **Step 5 : Lint**

Run : `venv/Scripts/python.exe -m ruff check src/sporia/domain/sdm_eval.py tests/test_sdm_eval.py`
Expected : `All checks passed!`

- [ ] **Step 6 : Commit**

```bash
git add src/sporia/domain/sdm_eval.py tests/test_sdm_eval.py
git commit -m "feat(sdm): repeated_cv_metrics (CV répétée, moyenne + erreur-type)"
```

---

### Task 3 : Gating prudent (`src/sporia/domain/metrics.py`)

**Files:**
- Modify: `src/sporia/domain/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Produces (pur, testable) : `_conservative(boyce, boyce_se) -> float` (= `boyce - boyce_se`), `_tier(lower) -> str`. `is_reliable_habitat` et `confidence_tier` inchangés en signature, gating désormais sur la borne prudente.

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter à `tests/test_metrics.py` :

```python
from sporia.domain.metrics import _conservative, _tier


def test_conservative_bound():
    assert _conservative(0.50, 0.03) == 0.47
    assert _conservative(0.12, 0.05) == 0.07


def test_tier_thresholds_on_lower_bound():
    assert _tier(0.55) == "élevée"    # >= 0.50
    assert _tier(0.47) == "bonne"     # >= 0.35, < 0.50
    assert _tier(0.20) == "modérée"   # < 0.35
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `venv/Scripts/python.exe -m pytest tests/test_metrics.py -q`
Expected : FAIL — `ImportError: cannot import name '_conservative'`.

- [ ] **Step 3 : Réécrire `metrics.py` avec la borne prudente**

Remplacer le corps de `src/sporia/domain/metrics.py` par (en gardant l'en-tête de module) :

```python
from functools import lru_cache
from importlib import resources

import yaml

DEFAULT_THRESHOLD = 0.10


@lru_cache(maxsize=1)
def _habitat_raw() -> dict[str, dict]:
    src = resources.files("sporia").joinpath("data", "species_metrics.yaml")
    with src.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return {sp: v for sp, v in raw.items() if isinstance(v, dict) and "boyce" in v}


def habitat_boyce() -> dict[str, float]:
    """Boyce moyen par espèce (rétrocompat : consommé par les tests / autres appelants)."""
    return {sp: float(v["boyce"]) for sp, v in _habitat_raw().items()}


def _conservative(boyce: float, boyce_se: float) -> float:
    """Borne prudente = boyce − erreur-type."""
    return float(boyce) - float(boyce_se)


def _tier(lower: float) -> str:
    if lower >= 0.50:
        return "élevée"
    if lower >= 0.35:
        return "bonne"
    return "modérée"


def _lower_bound(latin: str) -> float | None:
    """Borne prudente de l'espèce (None si absente ; boyce_se manquant → 0)."""
    v = _habitat_raw().get(latin)
    if v is None:
        return None
    return _conservative(float(v["boyce"]), float(v.get("boyce_se", 0.0)))


def is_reliable_habitat(latin: str, threshold: float = DEFAULT_THRESHOLD) -> bool:
    """True si (boyce − erreur-type) >= seuil. Absent → False."""
    lb = _lower_bound(latin)
    return lb is not None and lb >= threshold


def confidence_tier(latin: str) -> str:
    """Palier de confiance sur la borne prudente : « élevée » (>= 0.50), « bonne »
    (>= 0.35), sinon « modérée » (y compris borne absente)."""
    lb = _lower_bound(latin)
    return _tier(lb) if lb is not None else "modérée"
```

- [ ] **Step 4 : Lancer, vérifier le succès (dont non-régression)**

Run : `venv/Scripts/python.exe -m pytest tests/test_metrics.py -q`
Expected : PASS — les nouveaux tests ET les anciens (`test_cepe_is_reliable`, `test_mousseron_unreliable`, `test_species_without_model_unreliable`) : `boyce_se` étant absent du yaml actuel, la borne = boyce, donc gating identique.

- [ ] **Step 5 : Lint**

Run : `venv/Scripts/python.exe -m ruff check src/sporia/domain/metrics.py`
Expected : `All checks passed!`

- [ ] **Step 6 : Commit**

```bash
git add src/sporia/domain/metrics.py tests/test_metrics.py
git commit -m "feat(sdm): gating prudent boyce − erreur-type (is_reliable_habitat, confidence_tier)"
```

---

### Task 4 : Câbler la CV répétée dans `run_one` (`scripts/train_sdm.py`)

**Files:**
- Modify: `scripts/train_sdm.py`

**Interfaces:**
- Consumes: `repeated_cv_metrics(X, y, groups, repeats)` (Task 2).
- Produces: `run_one(...)` renvoie désormais `(n_presence, auc, boyce, boyce_se)` ; nouvel argument CLI `--repeats` (défaut 25).

- [ ] **Step 1 : Ajouter l'import**

À côté des autres imports `from sporia...` (vers la ligne 34-37) de `scripts/train_sdm.py`, ajouter :

```python
from sporia.domain.sdm_eval import repeated_cv_metrics  # noqa: E402
```

- [ ] **Step 2 : Remplacer la boucle CV de `run_one`**

Dans `run_one`, remplacer le bloc `GroupKFold` :

```python
    gkf = GroupKFold(n_splits=min(5, len(np.unique(grp))))
    aucs, boyces = [], []
    for tr, te in gkf.split(X, y, groups=grp):
        clf = RandomForestClassifier(n_estimators=300, min_samples_leaf=3, n_jobs=-1,
                                     class_weight="balanced_subsample", random_state=0).fit(X[tr], y[tr])
        p = clf.predict_proba(X[te])[:, 1]
        if len(np.unique(y[te])) == 2:
            aucs.append(roc_auc_score(y[te], p))
        boyces.append(boyce_index(p[y[te] == 1], p[y[te] == 0]))
    auc, boyce = float(np.nanmean(aucs)), float(np.nanmean(boyces))
```

par :

```python
    auc, boyce, boyce_se = repeated_cv_metrics(X, y, grp, repeats=repeats)
```

Modifier la signature de `run_one` pour accepter `repeats` : `def run_one(species, layers, feats, france, bg, predict, repeats=25, verbose=True):`. Retirer de `run_one` les imports devenus inutiles `from sklearn.model_selection import GroupKFold` et `from sklearn.metrics import roc_auc_score` (garder `RandomForestClassifier`, `CalibratedClassifierCV` pour le modèle final).

- [ ] **Step 3 : Reporter et retourner `boyce_se`**

Dans `run_one`, mettre à jour l'affichage verbeux et le `return` :

```python
    if verbose:
        print(f"  présence={len(pr)}  AUC(spatial)={auc:.3f}  Boyce={boyce:.3f}  BoyceSE={boyce_se:.3f}")
        print("  importances : " + ", ".join(
            f"{f} {imp:.2f}" for f, imp in sorted(zip(sfeats, base.feature_importances_), key=lambda x: -x[1])[:5]))
```

et remplacer les deux `return len(pr), auc, boyce` / `return len(pr), float("nan"), float("nan")` par des 4-uplets : `return len(pr), auc, boyce, boyce_se` et `return len(pr), float("nan"), float("nan"), float("nan")` (le early-return `[skip]` inclus).

- [ ] **Step 4 : Propager dans `main()` (arg CLI + récap)**

Ajouter l'argument :

```python
    ap.add_argument("--repeats", type=int, default=25, help="nb de découpages CV pour stabiliser le Boyce")
```

Passer `repeats` aux appels `run_one` (branche `--all` et branche mono-espèce) : `run_one(sp, layers, feats, france, bg, a.predict, repeats=a.repeats)` et `run_one(a.species, layers, feats, france, bg, a.predict, repeats=a.repeats)`.

Dans la branche `--all`, adapter la collecte et le tableau récap à 4 colonnes :

```python
        summary = []
        for i, sp in enumerate(species_list, 1):
            print(f"\n• [{i}/{len(species_list)}] {sp}", flush=True)
            n, auc, boyce, boyce_se = run_one(sp, layers, feats, france, bg, a.predict, repeats=a.repeats)
            summary.append((sp, n, auc, boyce, boyce_se))
        print("\n===================== RÉCAPITULATIF =====================")
        print(f"{'espèce':32s} {'présence':>8s} {'AUC':>6s} {'Boyce':>6s} {'BoyceSE':>8s}")
        for sp, n, auc, boyce, boyce_se in summary:
            print(f"{sp:32s} {n:8d} {auc:6.3f} {boyce:6.3f} {boyce_se:8.3f}")
```

- [ ] **Step 5 : Smoke test (une espèce, peu de répétitions)**

Run :
```bash
PYTHONUTF8=1 venv/Scripts/python.exe scripts/train_sdm.py "Boletus edulis" --repeats 3 2>&1 | grep -E "présence=|Boyce"
```
Expected : une ligne du type `présence=1052  AUC(spatial)=0.6xx  Boyce=0.6xx  BoyceSE=0.0xx` (valeurs indicatives ; l'important est que les 4 champs s'affichent sans erreur).

- [ ] **Step 6 : Lint (pas de NOUVELLE erreur)**

Run : `venv/Scripts/python.exe -m ruff check scripts/train_sdm.py`
Expected : pas d'erreur nouvelle par rapport à avant (les imports retirés ne doivent pas laisser d'`F401`).

- [ ] **Step 7 : Commit**

```bash
git add scripts/train_sdm.py
git commit -m "feat(sdm): run_one utilise la CV répétée (Boyce moyen + erreur-type)"
```

---

### Task 5 : Propager `boyce_se` jusqu'au YAML (`scripts/report_metrics.py`)

**Files:**
- Modify: `scripts/report_metrics.py`
- Test: `tests/test_report_metrics.py`

**Interfaces:**
- Consumes: le tableau récap de `train_sdm --all` (colonne `BoyceSE`).
- Produces: `parse_habitat()` renvoie `{latin: (auc, boyce, boyce_se)}` (se = `None` si le log est un ancien format sans la colonne) ; `emit_yaml` écrit `boyce_se` quand présent.

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `tests/test_report_metrics.py` :

```python
"""Parsing du récap habitat (avec colonne BoyceSE)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import report_metrics as rm  # noqa: E402


def test_parse_habitat_captures_se(monkeypatch):
    log = "Boletus edulis                       1052  0.683  0.690  0.026\n"
    monkeypatch.setattr(rm, "_read", lambda p: log if "sdm" in p else "")
    hab = rm.parse_habitat()
    assert hab["Boletus edulis"] == (0.683, 0.690, 0.026)
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run : `venv/Scripts/python.exe -m pytest tests/test_report_metrics.py -q`
Expected : FAIL — le parse actuel renvoie un 2-uplet `(0.683, 0.690)` (pas de SE), l'assertion échoue.

- [ ] **Step 3 : Capturer la SE dans `parse_habitat`**

Dans `scripts/report_metrics.py::parse_habitat`, remplacer la regex et le stockage :

```python
    for line in _read("_retrain_sdm.log").splitlines():
        m = re.match(r"\s*([A-Z][a-zéèA-Za-z]+ [a-z]+)\s+\d+\s+([01]\.\d{3})\s+(-?[01]\.\d{3})(?:\s+([01]\.\d{3}))?\s*$", line.rstrip())
        if m and m.group(1) in NOMS:
            se = float(m.group(4)) if m.group(4) is not None else None
            out[m.group(1)] = (float(m.group(2)), float(m.group(3)), se)
```

(La 4ᵉ colonne est optionnelle → les anciens logs à 3 colonnes donnent `se=None`.)

- [ ] **Step 4 : Adapter les consommateurs de `parse_habitat`**

`combine()` et l'affichage tabulaire dépaquettent désormais un 3-uplet. Dans `combine()`, remplacer `(ah, bh), (af, bf) = hab[sp], fru[sp]` par :

```python
        (ah, bh, _se), (af, bf) = hab[sp], fru[sp]
```

Dans `main()`, la fonction interne `cell(hab, sp, 7, 9)` lit `v[0]`, `v[1]` — comme le 3-uplet garde AUC en `[0]` et Boyce en `[1]`, l'affichage reste correct ; aucune autre modification d'affichage.

Dans `emit_yaml`, après avoir posé `boyce`/`auc`, écrire la SE quand elle existe :

```python
    for sp, vals in hab.items():
        auc, boyce = vals[0], vals[1]
        se = vals[2] if len(vals) > 2 else None
        entry = dict(raw.get(sp) or {})
        entry["boyce"], entry["auc"] = round(boyce, 3), round(auc, 3)
        if se is not None:
            entry["boyce_se"] = round(se, 3)
        raw[sp] = entry
```

et ajouter `"boyce_se"` à `_FIELD_ORDER` (juste après `"auc"`), pour un ordre d'affichage stable :

```python
_FIELD_ORDER = ["boyce", "auc", "boyce_se", "fruiting_boyce", "fruiting_auc", "radar_boyce", "radar_auc"]
```

- [ ] **Step 5 : Lancer les tests (nouveau + non-régression report)**

Run : `venv/Scripts/python.exe -m pytest tests/test_report_metrics.py -q`
Expected : PASS.

- [ ] **Step 6 : Lint (pas de NOUVELLE erreur)**

Run : `venv/Scripts/python.exe -m ruff check scripts/report_metrics.py tests/test_report_metrics.py`
Expected : `tests/test_report_metrics.py` clean ; `scripts/report_metrics.py` sans nouvelle erreur.

- [ ] **Step 7 : Commit**

```bash
git add scripts/report_metrics.py tests/test_report_metrics.py
git commit -m "feat(sdm): report_metrics propage boyce_se jusqu'à species_metrics.yaml"
```

---

### Task 6 : Ré-estimation stable + re-validation guilde (opérationnel)

Tâche **opérationnelle** (pas de TDD) : produit les métriques stables et tranche le chantier guilde. Aucun quota réseau (SDM = GBIF + couches statiques).

**Files:**
- Produces : `data/cache/sdm_*.npy`, `data/cache/_retrain_sdm.log`
- Modify : `src/sporia/data/species_metrics.yaml` (ré-émis, avec `boyce_se`)

- [ ] **Step 1 : Sauvegardes**

```bash
mkdir -p data/cache/_sdm_backup_pre_stab
cp -n data/cache/sdm_*.npy data/cache/_sdm_backup_pre_stab/
cp src/sporia/data/species_metrics.yaml src/sporia/data/species_metrics.yaml.bak_pre_stab
```

- [ ] **Step 2 : Ré-estimation complète (Boyce stable + cartes)**

```bash
PYTHONUTF8=1 venv/Scripts/python.exe scripts/train_sdm.py --all --predict --repeats 25 > data/cache/_retrain_sdm.log 2>&1; echo "EXIT=$?"
```
Vérifier que le récap final montre 4 colonnes (présence/AUC/Boyce/BoyceSE) pour les 14 espèces.

- [ ] **Step 3 : Ré-émettre les métriques**

```bash
PYTHONUTF8=1 venv/Scripts/python.exe scripts/report_metrics.py --emit-yaml
```
Vérifier que `src/sporia/data/species_metrics.yaml` contient `boyce_se` par espèce ET conserve `fruiting_*`/`radar_*`.

- [ ] **Step 4 : Re-valider le chantier guilde à métrique stable (comparaison propre)**

Les anciennes valeurs (Calocybe −0.188, etc.) étaient du Boyce mono-partition bruité → les comparer n'a pas de sens. La comparaison propre est **jeu restreint (open) vs jeu complet, tous deux sous la métrique stable**. Pour chaque espèce `open`, mesurer le Boyce stable ± SE dans les deux configurations, avec le diagnostic jetable existant (`scratchpad/diag_boyce_var.py`, adaptable) OU en réentraînant l'espèce avec puis sans la restriction de guilde (en éditant temporairement, hors commit). Décision documentée par espèce :
- Si la **borne prudente** (boyce − SE) du jeu restreint ≥ celle du jeu complet → le changement guilde aide → on le garde.
- Sinon → le rapporter ; le champ `guild` reste (infra utile pour la suite), mais on note que le jeu restreint n'apporte pas de gain mesurable.
Consigner les chiffres des 3 espèces dans le suivi.

- [ ] **Step 5 : Commit des métriques**

```bash
git add src/sporia/data/species_metrics.yaml
git commit -m "chore(sdm): métriques habitat stabilisées (Boyce moyen + erreur-type)"
```

Note : les `sdm_*.npy` sont dans `data/cache/` (non versionné) ; leur déploiement prod se fait par le processus habituel (scp), hors périmètre.

---

## Validation finale (après les 6 tasks)

- `venv/Scripts/python.exe -m pytest -q` : toute la suite passe.
- `species_metrics.yaml` : chaque espèce servie a `boyce`, `auc`, `boyce_se`, et sa borne prudente `boyce − boyce_se ≥ 0.10`.
- Les espèces dont la borne prudente passe sous 0.10 basculent en non-servies (comportement voulu, pas une régression) — le vérifier via `tests/test_served_species.py`.
