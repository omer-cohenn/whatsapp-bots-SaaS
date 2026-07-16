@echo off
REM ==========================================================================
REM  test_m13.bat  -  Double-click to test M13 "Back-Office ANALYTICS + CRM".
REM
REM  What M13 adds (on top of M12's control room):
REM    * A real SaaS-OWNER dashboard for Omer: LTV per business (plan price x
REM      tenure - an ESTIMATE), messages-per-business (billing basis), lead types
REM      (appointment / lead / human-handoff) in one donut, AI operations per day
REM      and per plan, and trend graphs fed by a DAILY platform snapshot.
REM    * A platform-level SALES CRM: every business is a card moving across the
REM      pipeline new -> contacted -> warming -> won/lost, with notes + a
REM      follow-up reminder, so Omer knows who to chase until they pay.
REM    * New routes (all behind the admin gate): GET analytics/leads-by-type,
REM      analytics/messages, analytics/ai-ops, analytics/by-plan, analytics/trends;
REM      GET crm; PATCH businesses/{id}/crm; POST + GET businesses/{id}/crm/notes.
REM      GET overview now stamps today's snapshot + returns avg_ltv; GET
REM      businesses/{id} now returns ltv_estimate / ai_calls / crm.
REM    * Isolation is NOT weakened: the three new tables (business_crm, crm_notes,
REM      platform_snapshots) have ZERO direct app_role grant - only the narrow
REM      SECURITY DEFINER functions reach them. Proven with a negative control.
REM
REM  Then it RE-RUNS M2 + the M3..M12 strict bundle to prove nothing regressed.
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
echo   BIZZ_UP - M13 "BACK-OFFICE ANALYTICS + CRM" - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the migrations, incl. 0018-0020)
echo     2) put the two pretend businesses in the database
echo     3) run the FULL explained M13 test (16 checks, incl. a negative control)
echo     4) run the strict M13 gate (pytest - the version CI uses, 30 tests)
echo     5) RE-RUN M2 + the M3..M12 strict bundle to prove no regression
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

echo [3/5] Running the FULL EXPLAINED M13 test (read this part)...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m13_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [4/5] Running the strict M13 gate (pytest - the version CI uses)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_m13_*.py -q"
if errorlevel 1 goto :fail
echo.

echo [5/5] No-regression check: re-running M2 + M3..M12...
echo --------------------------------------------------------------------------
echo   --- the M2 tenant wall (must still be 12/12)...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m2_full_test.py"
if errorlevel 1 goto :fail
echo   --- the strict M3..M12 pytest bundle (now incl. M13)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_auth_gate.py tests/strict/test_bot_builder_*.py tests/strict/test_bot_tryme.py tests/strict/test_bot_sim.py tests/strict/test_dashboard.py tests/strict/test_lead_status.py tests/strict/test_m8.py tests/strict/test_m9.py tests/strict/test_m10.py tests/strict/test_m11_slots.py tests/strict/test_m11_booking.py tests/strict/test_m11_isolation.py tests/strict/test_m11_google.py tests/strict/test_m11_1_*.py tests/strict/test_m11_2.py tests/strict/test_m6a.py tests/strict/test_m6a1.py tests/strict/test_m6a2.py tests/strict/test_m12_*.py tests/strict/test_m13_*.py tests/isolation tests/strict/test_secret_guard.py -q"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 3: M13 16/16 checks held (incl. the negative control)
echo     - step 4: pytest "passed" (the strict M13 CI gate, 30 tests)
echo     - step 5: M2 RESULT 12/12 + the M3..M13 bundle "passed"
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
