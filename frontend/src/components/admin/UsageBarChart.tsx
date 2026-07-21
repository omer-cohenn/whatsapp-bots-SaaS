// Tiny in-house bar chart for the admin usage panel. NO chart library — a plain
// inline-SVG bar chart so we never pull a heavy dep into node_modules (the
// project's known stale-deps trap). It renders one bar per day for a single
// metric, scaled to the window's max. Bars are decorative; the meaning lives in
// the accessible summary table the parent renders alongside, plus per-bar
// <title> tooltips and an aria-label on the figure.

type Point = {
  day: string // ISO date (YYYY-MM-DD)
  value: number
}

type Props = {
  /** Series for ONE metric, oldest → newest. */
  points: Point[]
  /** Bar/fill colour (a hex from the brand palette). */
  color: string
  /** Accessible name describing what this chart shows. */
  ariaLabel: string
}

// Fixed viewBox; the SVG scales responsively to its container width.
const VIEW_W = 600
const VIEW_H = 140
const PAD_BOTTOM = 4 // leave a hair of room under the baseline

function shortDay(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('he-IL', { day: 'numeric', month: 'numeric' })
}

export default function UsageBarChart({ points, color, ariaLabel }: Props) {
  const max = points.reduce((m, p) => Math.max(m, p.value), 0)
  const n = points.length

  // Empty / all-zero windows still render a baseline so the panel isn't blank.
  const usableH = VIEW_H - PAD_BOTTOM
  // Bar geometry: split the width into n slots, bar fills ~70% of its slot.
  const slot = n > 0 ? VIEW_W / n : VIEW_W
  const barW = Math.max(2, slot * 0.7)

  return (
    <figure className="m-0">
      {/* כמו LineChart: אין טקסט בתוך ה-SVG ו-preserveAspectRatio="none",
          אז המקלות פשוט נדחסים ונשארים קריאים (30 ימים ב-358px = ~12px
          למקל). אין סיבה לגלילה אופקית — רק קצת יותר גובה בטלפון. */}
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-label={ariaLabel}
        preserveAspectRatio="none"
        className="h-36 w-full sm:h-32"
      >
        {/* Baseline */}
        <line
          x1="0"
          y1={usableH}
          x2={VIEW_W}
          y2={usableH}
          stroke="#e2e8f0"
          strokeWidth="1"
        />
        {points.map((p, i) => {
          // Scale: tallest bar = full height; everything else proportional.
          const h = max > 0 ? (p.value / max) * usableH : 0
          const x = i * slot + (slot - barW) / 2
          const y = usableH - h
          return (
            <rect
              key={p.day}
              x={x}
              y={y}
              width={barW}
              height={h}
              rx={barW > 6 ? 2 : 0}
              fill={color}
            >
              <title>{`${shortDay(p.day)}: ${p.value}`}</title>
            </rect>
          )
        })}
      </svg>
    </figure>
  )
}
