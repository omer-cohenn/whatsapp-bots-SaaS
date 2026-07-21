// זהות העסק — לוגו · שם · כתובת · ארבעת כפתורי הקשר, מתחת לפסיפס התמונות.
//
// M20 revision. Two things changed from the first build:
//
//   1. NO CARD. The owner's words: "לא אהבתי שזה מחולק ככה לתיבות.. זה צריך
//      להיות רציף יותר". So this block has no border, no white surface and no
//      shadow — it sits directly on the page background and is separated from
//      what follows by rhythm and one hairline, exactly like the reference's
//      `space-y-12` sections.
//   2. It sits UNDER the gallery, not above it, because the gallery is now the
//      hero. The logo bleeds up over the top edge of the mosaic so the two read
//      as one masthead rather than two stacked things.
//
// Layout is a single CENTRED column, matching the owner's reference screenshot:
// the logo straddles the bottom edge of the photos, then the name, then the
// address, then the contact row — each centred under the one above. An earlier
// version split name-left / buttons-right; the owner rejected it, and centring
// is also what lets the logo sit on the seam without looking bolted to one side.
//
// Everything except the name is CONDITIONAL — an owner who filled in nothing but
// a name still gets a clean block rather than a scaffold of empty rows. Colours
// come only from the palette CSS variables set by `paletteVars`.
//
// 🔴 Shared by the public page AND the wizard preview — one implementation, so
// the preview cannot promise a layout the visitor will not get.

import type { PublicBusinessPage } from '../../../dashboard/businessPageTypes'
import ContactButtons from './ContactButtons'
import { MapPinIcon } from './brandIcons'

/** First character of the name — the fallback mark when there is no logo. */
function initial(name: string): string {
  return name.trim().charAt(0) || '★'
}

/**
 * The logo may be an uploaded `/media/...` path (POST /api/booking/logo) or a
 * legacy pasted http(s) URL. Anything else (a `javascript:` scheme, a stray
 * fragment) is dropped rather than emitted into a public page's `src`.
 */
function safeLogo(raw: string | null): string | null {
  if (!raw) return null
  const url = raw.trim()
  if (/^https?:\/\//i.test(url)) return url
  if (url.startsWith('/media/')) return url
  return null
}

type Props = {
  page: PublicBusinessPage
  /** false in the wizard preview: contact links are inert. */
  interactive?: boolean
  /** true when the gallery above is absent, so nothing bleeds upward. */
  standalone?: boolean
}

export default function BusinessIdentity({
  page,
  interactive = true,
  standalone = false,
}: Props) {
  const logo = safeLogo(page.logo_url)

  return (
    <header
      className={[
        // LAYER 3. `relative z-10` lifts it above the fog; the negative pull is
        // what makes it bite into the photos rather than sit under them.
        'relative z-10 flex flex-col items-center text-center',
        // Straddle the mosaic's bottom edge so the logo and the photos read as
        // one masthead. Nothing to pull up over when there is no gallery.
        standalone ? '' : '-mt-20 sm:-mt-24',
      ].join(' ')}
    >
      {/* The logo is ROUND and edge-feathered, matching the fog treatment of
          layer 2 rather than fighting it. Note the trade this accepts: a circular
          crop clips the corners of square logo artwork, so an owner whose mark
          fills a square will lose its corners. That is the owner's explicit
          choice — the soft round disc reads as part of the masthead, where the
          earlier hard-edged square read as a sticker pasted on top. */}
      <span
        className="flex h-28 w-28 shrink-0 items-center justify-center overflow-hidden rounded-full sm:h-32 sm:w-32"
        style={{
          // ROUND, with the same soft-edge treatment as layer 2 — no hard ring.
          // A crisp border would reintroduce exactly the sharp outline the fog
          // exists to remove, so instead the halo is a wide, very soft shadow in
          // the page's own background colour: the disc dissolves outward into the
          // fog instead of ending at a line.
          //
          // Slightly translucent with a blur behind it (the owner's "בשקיפות
          // קצת"), so the photo underneath shows through faintly and the mark
          // reads as floating ON the fog rather than pasted over it.
          backgroundColor: 'color-mix(in srgb, var(--bp-surface) 82%, transparent)',
          backdropFilter: 'blur(6px)',
          WebkitBackdropFilter: 'blur(6px)',
          boxShadow:
            '0 0 0 10px color-mix(in srgb, var(--bp-bg) 55%, transparent), ' +
            '0 0 26px 14px color-mix(in srgb, var(--bp-bg) 42%, transparent), ' +
            '0 14px 32px rgba(0,0,0,.16)',
          // Feather the artwork's own rim so the edge melts rather than cuts.
          // The core stays fully crisp — only the outer ~14% fades.
          maskImage: 'radial-gradient(circle at 50% 50%, #000 86%, transparent 100%)',
          WebkitMaskImage:
            'radial-gradient(circle at 50% 50%, #000 86%, transparent 100%)',
        }}
      >
        {logo ? (
          <img src={logo} alt="" className="h-full w-full object-cover" />
        ) : (
          <span
            aria-hidden="true"
            className="text-5xl font-black text-[color:var(--bp-primary)]"
          >
            {initial(page.business_name)}
          </span>
        )}
      </span>

      <h1 className="mt-4 text-3xl font-black leading-tight tracking-tight text-[color:var(--bp-text)] sm:text-4xl">
        {page.business_name}
      </h1>

      {page.tagline ? (
        <p className="mt-1.5 text-base font-medium text-[color:var(--bp-muted)]">
          {page.tagline}
        </p>
      ) : null}

      {page.address ? (
        <p className="mt-2 flex items-center justify-center gap-1.5 text-sm font-medium text-[color:var(--bp-muted)]">
          <MapPinIcon size={17} className="shrink-0 text-[color:var(--bp-primary)]" />
          <span>{page.address}</span>
        </p>
      ) : null}

      {/* Empty field ⇒ that button is absent; all empty ⇒ the row itself is absent. */}
      <ContactButtons
        interactive={interactive}
        className="mt-5 justify-center"
        fields={{
          phone: page.phone,
          whatsapp: page.whatsapp,
          instagram_url: page.instagram_url,
          waze_url: page.waze_url,
        }}
      />
    </header>
  )
}
