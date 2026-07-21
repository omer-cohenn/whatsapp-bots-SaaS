// תצוגת תמונה במסך מלא — נסגרת ב-Escape, לוכדת פוקוס, ומציגה את הכיתוב.
//
// A11y contract for this dialog:
//   * `role="dialog" aria-modal="true"` with an `aria-label`.
//   * Escape closes it; ArrowRight/ArrowLeft move between photos (RTL-aware: in
//     a right-to-left page "next" is on the LEFT, which is what the arrows do).
//   * FOCUS IS TRAPPED — Tab and Shift+Tab cycle inside the dialog only, so a
//     keyboard user can never tab into the page behind the overlay.
//   * Focus moves to the close button on open and is RESTORED to whatever opened
//     the dialog on close, so the gallery tile keeps its place in the tab order.
//   * The page behind is scroll-locked while the dialog is open.
//
// The caption is the alt text (see `galleryAlt`); a photo with no caption still
// gets a sane, non-empty description rather than `alt=""`.

import { useCallback, useEffect, useRef } from 'react'
import type { PublicBusinessImage } from '../../../dashboard/businessPageTypes'
import { imageSrc } from '../../../dashboard/businessPageTypes'
import Icon from '../../ui/Icon'

type Props = {
  images: PublicBusinessImage[]
  /** Index of the visible photo. */
  index: number
  onIndexChange: (next: number) => void
  onClose: () => void
  /** Used to build a meaningful alt for photos the owner left uncaptioned. */
  businessName: string
}

/** Caption if there is one, else a positional description — never empty. */
export function galleryAlt(
  image: PublicBusinessImage,
  position: number,
  total: number,
  businessName: string,
): string {
  const caption = image.caption?.trim()
  if (caption) return caption
  return `תמונה ${position} מתוך ${total} של ${businessName}`
}

/** Everything focusable inside the dialog, in DOM order. */
function focusables(root: HTMLElement): HTMLElement[] {
  return Array.from(
    root.querySelectorAll<HTMLElement>(
      'button:not([tabindex="-1"]), [href], [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((el) => !el.hasAttribute('disabled'))
}

export default function ImageLightbox({
  images,
  index,
  onIndexChange,
  onClose,
  businessName,
}: Props) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  // Whatever had focus before we opened — restored on unmount.
  const restoreRef = useRef<Element | null>(null)

  const total = images.length
  const image = images[index]

  const go = useCallback(
    (delta: number) => {
      if (total === 0) return
      onIndexChange((index + delta + total) % total)
    },
    [index, total, onIndexChange],
  )

  // Remember + restore focus, and lock background scrolling.
  useEffect(() => {
    restoreRef.current = document.activeElement
    closeRef.current?.focus()
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previousOverflow
      const back = restoreRef.current
      if (back instanceof HTMLElement) back.focus()
    }
  }, [])

  // Escape / arrows / the Tab focus trap.
  useEffect(() => {
    function onKeyDown(ev: KeyboardEvent) {
      if (ev.key === 'Escape') {
        ev.preventDefault()
        onClose()
        return
      }
      if (ev.key === 'ArrowLeft') {
        ev.preventDefault()
        go(1) // RTL: the left arrow advances
        return
      }
      if (ev.key === 'ArrowRight') {
        ev.preventDefault()
        go(-1)
        return
      }
      if (ev.key !== 'Tab') return

      const root = dialogRef.current
      if (!root) return
      const items = focusables(root)
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement

      // Wrap at both ends — and pull focus back in if it ever escaped.
      if (ev.shiftKey) {
        if (active === first || !root.contains(active)) {
          ev.preventDefault()
          last.focus()
        }
      } else if (active === last || !root.contains(active)) {
        ev.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown, true)
    return () => document.removeEventListener('keydown', onKeyDown, true)
  }, [go, onClose])

  if (!image) return null

  const caption = image.caption?.trim() || ''

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-label={`תמונה ${index + 1} מתוך ${total}`}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/95 p-4"
    >
      {/* Click-outside-to-close. A real <button> (not a div handler) so it is a
          proper control, but tabindex=-1 keeps it out of the trap's cycle — the
          keyboard route out of the dialog is Escape or the close button. */}
      <button
        type="button"
        tabIndex={-1}
        aria-hidden="true"
        onClick={onClose}
        className="absolute inset-0 cursor-default"
      />

      <button
        ref={closeRef}
        type="button"
        onClick={onClose}
        aria-label="סגירת התמונה"
        className="absolute top-4 left-4 z-10 flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-white transition hover:bg-white/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
      >
        <Icon name="x" size={24} />
      </button>

      {total > 1 ? (
        <button
          type="button"
          onClick={() => go(-1)}
          aria-label="התמונה הקודמת"
          className="absolute right-2 z-10 flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-white transition hover:bg-white/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white sm:right-5"
        >
          <Icon name="chevron-right" size={26} />
        </button>
      ) : null}

      {/* relative+z-10: the backdrop button above is absolutely positioned and
          would otherwise paint over the (statically positioned) photo. */}
      <figure className="relative z-10 flex max-h-full w-full max-w-4xl flex-col items-center gap-4">
        <img
          src={imageSrc(image.storage_path)}
          alt={galleryAlt(image, index + 1, total, businessName)}
          className="max-h-[72vh] w-auto max-w-full rounded-xl object-contain shadow-2xl"
        />
        <figcaption className="rounded-full bg-black/60 px-4 py-2 text-center text-sm text-white backdrop-blur-sm">
          {caption ? <span className="font-medium">{caption} · </span> : null}
          <span dir="rtl">{`${index + 1} מתוך ${total}`}</span>
        </figcaption>
      </figure>

      {total > 1 ? (
        <button
          type="button"
          onClick={() => go(1)}
          aria-label="התמונה הבאה"
          className="absolute left-2 z-10 flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-white transition hover:bg-white/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white sm:left-5"
        >
          <Icon name="chevron-left" size={26} />
        </button>
      ) : null}
    </div>
  )
}
