@echo off
rem One-time setup: creates a virtual environment (.venv) and installs requirements.
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul
where py >nul 2>nul && (set PY=py) || (set PY=python)
if not exist .venv (
  echo Creating virtual environment...
  %PY% -m venv .venv || goto :fail
)
.venv\Scripts\python -m pip install --upgrade pip >nul
.venv\Scripts\python -m pip install -r requirements.txt || goto :fail
echo.
echo Setup done. Next: double-click update.bat to download player data, then start.bat.
pause
goto :eof
:fail
echo Setup failed. Is Python installed? https://www.python.org/downloads/
pause
