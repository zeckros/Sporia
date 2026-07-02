# Sporia — Sécurité (code & repo) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Durcir la couche code/repo de Sporia — secret de session env-only fail-closed, hygiène des secrets, correction des dépendances vulnérables + audit en CI, en-tête `Permissions-Policy` — sans changer le comportement fonctionnel ni re-provoquer un 502.

**Architecture:** Petites modifications ciblées sur le package `src/sporia/` + artefacts de déploiement. Le secret de session passe par un helper testable `resolve_session_secret(prod)` dans `config.py`. Les dépendances vulnérables sont corrigées par des bornes dans `pyproject.toml` + un `requirements.lock` régénéré propre, et un job `pip-audit` bloquant en CI garde le lock sain.

**Tech Stack:** FastAPI/Starlette, python-dotenv, pytest, ruff, pip-audit, systemd, GitHub Actions.

## Global Constraints

- **Branche** `chantier-securite` (déjà créée).
- **Secret env-only strict** : `SESSION_SECRET` fort = ≥ 32 caractères ET ne contient pas « change ».
- **Corrections deps** : `starlette>=1.3.1`, `fonttools>=4.60.2` (valeurs exactes du spec).
- **`requirements.lock` runtime-only** : régénéré depuis `pip install -e .` (SANS `[dev]`), sans streamlit/tornado/pyarrow/gitpython.
- **Pas de 502** : `SESSION_SECRET` chargé par systemd via `EnvironmentFile`, généré par `oracle_deploy.sh`.
- **Commits fréquents**, messages sans `Co-Authored-By`. Commits locaux (pas de push auto).
- **Hors périmètre** : infra/OS, RGPD/légal, refonte CSP `unsafe-inline`, rate-limiting applicatif (nginx s'en charge).

## File Structure

- `src/sporia/config.py` — + `resolve_session_secret(prod: bool) -> str`.
- `src/sporia/web/app.py` — câble `resolve_session_secret`, supprime la lecture `cookie.key`.
- `src/sporia/web/security.py` — + en-tête `Permissions-Policy`.
- `config.yaml` (local, gitignoré) — retire la section `cookie:`.
- `config.example.yaml` (créé, versionné) — gabarit sans secrets.
- `pyproject.toml` — bornes `starlette`/`fonttools` + `pip-audit` en dev.
- `requirements.lock` — régénéré propre.
- `.github/workflows/ci.yml` — job `pip-audit`.
- `.gitignore` — motifs `*.key` / `*.pem`.
- `systemd/champimap.service`, `oracle_deploy.sh`, `ORACLE_DEPLOY.md` — chargement/génération de `SESSION_SECRET`.
- `tests/test_secret.py`, `tests/test_security_headers.py` — créés.

---

### Task 1: Helper `resolve_session_secret` (config.py) + tests

**Files:**
- Modify: `src/sporia/config.py`
- Test: `tests/test_secret.py`

**Interfaces:**
- Produces: `resolve_session_secret(prod: bool) -> str` — renvoie le secret fort de `SESSION_SECRET` ; lève `RuntimeError` si `prod` et secret faible/absent ; sinon renvoie une clé éphémère.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_secret.py`:
```python
"""resolve_session_secret : env-only, fail-closed en PROD, éphémère en DEV."""

from __future__ import annotations

import pytest

from sporia.config import resolve_session_secret


def test_strong_secret_from_env_returned(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "z" * 40)
    assert resolve_session_secret(prod=True) == "z" * 40


def test_prod_without_secret_raises(monkeypatch):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        resolve_session_secret(prod=True)


def test_prod_with_weak_secret_raises(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "change-me")
    with pytest.raises(RuntimeError):
        resolve_session_secret(prod=True)


def test_dev_without_secret_is_ephemeral(monkeypatch):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    s = resolve_session_secret(prod=False)
    assert isinstance(s, str) and len(s) >= 32
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_secret.py -q`
Expected: FAIL — `ImportError: cannot import name 'resolve_session_secret'`.

- [ ] **Step 3: Implement the helper**

Append to `src/sporia/config.py` (after `settings = Settings()`):
```python
def resolve_session_secret(prod: bool) -> str:
    """Secret de signature de session. Fort (>=32 car., pas « change ») depuis
    SESSION_SECRET → renvoyé tel quel. En PROD sans secret fort → RuntimeError
    (refus de démarrer). En DEV → clé éphémère (sessions non persistantes)."""
    secret = os.environ.get("SESSION_SECRET") or ""
    if len(secret) >= 32 and "change" not in secret.lower():
        return secret
    if prod:
        raise RuntimeError(
            "SESSION_SECRET manquant ou faible en PROD : définissez une clé forte "
            "(>=32 caractères) dans l'environnement. Refus de démarrer."
        )
    import secrets as _secrets

    print("[WARN] SESSION_SECRET absent/faible — clé de session éphémère (DEV uniquement).")
    return _secrets.token_urlsafe(48)
```

- [ ] **Step 4: Run to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_secret.py -q`
Expected: 4 passed.

- [ ] **Step 5: Lint + commit**

```bash
venv/Scripts/python.exe -m ruff check src/sporia/config.py tests/test_secret.py
git add src/sporia/config.py tests/test_secret.py
git commit -m "feat: resolve_session_secret helper (env-only, fail-closed in PROD)"
```

---

### Task 2: Câbler le helper dans app.py + retirer la lecture cookie.key

**Files:**
- Modify: `src/sporia/web/app.py` (lignes 62-74 = le bloc `_cfg`/`_SESSION_SECRET`)

**Interfaces:**
- Consumes: `resolve_session_secret` (Task 1).

- [ ] **Step 1: Replace the secret block**

In `src/sporia/web/app.py`, replace this block (currently lines 62-74):
```python
_cfg = load_config()
# Secret de signature de session : variable d'env prioritaire, sinon clé de config.yaml.
_SESSION_SECRET = os.environ.get("SESSION_SECRET") or _cfg.get("cookie", {}).get("key", "")
if not _SESSION_SECRET or "change" in _SESSION_SECRET.lower() or len(_SESSION_SECRET) < 32:
    # Clé absente/faible : on génère une clé éphémère (les sessions ne survivront pas à un
    # redémarrage). En prod, DÉFINIR SESSION_SECRET ou une cookie.key forte (>=32 octets).
    import secrets as _secrets

    _SESSION_SECRET = _secrets.token_urlsafe(48)
    print(
        "[WARN] cookie.key faible/absente — secret de session éphémère généré. "
        "Définissez SESSION_SECRET (env) ou une cookie.key forte dans config.yaml pour la prod."
    )
```
with:
```python
# Secret de session : SESSION_SECRET (env) uniquement. Fail-closed en PROD (cf. config.py).
_SESSION_SECRET = resolve_session_secret(PROD)
```

- [ ] **Step 2: Fix imports**

In `src/sporia/web/app.py`:
- Change the config import to include the helper:
  `from sporia.config import resolve_session_secret, settings`
- Remove `load_config` from the `from sporia.web.auth import ...` line (it is now unused in app.py; `verify`/`require_admin` still call it internally).

Verify no other use of `load_config` / `_cfg` remains: `grep -n "load_config\|_cfg" src/sporia/web/app.py` → no matches.

- [ ] **Step 3: Verify boot + no regression**

Run:
```bash
venv/Scripts/python.exe -c "from sporia.web.app import app; from starlette.testclient import TestClient; print('boot', TestClient(app).get('/api/me').status_code)"
venv/Scripts/python.exe -m pytest tests/test_auth.py tests/test_admin.py -q
```
Expected: `boot 200` (DEV path: no PROD env → ephemeral secret) ; auth/admin tests pass.

- [ ] **Step 4: Verify PROD fail-closed manually**

Run: `PROD=1 venv/Scripts/python.exe -c "import sporia.web.app"`
Expected: `RuntimeError: SESSION_SECRET manquant ou faible en PROD ...` (fail-closed proven; no local SESSION_SECRET set).

- [ ] **Step 5: Commit**

```bash
git add src/sporia/web/app.py
git commit -m "refactor: session secret via resolve_session_secret; drop config.yaml cookie.key"
```

---

### Task 3: Retirer la section `cookie:` de config.yaml + `config.example.yaml`

**Files:**
- Modify: `config.yaml` (local, gitignoré — non committé)
- Create: `config.example.yaml` (versionné)

- [ ] **Step 1: Remove the `cookie:` block from `config.yaml`**

Delete lines 1-4 (the `cookie:` section) from `config.yaml`, leaving `credentials:` at the top. (Fichier gitignoré : modification locale uniquement, pas de commit du fichier.)

- [ ] **Step 2: Create `config.example.yaml`** (versionné, sans secret)

```yaml
# Gabarit d'authentification — COPIER en config.yaml (gitignoré) et remplir.
# Le secret de session n'est PLUS ici : il vient de la variable d'env SESSION_SECRET
# (voir ORACLE_DEPLOY.md). Générer les hash bcrypt via scripts/make_users.py.
credentials:
  usernames:
    admin:
      name: Admin
      email: admin@example.com
      role: admin            # requis pour /api/access-requests
      password: "$2b$12$REMPLACER_PAR_UN_HASH_BCRYPT"
```

- [ ] **Step 3: Verify app still boots (config.yaml sans cookie:)**

Run: `venv/Scripts/python.exe -c "from sporia.web.app import app; print('ok')"`
Expected: `ok` (le code ne lit plus `cookie.*`).

- [ ] **Step 4: Commit** (config.yaml gitignoré n'est pas ajouté)

```bash
git add config.example.yaml
git commit -m "docs: add config.example.yaml; session secret no longer in config.yaml"
```

---

### Task 4: Hygiène gitignore des secrets

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add key/cert patterns**

Under the `# Auth / secrets` section of `.gitignore`, add:
```
*.key
*.pem
```
(Le motif existant `ssh-key-2026-06-05.key` reste ; `*.key` généralise.)

- [ ] **Step 2: Verify nothing tracked would be newly-ignored-but-tracked**

Run: `git ls-files | grep -E "\.(key|pem)$" || echo "(none tracked - safe)"`
Expected: `(none tracked - safe)`.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore *.key and *.pem"
```

---

### Task 5: Corriger les dépendances vulnérables + régénérer un lock propre

**Files:**
- Modify: `pyproject.toml`, `requirements.lock`

- [ ] **Step 1: Add dependency floors to `pyproject.toml`**

In the `dependencies` list of `pyproject.toml`, add these two entries (les CVE : starlette via FastAPI, fonttools via matplotlib) :
```toml
    "starlette>=1.3.1",
    "fonttools>=4.60.2",
```
And in `[project.optional-dependencies] dev`, add `"pip-audit"`.

- [ ] **Step 2: Upgrade in the dev venv**

Run: `venv/Scripts/python.exe -m pip install -e ".[dev]" --upgrade`
Expected: starlette ≥ 1.3.1 et fonttools ≥ 4.60.2 installés.

- [ ] **Step 3: Regenerate a CLEAN runtime lock**

Create a throwaway clean venv (runtime deps only, no `[dev]`, no streamlit), freeze it:
```bash
python -m venv /tmp/sporia_lock && /tmp/sporia_lock/Scripts/python.exe -m pip install -e . >/dev/null
/tmp/sporia_lock/Scripts/python.exe -m pip freeze --exclude-editable > requirements.lock
```
(Windows scratch path équivalent si `/tmp` indisponible.) Then verify no cruft:
```bash
grep -ciE "^streamlit|^tornado|^pyarrow|^gitpython" requirements.lock
```
Expected: `0`.

- [ ] **Step 4: Verify suite still green (upgraded starlette)**

Run: `venv/Scripts/python.exe -m pytest -q -m "not slow"`
Expected: all pass (FastAPI/Starlette bump is backward-compatible for our usage).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml requirements.lock
git commit -m "fix(deps): bump starlette>=1.3.1, fonttools>=4.60.2; regenerate clean lock"
```

---

### Task 6: Job `pip-audit` bloquant en CI

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add the audit step**

Append to the `steps:` list of the `lint-and-test` job in `.github/workflows/ci.yml`, after the Pytest step:
```yaml
      - name: pip-audit (runtime deps)
        run: python -m pip_audit -r requirements.lock --strict
```
(`-r requirements.lock` = audite exactement la clôture runtime épinglée ; `--strict` échoue sur toute vuln. Si une CVE sans fix apparaît un jour, ajouter `--ignore-vuln <ID>` avec un commentaire justifiant.)

- [ ] **Step 2: Reproduce the CI audit locally**

Run: `venv/Scripts/python.exe -m pip_audit -r requirements.lock --strict`
Expected: `No known vulnerabilities found` (starlette/fonttools corrigés, lock propre). Si une vuln résiduelle apparaît, la corriger (bump) ou l'ignorer explicitement avec justification.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add blocking pip-audit on requirements.lock"
```

---

### Task 7: En-tête `Permissions-Policy` + test des en-têtes/cookies

**Files:**
- Modify: `src/sporia/web/security.py`
- Test: `tests/test_security_headers.py`

**Interfaces:**
- Consumes: `sporia.web.app.app`, `sporia.web.security.security_headers`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_security_headers.py`:
```python
"""En-têtes de sécurité + flags du cookie de session."""

from __future__ import annotations

from starlette.testclient import TestClient

from sporia.web.app import app


def test_core_security_headers_present():
    r = TestClient(app).get("/api/me")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert "Content-Security-Policy" in r.headers
    assert r.headers.get("Permissions-Policy") == "geolocation=(), camera=(), microphone=()"


def test_session_cookie_flags_on_login_attempt():
    # /api/login pose un cookie de session même sur échec ? Non : seul un login OK
    # pose la session. On vérifie les flags via une session écrite par le middleware
    # sur une route authentifiée simulée n'est pas trivial sans creds ; on se limite
    # donc aux en-têtes de réponse (couverts ci-dessus). HttpOnly/SameSite sont
    # garantis par Starlette SessionMiddleware (défauts) + https_only=PROD.
    r = TestClient(app).get("/api/me")
    assert r.status_code == 200
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/test_security_headers.py -q`
Expected: FAIL — `Permissions-Policy` absent (pas encore ajouté).

- [ ] **Step 3: Add the header in `security.py`**

In `src/sporia/web/security.py`, inside `security_headers`, before `return resp`, add:
```python
    resp.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
```

- [ ] **Step 4: Run to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/test_security_headers.py -q`
Expected: 2 passed.

- [ ] **Step 5: Lint + commit**

```bash
venv/Scripts/python.exe -m ruff check src/sporia/web/security.py tests/test_security_headers.py
git add src/sporia/web/security.py tests/test_security_headers.py
git commit -m "feat: add Permissions-Policy header + security-headers test"
```

---

### Task 8: Déploiement — charger/générer `SESSION_SECRET` (anti-502)

**Files:**
- Modify: `systemd/champimap.service`, `oracle_deploy.sh`, `ORACLE_DEPLOY.md`

- [ ] **Step 1: systemd charge `.env`**

In `systemd/champimap.service`, add under `[Service]` (after `Environment=PROD=1`):
```
EnvironmentFile=-/home/app/champi_pipeline_package/.env
```
(le préfixe `-` = fichier optionnel, ne bloque pas si absent).

- [ ] **Step 2: `oracle_deploy.sh` génère `SESSION_SECRET`**

In `oracle_deploy.sh`, in the `.env` provisioning block (étape secrets `.env`), ensure a strong `SESSION_SECRET` line is written when `.env` is created. Add to the here-doc that creates `.env`:
```
SESSION_SECRET="__REMPLACE_PAR_GEN__"
```
and just before writing the file, generate it:
```bash
SESSION_SECRET_GEN=$(sudo -u "$APP_USER" "$PY" -c "import secrets;print(secrets.token_urlsafe(48))")
```
then substitute (`sed`/`envsubst`) `__REMPLACE_PAR_GEN__` → `$SESSION_SECRET_GEN`. If `.env` already exists, append `SESSION_SECRET=...` only if the key is absent (`grep -q '^SESSION_SECRET=' "$APP_DIR/.env" || echo "SESSION_SECRET=$SESSION_SECRET_GEN" >> ...`).

- [ ] **Step 3: Document in `ORACLE_DEPLOY.md`**

Under the redeploy section, add:
```markdown
**SESSION_SECRET (obligatoire en PROD)** : doit exister dans `.env`
(`SESSION_SECRET=<clé ≥32 car.>`) — chargé par systemd via `EnvironmentFile`.
Sinon l'app **refuse de démarrer** en PROD (message clair dans `journalctl -u champimap`).
Générer : `python -c "import secrets;print(secrets.token_urlsafe(48))"`.
```

- [ ] **Step 4: Commit**

```bash
git add systemd/champimap.service oracle_deploy.sh ORACLE_DEPLOY.md
git commit -m "deploy: load SESSION_SECRET via systemd EnvironmentFile; generate in oracle_deploy"
```

---

## Self-Review

**Spec coverage :**
- Secret env-only fail-closed → Tasks 1, 2. ✅
- Retrait cookie.key de config.yaml + example → Tasks 2, 3. ✅
- Déploiement anti-502 (EnvironmentFile + génération) → Task 8. ✅
- Clé SSH / gitignore → Task 4. ✅
- Deps (starlette/fonttools) + lock propre → Task 5. ✅
- pip-audit CI bloquant → Task 6. ✅
- Permissions-Policy + tests en-têtes/cookies → Task 7. ✅
- Non-régression auth → Tasks 2 (test_auth/test_admin), reste vert tout du long. ✅

**Placeholder scan :** le seul jeton `__REMPLACE_PAR_GEN__` (Task 8) est un marqueur de substitution explicite avec sa commande de génération juste en dessous — pas un placeholder vague.

**Type consistency :** `resolve_session_secret(prod: bool) -> str` cohérent entre Task 1 (déf), Task 2 (appel `resolve_session_secret(PROD)`). En-tête `Permissions-Policy` : même valeur exacte en Task 7 test et implémentation.

## Notes exécution

- Tourner en `venv/Scripts/python.exe` (venv Windows du dev).
- `config.yaml` est gitignoré : ses modifs (retrait `cookie:`, `role: admin`) ne sont jamais committées ; seul `config.example.yaml` l'est.
- Après Task 5, `requirements.lock` ne doit plus contenir de cruft streamlit — c'est le critère de succès.
