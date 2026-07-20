# SERVER — המדריך המלא לשרת 🖥️

> **אין במסמך הזה שום סוד.** לא סיסמאות, לא מפתחות, לא תוכן `.env`.
> ספר ההפעלה הקצר: [`DEPLOY.md`](DEPLOY.md) · תמונת הרשת:
> [`security/production-networking.md`](security/production-networking.md).
> עודכן: 2026-07-20.

---

## חלק 1 — איך נכנסים לשרת

### מה צריך להחזיק

| מה | איפה | הערה |
|---|---|---|
| מפתח ה-SSH | `C:\Users\<אתה>\.ssh\botik.pem` | **הקובץ הזה הוא המפתח לבית.** לא לשלוח, לא לצלם, לא להעלות לגיט. |
| כתובת השרת | `botik-dev.duckdns.org` | או ה-IP הקבוע `35.157.230.101` |
| שם המשתמש | `ubuntu` | ⚠️ **לא `root`** |

### הפקודה

```bash
ssh -i ~/.ssh/botik.pem ubuntu@botik-dev.duckdns.org
```

> **הטעות הכי נפוצה:** לנסות `ssh root@...`. השרת יסרב ויענה
> `Please login as the user "ubuntu" rather than the user "root"`.
> זו לא תקלה — AWS חוסמת כניסת root ישירה בכוונה. נכנסים כ-`ubuntu` ומשתמשים
> ב-`sudo` כשצריך הרשאות.

### למה כמעט כל פקודה כאן מתחילה ב-`sudo`

האפליקציה כולה יושבת תחת `/root/`, ולתיקייה הזו יש הרשאות `700` — כלומר **רק root
יכול בכלל להיכנס אליה**. המשתמש `ubuntu` מריץ פקודות עליה דרך `sudo`:

```bash
sudo ls /root/ManBuizz          # ✅ עובד
ls /root/ManBuizz               # ❌ Permission denied
cd /root/ManBuizz               # ❌ Permission denied — גם עם sudo אחר כך
```

**חשוב:** `cd /root/...` **לא יעבוד** גם אם תוסיף `sudo` אחר כך, כי ה-`cd` עצמו
רץ בלי הרשאות. במקום זה מריצים כל פקודה עם `sudo` מלפנים, או נכנסים ל-shell של root:

```bash
sudo -i        # מכאן אתה root ויכול לעשות cd רגיל
cd ~/ManBuizz
```

### אם החיבור מתנתק כל הזמן

```bash
ssh -i ~/.ssh/botik.pem -o ServerAliveInterval=30 ubuntu@botik-dev.duckdns.org
```

---

## חלק 2 — מה יש על השרת

### מפת הקבצים

```
/root/
├── deploy.sh              ← סקריפט הפריסה. זה מה שמריצים כדי לעדכן.
└── ManBuizz/              ← הרפו. עותק מלא של הקוד מגיטהאב.
    ├── backend/           Python · FastAPI
    ├── frontend/          React · נבנה ל-HTML/JS סטטי
    ├── gateway/           Node · חיבור הוואטסאפ (Baileys)
    ├── supabase/          מיגרציות SQL
    ├── docs/              התיעוד הזה
    └── infra/             ← כל מה שמפעיל את המערכת
        ├── .env                    🔴 כל הסודות. git-ignored. אין לו גיבוי חוץ מ-snapshot.
        ├── .env.example            תבנית בלי ערכים (כן בגיט)
        ├── Caddyfile               הגדרות ה-proxy וה-HTTPS
        ├── docker-compose.yml      הגדרת השירותים (בסיס)
        └── docker-compose.prod.yml שכבת הפרודקשן — סוגרת פורטים
```

### הנתונים עצמם — לא בקבצים, ב-Docker volumes

זו נקודה שמבלבלת: **מחיקת התיקייה `/root/ManBuizz` לא תמחק את מסד הנתונים.**
המידע חי ב-volumes נפרדים:

| Volume | מה בפנים |
|---|---|
| `bizz_up_pg_data` | 🔴 **כל המידע** — עסקים, לידים, שיחות, פוליסות הצפנה |
| `bizz_up_caddy_data` | תעודות ה-HTTPS (מתחדשות לבד) |
| `bizz_up_caddy_config` | מצב פנימי של Caddy |

הקבצים שלקוחות מעלים (תמונות/PDF) **לא** על השרת — הם ב-Cloudflare R2, מוצפנים.

---

## חלק 3 — איך זה עובד

### ששת השירותים

```
                    האינטרנט
                        │
                   80 / 443  ← הדלת היחידה שפתוחה החוצה
                        ▼
              ┌──────────────────┐
              │  reverse-proxy   │  Caddy · HTTPS אוטומטי
              └────────┬─────────┘
                       │
        ┌──────────────┴───────────────┐
        ▼                              ▼
   /api/*  /auth/*                  כל השאר
    backend:8000                   frontend:80
        │
        ├── postgres:5432   מסד הנתונים
        ├── redis:6379      שיחות חיות
        └── gateway:3000    וואטסאפ
```

### עיקרון האבטחה המרכזי

**רק ה-reverse-proxy מפרסם פורטים החוצה.** אומת בפועל:

```
bizz_up-reverse-proxy-1   0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp   ← פומבי
bizz_up-backend-1         8000/tcp                                    ← פנימי בלבד
bizz_up-postgres-1        5432/tcp                                    ← פנימי בלבד
bizz_up-redis-1           6379/tcp                                    ← פנימי בלבד
bizz_up-gateway-1         3000/tcp                                    ← פנימי בלבד
```

השורות בלי `0.0.0.0:` אינן נגישות מהאינטרנט — הן קיימות רק ברשת הפנימית של Docker.
בנוסף, ה-firewall של Lightsail פותח **רק 22/80/443**. שתי שכבות.

`/webhook/*`, `/internal/*`, `/docs`, `/openapi.json` **לא** מנותבים דרך ה-proxy.

---

## חלק 4 — פעולות יומיום

### לפרוס עדכון

```bash
# 1) במחשב שלך
git push origin main

# 2) על השרת
ssh -i ~/.ssh/botik.pem ubuntu@botik-dev.duckdns.org
sudo bash /root/deploy.sh
```

`deploy.sh` עושה: `git pull` → `docker compose ... up -d --build` → `docker image prune -f`.

> **⚠️ תלות חדשה = חובה rebuild.** אם הוספת חבילה (`openpyxl`, `boto3`…),
> חייבים `--build`. `deploy.sh` עושה את זה. **restart בלבד לא מספיק** — הקונטיינר
> יעלה עם האימג' הישן והקוד ייפול. זה נשך אותנו כבר פעמיים (M16, M17).

### לבדוק שהכול חי

```bash
sudo docker ps --format '{{.Names}}\t{{.Status}}'      # כולם צריכים healthy
sudo docker logs bizz_up-backend-1 --tail 50           # לוגים
sudo docker logs -f bizz_up-gateway-1                  # לוגים חיים (Ctrl+C ליציאה)
```

מבחוץ:
```bash
curl -o /dev/null -w "%{http_code}\n" https://botik-dev.duckdns.org/
```

### להריץ פקודה בתוך שירות

```bash
sudo docker exec bizz_up-backend-1 python -c "import openpyxl; print(openpyxl.__version__)"
sudo docker exec bizz_up-postgres-1 psql -U bizzup -d bizzup -c "SELECT count(*) FROM leads;"
```

### להפעיל מחדש שירות בודד

```bash
sudo docker restart bizz_up-backend-1
```

---

## חלק 5 — מגבלות וסכנות אמיתיות

### ⚠️ הזיכרון צפוף — אבל לא מהסיבה שנדמה

```
Mem:  911Mi total · 730Mi בשימוש · 62Mi פנוי · 180Mi available
Swap: 2.0Gi        · 466Mi בשימוש
```

**זה לא נובע ממספר הבוטים.** לאן הזיכרון באמת הולך (נמדד):

| תהליך | RAM |
|---|---|
| `dockerd` | **123 MB** ← הצרכן הגדול ביותר |
| `backend` worker #1 | 88 MB |
| `gateway` (node) | 83 MB |
| `backend` worker #2 | 30 MB |
| `containerd` | 28 MB |
| `multipathd` (של אובונטו) | 26 MB |
| תהליכי `postgres` | ~70 MB |

**התשתית צורכת יותר מהאפליקציה** — ‏`dockerd`+`containerd` לבדם 151MB, לפני שורת
קוד אחת. המסקנה המעשית: זהו **baseline קבוע**. בוט שני יוסיף סשן וואטסאפ, לא עוד
מאות מגהבייט. "יש רק בוט אחד ובכל זאת הזיכרון מלא" אינו סתירה — הם לא קשורים.

`available` הוא 180MB ועוד 313MB הם buff/cache שהמערכת תשחרר בלחץ — **צפוף, לא קריטי.**

**סימן ללחץ:** ה-`reverse-proxy` מסומן `unhealthy` כבר 3+ ימים עם
`wget: fork: Resource temporarily unavailable` — הקונטיינר לא מצליח ליצור תהליך
לבדיקת הבריאות. **האתר עובד** (מחזיר 200), כלומר זו בדיקת הבריאות שנכשלת, לא
השירות. עדיין: זה מחסור במשאבים, לא הגדרה שגויה.

**המנוף אם צריך אוויר:** יש **2 gunicorn workers** (`WEB_CONCURRENCY`,
ברירת מחדל ב-`backend/Dockerfile`). ירידה ל-1 משחררת ~30MB, ולתנועה נמוכה worker
אחד מספיק. לא שונה — החלטה פתוחה.

מכאן נובע גם: **build כבד עלול להיות איטי מאוד**, ואם תהליך נהרג פתאום — זה כמעט
תמיד OOM.

### 🔴 ל-`.env` אין גיבוי

`infra/.env` הוא **git-ignored** בכוונה. אם הוא נמחק, **הסודות אבודים** — כולל
מפתחות ההצפנה. בלי `PII_DATA_KEY` **כל הלידים במסד הופכים לג'יבריש בלתי הפיך.**
הגיבוי היחיד הוא snapshot של Lightsail.

### ✅ ניקוי סודות שבוצע (2026-07-20)

1. **`infra/.env.bak.<ts>` נמחק** — עותק ישן של `.env` עם סודות בפנים, שריד
   מהעבודה על המפתחות. נמחק ב-`shred` (דריסת הבייטים), לא ב-`rm`.
   **מה אומת לפני המחיקה:** אפס אזכורים בקוד ובשרת · compose קורא רק `infra/.env` ·
   **27 מפתחות בשני הקבצים, אפס מפתחות ייחודיים לגיבוי** (הושוו שמות מפתחות בלבד,
   לא ערכים). הבדיקה האחרונה היא הקריטית — מפתח שחסר ב-`.env` היה שובר את
   **הדיפלוי הבא** בלי להשפיע על הריצה הנוכחית.
   **אומת אחרי:** `docker compose config -q` תקין, האתר 200, כל השירותים חיים.
2. **הרשאות `.env` הודקו מ-`644` ל-`600`** — כעת רק `root` קורא. (גם קודם לא היה
   חשוף בפועל, כי `/root` הוא `700`; זו הידוק לעומק ולא תיקון פרצה.)

> **הכלל:** בתיקייה `infra/` צריכים להיות **בדיוק שני** קבצי env — `.env` (הסודות,
> git-ignored) ו-`.env.example` (התבנית, בגיט). כל קובץ env נוסף = עותק מיותר של
> סודות, ויש למחוק אותו.

---

## חלק 6 — פתרון תקלות

| תסמין | כנראה | מה לעשות |
|---|---|---|
| `Please login as the user "ubuntu"` | ניסית `root@` | `ubuntu@` |
| `Permission denied` על `/root` | `cd` בלי הרשאות | `sudo -i` ואז `cd`, או `sudo` לפני כל פקודה |
| האתר לא נטען | proxy/DNS | `sudo docker ps`, ואז `sudo docker logs bizz_up-reverse-proxy-1` |
| Caddy בלולאת קריסה | `PUBLIC_DOMAIN` ריק | חייב ערך מפורש — `:80` או הדומיין. **ריק שובר את ה-Caddyfile** |
| שגיאה אחרי הוספת חבילה | לא היה rebuild | `sudo bash /root/deploy.sh` (עם `--build`) |
| "שגיאה בשליחת ההודעה" ב-AI | Gemini איטי | תקין עד 120s; מעבר לזה — לבדוק לוגים |
| תהליך נהרג בלי סיבה | OOM | ראה מגבלת הזיכרון למעלה |

---

## חלק 7 — מה פתוח

1. **GitHub Actions auto-deploy נכשל** על ה-secret ‏`DEPLOY_SSH_KEY`. עד שיתוקן,
   `sudo bash /root/deploy.sh` ידני הוא הדרך.
2. **סודות שממתינים להחלפה:** `GOOGLE_CLIENT_SECRET`, `GEMINI_API_KEY`, וטוקן ה-R2
   (נחשף חלקית בצילום מסך).
3. **DuckDNS הוא זמני.** מעבר לדומיין בתשלום = עדכון `PUBLIC_DOMAIN` ב-`infra/.env`
   **וגם** ה-redirect URIs ב-Google Cloud Console. שני המקומות, אחרת ההתחברות תישבר.
4. **הזיכרון** — ראה חלק 5.
