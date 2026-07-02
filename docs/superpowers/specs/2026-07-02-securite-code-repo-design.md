# Sporia — Chantier 2/5 : Sécurité (code & repo) — Design

## Contexte

Le chantier 1 (Fondations) a livré un backend packagé et **déjà plutôt bien sécurisé** :
bcrypt + hash leurre anti-timing, CSP + en-têtes de sécurité, cookie de session `https_only`
en PROD, validation anti path-traversal, honeypot sur `/api/access-request`, `/docs` masqué
en PROD, rôle admin sur `/api/access-requests`, secrets gitignorés et **jamais** dans
l'historique git. La revue a aussi confirmé que **nginx gère déjà le rate-limiting** de façon
robuste ([deploy/nginx-champimap.conf](../../../deploy/nginx-champimap.conf) : `/api/login`
à 10 req/min, `/api/` à 20 req/s, 20 conns/IP, HSTS) — donc **pas de rate-limiting applicatif
à ajouter** (redondant).

Ce chantier durcit la couche **code & repo** uniquement. **Hors périmètre** (décidé avec
l'utilisateur) : durcissement infra/OS de la VM Oracle, et volet légal/RGPD (rattaché au
chantier #4 Monétisation). **Contrainte forte** : ne pas re-provoquer un 502 au déploiement.

## Décisions

- **Secret de session : env-only strict.** `SESSION_SECRET` vient **uniquement** de
  l'environnement ; `cookie.key` (et toute la section `cookie:` vestigiale) est **retirée de
  config.yaml**. En PROD sans secret fort → **refus de démarrer** avec message clair. En DEV →
  clé éphémère tolérée.
- **Audit de dépendances en environnement propre** (pas le venv de dev pollué).

## Périmètre & unités de travail

### 1. Secret de session (env-only, fail-closed en PROD)

- `sporia/config.py` : `settings.session_secret` reste la lecture de `SESSION_SECRET` (env).
  Ajouter un helper `resolve_session_secret(prod: bool) -> str` qui :
  - si un secret fort est présent (≥ 32 caractères, ne contient pas « change ») → le renvoie ;
  - sinon si `prod` → lève `RuntimeError` avec un message explicite (« Définissez
    SESSION_SECRET (≥32 octets) — refus de démarrer en PROD sans secret fort ») ;
  - sinon (DEV) → génère une clé éphémère (`secrets.token_urlsafe(48)`) + warning.
- `sporia/web/app.py` : remplacer le bloc actuel (lecture `_cfg.get("cookie",{}).get("key")` +
  génération silencieuse) par `resolve_session_secret(settings.prod)`. Supprimer la dépendance
  au `cookie.key` de config.yaml.
- `config.yaml` (gitignoré) : retirer la section `cookie:` entière (vestigiale — seule
  `cookie.key` était lue). Documenter dans un `config.example.yaml` versionné (sans secrets).
- **Déploiement (anti-502)** :
  - `systemd/champimap.service` : ajouter `EnvironmentFile=-/home/app/champi_pipeline_package/.env`
    (préfixe `-` = optionnel) → le service lit `SESSION_SECRET` depuis `.env`.
  - `oracle_deploy.sh` : à l'étape secrets, **générer un `SESSION_SECRET` fort dans `.env`**
    s'il est absent (comme la clé de session l'était pour config.yaml), et l'ajouter au gabarit
    `.env`.
  - `ORACLE_DEPLOY.md` : documenter que `SESSION_SECRET` doit exister dans `.env` (sinon refus
    de boot en PROD — comportement voulu, message clair dans les logs).

### 2. Clé SSH hors du repo

- Confirmer (déjà vérifié chantier 1) : non trackée, absente de l'historique.
- Instruire le déplacement hors de l'arborescence (`~/.ssh/sporia/`) — action locale utilisateur.
- `.gitignore` contient déjà `ssh-key-2026-06-05.key` ; ajouter un motif large `*.key` +
  `*.pem` par sécurité.

### 3. Dépendances

- **Vraies vulns applicatives à corriger** (confirmées par pip-audit) : `starlette` ≥ 1.3.1
  (2 CVE via FastAPI), `fonttools` ≥ 4.60.2 (via matplotlib). Ajouter des bornes basses dans
  `pyproject.toml`.
- **Régénérer `requirements.lock` depuis un environnement PROPRE** : le lock actuel est pollué
  (streamlit + tornado/pyarrow/gitpython, ~8 entrées, restes de l'ancienne UI Streamlit). Créer
  un venv jetable, `pip install -e .`, `pip freeze --exclude-editable` → lock sans cruft.
- **CI** : ajouter un job `pip-audit` dans [.github/workflows/ci.yml](../../../.github/workflows/ci.yml)
  qui installe `-e .` dans un env frais et échoue sur les vulns corrigeables. Une liste
  d'`--ignore-vuln` documentée (avec justification) est autorisée pour les cas sans fix.

### 4. En-têtes & cookies (hygiène légère)

- Confirmer par test les flags du cookie de session : `HttpOnly` (défaut Starlette), `SameSite=lax`,
  `Secure` en PROD (`https_only=PROD`). Pas de changement de comportement — juste un test de
  non-régression qui les vérifie.
- Ajouter un en-tête `Permissions-Policy` minimal (désactiver géoloc/caméra/micro non utilisés)
  dans `sporia/web/security.py`.
- **`unsafe-inline` du CSP : NON traité ici.** Le retirer impose de sortir les scripts/styles
  inline du frontend → **décalé au chantier #4 (UX/UI)**. Noté dans le spec, pas dans le code.

### 5. Tests

- `tests/test_secret.py` : `resolve_session_secret` — secret fort renvoyé tel quel ; PROD sans
  secret → `RuntimeError` ; DEV sans secret → clé éphémère non vide (≥ 32).
- `tests/test_security_headers.py` : présence de `Content-Security-Policy`, `X-Content-Type-Options`,
  `Permissions-Policy` ; et flags du cookie de session après login simulé (HttpOnly, SameSite).
- Non-régression auth (déjà couverte par `test_auth.py` / `test_admin.py`).

## Fichiers concernés

- Modifiés : `src/sporia/config.py`, `src/sporia/web/app.py`, `src/sporia/web/security.py`,
  `pyproject.toml`, `requirements.lock` (régénéré), `.github/workflows/ci.yml`, `.gitignore`,
  `systemd/champimap.service`, `oracle_deploy.sh`, `ORACLE_DEPLOY.md`, `config.yaml` (local, gitignoré).
- Créés : `config.example.yaml`, `tests/test_secret.py`, `tests/test_security_headers.py`.

## Vérification

1. `pytest` + `ruff` verts ; nouveaux tests secret/headers passent.
2. **Fail-closed** : `PROD=1` sans `SESSION_SECRET` → l'app refuse de démarrer avec le message
   attendu ; avec `SESSION_SECRET` fort → démarre normalement.
3. **DEV** : sans `PROD`, sans secret → démarre avec clé éphémère + warning.
4. `pip-audit` sur un env frais (`pip install -e .`) : plus de vuln corrigeable non traitée
   (starlette/fonttools à jour) ; le job CI passe.
5. `requirements.lock` régénéré ne contient plus streamlit/tornado/pyarrow/gitpython.
6. Déploiement : `EnvironmentFile` + `SESSION_SECRET` dans `.env` → pas de 502 ; l'app boote.

## Hors périmètre

Infra/OS VM Oracle (SSH key-only, ufw, fail2ban, unattended-upgrades) · légal/RGPD (CGU,
politique de confidentialité, purge des emails access-requests) · refonte CSP `unsafe-inline`
(frontend, chantier #4) · rate-limiting applicatif (déjà couvert par nginx).
