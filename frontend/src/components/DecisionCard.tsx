import { useState, type ReactNode } from 'react'

import { ACTION_TEXT, CHOOSABLE, materialLabel, pct, shortDate, signedPct, usd } from '../lib/format'
import type { Action, Proposal, QuoteFacts } from '../lib/types'
import { whatIf } from '../lib/whatif'
import { Button } from './Button'
import { MarginBar } from './MarginBar'
import { CustomerRecordLine } from './Outcomes'
import { Contact, LinesTable } from './QuoteParts'

export type Review = (body: { verdict: 'approve' | 'edit' | 'reject'; action?: string; subject?: string; body?: string; note?: string }) => void

const COUNT = ['No', 'One', 'Two', 'Three', 'Four', 'Five']
const pts = (v: number) => `${(Math.abs(v) * 100).toFixed(1)} points`
const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1)

/** A collapsed section of the detail panel, closed by default. */
export function Section({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border-b border-rule-soft last:border-b-0">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
        className="flex min-h-11 w-full items-center justify-between gap-3 text-left text-ink hover:text-go-soft">
        {title}
        <span aria-hidden className="text-ink-dim">{open ? '−' : '+'}</span>
      </button>
      {open ? <div className="space-y-3 pb-4">{children}</div> : null}
    </div>
  )
}

/** One plain sentence on what happened to this quote. */
function whatHappened(f: QuoteFacts, shown: { margin_after: number; margin_floor: number }): string {
  const ups = (f.cost_changes ?? []).filter((c) => c.pct_change > 0).length || 1
  const materials = `${COUNT[ups] ?? ups} material${ups === 1 ? '' : 's'} on this quote went up.`
  const gap = shown.margin_after - shown.margin_floor
  const where = gap < 0
    ? `which is ${pts(gap)} under this quote's ${pct(shown.margin_floor)} floor.`
    : `still ${pts(gap)} above this quote's ${pct(shown.margin_floor)} floor.`
  return `${materials} At the new costs the margin is ${pct(shown.margin_after)}, ${where}`
}

/** The detail panel for one quote Claude made a judgment call on: what happened, the three
 *  numbers that matter, the costs that moved, then the decision. Reasoning, line prices, the
 *  draft and the customer's record are one click away. */
export function QuoteDetail({ p, bar, k = 1, onReview, onViewQuote }: {
  p: Proposal & { facts: QuoteFacts }
  /** Confidence bar from the scenario eval; report only, never acts. */
  bar: number | null
  /** What-if multiplier on the cost moves; display only. */
  k?: number
  onReview: Review
  onViewQuote: (quoteId: string) => void
}) {
  const f = p.facts
  const shown = whatIf(f, k)
  const [choosing, setChoosing] = useState(false)
  const [action, setAction] = useState<Action>(p.action)
  const [subject, setSubject] = useState(p.draft_subject ?? '')
  const [body, setBody] = useState(p.draft_body ?? '')
  const [note, setNote] = useState('')
  const [sending, setSending] = useState(false)

  const escalated = p.decided_by === 'error'
  const changed = action !== p.action || subject !== (p.draft_subject ?? '') || body !== (p.draft_body ?? '')
  const needsDraft = action === 'reprice' || action === 'contact_customer'
  const act = (verdict: 'approve' | 'edit' | 'reject') => {
    setSending(true)
    onReview(verdict === 'reject'
      ? { verdict, note: note || undefined }
      : { verdict, action, subject, body, note: note || undefined })
  }
  const below = shown.margin_after < shown.margin_floor
  const changes = f.cost_changes?.length
    ? f.cost_changes
    : [{ material_id: f.material_id, pct_change: f.material_pct_change ?? 0, effective_date: f.effective_date,
         cost_when_quoted: undefined, cost_after: undefined }]

  return (
    <div className="flex flex-col gap-[18px]">
      <div>
        <h2 className="text-xl font-bold text-ink">{f.customer_name}</h2>
        <p className="text-ink-dim">
          {f.quote_id}, quoted at {usd(f.quote_value_usd)}{f.customer_tier === 'key' ? '. Key account.' : ''}
        </p>
      </div>

      <p className="text-[15px] text-ink">{whatHappened(f, shown)}</p>
      {k !== 1 ? (
        <p className="text-[13px] text-attn">These numbers show the increases at {k} times. Approving always uses the real numbers.</p>
      ) : null}

      <dl className="grid grid-cols-3 gap-3">
        <div><dt className="text-[13px] text-ink-dim">Quoted</dt><dd className="text-xl font-semibold text-ink">{pct(shown.margin_before)}</dd></div>
        <div><dt className="text-[13px] text-ink-dim">Now</dt><dd className={`text-xl font-semibold ${below ? 'text-stop' : 'text-ink'}`}>{pct(shown.margin_after)}</dd></div>
        <div><dt className="text-[13px] text-ink-dim">At risk</dt><dd className="text-xl font-semibold text-ink">{usd(shown.exposure_usd)}</dd></div>
      </dl>

      <ul className="flex flex-col gap-1.5 rounded-sm bg-ground px-3.5 py-3">
        {changes.map((c) => (
          <li key={c.material_id} className="flex justify-between gap-3">
            <span>{materialLabel(c.material_id)}</span>
            <span className="text-right">
              {c.cost_when_quoted != null && c.cost_after != null
                ? `$${c.cost_when_quoted.toFixed(2)} to $${c.cost_after.toFixed(2)}/lb`
                : signedPct(c.pct_change)}
              {c.effective_date ? `, ${shortDate(c.effective_date)}` : ''}
            </span>
          </li>
        ))}
      </ul>

      {escalated ? <p className="text-[13px] text-stop">Claude could not decide this one. Choose an action before approving.</p> : null}
      {f.contract_note ? <p className="text-[13px] text-attn">Contract note: {f.contract_note}</p> : null}
      {f.corrects ? (
        <p className="text-[13px] text-attn">
          This re-decides card #{f.corrects.proposal_id}, approved as {f.corrects.original_action}, with a price change that
          arrived later. That decision and anything it sent stay on record.
        </p>
      ) : null}

      <div className="flex flex-col gap-2">
        <Button tone="go" className="min-h-12 text-[15px] font-semibold"
          disabled={sending || (escalated && !changed) || (needsDraft && !body.trim())}
          onClick={() => act(changed ? 'edit' : 'approve')}>
          {changed ? `Save changes and approve: ${lower(ACTION_TEXT[action].verb)}` : `Approve: ${lower(ACTION_TEXT[action].verb)}`}
        </Button>
        <div className="flex gap-2">
          <Button className={`flex-1 ${choosing ? 'border-go text-go-soft' : ''}`} onClick={() => setChoosing(!choosing)}>
            Choose another action
          </Button>
          <Button className="flex-1" disabled={sending} onClick={() => act('reject')}>Reject</Button>
        </div>
        <p className="text-[13px] text-ink-dim">
          {action === 'reprice' ? 'Approving updates the quote prices and queues the email.'
            : action === 'contact_customer' ? 'Approving creates a call task for the account manager.'
              : 'Approving records the decision. Nothing is sent.'}
        </p>
      </div>

      {choosing ? (
        <div className="space-y-3 rounded-sm bg-ground px-3.5 py-3">
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Action">
            {CHOOSABLE.map((a) => (
              <button key={a} type="button" role="radio" aria-checked={action === a}
                onClick={() => setAction(a)}
                className={`rounded-sm border px-3 py-1.5 text-[13px] transition-colors ${
                  action === a ? 'border-go bg-nav-active text-go-soft' : 'border-rule-bright text-ink hover:border-ink-dim'}`}>
                {ACTION_TEXT[a].verb}
              </button>
            ))}
          </div>
          {action !== p.action ? (
            <button type="button" className="text-[13px] text-go hover:text-go-soft" onClick={() => { setAction(p.action); setSubject(p.draft_subject ?? ''); setBody(p.draft_body ?? '') }}>
              Back to {lower(ACTION_TEXT[p.action].verb)}
            </button>
          ) : null}
          {needsDraft && !body.trim() ? <p className="text-[13px] text-attn">Write the message under "Draft message" before approving.</p> : null}
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Note for the record (optional; it teaches the system)"
            aria-label="Note for the record"
            className="w-full rounded-sm border border-rule-bright bg-sheet px-3 py-2 text-sm text-ink outline-none focus:border-go"
          />
        </div>
      ) : null}

      <div className="border-t border-rule">
        <Section title="Why Claude recommends this">
          <p className="text-[13px] text-ink-dim">
            {escalated ? 'Error' : `Claude, ${Math.round((p.confidence ?? 0) * 100)}% sure.`}
            {bar != null && !escalated
              ? (p.confidence ?? 0) >= bar
                ? ` Clears the ${bar.toFixed(2)} confidence bar: in testing, every call this sure was right. You still approve it.`
                : ` Below the ${bar.toFixed(2)} confidence bar: Claude is less sure than usual. Read this one carefully.`
              : ''}
          </p>
          <p className="text-ink">{p.rationale}</p>
          {f.restated ? (
            <p className="text-[13px] text-ink-dim">{f.restated.reason.replace(/^restated: the/, 'The')}. The numbers here include it.</p>
          ) : null}
        </Section>
        <Section title="Line-by-line prices">
          <MarginBar before={shown.margin_before} after={shown.margin_after} floor={shown.margin_floor} />
          <LinesTable f={f} />
          <button type="button" onClick={() => onViewQuote(f.quote_id)} className="text-[13px] text-go hover:text-go-soft">
            Open {f.quote_id} in shop data
          </button>
        </Section>
        <Section title={action === 'contact_customer' ? 'Call task for the account manager' : 'Draft message to the customer'}>
          <Contact f={f} action={action} />
          {needsDraft ? (
            <>
              <input
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="Subject"
                aria-label="Subject"
                className="w-full rounded-sm border border-rule-bright bg-ground px-3 py-2 text-sm text-ink outline-none focus:border-go"
              />
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={10}
                aria-label="Message"
                className="w-full resize-y rounded-sm border border-rule-bright bg-ground px-3 py-2 text-sm leading-relaxed text-ink outline-none focus:border-go"
              />
              <p className="text-[13px] text-ink-dim">Edits here are saved when you approve.</p>
            </>
          ) : <p className="text-[13px] text-ink-dim">{ACTION_TEXT[action].verb} sends nothing to the customer.</p>}
        </Section>
        <Section title="This customer's past increases">
          <CustomerRecordLine r={p.customer_record} name={f.customer_name} />
        </Section>
      </div>
    </div>
  )
}
