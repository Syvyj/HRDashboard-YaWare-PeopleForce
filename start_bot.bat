@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM ========================================
REM Eva_Control_Bot - Startup Script Windows
REM ========================================

echo.
echo ========================================
echo Eva_Control_Bot - Starting...
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found!
    echo Please install Python 3.8+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python found
python --version

REM Check if .env file exists
if not exist ".env" (
    echo.
    echo [ERROR] .env file not found!
    echo Please create .env file with required variables:
    echo   - YAWARE_API_TOKEN
    echo   - PEOPLEFORCE_API_TOKEN
    echo   - TELEGRAM_BOT_TOKEN
    echo   - TELEGRAM_ADMIN_CHAT_IDS
    echo   - GOOGLE_SHEET_URL
    echo.
    pause
    exit /b 1
)

echo [OK] .env file found

REM Check if gcp-sa.json exists
if not exist "gcp-sa.json" (
    echo.
    echo [ERROR] gcp-sa.json file not found!
    echo This is the service account for Google Sheets access
    echo.
    pause
    exit /b 1
)

echo [OK] gcp-sa.json file found

REM Check if work_schedules.json exists
if not exist "config\work_schedules.json" (
    echo.
    echo [ERROR] config\work_schedules.json not found!
    echo.
    pause
    exit /b 1
)

REM Check if user_schedules.json exists
if not exist "config\user_schedules.json" (
    echo.
    echo [ERROR] config\user_schedules.json not found!
    echo.
    pause
    exit /b 1
)

echo [OK] Config files found

REM Install/update dependencies
echo.
echo Checking dependencies...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [WARNING] Error installing dependencies
    echo Try running manually: pip install -r requirements.txt
    pause
)

echo [OK] Dependencies installed

REM Start the bot
echo.
echo ========================================
echo Starting bot...
echo ========================================
echo.
echo To stop the bot press Ctrl+C
echo.

python scripts\run_attendance_bot.py

REM Handle errors
if %errorlevel% neq 0 (
    echo.
    echo ========================================
    echo [ERROR] Bot exited with error!
    echo ========================================
    echo.
    pause
    exit /b 1
)
