import { useCallback, useEffect, useState } from 'react'
import { fetchHealth } from '../lib/health.js'

// Maps a tri-state (true / false / null=unknown) to an accessible badge.
function StatusBadge({ state }) {
  if (state === true) {
    return (
      <span className="font-medium text-ok" role="img" aria-label="תקין">
        ✅ תקין
      </span>
    )
  }
  if (state === false) {
    return (
      <span className="font-medium text-bad" role="img" aria-label="תקלה">
        ❌ תקלה
      </span>
    )
  }
  return (
    <span className="font-medium text-slate-500" role="img" aria-label="לא ידוע">
      ⚪ לא ידוע
    </span>
  )
}

// One row: a human label + its status badge.
function CheckRow({ label, state }) {
  return (
    <li className="flex items-center justify-between gap-4 border-t border-slate-100 py-2 first:border-t-0">
      <span className="text-slate-700">{label}</span>
      <StatusBadge state={state} />
    </li>
  )
}

export default function StackHealth() {
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(true)

  const check = useCallback(async () => {
    setLoading(true)
    const result = await fetchHealth()
    setHealth(result)
    setLoading(false)
  }, [])

  useEffect(() => {
    check()
  }, [check])

  const backendUp = health?.ok === true

  return (
    <section
      aria-labelledby="health-title"
      className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
    >
      <div className="mb-3 flex items-center justify-between gap-4">
        <h2 id="health-title" className="text-lg font-bold text-slate-900">
          בריאות המערכת
        </h2>
        <button
          type="button"
          onClick={check}
          disabled={loading}
          className="rounded-lg bg-brand px-3 py-1.5 text-sm font-medium text-white transition hover:bg-brand-dark disabled:opacity-60"
        >
          {loading ? 'בודק…' : 'רענון'}
        </button>
      </div>

      {/* aria-live so screen readers announce status changes after a refresh. */}
      <ul aria-live="polite" aria-busy={loading} className="text-sm">
        <CheckRow label="שרת (Backend)" state={loading ? null : backendUp} />
        <CheckRow label="מסד נתונים (Postgres)" state={loading ? null : health?.postgres ?? null} />
        <CheckRow label="מטמון (Redis)" state={loading ? null : health?.redis ?? null} />
      </ul>

      {/* Plain-language footer line so a beginner can see what's wrong at a glance. */}
      <p className="mt-3 text-xs text-slate-500">
        {loading
          ? 'בודק חיבור לשרת…'
          : backendUp
            ? 'השרת מגיב דרך ‎/healthz.'
            : `אין מענה מהשרת${health?.error ? ` (${health.error})` : ''}. ודאו ש‑backend רץ.`}
      </p>
    </section>
  )
}
