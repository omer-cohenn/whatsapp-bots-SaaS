// The all-businesses table used by both AdminHome (a compact recent slice) and
// BusinessesList (the full searchable/paginated view). Each row is a real link
// into the business detail page, keyboard-operable for free. A short-date
// helper keeps the columns tight; null values show an em-dash.

import { Link } from 'react-router-dom'
import StatusBadge from './StatusBadge'
import { formatPrice } from '../../admin/labels'
import type { BusinessRow, Plan } from '../../admin/types'

// Compact date for table cells, e.g. "19 ביוני 2026". Null → "—".
function shortDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('he-IL', { day: 'numeric', month: 'short', year: 'numeric' })
}

type Props = {
  rows: BusinessRow[]
  /** Optional plan catalog → render a human plan name + price instead of code. */
  plans?: Plan[]
  /** Accessible caption for the table (visually hidden). */
  caption: string
}

export default function BusinessesTable({ rows, plans, caption }: Props) {
  // code → display label ("Pro · ₪99"); falls back to the raw code.
  const planLabel = (code: string): string => {
    const plan = plans?.find((p) => p.code === code)
    if (!plan) return code
    const name = plan.name || plan.code
    return `${name} · ${formatPrice(plan.price)}`
  }

  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
      <table className="w-full min-w-[720px] border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-slate-200 text-right text-xs font-medium text-slate-500">
            <th scope="col" className="px-4 py-3">שם העסק</th>
            <th scope="col" className="px-4 py-3">אימייל בעלים</th>
            <th scope="col" className="px-4 py-3">נרשם</th>
            <th scope="col" className="px-4 py-3">כניסה אחרונה</th>
            <th scope="col" className="px-4 py-3">מנוי</th>
            <th scope="col" className="px-4 py-3">סטטוס</th>
            <th scope="col" className="px-4 py-3">לידים</th>
            <th scope="col" className="px-4 py-3">הודעות (30 ימים)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.business_id}
              className="border-b border-slate-100 last:border-0 transition-colors hover:bg-slate-50"
            >
              <td className="px-4 py-3 font-medium text-slate-900">
                <Link
                  to={`/admin/businesses/${encodeURIComponent(row.business_id)}`}
                  className="rounded text-leaf-ink underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2"
                >
                  {row.name || 'ללא שם'}
                </Link>
              </td>
              <td className="px-4 py-3 text-slate-600">{row.owner_email || '—'}</td>
              <td className="px-4 py-3 text-slate-600">{shortDate(row.created_at)}</td>
              <td className="px-4 py-3 text-slate-600">{shortDate(row.last_login_at)}</td>
              <td className="px-4 py-3 text-slate-600">{planLabel(row.plan_code)}</td>
              <td className="px-4 py-3">
                <StatusBadge status={row.status} />
              </td>
              <td className="px-4 py-3 tabular-nums text-slate-900">{row.leads_count}</td>
              <td className="px-4 py-3 tabular-nums text-slate-900">{row.msgs_30d}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
