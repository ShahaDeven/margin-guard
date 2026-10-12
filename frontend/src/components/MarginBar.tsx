import { pct } from '../lib/format'

/** Margin before → after against the floor.
 *
 *  The words carry the meaning ("0.7 pts below the 27.7% floor"); the bar only
 *  illustrates it. The zone below the floor is tinted red, and the arrow runs from
 *  the margin as quoted to the margin after the cost change, so "the arrowhead
 *  is in the red zone" reads without a legend. */
export function MarginBar({ before, after, floor }: { before: number; after: number; floor: number }) {
  const lo = Math.min(after, floor) - 0.012
  const hi = Math.max(before, floor) + 0.012
  const x = (v: number) => ((v - lo) / (hi - lo)) * 100
  const below = after < floor
  const gap = Math.abs(after - floor) * 100
  const left = Math.min(x(before), x(after))
  const width = Math.abs(x(before) - x(after))

  return (
    <div className="w-full min-w-44">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-silver-dim">Margin</span>
        <span className="font-mono text-xs text-silver">
          {pct(before)} → <span className={below ? 'text-signal' : 'text-cyan'}>{pct(after)}</span>
        </span>
      </div>

      <div className="relative mt-2 h-3">
        {/* below-floor zone */}
        <div className="absolute inset-y-0 left-0 rounded-l-sm bg-signal/15" style={{ width: `${x(floor)}%` }} />
        <div className="absolute inset-y-0 right-0 rounded-r-sm bg-panel-2" style={{ left: `${x(floor)}%` }} />
        {/* floor line */}
        <div className="absolute -inset-y-0.5 w-0.5 bg-hiviz" style={{ left: `calc(${x(floor)}% - 1px)` }} />
        {/* was → now */}
        <div className={`absolute top-1/2 h-0.5 -translate-y-1/2 ${below ? 'bg-signal' : 'bg-cyan'}`} style={{ left: `${left}%`, width: `${width}%` }} />
        <div className="absolute top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-silver-dim bg-weave" style={{ left: `${x(before)}%` }} />
        <div
          className={`absolute top-1/2 h-0 w-0 -translate-y-1/2 border-y-[5px] border-r-[7px] border-y-transparent ${below ? 'border-r-signal' : 'border-r-cyan'}`}
          style={{ left: `calc(${x(after)}% - 3px)` }}
        />
      </div>

      <p className={`mt-1.5 text-[11px] ${below ? 'text-signal' : 'text-cyan'}`}>
        {gap < 0.05 ? 'right at' : `${gap.toFixed(1)} pts ${below ? 'below' : 'above'}`} the {pct(floor)} floor
      </p>
    </div>
  )
}
