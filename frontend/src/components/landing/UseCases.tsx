// "למי זה מתאים" — short industry use-case cards.

import Card from '../ui/Card'

type UseCase = {
  title: string
  body: string
}

const USE_CASES: UseCase[] = [
  { title: 'סוכני ביטוח', body: 'איסוף פניות וסינון לידים אוטומטי.' },
  { title: 'מספרות וקוסמטיקה', body: 'קביעת תורים ישירות בוואטסאפ.' },
  { title: 'קליניקות וטיפול', body: 'תיאום פגישות ותזכורות ללקוחות.' },
  { title: 'יועצים ומאמנים', body: 'מענה ראשוני וקביעת שיחות ייעוץ.' },
  {
    title: 'נותני שירות ובעלי מקצוע',
    body: 'הצעות מחיר וזימון קריאות שירות.',
  },
]

export default function UseCases() {
  return (
    <section
      id="use-cases"
      aria-labelledby="use-cases-heading"
      className="scroll-mt-20 bg-[#FAF9F5]"
    >
      <div className="mx-auto max-w-6xl px-6 py-16 lg:py-20">
        <div className="mx-auto max-w-2xl text-center">
          <h2
            id="use-cases-heading"
            className="text-2xl font-bold text-slate-900 sm:text-3xl"
          >
            מתאים לכל עסק שמדבר עם לקוחות
          </h2>
        </div>

        <ul className="mx-auto mt-10 flex max-w-4xl flex-wrap justify-center gap-4">
          {USE_CASES.map((useCase) => (
            <li key={useCase.title} className="w-full sm:w-[calc(50%-0.5rem)] lg:w-[calc(33.333%-0.667rem)]">
              <Card className="h-full">
                <h3 className="text-base font-semibold text-leaf-ink">
                  {useCase.title}
                </h3>
                <p className="mt-1.5 text-sm leading-relaxed text-slate-600">
                  {useCase.body}
                </p>
              </Card>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
