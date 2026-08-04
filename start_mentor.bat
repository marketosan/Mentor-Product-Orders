@echo off
REM Start Mentor on the shop's Windows machine.
REM
REM Double-click this, or point a service manager at it. Apache forwards to
REM the address it prints. Keep the window open -- closing it stops the app.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   No virtual environment found in .venv
    echo   Create one first:
    echo.
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    echo.
    echo   No .env file found. Copy .env.example to .env and fill it in.
    echo   The app will not start without a SECRET_KEY.
    echo.
    pause
    exit /b 1
)

echo Checking for unapplied migrations...
.venv\Scripts\python.exe manage.py migrate --check >nul 2>&1
if errorlevel 1 (
    echo.
    echo   The database is behind the code. Run:
    echo     .venv\Scripts\python manage.py migrate
    echo.
    pause
    exit /b 1
)

.venv\Scripts\python.exe serve.py
pause
