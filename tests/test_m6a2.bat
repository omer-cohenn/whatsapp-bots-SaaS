@echo off
REM ==========================================================================
REM  test_m6a2.bat  -  Double-click to test M6a.2: the owner's manual reply
REM                    now actually REACHES the customer on WhatsApp.
REM
REM  What M6a.2 adds (on top of M6a / M6a.1):
REM    * Before: when the OWNER typed a manual reply in the dashboard it was only
REM      SAVED (queued in Redis) - nothing sent it to WhatsApp. The customer never
REM      saw it. (The bot's own auto-replies WERE sent; only the human reply wasn't.)
REM    * Now: POST /api/conversations/{id}/reply still queues the reply AND
REM      best-effort SENDS it to WhatsApp via the gateway's new internal door
REM      POST /send-bot. The response gains "delivered": true/false. The
REM      conversation id IS the customer's WhatsApp address, so it doubles as "to".
REM    * New backend helper send_outbound(to, text): True only on a 2xx + ok,
REM      graceful False on any failure; never logs the phone/jid or the text.
REM    * New gateway door /send-bot: token-gated (401), validated (400),
REM      503 when not connected, 200 + message_id when it sent (loop-guarded).
REM
REM  NOTE: the REAL send to a SECOND person's phone is a MANUAL step for Omer.
REM        But because the gateway here is linked to your real WhatsApp, the LIVE
REM        check sends a tiny "please ignore" note to YOUR OWN number so you can
REM        see a real message arrive. If WhatsApp is not linked, that one check
REM        is skipped automatically.
REM
REM  Then it RE-RUNS the M2 wall + the strict M3..M11.2 + M6a + M6a.1 + M6a.2
REM  bundle to prove nothing regressed.
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
echo   BIZZ_UP - M6a.2 OWNER MANUAL REPLY -^> WHATSAPP - FULL TEST
echo ==========================================================================
echo   This will:
echo     1) make sure the stack is up (and apply the migrations)
echo     2) RESTART backend + gateway so the new M6a.2 code is loaded
echo     3) seed the two pretend businesses
echo     4) run the FULL explained M6a.2 test (10 checks, incl. a LIVE send)
echo     5) run the strict M6a.2 gate (pytest - the version CI uses)
echo     6) RE-RUN the M2 wall + M3..M11.2 + M6a + M6a.1 + M6a.2 (no regression)
echo ==========================================================================
echo.

echo [1/6] Bringing the stack up (this also runs the migrations)...
%COMPOSE% up -d
if errorlevel 1 goto :fail
echo.

echo [2/6] Restarting backend + gateway so the new code is loaded...
%COMPOSE% restart backend gateway
if errorlevel 1 goto :fail
echo   (giving the gateway a few seconds to boot its socket...)
timeout /t 8 /nobreak >nul
echo.

echo [3/6] Seeding the two pretend businesses...
%COMPOSE% run --rm --entrypoint sh migrate -c "psql -v ON_ERROR_STOP=1 -f /supabase/seed.sql"
if errorlevel 1 goto :fail
echo.

echo [4/6] Running the FULL EXPLAINED M6a.2 test (read this part)...
echo --------------------------------------------------------------------------
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m6a2_full_test.py"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo [5/6] Running the strict M6a.2 gate (pytest - the version CI uses)...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_m6a2.py -q"
if errorlevel 1 goto :fail
echo.

echo [6/6] No-regression check: re-running M2 + M3..M11.2 + M6a + M6a.1 + M6a.2...
echo --------------------------------------------------------------------------
echo   --- the M2 tenant wall (must still be 12/12)...
%COMPOSE% run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m2_full_test.py"
if errorlevel 1 goto :fail
echo   --- the strict M3..M11.2 + M6a + M6a.1 + M6a.2 pytest bundle...
%COMPOSE% run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/strict/test_auth_gate.py tests/strict/test_bot_builder_*.py tests/strict/test_bot_tryme.py tests/strict/test_bot_sim.py tests/strict/test_dashboard.py tests/strict/test_lead_status.py tests/strict/test_m8.py tests/strict/test_m9.py tests/strict/test_m10.py tests/strict/test_m11_slots.py tests/strict/test_m11_booking.py tests/strict/test_m11_isolation.py tests/strict/test_m11_google.py tests/strict/test_m11_1_*.py tests/strict/test_m11_2.py tests/strict/test_m6a.py tests/strict/test_m6a1.py tests/strict/test_m6a2.py tests/isolation tests/strict/test_secret_guard.py -q"
if errorlevel 1 goto :fail
echo --------------------------------------------------------------------------
echo.

echo ==========================================================================
echo   ALL DONE. You should have seen:
echo     - step 4: M6a.2 SCOREBOARD 10/10 checks held (incl. the LIVE send)
echo     - step 5: pytest "passed" (the strict M6a.2 CI gate)
echo     - step 6: M2 RESULT 12/12 + the full bundle "passed"
echo.
echo   MANUAL STEP (only you can do this): from a phone, message your linked
echo   WhatsApp so a chat shows in the dashboard; set it to "human" and type a
echo   reply - it should arrive on the customer's WhatsApp.
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
