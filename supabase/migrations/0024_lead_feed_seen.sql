-- מיגרציה 0024: עמודת feed_seen_at ללידים (החלטה 0022)
-- מטרה: לאפשר לבעל העסק לסמן התראה כ"נקראה" מבלי למחוק אותה מה-DB.
-- עמודה nullable: NULL = טרם נקראה, ערך = timestamp הסימון.
-- idempotent — בטוח להריץ כפול.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS feed_seen_at TIMESTAMPTZ;
