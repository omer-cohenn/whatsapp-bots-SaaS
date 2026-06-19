// Small helpers to render backend ISO timestamps as friendly Hebrew text.
// All timestamps from the API are ISO-8601 with an offset; we format in the
// browser's locale/timezone. Null/garbage in → '' out (callers hide the field).

/** "לפני X דק׳ / שעות / ימים", or an absolute date for older items. */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return ''
  const diffMs = Date.now() - then.getTime()
  const diffMin = Math.round(diffMs / 60000)
  if (diffMin < 1) return 'עכשיו'
  if (diffMin < 60) return `לפני ${diffMin} דק׳`
  const diffHr = Math.round(diffMin / 60)
  if (diffHr < 24) return `לפני ${diffHr} שע׳`
  const diffDay = Math.round(diffHr / 24)
  if (diffDay <= 7) return `לפני ${diffDay} ימים`
  return then.toLocaleDateString('he-IL', { day: 'numeric', month: 'short' })
}

/** "19 ביוני 2026, 10:05" — a full, readable timestamp. */
export function fullDateTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('he-IL', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
