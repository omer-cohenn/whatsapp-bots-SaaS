// A WhatsApp-style chat view for a single conversation. It loads the transcript,
// polls for new messages every few seconds while mounted, and lets the owner
// queue a manual reply (POST .../reply). The reply is shown optimistically as an
// "owner" bubble, then the next refresh reconciles with the server.
//
// Tenant scoping is entirely server-side: we pass only the conversationId, and
// the backend resolves the business from the session cookie.

import { useEffect, useRef, useState } from 'react'
import type { ConversationStatus, Message } from '../../dashboard/types'
import {
  getConversationMessages,
  replyToConversation,
} from '../../lib/dashboardClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { relativeTime } from '../../lib/formatDate'
import Alert from '../ui/Alert'
import Button from '../ui/Button'
import Icon from '../ui/Icon'
import Spinner from '../ui/Spinner'
import EmojiPicker from './EmojiPicker'

// How often (ms) we re-fetch the transcript while the panel is open.
const POLL_MS = 4000
const MAX_REPLY = 2000

type Props = {
  conversationId: string
  status: ConversationStatus
  /**
   * Called when the owner sends a reply while the chat is in bot/waiting mode,
   * so the parent can flip the conversation to "human" (taking it over). The
   * parent owns the actual status mutation; here we only signal intent.
   */
  onStatusChange?: (id: string, status: ConversationStatus) => void
}

export default function ChatPanel({
  conversationId,
  status,
  onStatusChange,
}: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  // The scrollable transcript container — we scroll THIS element only, never the
  // page (scrollIntoView would yank every scrollable ancestor, incl. the window).
  const logRef = useRef<HTMLDivElement>(null)
  // Set while a reply is in flight, so a poll arriving mid-send doesn't wipe the
  // optimistic bubble before the server has recorded it.
  const pendingRef = useRef(false)

  // Load + poll the transcript. Re-runs if the conversation changes.
  useEffect(() => {
    let active = true

    async function refresh(initial: boolean) {
      try {
        const res = await getConversationMessages(conversationId)
        if (!active || pendingRef.current) return
        setMessages(res.messages)
        setLoadError(null)
      } catch (err) {
        if (!active) return
        // Only surface the error on the first load; transient poll failures
        // shouldn't replace a transcript the owner is reading.
        if (initial) setLoadError(toFriendlyError(err, 'טעינת השיחה נכשלה.'))
      } finally {
        if (active && initial) setLoading(false)
      }
    }

    setLoading(true)
    setMessages([])
    void refresh(true)
    const timer = window.setInterval(() => void refresh(false), POLL_MS)

    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [conversationId])

  // On first load (spinner → messages), jump the transcript to the newest line.
  useEffect(() => {
    if (!loading && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [loading])

  // On every poll/new message, keep the transcript pinned to the bottom — BUT
  // only if the owner is already near the bottom, and ONLY by scrolling the
  // transcript container itself (never the page). This stops the leads page from
  // jumping on each 4s poll while the owner scrolls.
  useEffect(() => {
    const el = logRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120
    if (nearBottom) el.scrollTop = el.scrollHeight
  }, [messages])

  function insertEmoji(emoji: string) {
    const el = textareaRef.current
    if (!el) {
      setDraft((prev) => prev + emoji)
      return
    }
    const start = el.selectionStart ?? draft.length
    const end = el.selectionEnd ?? draft.length
    const next = draft.slice(0, start) + emoji + draft.slice(end)
    setDraft(next)
    // Restore the caret just after the inserted emoji on the next tick.
    requestAnimationFrame(() => {
      el.focus()
      const pos = start + emoji.length
      el.setSelectionRange(pos, pos)
    })
  }

  async function send() {
    const text = draft.trim()
    if (!text || sending) return
    setSending(true)
    setSendError(null)
    pendingRef.current = true

    // Optimistic owner bubble.
    const optimistic: Message = {
      role: 'owner',
      body: text,
      at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, optimistic])
    setDraft('')

    try {
      await replyToConversation(conversationId, text)
      // If the owner replied while the bot was handling it, signal a takeover.
      if (status !== 'human') {
        onStatusChange?.(conversationId, 'human')
      }
      // Reconcile with the server (the reply is now in the transcript).
      pendingRef.current = false
      const res = await getConversationMessages(conversationId)
      setMessages(res.messages)
    } catch (err) {
      // Roll the optimistic bubble back and let the owner retry.
      setMessages((prev) => prev.filter((m) => m !== optimistic))
      setDraft(text)
      setSendError(toFriendlyError(err, 'שליחת התגובה נכשלה. נסו שוב.'))
    } finally {
      pendingRef.current = false
      setSending(false)
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter inserts a newline.
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send()
    }
  }

  return (
    <section
      className="flex h-full min-h-0 flex-col rounded-xl border border-black/10 bg-white"
      aria-label="שיחה"
    >
      {/* Transcript */}
      <div
        ref={logRef}
        className="flex-1 space-y-2 overflow-y-auto p-4"
        role="log"
        aria-live="polite"
        aria-label="הודעות השיחה"
      >
        {loading ? (
          <Spinner className="py-8" label="טוען שיחה…" />
        ) : loadError ? (
          <Alert tone="error">{loadError}</Alert>
        ) : messages.length === 0 ? (
          <p className="py-8 text-center text-sm text-slate-500">
            אין הודעות בשיחה הזו עדיין.
          </p>
        ) : (
          messages.map((msg, i) => <Bubble key={i} message={msg} />)
        )}
      </div>

      {/* Composer */}
      <div className="border-t border-black/10 p-3">
        <div className="flex items-end gap-2">
          <EmojiPicker onPick={insertEmoji} disabled={sending} />
          <label htmlFor="chat-reply" className="sr-only">
            כתיבת תגובה ללקוח
          </label>
          <textarea
            id="chat-reply"
            ref={textareaRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            maxLength={MAX_REPLY}
            rows={1}
            placeholder="כתבו תגובה… (Enter לשליחה, Shift+Enter לשורה חדשה)"
            className="max-h-32 min-h-[2.5rem] min-w-0 flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400"
          />
          <Button
            type="button"
            onClick={() => void send()}
            disabled={sending || !draft.trim()}
            className="!bg-leaf text-white hover:!bg-leaf-dark"
          >
            <Icon name="send" size={16} />
            {sending ? 'שולח…' : 'שלח'}
          </Button>
        </div>
        {sendError ? (
          <p role="alert" className="mt-2 text-xs text-bad">
            {sendError}
          </p>
        ) : null}
      </div>
    </section>
  )
}

// --- one message bubble ------------------------------------------------------

// customer → start (right edge in RTL, "their" side), owner → end ("our" side),
// bot → centred, subtle and muted so it reads as an automated line.
function Bubble({ message }: { message: Message }) {
  const time = relativeTime(message.at)

  if (message.role === 'bot') {
    return (
      <div className="flex justify-center">
        <div className="max-w-[85%] rounded-lg bg-slate-50 px-3 py-1.5 text-center text-xs text-slate-500">
          <span className="me-1 font-medium">בוט:</span>
          <span className="whitespace-pre-wrap break-words">{message.body}</span>
        </div>
      </div>
    )
  }

  const isOwner = message.role === 'owner'
  return (
    <div className={`flex ${isOwner ? 'justify-end' : 'justify-start'}`}>
      <div
        className={[
          'max-w-[80%] rounded-2xl px-3 py-2 text-sm',
          isOwner
            ? 'rounded-ee-sm bg-leaf-soft text-leaf-ink'
            : 'rounded-es-sm bg-slate-100 text-slate-900',
        ].join(' ')}
      >
        <p className="whitespace-pre-wrap break-words">{message.body}</p>
        {time ? (
          <p
            className={`mt-1 text-[11px] ${
              isOwner ? 'text-leaf-ink/70' : 'text-slate-400'
            }`}
          >
            {time}
          </p>
        ) : null}
      </div>
    </div>
  )
}
