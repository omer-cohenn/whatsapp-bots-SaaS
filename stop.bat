@echo off
REM Stop the Bizz_up local dev stack (keeps the Postgres volume).
setlocal
cd /d "%~dp0"
echo Stopping the Bizz_up stack...
docker compose --env-file infra\.env.local -f infra\docker-compose.yml down
echo (stopped)
echo.
pause
endlocal
