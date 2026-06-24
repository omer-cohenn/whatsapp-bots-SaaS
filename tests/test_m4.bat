@echo off
REM ==========================================================================
REM  test_m4.bat  -  Double-click to test M4 "the AI bot builder".
REM  Proves an owner can design their bot safely: each business edits ONLY its
REM  own bot, broken configs are refused, and the AI helper is grounded, private,
REM  and degrades to 503 when no key is set. Then it RE-RUNS the M2 tenant wall
REM  AND the (now M4-extended) isolation suite to prove nothing regressed.
REM
REM  The AI is tested with a PRETEND Gemini (a fake plugged into the seam the
REM  backend exposes) - so you do NOT need a real GEMINI_API_KEY, and nothing
REM  calls the internet. Test step 3's check #9 deliberately runs with NO key to
REM  prove the "AI unavailable" (503) path.
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
echo   BIZZ_UP - M4 AI BOT BUILDER - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the database migrations)
echo     2) put the two pretend businesses + their bot configs in the database
echo     3) run the FULL explained M4 test (9 checks, plain language)
echo     4) run the strict M4 pass/fail gate (pytest - the version CI uses)
echo     5) RE-RUN the M2 tenant wall + isolation suite to prove no regression
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

echo [3/5] Running the FULL EXPLAINED M4 test (read this part)...
echo   (uses a PRETEND Gemini - no real key, no internet)
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m4_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [4/5] Running the strict M4 gate (pytest - the version CI uses)...
echo   (the Gemini call is mocked via monkeypatch; check #9 runs with NO key for the 503)
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest==8.3.4 pytest-asyncio==0.25.2 && PYTHONPATH=/app python -m pytest tests/strict/test_bot_builder_*.py -q"
if errorlevel 1 goto :fail
echo.

echo [5/5] No-regression check: re-running the M2 wall + the isolation suite...
echo --------------------------------------------------------------------------
echo   --- the M2 tenant wall (must still be 12/12)...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m2_full_test.py"
if errorlevel 1 goto :fail
echo   --- the strict isolation suite (now incl. bot_settings + bot_builder_messages)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest==8.3.4 pytest-asyncio==0.25.2 && PYTHONPATH=/app python -m pytest tests/isolation tests/strict/test_secret_guard.py -q"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 3: M4 RESULT 9/9 checks held (the bot builder is safe)
echo     - step 4: pytest "passed" (the strict M4 CI gate)
echo     - step 5: M2 RESULT 12/12 locks held + isolation pytest "passed"
echo               (M4 did NOT weaken the tenant wall)
echo.
echo   NOTE: the AI helper here uses a PRETEND Gemini. To see the REAL AI in a
echo   browser, put a real GEMINI_API_KEY in infra\.env.local, restart the stack,
echo   open http://localhost:5173, go to the bot builder, click the "AI assistant"
echo   button and chat. With no key the AI panel shows "unavailable" (by design).
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
echo    infra\.env.local may still be blank - fill it and try again. A missing
echo    GEMINI_API_KEY is FINE - these tests do not need it.)
echo **************************************************************************
echo.
pause
