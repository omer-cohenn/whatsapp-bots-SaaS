// Conversations page (M7, route /conversations). The live conversation list
// (newest activity first), filterable by status, with a per-conversation
// bot↔human↔closed control and a reply box for human-handled chats.
//
// One read: GET /api/conversations (optionally filtered by status). A status
// change updates the in-memory list so the row reflects its new state without a
// full refetch (and falls out of view if it no longer matches the filter). The
// tenant is always derived server-side from the session.

import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import DashboardLayout from '../components/DashboardLayout'
import ConversationCard from '../components/dashboard/ConversationCard'
import ChatTabs, { type ChatTab } from '../components/dashboard/ChatTabs'
import Button from '../components/ui/Button'
import Spinner from '../components/ui/Spinner'
import Alert from '../components/ui/Alert'
import Icon from '../components/ui/Icon'
import { getConversations } from '../lib/dashboardClient'
import { toFriendlyError } from '../lib/friendlyError'
import { useUnread } from '../dashboard/UnreadContext'
import type { Conversation, ConversationStatus } from '../dashboard/types'

type StatusFilter = 'all' | ConversationStatus

// Four tabs, WhatsApp-style. There is deliberately NO "נטוש" tab: abandonment
// is a LEAD state (close_reason), not a conversation state — the conversation
// statuses are only bot | waiting | human | closed. Abandoned leads live on the
// leads page, under its own "נטשו" filter.
const FILTER_TABS: ChatTab<StatusFilter>[] = [
  { value: 'waiting', label: 'ממתינות' },
  { value: 'bot', label: 'בוט' },
  { value: 'human', label: 'נציג' },
  { value: 'closed', label: 'סגורות' },
]

export default function ConversationsPage() {
  const { refresh: refreshUnread } = useUnread()
  const [filter, setFilter] = useState<StatusFilter>('waiting')
  const [conversations, setConversations] = useState<Conversation[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Accordion: id of the expanded row (null = all collapsed, one open at a time).
  const [openId, setOpenId] = useState<string | null>(null)

  // Deep-link support: the home "מחכים לך" notifications link here with
  // ?conversation=<id> to open that row straight away.
  const [searchParams] = useSearchParams()
  const focusId = searchParams.get('conversation')
  useEffect(() => {
    if (focusId) setOpenId(focusId)
  }, [focusId])

  const load = useCallback((statusFilter: StatusFilter) => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getConversations(statusFilter === 'all' ? undefined : statusFilter)
      .then((res) => {
        if (!cancelled) {
          setConversations(res.conversations)
          // Keep the nav badge in sync with the freshly-fetched total.
          refreshUnread()
        }
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err, 'טעינת השיחות נכשלה. נסו שוב.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [refreshUnread])

  useEffect(() => load(filter), [load, filter])

  // After a row changes status: update it in place, and drop it if it no longer
  // matches the active filter.
  const handleStatusChange = useCallback(
    (id: string, status: ConversationStatus) => {
      setConversations((prev) => {
        if (!prev) return prev
        return prev
          .map((c) => (c.conversation_id === id ? { ...c, status } : c))
          .filter((c) => filter === 'all' || c.status === filter)
      })
    },
    [filter],
  )

  return (
    <DashboardLayout>
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
            <Icon name="message-circle" size={22} className="text-leaf" />
            שיחות
          </h1>
          <Button variant="secondary" onClick={() => load(filter)} disabled={loading}>
            <Icon name="refresh" size={16} />
            רענון
          </Button>
        </div>

        {/* WhatsApp-style tab bar (M18). The counts come from the CURRENT list,
            so only the active tab can show one — the others aren't loaded. That
            is deliberate: a per-tab count would need a separate request per tab
            on every render. */}
        <ChatTabs
          label="סינון לפי מצב"
          tabs={FILTER_TABS.map((t) => ({
            ...t,
            count:
              t.value === filter
                ? (conversations ?? []).reduce((n, c) => n + (c.unread || 0), 0)
                : undefined,
          }))}
          value={filter}
          onChange={setFilter}
        />

        <section aria-labelledby="conversations-heading" aria-busy={loading}>
          <h2 id="conversations-heading" className="sr-only">
            רשימת השיחות
          </h2>
          {loading ? (
            <Spinner label="טוען שיחות…" className="py-12" />
          ) : error ? (
            <Alert tone="error">{error}</Alert>
          ) : conversations && conversations.length > 0 ? (
            <ul className="divide-y divide-black/5 overflow-hidden rounded-xl border border-black/10 bg-white dark:divide-white/5 dark:border-white/10 dark:bg-slate-800">
              {conversations.map((conv) => (
                <li key={conv.conversation_id}>
                  <ConversationCard
                    conversation={conv}
                    open={openId === conv.conversation_id}
                    onToggle={() =>
                      setOpenId((cur) => {
                        const next =
                          cur === conv.conversation_id
                            ? null
                            : conv.conversation_id
                        // Opening a row loads GET /api/conversations/{id}, which
                        // resets that conversation's unread to 0 server-side —
                        // refresh the badge shortly after so it reflects that.
                        if (next) {
                          setConversations((list) =>
                            list
                              ? list.map((c) =>
                                  c.conversation_id === next
                                    ? { ...c, unread: 0 }
                                    : c,
                                )
                              : list,
                          )
                          window.setTimeout(refreshUnread, 600)
                        }
                        return next
                      })
                    }
                    onStatusChange={handleStatusChange}
                  />
                </li>
              ))}
            </ul>
          ) : (
            <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-12 text-center text-sm text-slate-500">
              אין שיחות פעילות כרגע.
            </p>
          )}
        </section>
      </div>
    </DashboardLayout>
  )
}
