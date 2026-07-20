# DEPLOY — ספר הפעלה לפרודקשן 🚀

> המערכת חיה ב-**https://botik-dev.duckdns.org** (מאז 2026-07-17).
> ההחלטה המלאה: [`decisions/0025-production-deployment.md`](decisions/0025-production-deployment.md).
> תמונת הרשת המפורטת: [`security/production-networking.md`](security/production-networking.md).
> **המדריך המלא לשרת** (גישה, מפת קבצים, איך זה עובד): [`SERVER.md`](SERVER.md).
> **אין במסמך הזה שום סוד.** כל הסודות יושבים ב-`infra/.env` על השרת בלבד.

## הארכיטקטורה בשורה אחת

```
אינטרנט → Lightsail (80/443) → Caddy (HTTPS אוטומטי)
                                  ├─ /api/*, /auth/*  → backend:8000
                                  └─ כל השאר          → frontend:80 (build סטטי)
        postgres · redis · gateway → רשת Docker פנימית בלבד, לא מפורסמים החוצה
```

`/webhook/*`, `/internal/*`, `/docs`, `/openapi.json` ומסלולי ה-QR של השער **לא** מנותבים
דרך ה-proxy — הם פנימיים בלבד.

## איפה הכול יושב על השרת

| מה | איפה |
|---|---|
| הרפו | `/root/ManBuizz` |
| סקריפט הפריסה | `/root/deploy.sh` |
| הסודות | `<repo>/infra/.env` — **git-ignored, לא בגיט, אין לו גיבוי מלבד snapshot** |
| התבנית של הסודות | `infra/.env.example` (כן בגיט, בלי ערכים) |
| תעודות TLS | volume של Docker (`caddy_data`) |
| גיבויים | **snapshots אוטומטיים של Lightsail** |

השרת: AWS Lightsail, פרנקפורט, Ubuntu 24.04, מסלול 1GB + **swapfile 2GB**.
Static IP `35.157.230.101`. Firewall: **רק 22/80/443**.

## איך מעלים עדכון

```bash
# 1) במחשב שלך
git push origin main

# 2) על השרת (הדרך העובדת כרגע)
ssh -i ~/.ssh/botik.pem ubuntu@botik-dev.duckdns.org
sudo bash /root/deploy.sh
```

> **המשתמש הוא `ubuntu`, לא `root`.** AWS חוסמת כניסת root ישירה ותענה
> `Please login as the user "ubuntu"`. המדריך המלא לשרת — כולל מפת הקבצים,
> ההרשאות ופתרון תקלות — ב-[`SERVER.md`](SERVER.md).

> **תלות חדשה = חובה rebuild.** `deploy.sh` כולל `--build`, אז הוא מכסה את זה;
> אבל `restart` בלבד **לא** — הקונטיינר יעלה עם האימג' הישן. נשך אותנו ב-M16 וב-M17.

`deploy.sh` עושה: `git pull` → `docker compose --env-file infra/.env -f infra/docker-compose.yml
-f infra/docker-compose.prod.yml up -d --build` → `docker system prune`.

יש גם **GitHub Action** (`.github/workflows/deploy.yml`) שאמור לעשות את זה אוטומטית בכל push
ל-`main` — כרגע **נכשל על ה-secret של מפתח ה-SSH** (`DEPLOY_SSH_KEY`). עד שיתוקן, הדרך הידנית
למעלה היא הדרך.

## `PUBLIC_DOMAIN` — שתי המשמעויות

| ערך ב-`infra/.env` | מה קורה |
|---|---|
| `PUBLIC_DOMAIN=:80` | Caddy מגיש **HTTP רגיל** בלי דומיין (מצב ללא-דומיין / TLS במעלה הזרם) |
| `PUBLIC_DOMAIN=botik-dev.duckdns.org` | Caddy מוציא תעודה **אוטומטית** ומגיש **HTTPS** ב-443 |
| **ריק** | ⚠️ **שובר את ה-Caddyfile** — תמיד לקבוע ערך מפורש |

## פקודות יומיום

כל הפקודות מהתיקייה `/root/ManBuizz`, עם אותו זוג קבצי compose:

```bash
C="docker compose --env-file infra/.env -f infra/docker-compose.yml -f infra/docker-compose.prod.yml"

$C ps                       # מצב כל השירותים
$C logs -f backend          # לוגים חיים (backend / gateway / frontend / reverse-proxy / postgres / redis)
$C logs --tail=200 gateway  # 200 השורות האחרונות
$C restart gateway          # הפעלה מחדש של שירות בודד
```

## בדיקת בריאות

- מבחוץ: לפתוח `https://botik-dev.duckdns.org` — דף הנחיתה נטען + המנעול ירוק.
- התחברות: "התחברות" → Google OAuth → נחיתה בדשבורד.
- מבפנים: `$C ps` — כל השירותים `healthy`; `$C exec backend curl -s localhost:8000/healthz`
  מאשר Postgres + Redis.
- WhatsApp: עמוד `/whatsapp` בדשבורד מראה `connected` (או QR לסריקה).

## דברים שכדאי לזכור

- **RAM צפוף** — 1GB + 2GB swap. build כבד עלול להיות איטי; אם משהו נהרג, זה כנראה OOM.
- **AI איטי זה תקין** — ה-proxy מגדיר 120s timeout ל-backend בדיוק בשביל תורי Gemini.
- **מעבר לדומיין בתשלום** ידרוש עדכון בשני מקומות: `PUBLIC_DOMAIN` ב-`infra/.env`
  ו-redirect URIs ב-Google Cloud Console.
