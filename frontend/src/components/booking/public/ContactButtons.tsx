// שורת ארבעת כפתורי הקשר (ריבועים מעוגלים): Waze · Instagram · טלפון · WhatsApp.
//
// 🔴 הכלל של M20: שדה ריק ⇒ הכפתור פשוט לא קיים. לא מעומעם, לא מושבת — לא מרונדר.
//
// The rule from decision 0028 / contract §9, implemented literally: each of the
// four fields is tested INDEPENDENTLY and a falsy one produces no element at all.
// The row itself is built by filtering an array, so:
//   * one missing field leaves no hole and no stray gap — flexbox just centres
//     whatever survived;
//   * ALL four missing returns `null`, so there is no empty row and no margin
//     collapsing into a mystery blank strip under the address.
//
// COLOUR: every button wears the SAME colour, taken from the palette the owner
// picked — a soft tint of the brand accent with the accent itself as the glyph.
// Platform colours (WhatsApp green, the Instagram gradient…) were tried and
// rejected: four saturated logos fight each other and drag the eye away from the
// booking flow, and they ignore whichever palette the owner chose. One restrained
// colour keeps the row as a quiet utility strip, which is what the owner's
// reference screenshot actually shows.
//
// SHAPE + SIZE: a 52px rounded SQUARE (squircle) holding a 24px glyph, matching
// the owner's reference screenshot. It was briefly a small 36px circle; at that
// size the row read as a faint afterthought under the name, and these are the
// primary "call me / message me" affordances on the page. The tinted square is
// large enough to be an obvious tap target on a phone (52px clears the ~44px
// minimum) while the fill stays light enough not to compete with the photos.
//
// Link building:
//   phone     → `tel:` with separators stripped (a "+" prefix is kept)
//   whatsapp  → `https://wa.me/<digits>`; non-digits removed per wa.me's format
//   instagram/waze → already full http(s) URLs, server-validated (contract §5
//                    rejects `javascript:` with 422). We re-check here anyway —
//                    this is a public page rendering owner-supplied hrefs.
//
// Every external link gets rel="noopener noreferrer". Each tile is icon-only,
// so the accessible name comes from `aria-label` plus visually-hidden text.

import type { ReactNode } from 'react'
import type { BusinessContactFields } from '../../../dashboard/businessPageTypes'
import Icon from '../../ui/Icon'
import { InstagramIcon, WazeIcon } from './brandIcons'

type ContactButton = {
  key: string
  href: string
  label: string
  icon: ReactNode
  /** `tel:` stays in-tab; the rest open a new tab. */
  external: boolean
}

/** Digits only — what wa.me expects (it rejects "+", spaces and dashes). */
function waDigits(raw: string): string {
  return raw.replace(/\D/g, '')
}

/** Keep digits and a single leading "+", drop spaces/dashes/parens. */
function telValue(raw: string): string {
  const trimmed = raw.trim()
  const plus = trimmed.startsWith('+') ? '+' : ''
  const digits = trimmed.replace(/\D/g, '')
  return digits ? `${plus}${digits}` : ''
}

/** Defensive: only ever emit an http(s) href into a public page. */
function safeUrl(raw: string): string {
  return /^https?:\/\//i.test(raw.trim()) ? raw.trim() : ''
}

/** Build the row. Returns [] when the owner filled in nothing at all. */
function buildButtons(fields: BusinessContactFields): ContactButton[] {
  const out: ContactButton[] = []

  const waze = fields.waze_url ? safeUrl(fields.waze_url) : ''
  if (waze) {
    out.push({
      key: 'waze',
      href: waze,
      label: 'ניווט ב-Waze',
      icon: <WazeIcon size={24} />,
      external: true,
    })
  }

  const instagram = fields.instagram_url ? safeUrl(fields.instagram_url) : ''
  if (instagram) {
    out.push({
      key: 'instagram',
      href: instagram,
      label: 'עמוד האינסטגרם',
      icon: <InstagramIcon size={24} />,
      external: true,
    })
  }

  const tel = fields.phone ? telValue(fields.phone) : ''
  if (tel) {
    out.push({
      key: 'phone',
      href: `tel:${tel}`,
      label: 'התקשרו אלינו',
      icon: <Icon name="phone" size={24} />,
      external: false,
    })
  }

  const wa = fields.whatsapp ? waDigits(fields.whatsapp) : ''
  if (wa) {
    out.push({
      key: 'whatsapp',
      href: `https://wa.me/${wa}`,
      label: 'שליחת הודעת WhatsApp',
      icon: <Icon name="brand-whatsapp" size={24} />,
      external: true,
    })
  }

  return out
}

type Props = {
  fields: BusinessContactFields
  /** Extra positioning classes from the caller (the row itself never sets margin). */
  className?: string
  /**
   * false in the owner's wizard preview: the same markup renders, but as inert
   * <span>s so a preview click never dials the owner's own phone.
   */
  interactive?: boolean
}

export default function ContactButtons({
  fields,
  className = '',
  interactive = true,
}: Props) {
  const buttons = buildButtons(fields)
  // Nothing filled in ⇒ no row, no gap. (The `null` here is the product rule.)
  if (buttons.length === 0) return null

  return (
    <nav aria-label="דרכי יצירת קשר" className={`flex flex-wrap gap-3 ${className}`}>
      {buttons.map((b) => {
        const Tag = (interactive ? 'a' : 'span') as 'a'
        return (
        <Tag
          key={b.key}
          {...(interactive ? { href: b.href } : {})}
          aria-label={b.label}
          title={b.label}
          {...(interactive && b.external
            ? { target: '_blank', rel: 'noopener noreferrer' }
            : {})}
          // The tint comes from the palette's own accent via `color-mix`, so a new
          // palette needs no work here and the row can never clash with the page.
          // `--bp-primary` is set by `paletteVars` on the page wrapper; the
          // fallbacks keep the buttons visible if this ever renders outside it.
          style={{
            backgroundColor:
              'color-mix(in srgb, var(--bp-primary, #2563eb) 12%, transparent)',
            color: 'var(--bp-primary, #2563eb)',
          }}
          className="flex h-[52px] w-[52px] items-center justify-center rounded-[18px] transition hover:brightness-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
        >
          {b.icon}
          <span className="sr-only">{b.label}</span>
        </Tag>
        )
      })}
    </nav>
  )
}
