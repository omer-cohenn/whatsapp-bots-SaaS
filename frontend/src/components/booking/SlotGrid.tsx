// A grid of available "HH:MM" time slots rendered as an accessible radio group
// (arrow keys + screen-reader semantics for free). Used on the public booking
// page after the customer picks a service + date. The slots themselves come from
// GET /api/book/{slug}/slots (already filtered to available, local times).

type Props = {
  slots: string[]
  /** Currently chosen "HH:MM", or '' for none. */
  value: string
  onChange: (slot: string) => void
}

export default function SlotGrid({ slots, value, onChange }: Props) {
  if (slots.length === 0) {
    return (
      <p
        className="rounded-xl border border-dashed px-4 py-6 text-center text-sm"
        style={{ borderColor: 'var(--bp-border, #cbd5e1)', color: 'var(--bp-muted, #64748b)' }}
      >
        אין שעות פנויות ביום שנבחר. נסו תאריך אחר.
      </p>
    )
  }

  return (
    <div role="radiogroup" aria-label="בחירת שעה" className="grid grid-cols-3 gap-2 sm:grid-cols-4">
      {slots.map((slot) => {
        const selected = slot === value
        return (
          <button
            key={slot}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(slot)}
            // Palette-driven with neutral fallbacks: the same grid renders on the
            // designed public page and on the plain owner preview.
            style={
              selected
                ? {
                    backgroundColor: 'var(--bp-primary, #639922)',
                    borderColor: 'var(--bp-primary, #639922)',
                    color: 'var(--bp-on-primary, #ffffff)',
                  }
                : {
                    backgroundColor: 'var(--bp-bg, #ffffff)',
                    borderColor: 'var(--bp-border, #cbd5e1)',
                    color: 'var(--bp-text, #1e293b)',
                  }
            }
            className={`rounded-[var(--bp-radius,10px)] border px-3 py-2.5 text-sm font-semibold transition ${
              selected ? 'scale-105 shadow-md' : 'hover:brightness-95'
            }`}
          >
            {slot}
          </button>
        )
      })}
    </div>
  )
}
