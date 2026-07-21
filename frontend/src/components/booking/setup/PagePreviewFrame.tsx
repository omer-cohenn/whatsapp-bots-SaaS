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

  useEffect(() => {
    const outer = outerRef.current
    const canvas = canvasRef.current
    if (!outer || !canvas) return

    // `inert` has no React 18 JSX typing, so it is set imperatively. It removes
    // the subtree from the tab order AND the accessibility tree, which is what
    // makes the aria-hidden below correct rather than a focus trap for SR users.
    canvas.setAttribute('inert', '')

    const measure = () => {
      const next = Math.min(1, outer.clientWidth / CANVAS_WIDTH)
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
  }, [])

  return (
    <div
      ref={outerRef}
      className="overflow-hidden rounded-2xl border border-black/10"
      style={{ height }}
    >
      <div
        ref={canvasRef}
        aria-hidden="true"
        className="pointer-events-none select-none px-6 py-8"
        style={{
          ...themeVars,
          backgroundColor: 'var(--bp-bg)',
          width: CANVAS_WIDTH,
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
