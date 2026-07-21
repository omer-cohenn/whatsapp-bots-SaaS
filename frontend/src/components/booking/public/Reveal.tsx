// עטיפה לאנימציית הכניסה המדורגת — פותחת את המקטע בהשהיה קטנה, ומכבדת הפחתת תנועה.
//
// The animation itself is pure CSS (`.bp-reveal` in `publicPageStyles.ts`), so
// `prefers-reduced-motion` is handled by a media query rather than JS branching.
//
// 🔴 The one piece of JS here is a SAFETY NET, and it is the whole reason this is
// a component and not a class name. A fade-in that starts at `opacity: 0` leaves
// content invisible for as long as the animation fails to advance — and it can
// fail to advance: a throttled/never-painted tab holds the animation at frame 0
// indefinitely (observed while testing this page in a background renderer).
//
// So after the animation *would* have finished we simply DROP the class. From
// that moment the element renders at its plain, unstyled state — visible. If the
// animation ran, this is a no-op; if it never ran, this is what rescues the page.
// Timers keep firing in a throttled tab even when animation frames do not.

import { useEffect, useState, type ElementType, type ReactNode } from 'react'

type Props = {
  /** Position in the stagger; each step adds ~90ms of delay. */
  order?: number
  /** Rendered element — pass a landmark (`section`, `header`) where one fits. */
  as?: ElementType
  className?: string
  children: ReactNode
}

const STEP_MS = 90
/** Cap the stagger so a long page never leaves the last block waiting. */
const MAX_DELAY_MS = 450
/** Must match the `bp-rise` duration in publicPageStyles.ts. */
const DURATION_MS = 550
/** Slack before we drop the class, so we never cut a running animation short. */
const SETTLE_MARGIN_MS = 250

export default function Reveal({ order = 0, as: Tag = 'div', className = '', children }: Props) {
  const delay = Math.min(order * STEP_MS, MAX_DELAY_MS)
  const [settled, setSettled] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => setSettled(true), delay + DURATION_MS + SETTLE_MARGIN_MS)
    return () => clearTimeout(timer)
  }, [delay])

  if (settled) return <Tag className={className}>{children}</Tag>

  return (
    <Tag className={`bp-reveal ${className}`} style={{ animationDelay: `${delay}ms` }}>
      {children}
    </Tag>
  )
}
