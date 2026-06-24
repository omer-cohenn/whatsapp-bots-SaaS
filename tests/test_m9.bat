@echo off
REM ==========================================================================
REM  test_m9.bat  -  Double-click to test M9 "lead outcomes, unified around
REM  the LEAD" (decision 0009).
REM
REM  M9's idea: the LEAD's status is the ONE TRUE record of an outcome.
REM    - "בוצעה עסקה"  -> lead status 'deal'   + chat status 'closed'
REM    - "סגירת פנייה" -> lead status 'closed' + chat status 'closed'
REM  Both reuse the EXISTING endpoints (PATCH /api/leads/{id}/status and
REM  POST /api/conversations/{id}/status) - no new endpoint.
REM
REM  This proves: you can filter leads by deal/closed (tenant-scoped), every
REM  lead carries its conversation_id, EVERY handoff now leaves a tiny lead
REM  ("פנייה לנציג"), and the outcome flow works end-to-end. Then it RE-RUNS
REM  M2, M3, M4, M5, M7, M8 to prove nothing regressed.
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
echo   BIZZ_UP - M9 LEAD OUTCOMES - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the database migrations)
echo     2) put the two pretend businesses in the database
echo     3) run the FULL explained M9 test (11 checks, incl. a negative control)
echo     4) run the strict M9 gate (pytest - the version CI uses)
echo     5) RE-RUN M2/M3/M4/M5/M7/M8 to prove no regression
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

echo [3/5] Running the FULL EXPLAINED M9 test (read this part)...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m9_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [4/5] Running the strict M9 gate (pytest - the version CI uses)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_m9.py -q"
if errorlevel 1 goto :fail
echo.

echo [5/5] No-regression check: re-running M2..M8...
echo --------------------------------------------------------------------------
echo   --- the M2 tenant wall (must still be 12/12)...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m2_full_test.py"
if errorlevel 1 goto :fail
echo   --- the strict M3..M8 pytest bundle...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_auth_gate.py tests/strict/test_bot_builder_*.py tests/strict/test_bot_tryme.py tests/strict/test_bot_sim.py tests/strict/test_dashboard.py tests/strict/test_lead_status.py tests/strict/test_m8.py tests/isolation tests/strict/test_secret_guard.py -q"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 3: M9 RESULT 11/11 checks held (lead outcomes work + wall holds)
echo     - step 4: pytest "passed" (the strict M9 CI gate)
echo     - step 5: M2 RESULT 12/12 + the M3..M8 bundle "passed" (no regression)
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
