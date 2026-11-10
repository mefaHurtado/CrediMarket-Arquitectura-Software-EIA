@echo off
cd /d "%~dp0"
docker compose logs --tail=120
pause
