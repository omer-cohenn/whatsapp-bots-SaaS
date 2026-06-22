// Product-fact strip (NOT marketing metrics): four concrete truths about the
// product. White section between the warm hero and the warm how-it-works band.

const FACTS = [
  { value: '24/7', label: 'זמינות' },
  { value: 'כ-10 דק׳', label: 'להקמה' },
  { value: '0', label: 'שורות קוד' },
  { value: '100%', label: 'מוצפן ומבודד' },
]

export default function StatsStrip() {
  return (
    <section aria-labelledby="stats-heading" className="bg-white">
      <h2 id="stats-heading" className="sr-only">
        עובדות על המוצר
      </h2>
      <div className="mx-auto max-w-6xl px-6 py-10">
        <ul className="grid grid-cols-2 gap-6 text-center sm:grid-cols-4">
          {FACTS.map((fact) => (
            <li key={fact.label} className="flex flex-col items-center">
              <span className="text-2xl font-bold text-leaf sm:text-3xl">
                {fact.value}
              </span>
              <span className="mt-1 text-sm text-slate-600">{fact.label}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
