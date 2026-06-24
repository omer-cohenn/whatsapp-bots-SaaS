// מקטע תחומים ("מתאים לכל עסק"): כרטיסים צבעוניים עם איור מונפש לכל ענף.

import Reveal from './Reveal'
import { UseCaseArt } from './icons'
import { INDUSTRIES } from './data'

export default function IndustriesSection() {
  return (
    <section className="bx-ind">
      <Reveal dir="up" className="bx-ind-head">
        <h2 className="bx-ind-title">מתאים לכל עסק שמדבר עם לקוחות</h2>
        <p className="bx-ind-sub">יהיה התחום אשר יהיה — הבוט מדבר את השפה של הלקוחות שלכם.</p>
      </Reveal>

      <div className="bx-ind-grid">
        {INDUSTRIES.map((it, i) => {
          const m = i % 3
          const dir = m === 0 ? 'right' : m === 2 ? 'left' : 'up'
          return (
            <Reveal key={it.key} dir={dir} delay={m * 80}>
              <div className={`bx-card-tile bx-uc bx-th-${it.theme}`}>
                <div className={`bx-uc-img bx-uc-${it.theme}`}>
                  <span className="bx-uc-shine" />
                  <UseCaseArt k={it.key} />
                </div>
                <div className="bx-uc-body">
                  <h3 className="bx-uc-title">{it.title}</h3>
                  <p className="bx-uc-desc">{it.desc}</p>
                </div>
              </div>
            </Reveal>
          )
        })}
      </div>
    </section>
  )
}
