import { ACTION_TEXT, materialLabel, pct, shortDate, signedPct, usd } from '../lib/format'
import type { Proposal, QuoteFacts } from '../lib/types'
import { Button } from './Button'

const RULE_TEXT: Record<string, string> = {
  expires_before_change: 'expires before the change',
  price_lock: 'customer has a price lock',
  within_floor: 'margin stays above floor',
}

/** Decisions the policy settles by itself, grouped by the price change behind them.
 *  The person skims and confirms in bulk; nothing here needs judgment. */
export function RulesLane({ cards, onConfirm }: { cards: (Proposal & { facts: QuoteFacts })[]; onConfirm: (eventId: number) => void }) {
  const groups = new Map<number, (Proposal & { facts: QuoteFacts })[]>()
  for (const c of cards) groups.set(c.event_id, [...(groups.get(c.event_id) ?? []), c])

  if (!cards.length) return <Empty text="No rule decisions waiting." />

  return (
    <div className="space-y-5">
      {[...groups.entries()].map(([eventId, rows]) => {
        const e = rows[0].event
        const exposure = rows.reduce((s, r) => s + r.exposure_usd, 0)
        return (
          <section key={eventId} className="rounded-lg border border-line bg-panel">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3">
              <div>
                <p className="text-sm font-semibold text-silver-bright">
                  {materialLabel(e.material_id)} <span className="font-mono text-silver-dim">{signedPct(e.pct_change)}</span>
                  <span className="font-normal text-silver-dim"> · from {shortDate(e.effective_date)} · {e.vendor_name}</span>
                </p>
                <p className="mt-0.5 font-mono text-[11px] text-silver-dim">
                  {rows.length} quotes · {usd(exposure)} absorbed or locked in
                </p>
              </div>
              <Button tone="cyan" small onClick={() => onConfirm(eventId)}>CONFIRM ALL {rows.length}</Button>
            </header>
            <table className="w-full text-sm">
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-t border-line/50 first:border-t-0">
                    <td className="py-2 pl-5 font-mono text-xs text-silver-dim">{r.facts.quote_id}</td>
                    <td className="py-2 text-silver">{r.facts.customer_name}</td>
                    <td className="py-2 text-silver-bright">{ACTION_TEXT[r.action].short}</td>
                    <td className="py-2 text-silver-dim">{RULE_TEXT[r.rule_id ?? ''] ?? r.rule_id}</td>
                    <td className="py-2 font-mono text-xs text-silver-dim">{pct(r.facts.margin_before)} → {pct(r.facts.margin_after)}</td>
                    <td className="py-2 pr-5 text-right font-mono text-xs text-silver">{usd(r.exposure_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )
      })}
    </div>
  )
}

export function Empty({ text }: { text: string }) {
  return <p className="rounded-lg border border-dashed border-line px-5 py-10 text-center text-sm text-silver-dim">{text}</p>
}
