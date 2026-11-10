@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0iniciar_windows.ps1"
if errorlevel 1 echo No se pudo iniciar. Revisa Docker Desktop y VER_LOGS_WINDOWS.bat
pause
