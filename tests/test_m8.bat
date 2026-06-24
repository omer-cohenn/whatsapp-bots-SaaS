@echo off
REM ==========================================================================
REM  test_m8.bat  -  Double-click to test M8 "the in-app human-handoff chat".
REM  Proves an owner can take over a chat from the bot: there is a full
REM  transcript (customer + bot + owner lines, trimmed to the last 200), a
REM  status journey bot->waiting->human->closed, the bot stays SILENT in both
REM  'waiting' and 'human' (but the customer's messages are still recorded),
REM  and the read endpoints return status + linked lead + messages. Then it
REM  RE-RUNS the M2 tenant wall AND the M3/M4/M5/M7 suites to prove nothing
REM  regressed - and that business A can NEVER read business B's chat.
REM
REM  Needs: Docker Desktop running. (Same requirement as run.bat.)
REM  You do NOT need 'make' or Python on your PC - it all runs inside Docker.
REM ==========================================================================
setlocal

REM Use UTF-8 so the emojis and boxes in the test output show correctly.
chcp 65001 >nul

REM Go to the project root (this file lives in tests\, root is one up).
cd /d "%~dp0.."

set COMPOSE=docker compose --env-file infra/.env.local -f infra/docker-compose.yml

echo.
echo ==========================================================================
echo   BIZZ_UP - M8 IN-APP HUMAN-HANDOFF CHAT - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the database migrations)
echo     2) put the two pretend businesses + their bot configs in the database
echo     3) run the FULL explained M8 test (27 checks, plain language)
echo     4) run the strict M8 pass/fail gate (pytest - the version CI uses)
echo     5) RE-RUN M2 wall + M3/M4/M5/M7 to prove no regression
echo ==========================================================================
echo.

echo [1/5] Bringing the stack up (this also runs the migrations 0000..)...
%COMPOSE% up -d
if errorlevel 1 goto :fail
echo.

echo [2/5] Seeding the two pretend businesses + their bot_settings rows...
%COMPOSE% run --rm --entrypoint sh migrate -c "psql -v ON_ERROR_STOP=1 -f /supabase/seed.sql"
if errorlevel 1 goto :fail
echo.

echo [3/5] Running the FULL EXPLAINED M8 test (read this part)...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m8_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [4/5] Running the strict M8 gate (pytest - the version CI uses)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest==8.3.4 pytest-asyncio==0.25.2 && PYTHONPATH=/app python -m pytest tests/strict/test_m8.py -q"
if errorlevel 1 goto :fail
echo.

echo [5/5] No-regression check: re-running the wall + earlier milestones...
echo --------------------------------------------------------------------------
echo   --- the M2 tenant wall (must still be 12/12)...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m2_full_test.py"
if errorlevel 1 goto :fail
echo   --- the strict M2-M8 bundle (isolation + auth + builder + sim + dashboard + m8)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest==8.3.4 pytest-asyncio==0.25.2 && PYTHONPATH=/app python -m pytest tests/isolation tests/strict/test_auth_gate.py tests/strict/test_secret_guard.py tests/strict/test_bot_builder_*.py tests/strict/test_bot_tryme.py tests/strict/test_bot_sim.py tests/strict/test_dashboard.py tests/strict/test_lead_status.py tests/strict/test_m8.py -q"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 3: M8 SCOREBOARD 27/27 checks passed (the handoff chat works)
echo     - step 4: pytest "passed" (the strict M8 CI gate, 17 tests)
echo     - step 5: M2 RESULT 12/12 locks held + the strict bundle "passed"
echo               (M8 did NOT weaken the tenant wall, and A never sees B's chat)
echo ==========================================================================
echo.
pause
goto :eof

:fail
echo.
echo **************************************************************************
echo   SOMETHING FAILED above. Is Docker Desktop running?
echo   Tip: start the app first with run.bat, then run this again.
echo   (If the backend would not boot, a GOOGLE_* or SESSION_SECRET value in
echo    infra\.env.local may still be blank - fill it and try again.)
echo **************************************************************************
echo.
pause
