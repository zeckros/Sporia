# Sporia — Chantier 4.2/5 : Paiement Stripe — Design

## Contexte

Le chantier 4 (Monétisation) vise un **abonnement annuel Stripe** (choix utilisateur), décomposé
en 5 sous-projets : (4.1) Comptes & auto-inscription *(FAIT, mergé sur `main`)* → **(4.2) Paiement
Stripe** *(ce spec)* → (4.3) Gating + pricing → (4.4) Légal/RGPD → (4.5) UX polish.

Le 4.1 a posé le socle : store SQLite `src/sporia/users/accounts.py` (identité = email) avec les
colonnes d'abonnement **déjà présentes** (`subscription_status TEXT DEFAULT 'none'`,
`stripe_customer_id TEXT`, `current_period_end INTEGER`), email transactionnel Brevo
(`src/sporia/email.py`), secrets via `.env`, `SessionMiddleware`, session
`user = {username: email, name, role}`.

**Objectif du 4.2** : brancher Stripe pour **vendre l'abonnement annuel** et **synchroniser
automatiquement** le statut d'abonné sur le compte. **Uniquement la mécanique de paiement** :
Checkout, Billing Portal, webhook signé/idempotent, helpers de store. Aucun blocage d'accès,
aucun affichage de prix (c'est le 4.3).

## Décisions

- **Sans essai gratuit** (choix utilisateur) : Checkout → paiement immédiat → accès. On pourra
  ajouter un `trial_period_days` plus tard sans refonte.
- **Stripe hébergé** : **Checkout** (mode `subscription`) + **Billing Portal**. Stripe gère la
  carte, la 3-D Secure/SCA, les relances (dunning) et l'annulation. **Aucune donnée de carte ne
  touche le serveur** (zéro charge PCI), très peu de code. Pas de Stripe Elements/formulaire maison.
- **Prix dans le dashboard Stripe** : le Produit/Prix annuel est créé côté Stripe et référencé par
  `STRIPE_PRICE_ID` en `.env`. **Le montant n'est jamais en dur** dans le code → ajustable sans
  redéploiement.
- **Mapping webhook → compte via `stripe_customer_id`** : à la 1re Checkout on crée (ou réutilise)
  un Stripe Customer lié au compte, on stocke son id ; les événements Stripe (renouvellement,
  annulation, échec) référencent ce customer → on retrouve le compte.
- **Bibliothèque `stripe`** (SDK Python officiel) ajoutée aux dépendances.
- **Secrets via `.env`** (comme `SESSION_SECRET`/`BREVO_API_KEY`) : `STRIPE_SECRET_KEY`,
  `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`, `PUBLIC_BASE_URL`. Absents en DEV → les routes
  billing renvoient **503** (fonctionnalité désactivée), l'app démarre normalement.

## Contrainte de déploiement

Comme 4.1, ce sous-projet **n'est pas déployé seul** : construit + testé + mergé sur `main`, mais
**poussé/déployé seulement avec 4.1 + 4.3** (le paiement n'a de sens qu'avec le gating). La prod
reste inchangée d'ici là.

## Modèle de statut

`accounts.subscription_status` (déjà en base) prend les valeurs :

| Statut      | Sens                                   | Déclencheur webhook                       |
|-------------|----------------------------------------|-------------------------------------------|
| `none`      | jamais abonné (défaut)                  | —                                         |
| `active`    | abonnement payé et courant              | `checkout.session.completed` ; `customer.subscription.updated` (status `active`) |
| `past_due`  | paiement de renouvellement échoué       | `invoice.payment_failed` ; `customer.subscription.updated` (status `past_due`)   |
| `canceled`  | abonnement résilié / terminé            | `customer.subscription.deleted`           |

`current_period_end` (epoch) est mis à jour à chaque événement d'abonnement (fin de période
courante = date de fin d'accès). Le **jugement « accès autorisé »** (ex. `active`, ou `canceled`
mais `current_period_end` encore dans le futur) est laissé au **4.3** ; le 4.2 se contente
d'écrire fidèlement le statut et la date.

## Périmètre & unités

### 1. Intégration Stripe — `src/sporia/billing.py`

Module isolé encapsulant **tout** l'appel à `stripe`. Lit la config depuis l'environnement.

- `stripe_enabled() -> bool` : `True` si `STRIPE_SECRET_KEY` et `STRIPE_PRICE_ID` présents.
- `create_checkout_session(account: dict) -> str` : garantit un `stripe_customer_id` pour le
  compte (via `_ensure_customer`), crée une **Checkout Session** `mode="subscription"`,
  `line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}]`, `customer=<id>`,
  `success_url=f"{PUBLIC_BASE_URL}/?checkout=success"`,
  `cancel_url=f"{PUBLIC_BASE_URL}/?checkout=cancel"`, `client_reference_id=<user_id>`. Renvoie
  `session.url`.
- `create_portal_session(account: dict) -> str` : **Billing Portal Session** pour le
  `stripe_customer_id` du compte, `return_url=f"{PUBLIC_BASE_URL}/"`. Renvoie `session.url`.
  (Erreur explicite si le compte n'a pas de customer.)
- `_ensure_customer(account: dict) -> str` : si `account["stripe_customer_id"]` existe, le renvoie ;
  sinon `stripe.Customer.create(email=…, name=…, metadata={"user_id": …})`, persiste l'id via
  `accounts.set_stripe_customer(user_id, cid)`, renvoie l'id.
- `process_event(payload: bytes, sig_header: str) -> None` : vérifie la signature via
  `stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)` (lève en cas de
  signature invalide → route renvoie 400), puis **dispatch idempotent** :
  - `checkout.session.completed` → `_apply_active(customer_id, subscription_id)`.
  - `customer.subscription.updated` → map `stripe status` → notre statut + `current_period_end`.
  - `customer.subscription.deleted` → `canceled` (+ `current_period_end`).
  - `invoice.payment_failed` → `past_due`.
  - autres événements → ignorés (no-op, 200).
  La mise à jour passe par `accounts.get_by_stripe_customer(customer_id)` puis
  `accounts.set_subscription(...)`. Compte introuvable → log + no-op (200, pas d'erreur).

### 2. Helpers de store — `src/sporia/users/accounts.py`

Nouveaux helpers (le schéma existe déjà, aucune migration de colonne) :

- `set_stripe_customer(user_id: int, stripe_customer_id: str) -> None`.
- `get_by_stripe_customer(stripe_customer_id: str) -> dict | None`.
- `set_subscription(user_id: int, status: str, current_period_end: int | None = None) -> None`
  (met à jour `subscription_status`, `current_period_end` si fourni, `updated_at`). **Idempotent**
  (réécrire le même statut est sans effet de bord).

`get_by_email`/`get_by_stripe_customer` renvoient un dict incluant `id`, `email`, `name`, `role`,
`subscription_status`, `stripe_customer_id`, `current_period_end`.

### 3. Routes — `src/sporia/web/app.py`

- `POST /api/billing/checkout` (**auth requise**) → `create_checkout_session` du compte courant →
  `{"url": …}`. Si `not stripe_enabled()` → **503**.
- `POST /api/billing/portal` (**auth requise**) → `create_portal_session` → `{"url": …}`. 503 si
  désactivé ; 400 si le compte n'a pas encore de customer (jamais passé au paiement).
- `POST /api/stripe/webhook` (**public, non authentifié**) : lit le **corps brut**
  (`await request.body()`) + en-tête `Stripe-Signature`, appelle `process_event`. Signature
  invalide → **400** ; sinon **200** (`{"received": true}`). **Aucune session/CSRF** sur cette
  route (appelée par Stripe, pas par le navigateur).

`require_user` (existant) fournit le compte de session ; on **recharge** le compte frais depuis le
store (`accounts.get_by_email`) avant de créer une session Checkout/Portal (pour avoir
`id`/`stripe_customer_id` à jour).

### 4. Config — `.env` + `src/sporia/config.py`

Variables lues via l'environnement (jamais commitées) :
`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`, `PUBLIC_BASE_URL`
(ex. `https://sporia.duckdns.org` en prod, `http://localhost:8000` en dev). `billing.py` les lit
directement via `os.environ` (comme `email.py` pour Brevo) — pas besoin de les faire transiter par
l'objet `settings`, mais on documente leur présence attendue.

### 5. Dépendance

Ajouter `stripe` (SDK officiel) dans `pyproject.toml` (deps runtime) + régénérer `requirements.lock`.

## Frontend

**Hors périmètre 4.2.** Les boutons « S'abonner » / « Gérer mon abonnement » et l'affichage du prix
sont le **4.3**. En 4.2 la mécanique se teste par API (`curl`/`TestClient`) + Stripe CLI. Les
`success_url`/`cancel_url` pointent vers `/` avec un `?checkout=success|cancel` que le 4.3
exploitera pour l'UX post-paiement.

## Tests

Tous les appels réseau Stripe sont **mockés** (aucun appel réel en CI).

- `tests/test_accounts_billing.py` : `set_stripe_customer` puis `get_by_stripe_customer` retrouve le
  compte ; `set_subscription` écrit statut + `current_period_end` ; idempotence (2 appels →
  1 état) ; DB en `tmp_path`.
- `tests/test_billing.py` :
  - `_ensure_customer` : compte sans customer → `stripe.Customer.create` mocké appelé + id persisté ;
    compte avec customer → pas de création.
  - `process_event` avec `construct_event` mocké renvoyant un faux event :
    `checkout.session.completed` → compte `active` ; `customer.subscription.deleted` → `canceled` ;
    `invoice.payment_failed` → `past_due` ; `customer.subscription.updated` (past_due) → `past_due` +
    `current_period_end` mis à jour ; customer inconnu → no-op sans exception.
  - signature invalide (`construct_event` lève `SignatureVerificationError`) → `process_event` lève.
- `tests/test_billing_routes.py` (TestClient) : `/api/billing/checkout` et `/api/billing/portal`
  sans session → **401** ; avec session mais `stripe_enabled()` False → **503** ;
  `/api/stripe/webhook` avec signature invalide → **400** ; avec event valide mocké → **200** et
  compte mis à jour. `create_checkout_session`/`create_portal_session` mockés pour renvoyer une URL.

## Fichiers concernés

- **Créés** : `src/sporia/billing.py`, `tests/test_billing.py`, `tests/test_billing_routes.py`,
  `tests/test_accounts_billing.py`.
- **Modifiés** : `src/sporia/users/accounts.py` (3 helpers), `src/sporia/web/app.py` (3 routes),
  `pyproject.toml` + `requirements.lock` (dep `stripe`), `.env.example`/`ORACLE_DEPLOY.md`
  (variables Stripe + création Produit/Prix + endpoint webhook).

## Vérification

1. `pytest` + `ruff` verts ; nouveaux tests passent (Stripe mocké).
2. **Manuel (mode test Stripe)** : `.env` avec clés de test + `STRIPE_PRICE_ID` d'un prix test ;
   `stripe listen --forward-to localhost:8000/api/stripe/webhook` ; connecté,
   `POST /api/billing/checkout` → ouvrir l'URL → payer avec `4242 4242 4242 4242` → le webhook
   passe le compte à `active` (vérifier en base) ; `POST /api/billing/portal` → ouvre le portail ;
   annuler dans le portail → webhook → compte `canceled`.
3. `stripe_enabled()` False (pas de clés) → routes billing renvoient 503, le reste de l'app
   fonctionne (démarrage, login, overlays).

## Déploiement (avec 4.1 + 4.3)

Dans le dashboard Stripe : créer le **Produit + Prix annuel récurrent** (montant ~10-20€/an),
créer l'**endpoint webhook** `https://sporia.duckdns.org/api/stripe/webhook` (événements
`checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`,
`invoice.payment_failed`), récupérer `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` /
`STRIPE_PRICE_ID` → `.env` du serveur. Passer en clés **live** au go-live (nécessite la
vérification d'identité Stripe du compte). nginx : `/api/stripe/webhook` passe déjà par le proxy
`/api/` (pas d'auth) — s'assurer que le rate-limiting `/api/` ne bloque pas les rafales de webhooks
(zone permissive, ou exception pour ce path).

## Hors périmètre

Gating/paywall + affichage du prix + boutons UI (4.3) · CGV/mentions légales/droit de rétractation
(4.4) · refonte UX (4.5) · essai gratuit (`trial_period_days`, ajout futur trivial) · factures/TVA
au-delà de ce que Stripe gère nativement · plusieurs plans/tarifs (un seul prix annuel).
