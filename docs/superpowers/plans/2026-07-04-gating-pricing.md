# Gating + pricing (chantier 4.3) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verrouiller l'app derrière un abonnement actif (enforcement backend 402) et offrir l'UX de souscription (pricing + paywall + portail).

**Architecture:** Une règle d'accès pure `billing.has_access(account)` ; une dépendance FastAPI `require_subscription` qui l'applique (402) et qu'on substitue à `require_user` sur les routes data ; `/api/me` expose `subscribed` + `price_label`. Le frontend route vers un écran paywall quand connecté-non-abonné et déclenche Checkout/Portal.

**Tech Stack:** FastAPI + Starlette (`SessionMiddleware`), SQLite store existant, pytest + `TestClient`, JS/HTML vanilla (Leaflet+Tailwind CDN).

## Global Constraints

- Branche `chantier-gating` (base `main`). **NON déployé seul** — avec 4.1 + 4.2.
- Commits fréquents, **PAS de `Co-Authored-By`**. Interpréteur `venv/Scripts/python.exe`.
- Règle d'accès : `role=="admin"` OU `subscription_status=="active"` OU `current_period_end > now`.
- Refus d'accès data = **HTTP 402**. Routes publiques/non-data intactes (login/register/me/billing/webhook/verify-email/password/access-requests).
- `require_subscription` **renvoie le `user` de session** (`{username,name,role}`), pas le compte — signatures des routes inchangées.
- Prix affiché : env `SPORIA_PRICE_LABEL` (fallback `"15 €/an"`), exposé par `/api/me` (public).

---

## File Structure

- **Créés :** `tests/test_access.py`, `tests/test_gating_routes.py`.
- **Modifiés :** `src/sporia/billing.py` (+`has_access`, +`import time`), `src/sporia/web/auth.py` (+`require_subscription`), `src/sporia/web/app.py` (swap dépendances data + `/api/me` enrichi + `import os` si absent), `web/index.html` (pricing + `#paywall-screen` + bouton gérer), `web/app.js` (routage abonnement), `ORACLE_DEPLOY.md`.

---

### Task 1: Règle d'accès `has_access`

**Files:**
- Modify: `src/sporia/billing.py`
- Test: `tests/test_access.py`

**Interfaces:**
- Produces: `billing.has_access(account: dict | None) -> bool`.

- [ ] **Step 1: Écrire les tests**

Create `tests/test_access.py` :

```python
"""Règle d'accès abonnement (chantier 4.3)."""

import time

from sporia import billing


def test_none_account_no_access():
    assert billing.has_access(None) is False


def test_admin_always_access():
    assert billing.has_access({"role": "admin", "subscription_status": "none"}) is True


def test_active_status_access():
    assert billing.has_access({"role": "user", "subscription_status": "active"}) is True


def test_grace_period_future_access():
    future = int(time.time()) + 86400
    acc = {"role": "user", "subscription_status": "canceled", "current_period_end": future}
    assert billing.has_access(acc) is True


def test_period_expired_no_access():
    past = int(time.time()) - 86400
    acc = {"role": "user", "subscription_status": "canceled", "current_period_end": past}
    assert billing.has_access(acc) is False


def test_none_status_no_period_no_access():
    acc = {"role": "user", "subscription_status": "none", "current_period_end": None}
    assert billing.has_access(acc) is False
```

- [ ] **Step 2: Lancer → échec**

Run: `venv/Scripts/python.exe -m pytest tests/test_access.py -v`
Expected: FAIL — `AttributeError: module 'sporia.billing' has no attribute 'has_access'`.

- [ ] **Step 3: Implémenter**

Dans `src/sporia/billing.py`, ajouter `import time` sous `import os`, puis ajouter après `stripe_enabled()` :

```python
def has_access(account: dict | None) -> bool:
    """True si le compte a droit à l'app : admin, abonnement actif, ou période payée en cours."""
    if account is None:
        return False
    if account.get("role") == "admin":
        return True
    if account.get("subscription_status") == "active":
        return True
    cpe = account.get("current_period_end")
    return bool(cpe) and cpe > int(time.time())
```

- [ ] **Step 4: Lancer → succès**

Run: `venv/Scripts/python.exe -m pytest tests/test_access.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/sporia/billing.py tests/test_access.py
git commit -m "feat(4.3): billing.has_access (admin/active/grâce période)"
```

---

### Task 2: Gating backend (`require_subscription` + routes + `/api/me`)

**Files:**
- Modify: `src/sporia/web/auth.py`, `src/sporia/web/app.py`
- Test: `tests/test_gating_routes.py`

**Interfaces:**
- Consumes: `billing.has_access(account)` (Task 1), `accounts.get_by_email(email)`, `require_user` (existant).
- Produces: `require_subscription(request) -> dict` (renvoie le `user` de session) ; `/api/me` → `{authenticated, name, subscribed, role, price_label}`.

- [ ] **Step 1: Écrire les tests**

Create `tests/test_gating_routes.py` :

```python
"""Gating abonnement sur les routes data (chantier 4.3) — TestClient."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORIA_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.setenv("SPORIA_PRICE_LABEL", "12 €/an")

    import sporia.users.accounts as acc

    importlib.reload(acc)
    acc.init_db()
    import sporia.billing as billing

    importlib.reload(billing)
    import sporia.web.app as webapp

    importlib.reload(webapp)
    return TestClient(webapp.app), acc


def _login(c, acc, email, password="password123", role="user", status="none"):
    u = acc.create_user(email, password, name="U", role=role)
    if status != "none":
        acc.set_subscription(u["id"], status)
    r = c.post("/api/login", json={"username": email, "password": password})
    assert r.status_code == 200
    return u


def test_data_route_402_without_subscription(client):
    c, acc = client
    _login(c, acc, "free@sporia.fr")
    r = c.get("/api/outline")
    assert r.status_code == 402


def test_data_route_not_402_with_subscription(client):
    c, acc = client
    _login(c, acc, "sub@sporia.fr", status="active")
    r = c.get("/api/outline")
    assert r.status_code != 402  # 200 attendu (route sans I/O lourde)


def test_data_route_not_402_for_admin(client):
    c, acc = client
    _login(c, acc, "admin@sporia.fr", role="admin")
    r = c.get("/api/outline")
    assert r.status_code != 402


def test_me_unauthenticated_public(client):
    c, acc = client
    r = c.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is False
    assert body["subscribed"] is False
    assert body["price_label"] == "12 €/an"


def test_me_authenticated_subscribed_flag(client):
    c, acc = client
    _login(c, acc, "sub@sporia.fr", status="active")
    body = c.get("/api/me").json()
    assert body["authenticated"] is True
    assert body["subscribed"] is True


def test_public_routes_not_gated(client):
    c, acc = client
    # register (public) ne doit jamais renvoyer 402
    r = c.post(
        "/api/register",
        json={"email": "new@sporia.fr", "password": "password123", "name": "N"},
    )
    assert r.status_code != 402
```

- [ ] **Step 2: Lancer → échec**

Run: `venv/Scripts/python.exe -m pytest tests/test_gating_routes.py -v`
Expected: FAIL — `/api/outline` renvoie 200 (pas encore gated) donc `test_data_route_402_without_subscription` échoue, et `/api/me` n'a pas `subscribed`/`price_label`.

- [ ] **Step 3: Ajouter `require_subscription` dans `auth.py`**

Dans `src/sporia/web/auth.py`, ajouter après `require_admin` :

```python
def require_subscription(request: Request) -> dict:
    """Comme require_user, mais exige un accès abonnement actif (402 sinon)."""
    from sporia import billing

    user = require_user(request)
    account = accounts.get_by_email(user["username"])
    if not billing.has_access(account):
        raise HTTPException(status_code=402, detail="Abonnement requis.")
    return user
```

- [ ] **Step 4: Enrichir `/api/me` dans `app.py`**

S'assurer que `import os` est présent en tête de `src/sporia/web/app.py` (il l'est déjà). Remplacer la fonction `me` :

```python
@app.get("/api/me")
def me(request: Request):
    user = request.session.get("user")
    account = accounts.get_by_email(user["username"]) if user else None
    return {
        "authenticated": bool(user),
        "name": user["name"] if user else None,
        "subscribed": billing.has_access(account),
        "role": (user or {}).get("role"),
        "price_label": os.environ.get("SPORIA_PRICE_LABEL", "15 €/an"),
    }
```

- [ ] **Step 5: Importer `require_subscription` et l'appliquer aux routes data**

Dans `src/sporia/web/app.py`, à l'import auth (`from sporia.web.auth import require_admin, require_user, verify`), ajouter `require_subscription` :

```python
from sporia.web.auth import require_admin, require_subscription, require_user, verify
```

Puis, sur **chacune** des routes data suivantes, remplacer `Depends(require_user)` par `Depends(require_subscription)` (le nom du paramètre `user=` reste inchangé) : `api_dates`, `api_cities`, `api_outline`, `api_overlay`, `api_get_preferences`, `api_set_preferences`, `api_favorability`, `api_soil`, `api_soil_moisture`, `api_altitude`, `api_aspect`, `api_radar`, `api_radar_meta`, la route tuile radar, `api_fruiting_models`, `api_fruiting`, `api_point`, `api_forest`, `api_list_spots`, `api_add_spot`, `api_rename_spot`, `api_delete_spot`.

**Ne pas** toucher : `login`, `logout`, `me`, `register`, `password_*`, `verify_email`, `billing_*`, `stripe_webhook`, `api_list_access_requests` (reste `require_admin`).

Astuce de vérif : après édition, `grep -n "Depends(require_user)" src/sporia/web/app.py` ne doit **plus** rien retourner (toutes les occurrences data converties ; `me` lit la session directement, pas `require_user`).

- [ ] **Step 6: Lancer → succès**

Run: `venv/Scripts/python.exe -m pytest tests/test_gating_routes.py -v`
Expected: PASS (6 tests).

- [ ] **Step 7: Suite complète + lint**

Run: `venv/Scripts/python.exe -m pytest -q` puis `venv/Scripts/python.exe -m ruff check src tests`
Expected: tout vert ; `All checks passed!`. (Les tests 4.1/4.2 qui appellent des routes data en étant connectés mais non abonnés pourraient désormais recevoir 402 — vérifier : les tests existants ne frappent pas les routes data sans abonnement. S'il y a une régression, l'annoter et s'arrêter.)

- [ ] **Step 8: Commit**

```bash
git add src/sporia/web/auth.py src/sporia/web/app.py tests/test_gating_routes.py
git commit -m "feat(4.3): gating 402 sur routes data + /api/me subscribed/price_label"
```

---

### Task 3: Frontend — pricing, paywall, souscription, portail

**Files:**
- Modify: `web/index.html`, `web/app.js`

**Interfaces:**
- Consumes: `/api/me` (`subscribed`, `price_label`), `POST /api/billing/checkout` (`{url}`), `POST /api/billing/portal` (`{url}`).
- Produces: écran `#paywall-screen`, boutons `#subscribe-btn` / `.subscribe-cta` / `#manage-sub`, éléments `[data-price-label]`, fonctions JS `showPaywall`, `subscribe`, `openPortal`.

> Frontend non testé unitairement (convention projet) → vérification manuelle en fin de tâche.

- [ ] **Step 1: Ajouter le prix + CTA dans la section inscription (`web/index.html`)**

Après le paragraphe d'intro de la section contact (après la ligne
`Inscrivez-vous en quelques secondes pour accéder à la carte.` / son `</p>`), insérer :

```html
        <p class="mt-2 text-sm text-slate-500">
          Accès complet à la carte et aux prévisions quotidiennes —
          <span class="font-bold text-brand-600" data-price-label>15 €/an</span>.
        </p>
```

- [ ] **Step 2: Ajouter l'écran paywall (`web/index.html`)**

Juste avant `<!-- ============ PAGE DE CONNEXION ============ -->` (ligne ~482), insérer :

```html
  <!-- ============ PAYWALL (connecté, non abonné) ============ -->
  <div id="paywall-screen" class="hidden fixed inset-0 z-50 overflow-auto bg-slate-50">
    <div class="min-h-screen flex items-center justify-center px-5">
      <div class="max-w-md w-full bg-white rounded-2xl shadow-card border border-slate-200 p-7 text-center">
        <div class="font-black text-brand-600 text-2xl mb-2">Sporia</div>
        <h1 class="text-2xl font-black tracking-tight text-slate-900">Abonnez-vous pour accéder à la carte</h1>
        <p class="mt-3 text-slate-500">
          Accès complet aux prévisions de cueillette, mises à jour chaque jour.
        </p>
        <p class="mt-4 text-3xl font-black text-slate-900"><span data-price-label>15 €/an</span></p>
        <button id="subscribe-btn"
                class="mt-6 w-full py-3 rounded-xl bg-brand-500 hover:bg-brand-600 text-white font-bold shadow-card transition">
          S'abonner
        </button>
        <p id="paywall-note" class="hidden mt-3 text-sm font-semibold text-green-600"></p>
        <button id="paywall-logout" class="mt-5 text-sm text-slate-400 hover:text-brand-600 font-semibold transition">
          Se déconnecter
        </button>
      </div>
    </div>
  </div>
```

- [ ] **Step 3: Ajouter « Gérer mon abonnement » dans le header de l'app (`web/index.html`)**

Avant le bouton `#logout-btn` (ligne ~650), insérer :

```html
          <button id="manage-sub"
                  class="hidden px-3 py-2 md:py-1.5 rounded-lg text-sm font-semibold text-brand-700 border border-brand-200 bg-brand-50 hover:bg-brand-100 transition text-left md:text-center">
            Mon abonnement
          </button>
```

- [ ] **Step 4: Router selon l'abonnement au boot (`web/app.js`)**

Remplacer le corps de `boot()` (lignes ~64-74) — la partie après `setupLandingNav();` — par :

```javascript
  setupLandingNav();
  // Retour depuis Stripe Checkout
  const params = new URLSearchParams(location.search);
  const justPaid = params.get("checkout") === "success";
  if (params.has("checkout")) history.replaceState({}, "", location.pathname);
  try {
    const me = await API.get("/api/me");
    applyPriceLabel(me.price_label);
    if (me.authenticated) {
      state.name = me.name;
      if (me.subscribed) { startApp(); return; }
      showPaywall(justPaid);
      return;
    }
  } catch (e) { /* ignore */ }
  showLanding();
}

function applyPriceLabel(label) {
  if (!label) return;
  state.priceLabel = label;
  document.querySelectorAll("[data-price-label]").forEach((el) => { el.textContent = label; });
}

function showPaywall(justPaid) {
  document.getElementById("landing-screen").classList.add("hidden");
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("app-screen").classList.add("hidden");
  document.getElementById("paywall-screen").classList.remove("hidden");
  if (justPaid) {
    const note = document.getElementById("paywall-note");
    note.textContent = "Paiement reçu — activation en cours, actualisez dans un instant.";
    note.classList.remove("hidden");
  }
}

async function subscribe(btn) {
  if (btn) btn.disabled = true;
  try {
    const r = await API.post("/api/billing/checkout");
    location.href = r.url;
  } catch (e) {
    if (e && e.unauth) { showLoginPage(); return; }
    alert(e.message || "Abonnement indisponible pour le moment.");
    if (btn) btn.disabled = false;
  }
}

async function openPortal() {
  try {
    const r = await API.post("/api/billing/portal");
    location.href = r.url;
  } catch (e) {
    alert(e.message || "Portail indisponible.");
  }
}
```

Note : `API.get` lève `{unauth:true}` sur 401 ; `API.post` lève un `Error` classique. Le CTA « S'abonner » de la **landing** (utilisateur potentiellement non connecté) doit donc gérer un `Error` 401 → dans ce cas, ouvrir le login. Le bouton du **paywall** est toujours en session connectée.

- [ ] **Step 5: Câbler les boutons + adapter login/register (`web/app.js`)**

Dans le handler `#subscribe-btn` : à la fin de `boot()`-setup zone (près des autres `addEventListener`, par ex. juste après le bloc `.open-login`/`.back-landing` dans `boot()` ou en bas du fichier avec les autres bindings), ajouter :

```javascript
document.getElementById("subscribe-btn")?.addEventListener("click", (ev) => subscribe(ev.currentTarget));
document.getElementById("paywall-logout")?.addEventListener("click", async () => {
  try { await API.post("/api/logout"); } catch (e) {}
  location.reload();
});
document.getElementById("manage-sub")?.addEventListener("click", openPortal);
document.querySelectorAll(".subscribe-cta").forEach((b) =>
  b.addEventListener("click", (ev) => subscribe(ev.currentTarget)));
```

Adapter **login** (handler ligne ~115) : remplacer `state.name = res.name; startApp();` par un re-routage selon l'abonnement :

```javascript
    state.name = res.name;
    await routeAfterAuth();
```

Idem **register** (handler ligne ~164) : remplacer `state.name = res.name; startApp();` par `state.name = res.name; await routeAfterAuth();`.

Ajouter la fonction `routeAfterAuth` (près de `boot`) :

```javascript
async function routeAfterAuth() {
  try {
    const me = await API.get("/api/me");
    applyPriceLabel(me.price_label);
    if (me.subscribed) { startApp(); return; }
  } catch (e) { /* ignore */ }
  showPaywall(false);
}
```

- [ ] **Step 6: Afficher « Mon abonnement » dans l'app pour les abonnés (`web/app.js`)**

Dans `startApp()` (après `document.getElementById("nav-user").textContent = state.name || "";`, ligne ~213), ajouter :

```javascript
  document.getElementById("manage-sub")?.classList.remove("hidden");
```

(Le bouton reste `hidden` sur le paywall/landing ; `startApp` n'est atteint que par un abonné ou un admin.)

- [ ] **Step 7: Vérification manuelle**

Démarrer l'app en dev (sans clés Stripe) :

Run: `venv/Scripts/python.exe -m uvicorn sporia.web.app:app --port 8000`
Puis vérifier dans le navigateur :
- Déconnecté → landing affiche le prix (`15 €/an` par défaut, ou la valeur de `SPORIA_PRICE_LABEL`).
- S'inscrire (compte neuf, non abonné) → **écran paywall** (pas la carte).
- Cliquer « S'abonner » → l'API `/api/billing/checkout` renvoie **503** (Stripe désactivé en dev) → `alert` « Paiement indisponible… » (comportement attendu sans clés).
- Créer un admin (ou passer le compte `role=admin` en base) → connexion → **carte** directement, bouton « Mon abonnement » visible.

Arrêter uvicorn (Ctrl-C).

- [ ] **Step 8: Commit**

```bash
git add web/index.html web/app.js
git commit -m "feat(4.3): frontend paywall + pricing + souscription/portail Stripe"
```

---

### Task 4: Documentation `SPORIA_PRICE_LABEL`

**Files:**
- Modify: `ORACLE_DEPLOY.md`

- [ ] **Step 1: Documenter la variable**

Dans la section « Abonnement Stripe » de `ORACLE_DEPLOY.md`, sous le bloc `.env`, ajouter la ligne d'env et une note :

```
SPORIA_PRICE_LABEL=15 €/an
```

Note : ce libellé est **purement affiché** (landing + paywall) ; il doit être **aligné manuellement**
sur le prix réel du Produit Stripe. Le montant débité vient toujours de Stripe, jamais de cette
variable. Rappel : après migration, les comptes non-admin sont non abonnés → paywall (leur ouvrir
l'accès via un abonnement Stripe, ou passer `subscription_status=active`/`role=admin` en base pour
un accès offert).

- [ ] **Step 2: Commit**

```bash
git add ORACLE_DEPLOY.md
git commit -m "docs(4.3): SPORIA_PRICE_LABEL + note comptes migrés non abonnés"
```

---

## Vérification finale

1. `venv/Scripts/python.exe -m pytest -q` → tout vert.
2. `venv/Scripts/python.exe -m ruff check src tests` → `All checks passed!`.
3. `grep -n "Depends(require_user)" src/sporia/web/app.py` → **vide** (toutes les routes data gated).
4. Manuel : non-abonné → paywall + API data 402 ; admin/abonné → carte + « Mon abonnement ».

## Hors périmètre

CGV/mentions/rétractation (4.4) · refonte visuelle (4.5) · essai gratuit · multi-plans · grandfathering auto.
