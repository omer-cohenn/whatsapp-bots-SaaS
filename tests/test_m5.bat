@echo off
REM ==========================================================================
REM  test_m5.bat  -  Double-click to test M5 "the try-me test chat".
REM  Proves an owner can TRY their own bot like a customer, in a SANDBOX that
REM  saves nothing: the pure conversation engine handles every path correctly
REM  (menu, lead flows, validation, handoff, booking, back-to-menu), the
REM  /api/bot/tryme endpoint is login-gated + runs each owner's OWN config, and
REM  a whole test conversation writes NOTHING (no leads, no build-chat rows).
REM  Then it RE-RUNS the M2 wall, M3 login, and M4 bot-builder suites to prove
REM  nothing regressed.
REM
REM  No AI key is needed - try-me never calls Gemini (the engine is pure).
REM
REM  Needs: Docker Desktop running. (Same requirement as run.bat.)
REM  You do NOT need 'make' or Python on your PC - it all runs inside Docker.
REM ==========================================================================
setlocal

REM Use UTF-8 so the emojis and boxes in the test output show correctly.
chcp 65001 >nul

REM Go to the project root (this file lives in tests\, root is one up).
cd /d "%~dp0.."

set COMPOSE=docker compose --env-file infra/.env -f infra/docker-compose.yml

echo.
echo ==========================================================================
echo   BIZZ_UP - M5 TRY-ME TEST CHAT - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the database migrations)
echo     2) put the two pretend businesses + their bot configs in the database
echo     3) run the FULL explained M5 test (pure engine + endpoint, plain language)
echo     4) run the strict M5 pass/fail gate (pytest - the version CI uses)
echo     5) RE-RUN the M2 wall + M3 login + M4 bot-builder suites (no regression)
echo ==========================================================================
echo.

echo [1/5] Bringing the stack up (this also runs the migrations 0000..0005)...
%COMPOSE% up -d
if errorlevel 1 goto :fail
echo.

echo [2/5] Seeding the two pretend businesses + their bot_settings rows...
%COMPOSE% run --rm --entrypoint sh migrate -c "psql -v ON_ERROR_STOP=1 -f /supabase/seed.sql"
if errorlevel 1 goto :fail
echo.

echo [3/5] Running the FULL EXPLAINED M5 test (read this part)...
echo   (PART A is the pure engine - no DB needed; PART B hits /api/bot/tryme)
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m5_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [4/5] Running the strict M5 gate (pytest - the version CI uses)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest==8.3.4 pytest-asyncio==0.25.2 && PYTHONPATH=/app python -m pytest tests/strict/test_bot_tryme.py -q"
if errorlevel 1 goto :fail
echo.

echo [5/5] No-regression check: re-running M2 + M3 + M4...
echo --------------------------------------------------------------------------
echo   --- the M2 tenant wall (must still be 12/12)...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m2_full_test.py"
if errorlevel 1 goto :fail
echo   --- the M3 login front-door...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m3_full_test.py"
if errorlevel 1 goto :fail
echo   --- the M4 bot-builder full test...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m4_full_test.py"
if errorlevel 1 goto :fail
echo   --- the strict suites (isolation + auth gate + bot builder + secret guard)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest==8.3.4 pytest-asyncio==0.25.2 && PYTHONPATH=/app python -m pytest tests/isolation tests/strict/test_auth_gate.py tests/strict/test_bot_builder_*.py tests/strict/test_secret_guard.py -q"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 3: M5 RESULT all checks held (engine paths + endpoint safe)
echo     - step 4: pytest "passed" (the strict M5 CI gate)
echo     - step 5: M2 12/12 + M3 + M4 all green + strict pytest "passed"
echo               (M5 did NOT weaken the tenant wall, login, or builder)
echo ==========================================================================
echo.
pause
goto :eof

:fail
echo.
echo **************************************************************************
echo   SOMETHING FAILED above. Is Docker Desktop running?
echo   Tip: start the app first with run.bat, then run this again.
echo   (A missing GEMINI_API_KEY is FINE - the try-me does not need it.)
echo **************************************************************************
echo.
pause
