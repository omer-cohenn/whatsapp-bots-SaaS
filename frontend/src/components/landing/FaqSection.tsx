// מקטע שאלות נפוצות (FAQ): רשימת אקורדיון נגישה (aria-expanded) עם פתיחה/סגירה.

import { useState } from 'react'
import Reveal from './Reveal'
import { FAQ } from './data'

export default function FaqSection() {
  const [open, setOpen] = useState(0)
  return (
    <section className="bx-faq">
      <Reveal dir="up" className="bx-faq-head">
        <h2 className="bx-faq-title">שאלות נפוצות</h2>
      </Reveal>
      <div className="bx-faq-list">
        {FAQ.map((item, i) => (
          <Reveal key={i} dir="up" delay={i * 60}>
            <div className={`bx-card-tile bx-faq-item ${open === i ? 'open' : ''}`}>
              <button className="bx-faq-q" type="button" onClick={() => setOpen(open === i ? -1 : i)} aria-expanded={open === i}>
                <span>{item.q}</span>
                <svg aria-hidden="true" focusable="false" className="bx-faq-chev" width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M6 9l6 6 6-6" stroke="#3f9a39" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </button>
              <div className="bx-faq-a-wrap"><div className="bx-faq-a"><p>{item.a}</p></div></div>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  )
}
