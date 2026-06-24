// רצועת נתונים: ארבע תיבות מספרים מונפשות (זמן הקמה, אחוז פתיחה, הודעות שמתפספסות, זמינות).

import Reveal from './Reveal'
import Counter from './Counter'

export default function StatsBand() {
  const stats = [
    { dir: 'right' as const, d: 0, num: (<><Counter to={10} /><span className="bx-stat-unit">דק'</span></>), label: 'להקמה מלאה' },
    { dir: 'right' as const, d: 90, num: (<><Counter to={98} /><span className="bx-stat-unit">%</span></>), label: 'פתיחה להודעות בוואטסאפ' },
    { dir: 'left' as const, d: 90, num: (<Counter from={50} to={0} />), label: 'הודעות שמתפספסות' },
    { dir: 'left' as const, d: 0, num: (<span className="bx-stat-static">24/7</span>), label: 'זמינות מלאה' },
  ]
  return (
    <section className="bx-stats">
      <div className="bx-grid4">
        {stats.map((s, i) => (
          <Reveal key={i} dir={s.dir} delay={s.d}>
            <div className="bx-stat">
              <div className="bx-stat-box"><div className="bx-stat-num">{s.num}</div></div>
              <div className="bx-stat-label">{s.label}</div>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  )
}
