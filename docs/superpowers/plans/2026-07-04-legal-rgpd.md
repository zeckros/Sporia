# Légal & RGPD (chantier 4.4) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** Suppression de compte self-service (RGPD) + contenu légal (CGV/mentions/confidentialité + rétractation).

**Architecture:** Helpers de purge par store (accounts/prefs/spots) + annulation Stripe best-effort dans billing ; une route `DELETE /api/account` orchestre. Contenu légal = HTML statique (placeholders `[À COMPLÉTER]`) + case de consentement rétractation sur le paywall.

**Tech Stack:** FastAPI/Starlette, SQLite + JSON stores, pytest+TestClient, HTML/JS vanilla.

## Global Constraints

- Branche `chantier-legal` (base `main`). NON déployé seul. Commits fréquents, PAS de `Co-Authored-By`. `venv/Scripts/python.exe`.
- Effacement réel (compte+tokens+prefs+spots) ; annulation Stripe best-effort (jamais bloquante).
- Placeholders légaux `[À COMPLÉTER : ...]` pour infos éditeur/hébergeur/SIRET.

---

### Task 1: Helpers de purge (accounts/prefs/spots)

**Files:** Modify `src/sporia/users/accounts.py`, `src/sporia/users/prefs.py`, `src/sporia/users/spots.py` ; Test `tests/test_account_delete.py`.

**Interfaces produites:** `accounts.delete_user(user_id:int)->None`, `prefs.delete_user(username:str)->None`, `spots.delete_user(username:str)->None`.

- [ ] **Step 1: Tests**

Create `tests/test_account_delete.py` :

```python
"""Purge des données d'un compte (chantier 4.4)."""

import importlib

import pytest


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORIA_DB", str(tmp_path / "t.db"))
    import sporia.config as cfg

    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)
    import sporia.users.accounts as acc
    import sporia.users.prefs as prefs
    import sporia.users.spots as spots

    importlib.reload(acc)
    importlib.reload(prefs)
    importlib.reload(spots)
    acc.init_db()
    return acc, prefs, spots


def test_accounts_delete_user_removes_row_and_tokens(stores):
    acc, _, _ = stores
    u = acc.create_user("a@b.fr", "password123")
    acc.create_token(u["id"], "reset", 3600)
    acc.delete_user(u["id"])
    assert acc.get_by_email("a@b.fr") is None
    assert acc.consume_token("whatever", "reset") is None  # table vidée pour ce user


def test_accounts_delete_user_idempotent(stores):
    acc, _, _ = stores
    u = acc.create_user("a@b.fr", "password123")
    acc.delete_user(u["id"])
    acc.delete_user(u["id"])  # ne lève pas


def test_prefs_delete_user(stores):
    _, prefs, _ = stores
    prefs.set_species("a@b.fr", ["Boletus edulis"])
    prefs.set_species("c@d.fr", ["Cantharellus cibarius"])
    prefs.delete_user("a@b.fr")
    assert prefs.get_species("a@b.fr") is None
    assert prefs.get_species("c@d.fr") == ["Cantharellus cibarius"]
    prefs.delete_user("a@b.fr")  # no-op, ne lève pas


def test_spots_delete_user(stores):
    _, _, spots = stores
    spots.add_spot("a@b.fr", 46.0, 2.0, "coin")
    spots.add_spot("c@d.fr", 47.0, 3.0, "autre")
    spots.delete_user("a@b.fr")
    assert spots.list_spots("a@b.fr") == []
    assert len(spots.list_spots("c@d.fr")) == 1
```

- [ ] **Step 2: Lancer → échec** — `venv/Scripts/python.exe -m pytest tests/test_account_delete.py -q` (AttributeError delete_user).

- [ ] **Step 3: Implémenter**

`accounts.py` (fin de fichier) :

```python
def delete_user(user_id: int) -> None:
    with _connect() as c:
        c.execute("DELETE FROM tokens WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
```

`prefs.py` (fin de fichier) :

```python
def delete_user(username: str) -> None:
    with _LOCK:
        allp = _load_all()
        if username in allp:
            del allp[username]
            p = _path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(allp, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(p)
```

(prefs.py utilise déjà `_LOCK`, `json`, `_path`, `_load_all`.)

`spots.py` (fin de fichier) :

```python
def delete_user(username: str) -> None:
    with _LOCK:
        allp = _load_all()
        if username in allp:
            del allp[username]
            _save_all(allp)
```

- [ ] **Step 4: Lancer → succès** (4 tests).
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(4.4): delete_user (accounts+prefs+spots)"`.

---

### Task 2: Annulation Stripe best-effort

**Files:** Modify `src/sporia/billing.py` ; Test `tests/test_cancel_subscription.py`.

**Interface produite:** `billing.cancel_subscription(account: dict) -> None` (best-effort, ne lève jamais).

- [ ] **Step 1: Tests**

Create `tests/test_cancel_subscription.py` :

```python
"""Annulation Stripe best-effort (chantier 4.4)."""

import importlib

import pytest


@pytest.fixture()
def billing(monkeypatch, tmp_path):
    monkeypatch.setenv("SPORIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_x")
    import sporia.billing as b

    importlib.reload(b)
    return b


def test_cancel_no_customer_noop(billing):
    billing.cancel_subscription({"stripe_customer_id": None})  # ne lève pas


def test_cancel_deletes_each_subscription(billing, monkeypatch):
    deleted = []
    monkeypatch.setattr(
        billing.stripe.Subscription, "list",
        lambda customer: {"data": [{"id": "sub_1"}, {"id": "sub_2"}]},
    )
    monkeypatch.setattr(
        billing.stripe.Subscription, "delete", lambda sid: deleted.append(sid)
    )
    billing.cancel_subscription({"stripe_customer_id": "cus_1"})
    assert deleted == ["sub_1", "sub_2"]


def test_cancel_swallows_errors(billing, monkeypatch):
    def boom(customer):
        raise RuntimeError("stripe down")

    monkeypatch.setattr(billing.stripe.Subscription, "list", boom)
    billing.cancel_subscription({"stripe_customer_id": "cus_1"})  # ne lève pas
```

- [ ] **Step 2: Lancer → échec**.

- [ ] **Step 3: Implémenter** — dans `billing.py`, après `create_portal_session` :

```python
def cancel_subscription(account: dict) -> None:
    """Résilie les abonnements Stripe du compte (best-effort, ne lève jamais)."""
    cid = account.get("stripe_customer_id")
    if not cid or not stripe_enabled():
        return
    try:
        _configure()
        subs = stripe.Subscription.list(customer=cid)
        for sub in subs["data"]:
            stripe.Subscription.delete(sub["id"])
    except Exception as e:  # jamais bloquer la suppression de compte
        print(f"[billing] annulation Stripe échouée pour {cid} : {e}")
```

- [ ] **Step 4: Lancer → succès** (3 tests) + `ruff check`.
- [ ] **Step 5: Commit** — `feat(4.4): billing.cancel_subscription (best-effort)`.

---

### Task 3: Route `DELETE /api/account`

**Files:** Modify `src/sporia/web/app.py` ; Test `tests/test_account_route.py`.

**Interface produite:** `DELETE /api/account` (require_user) → purge complète + session.clear.

- [ ] **Step 1: Tests**

Create `tests/test_account_route.py` :

```python
"""Route de suppression de compte (chantier 4.4)."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    import sporia.config as cfg

    monkeypatch.setattr(cfg.settings, "data_dir", tmp_path)
    import sporia.users.accounts as acc
    import sporia.users.prefs as prefs
    import sporia.users.spots as spots

    importlib.reload(acc)
    importlib.reload(prefs)
    importlib.reload(spots)
    acc.init_db()
    import sporia.billing as billing

    importlib.reload(billing)
    import sporia.web.app as webapp

    importlib.reload(webapp)
    return TestClient(webapp.app), acc, prefs, spots


def test_delete_requires_auth(client):
    c, *_ = client
    assert c.delete("/api/account").status_code == 401


def test_delete_purges_everything(client):
    c, acc, prefs, spots = client
    acc.create_user("a@b.fr", "password123", name="A")
    c.post("/api/login", json={"username": "a@b.fr", "password": "password123"})
    prefs.set_species("a@b.fr", ["Boletus edulis"])
    spots.add_spot("a@b.fr", 46.0, 2.0, "coin")

    r = c.delete("/api/account")
    assert r.status_code == 200

    assert acc.get_by_email("a@b.fr") is None
    assert prefs.get_species("a@b.fr") is None
    assert spots.list_spots("a@b.fr") == []
    assert c.get("/api/me").json()["authenticated"] is False
```

- [ ] **Step 2: Lancer → échec** (404/405 : route absente).

- [ ] **Step 3: Implémenter** — dans `app.py`, après les routes billing (avant `# ===== API données`), en s'appuyant sur les imports existants (`accounts`, `user_prefs`, `user_spots`, `billing`, `require_user`) :

```python
@app.delete("/api/account")
def delete_account(request: Request, user=Depends(require_user)):
    account = accounts.get_by_email(user["username"])
    if account is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    billing.cancel_subscription(account)
    user_prefs.delete_user(account["email"])
    user_spots.delete_user(account["email"])
    accounts.delete_user(account["id"])
    request.session.clear()
    return {"ok": True}
```

(Vérifier les alias d'import en tête d'`app.py` : `from sporia.users import prefs as user_prefs`, `from sporia.users import spots as user_spots` — utiliser les mêmes.)

- [ ] **Step 4: Lancer → succès** (2 tests) puis suite complète `pytest -q` + `ruff check src tests`.
- [ ] **Step 5: Commit** — `feat(4.4): DELETE /api/account (purge RGPD + session)`.

---

### Task 4: Frontend — modale légale, bouton supprimer, consentement rétractation

**Files:** Modify `web/index.html`, `web/app.js`. (Non testé unitairement → vérif manuelle.)

- [ ] **Step 1: Réécrire le contenu de la modale `#cgu-modal`** (`web/index.html`, corps `flex-1 overflow-y-auto ...`, lignes ~841-879) en 3 sections. Remplacer les 6 `<div>` par :

```html
        <div>
          <div class="font-black text-slate-900 text-base mb-2">Conditions d'utilisation & de vente (CGU/CGV)</div>
          <p class="mb-2"><strong>Objet.</strong> Sporia est un service d'aide à la prospection de champignons : il croise
          des données météo, forestières, pédologiques et d'occurrences pour estimer, à titre <strong>purement indicatif</strong>,
          les zones et moments favorables.</p>
          <p class="mb-2"><strong>Accès & abonnement.</strong> L'accès complet requiert un <strong>abonnement annuel</strong>
          payant, souscrit et géré via notre prestataire de paiement (Stripe). Le tarif en vigueur est affiché avant paiement.
          L'abonnement se reconduit annuellement ; vous pouvez le résilier à tout moment depuis « Mon abonnement » (l'accès
          reste ouvert jusqu'à la fin de la période payée).</p>
          <p class="mb-2"><strong>Droit de rétractation.</strong> Le service numérique étant fourni immédiatement, vous
          demandez expressément son exécution dès la souscription et <strong>renoncez à votre droit de rétractation</strong>
          de 14 jours (art. L221-28 3° du Code de la consommation), consentement recueilli par case à cocher au paiement.</p>
          <p class="mb-2"><strong>Sécurité — avertissement essentiel.</strong> Les estimations ne constituent <strong>en aucun
          cas</strong> une garantie de présence ni une identification. <strong>Ne consommez jamais</strong> un champignon sans
          identification formelle par une personne compétente (pharmacien, société mycologique) — certaines espèces sont
          mortelles. Respectez la réglementation de cueillette, la propriété privée et les espaces protégés. L'éditeur décline
          toute responsabilité en cas d'intoxication, d'accident ou d'infraction.</p>
          <p><strong>Responsabilité.</strong> Service fourni « en l'état », sans garantie de disponibilité ni d'exactitude.</p>
        </div>
        <div>
          <div class="font-black text-slate-900 text-base mb-2">Mentions légales</div>
          <p class="mb-1"><strong>Éditeur :</strong> [À COMPLÉTER : nom / statut juridique / SIRET / adresse / email de contact].</p>
          <p class="mb-1"><strong>Directeur de la publication :</strong> [À COMPLÉTER].</p>
          <p><strong>Hébergeur :</strong> [À COMPLÉTER : Oracle Cloud (Oracle Corporation) / adresse].</p>
        </div>
        <div>
          <div class="font-black text-slate-900 text-base mb-2">Politique de confidentialité (RGPD)</div>
          <p class="mb-2"><strong>Responsable de traitement :</strong> [À COMPLÉTER]. <strong>Données collectées :</strong>
          email, nom, mot de passe (haché), préférences d'espèces, spots enregistrés, statut d'abonnement et identifiant client
          Stripe.</p>
          <p class="mb-2"><strong>Finalités & base légale :</strong> fourniture du service et facturation — exécution du contrat
          d'abonnement. <strong>Sous-traitants :</strong> Stripe (paiement), Brevo (emails transactionnels), Oracle Cloud
          (hébergement). Aucune donnée n'est cédée ni revendue à des tiers à des fins commerciales.</p>
          <p class="mb-2"><strong>Conservation :</strong> le temps de la relation contractuelle, puis suppression. <strong>Vos
          droits :</strong> accès, rectification, effacement, portabilité, opposition — exerçables en nous contactant
          [À COMPLÉTER : email] ou, pour l'effacement, directement via <strong>« Supprimer mon compte »</strong> dans l'application.</p>
          <p><strong>Cookies :</strong> seul un cookie de session strictement nécessaire à l'authentification est utilisé
          (aucun traceur publicitaire).</p>
        </div>
```

Et adapter le titre de la modale (chercher le `<h...>` d'en-tête au-dessus de la ligne 839) en « Informations légales » si présent (sinon laisser).

- [ ] **Step 2: Footer** — remplacer le libellé du bouton `open-cgu` (ligne ~478) `CGU` par `CGU · Mentions · Confidentialité`.

- [ ] **Step 3: Bouton « Supprimer mon compte »** dans le header app — après `#logout-btn` (ligne ~653) :

```html
          <button id="delete-account"
                  class="px-3 py-2 md:py-1.5 rounded-lg text-sm font-semibold text-slate-400 border border-slate-200 hover:text-red-600 hover:border-red-200 hover:bg-red-50 transition text-left md:text-center">
            Supprimer mon compte
          </button>
```

- [ ] **Step 4: Case rétractation sur le paywall** — dans `#paywall-screen`, juste avant `#subscribe-btn` :

```html
        <label class="mt-5 flex items-start gap-2 text-left text-xs text-slate-500">
          <input id="retract-consent" type="checkbox" class="mt-0.5 shrink-0" />
          <span>J'accepte les CGV et je demande l'accès immédiat au service, renonçant expressément à mon
          droit de rétractation de 14 jours. <button type="button" class="open-cgu text-brand-600 font-semibold underline">Lire les CGV</button></span>
        </label>
```

et ajouter l'attribut `disabled` par défaut au bouton `#subscribe-btn` (ajouter ` disabled` dans sa balise + classe `disabled:opacity-50 disabled:cursor-not-allowed`).

- [ ] **Step 5: JS** (`web/app.js`) — câbler suppression + toggle consentement. Après le binding `#manage-sub` :

```javascript
document.getElementById("delete-account")?.addEventListener("click", deleteAccount);
document.getElementById("retract-consent")?.addEventListener("change", (ev) => {
  const btn = document.getElementById("subscribe-btn");
  if (btn) btn.disabled = !ev.currentTarget.checked;
});
```

et la fonction (près de `openPortal`) :

```javascript
async function deleteAccount() {
  if (!confirm("Supprimer définitivement votre compte, vos préférences et vos spots ? " +
               "Votre abonnement sera résilié. Cette action est irréversible.")) return;
  try {
    await API.del("/api/account");
  } catch (e) { /* on recharge quand même */ }
  location.reload();
}
```

- [ ] **Step 6: Vérif manuelle** — `node --check web/app.js` ; démarrer uvicorn, ouvrir la modale (3 sections), vérifier case rétractation décochée ⇒ S'abonner désactivé, cochée ⇒ actif ; bouton supprimer présent.

- [ ] **Step 7: Commit** — `feat(4.4): frontend légal (modale 3 sections, suppression compte, consentement rétractation)`.

---

## Vérification finale

1. `pytest -q` + `ruff check src tests` verts.
2. Manuel : suppression de compte effective (reconnexion impossible) ; consentement rétractation gate le bouton ; modale complète.

## Hors périmètre

Refonte visuelle (4.5) · export portabilité automatisé · registre RGPD · bannière cookies (inutile).
