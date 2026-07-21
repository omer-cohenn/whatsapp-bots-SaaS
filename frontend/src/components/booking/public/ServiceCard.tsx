// כרטיס שירות — בדיוק כמו ב-HTML המקורי: שם, שעון + משך, ומחיר גדול בצבע המותג.
//
// The owner asked for this one literally: "השירותים והמחירים גם יוצגו בדיוק כמו
// שהם בHTML המקורי". The reference's step-1 markup is:
//
//   name (font-bold text-lg)          |  ₪price (font-black text-xl, accent)
//   🕐 duration דקות (text-xs, muted) |
//
//   card surface = the PAGE background, sitting inset on the booking panel;
//   selected     = accent ring + a slight scale-up;
//   unselected   = slightly dimmed, brightening on hover.
//
// Colours are palette variables with fallbacks, so this renders correctly both on
// the designed page (where `paletteVars` sets them) and inside the owner's plain
// settings preview (where it falls back to the house neutral).
//
// 🔴 Shared: the public booking flow AND the wizard preview render THIS file.

import Icon from '../../ui/Icon'

type Props = {
  name: string
  description?: string | null
  durationMinutes: number
  /** null ⇒ "ללא עלות" rather than a bare "₪0". */
  price: number | null
  selected: boolean
  onSelect: () => void
  /** false ⇒ the card is inert (wizard preview). */
  interactive?: boolean
}

/** "ללא עלות" when no price is set, else "₪{price}". */
export function priceLabel(price: number | null): string {
  return price == null ? 'ללא עלות' : `₪${price}`
}

export default function ServiceCard({
  name,
  description,
  durationMinutes,
  price,
  selected,
  onSelect,
  interactive = true,
}: Props) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      disabled={!interactive}
      onClick={onSelect}
      style={{
        backgroundColor: 'var(--bp-bg, #f8fafc)',
        borderColor: selected ? 'var(--bp-primary, #2563eb)' : 'var(--bp-border, #e2e8f0)',
        color: 'var(--bp-text, #0f172a)',
      }}
      className={[
        'flex items-center justify-between gap-4 rounded-[var(--bp-radius,18px)] border p-5 text-start transition duration-200',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--bp-primary,#2563eb)] focus-visible:ring-offset-2',
        selected
          ? 'scale-[1.02] shadow-lg ring-2 ring-[color:var(--bp-primary,#2563eb)]'
          : 'opacity-85 hover:opacity-100',
      ].join(' ')}
    >
      <span className="flex min-w-0 flex-col gap-1">
        <span className="truncate text-lg font-bold">{name}</span>
        <span
          className="flex items-center gap-1.5 text-xs font-medium"
          style={{ color: 'var(--bp-muted, #64748b)' }}
        >
          <Icon name="clock" size={14} />
          {`${durationMinutes} דקות`}
        </span>
        {description ? (
          <span
            className="mt-1 line-clamp-2 text-sm leading-relaxed"
            style={{ color: 'var(--bp-muted, #64748b)' }}
          >
            {description}
          </span>
        ) : null}
      </span>

      <span
        className="shrink-0 text-xl font-black"
        style={{ color: 'var(--bp-primary, #2563eb)' }}
      >
        {priceLabel(price)}
      </span>
    </button>
  )
}
