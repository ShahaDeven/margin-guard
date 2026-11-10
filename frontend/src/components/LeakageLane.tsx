import { pct, shortDate, usd } from '../lib/format'
import type { Leakage } from '../lib/types'
import { MarginBar, sharedScale } from './MarginBar'
import { Family } from './QuoteParts'
import { Empty } from './RulesLane'

const head = 'pb-2 font-label text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-dim'

/** The owner's view: margin won jobs already lost because costs moved between
 *  quote and order. Every figure comes from margin_guard/leakage.py over the
 *  won quotes and the price history; nothing here is estimated by a model. */
export function LeakageLane({ r }: { r: Leakage | null }) {
  if (!r) return <Empty text="Loading the leakage report…" />
  if (!r.won_jobs || !r.period) return <Empty text="No won quotes with an order date yet, so there is nothing to look back on." />

  const worst = Math.max(...r.by_material.map((m) => Math.abs(m.leak_usd)), 1)
  const months = r.by_month
  const peak = Math.max(...months.map((m) => Math.abs(m.leak_usd)), 1)
  const scale = sharedScale(r.top_jobs.map((j) => ({ margin_before: j.margin_quoted, margin_after: j.margin_realized, margin_floor: j.margin_floor })))

  return (
    <div className="space-y-6">
      <section className="rounded-sm border border-rule bg-sheet px-6 py-5">
        <h2 className="font-label text-2xl font-semibold text-ink-bright">
          {usd(r.leaked_usd)} of margin leaked on {r.jobs_leaked} of {r.won_jobs} won jobs
        </h2>
        <p className="mt-1 max-w-3xl text-[15px] leading-relaxed text-ink">
          Between {shortDate(r.period.from)} and {shortDate(r.period.to)}, costs moved after these jobs were quoted and
          before the customer ordered, so they shipped at the old price on new costs. Decreases gave back{' '}
          {usd(r.gained_usd)}, for {usd(r.net_leaked_usd)} net. Margin went from {pct(r.margin_quoted)} as quoted to{' '}
          {pct(r.margin_realized)} as ordered, and {r.below_floor_jobs} job{r.below_floor_jobs === 1 ? ' was' : 's were'} pushed below its floor.
        </p>
        <p className="mt-3 text-xs text-ink-dim">
          {r.assumption} Every dollar comes from a change that took effect inside the quote's window, when a revised quote
          could still have recovered it.
          {r.skipped_jobs.length ? ` ${r.skipped_jobs.length} won jobs were left out: a material had no cost history back to the quote date.` : ''}
        </p>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section className="rounded-sm border border-rule bg-sheet px-5 py-4">
          <h3 className="mb-3 font-label text-lg font-semibold text-ink-bright">By material</h3>
          <table className="w-full text-sm">
            <thead><tr className="text-left"><th className={head}>Material</th><th className={head}>Leaked</th><th className={`${head} text-right`}>Jobs</th></tr></thead>
            <tbody>
              {r.by_material.map((m) => (
                <tr key={m.material_id} className="border-t border-rule">
                  <td className="py-2 pr-3 text-ink-bright"><Family id={m.material_id}>{m.material_name}</Family></td>
                  <td className="w-1/2 py-2 pr-3">
                    <div className="flex items-center gap-3">
                      <div className="h-2 flex-1 bg-sheet-2">
                        <div className={`h-2 ${m.leak_usd >= 0 ? 'bg-stop/80' : 'bg-go/80'}`} style={{ width: `${(Math.abs(m.leak_usd) / worst) * 100}%` }} />
                      </div>
                      <span className={`w-20 text-right font-label text-[13px] ${m.leak_usd >= 0 ? 'text-ink-bright' : 'text-go'}`}>{usd(m.leak_usd)}</span>
                    </div>
                  </td>
                  <td className="py-2 text-right font-label text-ink-dim">{m.jobs}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="rounded-sm border border-rule bg-sheet px-5 py-4">
          <h3 className="mb-3 font-label text-lg font-semibold text-ink-bright">By order month</h3>
          <div className="flex h-40 items-end gap-2">
            {months.map((m) => (
              <div key={m.month} className="flex flex-1 flex-col items-center gap-1.5">
                <span className="font-label text-[12px] text-ink-dim">{m.leak_usd ? usd(m.leak_usd) : ''}</span>
                <div className={`w-full ${m.leak_usd >= 0 ? 'bg-stop/80' : 'bg-go/80'}`} style={{ height: `${(Math.abs(m.leak_usd) / peak) * 100}px` }} />
                <span className="font-label text-[12px] text-ink">{new Date(`${m.month}-15T12:00:00`).toLocaleDateString('en-US', { month: 'short' })}</span>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-ink-dim">{months.reduce((s, m) => s + m.jobs, 0)} won jobs by the month the customer ordered.</p>
        </section>
      </div>

      <section className="rounded-sm border border-rule bg-sheet px-5 py-4">
        <h3 className="mb-1 font-label text-lg font-semibold text-ink-bright">Jobs that leaked the most</h3>
        <p className="mb-3 text-xs text-ink-dim">Margin bars share one scale. Quoted is the margin the job was priced at; now is the margin at the costs on the order date.</p>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left">
              <th className={head}>Job</th><th className={head}>Quoted → ordered</th><th className={`${head} w-72`}>Margin</th>
              <th className={`${head} text-right`}>Revenue</th><th className={`${head} text-right`}>Leaked</th>
            </tr>
          </thead>
          <tbody>
            {r.top_jobs.map((j) => (
              <tr key={j.quote_id} className="border-t border-rule align-top">
                <td className="py-3 pr-4">
                  <span className="text-ink-bright">{j.customer_name}</span>
                  <span className="block font-label text-[12px] text-ink-dim">{j.quote_id}</span>
                  <span className="mt-1 flex flex-wrap gap-x-3 font-label text-[12px] text-ink-dim">
                    {Object.entries(j.by_material).map(([m, v]) => <Family key={m} id={m}>{`${m.replace(/^MAT-/, '')} ${usd(v)}`}</Family>)}
                  </span>
                </td>
                <td className="py-3 pr-4 font-label text-[13px] text-ink">{shortDate(j.issued_date)} → {shortDate(j.ordered_date)}</td>
                <td className="py-3 pr-4"><MarginBar before={j.margin_quoted} after={j.margin_realized} floor={j.margin_floor} scale={scale} /></td>
                <td className="py-3 text-right font-label text-[13px] text-ink">{usd(j.revenue_usd)}</td>
                <td className="py-3 text-right font-label text-[15px] font-semibold text-ink-bright">{usd(j.leak_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}
