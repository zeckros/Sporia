#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ajoute / met à jour un utilisateur dans config.yaml (mot de passe hashé bcrypt).

Usage :
    python scripts/make_users.py <login> <mot_de_passe> [nom] [email]

Exemple :
    python scripts/make_users.py theo monNouveauMotDePasse "Théo" theo@exemple.fr

Le hash bcrypt produit est compatible avec la vérification de server.py (bcrypt.checkpw).
"""
import sys
from pathlib import Path

import bcrypt
import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    login = sys.argv[1]
    password = sys.argv[2]
    name = sys.argv[3] if len(sys.argv) > 3 else login
    email = sys.argv[4] if len(sys.argv) > 4 else f"{login}@example.com"

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("credentials", {}).setdefault("usernames", {})

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    cfg["credentials"]["usernames"][login] = {"name": name, "email": email, "password": hashed}

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    print(f"[OK] Utilisateur '{login}' enregistre (mot de passe hashe) dans {CONFIG_PATH}")


if __name__ == "__main__":
    main()
