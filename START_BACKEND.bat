@echo off
title CMining Backend Server
echo.
echo ============================================
echo   CMining Backend Server - Starting...
echo ============================================
echo.

cd /d "c:\Users\USER\Documents\TOOLS\CMINING TOOL\CMining-Monorepo\backend"

REM Activate virtual environment and start Flask
call venv\Scripts\activate.bat
set FLASK_ENV=production
python app.py

pause
