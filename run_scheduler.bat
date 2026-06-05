@echo off
REM Launcher for the pipeline scheduler (Windows)
REM This script activates the venv and runs the scheduler

setlocal enabledelayedexpansion

cd /d "%~dp0"

REM Activate virtualenv
call .\venv\Scripts\activate.bat

REM Check if schedule is installed
python -c "import schedule" >nul 2>&1
if errorlevel 1 (
    echo Installing schedule...
    pip install schedule
)

REM Start scheduler
echo.
echo Starting Pipeline Scheduler...
echo.
python scheduler.py

pause
