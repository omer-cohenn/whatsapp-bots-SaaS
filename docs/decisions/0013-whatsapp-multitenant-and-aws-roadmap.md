# 0013 — WhatsApp multi-tenant (M6) + AWS deploy roadmap (beginner path)

> סטטוס: **תוכנית מאושרת — לא בבנייה עדיין** (Omer בחר "רק לתכנן"). תאריך: 2026-06-21.
> מסמך הבנה + רואד‑מאפ. הביצוע בהמשך, מסע‑מסע, בהדרכה צמודה.

## למה
לפני בניית M6, מיפינו (סוכני Explore) איך החיבור לוואטסאפ עובד, איך הוא ייעשה רב‑דיירי, ואיך מעלים את כל
המערכת ל‑AWS — עבור Omer שאין לו רקע בענן.

## איך וואטסאפ עובד היום (spike)
- שער Node + **Baileys** (QR/"מכשירים מקושרים", לא Meta Cloud API — החלטה 0001). **חד‑דייר**; מפתחות כקבצים
  לא‑מוצפנים ב‑`gateway/auth/`.
- נכנס → `POST /webhook/whatsapp` (+`X-Gateway-Token`) → backend מקבל+מאמת אבל **לא מריץ בוט עדיין**.
- מוכן כבר: `whatsapp_connections` (`gateway_account_id ↔ business_id`), `whatsapp_credentials` (תכשיט‑כתר
  מוצפן, gateway_role בלבד), תורי outbox (`conv:{}:{}:outbox`, `booking:outbox:{}`), דגל `is_published`.

## M6 — יעדים (רב‑דיירי)
1. סוקט נפרד לכל עסק (מפה לפי `gateway_account_id`).
2. onboarding/QR דרך האפליקציה בערוץ מאובטח; להסיר/לאבטח `/qr`,`/inbox`,`/send`.
3. מפתחות מוצפנים במסד (KEK) במקום דיסק; rehydrate בהפעלה.
4. ניתוב נכנס `gateway_account_id`→`business_id`→`run_turn` — **רק אם `is_published`**.
5. ריקון תורי ה‑outbox ושליחה אמיתית דרך השער.
6. חוסן: אידמפוטנטיות `message_id`, לא‑טקסט, reconnect+backoff, rate‑limit (סיכון חסימה — Baileys לא רשמי).

## AWS — החלטות נעולות (Q&A)
- **שרת אחד פשוט** (Lightsail) שמריץ את אותו `docker-compose` + **Caddy** ל‑HTTPS אוטומטי. (לא Fargate/ALB/KMS —
  זו הארכיטקטורה המנוהלת ב‑`roadmap-parts/devops-aws.md`, שלב עתידי לסקייל.)
- **תקציב מינימלי** ~$15–40/חודש; התראת תקציב ביום הראשון; לא מקימים משאב בתשלום בלי אישור מפורש.
- **אזור** אירופה (eu-central-1/eu-west-1).
- **אין דומיין** — נקנה (~$10–15/שנה) ונחבר רשומת A ל‑Static IP.

## רואד‑מאפ AWS (שלבים)
0. חשבון AWS + התראת תקציב + בחירת אזור + קניית דומיין (חינם חוץ מהדומיין).
1. Lightsail instance (Ubuntu 2GB ~$12) + Static IP + firewall (רק 80/443) + Docker.
2. דומיין → A record → Static IP; Caddy ל‑HTTPS (מחליף ngrok).
3. git clone + `.env` עם סודות אמיתיים (600); כתובות production ל‑Google/PUBLIC_BASE_URL; `docker compose up`.
4. גיבוי DB יומי (`pg_dump` + Lightsail snapshots ~$2); הסרת כלי dev של השער.
5. עלייה לאוויר ובדיקה מקצה‑לקצה (login, וואטסאפ, הזמנה, ליד).

## עלות צפויה
~$15–20/חודש (Lightsail 2GB + snapshots + דומיין). עד ~$25–40 אם 4GB.

## מה הלאה
שני מסעות נפרדים, צעד‑צעד: (1) M6 מקומית, (2) AWS שרת‑אחד. לא בונים עד אישור Omer לכל מסע.
הרואד‑מאפ המנוהל המלא (סקייל עתידי): `docs/spec/roadmap-parts/devops-aws.md`.
