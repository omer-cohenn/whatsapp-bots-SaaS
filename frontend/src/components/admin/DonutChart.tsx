// Tiny in-house donut chart (M13). NO chart library — a plain inline-SVG donut
// drawn from stroke-dasharray arc segments, with a centred total and an
// accessible legend (label · value · share). Mirrors UsageBarChart's "the SVG
// is decorative; the legend carries the meaning" approach. Colours come from
// the brand palette (passed per slice). Empty / all-zero data renders a neutral
// ring + a "0" centre so the panel is never blank.

export type DonutSlice = {
  label: string
  value: number
  /** Slice colour (a hex from the brand palette). */
  color: string
}

type Props = {
  slices: DonutSlice[]
  /** Accessible name for the whole figure. */
  ariaLabel: string
  /** Small caption shown under the centre total (e.g. "סה""כ"). */
  centerCaption?: string
}

// Geometry: a square viewBox, ring drawn as a stroked circle.
const SIZE = 120
const R = 48
const STROKE = 18
const CIRC = 2 * Math.PI * R
const CENTER = SIZE / 2

export default function DonutChart({ slices, ariaLabel, centerCaption }: Props) {
  const total = slices.reduce((sum, s) => sum + s.value, 0)

  // Build arc segments as dash offsets around the ring (start at 12 o'clock).
  let acc = 0
  const segments =
    total > 0
      ? slices
          .filter((s) => s.value > 0)
          .map((s) => {
            const frac = s.value / total
            const seg = {
              color: s.color,
              dash: frac * CIRC,
              gap: CIRC - frac * CIRC,
              offset: -acc * CIRC,
            }
            acc += frac
            return seg
          })
      : []

  return (
    <div className="flex flex-wrap items-center gap-5">
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label={ariaLabel}
        className="h-32 w-32 flex-shrink-0 -rotate-90"
      >
        {/* Track ring (always present, so an all-zero chart still shows). */}
        <circle
          cx={CENTER}
          cy={CENTER}
          r={R}
          fill="none"
          stroke="#e2e8f0"
          strokeWidth={STROKE}
        />
        {segments.map((seg, i) => (
          <circle
            key={i}
            cx={CENTER}
            cy={CENTER}
            r={R}
            fill="none"
            stroke={seg.color}
            strokeWidth={STROKE}
            strokeDasharray={`${seg.dash} ${seg.gap}`}
            strokeDashoffset={seg.offset}
          />
        ))}
        {/* Centre total — un-rotate the text so it reads upright. */}
        <g transform={`rotate(90 ${CENTER} ${CENTER})`}>
          <text
            x={CENTER}
            y={centerCaption ? CENTER - 1 : CENTER + 5}
            textAnchor="middle"
            className="fill-slate-900 text-[20px] font-semibold tabular-nums"
          >
            {total}
          </text>
          {centerCaption ? (
            <text
              x={CENTER}
              y={CENTER + 14}
              textAnchor="middle"
              className="fill-slate-500 text-[9px]"
            >
              {centerCaption}
            </text>
          ) : null}
        </g>
      </svg>

      {/* Legend — the accessible source of truth.
          הטבעת היא 128px קבועים והמקרא קצר, אז השניים נכנסים זה לצד זה גם
          ב-358px; ה-flex-wrap שמעל כבר מוריד את המקרא לשורה משלו אם צריך.
          min-w-0 מונע מהמקרא להרחיב את הכרטיס ולדחוף גלילה אופקית. */}
      <ul className="flex min-w-0 flex-col gap-2 text-sm">
        {slices.map((s) => {
          const pct = total > 0 ? Math.round((s.value / total) * 100) : 0
          return (
            <li key={s.label} className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className="h-3 w-3 flex-shrink-0 rounded-sm"
                style={{ backgroundColor: s.color }}
              />
              <span className="text-slate-700">{s.label}</span>
              <span className="font-medium tabular-nums text-slate-900">
                {s.value}
              </span>
              <span className="text-xs text-slate-400">({pct}%)</span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
