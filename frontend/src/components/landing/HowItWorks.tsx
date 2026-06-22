// "איך זה עובד" — four numbered steps from sign-in to receiving leads. The
// section id is the smooth-scroll target for the header nav + the hero CTA.

import Icon, { type IconName } from '../ui/Icon'

type Step = {
  icon: IconName
  title: string
  body: string
}

const STEPS: Step[] = [
  {
    icon: 'brand-google',
    title: 'מתחברים עם Google',
    body: 'חשבון ועסק נפתחים אוטומטית — בלי טפסים ארוכים.',
  },
  {
    icon: 'sparkles',
    title: 'בונים בוט עם עוזר ה-AI',
    body: 'בשפה חופשית, בלי קוד — מתארים והבוט נבנה.',
  },
  {
    icon: 'message-circle',
    title: 'מחברים את הוואטסאפ של העסק',
    body: 'סריקת QR מהירה — המספר הקיים של העסק.',
  },
  {
    icon: 'users',
    title: 'מקבלים לידים ופגישות',
    body: 'אוטומטית, ישר לדשבורד שלכם.',
  },
]

export default function HowItWorks() {
  return (
    <section
      id="how-it-works"
      aria-labelledby="how-heading"
      className="scroll-mt-20 bg-[#FAF9F5]"
    >
      <div className="mx-auto max-w-6xl px-6 py-16 lg:py-20">
        <div className="mx-auto max-w-2xl text-center">
          <h2
            id="how-heading"
            className="text-2xl font-bold text-slate-900 sm:text-3xl"
          >
            איך זה עובד
          </h2>
          <p className="mt-3 text-base text-slate-600">
            ארבעה צעדים פשוטים — ואתם באוויר.
          </p>
        </div>

        <ol className="mt-12 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((step, index) => (
            <li key={step.title} className="flex flex-col items-center text-center">
              <span className="relative mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-leaf text-white">
                <Icon name={step.icon} size={26} />
                <span
                  aria-hidden="true"
                  className="absolute -top-2 -start-2 flex h-6 w-6 items-center justify-center rounded-full border-2 border-[#FAF9F5] bg-leaf-ink text-xs font-bold text-white"
                >
                  {index + 1}
                </span>
              </span>
              <h3 className="text-lg font-semibold text-leaf-ink">{step.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">
                {step.body}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
