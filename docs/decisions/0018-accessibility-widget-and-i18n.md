# 0018 — Floating Accessibility Widget + i18n foundation

> Status: **approved, building** · Date: 2026-06-24 · Owner: Omer
> Israeli AA target (ת"י 5568 / WCAG 2.1 AA). Self-contained frontend feature, no backend/DB.

## The story (plain language)
A visitor opens a business site. Top corner shows a round "accessibility person" icon. They click —
a small panel opens with 5 toggles: high contrast, large text, underline links, focus highlight,
stop animations. Toggling one applies instantly. The choice survives a browser restart (localStorage).
"Reset" clears everything and wipes the saved state.

## Decisions locked
1. **i18n: install a real library** (`i18next` + `react-i18next`). Set up the foundation
   (`src/i18n/index.ts`, `he` + `en` resources, language from `document.documentElement.lang`,
   `fallbackLng: 'he'`), and make the accessibility widget its first consumer.
   - **Scope guard:** we do **NOT** migrate the hundreds of existing inline-Hebrew strings now, and we
     do **NOT** add a visible language switcher yet (site is Hebrew-only in practice). The foundation
     is ready for incremental, page-by-page adoption later.
2. **Two agents** — `bizzup-frontend-builder` (build) → `bizzup-test-runner` (QA + a11y, read-only).
   No data agent (no migration), no backend agent (no endpoint).
3. **Colors = project design tokens only** — focus ring / active state use `brand` (`#128C7E`) from
   `tailwind.config.js`, matching the existing `:focus-visible { ring-brand }` in `index.css`. No
   hand-picked colors.

## Architecture (what moves where)
| What | Where | Note |
|---|---|---|
| 5 boolean prefs | React `useState` | live runtime state |
| Persistence | `localStorage["accessibility-preferences"]` | load on mount, write on change |
| Effect application | classes on `<body>`/`<html>` | e.g. `a11y-large-text` |
| Effect CSS | one `<style>` block injected into `<head>` once | not Tailwind-dependent |
| i18n init | `src/i18n/index.ts`, imported in `main.tsx` | `accessibility` namespace |
| Mount | `App.tsx`, beside `<Routes>` inside `<AuthProvider>` | shows on every page |

**Data shape:** `{ highContrast, largeText, underlineLinks, focusHighlight, stopAnimations }` (all `boolean`).
**Body/html classes:** `a11y-high-contrast`, `a11y-large-text`, `a11y-underline-links`,
`a11y-focus-highlight`, `a11y-reduce-motion`.

## The 5 effects
1. **High contrast** — `filter: contrast(150%) brightness(1.1)` on body; kill text/box-shadow.
2. **Large text** — `font-size: ~120%` on html + `line-height: 1.6`.
3. **Underline links** — `text-decoration: underline` on all `<a>`.
4. **Focus highlight** — `3px` outline on `*:focus` (theme color) + `outline-offset: 2px`.
5. **Stop animations** — animation/transition → ~0ms (reduced motion).

## Flow / logic
```
mount → read localStorage → apply matching classes if present
click button → toggle open/closed (aria-expanded)
toggle option → update state → add/remove class → write localStorage
click "reset" → all off → remove every class → delete localStorage
Esc / click outside → close panel (does NOT reset settings)
```
Button "active" state (inverted fill) = panel open **or** ≥1 option on.

## The 10 goals
1. i18next foundation (`src/i18n/index.ts`) + `accessibility` namespace (he/en), imported in `main.tsx`.
2. `useA11yPreferences` hook — state + localStorage load/save.
3. Inject the single `<style>` block into `<head>` once (idempotent).
4. Add/remove body/html classes from state.
5. Floating button — 56px (w-14 h-14), 4px focus ring, active/neutral states, ~24px SVG icon centered.
6. Direction-aware position — start corner by `dir` (left in RTL).
7. Panel — w-72, header + X close, list of 5 rows (label + toggle + description).
8. Full a11y — `role="dialog"`, `aria-labelledby`, `aria-expanded`, `aria-describedby`, `aria-label`, `title`.
9. Full-width "reset" button + divider.
10. Mount in `App.tsx` + Esc/click-outside close + passes ESLint `jsx-a11y`.

## Agents & workflow
```
Agent A (frontend-builder: widget + hook + i18n foundation)
   └─► Agent B (test-runner: QA + a11y review, read-only)
          └─► main loop verifies in preview, fixes until green
                 └─► checkpoint (commit)
```
Serial because QA must read the built code; no backend phase exists. Visual proof (preview
screenshots) done by the main loop.

## Security & isolation
- No tenant data, no `business_id`, no secrets, no PII, no logging. localStorage only (client-side).
- Sacred read-only folders (`last_bo`, `qr_wa_scanner`) untouched.
- New npm deps: `i18next`, `react-i18next` (approved).

## i18n strings (`accessibility` namespace)
| key | he | en |
|---|---|---|
| button_aria | פתח תפריט נגישות | Open accessibility menu |
| button_title | נגישות | Accessibility |
| panel_title | הגדרות נגישות | Accessibility settings |
| close_aria | סגור תפריט נגישות | Close accessibility menu |
| high_contrast | ניגודיות גבוהה | High contrast |
| high_contrast_desc | הגברת הניגודיות לקריאה טובה יותר | Increase contrast for better readability |
| large_text | טקסט גדול | Large text |
| large_text_desc | הגדלת גודל הטקסט | Increase the text size |
| underline_links | קו תחתון לקישורים | Underline links |
| underline_links_desc | הוספת קו תחתון לכל הקישורים | Add an underline to all links |
| focus_highlight | הדגשת פוקוס | Focus highlight |
| focus_highlight_desc | הדגשה ברורה יותר של רכיבים בפוקוס | Make focused elements clearly visible |
| stop_animations | הפסקת אנימציות | Stop all animations and transitions |
| stop_animations_desc | הפסקת כל האנימציות והמעברים | Stop all animations and transitions |
| reset | איפוס הגדרות נגישות | Reset accessibility settings |
