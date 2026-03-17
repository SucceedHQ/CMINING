@echo off
setlocal
title CMining Control Center

:menu
cls
echo ============================================================
echo           CMINING MONOREPO - CONTROL CENTER
echo ============================================================
echo.
echo [1] START BACKEND (Local Flask Server)
echo [2] START ADMIN DASHBOARD (Local Web UI)
echo [3] START WORKER APP (Desktop Miner)
echo [4] OPEN DEPLOYMENT GUIDE (PythonAnywhere)
echo [5] EXIT
echo.
echo ============================================================
set /p choice="Enter your choice [1-5]: "

if "%choice%"=="1" goto start_backend
if "%choice%"=="2" goto start_admin
if "%choice%"=="3" goto start_worker
if "%choice%"=="4" goto open_guide
if "%choice%"=="5" goto exit
echo Invalid choice, try again.
pause
goto menu

:start_backend
start cmd /k "START_BACKEND.bat"
goto menu

:start_admin
echo Starting Admin Dashboard (Vite)...
cd /d "admin-dashboard"
start cmd /k "npm run dev"
timeout /t 3
start http://localhost:5173
cd ..
goto menu

:start_worker
start cmd /k "START_WORKER_APP.bat"
goto menu

:open_guide
start notepad "backend\DEPLOY_TO_PYTHONANYWHERE.md"
goto menu

:exit
exit
