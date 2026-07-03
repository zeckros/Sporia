# Sporia — Modèle : hygiène & métriques reproductibles — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ne plus servir les cartes d'habitat trompeuses (Boyce négatif/faible) via une règle pilotée par un snapshot de métriques versionné, et rendre `report_metrics.py` reproductible — sans toucher au calcul des espèces conservées.

**Architecture:** Un fichier versionné `species_metrics.yaml` (Boyce/AUC habitat par espèce, généré depuis les logs de retrain) devient la source de vérité. Un helper `sporia.domain.metrics.is_reliable_habitat()` en dérive quelles espèces sont fiables (Boyce ≥ seuil). Les deux filtres d'exclusion en dur (`_HIDDEN_FRUITING`, `EXCLUDED_FROM_MODELING`) sont remplacés par ce helper.

**Tech Stack:** Python, PyYAML, pytest, scikit-learn (déjà en place).

## Global Constraints

- **Branche** `chantier-modele` (déjà créée).
- **Seuil Boyce = 0.10** (validé) : exclut `Calocybe gambosa` (−0.19) et `Morchella esculenta` (pas de modèle) ; **garde `Boletus edulis` (0.389)** et toute espèce à Boyce positif.
- **Iso-comportement** pour les espèces conservées : on ne change QUE la liste servie, jamais le scoring.
- `species_metrics.yaml` est **généré une fois puis committé** (les logs `data/cache/_retrain_*.log` sont gitignorés ; le YAML, non).
- Commits fréquents, messages sans `Co-Authored-By`.

## File Structure

- Créés : `src/sporia/data/species_metrics.yaml`, `src/sporia/domain/metrics.py`, `tests/test_metrics.py`, `tests/test_served_species.py`.
- Modifiés : `scripts/report_metrics.py` (fix UTF-8 + `--emit-yaml`), `src/sporia/enrich/fruiting_live.py` (2 usages de `_HIDDEN_FRUITING`), `src/sporia/overlays/fruiting.py` (retrait `EXCLUDED_FROM_MODELING`).

---

### Task 1: `report_metrics.py` — fix UTF-8 + émission du snapshot YAML

**Files:**
- Modify: `scripts/report_metrics.py`
- Create (généré): `src/sporia/data/species_metrics.yaml`

**Interfaces:**
- Produces: `src/sporia/data/species_metrics.yaml` = `{ "<latin>": {boyce: <float>, auc: <float>} }` pour chaque espèce ayant un modèle d'habitat.

- [ ] **Step 1: Fix the stdout encoding crash**

Le script plante en fin (`UnicodeEncodeError` sur `≤`/`—`/`·` vers stdout cp1252 Windows). Au tout début de `main()` (avant le premier `print`), ajouter :
```python
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
```

- [ ] **Step 2: Add the YAML emitter**

Ajouter cette fonction dans `scripts/report_metrics.py` (au-dessus de `main`) :
```python
def emit_yaml(hab: dict) -> Path:
    """Écrit src/sporia/data/species_metrics.yaml depuis les métriques habitat parsées."""
    dest = Path(__file__).resolve().parent.parent / "src" / "sporia" / "data" / "species_metrics.yaml"
    lines = [
        "# Métriques habitat (SDM) par espèce — Boyce/AUC (CV spatiale).",
        "# Généré par : python scripts/report_metrics.py --emit-yaml",
        "# Boyce ~0=hasard, 1=parfait. Sert à décider quelles espèces sont servies (seuil 0.10).",
    ]
    for sp in sorted(hab, key=lambda s: -hab[s][1]):
        auc, boyce = hab[sp]
        lines.append(f"{sp}: {{boyce: {boyce:.3f}, auc: {auc:.3f}}}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest
```
And in `main()`, right after `hab, fru = parse_habitat(), parse_fruiting()`, add :
```python
    import sys
    if "--emit-yaml" in sys.argv:
        p = emit_yaml(hab)
        print(f"[emit] {p} ({len(hab)} espèces)")
```

- [ ] **Step 3: Generate the snapshot**

Run: `venv/Scripts/python.exe scripts/report_metrics.py --emit-yaml`
Expected: le tableau s'affiche **sans crash**, puis `[emit] .../species_metrics.yaml (13 espèces)`.

- [ ] **Step 4: Sanity-check the generated file**

Run: `venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('src/sporia/data/species_metrics.yaml',encoding='utf-8')); print('Boletus edulis', d['Boletus edulis']); print('Calocybe gambosa', d['Calocybe gambosa'])"`
Expected: `Boletus edulis {'boyce': 0.389, 'auc': 0.685}` et `Calocybe gambosa {'boyce': -0.188, 'auc': 0.659}` (valeurs proches ; issues du log courant).

- [ ] **Step 5: Commit**

```bash
git add scripts/report_metrics.py src/sporia/data/species_metrics.yaml
git commit -m "feat: report_metrics UTF-8 + emit versioned species_metrics.yaml"
```

---

### Task 2: `sporia.domain.metrics` — fiabilité de l'habitat

**Files:**
- Create: `src/sporia/domain/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `src/sporia/data/species_metrics.yaml` (Task 1).
- Produces: `habitat_boyce() -> dict[str, float]` ; `is_reliable_habitat(latin: str, threshold: float = 0.10) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_metrics.py`:
```python
"""Fiabilité de l'habitat depuis species_metrics.yaml."""

from __future__ import annotations

from sporia.domain.metrics import habitat_boyce, is_reliable_habitat


def test_habitat_boyce_loads_yaml():
    b = habitat_boyce()
    assert isinstance(b, dict)
    assert "Boletus edulis" in b


def test_cepe_is_reliable():
    assert is_reliable_habitat("Boletus edulis") is True  # 0.389 >= 0.10


def test_mousseron_unreliable():
    assert is_reliable_habitat("Calocybe gambosa") is False  # -0.19 < 0.10


def test_species_without_model_unreliable():
    assert is_reliable_habitat("Morchella esculenta") is False  # absent du yaml
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_metrics.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sporia.domain.metrics'`.

- [ ] **Step 3: Implement `src/sporia/domain/metrics.py`**

```python
"""Fiabilité de la carte d'habitat (SDM) par espèce, depuis data/species_metrics.yaml.
Ne servir que les espèces au Boyce habitat >= seuil (les autres induisent l'utilisateur
en erreur : ex. Calocybe gambosa Boyce -0.19, ou morille sans modèle)."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

import yaml

DEFAULT_THRESHOLD = 0.10


@lru_cache(maxsize=1)
def habitat_boyce() -> dict[str, float]:
    src = resources.files("sporia").joinpath("data", "species_metrics.yaml")
    with src.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return {sp: float(v["boyce"]) for sp, v in raw.items() if isinstance(v, dict) and "boyce" in v}


def is_reliable_habitat(latin: str, threshold: float = DEFAULT_THRESHOLD) -> bool:
    """True si l'espèce a un modèle d'habitat fiable (Boyce présent ET >= seuil).
    Absent (pas de modèle) ou Boyce < seuil → False (espèce non servie)."""
    b = habitat_boyce().get(latin)
    return b is not None and b >= threshold
```

- [ ] **Step 4: Run to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_metrics.py -q`
Expected: 4 passed.

- [ ] **Step 5: Lint + commit**

```bash
venv/Scripts/python.exe -m ruff check src/sporia/domain/metrics.py tests/test_metrics.py
git add src/sporia/domain/metrics.py tests/test_metrics.py
git commit -m "feat: sporia.domain.metrics.is_reliable_habitat (Boyce threshold)"
```

---

### Task 3: Câbler l'exclusion pilotée par les données

**Files:**
- Modify: `src/sporia/enrich/fruiting_live.py` (les 2 usages de `_HIDDEN_FRUITING` : lignes ~49-56 def, ~65 dans `available_models`, ~372), `src/sporia/overlays/fruiting.py` (ligne 15 + 21)
- Test: `tests/test_served_species.py`

**Interfaces:**
- Consumes: `sporia.domain.metrics.is_reliable_habitat` (Task 2).

- [ ] **Step 1: Write the failing test**

Create `tests/test_served_species.py`:
```python
"""Les espèces servies excluent les cartes d'habitat trompeuses (marqué slow : dépend
des modèles bakés data/cache/fruiting_*.pkl, absents en CI)."""

from __future__ import annotations

import pytest


@pytest.mark.slow
def test_served_excludes_misleading():
    from sporia.overlays.fruiting import fruiting_models

    served = fruiting_models()
    assert "Calocybe gambosa" not in served
    assert "Morchella esculenta" not in served


@pytest.mark.slow
def test_served_keeps_cepe_and_strong():
    from sporia.overlays.fruiting import fruiting_models

    served = fruiting_models()
    assert "Boletus edulis" in served  # 0.389, gardé (espèce vedette)
    assert "Imleria badia" in served  # 0.727
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_served_species.py -q -m slow`
Expected: FAIL — `Calocybe gambosa` est encore servi (pas encore exclu).

- [ ] **Step 3: Update `fruiting_live.py`**

In `src/sporia/enrich/fruiting_live.py` :
- Add near the top imports: `from sporia.domain.metrics import is_reliable_habitat`.
- **Delete** the `_HIDDEN_FRUITING = { ... }` block (lignes ~45-56, commentaire inclus).
- In `available_models()` (ligne ~65), replace `if sp not in _HIDDEN_FRUITING:` with `if is_reliable_habitat(sp):`.
- At ligne ~372, replace `if sp in _HIDDEN_FRUITING:` with `if not is_reliable_habitat(sp):`.

Verify no stray reference remains: `grep -n "_HIDDEN_FRUITING" src/sporia/enrich/fruiting_live.py` → aucune.

- [ ] **Step 4: Update `overlays/fruiting.py`**

In `src/sporia/overlays/fruiting.py` :
- **Delete** `EXCLUDED_FROM_MODELING = {"Morchella esculenta"}` (ligne 15).
- Replace `fruiting_models()` body (ligne 21) with:
  `return fruiting_live.available_models()`
  (la fiabilité est désormais appliquée en amont dans `available_models`).

Verify: `grep -n "EXCLUDED_FROM_MODELING" src/sporia/overlays/fruiting.py` → aucune.

- [ ] **Step 5: Run to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_served_species.py -q -m slow`
Expected: 2 passed (`Calocybe gambosa`/`Morchella esculenta` exclus ; `Boletus edulis`/`Imleria badia` servis).

- [ ] **Step 6: Iso-behavior + full suite + lint**

Run:
```bash
venv/Scripts/python.exe -c "import champi_core" 2>/dev/null; venv/Scripts/python.exe -c "from sporia import api; print('served:', sorted(api.fruiting_models()))"
venv/Scripts/python.exe -m ruff check src tests
venv/Scripts/python.exe -m pytest -q
```
Expected: la liste servie **ne contient ni `Calocybe gambosa` ni `Morchella esculenta`** ; ruff clean ; suite verte (les tests slow inclus tournent en local car les pkls sont présents).

- [ ] **Step 7: Commit**

```bash
git add src/sporia/enrich/fruiting_live.py src/sporia/overlays/fruiting.py tests/test_served_species.py
git commit -m "feat: serve only species with reliable habitat (Boyce>=0.10); drop misleading Mousseron"
```

---

## Self-Review

**Spec coverage :**
- `species_metrics.yaml` versionné + généré depuis les logs → Task 1. ✅
- `domain/metrics.py` (habitat_boyce + prédicat de fiabilité) → Task 2. ✅
- Remplacer `_HIDDEN_FRUITING` + retirer `EXCLUDED_FROM_MODELING` → Task 3. ✅
- Fix crash unicode report_metrics → Task 1 Step 1. ✅
- Tests (metrics + served) → Tasks 2, 3. ✅
- Mousseron exclu / Cèpe gardé → Task 3 tests. ✅
- Badge UI → hors périmètre (chantier #4), non planifié ici. ✅ (conforme au spec)

**Placeholder scan :** aucun « TBD/TODO ». Les valeurs Boyce des étapes de vérif (0.389, −0.188) sont les valeurs réelles du log courant, données comme attendu.

**Type consistency :** `is_reliable_habitat(latin, threshold=0.10) -> bool` cohérent entre Task 2 (déf) et Task 3 (usages). Le spec nommait `hidden_species(threshold)` ; réalisé ici par le prédicat inverse `is_reliable_habitat` (plus simple à câbler, gère « pas de modèle » = non fiable). `habitat_boyce() -> dict[str,float]` cohérent Task 2 ↔ tests.

## Notes exécution

- `species_metrics.yaml` est un artefact **généré puis committé** (Task 1). En CI il n'est pas régénéré (les logs sont gitignorés) — la CI lit le YAML committé.
- `tests/test_served_species.py` est marqué **`slow`** car il dépend des `data/cache/fruiting_*.pkl` (absents en CI) ; il tourne en local. `tests/test_metrics.py` lit le YAML committé → tourne partout.
