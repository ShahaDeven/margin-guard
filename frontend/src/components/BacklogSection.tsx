import { Fragment, useEffect, useState } from 'react'

import { api } from '../lib/api'
import { materialLabel, pct, shortDate, unitPrice, usd } from '../lib/format'
import type { Backlog, BacklogOrder } from '../lib/types'
import { Button } from './Button'
import { FIGURE } from './MarginBar'

const head = 'border-b border-rule px-4 py-3 text-[13px] font-medium text-ink-dim'
const cell = 'border-b border-rule-soft px-4 py-3'
const link = 'text-[13px] text-go hover:text-go-soft'

/** Increases are terracotta; give-backs and zero are plain text, with a minus sign when negative. */
const money = (v: number, digits = 0) => (v ? usd(v, digits) : '–')
const tone = (v: number) => (v > 0 ? 'text-stop' : 'text-ink')

/** Orders still to buy: won orders whose material isn't bought yet. Their price is fixed, so
 *  every increase that lands before the buy date comes out of margin. The one lever left is
 *  buying the material early. */
export function BacklogSection({ version, onViewQuote, run, focusQuote }: {
  version: number
  onViewQuote: (quoteId: string) => void
  run: (fn: () => Promise<unknown>) => void
  /** Open this order's detail first (from a Home link). */
  focusQuote?: string
}) {
  const [r, setR] = useState<Backlog | null>(null)
  const [open, setOpen] = useState<string | null>(focusQuote ?? null)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => { api.backlog().then(setR).catch(() => setR(null)) }, [version])
  useEffect(() => {
    if (focusQuote) document.getElementById(`order-${focusQuote}`)?.scrollIntoView({ block: 'center' })
  }, [focusQuote, r])
  if (!r) return <p className="text-ink-dim">Loading…</p>
  if (!r.orders.length) return <p className="text-ink">No won orders are waiting for material.</p>

  const sorted = [...r.orders].sort((a, b) => b.absorbing_usd - a.absorbing_usd)
  const affected = sorted.filter((o) => o.absorbing_usd !== 0 || o.material_bought_on)
  const unaffected = sorted.filter((o) => o.absorbing_usd === 0 && !o.material_bought_on)
  const shown = showAll ? [...affected, ...unaffected] : affected
  const buyable = r.orders.filter((o) => o.buy_before && !o.material_bought_on)

  return (
    <div className="flex flex-col gap-5">
      <div>
        {/* Both counts, labelled in one sentence; the second is the same one Home shows. */}
        <h2 className="text-xl font-semibold text-ink">
          {r.waiting} won order{r.waiting === 1 ? '' : 's'} still to buy.{' '}
          {r.orders_absorbing ? (
            <>
              {r.orders_absorbing} absorb{r.orders_absorbing === 1 ? 's' : ''} increases,{' '}
              <span className={`${FIGURE} text-[28px] text-stop`}>{usd(r.absorbing_usd)}</span> in total.
            </>
          ) : 'None absorb increases.'}
        </h2>
        <p className="mt-1 max-w-3xl text-ink">
          These jobs are won, so their prices are fixed and can't be revised. Their material is bought when the job is
          scheduled, so every increase on file that takes effect before then comes out of their margin
          {r.below_floor ? <>, and {r.below_floor} will land below {r.below_floor === 1 ? 'its' : 'their'} floor</> : null}.
          {r.gaining_usd ? <> Decreases give {usd(r.gaining_usd)} back on others.</> : null}
        </p>
      </div>

      {buyable.length ? (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-md border border-rule bg-sheet px-4 py-3">
          <p className="min-w-0 flex-1 text-ink">
            <span className="font-semibold">Buying now saves {usd(r.buy_now_saves_usd)}.</span>{' '}
            {buyable.length === r.orders_absorbing
              ? `${buyable.length === 1 ? 'It is' : `All ${buyable.length} are`} worth buying early`
              : `${buyable.length} of them ${buyable.length === 1 ? 'is' : 'are'} worth buying early`}: an increase still to
            come lands before {buyable.length === 1 ? 'its' : 'their'} buy date.
            {buyable.length < r.orders_absorbing ? ' For the others, the increase is already in effect.' : ''}
            {' '}Whether the cash and the storage are worth it is your call.
          </p>
          <Button tone="go" className="font-semibold" onClick={() => run(async () => {
            for (const o of buyable) await api.buyNow(o.quote_id)
          })}>
            Buy now for {buyable.length} order{buyable.length === 1 ? '' : 's'}
          </Button>
        </div>
      ) : null}
      {r.bought_early ? (
        <p className="text-[13px] text-ink-dim">
          Bought early so far: {r.bought_early} order{r.bought_early === 1 ? '' : 's'}, {usd(r.saved_by_buying_early_usd)} kept.
        </p>
      ) : null}

      <div className="overflow-x-auto rounded-md border border-rule bg-sheet">
        <table className="w-full min-w-[640px] border-collapse">
          <thead>
            <tr className="text-left">
              <th className={head}>Order</th>
              <th className={head}>Buying</th>
              <th className={`${head} text-right`}>Order value</th>
              <th className={head}>Margin</th>
              <th className={`${head} text-right`}>Absorbing</th>
              <th className={`${head} relative`}><span className="sr-only">Action</span></th>
            </tr>
          </thead>
          <tbody>
            {shown.map((o) => (
              <Fragment key={o.quote_id}>
                <tr id={`order-${o.quote_id}`} className={`cursor-pointer align-top ${open === o.quote_id ? 'bg-sheet-2' : 'hover:bg-sheet-2/50'}`}
                  onClick={() => setOpen(open === o.quote_id ? null : o.quote_id)}>
                  <td className={cell}>
                    <div className="font-semibold">{o.customer_name}</div>
                    <div className="text-[13px] text-ink-dim">{o.quote_id}</div>
                  </td>
                  <td className={cell}>{o.material_bought_on ? `Bought early, ${shortDate(o.material_bought_on)}` : shortDate(o.material_buy_date)}</td>
                  <td className={`${cell} text-right`}>{usd(o.revenue_usd)}</td>
                  <td className={cell}>
                    <div>{pct(o.margin_as_ordered)} as ordered</div>
                    <div className={`text-[13px] ${o.below_floor ? 'text-stop' : 'text-ink-dim'}`}>
                      {pct(o.margin_at_buy)} at buy{o.below_floor ? `, under the ${pct(o.margin_floor)} floor` : ''}
                    </div>
                  </td>
                  <td className={`${cell} text-right font-semibold ${tone(o.absorbing_usd)}`}>{money(o.absorbing_usd)}</td>
                  <td className={`${cell} text-right`} onClick={(e) => e.stopPropagation()}>
                    {o.material_bought_on
                      ? <Button small onClick={() => run(() => api.undoBuy(o.quote_id))}>Undo</Button>
                      : o.buy_before ? <Button small onClick={() => run(() => api.buyNow(o.quote_id))}>Buy now</Button> : null}
                  </td>
                </tr>
                {open === o.quote_id ? <Detail o={o} onViewQuote={onViewQuote} /> : null}
              </Fragment>
            ))}
          </tbody>
        </table>
        {unaffected.length ? (
          <div className="px-4 py-3">
            <button type="button" className={link} onClick={() => setShowAll(!showAll)}>
              {showAll ? 'Hide the unaffected orders' : `Show ${unaffected.length} unaffected order${unaffected.length === 1 ? '' : 's'}`}
            </button>
          </div>
        ) : null}
      </div>
      <p className="text-[13px] text-ink-dim">
        {r.assumption} Orders with no planned buy date count as bought on the order date, the same assumption as Already leaked.
      </p>
    </div>
  )
}

function Detail({ o, onViewQuote }: { o: BacklogOrder; onViewQuote: (quoteId: string) => void }) {
  return (
    <tr>
      <td colSpan={6} className="border-b border-rule-soft bg-ground/40 px-4 pb-4 pt-3">
        {o.changes.length ? (
          <ul className="mb-3 space-y-1 text-[13px] text-ink">
            {o.changes.map((c) => (
              <li key={c.material_id}>
                {materialLabel(c.material_id)}: {unitPrice(c.cost_as_ordered)} to {unitPrice(c.cost_at_buy)}/lb from {shortDate(c.effective_date)}
                <span className="text-ink-dim">{c.after_today ? ', still to come' : ', already in effect'}</span>
                {': '}<span className={tone(c.absorbing_usd)}>{money(c.absorbing_usd, 2)}</span>
              </li>
            ))}
          </ul>
        ) : <p className="mb-3 text-[13px] text-ink-dim">No cost has moved since this order came in.</p>}
        {o.buy_before && !o.material_bought_on ? (
          <p className="mb-3 text-[13px] text-ink">Buying before {shortDate(o.buy_before)} keeps {usd(o.buy_now_saves_usd, 2)} of this order's margin.</p>
        ) : null}
        <table className="w-full text-[13px]">
          <thead className="text-left text-ink-dim">
            <tr>
              <th className="pb-1 font-normal">Part and material</th>
              <th className="pb-1 text-right font-normal">Pounds</th>
              <th className="pb-1 text-right font-normal">As ordered</th>
              <th className="pb-1 text-right font-normal">Today</th>
              <th className="pb-1 text-right font-normal">At buy</th>
              <th className="pb-1 text-right font-normal">Absorbing</th>
            </tr>
          </thead>
          <tbody>
            {o.lines.map((l, i) => (
              <tr key={`${l.line_id}-${l.material_id}-${i}`} className="border-t border-rule-soft">
                <td className="py-1 text-ink">{l.part_name}, <span className="text-ink-dim">{materialLabel(l.material_id)}</span></td>
                <td className="py-1 text-right text-ink-dim">{l.lb.toLocaleString('en-US', { maximumFractionDigits: 0 })}</td>
                <td className="py-1 text-right text-ink">{unitPrice(l.cost_as_ordered)}</td>
                <td className="py-1 text-right text-ink">{unitPrice(l.cost_today)}</td>
                <td className="py-1 text-right text-ink">{unitPrice(l.cost_at_buy)}</td>
                <td className={`py-1 text-right ${tone(l.absorbing_usd)}`}>{money(l.absorbing_usd, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" className={`${link} mt-2`} onClick={() => onViewQuote(o.quote_id)}>Open {o.quote_id} in shop data</button>
      </td>
    </tr>
  )
}
