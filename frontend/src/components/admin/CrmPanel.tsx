// Shared CRM control panel (M13). Used both inside the pipeline board's card
// dialog and on the business detail page. It lets the operator:
//   * change the sales stage (PATCH .../crm)
//   * set/clear the next-follow-up date (same PATCH)
//   * add a note (POST .../crm/notes) and read the activity log (GET .../crm/notes)
//
// Stage + follow-up save together (one PATCH). Notes load lazily on mount and
// after each add. Success/error surface via an Alert (role="alert"); 404/422
// map to friendly Hebrew via toFriendlyError.

import { useCallback, useEffect, useState } from 'react'
import Select from '../ui/Select'
import Field from '../ui/Field'
import Textarea from '../ui/Textarea'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import Icon from '../ui/Icon'
import Spinner from '../ui/Spinner'
import {
  addCrmNote,
  getCrmNotes,
  setCrmStage,
} from '../../lib/adminClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { CRM_STAGE_META, CRM_STAGE_ORDER } from '../../admin/labels'
import { fullDateTime } from '../../lib/formatDate'
import type { CrmNote, CrmStage } from '../../admin/types'

// An ISO timestamp → the YYYY-MM-DD a <input type="date"> expects (or '').
function toDateInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

type Props = {
  businessId: string
  stage: CrmStage
  nextFollowupAt: string | null
  /** Called after a successful stage/follow-up save with the server's values. */
  onChanged?: (stage: CrmStage, nextFollowupAt: string | null) => void
}

const STAGE_OPTIONS = CRM_STAGE_ORDER.map((s) => ({
  value: s,
  label: CRM_STAGE_META[s].label,
}))

export default function CrmPanel({
  businessId,
  stage,
  nextFollowupAt,
  onChanged,
}: Props) {
  const [newStage, setNewStage] = useState<CrmStage>(stage)
  const [followup, setFollowup] = useState(toDateInput(nextFollowupAt))
  const [saving, setSaving] = useState(false)
  const [saveResult, setSaveResult] = useState<
    { tone: 'info' | 'error'; text: string } | null
  >(null)

  const [notes, setNotes] = useState<CrmNote[]>([])
  const [notesLoading, setNotesLoading] = useState(true)
  const [notesError, setNotesError] = useState<string | null>(null)
  const [noteDraft, setNoteDraft] = useState('')
  const [addingNote, setAddingNote] = useState(false)
  const [noteResult, setNoteResult] = useState<
    { tone: 'info' | 'error'; text: string } | null
  >(null)

  // Re-seed the controls when the parent's current values change.
  useEffect(() => {
    setNewStage(stage)
    setFollowup(toDateInput(nextFollowupAt))
  }, [stage, nextFollowupAt])

  const loadNotes = useCallback(() => {
    let cancelled = false
    setNotesLoading(true)
    setNotesError(null)
    getCrmNotes(businessId)
      .then((res) => {
        if (!cancelled) setNotes(res.notes)
      })
      .catch((err) => {
        if (!cancelled)
          setNotesError(toFriendlyError(err, 'טעינת הפתקים נכשלה. נסו שוב.'))
      })
      .finally(() => {
        if (!cancelled) setNotesLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [businessId])

  useEffect(() => loadNotes(), [loadNotes])

  const dirty =
    newStage !== stage || followup !== toDateInput(nextFollowupAt)

  async function onSaveStage() {
    setSaving(true)
    setSaveResult(null)
    try {
      // Empty date clears the follow-up (send null); a date sends YYYY-MM-DD.
      const res = await setCrmStage(businessId, newStage, followup || null)
      onChanged?.(res.stage, res.next_followup_at)
      setSaveResult({ tone: 'info', text: 'שלב המכירה עודכן בהצלחה.' })
    } catch (err) {
      setSaveResult({
        tone: 'error',
        text: toFriendlyError(err, 'עדכון שלב המכירה נכשל. נסו שוב.'),
      })
    } finally {
      setSaving(false)
    }
  }

  async function onAddNote() {
    const text = noteDraft.trim()
    if (!text) return
    setAddingNote(true)
    setNoteResult(null)
    try {
      await addCrmNote(businessId, text)
      setNoteDraft('')
      setNoteResult({ tone: 'info', text: 'הפתק נוסף.' })
      loadNotes()
    } catch (err) {
      setNoteResult({
        tone: 'error',
        text: toFriendlyError(err, 'הוספת הפתק נכשלה. נסו שוב.'),
      })
    } finally {
      setAddingNote(false)
    }
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Stage + follow-up */}
      <div className="grid gap-4 sm:grid-cols-2">
        <Select
          label="שלב מכירה"
          options={STAGE_OPTIONS}
          value={newStage}
          onChange={(e) => setNewStage(e.target.value as CrmStage)}
          disabled={saving}
        />
        <Field
          label="תזכורת חזרה"
          type="date"
          value={followup}
          onChange={(e) => setFollowup(e.target.value)}
          disabled={saving}
          hint="השאירו ריק כדי לבטל את התזכורת."
        />
      </div>

      <div className="flex items-center gap-3">
        <Button onClick={() => void onSaveStage()} disabled={saving || !dirty}>
          <Icon name="device-floppy" size={18} />
          {saving ? 'שומר…' : 'שמירת שלב'}
        </Button>
        {!dirty && !saveResult ? (
          <span className="text-sm text-slate-400">אין שינויים לשמירה.</span>
        ) : null}
      </div>

      {saveResult ? <Alert tone={saveResult.tone}>{saveResult.text}</Alert> : null}

      {/* Notes */}
      <div className="border-t border-slate-200 pt-4">
        <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700">
          <Icon name="note" size={18} className="text-leaf" />
          פתקים ופעולות
        </h3>

        <div className="mt-3 flex flex-col gap-2">
          <Textarea
            label="פתק חדש"
            value={noteDraft}
            onChange={(e) => setNoteDraft(e.target.value)}
            placeholder="למשל: התקשרתי, ביקש הצעת מחיר עד יום ראשון…"
            rows={2}
            maxLength={2000}
            disabled={addingNote}
          />
          <div className="flex items-center gap-3">
            <Button
              variant="secondary"
              onClick={() => void onAddNote()}
              disabled={addingNote || noteDraft.trim().length === 0}
            >
              <Icon name="plus" size={16} />
              {addingNote ? 'מוסיף…' : 'הוספת פתק'}
            </Button>
          </div>
          {noteResult ? <Alert tone={noteResult.tone}>{noteResult.text}</Alert> : null}
        </div>

        <div className="mt-4">
          {notesLoading ? (
            <Spinner label="טוען פתקים…" className="py-6" />
          ) : notesError ? (
            <Alert tone="error">{notesError}</Alert>
          ) : notes.length > 0 ? (
            <ul className="flex flex-col gap-2">
              {notes.map((n) => (
                <li
                  key={n.id}
                  className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2"
                >
                  <p className="whitespace-pre-wrap text-sm text-slate-800">{n.note}</p>
                  <p className="mt-1 text-xs text-slate-400">
                    {n.admin_email || 'מנהל'}
                    {n.created_at ? ` · ${fullDateTime(n.created_at)}` : ''}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="rounded-lg border border-dashed border-slate-300 bg-white px-3 py-6 text-center text-sm text-slate-500">
              אין עדיין פתקים.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
