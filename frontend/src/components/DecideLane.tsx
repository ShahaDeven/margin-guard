import { useEffect, useMemo, useRef, useState, type KeyboardEvent as RowKeyEvent, type ReactNode } from 'react'

import { ACTION_TEXT, materialLabel, pct, shortDate, usd } from '../lib/format'
import type { CostChange, Email, Material, Proposal, QuoteFacts, ReviewFacts } from '../lib/types'
import { isQuote } from '../lib/types'
import { whatIf } from '../lib/whatif'
import { QuoteDetail, type Review } from './DecisionCard'
import { ReviewCard } from './ReviewCard'

const WHAT_IF = [1, 1.25, 1.5, 2]

type Basic = 'all' | 'below' | 'contact_customer' | 'reprice' | 'questions'
/** What the table shows; `customer:{id}` comes from a Home link, `material:{id}` from the
 *  filter or from a price change the ERP sync brought in. */
export type DecideFilter = Basic | `customer:${string}` | `material:${string}`

/** Every material whose cost moved on this card, the one that triggered it first. */
const movedOn = (f: QuoteFacts) => (f.cost_changes?.length ? f.cost_changes.map((c) => c.material_id) : [f.material_id])

/** Does the card concern this material: a quote it moved, or a supplier question about it? */
const concerns = (p: Proposal, m: string) =>
  isQuote(p) ? movedOn(p.facts).includes(m) : (p.facts as ReviewFacts).material_id === m
const FILTERS: { id: Basic; label: string }[] = [
  { id: 'all', label: 'Everything' },
  { id: 'below', label: 'Under the floor' },
  { id: 'contact_customer', label: 'Call the customer first' },
  { id: 'reprice', label: 'Send a revised quote' },
  { id: 'questions', label: 'Supplier questions' },
]

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** An outline button that opens a small panel under it; closes on outside click or Escape. */
function Popover({ label, active, wide, children }: {
  label: string; active?: boolean; wide?: boolean; children: (close: () => void) => ReactNode
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); window.removeEventListener('keydown', onKey) }
  }, [open])
  return (
    <div ref={ref} className="relative">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
        className={`min-h-11 rounded-sm border bg-sheet px-3.5 text-sm transition-colors ${
          active ? 'border-go text-go-soft' : 'border-rule-bright text-ink hover:border-ink-dim'}`}>
        {label}
      </button>
      {open ? (
        <div className={`absolute right-0 z-30 mt-2 max-h-[75vh] overflow-y-auto rounded-md border border-rule bg-sheet p-2 shadow-[0_12px_32px_rgba(0,0,0,0.35)] ${wide ? 'w-[22rem] max-w-[calc(100vw-2rem)]' : 'w-72'}`}>
          {children(() => setOpen(false))}
        </div>
      ) : null}
    </div>
  )
}

function Choice({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" role="menuitemradio" aria-checked={on} onClick={onClick}
      className={`flex w-full items-center justify-between rounded-sm px-2.5 py-2 text-left text-sm ${
        on ? 'bg-nav-active text-go-soft' : 'text-ink hover:bg-nav-active/60'}`}>
      {children}
      {on ? <span aria-hidden>✓</span> : null}
    </button>
  )
}

/** A supplier question, as a row: who sent it and what it is about. */
function reviewRow(p: Proposal, inbox: Email[]) {
  const f = p.facts as ReviewFacts
  const email = inbox.find((m) => m.id === f.email_id)
  if (f.kind === 'correction') {
    return { name: f.customer_name ?? 'A decision you approved', sub: `${f.quote_id}, missed a later price change`,
      risk: f.revised ? usd(f.revised.exposure_usd) : '' }
  }
  if (f.kind === 'erp_conflict') {
    return { name: 'Odoo', sub: f.quote_id ? `${f.summary ?? 'A write was refused'}, ${f.quote_id}` : f.summary ?? 'A write was refused', risk: '' }
  }
  if (f.kind === 'invoice_drift') {
    return { name: f.vendor_name ?? 'Supplier invoice', sub: 'Invoice billed above the price on file',
      risk: f.overpaid_usd != null ? usd(f.overpaid_usd) : '' }
  }
  return { name: email?.vendor_name ?? f.vendor_name ?? email?.from_addr ?? 'Supplier email',
    // One row per price read off a scan, so each says which price it is.
    sub: f.ocr && f.material_text ? `Price read from a scan: ${f.material_text}`
      : email?.subject ?? p.event.email_subject ?? `Email ${f.email_id}`, risk: '' }
}

/** The estimator's screen: every decision waiting, one row each, and the selected one in
 *  full beside it. Supplier questions sit at the top of the same table. */
export function DecideLane({ cards, inbox, materials, arrived, bar, notice, filter, setFilter, onReview, onResolve, onDismiss, onRedecide, onForceErp, onViewQuote }: {
  cards: Proposal[]
  inbox: Email[]
  materials: Material[]
  arrived: Set<number>
  bar: number | null
  /** Shown under the header, e.g. "only cards from email E03". */
  notice?: ReactNode
  filter: DecideFilter
  setFilter: (f: DecideFilter) => void
  onReview: (id: number) => Review
  onResolve: (id: number, materialId: string, fix?: { price?: number; effective_date?: string }) => void
  onDismiss: (id: number, note?: string) => void
  onRedecide: (id: number) => void
  onForceErp: (outboxId: number) => void
  onViewQuote: (quoteId: string) => void
}) {
  const [k, setK] = useState(1)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const panel = useRef<HTMLElement>(null)

  const questions = cards.filter((p) => p.kind === 'event_review')
  const quotes = cards.filter(isQuote)
  const rows: Proposal[] = useMemo(() => {
    const show = (p: Proposal) => {
      if (filter === 'all') return true
      if (filter === 'questions') return p.kind === 'event_review'
      if (filter.startsWith('customer:')) return isQuote(p) && p.facts.customer_id === filter.slice(9)
      if (filter.startsWith('material:')) return concerns(p, filter.slice(9))
      if (!isQuote(p)) return false
      if (filter === 'below') return p.facts.margin_after < p.facts.margin_floor
      return p.action === filter
    }
    return [...questions, ...quotes].filter(show)
  }, [questions, quotes, filter])
  // When the selected row leaves (approved, rejected, answered), the row that moved into its
  // place is selected, so working down the queue never jumps back to the top.
  const lastIndex = useRef(0)
  const found = rows.findIndex((p) => p.id === selectedId)
  const selected = found >= 0 ? rows[found] : rows[Math.min(lastIndex.current, rows.length - 1)] ?? null
  useEffect(() => { if (selected) lastIndex.current = rows.indexOf(selected) }, [rows, selected])

  const select = (id: number) => {
    setSelectedId(id)
    if (window.matchMedia('(max-width: 1023px)').matches) panel.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  // J and K move the selection; ignored while typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.closest('input, textarea, select, [contenteditable]') || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key !== 'j' && e.key !== 'k') return
      const i = selected ? rows.indexOf(selected) : -1
      const next = rows[e.key === 'j' ? Math.min(i + 1, rows.length - 1) : Math.max(i - 1, 0)]
      if (next) {
        setSelectedId(next.id)
        document.getElementById(`row-${next.id}`)?.scrollIntoView({ block: 'nearest' })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [rows, selected])

  const below = quotes.filter((p) => p.facts.margin_after < p.facts.margin_floor).length
  const focusMaterial = filter.startsWith('material:') ? filter.slice(9) : null
  // The price changes behind the open cards, the way Settled by rules groups them: one entry per
  // material, with its move and how many cards it is on.
  const byMaterial = useMemo(() => {
    const seen = new Map<string, { id: string; n: number; move: string }>()
    for (const p of quotes) {
      for (const c of p.facts.cost_changes?.length ? p.facts.cost_changes : [{ material_id: p.facts.material_id } as CostChange]) {
        const e = seen.get(c.material_id) ?? { id: c.material_id, n: 0, move: '' }
        e.n += 1
        // Each quote was costed on its own date, so only the new price and its date are shared.
        if (!e.move && c.cost_after != null) {
          e.move = `to $${c.cost_after.toFixed(2)}/lb${c.effective_date ? ` from ${shortDate(c.effective_date)}` : ''}`
        }
        seen.set(c.material_id, e)
      }
    }
    return [...seen.values()].sort((a, b) => b.n - a.n)
  }, [quotes])
  const filterLabel = filter.startsWith('customer:')
    ? quotes.find((p) => p.facts.customer_id === filter.slice(9))?.facts.customer_name ?? 'one customer'
    : focusMaterial ? materialLabel(focusMaterial)
      : FILTERS.find((x) => x.id === filter)?.label.toLowerCase() ?? ''
  const atRisk = quotes.reduce((s, p) => s + p.facts.exposure_usd, 0)
  const summary = [
    quotes.length === below
      ? `${plural(quotes.length, 'open quote')} fell below ${quotes.length === 1 ? 'its' : 'their'} margin floor.`
      : `${plural(quotes.length, 'open quote')} need${quotes.length === 1 ? 's' : ''} a decision, ${below} below the margin floor.`,
    `${usd(atRisk)} at risk, largest first.`,
    questions.length ? `${plural(questions.length, 'supplier question')} at the top.` : '',
  ].filter(Boolean).join(' ')
  // A column that says the same thing on every row is said once, above the table (rule 9).
  const actionOf = (p: Proposal) => (isQuote(p) ? ACTION_TEXT[p.action].verb : 'Answer a question')
  const sameAction = rows.length > 1 && new Set(rows.map(actionOf)).size === 1 ? actionOf(rows[0]) : null

  return (
    <div className="flex flex-col gap-[18px]">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-ink">To decide</h1>
          <p className="mt-1 text-ink-dim">{cards.length ? summary : 'Nothing needs you right now.'}</p>
          {sameAction ? (
            <p className="text-ink-dim">Recommended for every one shown: {sameAction.charAt(0).toLowerCase() + sameAction.slice(1)}.</p>
          ) : null}
        </div>
        <div className="flex gap-2">
          <Popover label={filter === 'all' ? 'Filter' : `Filter: ${filterLabel}`} active={filter !== 'all'} wide>
            {(close) => (
              <div role="menu" aria-label="Show">
                {FILTERS.map((x) => (
                  <Choice key={x.id} on={filter === x.id} onClick={() => { setFilter(x.id); close() }}>{x.label}</Choice>
                ))}
                {byMaterial.length ? (
                  <>
                    <p className="mt-1.5 border-t border-rule px-2.5 pb-1 pt-2 text-[13px] text-ink-dim">By price change</p>
                    {byMaterial.map((m) => (
                      <Choice key={m.id} on={focusMaterial === m.id} onClick={() => { setFilter(`material:${m.id}`); close() }}>
                        <span className="flex justify-between gap-4">
                          <span>{materialLabel(m.id)}<span className="text-ink-dim">{m.move ? `, ${m.move}` : ''}</span></span>
                          <span className="text-ink-dim">{m.n}</span>
                        </span>
                      </Choice>
                    ))}
                  </>
                ) : null}
              </div>
            )}
          </Popover>
          <Popover label={k === 1 ? 'What if increases were bigger' : `What if: ${k} times`} active={k !== 1}>
            {(close) => (
              <div role="menu" aria-label="Increases at">
                <p className="px-2.5 pb-1.5 pt-1 text-[13px] text-ink-dim">Show every margin and dollar at risk as if the increases were</p>
                {WHAT_IF.map((v) => (
                  <Choice key={v} on={k === v} onClick={() => { setK(v); close() }}>{v === 1 ? 'As announced' : `${v} times as big`}</Choice>
                ))}
              </div>
            )}
          </Popover>
        </div>
      </div>
      {k !== 1 ? (
        <p className="text-[13px] text-attn">Hypothetical: margins and dollars at risk show the increases at {k} times. Approving always uses the real numbers.</p>
      ) : null}
      {notice}

      {cards.length ? (
        <div className="flex flex-wrap items-start gap-5">
          <div className="min-w-0 flex-[3_1_480px] overflow-x-auto rounded-md border border-rule bg-sheet">
            <table className="w-full min-w-[520px] border-collapse">
              <thead>
                <tr className="text-left text-[13px] text-ink-dim">
                  <th className="border-b border-rule px-4 py-3 font-medium">Customer</th>
                  <th className="border-b border-rule px-4 py-3 font-medium">Margin now</th>
                  {sameAction ? null : <th className="border-b border-rule px-4 py-3 font-medium">Recommended</th>}
                  <th className="border-b border-rule px-4 py-3 text-right font-medium">At risk</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => {
                  const on = selected?.id === p.id
                  const cls = `cursor-pointer outline-none transition-colors focus-visible:bg-nav-active ${on ? 'bg-sheet-2' : 'hover:bg-sheet-2/50'} ${arrived.has(p.id) ? 'mg-arrive' : ''}`
                  const keys = (e: RowKeyEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(p.id) } }
                  if (!isQuote(p)) {
                    const r = reviewRow(p, inbox)
                    return (
                      <tr key={p.id} id={`row-${p.id}`} tabIndex={0} aria-selected={on} onClick={() => select(p.id)} onKeyDown={keys} className={cls}>
                        <td className="border-b border-rule-soft px-4 py-3.5"><div className="font-semibold">{r.name}</div><div className="text-[13px] text-ink-dim">{r.sub}</div></td>
                        <td className="border-b border-rule-soft px-4 py-3.5 text-ink-dim">–</td>
                        {sameAction ? null : <td className="border-b border-rule-soft px-4 py-3.5 text-attn">Answer a question</td>}
                        <td className="border-b border-rule-soft px-4 py-3.5 text-right font-semibold">{r.risk}</td>
                      </tr>
                    )
                  }
                  const f: QuoteFacts = p.facts
                  const s = whatIf(f, k)
                  const gap = s.margin_after - s.margin_floor
                  return (
                    <tr key={p.id} id={`row-${p.id}`} tabIndex={0} aria-selected={on} onClick={() => select(p.id)} onKeyDown={keys} className={cls}>
                      <td className="border-b border-rule-soft px-4 py-3.5">
                        <div className="font-semibold">{f.customer_name}</div>
                        <div className="text-[13px] text-ink-dim">{f.quote_id}, {usd(f.quote_value_usd)}</div>
                        {focusMaterial && movedOn(f).length > 1 ? (
                          <div className="text-[13px] text-ink-dim">
                            Also on this quote: {movedOn(f).filter((m) => m !== focusMaterial).map(materialLabel).join(', ')}
                          </div>
                        ) : null}
                      </td>
                      <td className="border-b border-rule-soft px-4 py-3.5">
                        <div>{pct(s.margin_after)}</div>
                        <div className={`text-[13px] ${gap < 0 ? 'text-stop' : 'text-ink-dim'}`}>
                          {(Math.abs(gap) * 100).toFixed(1)} pts {gap < 0 ? 'under' : 'above'} floor
                        </div>
                      </td>
                      {sameAction ? null : <td className={`border-b border-rule-soft px-4 py-3.5 ${p.decided_by === 'error' ? 'text-stop' : ''}`}>{ACTION_TEXT[p.action].verb}</td>}
                      <td className="border-b border-rule-soft px-4 py-3.5 text-right font-semibold">{usd(s.exposure_usd)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <p className="px-4 py-3 text-[13px] text-ink-dim">
              {rows.length === cards.length ? `Showing all ${cards.length}` : rows.length ? `Showing ${rows.length} of ${cards.length}` : 'Nothing matches this filter.'}
              <span className="hidden sm:inline">. J and K move the selection.</span>
            </p>
          </div>

          {selected ? (
            <aside ref={panel} aria-label="Selected decision"
              className="min-w-0 flex-[2_1_340px] scroll-mt-4 rounded-md border border-rule bg-sheet p-[22px] lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
              {isQuote(selected) ? (
                <QuoteDetail key={selected.id} p={selected} bar={bar} k={k} onReview={onReview(selected.id)} onViewQuote={onViewQuote} focusMaterial={focusMaterial} />
              ) : (
                <ReviewCard
                  key={selected.id}
                  p={selected}
                  email={inbox.find((m) => m.id === (selected.facts as ReviewFacts).email_id)}
                  materials={materials}
                  onResolve={(mat, fix) => onResolve(selected.id, mat, fix)}
                  onDismiss={(note) => onDismiss(selected.id, note)}
                  onRedecide={() => onRedecide(selected.id)}
                  onForceErp={onForceErp}
                />
              )}
            </aside>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
