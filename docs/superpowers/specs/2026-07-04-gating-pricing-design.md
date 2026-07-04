# Sporia — Chantier 4.3/5 : Gating + pricing — Design

## Contexte

Chantier 4 (Monétisation), décomposé en 5 sous-projets : (4.1) Comptes *(FAIT)* → (4.2) Paiement
Stripe *(FAIT)* → **(4.3) Gating + pricing** *(ce spec)* → (4.4) Légal/RGPD → (4.5) UX polish.

Acquis : store SQLite (identité email) avec `subscription_status` (`none`/`active`/`past_due`/
`canceled`) + `current_period_end` ; `src/sporia/billing.py` (Checkout, Portal, webhook) ; routes
`/api/billing/checkout`, `/api/billing/portal`, `/api/stripe/webhook`. Frontend :
`web/index.html` + `web/app.js`, 3 écrans (`#landing-screen` public, `#login-screen`,
`#app-screen`) ; `/api/me` → `{authenticated, name}` pilote `startApp()`. ~20 routes data
protégées par `Depends(require_user)`.

**Objectif 4.3** : verrouiller l'app derrière un **abonnement actif** (enforcement backend) et
offrir une **UX de souscription** claire (pricing + paywall). C'est le sous-projet qui rend le
paiement « utile ».

## Décisions

- **Règle d'accès = source de vérité côté serveur.** Le frontend ne fait que refléter l'état ; la
  vraie barrière est le backend (402).
- **Grâce jusqu'à fin de période** : un abonnement `canceled`/`past_due` dont `current_period_end`
  est encore dans le futur garde l'accès (l'utilisateur a payé sa période). Passé cette date, accès
  coupé.
- **Admin bypasse** le paywall (`role == "admin"`).
- **Prix affiché = une seule source éditable** : variable d'environnement `SPORIA_PRICE_LABEL`
  (fallback `"15 €/an"`), exposée publiquement via `/api/me`. À aligner manuellement sur le prix
  réel créé dans Stripe (le montant réellement débité vient toujours de Stripe, jamais du front).
- **Non déployé seul** : construit + testé + mergé sur `main`, poussé/déployé avec 4.1 + 4.2.

## Périmètre & unités

### 1. Règle d'accès — `src/sporia/billing.py`

```python
def has_access(account: dict | None) -> bool:
    if account is None:
        return False
    if account.get("role") == "admin":
        return True
    if account.get("subscription_status") == "active":
        return True
    cpe = account.get("current_period_end")
    return bool(cpe) and cpe > int(time.time())
```

Pure, testable isolément. `account` = dict façon `accounts.get_by_email(...)` (contient `role`,
`subscription_status`, `current_period_end`).

### 2. Dépendance de gating — `src/sporia/web/auth.py`

`require_subscription(request) -> dict` : appelle `require_user` (401 si non connecté), **recharge
le compte frais** via `accounts.get_by_email(user["username"])` pour le contrôle d'accès, puis
`billing.has_access(account)` sinon lève **HTTPException 402** (`detail="Abonnement requis."`).
**Renvoie le `user` de session inchangé** (même forme que `require_user` : `{username, name,
role}`) — les routes data qui lisent `user["username"]` (prefs, spots) restent identiques, aucun
changement de signature en aval. Import de `billing` fait dans la fonction (évite tout cycle
d'import auth↔billing au chargement).

### 3. Application du gating — `src/sporia/web/app.py`

Remplacer `Depends(require_user)` → `Depends(require_subscription)` sur les routes **data** :
`/api/dates`, `/api/cities`, `/api/outline`, `/api/overlay`, `/api/preferences` (GET+POST),
`/api/favorability`, `/api/soil`, `/api/soil-moisture`, `/api/altitude`, `/api/aspect`,
`/api/radar`, `/api/radar-meta`, la tuile radar, `/api/fruiting-models`, `/api/fruiting`,
`/api/point`, `/api/forest`, et les routes spots (`/api/spots` list/add/rename/delete).

**Restent sur `require_user` ou publiques** : `/api/me`, `/api/login`, `/api/logout`,
`/api/register`, `/api/password/*`, `/api/verify-email`, `/api/billing/*`, `/api/stripe/webhook`,
`/api/access-requests*` (déjà `require_admin`).

### 4. `/api/me` enrichi — `src/sporia/web/app.py`

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

Reste **public** (renvoie `authenticated: false` sans session) pour que la landing affiche le prix.

### 5. Frontend — `web/index.html` + `web/app.js`

- **Section pricing** sur la landing (`#landing-screen`) : décrit l'offre (accès complet, MAJ
  quotidiennes, X€/an) avec un CTA « S'abonner ». Le label prix est injecté depuis
  `me.price_label` (élément `[data-price-label]`).
- **Écran paywall** `#paywall-screen` (nouveau, `hidden` par défaut) : titre « Abonnez-vous pour
  accéder à Sporia », prix, bouton **« S'abonner »** (`id="subscribe-btn"`), lien de déconnexion,
  et mention « déjà payé ? actualisez ».
- **`web/app.js`** :
  - Après `/api/me` (init) : `if (me.authenticated && me.subscribed) startApp();
    else if (me.authenticated) showPaywall(); else showLanding();`. Stocker
    `state.subscribed`, `state.priceLabel`, injecter le prix dans les `[data-price-label]`.
  - `showPaywall()` : masque landing/login/app, montre `#paywall-screen`.
  - `subscribe()` (bouton S'abonner, landing + paywall) : `const r = await
    API.post("/api/billing/checkout"); location.href = r.url;`. Si l'appel renvoie 401 (pas
    connecté depuis la landing) → ouvrir le login d'abord.
  - Après login/register réussis : re-lire `/api/me` (ou utiliser la réponse) pour router vers
    `startApp()` **ou** `showPaywall()` au lieu d'appeler `startApp()` en dur.
  - **« Gérer mon abonnement »** dans le menu utilisateur de `#app-screen` (`id="manage-sub"`) :
    `const r = await API.post("/api/billing/portal"); location.href = r.url;`.
  - **Retour Stripe** : au chargement, si `location.search` contient `checkout=success` →
    nettoyer l'URL (`history.replaceState`) et laisser le routage `/api/me` décider (si le webhook
    a déjà activé → app ; sinon paywall avec bandeau « paiement reçu, activation en cours,
    actualisez dans un instant »). `checkout=cancel` → paywall simple.

### 6. Config / déploiement — `ORACLE_DEPLOY.md`

Documenter `SPORIA_PRICE_LABEL` (ex. `SPORIA_PRICE_LABEL="15 €/an"`) dans le `.env`, à **aligner
sur le prix Stripe**. Rappel : déployer 4.1 + 4.2 + 4.3 ensemble ; après migration, les comptes
existants non-admin sont **non abonnés** → paywall (accorder l'accès via Stripe, ou passer un
compte `role=admin`/`subscription_status=active` en base si besoin d'un accès offert).

## Tests (pytest)

- `tests/test_access.py` — `billing.has_access` : `None` → False ; `role=admin` → True ;
  `status=active` → True ; `status=canceled` mais `current_period_end` futur → True ;
  `current_period_end` passé → False ; `status=none` sans période → False.
- `tests/test_gating_routes.py` (TestClient) :
  - connecté **non abonné** → `/api/overlay?...` (et un autre GET data) renvoie **402** ;
  - connecté **abonné** (compte `subscription_status=active`) → même route ne renvoie pas 402
    (200 ou 4xx métier, mais pas 402) ;
  - **admin** non abonné → pas 402 ;
  - `/api/me` non connecté → `{authenticated: false, subscribed: false, price_label: "..."}` ;
  - `/api/me` connecté abonné → `subscribed: true` ;
  - route publique `/api/register` ou `/api/login` accessible sans abonnement (pas 402).

Fixtures : `SPORIA_DB` en `tmp_path`, `SESSION_SECRET` fort, comptes créés via `accounts`.
Le calcul d'accès s'appuie sur les colonnes du store (aucun appel Stripe → rien à mocker ici).

## Fichiers concernés

- **Créés** : `tests/test_access.py`, `tests/test_gating_routes.py`.
- **Modifiés** : `src/sporia/billing.py` (+`has_access`, +`import time`), `src/sporia/web/auth.py`
  (+`require_subscription`), `src/sporia/web/app.py` (swap dépendances data + `/api/me` enrichi),
  `web/index.html` (section pricing + `#paywall-screen` + « Gérer l'abonnement »), `web/app.js`
  (routage abonnement, `showPaywall`, `subscribe`, portail, retour Stripe), `ORACLE_DEPLOY.md`
  (`SPORIA_PRICE_LABEL`).

## Vérification

1. `pytest` + `ruff` verts ; nouveaux tests passent.
2. Manuel : compte non abonné → paywall, la carte est inaccessible (API 402) ; « S'abonner » →
   Checkout Stripe (test) → paiement `4242…` → retour `?checkout=success` → après webhook, l'app
   s'ouvre ; « Gérer mon abonnement » → portail ; admin → accès direct sans paywall.
3. Landing (déconnecté) affiche le prix (`price_label`).

## Hors périmètre

CGV/mentions légales/droit de rétractation (4.4) · refonte visuelle complète (4.5) · essai gratuit
· plusieurs plans/tarifs · facturation/relances (gérées par Stripe) · grandfathering automatique
des anciens comptes (manuel si besoin).
