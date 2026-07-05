# Checklist de déploiement — Monétisation (chantiers 3 + 4.1→4.5)

Déploiement **conjoint** de : hygiène modèle (3) + Comptes (4.1) + Stripe (4.2) + Gating/paywall
(4.3) + Légal/RGPD (4.4) + Badge de confiance (4.5). **Ne jamais déployer 4.1 seul** (ouvrirait
l'inscription gratuite sans paywall).

> **Règles apprises (incident 502)** : on se connecte en SSH **en `ubuntu`** (le seul sudoer) ;
> `app` n'est PAS sudoer. Exécuter les commandes **une par une** (ne pas coller de bloc multi-lignes
> — le shell peut mal découper les chemins). `sudo -u app …` = opérations repo/venv en tant que
> `app` ; `sudo systemctl …` = en root. Adapter le chemin du repo si besoin
> (`/home/app/champi_pipeline_package` ou `/home/app/Sporia`).

---

## Phase 0 — En local (machine de dev), avant de toucher au serveur

```
venv/Scripts/python.exe -m pytest -q
```
Attendu : `116 passed`. Puis pousser `main` (contient 3 + 4.1→4.5, non poussés) :
```
git push origin main
```

---

## Phase 1 — Stripe (dashboard, aucune commande serveur) — **mode test d'abord**

1. **Produit + Prix** : Products → Add product « Sporia » → prix **récurrent annuel** (montant visé,
   ~10-20 €/an) → copier l'ID du prix `price_...`.
2. **Webhook** : Developers → Webhooks → Add endpoint
   `https://sporia.duckdns.org/api/stripe/webhook` → événements :
   `checkout.session.completed`, `customer.subscription.updated`,
   `customer.subscription.deleted`, `invoice.payment_failed` → copier le **signing secret**
   `whsec_...`.
3. **Clé API** : Developers → API keys → copier la **clé secrète** de test `sk_test_...`.

Garder sous la main : `sk_test_...`, `whsec_...`, `price_...`.

---

## Phase 2 — Serveur : sauvegardes puis mise à jour du code

Se connecter :
```
ssh -i ~/.ssh/sporia/ssh-key.key ubuntu@<ip-oracle>
```
Aller dans le repo :
```
cd /home/app/champi_pipeline_package
```
**Sauvegardes** (secrets + base comptes + config) — datées :
```
sudo -u app cp -a .env .env.bak.$(date +%F)
```
```
sudo -u app cp -a config.yaml config.yaml.bak.$(date +%F)
```
```
test -f data/sporia.db && sudo -u app cp -a data/sporia.db data/sporia.db.bak.$(date +%F) || echo "pas encore de sporia.db (1er passage)"
```
Noter le commit actuel (pour rollback) :
```
sudo -u app git rev-parse --short HEAD
```
Récupérer le code :
```
sudo -u app git pull origin main
```
Réinstaller le paquet (récupère la nouvelle dépendance `stripe`) :
```
sudo -u app ./venv/bin/pip install -e .
```
Vérifier que `stripe` est bien là :
```
sudo -u app ./venv/bin/python -c "import stripe; print(stripe.VERSION)"
```

---

## Phase 3 — Rôle admin (AVANT migration) + variables `.env`

**3a. S'assurer que ton compte admin a `role: admin` dans `config.yaml`** (sinon tu seras paywallé
après migration). Éditer :
```
sudo -u app nano config.yaml
```
Sous ton compte (identifié par son email), vérifier la présence de `role: admin`. Sauver.

**3b. Éditer le `.env`** (chargé par systemd `EnvironmentFile`) :
```
sudo -u app nano .env
```
Vérifier/compléter ces lignes (une par ligne, sans espace autour du `=`) :
```
PROD=1
SESSION_SECRET=<clé forte ≥32 car. — déjà présente depuis le chantier 2 ; NE PAS changer>
BREVO_API_KEY=<clé API Brevo>
MAIL_FROM=no-reply@sporia.duckdns.org
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...
PUBLIC_BASE_URL=https://sporia.duckdns.org
SPORIA_PRICE_LABEL=15 €/an
```
> `SESSION_SECRET` **doit** exister (sinon l'app refuse de démarrer en PROD). Si absent :
> `python -c "import secrets;print(secrets.token_urlsafe(48))"` puis l'ajouter.
> `SPORIA_PRICE_LABEL` doit correspondre au montant réel du prix Stripe.

**3c. Placeholders légaux** : les mentions légales / confidentialité contiennent des
`[À COMPLÉTER]` (identité éditeur, SIRET, hébergeur, email de contact). Les remplir dans
`web/index.html` (modale légale) **avant l'ouverture commerciale** — éditable à chaud :
```
sudo -u app nano web/index.html
```
(chercher « À COMPLÉTER »).

---

## Phase 4 — Migration des comptes vers SQLite (**une seule fois**)

Bascule `config.yaml` → `data/sporia.db` + remappe `user_prefs`/`user_spots` (clé username → email).
Idempotent (relançable sans dommage). Depuis le repo :
```
sudo -u app ./venv/bin/python scripts/migrate_accounts.py
```
Après ça : **connexion par email**. Sauvegarder désormais `data/sporia.db` au même titre que
`config.yaml`.

> Filet de sécurité — accès offert à un compte sans passer par Stripe (ex. toi si le rôle admin
> n'a pas pris, ou un bêta-testeur) :
> ```
> sudo -u app ./venv/bin/python -c "import sqlite3,sys; c=sqlite3.connect('data/sporia.db'); c.execute(\"UPDATE users SET role='admin' WHERE email=?\", ('TON_EMAIL',)); c.commit(); print('rows', c.total_changes)"
> ```
> (ou `subscription_status='active'` au lieu de `role='admin'` pour un accès abonné offert.)

---

## Phase 5 — Redémarrer et vérifier

Redémarrer le web (relit `.env`, code, front) :
```
sudo systemctl restart champimap.service
```
État + logs (Ctrl-C pour quitter le suivi) :
```
sudo systemctl status champimap.service --no-pager
```
```
sudo journalctl -u champimap.service -n 40 --no-pager
```
Vérifs fonctionnelles (depuis ta machine ou la VM) :
```
curl -s https://sporia.duckdns.org/api/me
```
Attendu : `{"authenticated":false,...,"subscribed":false,...,"price_label":"15 €/an"}`.

Dans le navigateur (https://sporia.duckdns.org) :
- **Toi (admin)** : connexion par email → **la carte s'ouvre directement** (pas de paywall),
  bouton « Mon abonnement » visible.
- **Compte de test non-abonné** (inscris-en un) → **écran paywall** ; la carte est inaccessible
  (les appels data renvoient 402).
- **Modale légale** (pied de page « CGU · Mentions · Confidentialité ») : 3 sections présentes,
  placeholders remplis.

---

## Phase 6 — Test bout-en-bout du paiement (mode test Stripe)

1. Sur le paywall d'un compte test : cocher la **case de rétractation** (le bouton « S'abonner »
   s'active) → cliquer → redirection Stripe Checkout.
2. Payer avec la carte de test **`4242 4242 4242 4242`**, date future, CVC quelconque.
3. Retour sur `…/?checkout=success`. Le webhook Stripe passe le compte à `active` →
   **la carte s'ouvre**. Vérifier côté Stripe (Dashboard → Webhooks) que l'événement est **200**.
4. « Mon abonnement » → ouvre le **portail Stripe** ; y résilier → webhook → l'accès reste jusqu'à
   la fin de période puis se coupe.

Si le webhook échoue (non-200) : vérifier `STRIPE_WEBHOOK_SECRET` dans `.env` et que nginx laisse
passer `/api/stripe/webhook` (zone `/api/`, pas de blocage).

---

## Phase 7 — Passage en production réelle (clés live)

Quand tout est validé en test **et** que le compte Stripe est vérifié (identité/SIRET) :
1. Refaire la Phase 1 en **mode live** (nouveau produit/prix live, nouvel endpoint webhook live).
2. Mettre à jour `.env` avec `sk_live_...`, le nouveau `whsec_...` live, le `price_...` live.
3. `sudo systemctl restart champimap.service`
4. Refaire un achat réel (petit montant) pour valider, puis rembourser via le portail si besoin.

---

## Rollback (si un déploiement casse)

Revenir au commit précédent (celui noté en Phase 2) :
```
cd /home/app/champi_pipeline_package
```
```
sudo -u app git checkout <commit-court-précédent>
```
```
sudo -u app ./venv/bin/pip install -e .
```
```
sudo systemctl restart champimap.service
```
Restaurer les sauvegardes si nécessaire :
```
sudo -u app cp -a .env.bak.<date> .env
```
```
sudo -u app cp -a data/sporia.db.bak.<date> data/sporia.db
```
```
sudo systemctl restart champimap.service
```
> ⚠️ La migration comptes (Phase 4) est idempotente mais **ne se dé-migre pas** ; c'est pourquoi on
> sauvegarde `data/sporia.db` et `config.yaml` avant. En cas de gros souci, restaurer la sauvegarde
> `sporia.db` (ou la supprimer pour re-semer depuis `config.yaml` via une nouvelle migration).

---

## Récapitulatif « une page »

| Phase | Où | Action |
|------|----|--------|
| 0 | local | `pytest` vert → `git push origin main` |
| 1 | Stripe | créer prix annuel + webhook + clé (test) |
| 2 | serveur (ubuntu) | backups → `git pull` → `pip install -e .` |
| 3 | serveur | `role: admin` dans config.yaml + `.env` (Brevo, Stripe, PUBLIC_BASE_URL, SPORIA_PRICE_LABEL) + placeholders légaux |
| 4 | serveur | `migrate_accounts.py` (une fois) |
| 5 | serveur | `restart champimap` + vérifs (admin=carte, test=paywall) |
| 6 | navigateur | paiement test `4242…` → webhook 200 → accès |
| 7 | plus tard | bascule clés **live** (compte Stripe vérifié) |
