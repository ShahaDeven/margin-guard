import { Fragment, useState } from 'react'

import { materialLabel, pct, shortDate, usd } from '../lib/format'
import type { HistoryRow, Leakage, LeakageJob } from '../lib/types'
import { MarginBar, sharedScale } from './MarginBar'
import { Family } from './QuoteParts'
import { Empty } from './RulesLane'

const head = 'pb-2 font-label text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-dim'
const link = 'font-label text-[13px] font-semibold text-ink-dim underline-offset-2 hover:text-ink-bright hover:underline'

type Filter =
  | { kind: 'leaked'; label: string }
  | { kind: 'locked'; label: string }
  | { kind: 'material'; id: string; label: string }
  | { kind: 'month'; month: string; label: string }

const monthName = (m: string) => new Date(`${m}-15T12:00:00`).toLocaleDateString('en-US', { month: 'long' })

/** The owner's view: margin won jobs already lost because costs moved between
 *  quote and order. Every figure comes from margin_guard/leakage.py over the
 *  won quotes and the price history; nothing here is estimated by a model.
 *  Every figure opens the jobs behind it, and every job opens its calculation. */
export function LeakageLane({ r, onViewQuote }: { r: Leakage | null; onViewQuote: (quoteId: string) => void }) {
  const [filter, setFilter] = useState<Filter | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  if (!r) return <Empty text="Loading the leakage report…" />
  if (!r.won_jobs || !r.period) return <Empty text="No won quotes with an order date yet, so there is nothing to look back on." />

  const worst = Math.max(...r.by_material.map((m) => Math.abs(m.leak_usd)), 1)
  const months = r.by_month
  const peak = Math.max(...months.map((m) => Math.abs(m.leak_usd)), 1)

  const byLeak = (a: LeakageJob, b: LeakageJob) => b.leak_usd - a.leak_usd
  const shown = !filter ? r.top_jobs
    : filter.kind === 'leaked' ? r.jobs.filter((j) => j.leak_usd > 0).sort(byLeak)
      : filter.kind === 'locked' ? r.jobs.filter((j) => j.leak_usd > 0 && j.price_locked).sort(byLeak)
      : filter.kind === 'material' ? r.jobs.filter((j) => filter.id in j.by_material).sort((a, b) => b.by_material[filter.id] - a.by_material[filter.id])
        : r.jobs.filter((j) => j.ordered_date.startsWith(filter.month) && j.leak_usd !== 0).sort(byLeak)
  const scale = sharedScale(shown.map((j) => ({ margin_before: j.margin_quoted, margin_after: j.margin_realized, margin_floor: j.margin_floor })))
  const pick = (f: Filter) => {
    setFilter(f)
    setOpen(null)
    document.getElementById('leak-jobs')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

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
        <p className="mt-3 max-w-3xl text-[15px] leading-relaxed text-ink">
          <span className="font-semibold text-ink-bright">{usd(r.recoverable_usd)} was recoverable</span> by a revised quote or a call
          before the order. The other {usd(r.locked_usd)}, on {r.jobs_locked} job{r.jobs_locked === 1 ? '' : 's'}, was locked in: the
          customer had a price lock covering the order date, so those prices could not have moved.
        </p>
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1">
          <button type="button" className={link} onClick={() => pick({ kind: 'leaked', label: `all ${r.jobs_leaked} jobs that leaked` })}>
            Show all {r.jobs_leaked} jobs that leaked
          </button>
          {r.jobs_locked ? (
            <button type="button" className={link} onClick={() => pick({ kind: 'locked', label: `the ${r.jobs_locked} price-locked jobs` })}>
              Show the {r.jobs_locked} price-locked jobs
            </button>
          ) : null}
        </div>
        <p className="mt-3 text-xs text-ink-dim">
          {r.assumption} Every dollar comes from a change that took effect inside the quote's window, when a revised quote
          could still have recovered it, unless a price lock covered the order date. Locks are each customer's current lock;
          lock history is not recorded.
          {r.skipped_jobs.length ? ` ${r.skipped_jobs.length} won jobs were left out: a material had no cost history back to the quote date.` : ''}
        </p>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section className="rounded-sm border border-rule bg-sheet px-5 py-4">
          <h3 className="font-label text-lg font-semibold text-ink-bright">By material</h3>
          <p className="mb-3 text-xs text-ink-dim">Click a material to see the jobs behind its figure.</p>
          <table className="w-full text-sm">
            <thead><tr className="text-left"><th className={head}>Material</th><th className={head}>Leaked</th><th className={`${head} text-right`}>Jobs</th></tr></thead>
            <tbody>
              {r.by_material.map((m) => {
                const on = filter?.kind === 'material' && filter.id === m.material_id
                return (
                  <tr key={m.material_id} className={`border-t border-rule ${on ? 'bg-sheet-2' : ''}`}>
                    <td className="py-2 pr-3">
                      <button
                        type="button"
                        aria-pressed={on}
                        onClick={() => pick({ kind: 'material', id: m.material_id, label: m.material_name })}
                        className="text-left text-ink-bright underline-offset-2 hover:underline"
                      >
                        <Family id={m.material_id}>{m.material_name}</Family>
                      </button>
                    </td>
                    <td className="w-1/2 py-2 pr-3">
                      <div className="flex items-center gap-3">
                        <div className="h-2 flex-1 bg-sheet-2">
                          <div className={`h-2 ${m.leak_usd >= 0 ? 'bg-stop/70' : 'bg-go/70'}`} style={{ width: `${(Math.abs(m.leak_usd) / worst) * 100}%` }} />
                        </div>
                        <span className={`w-20 text-right font-label text-[13px] ${m.leak_usd >= 0 ? 'text-ink-bright' : 'text-go'}`}>{usd(m.leak_usd)}</span>
                      </div>
                    </td>
                    <td className="py-2 text-right font-label text-ink-dim">{m.jobs}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>

        <section className="rounded-sm border border-rule bg-sheet px-5 py-4">
          <h3 className="font-label text-lg font-semibold text-ink-bright">By order month</h3>
          <p className="mb-3 text-xs text-ink-dim">Click a month to see the jobs ordered in it.</p>
          <div className="flex h-44 items-end gap-2">
            {months.map((m) => {
              const on = filter?.kind === 'month' && filter.month === m.month
              return (
                <button
                  key={m.month}
                  type="button"
                  aria-pressed={on}
                  aria-label={`${monthName(m.month)}: ${usd(m.leak_usd)} on ${m.jobs} jobs`}
                  onClick={() => pick({ kind: 'month', month: m.month, label: `jobs ordered in ${monthName(m.month)}` })}
                  className={`group flex h-full flex-1 flex-col items-center justify-end gap-1.5 rounded-sm px-0.5 pb-1 ${on ? 'bg-sheet-2' : 'hover:bg-sheet-2/60'}`}
                >
                  <span className="font-label text-[12px] text-ink-dim">{m.leak_usd ? usd(m.leak_usd) : ''}</span>
                  <span className={`block w-full ${m.leak_usd >= 0 ? 'bg-stop/70' : 'bg-go/70'}`} style={{ height: `${(Math.abs(m.leak_usd) / peak) * 100}px` }} />
                  <span className={`font-label text-[12px] ${on ? 'font-semibold text-ink-bright' : 'text-ink'}`}>{monthName(m.month).slice(0, 3)}</span>
                </button>
              )
            })}
          </div>
          <p className="mt-3 text-xs text-ink-dim">{months.reduce((s, m) => s + m.jobs, 0)} won jobs by the month the customer ordered.</p>
        </section>
      </div>

      <section id="leak-jobs" className="scroll-mt-20 rounded-sm border border-rule bg-sheet px-5 py-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h3 className="font-label text-lg font-semibold text-ink-bright">
            {filter ? `Showing ${filter.kind === 'material' ? `jobs where ${filter.label} moved` : filter.label}` : 'Jobs that leaked the most'}
            <span className="ml-2 font-normal text-ink-dim">{shown.length} job{shown.length === 1 ? '' : 's'}</span>
          </h3>
          {filter ? <button type="button" className={link} onClick={() => { setFilter(null); setOpen(null) }}>Show the top 10 again</button> : null}
        </div>
        <p className="mb-3 text-xs text-ink-dim">
          Margin bars share one scale. Quoted is the margin the job was priced at; now is the margin at the costs on the order date.
          Open a trace to see every line and the price-history rows behind it.
        </p>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left">
              <th className={head}>Job</th><th className={head}>Quoted → ordered</th><th className={`${head} w-72`}>Margin</th>
              <th className={`${head} text-right`}>Revenue</th><th className={`${head} text-right`}>Leaked</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((j) => {
              const isOpen = open === j.quote_id
              return (
                <Fragment key={j.quote_id}>
                  <tr className={`border-t border-rule align-top ${isOpen ? 'bg-sheet-2/60' : ''}`}>
                    <td className="py-3 pr-4">
                      <span className="text-ink-bright">{j.customer_name}</span>
                      {j.price_locked ? (
                        <span className="ml-2 rounded-sm border border-rule-bright px-1.5 py-px align-[1px] font-label text-[12px] tracking-wider text-ink">
                          PRICE LOCK TO {shortDate(j.price_lock_until).toUpperCase()}
                        </span>
                      ) : null}
                      <span className="block font-label text-[12px] text-ink-dim">{j.quote_id}</span>
                      <span className="mt-1 flex flex-wrap gap-x-3 font-label text-[12px] text-ink-dim">
                        {Object.entries(j.by_material).map(([m, v]) => <Family key={m} id={m}>{`${materialLabel(m)} ${usd(v)}`}</Family>)}
                      </span>
                      <span className="mt-2 flex gap-4">
                        <button type="button" aria-expanded={isOpen} className={link} onClick={() => setOpen(isOpen ? null : j.quote_id)}>
                          {isOpen ? 'Hide trace' : 'Trace'}
                        </button>
                        <button type="button" className={link} onClick={() => onViewQuote(j.quote_id)}>Open {j.quote_id} in Data</button>
                      </span>
                    </td>
                    <td className="py-3 pr-4 font-label text-[13px] text-ink">{shortDate(j.issued_date)} → {shortDate(j.ordered_date)}</td>
                    <td className="py-3 pr-4"><MarginBar before={j.margin_quoted} after={j.margin_realized} floor={j.margin_floor} scale={scale} /></td>
                    <td className="py-3 text-right font-label text-[13px] text-ink">{usd(j.revenue_usd)}</td>
                    <td className="py-3 text-right font-label text-[15px] font-semibold text-ink-bright">
                      {usd(j.leak_usd)}
                      {j.price_locked && j.leak_usd > 0 ? <span className="block text-[12px] font-normal text-ink-dim">locked in</span> : null}
                    </td>
                  </tr>
                  {isOpen ? (
                    <tr className="bg-sheet-2/60">
                      <td colSpan={5} className="px-4 pb-4"><Trace j={j} /></td>
                    </tr>
                  ) : null}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </section>
    </div>
  )
}

/** Where a cost came from: the price-history row, its date and supplier, and the email if one sent it. */
function Source({ row }: { row: HistoryRow | null }) {
  if (!row) return <span className="text-stop">no price history on that date</span>
  return (
    <span className="text-ink-dim">
      from {shortDate(row.effective_date)}
      {row.vendor_name ? ` · ${row.vendor_name}` : ' · shop entry'}
      {row.email_id ? <> · email <span className="text-ink">{row.email_id}</span></> : ` · history row #${row.id}`}
    </span>
  )
}

/** The leak for one job, row by row: qty × lb per unit × (1 + scrap) × (cost on the order date − cost on the quote date). */
function Trace({ j }: { j: LeakageJob }) {
  const sum = j.trace.reduce((s, t) => s + t.leak_usd, 0)
  return (
    <div className="rounded-sm border border-rule bg-sheet px-4 py-3">
      <p className="mb-2 text-[13px] text-ink">
        Each line: quantity × lb per unit × (1 + scrap) × (material cost on the order date {shortDate(j.ordered_date)} − cost on the
        quote date {shortDate(j.issued_date)}), at the costing supplier's price.
      </p>
      <table className="w-full table-fixed text-[13px]">
        <colgroup><col className="w-[22%]" /><col className="w-[12%]" /><col className="w-[16%]" /><col className="w-[19%]" /><col className="w-[19%]" /><col className="w-[12%]" /></colgroup>
        <thead>
          <tr className="text-left">
            <th className={head}>Line</th><th className={head}>Material</th><th className={head}>Qty × lb × scrap</th>
            <th className={head}>$/lb at quote</th><th className={head}>$/lb at order</th><th className={`${head} text-right`}>Leaked</th>
          </tr>
        </thead>
        <tbody>
          {j.trace.map((t) => {
            const moved = t.cost_at_order !== t.cost_at_quote
            return (
              <tr key={`${t.line_id}-${t.material_id}`} className={`border-t border-rule align-top ${moved ? '' : 'opacity-60'}`}>
                <td className="py-2 pr-3 text-ink-bright">{t.part_name}<span className="block font-label text-[12px] text-ink-dim">line {t.line_id}</span></td>
                <td className="py-2 pr-3 font-label"><Family id={t.material_id} /></td>
                <td className="py-2 pr-3 font-label text-ink">
                  {t.qty.toLocaleString()} × {t.lb_per_unit} lb × {(1 + t.scrap_rate).toFixed(2)}
                </td>
                <td className="py-2 pr-3 font-label">
                  <span className="text-ink-bright">${t.cost_at_quote.toFixed(4)}</span>
                  <span className="block text-[12px]"><Source row={t.quote_row} /></span>
                </td>
                <td className="py-2 pr-3 font-label">
                  <span className={moved ? 'font-semibold text-ink-bright' : 'text-ink-bright'}>${t.cost_at_order.toFixed(4)}</span>
                  <span className="block text-[12px]"><Source row={t.order_row} /></span>
                </td>
                <td className={`py-2 text-right font-label ${t.leak_usd > 0 ? 'font-semibold text-ink-bright' : t.leak_usd < 0 ? 'text-go' : 'text-ink-dim'}`}>
                  {moved ? usd(t.leak_usd, 2) : 'no move'}
                </td>
              </tr>
            )
          })}
        </tbody>
        <tfoot className="font-label">
          <tr className="border-t border-rule-bright">
            <td colSpan={5} className="pt-2 text-ink">Sum of the lines</td>
            <td className="pt-2 text-right text-ink-bright">{usd(sum, 2)}</td>
          </tr>
          {Math.abs(j.basis_difference_usd) >= 0.01 ? (
            <tr>
              <td colSpan={5} className="text-ink-dim">The quote's own cost basis vs price history on the quote date (rounding, or an estimator's number)</td>
              <td className="text-right text-ink-dim">{usd(j.basis_difference_usd, 2)}</td>
            </tr>
          ) : null}
          {j.price_locked ? (
            <tr>
              <td colSpan={6} className="pt-1 text-ink-dim">
                {j.customer_name} has a price lock to {shortDate(j.price_lock_until)}, covering the order date, so this leak was locked in
                by the contract: a revised quote could not have recovered it.
              </td>
            </tr>
          ) : null}
          <tr>
            <td colSpan={5} className="font-semibold text-ink-bright">Leaked on this job</td>
            <td className="text-right text-[15px] font-semibold text-ink-bright">{usd(j.leak_usd, 2)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
