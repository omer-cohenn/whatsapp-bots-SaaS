// Conversations page (M7, route /conversations). The live conversation list
// (newest activity first), filterable by status, with a per-conversation
// bot↔human↔closed control and a reply box for human-handled chats.
//
// One read: GET /api/conversations (optionally filtered by status). A status
// change updates the in-memory list so the row reflects its new state without a
// full refetch (and falls out of view if it no longer matches the filter). The
// tenant is always derived server-side from the session.

import { useCallback, useEffect, useState } from 'react'
import DashboardLayout from '../components/DashboardLayout'
import ConversationCard from '../components/dashboard/ConversationCard'
import SegmentedControl, { type Segment } from '../components/dashboard/SegmentedControl'
import Button from '../components/ui/Button'
import Spinner from '../components/ui/Spinner'
import Alert from '../components/ui/Alert'
import Icon from '../components/ui/Icon'
import { getConversations } from '../lib/dashboardClient'
import { toFriendlyError } from '../lib/friendlyError'
import type { Conversation, ConversationStatus } from '../dashboard/types'

type StatusFilter = 'all' | ConversationStatus

const FILTER_SEGMENTS: Segment<StatusFilter>[] = [
  { value: 'all', label: 'הכול' },
  { value: 'bot', label: 'בוט' },
  { value: 'human', label: 'נציג' },
  { value: 'closed', label: 'סגורות' },
]

export default function ConversationsPage() {
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [conversations, setConversations] = useState<Conversation[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback((statusFilter: StatusFilter) => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getConversations(statusFilter === 'all' ? undefined : statusFilter)
      .then((res) => {
        if (!cancelled) setConversations(res.conversations)
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
  }, [])

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

        <SegmentedControl
          label="סינון לפי מצב"
          segments={FILTER_SEGMENTS}
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
            <ul className="flex flex-col gap-3">
              {conversations.map((conv) => (
                <li key={conv.conversation_id}>
                  <ConversationCard
                    conversation={conv}
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
