import { pct } from '../lib/format'

/** The display-figure style: Archivo Narrow 600 with tabular numerals. Numbers only. */
export const FIGURE = 'font-figure font-semibold tabular-nums'

/** The margin-floor bar, the product's one signature chart.
 *
 *  A track with a tick at the floor, a hollow dot at the margin as quoted and an arrow to the
 *  margin now, each labelled on the bar ("Quoted 31.2%", "Now 28.2%", "Floor 29.7%"). The part
 *  of the track below the floor is terracotta, the rest dim. It replaces the margin numbers
 *  wherever it appears, and appears once per screen: the To decide panel, the Quote check
 *  verdict and a Leakage job's detail. Never in list rows.
 *
 *  The scale is fitted to the three values with room either side, so the labels on the two
 *  outer points can run outward without leaving the bar. */
export function MarginBar({ before, after, floor, beforeLabel = 'Quoted', afterLabel = 'Now' }: {
  before: number
  after: number
  floor: number
  beforeLabel?: string
  afterLabel?: string
}) {
  const lo0 = Math.min(before, after, floor)
  const hi0 = Math.max(before, after, floor)
  const span = Math.max(hi0 - lo0, 0.01)
  const lo = lo0 - span * 0.75
  const hi = hi0 + span * 0.75
  const x = (v: number) => ((v - lo) / (hi - lo)) * 100
  const below = after < floor
  const fell = after < before
  const same = Math.abs(after - before) < 0.0005
  const left = Math.min(x(before), x(after))
  const width = Math.abs(x(before) - x(after))

  // The point further left takes its label to the left, the other to the right, so they never meet.
  const label = (text: string, v: number, side: 'left' | 'right', tone = 'text-ink') => (
    <span
      className="absolute bottom-full mb-2 whitespace-nowrap text-[13px] leading-none text-ink-dim"
      style={{ left: `${x(v)}%`, transform: side === 'left' ? 'translateX(calc(-100% + 5px))' : 'translateX(-5px)' }}
    >
      {text} <span className={`font-semibold ${tone}`}>{pct(v)}</span>
    </span>
  )

  return (
    <div
      className="relative mb-7 mt-7 h-1.5 w-full min-w-48"
      role="img"
      aria-label={`Margin ${pct(before)} ${beforeLabel.toLowerCase()}, ${pct(after)} ${afterLabel.toLowerCase()}, floor ${pct(floor)}${below ? ', below the floor' : ''}.`}
    >
      {/* Track: terracotta below the floor, dim above it. */}
      <div className="absolute inset-y-0 left-0 rounded-l-full bg-stop/45" style={{ width: `${x(floor)}%` }} />
      <div className="absolute inset-y-0 right-0 rounded-r-full bg-rule-bright" style={{ left: `${x(floor)}%` }} />
      {/* Floor tick and its label underneath. */}
      <div className="absolute -inset-y-1.5 w-0.5 bg-ink" style={{ left: `calc(${x(floor)}% - 1px)` }} />
      <span className="absolute top-full mt-2.5 -translate-x-1/2 whitespace-nowrap text-[13px] leading-none text-ink-dim" style={{ left: `${x(floor)}%` }}>
        Floor <span className="font-semibold text-ink">{pct(floor)}</span>
      </span>

      {same ? null : (
        <>
          {/* The move from quoted to now, with its arrowhead at now. */}
          <div className={`absolute top-1/2 h-0.5 -translate-y-1/2 ${below ? 'bg-stop' : 'bg-ink'}`} style={{ left: `${left}%`, width: `${width}%` }} />
          <div
            className={`absolute top-1/2 h-0 w-0 -translate-y-1/2 border-y-[6px] border-y-transparent ${
              fell ? `border-r-[9px] ${below ? 'border-r-stop' : 'border-r-ink'}` : `border-l-[9px] ${below ? 'border-l-stop' : 'border-l-ink'}`}`}
            style={{ left: fell ? `calc(${x(after)}% - 2px)` : `calc(${x(after)}% - 7px)` }}
          />
        </>
      )}
      <div className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink bg-sheet" style={{ left: `${x(before)}%` }} />

      {same
        ? label(`${beforeLabel} and ${afterLabel.toLowerCase()}`, before, 'right', below ? 'text-stop' : 'text-ink')
        : (
          <>
            {label(beforeLabel, before, fell ? 'right' : 'left')}
            {label(afterLabel, after, fell ? 'left' : 'right', below ? 'text-stop' : 'text-ink')}
          </>
        )}
    </div>
  )
}
