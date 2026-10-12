import { pct } from '../lib/format'

/** Margin before → after against the floor, on one small track.
 *  The point an estimator needs at a glance: did we cross the line? */
export function MarginBar({ before, after, floor }: { before: number; after: number; floor: number }) {
  const lo = Math.min(after, floor) - 0.015
  const hi = Math.max(before, floor) + 0.015
  const x = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`
  const below = after < floor

  return (
    <div className="w-full min-w-40">
      <div className="relative h-2 rounded-full bg-panel-2">
        {/* drop from before to after */}
        <div
          className={`absolute top-0 h-2 rounded-full ${below ? 'bg-signal/35' : 'bg-cyan/25'}`}
          style={{ left: x(after), width: `calc(${x(before)} - ${x(after)})` }}
        />
        <div className="absolute -top-1 h-4 w-px bg-hiviz" style={{ left: x(floor) }} title={`floor ${pct(floor)}`} />
        <div className="absolute top-0 h-2 w-2 -translate-x-1/2 rounded-full bg-silver-dim" style={{ left: x(before) }} />
        <div
          className={`absolute top-0 h-2 w-2 -translate-x-1/2 rounded-full ${below ? 'bg-signal' : 'bg-cyan'}`}
          style={{ left: x(after) }}
        />
      </div>
      <div className="mt-1.5 flex justify-between font-mono text-[10px] text-silver-dim">
        <span>
          {pct(before)} → <span className={below ? 'text-signal' : 'text-cyan'}>{pct(after)}</span>
        </span>
        <span className="text-hiviz/80">floor {pct(floor)}</span>
      </div>
    </div>
  )
}
