// "נסה אותי" (M5) — a WhatsApp-style test chat that lets the OWNER play the
// part of a customer and see exactly how their bot would reply, end to end.
//
// How it works (against the frozen /api/bot/tryme contract):
//   * On open we POST tryMe('', null) — an empty message with a null state — to
//     fetch the greeting + menu. The response carries an opaque `state`.
//   * We hold that `state` in React and echo it back on EVERY turn (the client
//     never inspects or trusts it; the tenant is server-side from the session).
//   * Sending a message appends the owner's bubble immediately, POSTs the turn,
//     then appends each `reply` as a bot bubble.
//   * event === 'lead_completed' → render `lead` as a small card (test only, not
//     saved). event === 'handed_off' → a subtle "would hand off" note.
//   * "התחל מחדש" clears the transcript and re-opens with a fresh state.
//
// Nothing here is persisted: the lead card is just this conversation's own typed
// answers, shown to reassure the owner, then discarded.
//
// A11y: a labelled chat region; the transcript is an aria-live log so screen
// readers announce bot replies; the composer is a real <form> (Enter submits);
// visible focus + reduced-motion come from the global theme.

import { useCallback, useEffect, useRef, useState } from 'react'
import DashboardLayout from '../components/DashboardLayout'
import Button from '../components/ui/Button'
import Icon from '../components/ui/Icon'
import Spinner from '../components/ui/Spinner'
import Alert from '../components/ui/Alert'
import Badge from '../components/ui/Badge'
import { tryMe } from '../lib/botClient'
import { ApiError } from '../lib/apiClient'
import type { ConvState, TryMeEvent } from '../botbuilder/types'

// Mirror AIChatPanel.toFriendlyError: friendly Hebrew for 401 / 5xx / network.
function toFriendlyError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return 'פג תוקף ההתחברות. רעננו את העמוד והתחברו מחדש.'
    if (err.status === 0) return 'אין חיבור לשרת. בדקו את החיבור ונסו שוב.'
    if (err.status >= 500) return 'אירעה תקלה זמנית בשרת. נסו שוב בעוד רגע.'
  }
  return 'אירעה תקלה בשליחת ההודעה. נסו שוב.'
}

// A single thing rendered in the transcript: a chat bubble, a collected-lead
// card, or the handoff note. Each is identified for a stable React key.
type Bubble = { kind: 'bubble'; id: number; from: 'customer' | 'bot'; text: string }
type LeadCard = { kind: 'lead'; id: number; lead: Record<string, string> }
type HandoffNote = { kind: 'handoff'; id: number }
type Entry = Bubble | LeadCard | HandoffNote

let entrySeq = 0
function nextId(): number {
  entrySeq += 1
  return entrySeq
}

export default function TryMePage() {
  const [entries, setEntries] = useState<Entry[]>([])
  const [state, setState] = useState<ConvState>(null)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [opening, setOpening] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const inputRef = useRef<HTMLTextAreaElement>(null)
  const transcriptEndRef = useRef<HTMLDivElement>(null)

  // Apply a tryMe response to the transcript + held state.
  const applyResponse = useCallback(
    (replies: string[], nextState: ConvState, event: TryMeEvent | null, lead: Record<string, string> | null) => {
      setState(nextState)
      setEntries((prev) => {
        const added: Entry[] = replies.map((text) => ({ kind: 'bubble', id: nextId(), from: 'bot', text }))
        if (event === 'lead_completed' && lead) {
          added.push({ kind: 'lead', id: nextId(), lead })
        } else if (event === 'handed_off') {
          added.push({ kind: 'handoff', id: nextId() })
        }
        return [...prev, ...added]
      })
    },
    [],
  )

  // (Re)open the chat with a fresh state: empty message → greeting + menu.
  const open = useCallback(() => {
    let cancelled = false
    setError(null)
    setOpening(true)
    setEntries([])
    setState(null)
    setInput('')
    tryMe('', null)
      .then((res) => {
        if (cancelled) return
        applyResponse(res.replies, res.state, res.event, res.lead)
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err))
      })
      .finally(() => {
        if (!cancelled) {
          setOpening(false)
          requestAnimationFrame(() => inputRef.current?.focus())
        }
      })
    return () => {
      cancelled = true
    }
  }, [applyResponse])

  // Open once on mount.
  useEffect(() => open(), [open])

  // Keep the transcript scrolled to the latest entry.
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ block: 'end' })
  }, [entries, opening, sending])

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    const text = input.trim()
    if (!text || sending || opening) return
    setError(null)
    setInput('')
    setEntries((prev) => [...prev, { kind: 'bubble', id: nextId(), from: 'customer', text }])
    setSending(true)
    try {
      const res = await tryMe(text, state)
      applyResponse(res.replies, res.state, res.event, res.lead)
    } catch (err) {
      setError(toFriendlyError(err))
    } finally {
      setSending(false)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }

  function onReset() {
    if (sending) return
    open()
  }

  return (
    <DashboardLayout>
      <div className="mx-auto flex w-full max-w-2xl flex-col px-4 py-6 sm:px-6">
        {/* Header */}
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
              <Icon name="player-play" size={22} className="text-leaf" />
              נסה אותי
            </h1>
            <p className="mt-1 text-sm text-slate-600">
              דברו עם הבוט כאילו אתם לקוח. זהו מצב בדיקה — שום דבר לא נשמר.
            </p>
          </div>
          <Button onClick={onReset} disabled={sending || opening} variant="secondary">
            <Icon name="player-play" size={16} />
            התחל מחדש
          </Button>
        </div>

        {/* WhatsApp-style chat window */}
        <section
          aria-label="צ׳אט בדיקה עם הבוט"
          className="flex h-[70vh] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
        >
          {/* Chat bar (mimics a WhatsApp conversation header). */}
          <header className="flex items-center gap-3 border-b border-slate-200 bg-leaf-dark px-4 py-3 text-white">
            <span
              aria-hidden="true"
              className="flex h-9 w-9 items-center justify-center rounded-full bg-leaf"
            >
              <Icon name="robot" size={20} />
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">הבוט שלך</p>
              <p className="truncate text-xs text-leaf-light">מצב בדיקה</p>
            </div>
          </header>

          {/* Transcript */}
          <div className="flex-1 space-y-3 overflow-y-auto bg-[#ece9e1] px-4 py-4">
            {opening ? <Spinner label="פותח שיחה…" className="py-6" /> : null}

            <ul aria-live="polite" aria-busy={sending} className="space-y-3">
              {entries.map((entry) => {
                if (entry.kind === 'bubble') {
                  const isCustomer = entry.from === 'customer'
                  return (
                    <li
                      key={entry.id}
                      className={isCustomer ? 'flex justify-start' : 'flex justify-end'}
                    >
                      <span
                        className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm shadow-sm ${
                          isCustomer
                            ? 'rounded-tl-sm bg-leaf text-white'
                            : 'rounded-tr-sm border border-slate-200 bg-white text-slate-800'
                        }`}
                      >
                        <span className="sr-only">{isCustomer ? 'את/ה: ' : 'הבוט: '}</span>
                        {entry.text}
                      </span>
                    </li>
                  )
                }
                if (entry.kind === 'lead') {
                  return (
                    <li key={entry.id} className="flex justify-end">
                      <div className="max-w-[85%] rounded-2xl border border-leaf/30 bg-leaf-soft px-4 py-3 text-sm text-leaf-ink shadow-sm">
                        <p className="mb-2 flex items-center gap-2 font-medium">
                          <Icon name="users" size={16} />
                          זה מה שהיה נאסף (במצב בדיקה — לא נשמר)
                        </p>
                        <dl className="space-y-1">
                          {Object.entries(entry.lead).map(([key, value]) => (
                            <div key={key} className="flex gap-2">
                              <dt className="font-medium text-leaf-ink">{key}:</dt>
                              <dd className="min-w-0 break-words text-leaf-ink/90">{value}</dd>
                            </div>
                          ))}
                        </dl>
                      </div>
                    </li>
                  )
                }
                // handoff note
                return (
                  <li key={entry.id} className="flex justify-center">
                    <span className="flex items-center gap-2 rounded-full bg-white/70 px-3 py-1 text-xs text-slate-600">
                      <Icon name="users" size={14} />
                      כאן הבוט היה מעביר את השיחה לנציג אנושי.
                    </span>
                  </li>
                )
              })}
            </ul>

            {sending ? (
              <p className="flex justify-end">
                <span className="rounded-2xl rounded-tr-sm border border-slate-200 bg-white px-3.5 py-2 text-sm text-slate-500 shadow-sm">
                  הבוט מקליד…
                </span>
              </p>
            ) : null}

            <div ref={transcriptEndRef} />
          </div>

          {/* Error (announced via Alert's live region). */}
          {error ? (
            <div className="border-t border-slate-200 px-4 py-3">
              <Alert tone="error">{error}</Alert>
            </div>
          ) : null}

          {/* Composer */}
          <form onSubmit={onSubmit} className="flex items-end gap-2 border-t border-slate-200 bg-white p-3">
            <label htmlFor="tryme-input" className="sr-only">
              הודעה כלקוח
            </label>
            <textarea
              id="tryme-input"
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
              maxLength={2000}
              disabled={opening}
              placeholder="כתבו הודעה כאילו אתם לקוח…"
              className="max-h-32 flex-1 resize-none rounded-2xl border border-slate-300 px-3.5 py-2 text-sm text-slate-900 placeholder:text-slate-400 disabled:bg-slate-50"
            />
            <Button
              type="submit"
              disabled={sending || opening || input.trim().length === 0}
              aria-label="שלח הודעה"
              className="h-10 w-10 flex-shrink-0 rounded-full !bg-leaf p-0 text-white hover:!bg-leaf-dark"
            >
              <Icon name="send" size={18} />
            </Button>
          </form>
        </section>

        {/* Coming-soon hint for booking, which the engine flags but doesn't run. */}
        <p className="mt-3 text-center text-xs text-slate-500">
          <Badge tone="neutral">טיפ</Badge>{' '}
          כתבו "תפריט" בכל שלב כדי לחזור לתפריט הראשי.
        </p>
      </div>
    </DashboardLayout>
  )
}
