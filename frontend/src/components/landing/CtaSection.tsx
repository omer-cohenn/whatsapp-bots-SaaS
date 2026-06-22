// Closing call-to-action band on the leaf-green brand color, with a high-
// contrast white button linking to the Google sign-in flow.

export default function CtaSection() {
  return (
    <section aria-labelledby="cta-heading" className="bg-leaf">
      <div className="mx-auto max-w-4xl px-6 py-16 text-center lg:py-20">
        <h2
          id="cta-heading"
          className="text-2xl font-bold text-white sm:text-3xl"
        >
          מוכנים להתחיל?
        </h2>
        <p className="mx-auto mt-3 max-w-xl text-base text-white/90">
          חיבור מהיר, בלי קוד — והבוט עובד בשבילכם כבר היום.
        </p>
        <a
          href="/auth/google"
          className="mt-8 inline-flex items-center justify-center rounded-lg bg-white px-8 py-3 text-base font-semibold text-leaf-ink transition-colors hover:bg-leaf-soft"
        >
          התחילו חינם
        </a>
      </div>
    </section>
  )
}
