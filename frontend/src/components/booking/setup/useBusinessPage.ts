// טעינת נתוני העמוד העסקי (M20) — hook משותף לשני טאבי ההקמה
//
// Both setup tabs ("פרטי העסק וזמינות" and "תמונות ועיצוב") read the same
// GET /api/booking/page. They mount separately, so each gets its own copy rather
// than sharing state through a context nobody else needs.
//
// `setPage` exists so a child can push the server's own response back in — the
// PUT returns the whole page, so a successful save refreshes the screen with no
// second request.

import { useCallback, useEffect, useState } from 'react'
import type { BusinessPage } from '../../../dashboard/businessPageTypes'
import { getBusinessPage } from '../../../lib/businessPageClient'
import { toFriendlyError } from '../../../lib/friendlyError'

export function useBusinessPage() {
  const [page, setPage] = useState<BusinessPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getBusinessPage()
      .then((data) => {
        if (!cancelled) setPage(data)
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err, 'טעינת פרטי העמוד נכשלה. נסו שוב.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => load(), [load])

  return { page, setPage, loading, error }
}
