// עוטף את כרטיס פרטי העסק (M20) — טוען את נתוני העמוד בנפרד
//
// A thin loader around BusinessDetailsCard. It exists so BookingSettingsPanel
// can drop the business details into its "פרטי העסק וזמינות" tab without calling
// GET /api/booking/page on the services tab too — hooks can't be conditional, so
// the fetch has to live behind its own component boundary.

import BusinessDetailsCard from './BusinessDetailsCard'
import Alert from '../../ui/Alert'
import Spinner from '../../ui/Spinner'
import { useBusinessPage } from './useBusinessPage'

export default function DetailsPanel() {
  const { page, setPage, loading, error } = useBusinessPage()

  if (loading) return <Spinner label="טוען את פרטי העסק…" className="py-8" />
  if (error) return <Alert tone="error">{error}</Alert>
  if (!page) return null

  return <BusinessDetailsCard page={page} onSaved={setPage} />
}
