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
    <>
      {/* מתחת ל-md: שורת כרטיס לכל עסק. הטבלה הזו רחבה 720px בשמונה עמודות —
          לגרור אותה לצדדים במסך של 358px זה עונש על המסך שהכי משתמשים בו
          לסריקה מהירה. הכרטיס לא מוותר על שום נתון: הוא מציג את כל שמונת
          השדות, רק מסודרים בשתי עמודות במקום בשמונה. מ-md ומעלה חוזרת
          הטבלה המקורית, ללא שינוי. */}
      <ul aria-label={caption} className="flex flex-col gap-2 md:hidden">
        {rows.map((row) => (
          <li
            key={row.business_id}
            className="rounded-2xl border border-slate-200 bg-white p-3"
          >
            <div className="flex items-start justify-between gap-2">
              <Link
                to={`/admin/businesses/${encodeURIComponent(row.business_id)}`}
                className="flex min-h-11 min-w-0 flex-1 items-center break-words rounded text-sm font-medium text-leaf-ink underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2"
              >
                {row.name || 'ללא שם'}
              </Link>
              <span className="shrink-0">
                <StatusBadge status={row.status} />
              </span>
            </div>

            {row.owner_email ? (
              <p className="mt-0.5 break-all text-xs text-slate-500">
                {row.owner_email}
              </p>
            ) : null}

            {/* שאר השדות — שתי עמודות, לא עמודה אחת ארוכה. */}
            <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
              <div className="flex flex-col">
                <dt className="text-slate-500">נרשם</dt>
                <dd className="font-medium text-slate-900">{shortDate(row.created_at)}</dd>
              </div>
              <div className="flex flex-col">
                <dt className="text-slate-500">כניסה אחרונה</dt>
                <dd className="font-medium text-slate-900">
                  {shortDate(row.last_login_at)}
                </dd>
              </div>
              <div className="flex flex-col">
                <dt className="text-slate-500">לידים</dt>
                <dd className="font-medium tabular-nums text-slate-900">
                  {row.leads_count}
                </dd>
              </div>
              <div className="flex flex-col">
                <dt className="text-slate-500">הודעות (30 ימים)</dt>
                <dd className="font-medium tabular-nums text-slate-900">{row.msgs_30d}</dd>
              </div>
              <div className="col-span-2 flex flex-col">
                <dt className="text-slate-500">מנוי</dt>
                <dd className="font-medium text-slate-900">{planLabel(row.plan_code)}</dd>
              </div>
            </dl>
          </li>
        ))}
      </ul>

      {/* מ-md ומעלה: הטבלה המקורית, בלי שינוי. */}
      <div className="hidden overflow-x-auto rounded-2xl border border-slate-200 bg-white md:block">
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
    </>
  )
}
