@echo off
REM ==========================================================================
REM  test_m10.bat  -  Double-click to test M10 "transcript TTL by status +
REM  private outcome note" (decision 0010).
REM
REM  M10's two promises:
REM    1) THE CHAT MUST NOT VANISH WHILE A HUMAN IS NEEDED.
REM       A live chat normally fades after ~60 min of silence. Once a customer
REM       asks for a human ('waiting') or an owner takes over ('human'), the
REM       chat PERSISTS (no timer) until someone answers. 'closed' lingers 30
REM       days. A NEW message on a waiting/human chat must NOT bring the 60-min
REM       timer back (the bug M10 kills).
REM    2) THE OWNER'S OUTCOME NOTE IS PRIVATE.
REM       deal/closed can carry a note - encrypted at rest, decrypted only for
REM       the owning business; another business can never read or write it.
REM
REM  Then it RE-RUNS M2..M9 to prove nothing regressed.
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
echo   BIZZ_UP - M10 TRANSCRIPT TTL + OUTCOME NOTE - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the database migrations, incl. 0007)
echo     2) put the two pretend businesses in the database
echo     3) run the FULL explained M10 test (10 checks, incl. a negative control)
echo     4) run the strict M10 gate (pytest - the version CI uses)
echo     5) RE-RUN M2/M3/M4/M5/M7/M8/M9 to prove no regression
echo ==========================================================================
echo.

echo [1/5] Bringing the stack up (this also runs the migrations)...
%COMPOSE% up -d
if errorlevel 1 goto :fail
echo.

echo [2/5] Seeding the two pretend businesses...
%COMPOSE% run --rm --entrypoint sh migrate -c "psql -v ON_ERROR_STOP=1 -f /supabase/seed.sql"
if errorlevel 1 goto :fail
echo.

echo [3/5] Running the FULL EXPLAINED M10 test (read this part)...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m10_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [4/5] Running the strict M10 gate (pytest - the version CI uses)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/test_m10.py -q"
if errorlevel 1 goto :fail
echo.

echo [5/5] No-regression check: re-running M2..M9...
echo --------------------------------------------------------------------------
echo   --- the M2 tenant wall (must still be 12/12)...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m2_full_test.py"
if errorlevel 1 goto :fail
echo   --- the strict M3..M9 pytest bundle...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/test_auth_gate.py tests/test_bot_builder.py tests/test_bot_tryme.py tests/test_bot_sim.py tests/test_dashboard.py tests/test_lead_status.py tests/test_m8.py tests/test_m9.py tests/isolation tests/test_secret_guard.py -q"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 3: M10 RESULT 10/10 checks held (chat persists + note private)
echo     - step 4: pytest "passed" (the strict M10 CI gate, 13 tests)
echo     - step 5: M2 RESULT 12/12 + the M3..M9 bundle "passed" (no regression)
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
