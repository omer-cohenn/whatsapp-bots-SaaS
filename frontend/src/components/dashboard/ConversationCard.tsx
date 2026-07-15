// One live conversation as an ACCORDION ROW (the StepsEditor accordion pattern:
// only one row is open at a time, controlled by the parent list).
//
//  - Collapsed: a status chip + last-message preview + relative last-activity.
//  - Expanded: lazily fetches GET /api/conversations/{id} to show the linked
//    lead's details (name / phone / collected answers) and the handling actions:
//      • "לשיחה עם הלקוח" — flips waiting/bot → human (POST status) and reveals
//        the inline ChatPanel for this conversation.
//      • "טופל" — flips → closed (POST status).
//
// Per-row state lives here so one slow request never blocks the rest of the list;
// the parent is told about every status change so its filtered view stays correct.
// Tenant scoping is entirely server-side — we only ever send the conversation id.

import { useEffect, useState } from 'react'
import type {
  Conversation,
  ConversationDetail,
  ConversationStatus,
} from '../../dashboard/types'
import {
  getConversation,
  setConversationStatus,
  setLeadStatus,
} from '../../lib/dashboardClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { relativeTime } from '../../lib/formatDate'
import { closeReasonMeta } from '../../dashboard/closeReason'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import Icon from '../ui/Icon'
import Spinner from '../ui/Spinner'
import ChatPanel from './ChatPanel'
import OutcomeNoteDialog from './OutcomeNoteDialog'

const STATUS_META: Record<
  ConversationStatus,
  { label: string; tone: 'leaf' | 'info' | 'neutral' | 'warning' }
> = {
  bot: { label: 'בוט', tone: 'leaf' },
  // 'waiting' = customer asked for a human, bot stepped aside, no one took it yet.
  // Surfaced with an attention colour so the owner spots it at a glance.
  waiting: { label: 'המתנה לנציג', tone: 'warning' },
  human: { label: 'נציג אנושי', tone: 'info' },
  closed: { label: 'סגור', tone: 'neutral' },
}

type Props = {
  conversation: Conversation
  /** This row is the one currently expanded in the accordion. */
  open: boolean
  /** Ask the parent to expand this row (and collapse the others) or collapse it. */
  onToggle: () => void
  /** Called after a successful status change so the parent can update its list. */
  onStatusChange: (id: string, status: ConversationStatus) => void
}

export default function ConversationCard({
  conversation,
  open,
  onToggle,
  onStatusChange,
}: Props) {
  const meta = STATUS_META[conversation.status]
  const bodyId = `conversation-body-${conversation.conversation_id}`

  // Lead/detail are lazily fetched the first time the row is opened.
  const [detail, setDetail] = useState<ConversationDetail | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)

  // Status-change in flight (used to disable the action buttons).
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  // The inline chat is shown once the owner takes the conversation over, or
  // straight away if it's already human-handled.
  const [showChat, setShowChat] = useState(conversation.status === 'human')

  // Outcome-note dialog: marking deal/closed requires a free-text note first.
  const [outcome, setOutcome] = useState<'deal' | 'closed' | null>(null)
  const [outcomeError, setOutcomeError] = useState<string | null>(null)

  // Load the detail when the row first opens (re-load if the id changes).
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoadingDetail(true)
    setDetailError(null)
    getConversation(conversation.conversation_id)
      .then((res) => {
        if (!cancelled) setDetail(res)
      })
      .catch((err) => {
        if (!cancelled) {
          setDetailError(toFriendlyError(err, 'טעינת פרטי השיחה נכשלה. נסו שוב.'))
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, conversation.conversation_id])

  // Keep the chat visible whenever the conversation is human-handled.
  useEffect(() => {
    if (conversation.status === 'human') setShowChat(true)
  }, [conversation.status])

  async function changeStatus(next: ConversationStatus) {
    if (busy || next === conversation.status) return
    setBusy(true)
    setActionError(null)
    try {
      const res = await setConversationStatus(conversation.conversation_id, next)
      onStatusChange(conversation.conversation_id, res.status)
      if (res.status === 'human') setShowChat(true)
    } catch (err) {
      setActionError(toFriendlyError(err, 'שינוי מצב השיחה נכשל. נסו שוב.'))
    } finally {
      setBusy(false)
    }
  }

  // Outcome buttons (M9/M10): a conversation is resolved as either a closed deal
  // or a plain closed enquiry, AND the owner must record a short outcome note.
  // The buttons open OutcomeNoteDialog; this runs on confirm. The LEAD status is
  // the source of truth, so we set it first (deal | closed + note) when a lead
  // is attached, then always close the live conversation so the bot stays
  // silent. If no lead is attached we just close.
  async function confirmOutcome(note: string) {
    if (!outcome || busy || conversation.status === 'closed') return
    setBusy(true)
    setOutcomeError(null)
    try {
      const lead = detail?.lead ?? null
      if (lead) {
        await setLeadStatus(lead.id, outcome, note)
      }
      const res = await setConversationStatus(
        conversation.conversation_id,
        'closed',
      )
      setOutcome(null)
      onStatusChange(conversation.conversation_id, res.status)
    } catch (err) {
      setOutcomeError(toFriendlyError(err, 'שינוי מצב השיחה נכשל. נסו שוב.'))
    } finally {
      setBusy(false)
    }
  }

  // "לשיחה עם הלקוח": take the conversation over (→ human) and reveal the chat.
  async function takeOver() {
    if (conversation.status !== 'human') {
      await changeStatus('human')
    } else {
      setShowChat(true)
    }
  }

  const lead = detail?.lead ?? null
  const answers = Object.entries(lead?.answers ?? {})
  // "Why it closed" (decision 0021) — additional context shown next to the live
  // status when the backend has stamped a close_reason.
  const closeMeta = closeReasonMeta(lead?.close_reason ?? null)

  return (
    <article className="overflow-hidden rounded-xl border border-black/10 bg-white dark:border-white/10 dark:bg-slate-800">
      {/* Accordion header — click to expand/collapse this conversation. */}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={bodyId}
        className="flex w-full items-center gap-3 px-4 py-3 text-right hover:bg-slate-50 dark:hover:bg-slate-700/50"
      >
        <span
          aria-hidden="true"
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-300"
        >
          <Icon name="message-circle" size={18} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-slate-900 dark:text-slate-100" dir="ltr">
            {conversation.conversation_id}
          </span>
          <span className="block truncate text-xs text-slate-500">
            {conversation.preview || 'אין הודעות עדיין'}
            {conversation.last_activity_at
              ? ` · ${relativeTime(conversation.last_activity_at)}`
              : ''}
          </span>
        </span>
        <Badge tone={meta.tone}>{meta.label}</Badge>
        <Icon
          name="chevron-down"
          size={18}
          className={`flex-shrink-0 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {/* Accordion body — lead details + actions + (optional) inline chat. */}
      {open ? (
        <div id={bodyId} className="border-t border-black/10 px-4 pb-4 pt-3 dark:border-white/10">
          {loadingDetail ? (
            <Spinner className="py-6" label="טוען פרטי שיחה…" />
          ) : detailError ? (
            <p role="alert" className="text-sm text-bad">
              {detailError}
            </p>
          ) : (
            <>
              {/* Linked lead's details (if any lead is attached). */}
              {lead ? (
                <div className="flex flex-col gap-3">
                  <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                    <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                      {lead.contact_name || 'ליד ללא שם'}
                    </p>
                    {lead.phone ? (
                      <p className="text-xs text-slate-500" dir="ltr">
                        {lead.phone}
                      </p>
                    ) : null}
                    {closeMeta ? (
                      <Badge tone={closeMeta.tone}>{closeMeta.label}</Badge>
                    ) : null}
                  </div>

                  {answers.length > 0 ? (
                    <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
                      {answers.map(([key, value]) => (
                        <div key={key} className="min-w-0">
                          <dt className="text-[11px] text-slate-400">{key}</dt>
                          <dd className="truncate text-sm text-slate-800 dark:text-slate-200" title={value}>
                            {value || <span className="text-slate-400">טרם נענה</span>}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  ) : (
                    <p className="text-sm text-slate-400">עדיין לא נאספו פרטים.</p>
                  )}
                </div>
              ) : (
                <p className="text-sm text-slate-400">לא משויך ליד לשיחה הזו.</p>
              )}

              {/* Actions */}
              <div
                className="mt-4 flex flex-wrap items-center gap-2"
                role="group"
                aria-label="טיפול בשיחה"
              >
                <Button
                  type="button"
                  onClick={() => void takeOver()}
                  disabled={busy}
                  className="!bg-leaf text-white hover:!bg-leaf-dark"
                >
                  <Icon name="users" size={16} />
                  {busy && conversation.status !== 'human'
                    ? 'מעביר…'
                    : 'לשיחה עם הלקוח'}
                </Button>

                {conversation.status !== 'closed' ? (
                  <>
                    <Button
                      type="button"
                      onClick={() => {
                        setOutcomeError(null)
                        setOutcome('deal')
                      }}
                      disabled={busy}
                      className="!bg-leaf text-white hover:!bg-leaf-dark"
                    >
                      <Icon name="checks" size={16} />
                      בוצעה עסקה
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => {
                        setOutcomeError(null)
                        setOutcome('closed')
                      }}
                      disabled={busy}
                    >
                      <Icon name="x" size={16} />
                      סגירת פנייה
                    </Button>
                  </>
                ) : null}

                {/* Hand back to the bot once a human is done. */}
                {conversation.status === 'human' ? (
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => void changeStatus('bot')}
                    disabled={busy}
                  >
                    <Icon name="robot" size={16} />
                    החזר לבוט
                  </Button>
                ) : null}
              </div>

              {actionError ? (
                <p role="alert" className="mt-2 text-xs text-bad">
                  {actionError}
                </p>
              ) : null}

              {/* Inline chat — revealed after takeover (or if already human). */}
              {showChat ? (
                <div className="mt-4 h-[28rem]">
                  <ChatPanel
                    conversationId={conversation.conversation_id}
                    status={conversation.status}
                    onStatusChange={onStatusChange}
                    fallbackAnswers={lead?.answers}
                    fallbackName={lead?.contact_name}
                    fallbackPhone={lead?.phone}
                  />
                </div>
              ) : null}

              <OutcomeNoteDialog
                outcome={outcome ?? 'deal'}
                open={outcome !== null}
                saving={busy}
                error={outcomeError}
                onCancel={() => {
                  if (!busy) setOutcome(null)
                }}
                onConfirm={(note) => void confirmOutcome(note)}
              />
            </>
          )}
        </div>
      ) : null}
    </article>
  )
}
