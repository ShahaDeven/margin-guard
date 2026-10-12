import { useEffect, useState } from 'react'

import { api } from '../lib/api'
import { ACTION_TEXT, materialLabel, pct, shortDate, unitPrice, usd } from '../lib/format'
import type { DataCustomer, DataMaterial, DataQuote, QuoteDetail } from '../lib/types'

type View = 'quotes' | 'customers' | 'materials'

/** Read-only view of the shop behind the cards, so any number on a card can be checked. */
export function DataLane({ asOf, version, focusedQuote, onFocusHandled }: {
  asOf: string
  version: number
  focusedQuote: string | null
  onFocusHandled: () => void
}) {
  const [view, setView] = useState<View>('quotes')
  const [query, setQuery] = useState('')
  const [openOnly, setOpenOnly] = useState(true)
  const [openQuote, setOpenQuote] = useState<string | null>(null)
  const [quotes, setQuotes] = useState<DataQuote[]>([])
  const [customers, setCustomers] = useState<DataCustomer[]>([])
  const [materials, setMaterials] = useState<DataMaterial[]>([])

  useEffect(() => {
    api.dataQuotes().then(setQuotes).catch(() => {})
    api.dataCustomers().then(setCustomers).catch(() => {})
    api.dataMaterials().then(setMaterials).catch(() => {})
  }, [version])

  // Arriving from a card's "View quote": show that quote, opened.
  useEffect(() => {
    if (!focusedQuote) return
    setView('quotes')
    setOpenOnly(false)
    setQuery(focusedQuote)
    setOpenQuote(focusedQuote)
    onFocusHandled()
  }, [focusedQuote, onFocusHandled])

  const q = query.trim().toLowerCase()
  const match = (...fields: (string | null | undefined)[]) => !q || fields.some((f) => f?.toLowerCase().includes(q))

  const shownQuotes = quotes.filter((x) => (!openOnly || x.status === 'open') && match(x.id, x.customer_name))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-md border border-line bg-panel p-0.5">
          {(['quotes', 'customers', 'materials'] as View[]).map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setView(v)}
              className={`rounded px-3 py-1.5 text-sm capitalize transition-colors ${view === v ? 'bg-panel-2 text-silver-bright' : 'text-silver-dim hover:text-silver'}`}
            >
              {v}
            </button>
          ))}
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={view === 'quotes' ? 'Search quote or customer…' : view === 'customers' ? 'Search customer, buyer, manager…' : 'Search material…'}
          className="min-w-56 flex-1 rounded border border-line bg-panel-2 px-3 py-1.5 text-sm text-silver outline-none focus:border-line-bright"
        />
        {view === 'quotes' ? (
          <label className="flex items-center gap-2 text-sm text-silver-dim">
            <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} className="accent-purple" />
            open only
          </label>
        ) : null}
      </div>

      {view === 'quotes' ? (
        <div className="overflow-hidden rounded-lg border border-line bg-panel">
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left font-mono text-[10px] uppercase tracking-wider text-silver-dim">
              <tr>
                <th className="px-4 py-2 font-normal">Quote</th>
                <th className="py-2 font-normal">Customer</th>
                <th className="py-2 text-right font-normal">Value</th>
                <th className="py-2 text-right font-normal">Margin / floor</th>
                <th className="py-2 pl-4 font-normal">Valid until</th>
                <th className="py-2 font-normal">Status</th>
                <th className="py-2 pr-4 text-right font-normal">Cards</th>
              </tr>
            </thead>
            <tbody>
              {shownQuotes.map((x) => (
                <QuoteRow key={x.id} x={x} open={openQuote === x.id} onToggle={() => setOpenQuote(openQuote === x.id ? null : x.id)} version={version} />
              ))}
            </tbody>
          </table>
          {!shownQuotes.length ? <p className="px-4 py-6 text-center text-sm text-silver-dim">No quotes match.</p> : null}
          <p className="border-t border-line px-4 py-2 font-mono text-[10px] text-silver-dim">
            {shownQuotes.length} of {quotes.length} quotes · margin is at current quoted prices and the costs when quoted
          </p>
        </div>
      ) : null}

      {view === 'customers' ? (
        <div className="grid gap-3 md:grid-cols-2">
          {customers.filter((c) => match(c.name, c.buyer_name, c.account_manager, c.id)).map((c) => (
            <article key={c.id} className="rounded-lg border border-line bg-panel px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-silver-bright">{c.name}</span>
                {c.tier === 'key' ? <span className="rounded border border-purple/40 px-1.5 py-px font-mono text-[10px] text-purple">KEY</span> : null}
                {c.price_lock_until ? (
                  <span className="rounded border border-cyan/40 px-1.5 py-px font-mono text-[10px] text-cyan">LOCKED TO {shortDate(c.price_lock_until).toUpperCase()}</span>
                ) : null}
                <span className="ml-auto font-mono text-[10px] text-silver-dim">{c.id}</span>
              </div>
              <p className="mt-2 text-sm text-silver">
                {c.buyer_name} · <a className="font-mono text-cyan" href={`tel:${c.buyer_phone.replace(/[^\d+]/g, '')}`}>{c.buyer_phone}</a>
              </p>
              <p className="text-xs text-silver-dim">{c.buyer_email}</p>
              <p className="mt-1 text-xs text-silver-dim">Account manager: {c.account_manager} · {c.account_manager_phone}</p>
              {c.contract_note ? <p className="mt-2 rounded border border-hiviz/25 bg-hiviz/3 px-2 py-1 text-xs text-silver">{c.contract_note}</p> : null}
              <p className="mt-2 font-mono text-[11px] text-silver-dim">
                {c.open_quotes} open quotes · {usd(c.open_value_usd)} · {c.won_quotes} won this year
              </p>
            </article>
          ))}
        </div>
      ) : null}

      {view === 'materials' ? (
        <div className="space-y-3">
          {materials.filter((m) => match(m.name, m.id, ...m.aliases)).map((m) => (
            <article key={m.id} className="rounded-lg border border-line bg-panel px-4 py-3">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="font-semibold text-silver-bright">{m.name}</span>
                <span className="font-mono text-xs text-silver-dim">{materialLabel(m.id)} · {m.category}</span>
                <span className="ml-auto font-mono text-silver-bright">${m.cost_per_lb.toFixed(4)}<span className="text-xs text-silver-dim">/lb today</span></span>
              </div>
              <ol className="mt-2 space-y-0.5 overflow-x-auto whitespace-pre font-mono text-xs">
                {m.history.map((h, i) => {
                  const prev = m.history[i - 1]
                  const delta = prev ? (h.cost_per_lb - prev.cost_per_lb) / prev.cost_per_lb : null
                  const future = h.effective_date > asOf
                  return (
                    <li key={`${h.effective_date}-${i}`} className={future ? 'text-hiviz' : 'text-silver-dim'}>
                      {future ? 'scheduled ' : 'since     '}{shortDate(h.effective_date).padEnd(7)}  ${h.cost_per_lb.toFixed(4)}/lb
                      {delta != null ? `  ${delta >= 0 ? '+' : ''}${(delta * 100).toFixed(1)}%` : ''}
                      {h.vendor_name ? `  · ${h.vendor_name}` : ''}{h.email_id ? ` (${h.email_id})` : ''}
                    </li>
                  )
                })}
              </ol>
              <p className="mt-2 text-xs text-silver-dim">Used in: {m.parts.join(' · ') || 'no parts'}</p>
              <p className="mt-0.5 text-xs text-silver-dim">Vendors call it: {m.aliases.join(', ')}</p>
            </article>
          ))}
        </div>
      ) : null}
    </div>
  )
}

const STATUS_TONE: Record<string, string> = {
  open: 'text-cyan', won: 'text-silver', lost: 'text-silver-dim', expired: 'text-silver-dim',
}

function QuoteRow({ x, open, onToggle, version }: { x: DataQuote; open: boolean; onToggle: () => void; version: number }) {
  const [detail, setDetail] = useState<QuoteDetail | null>(null)
  useEffect(() => {
    if (open) api.dataQuote(x.id).then(setDetail).catch(() => {})
  }, [open, x.id, version])
  const below = x.margin < x.margin_floor

  return (
    <>
      <tr onClick={onToggle} className={`cursor-pointer border-t border-line/60 hover:bg-panel-2 ${open ? 'bg-panel-2' : ''}`}>
        <td className="px-4 py-2 font-mono text-xs text-silver">
          {x.id}
          {x.revisions ? <span className="ml-2 rounded bg-purple/15 px-1 text-[10px] text-purple">revised</span> : null}
        </td>
        <td className="py-2 text-silver">{x.customer_name}{x.tier === 'key' ? <span className="ml-1.5 text-[10px] text-purple">KEY</span> : null}</td>
        <td className="py-2 text-right font-mono text-xs text-silver">{usd(x.value_usd)}</td>
        <td className="py-2 text-right font-mono text-xs">
          <span className={below ? 'text-signal' : 'text-silver'}>{pct(x.margin)}</span>
          <span className="text-silver-dim"> / {pct(x.margin_floor)}</span>
        </td>
        <td className="py-2 pl-4 font-mono text-xs text-silver-dim">{shortDate(x.valid_until)}</td>
        <td className={`py-2 font-mono text-xs ${STATUS_TONE[x.status]}`}>{x.status}</td>
        <td className="py-2 pr-4 text-right font-mono text-xs">
          {x.open_cards ? <span className="text-hiviz">{x.open_cards} open</span> : <span className="text-silver-dim">-</span>}
        </td>
      </tr>
      {open && detail ? (
        <tr className="bg-panel-2/60">
          <td colSpan={7} className="space-y-4 px-4 py-4">
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-silver-dim">
              <span>Issued {shortDate(detail.issued_date)} · valid until {shortDate(detail.valid_until)}</span>
              <span>Buyer: <span className="text-silver">{detail.buyer_name}</span> · <span className="font-mono text-cyan">{detail.buyer_phone}</span></span>
              <span>Account manager: {detail.account_manager}</span>
              {detail.price_lock_until ? <span className="text-cyan">Price lock to {shortDate(detail.price_lock_until)}</span> : null}
            </div>
            {detail.contract_note ? <p className="text-xs text-silver">Contract note: {detail.contract_note}</p> : null}

            <table className="w-full font-mono text-xs">
              <thead className="text-left text-[10px] uppercase tracking-wider text-silver-dim">
                <tr>
                  <th className="pb-1.5 font-normal">Part</th>
                  <th className="pb-1.5 font-normal">Made from</th>
                  <th className="pb-1.5 text-right font-normal">Qty</th>
                  <th className="pb-1.5 text-right font-normal">Cost / unit when quoted</th>
                  <th className="pb-1.5 text-right font-normal">Price / unit</th>
                </tr>
              </thead>
              <tbody>
                {detail.lines.map((l) => (
                  <tr key={l.id} className="border-t border-line/50">
                    <td className="py-1.5 font-sans text-[13px] text-silver">{l.part_name}</td>
                    <td className="py-1.5 font-sans text-xs text-silver-dim">{l.materials}</td>
                    <td className="py-1.5 text-right text-silver-dim">{l.qty.toLocaleString()}</td>
                    <td className="py-1.5 text-right text-silver-dim">{unitPrice(l.material_cost_basis + l.conversion_cost)}</td>
                    <td className="py-1.5 text-right text-silver">{unitPrice(l.unit_price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {detail.revisions.length ? (
              <div>
                <p className="font-mono text-[10px] uppercase tracking-wider text-purple">Price revisions</p>
                <ul className="mt-1 space-y-0.5 font-mono text-xs text-silver">
                  {detail.revisions.map((r) => (
                    <li key={r.id}>{r.part_name}: {unitPrice(r.old_price)} → <span className="text-cyan">{unitPrice(r.new_price)}</span></li>
                  ))}
                </ul>
              </div>
            ) : null}

            {detail.cards.length ? (
              <div>
                <p className="font-mono text-[10px] uppercase tracking-wider text-silver-dim">Cards raised on this quote</p>
                <ul className="mt-1 space-y-0.5 text-xs">
                  {detail.cards.map((c) => (
                    <li key={c.id} className="text-silver-dim">
                      <span className="font-mono">{c.status.padEnd(10)}</span>{' '}
                      <span className="text-silver">{ACTION_TEXT[c.final_action ?? c.action].short}</span>
                      {' '}· {materialLabel(c.material_id)} via {c.email_id} · {c.decided_by === 'llm' ? 'Claude' : c.decided_by}
                      {c.exposure_usd ? ` · ${usd(c.exposure_usd)} at risk` : ''}
                    </li>
                  ))}
                </ul>
              </div>
            ) : <p className="text-xs text-silver-dim">No supplier change has touched this quote.</p>}
          </td>
        </tr>
      ) : null}
    </>
  )
}
