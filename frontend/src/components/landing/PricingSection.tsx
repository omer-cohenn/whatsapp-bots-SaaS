// מקטע מסלולים (Pricing): שלושה כרטיסי תמחור עם הדגשת המסלול הפופולרי.

import Reveal from './Reveal'
import { PLANS } from './data'

export default function PricingSection() {
  return (
    <section className="bx-pricing">
      <Reveal dir="up" className="bx-pricing-head">
        <h2 className="bx-pricing-title">
          מסלולים פשוטים, בלי הפתעות
          <span className="bx-demo-stamp">דמו</span>
        </h2>
        <p className="bx-pricing-sub">
          מתחילים בחינם, משדרגים כשהעסק צומח. · המחירים להמחשה בלבד
        </p>
      </Reveal>

      <div className="bx-pricing-grid">
        {PLANS.map((pl, i) => {
          const dir = i === 0 ? 'right' : i === 2 ? 'left' : 'up'
          return (
            <Reveal key={pl.name} dir={dir} delay={i * 80}>
              <div className={`bx-card-tile bx-plan ${pl.popular ? 'bx-plan-pop' : ''}`}>
                <div className="bx-plan-top">
                  <h3 className="bx-plan-name">{pl.name}</h3>
                  {pl.popular && <span className="bx-plan-badge">הכי פופולרי</span>}
                </div>
                <div className="bx-plan-price">
                  <div className="bx-plan-price-row">
                    <span className="bx-plan-amt">{pl.amt}</span>
                    <span className="bx-plan-per">{pl.per}</span>
                    {pl.was && <span className="bx-plan-was">{pl.was}</span>}
                  </div>
                  {pl.note && <p className="bx-plan-note">{pl.note}</p>}
                  {pl.annual && <p className="bx-plan-annual">{pl.annual}</p>}
                </div>
                <ul className="bx-plan-feats">
                  {pl.feats.map((f, j) => (
                    <li key={j}>
                      <svg aria-hidden="true" focusable="false" width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M5 12.5l4.5 4.5L19 7" stroke="#3f9a39" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
                <a className={`bx-plan-cta ${pl.popular ? 'pop' : ''}`} href="/auth/google">התחילו</a>
              </div>
            </Reveal>
          )
        })}
      </div>
    </section>
  )
}
