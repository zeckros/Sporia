# Sporia — Chantier 4.1/5 : Comptes & auto-inscription — Design

## Contexte

Le chantier 4 (Monétisation) vise un **abonnement annuel Stripe** (choix utilisateur), décomposé
en 5 sous-projets : **(4.1) Comptes & auto-inscription** *(ce spec)* → (4.2) Paiement Stripe →
(4.3) Gating + pricing → (4.4) Légal/RGPD → (4.5) UX polish.

Aujourd'hui l'app est **sur invitation** : comptes statiques dans `config.yaml` (bcrypt), pas
d'auto-inscription ; l'auth (`sporia/web/auth.py`) lit `config.yaml` ; `user_prefs`/`user_spots`
sont des JSON par compte, **clés = username**. Le frontend a déjà une landing et un formulaire
« demande d'accès ».

**Objectif du 4.1** : socle de comptes **dynamique** qui débloque le billing — inscription
self-service, connexion, reset de mot de passe, schéma prêt pour l'abonnement. **Sans casser la
prod** et **sans être déployé seul** (voir contrainte de déploiement).

## Décisions

- **Store = SQLite** (`data/sporia.db`, gitignoré) via le module stdlib `sqlite3`.
- **Identité = email** (login par email). Les comptes migrés (theo…) basculent sur leur email ;
  leurs `user_prefs`/`user_spots` sont **remappés** username→email à la migration.
- **Email = service transactionnel** (Brevo par défaut, français/RGPD), derrière une abstraction
  `send_email()` swappable ; clé dans `.env` (`BREVO_API_KEY`, `MAIL_FROM`).
- **Vérification email non bloquante** : compte utilisable dès l'inscription ; `email_verified`
  suivi mais pas requis pour se connecter (le vrai gate = le paiement, en 4.3).
- **Suppression de compte (RGPD) décalée** au sous-projet 4.4 (Légal).

## Contrainte de déploiement

Ce socle **ouvre l'auto-inscription** (accès gratuit à tous tant que le paywall n'existe pas).
→ **Non déployé seul en prod.** Construit + testé + mergé sur `main`, mais **poussé/déployé
seulement avec 4.2 (paiement) + 4.3 (gating)**. La prod reste sur invitation d'ici là.

## Périmètre & unités

### 1. Store de comptes — `src/sporia/users/accounts.py`

SQLite (`settings.data_dir / "sporia.db"`), schéma créé à la volée (idempotent) :
```
users(id INTEGER PK, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
      name TEXT, role TEXT DEFAULT 'user', email_verified INTEGER DEFAULT 0,
      subscription_status TEXT DEFAULT 'none', stripe_customer_id TEXT,
      current_period_end INTEGER, created_at INTEGER, updated_at INTEGER)
tokens(token TEXT PK, user_id INTEGER NOT NULL, kind TEXT NOT NULL,  -- 'reset' | 'verify'
       expires_at INTEGER NOT NULL)
```
API : `init_db()` ; `create_user(email, password, name=None, role='user') -> dict` (bcrypt,
409/ValueError si email existe) ; `get_by_email(email) -> dict | None` ; `verify_password(email,
password) -> dict | None` (temps constant via hash leurre, cf. auth actuel) ; `set_password(user_id,
password)` ; `set_verified(user_id)` ; `create_token(user_id, kind, ttl_s) -> str` (token
`secrets.token_urlsafe`) ; `consume_token(token, kind) -> user_id | None` (usage unique + expiration).
Les colonnes abonnement (`subscription_status`, `stripe_customer_id`, `current_period_end`)
existent mais restent à leur défaut (remplies par 4.2).

### 2. Envoi d'email — `src/sporia/email.py`

`send_email(to: str, subject: str, html: str) -> bool` : POST API Brevo (`requests`), clé/expéditeur
depuis l'environnement (`BREVO_API_KEY`, `MAIL_FROM`). En l'absence de clé (DEV) → log + `False`
(pas d'échec dur). Deux gabarits : email de vérification, email de reset (lien
`https://<host>/verify-email?token=…` / page reset).

### 3. Auth sur le store — `src/sporia/web/auth.py`

- `verify(email, password)` lit désormais **le store SQLite** (`accounts.verify_password`) au lieu de
  `config.yaml`. Renvoie `{username: <email>, name, role}` (session inchangée dans sa forme).
- `require_admin` : vérifie le **rôle porté par la session** (`user["role"] == "admin"`) plutôt que
  `admin_usernames(config.yaml)`. Le rôle est mis en session au login.
- `config.yaml` n'est plus lu par l'auth après migration (conservé uniquement comme source de seed).

### 4. Routes — `src/sporia/web/app.py`

- `POST /api/register` `{email, password, name?}` → `create_user` + envoi email de vérification +
  ouverture de session (connecté directement). 409 si email déjà pris ; 400 si email/mdp invalides
  (email regex existant ; mdp ≥ 8).
- `POST /api/login` : inchangé en surface, mais passe par le nouveau `verify` (login par email).
- `POST /api/password/forgot` `{email}` → si compte existe, `create_token(reset)` + email (réponse
  **toujours 200** neutre, anti-énumération).
- `POST /api/password/reset` `{token, password}` → `consume_token(reset)` + `set_password`.
- `GET /api/verify-email?token=…` → `consume_token(verify)` + `set_verified` → redirige vers l'app.
- Rate-limiting : couvert par nginx (zone `/api/` + `/api/login` stricte déjà en place ; `register`
  et `forgot` tombent dans la zone `/api/`).

### 5. Migration — `scripts/migrate_accounts.py`

Idempotent : si la table `users` est vide, sème depuis `config.yaml` (email, hash, name, role) ;
puis **remappe** `data/user_prefs.json` et `data/user_spots.json` (clé username → email
correspondant). Exécuté une fois au déploiement (documenté dans ORACLE_DEPLOY.md).

### 6. Frontend minimal — `web/index.html` + `web/app.js`

- Formulaire **« Créer un compte »** (email, mot de passe, nom) sur la landing → `POST /api/register`
  → bascule dans l'app. (La section « demande d'accès » actuelle est remplacée/complétée.)
- Lien **« Mot de passe oublié »** sur l'écran de connexion → `POST /api/password/forgot` + écran de
  saisie du nouveau mot de passe (`/api/password/reset`).
- UX volontairement sobre (la refonte est en 4.5).

## Tests

- `tests/test_accounts.py` : `create_user` (hash ≠ clair ; 2e même email → erreur) ; `verify_password`
  (bon/mauvais mdp/inconnu) ; `create_token`/`consume_token` (usage unique, expiré → None) ; DB en
  `tmp_path` (monkeypatch du chemin, pas de state partagé).
- `tests/test_register_flow.py` (TestClient, envoi email **mocké**) : register crée le compte + session ;
  email dupliqué → 409 ; forgot répond 200 neutre même email inconnu ; reset avec token valide change
  le mdp ; login post-register OK.
- Non-régression : `test_auth`/`test_admin` adaptés au store (ou seed d'un compte de test).

## Fichiers concernés

- Créés : `src/sporia/users/accounts.py`, `src/sporia/email.py`, `scripts/migrate_accounts.py`,
  `tests/test_accounts.py`, `tests/test_register_flow.py`.
- Modifiés : `src/sporia/web/auth.py` (verify + require_admin sur store), `src/sporia/web/app.py`
  (routes register/login/password/verify), `web/index.html` + `web/app.js` (signup + forgot),
  `.env`/`ORACLE_DEPLOY.md` (BREVO_API_KEY, MAIL_FROM, migration).

## Vérification

1. `pytest` + `ruff` verts ; nouveaux tests passent.
2. Inscription d'un compte de test → connexion → `/api/me` authentifié ; email dupliqué → 409.
3. Reset : forgot (200 neutre) → token → reset → login avec le nouveau mdp.
4. Migration idempotente : lancer 2× ne duplique pas ; theo (migré) se connecte par email, ses
   spots/prefs préservés (remappés).
5. `require_admin` : compte `role=user` → 403 sur `/api/access-requests` ; `role=admin` → OK.

## Hors périmètre

Stripe/abonnement (4.2) · gating/paywall + pricing affiché (4.3) · CGV/RGPD + suppression de compte
self-service (4.4) · refonte UX + badge confiance + CSP (4.5) · dual-login email+username (YAGNI :
login par email uniquement).
