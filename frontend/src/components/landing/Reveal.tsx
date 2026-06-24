// עוטף "גילוי בגלילה": מחליק תוכן פנימה כשהוא נכנס לתצוגה (IntersectionObserver).

import { useEffect, useRef, useState } from 'react'

type RevealProps = {
  children: React.ReactNode
  dir?: 'up' | 'left' | 'right'
  delay?: number
  className?: string
}

export default function Reveal({ children, dir = 'up', delay = 0, className = '' }: RevealProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [vis, setVis] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => { if (e.isIntersecting) { setVis(true); io.unobserve(el) } }),
      { threshold: 0.15 }
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])
  return (
    <div ref={ref} className={`reveal reveal-${dir} ${vis ? 'is-visible' : ''} ${className}`} style={{ transitionDelay: `${delay}ms` }}>
      {children}
    </div>
  )
}
