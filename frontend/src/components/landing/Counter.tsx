// מונה מספרים מונפש (איטי): סופר מ-from ל-to כשהוא נכנס לתצוגה; מכבד reduced-motion.

import { useEffect, useRef, useState } from 'react'

type CounterProps = { from?: number; to: number; duration?: number; suffix?: string }

export default function Counter({ from = 0, to, duration = 4200, suffix = '' }: CounterProps) {
  const ref = useRef<HTMLSpanElement>(null)
  const [val, setVal] = useState(from)
  const started = useRef(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting && !started.current) {
          started.current = true
          io.unobserve(el)
          const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
          if (reduce) { setVal(to); return }
          const t0 = performance.now()
          const tick = (now: number) => {
            const t = Math.min((now - t0) / duration, 1)
            const e2 = 1 - Math.pow(1 - t, 3)
            setVal(Math.round(from + (to - from) * e2))
            if (t < 1) requestAnimationFrame(tick)
          }
          requestAnimationFrame(tick)
        }
      })
    }, { threshold: 0.4 })
    io.observe(el)
    return () => io.disconnect()
  }, [from, to, duration])
  return <span ref={ref}>{val}{suffix}</span>
}
