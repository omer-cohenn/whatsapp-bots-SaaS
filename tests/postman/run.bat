@echo off
REM ============================================================================
REM  Bizz_up — Postman/newman CI smoke runner.
REM  Runs the pre-deploy auth-matrix collection. Exits non-zero on ANY failed
REM  assertion so CI blocks the deploy.
REM
REM  SECRETS ARE NEVER COMMITTED. Provide them as environment variables before
REM  running (CI sets these from its secret store):
REM     BASE_URL       - target backend base URL (default http://localhost:8000)
REM     GATEWAY_TOKEN  - the X-Gateway-Token (same value as GATEWAY_API_TOKEN)
REM     SESSION_COOKIE - a full 'bizzup_session=<sid>' cookie for the /api smoke
REM     BOOKING_SLUG   - a seeded business's public booking slug (optional)
REM     EXPECT_PROD    - 'true' to assert /openapi.json is 404 (prod backend)
REM
REM  newman: if not installed globally, this uses `npx -y newman`.
REM ============================================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if "%BASE_URL%"==""      set "BASE_URL=http://localhost:8000"
if "%EXPECT_PROD%"==""   set "EXPECT_PROD=false"

echo Running newman against %BASE_URL% ...

npx -y newman run bizzup.postman_collection.json ^
  -e ci.postman_environment.json ^
  --env-var "baseUrl=%BASE_URL%" ^
  --env-var "gatewayToken=%GATEWAY_TOKEN%" ^
  --env-var "sessionCookie=%SESSION_COOKIE%" ^
  --env-var "bookingSlug=%BOOKING_SLUG%" ^
  --env-var "expectProdHardening=%EXPECT_PROD%" ^
  --reporters cli

set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo newman FAILED with exit code %RC% — deploy should be blocked.
  exit /b %RC%
)
echo.
echo newman PASSED.
exit /b 0
