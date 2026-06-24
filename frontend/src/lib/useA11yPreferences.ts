// useA11yPreferences — runtime state + persistence for the accessibility widget.
//
// Five independent boolean toggles. State lives in React; it is mirrored to
// localStorage (survives a browser restart) and to classes on <body>/<html>
// (so the matching injected CSS applies). The effect CSS is injected into <head>
// exactly once. Nothing here touches the network, tenant data, or PII — it is
// entirely client-side.

import { useCallback, useEffect, useState } from 'react'

export type Preferences = {
  highContrast: boolean
  largeText: boolean
  underlineLinks: boolean
  focusHighlight: boolean
  stopAnimations: boolean
}

export type PreferenceKey = keyof Preferences

const STORAGE_KEY = 'accessibility-preferences'
const STYLE_ID = 'a11y-style'

const DEFAULT_PREFS: Preferences = {
  highContrast: false,
  largeText: false,
  underlineLinks: false,
  focusHighlight: false,
  stopAnimations: false,
}

// Each preference maps to one class + the element it belongs on. Large-text goes
// on <html> (so the root font-size scales everything); the rest go on <body>.
type ClassTarget = 'html' | 'body'
const CLASS_MAP: Record<PreferenceKey, { className: string; target: ClassTarget }> = {
  highContrast: { className: 'a11y-high-contrast', target: 'body' },
  largeText: { className: 'a11y-large-text', target: 'html' },
  underlineLinks: { className: 'a11y-underline-links', target: 'body' },
  focusHighlight: { className: 'a11y-focus-highlight', target: 'body' },
  stopAnimations: { className: 'a11y-reduce-motion', target: 'body' },
}

// The effect CSS. Not Tailwind-dependent, so it is injected as a raw <style>.
// The brand color literal (#128C7E) matches the `brand` design token.
const A11Y_CSS = `
body.a11y-high-contrast {
  filter: contrast(150%) brightness(1.1);
}
body.a11y-high-contrast * {
  text-shadow: none !important;
  box-shadow: none !important;
}
html.a11y-large-text {
  font-size: 120%;
  line-height: 1.6;
}
body.a11y-underline-links a {
  text-decoration: underline !important;
}
body.a11y-focus-highlight *:focus {
  outline: 3px solid #128C7E !important;
  outline-offset: 2px !important;
}
body.a11y-reduce-motion *,
body.a11y-reduce-motion *::before,
body.a11y-reduce-motion *::after {
  animation-duration: 0.01ms !important;
  animation-iteration-count: 1 !important;
  transition-duration: 0.01ms !important;
  scroll-behavior: auto !important;
}
`

// Inject the effect stylesheet once. Guarded by id so repeated calls (e.g. from
// React StrictMode double-mounts) are no-ops.
function ensureStyleInjected(): void {
  if (typeof document === 'undefined') return
  if (document.getElementById(STYLE_ID)) return
  const style = document.createElement('style')
  style.id = STYLE_ID
  style.textContent = A11Y_CSS
  document.head.appendChild(style)
}

// Add/remove every preference class to match the given state.
function applyClasses(prefs: Preferences): void {
  if (typeof document === 'undefined') return
  ;(Object.keys(CLASS_MAP) as PreferenceKey[]).forEach((key) => {
    const { className, target } = CLASS_MAP[key]
    const el = target === 'html' ? document.documentElement : document.body
    el.classList.toggle(className, prefs[key])
  })
}

// Read + validate localStorage. Bad/partial JSON falls back to defaults.
function readStored(): Preferences {
  if (typeof window === 'undefined') return { ...DEFAULT_PREFS }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_PREFS }
    const parsed = JSON.parse(raw) as Partial<Record<PreferenceKey, unknown>>
    const next: Preferences = { ...DEFAULT_PREFS }
    ;(Object.keys(DEFAULT_PREFS) as PreferenceKey[]).forEach((key) => {
      if (typeof parsed[key] === 'boolean') next[key] = parsed[key] as boolean
    })
    return next
  } catch {
    return { ...DEFAULT_PREFS }
  }
}

export function useA11yPreferences() {
  const [prefs, setPrefs] = useState<Preferences>(DEFAULT_PREFS)

  // On mount: inject CSS once, load stored prefs, apply their classes.
  useEffect(() => {
    ensureStyleInjected()
    const stored = readStored()
    setPrefs(stored)
    applyClasses(stored)
  }, [])

  const toggle = useCallback((key: PreferenceKey) => {
    setPrefs((prev) => {
      const next = { ...prev, [key]: !prev[key] }
      applyClasses(next)
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      } catch {
        // localStorage may be unavailable (private mode); preferences still
        // apply for the current session.
      }
      return next
    })
  }, [])

  const reset = useCallback(() => {
    setPrefs(DEFAULT_PREFS)
    applyClasses(DEFAULT_PREFS)
    try {
      window.localStorage.removeItem(STORAGE_KEY)
    } catch {
      // ignore — nothing to clean up if storage is unavailable
    }
  }, [])

  return { prefs, toggle, reset }
}
