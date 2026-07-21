// Tiny in-house stacked-bar chart (M13). NO chart library — a plain inline-SVG
// bar chart that stacks up to two series per category, mirroring UsageBarChart.
// One bar per category (e.g. a plan code), split into a bottom + top segment.
// The SVG is decorative; meaning lives in the figure aria-label, per-segment
// <title> tooltips, the x-axis category labels and the legend the parent shows.

export type StackedCategory = {
  /** x-axis label for this bar (e.g. a plan name). */
  label: string
  /** Bottom segment value. */
  a: number
  /** Top segment value (stacked on top of `a`). */
  b: number
}

type Props = {
  categories: StackedCategory[]
  /** Bottom-segment colour + name (for the legend/tooltip). */
  aColor: string
  aName: string
  /** Top-segment colour + name. */
  bColor: string
  bName: string
  /** Accessible name for the whole figure. */
  ariaLabel: string
}

const VIEW_W = 600
const VIEW_H = 180
const PAD_TOP = 10
const PAD_BOTTOM = 26 // room for the category labels

export default function StackedBarChart({
  categories,
  aColor,
  aName,
  bColor,
  bName,
  ariaLabel,
}: Props) {
  const n = categories.length
  const max = categories.reduce((m, c) => Math.max(m, c.a + c.b), 0)

  const plotH = VIEW_H - PAD_TOP - PAD_BOTTOM
  const slot = n > 0 ? VIEW_W / n : VIEW_W
  const barW = Math.min(64, Math.max(8, slot * 0.5))
  const hAt = (v: number) => (max > 0 ? (v / max) * plotH : 0)
  const baseline = PAD_TOP + plotH

  return (
    <figure className="m-0">
      {/* הגרף היחיד כאן שיש בתוכו טקסט (שמות התוכניות על ציר ה-x). ה-SVG
          מוקטן יחד עם המכולה, כך שגם הטקסט מוקטן: ב-358px ה-viewBox של 600
          מתכווץ לפקטור 0.6 והתוויות יורדות ל-~6.5px — בלתי קריא. לכן דווקא
          כאן בוחרים גלילה אופקית עם רוחב מינימלי של 480px (פקטור ~0.8,
          תוויות ~9px): עדיף לגלול מעט מאשר להסתכל על גרף שאי אפשר לקרוא.
          הגלילה היא של המכולה בלבד — העמוד לא נגלל לצדדים. */}
      <div className="min-w-0 overflow-x-auto">
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-label={ariaLabel}
        className="h-44 w-full min-w-[480px] sm:min-w-0"
      >
        {/* Baseline */}
        <line
          x1="0"
          y1={baseline}
          x2={VIEW_W}
          y2={baseline}
          stroke="#e2e8f0"
          strokeWidth="1"
        />
        {categories.map((c, i) => {
          const cx = i * slot + slot / 2
          const x = cx - barW / 2
          const hA = hAt(c.a)
          const hB = hAt(c.b)
          const yA = baseline - hA
          const yB = yA - hB
          return (
            <g key={c.label}>
              {hA > 0 ? (
                <rect x={x} y={yA} width={barW} height={hA} fill={aColor} rx="2">
                  <title>{`${c.label} · ${aName}: ${c.a}`}</title>
                </rect>
              ) : null}
              {hB > 0 ? (
                <rect x={x} y={yB} width={barW} height={hB} fill={bColor} rx="2">
                  <title>{`${c.label} · ${bName}: ${c.b}`}</title>
                </rect>
              ) : null}
              <text
                x={cx}
                y={VIEW_H - 8}
                textAnchor="middle"
                className="fill-slate-500 text-[11px]"
              >
                {c.label}
              </text>
            </g>
          )
        })}
      </svg>
      </div>

      {/* Legend */}
      <ul className="mt-2 flex flex-wrap items-center gap-4 text-xs text-slate-600">
        <li className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="h-3 w-3 rounded-sm"
            style={{ backgroundColor: aColor }}
          />
          {aName}
        </li>
        <li className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="h-3 w-3 rounded-sm"
            style={{ backgroundColor: bColor }}
          />
          {bName}
        </li>
      </ul>
    </figure>
  )
}
