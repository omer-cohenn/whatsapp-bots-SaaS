// "מסלולים" — three display-only pricing tiers (no billing exists yet). The
// middle tier is visually highlighted and carries a "הכי פופולרי" badge. Every
// CTA is a real link to /auth/google.

import Badge from '../ui/Badge'
import Icon from '../ui/Icon'

type Plan = {
  name: string
  price: string
  period?: string
  features: string[]
  highlighted?: boolean
}

const PLANS: Plan[] = [
  {
    name: 'בסיסי',
    price: '₪0',
    features: [
      'בוט וואטסאפ',
      'איסוף לידים',
      'מצב "נסה אותי" (try-me)',
      'דשבורד בסיסי',
    ],
  },
  {
    name: 'מקצועי',
    price: '₪149',
    period: '/חודש',
    highlighted: true,
    features: [
      'כל מה שבבסיסי',
      'קביעת תורים',
      'יומן Google ופגישות Meet',
      'מעבר לנציג אנושי',
    ],
  },
  {
    name: 'עסקי',
    price: '₪349',
    period: '/חודש',
    features: [
      'כל מה שבמקצועי',
      'מענה מידע מהעסק (RAG)',
      'ריבוי משתמשים',
      'תמיכה מועדפת',
    ],
  },
]

export default function Pricing() {
  return (
    <section id="pricing" aria-labelledby="pricing-heading" className="scroll-mt-20 bg-white">
      <div className="mx-auto max-w-6xl px-6 py-16 lg:py-20">
        <div className="mx-auto max-w-2xl text-center">
          <h2
            id="pricing-heading"
            className="text-2xl font-bold text-slate-900 sm:text-3xl"
          >
            מסלולים פשוטים, בלי הפתעות
          </h2>
          <p className="mt-3 text-base text-slate-600">
            מתחילים בחינם, משדרגים כשהעסק צומח.
          </p>
        </div>

        <ul className="mt-12 grid items-stretch gap-6 lg:grid-cols-3">
          {PLANS.map((plan) => (
            <li key={plan.name}>
              <div
                className={`flex h-full flex-col rounded-2xl border bg-white p-6 shadow-sm ${
                  plan.highlighted
                    ? 'border-leaf ring-2 ring-leaf'
                    : 'border-slate-200'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-xl font-bold text-slate-900">{plan.name}</h3>
                  {plan.highlighted ? <Badge tone="leaf">הכי פופולרי</Badge> : null}
                </div>

                <p className="mt-4 flex items-end gap-1">
                  <span className="text-4xl font-bold text-leaf-ink">{plan.price}</span>
                  {plan.period ? (
                    <span className="pb-1 text-sm text-slate-500">{plan.period}</span>
                  ) : null}
                </p>

                <ul className="mt-6 flex flex-1 flex-col gap-3">
                  {plan.features.map((feature) => (
                    <li key={feature} className="flex items-start gap-2 text-sm text-slate-700">
                      <span className="mt-0.5 flex-shrink-0 text-leaf">
                        <Icon name="check" size={18} />
                      </span>
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>

                <a
                  href="/auth/google"
                  className={`mt-8 inline-flex w-full items-center justify-center rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors ${
                    plan.highlighted
                      ? 'bg-leaf text-white hover:bg-leaf-dark'
                      : 'border border-slate-300 bg-white text-slate-800 hover:border-slate-400 hover:bg-slate-50'
                  }`}
                >
                  התחילו
                </a>
              </div>
            </li>
          ))}
        </ul>

        <p className="mt-6 text-center text-xs text-slate-500">
          מחירי השקה — לבדיקה, ניתן לעדכון.
        </p>
      </div>
    </section>
  )
}
