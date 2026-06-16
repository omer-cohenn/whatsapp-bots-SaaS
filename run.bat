@echo off
REM ============================================================
REM  Bizz_up - run the local dev stack (M0 + M1)
REM  Double-click this file, or run it from the project folder.
REM  Windows-friendly equivalent of `make dev` (no Git Bash needed).
REM  Clean by design: deps are installed inside Docker (NOT per-run like the
REM  old run.bat / B2), and it uses its own folder so it is portable (B14).
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo === Bizz_up dev stack (M0 + M1) ===
echo.

REM --- 1) Docker must be running ---
docker info >nul 2>&1
if errorlevel 1 goto :no_docker

REM --- 2) Make sure the local secrets file exists ---
if not exist "infra\.env.local" goto :gen_env
goto :start

:gen_env
echo [!] infra\.env.local not found - generating fresh secrets...
where python >nul 2>&1
if errorlevel 1 goto :no_python
python -c "import secrets,pathlib;t=lambda:secrets.token_urlsafe(32);pathlib.Path('infra/.env.local').write_text('GATEWAY_API_TOKEN='+t()+'\nBACKEND_WEBHOOK_URL=http://backend:8000/webhook/whatsapp\nPOSTGRES_USER=bizzup\nPOSTGRES_PASSWORD='+t()+'\nPOSTGRES_DB=bizzup\nREDIS_PASSWORD='+t()+'\n',encoding='utf-8')"
echo     created infra\.env.local
goto :start

:start
echo.
echo Starting the stack (first run builds images - this can take a few minutes)...
echo.
echo   When it is healthy, open in your browser:
echo     Frontend (health):  http://localhost:5173
echo     WhatsApp QR (M1):   http://localhost:3000/qr
echo.
echo   Watch THIS window for the line:  "whatsapp message received"  (the M1 proof)
echo   Stop with Ctrl+C, or run stop.bat
echo.
docker compose --env-file infra\.env.local -f infra\docker-compose.yml up --build
echo.
echo (stack stopped)
goto :end

:no_docker
echo [X] Docker is not running.
echo     Open Docker Desktop, wait until it says "running", then run this again.
goto :end

:no_python
echo [X] infra\.env.local is missing and Python was not found to generate it.
echo     Copy infra\.env.local.example to infra\.env.local, fill the values, then re-run.
goto :end

:end
echo.
pause
endlocal
