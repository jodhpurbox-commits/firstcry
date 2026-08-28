@echo off
title Push Meesho Bot to GitHub / Render
echo ========================================================
echo  Meesho Number + OTP Bot - Cloud Deployment Helper
echo ========================================================
echo.
set /p REPO_URL="Enter your GitHub Repository URL (e.g. https://github.com/username/meesho-bot.git): "
if "%REPO_URL%"=="" (
    echo No URL provided. Exiting.
    pause
    exit /b
)

"%LOCALAPPDATA%\MinGit\cmd\git.exe" remote remove origin 2>nul
"%LOCALAPPDATA%\MinGit\cmd\git.exe" remote add origin %REPO_URL%
"%LOCALAPPDATA%\MinGit\cmd\git.exe" branch -M main
"%LOCALAPPDATA%\MinGit\cmd\git.exe" push -u origin main

echo.
echo ========================================================
echo  Code pushed to GitHub successfully!
echo.
echo  Next step:
echo  1. Go to https://dashboard.render.com
echo  2. Click 'New +' -> 'Web Service'
echo  3. Select your GitHub repository
echo  4. Render will auto-detect render.yaml and deploy 24/7!
echo ========================================================
pause
