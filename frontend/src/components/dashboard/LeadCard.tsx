// One lead, expanded to show EVERY collected detail (the owner explicitly wants
// no hiding). Header: avatar initials, contact name, flow + status badge. Body:
// a grid of every key/value in `answers`, plus the lead's metadata (phone, step,
// times). Footer actions (shown at ANY status): a single in-app chat button + a
// control to manually mark the lead as a deal / closed (which requires an
// outcome note via OutcomeNoteDialog).
//
// Abandoned leads (the נוטשים list) reuse this card — they simply carry partial
// answers and an "abandoned" status, which the badge + step text make clear.

import { useState } from 'react'
import type {
  ConversationStatus,
  Lead,
  LeadStatus,
} from '../../dashboard/types'
import { fullDateTime, relativeTime } from '../../lib/formatDate'
import { deleteLead, getConversation, setLeadStatus } from '../../lib/dashboardClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { closeReasonMeta } from '../../dashboard/closeReason'
import Badge from '../ui/Badge'
import Icon from '../ui/Icon'
import Modal from '../ui/Modal'
import AnswerValue, { answerPreviewText, hasFileAnswer } from './AnswerValue'
import ChatPanel from './ChatPanel'
import OutcomeNoteDialog from './OutcomeNoteDialog'

// Status → Hebrew label + Badge tone (covers every concrete LeadStatus).
const STATUS_META: Record<LeadStatus, { label: string; tone: 'leaf' | 'info' | 'warning' | 'neutral' }> = {
  new: { label: 'חדש', tone: 'leaf' },
  in_progress: { label: 'פתוח', tone: 'info' },
  abandoned: { label: 'ננטש', tone: 'warning' },
  deal: { label: 'בוצעה עסקה', tone: 'leaf' },
  closed: { label: 'ליד סגור', tone: 'neutral' },
}

// First letters of the contact name for the avatar (falls back to a glyph).
function initials(name: string | null): string {
  if (!name) return '—'
  const parts = name.trim().split(/\s+/).slice(0, 2)
  return parts.map((p) => p[0]).join('') || '—'
}

type Props = {
  lead: Lead
  /** Called after a manual status change succeeds, so the page can refetch. */
  onStatusChange?: () => void
  /** Called after the lead is successfully deleted from the DB. */
  onDelete?: () => void
}

export default function LeadCard({ lead, onStatusChange, onDelete }: Props) {
  const meta = STATUS_META[lead.status]
  const answers = Object.entries(lead.answers ?? {})
  // "Why it closed" (decision 0021), shown alongside the live status when set.
  const closeMeta = closeReasonMeta(lead.close_reason)

  const [saving, setSaving] = useState<LeadStatus | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  // Delete confirmation
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  async function confirmDelete() {
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteLead(lead.id)
      setShowDeleteConfirm(false)
      onDelete?.()
    } catch {
      setDeleteError('המחיקה נכשלה. נסו שוב.')
    } finally {
      setDeleting(false)
    }
  }

  // Outcome-note dialog: deal/closed require a free-text note before saving.
  const [outcome, setOutcome] = useState<'deal' | 'closed' | null>(null)
  const [outcomeError, setOutcomeError] = useState<string | null>(null)

  // In-app chat: revealed when the owner opens it for this lead's conversation.
  // We fetch the conversation first to learn its current handling status; if it
  // no longer lives in Redis we fall back to 'human' so the owner can still
  // read the (empty) panel and reply.
  const [showChat, setShowChat] = useState(false)
  const [openingChat, setOpeningChat] = useState(false)
  const [chatStatus, setChatStatus] = useState<ConversationStatus>('human')

  async function openInAppChat() {
    if (!lead.conversation_id) return
    if (showChat) {
      setShowChat(false)
      return
    }
    setOpeningChat(true)
    setActionError(null)
    try {
      const detail = await getConversation(lead.conversation_id)
      setChatStatus(detail.status)
    } catch {
      // Conversation gone from Redis (or not ours) — still let the owner open
      // the panel in human mode; no PII is exposed by this fallback.
      setChatStatus('human')
    } finally {
      setOpeningChat(false)
      setShowChat(true)
    }
  }

  // deal/closed go through the dialog (a note is mandatory); confirm saves the
  // status together with the encrypted-at-rest note.
  async function confirmOutcome(note: string) {
    if (!outcome) return
    setSaving(outcome)
    setOutcomeError(null)
    try {
      await setLeadStatus(lead.id, outcome, note)
      setOutcome(null)
      onStatusChange?.()
    } catch (err) {
      setOutcomeError(toFriendlyError(err, 'עדכון הסטטוס נכשל. נסו שוב.'))
    } finally {
      setSaving(null)
    }
  }

  return (
    <article className="rounded-xl border border-black/10 bg-white p-3 sm:p-4 dark:border-white/10 dark:bg-slate-800">
      <div className="flex items-center gap-3">
        <span
          aria-hidden="true"
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-leaf-soft text-sm font-medium text-leaf-ink"
        >
          {initials(lead.contact_name)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
            {lead.contact_name || 'ליד ללא שם'}
          </p>
          <p className="truncate text-xs text-slate-500">
            {lead.lead_name}
            {lead.status === 'abandoned'
              ? ` · עצר בשלב ${lead.last_step_index + 1}`
              : ''}
            {lead.is_test ? ' · בדיקה' : ''}
          </p>
        </div>
        <div className="flex flex-shrink-0 flex-wrap items-center justify-end gap-1.5">
          {closeMeta ? (
            <Badge tone={closeMeta.tone}>{closeMeta.label}</Badge>
          ) : null}
          <Badge tone={meta.tone}>{meta.label}</Badge>
        </div>
      </div>

      {/* Every collected answer — nothing hidden.
          גם בטלפון זו רשת של שתי עמודות ולא עמודה אחת: הערכים כאן קצרים
          (שם, טלפון, בחירה מתפריט), אז שתי עמודות מקוצצות (`truncate`) מראות
          פי שניים מידע במבט אחד — והערך המלא זמין ב-`title` ובלחיצה. */}
      {answers.length > 0 ? (
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-black/10 pt-3 sm:grid-cols-3 sm:gap-x-6 dark:border-white/10">
          {answers.map(([key, value]) => (
            <div key={key} className="min-w-0">
              <dt className="text-[11px] text-slate-400">{key}</dt>
              <dd
                className={`text-sm text-slate-800 dark:text-slate-200 ${
                  hasFileAnswer(value) ? '' : 'truncate'
                }`}
                title={answerPreviewText(value)}
              >
                <AnswerValue value={value} />
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-3 border-t border-black/10 pt-3 text-sm text-slate-400">
          עדיין לא נאספו פרטים.
        </p>
      )}

      {/* Metadata footer */}
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-slate-400">
        {lead.phone ? <span>טלפון: {lead.phone}</span> : null}
        {lead.started_at ? <span>התחיל: {relativeTime(lead.started_at)}</span> : null}
        {lead.submitted_at ? (
          <span title={fullDateTime(lead.submitted_at)}>
            הושלם: {relativeTime(lead.submitted_at)}
          </span>
        ) : lead.last_activity_at ? (
          <span title={fullDateTime(lead.last_activity_at)}>
            פעילות אחרונה: {relativeTime(lead.last_activity_at)}
          </span>
        ) : null}
      </div>

      {/* Saved outcome note (shown once the owner records one). */}
      {lead.outcome_note ? (
        <div className="mt-3 border-t border-black/10 pt-3 dark:border-white/10">
          <p className="text-[11px] text-slate-400">סיכום הטיפול</p>
          <p className="whitespace-pre-wrap break-words text-sm text-slate-800 dark:text-slate-200">
            {lead.outcome_note}
          </p>
        </div>
      ) : null}

      {/* Actions: ONE in-app chat button + manual status + delete. Shown at any status.
          `flex-wrap` ולא עמודה: בטלפון הכפתורים נשברים לשתי שורות צפופות
          במקום ארבע שורות ברוחב מלא. `ms-auto` על "מחק" עדיין דוחף אותו
          לקצה, כך שכפתור ההרס לא צמוד לפעולות הרגילות. */}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-black/10 pt-3 dark:border-white/10">
        {lead.conversation_id ? (
          <button
            type="button"
            onClick={() => void openInAppChat()}
            disabled={openingChat}
            aria-expanded={showChat}
            className="inline-flex items-center gap-1.5 rounded-lg bg-leaf px-3 py-2.5 text-sm font-medium sm:py-1.5 text-white outline-none transition-colors hover:bg-leaf-dark focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Icon name="message-circle" size={16} />
            {openingChat ? 'פותח…' : "צ'אט באפליקציה"}
            <span className="sr-only"> עם {lead.contact_name || 'הליד'}</span>
          </button>
        ) : null}

        {lead.status !== 'deal' ? (
          <button
            type="button"
            onClick={() => {
              setOutcomeError(null)
              setOutcome('deal')
            }}
            disabled={saving !== null}
            className="inline-flex items-center gap-1.5 rounded-lg border border-leaf px-3 py-2.5 text-sm font-medium sm:py-1.5 text-leaf-ink outline-none transition-colors hover:bg-leaf-soft focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Icon name="checks" size={16} />
            {saving === 'deal' ? 'מעדכן…' : 'בוצעה עסקה'}
          </button>
        ) : null}

        {lead.status !== 'closed' ? (
          <button
            type="button"
            onClick={() => {
              setOutcomeError(null)
              setOutcome('closed')
            }}
            disabled={saving !== null}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2.5 text-sm font-medium sm:py-1.5 text-slate-600 outline-none transition-colors hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            <Icon name="x" size={16} />
            {saving === 'closed' ? 'מעדכן…' : 'ליד סגור'}
          </button>
        ) : null}

        {/* Delete button — always visible, starts a confirm flow */}
        <button
          type="button"
          onClick={() => { setDeleteError(null); setShowDeleteConfirm(true) }}
          disabled={saving !== null || deleting}
          title="מחק ליד לצמיתות"
          className="ms-auto inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-2.5 text-sm font-medium sm:py-1.5 text-red-600 outline-none transition-colors hover:bg-red-50 focus-visible:ring-2 focus-visible:ring-red-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Icon name="trash" size={15} />
          מחק
        </button>
      </div>

      {actionError ? (
        <p role="alert" className="mt-2 text-xs text-bad">
          {actionError}
        </p>
      ) : null}

      {/* Delete confirmation Modal */}
      <Modal
        open={showDeleteConfirm}
        title="מחיקת ליד לצמיתות"
        onClose={() => { if (!deleting) setShowDeleteConfirm(false) }}
      >
        <p className="text-sm text-slate-700">
          האם למחוק את הליד של{' '}
          <span className="font-semibold">{lead.contact_name || 'ליד ללא שם'}</span>{' '}
          לצמיתות? לא ניתן לשחזר.
        </p>
        {deleteError ? (
          <p role="alert" className="mt-2 text-xs text-red-600">{deleteError}</p>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => setShowDeleteConfirm(false)}
            disabled={deleting}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-60 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-700"
          >
            ביטול
          </button>
          <button
            type="button"
            onClick={() => void confirmDelete()}
            disabled={deleting}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
          >
            {deleting ? 'מוחק…' : 'כן, מחק לצמיתות'}
          </button>
        </div>
      </Modal>

      <OutcomeNoteDialog
        outcome={outcome ?? 'deal'}
        open={outcome !== null}
        saving={saving !== null}
        error={outcomeError}
        onCancel={() => {
          if (saving === null) setOutcome(null)
        }}
        onConfirm={(note) => void confirmOutcome(note)}
      />

      {/* Inline in-app chat for this lead's conversation (opened on demand). */}
      {showChat && lead.conversation_id ? (
        <div className="mt-3 h-[28rem]">
          <ChatPanel
            conversationId={lead.conversation_id}
            status={chatStatus}
            onStatusChange={(_id, next) => setChatStatus(next)}
            fallbackAnswers={lead.answers}
            fallbackName={lead.contact_name}
            fallbackPhone={lead.phone}
          />
        </div>
      ) : null}
    </article>
  )
}
