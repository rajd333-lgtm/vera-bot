@echo off
title magicpin AI Challenge - Vera Bot
color 0A

echo.
echo ========================================
echo   magicpin AI Challenge - Vera Bot
echo ========================================
echo.

:: ── SET YOUR GEMINI API KEY HERE ─────────────────────────────────────────────
set GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
:: ─────────────────────────────────────────────────────────────────────────────

if "%GEMINI_API_KEY%"=="YOUR_GEMINI_API_KEY_HERE" (
    echo [FAIL] You forgot to set your Gemini API key!
    echo.
    echo   1. Open this file in Notepad
    echo   2. Replace YOUR_GEMINI_API_KEY_HERE with your real key
    echo   3. Get a free key at: https://aistudio.google.com
    echo.
    pause
    exit /b 1
)

:: Install dependencies if needed
echo [INFO] Checking dependencies...
pip show uvicorn >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing dependencies...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [FAIL] pip install failed. Make sure Python is installed.
        pause
        exit /b 1
    )
)
echo [OK]  Dependencies ready

:: Kill any old process on port 8080
echo [INFO] Clearing port 8080...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8080 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)

:: Start bot server in a new window
echo [INFO] Starting Vera Bot server...
start "Vera Bot Server" cmd /k "title Vera Bot Server && set GEMINI_API_KEY=%GEMINI_API_KEY% && echo Starting bot... && uvicorn main:app --host 0.0.0.0 --port 8080 --log-level info"

:: Wait for bot to be ready (poll healthz)
echo [INFO] Waiting for bot to start...
set /a attempts=0
:WAIT_LOOP
    timeout /t 2 /nobreak >nul
    curl -s --max-time 2 http://localhost:8080/v1/healthz >nul 2>&1
    if %errorlevel%==0 goto BOT_READY
    set /a attempts+=1
    if %attempts% geq 15 (
        echo [FAIL] Bot did not start after 30 seconds.
        echo        Check the "Vera Bot Server" window for errors.
        pause
        exit /b 1
    )
    echo [INFO] Still waiting... attempt %attempts%/15
goto WAIT_LOOP

:BOT_READY
echo [OK]  Bot is running at http://localhost:8080
echo.
curl -s http://localhost:8080/v1/healthz
echo.
echo.

:: Run the judge
echo [INFO] Starting judge simulator...
echo ========================================
echo.
python judge_simulator.py

echo.
echo ========================================
echo   Judge finished!
echo ========================================
echo.
echo The bot server is still running in the other window.
echo Close it manually when done, or press any key to stop it.
pause

:: Kill bot server
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8080 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)
echo [OK]  Bot stopped.
