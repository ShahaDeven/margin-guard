import { useState } from 'react'

import { materialLabel, shortDate } from '../lib/format'
import type { Email, Material, Proposal, ReviewFacts } from '../lib/types'
import { Attachments } from './Attachments'
import { Button } from './Button'

/** A supplier email the system would not guess on. The person answers the one
 *  question it couldn't (which material?), or dismisses it. */
export function ReviewCard({
  p, email, materials, onResolve, onDismiss, onRedecide, onForceErp,
}: {
  p: Proposal
  email?: Email
  materials: Material[]
  onResolve: (materialId: string, fix?: { price?: number; effective_date?: string }) => void
  onDismiss: (note?: string) => void
  onRedecide: () => void
  onForceErp?: (outboxId: number) => void
}) {
  const f = p.facts as ReviewFacts
  const [sending, setSending] = useState(false)
  const candidates = f.match_candidates?.length ? f.match_candidates : []
  const canResolve = f.new_cost_per_lb != null && !!f.effective_date
  const name = (id: string) => materials.find((m) => m.id === id)?.name ?? materialLabel(id)

  if (f.kind === 'correction') {
    return <CorrectionCard f={f} sending={sending} onRedecide={() => { setSending(true); onRedecide() }}
      onKeep={() => { setSending(true); onDismiss('Kept the original decision') }} />
  }
  if (f.kind === 'erp_conflict') {
    return (
      <article className="space-y-4">
        <h2 className="text-xl font-bold text-ink">
          <span className="mb-1 block text-[13px] font-medium text-attn">Needs a look</span>
          {f.summary ?? 'Odoo refused a write'}{f.quote_id ? `, ${f.quote_id}` : ''}
        </h2>
        <p className="text-ink">{f.review_reasons?.[0]}</p>
        <p className="text-[13px] text-ink-dim">
          Margin Guard checks what Odoo holds before every write, and stopped because it had changed. Look at the record in
          Odoo: if Margin Guard's version is right, write it anyway; otherwise keep Odoo's, and the next sync brings it in.
        </p>
        <div className="flex flex-wrap gap-2">
          {onForceErp && f.outbox_id ? (
            <Button disabled={sending} onClick={() => { setSending(true); onForceErp(f.outbox_id!) }}>Write it anyway</Button>
          ) : null}
          <Button disabled={sending} onClick={() => { setSending(true); onDismiss('Kept what Odoo has') }}>Keep Odoo's version</Button>
        </div>
      </article>
    )
  }
  if (f.ocr) {
    return <OcrCard f={f} email={email} materials={materials} name={name} sending={sending}
      onApply={(mat, fix) => { setSending(true); onResolve(mat, fix) }} onDismiss={() => { setSending(true); onDismiss('Not a price change') }} />
  }
  if (f.kind === 'invoice_drift') {
    return <DriftCard f={f} name={name} sending={sending} onApply={() => { setSending(true); onResolve(f.material_id!) }}
      onDismiss={() => { setSending(true); onDismiss() }} />
  }

  return (
    <article>
      <div className="space-y-4">
        <div>
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h2 className="text-xl font-bold text-ink">
              <span className="mb-1 block text-[13px] font-medium text-attn">Needs a look</span>
              {email?.subject ?? p.event.email_subject}
            </h2>
            <span className="text-[13px] text-ink-dim">From {email?.vendor_name ?? email?.from_addr ?? 'an unknown sender'}</span>
          </div>
          {/* The reasons name internal ids ("candidates: MAT-EPDM-70…"); when the question below
              asks the same thing in plain words, it stands alone. */}
          {canResolve && candidates.length ? null : (
            <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-ink marker:text-attn">
              {(f.review_reasons ?? []).map((r) => (
                <li key={r}>{r.charAt(0).toUpperCase() + r.slice(1)}.</li>
              ))}
            </ul>
          )}
        </div>
        {email ? (
          <details className="group">
            <summary className="inline-flex cursor-pointer select-none items-center gap-1.5 text-[13px] font-medium text-go hover:text-go-soft">
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden className="transition-transform group-open:rotate-90"><path d="M3 1.5 L7 5 L3 8.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
              <span className="group-open:hidden">Show the email</span><span className="hidden group-open:inline">Hide the email</span>
            </summary>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-sm border border-rule bg-sheet px-3 py-2 font-sans text-[13px] leading-relaxed text-ink">
              {email.body}
            </pre>
          </details>
        ) : null}
        {email ? <Attachments files={email.attachments} /> : null}

        {canResolve && candidates.length ? (
          <div className="space-y-2">
            <p className="text-sm text-ink">
              ${f.new_cost_per_lb?.toFixed(2)}/lb from {shortDate(f.effective_date)}. Which material is "{f.material_text}"?
            </p>
            <div className="flex flex-wrap gap-2">
              {candidates.map((id) => (
                <Button key={id} disabled={sending} onClick={() => { setSending(true); onResolve(id) }}>
                  It's {name(id)}
                </Button>
              ))}
              <Button disabled={sending} onClick={() => { setSending(true); onDismiss() }}>Neither, dismiss</Button>
            </div>
            <p className="text-[12px] text-ink-dim">Your answer becomes a price change, and the agents check every open quote that uses it.</p>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <Button disabled={sending} onClick={() => { setSending(true); onDismiss() }}>Noted, dismiss</Button>
            <span className="text-[12px] text-ink-dim">No exact price and date to apply, so there's nothing for the agents to act on yet.</span>
          </div>
        )}
      </div>
    </article>
  )
}

/** An invoice billed a material above the price on file: an increase nobody announced,
 *  or a billing error. The person applies it as a price change or dismisses it. */
function DriftCard({ f, name, sending, onApply, onDismiss }: {
  f: ReviewFacts
  name: (id: string) => string
  sending: boolean
  onApply: () => void
  onDismiss: () => void
}) {
  const head = 'pb-1.5 text-[13px] font-medium text-ink-dim'
  return (
    <article>
      <div className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 className="text-xl font-bold text-ink">
            <span className="mb-1 block text-[13px] font-medium text-attn">Needs a look</span>
            Invoice billed {f.material_id ? name(f.material_id) : f.material_text} above the price on file
          </h2>
          <span className="text-[13px] text-ink-dim">{f.vendor_name}</span>
        </div>
        <p className="text-[15px] text-ink">
          On file <span className="text-ink-bright">${f.old_cost_per_lb?.toFixed(4)}/lb</span>
          {f.expected_row ? <span className="text-ink-dim"> from {shortDate(f.expected_row.effective_date)}</span> : null}
          {', '}billed <span className="font-semibold text-ink-bright">${f.new_cost_per_lb?.toFixed(4)}/lb</span>
          {f.pct_change != null ? <span className="text-stop"> {f.pct_change >= 0 ? '+' : ''}{(f.pct_change * 100).toFixed(1)}%</span> : null}
          <span className="text-ink-dim">. No price notice on file.</span>
        </p>
        <table className="w-full max-w-xl text-sm">
          <thead><tr className="text-left"><th className={head}>Invoice</th><th className={head}>Date</th><th className={`${head} text-right`}>Over the price on file</th></tr></thead>
          <tbody>
            {(f.invoices ?? []).map((i) => (
              <tr key={`${i.invoice_no}-${i.line_no}`} className="border-t border-rule">
                <td className="py-1.5 text-ink">{i.invoice_no} <span className="text-ink-dim">line {i.line_no}</span></td>
                <td className="py-1.5 text-ink">{shortDate(i.date)}</td>
                <td className="py-1.5 text-right text-ink-bright">${i.overpaid_usd.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot><tr className="border-t border-rule-bright"><td colSpan={2} className="pt-1.5 font-semibold text-ink-bright">Total over the price on file</td>
            <td className="pt-1.5 text-right font-semibold text-ink-bright">${(f.overpaid_usd ?? 0).toFixed(2)}</td></tr></tfoot>
        </table>
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <Button disabled={sending || !f.material_id} onClick={onApply}>Apply as a price change from {shortDate(f.effective_date)}</Button>
            <Button disabled={sending} onClick={onDismiss}>Dismiss: one-off or billing error</Button>
          </div>
          <p className="text-[12px] text-ink-dim">
            Applying records ${f.new_cost_per_lb?.toFixed(4)}/lb from {f.vendor_name}, and the agents check every open quote that uses it.
            Dismissing changes nothing; dispute the invoice with the supplier if it's an error.
          </p>
        </div>
      </div>
    </article>
  )
}

/** A decision a person approved was computed without a price change that arrived later.
 *  The decision stands; this card shows the original and revised numbers side by side and
 *  asks whether to re-decide. Re-deciding is a separate step that raises a new card. */
function CorrectionCard({ f, sending, onRedecide, onKeep }: {
  f: ReviewFacts
  sending: boolean
  onRedecide: () => void
  onKeep: () => void
}) {
  const o = f.original!
  const r = f.revised!
  const floor = f.margin_floor ?? 0
  const head = 'pb-1.5 text-[13px] font-medium text-ink-dim'
  const tone = (m: number) => (m < floor ? 'text-stop' : 'text-ink-bright')
  return (
    <article>
      <div className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 className="text-xl font-bold text-ink">
            <span className="mb-1 block text-[13px] font-medium text-attn">Needs a look</span>
            A decision you approved missed a later price change: {f.customer_name}, {f.quote_id}
          </h2>
          <span className="text-[13px] text-ink-dim">corrects card #{f.corrects}</span>
        </div>
        <p className="text-sm text-ink">{f.review_reasons?.[0]}</p>
        <table className="w-full max-w-2xl text-sm">
          <thead><tr className="text-left"><th className={head}></th><th className={head}>As decided</th><th className={head}>With the change</th></tr></thead>
          <tbody className="font-label">
            <tr className="border-t border-rule"><td className="py-1.5 text-ink-dim">Decision</td>
              <td className="py-1.5 text-ink-bright">{o.final_action} <span className="text-ink-dim">({o.status}{o.reviewed_at ? `, ${o.reviewed_at.slice(0, 10)}` : ''})</span></td>
              <td className="py-1.5 text-ink-dim">to be re-decided, or kept</td></tr>
            <tr className="border-t border-rule"><td className="py-1.5 text-ink-dim">Margin after</td>
              <td className={`py-1.5 ${tone(o.margin_after)}`}>{(o.margin_after * 100).toFixed(1)}%</td>
              <td className={`py-1.5 font-semibold ${tone(r.margin_after)}`}>{(r.margin_after * 100).toFixed(1)}%</td></tr>
            <tr className="border-t border-rule"><td className="py-1.5 text-ink-dim">At risk</td>
              <td className="py-1.5 text-ink-bright">${o.exposure_usd.toFixed(2)}</td>
              <td className="py-1.5 font-semibold text-ink-bright">${r.exposure_usd.toFixed(2)}</td></tr>
            {r.lines.map((ln) => {
              const was = o.lines.find((x) => x.line_id === ln.line_id)
              return (
                <tr key={ln.line_id} className="border-t border-rule"><td className="py-1.5 text-ink-dim">{ln.part_name}: price to hold margin</td>
                  <td className="py-1.5 text-ink-bright">{was ? `$${was.proposed_unit_price.toFixed(4)}` : '-'}</td>
                  <td className="py-1.5 font-semibold text-ink-bright">${ln.proposed_unit_price.toFixed(4)}</td></tr>
              )
            })}
          </tbody>
        </table>
        <p className="text-xs text-ink-dim">Floor {(floor * 100).toFixed(1)}%. Nothing already sent or written is changed by this card.</p>
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <Button disabled={sending} onClick={onRedecide}>Re-decide with the revised numbers</Button>
            <Button disabled={sending} onClick={onKeep}>Keep the original decision</Button>
          </div>
          <p className="text-[12px] text-ink-dim">
            Re-deciding raises a new card for this quote, decided on the revised numbers, for you to approve. The original
            decision and anything it sent stay on record either way.
          </p>
        </div>
      </div>
    </article>
  )
}

const UNIT_WORD: Record<string, string> = { lb: 'lb', kg: 'kg', cwt: 'cwt (100 lb)', short_ton: 'short ton', metric_ton: 'metric ton' }
const fieldCls = 'w-full rounded-sm border border-rule-bright bg-sheet px-3 py-2 text-sm text-ink outline-none focus:border-go'

/** A price read off a scan by OCR. The person checks it against the original (one click
 *  away), corrects what the OCR misread, and applies it; nothing moves a quote before that. */
function OcrCard({ f, email, materials, name, sending, onApply, onDismiss }: {
  f: ReviewFacts
  email?: Email
  materials: Material[]
  name: (id: string) => string
  sending: boolean
  onApply: (materialId: string, fix: { price?: number; effective_date?: string }) => void
  onDismiss: () => void
}) {
  const q = f.quoted
  const quotedUnit = q?.price != null && q.unit && UNIT_WORD[q.unit] ? q.unit : 'lb'
  const read = q?.price != null && quotedUnit === q.unit ? q.price : f.new_cost_per_lb
  const [material, setMaterial] = useState(f.material_id ?? '')
  const money = (n: number) => (Number.isInteger(n * 100) ? n.toFixed(2) : String(n))     // 33.5 -> 33.50, 1.8425 stays
  const [price, setPrice] = useState(read != null ? money(read) : '')
  const [day, setDay] = useState(f.effective_date ?? '')
  const value = Number(price)
  const ok = !!material && price.trim() !== '' && value > 0 && /^\d{4}-\d{2}-\d{2}$/.test(day)
  const changed = read == null || value !== read || day !== f.effective_date || material !== f.material_id
  const others = (f.review_reasons ?? []).filter((r) => !r.startsWith('read by OCR'))
  const choices = f.match_candidates?.length ? f.match_candidates : materials.map((m) => m.id)
  const per = q?.pack_qty && quotedUnit === q.unit ? `${q.pack_qty} ${UNIT_WORD[quotedUnit]} pack` : UNIT_WORD[quotedUnit]

  return (
    <article className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-xl font-bold text-ink">
          <span className="mb-1 block text-[13px] font-medium text-attn">Check a price read from a scan</span>
          {f.material_id ? name(f.material_id) : `"${f.material_text}"`}
        </h2>
        <span className="text-[13px] text-ink-dim">From {email?.vendor_name ?? email?.from_addr ?? 'an unknown sender'}</span>
      </div>
      <p className="text-sm text-ink">
        {(f.ocr?.files ?? []).join(', ')} has no text, so it was read by OCR
        {f.ocr?.notes?.[0] ? <span className="text-ink-dim"> ({f.ocr.notes[0].replace(/^read by OCR, /, '')})</span> : null}.
        OCR can misread a digit, so check the figures against the original before they move any quote.
      </p>
      {others.length ? (
        <ul className="list-disc space-y-0.5 pl-5 text-sm text-ink marker:text-attn">
          {others.map((r) => <li key={r}>{r.charAt(0).toUpperCase() + r.slice(1)}.</li>)}
        </ul>
      ) : null}
      {email ? <Attachments files={email.attachments} /> : null}

      <div className="grid grid-cols-2 gap-3">
        <label className="col-span-2 block">
          <span className="mb-1 block text-[13px] text-ink-dim">Material</span>
          <select value={material} onChange={(e) => setMaterial(e.target.value)} className={fieldCls} disabled={sending}>
            {f.material_id ? null : <option value="">Which material?</option>}
            {choices.map((id) => <option key={id} value={id}>{name(id)}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[13px] text-ink-dim">New price, $ per {per}</span>
          <input value={price} onChange={(e) => setPrice(e.target.value)} inputMode="decimal" className={fieldCls} disabled={sending} />
        </label>
        <label className="block">
          <span className="mb-1 block text-[13px] text-ink-dim">From</span>
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} className={fieldCls} disabled={sending} />
        </label>
      </div>
      <p className="text-[13px] text-ink-dim">
        Read as {read != null ? `$${money(read)} per ${per}` : 'no price'}
        {f.new_cost_per_lb != null && quotedUnit !== 'lb' ? ` ($${f.new_cost_per_lb.toFixed(2)}/lb)` : ''}
        {f.effective_date ? `, from ${shortDate(f.effective_date)}` : ''}
        {f.old_cost_per_lb != null ? `. The price on file is $${f.old_cost_per_lb.toFixed(2)}/lb.` : '.'}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={sending || !ok} onClick={() => onApply(material, { price: value, effective_date: day })}>
          {changed ? 'Apply my corrected figures' : 'Figures match the original: apply'}
        </Button>
        <Button disabled={sending} onClick={onDismiss}>Not a price change, dismiss</Button>
      </div>
      <p className="text-[12px] text-ink-dim">Applying makes it a price change, and the agents check every open quote that uses it.</p>
    </article>
  )
}
