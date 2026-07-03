#!/usr/bin/env python3
"""Migre les comptes config.yaml → SQLite (si users vide) + remappe user_prefs/user_spots
(clé username → email). Idempotent : relançable sans dupliquer.

Pointer une base précise via la variable d'env SPORIA_DB (sinon data/sporia.db)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import yaml  # noqa: E402

from sporia.config import settings  # noqa: E402
from sporia.users import accounts  # noqa: E402


def _remap(json_path: Path, mapping: dict[str, str]) -> None:
    if not json_path.exists():
        return
    data = json.loads(json_path.read_text(encoding="utf-8"))
    changed = False
    for old, new in mapping.items():
        if old in data and new not in data:
            data[new] = data.pop(old)
            changed = True
    if changed:
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  remap {json_path.name}: {mapping}")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    accounts.init_db()
    with accounts._connect() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    if n > 0:
        print(f"users déjà peuplé ({n}) — migration ignorée.")
        return
    cfg = yaml.safe_load((settings.base_dir / "config.yaml").read_text(encoding="utf-8")) or {}
    users = cfg.get("credentials", {}).get("usernames", {})
    mapping: dict[str, str] = {}
    for username, v in users.items():
        email = (v.get("email") or f"{username}@sporia.local").strip().lower()
        now = int(time.time())
        with accounts._connect() as c:
            c.execute(
                "INSERT INTO users(email,password_hash,name,role,email_verified,created_at,updated_at)"
                " VALUES(?,?,?,?,1,?,?)",
                (email, v["password"], v.get("name", username), v.get("role", "user"), now, now),
            )
        mapping[username] = email
        print(f"  + {username} → {email} ({v.get('role', 'user')})")
    _remap(settings.data_dir / "user_prefs.json", mapping)
    _remap(settings.data_dir / "user_spots.json", mapping)
    print("Migration terminée.")


if __name__ == "__main__":
    main()
