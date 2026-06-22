// "שאלות נפוצות" — an accessible accordion. Each item is a <button> with
// aria-expanded controlling a region; multiple items may be open at once. Fully
// keyboard-operable (native button semantics) with a visible focus ring.

import { useState } from 'react'
import Icon from '../ui/Icon'

type QA = {
  question: string
  answer: string
}

const ITEMS: QA[] = [
  { question: 'צריך לדעת לתכנת?', answer: 'לא.' },
  {
    question: 'צריך מספר וואטסאפ חדש?',
    answer: 'לא — מחברים את הוואטסאפ הקיים של העסק.',
  },
  {
    question: 'הנתונים מאובטחים?',
    answer: 'כן — כל הנתונים מוצפנים ומבודדים לחלוטין בין עסקים.',
  },
  {
    question: 'כמה זמן לוקח להקים?',
    answer: 'דקות — מתחברים, בונים עם ה-AI, ומחברים וואטסאפ.',
  },
  { question: 'אפשר לבטל?', answer: 'כן, בכל עת.' },
]

export default function Faq() {
  const [openIndex, setOpenIndex] = useState<number | null>(0)

  return (
    <section id="faq" aria-labelledby="faq-heading" className="scroll-mt-20 bg-[#FAF9F5]">
      <div className="mx-auto max-w-3xl px-6 py-16 lg:py-20">
        <h2
          id="faq-heading"
          className="text-center text-2xl font-bold text-slate-900 sm:text-3xl"
        >
          שאלות נפוצות
        </h2>

        <ul className="mt-10 flex flex-col gap-3">
          {ITEMS.map((item, index) => {
            const isOpen = openIndex === index
            const panelId = `faq-panel-${index}`
            const buttonId = `faq-button-${index}`
            return (
              <li
                key={item.question}
                className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
              >
                <h3>
                  <button
                    type="button"
                    id={buttonId}
                    aria-expanded={isOpen}
                    aria-controls={panelId}
                    onClick={() => setOpenIndex(isOpen ? null : index)}
                    className="flex w-full items-center justify-between gap-4 px-5 py-4 text-start text-base font-semibold text-slate-900 transition-colors hover:bg-slate-50"
                  >
                    <span>{item.question}</span>
                    <span
                      className={`flex-shrink-0 text-leaf transition-transform ${
                        isOpen ? 'rotate-180' : ''
                      }`}
                    >
                      <Icon name="chevron-down" size={20} />
                    </span>
                  </button>
                </h3>
                <div
                  id={panelId}
                  role="region"
                  aria-labelledby={buttonId}
                  hidden={!isOpen}
                  className="px-5 pb-4 text-sm leading-relaxed text-slate-600"
                >
                  {item.answer}
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    </section>
  )
}
