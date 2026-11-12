import { useEffect, useState } from 'react'

import { api } from '../lib/api'
import { ACTION_TEXT, materialLabel, pct, shortDate, unitPrice, usd } from '../lib/format'
import type { DataCustomer, DataMaterial, DataQuote, QuoteDetail } from '../lib/types'

type View = 'quotes' | 'customers' | 'materials'
type Status = 'open' | 'won' | 'lost' | 'all'

const VIEWS: { id: View; label: string }[] = [
  { id: 'quotes', label: 'Quotes' }, { id: 'customers', label: 'Customers' }, { id: 'materials', label: 'Materials' },
]
const STATUSES: { id: Status; label: string }[] = [
  { id: 'open', label: 'Open' }, { id: 'won', label: 'Won' }, { id: 'lost', label: 'Lost' }, { id: 'all', label: 'All' },
]
const STATUS_WORD: Record<string, string> = { open: 'Open', won: 'Won', lost: 'Lost', expired: 'Expired' }

const head = 'border-b border-rule px-4 py-2.5 text-[13px] font-medium text-ink-dim'
const cell = 'border-b border-rule-soft px-4 py-2.5 align-top'
const panel = 'rounded-md border border-rule bg-sheet'

function Segmented<T extends string>({ items, value, onChange, label }: {
  items: { id: T; label: string }[]; value: T; onChange: (v: T) => void; label: string
}) {
  return (
    <div className="inline-flex rounded-sm border border-rule-bright p-0.5" role="group" aria-label={label}>
      {items.map((x) => (
        <button key={x.id} type="button" aria-pressed={value === x.id} onClick={() => onChange(x.id)}
          className={`rounded-[4px] px-3 py-1.5 text-sm transition-colors ${value === x.id ? 'bg-nav-active font-semibold text-go-soft' : 'text-ink hover:text-go-soft'}`}>
          {x.label}
        </button>
      ))}
    </div>
  )
}

/** Read-only view of the shop behind every figure, so any number can be checked. */
export function DataLane({ asOf, version, focusedQuote, onFocusHandled }: {
  asOf: string
  version: number
  focusedQuote: string | null
  onFocusHandled: () => void
}) {
  const [view, setView] = useState<View>('quotes')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<Status>('open')
  const [openQuote, setOpenQuote] = useState<string | null>(null)
  const [quotes, setQuotes] = useState<DataQuote[]>([])
  const [customers, setCustomers] = useState<DataCustomer[]>([])
  const [materials, setMaterials] = useState<DataMaterial[]>([])

  useEffect(() => {
    api.dataQuotes().then(setQuotes).catch(() => {})
    api.dataCustomers().then(setCustomers).catch(() => {})
    api.dataMaterials().then(setMaterials).catch(() => {})
  }, [version])

  // Arriving from "Open in shop data": show that quote, opened.
  useEffect(() => {
    if (!focusedQuote) return
    setView('quotes')
    setStatus('all')
    setQuery(focusedQuote)
    setOpenQuote(focusedQuote)
    onFocusHandled()
  }, [focusedQuote, onFocusHandled])

  const q = query.trim().toLowerCase()
  const match = (...fields: (string | null | undefined)[]) => !q || fields.some((f) => f?.toLowerCase().includes(q))
  const shownQuotes = quotes.filter((x) => (status === 'all' || x.status === status) && match(x.id, x.customer_name))
  // With one status chosen, every row says the same thing, so the column goes (rule 9).
  const showStatus = status === 'all'
  const cols = showStatus ? 8 : 7

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Segmented items={VIEWS} value={view} onChange={setView} label="Show" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search"
          placeholder={view === 'quotes' ? 'Search quote or customer…' : view === 'customers' ? 'Search customer, buyer, manager…' : 'Search material…'}
          className="min-w-56 flex-1 rounded-sm border border-rule-bright bg-ground px-3 py-2 text-sm text-ink outline-none focus:border-go"
        />
        {view === 'quotes' ? <Segmented items={STATUSES} value={status} onChange={setStatus} label="Status" /> : null}
      </div>

      {view === 'quotes' ? (
        <div className={`${panel} overflow-x-auto`}>
          <table className="w-full min-w-[640px] border-collapse text-sm">
            <thead>
              <tr className="text-left">
                <th className={head}>Quote</th>
                <th className={head}>Customer</th>
                <th className={`${head} text-right`}>Value</th>
                <th className={`${head} text-right`}>Margin</th>
                <th className={`${head} text-right`}>Floor</th>
                <th className={head}>Valid until</th>
                {showStatus ? <th className={head}>Status</th> : null}
                <th className={`${head} text-right`}>Decisions</th>
              </tr>
            </thead>
            <tbody>
              {shownQuotes.map((x) => (
                <QuoteRow key={x.id} x={x} cols={cols} showStatus={showStatus} open={openQuote === x.id}
                  onToggle={() => setOpenQuote(openQuote === x.id ? null : x.id)} version={version} />
              ))}
            </tbody>
          </table>
          {!shownQuotes.length ? <p className="px-4 py-6 text-center text-sm text-ink-dim">No quotes match.</p> : null}
          <p className="px-4 py-2.5 text-[13px] text-ink-dim">
            {shownQuotes.length} of {quotes.length} quotes. Margin is at the current quoted prices and the costs when quoted.
          </p>
        </div>
      ) : null}

      {view === 'customers' ? (
        <div className="grid gap-3 md:grid-cols-2">
          {customers.filter((c) => match(c.name, c.buyer_name, c.account_manager, c.id)).map((c) => (
            <article key={c.id} className={`${panel} px-4 py-3`}>
              <p>
                <span className="font-semibold text-ink">{c.name}</span>
                {c.tier === 'key' ? <span className="ml-2 text-[13px] text-ink-dim">Key account</span> : null}
              </p>
              {c.price_lock_until ? <p className="text-[13px] text-ink-dim">Price lock to {shortDate(c.price_lock_until)}</p> : null}
              <p className="mt-2 text-sm text-ink">
                Buyer {c.buyer_name}, <a className="text-go hover:text-go-soft" href={`tel:${c.buyer_phone.replace(/[^\d+]/g, '')}`}>{c.buyer_phone}</a>
              </p>
              <p className="text-[13px] text-ink-dim">{c.buyer_email}</p>
              <p className="mt-1 text-[13px] text-ink-dim">Account manager {c.account_manager}, {c.account_manager_phone}</p>
              {c.contract_note ? <p className="mt-2 rounded-sm bg-ground px-2.5 py-1.5 text-[13px] text-ink">Contract note: {c.contract_note}</p> : null}
              <p className="mt-2 text-[13px] text-ink-dim">
                {c.open_quotes} open quote{c.open_quotes === 1 ? '' : 's'} worth {usd(c.open_value_usd)}, {c.won_quotes} won this year
              </p>
            </article>
          ))}
        </div>
      ) : null}

      {view === 'materials' ? (
        <div className="flex flex-col gap-3">
          {materials.filter((m) => match(m.name, m.id, ...m.aliases)).map((m) => (
            <article key={m.id} className={`${panel} px-4 py-3`}>
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="font-semibold text-ink">{m.name}</span>
                <span className="text-[13px] text-ink-dim">{materialLabel(m.id)}, {m.category}</span>
                <span className="ml-auto text-ink">${m.cost_per_lb.toFixed(4)}<span className="text-[13px] text-ink-dim">/lb today</span></span>
              </div>
              <table className="mt-2 text-[13px]">
                <tbody>
                  {m.history.map((h, i) => {
                    const prev = m.history[i - 1]
                    const delta = prev ? (h.cost_per_lb - prev.cost_per_lb) / prev.cost_per_lb : null
                    const future = h.effective_date > asOf
                    return (
                      <tr key={`${h.effective_date}-${i}`} className="text-ink-dim">
                        <td className="py-0.5 pr-4 whitespace-nowrap">{future ? 'Scheduled from' : 'From'} {shortDate(h.effective_date)}</td>
                        <td className="py-0.5 pr-4 text-right text-ink tabular-nums">${h.cost_per_lb.toFixed(4)}/lb</td>
                        <td className="py-0.5 pr-4 text-right tabular-nums">{delta != null ? `${delta >= 0 ? '+' : ''}${(delta * 100).toFixed(1)}%` : ''}</td>
                        <td className="py-0.5">{h.vendor_name ?? 'Shop entry'}{h.email_id ? ', by email' : ''}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <p className="mt-2 text-[13px] text-ink-dim">Used in: {m.parts.join(', ') || 'no parts'}</p>
              <p className="mt-0.5 text-[13px] text-ink-dim">Suppliers call it: {m.aliases.join(', ')}</p>
            </article>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function QuoteRow({ x, cols, showStatus, open, onToggle, version }: {
  x: DataQuote; cols: number; showStatus: boolean; open: boolean; onToggle: () => void; version: number
}) {
  const [detail, setDetail] = useState<QuoteDetail | null>(null)
  useEffect(() => {
    if (open) api.dataQuote(x.id).then(setDetail).catch(() => {})
  }, [open, x.id, version])
  const below = x.margin < x.margin_floor

  return (
    <>
      <tr onClick={onToggle} className={`cursor-pointer ${open ? 'bg-sheet-2' : 'hover:bg-sheet-2/50'}`}>
        <td className={cell}>
          {x.id}
          {x.revisions ? <span className="ml-2 text-[13px] text-ink-dim">revised</span> : null}
        </td>
        <td className={cell}>
          <span className="text-ink">{x.customer_name}</span>
          {x.tier === 'key' ? <span className="ml-2 text-[13px] text-ink-dim">Key account</span> : null}
        </td>
        <td className={`${cell} text-right`}>{usd(x.value_usd)}</td>
        <td className={`${cell} text-right ${below ? 'text-stop' : ''}`}>{pct(x.margin)}</td>
        <td className={`${cell} text-right text-ink-dim`}>{pct(x.margin_floor)}</td>
        <td className={`${cell} whitespace-nowrap text-ink-dim`}>{shortDate(x.valid_until)}</td>
        {showStatus ? <td className={`${cell} text-ink-dim`}>{STATUS_WORD[x.status] ?? x.status}</td> : null}
        <td className={`${cell} text-right`}>
          {/* Opens the row, where the decisions are listed. */}
          {x.open_cards ? <span className="text-go">{x.open_cards} open</span> : <span className="text-ink-dim">–</span>}
        </td>
      </tr>
      {open && detail ? (
        <tr>
          <td colSpan={cols} className="space-y-4 border-b border-rule-soft bg-ground/40 px-4 py-4">
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-[13px] text-ink-dim">
              <span>Issued {shortDate(detail.issued_date)}, valid until {shortDate(detail.valid_until)}</span>
              <span>Buyer <span className="text-ink">{detail.buyer_name}</span>, {detail.buyer_phone}</span>
              <span>Account manager {detail.account_manager}</span>
              {detail.price_lock_until ? <span>Price lock to {shortDate(detail.price_lock_until)}</span> : null}
            </div>
            {detail.contract_note ? <p className="text-[13px] text-ink">Contract note: {detail.contract_note}</p> : null}

            <table className="w-full text-[13px]">
              <thead className="text-left text-ink-dim">
                <tr>
                  <th className="pb-1.5 font-medium">Part</th>
                  <th className="pb-1.5 font-medium">Made from</th>
                  <th className="pb-1.5 text-right font-medium">Qty</th>
                  <th className="pb-1.5 text-right font-medium">Cost each when quoted</th>
                  <th className="pb-1.5 text-right font-medium">Price each</th>
                </tr>
              </thead>
              <tbody>
                {detail.lines.map((l) => (
                  <tr key={l.id} className="border-t border-rule-soft">
                    <td className="py-1.5 text-ink">{l.part_name}</td>
                    <td className="py-1.5 text-ink-dim">{l.materials}</td>
                    <td className="py-1.5 text-right text-ink-dim">{l.qty.toLocaleString()}</td>
                    <td className="py-1.5 text-right text-ink-dim">{unitPrice(l.material_cost_basis + l.conversion_cost)}</td>
                    <td className="py-1.5 text-right text-ink">{unitPrice(l.unit_price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {detail.revisions.length ? (
              <div>
                <p className="text-[13px] font-medium text-ink">Price revisions</p>
                <ul className="mt-1 space-y-0.5 text-[13px] text-ink">
                  {detail.revisions.map((r) => (
                    <li key={r.id}>{r.part_name}: {unitPrice(r.old_price)} to {unitPrice(r.new_price)}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {detail.cards.length ? (
              <div>
                <p className="text-[13px] font-medium text-ink-dim">Decisions on this quote</p>
                <ul className="mt-1 space-y-0.5 text-[13px] text-ink-dim">
                  {detail.cards.map((c) => (
                    <li key={c.id}>
                      <span className="text-ink">{ACTION_TEXT[c.final_action ?? c.action].short}</span>,{' '}
                      {c.status === 'pending' ? 'waiting' : c.status}, after the {materialLabel(c.material_id)} change,
                      decided by {c.decided_by === 'llm' ? 'Claude' : c.decided_by === 'rule' ? 'a rule' : c.decided_by}
                      {c.exposure_usd ? `, ${usd(c.exposure_usd)} at risk` : ''}
                    </li>
                  ))}
                </ul>
              </div>
            ) : <p className="text-[13px] text-ink-dim">No supplier change has touched this quote.</p>}
          </td>
        </tr>
      ) : null}
    </>
  )
}
