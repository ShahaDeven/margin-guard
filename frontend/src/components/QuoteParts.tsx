import type { ReactNode } from 'react'

import { FAMILY_BG, familyOf, materialLabel, shortDate, signedPct, unitPrice } from '../lib/format'
import type { Action, QuoteFacts } from '../lib/types'

/** A material named the way the catalogue tabs it: a family-coloured tab, then the name. */
export function Family({ id, children }: { id: string; children?: ReactNode }) {
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span aria-hidden className={`inline-block h-2.5 w-2.5 translate-y-px rounded-[1px] ${FAMILY_BG[familyOf(id)] ?? FAMILY_BG.other}`} />
      {children ?? materialLabel(id)}
    </span>
  )
}

/** Every cost change behind this card's numbers, not just the one that triggered it,
 *  set as catalogue specs: family tab, material, $/lb was → now, change, date. */
export function CostChanges({ f }: { f: QuoteFacts }) {
  const changes = f.cost_changes?.length
    ? f.cost_changes
    : [{ material_id: f.material_id, pct_change: f.material_pct_change ?? 0, effective_date: f.effective_date,
         cost_when_quoted: undefined, cost_after: undefined }]
  return (
    <span className="flex flex-wrap gap-x-4 gap-y-0.5 font-label text-[13px]">
      {changes.map((c, i) => (
        <span key={c.material_id} className={i === 0 ? 'text-ink-bright' : 'text-ink-dim'}>
          <Family id={c.material_id} />
          {c.cost_when_quoted != null && c.cost_after != null ? (
            <span className="text-ink-dim"> ${c.cost_when_quoted.toFixed(2)} → <span className={i === 0 ? 'font-semibold text-ink-bright' : ''}>${c.cost_after.toFixed(2)}</span>/lb</span>
          ) : null}
          <span className={i === 0 ? 'font-semibold text-ink-bright' : ''}> {signedPct(c.pct_change)}</span>
          {c.effective_date ? <span className="text-ink-dim"> from {shortDate(c.effective_date)}</span> : null}
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
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded border border-go/30 bg-go/4 px-3 py-2 text-sm">
        <span className="font-label text-[12px] uppercase tracking-wider text-go">Call</span>
        <span className="text-ink-bright">{b.name}</span>
        {b.phone ? (
          <a href={`tel:${b.phone.replace(/[^\d+]/g, '')}`} className="font-label text-go underline decoration-go/40 underline-offset-2">
            {b.phone}
          </a>
        ) : null}
        {b.email ? <span className="text-ink-dim">{b.email}</span> : null}
        {am?.name ? <span className="ml-auto text-xs text-ink-dim">Account manager: {am.name} · {am.phone}</span> : null}
      </div>
    )
  }
  if (action === 'reprice') {
    return (
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded border border-rule px-3 py-2 text-sm">
        <span className="font-label text-[12px] uppercase tracking-wider text-ink-dim">Email to</span>
        <span className="text-ink-bright">{b.name}</span>
        <span className="font-label text-ink">{b.email}</span>
        {b.phone ? <span className="ml-auto text-xs text-ink-dim">{b.phone}</span> : null}
      </div>
    )
  }
  return null
}

/** Line-by-line: what each part costs us now and after, what we quoted, what we'd revise to. */
export function LinesTable({ f, revisedLabel = 'Revised' }: { f: QuoteFacts; revisedLabel?: string }) {
  return (
    <table className="w-full font-label text-xs">
      <thead className="text-left text-[12px] uppercase tracking-wider text-ink-dim">
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
            <tr key={ln.line_id} className="border-t border-rule/60 align-top">
              <td className="py-1.5 font-sans text-[13px] text-ink">
                {ln.part_name}
                {hits.length ? (
                  <span className="mt-0.5 flex flex-wrap gap-1">
                    {hits.map((m) => (
                      <span
                        key={m}
                        className={`rounded-sm bg-sheet-2 px-1 font-label text-[12px] ${m === f.material_id ? 'text-ink-bright' : 'text-ink-dim'}`}
                      >
                        {materialLabel(m)}
                      </span>
                    ))}
                  </span>
                ) : null}
              </td>
              <td className="py-1.5 text-right text-ink-dim">{ln.qty.toLocaleString()}</td>
              <td className="py-1.5 text-right text-ink-dim">{unitPrice(ln.unit_cost_before)} → {unitPrice(ln.unit_cost_after)}</td>
              <td className="py-1.5 text-right text-ink">{unitPrice(ln.unit_price)}</td>
              <td className={`py-1.5 text-right ${ln.proposed_unit_price !== ln.unit_price ? 'text-go' : 'text-ink-dim'}`}>
                {unitPrice(ln.proposed_unit_price)}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
