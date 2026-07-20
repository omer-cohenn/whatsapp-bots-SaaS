# 0025 — עלייה לאוויר: AWS Lightsail + Caddy + דומיין + auto-deploy

> סטטוס: **done · חי בפרודקשן** · תאריך: 2026-07-17 · Owner: Omer
> Commits: `8f37108`, `9755991`, `4fcf3f9`, `8ce0a0f`, `f55fd46`
> מממש את שלבי ה-AWS מ-[`0013-whatsapp-multitenant-and-aws-roadmap.md`](0013-whatsapp-multitenant-and-aws-roadmap.md),
> על גבי תשתית הפרודקשן מ-[`0024-security-hardening-and-qa-gate.md`](0024-security-hardening-and-qa-gate.md).
> **Runbook תפעולי:** [`../DEPLOY.md`](../DEPLOY.md).

## 🟢 המערכת חיה: **https://botik-dev.duckdns.org**

## מה הוקם

### השרת
- **AWS Lightsail**, אזור **פרנקפורט** (eu-central-1), **Ubuntu 24.04**, מסלול **1GB**.
- נוסף **swapfile של 2GB** — 1GB RAM לבדו לא הספיק ל-`docker compose up --build`
  (ה-build של ה-frontend נהרג ב-OOM).
- **Static IP: `35.157.230.101`**.
- **Firewall של Lightsail: רק 22 / 80 / 443** פתוחים.
- גיבוי: **snapshots אוטומטיים של Lightsail**.

### הדומיין וה-HTTPS
- דומיין חינמי **DuckDNS**: `botik-dev.duckdns.org` → מצביע ל-Static IP.
- **Caddy** מסיים HTTPS אוטומטית (Let's Encrypt), לפי `PUBLIC_DOMAIN` ב-`infra/.env`.
- **Google OAuth**: מסך ההסכמה **פורסם** (published, לא Testing) ו-redirect URIs
  מצביעים לדומיין.

### הפעלה
```bash
docker compose --env-file infra/.env \
  -f infra/docker-compose.yml -f infra/docker-compose.prod.yml up -d --build
```
על השרת זה עטוף ב-`/root/deploy.sh` (git pull → compose up --build → prune).

### Auto-deploy
`.github/workflows/deploy.yml` — כל push ל-`main` עושה SSH לשרת ומריץ `~/deploy.sh`,
מסודר ב-concurrency group כדי ששני deploys לא ירוצו במקביל.
Secrets: `DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_SSH_KEY`.

> ⚠️ **מצב אמיתי היום:** ה-Action **נכשל על ה-secret של מפתח ה-SSH**
> (ראו `f55fd46` — ניסיון retrigger). **הדרך העובדת כרגע היא ידנית:**
> `ssh` לשרת → `~/deploy.sh`. תיקון המפתח פתוח ב-STATUS.

## ארבעה תיקונים שנלמדו תוך כדי ההעלאה

| # | Commit | הבעיה | התיקון |
|---|---|---|---|
| a | `8f37108` | ה-override של prod הסיר את ה-bind-mount מ-backend/frontend אבל **לא מה-gateway** — קוד ה-host האפיל על ה-`node_modules` של ה-image, והשער קרס ב-`Cannot find module 'express'` | `volumes: !override []` גם ל-gateway |
| b | `9755991` | `frontend/Dockerfile.prod` העתיק `index.html`/configs/`src` אבל **לא `public/`** — Vite לא פלט assets, הלוגו וה-favicon חסרו וכל בקשה נפלה ל-`index.html` | `COPY public/` לפני ה-build |
| c | — | **`PUBLIC_DOMAIN` ריק שובר את ה-Caddyfile.** הסמנטיקה: `PUBLIC_DOMAIN=:80` = HTTP בלי דומיין; דומיין אמיתי = HTTPS אוטומטי | לקבוע ערך מפורש ב-`infra/.env` |
| d | `4fcf3f9` | תור AI (Gemini) לוקח ~10 שניות בשרת קטן; ה-proxy קטע תשובה איטית-אך-תקינה והמשתמש ראה "שליחה נכשלה" | `response_header_timeout` + `read_timeout` = **120s** ל-backend ב-`Caddyfile` |

## איך מעלים עדכון

1. `git push` ל-`main`.
2. **הדרך העובדת:** SSH לשרת כ-root → `~/deploy.sh`
   (עושה `git pull`, `docker compose ... up -d --build`, ואז `docker system prune`).
3. **כשה-Action יתוקן:** ה-push לבדו יריץ את אותו `~/deploy.sh` אוטומטית.
4. אימות: לפתוח את `https://botik-dev.duckdns.org` + `docker compose ... ps`.

## Consequences
- כתובות פרודקשן (Google OAuth, `PUBLIC_BASE_URL`) קשורות עכשיו ל-DuckDNS —
  **מעבר לדומיין בתשלום ידרוש עדכון בשני המקומות** (Google Console + `infra/.env`).
- `infra/.env` על השרת הוא היחיד שמחזיק סודות אמיתיים והוא **לא ב-git** — אין ממנו גיבוי
  מלבד ה-snapshot של Lightsail.
- 1GB + swap עובד אבל צפוף; build כבד עלול להאט. שדרוג ל-2GB הוא המסלול אם יצטופף.
