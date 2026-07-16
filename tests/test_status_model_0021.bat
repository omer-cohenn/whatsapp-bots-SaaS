@echo off
REM ==========================================================================
REM  test_status_model_0021.bat  -  Double-click to test the conversation/lead
REM  status model (decision 0021): close reasons + the human-mode abandon-clock
REM  fix + the WhatsApp-style unread badge.
REM
REM  THE STORY: a chat ends one of 3 ways and we write down WHY on the lead -
REM    "completed" (gave all details), "abandoned" (60 min quiet), or "answered"
REM    (a person handled it). The BIG bug fixed: a customer talking to a HUMAN
REM    for over an hour used to be wrongly marked "abandoned" - now EVERY
REM    incoming message resets the 60-minute timer. Plus: an unread badge that
REM    counts messages the owner hasn't read and clears when they open the chat.
REM
REM  This runs the FULL explained test (20 checks, incl. a negative control),
REM  then the strict pytest gate (CI version), then RE-RUNS the M2 tenant wall
REM  + the M10 TTL + M14 closed-fresh suites to prove no regression.
REM
REM  Needs: Docker Desktop running. You do NOT need 'make' or Python on your PC.
REM ==========================================================================
setlocal

REM Use UTF-8 so the emojis, boxes, and Hebrew in the output show correctly.
chcp 65001 >nul

REM Go to the project root (this file lives in tests\, root is one up).
cd /d "%~dp0.."

set COMPOSE=docker compose --env-file infra/.env -f infra/docker-compose.yml

echo.
echo ==========================================================================
echo   BIZZ_UP - STATUS MODEL (0021) - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the database migrations)
echo     2) RESTART the backend so the new code is loaded
echo     3) put the two pretend businesses in the database
echo     4) run the FULL explained test (20 checks, incl. a negative control)
echo     5) run the strict gate (pytest - the version CI uses)
echo     6) RE-RUN the M2 tenant wall + M10/M14 to prove no regression
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

echo [4/6] Running the FULL EXPLAINED test (read this part)...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm --no-deps backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/status_model_0021_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [5/6] Running the strict gate (pytest - the version CI uses)...
%COMPOSE% run --rm --no-deps backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_status_model_0021.py -q"
if errorlevel 1 goto :fail
echo.

echo [6/6] No-regression check: the tenant wall + the TTL/closed-fresh suites...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm --no-deps backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/isolation tests/strict/test_secret_guard.py tests/strict/test_m10.py tests/strict/test_m14.py -q"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 4: SCOREBOARD 20/20 checks passed
echo     - step 5: pytest "passed" (the strict CI gate, 23 tests)
echo     - step 6: tenant wall + secret guard 16 passed, M10/M14 22 passed
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
