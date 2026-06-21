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
      <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-6 text-center text-sm text-slate-500">
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
            className={`rounded-lg border px-3 py-2 text-sm font-medium transition ${
              selected
                ? 'border-leaf bg-leaf text-white'
                : 'border-slate-300 bg-white text-slate-800 hover:border-leaf hover:bg-leaf-soft'
            }`}
          >
            {slot}
          </button>
        )
      })}
    </div>
  )
}
