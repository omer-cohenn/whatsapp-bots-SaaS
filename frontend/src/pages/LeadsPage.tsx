// Leads page (M7, route /leads). Shows EVERY collected lead with its full
// decrypted answers (the owner wants no hiding), filterable by status (incl.
// "חדש" / "פתוח") and by flow type, searchable by free text, and exportable to
// .xlsx (M17).
//
// One read: GET /api/leads (filtered server-side by status/period/flow). A
// SECOND fetch pulls the abandoned leads on their own. That second list is no
// longer RENDERED as its own section — it was a permanent duplicate of the
// "נטשו" status tab — but it is still fetched, because the "ננטשו" KPI count and
// the flow-filter options are derived from it. The tenant is server-side only.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import DashboardLayout from '../components/DashboardLayout'
import LeadCard from '../components/dashboard/LeadCard'
import StatCard from '../components/dashboard/StatCard'
import SegmentedControl, { type Segment } from '../components/dashboard/SegmentedControl'
import Select from '../components/ui/Select'
import Spinner from '../components/ui/Spinner'
import Alert from '../components/ui/Alert'
import Icon from '../components/ui/Icon'
import Button from '../components/ui/Button'
import { getLeads, leadsExportUrl } from '../lib/dashboardClient'
import { leadMatches } from '../dashboard/leadSearch'
import { toFriendlyError } from '../lib/friendlyError'
import type { Lead, LeadStatusFilter } from '../dashboard/types'

// Filter chips. "ליד שלם" maps to the backend `new` status (a completed lead);
// פתוחים → in_progress; נטשו → abandoned; "בוצעה עסקה" → deal; נסגרו → closed.
// הכול shows everything (incl. deal/closed). deal/closed work server-side now.
const STATUS_SEGMENTS: Segment<LeadStatusFilter>[] = [
  { value: 'in_progress', label: 'פתוחים' },
  { value: 'new', label: 'ליד שלם' },
  { value: 'deal', label: 'בוצעה עסקה' },
  { value: 'closed', label: 'נסגרו' },
  { value: 'abandoned', label: 'נטשו' },
  { value: 'all', label: 'הכול' },
]

export default function LeadsPage() {
  // Deep link from the home feed: /leads?highlight=<lead id> opens the page on
  // the "הכול" filter (so the lead is guaranteed to be in the list), scrolls to
  // its card and flashes it briefly.
  const [searchParams, setSearchParams] = useSearchParams()
  const highlightId = searchParams.get('highlight')

  const [status, setStatus] = useState<LeadStatusFilter>(highlightId ? 'all' : 'in_progress')
  const [flow, setFlow] = useState<string>('all')

  // Free-text search. Purely CLIENT-SIDE: the searchable fields (name, phone,
  // answers) are encrypted at rest, so SQL can't match them — but the browser
  // already holds every decrypted lead, so we filter the arrays in memory.
  const [query, setQuery] = useState('')

  // Main list (respects the status + flow filters).
  const [leads, setLeads] = useState<Lead[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // The abandoned ("נוטשים") list — always fetched separately.
  const [abandoned, setAbandoned] = useState<Lead[]>([])

  const flowParam = flow === 'all' ? undefined : flow

  const load = useCallback((statusFilter: LeadStatusFilter, flowFilter?: string) => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([
      getLeads({ status: statusFilter, flow: flowFilter }),
      getLeads({ status: 'abandoned', flow: flowFilter }),
    ])
      .then(([main, aband]) => {
        if (cancelled) return
        setLeads(main.leads)
        setAbandoned(aband.leads)
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err, 'טעינת הלידים נכשלה. נסו שוב.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => load(status, flowParam), [load, status, flowParam])

  // Once the list is on screen, scroll to the deep-linked lead and flash it,
  // then drop the query param so a refresh doesn't re-flash.
  useEffect(() => {
    if (!highlightId || loading || !leads) return
    const el = document.getElementById(`lead-${highlightId}`)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('ring-2', 'ring-leaf', 'rounded-xl')
    const timer = window.setTimeout(() => {
      el.classList.remove('ring-2', 'ring-leaf', 'rounded-xl')
      setSearchParams({}, { replace: true })
    }, 2500)
    return () => window.clearTimeout(timer)
  }, [highlightId, loading, leads, setSearchParams])

  // After a manual status change on a card, refetch the current view.
  const refresh = useCallback(() => {
    load(status, flowParam)
  }, [load, status, flowParam])

  // Flow filter options come from whatever flows currently appear in the data.
  const flowOptions = useMemo(() => {
    const names = new Set<string>()
    for (const l of leads ?? []) names.add(l.lead_name)
    for (const l of abandoned) names.add(l.lead_name)
    return [
      { value: 'all', label: 'כל המסלולים' },
      ...[...names].sort().map((n) => ({ value: n, label: n })),
    ]
  }, [leads, abandoned])

  // The search narrows the VIEW only — the KPI cards below stay on the
  // unfiltered numbers.
  const trimmedQuery = query.trim()
  const searching = trimmedQuery !== ''
  const visibleLeads = useMemo(
    () => (searching ? (leads ?? []).filter((l) => leadMatches(l, trimmedQuery)) : leads),
    [leads, searching, trimmedQuery],
  )

  // KPI counts off the full (status=all) picture. Deliberately computed from the
  // UNFILTERED lists: a search narrows what you look at, not what you have — the
  // stats must keep showing the whole picture.
  // Only computable when the
  // current filter is 'all' (that's when `leads` holds every lead). "ליד שלם" =
  // the backend `new` status; פתוחים = in_progress; ננטשו from the abandoned list.
  const counts = useMemo(() => {
    const all = status === 'all' ? leads ?? [] : null
    return {
      completedCount: all ? all.filter((l) => l.status === 'new').length : null,
      openCount: all ? all.filter((l) => l.status === 'in_progress').length : null,
      abandonedCount: abandoned.length,
    }
  }, [leads, abandoned, status])

  // Nothing to export while loading, on error, or when the visible list is empty.
  const exportDisabled = loading || !!error || (visibleLeads?.length ?? 0) === 0

  return (
    <DashboardLayout>
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-4 py-6 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
            <Icon name="users" size={22} className="text-leaf" />
            לידים
          </h1>
        </div>

        {/* KPI cards (when we can compute them, i.e. status=all) */}
        {counts.completedCount !== null ? (
          <div className="grid grid-cols-3 gap-3" aria-label="סיכום לידים">
            <StatCard
              icon="checks"
              chipClassName="bg-[#1D9E75]"
              value={counts.completedCount ?? 0}
              label="ליד שלם"
            />
            <StatCard
              icon="clock"
              chipClassName="bg-[#378ADD]"
              value={counts.openCount ?? 0}
              label="פתוחים"
            />
            <StatCard
              icon="user-off"
              chipClassName="bg-[#D85A30]"
              value={counts.abandonedCount}
              label="ננטשו"
            />
          </div>
        ) : null}

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3">
          <SegmentedControl
            label="סינון לפי סטטוס"
            segments={STATUS_SEGMENTS}
            value={status}
            onChange={setStatus}
          />
          <div className="w-48">
            <Select
              label="סינון לפי מסלול"
              options={flowOptions}
              value={flow}
              onChange={(e) => setFlow(e.target.value)}
            />
          </div>

          {/* Free-text search over the already-loaded (decrypted) leads. */}
          <div className="flex w-full flex-col gap-1.5 sm:w-64">
            <label
              htmlFor="leads-search"
              className="text-sm font-medium text-slate-800 dark:text-slate-200"
            >
              חיפוש
            </label>
            <div className="relative">
              <input
                id="leads-search"
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape' && query) {
                    e.preventDefault()
                    setQuery('')
                  }
                }}
                placeholder="שם, טלפון, או כל תשובה…"
                autoComplete="off"
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 pl-9 text-sm text-slate-900 placeholder:text-slate-400 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 dark:placeholder:text-slate-400 [&::-webkit-search-cancel-button]:hidden"
              />
              {query ? (
                <button
                  type="button"
                  onClick={() => setQuery('')}
                  aria-label="ניקוי החיפוש"
                  title="ניקוי החיפוש"
                  className="absolute inset-y-0 left-0 flex items-center rounded-lg px-2.5 text-slate-400 outline-none transition-colors hover:text-slate-700 focus-visible:ring-2 focus-visible:ring-leaf dark:hover:text-slate-100"
                >
                  <Icon name="x" size={16} />
                </button>
              ) : null}
            </div>
          </div>

          {/* Export. Sits with the filters (top of the page) because what it
              downloads IS the current filter + search — keeping them together
              makes that relationship obvious. `mr-auto` pushes it to the far
              edge in RTL so it never crowds the search box. Excel green is
              deliberate: the one button on this page that leaves the app. */}
          <div className="flex flex-col gap-1.5 sm:mr-auto sm:self-end">
            <button
              type="button"
              disabled={exportDisabled}
              title={exportDisabled ? 'אין לידים לייצוא בתצוגה הנוכחית' : undefined}
              aria-describedby="leads-export-note"
              onClick={() => {
                window.location.assign(
                  leadsExportUrl({ status, flow: flowParam, q: trimmedQuery || undefined }),
                )
              }}
              className="inline-flex items-center gap-2 rounded-lg bg-[#1D6F42] px-4 py-2 text-sm font-semibold text-white shadow-sm outline-none transition-colors hover:bg-[#175634] focus-visible:ring-2 focus-visible:ring-[#1D6F42] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:focus-visible:ring-offset-slate-900"
            >
              <span aria-hidden="true">📊</span>
              ייצוא לאקסל
            </button>
          </div>
        </div>

        {exportDisabled ? (
          <p className="sr-only" role="status">
            אין לידים לייצוא בתצוגה הנוכחית
          </p>
        ) : null}

        {/* Result count — only while a search is actually narrowing the list. */}
        {searching && !loading && !error && leads ? (
          <p className="-mt-3 text-sm text-slate-500 dark:text-slate-400" aria-live="polite">
            מציג {visibleLeads?.length ?? 0} מתוך {leads.length} לידים
          </p>
        ) : null}

        {/* Main list */}
        <section aria-labelledby="leads-list-heading" aria-busy={loading}>
          <h2 id="leads-list-heading" className="sr-only">
            רשימת הלידים
          </h2>
          {loading ? (
            <Spinner label="טוען לידים…" className="py-12" />
          ) : error ? (
            <Alert tone="error">{error}</Alert>
          ) : visibleLeads && visibleLeads.length > 0 ? (
            <ul className="flex flex-col gap-3">
              {visibleLeads.map((lead) => (
                <li key={lead.id} id={`lead-${lead.id}`}>
                  <LeadCard lead={lead} onStatusChange={refresh} onDelete={refresh} />
                </li>
              ))}
            </ul>
          ) : searching ? (
            <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-12 text-center dark:border-slate-600 dark:bg-slate-800">
              <p className="text-sm text-slate-500 dark:text-slate-400">
                לא נמצאו לידים עבור "{trimmedQuery}"
              </p>
              <Button variant="ghost" onClick={() => setQuery('')}>
                <Icon name="x" size={16} />
                נקה חיפוש
              </Button>
            </div>
          ) : (
            <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-12 text-center text-sm text-slate-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-400">
              אין לידים להצגה בסינון הנוכחי.
            </p>
          )}
        </section>

        {/* The export button lives up with the filters; this note stays down here
            so it doesn't crowd the toolbar, and `aria-describedby` still ties the
            two together for a screen reader. */}
        <p id="leads-export-note" className="text-xs text-slate-500 dark:text-slate-400">
          קישורי הקבצים בקובץ נפתחים בדפדפן ודורשים להיות מחוברים לחשבון.
        </p>

        {/* The "מעקב נוטשים" section used to live here and render the abandoned
            list a SECOND time under every other filter. It was permanent clutter:
            the status bar already has a "ננטשו" tab showing exactly these leads,
            and the KPI card above still counts them — so nothing was lost by
            removing it, only a duplicate. `abandoned` is still fetched, because
            the count and the flow-filter options are both derived from it. */}
      </div>
    </DashboardLayout>
  )
}
