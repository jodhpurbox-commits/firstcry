@echo off
REM Double-click this file to launch the FirstCry Telegram Mini App.
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0launch_mini_app.ps1"
