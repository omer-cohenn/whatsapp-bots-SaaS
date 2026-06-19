// "עוזר ה-AI שלך" — a half-window chat panel that helps the owner build the bot.
//
// Behavior (per the M4 contract):
//   * Opens as a right-side half-window dialog with a fixed greeting bubble.
//   * On open it loads GET /api/bot/ai/history (oldest→newest) to rehydrate.
//   * Sending a message POSTs /api/bot/ai/chat with the current working config.
//     The `reply` is shown; if `changes` is present it is the full validated
//     BotSettings — we apply it to the builder's in-memory config LIVE (the
//     parent updates immediately, before any save).
//   * Errors map to friendly Hebrew: 503 = AI not configured, 502 = temporary.
//
// A11y: role="dialog" + aria-modal, labelled by its heading; Escape closes and
// focus returns to the opener; the transcript is an aria-live log; the composer
// is a real <form> so Enter submits.

import { useEffect, useRef, useState } from 'react'
import { aiChat, aiHistory } from '../../lib/botClient'
import { ApiError } from '../../lib/apiClient'
import type { BotAiMessage, BotSettings } from '../../botbuilder/types'
import Button from '../ui/Button'
import Icon from '../ui/Icon'
import Spinner from '../ui/Spinner'
import Alert from '../ui/Alert'

const GREETING = 'היי, אני העוזר החכם שלך. במה אוכל לעזור לך היום?'

type ChatMessage = { role: 'user' | 'assistant'; content: string }

// The owner should never see raw JSON. The backend already sends plain language,
// but older history rows (and any stray fence) are scrubbed here too: strip every
// ```...``` block and tidy the leftover blank lines.
function stripFences(text: string): string {
  return text
    .replace(/```json[\s\S]*?```/gi, '')
    .replace(/```[\s\S]*?```/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

type Props = {
  open: boolean
  onClose: () => void
  /** Current working config, sent as untrusted prompt context. */
  config: BotSettings
  /** Apply a validated config change returned by the AI, live. */
  onApplyChanges: (next: BotSettings) => void
}

function toFriendlyError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 503) return 'עוזר ה-AI אינו זמין כרגע (לא הוגדר). נסו שוב מאוחר יותר.'
    if (err.status === 502) return 'עוזר ה-AI לא זמין זמנית. נסו שוב בעוד רגע.'
    if (err.status === 401) return 'פג תוקף ההתחברות. רעננו את העמוד והתחברו מחדש.'
  }
  return 'אירעה תקלה בשליחת ההודעה. נסו שוב.'
}

export default function AIChatPanel({ open, onClose, config, onApplyChanges }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // A short status announced politely when the AI updates the builder.
  const [appliedNote, setAppliedNote] = useState<string | null>(null)

  const inputRef = useRef<HTMLTextAreaElement>(null)
  const transcriptEndRef = useRef<HTMLDivElement>(null)
  // Remember the element that opened us, to restore focus on close.
  const openerRef = useRef<Element | null>(null)

  // Load history each time the panel opens.
  useEffect(() => {
    if (!open) return
    openerRef.current = document.activeElement
    let cancelled = false
    setError(null)
    setAppliedNote(null)
    setLoadingHistory(true)
    aiHistory()
      .then((res) => {
        if (cancelled) return
        const prior: ChatMessage[] = (res.messages ?? []).map((m: BotAiMessage) => ({
          role: m.role === 'user' ? 'user' : 'assistant',
          content: m.content,
        }))
        setMessages(prior)
      })
      .catch(() => {
        // History is best-effort; a failure shouldn't block chatting.
        if (!cancelled) setMessages([])
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingHistory(false)
          // Focus the composer once the panel is ready.
          requestAnimationFrame(() => inputRef.current?.focus())
        }
      })
    return () => {
      cancelled = true
    }
  }, [open])

  // Restore focus to the opener when closing.
  useEffect(() => {
    if (open) return
    const opener = openerRef.current
    if (opener instanceof HTMLElement) opener.focus()
  }, [open])

  // Keep the transcript scrolled to the latest message.
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, loadingHistory, sending])

  // Escape closes the dialog (document-level so it works regardless of which
  // element inside the panel has focus).
  useEffect(() => {
    if (!open) return
    function onEscape(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onEscape)
    return () => document.removeEventListener('keydown', onEscape)
  }, [open, onClose])

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    const text = input.trim()
    if (!text || sending) return
    setError(null)
    setAppliedNote(null)
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setSending(true)
    try {
      const res = await aiChat(text, config)
      setMessages((prev) => [...prev, { role: 'assistant', content: res.reply }])
      // A present `changes` is the full validated BotSettings — apply it live.
      if (res.changes) {
        onApplyChanges(res.changes)
        setAppliedNote('עוזר ה-AI עדכן את הבוט. בדקו ולחצו "שמור שינויים" כדי לשמור.')
      }
    } catch (err) {
      setError(toFriendlyError(err))
    } finally {
      setSending(false)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop (click to close). Decorative — the dialog owns the a11y. */}
      <button
        type="button"
        aria-label="סגירת עוזר ה-AI"
        onClick={onClose}
        className="flex-1 bg-black/30"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="ai-panel-title"
        className="flex h-full w-full max-w-md flex-col bg-white shadow-xl sm:w-[min(28rem,50vw)]"
      >
        <header className="flex items-center justify-between gap-2 border-b border-slate-200 bg-leaf-dark px-4 py-3">
          <h2 id="ai-panel-title" className="flex items-center gap-2 text-base font-medium text-white">
            <Icon name="sparkles" size={18} />
            עוזר ה-AI שלך
          </h2>
          <Button
            variant="ghost"
            onClick={onClose}
            aria-label="סגור"
            className="px-2 py-1 text-white hover:bg-white/10"
          >
            <Icon name="x" size={18} />
          </Button>
        </header>

        {/* Transcript */}
        <div className="flex-1 space-y-3 overflow-y-auto bg-slate-50 px-4 py-4">
          <p className="max-w-[85%] rounded-2xl rounded-tr-sm border border-slate-200 bg-white px-3.5 py-2 text-sm text-slate-800">
            {GREETING}
          </p>

          {loadingHistory ? (
            <Spinner label="טוען שיחה…" className="py-4" />
          ) : null}

          <ul aria-live="polite" aria-busy={sending} className="space-y-3">
            {messages.map((m, i) => (
              <li
                key={i}
                className={m.role === 'user' ? 'flex justify-start' : 'flex justify-end'}
              >
                <span
                  className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm ${
                    m.role === 'user'
                      ? 'rounded-tl-sm bg-leaf text-white'
                      : 'rounded-tr-sm border border-slate-200 bg-white text-slate-800'
                  }`}
                >
                  <span className="sr-only">{m.role === 'user' ? 'את/ה: ' : 'העוזר: '}</span>
                  {m.role === 'user' ? m.content : stripFences(m.content) || '✅ השינויים הוחלו.'}
                </span>
              </li>
            ))}
          </ul>

          {sending ? (
            <p className="flex justify-end">
              <span className="rounded-2xl rounded-tr-sm border border-slate-200 bg-white px-3.5 py-2 text-sm text-slate-500">
                העוזר מקליד…
              </span>
            </p>
          ) : null}

          <div ref={transcriptEndRef} />
        </div>

        {/* Status / errors */}
        {appliedNote ? (
          <div className="px-4 pt-3">
            <Alert tone="info">{appliedNote}</Alert>
          </div>
        ) : null}
        {error ? (
          <div className="px-4 pt-3">
            <Alert tone="error">{error}</Alert>
          </div>
        ) : null}

        {/* Composer */}
        <form onSubmit={onSubmit} className="flex items-end gap-2 border-t border-slate-200 p-3">
          <label htmlFor="ai-chat-input" className="sr-only">
            הודעה לעוזר ה-AI
          </label>
          <textarea
            id="ai-chat-input"
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends; Shift+Enter makes a newline.
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void onSubmit(e)
              }
            }}
            rows={1}
            maxLength={8000}
            placeholder="כתוב הודעה... (אפשר גם לתאר בוט שלם ואבנה אותו)"
            className="max-h-32 flex-1 resize-none rounded-2xl border border-slate-300 px-3.5 py-2 text-sm text-slate-900 placeholder:text-slate-400"
          />
          <Button
            type="submit"
            disabled={sending || input.trim().length === 0}
            aria-label="שלח הודעה"
            className="h-10 w-10 flex-shrink-0 rounded-full bg-leaf p-0 text-white hover:bg-leaf-dark"
          >
            <Icon name="send" size={18} />
          </Button>
        </form>
      </div>
    </div>
  )
}
