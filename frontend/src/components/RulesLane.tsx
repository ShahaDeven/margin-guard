import { Fragment, useState } from 'react'

import { ACTION_TEXT, materialLabel, pct, shortDate, signedPct, usd } from '../lib/format'
import type { Proposal, QuoteFacts } from '../lib/types'
import { Button } from './Button'

const RULE_TEXT: Record<string, string> = {
  expires_before_change: 'Expires before the change',
  price_lock: 'Customer has a price lock',
  within_floor: 'Margin stays above floor',
}

type Card = Proposal & { facts: QuoteFacts }

const head = 'border-b border-rule px-4 py-2.5 text-[13px] font-medium text-ink-dim'
const cell = 'border-b border-rule-soft px-4 py-3 align-top'

/** The one cost-moved format: material, old price, arrow, new price per unit, effective date.
 *  The old price is the new one over (1 + change); every card carries both of those. */
function costMoved(rows: Card[]): string {
  const e = rows[0].event
  const name = materialLabel(e.material_id)
  const change = rows.map((r) => r.facts.cost_changes?.find((c) => c.material_id === e.material_id)).find((c) => c?.cost_after != null)
  const when = e.effective_date ? `, ${shortDate(e.effective_date)}` : ''
  if (change?.cost_after != null && e.pct_change != null) {
    const before = change.cost_after / (1 + e.pct_change)
    return `${name}, $${before.toFixed(2)} → $${change.cost_after.toFixed(2)}/lb${when}`
  }
  return `${name}, ${signedPct(e.pct_change)}${when}`
}

/** Decisions the policy settles by itself, one row per price change, costliest first. The
 *  person skims, opens one to check, and confirms in bulk; nothing here needs judgment. */
export function RulesLane({ cards, onConfirm, onConfirmAll }: {
  cards: Card[]
  onConfirm: (eventId: number) => void
  onConfirmAll: (eventIds: number[]) => void
}) {
  const [open, setOpen] = useState<number | null>(null)
  const byEvent = new Map<number, Card[]>()
  for (const c of cards) byEvent.set(c.event_id, [...(byEvent.get(c.event_id) ?? []), c])
  const groups = [...byEvent.entries()]
    .map(([eventId, rows]) => ({ eventId, rows, usd: rows.reduce((s, r) => s + r.exposure_usd, 0) }))
    .sort((a, b) => b.usd - a.usd)

  return (
    <div className="flex flex-col gap-[18px]">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-ink">Settled by rules</h1>
          <p className="mt-1 text-ink-dim">Price changes the policy settled by itself. Confirm them in bulk or open one to check.</p>
        </div>
        {cards.length ? (
          <Button tone="go" className="font-semibold" onClick={() => onConfirmAll(groups.map((g) => g.eventId))}>
            Confirm all {cards.length}
          </Button>
        ) : null}
      </div>

      {cards.length ? (
        <ul className="overflow-hidden rounded-md border border-rule bg-sheet">
          {groups.map((g) => {
            const isOpen = open === g.eventId
            return (
              <li key={g.eventId} className="border-b border-rule-soft last:border-b-0">
                <div className={`flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3.5 ${isOpen ? 'bg-sheet-2' : ''}`}>
                  <button type="button" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : g.eventId)}
                    className="min-w-0 flex-[1_1_18rem] text-left">
                    <span className="block font-semibold text-ink">{costMoved(g.rows)}</span>
                    <span className="block text-[13px] text-ink-dim">
                      {g.rows[0].event.vendor_name ?? 'Supplier'}, {g.rows.length} quote{g.rows.length === 1 ? '' : 's'}
                    </span>
                  </button>
                  <span className="text-right text-ink">
                    {usd(g.usd)} <span className="text-ink-dim">absorbed or locked in</span>
                  </span>
                  <Button small onClick={() => onConfirm(g.eventId)}>Confirm {g.rows.length}</Button>
                </div>
                {isOpen ? <Quotes rows={g.rows} /> : null}
              </li>
            )
          })}
        </ul>
      ) : <Empty text="No rule decisions waiting." />}
    </div>
  )
}

/** The quotes behind one price change: money first, the $0 ones behind a link. */
function Quotes({ rows }: { rows: Card[] }) {
  const [showAll, setShowAll] = useState(false)
  const sorted = [...rows].sort((a, b) => b.exposure_usd - a.exposure_usd)
  const money = sorted.filter((r) => r.exposure_usd > 0)
  const zero = sorted.filter((r) => r.exposure_usd <= 0)
  const shown = showAll ? sorted : money
  const allExpire = zero.every((r) => r.rule_id === 'expires_before_change')
  // A column with the same value on every row is said once instead (rule 9).
  const oneDecision = new Set(shown.map((r) => r.action)).size === 1 ? ACTION_TEXT[shown[0]?.action ?? 'honor'].short : null
  const why = (r: Card) => RULE_TEXT[r.rule_id ?? ''] ?? r.rule_id ?? ''
  const oneWhy = shown.length && new Set(shown.map(why)).size === 1 ? why(shown[0]) : null
  const said = [oneDecision, oneWhy ? oneWhy.charAt(0).toLowerCase() + oneWhy.slice(1) : null].filter(Boolean)

  return (
    <div className="border-t border-rule-soft bg-ground/40 px-4 pb-3 pt-2">
      {said.length && shown.length ? <p className="pb-2 text-[13px] text-ink-dim">Every one shown: {said.join(', ').replace(/^./, (c) => c.toLowerCase())}.</p> : null}
      {shown.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse text-sm">
            <thead>
              <tr className="text-left">
                <th className={head}>Quote</th>
                {oneDecision ? null : <th className={head}>Decision</th>}
                {oneWhy ? null : <th className={head}>Why</th>}
                <th className={head}>Margin</th>
                <th className={`${head} text-right`}>Amount</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <Fragment key={r.id}>
                  <tr>
                    <td className={cell}>
                      <div className="text-ink">{r.facts.customer_name}</div>
                      <div className="text-[13px] text-ink-dim">{r.facts.quote_id}</div>
                    </td>
                    {oneDecision ? null : <td className={cell}>{ACTION_TEXT[r.action].short}</td>}
                    {oneWhy ? null : <td className={`${cell} text-ink-dim`}>{why(r)}</td>}
                    <td className={cell}>
                      <div>{pct(r.facts.margin_before)} as quoted</div>
                      <div className={`text-[13px] ${r.facts.margin_after < r.facts.margin_floor ? 'text-stop' : 'text-ink-dim'}`}>
                        {pct(r.facts.margin_after)} after the change
                      </div>
                    </td>
                    <td className={`${cell} text-right`}>{usd(r.exposure_usd)}</td>
                  </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {zero.length ? (
        <button type="button" className="mt-2 text-[13px] text-go hover:text-go-soft" onClick={() => setShowAll(!showAll)}>
          {showAll ? 'Hide the $0 quotes'
            : allExpire ? `Show ${zero.length} that expire before the change` : `Show ${zero.length} with nothing at stake`}
        </button>
      ) : null}
    </div>
  )
}

export function Empty({ text }: { text: string }) {
  return <p className="rounded-md border border-dashed border-rule px-5 py-10 text-center text-sm text-ink-dim">{text}</p>
}
