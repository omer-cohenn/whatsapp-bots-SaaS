@echo off
REM ==========================================================================
REM  test_m11_2.bat  -  Double-click to test M11.2 "service card image".
REM
REM  What M11.2 adds on top of the M11.1 booking page:
REM    * Each service can now carry a PICTURE. The owner uploads a photo; the
REM      browser shrinks it on a canvas into a small compressed data: URL and
REM      saves it in the new services.image_url column (a plain http(s) link is
REM      also accepted). No image -> the public card shows a placeholder frame.
REM    * Full tenant isolation on the NEW field too: business A can never read or
REM      change business B's service image.
REM
REM  Then it RE-RUNS M2..M11.1 to prove nothing regressed.
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
echo   BIZZ_UP - M11.2 SERVICE CARD IMAGE - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the migrations, incl. 0012)
echo     2) put the two pretend businesses in the database
echo     3) run the FULL explained M11.2 test (13 checks, incl. a negative control)
echo     4) run the strict M11.2 gate (pytest - the version CI uses, 11 tests)
echo     5) RE-RUN M2/M3/M4/M5/M7/M8/M9/M10/M11/M11.1 to prove no regression
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

echo [3/5] Running the FULL EXPLAINED M11.2 test (read this part)...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m11_2_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [4/5] Running the strict M11.2 gate (pytest - the version CI uses)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_m11_2.py -q"
if errorlevel 1 goto :fail
echo.

echo [5/5] No-regression check: re-running M2..M11.1...
echo --------------------------------------------------------------------------
echo   --- the M2 tenant wall (must still be 12/12)...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m2_full_test.py"
if errorlevel 1 goto :fail
echo   --- the strict M3..M11.1 pytest bundle...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_auth_gate.py tests/strict/test_bot_builder_*.py tests/strict/test_bot_tryme.py tests/strict/test_bot_sim.py tests/strict/test_dashboard.py tests/strict/test_lead_status.py tests/strict/test_m8.py tests/strict/test_m9.py tests/strict/test_m10.py tests/strict/test_m11_slots.py tests/strict/test_m11_booking.py tests/strict/test_m11_isolation.py tests/strict/test_m11_google.py tests/strict/test_m11_1_*.py tests/strict/test_m11_2.py tests/isolation tests/strict/test_secret_guard.py -q"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 3: M11.2 SCOREBOARD 13/13 checks held (incl. the negative control)
echo     - step 4: pytest "passed" (the strict M11.2 CI gate, 11 tests)
echo     - step 5: M2 RESULT 12/12 + the M3..M11.2 bundle "passed" (no regression)
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
