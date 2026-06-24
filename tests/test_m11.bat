@echo off
REM ==========================================================================
REM  test_m11.bat  -  Double-click to test M11 "public booking page +
REM  per-business Google Calendar" (decision 0011).
REM
REM  What M11 gives a business:
REM    * A PUBLIC booking page on a non-guessable link. A customer (no login)
REM      sees the services, picks a free time, and books - and that booking
REM      becomes a LEAD like every other enquiry.
REM    * SPLIT working hours (e.g. mornings AND evenings), and rules:
REM      earliest-notice, how-far-ahead, gaps between meetings. Times are typed
REM      in local Asia/Jerusalem but STORED in UTC.
REM    * The customer can cancel / reschedule with their own private link; the
REM      owner can confirm / reschedule from the dashboard.
REM    * Customer name / phone / email are ENCRYPTED at rest (gibberish in the
REM      raw DB), decrypted only for the owner.
REM    * OPTIONAL Google Calendar: each booking becomes an event on the owner's
REM      calendar (Meet link only if the owner turns Meet on). If Google is down
REM      the booking STILL succeeds. The Google token never leaks in a response.
REM    * Full tenant isolation (incl. the old C4 bug): business A can never see
REM      or change business B's bookings / services / settings.
REM
REM  Then it RE-RUNS M2..M10 to prove nothing regressed.
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
echo   BIZZ_UP - M11 PUBLIC BOOKING + GOOGLE CALENDAR - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the migrations, incl. 0008-0010)
echo     2) put the two pretend businesses in the database
echo     3) run the FULL explained M11 test (21 checks, incl. a negative control)
echo     4) run the strict M11 gate (pytest - the version CI uses, 28 tests)
echo     5) RE-RUN M2/M3/M4/M5/M7/M8/M9/M10 to prove no regression
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

echo [3/5] Running the FULL EXPLAINED M11 test (read this part)...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m11_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [4/5] Running the strict M11 gate (pytest - the version CI uses)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_m11_slots.py tests/strict/test_m11_booking.py tests/strict/test_m11_isolation.py tests/strict/test_m11_google.py -q"
if errorlevel 1 goto :fail
echo.

echo [5/5] No-regression check: re-running M2..M10...
echo --------------------------------------------------------------------------
echo   --- the M2 tenant wall (must still be 12/12)...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m2_full_test.py"
if errorlevel 1 goto :fail
echo   --- the strict M3..M10 pytest bundle...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_auth_gate.py tests/strict/test_bot_builder_*.py tests/strict/test_bot_tryme.py tests/strict/test_bot_sim.py tests/strict/test_dashboard.py tests/strict/test_lead_status.py tests/strict/test_m8.py tests/strict/test_m9.py tests/strict/test_m10.py tests/isolation tests/strict/test_secret_guard.py -q"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 3: M11 SCOREBOARD 21/21 checks held (incl. the negative control)
echo     - step 4: pytest "passed" (the strict M11 CI gate, 28 tests)
echo     - step 5: M2 RESULT 12/12 + the M3..M10 bundle "passed" (no regression)
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
