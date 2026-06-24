@echo off
REM ==========================================================================
REM  test_m6a1.bat  -  Double-click to test M6a.1 external "test numbers".
REM
REM  What M6a.1 adds (on top of M6a "Message Yourself"):
REM    * The owner can register up to 5 OUTSIDE phone numbers (each with an
REM      optional name). When ANY of those numbers messages the owner's linked
REM      WhatsApp, the gateway runs it through the REAL bot (run_turn,
REM      is_test=False) and replies - exactly like the self-chat.
REM    * Everyone NOT on the list is IGNORED (silent). The bot answers only when
REM      the business's bot is PUBLISHED. Self-chat keeps working unchanged.
REM    * Owner admin routes: GET/PUT /api/whatsapp/test-numbers (session-gated,
REM      tenant-scoped, <=5 cap, phone+label encrypted at rest).
REM
REM  NOTE: the REAL send/receive from a SECOND phone is a MANUAL step for Omer
REM        (a script cannot type in WhatsApp). The whole backend pipeline UP TO
REM        the phone is proven automatically below.
REM
REM  Then it RE-RUNS the M2 wall + the strict M3..M11.2 + M6a + M6a.1 bundle to
REM  prove nothing regressed.
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
echo   BIZZ_UP - M6a.1 EXTERNAL "TEST NUMBERS" ALLOW-LIST - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the migrations, incl. 0014)
echo     2) put the two pretend businesses in the database
echo     3) run the FULL explained M6a.1 test (11 checks, incl. a negative control)
echo     4) run the strict M6a.1 gate (pytest - the version CI uses, 16 tests)
echo     5) RE-RUN the M2 wall + M3..M11.2 + M6a + M6a.1 to prove no regression
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

echo [3/5] Running the FULL EXPLAINED M6a.1 test (read this part)...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m6a1_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [4/5] Running the strict M6a.1 gate (pytest - the version CI uses)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_m6a1.py -q"
if errorlevel 1 goto :fail
echo.

echo [5/5] No-regression check: re-running M2 + M3..M11.2 + M6a + M6a.1...
echo --------------------------------------------------------------------------
echo   --- the M2 tenant wall (must still be 12/12)...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m2_full_test.py"
if errorlevel 1 goto :fail
echo   --- the strict M3..M11.2 + M6a + M6a.1 pytest bundle...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_auth_gate.py tests/strict/test_bot_builder_*.py tests/strict/test_bot_tryme.py tests/strict/test_bot_sim.py tests/strict/test_dashboard.py tests/strict/test_lead_status.py tests/strict/test_m8.py tests/strict/test_m9.py tests/strict/test_m10.py tests/strict/test_m11_slots.py tests/strict/test_m11_booking.py tests/strict/test_m11_isolation.py tests/strict/test_m11_google.py tests/strict/test_m11_1_*.py tests/strict/test_m11_2.py tests/strict/test_m6a.py tests/strict/test_m6a1.py tests/isolation tests/strict/test_secret_guard.py -q"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 3: M6a.1 SCOREBOARD 11/11 checks held (incl. the negative control)
echo     - step 4: pytest "passed" (the strict M6a.1 CI gate, 16 tests)
echo     - step 5: M2 RESULT 12/12 + the M3..M11.2+M6a+M6a.1 bundle "passed"
echo.
echo   MANUAL STEP (only you can do this): scan the QR at :3000/qr, add a SECOND
echo   phone you own to "מספרים לבדיקה" in the dashboard, then message your
echo   linked WhatsApp from that phone - the bot should reply. A phone NOT on the
echo   list gets no reply.
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
