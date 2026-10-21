@echo off
rem Double-click to start odds-server.
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul
if exist .venv\Scripts\python.exe (.venv\Scripts\python server.py & goto :eof)
where py >nul 2>nul && (py server.py & goto :eof)
where python >nul 2>nul && (python server.py & goto :eof)
echo Python was not found. Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH").
pause
