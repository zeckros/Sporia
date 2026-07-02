# Sporia

Prévision de cueillette de champignons en France. Web-app FastAPI + Leaflet
adossée à un pipeline météo (Météo-France AROME + radar) et à un modèle
d'habitat / fructification par espèce.

En production : <https://sporia.duckdns.org>

## Développement

```bash
python -m venv venv
# Linux/macOS : source venv/bin/activate
# Windows     : venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install
pytest -q
uvicorn sporia.web.app:app --reload --port 8000
```


## Architecture

- `src/sporia/` — package applicatif (config, domain, geo, overlays, points,
  places, enrich, users, pipeline, web).
- `scripts/` — entraînement de modèles (`train_*.py`) et pré-calculs (`bake_*.py`).
- `web/` — frontend statique (`index.html`, `app.js`) + overlays générés.
- `data/`, `output/` — caches et artefacts (gitignorés, régénérés par le pipeline).
- `tests/` — pytest (caractérisation des chemins critiques).

## Déploiement

Oracle Cloud + nginx (TLS) + systemd. Voir `ORACLE_DEPLOY.md`.

> **Sécurité** : la clé SSH de déploiement ne doit **pas** vivre dans le dépôt.
> La conserver hors de l'arborescence (p. ex. `~/.ssh/sporia/`).

## Licence

Propriétaire — tous droits réservés. Voir `LICENSE`.
