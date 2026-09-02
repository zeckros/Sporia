# Comptes bêta-testeurs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Une demande d'accès acceptée crée un compte débloqué gratuitement, et un écran admin permet de basculer n'importe quel compte en bêta.

**Architecture:** L'accès bêta est la valeur `'beta'` de la colonne `subscription_status` (déjà en TEXT, aucune migration). `billing.has_access` l'accepte au même titre que `'active'`. Deux endpoints admin (liste + bascule) alimentent une nouvelle modale « Comptes », et `/api/me` expose un champ `access` qui pilote l'affichage « Accès bêta — offert ».

**Tech Stack:** FastAPI, SQLite (`sporia.users.accounts`), pytest + `starlette.testclient`, Jinja2 partials, JS modules ES, Tailwind CLI.

**Spec:** `docs/superpowers/specs/2026-09-02-comptes-beta-testeurs-design.md`

## Global Constraints

- Tests : `venv/Scripts/python.exe -m pytest` (Windows). Suite verte avant chaque commit.
- Hooks pre-commit actifs (ruff check + format, end-of-file-fixer, large files > 1024 Ko refusés).
- Commits **sans** ligne `Co-Authored-By`.
- Messages de commit et libellés d'interface en français.
- Statuts d'accès admis pour la bascule : exactement `"beta"` et `"none"`.
- La liste des comptes ne doit **jamais** exposer `password_hash` ni `stripe_customer_id`.
- Après toute modification de classes Tailwind dans `web/js/**` ou `src/sporia/web/templates/**`, régénérer le CSS : `bash scripts/build-css.sh`.
- Toute modification de `web/js/**` ou `web/css/**` impose de monter le cache-bust `?v=` dans `src/sporia/web/templates/index.html` (actuellement `v=82` → `v=83`).

---

### Task 1 : `has_access` accepte le statut bêta

**Files:**
- Modify: `src/sporia/billing.py:36-45`
- Test: `tests/test_beta_access.py` (créer)

**Interfaces:**
- Consumes: rien.
- Produces: `billing.has_access(account: dict | None) -> bool` renvoie `True` quand `account["subscription_status"] == "beta"`. Toutes les tâches suivantes en dépendent.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/test_beta_access.py` :

```python
"""Accès bêta : statut 'beta' débloquant, endpoints admin, exposition dans /api/me."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


def test_has_access_true_for_beta():
    from sporia import billing

    assert billing.has_access({"role": "user", "subscription_status": "beta"}) is True


def test_has_access_still_true_for_active():
    from sporia import billing

    assert billing.has_access({"role": "user", "subscription_status": "active"}) is True


def test_has_access_false_for_none():
    from sporia import billing

    assert billing.has_access({"role": "user", "subscription_status": "none"}) is False
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `venv/Scripts/python.exe -m pytest tests/test_beta_access.py -v`
Expected: `test_has_access_true_for_beta` FAIL (`assert False is True`). Les deux autres passent déjà.

- [ ] **Step 3: Implémenter**

Dans `src/sporia/billing.py`, remplacer :

```python
    if account.get("subscription_status") == "active":
        return True
```

par :

```python
    # 'beta' = accès offert accordé par un admin (bêta-testeur), sans passage par Stripe.
    if account.get("subscription_status") in ("active", "beta"):
        return True
```

- [ ] **Step 4: Lancer le test, vérifier le succès**

Run: `venv/Scripts/python.exe -m pytest tests/test_beta_access.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sporia/billing.py tests/test_beta_access.py
git commit -m "feat(beta): has_access accepte le statut beta"
```

---

### Task 2 : Une demande acceptée crée un compte bêta

**Files:**
- Modify: `src/sporia/web/app.py:574-604` (`api_create_account_from_request`)
- Test: `tests/test_beta_access.py`

**Interfaces:**
- Consumes: `billing.has_access` (Task 1), `accounts.set_subscription(user_id: int, status: str, current_period_end: int | None = None) -> None` (existant).
- Produces: après `POST /api/admin/accounts/from-request`, le compte créé a `subscription_status == "beta"`.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter en tête de `tests/test_beta_access.py`, après les imports, la fixture et les deux helpers (ils resserviront aux tâches 4 et 5) :

```python
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORIA_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)

    import sporia.users.accounts as acc

    importlib.reload(acc)
    acc.init_db()
    import sporia.billing as billing

    importlib.reload(billing)
    import sporia.web.app as webapp

    importlib.reload(webapp)
    # `settings.data_dir` n'est pas configurable par l'environnement : sans ce patch,
    # les demandes d'accès des tests s'écriraient dans le data/ du dépôt.
    import sporia.users.access_requests as areq

    monkeypatch.setattr(areq, "_path", lambda: tmp_path / "access_requests.json")
    return TestClient(webapp.app), acc, webapp


def _login(client, acc, email, password="password123", role="user"):
    acc.create_user(email, password, name="U", role=role)
    r = client.post("/api/login", json={"username": email, "password": password})
    assert r.status_code == 200, r.text
```

Puis le test :

```python
def test_account_from_request_is_beta(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    from sporia.users import access_requests

    req = access_requests.add_request("Testeur", "testeur@sporia.fr", "Je veux tester")
    r = c.post("/api/admin/accounts/from-request", json={"request_id": req["id"]})
    assert r.status_code == 200, r.text
    created = acc.get_by_email("testeur@sporia.fr")
    assert created["subscription_status"] == "beta"


def test_beta_account_passes_the_paywall(client):
    """Le test qui compte vraiment : la barrière 402 s'ouvre pour un bêta."""
    c, acc, webapp = client
    _login(c, acc, "testeur@sporia.fr")
    assert c.get("/api/dates").status_code == 402

    compte = acc.get_by_email("testeur@sporia.fr")
    acc.set_subscription(compte["id"], "beta")
    assert c.get("/api/dates").status_code == 200
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `venv/Scripts/python.exe -m pytest tests/test_beta_access.py::test_account_from_request_is_beta -v`
Expected: FAIL — `assert 'none' == 'beta'`.

- [ ] **Step 3: Implémenter**

Dans `src/sporia/web/app.py`, après le bloc `try/except` qui crée `acc` et avant `token = accounts.create_token(...)` :

```python
    # Une demande acceptée = un bêta-testeur : accès offert, sans passage par le paywall.
    accounts.set_subscription(acc["id"], "beta")
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `venv/Scripts/python.exe -m pytest tests/test_beta_access.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sporia/web/app.py tests/test_beta_access.py
git commit -m "feat(beta): une demande acceptee cree un compte debloque"
```

---

### Task 3 : Lecture des comptes dans le store

**Files:**
- Modify: `src/sporia/users/accounts.py` (ajout après `get_by_email`, vers la ligne 78)
- Test: `tests/test_beta_access.py`

**Interfaces:**
- Consumes: `accounts._connect()`, `accounts.init_db()` (existants).
- Produces: `accounts.list_accounts(limit: int = 500) -> tuple[list[dict], bool]` — `(comptes, truncated)`, du plus récent au plus ancien. Chaque dict contient exactement `id`, `email`, `name`, `role`, `subscription_status`, `current_period_end`, `created_at`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
def test_list_accounts_excludes_secrets_and_sorts_recent_first(client):
    c, acc, webapp = client
    acc.create_user("premier@sporia.fr", "password123", name="Premier")
    acc.create_user("second@sporia.fr", "password123", name="Second")
    rows, truncated = acc.list_accounts()
    assert truncated is False
    assert [r["email"] for r in rows][:2] == ["second@sporia.fr", "premier@sporia.fr"]
    assert set(rows[0]) == {
        "id", "email", "name", "role", "subscription_status",
        "current_period_end", "created_at",
    }


def test_list_accounts_flags_truncation(client):
    c, acc, webapp = client
    for i in range(3):
        acc.create_user(f"u{i}@sporia.fr", "password123")
    rows, truncated = acc.list_accounts(limit=2)
    assert len(rows) == 2
    assert truncated is True
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `venv/Scripts/python.exe -m pytest tests/test_beta_access.py -k list_accounts -v`
Expected: FAIL — `AttributeError: module 'sporia.users.accounts' has no attribute 'list_accounts'`.

- [ ] **Step 3: Implémenter**

Dans `src/sporia/users/accounts.py`, après `get_by_email` :

```python
def list_accounts(limit: int = 500) -> tuple[list[dict], bool]:
    """Comptes du plus récent au plus ancien. Renvoie (liste, truncated).

    Ne sélectionne jamais password_hash ni stripe_customer_id : cette liste part
    vers le navigateur d'un admin. `truncated` dit explicitement que le plafond a
    été atteint, plutôt que de laisser croire que la liste est complète."""
    init_db()
    with _connect() as c:
        rows = c.execute(
            "SELECT id,email,name,role,subscription_status,current_period_end,created_at "
            "FROM users ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit + 1,),
        ).fetchall()
    return [dict(r) for r in rows[:limit]], len(rows) > limit
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `venv/Scripts/python.exe -m pytest tests/test_beta_access.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/sporia/users/accounts.py tests/test_beta_access.py
git commit -m "feat(beta): accounts.list_accounts sans secrets, avec drapeau truncated"
```

---

### Task 4 : Endpoints admin — liste et bascule

**Files:**
- Modify: `src/sporia/web/app.py` (après `api_delete_access_request`, vers la ligne 612)
- Test: `tests/test_beta_access.py`

**Interfaces:**
- Consumes: `accounts.list_accounts` (Task 3), `accounts.set_subscription`, `accounts.get_by_email`, `require_admin`, `_valid_email` (existants dans `app.py`).
- Produces:
  - `GET /api/admin/accounts` → `{"accounts": [...], "truncated": bool}`
  - `POST /api/admin/accounts/access` corps `{"email": str, "status": "beta" | "none"}` → `{"ok": True, "email": str, "status": str}`

- [ ] **Step 1: Écrire les tests qui échouent**

```python
def test_admin_accounts_requires_admin(client):
    c, acc, webapp = client
    _login(c, acc, "simple@sporia.fr")
    assert c.get("/api/admin/accounts").status_code == 403


def test_admin_accounts_lists_without_secrets(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    r = c.get("/api/admin/accounts")
    assert r.status_code == 200
    body = r.json()
    assert body["truncated"] is False
    assert "password_hash" not in body["accounts"][0]
    assert "stripe_customer_id" not in body["accounts"][0]


def test_set_access_toggles_beta_then_back(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    acc.create_user("testeur@sporia.fr", "password123")

    r = c.post("/api/admin/accounts/access",
               json={"email": "testeur@sporia.fr", "status": "beta"})
    assert r.status_code == 200, r.text
    assert acc.get_by_email("testeur@sporia.fr")["subscription_status"] == "beta"

    r = c.post("/api/admin/accounts/access",
               json={"email": "testeur@sporia.fr", "status": "none"})
    assert r.status_code == 200
    assert acc.get_by_email("testeur@sporia.fr")["subscription_status"] == "none"


def test_set_access_unknown_email_404(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    r = c.post("/api/admin/accounts/access",
               json={"email": "inconnu@sporia.fr", "status": "beta"})
    assert r.status_code == 404


def test_set_access_refuses_admin_account_409(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    acc.create_user("autre-admin@sporia.fr", "password123", role="admin")
    r = c.post("/api/admin/accounts/access",
               json={"email": "autre-admin@sporia.fr", "status": "beta"})
    assert r.status_code == 409


def test_set_access_refuses_paying_account_409(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    payant = acc.create_user("payant@sporia.fr", "password123")
    acc.set_subscription(payant["id"], "active")
    r = c.post("/api/admin/accounts/access",
               json={"email": "payant@sporia.fr", "status": "beta"})
    assert r.status_code == 409


def test_set_access_rejects_invalid_status_400(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    acc.create_user("testeur@sporia.fr", "password123")
    r = c.post("/api/admin/accounts/access",
               json={"email": "testeur@sporia.fr", "status": "admin"})
    assert r.status_code == 400
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `venv/Scripts/python.exe -m pytest tests/test_beta_access.py -k "admin_accounts or set_access" -v`
Expected: 7 FAIL en 404 (routes inexistantes).

- [ ] **Step 3: Implémenter**

Dans `src/sporia/web/app.py`, après `api_delete_access_request` :

```python
class AccountAccessIn(BaseModel):
    email: str
    status: str


@app.get("/api/admin/accounts")
def api_admin_accounts(user=Depends(require_admin)):
    """Liste des comptes pour l'écran d'administration — RÉSERVÉ ADMIN."""
    items, truncated = accounts.list_accounts()
    return {"accounts": items, "truncated": truncated}


@app.post("/api/admin/accounts/access")
def api_admin_set_access(body: AccountAccessIn, user=Depends(require_admin)):
    """Accorde ou retire l'accès bêta d'un compte — RÉSERVÉ ADMIN.

    Refuse les comptes admin (le rôle donne déjà l'accès) et les comptes à
    abonnement Stripe actif (leur statut appartient à Stripe, pas à cet écran)."""
    status = (body.status or "").strip()
    if status not in ("beta", "none"):
        raise HTTPException(status_code=400, detail="Statut invalide (beta ou none).")
    account = accounts.get_by_email(_valid_email(body.email))
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    if account.get("role") == "admin":
        raise HTTPException(status_code=409, detail="Un compte admin a déjà l'accès complet.")
    if account.get("subscription_status") == "active":
        raise HTTPException(
            status_code=409, detail="Abonnement Stripe actif : statut géré par Stripe."
        )
    accounts.set_subscription(account["id"], status)
    return {"ok": True, "email": account["email"], "status": status}
```

- [ ] **Step 4: Lancer la suite complète, vérifier le succès**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: 14 tests dans `test_beta_access.py`, suite entièrement verte.

- [ ] **Step 5: Commit**

```bash
git add src/sporia/web/app.py tests/test_beta_access.py
git commit -m "feat(beta): endpoints admin liste des comptes et bascule d acces"
```

---

### Task 5 : `/api/me` expose le type d'accès

**Files:**
- Modify: `src/sporia/web/app.py:146-156` (`me`) + ajout d'un helper juste au-dessus
- Test: `tests/test_beta_access.py`

**Interfaces:**
- Consumes: `billing.has_access` (Task 1).
- Produces: `/api/me` renvoie en plus `"access"` ∈ `{"admin", "beta", "paid", "none"}`. Le champ `subscribed` est **conservé inchangé** — le frontend existant continue de fonctionner.

- [ ] **Step 1: Écrire les tests qui échouent**

```python
def test_me_access_none_then_beta(client):
    c, acc, webapp = client
    _login(c, acc, "testeur@sporia.fr")
    assert c.get("/api/me").json()["access"] == "none"

    compte = acc.get_by_email("testeur@sporia.fr")
    acc.set_subscription(compte["id"], "beta")
    body = c.get("/api/me").json()
    assert body["access"] == "beta"
    assert body["subscribed"] is True


def test_me_access_admin(client):
    c, acc, webapp = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    assert c.get("/api/me").json()["access"] == "admin"


def test_me_access_paid(client):
    c, acc, webapp = client
    _login(c, acc, "payant@sporia.fr")
    compte = acc.get_by_email("payant@sporia.fr")
    acc.set_subscription(compte["id"], "active")
    assert c.get("/api/me").json()["access"] == "paid"


def test_me_access_none_when_anonymous(client):
    c, acc, webapp = client
    assert c.get("/api/me").json()["access"] == "none"
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `venv/Scripts/python.exe -m pytest tests/test_beta_access.py -k me_access -v`
Expected: 4 FAIL — `KeyError: 'access'`.

- [ ] **Step 3: Implémenter**

Dans `src/sporia/web/app.py`, juste avant `@app.get("/api/me")` :

```python
def _access_kind(account: dict | None) -> str:
    """Nature de l'accès, pour l'affichage seul. La barrière reste has_access."""
    if account is None:
        return "none"
    if account.get("role") == "admin":
        return "admin"
    if account.get("subscription_status") == "beta":
        return "beta"
    return "paid" if billing.has_access(account) else "none"
```

Puis ajouter la clé dans le dict renvoyé par `me`, après `"role"` :

```python
        "access": _access_kind(account),
```

- [ ] **Step 4: Lancer la suite complète, vérifier le succès**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: 18 tests dans `test_beta_access.py`, suite entièrement verte.

- [ ] **Step 5: Commit**

```bash
git add src/sporia/web/app.py tests/test_beta_access.py
git commit -m "feat(beta): /api/me expose le type d acces"
```

---

### Task 6 : Interface — modale « Comptes » et mention « Accès bêta »

**Files:**
- Modify: `src/sporia/web/templates/partials/modals.html` (ajouter la modale en fin de fichier)
- Modify: `src/sporia/web/templates/partials/app.html` (entrées de menu)
- Modify: `web/js/main.js` (ouverture, rendu, bascule, mention bêta)
- Modify: `src/sporia/web/templates/index.html` (cache-bust `v=82` → `v=83`)
- Modify: `web/css/tailwind.css` (régénéré, jamais édité à la main)

**Interfaces:**
- Consumes: `GET /api/admin/accounts` et `POST /api/admin/accounts/access` (Task 4), champ `access` de `/api/me` (Task 5), `API` et `escapeHtml` (`web/js/util.js`).
- Produces: aucune interface consommée par une tâche ultérieure.

Cette tâche n'a pas de test automatisé : le dépôt ne teste pas le DOM. Elle se valide par la checklist manuelle de l'étape 6.

- [ ] **Step 1: Ajouter la modale**

À la fin de `src/sporia/web/templates/partials/modals.html`, en calquant la modale « Demandes d'accès » :

```html
  <!-- ============ MODALE « Comptes » (admin) ============ -->
  <div id="accounts-modal" class="hidden fixed inset-0 z-[2000] flex items-center justify-center p-4">
    <div id="acct-backdrop" class="absolute inset-0 bg-sousbois/80"></div>
    <div class="relative bg-sousbois text-os rounded-sm shadow-lg2 border border-os/10 w-full max-w-2xl max-h-[85vh] flex flex-col">
      <div class="flex items-start justify-between p-5 border-b border-os/10">
        <div>
          <div class="font-black text-lg text-os">Comptes</div>
          <div class="text-xs text-os/60">Accorder ou retirer l'accès bêta.</div>
        </div>
        <button id="acct-close" class="text-os/40 hover:text-os text-xl leading-none">&times;</button>
      </div>
      <div class="px-5 pt-4">
        <input id="acct-filter" type="text" placeholder="Filtrer par email ou nom…"
               class="w-full px-3 py-2 rounded-sm bg-transparent text-os placeholder:text-os/40 border border-os/20 focus:border-girolle focus:ring-2 focus:ring-girolle/30 outline-none text-sm" />
      </div>
      <div id="acct-list" class="flex-1 overflow-y-auto nice-scroll p-5 flex flex-col gap-2"></div>
    </div>
  </div>
```

- [ ] **Step 2: Ajouter les entrées de menu**

Dans `src/sporia/web/templates/partials/app.html`, juste après le bouton `#admin-requests-btn` :

```html
            <button id="admin-accounts-btn" class="admin-only hidden w-full text-left px-3 py-2 rounded-sm text-sm font-semibold text-girolle hover:bg-os/10 transition">👥 Comptes</button>
```

Et dans le panneau profil mobile, juste après le bouton `.profil-act` qui cible `admin-requests-btn` :

```html
          <button class="profil-act admin-only hidden w-full text-left px-4 py-3 rounded-sm bg-os/5 border border-os/10 font-semibold text-girolle hover:bg-os/10 transition" data-target="admin-accounts-btn">👥 Comptes</button>
```

Ajouter enfin, juste après le bouton `#manage-sub`, la mention réservée aux bêta-testeurs :

```html
            <div id="beta-badge" class="hidden px-3 py-2 text-sm font-semibold text-girolle">Accès bêta — offert</div>
```

- [ ] **Step 3: Câbler le JS**

Dans `web/js/main.js`, à côté de la ligne qui câble `admin-requests-btn` (vers la ligne 783) :

```js
  document.getElementById("admin-accounts-btn")?.addEventListener("click", openAccounts);
  document.getElementById("acct-close")?.addEventListener("click", closeAccounts);
  document.getElementById("acct-backdrop")?.addEventListener("click", closeAccounts);
  document.getElementById("acct-filter")?.addEventListener("input", (e) => {
    renderAccounts(state.accounts || [], e.target.value);
  });
```

Puis, après `renderAccessRequests`, ajouter le bloc complet :

```js
/* ---------- Comptes (admin) ---------- */
const ACCESS_LABEL = {
  admin: ["Admin", "text-girolle"],
  beta: ["Bêta — offert", "text-green-300"],
  active: ["Abonné", "text-green-300"],
  none: ["Aucun accès", "text-os/50"],
};

function accountKind(a) {
  if (a.role === "admin") return "admin";
  if (a.subscription_status === "beta") return "beta";
  if (a.subscription_status === "active") return "active";
  return "none";
}

async function openAccounts() {
  const list = document.getElementById("acct-list");
  list.innerHTML = `<div class="text-sm text-os/50 text-center py-6">Chargement…</div>`;
  document.getElementById("accounts-modal").classList.remove("hidden");
  try {
    const r = await API.get("/api/admin/accounts");
    state.accounts = r.accounts || [];
    state.accountsTruncated = !!r.truncated;
    renderAccounts(state.accounts, document.getElementById("acct-filter").value);
  } catch (e) {
    list.innerHTML = `<div class="text-sm text-red-400 text-center py-6">Erreur de chargement.</div>`;
  }
}

function closeAccounts() {
  document.getElementById("accounts-modal").classList.add("hidden");
}

function renderAccounts(accounts, filter) {
  const list = document.getElementById("acct-list");
  const q = (filter || "").trim().toLowerCase();
  const rows = q
    ? accounts.filter((a) => `${a.email} ${a.name || ""}`.toLowerCase().includes(q))
    : accounts;
  if (!rows.length) {
    list.innerHTML = `<div class="text-sm text-os/50 text-center py-6">Aucun compte.</div>`;
    return;
  }
  const banner = state.accountsTruncated
    ? `<div class="text-xs text-amber-300 pb-2">Liste plafonnée aux 500 comptes les plus récents.</div>`
    : "";
  list.innerHTML = banner + rows.map((a) => {
    const kind = accountKind(a);
    const [label, cls] = ACCESS_LABEL[kind];
    const date = a.created_at ? new Date(a.created_at * 1000).toLocaleDateString("fr-FR") : "";
    const locked = kind === "admin" || kind === "active";
    const btn = locked
      ? `<span class="text-[11px] text-os/40 shrink-0" title="${kind === "admin" ? "Le rôle admin donne déjà l'accès." : "Statut géré par Stripe."}">non modifiable</span>`
      : `<button class="acct-toggle px-3 py-1.5 rounded-sm bg-girolle hover:bg-lactaire text-sousbois text-xs font-bold shadow-card transition shrink-0" data-next="${kind === "beta" ? "none" : "beta"}">${kind === "beta" ? "Retirer la bêta" : "Passer en bêta"}</button>`;
    return `<div class="rounded-sm border border-os/10 bg-os/5 p-3 flex items-center justify-between gap-3" data-email="${escapeHtml(a.email)}">
      <div class="min-w-0">
        <div class="font-semibold text-sm text-os truncate">${escapeHtml(a.name || a.email)}</div>
        <div class="text-xs text-os/60 truncate">${escapeHtml(a.email)}</div>
        <div class="text-[11px] mt-0.5 ${cls}">${label}${date ? ` · inscrit le ${date}` : ""}</div>
      </div>
      ${btn}
    </div>`;
  }).join("");
  list.querySelectorAll(".acct-toggle").forEach((b) => {
    b.addEventListener("click", () => toggleAccountAccess(b));
  });
}

async function toggleAccountAccess(btn) {
  const email = btn.closest("[data-email]").dataset.email;
  btn.disabled = true;
  try {
    await API.post("/api/admin/accounts/access", { email, status: btn.dataset.next });
    await openAccounts();   // recharge : le statut vient toujours du serveur
  } catch (e) {
    btn.disabled = false;
    alert(e.message || "Bascule impossible.");
  }
}
```

- [ ] **Step 4: Afficher la mention bêta au lieu de « Mon abonnement »**

Dans `web/js/main.js`, remplacer la ligne 286 :

```js
  document.getElementById("manage-sub")?.classList.remove("hidden");
```

par :

```js
  // Un bêta-testeur n'a rien à gérer chez Stripe : on lui dit que l'accès est offert.
  const isBeta = state.access === "beta";
  document.getElementById("manage-sub")?.classList.toggle("hidden", isBeta);
  document.getElementById("beta-badge")?.classList.toggle("hidden", !isBeta);
```

Et renseigner `state.access` aux deux endroits qui lisent `/api/me` — après `state.role = me.role;` (lignes 41 et 72) :

```js
      state.access = me.access;
```

- [ ] **Step 5: Régénérer le CSS et monter le cache-bust**

```bash
bash scripts/build-css.sh
```

Puis dans `src/sporia/web/templates/index.html`, remplacer les trois occurrences de `?v=82` par `?v=83`.

- [ ] **Step 6: Vérification manuelle**

Lancer : `venv/Scripts/python.exe -m uvicorn sporia.web.app:app --port 8000`

Vérifier, connecté en **admin** :
- Le menu compte affiche « 👥 Comptes » ; la modale s'ouvre et liste les comptes, le plus récent en haut.
- Le filtre réduit la liste sur l'email comme sur le nom.
- Un compte sans accès affiche « Aucun accès » et le bouton « Passer en bêta » ; après clic, il affiche « Bêta — offert » et « Retirer la bêta ».
- Un compte admin et un compte abonné affichent « non modifiable ».

Vérifier, connecté avec un **compte passé en bêta** :
- L'app s'ouvre directement, sans paywall.
- Le menu compte affiche « Accès bêta — offert » et **pas** « Mon abonnement ».

Vérifier, connecté avec un **compte sans accès** : le paywall s'affiche toujours.

- [ ] **Step 7: Lancer la suite complète**

Run: `venv/Scripts/python.exe -m pytest -q`
Expected: suite entièrement verte (aucun test ne couvre le DOM, mais les partials modifiés sont rendus par les tests de route existants).

- [ ] **Step 8: Commit**

```bash
git add src/sporia/web/templates/partials/modals.html src/sporia/web/templates/partials/app.html src/sporia/web/templates/index.html web/js/main.js web/css/tailwind.css
git commit -m "feat(beta): ecran admin Comptes et mention Acces beta offert"
```

---

## Déploiement

Aucune migration de base : la colonne `subscription_status` existe déjà et `'beta'` n'est qu'une nouvelle valeur. Après `git pull origin main` sur le serveur, `sudo systemctl restart champimap.service` suffit.

Rattrapage des testeurs déjà acceptés : ouvrir la modale « Comptes » en admin et les passer en bêta un par un — c'est le mode opératoire retenu, il n'y a pas de migration en masse.
