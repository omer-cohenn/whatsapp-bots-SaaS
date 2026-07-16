@echo off
REM ==========================================================================
REM  test_m2.bat  -  Double-click to test the M2 "tenant wall".
REM  Runs EVERY M2 test we built, with plain-language explanations, then the
REM  strict pass/fail gate, then proves the gate catches a real break.
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
echo   BIZZ_UP - M2 TENANT WALL - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the database migrations)
echo     2) put two pretend businesses in the database (Avi and Bella)
echo     3) run the FULL explained test (12 checks, plain language)
echo     4) run the strict pass/fail gate (the robot version, for CI)
echo     5) BREAK one lock on purpose to prove the test would catch it, then fix it
echo ==========================================================================
echo.

echo [1/5] Bringing the stack up (this also runs the migrations)...
%COMPOSE% up -d
if errorlevel 1 goto :fail
echo.

echo [2/5] Seeding the two pretend businesses (Avi Insurance / Bella Barber)...
%COMPOSE% run --rm --entrypoint sh migrate -c "psql -v ON_ERROR_STOP=1 -f /supabase/seed.sql"
if errorlevel 1 goto :fail
echo.

echo [3/5] Running the FULL EXPLAINED test (read this part)...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m2_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [4/5] Running the strict pass/fail gate (pytest - the version CI uses)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest==8.3.4 pytest-asyncio==0.25.2 && PYTHONPATH=/app python -m pytest tests/isolation tests/strict/test_secret_guard.py -q"
if errorlevel 1 goto :fail
echo.

echo [5/5] Proof the test is REAL: break one lock, expect a FAIL, then restore...
echo   --- breaking the 'WITH CHECK' lock on leads...
%COMPOSE% run --rm --entrypoint sh migrate -c "psql -v ON_ERROR_STOP=1 -c \"DROP POLICY IF EXISTS p_tenant_isolation ON leads; CREATE POLICY p_tenant_isolation ON leads USING (business_id = current_business_id()) WITH CHECK (true);\""
echo   --- running the test with the lock broken (it SHOULD report a failure)...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m2_full_test.py" | findstr /C:"RESULT"
echo   --- restoring the lock (re-applying the migrations)...
%COMPOSE% run --rm migrate >nul
echo   --- re-running to confirm it is green again...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m2_full_test.py" | findstr /C:"RESULT"
echo.

echo ==========================================================================
echo   ALL DONE. If steps 3 and 4 said "locks held / passed", the wall is solid.
echo   Step 5 should have shown one FAILED line (broken) then a held line (fixed).
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
