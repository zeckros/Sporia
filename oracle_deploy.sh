#!/bin/bash
# =============================================================================
# ChampiMap — Déploiement Oracle Cloud Free Tier (Ubuntu/ARM)
# Stack : FastAPI/uvicorn (web) + scheduler (collecte) derrière nginx + TLS.
# =============================================================================
# Usage :
#   sudo REPO_URL=https://github.com/<vous>/champi_pipeline_package.git \
#        DOMAIN=mondomaine.fr EMAIL=moi@exemple.fr \
#        bash oracle_deploy.sh
#   (DOMAIN/EMAIL optionnels : sans eux, pas de TLS automatique — accès HTTP only.)
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

APP_USER="app"
APP_HOME="/home/$APP_USER"
APP_DIR="$APP_HOME/champi_pipeline_package"
REPO_URL="${REPO_URL:-https://github.com/your-username/champi_pipeline_package.git}"
DOMAIN="${DOMAIN:-}"
EMAIL="${EMAIL:-}"
PY="$APP_DIR/venv/bin/python"
PIP="$APP_DIR/venv/bin/pip"

echo "=========================================="
echo "  ChampiMap — Oracle Cloud Deploy (FastAPI)"
echo "=========================================="

# --- 1. Paquets système (dont libs géo pour rasterio/geopandas + nginx/certbot) ---
echo -e "${YELLOW}[1/9] Paquets système...${NC}"
sudo apt-get update
sudo apt-get install -y \
    git curl wget build-essential \
    python3-dev python3-venv python3-pip \
    gdal-bin libgdal-dev libgeos-dev libproj-dev \
    nginx certbot python3-certbot-nginx

# --- 2. Utilisateur applicatif ---
echo -e "${YELLOW}[2/9] Utilisateur '$APP_USER'...${NC}"
id "$APP_USER" &>/dev/null || sudo useradd -m -s /bin/bash "$APP_USER"

# --- 3. Code source ---
echo -e "${YELLOW}[3/9] Récupération du code...${NC}"
if [ ! -d "$APP_DIR/.git" ]; then
    sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
else
    sudo -u "$APP_USER" git -C "$APP_DIR" pull origin main || true
fi

# --- 4. Environnement Python ---
echo -e "${YELLOW}[4/9] Environnement virtuel + dépendances...${NC}"
[ -d "$APP_DIR/venv" ] || sudo -u "$APP_USER" python3 -m venv "$APP_DIR/venv"
sudo -u "$APP_USER" "$PIP" install --upgrade pip setuptools wheel
sudo -u "$APP_USER" "$PIP" install -r "$APP_DIR/requirements.txt"
sudo -u "$APP_USER" "$PIP" install schedule   # boucle du scheduler

# --- 5. Secrets : config.yaml (auth + clé de session) ---
echo -e "${YELLOW}[5/9] Provisioning config.yaml...${NC}"
if [ ! -f "$APP_DIR/config.yaml" ]; then
    KEY=$(sudo -u "$APP_USER" "$PY" -c "import secrets;print(secrets.token_urlsafe(48))")
    ADMIN_PASS="${ADMIN_PASSWORD:-$(sudo -u "$APP_USER" "$PY" -c "import secrets;print(secrets.token_urlsafe(12))")}"
    HASH=$(sudo -u "$APP_USER" "$PY" -c "import bcrypt,sys;print(bcrypt.hashpw(sys.argv[1].encode(),bcrypt.gensalt()).decode())" "$ADMIN_PASS")
    sudo -u "$APP_USER" tee "$APP_DIR/config.yaml" >/dev/null <<EOF
cookie:
  name: champimap_auth
  key: $KEY
  expiry_days: 30
credentials:
  usernames:
    admin:
      name: Admin
      email: admin@example.com
      password: $HASH
EOF
    sudo chmod 600 "$APP_DIR/config.yaml"
    echo -e "${GREEN}✓ config.yaml créé. Compte admin → identifiant: admin  mot de passe: ${ADMIN_PASS}${NC}"
    echo -e "${YELLOW}  (Notez ce mot de passe maintenant ! Ajoutez d'autres comptes via scripts/make_users.py)${NC}"
else
    echo -e "${GREEN}✓ config.yaml déjà présent (laissé tel quel)${NC}"
fi

# --- 6. Secrets : .env (clés API Météo-France, requis pour la COLLECTE) ---
echo -e "${YELLOW}[6/9] Vérification .env (clés API Météo-France)...${NC}"
if [ ! -f "$APP_DIR/.env" ]; then
    sudo -u "$APP_USER" tee "$APP_DIR/.env" >/dev/null <<'EOF'
# Clés API Météo-France (https://portail-api.meteofrance.fr) — À REMPLIR.
API_KEY_AROME=""
API_KEY_STATIONS=""
API_KEY_RADAR=""
EOF
    sudo chmod 600 "$APP_DIR/.env"
    echo -e "${RED}⚠ .env créé VIDE — la collecte de données ne fonctionnera pas tant que les clés"
    echo -e "  Météo-France ne sont pas renseignées dans $APP_DIR/.env (le site web, lui, démarre).${NC}"
else
    echo -e "${GREEN}✓ .env déjà présent${NC}"
fi

# --- 7. Dossiers de sortie + services systemd ---
echo -e "${YELLOW}[7/9] Dossiers + services systemd...${NC}"
sudo -u "$APP_USER" mkdir -p "$APP_DIR/output/tiff" "$APP_DIR/data/cache" "$APP_DIR/web/overlays"
sudo cp "$APP_DIR/systemd/champimap.service" /etc/systemd/system/
sudo cp "$APP_DIR/systemd/scheduler.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now scheduler.service
sudo systemctl enable --now champimap.service

# --- 8. nginx (reverse proxy) ---
echo -e "${YELLOW}[8/9] Configuration nginx...${NC}"
sudo cp "$APP_DIR/deploy/nginx-champimap.conf" /etc/nginx/sites-available/champimap
if [ -n "$DOMAIN" ]; then
    sudo sed -i "s/server_name _;/server_name $DOMAIN;/" /etc/nginx/sites-available/champimap
fi
sudo ln -sf /etc/nginx/sites-available/champimap /etc/nginx/sites-enabled/champimap
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# --- 9. TLS (Let's Encrypt) ---
echo -e "${YELLOW}[9/9] HTTPS (certbot)...${NC}"
if [ -n "$DOMAIN" ] && [ -n "$EMAIL" ]; then
    sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect
    echo -e "${GREEN}✓ TLS activé pour https://$DOMAIN${NC}"
else
    echo -e "${YELLOW}⚠ DOMAIN/EMAIL non fournis → pas de TLS. Accès HTTP uniquement (NON sécurisé"
    echo -e "  pour la connexion). Relancez certbot manuellement une fois le domaine prêt.${NC}"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}Déploiement terminé.${NC}"
echo "=========================================="
echo "  Web   : ${DOMAIN:+https://$DOMAIN}  (sinon http://<ip-oracle>)"
echo "  État  : sudo systemctl status champimap.service scheduler.service"
echo "  Logs  : sudo journalctl -u champimap.service -f"
echo "  Pare-feu Oracle : ouvrir 80/443 (Ingress). Ne PAS exposer 8000."
echo ""
