@echo off
REM ==========================================================================
REM  test_m3.bat  -  Double-click to test M3 "Login & accounts".
REM  Proves the front door is safe (no login = no entry, each owner sees only
REM  their own), runs the strict pass/fail gate, AND re-runs the M2 tenant wall
REM  to prove M3 did not weaken it (must still be 12/12).
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
echo   BIZZ_UP - M3 LOGIN ^& ACCOUNTS - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the database migrations)
echo     2) put the pretend business in the database (Avi Insurance)
echo     3) run the FULL explained M3 test (5 checks, plain language)
echo     4) run the strict M3 pass/fail gate (pytest - the version CI uses)
echo     5) RE-RUN the M2 tenant wall to prove M3 did not break it (12/12)
echo ==========================================================================
echo.

echo [1/5] Bringing the stack up (this also runs the migrations)...
%COMPOSE% up -d
if errorlevel 1 goto :fail
echo.

echo [2/5] Seeding the pretend business (Avi Insurance / Bella Barber)...
%COMPOSE% run --rm --entrypoint sh migrate -c "psql -v ON_ERROR_STOP=1 -f /supabase/seed.sql"
if errorlevel 1 goto :fail
echo.

echo [3/5] Running the FULL EXPLAINED M3 test (read this part)...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m3_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [4/5] Running the strict M3 gate (pytest - the version CI uses)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest==8.3.4 pytest-asyncio==0.25.2 && PYTHONPATH=/app python -m pytest tests/strict/test_auth_gate.py -q"
if errorlevel 1 goto :fail
echo.

echo [5/5] No-regression check: re-running the M2 tenant wall (must be 12/12)...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m2_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 3: M3 RESULT 5/5 checks held (the front door is safe)
echo     - step 4: pytest "passed" (the strict CI gate)
echo     - step 5: M2 RESULT 12/12 locks held (the wall did NOT regress)
echo.
echo   NOTE: a REAL Google login (clicking "Sign in with Google" at
echo   http://localhost:5173) must be tested by hand in a browser - OAuth needs
echo   a real Google account and a real browser, which a script cannot do.
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
echo    infra\.env may still be blank - fill it and try again.)
echo **************************************************************************
echo.
pause
