// AccessibilityWidget — a floating, always-available accessibility menu.
//
// A round button pinned to the top start-corner opens a small panel with five
// toggles (high contrast, large text, underline links, focus highlight, stop
// animations). Each toggle applies instantly and persists via
// useA11yPreferences. All user-facing text comes from the `accessibility` i18n
// namespace; panel direction follows the active language. Mounted once in
// App.tsx so it appears on every public and protected page.

import { useEffect, useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useA11yPreferences, type PreferenceKey } from '../lib/useA11yPreferences'

// Order + translation keys for the five option rows.
const OPTIONS: { key: PreferenceKey; labelKey: string; descKey: string }[] = [
  { key: 'highContrast', labelKey: 'high_contrast', descKey: 'high_contrast_desc' },
  { key: 'largeText', labelKey: 'large_text', descKey: 'large_text_desc' },
  { key: 'underlineLinks', labelKey: 'underline_links', descKey: 'underline_links_desc' },
  { key: 'focusHighlight', labelKey: 'focus_highlight', descKey: 'focus_highlight_desc' },
  { key: 'stopAnimations', labelKey: 'stop_animations', descKey: 'stop_animations_desc' },
]

// Standard "accessibility person" glyph (~24px), centered in the button.
function AccessibilityIcon() {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="12" cy="4" r="2" />
      <path d="M21 9c0 .55-.45 1-1 1h-3.5v11c0 .55-.45 1-1 1s-1-.45-1-1v-5h-2v5c0 .55-.45 1-1 1s-1-.45-1-1V10H6c-.55 0-1-.45-1-1s.45-1 1-1h14c.55 0 1 .45 1 1z" />
    </svg>
  )
}

export default function AccessibilityWidget() {
  const { t, i18n } = useTranslation('accessibility')
  const { prefs, toggle, reset } = useA11yPreferences()
  const [open, setOpen] = useState(false)

  const containerRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const rowIdPrefix = useId()

  // Panel direction follows the active language (LTR for English, else RTL).
  const dir = i18n.language?.startsWith('en') ? 'ltr' : 'rtl'

  // The button reads "active" (inverted fill) when the panel is open OR any
  // preference is on.
  const anyOn = Object.values(prefs).some(Boolean)
  const active = open || anyOn

  // Esc closes the panel; click outside closes the panel. Neither resets prefs.
  useEffect(() => {
    if (!open) return

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    function onPointerDown(e: PointerEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }

    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('pointerdown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('pointerdown', onPointerDown)
    }
  }, [open])

  // Start corner by direction: left in RTL (Hebrew), right in LTR (English).
  const sidePosition = dir === 'rtl' ? 'left-4' : 'right-4'

  return (
    <div ref={containerRef} className={`fixed top-20 ${sidePosition} z-50`} dir={dir}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={t('button_aria')}
        title={t('button_title')}
        aria-expanded={open}
        className={`flex h-14 w-14 items-center justify-center rounded-full shadow-xl transition focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand ${
          active
            ? 'bg-brand text-white hover:bg-brand-dark'
            : 'bg-white text-brand hover:bg-slate-100'
        }`}
      >
        <AccessibilityIcon />
      </button>

      {open && (
        <div
          role="dialog"
          aria-labelledby={titleId}
          dir={dir}
          className="mt-3 w-72 rounded-xl border border-slate-200 bg-white p-4 shadow-2xl"
        >
          {/* Header: title + close button */}
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 id={titleId} className="text-base font-semibold text-slate-900">
              {t('panel_title')}
            </h2>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label={t('close_aria')}
              className="flex h-8 w-8 items-center justify-center rounded-md text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
            >
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                aria-hidden="true"
                focusable="false"
              >
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>

          {/* Five option rows */}
          <ul className="space-y-3">
            {OPTIONS.map(({ key, labelKey, descKey }) => {
              const descId = `${rowIdPrefix}-${key}-desc`
              return (
                <li key={key}>
                  <label className="flex cursor-pointer items-center justify-between gap-3">
                    <span className="text-sm font-medium text-slate-800">
                      {t(labelKey)}
                    </span>
                    <input
                      type="checkbox"
                      checked={prefs[key]}
                      onChange={() => toggle(key)}
                      aria-describedby={descId}
                      className="h-5 w-5 flex-shrink-0 rounded border-slate-300 text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                    />
                  </label>
                  <p id={descId} className="mt-0.5 text-xs text-slate-500">
                    {t(descKey)}
                  </p>
                </li>
              )
            })}
          </ul>

          {/* Footer: divider + full-width reset */}
          <hr className="my-3 border-slate-200" />
          <button
            type="button"
            onClick={reset}
            className="w-full rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-800 transition hover:bg-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            {t('reset')}
          </button>
        </div>
      )}
    </div>
  )
}
