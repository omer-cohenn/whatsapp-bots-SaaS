// קריאה אחת לנקודת הקצה הפומבית של העמוד העסקי.
//
// GET /api/book/{slug}/page — contract §9. NO session, NO cookie, and the client
// never sends a business_id: the tenant is resolved server-side from the verified
// {slug} in the path. The response is a closed list of 11 public fields, so this
// page can never surface owner-only data.
//
// This is a deliberately tiny helper that reuses the shared `api` wrapper for the
// same timeout + typed-error behaviour as the rest of the app. It is separate
// from `lib/businessPageClient.ts` (the OWNER-side client) because the public
// page must not be able to reach an authenticated endpoint by accident.

import { api } from '../../../lib/apiClient'
import type { PublicBusinessPage } from '../../../dashboard/businessPageTypes'

/** 404 (thrown as `ApiError`) when the slug is unknown. */
export function getPublicBusinessPage(slug: string): Promise<PublicBusinessPage> {
  return api.get<PublicBusinessPage>(`/api/book/${encodeURIComponent(slug)}/page`)
}
