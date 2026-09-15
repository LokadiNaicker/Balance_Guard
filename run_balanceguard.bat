@echo off
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    start "BalanceGuard Server" cmd /k "py app.py"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python 3 was not found.
        echo Install it from https://www.python.org/downloads/ and try again.
        pause
        exit /b 1
    )
    start "BalanceGuard Server" cmd /k "python app.py"
)

timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8501"

