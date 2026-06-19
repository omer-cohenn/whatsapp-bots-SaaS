// One live conversation row: its id/preview, a status badge, a bot↔human↔closed
// control, and — when the owner has taken it over (status === 'human') — a reply
// box that queues a manual message via POST .../reply.
//
// State (status change + reply send) is owned here per-row so one slow request
// never blocks the rest of the list; the parent is told about a status change so
// its filtered view stays correct.

import { useState } from 'react'
import type { Conversation, ConversationStatus } from '../../dashboard/types'
import {
  replyToConversation,
  setConversationStatus,
} from '../../lib/dashboardClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { relativeTime } from '../../lib/formatDate'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import Icon from '../ui/Icon'

const STATUS_META: Record<
  ConversationStatus,
  { label: string; tone: 'leaf' | 'info' | 'neutral' }
> = {
  bot: { label: 'בוט', tone: 'leaf' },
  human: { label: 'נציג אנושי', tone: 'info' },
  closed: { label: 'סגור', tone: 'neutral' },
}

const MAX_REPLY = 2000

type Props = {
  conversation: Conversation
  /** Called after a successful status change so the parent can update its list. */
  onStatusChange: (id: string, status: ConversationStatus) => void
}

export default function ConversationCard({ conversation, onStatusChange }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [reply, setReply] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)

  const meta = STATUS_META[conversation.status]

  async function changeStatus(next: ConversationStatus) {
    if (busy || next === conversation.status) return
    setBusy(true)
    setError(null)
    try {
      const res = await setConversationStatus(conversation.conversation_id, next)
      onStatusChange(conversation.conversation_id, res.status)
    } catch (err) {
      setError(toFriendlyError(err, 'שינוי מצב השיחה נכשל. נסו שוב.'))
    } finally {
      setBusy(false)
    }
  }

  async function sendReply(e: React.FormEvent) {
    e.preventDefault()
    const text = reply.trim()
    if (!text || sending) return
    setSending(true)
    setError(null)
    setSent(false)
    try {
      await replyToConversation(conversation.conversation_id, text)
      setReply('')
      setSent(true)
    } catch (err) {
      setError(toFriendlyError(err, 'שליחת התגובה נכשלה. נסו שוב.'))
    } finally {
      setSending(false)
    }
  }

  const isHuman = conversation.status === 'human'

  return (
    <article className="flex flex-col gap-3 rounded-xl border border-black/10 bg-white p-4">
      <div className="flex items-center gap-3">
        <span
          aria-hidden="true"
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-500"
        >
          <Icon name="message-circle" size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-slate-900" dir="ltr">
            {conversation.conversation_id}
          </p>
          <p className="truncate text-xs text-slate-500">
            {conversation.preview || 'אין הודעות עדיין'}
            {conversation.last_activity_at
              ? ` · ${relativeTime(conversation.last_activity_at)}`
              : ''}
          </p>
        </div>
        <Badge tone={meta.tone}>{meta.label}</Badge>
      </div>

      {/* bot ↔ human ↔ closed control */}
      <div
        className="flex flex-wrap items-center gap-2"
        role="group"
        aria-label="מצב טיפול בשיחה"
      >
        <span className="text-xs text-slate-500">מצב טיפול:</span>
        <Button
          variant={conversation.status === 'bot' ? 'primary' : 'secondary'}
          onClick={() => void changeStatus('bot')}
          disabled={busy}
          aria-pressed={conversation.status === 'bot'}
          className={
            conversation.status === 'bot' ? '!bg-leaf px-3 py-1.5 text-xs hover:!bg-leaf-dark' : 'px-3 py-1.5 text-xs'
          }
        >
          <Icon name="robot" size={14} />
          בוט
        </Button>
        <Button
          variant={isHuman ? 'primary' : 'secondary'}
          onClick={() => void changeStatus('human')}
          disabled={busy}
          aria-pressed={isHuman}
          className={isHuman ? '!bg-leaf px-3 py-1.5 text-xs hover:!bg-leaf-dark' : 'px-3 py-1.5 text-xs'}
        >
          <Icon name="users" size={14} />
          נציג
        </Button>
        <Button
          variant={conversation.status === 'closed' ? 'primary' : 'secondary'}
          onClick={() => void changeStatus('closed')}
          disabled={busy}
          aria-pressed={conversation.status === 'closed'}
          className={
            conversation.status === 'closed'
              ? '!bg-slate-700 px-3 py-1.5 text-xs hover:!bg-slate-800'
              : 'px-3 py-1.5 text-xs'
          }
        >
          <Icon name="x" size={14} />
          סגור
        </Button>
      </div>

      {/* Reply box: only when a human is handling this chat. */}
      {isHuman ? (
        <form onSubmit={sendReply} className="flex flex-col gap-2 border-t border-black/10 pt-3">
          <label htmlFor={`reply-${conversation.conversation_id}`} className="sr-only">
            כתיבת תגובה לשיחה
          </label>
          <div className="flex items-end gap-2">
            <textarea
              id={`reply-${conversation.conversation_id}`}
              value={reply}
              maxLength={MAX_REPLY}
              rows={2}
              onChange={(e) => {
                setReply(e.target.value)
                setSent(false)
              }}
              placeholder="כתבו תגובה ללקוח…"
              className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400"
            />
            <Button
              type="submit"
              disabled={sending || !reply.trim()}
              className="!bg-leaf text-white hover:!bg-leaf-dark"
            >
              <Icon name="send" size={16} />
              {sending ? 'שולח…' : 'שלח'}
            </Button>
          </div>
          {sent ? (
            <p role="status" aria-live="polite" className="text-xs text-ok">
              התגובה נשלחה לתור השליחה.
            </p>
          ) : null}
        </form>
      ) : null}

      {error ? (
        <p role="alert" className="text-xs text-bad">
          {error}
        </p>
      ) : null}
    </article>
  )
}
