# Pipeline Scheduler Setup

Automates `collect_day.py` (every 5 min) and `interpret_day.py` (every hour).

## Quick Start

### Option 1: PowerShell (Recommended for Windows)
```powershell
.\run_scheduler.ps1
```

### Option 2: Command Prompt (Batch)
```cmd
run_scheduler.bat
```

### Option 3: Manual (Any Terminal)
```powershell
.\venv\Scripts\Activate.ps1
pip install schedule  # if not already installed
python scheduler.py
```

## What It Does

- **`collect_day.py`** — Runs every **5 minutes**
  - Collects HDF5 radar, JSON stations, GRIB2 AROME data
  - Updates `data/state_fetch.json` with latest fetch timestamps

- **`interpret_day.py`** — Runs every **hour at :00**
  - Generates GeoTIFF outputs (RR_*.tif, T_*.tif)
  - For today's date (YYYY-MM-DD)
  - Streamlit app reloads the latest files automatically

## Logs

All activity is logged to console with timestamps:
```
2025-12-03 22:15:30,123 - INFO - Starting collect_day.py...
2025-12-03 22:15:45,456 - INFO - ✓ collect_day.py completed successfully
2025-12-03 23:00:00,789 - INFO - Starting interpret_day.py...
2025-12-03 23:05:12,345 - INFO - ✓ interpret_day.py completed successfully for 2025-12-03
```

## Stopping

Press `Ctrl+C` in the scheduler terminal to stop gracefully.

## Optional: Run as Windows Service (Advanced)

To run the scheduler continuously in the background:

1. Install **NSSM** (Non-Sucking Service Manager):
   ```cmd
   choco install nssm
   ```

2. Create a service:
   ```cmd
   nssm install champi_scheduler "C:\path\to\venv\Scripts\python.exe" "C:\path\to\scheduler.py"
   nssm start champi_scheduler
   ```

3. Check logs:
   ```cmd
   nssm edit champi_scheduler  # GUI to configure logging
   ```

## Optional: Run in Background (PowerShell)

Start scheduler in background PowerShell job:
```powershell
$job = Start-Job -ScriptBlock { & .\run_scheduler.ps1 }
# To stop: Stop-Job $job
# To view output: Receive-Job $job
```

## Troubleshooting

- **"schedule" not found**: Run `pip install schedule` in the venv.
- **collect_day.py fails**: Check `data/state_fetch.json` and network connectivity.
- **interpret_day.py fails**: Ensure GeoTIFF output dir exists (`output/tiff/`).
- **Timeout**: Adjust timeouts in `scheduler.py` if operations take longer.

## Files

- `scheduler.py` — Main scheduler logic
- `run_scheduler.bat` — Windows batch launcher
- `run_scheduler.ps1` — PowerShell launcher
- `SCHEDULER_SETUP.md` — This file
