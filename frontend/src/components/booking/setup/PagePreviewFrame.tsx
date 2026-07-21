// מסגרת התצוגה המקדימה — מציגה את העמוד האמיתי, מוקטן.
//
// 🔴 Why this exists. The owner's first complaint about M20 was that the wizard's
// preview "לא תואמת לאיך שהעמוד באמת נראה". It was a hand-drawn miniature: a
// second implementation of the page that drifted from the real one the moment
// either changed.
//
// So there is no miniature any more. This frame renders the REAL
// <BusinessPageView> at the REAL desktop width (1024px, the public page's
// max-w-5xl canvas) and then scales the whole thing down with a CSS transform to
// fit whatever space the settings card has. Nothing is reinterpreted, re-styled
// or approximated — every pixel is the page, just smaller. If the page changes,
// the preview changes with it, because they are the same component.
//
// The canvas is `inert` + `aria-hidden` + `pointer-events-none`: a preview must
// never be tabbable (a keyboard user would walk a duplicate of the page) and a
// stray click must never dial the owner's own phone number.

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'

/** Matches `PublicBookingLayout`'s max-w-5xl (64rem) page canvas. */
const CANVAS_WIDTH = 1024

/**
 * 🔴 The phone canvas. On a 390px screen the settings card is ~309px wide, so a
 * 1024px canvas scaled down to 0.30 — the page was there, but every word in it
 * was four pixels tall. A preview nobody can read is not a preview.
 *
 * So on a phone the canvas is a PHONE, not a shrunken desktop: 390px wide,
 * ~0.79 scale, readable. And it is not a compromise — the owner is holding a
 * phone, their customers mostly are too, and the page's own breakpoints are
 * viewport-based, so at this width <BusinessPageView> lays itself out exactly as
 * it will for a phone visitor. Same component, same rules, just the layout that
 * actually matters on this screen.
 */
const PHONE_CANVAS_WIDTH = 390

/** The `sm` breakpoint — below it the settings card is simply too narrow. */
const DESKTOP_QUERY = '(min-width: 640px)'

type Props = {
  /** The palette custom properties, exactly as the public page wrapper gets them. */
  themeVars: CSSProperties
  children: ReactNode
}

export default function PagePreviewFrame({ themeVars, children }: Props) {
  const outerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(0.5)
  const [height, setHeight] = useState(480)
  // Which canvas we are previewing on, kept live so rotating the phone or
  // dragging a desktop window across 640px re-renders at the right width.
  const [wide, setWide] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(DESKTOP_QUERY).matches,
  )

  useEffect(() => {
    const mq = window.matchMedia(DESKTOP_QUERY)
    const sync = () => setWide(mq.matches)
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])

  const canvasWidth = wide ? CANVAS_WIDTH : PHONE_CANVAS_WIDTH

  useEffect(() => {
    const outer = outerRef.current
    const canvas = canvasRef.current
    if (!outer || !canvas) return

    // `inert` has no React 18 JSX typing, so it is set imperatively. It removes
    // the subtree from the tab order AND the accessibility tree, which is what
    // makes the aria-hidden below correct rather than a focus trap for SR users.
    canvas.setAttribute('inert', '')

    const measure = () => {
      const next = Math.min(1, outer.clientWidth / canvasWidth)
      setScale(next)
      // The scaled box has no layout height of its own (transform doesn't
      // reflow), so the wrapper is told what to reserve.
      setHeight(canvas.scrollHeight * next)
    }

    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(outer)
    observer.observe(canvas)
    return () => observer.disconnect()
  }, [canvasWidth])

  return (
    <div
      ref={outerRef}
      className="overflow-hidden rounded-2xl border border-black/10"
      style={{ height }}
    >
      <div
        ref={canvasRef}
        aria-hidden="true"
        className="pointer-events-none select-none px-4 py-6 sm:px-6 sm:py-8"
        style={{
          ...themeVars,
          backgroundColor: 'var(--bp-bg)',
          width: canvasWidth,
          transform: `scale(${scale})`,
          // RTL page ⇒ the canvas is anchored to the right edge.
          transformOrigin: 'top right',
        }}
      >
        {children}
      </div>
    </div>
  )
}
