// All-businesses list (M12, route /admin/businesses). A searchable, paginated
// table of every business on the platform. Search is debounced and resets to
// the first page; pagination walks limit/offset windows via Prev/Next. Each row
// links into the business detail page (BusinessesTable handles the row links).
//
// Two reads: GET /api/admin/plans once (to label plans), and
// GET /api/admin/businesses on every search/page change. Admin-gated
// server-side; this is the deliberate cross-tenant operator view.

import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import DashboardLayout from '../../components/DashboardLayout'
import BusinessesTable from '../../components/admin/BusinessesTable'
import Field from '../../components/ui/Field'
import Button from '../../components/ui/Button'
import Spinner from '../../components/ui/Spinner'
import Alert from '../../components/ui/Alert'
import Icon from '../../components/ui/Icon'
import { listBusinesses, getPlans } from '../../lib/adminClient'
import { toFriendlyError } from '../../lib/friendlyError'
import type { BusinessRow, Plan } from '../../admin/types'

const PAGE_SIZE = 50

export default function BusinessesList() {
  // The raw text in the box vs. the debounced value we actually query with.
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)

  const [rows, setRows] = useState<BusinessRow[]>([])
  const [plans, setPlans] = useState<Plan[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Debounce the search box → commit to `search` 350ms after typing stops, and
  // reset to the first page so results aren't offset into nothing.
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      setSearch(searchInput.trim())
      setOffset(0)
    }, 350)
    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
  }, [searchInput])

  // Plan catalog once, for labelling the מנוי column.
  useEffect(() => {
    let cancelled = false
    getPlans()
      .then((res) => {
        if (!cancelled) setPlans(res.plans)
      })
      .catch(() => {
        if (!cancelled) setPlans([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  // The list itself, re-fetched on search/page change.
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    listBusinesses({ search: search || undefined, limit: PAGE_SIZE, offset })
      .then((res) => {
        if (!cancelled) setRows(res.businesses)
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err, 'טעינת העסקים נכשלה. נסו שוב.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [search, offset])

  const page = Math.floor(offset / PAGE_SIZE) + 1
  // A full page implies there may be more; a short page is the last one.
  const hasNext = rows.length === PAGE_SIZE
  const hasPrev = offset > 0

  return (
    <DashboardLayout>
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-10">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
            <Icon name="building-store" size={22} className="text-leaf" />
            כל העסקים
          </h1>
          <Link
            to="/admin"
            className="inline-flex items-center gap-1 rounded text-sm font-medium text-leaf-ink underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2"
          >
            <Icon name="chevron-right" size={16} />
            חזרה לניהול
          </Link>
        </div>

        {/* Search */}
        <div className="max-w-sm">
          <Field
            label="חיפוש עסק"
            type="search"
            placeholder="שם עסק או אימייל בעלים…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            hint="החיפוש מתעדכן תוך כדי הקלדה."
          />
        </div>

        {/* Table */}
        <section aria-labelledby="businesses-heading" aria-busy={loading}>
          <h2 id="businesses-heading" className="sr-only">
            רשימת כל העסקים
          </h2>
          {loading ? (
            <Spinner label="טוען עסקים…" className="py-12" />
          ) : error ? (
            <Alert tone="error">{error}</Alert>
          ) : rows.length > 0 ? (
            <BusinessesTable rows={rows} plans={plans} caption="כל העסקים בפלטפורמה" />
          ) : (
            <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-12 text-center text-sm text-slate-500">
              {search ? 'לא נמצאו עסקים שתואמים לחיפוש.' : 'אין עדיין עסקים להצגה.'}
            </p>
          )}
        </section>

        {/* Pagination */}
        {!error && (hasPrev || hasNext) ? (
          <nav
            aria-label="דפדוף בין עמודים"
            className="flex items-center justify-between gap-3"
          >
            <Button
              variant="secondary"
              disabled={!hasPrev || loading}
              onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            >
              <Icon name="chevron-right" size={16} />
              הקודם
            </Button>
            <span aria-live="polite" className="text-sm text-slate-500">
              עמוד {page}
            </span>
            <Button
              variant="secondary"
              disabled={!hasNext || loading}
              onClick={() => setOffset((o) => o + PAGE_SIZE)}
            >
              הבא
              <Icon name="chevron-left" size={16} />
            </Button>
          </nav>
        ) : null}
      </div>
    </DashboardLayout>
  )
}
