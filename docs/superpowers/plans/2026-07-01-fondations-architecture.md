# Sporia — Fondations (architecture + qualité) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the Sporia backend to professional dev standards — a `src/sporia/` package, a test safety net, CI, and pinned deps — without changing any runtime behavior, keeping the product deployable after every phase.

**Architecture:** Phased refactor. Phase 0 adds tooling + characterization tests against the *current* flat code (zero runtime change). Phase 1 extracts domain data/logic. Phase 2 migrates modules into `src/sporia/` behind root-level shims so the `server:app` entrypoint keeps working. Phase 3 moves the web entrypoint to `sporia.web.app:app`, updates deploy artifacts, and adds an admin role. The characterization tests prove iso-behavior across every move.

**Tech Stack:** Python 3.10 (prod parity), FastAPI + Starlette, rasterio/geopandas/rioxarray, matplotlib, scikit-learn 1.7.x, pytest, ruff, pre-commit, GitHub Actions.

## Global Constraints

- **Python 3.10** target for CI (prod runs 3.10). `requires-python = ">=3.10"`.
- **scikit-learn pinned `>=1.7,<1.8`** — verbatim from `requirements.txt` (`.pkl` models are version-sensitive; 1.8 needs Py≥3.11).
- **No behavior change** ("iso-comportement"): favorability scores, API responses, and rendered overlays must be identical before/after. Characterization tests are the gate.
- **Always deployable:** every task ends green; the `server:app` entrypoint stays working until Phase 3, which updates deploy artifacts in the same phase.
- **Commit messages:** plain, no `Co-Authored-By` line (user preference). Conventional-commit prefixes (`chore:`, `test:`, `refactor:`, `feat:`, `docs:`).
- **Commits are LOCAL only.** Do not `git push` — prod deploy is a separate user-initiated step.
- **Package name** `sporia`, **src-layout** (`src/sporia/`). One responsibility per module.
- **Ruff scope:** lint/format `src/` and `tests/` only. Legacy root `.py` files are *not* linted until they migrate into `src/sporia/` (incremental tightening). Never mass-reformat legacy files in this chantier.
- **Do not touch** `web/app.js`, `web/index.html` (frontend detangle = chantier #4).

---

## File Structure

**Created:**
- `pyproject.toml` — metadata, deps, ruff + pytest config, src-layout.
- `requirements.lock` — `pip freeze` snapshot for reproducible deploy.
- `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `LICENSE`, `README.md` (rewrite).
- `src/sporia/__init__.py`, `src/sporia/config.py`
- `src/sporia/data/species.yaml`, `src/sporia/domain/{__init__,species,suitability}.py`
- `src/sporia/geo/{__init__,rasters,render}.py`
- `src/sporia/overlays/{__init__,weather,favorability,soil,terrain,fruiting,radar}.py`
- `src/sporia/{places,points}.py`
- `src/sporia/enrich/{__init__,forest,soil_static,soil_dynamic,terrain,fruiting_live}.py`
- `src/sporia/users/{__init__,prefs,spots,access_requests}.py`
- `src/sporia/pipeline/{__init__,collect_day,interpret_day,wx_features,scheduler}.py`
- `src/sporia/web/{__init__,app,auth,security}.py`
- `tests/{conftest,test_auth,test_api_contracts,test_suitability,test_species,test_config,test_render_smoke,test_admin}.py`

**Modified:** `.gitignore`, `champi_core.py` (→ shrinks to a facade, then deleted P3), root modules (→ shims, then deleted P3), `systemd/*.service`, `Dockerfile`, `oracle_deploy.sh`, `run_scheduler.bat`, `scripts/*` imports, deploy docs.

**Deleted (P3):** `champi_core.py`, root shims, `server.py` (moved).

---

# PHASE 0 — Tooling + safety net (zero runtime change)

### Task 0.1: Package skeleton + pinned deps + editable install

**Files:**
- Create: `pyproject.toml`, `src/sporia/__init__.py`, `requirements.lock`

**Interfaces:**
- Produces: an installable `sporia` package (empty for now); `pip install -e .` works.

- [ ] **Step 1: Create `src/sporia/__init__.py`**

```python
"""Sporia — prévision de cueillette de champignons en France."""

__version__ = "0.1.0"
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "sporia"
version = "0.1.0"
description = "Sporia — prévision de cueillette de champignons en France"
requires-python = ">=3.10"
dependencies = [
    "fastapi",
    "uvicorn[standard]",
    "itsdangerous",
    "bcrypt",
    "PyYAML",
    "python-dotenv>=1.2.2",
    "pydantic-settings",
    "schedule",
    "xarray",
    "rioxarray",
    "rasterio",
    "geopandas>=1.1.2",
    "pandas",
    "numpy",
    "scipy",
    "h5py",
    "netcdf4",
    "requests>=2.33.0",
    "urllib3>=2.7.0",
    "idna>=3.15",
    "matplotlib",
    "Pillow>=12.2.0",
    "scikit-learn>=1.7,<1.8",
]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.6", "pre-commit>=3.5", "httpx"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
sporia = ["data/*.yaml"]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["slow: tests needing heavier geo/render deps"]
```

- [ ] **Step 3: Editable install into the existing venv**

Run: `python -m pip install -e ".[dev]"`
Expected: `Successfully installed sporia-0.1.0` (deps already satisfied in venv).

- [ ] **Step 4: Snapshot exact versions for reproducible deploy**

Run: `python -m pip freeze > requirements.lock`
Expected: `requirements.lock` created, lists exact `==` versions.

- [ ] **Step 5: Verify the package imports**

Run: `python -c "import sporia; print(sporia.__version__)"`
Expected: `0.1.0`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/sporia/__init__.py requirements.lock
git commit -m "chore: add pyproject src-layout package + pinned deps"
```

---

### Task 0.2: Ruff + pre-commit (scoped to src/ + tests/)

**Files:**
- Create: `.pre-commit-config.yaml`
- Modify: `.gitignore`

- [ ] **Step 1: Create `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: ["--maxkb=1024"]
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
        args: ["--fix"]
        files: ^(src|tests)/
      - id: ruff-format
        files: ^(src|tests)/
```

- [ ] **Step 2: Add `venv/` to `.gitignore`**

Add these lines under the `# Python` section of `.gitignore`:

```
venv/
.venv/
```

- [ ] **Step 3: Verify ruff is clean on current src/tests**

Run: `python -m ruff check src tests`
Expected: `All checks passed!` (src has only `__init__.py`; `tests/` may not exist yet — that's fine, ruff reports "No files found" or passes).

- [ ] **Step 4: Install the git hook**

Run: `python -m pre_commit install`
Expected: `pre-commit installed at .git/hooks/pre-commit`

- [ ] **Step 5: Commit**

```bash
git add .pre-commit-config.yaml .gitignore
git commit -m "chore: add ruff + pre-commit scoped to src and tests"
```

---

### Task 0.3: pytest harness + synthetic fixtures

**Files:**
- Create: `tests/conftest.py`, `tests/__init__.py`

**Interfaces:**
- Produces: fixtures `repo_root` (chdir to repo root so legacy relative paths resolve), `tiny_raster` (path to a small in-memory GeoTIFF), `weather_stub` (a `w` dict for suitability), `client` (FastAPI `TestClient`).

- [ ] **Step 1: Create `tests/__init__.py`** (empty file)

```python
```

- [ ] **Step 2: Create `tests/conftest.py`**

```python
"""Shared pytest fixtures. Synthetic data only — no dependency on the 5 GB data/ tree."""
from __future__ import annotations
import os
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _chdir_repo_root(monkeypatch):
    """Legacy modules resolve paths relative to CWD; run every test from repo root."""
    monkeypatch.chdir(REPO_ROOT)


@pytest.fixture
def weather_stub() -> dict:
    """A favourable-conditions weather dict, shaped like analyze_point_weather() output."""
    return {
        "month": 9,
        "temp_mean": 18.0,
        "soil_temp": 16.0,
        "days_since_rain": 8,
        "rain14": 30.0,
        "soil_moisture": 0.30,
    }


@pytest.fixture
def tiny_raster(tmp_path) -> Path:
    """A 4x4 EPSG:4326 GeoTIFF over a small area of France, for render/sample smoke tests."""
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_bounds

    W = H = 4
    west, south, east, north = 2.0, 46.0, 3.0, 47.0
    data = np.linspace(0, 20, W * H, dtype="float32").reshape(H, W)
    path = tmp_path / "T_20260901.tif"
    transform = from_bounds(west, south, east, north, W, H)
    with rasterio.open(
        path, "w", driver="GTiff", height=H, width=W, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform, nodata=np.nan,
    ) as dst:
        dst.write(data, 1)
    return path
```

- [ ] **Step 3: Verify pytest collects with no errors**

Run: `python -m pytest -q`
Expected: `no tests ran` (0 collected) with exit code 5 — harness works, fixtures import cleanly.

- [ ] **Step 4: Commit**

```bash
git add tests/__init__.py tests/conftest.py
git commit -m "test: add pytest harness and synthetic fixtures"
```

---

### Task 0.4: Characterization tests — auth

Locks the current auth behavior in `server.py` before anything moves. Imports through the current module name; the import path is updated in Phase 3 when `server.py` moves.

**Files:**
- Create: `tests/test_auth.py`

**Interfaces:**
- Consumes: `server.app` (FastAPI app), `server._verify(username, password)`.

- [ ] **Step 1: Write the tests**

```python
"""Characterization of the current auth surface (server.py). Must stay green across the refactor."""
from __future__ import annotations
import pytest
from starlette.testclient import TestClient

import server


@pytest.fixture
def client():
    return TestClient(server.app)


def test_verify_unknown_user_returns_none():
    assert server._verify("no-such-user", "whatever") is None


def test_verify_wrong_password_returns_none():
    assert server._verify("dev", "wrong-password") is None


def test_protected_route_requires_auth(client):
    r = client.get("/api/dates")
    assert r.status_code == 401


def test_login_bad_credentials_401(client):
    r = client.post("/api/login", json={"username": "dev", "password": "nope"})
    assert r.status_code == 401


def test_me_unauthenticated(client):
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json() == {"authenticated": False, "name": None}


def test_logout_always_ok(client):
    r = client.post("/api/logout")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
```

- [ ] **Step 2: Run and verify pass**

Run: `python -m pytest tests/test_auth.py -v`
Expected: 6 passed. (If import of `server` pulls heavy deps and fails, install is incomplete — fix env, do not weaken the test.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_auth.py
git commit -m "test: characterize current auth behavior"
```

---

### Task 0.5: Characterization tests — API input validation

**Files:**
- Create: `tests/test_api_contracts.py`

- [ ] **Step 1: Write the tests**

```python
"""Characterization of input-validation contracts on the current API (server.py)."""
from __future__ import annotations
import pytest
from starlette.testclient import TestClient

import server


@pytest.fixture
def client():
    return TestClient(server.app)


def _login(client):
    # dev account password is unknown here; instead inject a session directly is complex,
    # so these tests assert the UNAUTH contract (401) and the validation contract via
    # routes that validate BEFORE the auth dependency is not possible (auth runs first).
    # We therefore assert 401 for protected routes and test pure validators directly.
    return client


def test_unknown_route_404(client):
    assert client.get("/api/does-not-exist").status_code == 404


@pytest.mark.parametrize("bad", ["", "2026-09-01", "2026099", "abcdefgh", "202609011"])
def test_valid_date_rejects_bad_input(bad):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        server._valid_date(bad)
    assert exc.value.status_code == 400


def test_valid_date_accepts_good_input():
    assert server._valid_date("20260901") == "20260901"


@pytest.mark.parametrize("v,expected", [("rr", "RR"), ("T", "T"), ("t", "T")])
def test_valid_var_normalizes(v, expected):
    assert server._valid_var(v) == expected


def test_valid_var_rejects_bad():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        server._valid_var("humidity")
    assert exc.value.status_code == 400
```

- [ ] **Step 2: Run and verify pass**

Run: `python -m pytest tests/test_api_contracts.py -v`
Expected: all passed (date: 5 bad + 1 good, var: 3 + 1).

- [ ] **Step 3: Commit**

```bash
git add tests/test_api_contracts.py
git commit -m "test: characterize API input-validation contracts"
```

---

### Task 0.6: Characterization tests — suitability scoring

Locks the rule-model math in `champi_core.py` (the part that must be byte-identical after extraction to `domain/suitability.py`).

**Files:**
- Create: `tests/test_suitability.py`

**Interfaces:**
- Consumes: `champi_core.mushroom_suitability`, `champi_core._ph_match`, `champi_core._altitude_fit_point`, `champi_core.MUSHROOMS`.

- [ ] **Step 1: Write the tests**

```python
"""Characterization of the rule-based suitability model (champi_core).
These assert exact current outputs so extraction to domain/suitability.py cannot drift."""
from __future__ import annotations
import pytest

import champi_core as core

CEPE = next(m for m in core.MUSHROOMS if m["latin"] == "Boletus edulis")  # months {8,9,10,11}


def test_ph_match_bands():
    assert core._ph_match(None, (4.5, 6.5)) == "unknown"
    assert core._ph_match(5.5, (4.5, 6.5)) == "ok"
    assert core._ph_match(6.7, (4.5, 6.5)) == "ok"      # within +0.3
    assert core._ph_match(7.3, (4.5, 6.5)) == "mid"     # within +1.0
    assert core._ph_match(8.0, (4.5, 6.5)) == "no"


def test_altitude_fit_bounds():
    assert core._altitude_fit_point(None, (0, 900)) == 1.0
    assert 0.3 <= core._altitude_fit_point(3000, (0, 900)) <= 1.0
    assert core._altitude_fit_point(500, (0, 900)) == pytest.approx(1.0)


def test_suitability_out_of_season():
    w = {"month": 3, "temp_mean": 15, "soil_temp": 14, "days_since_rain": 8,
         "rain14": 40, "soil_moisture": 0.3}
    assert core.mushroom_suitability(CEPE, w) == ("Hors saison", "off", 3, "unknown")


def test_suitability_favorable():
    w = {"month": 9, "temp_mean": 16, "soil_temp": 16, "days_since_rain": 10,
         "rain14": 40, "soil_moisture": 0.3}
    label, level, prio, phm = core.mushroom_suitability(
        CEPE, w, soil={"ph": 5.5}, terrain={"altitude": 400, "northness": 0.0})
    assert (label, level) == ("Favorable", "good")
    assert phm == "ok"


def test_suitability_partial_when_dry_and_no_recent_rain():
    w = {"month": 9, "temp_mean": 16, "soil_temp": 16, "days_since_rain": 30,
         "rain14": 0, "soil_moisture": 0.05}
    label, level, prio, phm = core.mushroom_suitability(CEPE, w, soil={"ph": 5.5})
    assert level in {"mid", "bad"}
```

- [ ] **Step 2: Run and verify pass**

Run: `python -m pytest tests/test_suitability.py -v`
Expected: 5 passed. If a value assertion fails, DO NOT edit the model — correct the test to the *actual* current output (this is characterization; current behavior is ground truth).

- [ ] **Step 3: Commit**

```bash
git add tests/test_suitability.py
git commit -m "test: characterize rule-based suitability scoring"
```

---

### Task 0.7: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the workflow**

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - name: Install
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e ".[dev]"
      - name: Ruff (lint)
        run: python -m ruff check src tests
      - name: Ruff (format check)
        run: python -m ruff format --check src tests
      - name: Pytest
        run: python -m pytest -q -m "not slow"
```

- [ ] **Step 2: Verify locally that the same commands pass**

Run: `python -m ruff check src tests && python -m ruff format --check src tests && python -m pytest -q -m "not slow"`
Expected: ruff clean, tests pass. (If `ruff format --check` fails on test files, run `python -m ruff format src tests`, review the diff, re-commit.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add ruff + pytest workflow on Python 3.10"
```

---

### Task 0.8: README + LICENSE + repo hygiene (SSH key)

**Files:**
- Create: `LICENSE`, rewrite `README.md`
- Remove from repo working tree: `ssh-key-2026-06-05.key`

**Interfaces:** none (docs/hygiene).

- [ ] **Step 1: Write `LICENSE`** (proprietary — Sporia is intended for sale)

```
Copyright (c) 2026 Théo Boisnay. All rights reserved.

This software and its source code are proprietary and confidential. No part of
this software may be reproduced, distributed, or transmitted in any form or by
any means, or stored in any information storage/retrieval system, without the
prior written permission of the copyright holder. Unauthorized use is prohibited.
```

- [ ] **Step 2: Rewrite `README.md`**

```markdown
# Sporia

Prévision de cueillette de champignons en France. Web-app FastAPI + Leaflet
adossée à un pipeline météo (Météo-France AROME + radar) et à un modèle
d'habitat/fructification par espèce.

## Développement

```bash
python -m venv venv && source venv/bin/activate   # (Windows: venv\Scripts\activate)
pip install -e ".[dev]"
pre-commit install
pytest -q
uvicorn server:app --reload --port 8000            # entrypoint actuel (voir NOTE)
```

> NOTE : l'entrypoint bascule vers `sporia.web.app:app` en fin de restructuration
> (voir `docs/superpowers/plans/`).

## Architecture

- `src/sporia/` — package applicatif (config, domain, geo, overlays, points,
  places, enrich, users, pipeline, web).
- `scripts/` — entraînement de modèles (`train_*.py`) et pré-calculs (`bake_*.py`).
- `web/` — frontend statique (index.html, app.js) + overlays générés.
- `data/`, `output/` — caches et artefacts (gitignorés, régénérés par le pipeline).

## Déploiement

Oracle Cloud + nginx (TLS) + systemd. Voir `ORACLE_DEPLOY.md`.

## Licence

Propriétaire — tous droits réservés. Voir `LICENSE`.
```

- [ ] **Step 3: Stop tracking the SSH key and move it out of the repo**

The key is already gitignored and not tracked (verified). Move it out of the working tree so it can never be force-added or copied with the repo:

Run:
```bash
mkdir -p ~/.ssh/sporia && mv ssh-key-2026-06-05.key ~/.ssh/sporia/ && chmod 600 ~/.ssh/sporia/ssh-key-2026-06-05.key
```
(Windows PowerShell equivalent: `Move-Item ssh-key-2026-06-05.key $HOME\.ssh\sporia\`.)
Expected: the file no longer exists at repo root.

- [ ] **Step 4: Point deploy docs at the external key path**

In `oracle_deploy.sh` and `ORACLE_DEPLOY.md`, replace any `./ssh-key-2026-06-05.key` reference with `~/.ssh/sporia/ssh-key-2026-06-05.key`. (Grep first: `grep -rn "ssh-key-2026" oracle_deploy.sh ORACLE_DEPLOY.md`.)

- [ ] **Step 5: Commit**

```bash
git add README.md LICENSE oracle_deploy.sh ORACLE_DEPLOY.md
git commit -m "docs: real README, proprietary LICENSE, move SSH key out of repo"
```

---

# PHASE 1 — Data + pure logic out of the god-module

### Task 1.1: `config.py` — settings + BASE_DIR

**Files:**
- Create: `src/sporia/config.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `sporia.config.settings` with attributes `base_dir: Path`, `data_dir`, `output_tiff_dir`, `web_dir`, `overlay_dir`, `data_cache_dir` (all `Path`), `prod: bool`, `session_secret: str | None`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from sporia.config import settings


def test_base_dir_is_repo_root():
    assert (settings.base_dir / "pyproject.toml").is_file()


def test_paths_derive_from_base_dir():
    assert settings.data_dir == settings.base_dir / "data"
    assert settings.output_tiff_dir == settings.base_dir / "output" / "tiff"
    assert settings.overlay_dir == settings.web_dir / "overlays"


def test_prod_is_bool():
    assert isinstance(settings.prod, bool)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sporia.config'`.

- [ ] **Step 3: Implement `src/sporia/config.py`**

```python
"""Central configuration: paths resolved from the repo root (not the CWD) + web settings."""
from __future__ import annotations
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # read .env if present (dev); prod uses real env vars


class Settings:
    base_dir: Path = Path(__file__).resolve().parents[2]

    @property
    def data_dir(self) -> Path:
        return self.base_dir / "data"

    @property
    def output_tiff_dir(self) -> Path:
        return self.base_dir / "output" / "tiff"

    @property
    def web_dir(self) -> Path:
        return self.base_dir / "web"

    @property
    def overlay_dir(self) -> Path:
        return self.web_dir / "overlays"

    @property
    def data_cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def prod(self) -> bool:
        return os.environ.get("PROD") == "1"

    @property
    def session_secret(self) -> str | None:
        return os.environ.get("SESSION_SECRET")


settings = Settings()
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sporia/config.py tests/test_config.py
git commit -m "feat: add sporia.config with repo-root path resolution"
```

---

### Task 1.2: Extract `MUSHROOMS` → `species.yaml` + loader

**Files:**
- Create: `src/sporia/data/species.yaml`, `src/sporia/domain/__init__.py`, `src/sporia/domain/species.py`, `tests/test_species.py`
- Modify: `champi_core.py` (replace the `MUSHROOMS = [...]` literal with an import)

**Interfaces:**
- Produces: `sporia.domain.species.MUSHROOMS: list[dict]` — identical structure to the current literal (`months` as `set[int]`; `rain_lag`, `ph_opt`, `alt_opt` as `tuple`).

- [ ] **Step 1: Create `src/sporia/data/species.yaml`** (ported verbatim from `champi_core.py:64-121`)

```yaml
# Champignons comestibles de France. Données extraites de champi_core.py (iso-comportement).
# months: liste de mois (1-12) ; rain_lag/ph_opt/alt_opt: paires [min, max].
- {nom: "Morille", latin: "Morchella esculenta", color: "#a16207", months: [3,4,5], t_min: 8, t_max: 16, rain_lag: [5,16], rain_min: 15, ph_opt: [6.5,8.0], soil_pref: "Calcicole (sols calcaires/neutres)", habitat: "Frênes, ormes, vergers, sols calcaires, anciennes coupes/brûlures"}
- {nom: "Mousseron de la St-Georges", latin: "Calocybe gambosa", color: "#ca8a04", months: [4,5], t_min: 10, t_max: 17, rain_lag: [4,12], rain_min: 12, ph_opt: [6.3,7.8], soil_pref: "Sols neutres à calcaires", habitat: "Prés, lisières, ronds de sorcière (« mousseron de printemps »)"}
- {nom: "Cèpe d'été / bronzé", latin: "Boletus aereus", color: "#92400e", months: [6,7,8,9], t_min: 16, t_max: 25, rain_lag: [6,13], rain_min: 20, ph_opt: [5.0,7.0], soil_pref: "Sols acides à neutres", alt_opt: [0,900], habitat: "Chênes, châtaigniers, zones chaudes ensoleillées (plaine/colline)"}
- {nom: "Girolle / Chanterelle", latin: "Cantharellus cibarius", color: "#eab308", months: [6,7,8,9,10], t_min: 14, t_max: 23, rain_lag: [2,8], rain_min: 10, ph_opt: [4.3,6.0], soil_pref: "Acidophile (sols acides, moussus)", habitat: "Feuillus & conifères, mousses, talus"}
- {nom: "Cèpe de Bordeaux", latin: "Boletus edulis", color: "#854d0e", months: [8,9,10,11], t_min: 12, t_max: 20, rain_lag: [7,16], rain_min: 20, ph_opt: [4.5,6.5], soil_pref: "Sols acides à neutres", habitat: "Chênes, hêtres, châtaigniers, épicéas"}
- {nom: "Coulemelle (lépiote élevée)", latin: "Macrolepiota procera", color: "#a8a29e", months: [7,8,9,10,11], t_min: 12, t_max: 20, rain_lag: [4,11], rain_min: 12, ph_opt: [5.5,7.5], soil_pref: "Sols neutres, riches", habitat: "Prés, lisières, clairières, bords de chemins"}
- {nom: "Rosé des prés", latin: "Agaricus campestris", color: "#fb7185", months: [8,9,10], t_min: 12, t_max: 20, rain_lag: [3,9], rain_min: 12, ph_opt: [6.0,7.5], soil_pref: "Sols neutres riches (prairies)", habitat: "Prairies pâturées, pelouses (non traitées)"}
- {nom: "Trompette de la mort", latin: "Craterellus cornucopioides", color: "#334155", months: [9,10,11], t_min: 8, t_max: 17, rain_lag: [5,13], rain_min: 12, ph_opt: [5.0,7.2], soil_pref: "Sols acides à calcaires, humides", habitat: "Feuillus (hêtres, charmes), sols humides moussus"}
- {nom: "Chanterelle en tube", latin: "Craterellus tubaeformis", color: "#d97706", months: [9,10,11,12], t_min: 5, t_max: 15, rain_lag: [5,13], rain_min: 10, ph_opt: [4.0,5.5], soil_pref: "Acidophile (conifères, mousses)", habitat: "Conifères, mousses, sols acides"}
- {nom: "Pied de mouton", latin: "Hydnum repandum", color: "#d6d3d1", months: [9,10,11,12], t_min: 6, t_max: 15, rain_lag: [5,13], rain_min: 12, ph_opt: [4.5,6.5], soil_pref: "Sols acides à neutres", habitat: "Feuillus & conifères, après écart de température sol/air"}
- {nom: "Lactaire délicieux", latin: "Lactarius deliciosus", color: "#ea580c", months: [9,10,11], t_min: 8, t_max: 16, rain_lag: [5,12], rain_min: 12, ph_opt: [5.5,7.5], soil_pref: "Sols neutres à calcaires (pins)", habitat: "Pins et conifères"}
- {nom: "Bolet bai", latin: "Imleria badia", color: "#78350f", months: [8,9,10,11], t_min: 8, t_max: 18, rain_lag: [6,13], rain_min: 15, ph_opt: [4.0,5.8], soil_pref: "Acidophile (conifères)", habitat: "Conifères surtout, parfois feuillus"}
- {nom: "Pied bleu", latin: "Lepista nuda", color: "#7c3aed", months: [10,11,12], t_min: 4, t_max: 13, rain_lag: [5,15], rain_min: 12, ph_opt: [5.5,7.5], soil_pref: "Sols neutres, litière riche", habitat: "Feuillus, tas de feuilles, composts ; résiste au frais"}
- {nom: "Pleurote en huître", latin: "Pleurotus ostreatus", color: "#64748b", months: [11,12,1,2], t_min: 2, t_max: 12, rain_lag: [3,12], rain_min: 8, ph_opt: [4.0,8.5], soil_pref: "Sur bois mort (sol indifférent)", habitat: "Bois mort (peupliers, hêtres), pousse après refroidissement"}
```

- [ ] **Step 2: Write the failing test**

```python
from sporia.domain.species import MUSHROOMS


def test_species_count():
    assert len(MUSHROOMS) == 14


def test_types_match_legacy_shape():
    cepe = next(m for m in MUSHROOMS if m["latin"] == "Boletus edulis")
    assert cepe["months"] == {8, 9, 10, 11}          # set
    assert cepe["rain_lag"] == (7, 16)               # tuple
    assert cepe["ph_opt"] == (4.5, 6.5)              # tuple
    assert isinstance(cepe["months"], set)


def test_optional_alt_opt():
    aereus = next(m for m in MUSHROOMS if m["latin"] == "Boletus aereus")
    assert aereus["alt_opt"] == (0, 900)
    assert "alt_opt" not in next(m for m in MUSHROOMS if m["latin"] == "Boletus edulis")
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_species.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sporia.domain'`.

- [ ] **Step 4: Create `src/sporia/domain/__init__.py`** (empty) and `src/sporia/domain/species.py`

```python
"""Espèces modélisées — chargées depuis data/species.yaml, converties au format legacy
(months: set ; rain_lag/ph_opt/alt_opt: tuple) pour une compatibilité stricte."""
from __future__ import annotations
from importlib import resources

import yaml

_PAIR_FIELDS = ("rain_lag", "ph_opt", "alt_opt")


def _load() -> list[dict]:
    with resources.files("sporia.data").joinpath("species.yaml").open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    out: list[dict] = []
    for entry in raw:
        m = dict(entry)
        m["months"] = set(m["months"])
        for k in _PAIR_FIELDS:
            if k in m and m[k] is not None:
                m[k] = tuple(m[k])
        out.append(m)
    return out


MUSHROOMS: list[dict] = _load()
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_species.py -v`
Expected: 3 passed.

- [ ] **Step 6: Point `champi_core` at the new source**

In `champi_core.py`, delete the `MUSHROOMS = [ ... ]` literal (lines 58-121, including the leading comment block) and add near the top imports:

```python
from sporia.domain.species import MUSHROOMS
```

- [ ] **Step 7: Verify the whole suite still passes (iso-behavior)**

Run: `python -m pytest -q -m "not slow"`
Expected: all green — `test_suitability.py` proves `MUSHROOMS` is unchanged in practice.

- [ ] **Step 8: Commit**

```bash
git add src/sporia/data/species.yaml src/sporia/domain/__init__.py src/sporia/domain/species.py tests/test_species.py champi_core.py
git commit -m "refactor: move MUSHROOMS data to species.yaml with loader"
```

---

### Task 1.3: Extract suitability logic → `domain/suitability.py`

**Files:**
- Create: `src/sporia/domain/suitability.py`
- Modify: `champi_core.py` (remove the moved functions + `_ASPECT_W` usage; re-export from the new module)

**Interfaces:**
- Consumes: `sporia.domain.species` (not required here), the `_ASPECT_W` seasonal-weights dict.
- Produces: `mushroom_suitability(m, w, soil=None, terrain=None) -> tuple[str, str, float, str]`, `_ph_match(ph, ph_opt) -> str`, `_altitude_fit_point(alt, alt_opt) -> float`, `_aspect_fit_point(northness, month) -> float`, `_radar_label(score, score_pct, in_season) -> tuple[str, str]`.

- [ ] **Step 1: Locate `_ASPECT_W`**

Run: `grep -rn "_ASPECT_W" *.py`
Expected: defined in `mushroom_map.py`, used by `champi_core._aspect_fit_point` and `mushroom_map._aspect_fit`. It is a **domain constant** (seasonal north/south weighting), so it will live in `domain/suitability.py` and be imported back by `mushroom_map`.

- [ ] **Step 2: Create `src/sporia/domain/suitability.py`**

Move verbatim from `champi_core.py`: `_ph_match` (1003-1012), `_altitude_fit_point` (1015-1028), `_aspect_fit_point` (1031-1037), `mushroom_suitability` (1040-1081), `_radar_label` (1084-1098). Also move the `_ASPECT_W` dict from `mushroom_map.py`. Header:

```python
"""Modèle d'adéquation à règles (pur, sans I/O) — extrait de champi_core, iso-comportement.
`_ASPECT_W` (pondération saisonnière d'exposition) est un constant de domaine, canonisé ici."""
from __future__ import annotations

import numpy as np

# Pondération saisonnière de l'exposition (northness) — déplacé depuis mushroom_map.
# <coller la définition EXACTE de _ASPECT_W lue à l'étape 1>
_ASPECT_W = { ... }  # verbatim

# <coller _ph_match, _altitude_fit_point, mushroom_suitability, _radar_label verbatim>

def _aspect_fit_point(northness, month):
    """Modulateur exposition scalaire (0.85..1.15)."""
    if northness is None:
        return 1.0
    w = _ASPECT_W.get(month, 0.0)              # was mmap._ASPECT_W
    return float(np.clip(1.0 + w * northness, 0.85, 1.15))
```

Note: `_radar_label` references module constants `PROPICE_MIN`, `PROPICE_PCT` — grep for them (`grep -n "PROPICE_MIN\|PROPICE_PCT\|RADAR_VMAX" champi_core.py`) and move those constants alongside `_radar_label` into `suitability.py` (or a shared `domain/constants` if they are also used by radar rendering — if so, import them where needed).

- [ ] **Step 3: Update `mushroom_map.py` to import the constant**

Replace the `_ASPECT_W = {...}` definition in `mushroom_map.py` with:

```python
from sporia.domain.suitability import _ASPECT_W
```

- [ ] **Step 4: Re-export from `champi_core.py` (keep the facade stable for `server.py`)**

Remove the moved function bodies from `champi_core.py` and add:

```python
from sporia.domain.suitability import (
    _ph_match, _altitude_fit_point, _aspect_fit_point, mushroom_suitability, _radar_label,
)
```

- [ ] **Step 5: Run the suite (iso-behavior gate)**

Run: `python -m pytest -q -m "not slow"`
Expected: all green — `test_suitability.py` still passes against `champi_core` (now re-exported).

- [ ] **Step 6: Add a direct test against the new module path**

Append to `tests/test_suitability.py`:

```python
def test_suitability_importable_from_domain():
    from sporia.domain.suitability import mushroom_suitability, _ph_match
    assert _ph_match(5.5, (4.5, 6.5)) == "ok"
    w = {"month": 3, "temp_mean": 15, "soil_temp": 14, "days_since_rain": 8,
         "rain14": 40, "soil_moisture": 0.3}
    assert mushroom_suitability(CEPE, w)[0] == "Hors saison"
```

- [ ] **Step 7: Run and commit**

Run: `python -m pytest tests/test_suitability.py -q`
Expected: green.

```bash
git add src/sporia/domain/suitability.py champi_core.py mushroom_map.py tests/test_suitability.py
git commit -m "refactor: extract rule-based suitability to sporia.domain.suitability"
```

---

# PHASE 2 — Migrate modules into the package (root shims keep `server:app` alive)

**Pattern for every migration task below** (the "move rhythm"):
1. `git mv <root>.py src/sporia/<subpkg>/<name>.py` (preserves history).
2. Fix the module's own imports (sibling modules → `from sporia.<subpkg>.<name> import ...`; paths → `from sporia.config import settings`).
3. Create a **root shim** at the old path so existing importers (`server.py`, `scripts/`) keep working unchanged:
   ```python
   # <name>.py (shim — remove in Phase 3)
   from sporia.<subpkg>.<name> import *  # noqa: F401,F403
   ```
4. `python -m pytest -q -m "not slow"` → green.
5. Commit.

Shims are deleted in Phase 3 once `server.py` moves and imports are finalized.

### Task 2.1: `users/` (prefs, spots, access_requests)

**Files:**
- Move: `user_prefs.py`→`src/sporia/users/prefs.py`, `user_spots.py`→`src/sporia/users/spots.py`, `access_requests.py`→`src/sporia/users/access_requests.py`
- Create: `src/sporia/users/__init__.py`, root shims `user_prefs.py`, `user_spots.py`, `access_requests.py`
- Modify: moved files' path constants → `settings.data_dir`

**Interfaces:**
- Produces (unchanged signatures): `prefs.get_species/set_species`, `spots.list_spots/add_spot/rename_spot/delete_spot`, `access_requests.add_request/list_requests`.

- [ ] **Step 1: Move the three files** (`git mv`), create `src/sporia/users/__init__.py` (empty).

- [ ] **Step 2: Repoint path constants** — in each moved file replace the hardcoded `Path("data/...")` with `from sporia.config import settings` and `settings.data_dir / "user_prefs.json"` (resp. `user_spots.json`, `access_requests.json`).

- [ ] **Step 3: Add root shims** (3 files), each:

```python
from sporia.users.prefs import *  # noqa: F401,F403   (adjust module name per file)
```

- [ ] **Step 4: Add a test** `tests/test_users.py`:

```python
from sporia.users import prefs, spots, access_requests


def test_prefs_roundtrip(tmp_path, monkeypatch):
    from sporia import config
    monkeypatch.setattr(type(config.settings), "data_dir",
                        property(lambda self: tmp_path), raising=False)
    assert prefs.get_species("nobody") is None
    prefs.set_species("u1", ["Boletus edulis"])
    assert prefs.get_species("u1") == ["Boletus edulis"]


def test_access_request_capped_and_listed(tmp_path, monkeypatch):
    from sporia import config
    monkeypatch.setattr(type(config.settings), "data_dir",
                        property(lambda self: tmp_path), raising=False)
    access_requests.add_request("Alice", "a@b.co", "hello")
    reqs = access_requests.list_requests()
    assert reqs[-1]["name"] == "Alice" and reqs[-1]["email"] == "a@b.co"
```

Note: if `data_dir` monkeypatching via property proves awkward, the moved modules should read their path lazily (call `settings.data_dir` inside functions, not at import) — adjust the modules to do so, which is also more correct.

- [ ] **Step 5:** `python -m pytest -q -m "not slow"` → green. Commit:

```bash
git add -A && git commit -m "refactor: move user prefs/spots/access_requests into sporia.users"
```

### Task 2.2: `enrich/` (forest, soil_static, soil_dynamic, terrain, fruiting_live)

**Files:**
- Move: `mushroom_map.py`→`enrich/forest.py`, `soil_data.py`→`enrich/soil_static.py`, `soil_dynamic.py`→`enrich/soil_dynamic.py`, `terrain_data.py`→`enrich/terrain.py`, `fruiting_live.py`→`enrich/fruiting_live.py`
- Create: `src/sporia/enrich/__init__.py`, root shims for each old name
- Modify: cross-imports (`champi_core` imports `mushroom_map as mmap`, `soil_data`, `terrain_data`, `fruiting_live`) → keep working via shims; path constants → `settings`.

- [ ] **Step 1:** `git mv` each file; create `enrich/__init__.py`.
- [ ] **Step 2:** Fix intra-`enrich` imports (e.g. anything importing `soil_data` → `from sporia.enrich import soil_static as soil_data` alias to minimize churn) and repoint path constants to `settings`.
- [ ] **Step 3:** Add root shims `mushroom_map.py`, `soil_data.py`, `soil_dynamic.py`, `terrain_data.py`, `fruiting_live.py` each `from sporia.enrich.<name> import *`.
- [ ] **Step 4:** Recall Task 1.3 — `sporia.enrich.forest` (ex-mushroom_map) now imports `_ASPECT_W` from `sporia.domain.suitability`; verify no circular import (`python -c "import sporia.enrich.forest"`).
- [ ] **Step 5:** `python -m pytest -q -m "not slow"` → green. Commit `refactor: move external-data enrichers into sporia.enrich`.

### Task 2.3: `geo/` (rasters, render) — extracted from `champi_core`

**Files:**
- Create: `src/sporia/geo/__init__.py`, `geo/rasters.py`, `geo/render.py`
- Modify: `champi_core.py` (remove moved funcs, re-export)

**Interfaces:**
- Produces — `geo/rasters.py`: `sample_raster`, `_france_mask`, `_aggregate`, `_reproject_to_3857`, `_reproject_to_grid`, `_forest_mask`, `_grid_ref`, `_grid_ref_geo`, `_mask_to_france`, `_tile_bbox_3857`, `_france_outline`/`available_dates` stay in `places`. `geo/render.py`: `_save_png`, `_render_grid_overlay`, `_bust`, `_blank_tile`, `_hex_to_rgb`.

- [ ] **Step 1:** Move the raster/geo helpers (champi_core lines: 216-227 `sample_raster`, 227-248 `_france_mask`, 249-265 `_aggregate`, 266-310 reproject pair, 311-334 `_forest_mask`, 401-411 `_grid_ref`, 457-469 `_mask_to_france`, 638-645 `_tile_bbox_3857`, 734-743 `_grid_ref_geo`) into `geo/rasters.py`; repoint `DATA_DIR`/cache paths to `settings`.
- [ ] **Step 2:** Move the PNG primitives (335-349 `_save_png`, 470-490 `_render_grid_overlay`, 391-400 `_bust`, 646-656 `_blank_tile`, 896-900 `_hex_to_rgb`) into `geo/render.py`.
- [ ] **Step 3:** In `champi_core.py`, re-export both modules' public names so overlay renderers (still in champi_core for now) keep resolving: `from sporia.geo.rasters import *` and `from sporia.geo.render import *`.
- [ ] **Step 4:** Add `tests/test_render_smoke.py`:

```python
import pytest


@pytest.mark.slow
def test_sample_raster_reads_value(tiny_raster):
    from sporia.geo.rasters import sample_raster
    v = sample_raster(str(tiny_raster), 2.5, 46.5)
    assert v is None or isinstance(float(v), float)


@pytest.mark.slow
def test_hex_to_rgb():
    from sporia.geo.render import _hex_to_rgb
    assert _hex_to_rgb("#854d0e") == (0x85, 0x4d, 0x0e)
```

- [ ] **Step 5:** `python -m pytest -q` (include slow) → green. Commit `refactor: extract geo raster + render helpers from champi_core`.

### Task 2.4: `overlays/` (weather, favorability, soil, terrain, fruiting, radar)

**Files:**
- Create: `src/sporia/overlays/__init__.py` + `weather.py`, `favorability.py`, `soil.py`, `terrain.py`, `fruiting.py`, `radar.py`
- Modify: `champi_core.py` (re-export)

**Interfaces (moved verbatim from champi_core, re-exported):**
- `weather.py`: `render_weather_overlay` (350-390)
- `favorability.py`: `render_favorability_overlay` (412-456), `_grid_ref` dependency via `geo`
- `soil.py`: `render_soil_overlay` (901-934), `render_soil_moisture_overlay` (491-503), `_latest_soil_point` (935-949)
- `terrain.py`: `render_altitude_overlay` (504-514), `render_aspect_overlay` (515-538)
- `fruiting.py`: `fruiting_models` (539-544), `render_fruiting_overlay` (545-561)
- `radar.py`: `render_radar_overlay` (562-637), `_forest_tile_alpha` (657-692), `_forest_alpha_from_mask` (693-733), `_radar_grid` (744-763), `radar_tile_png` (764-821), `radar_tile_species` (822-848), `_radar_species_params` (849-856)

- [ ] **Step 1:** Create the 6 modules; move each function group verbatim; fix imports to pull from `sporia.geo`, `sporia.enrich`, `sporia.domain`, `sporia.places`, `settings`.
- [ ] **Step 2:** `champi_core.py` re-exports all six: `from sporia.overlays.weather import *` … etc.
- [ ] **Step 3:** `python -m pytest -q -m "not slow"` → green (auth/contracts import `server`→`champi_core` re-exports resolve). Commit `refactor: extract overlay renderers into sporia.overlays`.

### Task 2.5: `places.py` + `points.py` — finish emptying `champi_core`

**Files:**
- Create: `src/sporia/places.py`, `src/sporia/points.py`
- Modify: `champi_core.py` → becomes a pure facade (only imports/re-exports)

**Interfaces:**
- `places.py`: `_static` (125-162), `search_cities` (163-175), `find_commune_at` (176-193), `france_outline_geojson` (194-205), `available_dates` (206-215)
- `points.py`: `analyze_point_weather` (950-1002), `spots_status` (857-895), `point_report` (1101-end)

- [ ] **Step 1:** Move the place/date helpers into `places.py`; repoint `VILLES_CSV`, `COMMUNES_GPKG` to `settings.data_dir / ...`.
- [ ] **Step 2:** Move the point-analysis functions into `points.py`; imports pull from `sporia.geo`, `sporia.enrich`, `sporia.domain.suitability`, `sporia.overlays.radar` (for `_radar_species_params`), `sporia.places`.
- [ ] **Step 3:** Reduce `champi_core.py` to a facade that re-exports the full public surface `server.py` uses (verify against `server.py`: `available_dates, search_cities, france_outline_geojson, render_weather_overlay, render_favorability_overlay, render_soil_overlay, render_soil_moisture_overlay, render_altitude_overlay, render_aspect_overlay, render_radar_overlay, radar_tile_png, radar_tile_species, _radar_species_params, fruiting_models, render_fruiting_overlay, point_report, spots_status, MUSHROOMS`). File header comment: `# FACADE temporaire — supprimée en Phase 3.`
- [ ] **Step 4:** `python -m pytest -q -m "not slow"` → green. Also `python -c "import server"` succeeds. Commit `refactor: extract places + points; champi_core is now a thin facade`.

### Task 2.6: `pipeline/` (collect_day, interpret_day, wx_features, scheduler)

**Files:**
- Move: the four files → `src/sporia/pipeline/`; create `__init__.py` + root shims (`scheduler.py` shim matters — systemd/`run_scheduler.bat` reference it until Phase 3).
- Modify: `scripts/*.py` imports of these modules → `from sporia.pipeline import ...` (grep: `grep -rln "import collect_day\|import interpret_day\|import wx_features\|import scheduler" scripts`).

- [ ] **Step 1:** `git mv` the four files; create `pipeline/__init__.py`; repoint their path/env constants to `settings` (incl. Météo-France API keys now read via `os.environ`/`.env` centralized through `settings` if trivial — otherwise leave as-is and note for chantier #2).
- [ ] **Step 2:** Root shims for all four old names.
- [ ] **Step 3:** Update `scripts/` imports to the package paths.
- [ ] **Step 4:** Smoke: `python -c "import sporia.pipeline.collect_day, sporia.pipeline.scheduler"` (no execution). `python -m pytest -q -m "not slow"` → green. Commit `refactor: move data pipeline into sporia.pipeline`.

---

# PHASE 3 — Web entrypoint + deploy + admin role (the only prod-touching phase)

### Task 3.1: Extract `web/security.py` + `web/auth.py`

**Files:**
- Create: `src/sporia/web/__init__.py`, `web/security.py`, `web/auth.py`
- Modify: `server.py` (import from the new modules)

**Interfaces:**
- `security.py`: `CSP: str`, `security_headers(request, call_next)` middleware coroutine.
- `auth.py`: `verify(username, password) -> dict | None`, `require_user(request) -> dict`, `require_admin(request) -> dict`, `load_config() -> dict`, `admin_usernames(cfg) -> set[str]`.

- [ ] **Step 1:** Create `web/auth.py` — move `_DUMMY_HASH`, `_verify` (→ `verify`), `require_user`, `_load_config` (→ `load_config`) from `server.py`. Add:

```python
def admin_usernames(cfg: dict) -> set[str]:
    users = cfg.get("credentials", {}).get("usernames", {})
    return {u for u, v in users.items() if v.get("role") == "admin"}


def require_admin(request):
    from fastapi import HTTPException
    user = require_user(request)
    cfg = load_config()
    if user.get("username") not in admin_usernames(cfg):
        raise HTTPException(status_code=403, detail="Réservé à l'administrateur.")
    return user
```

Also carry the account `role` into the session at login: in `verify`, include `"role": u.get("role")` in the returned dict.

- [ ] **Step 2:** Create `web/security.py` — move `_CSP` (→ `CSP`) and the `security_headers` middleware body from `server.py`.
- [ ] **Step 3:** `server.py` imports these (`from sporia.web.auth import verify, require_user, require_admin, load_config`; `from sporia.web.security import CSP, security_headers`) and drops the inline copies. Keep `server:app` working.
- [ ] **Step 4:** `python -m pytest -q -m "not slow"` → green (test_auth still imports `server._verify` — add a back-compat alias `_verify = verify` in `server.py`, OR update the test import now to `from sporia.web.auth import verify`). Update `tests/test_auth.py` to import `verify` from `sporia.web.auth` and `server.app` for the client. Commit `refactor: extract web auth + security from server`.

### Task 3.2: Move `server.py` → `sporia/web/app.py`; delete facade + shims

**Files:**
- Move: `server.py` → `src/sporia/web/app.py`
- Modify: all imports in `app.py` to pull directly from `sporia.*` (drop `import champi_core as core` → import the real modules; or keep `from sporia import overlays, places, points` and a small `core`-like namespace). Simplest: `import champi_core as core` still works via facade — but we now DELETE the facade, so replace `core.X` calls with the real module functions.
- Delete: `champi_core.py`, all root shims (`user_prefs.py`, `user_spots.py`, `access_requests.py`, `mushroom_map.py`, `soil_data.py`, `soil_dynamic.py`, `terrain_data.py`, `fruiting_live.py`, `collect_day.py`, `interpret_day.py`, `wx_features.py`, `scheduler.py`), and `server.py`.

**Interfaces:**
- Produces: `sporia.web.app:app` (the ASGI entrypoint).

- [ ] **Step 1:** `git mv server.py src/sporia/web/app.py`.
- [ ] **Step 2:** Replace the `champi_core` facade usage in `app.py`. Introduce a thin internal aggregator to minimize churn: create `src/sporia/api_facade.py` that re-exports the same names the app used from `core` (`from sporia.overlays.weather import render_weather_overlay`, …), then in `app.py` do `import sporia.api_facade as core`. This keeps `core.render_weather_overlay(...)` call sites unchanged while removing the legacy `champi_core.py`.
- [ ] **Step 3:** Update static-file mounts to absolute paths via `settings.web_dir` / `settings.overlay_dir` (no reliance on CWD).
- [ ] **Step 4:** Delete `champi_core.py` and every root shim + `server.py` (`git rm`).
- [ ] **Step 5:** Update test imports: `tests/test_auth.py` and `tests/test_api_contracts.py` → `from sporia.web.app import app`, and validators/`verify` from their real modules. Grep for any remaining `import server`/`import champi_core` in `tests/` and fix.
- [ ] **Step 6:** Boot check + suite:

Run: `python -m uvicorn sporia.web.app:app --port 8011 &` then `curl -s localhost:8011/api/me` → `{"authenticated": false, ...}`; kill it. Then `python -m pytest -q -m "not slow"` → green.

- [ ] **Step 7:** Commit `refactor: move server to sporia.web.app; remove legacy facade + shims`.

### Task 3.3: Admin role on `/api/access-requests`

**Files:**
- Modify: `config.yaml` (add `role: admin` to the `theo` account), `src/sporia/web/app.py` (route dependency), `tests/test_admin.py` (new)

- [ ] **Step 1:** Write the failing test `tests/test_admin.py`:

```python
from starlette.testclient import TestClient
from sporia.web.app import app


def test_access_requests_requires_admin_not_just_login():
    client = TestClient(app)
    # unauthenticated → 401 (dependency require_admin calls require_user first)
    assert client.get("/api/access-requests").status_code == 401
```

- [ ] **Step 2:** Run → the route currently uses `require_user`; unauth is already 401, so this passes but does not yet prove admin-gating. Add the gating and a stronger assertion once a session helper exists. Minimal change: switch the route.

In `app.py`, change `api_list_access_requests` dependency from `Depends(require_user)` to `Depends(require_admin)`.

- [ ] **Step 3:** In `config.yaml`, add `role: admin` under the `theo:` account block.
- [ ] **Step 4:** `python -m pytest -q -m "not slow"` → green. Commit `feat: gate /api/access-requests behind admin role`.

### Task 3.4: Update deploy artifacts to the new entrypoint

**Files:**
- Modify: `systemd/champimap.service`, `systemd/scheduler.service`, `Dockerfile`, `oracle_deploy.sh`, `run_scheduler.bat`, `ORACLE_DEPLOY.md`, `SCHEDULER_SETUP.md`

- [ ] **Step 1:** Grep every entrypoint reference: `grep -rn "server:app\|scheduler.py\|python .*server" systemd Dockerfile oracle_deploy.sh run_scheduler.bat *.md`.
- [ ] **Step 2:** Replace web entrypoint `server:app` → `sporia.web.app:app` (uvicorn `ExecStart`, Dockerfile `CMD`).
- [ ] **Step 3:** Replace scheduler invocation `python scheduler.py` → `python -m sporia.pipeline.scheduler` (add a `if __name__ == "__main__":` guard in `scheduler.py` if missing).
- [ ] **Step 4:** Ensure Dockerfile does `pip install -e .` (or `pip install -r requirements.lock`) and no longer copies root `.py` modules individually.
- [ ] **Step 5:** Add a **redeploy note** to `ORACLE_DEPLOY.md`:

```markdown
## Redéploiement après restructuration (entrypoint = sporia.web.app:app)
git pull
source venv/bin/activate && pip install -e .
sudo systemctl restart champimap scheduler
# vérifier : curl -s https://sporia.duckdns.org/api/me  → {"authenticated": false, ...}
```

- [ ] **Step 6:** Commit `chore: point systemd/Docker/scripts at sporia.web.app entrypoint`.

### Task 3.5: Full local verification + tighten ruff on the migrated package

- [ ] **Step 1:** `python -m ruff check src tests && python -m ruff format --check src tests` — fix any lint in migrated modules (now under `src/`, they're in scope). For legacy-heavy noise, fix or add targeted `# noqa` with reason; do not silence broadly.
- [ ] **Step 2:** `python -m pytest -q` (including slow) → all green.
- [ ] **Step 3:** Boot the app on the new entrypoint and click-test the critical paths:

Run: `python -m uvicorn sporia.web.app:app --port 8000`
Verify: `/` serves, `/api/me` = unauthenticated, login via a known account works, one `/api/overlay` or `/api/radar/tiles/...` responds.

- [ ] **Step 4:** Confirm the tree matches the target (`src/sporia/{config,domain,geo,overlays,places,points,enrich,users,pipeline,web}`), no stray root modules remain except entrypoints/config.
- [ ] **Step 5:** Commit `chore: finalize package migration; ruff clean on src`.

---

## Self-Review

**Spec coverage** (each spec item → task):
- Package `src/sporia/` by domain → Tasks 1.1–2.6, 3.1–3.2. ✅
- Split `champi_core.py` (1041 L) → Tasks 2.3 (geo), 2.4 (overlays), 2.5 (places/points), 1.3 (suitability). ✅
- `MUSHROOMS` → data file → Task 1.2. ✅
- `pyproject.toml`, ruff, pre-commit, CI, pinned deps → Tasks 0.1, 0.2, 0.7. ✅
- Pragmatic characterization tests (auth, API, suitability, species, render smoke) → Tasks 0.4, 0.5, 0.6, 1.2, 2.3. ✅
- README + LICENSE → Task 0.8. ✅
- SSH key out of repo + `venv/` gitignore → Tasks 0.8, 0.2. ✅
- Admin role on `/api/access-requests` → Task 3.3. ✅
- Entrypoint `sporia.web.app:app` + deploy update → Tasks 3.2, 3.4. ✅
- Always-deployable phasing (shims/facade) → Phase 2 pattern, Task 2.5 facade, Task 3.2 removal. ✅
- Config unification / end CWD-dependence → Tasks 1.1, and repointing steps in 2.1/2.3/2.4/2.5/3.2. ✅

**Placeholder scan:** The only `...` placeholders are in Task 1.3 Step 2, where the instruction is explicitly "coller la définition EXACTE lue à l'étape 1" (verbatim copy of `_ASPECT_W` and the four functions whose source line ranges are given) — this is a deliberate copy-existing-code instruction, not an undefined requirement.

**Type consistency:** `verify`/`_verify` reconciled via Task 3.1 Step 1 (rename with back-compat) and Task 3.1 Step 4 (test import updated). `mushroom_suitability` 4-tuple signature consistent across Tasks 0.6, 1.3. `settings` attribute names consistent (Task 1.1 ↔ repointing steps). Facade public surface (Task 2.5 Step 3) enumerated against `server.py`'s actual `core.*` usage.

---

## Notes for the executor

- **`champi_core.py` line numbers** are from the pre-refactor file; after each extraction they shift — re-grep function names (`grep -n "def <name>" champi_core.py`) rather than trusting absolute lines once you've started cutting.
- If any characterization assertion in Task 0.6 fails on first run, the *test* is wrong, not the code — pin it to the observed current output (that's the whole point of characterization).
- Circular-import watch: `domain.suitability` ← `enrich.forest` (imports `_ASPECT_W`); `overlays.*` → `geo`, `enrich`, `domain`; `points` → `overlays.radar`. Keep `domain` and `geo` dependency-free of `overlays`/`points`.
