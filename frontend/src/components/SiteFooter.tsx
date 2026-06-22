// Shared footer with legal links, shown on every page.
import { Link } from 'react-router-dom'

export default function SiteFooter() {
  return (
    <footer className="border-t border-slate-200 bg-white">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-center gap-x-4 gap-y-2 px-6 py-4 text-center text-sm text-slate-400">
        <span>© {new Date().getFullYear()} בוטיק</span>
        <Link to="/terms" className="rounded text-slate-500 hover:text-brand hover:underline">
          תנאי שימוש
        </Link>
        <Link to="/privacy" className="rounded text-slate-500 hover:text-brand hover:underline">
          מדיניות פרטיות
        </Link>
        <Link to="/accessibility" className="rounded text-slate-500 hover:text-brand hover:underline">
          הצהרת נגישות
        </Link>
      </div>
    </footer>
  )
}
