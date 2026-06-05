# Déploiement ChampiMap sur Oracle Cloud Free Tier

Guide de mise en ligne de **ChampiMap** (collecte de données + site web **FastAPI**) sur une VM
Oracle Cloud Free Tier (Ubuntu, ARM), derrière **nginx + HTTPS (Let's Encrypt)**.

> Architecture : `scheduler.service` (collecte radar/stations/AROME) + `champimap.service`
> (FastAPI/uvicorn sur `127.0.0.1:8000`) exposé via **nginx** en `:80/:443`. L'ancienne stack
> Streamlit n'est plus utilisée.

---

## Prérequis
- Compte Oracle Cloud Free Tier
- Un **nom de domaine** pointant (enregistrement A) vers l'IP publique de la VM — requis pour le
  HTTPS (Let's Encrypt). Sans domaine, le site fonctionne en HTTP seul (déconseillé : la connexion
  circule en clair).
- Clés API **Météo-France** (https://portail-api.meteofrance.fr) pour la collecte.

---

## Étape 1 — Créer la VM
1. **Compute → Instances → Create Instance**
   - Image : **Ubuntu 22.04 LTS** (ARM/Ampere, free tier)
   - Shape : Ampere (1 OCPU / 1 Go RAM minimum ; 2-4 Go recommandé si possible)
   - Téléchargez la **clé SSH**
2. Notez l'**IP publique** une fois l'instance **RUNNING**.

---

## Étape 2 — Se connecter en SSH
```bash
chmod 600 ssh-key-XXXX.key
ssh -i ssh-key-XXXX.key ubuntu@<ip-oracle>
```
(Windows/PowerShell : `ssh -i "C:\chemin\ssh-key-XXXX.key" ubuntu@<ip-oracle>`)

---

## Étape 3 — Déployer
```bash
git clone https://github.com/<vous>/champi_pipeline_package.git
cd champi_pipeline_package

# Déploiement (domaine/email → HTTPS automatique)
sudo REPO_URL=https://github.com/<vous>/champi_pipeline_package.git \
     DOMAIN=mondomaine.fr EMAIL=moi@exemple.fr \
     bash oracle_deploy.sh
```

**Ce que fait le script (`oracle_deploy.sh`) :**
1. Paquets système (Python, **libs géo GDAL/GEOS/PROJ**, **nginx**, **certbot**)
2. Utilisateur `app` non-root
3. Clone + venv + `pip install -r requirements.txt` (+ `schedule`)
4. **Génère `config.yaml`** avec une **clé de session aléatoire forte** et un compte **admin**
   (mot de passe affiché une fois — à noter)
5. Crée un **`.env`** vide pour les clés API (à remplir, sinon la collecte ne tourne pas)
6. Installe et démarre les services **`scheduler`** + **`champimap`**
7. Configure **nginx** (reverse proxy → `127.0.0.1:8000`)
8. Obtient le **certificat TLS** via certbot (si DOMAIN/EMAIL fournis)

---

## Étape 4 — Renseigner les secrets

### Clés API Météo-France (collecte)
```bash
sudo -u app nano /home/app/champi_pipeline_package/.env
# Renseigner API_KEY_AROME / API_KEY_STATIONS / API_KEY_RADAR puis :
sudo systemctl restart scheduler.service
```

### Comptes utilisateurs (en plus de `admin`)
```bash
cd /home/app/champi_pipeline_package
sudo -u app ./venv/bin/python scripts/make_users.py <login> "<mot_de_passe_fort>" "Nom" email@x.fr
sudo systemctl restart champimap.service   # config.yaml relue au démarrage
```
> ⚠️ `config.yaml` et `.env` contiennent des secrets : ils sont **gitignorés**, en `chmod 600`,
> propriété `app`. Ne jamais les committer.

---

## Étape 5 — Pare-feu Oracle (Security List)
Ouvrir en **Ingress** les ports **80** et **443** (TCP, source `0.0.0.0/0`).
**Ne pas** exposer le port 8000 (l'app n'écoute qu'en local, derrière nginx).

Côté VM, le pare-feu Ubuntu (si actif) :
```bash
sudo ufw allow 80,443/tcp
```

---

## Étape 6 — Accès
- Avec domaine + TLS : **https://mondomaine.fr**
- Sans domaine : `http://<ip-oracle>` (HTTP seul — éviter pour la connexion)

Connexion : compte `admin` (mot de passe affiché par le script) ou comptes créés à l'étape 4.

---

## Exploitation

### État / logs
```bash
sudo systemctl status champimap.service scheduler.service
sudo journalctl -u champimap.service -f      # web
sudo journalctl -u scheduler.service -f      # collecte
sudo nginx -t                                # valider la conf nginx
```

### Redémarrer
```bash
sudo systemctl restart champimap.service     # après modif code/UI/config.yaml
sudo systemctl restart scheduler.service     # après modif .env / pipeline
```

### Mettre à jour le code
```bash
cd /home/app/champi_pipeline_package
sudo -u app git pull origin main
sudo -u app ./venv/bin/pip install -r requirements.txt   # si deps changées
sudo systemctl restart champimap.service scheduler.service
```

---

## Sécurité (résumé)
- **HTTPS obligatoire** en public (certbot) : la connexion transmet identifiants/cookies.
- **Clé de session forte** : générée dans `config.yaml` (ou via `SESSION_SECRET`). En prod,
  `champimap.service` lance avec `PROD=1` → cookie `Secure`, `/docs` masqué.
- **Mots de passe forts** pour tous les comptes (`scripts/make_users.py`, bcrypt).
- L'app n'écoute qu'en **127.0.0.1:8000** ; seul nginx est exposé.
- Renouvellement TLS auto via le timer certbot (`systemctl list-timers | grep certbot`).

---

## Dépannage
```bash
# Service web qui ne démarre pas ?
sudo journalctl -u champimap.service -n 50
./venv/bin/python -c "import fastapi, champi_core; print('imports OK')"

# uvicorn écoute-t-il en local ?
sudo ss -tlnp | grep 8000

# 502 Bad Gateway via nginx ? → champimap.service est down (voir logs)
sudo nginx -t && sudo systemctl reload nginx

# Collecte ne produit rien ? → clés API manquantes/expirées
cd /home/app/champi_pipeline_package && ./venv/bin/python collect_day.py
sudo journalctl -u scheduler.service -f
```

---

## Garder la VM active
Oracle suspend les VM Free Tier inactives 7+ jours. Le `scheduler.service` (collecte toutes les
5 min) maintient la VM active en continu. ✓

## Coûts : 0 € (VM 1 ARM/1 Go, 20 Go disque, 1 To/mois sortant, TLS Let's Encrypt — tous gratuits).
