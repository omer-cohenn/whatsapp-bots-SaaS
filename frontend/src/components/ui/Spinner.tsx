// Accessible loading spinner. The wrapper carries aria-busy + a label so screen
// readers announce "loading". Animation honors prefers-reduced-motion via the
// global rule in index.css.

type SpinnerProps = {
  label?: string
  className?: string
}

export default function Spinner({ label = 'טוען…', className = '' }: SpinnerProps) {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-live="polite"
      className={`flex items-center justify-center gap-3 text-slate-600 ${className}`}
    >
      <span
        aria-hidden="true"
        className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-brand"
      />
      <span>{label}</span>
    </div>
  )
}
