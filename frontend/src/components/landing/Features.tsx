// "יכולות" — the capability card grid. RAG (מענה מידע) is flagged "בקרוב".

import Card from '../ui/Card'
import Badge from '../ui/Badge'
import Icon, { type IconName } from '../ui/Icon'

type Feature = {
  icon: IconName
  title: string
  body: string
  soon?: boolean
}

const FEATURES: Feature[] = [
  {
    icon: 'users',
    title: 'איסוף לידים',
    body: 'שאלון חכם שאוסף את הפרטים החשובים — שמור ומוצפן.',
  },
  {
    icon: 'calendar-event',
    title: 'קביעת תורים',
    body: 'דף הזמנה לעסק, מסונכרן ליומן Google ולפגישות Meet.',
  },
  {
    icon: 'message-circle',
    title: 'מעבר לנציג אנושי',
    body: 'הבוט מזהה צורך ומעביר לצ׳אט חי עם נציג מהצוות.',
  },
  {
    icon: 'sparkles',
    title: 'בונה בוט עם AI',
    body: 'מתארים בשפה חופשית — והעוזר בונה את הבוט בשבילכם.',
  },
  {
    icon: 'robot',
    title: 'דשבורד מלא',
    body: 'לידים, שיחות ופגישות — הכול במקום אחד וברור.',
  },
  {
    icon: 'world',
    title: 'מענה מידע מהעסק',
    body: 'תשובות מדויקות מתוך הקבצים והאתר של העסק (RAG).',
    soon: true,
  },
]

export default function Features() {
  return (
    <section id="features" aria-labelledby="features-heading" className="scroll-mt-20 bg-white">
      <div className="mx-auto max-w-6xl px-6 py-16 lg:py-20">
        <div className="mx-auto max-w-2xl text-center">
          <h2
            id="features-heading"
            className="text-2xl font-bold text-slate-900 sm:text-3xl"
          >
            כל מה שהעסק צריך — בבוט אחד
          </h2>
          <p className="mt-3 text-base text-slate-600">
            יכולות שעובדות בשבילכם, בלי להרים אצבע.
          </p>
        </div>

        <ul className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((feature) => (
            <li key={feature.title}>
              <Card className="h-full">
                <div className="flex items-start justify-between gap-3">
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-leaf-soft text-leaf-ink">
                    <Icon name={feature.icon} size={24} />
                  </span>
                  {feature.soon ? <Badge tone="leaf">בקרוב</Badge> : null}
                </div>
                <h3 className="mt-4 text-lg font-semibold text-slate-900">
                  {feature.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-600">
                  {feature.body}
                </p>
              </Card>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
