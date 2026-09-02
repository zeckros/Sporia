# Sporia — Comptes bêta-testeurs — Design

## Contexte

Deux chemins mènent aujourd'hui à un compte Sporia :

- `/api/register` — auto-inscription publique. L'inscrit paie l'abonnement (15 €/an).
- `/api/access-request` — demande d'accès publique, examinée par un admin, qui crée le compte
  via `POST /api/admin/accounts/from-request`.

Le second chemin sert au recrutement des bêta-testeurs, mais `accounts.create_user` laisse
`subscription_status` à sa valeur par défaut `'none'`. `billing.has_access` renvoie donc `False`
et le testeur, pourtant accepté, se heurte au paywall et doit payer.

**Objectif** : une demande acceptée donne un compte débloqué, gratuitement, et l'admin peut
basculer n'importe quel compte en bêta après coup.

Acquis mobilisés : table `users` (`role`, `subscription_status`, `current_period_end`,
`stripe_customer_id`) ; `billing.has_access` ; modale admin « Demandes d'accès » ;
`/api/me` qui pilote l'affichage du menu compte.

## Décisions

- **L'accès bêta est un `subscription_status`**, valeur `'beta'`. La colonne existe déjà en TEXT :
  aucune migration de schéma. `has_access` l'accepte au même titre que `'active'`.
- **Toute demande acceptée devient bêta.** Pas de choix au moment d'accepter : le formulaire de
  demande d'accès *est* le programme bêta. L'auto-inscription publique reste payante.
- **Pas de migration des comptes existants.** Le rattrapage se fait par l'écran admin, à la main.
- **La bascule est réversible** (`beta` ⇄ `none`) et refuse deux cas : un compte admin (le rôle
  donne déjà l'accès) et un compte à abonnement Stripe actif (on n'écrase pas un payant).
- **Le testeur voit son statut** : « Accès bêta — offert » à la place de « Mon abonnement ».

### Alternatives écartées

- **Colonne dédiée `beta_access`** — orthogonale à l'état Stripe, elle conserverait la trace d'un
  ancien testeur devenu payant. Écartée : migration de schéma et deux sources de vérité dans
  `has_access`, pour un historique dont personne n'a exprimé le besoin.
- **`role = 'beta'`** — le rôle porte les permissions, pas le droit d'accès. Un testeur ne pourrait
  plus être admin, ni un admin être testeur.

### Pourquoi le statut Stripe ne peut pas écraser un bêta

Un testeur n'a pas de `stripe_customer_id`. Or les webhooks résolvent le compte *par* cet
identifiant (`accounts.get_by_stripe_customer`). Aucun événement Stripe ne peut donc viser un
compte bêta tant qu'il n'a pas lui-même engagé un paiement. S'il s'abonne un jour, le webhook le
passe en `'active'` — comportement souhaitable, il devient un payant.

## Périmètre & unités

### 1. Règle d'accès — `src/sporia/billing.py`

`has_access` accepte `'beta'` :

```python
if account.get("subscription_status") in ("active", "beta"):
    return True
```

Le reste (admin, grâce jusqu'à `current_period_end`) est inchangé.

### 2. Acceptation d'une demande — `src/sporia/web/app.py`

`api_create_account_from_request` passe le compte en `'beta'` juste après `create_user`, avant
l'envoi du lien d'invitation. Le corps du mail et le jeton de 7 jours ne changent pas.

### 3. Lecture des comptes — `src/sporia/users/accounts.py`

```python
def list_accounts(limit: int = 500) -> tuple[list[dict], bool]:
    """Comptes du plus récent au plus ancien. Renvoie (liste, truncated)."""
```

Champs exposés : `id`, `email`, `name`, `role`, `subscription_status`, `current_period_end`,
`created_at`. **Jamais `password_hash` ni `stripe_customer_id`.** Le drapeau `truncated` dit
explicitement que la liste est plafonnée, plutôt que de laisser croire qu'elle est complète.

### 4. Bascule d'accès — aucune nouvelle fonction

`accounts.set_subscription(user_id, status)` fait déjà exactement cela : l'endpoint l'appelle avec
`'beta'` ou `'none'`. Pas de helper supplémentaire — les contrôles (admin, payant) appartiennent à
la couche web, pas au store.

### 5. Endpoints admin — `src/sporia/web/app.py`

| Route | Méthode | Réponse |
|---|---|---|
| `/api/admin/accounts` | GET | `{accounts: [...], truncated: bool}` |
| `/api/admin/accounts/access` | POST | `{ok: true, email, status}` |

Les deux sous `Depends(require_admin)`. Corps du POST : `{email: str, status: "beta" \| "none"}`.

Erreurs :

- **403** — appelant non-admin (déjà porté par `require_admin`).
- **404** — email inconnu.
- **409** — le compte visé est admin.
- **409** — le compte a `subscription_status == 'active'` (payant Stripe).
- **400** — `status` hors des deux valeurs admises.

### 6. Statut exposé au frontend — `/api/me`

Ajout d'un champ `access` calculé côté serveur :

| Valeur | Condition |
|---|---|
| `admin` | `role == 'admin'` |
| `beta` | `subscription_status == 'beta'` |
| `paid` | `has_access` vrai sans être l'un des deux précédents |
| `none` | `has_access` faux |

`subscribed` est conservé tel quel : le frontend existant continue de fonctionner sans
modification, et `access` ne sert qu'à l'affichage.

### 7. Interface — `web/js/main.js`, `templates/partials/modals.html`, `partials/app.html`

- Modale **« Comptes »**, admin-only, sur le modèle de « Demandes d'accès » : une ligne par compte
  (email, nom, statut lisible, date), un champ de filtre texte, un bouton de bascule par ligne.
  Le bouton est désactivé pour les comptes admin et payants, avec l'explication en `title`.
- Entrée « 👥 Comptes » dans le menu compte et dans le panneau profil mobile, à côté de
  « Demandes d'accès », portant la classe `admin-only` existante.
- Menu compte : quand `access === 'beta'`, « Mon abonnement » cède la place à un libellé non
  cliquable « Accès bêta — offert ».
- Bandeau `truncated` affiché en tête de liste le cas échéant.

## Tests

`tests/test_beta_access.py` :

- `has_access` vrai pour `subscription_status='beta'`, faux pour `'none'`.
- `from-request` crée un compte dont le statut vaut `'beta'`.
- `GET /api/admin/accounts` : 403 pour un non-admin ; la charge utile ne contient ni
  `password_hash` ni `stripe_customer_id`.
- `POST .../access` : bascule `none → beta` puis `beta → none` ; 404 sur email inconnu ;
  409 sur compte admin ; 409 sur compte `active` ; 400 sur statut invalide.
- `/api/me` renvoie `access` correct pour les quatre cas (admin, beta, paid, none).
- Un compte bêta obtient bien 200 sur une route protégée par `require_subscription`
  (là où un compte `none` reçoit 402).

Fixtures existantes : `monkeypatch.setenv("SPORIA_DB", tmp_path)`, comptes créés via `accounts`.

## Hors périmètre

- Migration en masse des comptes existants (décision explicite : rattrapage à la main).
- Date de fin de bêta et bascule automatique vers le paywall.
- Parcours « s'abonner quand même » pour un testeur.
- Pagination et recherche serveur de la liste des comptes ; le plafond à 500 et le drapeau
  `truncated` tiennent lieu de garde-fou jusqu'à ce que le volume l'exige.
