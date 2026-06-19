@echo off
REM ==========================================================================
REM  test_m7b.bat  -  Double-click to test the M7 POLISH ("work a lead to a sale").
REM  M7 gave the owner the dashboard WINDOWS. This polish adds the BUTTONS:
REM    - PATCH /api/leads/{id}/status  (owner stamps a lead 'deal' / 'closed';
REM                                     GET /api/leads reflects it; 422 on junk,
REM                                     404 on unknown id, 401 with no login,
REM                                     and A can NEVER stamp B's lead)
REM    - GET  /api/dashboard 'orders'  (= count of status='deal' leads; bumps when
REM                                     you mark a deal; is_test + period respected)
REM  Then it RE-RUNS M2 wall, M3 login, M4 builder, M5 (try-me + sim), and the full
REM  M7 dashboard suite to prove nothing regressed.
REM
REM  No AI key is needed - none of these read/write paths call Gemini.
REM
REM  Needs: Docker Desktop running. You do NOT need 'make' or Python on your PC.
REM ==========================================================================
setlocal

REM Use UTF-8 so the emojis and boxes in the test output show correctly.
chcp 65001 >nul

REM Go to the project root (this file lives in tests\, root is one up).
cd /d "%~dp0.."

set COMPOSE=docker compose --env-file infra/.env.local -f infra/docker-compose.yml

echo.
echo ==========================================================================
echo   BIZZ_UP - M7 POLISH (lead status + dashboard orders) - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the database migrations)
echo     2) put the two pretend businesses + their bot configs in the database
echo     3) run the FULL explained M7-polish test (9 checks)
echo     4) run the strict M7-polish gate (pytest - the version CI uses)
echo     5) RE-RUN M2 wall + M3 login + M4 builder + M5 try-me + M5 sim + M7 dash
echo ==========================================================================
echo.

echo [1/5] Bringing the stack up (this also runs the migrations)...
%COMPOSE% up -d
if errorlevel 1 goto :fail
echo.

echo [2/5] Seeding the two pretend businesses + their bot_settings rows...
%COMPOSE% run --rm --entrypoint sh migrate -c "psql -v ON_ERROR_STOP=1 -f /supabase/seed.sql"
if errorlevel 1 goto :fail
echo.

echo [3/5] Running the FULL EXPLAINED M7-polish test (read this part)...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m7b_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [4/5] Running the strict M7-polish gate (pytest - the version CI uses)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest==8.3.4 pytest-asyncio==0.25.2 && PYTHONPATH=/app python -m pytest tests/test_lead_status.py -q"
if errorlevel 1 goto :fail
echo.

echo [5/5] No-regression check: re-running M2 + M3 + M4 + M5 + M7 dashboard...
echo --------------------------------------------------------------------------
echo   --- the M2 tenant wall (must still be 12/12)...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m2_full_test.py"
if errorlevel 1 goto :fail
echo   --- the M3 login front-door...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m3_full_test.py"
if errorlevel 1 goto :fail
echo   --- the M4 bot-builder full test...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m4_full_test.py"
if errorlevel 1 goto :fail
echo   --- the M5 try-me full test...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m5_full_test.py"
if errorlevel 1 goto :fail
echo   --- the M5b lead-memory full test...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m5b_full_test.py"
if errorlevel 1 goto :fail
echo   --- the M7 dashboard full test...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m7_full_test.py"
if errorlevel 1 goto :fail
echo   --- the strict suites (isolation + auth gate + builder + secret guard + tryme + sim + dashboard + lead-status)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest==8.3.4 pytest-asyncio==0.25.2 && PYTHONPATH=/app python -m pytest tests/isolation tests/test_auth_gate.py tests/test_bot_builder.py tests/test_secret_guard.py tests/test_bot_tryme.py tests/test_bot_sim.py tests/test_dashboard.py tests/test_lead_status.py -q"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 3: M7-polish RESULT 9/9
echo     - step 4: pytest "8 passed" (strict M7-polish gate)
echo     - step 5: M2 12/12 + M3 5/5 + M4 9/9 + M5 18/18 + M5b 10/10 + M7 15/15
echo               all green, and the strict bundle "passed" (no regression)
echo ==========================================================================
echo.
pause
goto :eof

:fail
echo.
echo **************************************************************************
echo   SOMETHING FAILED above. Is Docker Desktop running?
echo   Tip: start the app first with run.bat, then run this again.
echo **************************************************************************
echo.
pause
