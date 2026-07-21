// עורך רשימת מספרי בדיקה (עד 5): טוען, מאמת ושומר את המספרים שיקבלו מענה מהבוט.

import { useEffect, useId, useState } from 'react'
import Button from '../ui/Button'
import Card from '../ui/Card'
import Spinner from '../ui/Spinner'
import Alert from '../ui/Alert'
import Field from '../ui/Field'
import Icon from '../ui/Icon'
import { getTestNumbers, setTestNumbers } from '../../lib/whatsappClient'
import type { TestNumber } from '../../lib/whatsappClient'
import { toFriendlyError } from '../../lib/friendlyError'

const MAX_TEST_NUMBERS = 5

// Each editable row needs a stable id so React keeps inputs/focus across
// add/remove without re-keying by array index.
type NumberRow = TestNumber & { id: string }

let rowSeq = 0
function makeRow(value: Partial<TestNumber> = {}): NumberRow {
  rowSeq += 1
  return { id: `row-${rowSeq}`, phone: value.phone ?? '', label: value.label ?? '' }
}

// Mirror the backend's normalisation closely enough to validate client-side:
// keep digits only, strip a leading '+'. A row is valid when something remains.
function digitsOnly(raw: string): string {
  return raw.replace(/\D/g, '')
}

// The owner may register up to 5 external numbers. Only those — plus the owner's
// own self-chat — get bot replies, and only while the bot is published.
export default function TestNumbersCard() {
  const [rows, setRows] = useState<NumberRow[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  // Friendly per-form validation message ("עד 5 מספרים", "מספר לא תקין").
  const [validationError, setValidationError] = useState<string | null>(null)

  const headingId = useId()

  // Load the current allowlist once.
  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const res = await getTestNumbers()
        if (!alive) return
        const next = res.numbers.map((n) => makeRow(n))
        setRows(next.length > 0 ? next : [makeRow()])
      } catch (err) {
        if (!alive) return
        setLoadError(toFriendlyError(err, 'טעינת מספרי הבדיקה נכשלה. נסו שוב.'))
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  // Any edit clears the previous success/validation feedback.
  function patchRow(id: string, patch: Partial<TestNumber>) {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)))
    setSaved(false)
    setValidationError(null)
  }

  function addRow() {
    if (rows.length >= MAX_TEST_NUMBERS) {
      setValidationError(`אפשר להוסיף עד ${MAX_TEST_NUMBERS} מספרים.`)
      return
    }
    setRows((prev) => [...prev, makeRow()])
    setSaved(false)
    setValidationError(null)
  }

  function removeRow(id: string) {
    setRows((prev) => {
      const next = prev.filter((r) => r.id !== id)
      // Always keep at least one (empty) row so the form never collapses.
      return next.length > 0 ? next : [makeRow()]
    })
    setSaved(false)
    setValidationError(null)
  }

  async function onSave() {
    if (saving) return
    setValidationError(null)
    setSaveError(null)
    setSaved(false)

    // Drop fully-empty rows (a blank trailing row is fine — it just isn't saved).
    const filled = rows.filter((r) => r.phone.trim() !== '' || (r.label ?? '').trim() !== '')

    if (filled.length > MAX_TEST_NUMBERS) {
      setValidationError(`אפשר לשמור עד ${MAX_TEST_NUMBERS} מספרים.`)
      return
    }

    // Every non-empty row must have a phone with at least one digit.
    const bad = filled.some((r) => digitsOnly(r.phone) === '')
    if (bad) {
      setValidationError('מספר לא תקין. הזינו ספרות בלבד, בפורמט בינלאומי (למשל 972501234567).')
      return
    }

    const items: TestNumber[] = filled.map((r) => {
      const label = (r.label ?? '').trim()
      return { phone: digitsOnly(r.phone), label: label === '' ? null : label }
    })

    setSaving(true)
    try {
      const res = await setTestNumbers(items)
      const next = res.numbers.map((n) => makeRow(n))
      setRows(next.length > 0 ? next : [makeRow()])
      setSaved(true)
    } catch (err) {
      setSaveError(toFriendlyError(err, 'שמירת מספרי הבדיקה נכשלה. נסו שוב.'))
    } finally {
      setSaving(false)
    }
  }

  const atCap = rows.length >= MAX_TEST_NUMBERS

  return (
    <Card>
      <section aria-labelledby={headingId} aria-busy={loading}>
        <h2 id={headingId} className="text-base font-semibold text-slate-900">
          מספרים לבדיקה (עד {MAX_TEST_NUMBERS})
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          רק המספרים האלה (והצ׳אט עם עצמכם) יקבלו תשובות מהבוט — וזאת רק כשהבוט
          מפורסם. כל מספר אחר יקבל מענה שקט (לא תישלח תשובה).
        </p>

        {loading ? (
          <Spinner label="טוען מספרי בדיקה…" className="py-8" />
        ) : loadError ? (
          <Alert tone="error" className="mt-4">
            {loadError}
          </Alert>
        ) : (
          <>
            <ul className="mt-4 flex flex-col gap-3">
              {rows.map((row, index) => (
                <li
                  key={row.id}
                  // Phones stack the number, the name and the remove control;
                  // from sm they sit on one line as before. min-w-0 on the two
                  // fields keeps a long typed value from widening the row.
                  className="flex flex-col gap-3 rounded-xl border border-slate-200 p-3 sm:flex-row sm:items-end"
                >
                  <div className="min-w-0 flex-1">
                    <Field
                      label={`מספר ${index + 1}`}
                      hint="פורמט בינלאומי, למשל 972501234567"
                      type="tel"
                      inputMode="tel"
                      dir="ltr"
                      autoComplete="off"
                      placeholder="972501234567"
                      value={row.phone}
                      onChange={(e) => patchRow(row.id, { phone: e.target.value })}
                    />
                  </div>
                  <div className="min-w-0 flex-1">
                    <Field
                      label="שם (לא חובה)"
                      placeholder="למשל: רכש"
                      autoComplete="off"
                      value={row.label ?? ''}
                      onChange={(e) => patchRow(row.id, { label: e.target.value })}
                    />
                  </div>
                  <Button
                    variant="ghost"
                    onClick={() => removeRow(row.id)}
                    className="min-h-[44px] text-bad hover:bg-red-50 sm:mb-0.5 sm:min-h-0"
                    aria-label={`הסרת מספר ${index + 1}`}
                  >
                    <Icon name="trash" size={16} />
                    הסרה
                  </Button>
                </li>
              ))}
            </ul>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button
                variant="secondary"
                onClick={addRow}
                disabled={atCap}
                className="min-h-[44px] sm:min-h-0"
              >
                <Icon name="plus" size={16} />
                הוספת מספר
              </Button>
              <Button
                onClick={() => void onSave()}
                disabled={saving}
                className="min-h-[44px] sm:min-h-0"
              >
                {saving ? (
                  <>
                    <span
                      aria-hidden="true"
                      className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                    />
                    שומר…
                  </>
                ) : (
                  <>
                    <Icon name="device-floppy" size={16} />
                    שמירה
                  </>
                )}
              </Button>
            </div>

            {atCap ? (
              <p className="mt-2 text-xs text-slate-400">
                הגעתם למקסימום של {MAX_TEST_NUMBERS} מספרים.
              </p>
            ) : null}

            {/* Async feedback — announced to screen readers. */}
            <div aria-live="polite" className="mt-3 empty:mt-0">
              {validationError ? (
                <Alert tone="warning">{validationError}</Alert>
              ) : saveError ? (
                <Alert tone="error">{saveError}</Alert>
              ) : saved ? (
                <Alert tone="info">המספרים נשמרו.</Alert>
              ) : null}
            </div>
          </>
        )}
      </section>
    </Card>
  )
}
