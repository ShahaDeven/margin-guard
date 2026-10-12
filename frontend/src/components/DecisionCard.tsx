import { useState } from 'react'

import { ACTION_TEXT, CHOOSABLE, usd } from '../lib/format'
import type { Action, Proposal, QuoteFacts } from '../lib/types'
import { Button } from './Button'
import { MarginBar } from './MarginBar'
import { Contact, CostChanges, LinesTable } from './QuoteParts'

type Review = (body: { verdict: 'approve' | 'edit' | 'reject'; action?: string; subject?: string; body?: string; note?: string }) => void

/** One quote Claude made a judgment call on. Closed: who, what we recommend,
 *  how much is at stake. Open: why, the numbers, and an editable draft. */
export function DecisionCard({ p, fresh, onReview, onViewQuote }: {
  p: Proposal & { facts: QuoteFacts }
  fresh: boolean
  onReview: Review
  onViewQuote: (quoteId: string) => void
}) {
  const f = p.facts
  const [open, setOpen] = useState(false)
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

  return (
    <article className={`rounded-lg border bg-panel ${fresh ? 'mg-arrive border-hiviz/50' : 'border-line'} ${open ? 'border-line-bright' : ''}`}>
      <button type="button" onClick={() => setOpen(!open)} className="grid w-full grid-cols-[1fr_auto] items-center gap-x-6 gap-y-3 px-5 py-4 text-left md:grid-cols-[minmax(0,1.6fr)_minmax(10rem,1fr)_auto]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-[15px] font-semibold text-silver-bright">{f.customer_name}</span>
            {f.customer_tier === 'key' ? (
              <span className="rounded border border-purple/40 px-1.5 py-px font-mono text-[10px] tracking-wider text-purple">KEY ACCOUNT</span>
            ) : null}
            {f.contract_note ? (
              <span className="rounded border border-hiviz/40 px-1.5 py-px font-mono text-[10px] tracking-wider text-hiviz">CONTRACT NOTE</span>
            ) : null}
          </div>
          <p className="mt-1 text-sm text-silver">
            <span className={escalated ? 'text-signal' : 'text-silver-bright'}>{ACTION_TEXT[p.action].verb}</span>
            <span className="text-silver-dim"> · {f.quote_id} · {usd(f.quote_value_usd)}</span>
          </p>
          <p className="mt-0.5 text-xs">
            <CostChanges f={f} />
          </p>
        </div>
        <div className="col-span-2 md:col-span-1">
          <MarginBar before={f.margin_before} after={f.margin_after} floor={f.margin_floor} />
        </div>
        <div className="row-start-1 text-right md:row-start-auto">
          <div className="font-mono text-base text-silver-bright">{usd(f.exposure_usd)}</div>
          <div className="font-mono text-[10px] uppercase tracking-wider text-silver-dim">at risk</div>
        </div>
      </button>

      {open ? (
        <div className="space-y-5 border-t border-line px-5 py-5">
          <div className="flex gap-3">
            <span className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-purple">
              {escalated ? 'Error' : `Claude · ${Math.round((p.confidence ?? 0) * 100)}% sure`}
            </span>
            <p className="flex-1 text-sm leading-relaxed text-silver">{p.rationale}</p>
          </div>

          {f.contract_note ? (
            <p className="rounded border border-hiviz/30 bg-hiviz/[0.04] px-3 py-2 text-sm text-silver">
              <span className="font-mono text-[10px] uppercase tracking-wider text-hiviz">Contract note · </span>
              {f.contract_note}
            </p>
          ) : null}

          <LinesTable f={f} />
          <button type="button" onClick={() => onViewQuote(f.quote_id)} className="font-mono text-[11px] text-silver-dim underline-offset-2 hover:text-silver hover:underline">
            View {f.quote_id} in Data →
          </button>

          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[10px] uppercase tracking-wider text-silver-dim">Action</span>
              {CHOOSABLE.map((a) => (
                <button
                  key={a}
                  type="button"
                  onClick={() => setAction(a)}
                  className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                    action === a ? 'border-purple/70 bg-purple/15 text-silver-bright' : 'border-line text-silver-dim hover:border-line-bright'
                  }`}
                >
                  {ACTION_TEXT[a].short}
                </button>
              ))}
            </div>
            <Contact f={f} action={action} />
            {needsDraft ? (
              <>
                <input
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder="Subject"
                  className="w-full rounded border border-line bg-panel-2 px-3 py-2 text-sm text-silver-bright outline-none focus:border-purple/60"
                />
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  rows={9}
                  className="w-full resize-y rounded border border-line bg-panel-2 px-3 py-2 text-sm leading-relaxed text-silver outline-none focus:border-purple/60"
                />
              </>
            ) : null}
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Note for the record (optional, but it teaches the system)"
              className="w-full rounded border border-line bg-panel-2 px-3 py-2 text-sm text-silver outline-none focus:border-line-bright"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button tone="cyan" disabled={sending || escalated && !changed || needsDraft && !body.trim()} onClick={() => act(changed ? 'edit' : 'approve')}>
              {changed ? 'SAVE CHANGES & APPROVE' : 'APPROVE'}
            </Button>
            <Button tone="signal" disabled={sending} onClick={() => act('reject')}>REJECT</Button>
            <span className="ml-auto font-mono text-[10px] text-silver-dim">
              {action === 'reprice' ? 'Approving updates the quote prices and queues the email.'
                : action === 'contact_customer' ? 'Approving creates a call task for the account manager.'
                  : 'Approving records the decision; nothing is sent.'}
            </span>
          </div>
        </div>
      ) : null}
    </article>
  )
}
