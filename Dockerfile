# Image de l'app web ChampiMap (FastAPI/uvicorn).
# Le pipeline de collecte (scheduler.py) tourne plutôt en service systemd (voir oracle_deploy.sh).
FROM python:3.11-slim

# Libs système pour rasterio / geopandas (GDAL, GEOS, PROJ)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev libproj-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
ENV PROD=1
# config.yaml et .env (secrets) doivent être montés en volume au run, ils ne sont pas dans l'image.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
