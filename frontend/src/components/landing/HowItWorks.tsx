// מקטע "איך זה עובד": רשת כרטיסי שלבים עם מעבר אוטומטי לכרטיס פעיל.

import { useEffect, useState } from 'react'
import Reveal from './Reveal'
import { StepIcon } from './icons'
import { STEPS } from './data'

export default function HowItWorks() {
  const [active, setActive] = useState(0)
  useEffect(() => {
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) { setActive(STEPS.length - 1); return }
    const id = setInterval(() => setActive((a) => (a + 1) % STEPS.length), 4500)
    return () => clearInterval(id)
  }, [])

  return (
    <section className="bx-hiw">
      <Reveal dir="up" className="bx-hiw-head">
        <h2 className="bx-hiw-title">איך זה עובד</h2>
        <p className="bx-hiw-sub">מסלול קצר מההרשמה ועד הלידים הראשונים.</p>
      </Reveal>

      <div className="bx-hiw-grid">
        {STEPS.map((s, i) => {
          const col = i % 3
          const dir = col === 0 ? 'right' : col === 2 ? 'left' : 'up'
          return (
            <Reveal key={s.n} dir={dir} delay={col * 80}>
              <div className={`bx-card-tile bx-hcard ${active === i ? 'active' : ''}`} onMouseEnter={() => setActive(i)}>
                <div className="bx-node-circle"><StepIcon k={s.key} /><span className="bx-node-badge">{s.n}</span></div>
                <h3 className="bx-hcard-title">{s.title}</h3>
                <p className="bx-hcard-desc">{s.desc}</p>
              </div>
            </Reveal>
          )
        })}
      </div>
    </section>
  )
}
