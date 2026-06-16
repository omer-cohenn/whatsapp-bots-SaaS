import StackHealth from './components/StackHealth.jsx'

export default function App() {
  return (
    <>
      {/* Keyboard users can jump straight to the main content (WCAG 2.4.1). */}
      <a href="#main" className="skip-link">
        דלגו לתוכן
      </a>

      <div className="flex min-h-screen flex-col">
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex max-w-5xl items-center px-6 py-4">
            <span className="text-xl font-bold text-brand">Bizz_up</span>
          </div>
        </header>

        <main id="main" className="mx-auto flex w-full max-w-5xl flex-1 flex-col items-center gap-10 px-6 py-16">
          {/* Placeholder hero */}
          <section aria-labelledby="hero-title" className="text-center">
            <h1 id="hero-title" className="text-4xl font-bold text-slate-900 sm:text-5xl">
              Bizz_up — בקרוב 🚀
            </h1>
            <p className="mt-4 text-lg text-slate-600">
              פלטפורמת בוטים חכמים לוואטסאפ לעסקים.
            </p>
          </section>

          {/* Stack health panel */}
          <StackHealth />
        </main>

        <footer className="border-t border-slate-200 bg-white">
          <div className="mx-auto max-w-5xl px-6 py-4 text-center text-sm text-slate-400">
            © {new Date().getFullYear()} Bizz_up
          </div>
        </footer>
      </div>
    </>
  )
}
