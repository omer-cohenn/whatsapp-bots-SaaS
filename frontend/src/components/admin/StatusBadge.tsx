// A subscription-status pill (פעיל / מושהה / בוטל) built on the shared Badge,
// so every admin surface renders status the same way.

import Badge from '../ui/Badge'
import { STATUS_META } from '../../admin/labels'
import type { SubscriptionStatus } from '../../admin/types'

export default function StatusBadge({ status }: { status: SubscriptionStatus }) {
  const meta = STATUS_META[status] ?? STATUS_META.cancelled
  return <Badge tone={meta.tone}>{meta.label}</Badge>
}
