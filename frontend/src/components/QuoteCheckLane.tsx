import { useEffect, useMemo, useState } from 'react'

import { api } from '../lib/api'
import { materialLabel, pct, shortDate, usd } from '../lib/format'
import type { DataCustomer, Email, Part, QuoteCheck } from '../lib/types'
import { Button } from './Button'
import { MarginBar } from './MarginBar'

type Line = { key: number; part_id: string; qty: string; unit_price: string }

const label = 'mb-1 block text-[13px] text-ink-dim'
const head = 'pb-2 text-[13px] font-medium text-ink-dim'
const field = 'w-full rounded-sm border border-rule-bright bg-ground px-2.5 py-2 text-sm text-ink outline-none focus:border-go'
const panel = 'rounded-md border border-rule bg-sheet px-5 py-4'
const TARGET = 0.3   // a new line is priced at a 30% margin on today's cost until the estimator changes it
/** Shortening is the recommended way out only if the quote stays valid this long; otherwise price for the increases. */
const MIN_USEFUL_DAYS = 14

let seq = 0
const priceFor = (p?: Part) => (p ? (p.unit_cost_now / (1 - TARGET)).toFixed(4) : '')
const names = (ids: string[]) => {
  const xs = ids.map(materialLabel)
  return xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`
}

/** Check a quote before it goes out: does a price change already on file land inside it?
 *  Everything is computed by margin_guard/quotecheck.py; nothing is saved. */
export function QuoteCheckLane({ inbox, onAnswer }: { inbox: Email[]; onAnswer: () => void }) {
  const [customers, setCustomers] = useState<DataCustomer[]>([])
  const [parts, setParts] = useState<Part[]>([])
  const [customer, setCustomer] = useState('')
  const [days, setDays] = useState('60')
  const [floor, setFloor] = useState('25')
  const [lines, setLines] = useState<Line[]>([])
  const [r, setR] = useState<QuoteCheck | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  /** Set after "Use these prices": the estimator's own prices, so it applies once and can be undone. */
  const [held, setHeld] = useState<{ before: Record<number, string>; fromUsd: number; toUsd: number } | null>(null)

  useEffect(() => {
    Promise.all([api.dataCustomers(), api.parts()]).then(([c, p]) => {
      setCustomers(c)
      setParts(p)
      setCustomer((cur) => cur || c[0]?.id || '')
      const first = p.find((x) => x.id === 'P-1004') ?? p[0]
      setLines((cur) => cur.length ? cur : [{ key: ++seq, part_id: first?.id ?? '', qty: '2500', unit_price: priceFor(first) }])
    }).catch((e) => setError(String(e)))
  }, [])

  const body = useMemo(() => {
    const ls = lines.filter((l) => l.part_id && +l.qty > 0 && +l.unit_price > 0)
      .map((l) => ({ part_id: l.part_id, qty: +l.qty, unit_price: +l.unit_price }))
    if (!customer || !ls.length || !(+days >= 1)) return null
    return { customer_id: customer, valid_days: Math.round(+days), margin_floor: +floor / 100, lines: ls }
  }, [customer, days, floor, lines])

  useEffect(() => {
    if (!body) return
    const t = window.setTimeout(() => {
      api.quoteCheck(body).then((x) => { setR(x); setError(null) }).catch((e) => setError(e instanceof Error ? e.message : String(e)))
    }, 250)
    return () => window.clearTimeout(t)
  }, [body])

  // Any edit by the estimator starts a fresh baseline for the next suggestion.
  const edit = (fn: (ls: Line[]) => Line[]) => { setHeld(null); setLines(fn) }
  const setLine = (key: number, patch: Partial<Line>) => edit((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  const partOf = (id: string) => parts.find((p) => p.id === id)
  const cust = customers.find((c) => c.id === customer)

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
      <section className={`${panel} self-start`} aria-label="The quote">
        <h2 className="mb-4 text-lg font-semibold text-ink">The quote</h2>
        <div className="space-y-4">
          <label className="block">
            <span className={label}>Customer</span>
            <select value={customer} onChange={(e) => setCustomer(e.target.value)} className={field}>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}{c.tier === 'key' ? ' (key account)' : ''}</option>)}
            </select>
            {cust?.price_lock_until ? <span className="mt-1 block text-[13px] text-ink-dim">Price lock to {shortDate(cust.price_lock_until)}</span> : null}
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block"><span className={label}>Valid for (days)</span>
              <input type="number" min={1} value={days} onChange={(e) => setDays(e.target.value)} className={field} /></label>
            <label className="block"><span className={label}>Margin floor (%)</span>
              <input type="number" min={0} max={99} step={0.5} value={floor} onChange={(e) => setFloor(e.target.value)} className={field} /></label>
          </div>
          <div>
            <span className={label}>Lines</span>
            <div className="space-y-2">
              {lines.map((l) => {
                const p = partOf(l.part_id)
                return (
                  <div key={l.key} className="rounded-sm bg-ground p-2.5">
                    <select value={l.part_id} aria-label="Part"
                      onChange={(e) => setLine(l.key, { part_id: e.target.value, unit_price: priceFor(partOf(e.target.value)) })} className={field}>
                      {parts.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                    </select>
                    <div className="mt-2 grid grid-cols-[1fr_1fr_auto] items-end gap-2">
                      <label className="block"><span className={label}>Quantity</span>
                        <input type="number" min={1} value={l.qty} onChange={(e) => setLine(l.key, { qty: e.target.value })} className={field} /></label>
                      <label className="block"><span className={label}>Unit price ($)</span>
                        <input type="number" min={0} step={0.0001} value={l.unit_price} onChange={(e) => setLine(l.key, { unit_price: e.target.value })} className={field} /></label>
                      <button type="button" disabled={lines.length === 1} onClick={() => edit((ls) => ls.filter((x) => x.key !== l.key))}
                        className="min-h-10 px-1 text-[13px] text-ink-dim hover:text-ink disabled:opacity-30">Remove</button>
                    </div>
                    {p ? <p className="mt-1.5 text-[13px] text-ink-dim">Costs ${p.unit_cost_now.toFixed(4)} a unit today. Made from {names(p.materials)}.</p> : null}
                  </div>
                )
              })}
            </div>
            <button type="button" onClick={() => edit((ls) => [...ls, { key: ++seq, part_id: parts[0]?.id ?? '', qty: '1000', unit_price: priceFor(parts[0]) }])}
              className="mt-2 text-[13px] text-go hover:text-go-soft">Add a line</button>
          </div>
          <p className="text-[13px] text-ink-dim">New lines start at a {TARGET * 100}% margin on today's cost. Nothing here is saved; the check reads the price changes on file.</p>
        </div>
      </section>

      <section aria-live="polite" className="min-w-0 space-y-5">
        {error ? <p className="rounded-sm border border-stop/50 px-4 py-2 text-sm text-stop">{error}</p> : null}
        {r ? <Result r={r} inbox={inbox} copied={copied} held={held}
          onShorten={(d) => setDays(String(d))}
          onReprice={() => {
            if (held) return          // one-shot: applying again would hold the already-raised margin
            const to = r.suggestions.find((x) => x.kind === 'reprice')?.value_usd ?? r.value_usd
            setHeld({ before: Object.fromEntries(lines.map((l) => [l.key, l.unit_price])), fromUsd: r.value_usd, toUsd: to })
            setLines((ls) => ls.map((l) => {
              const x = r.lines.find((y) => y.part_id === l.part_id && +l.unit_price === y.unit_price)
              return x ? { ...l, unit_price: x.price_to_hold_margin.toFixed(4) } : l
            }))
          }}
          onUndo={() => {
            if (!held) return
            setLines((ls) => ls.map((l) => (l.key in held.before ? { ...l, unit_price: held.before[l.key] } : l)))
            setHeld(null)
          }}
          onCopy={(t) => { navigator.clipboard?.writeText(t).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1500) }) }}
          onAnswer={onAnswer} /> : <p className="text-sm text-ink-dim">Checking…</p>}
      </section>
    </div>
  )
}

/** A status word, then one plain sentence. Only "Below floor" is coloured. */
function Verdict({ r }: { r: QuoteCheck }) {
  const worst = r.worst_margin_during_validity
  const gap = Math.abs(worst - r.margin_floor) * 100
  const when = shortDate(r.worst_date)
  // An increase later partly reversed: the quote recovers by expiry, but not while it lasts.
  const recovers = r.margin_at_expiry > worst + 0.0005
    ? ` It recovers to ${pct(r.margin_at_expiry)} by expiry, but an order in between gets the worse margin.` : ''
  const [word, tone, text] = {
    clear: ['Clear', 'text-ink-dim', `No increase on file lands before this quote expires on ${shortDate(r.valid_until)}, so the margin holds.`],
    margin_erodes: ['Tighter', 'text-ink-dim', `An order on or after ${when} earns ${usd(r.maximum_exposure_usd)} less margin, but stays above the floor.${recovers}`],
    below_floor_after_change: ['Below floor', 'text-stop', `If the customer orders on or after ${when}, margin falls ${gap.toFixed(1)} points under the floor: ${usd(r.maximum_exposure_usd)} at risk.${recovers}`],
    below_floor_now: ['Below floor', 'text-stop', `This is priced under the floor already, before any change on file.`],
  }[r.verdict]
  return (
    <div>
      <p className={`text-[13px] font-semibold ${tone}`}>{word}</p>
      <h2 className="mt-0.5 text-xl leading-snug text-ink">{text}</h2>
    </div>
  )
}

function Result({ r, inbox, copied, held, onShorten, onReprice, onUndo, onCopy, onAnswer }: {
  r: QuoteCheck; inbox: Email[]; copied: boolean; held: { fromUsd: number; toUsd: number } | null
  onShorten: (days: number) => void; onReprice: () => void; onUndo: () => void; onCopy: (t: string) => void; onAnswer: () => void
}) {
  const [showClause, setShowClause] = useState(false)
  const worst = r.worst_margin_during_validity
  const dips = worst < r.margin_now - 0.0005
  const shorten = r.suggestions.find((s) => s.kind === 'shorten')
  const recommended = shorten?.valid_days && shorten.valid_days >= MIN_USEFUL_DAYS && !held ? 'shorten' : 'reprice'

  return (
    <>
      <div className={panel}>
        <Verdict r={r} />
        <p className="mt-1 text-[13px] text-ink-dim">{r.customer.name}, {usd(r.value_usd)}, valid until {shortDate(r.valid_until)}.</p>
        <div className="mt-2 max-w-xl">
          <MarginBar before={r.margin_now} after={worst} floor={r.margin_floor}
            afterLabel={dips ? `If ordered after ${shortDate(r.worst_date)}` : 'Lowest while valid'} />
        </div>
      </div>

      {r.price_locked ? (
        <p className="rounded-sm border border-rule bg-sheet px-4 py-3 text-sm text-ink">
          {r.customer.name} has a price lock to {shortDate(r.customer.price_lock_until)}, so an escalation clause may not hold.
          {shorten?.valid_days ? <> <button type="button" className="text-go hover:text-go-soft" onClick={() => onShorten(shorten.valid_days!)}>Shorten it to {shorten.valid_days} days</button></> : null}
        </p>
      ) : null}
      {r.pending_reviews.map((p) => {
        const email = inbox.find((m) => m.id === p.email_id)
        const who = p.kind === 'invoice_drift' ? 'An invoice' : `An email from ${email?.vendor_name ?? 'a supplier'}`
        return (
          <p key={p.proposal_id} className="rounded-sm border border-rule bg-sheet px-4 py-3 text-sm text-ink">
            {who} about {names(p.materials)} still needs an answer, so a price change may be missing from this check.{' '}
            <button type="button" className="text-go hover:text-go-soft" onClick={onAnswer}>Answer it</button>
          </p>
        )
      })}

      {r.changes.length ? (
        <div className={panel}>
          <h3 className="mb-1 text-lg font-semibold text-ink">Ways out</h3>
          <div className="divide-y divide-rule-soft">
            {r.suggestions.map((s) => {
              const tone = s.kind === recommended ? 'go' : 'neutral'
              return (
                <div key={s.kind} className="py-3 last:pb-0">
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                    <p className="min-w-0 flex-1 text-sm text-ink">
                      {s.kind === 'shorten' ? `Shorten it to ${s.valid_days} days, so it expires before the first increase.`
                        : s.kind === 'reprice' ? (held
                          ? `Prices now hold margin through ${shortDate(r.valid_until)}: ${usd(held.fromUsd, 2)} became ${usd(held.toUsd, 2)}.`
                          : `Price for the increases: ${usd(s.value_usd ?? r.value_usd, 2)} in total, ${usd((s.value_usd ?? r.value_usd) - r.value_usd, 2)} more.`)
                          : 'Add a material escalation clause, so the price moves with the supplier cost.'}
                    </p>
                    {s.kind === 'shorten' && s.valid_days ? <Button small tone={tone} onClick={() => onShorten(s.valid_days!)}>Use {s.valid_days} days</Button> : null}
                    {s.kind === 'reprice' ? (held
                      ? <Button small onClick={onUndo}>Undo prices</Button>
                      : <Button small tone={tone} onClick={onReprice}>Use these prices</Button>) : null}
                    {s.kind === 'clause' ? (
                      <Button small onClick={() => setShowClause(!showClause)}>{showClause ? 'Hide clause' : 'Show clause'}</Button>
                    ) : null}
                  </div>
                  {s.kind === 'clause' && showClause ? (
                    <div className="mt-2 space-y-2 rounded-sm bg-ground px-3 py-2.5">
                      <p className="text-[13px] leading-relaxed text-ink">{s.text}</p>
                      <Button small onClick={() => onCopy(s.text)}>{copied ? 'Copied' : 'Copy clause'}</Button>
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
        </div>
      ) : null}

      <div className={panel}>
        <h3 className="mb-2 text-lg font-semibold text-ink">Margin if the order comes on or after</h3>
        <table className="w-full text-sm">
          <thead><tr className="text-left"><th className={head}>Date</th><th className={head}>What changes</th><th className={`${head} text-right`}>Margin</th></tr></thead>
          <tbody>
            {r.timeline.map((t, i) => (
              <tr key={t.date} className="border-t border-rule-soft align-top">
                <td className="py-2 pr-4 text-ink">{i === 0 ? `Today, ${shortDate(t.date)}` : shortDate(t.date)}</td>
                <td className="py-2 pr-4 text-[13px] text-ink">
                  {i === 0 ? <span className="text-ink-dim">Costs on file today</span> : t.changes.map((c) => (
                    <span key={c.material_id} className="block">
                      {materialLabel(c.material_id)} to ${c.cost_per_lb.toFixed(2)}/lb
                      <span className="text-ink-dim">, from {c.vendor_name ?? 'a shop entry'}</span>
                    </span>
                  ))}
                </td>
                <td className={`py-2 text-right font-semibold ${t.below_floor ? 'text-stop' : 'text-ink'}`}>{pct(t.margin)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className={panel}>
        <h3 className="mb-2 text-lg font-semibold text-ink">By line</h3>
        <div className="-mx-5 overflow-x-auto px-5">
        <table className="w-full min-w-[34rem] text-sm">
          <thead><tr className="text-left">
            <th className={head}>Part</th><th className={`${head} pl-3 text-right`}>Qty</th><th className={`${head} pl-3 text-right`}>Price</th>
            <th className={`${head} pl-3 text-right`}>Cost now, at peak</th><th className={`${head} pl-3 text-right`}>Margin now, at worst</th><th className={`${head} pl-3 text-right`}>Price to hold</th>
          </tr></thead>
          <tbody>
            {r.lines.map((l, i) => (
              <tr key={`${l.part_id}-${i}`} className="border-t border-rule-soft">
                <td className="py-2 pr-3 text-ink">{l.part_name}</td>
                <td className="py-2 pl-3 text-right text-ink">{l.qty.toLocaleString()}</td>
                <td className="py-2 pl-3 text-right text-ink">${l.unit_price.toFixed(4)}</td>
                <td className="py-2 pl-3 text-right text-ink-dim">${l.unit_cost_now.toFixed(4)}, <span className={l.affected ? 'text-ink' : ''}>${l.unit_cost_worst.toFixed(4)}</span></td>
                <td className="py-2 pl-3 text-right text-ink">{pct(l.margin_now)}, <span className={l.margin_worst < r.margin_floor ? 'text-stop' : ''}>{pct(l.margin_worst)}</span></td>
                <td className={`py-2 pl-3 text-right ${l.affected ? 'font-semibold text-ink' : 'text-ink-dim'}`}>${l.price_to_hold_margin.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
    </>
  )
}
