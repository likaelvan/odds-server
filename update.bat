@echo off
rem Refresh player data. First run downloads the archive; later runs only fetch new results from Wikipedia.
rem To force a fresh archive download: update.bat --redownload
cd /d "%~dp0"
set ARGS=--skip-archive
if /i "%~1"=="--redownload" set ARGS=
if exist .venv\Scripts\python.exe (.venv\Scripts\python update_stats.py %ARGS%) else (py update_stats.py %ARGS%)
pause
