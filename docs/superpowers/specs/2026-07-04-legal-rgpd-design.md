# Sporia — Chantier 4.4/5 : Légal & RGPD — Design

## Contexte

Chantier 4 (Monétisation) : (4.1) Comptes → (4.2) Stripe → (4.3) Gating/pricing *(tous FAITS,
mergés)* → **(4.4) Légal/RGPD** *(ce spec)* → (4.5) UX polish. L'app vend un **abonnement annuel**
en France ; il faut le socle **légal** (CGV, mentions légales, confidentialité, rétractation) et le
**droit RGPD à l'effacement** (suppression de compte self-service). Une modale `#cgu-modal` existe
(6 sections, rédigée pour un accès « sur invitation » — à moderniser).

## Décisions

- **Deux volets** : (A) suppression de compte (code, testé) ; (B) contenu légal (texte, avec
  **placeholders** `[À COMPLÉTER]` pour les infos que seul l'éditeur connaît : identité, SIRET,
  adresse, hébergeur).
- **Rétractation** : un service numérique à **accès immédiat** permet de faire **renoncer**
  l'utilisateur à son droit de rétractation de 14 jours (art. L221-28 3° C. conso), à condition de
  recueillir son **consentement exprès**. → case à cocher obligatoire sur le paywall avant paiement.
- **Suppression = effacement réel** (pas d'anonymisation) : ligne compte + tokens + préférences +
  spots supprimés ; abonnement Stripe **annulé best-effort**.
- **Non déployé seul** : mergé sur `main`, déployé avec 4.1+4.2+4.3.

## Volet A — Suppression de compte

### 1. Helpers de purge

- `accounts.delete_user(user_id: int) -> None` — `DELETE FROM users WHERE id=?` + `DELETE FROM
  tokens WHERE user_id=?`.
- `prefs.delete_user(username: str) -> None` — retire la clé `username` du JSON (verrou + écriture
  atomique, no-op si absente).
- `spots.delete_user(username: str) -> None` — idem sur `user_spots.json`.
- `billing.cancel_subscription(account: dict) -> None` — **best-effort** : si `stripe_enabled()` et
  `account["stripe_customer_id"]`, lister les abonnements du customer
  (`stripe.Subscription.list(customer=cid)`) et `stripe.Subscription.delete(sub.id)` chacun ;
  toute exception est loggée et avalée (la suppression de compte ne doit jamais échouer à cause de
  Stripe).

### 2. Route `DELETE /api/account`

`require_user` (un utilisateur supprime **son** compte). Séquence :
1. `account = accounts.get_by_email(user["username"])` ; si None → 404.
2. `billing.cancel_subscription(account)` (best-effort).
3. `prefs.delete_user(email)` ; `spots.delete_user(email)`.
4. `accounts.delete_user(account["id"])`.
5. `request.session.clear()`.
6. `return {"ok": True}`.

### 3. Frontend

Bouton **« Supprimer mon compte »** dans le header de l'app (`id="delete-account"`, style discret
rouge) → `confirm("Supprimer définitivement votre compte, vos préférences et vos spots ? Votre
abonnement sera résilié. Cette action est irréversible.")` → `API.del("/api/account")` →
`location.reload()`.

## Volet B — Contenu légal

Refondre `#cgu-modal` en **trois sections** clairement titrées (mêmes styles Tailwind existants) :

1. **CGU / CGV** : objet ; accès via **abonnement annuel** (remplace « sur invitation ») ; prix et
   reconduction (via le portail Stripe) ; avertissement sécurité (conservé : ne jamais consommer
   sans identification) ; **droit de rétractation** — clause de renonciation pour accès immédiat au
   service numérique ; responsabilité « en l'état ».
2. **Mentions légales** : éditeur `[À COMPLÉTER : nom / statut / SIRET / adresse / email]` ;
   directeur de publication `[À COMPLÉTER]` ; hébergeur `[À COMPLÉTER : Oracle Cloud / adresse]`.
3. **Politique de confidentialité (RGPD)** : responsable de traitement `[À COMPLÉTER]` ; données
   collectées (email, nom, mot de passe haché, préférences, spots, statut d'abonnement, id client
   Stripe) ; finalités (fourniture du service, facturation) ; **base légale** = exécution du
   contrat ; **sous-traitants** : Stripe (paiement), Brevo (emails), Oracle Cloud (hébergement) ;
   durée de conservation ; **droits** (accès, rectification, effacement, portabilité, opposition) ;
   **suppression self-service** (bouton dans l'app) ; contact `[À COMPLÉTER]`.

Le lien du pied de page « CGU » devient « CGU · Mentions · Confidentialité » (ouvre la même modale).

### Consentement rétractation (paywall)

Sur `#paywall-screen`, avant le bouton `#subscribe-btn` : case à cocher `#retract-consent`
(obligatoire) — « J'accepte les CGV et je demande l'accès immédiat au service, renonçant
expressément à mon droit de rétractation de 14 jours. » Le bouton S'abonner reste **désactivé**
tant que la case n'est pas cochée (JS). Un lien « lire les CGV » ouvre la modale.

## Tests (pytest)

- `tests/test_account_delete.py` :
  - `accounts.delete_user` : compte + token supprimés ; `get_by_email` → None ; idempotent (2e
    appel sans erreur).
  - `prefs.delete_user` / `spots.delete_user` : la clé disparaît, les autres comptes préservés,
    no-op si absente.
- `tests/test_account_route.py` (TestClient) :
  - `DELETE /api/account` sans session → 401 ;
  - avec session : préf + spot créés d'abord → après suppression, 200, `/api/me` →
    `authenticated: false`, `accounts.get_by_email` → None, prefs/spots purgés ;
  - Stripe non configuré (`stripe_enabled()` False) → aucune erreur (cancel best-effort no-op).
- `tests/test_cancel_subscription.py` : `billing.cancel_subscription` — sans customer → no-op ;
  avec customer + Stripe activé, `stripe.Subscription.list`/`delete` **mockés** → delete appelé
  pour chaque abonnement ; exception Stripe mockée → avalée (pas de levée).

Frontend non testé unitairement (convention projet) → vérif manuelle (bouton supprimer, case
rétractation désactive/active S'abonner).

## Fichiers concernés

- **Créés** : `tests/test_account_delete.py`, `tests/test_account_route.py`,
  `tests/test_cancel_subscription.py`.
- **Modifiés** : `src/sporia/users/accounts.py` (+`delete_user`), `src/sporia/users/prefs.py`
  (+`delete_user`), `src/sporia/users/spots.py` (+`delete_user`), `src/sporia/billing.py`
  (+`cancel_subscription`), `src/sporia/web/app.py` (+`DELETE /api/account`), `web/index.html`
  (modale légale 3 sections + bouton supprimer + case rétractation + libellé footer),
  `web/app.js` (`deleteAccount`, gating case rétractation ↔ bouton S'abonner).

## Vérification

1. `pytest` + `ruff` verts ; nouveaux tests passent.
2. Manuel : case rétractation décochée → S'abonner désactivé ; cochée → actif. Modale montre les
   3 sections. « Supprimer mon compte » → confirmation → compte parti, retour landing, reconnexion
   impossible.

## Hors périmètre

Refonte visuelle (4.5) · signature électronique des CGV · export de données automatisé (droit à la
portabilité au-delà de la demande manuelle) · registre RGPD des traitements (doc interne, hors
code) · bannière cookies (aucun cookie tiers/traceur — seul un cookie de session fonctionnel).
