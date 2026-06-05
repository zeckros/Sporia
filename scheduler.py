#!/usr/bin/env python3
"""
Scheduler to automate data collection and interpretation.
- Runs collect_day.py every 5 minutes
- Runs interpret_day.py every hour (at :00)

Install schedule: pip install schedule
Run this script: python scheduler.py
"""

import schedule
import time
import subprocess
import sys
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_collect_day():
    """Run collect_day.py"""
    logger.info("Starting collect_day.py...")
    try:
        result = subprocess.run(
            [sys.executable, "collect_day.py"],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        if result.returncode == 0:
            logger.info("✓ collect_day.py completed successfully")
        else:
            logger.error(f"✗ collect_day.py failed with return code {result.returncode}")
            logger.error(f"STDERR: {result.stderr}")
    except subprocess.TimeoutExpired:
        logger.error("✗ collect_day.py timed out (>5 min)")
    except Exception as e:
        logger.error(f"✗ Error running collect_day.py: {e}")

def run_soil_dynamic():
    """Run soil_dynamic.py (Open-Meteo soil moisture + soil temperature).
    Slow + rate-limited, refreshed ~once/day — kept off collect_day's 5-min path."""
    logger.info("Starting soil_dynamic.py...")
    try:
        from datetime import date
        today = date.today().isoformat()
        result = subprocess.run(
            [sys.executable, "soil_dynamic.py", today],
            capture_output=True,
            text=True,
            timeout=900  # 15 minute timeout (bulk Open-Meteo can be slow/flaky)
        )
        if result.returncode == 0:
            logger.info(f"✓ soil_dynamic.py completed successfully for {today}")
        else:
            logger.error(f"✗ soil_dynamic.py failed with return code {result.returncode}")
            logger.error(f"STDERR: {result.stderr}")
    except subprocess.TimeoutExpired:
        logger.error("✗ soil_dynamic.py timed out (>15 min)")
    except Exception as e:
        logger.error(f"✗ Error running soil_dynamic.py: {e}")


def run_fruiting_prewarm():
    """Pré-chauffe la météo récente + pré-score les modèles « pousse en ce moment »
    (fruiting_live) → l'endpoint /api/fruiting reste rapide (~7 s en cache chaud
    au lieu de ~4 min). Récupère ~21 j de météo Open-Meteo (lent), donc 1×/jour."""
    logger.info("Starting fruiting_live prewarm...")
    try:
        result = subprocess.run(
            [sys.executable, "fruiting_live.py", "prewarm"],
            capture_output=True,
            text=True,
            timeout=900  # 15 min (fetch Open-Meteo grille grossière)
        )
        if result.returncode == 0:
            logger.info("✓ fruiting prewarm completed")
        else:
            logger.error(f"✗ fruiting prewarm failed (code {result.returncode})")
            logger.error(f"STDERR: {result.stderr}")
    except subprocess.TimeoutExpired:
        logger.error("✗ fruiting prewarm timed out (>15 min)")
    except Exception as e:
        logger.error(f"✗ Error running fruiting prewarm: {e}")


def run_cleanup():
    """Purge quotidienne des données brutes/intermédiaires (scripts/prune_data.py) :
    tuiles AROME, radar H5, daily déjà interprétés, vieux rasters, zip WorldClim.
    Rétention relative à la donnée la plus récente → ne vide jamais par erreur."""
    logging.info("Starting data prune...")
    try:
        result = subprocess.run(
            [sys.executable, "scripts/prune_data.py"],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            logging.info("✓ data prune completed\n" + (result.stdout or "").strip())
        else:
            logging.error(f"✗ data prune failed (code {result.returncode})\n{result.stderr}")
    except Exception as e:
        logging.error(f"✗ Error running data prune: {e}")


def run_interpret_day():
    """Run interpret_day.py for today's date"""
    logger.info("Starting interpret_day.py...")
    try:
        from datetime import date
        today = date.today().isoformat()  # YYYY-MM-DD format
        result = subprocess.run(
            [sys.executable, "interpret_day.py", today],
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )
        if result.returncode == 0:
            logger.info(f"✓ interpret_day.py completed successfully for {today}")
        else:
            logger.error(f"✗ interpret_day.py failed with return code {result.returncode}")
            logger.error(f"STDERR: {result.stderr}")
    except subprocess.TimeoutExpired:
        logger.error("✗ interpret_day.py timed out (>10 min)")
    except Exception as e:
        logger.error(f"✗ Error running interpret_day.py: {e}")

def main():
    """Schedule and run jobs"""
    logger.info("=" * 60)
    logger.info("Pipeline Scheduler Started")
    logger.info("=" * 60)
    logger.info("Schedule:")
    logger.info("  - collect_day.py: every 5 minutes")
    logger.info("  - interpret_day.py: every hour at :00")
    logger.info("  - soil_dynamic.py: daily at 05:30 (+ startup if missing)")
    logger.info("  - fruiting prewarm: daily at 06:00 (+ startup if missing)")
    logger.info("  - data prune: daily at 06:30 (raw/intermediate cleanup)")
    logger.info("=" * 60)

    # Schedule jobs
    schedule.every(5).minutes.do(run_collect_day)
    schedule.every().hour.at(":00").do(run_interpret_day)
    schedule.every().day.at("05:30").do(run_soil_dynamic)
    schedule.every().day.at("06:00").do(run_fruiting_prewarm)  # après la météo sol
    schedule.every().day.at("06:30").do(run_cleanup)           # purge données brutes

    # Catch-up au démarrage : bake des couches STATIQUES (sol SoilGrids + relief
    # altitude/exposition) si absentes — one-time, ensuite hors-ligne.
    from datetime import date
    from pathlib import Path
    if not (Path("data/cache") / "soil_ph.npy").exists():
        logger.info("Static soil layers missing — baking SoilGrids (one-time)...")
        try:
            import soil_data
            soil_data.build_soil_static()
        except Exception as e:
            logger.warning(f"Soil static bake failed: {e}")
    if not (Path("data/cache") / "altitude.npy").exists():
        logger.info("Terrain layers missing — baking altitude/aspect (one-time)...")
        try:
            import terrain_data
            terrain_data.build_terrain_static()
        except Exception as e:
            logger.warning(f"Terrain bake failed: {e}")

    # Catch-up: refresh soil moisture/temperature rasters if today's are missing/stale.
    sm_today = Path("output/tiff") / f"SM_{date.today().strftime('%Y%m%d')}.tif"
    if not sm_today.exists():
        logger.info("Soil rasters missing for today — running initial soil fetch...")
        run_soil_dynamic()

    # Catch-up: pré-chauffe « pousse en ce moment » si un modèle existe et que la
    # météo récente du jour n'est pas en cache (sinon /api/fruiting serait lent).
    wx_today = Path("data/cache") / f"wx_recent_{date.today().strftime('%Y%m%d')}.npz"
    if list(Path("data/cache").glob("fruiting_*.pkl")) and not wx_today.exists():
        logger.info("Fruiting weather cache missing for today — prewarming...")
        run_fruiting_prewarm()

    # Run the scheduler loop
    try:
        while True:
            schedule.run_pending()
            time.sleep(10)  # Check every 10 seconds
    except KeyboardInterrupt:
        logger.info("\nScheduler stopped by user")
        sys.exit(0)

if __name__ == "__main__":
    main()
