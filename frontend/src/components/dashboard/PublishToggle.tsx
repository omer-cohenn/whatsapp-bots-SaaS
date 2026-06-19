// The go-live (publish) control. A single accessible switch that calls
// PUT /api/bot/publish and shows a clear "פורסם / טיוטה" state. Reusable on the
// dashboard home and the bot-builder header.
//
// It owns its own request state (saving / error) but takes the current value +
// an onChange so the parent stays the source of truth and can react to changes.

import { useState } from 'react'
import { setPublished } from '../../lib/dashboardClient'
import { toFriendlyError } from '../../lib/friendlyError'
import Icon from '../ui/Icon'

type Props = {
  /** Current published state (from the loaded bot settings). */
  isPublished: boolean
  /** Called with the new state after a successful PUT. */
  onChange: (next: boolean) => void
}

export default function PublishToggle({ isPublished, onChange }: Props) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function toggle() {
    if (saving) return
    const next = !isPublished
    setSaving(true)
    setError(null)
    try {
      const res = await setPublished(next)
      onChange(res.is_published)
    } catch (err) {
      setError(toFriendlyError(err, 'עדכון מצב הפרסום נכשל. נסו שוב.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-3">
        <span className="flex items-center gap-1.5 text-sm font-medium text-slate-800">
          <span
            aria-hidden="true"
            className={`h-2 w-2 rounded-full ${isPublished ? 'bg-leaf' : 'bg-slate-300'}`}
          />
          {isPublished ? 'פורסם' : 'טיוטה'}
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={isPublished}
          aria-label={isPublished ? 'הבוט מפורסם — לחצו כדי להחזיר לטיוטה' : 'הבוט בטיוטה — לחצו כדי לפרסם'}
          disabled={saving}
          onClick={() => void toggle()}
          className={`relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full p-0.5 transition disabled:opacity-60 ${
            isPublished ? 'bg-leaf' : 'bg-slate-300'
          }`}
        >
          <span
            aria-hidden="true"
            className={`flex h-5 w-5 items-center justify-center rounded-full bg-white shadow transition-transform ${
              // RTL: "on" knob sits at the inline-start (right) edge.
              isPublished ? '-translate-x-5' : 'translate-x-0'
            }`}
          >
            {saving ? (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-leaf" />
            ) : isPublished ? (
              <Icon name="checks" size={12} className="text-leaf" />
            ) : null}
          </span>
        </button>
      </div>
      {error ? (
        <span role="alert" className="text-xs text-bad">
          {error}
        </span>
      ) : null}
    </div>
  )
}
