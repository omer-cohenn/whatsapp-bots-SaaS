// מקטע יכולות ("כל מה שהעסק צריך"): רשת כרטיסי יכולות עם תג "בקרוב" לפי הצורך.

import Reveal from './Reveal'
import { FeatIcon } from './icons'
import { FEATURES } from './data'

export default function FeaturesSection() {
  return (
    <section className="bx-feats">
      <Reveal dir="up" className="bx-feats-head">
        <h2 className="bx-feats-title">כל מה שהעסק צריך — <span className="bx-accent">בבוט אחד</span></h2>
        
      </Reveal>

      <div className="bx-feats-grid">
        {FEATURES.map((f, i) => {
          const col = i % 3
          const dir = col === 0 ? 'right' : col === 2 ? 'left' : 'up'
          return (
            <Reveal key={f.key} dir={dir} delay={col * 80}>
              <div className="bx-card-tile bx-feat">
                {f.soon && <span className="bx-feat-soon">בקרוב</span>}
                <div className="bx-feat-icon"><FeatIcon k={f.key} /></div>
                <h3 className="bx-feat-title">{f.title}</h3>
                <p className="bx-feat-desc">{f.desc}</p>
              </div>
            </Reveal>
          )
        })}
      </div>
    </section>
  )
}
