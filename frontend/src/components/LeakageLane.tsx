import { Fragment, useState } from 'react'

import { materialLabel, pct, shortDate, usd } from '../lib/format'
import type { HistoryRow, Leakage, LeakageJob } from '../lib/types'
import { BacklogSection } from './BacklogSection'
import { FIGURE, MarginBar } from './MarginBar'
import { Empty } from './RulesLane'

const head = 'border-b border-rule px-4 py-3 text-[13px] font-medium text-ink-dim'
const cell = 'border-b border-rule-soft px-4 py-3'
const link = 'text-[13px] text-go hover:text-go-soft'
const panel = 'rounded-md border border-rule bg-sheet'

/** Money lost is terracotta; money gained back is plain text with a minus sign. */
const tone = (v: number) => (v > 0 ? 'text-stop' : 'text-ink')

type Filter =
  | { kind: 'leaked'; label: string }
  | { kind: 'locked'; label: string }
  | { kind: 'material'; id: string; label: string }
  | { kind: 'month'; month: string; label: string }

export type LeakageTab = 'orders' | 'leaked'

const monthName = (m: string) => new Date(`${m}-15T12:00:00`).toLocaleDateString('en-US', { month: 'long' })

/** The Leakage page: two tabs under the heading, one table each. */
export function LeakagePage({ tab, setTab, r, version, run, onViewQuote, focusMaterial, focusQuote }: {
  tab: LeakageTab
  setTab: (t: LeakageTab) => void
  r: Leakage | null
  version: number
  run: (fn: () => Promise<unknown>) => void
  onViewQuote: (quoteId: string) => void
  focusMaterial?: string
  focusQuote?: string
}) {
  const tabs: { id: LeakageTab; label: string }[] = [
    { id: 'orders', label: 'Orders still to buy' },
    { id: 'leaked', label: 'Already leaked' },
  ]
  return (
    <div className="flex flex-col gap-6">
      <div role="tablist" aria-label="Leakage" className="flex gap-1 border-b border-rule">
        {tabs.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
            className={`-mb-px min-h-11 border-b-2 px-3 transition-colors ${
              tab === t.id ? 'border-go font-semibold text-go-soft' : 'border-transparent text-ink hover:text-go-soft'}`}>
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === 'orders'
          ? <BacklogSection version={version} onViewQuote={onViewQuote} run={run} focusQuote={focusQuote} />
          : <LeakageLane key={focusMaterial ?? ''} r={r} onViewQuote={onViewQuote} focusMaterial={focusMaterial} />}
      </div>
    </div>
  )
}

/** Already leaked: margin won jobs lost because costs moved between quote and order. Every
 *  figure comes from margin_guard/leakage.py over the won quotes and the price history;
 *  nothing here is estimated by a model. Every figure opens the jobs behind it, and every
 *  job opens its calculation. */
export function LeakageLane({ r, onViewQuote, focusMaterial }: {
  r: Leakage | null
  onViewQuote: (quoteId: string) => void
  focusMaterial?: string
}) {
  const initial = focusMaterial && r?.by_material.find((m) => m.material_id === focusMaterial)
  const [filter, setFilter] = useState<Filter | null>(
    initial ? { kind: 'material', id: initial.material_id, label: materialLabel(initial.material_id) } : null)
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
  const pick = (f: Filter) => {
    setFilter(f)
    setOpen(null)
    document.getElementById('leak-jobs')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="flex flex-col gap-6">
      <section>
        <h2 className="text-xl font-semibold text-ink">
          <span className={`${FIGURE} text-[28px] text-stop`}>{usd(r.leaked_usd)}</span> of margin leaked on {r.jobs_leaked} of {r.won_jobs} won jobs
        </h2>
        <p className="mt-1 max-w-3xl text-ink">
          Between {shortDate(r.period.from)} and {shortDate(r.period.to)}, costs moved after these jobs were quoted and
          before the customer ordered, so they shipped at the old price on new costs. Decreases gave back{' '}
          {usd(r.gained_usd)}, for {usd(r.net_leaked_usd)} net. Margin went from {pct(r.margin_quoted)} as quoted to{' '}
          {pct(r.margin_realized)} as ordered, and {r.below_floor_jobs} job{r.below_floor_jobs === 1 ? ' was' : 's were'} pushed below its floor.
        </p>
        <p className="mt-3 max-w-3xl text-ink">
          <span className="font-semibold">{usd(r.recoverable_usd)} was recoverable</span> by a revised quote or a call
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
        <p className="mt-3 text-[13px] text-ink-dim">
          {r.assumption} Every dollar comes from a change that took effect inside the quote's window, when a revised quote
          could still have recovered it, unless a price lock covered the order date. Locks are each customer's current lock;
          lock history is not recorded.
          {r.skipped_jobs.length ? ` ${r.skipped_jobs.length} won jobs were left out: a material had no cost history back to the quote date.` : ''}
        </p>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section className={`${panel} min-w-0 px-5 py-4`}>
          <h3 className="text-lg font-semibold text-ink">By material</h3>
          <p className="mb-3 text-[13px] text-ink-dim">Click a material to see the jobs behind its figure.</p>
          <ul className="flex flex-col gap-1">
            {r.by_material.map((m) => {
              const on = filter?.kind === 'material' && filter.id === m.material_id
              return (
                <li key={m.material_id}>
                  <button type="button" aria-pressed={on}
                    onClick={() => pick({ kind: 'material', id: m.material_id, label: materialLabel(m.material_id) })}
                    className={`grid w-full grid-cols-[minmax(0,8rem)_minmax(0,1fr)_5rem_3rem] items-center gap-3 rounded-sm px-2 py-1.5 text-left ${on ? 'bg-sheet-2' : 'hover:bg-sheet-2/60'}`}>
                    <span className="truncate" title={m.material_name}>{materialLabel(m.material_id)}</span>
                    <span className="h-2.5 rounded-[2px] bg-rule-soft" aria-hidden>
                      <span className={`block h-2.5 rounded-[2px] ${m.leak_usd >= 0 ? 'bg-stop' : 'bg-ink-dim'}`} style={{ width: `${(Math.abs(m.leak_usd) / worst) * 100}%` }} />
                    </span>
                    <span className={`text-right tabular-nums ${tone(m.leak_usd)}`}>{usd(m.leak_usd)}</span>
                    <span className="text-right text-[13px] text-ink-dim">{m.jobs} job{m.jobs === 1 ? '' : 's'}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </section>

        <section className={`${panel} min-w-0 px-5 py-4`}>
          <h3 className="text-lg font-semibold text-ink">By order month</h3>
          <p className="mb-3 text-[13px] text-ink-dim">Click a month to see the jobs ordered in it.</p>
          <div className="flex h-44 items-end gap-1 sm:gap-2">
            {months.map((m) => {
              const on = filter?.kind === 'month' && filter.month === m.month
              return (
                <button key={m.month} type="button" aria-pressed={on}
                  aria-label={`${monthName(m.month)}: ${usd(m.leak_usd)} on ${m.jobs} jobs`}
                  onClick={() => pick({ kind: 'month', month: m.month, label: `jobs ordered in ${monthName(m.month)}` })}
                  className={`flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1.5 rounded-sm px-0.5 pb-1 ${on ? 'bg-sheet-2' : 'hover:bg-sheet-2/60'}`}>
                  <span className="hidden text-xs text-ink-dim sm:block">{m.leak_usd ? usd(m.leak_usd) : ''}</span>
                  <span className={`block w-full rounded-[2px] ${m.leak_usd >= 0 ? 'bg-stop' : 'bg-ink-dim'}`} style={{ height: `${(Math.abs(m.leak_usd) / peak) * 100}px` }} />
                  <span className={`text-xs ${on ? 'font-semibold text-ink' : 'text-ink-dim'}`}>{monthName(m.month).slice(0, 3)}</span>
                </button>
              )
            })}
          </div>
          <p className="mt-3 text-[13px] text-ink-dim">{months.reduce((s, m) => s + m.jobs, 0)} won jobs by the month the customer ordered.</p>
        </section>
      </div>

      <section id="leak-jobs" className="scroll-mt-6">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h3 className="text-lg font-semibold text-ink">
            {filter ? `Showing ${filter.kind === 'material' ? `jobs where ${filter.label} moved` : filter.label}` : 'Jobs that leaked the most'}
            <span className="ml-2 text-sm font-normal text-ink-dim">{shown.length} job{shown.length === 1 ? '' : 's'}</span>
          </h3>
          {filter ? <button type="button" className={link} onClick={() => { setFilter(null); setOpen(null) }}>Show the top 10 again</button> : null}
        </div>
        <div className={`${panel} overflow-x-auto`}>
          <table className="w-full min-w-[640px] border-collapse">
            <thead>
              <tr className="text-left">
                <th className={head}>Job</th><th className={head}>Quoted, ordered</th><th className={head}>Margin</th>
                <th className={`${head} text-right`}>Revenue</th><th className={`${head} text-right`}>Leaked</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((j) => {
                const isOpen = open === j.quote_id
                const below = j.margin_realized < j.margin_floor
                return (
                  <Fragment key={j.quote_id}>
                    <tr className={`align-top ${isOpen ? 'bg-sheet-2' : ''}`}>
                      <td className={cell}>
                        <div className="font-semibold">{j.customer_name}</div>
                        <div className="text-[13px] text-ink-dim">
                          {j.quote_id}{j.price_locked ? `, price lock to ${shortDate(j.price_lock_until)}` : ''}
                        </div>
                        <div className="mt-1 text-[13px] text-ink-dim">
                          {Object.entries(j.by_material).map(([m, v]) => `${materialLabel(m)} ${usd(v)}`).join(', ')}
                        </div>
                        <div className="mt-1.5 flex gap-4">
                          <button type="button" aria-expanded={isOpen} className={link} onClick={() => setOpen(isOpen ? null : j.quote_id)}>
                            {isOpen ? 'Hide trace' : 'Trace'}
                          </button>
                          <button type="button" className={link} onClick={() => onViewQuote(j.quote_id)}>Open in shop data</button>
                        </div>
                      </td>
                      <td className={cell}>
                        <div>{shortDate(j.issued_date)}</div>
                        <div className="text-[13px] text-ink-dim">ordered {shortDate(j.ordered_date)}</div>
                      </td>
                      <td className={cell}>
                        <div>{pct(j.margin_quoted)} as quoted</div>
                        <div className={`text-[13px] ${below ? 'text-stop' : 'text-ink-dim'}`}>
                          {pct(j.margin_realized)} as ordered{below ? `, under the ${pct(j.margin_floor)} floor` : ''}
                        </div>
                      </td>
                      <td className={`${cell} text-right`}>{usd(j.revenue_usd)}</td>
                      <td className={`${cell} text-right font-semibold ${tone(j.leak_usd)}`}>
                        {usd(j.leak_usd)}
                        {j.price_locked && j.leak_usd > 0 ? <span className="block text-[13px] font-normal text-ink-dim">locked in</span> : null}
                      </td>
                    </tr>
                    {isOpen ? (
                      <tr>
                        <td colSpan={5} className="border-b border-rule-soft bg-ground/40 px-4 pb-4 pt-3"><Trace j={j} /></td>
                      </tr>
                    ) : null}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

/** Where a cost came from: the price-history row's date and supplier. */
function Source({ row }: { row: HistoryRow | null }) {
  if (!row) return <span className="text-stop">no price history on that date</span>
  return (
    <span className="text-ink-dim">
      from {shortDate(row.effective_date)}, {row.vendor_name ?? 'a shop entry'}{row.email_id ? ', by email' : ''}
    </span>
  )
}

/** The leak for one job, row by row: qty × lb per unit × (1 + scrap) × (cost on the order date − cost on the quote date). */
function Trace({ j }: { j: LeakageJob }) {
  const sum = j.trace.reduce((s, t) => s + t.leak_usd, 0)
  const th = 'pb-1.5 text-[13px] font-medium text-ink-dim'
  return (
    <div>
      <div className="mb-6 max-w-xl">
        <MarginBar before={j.margin_quoted} after={j.margin_realized} floor={j.margin_floor} afterLabel="As ordered" />
      </div>
      <p className="mb-2 text-[13px] text-ink">
        Each line: quantity × lb per unit × (1 + scrap) × (material cost on the order date, {shortDate(j.ordered_date)}, minus the cost
        on the quote date, {shortDate(j.issued_date)}), at the costing supplier's price.
      </p>
      <table className="w-full table-fixed text-[13px]">
        <colgroup><col className="w-[22%]" /><col className="w-[12%]" /><col className="w-[16%]" /><col className="w-[19%]" /><col className="w-[19%]" /><col className="w-[12%]" /></colgroup>
        <thead>
          <tr className="text-left">
            <th className={th}>Line</th><th className={th}>Material</th><th className={th}>Qty × lb × scrap</th>
            <th className={th}>$/lb at quote</th><th className={th}>$/lb at order</th><th className={`${th} text-right`}>Leaked</th>
          </tr>
        </thead>
        <tbody>
          {j.trace.map((t) => {
            const moved = t.cost_at_order !== t.cost_at_quote
            return (
              <tr key={`${t.line_id}-${t.material_id}`} className={`border-t border-rule-soft align-top ${moved ? '' : 'opacity-60'}`}>
                <td className="py-2 pr-3 text-ink">{t.part_name}</td>
                <td className="py-2 pr-3">{materialLabel(t.material_id)}</td>
                <td className="py-2 pr-3 text-ink">{t.qty.toLocaleString()} × {t.lb_per_unit} lb × {(1 + t.scrap_rate).toFixed(2)}</td>
                <td className="py-2 pr-3">
                  <span className="text-ink">${t.cost_at_quote.toFixed(4)}</span>
                  <span className="block"><Source row={t.quote_row} /></span>
                </td>
                <td className="py-2 pr-3">
                  <span className={moved ? 'font-semibold text-ink' : 'text-ink'}>${t.cost_at_order.toFixed(4)}</span>
                  <span className="block"><Source row={t.order_row} /></span>
                </td>
                <td className={`py-2 text-right ${moved ? tone(t.leak_usd) : 'text-ink-dim'}`}>{moved ? usd(t.leak_usd, 2) : 'no move'}</td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr className="border-t border-rule">
            <td colSpan={5} className="pt-2 text-ink">Sum of the lines</td>
            <td className="pt-2 text-right text-ink">{usd(sum, 2)}</td>
          </tr>
          {Math.abs(j.basis_difference_usd) >= 0.01 ? (
            <tr>
              <td colSpan={5} className="text-ink-dim">The quote's own cost basis against price history on the quote date (rounding, or an estimator's number)</td>
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
            <td colSpan={5} className="font-semibold text-ink">Leaked on this job</td>
            <td className={`text-right font-semibold ${tone(j.leak_usd)}`}>{usd(j.leak_usd, 2)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
