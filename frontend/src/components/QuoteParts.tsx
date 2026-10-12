import { materialLabel, shortDate, signedPct, unitPrice } from '../lib/format'
import type { Action, QuoteFacts } from '../lib/types'

/** Every cost change behind this card's numbers, not just the one that triggered it. */
export function CostChanges({ f }: { f: QuoteFacts }) {
  const changes = f.cost_changes?.length
    ? f.cost_changes
    : [{ material_id: f.material_id, pct_change: f.material_pct_change ?? 0, effective_date: f.effective_date }]
  return (
    <span>
      {changes.map((c, i) => (
        <span key={c.material_id}>
          {i > 0 ? <span className="text-silver-dim"> · </span> : null}
          <span className={i === 0 ? 'text-silver' : 'text-silver-dim'}>
            {materialLabel(c.material_id)} {signedPct(c.pct_change)}
          </span>
          {c.effective_date ? <span className="text-silver-dim"> from {shortDate(c.effective_date)}</span> : null}
        </span>
      ))}
    </span>
  )
}

/** Who to call or write to, right where the decision is made. */
export function Contact({ f, action }: { f: QuoteFacts; action: Action }) {
  const b = f.buyer
  if (!b?.name) return null
  const am = f.account_manager
  if (action === 'contact_customer') {
    return (
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded border border-cyan/30 bg-cyan/[0.04] px-3 py-2 text-sm">
        <span className="font-mono text-[10px] uppercase tracking-wider text-cyan">Call</span>
        <span className="text-silver-bright">{b.name}</span>
        {b.phone ? (
          <a href={`tel:${b.phone.replace(/[^\d+]/g, '')}`} className="font-mono text-cyan underline decoration-cyan/40 underline-offset-2">
            {b.phone}
          </a>
        ) : null}
        {b.email ? <span className="text-silver-dim">{b.email}</span> : null}
        {am?.name ? <span className="ml-auto text-xs text-silver-dim">Account manager: {am.name} · {am.phone}</span> : null}
      </div>
    )
  }
  if (action === 'reprice') {
    return (
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded border border-line px-3 py-2 text-sm">
        <span className="font-mono text-[10px] uppercase tracking-wider text-silver-dim">Email to</span>
        <span className="text-silver-bright">{b.name}</span>
        <span className="font-mono text-silver">{b.email}</span>
        {b.phone ? <span className="ml-auto text-xs text-silver-dim">{b.phone}</span> : null}
      </div>
    )
  }
  return null
}

/** Line-by-line: what each part costs us now and after, what we quoted, what we'd revise to. */
export function LinesTable({ f, revisedLabel = 'Revised' }: { f: QuoteFacts; revisedLabel?: string }) {
  return (
    <table className="w-full font-mono text-xs">
      <thead className="text-left text-[10px] uppercase tracking-wider text-silver-dim">
        <tr>
          <th className="pb-2 font-normal">Part</th>
          <th className="pb-2 text-right font-normal">Qty</th>
          <th className="pb-2 text-right font-normal">Unit cost now → after</th>
          <th className="pb-2 text-right font-normal">Quoted / unit</th>
          <th className="pb-2 text-right font-normal">{revisedLabel} / unit</th>
        </tr>
      </thead>
      <tbody>
        {f.lines.map((ln) => {
          const hits = ln.changed_materials ?? (ln.uses_changed_material ? [f.material_id] : [])
          return (
            <tr key={ln.line_id} className="border-t border-line/60 align-top">
              <td className="py-1.5 font-sans text-[13px] text-silver">
                {ln.part_name}
                {hits.length ? (
                  <span className="mt-0.5 flex flex-wrap gap-1">
                    {hits.map((m) => (
                      <span
                        key={m}
                        className={`rounded px-1 font-mono text-[10px] ${m === f.material_id ? 'bg-hiviz/10 text-hiviz' : 'bg-panel-2 text-silver-dim'}`}
                      >
                        {materialLabel(m)}
                      </span>
                    ))}
                  </span>
                ) : null}
              </td>
              <td className="py-1.5 text-right text-silver-dim">{ln.qty.toLocaleString()}</td>
              <td className="py-1.5 text-right text-silver-dim">{unitPrice(ln.unit_cost_before)} → {unitPrice(ln.unit_cost_after)}</td>
              <td className="py-1.5 text-right text-silver">{unitPrice(ln.unit_price)}</td>
              <td className={`py-1.5 text-right ${ln.proposed_unit_price !== ln.unit_price ? 'text-cyan' : 'text-silver-dim'}`}>
                {unitPrice(ln.proposed_unit_price)}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
