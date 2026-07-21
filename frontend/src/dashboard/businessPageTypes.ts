// הטיפוסים של העמוד העסקי (M20) — משותפים לאשף ההקמה ולעמוד הפומבי
//
// Shared types for the business page (M20). Mirrors
// `docs/spec/business-page-contract.md` — that document is authoritative; if the
// two ever disagree, the contract wins and this file is the bug.
//
// This lives in its OWN file (not appointmentTypes.ts) so the owner-side wizard
// and the public page can be built independently without both editing one
// shared file.

/** One gallery image, as the OWNER sees it. */
export type BusinessImage = {
  id: string
  /** Relative: "{business_id}/{uuid}.png" → render as `/media/${storage_path}`. */
  storage_path: string
  /** Short owner-written description, e.g. "סדנת שוקולד". Max 120 chars. */
  caption: string | null
  sort_order: number
  mime_type: string | null
  size_bytes: number | null
  created_at: string | null
}

/** The same image as an ANONYMOUS visitor sees it — three fields, nothing else. */
export type PublicBusinessImage = {
  id: string
  storage_path: string
  caption: string | null
}

/**
 * The owner's chosen look. The backend stores and returns this blob WITHOUT
 * interpreting it, so the palette list can change with no backend work — see
 * §4 of the contract.
 */
export type PageTheme = {
  /** Key into the frontend's palette table. Absent/unknown ⇒ the default. */
  palette?: string
  /** Corner rounding in px, if the owner overrode the palette's own. */
  radius?: number
}

/** The four hero contact fields. A field left empty HIDES its button entirely. */
export type BusinessContactFields = {
  phone: string | null
  whatsapp: string | null
  instagram_url: string | null
  waze_url: string | null
}

/** GET/PUT /api/booking/page — the owner's view (settings + gallery). */
export type BusinessPage = BusinessContactFields & {
  slug: string
  /** Read from the `businesses` table; NOT editable here. */
  business_name: string
  tagline: string | null
  about: string | null
  address: string | null
  logo_url: string | null
  page_theme: PageTheme
  /** Already ordered by sort_order, then created_at. */
  images: BusinessImage[]
  updated_at: string | null
}

/**
 * PUT /api/booking/page body. EVERY field is optional, and the distinction
 * matters — this is the single most important rule in the contract:
 *
 *   key omitted   → the column is left ALONE
 *   key = null    → the column is CLEARED
 *   key = ""      → normalised to null (also clears)
 *
 * Clearing is how a hero button is removed: `{ phone: null }` deletes the call
 * button. So never spread a whole object into this — send only what changed, or
 * you will wipe fields you never touched.
 */
export type BusinessPageUpdate = Partial<{
  /**
   * Writes through to `businesses.name` (M20 revision). Unlike every other key
   * here it may NOT be null or empty — a business with no name has nothing to
   * put at the top of its page — so the server enforces min_length 1 and we
   * simply never send it blank.
   */
  business_name: string
  tagline: string | null
  about: string | null
  address: string | null
  phone: string | null
  whatsapp: string | null
  instagram_url: string | null
  waze_url: string | null
  logo_url: string | null
  page_theme: PageTheme
}>

/** GET /api/book/{slug}/page — the public payload. No owner-only fields. */
export type PublicBusinessPage = BusinessContactFields & {
  business_name: string
  tagline: string | null
  about: string | null
  address: string | null
  logo_url: string | null
  page_theme: PageTheme
  images: PublicBusinessImage[]
}

/** Server-enforced cap. Mirrored here only to keep the UI honest before upload. */
export const MAX_BUSINESS_IMAGES = 40

/** Build the displayable URL for a stored image. */
export function imageSrc(storagePath: string): string {
  return `/media/${storagePath}`
}
