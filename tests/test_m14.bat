@echo off
REM ==========================================================================
REM  test_m14.bat  -  Double-click to test M14 "two bot fixes".
REM
REM  FIX A: the bot's OPENING message shouldn't list the menu TWICE. The
REM    GREETING (the AI builder's short hello) must NOT contain its own option
REM    list/numbers - the engine already adds the real numbered menu right
REM    after it. We check the AI builder's instructions now forbid that.
REM
REM  FIX B: a CLOSED chat should START FRESH when the customer writes again -
REM    clean transcript, greeting+menu, a NEW lead if they pick something -
REM    while the OLD finished lead stays saved in the database (history kept).
REM    Resetting one chat must NEVER touch another business's chats.
REM
REM  This runs the FULL explained M14 test (12 checks, incl. a negative
REM  control), then the strict M14 gate (pytest, the version CI uses), then
REM  RE-RUNS M2 + M5/M5b + the M8/M9/M10/M11 + bot_sim/tryme bundle to prove
REM  nothing regressed.
REM
REM  Needs: Docker Desktop running. You do NOT need 'make' or Python on your PC.
REM ==========================================================================
setlocal

REM Use UTF-8 so the emojis, boxes, and Hebrew in the output show correctly.
chcp 65001 >nul

REM Go to the project root (this file lives in tests\, root is one up).
cd /d "%~dp0.."

set COMPOSE=docker compose --env-file infra/.env.local -f infra/docker-compose.yml

echo.
echo ==========================================================================
echo   BIZZ_UP - M14 TWO BOT FIXES - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the database migrations)
echo     2) RESTART the backend so the new code is loaded
echo     3) put the two pretend businesses in the database
echo     4) run the FULL explained M14 test (12 checks, incl. a negative control)
echo     5) run the strict M14 gate (pytest - the version CI uses)
echo     6) RE-RUN M2 + the engine/runtime/conversation bundle (no regression)
echo ==========================================================================
echo.

echo [1/6] Bringing the stack up (this also runs the migrations)...
%COMPOSE% up -d
if errorlevel 1 goto :fail
echo.

echo [2/6] Restarting the backend so the new code loads (no auto-reload)...
%COMPOSE% restart backend
if errorlevel 1 goto :fail
echo.

echo [3/6] Seeding the two pretend businesses...
%COMPOSE% run --rm --entrypoint sh migrate -c "psql -v ON_ERROR_STOP=1 -f /supabase/seed.sql"
if errorlevel 1 goto :fail
echo.

echo [4/6] Running the FULL EXPLAINED M14 test (read this part)...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m14_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [5/6] Running the strict M14 gate (pytest - the version CI uses)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_m14.py -q"
if errorlevel 1 goto :fail
echo.

echo [6/6] No-regression check: re-running the tenant wall + the bundle...
echo --------------------------------------------------------------------------
echo   --- the M2 tenant wall (must still be 12/12)...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m2_full_test.py"
if errorlevel 1 goto :fail
echo   --- the M5 engine + M5b runtime narrated suites...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m5_full_test.py"
if errorlevel 1 goto :fail
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m5b_full_test.py"
if errorlevel 1 goto :fail
echo   --- the strict M8/M9/M10/M11 + bot_sim/tryme + builder + isolation bundle...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_bot_builder_*.py tests/strict/test_bot_tryme.py tests/strict/test_bot_sim.py tests/strict/test_m8.py tests/strict/test_m9.py tests/strict/test_m10.py tests/strict/test_m11_slots.py tests/strict/test_m11_booking.py tests/strict/test_m11_isolation.py tests/strict/test_m11_google.py tests/strict/test_m11_1_*.py tests/strict/test_m11_2.py tests/strict/test_lead_status.py tests/strict/test_dashboard.py tests/isolation tests/strict/test_auth_gate.py tests/strict/test_secret_guard.py -q"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 4: M14 SCOREBOARD 12/12 checks passed (both fixes work)
echo     - step 5: pytest "passed" (the strict M14 CI gate)
echo     - step 6: M2 RESULT 12/12 + M5 18/18 + M5b 10/10 + the bundle "passed"
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
