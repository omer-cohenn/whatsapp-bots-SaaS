@echo off
REM ==========================================================================
REM  test_m12.bat  -  Double-click to test M12 "Back-Office" (the control room).
REM
REM  What M12 adds:
REM    * A platform-operator CONTROL ROOM for Omer (the mall owner): one window
REM      onto EVERY business at once - who opened and when, last login, which
REM      plan, how busy (messages/leads). And actions: change a plan, or SUSPEND
REM      a business. Suspending really SILENCES that business's WhatsApp bot.
REM    * It is the ONE place we cross the tenant wall on purpose, so it has its
REM      OWN locked door: only emails on ADMIN_EMAILS may enter (checked LIVE).
REM      Crossing happens only through narrow SECURITY DEFINER db functions - the
REM      normal app role gets ZERO direct access to the control-room tables.
REM    * Admin routes: GET /api/admin/overview, /businesses, /businesses/{id},
REM      /businesses/{id}/usage, /plans; PATCH /businesses/{id}/subscription.
REM      /api/me gains an is_admin flag.
REM
REM  Then it RE-RUNS M2..M11.2 + M6a/.1/.2 to prove nothing regressed.
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
echo   BIZZ_UP - M12 "BACK-OFFICE" (control room) - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the migrations, incl. 0015-0017)
echo     2) put the two pretend businesses in the database
echo     3) run the FULL explained M12 test (13 checks, incl. a negative control)
echo     4) run the strict M12 gate (pytest - the version CI uses, 26 tests)
echo     5) RE-RUN M2 + the M3..M11.2 + M6a/.1/.2 bundle to prove no regression
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

echo [3/5] Running the FULL EXPLAINED M12 test (read this part)...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m12_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [4/5] Running the strict M12 gate (pytest - the version CI uses)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_m12_*.py -q"
if errorlevel 1 goto :fail
echo.

echo [5/5] No-regression check: re-running M2..M11.2 + M6a/.1/.2...
echo --------------------------------------------------------------------------
echo   --- the M2 tenant wall (must still be 12/12)...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m2_full_test.py"
if errorlevel 1 goto :fail
echo   --- the strict M3..M11.2 + M6a/.1/.2 pytest bundle...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_auth_gate.py tests/strict/test_bot_builder_*.py tests/strict/test_bot_tryme.py tests/strict/test_bot_sim.py tests/strict/test_dashboard.py tests/strict/test_lead_status.py tests/strict/test_m8.py tests/strict/test_m9.py tests/strict/test_m10.py tests/strict/test_m11_slots.py tests/strict/test_m11_booking.py tests/strict/test_m11_isolation.py tests/strict/test_m11_google.py tests/strict/test_m11_1_*.py tests/strict/test_m11_2.py tests/strict/test_m6a.py tests/strict/test_m6a1.py tests/strict/test_m6a2.py tests/strict/test_m12_*.py tests/isolation tests/strict/test_secret_guard.py -q"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 3: M12 13/13 checks held (incl. the negative control)
echo     - step 4: pytest "passed" (the strict M12 CI gate, 26 tests)
echo     - step 5: M2 RESULT 12/12 + the M3..M11.2+M6a/.1/.2+M12 bundle "passed"
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
