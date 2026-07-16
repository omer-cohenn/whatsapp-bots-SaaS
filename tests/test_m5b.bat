@echo off
REM ==========================================================================
REM  test_m5b.bat  -  Double-click to test M5 "the bot's LEAD MEMORY".
REM  Where test_m5.bat proved the no-save "try-me" sandbox, THIS proves the real
REM  RUNTIME that REMEMBERS: starting a flow opens a lead (is_test, in_progress)
REM  + a 'started' event; answers grow the SAME lead + 'step' events; finishing
REM  flips it to 'new' + submitted_at + 'completed'; the stored phone/name/answers
REM  are ENCRYPTED at rest (ciphertext, not plaintext); a human handoff sets the
REM  chat to 'human' in Redis and the bot then goes SILENT; an idle in_progress
REM  lead is swept to 'abandoned' + an 'abandoned' event; and business A can never
REM  read or write business B's leads (/api/bot/sim is 401 without a login and
REM  scoped to the caller only).
REM  Then it RE-RUNS the M2 wall, M3 login, M4 builder, and M5 try-me suites to
REM  prove nothing regressed.
REM
REM  No AI key is needed - the runtime path never calls Gemini (the engine is pure).
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
echo   BIZZ_UP - M5 LEAD MEMORY (runtime) - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the database migrations 0000..0006)
echo     2) put the two pretend businesses + their bot configs in the database
echo     3) run the FULL explained M5b test (lead lifecycle + encryption + sweep)
echo     4) run the strict M5b pass/fail gate (pytest - the version CI uses)
echo     5) RE-RUN M2 wall + M3 login + M4 builder + M5 try-me suites (no regression)
echo ==========================================================================
echo.

echo [1/5] Bringing the stack up (this also runs the migrations 0000..0006)...
%COMPOSE% up -d
if errorlevel 1 goto :fail
echo.

echo [2/5] Seeding the two pretend businesses + their bot_settings rows...
%COMPOSE% run --rm --entrypoint sh migrate -c "psql -v ON_ERROR_STOP=1 -f /supabase/seed.sql"
if errorlevel 1 goto :fail
echo.

echo [3/5] Running the FULL EXPLAINED M5b test (read this part)...
echo   (drives POST /api/bot/sim + bot_runtime.run_turn against the real stack)
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m5b_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [4/5] Running the strict M5b gate (pytest - the version CI uses)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest==8.3.4 pytest-asyncio==0.25.2 && PYTHONPATH=/app python -m pytest tests/strict/test_bot_sim.py -q"
if errorlevel 1 goto :fail
echo.

echo [5/5] No-regression check: re-running M2 + M3 + M4 + M5 try-me...
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
echo   --- the M5 try-me full test...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m5_full_test.py"
if errorlevel 1 goto :fail
echo   --- the strict suites (isolation + auth gate + builder + secret guard + tryme + sim)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest==8.3.4 pytest-asyncio==0.25.2 && PYTHONPATH=/app python -m pytest tests/isolation tests/strict/test_auth_gate.py tests/strict/test_bot_builder_*.py tests/strict/test_secret_guard.py tests/strict/test_bot_tryme.py tests/strict/test_bot_sim.py -q"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 3: M5b RESULT 10/10 checks held (lead memory works, wall holds)
echo     - step 4: pytest "passed" (the strict M5b CI gate)
echo     - step 5: M2 12/12 + M3 + M4 + M5 try-me all green + strict pytest "passed"
echo               (M5b did NOT weaken the tenant wall, login, builder, or try-me)
echo ==========================================================================
echo.
pause
goto :eof

:fail
echo.
echo **************************************************************************
echo   SOMETHING FAILED above. Is Docker Desktop running?
echo   Tip: start the app first with run.bat, then run this again.
echo   (A missing GEMINI_API_KEY is FINE - the runtime path does not need it.)
echo **************************************************************************
echo.
pause
