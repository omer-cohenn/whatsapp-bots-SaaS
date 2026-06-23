// Tiny in-house line chart (M13). NO chart library — a plain inline-SVG line
// chart so we never pull a heavy dep into node_modules (the project's known
// stale-deps trap; we mirror UsageBarChart's approach). It draws 1–2 series
// over a shared x-axis (the same days), the second series dashed so the two
// read apart without relying on colour alone. The line is decorative; meaning
// lives in the figure's aria-label + per-point <title> tooltips, and the parent
// should render an accessible total/summary alongside.

type Series = {
  /** y-values, oldest → newest. Must line up with `labels`. */
  values: number[]
  /** Stroke colour (a hex from the brand palette). */
  color: string
  /** Short name for this series (used in tooltips). */
  name: string
  /** Render dashed (the secondary series). */
  dashed?: boolean
}

type Props = {
  /** x-axis labels (ISO dates or short text), one per data point. */
  labels: string[]
  /** 1 or 2 series. */
  series: Series[]
  /** Accessible name describing the whole chart. */
  ariaLabel: string
  /** Optional formatter for the tooltip value (e.g. money). Defaults to String. */
  formatValue?: (v: number) => string
  /** Fill the area under each line (clearer "body" for cumulative charts). */
  fillArea?: boolean
}

// Fixed viewBox; the SVG scales responsively to its container width.
const VIEW_W = 600
const VIEW_H = 160
const PAD_X = 8
const PAD_TOP = 10
const PAD_BOTTOM = 6

function shortDay(label: string): string {
  const d = new Date(label)
  if (Number.isNaN(d.getTime())) return label
  return d.toLocaleDateString('he-IL', { day: 'numeric', month: 'numeric' })
}

export default function LineChart({
  labels,
  series,
  ariaLabel,
  formatValue = (v) => String(v),
  fillArea = false,
}: Props) {
  const n = labels.length
  // Shared y-scale across both series so they're comparable.
  const max = series.reduce(
    (m, s) => s.values.reduce((mm, v) => Math.max(mm, v), m),
    0,
  )

  const plotW = VIEW_W - PAD_X * 2
  const plotH = VIEW_H - PAD_TOP - PAD_BOTTOM
  // x position for point i; single-point series sits centred.
  const xAt = (i: number) => (n > 1 ? PAD_X + (i / (n - 1)) * plotW : VIEW_W / 2)
  // y position for value v (0 at the baseline, max at the top).
  const yAt = (v: number) =>
    PAD_TOP + (max > 0 ? plotH - (v / max) * plotH : plotH)

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-label={ariaLabel}
        preserveAspectRatio="none"
        className="h-40 w-full"
      >
        {/* Baseline */}
        <line
          x1={PAD_X}
          y1={PAD_TOP + plotH}
          x2={VIEW_W - PAD_X}
          y2={PAD_TOP + plotH}
          stroke="#e2e8f0"
          strokeWidth="1"
        />
        {series.map((s) => {
          // Build the polyline path; guard against empty/mismatched series.
          const pts = s.values.map((v, i) => `${xAt(i)},${yAt(v)}`).join(' ')
          const baseY = PAD_TOP + plotH
          return (
            <g key={s.name}>
              {fillArea && n > 1 ? (
                // Close the line down to the baseline so the area below it fills —
                // a flat cumulative line reads as a solid block, not a floating wire.
                <polygon
                  points={`${xAt(0)},${baseY} ${pts} ${xAt(n - 1)},${baseY}`}
                  fill={s.color}
                  fillOpacity="0.14"
                  stroke="none"
                />
              ) : null}
              {n > 1 ? (
                <polyline
                  points={pts}
                  fill="none"
                  stroke={s.color}
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeDasharray={s.dashed ? '6 5' : undefined}
                  vectorEffect="non-scaling-stroke"
                />
              ) : null}
              {s.values.map((v, i) => (
                <circle
                  key={`${s.name}-${i}`}
                  cx={xAt(i)}
                  cy={yAt(v)}
                  r={n > 30 ? 0 : 2.5}
                  fill={s.color}
                >
                  <title>{`${s.name} · ${shortDay(labels[i])}: ${formatValue(v)}`}</title>
                </circle>
              ))}
            </g>
          )
        })}
      </svg>
    </figure>
  )
}
