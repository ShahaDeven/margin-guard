import { Fragment, useEffect, useState } from 'react'

import { api } from '../lib/api'
import { materialLabel, pct, shortDate, unitPrice, usd } from '../lib/format'
import type { Backlog, BacklogOrder } from '../lib/types'
import { Button } from './Button'

const head = 'pb-2 font-label text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-dim'
const link = 'font-label text-[13px] font-semibold text-ink-dim underline-offset-2 hover:text-ink-bright hover:underline'

/** Won orders whose material isn't bought yet. Their price is fixed, so every increase that lands
 *  before the buy date comes out of margin. The one lever left is buying the material early. */
export function BacklogSection({ version, onViewQuote, run }: {
  version: number
  onViewQuote: (quoteId: string) => void
  run: (fn: () => Promise<unknown>) => void
}) {
  const [r, setR] = useState<Backlog | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => { api.backlog().then(setR).catch(() => setR(null)) }, [version])
  if (!r || !r.orders.length) return null

  return (
    <section className="rounded-sm border border-rule bg-sheet px-6 py-5">
      <h2 className="font-label text-2xl font-semibold text-ink-bright">
        {r.waiting} won order{r.waiting === 1 ? '' : 's'} still to buy material for:{' '}
        <span className={r.absorbing_usd ? 'text-stop' : ''}>{usd(r.absorbing_usd)} of increases to absorb</span>
      </h2>
      <p className="mt-1 max-w-3xl text-[15px] leading-relaxed text-ink">
        These jobs are won, so their prices are fixed and can't be revised. Their material is bought when the job is
        scheduled, so every increase on file that takes effect before then comes out of their margin
        {r.below_floor ? <>, and {r.below_floor} will land below {r.below_floor === 1 ? 'its' : 'their'} floor</> : null}.
        {r.gaining_usd ? <> Decreases give {usd(r.gaining_usd)} back on others.</> : null}
      </p>
      {r.buy_now_saves_usd ? (
        <p className="mt-3 max-w-3xl text-[15px] leading-relaxed text-ink">
          <span className="font-semibold text-go">Buying now saves {usd(r.buy_now_saves_usd)}</span>: those orders' material
          would be bought before the increases take effect. Whether that's worth the cash and the storage is your call.
        </p>
      ) : null}
      {r.bought_early ? (
        <p className="mt-2 text-sm text-ink-dim">
          Bought early so far: {r.bought_early} order{r.bought_early === 1 ? '' : 's'}, {usd(r.saved_by_buying_early_usd)} kept.
        </p>
      ) : null}

      <table className="mt-4 w-full text-sm">
        <thead>
          <tr className="text-left">
            <th className={head}>Order · customer</th>
            <th className={head}>Material bought</th>
            <th className={`${head} text-right`}>Order value</th>
            <th className={`${head} pl-4`}>Margin as ordered → at buy</th>
            <th className={`${head} text-right`}>Absorbing</th>
            <th className={`${head} pl-4`}></th>
          </tr>
        </thead>
        <tbody>
          {r.orders.map((o) => (
            <Fragment key={o.quote_id}>
              <tr className="cursor-pointer border-t border-rule hover:bg-sheet-2" onClick={() => setOpen(open === o.quote_id ? null : o.quote_id)}>
                <td className="py-2 pr-3">
                  <span className="font-label text-ink-bright">{o.quote_id}</span>
                  <span className="text-ink"> · {o.customer_name}</span>
                </td>
                <td className="py-2 pr-3 font-label text-ink">
                  {o.material_bought_on
                    ? <span className="text-go">bought early {shortDate(o.material_bought_on)}</span>
                    : <>planned {shortDate(o.material_buy_date)}</>}
                </td>
                <td className="py-2 text-right font-label text-ink">{usd(o.revenue_usd)}</td>
                <td className="py-2 pl-4 font-label">
                  <span className="text-ink">{pct(o.margin_as_ordered)}</span>
                  <span className="text-ink-dim"> → </span>
                  <span className={o.below_floor ? 'text-stop' : o.margin_at_buy < o.margin_as_ordered ? 'text-attn' : 'text-ink'}>{pct(o.margin_at_buy)}</span>
                  {o.below_floor ? <span className="ml-2 text-[12px] text-stop">below {pct(o.margin_floor)} floor</span> : null}
                </td>
                <td className={`py-2 text-right font-label ${o.absorbing_usd > 0 ? 'text-stop' : o.absorbing_usd < 0 ? 'text-go' : 'text-ink-dim'}`}>
                  {o.absorbing_usd ? usd(o.absorbing_usd) : '–'}
                </td>
                <td className="py-2 pl-4 text-right" onClick={(e) => e.stopPropagation()}>
                  {o.material_bought_on ? (
                    <Button small onClick={() => run(() => api.undoBuy(o.quote_id))}>Undo</Button>
                  ) : o.buy_before ? (
                    <Button small tone="go" onClick={() => run(() => api.buyNow(o.quote_id))}>
                      Buy now · save {usd(o.buy_now_saves_usd)}
                    </Button>
                  ) : null}
                </td>
              </tr>
              {open === o.quote_id ? <Detail o={o} onViewQuote={onViewQuote} /> : null}
            </Fragment>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-ink-dim">
        {r.assumption} Orders with no planned buy date count as bought on the order date, the same assumption as Leakage below.
      </p>
    </section>
  )
}

function Detail({ o, onViewQuote }: { o: BacklogOrder; onViewQuote: (quoteId: string) => void }) {
  return (
    <tr>
      <td colSpan={6} className="bg-sheet-2/40 px-3 pb-4 pt-2">
        {o.changes.length ? (
          <ul className="mb-3 space-y-1 text-[13px] text-ink">
            {o.changes.map((c) => (
              <li key={c.material_id}>
                <span className="font-semibold text-ink-bright">{materialLabel(c.material_id)}</span>{' '}
                {unitPrice(c.cost_as_ordered)} → {unitPrice(c.cost_at_buy)}/lb from {shortDate(c.effective_date)}
                {c.after_today ? <span className="text-attn"> (still to come)</span> : <span className="text-ink-dim"> (already in effect)</span>}
                {': '}<span className={c.absorbing_usd > 0 ? 'text-stop' : 'text-go'}>{usd(c.absorbing_usd, 2)}</span>
              </li>
            ))}
          </ul>
        ) : <p className="mb-3 text-[13px] text-ink-dim">No cost has moved since this order came in.</p>}
        {o.buy_before && !o.material_bought_on ? (
          <p className="mb-3 text-[13px] text-ink">
            Buying before {shortDate(o.buy_before)} keeps {usd(o.buy_now_saves_usd, 2)} of this order's margin.
          </p>
        ) : null}
        <table className="w-full font-label text-xs">
          <thead className="text-left text-[12px] uppercase tracking-wider text-ink-dim">
            <tr>
              <th className="pb-1 font-normal">Part · material</th>
              <th className="pb-1 text-right font-normal">Lb</th>
              <th className="pb-1 text-right font-normal">As ordered</th>
              <th className="pb-1 text-right font-normal">Today</th>
              <th className="pb-1 text-right font-normal">At buy</th>
              <th className="pb-1 text-right font-normal">Absorbing</th>
            </tr>
          </thead>
          <tbody>
            {o.lines.map((l, i) => (
              <tr key={`${l.line_id}-${l.material_id}-${i}`} className="border-t border-rule/60">
                <td className="py-1 text-ink">{l.part_name} <span className="text-ink-dim">· {materialLabel(l.material_id)}</span></td>
                <td className="py-1 text-right text-ink-dim">{l.lb.toLocaleString('en-US', { maximumFractionDigits: 0 })}</td>
                <td className="py-1 text-right text-ink">{unitPrice(l.cost_as_ordered)}</td>
                <td className="py-1 text-right text-ink">{unitPrice(l.cost_today)}</td>
                <td className="py-1 text-right text-ink-bright">{unitPrice(l.cost_at_buy)}</td>
                <td className={`py-1 text-right ${l.absorbing_usd > 0 ? 'text-stop' : l.absorbing_usd < 0 ? 'text-go' : 'text-ink-dim'}`}>
                  {l.absorbing_usd ? usd(l.absorbing_usd, 2) : '–'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" className={`${link} mt-2`} onClick={() => onViewQuote(o.quote_id)}>View {o.quote_id} in Data</button>
      </td>
    </tr>
  )
}
