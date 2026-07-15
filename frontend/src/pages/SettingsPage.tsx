// Owner settings page: display-mode toggle + account deletion.
// All text is Hebrew, layout is RTL.

import { useState } from 'react'
import DashboardLayout from '../components/DashboardLayout'
import Modal from '../components/ui/Modal'
import Alert from '../components/ui/Alert'
import Icon from '../components/ui/Icon'
import { useTheme } from '../lib/ThemeContext'
import { deleteAccount } from '../lib/dashboardClient'

// ── Dark-mode toggle ────────────────────────────────────────────────────────

function ThemeToggleRow() {
  const { theme, toggleTheme } = useTheme()
  const isDark = theme === 'dark'

  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-sm font-medium text-slate-800 dark:text-slate-100">
        מצב כהה
      </span>

      {/* Pill-shaped toggle switch — aria-pressed + visible focus ring */}
      <button
        type="button"
        role="switch"
        aria-checked={isDark}
        aria-label={isDark ? 'כבה מצב כהה' : 'הפעל מצב כהה'}
        onClick={toggleTheme}
        className={[
          'relative inline-flex h-7 w-12 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent',
          'transition-colors duration-200 ease-in-out',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2',
          isDark ? 'bg-leaf' : 'bg-slate-300',
        ].join(' ')}
      >
        {/* Sliding circle */}
        <span
          aria-hidden="true"
          className={[
            'pointer-events-none inline-block h-6 w-6 rounded-full bg-white shadow',
            'transform transition duration-200 ease-in-out',
            isDark ? '-translate-x-5' : 'translate-x-0',
          ].join(' ')}
        />
      </button>
    </div>
  )
}

// ── Delete-account section ──────────────────────────────────────────────────

function DeleteAccountSection() {
  const [modalOpen, setModalOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleConfirmDelete() {
    setLoading(true)
    setError(null)
    try {
      await deleteAccount()
      // Force a full page reload so the session cookie is cleared from state
      // and the user lands on the public landing page.
      window.location.href = '/'
    } catch {
      setError('אירעה שגיאה במחיקת החשבון. אנא נסה שוב מאוחר יותר.')
      setLoading(false)
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setModalOpen(true)}
        className="inline-flex items-center gap-2 rounded-lg border border-bad px-4 py-2 text-sm font-medium text-bad transition hover:bg-red-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bad focus-visible:ring-offset-2 dark:hover:bg-red-950"
      >
        <Icon name="trash" size={16} />
        מחק חשבון
      </button>

      <Modal
        open={modalOpen}
        title="מחיקת חשבון"
        onClose={() => {
          if (!loading) setModalOpen(false)
        }}
      >
        <p className="mb-4 text-sm leading-relaxed text-slate-700 dark:text-slate-300">
          האם למחוק את חשבון העסק לצמיתות? כל המידע — לידים, שיחות, הגדרות הבוט
          — יימחק ולא ניתן לשחזר.
        </p>

        {error && (
          <Alert tone="error" className="mb-4">
            {error}
          </Alert>
        )}

        <div className="flex justify-start gap-3">
          {/* Primary action on the right (RTL = visual left) */}
          <button
            type="button"
            onClick={handleConfirmDelete}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg bg-bad px-4 py-2 text-sm font-medium text-white transition hover:bg-red-800 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bad focus-visible:ring-offset-2"
          >
            {loading ? 'מוחק…' : 'כן, מחק לצמיתות'}
          </button>

          <button
            type="button"
            onClick={() => setModalOpen(false)}
            disabled={loading}
            className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
          >
            ביטול
          </button>
        </div>
      </Modal>
    </>
  )
}

// ── Page ────────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  return (
    <DashboardLayout>
      <div className="p-6 md:p-8">
        {/* Page heading */}
        <div className="mb-8 flex items-center gap-3">
          <Icon name="settings" size={24} className="text-leaf-deep dark:text-leaf-light" />
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">הגדרות</h1>
        </div>

        <div className="max-w-lg space-y-6">
          {/* ── Section 1: Display ───────────────────────────────────────── */}
          <section
            aria-labelledby="section-display"
            className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-800"
          >
            <h2
              id="section-display"
              className="mb-4 text-base font-semibold text-slate-900 dark:text-white"
            >
              מצב תצוגה
            </h2>
            <ThemeToggleRow />
          </section>

          {/* ── Section 2: Account ───────────────────────────────────────── */}
          <section
            aria-labelledby="section-account"
            className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-800"
          >
            <h2
              id="section-account"
              className="mb-1 text-base font-semibold text-slate-900 dark:text-white"
            >
              חשבון
            </h2>
            <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
              פעולות בלתי-הפיכות. יש להשתמש בזהירות.
            </p>
            <DeleteAccountSection />
          </section>
        </div>
      </div>
    </DashboardLayout>
  )
}
