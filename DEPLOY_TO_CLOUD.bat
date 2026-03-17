@echo off
setlocal
title CMining - ONE CLICK PYTHONANYWHERE DEPLOYER

echo.
echo ============================================================
echo      CMINING - PYTHONANYWHERE AUTOMATIC DEPLOYER
echo ============================================================
echo.
echo This script will help you prepare the files for PythonAnywhere.
echo.

set PROJECT_ROOT=%~dp0
set BACKEND_DIR=%PROJECT_ROOT%backend

if not exist "%BACKEND_DIR%\app.py" (
    echo [ERROR] Could not find backend/app.py. Run this from the monorepo root.
    pause
    exit /b
)

echo [1/3] Creating backend_deploy.zip...
if exist "%PROJECT_ROOT%backend_deploy.zip" del "%PROJECT_ROOT%backend_deploy.zip"
powershell -Command "Compress-Archive -Path '%BACKEND_DIR%\app.py', '%BACKEND_DIR%\requirements.txt', '%BACKEND_DIR%\wsgi.py', '%BACKEND_DIR%\DEPLOY_TO_PYTHONANYWHERE.md' -DestinationPath '%PROJECT_ROOT%backend_deploy.zip'"

echo.
echo [2/3] SUCCESS! backend_deploy.zip is ready.
echo.
echo [3/3] FINAL STEPS:
echo 1. Log in to PythonAnywhere.
echo 2. Go to 'Files' tab.
echo 3. Upload 'backend_deploy.zip' to /home/SucceedHQ/CMining-Monorepo/
echo 4. In a Bash Console, run: 
echo    unzip -o ~/CMining-Monorepo/backend_deploy.zip -d ~/CMining-Monorepo/backend/
echo 5. Go to 'Web' tab and click 'Reload succeedhq.pythonanywhere.com'
echo.
echo Once reloaded, visit https://succeedhq.pythonanywhere.com/
echo It should say 'CMining Backend is running correctly'.
echo.
pause
