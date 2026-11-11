import { type ReactNode, useEffect, useMemo, useState } from 'react'

import { api } from '../lib/api'
import { pct, shortDate, usd } from '../lib/format'
import type { DataCustomer, Part, QuoteCheck } from '../lib/types'
import { Button } from './Button'
import { MarginBar } from './MarginBar'
import { Family } from './QuoteParts'

type Line = { key: number; part_id: string; qty: string; unit_price: string }

const head = 'pb-2 font-label text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-dim'
const field = 'w-full rounded-sm border border-rule bg-sheet-2 px-2.5 py-1.5 text-sm text-ink-bright outline-none focus:border-attn/70'
const TARGET = 0.3   // a new line is priced at a 30% margin on today's cost until the estimator changes it

let seq = 0
const priceFor = (p?: Part) => (p ? (p.unit_cost_now / (1 - TARGET)).toFixed(4) : '')

/** Check a quote before it goes out: does a price change already on file land inside it?
 *  Everything is computed by margin_guard/quotecheck.py; nothing is saved. */
export function QuoteCheckLane({ onAnswer }: { onAnswer: () => void }) {
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
      <section className="rounded-sm border border-rule bg-sheet px-5 py-4" aria-label="The quote">
        <h2 className="mb-3 font-label text-lg font-semibold text-ink-bright">The quote</h2>
        <div className="space-y-3">
          <label className="block">
            <span className={head}>Customer</span>
            <select value={customer} onChange={(e) => setCustomer(e.target.value)} className={field}>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}{c.tier === 'key' ? ' (key account)' : ''}</option>)}
            </select>
            {cust?.price_lock_until ? <span className="mt-1 block font-label text-[12px] text-ink-dim">Price lock to {shortDate(cust.price_lock_until)}</span> : null}
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block"><span className={head}>Valid for (days)</span>
              <input type="number" min={1} value={days} onChange={(e) => setDays(e.target.value)} className={field} /></label>
            <label className="block"><span className={head}>Margin floor (%)</span>
              <input type="number" min={0} max={99} step={0.5} value={floor} onChange={(e) => setFloor(e.target.value)} className={field} /></label>
          </div>
          <div>
            <span className={head}>Lines</span>
            <div className="space-y-2">
              {lines.map((l) => {
                const p = partOf(l.part_id)
                return (
                  <div key={l.key} className="rounded-sm border border-rule bg-ground/40 p-2.5">
                    <select value={l.part_id} aria-label="Part"
                      onChange={(e) => setLine(l.key, { part_id: e.target.value, unit_price: priceFor(partOf(e.target.value)) })} className={field}>
                      {parts.map((x) => <option key={x.id} value={x.id}>{x.id} · {x.name}</option>)}
                    </select>
                    <div className="mt-2 grid grid-cols-[1fr_1fr_auto] items-end gap-2">
                      <label className="block"><span className="font-label text-[12px] text-ink-dim">Qty</span>
                        <input type="number" min={1} value={l.qty} onChange={(e) => setLine(l.key, { qty: e.target.value })} className={field} /></label>
                      <label className="block"><span className="font-label text-[12px] text-ink-dim">Unit price ($)</span>
                        <input type="number" min={0} step={0.0001} value={l.unit_price} onChange={(e) => setLine(l.key, { unit_price: e.target.value })} className={field} /></label>
                      <button type="button" disabled={lines.length === 1} onClick={() => edit((ls) => ls.filter((x) => x.key !== l.key))}
                        className="pb-1.5 font-label text-[13px] font-semibold text-ink-dim hover:text-stop disabled:opacity-30">Remove</button>
                    </div>
                    {p ? <p className="mt-1.5 font-label text-[12px] text-ink-dim">Cost today ${p.unit_cost_now.toFixed(4)}/unit · {p.materials.map((m) => <Family key={m} id={m} />).reduce<ReactNode[]>((a, x, i) => (i ? [...a, ' ', x] : [x]), [])}</p> : null}
                  </div>
                )
              })}
            </div>
            <button type="button" onClick={() => edit((ls) => [...ls, { key: ++seq, part_id: parts[0]?.id ?? '', qty: '1000', unit_price: priceFor(parts[0]) }])}
              className="mt-2 font-label text-[13px] font-semibold text-ink-dim underline-offset-2 hover:text-ink-bright hover:underline">Add a line</button>
          </div>
          <p className="text-xs text-ink-dim">New lines start at a {TARGET * 100}% margin on today's cost. Nothing here is saved; the check reads the price changes on file.</p>
        </div>
      </section>

      <section aria-live="polite" className="min-w-0 space-y-5">
        {error ? <p className="rounded-sm border border-stop/50 bg-stop/5 px-4 py-2 text-sm text-stop">{error}</p> : null}
        {r ? <Result r={r} copied={copied} held={held}
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

function Verdict({ r }: { r: QuoteCheck }) {
  const first = r.timeline[1]
  const gap = Math.abs(r.margin_at_expiry - r.margin_floor) * 100
  const [tone, text] = {
    clear: ['text-go', `No price change on file lands before this quote expires on ${shortDate(r.valid_until)}. Margin holds at ${pct(r.margin_now)}.`],
    margin_erodes: ['text-attn', `${r.changes.length} increase${r.changes.length === 1 ? '' : 's'} on file land${r.changes.length === 1 ? 's' : ''} before this quote expires. If the order comes after ${shortDate(first?.date)}, margin falls to ${pct(r.margin_at_expiry)}, still above the ${pct(r.margin_floor)} floor (${usd(r.at_risk_usd)} less margin).`],
    below_floor_after_change: ['text-stop', `If the customer orders after ${shortDate(first?.date)}, margin falls to ${pct(r.margin_at_expiry)}, ${gap.toFixed(1)} pts below the ${pct(r.margin_floor)} floor: ${usd(r.at_risk_usd)} at risk on this quote.`],
    below_floor_now: ['text-stop', `This is priced below the floor already: ${pct(r.margin_now)} against ${pct(r.margin_floor)}, before any change on file.`],
  }[r.verdict]
  return <h2 className={`font-label text-[22px] font-semibold leading-snug ${tone}`}>{text}</h2>
}

function Result({ r, copied, held, onShorten, onReprice, onUndo, onCopy, onAnswer }: {
  r: QuoteCheck; copied: boolean; held: { fromUsd: number; toUsd: number } | null
  onShorten: (days: number) => void; onReprice: () => void; onUndo: () => void; onCopy: (t: string) => void; onAnswer: () => void
}) {
  const scale = { lo: Math.min(r.margin_at_expiry, r.margin_floor) - 0.012, hi: Math.max(r.margin_now, r.margin_floor) + 0.012 }
  return (
    <>
      <div className="rounded-sm border border-rule bg-sheet px-5 py-4">
        <Verdict r={r} />
        <p className="mt-1 text-sm text-ink-dim">{r.customer.name} · {usd(r.value_usd)} · issued {shortDate(r.issued)}, valid until {shortDate(r.valid_until)}</p>
        <div className="mt-4 max-w-md"><MarginBar before={r.margin_now} after={r.margin_at_expiry} floor={r.margin_floor} scale={scale} /></div>
        {r.price_locked ? (
          <p className="mt-3 rounded-sm border border-rule-bright px-3 py-2 text-sm text-ink">
            {r.customer.name} has a price lock to {shortDate(r.customer.price_lock_until)}. An escalation clause may not hold against it; price for the increases or shorten the validity instead.
          </p>
        ) : null}
        {r.pending_reviews.length ? (
          <div className="mt-3 rounded-sm border border-attn/50 bg-attn/3 px-3 py-2 text-sm text-ink">
            {r.pending_reviews.length} supplier {r.pending_reviews[0].kind === 'invoice_drift' ? 'item' : 'email'}{r.pending_reviews.length === 1 ? '' : 's'} about these materials still need{r.pending_reviews.length === 1 ? 's' : ''} a person, so a change may be missing from this check:
            <ul className="mt-1 list-disc pl-5">{r.pending_reviews.map((p) => <li key={p.proposal_id}>{p.email_id ?? 'invoice'}: {p.reasons[0]}</li>)}</ul>
            <button type="button" onClick={onAnswer} className="mt-1 font-label text-[13px] font-semibold text-attn underline-offset-2 hover:underline">Answer in Decide</button>
          </div>
        ) : null}
      </div>

      {r.changes.length ? (
        <div className="rounded-sm border border-rule bg-sheet px-5 py-4">
          <h3 className="mb-2 font-label text-lg font-semibold text-ink-bright">Ways out</h3>
          <div className="divide-y divide-rule">
            {r.suggestions.map((s) => (
              <div key={s.kind} className="flex flex-wrap items-start gap-x-4 gap-y-2 py-3 first:pt-0">
                <p className="min-w-0 flex-1 text-sm leading-relaxed text-ink">
                  {s.kind === 'reprice' && held
                    ? `Prices set to hold each line's margin through ${shortDate(r.valid_until)}: ${usd(held.fromUsd, 2)} became ${usd(held.toUsd, 2)}. If the order comes after the increases, margin is back where you priced it.`
                    : s.text}
                </p>
                {s.kind === 'shorten' && s.valid_days ? <Button small onClick={() => onShorten(s.valid_days!)}>Use {s.valid_days} days</Button> : null}
                {s.kind === 'reprice' ? (held
                  ? <Button small onClick={onUndo}>Undo prices</Button>
                  : <Button small onClick={onReprice}>Use these prices</Button>) : null}
                {s.kind === 'clause' ? <Button small onClick={() => onCopy(s.text)}>{copied ? 'Copied' : 'Copy clause'}</Button> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="rounded-sm border border-rule bg-sheet px-5 py-4">
        <h3 className="mb-2 font-label text-lg font-semibold text-ink-bright">Margin if the order comes on or after</h3>
        <table className="w-full text-sm">
          <thead><tr className="text-left"><th className={head}>Date</th><th className={head}>What changes</th><th className={`${head} text-right`}>Margin</th></tr></thead>
          <tbody>
            {r.timeline.map((t, i) => (
              <tr key={t.date} className="border-t border-rule align-top">
                <td className="py-2 pr-4 font-label text-ink">{i === 0 ? `Today, ${shortDate(t.date)}` : shortDate(t.date)}</td>
                <td className="py-2 pr-4 font-label text-[13px] text-ink">
                  {i === 0 ? <span className="text-ink-dim">Costs on file today</span> : t.changes.map((c) => (
                    <span key={c.material_id} className="mr-4 inline-block">
                      <Family id={c.material_id}>{c.material_name}</Family> to ${c.cost_per_lb.toFixed(2)}/lb
                      <span className="text-ink-dim"> · {c.vendor_name ?? 'shop entry'}{c.email_id ? ` · email ${c.email_id}` : ''}</span>
                    </span>
                  ))}
                </td>
                <td className={`py-2 text-right font-label font-semibold ${t.below_floor ? 'text-stop' : 'text-ink-bright'}`}>{pct(t.margin)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-sm border border-rule bg-sheet px-5 py-4">
        <h3 className="mb-2 font-label text-lg font-semibold text-ink-bright">By line</h3>
        <div className="-mx-5 overflow-x-auto px-5">
        <table className="w-full min-w-[40rem] text-sm">
          <thead><tr className="text-left">
            <th className={head}>Part</th><th className={`${head} text-right`}>Qty</th><th className={`${head} text-right`}>Price</th>
            <th className={`${head} text-right`}>Cost today → at expiry</th><th className={`${head} text-right`}>Margin</th><th className={`${head} text-right`}>Price to hold margin</th>
          </tr></thead>
          <tbody>
            {r.lines.map((l, i) => (
              <tr key={`${l.part_id}-${i}`} className="border-t border-rule">
                <td className="py-2 pr-3 text-ink-bright">{l.part_name}</td>
                <td className="py-2 text-right font-label text-ink">{l.qty.toLocaleString()}</td>
                <td className="py-2 text-right font-label text-ink">${l.unit_price.toFixed(4)}</td>
                <td className="py-2 text-right font-label text-ink-dim">${l.unit_cost_now.toFixed(4)} → <span className={l.affected ? 'text-ink-bright' : ''}>${l.unit_cost_at_expiry.toFixed(4)}</span></td>
                <td className="py-2 text-right font-label text-ink">{pct(l.margin_now)} → <span className={l.margin_at_expiry < r.margin_floor ? 'text-stop' : ''}>{pct(l.margin_at_expiry)}</span></td>
                <td className={`py-2 text-right font-label ${l.affected ? 'font-semibold text-ink-bright' : 'text-ink-dim'}`}>${l.price_to_hold_margin.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
    </>
  )
}
