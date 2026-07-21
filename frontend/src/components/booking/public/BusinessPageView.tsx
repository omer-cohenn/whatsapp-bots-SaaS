// העמוד העסקי עצמו — מקטע אחד רציף, בלי תיבות.
//
// 🔴 THE POINT OF THIS FILE. Before the M20 revision there were two hand-built
// approximations of the business page: the real one in `PublicBookingPage.tsx`
// and a miniature inside the wizard's palette picker. They drifted, and the owner
// caught it ("התצוגה מקדימה לא תואמת לאיך שהעמוד באמת נראה"). The fix is not to
// re-sync them — it is to delete one of them. This component IS the page, and
// both the public route and the wizard preview render it. A preview that can lie
// is worse than no preview.
//
// The layout answers the second complaint ("זה צריך להיות רציף יותר"):
//   * the gallery is the hero, full width, at the very top;
//   * identity flows under it with no card around it;
//   * sections are separated by vertical rhythm and at most ONE hairline, the way
//     the reference stacks `space-y-12` blocks — no borders, no stacked shadows;
//   * the page background (`--bp-bg`) carries through the whole thing, so the
//     owner's palette is the page rather than a tint at the edges.
//
// The booking flow is passed in as `children` so this file stays presentational
// and the live page can hand in a real <BookingFlow mode="live">, while the
// wizard hands in <BookingFlow mode="preview"> with the owner's real services.

import type { ReactNode } from 'react'
import type { PublicBusinessPage } from '../../../dashboard/businessPageTypes'
import BusinessIdentity from './BusinessIdentity'
import HeroGallery from './HeroGallery'
import Reveal from './Reveal'

type Props = {
  page: PublicBusinessPage
  /** The booking experience. Optional so a page with no services still renders. */
  children?: ReactNode
  /** false in the wizard preview: nothing inside is clickable. */
  interactive?: boolean
  /** false in the preview: skip the staggered entry animation. */
  animate?: boolean
}

export default function BusinessPageView({
  page,
  children,
  interactive = true,
  animate = true,
}: Props) {
  const hasImages = page.images.length > 0

  // `Reveal` staggers the entry animation on the real page. In the preview the
  // blocks must be there the instant a palette is clicked, so we render plainly.
  const block = (order: number, node: ReactNode) =>
    animate ? (
      <Reveal order={order}>{node}</Reveal>
    ) : (
      <div>{node}</div>
    )

  return (
    <div className="flex flex-col gap-8 sm:gap-12">
      {hasImages
        ? block(
            0,
            <HeroGallery
              images={page.images}
              businessName={page.business_name}
              interactive={interactive}
            />,
          )
        : null}

      {block(
        1,
        <BusinessIdentity page={page} interactive={interactive} standalone={!hasImages} />,
      )}

      {page.about ? (
        <p className="max-w-3xl whitespace-pre-wrap text-base leading-relaxed text-[color:var(--bp-muted)]">
          {page.about}
        </p>
      ) : null}

      {children ? (
        <>
          {/* The one hairline on the page. Everything else flows. */}
          <hr className="border-0 border-t border-[color:var(--bp-border)]" aria-hidden="true" />
          {block(
            2,
            <section aria-label="קביעת תור">
              <div className="mb-8 text-center">
                <h2 className="text-2xl font-black tracking-tight text-[color:var(--bp-text)] sm:text-3xl">
                  קביעת תור
                </h2>
                <p className="mt-1.5 text-sm text-[color:var(--bp-muted)]">
                  תהליך קצר — בוחרים שירות, תאריך ושעה, ומשאירים פרטים.
                </p>
              </div>
              {children}
            </section>,
          )}
        </>
      ) : null}
    </div>
  )
}
