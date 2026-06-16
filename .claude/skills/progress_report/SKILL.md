---
name: progress_report
description: Draft a WhatsApp-ready progress update for Omer's mentor — in Hebrew, simple and lightly cynical — summarizing what was actually done on Bizz_up since the last update and the next planned steps. Use when Omer wants to update his mentor, send a status message, or asks for a "progress report / סיכום / עדכון".
---

# Skill: progress_report

Produce a **copy-paste-ready WhatsApp message** that updates Omer's mentor on the project status:
what was genuinely accomplished **since the last update**, and **what's planned next**. Match the
house style we already established with Omer.

## Optional arguments
`$ARGUMENTS` may carry hints. Honor them; otherwise use the defaults:
- length: `short` (4–6 lines) | **`full`** (default, sectioned)
- language: **`hebrew`** (default) | `english`
- tone: **`light-cynical`** (default) | `formal`
- audience: defaults to **the mentor**

## Step 1 — Find the baseline ("what was the last update?")
- Look in `docs/progress-reports/` for the most recent dated file `YYYY-MM-DD-progress.md`.
- That file is the **previous update**. Everything since then is "new".
- If the folder is missing/empty, this is the **first** report — cover the project from the start.

## Step 2 — Gather what's REALLY new since the baseline
Collect concrete, true accomplishments — never invent progress. Sources, in order:
1. The current conversation / work done in this session.
2. Decision records in `docs/decisions/` created or changed after the baseline date.
3. Changes to `docs/bugs.md`, `docs/security-issues.md`, `CLAUDE.md`, and any new agents / skills /
   folders / code.
4. If the project is a git repo: `git log` since the baseline date for real commits.
Prefer **specifics and small numbers** (files scanned, # of bugs, # of API endpoints, # of decisions)
over vague claims. If you're unsure whether something happened, ask Omer instead of guessing.

## Step 3 — Draft the message (HOUSE STYLE — important)
- **Tone:** simple, human Hebrew. Lightly cynical / humorous, but **not pompous or buzzwordy**
  ("לא מתפלצנת"). Make Omer look methodical; be honest about messy findings, but with a wink.
- **Make the real work clear** — the mentor should understand *what was actually done*, not just the
  funny bits. Lead with substance, season with humor.
- **WhatsApp formatting:** short lines, a few emojis as section markers, easy to skim. Wrap the final
  message in a ``` fenced code block ``` so it copies cleanly. Leave a placeholder for the greeting if
  the mentor's name is unknown (e.g. "היי 👋").
- **Structure** (adapt to what actually happened — drop sections that don't apply):
  1. שורת פתיחה קצרה — שם הפרויקט + שזה עדכון.
  2. 🎯 מה עשינו / הגישה — הצעדים האמיתיים מאז העדכון האחרון.
  3. 🔍 ממצאים / מספרים — נתונים קונקרטיים (אם רלוונטי).
  4. 🧭 החלטות שהתקבלו (אם היו).
  5. ➡️ השלב הבא המתוכנן.
  6. שורת סיכום קצרה וקצת צינית.

## Step 4 — Offer quick variants
After the draft, offer: shorten to a "tweet" version, add dry numbers, soften/sharpen the tone, or
switch to English.

## Step 5 — Save as the new baseline
Offer to save the draft to `docs/progress-reports/<today>-progress.md`. Saving makes it the baseline
for the **next** report, so each report only covers new ground.
- **Never guess the date** — use today's date from the session context (do not fabricate it).
- Save a clean copy: a short metadata header (date, audience, language) + the message body.

## Rules
- **Never fabricate progress.** Only report what truly happened since the baseline.
- The original folders `last_bo` and `qr_wa_scanner` are **read-only** — don't scan/modify them for
  this; rely on the `docs/`.
- Defaults: language = Hebrew, tone = light-cynical, audience = the mentor.
