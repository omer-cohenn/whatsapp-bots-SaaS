// Hero: the product promise + primary CTA. A decorative CSS chat-bubble mock
// sits beside the copy on large screens (aria-hidden — purely illustrative).

import Icon from '../ui/Icon'

export default function Hero() {
  return (
    <section
      aria-labelledby="hero-heading"
      className="bg-[#FAF9F5]"
    >
      <div className="mx-auto grid max-w-6xl items-center gap-12 px-6 py-16 lg:grid-cols-2 lg:py-24">
        {/* Copy */}
        <div className="text-center lg:text-start">
          <h1
            id="hero-heading"
            className="text-3xl font-bold leading-tight text-slate-900 sm:text-4xl lg:text-5xl"
          >
            הבוט שעונה ללקוחות, אוסף לידים וקובע פגישות —{' '}
            <span className="text-leaf">אוטומטית בוואטסאפ.</span>
          </h1>

          <p className="mx-auto mt-5 max-w-xl text-base leading-relaxed text-slate-600 sm:text-lg lg:mx-0">
            בלי קוד, בלי מפתח, בלי אפליקציה ללקוח. מקימים בוט חכם בדקות, מחברים את
            הוואטסאפ של העסק — והוא עובד בשבילכם 24/7.
          </p>

          <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row sm:justify-center lg:justify-start">
            <a
              href="/auth/google"
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-leaf px-6 py-3 text-base font-semibold text-white transition-colors hover:bg-leaf-dark sm:w-auto"
            >
              <Icon name="brand-google" size={20} />
              התחילו חינם
            </a>
            <a
              href="#how-it-works"
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-6 py-3 text-base font-medium text-slate-800 transition-colors hover:border-slate-400 hover:bg-slate-50 sm:w-auto"
            >
              איך זה עובד
            </a>
          </div>
        </div>

        {/* Decorative chat mock (pure CSS, illustrative only). */}
        <div aria-hidden="true" className="hidden lg:block">
          <div className="mx-auto max-w-sm rounded-3xl border border-slate-200 bg-white p-5 shadow-lg">
            <div className="mb-4 flex items-center gap-3 border-b border-slate-100 pb-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-brand text-white">
                <Icon name="robot" size={22} />
              </span>
              <div>
                <p className="text-sm font-semibold text-slate-900">הבוט של העסק</p>
                <p className="text-xs text-leaf">מחובר · עכשיו</p>
              </div>
            </div>

            <div className="flex flex-col gap-3">
              <p className="max-w-[80%] self-start rounded-2xl rounded-tr-sm bg-slate-100 px-4 py-2 text-sm text-slate-800">
                היי! אשמח לקבוע תור 🙂
              </p>
              <p className="max-w-[85%] self-end rounded-2xl rounded-tl-sm bg-[#DCF8C6] px-4 py-2 text-sm text-slate-800">
                בשמחה! לאיזה שירות, ומתי נוח לך?
              </p>
              <p className="max-w-[80%] self-start rounded-2xl rounded-tr-sm bg-slate-100 px-4 py-2 text-sm text-slate-800">
                תספורת, מחר בבוקר
              </p>
              <p className="max-w-[85%] self-end rounded-2xl rounded-tl-sm bg-[#DCF8C6] px-4 py-2 text-sm text-slate-800">
                קבעתי לך מחר ב-09:30 ✅ נתראה!
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
