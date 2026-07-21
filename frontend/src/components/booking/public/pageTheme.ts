// פלטות הצבע של העמוד העסקי (M20) — הטבלה שהבעלים בוחר ממנה והמבקר רואה.
//
// The palette table for the public business page. `PageTheme.palette` (see
// `dashboard/businessPageTypes.ts`) is just a STRING key into this table — the
// backend stores the blob without interpreting it (contract §4), so the whole
// look lives here and adding a palette needs no backend work.
//
// This module is the single source of truth for both sides: the public page
// (agent D) renders from it, and the owner wizard's palette picker reads the
// same `PAGE_PALETTES` list so the swatches can never drift from the real page.
//
// Two rules that keep a visitor from ever seeing something broken:
//   1. An absent or UNKNOWN palette key falls back to `DEFAULT_PALETTE` — the
//      owner who never opened the wizard still gets a designed page.
//   2. Light AND dark palettes are both safe now. The original build allowed only
//      light ones because `BookingFlow` rendered hardcoded white cards with slate
//      text, so a dark page made the booking form unreadable. The M20 revision
//      themed that flow off these same variables, and the public render path was
//      re-checked for hardcoded colours before the dark palettes were added — the
//      only two left are the lightbox controls (white-on-black by design, over a
//      full dark overlay) and the pre-M20 "card" layout, which the themed page
//      never uses.
//
//      So a DARK palette must set `surface` to an elevated dark, `text` to a light
//      ink, and `onPrimary` to whatever actually reads on `primary` (dark text on
//      gold, white on crimson). Getting `onPrimary` wrong is the one mistake that
//      produces an invisible button.

import type { PageTheme } from '../../../dashboard/businessPageTypes'

export type PagePalette = {
  /** Stored in `page_theme.palette`. Never change a key — it is persisted data. */
  key: string
  /** Hebrew name for the owner's picker. */
  label: string
  /** Accent: buttons, the logo halo, active borders. AA-safe on `bg`. */
  primary: string
  /** Text colour that passes AA on top of `primary`. */
  onPrimary: string
  /** Page background. May be light or dark — see the note above. */
  bg: string
  /** Card / hero surface. */
  surface: string
  /** Body text on `surface`. */
  text: string
  /** Secondary text on `surface` (AA-safe). */
  muted: string
  /** Hairline borders. */
  border: string
}

/** Corner rounding used when the owner did not override `page_theme.radius`. */
const DEFAULT_RADIUS = 22
const MIN_RADIUS = 0
const MAX_RADIUS = 40

export const PAGE_PALETTES: PagePalette[] = [
  // ---- light ---------------------------------------------------------------
  {
    key: 'leaf',
    label: 'ירוק טבעי',
    // Darkened from #639922 when the palettes were contrast-checked: white on the
    // old green measured 3.44 and the accent-vs-background only 2.83, both under
    // the AA thresholds. This is the DEFAULT palette, so every business that never
    // opens the wizard was shipping a button whose label was hard to read.
    primary: '#4f7a15',
    onPrimary: '#ffffff',
    bg: '#ece9e1',
    surface: '#ffffff',
    text: '#1b2e0c',
    muted: '#5b6b4a',
    border: '#d8e2c6',
  },
  {
    key: 'ocean',
    label: 'כחול אוקיינוס',
    primary: '#0369a1',
    onPrimary: '#ffffff',
    bg: '#eff6fb',
    surface: '#ffffff',
    text: '#0f172a',
    muted: '#51667e',
    border: '#cfe1ef',
  },
  {
    key: 'sand',
    label: 'חול וקרם',
    primary: '#a16207',
    onPrimary: '#ffffff',
    bg: '#faf7f0',
    surface: '#ffffff',
    text: '#292524',
    muted: '#78716c',
    border: '#e7e0d2',
  },
  {
    key: 'lavender',
    label: 'סגול ערפילי',
    primary: '#7c3aed',
    onPrimary: '#ffffff',
    bg: '#f5f3ff',
    surface: '#ffffff',
    text: '#2e1065',
    muted: '#5b21b6',
    border: '#ddd6fe',
  },
  {
    key: 'mono',
    label: 'שחור־לבן קלאסי',
    primary: '#1f2937',
    onPrimary: '#ffffff',
    bg: '#f4f4f5',
    surface: '#ffffff',
    text: '#111827',
    muted: '#5b6472',
    border: '#e0e2e6',
  },

  // ---- dark ----------------------------------------------------------------
  {
    // The one the owner asked for by name. Gold is a LIGHT accent, so `onPrimary`
    // is near-black — white text on gold fails contrast badly.
    key: 'blackgold',
    label: 'שחור וזהב',
    primary: '#d4af37',
    onPrimary: '#17130a',
    bg: '#0b0b0d',
    surface: '#17171b',
    text: '#f6f2e8',
    muted: '#a89f8c',
    border: '#2b2b32',
  },
  {
    key: 'crimson',
    label: 'ארגמן ופחם',
    primary: '#e11d48',
    onPrimary: '#ffffff',
    bg: '#1c1917',
    surface: '#292524',
    text: '#fafaf9',
    muted: '#a8a29e',
    border: '#3b3633',
  },
  {
    key: 'navy',
    label: 'נייבי ופלטינה',
    primary: '#d8c38a',
    onPrimary: '#101a2c',
    bg: '#0f172a',
    surface: '#1b2942',
    text: '#eaf0f8',
    muted: '#94a5bf',
    border: '#2d3f5d',
  },
  {
    key: 'urban',
    label: 'כתום אורבני',
    primary: '#f97316',
    onPrimary: '#1a0f05',
    bg: '#18181b',
    surface: '#242428',
    text: '#fafafa',
    muted: '#a1a1aa',
    border: '#35353c',
  },
  {
    key: 'cocoa',
    label: 'קקאו ושמנת',
    primary: '#e0a45c',
    onPrimary: '#2a1608',
    bg: '#241610',
    surface: '#33231a',
    text: '#f7ebdc',
    muted: '#c0a085',
    border: '#463122',
  },
]

/** Used whenever `page_theme.palette` is missing, empty, or unrecognised. */
export const DEFAULT_PALETTE: PagePalette = PAGE_PALETTES[0]

/** Look up a palette by key. Unknown/absent ⇒ the default (never throws). */
export function resolvePalette(theme: PageTheme | null | undefined): PagePalette {
  const key = theme?.palette
  if (!key) return DEFAULT_PALETTE
  return PAGE_PALETTES.find((p) => p.key === key) ?? DEFAULT_PALETTE
}

/** The owner's radius override, clamped; falls back to the house default. */
export function resolveRadius(theme: PageTheme | null | undefined): number {
  const raw = theme?.radius
  if (typeof raw !== 'number' || !Number.isFinite(raw)) return DEFAULT_RADIUS
  return Math.min(MAX_RADIUS, Math.max(MIN_RADIUS, Math.round(raw)))
}

/**
 * The palette as CSS custom properties, to be spread onto the page wrapper's
 * `style`. Children then reference them (`bg-[color:var(--bp-surface)]`), so a
 * palette switch is one style object and not a re-render of every class name.
 */
/**
 * CSS variables for an ALREADY-RESOLVED palette + radius.
 *
 * The wizard's live preview needs this: it renders a palette the owner is only
 * hovering over, which has no stored `PageTheme` blob behind it yet. The public
 * page uses `paletteVars(theme)` below, which resolves first and then calls this.
 */
export function paletteVarsFor(
  p: PagePalette,
  radius: number,
): React.CSSProperties & Record<string, string> {
  return {
    '--bp-primary': p.primary,
    '--bp-on-primary': p.onPrimary,
    '--bp-bg': p.bg,
    '--bp-surface': p.surface,
    '--bp-text': p.text,
    '--bp-muted': p.muted,
    '--bp-border': p.border,
    '--bp-radius': `${radius}px`,
  }
}

export function paletteVars(
  theme: PageTheme | null | undefined,
): React.CSSProperties & Record<string, string> {
  const p = resolvePalette(theme)
  return {
    '--bp-primary': p.primary,
    '--bp-on-primary': p.onPrimary,
    '--bp-bg': p.bg,
    '--bp-surface': p.surface,
    '--bp-text': p.text,
    '--bp-muted': p.muted,
    '--bp-border': p.border,
    '--bp-radius': `${resolveRadius(theme)}px`,
  }
}
