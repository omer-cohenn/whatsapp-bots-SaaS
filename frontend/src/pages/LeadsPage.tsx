// Leads page (M7, route /leads). Shows EVERY collected lead with its full
// decrypted answers (the owner wants no hiding), filterable by status (incl.
// "חדש" / "פתוח") and by flow type. Below the main list is a separate
// "מעקב נוטשים" section — abandoned leads with their phone + partial answers, so
// the owner can follow up.
//
// One read: GET /api/leads (filtered server-side by status/period/flow). The
// abandoned list is derived from a second filtered fetch so each list paginates
// independently of the chosen status filter. The tenant is server-side only.

import { useCallback, useEffect, useMemo, useState } from 'react'
import DashboardLayout from '../components/DashboardLayout'
import LeadCard from '../components/dashboard/LeadCard'
import StatCard from '../components/dashboard/StatCard'
import SegmentedControl, { type Segment } from '../components/dashboard/SegmentedControl'
import Select from '../components/ui/Select'
import Spinner from '../components/ui/Spinner'
import Alert from '../components/ui/Alert'
import Icon from '../components/ui/Icon'
import { getLeads } from '../lib/dashboardClient'
import { toFriendlyError } from '../lib/friendlyError'
import type { Lead, LeadStatusFilter } from '../dashboard/types'

// Filter chips. הושלמו maps to the backend `new` status (a completed lead);
// פתוחים → in_progress; נטשו → abandoned. הכול shows everything (incl. deal/closed).
const STATUS_SEGMENTS: Segment<LeadStatusFilter>[] = [
  { value: 'all', label: 'הכול' },
  { value: 'in_progress', label: 'פתוחים' },
  { value: 'new', label: 'הושלמו' },
  { value: 'abandoned', label: 'נטשו' },
]

export default function LeadsPage() {
  const [status, setStatus] = useState<LeadStatusFilter>('all')
  const [flow, setFlow] = useState<string>('all')

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

  // KPI counts off the full (status=all) picture. Only computable when the
  // current filter is 'all' (that's when `leads` holds every lead). הושלמו = the
  // backend `new` status; פתוחים = in_progress; ננטשו from the abandoned list.
  const counts = useMemo(() => {
    const all = status === 'all' ? leads ?? [] : null
    return {
      completedCount: all ? all.filter((l) => l.status === 'new').length : null,
      openCount: all ? all.filter((l) => l.status === 'in_progress').length : null,
      abandonedCount: abandoned.length,
    }
  }, [leads, abandoned, status])

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
              label="הושלמו"
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
        </div>

        {/* Main list */}
        <section aria-labelledby="leads-list-heading" aria-busy={loading}>
          <h2 id="leads-list-heading" className="sr-only">
            רשימת הלידים
          </h2>
          {loading ? (
            <Spinner label="טוען לידים…" className="py-12" />
          ) : error ? (
            <Alert tone="error">{error}</Alert>
          ) : leads && leads.length > 0 ? (
            <ul className="flex flex-col gap-3">
              {leads.map((lead) => (
                <li key={lead.id}>
                  <LeadCard lead={lead} onStatusChange={refresh} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-12 text-center text-sm text-slate-500">
              אין לידים להצגה בסינון הנוכחי.
            </p>
          )}
        </section>

        {/* Abandoned follow-up list (only when not already filtered to abandoned) */}
        {!loading && !error && status !== 'abandoned' && abandoned.length > 0 ? (
          <section aria-labelledby="abandoned-heading" className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <h2
                id="abandoned-heading"
                className="flex items-center gap-2 text-lg font-medium text-slate-900"
              >
                <Icon name="user-off" size={20} className="text-[#D85A30]" />
                מעקב נוטשים
              </h2>
              <span className="text-sm text-slate-500">
                לידים שלא הושלמו — שווה לפנות אליהם
              </span>
            </div>
            <ul className="flex flex-col gap-3">
              {abandoned.map((lead) => (
                <li key={lead.id}>
                  <LeadCard lead={lead} onStatusChange={refresh} />
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </DashboardLayout>
  )
}
