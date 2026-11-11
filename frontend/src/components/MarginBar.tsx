import { pct } from '../lib/format'

export type Scale = { lo: number; hi: number }

/** The scale every margin bar on a screen shares, so bars compare down the column. */
export function sharedScale(rows: { margin_before: number; margin_after: number; margin_floor: number }[]): Scale | undefined {
  if (!rows.length) return undefined
  const lo = Math.min(...rows.map((r) => Math.min(r.margin_after, r.margin_floor)))
  const hi = Math.max(...rows.map((r) => Math.max(r.margin_before, r.margin_floor)))
  return { lo: lo - 0.01, hi: hi + 0.01 }
}

const pts = (v: number) => `${(Math.abs(v) * 100).toFixed(1)} pts`

/** Margin as quoted, margin now, and the floor between them.
 *
 *  The sentence underneath carries the meaning ("0.7 pts below the 27.7% floor,
 *  was 3.0 pts above"); the bar illustrates it. Everything left of the floor tick
 *  is the shaded below-floor zone, the hollow dot is the margin as quoted and the
 *  arrowhead is the margin now. */
export function MarginBar({ before, after, floor, scale }: { before: number; after: number; floor: number; scale?: Scale }) {
  const lo = scale?.lo ?? Math.min(after, floor) - 0.012
  const hi = scale?.hi ?? Math.max(before, floor) + 0.012
  const x = (v: number) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100))
  const below = after < floor
  const text = below ? 'text-stop' : 'text-go'
  const fill = below ? 'bg-stop' : 'bg-go'
  const left = Math.min(x(before), x(after))
  const width = Math.abs(x(before) - x(after))
  const gapNow = after - floor
  const gapThen = before - floor

  return (
    <div className="w-full min-w-48">
      <p className="font-label text-[13px] text-ink-dim">
        Quoted <span className="text-ink">{pct(before)}</span> → now <span className={`font-semibold ${text}`}>{pct(after)}</span>
      </p>

      <div className="relative mt-6 h-2.5" role="img" aria-label={`Margin ${pct(before)} as quoted, ${pct(after)} now, floor ${pct(floor)}`}>
        <span
          className="absolute bottom-full mb-2 -translate-x-1/2 font-label text-[12px] font-semibold uppercase leading-none tracking-[0.06em] text-attn"
          style={{ left: `${x(floor)}%` }}
        >
          floor
        </span>
        <div className="absolute inset-y-0 left-0 bg-stop/20" style={{ width: `${x(floor)}%` }} />
        <div className="absolute inset-y-0 right-0 bg-sheet-2" style={{ left: `${x(floor)}%` }} />
        <div className="absolute -inset-y-1 w-0.5 bg-attn" style={{ left: `calc(${x(floor)}% - 1px)` }} />
        <div className={`absolute top-1/2 h-0.5 -translate-y-1/2 ${fill}`} style={{ left: `${left}%`, width: `${width}%` }} />
        <div className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink bg-ground" style={{ left: `${x(before)}%` }} />
        <div
          className={`absolute top-1/2 h-0 w-0 -translate-y-1/2 border-y-[6px] border-r-[8px] border-y-transparent ${below ? 'border-r-stop' : 'border-r-go'}`}
          style={{ left: `calc(${x(after)}% - 3px)` }}
        />
      </div>

      <p className={`mt-2 font-label text-[13px] font-semibold ${text}`}>
        {Math.abs(gapNow) < 0.0005 ? 'Right at' : `${pts(gapNow)} ${below ? 'below' : 'above'}`} the {pct(floor)} floor
        <span className="font-normal text-ink-dim"> · was {pts(gapThen)} {gapThen >= 0 ? 'above' : 'below'}</span>
      </p>
    </div>
  )
}
