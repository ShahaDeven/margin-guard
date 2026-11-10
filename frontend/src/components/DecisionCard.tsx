import { useEffect, useRef, useState } from 'react'

import { ACTION_TEXT, CHOOSABLE, FAMILY_BG, familyOf, usd } from '../lib/format'
import type { Action, Proposal, QuoteFacts } from '../lib/types'
import { whatIf } from '../lib/whatif'
import { Button } from './Button'
import { MarginBar, type Scale } from './MarginBar'
import { Contact, CostChanges, LinesTable } from './QuoteParts'

/** The queue's shared columns: customer and action | moved cost | margin vs floor | at risk. */
export const QUEUE_COLS = 'md:grid-cols-[minmax(0,1.15fr)_minmax(0,1.25fr)_minmax(15rem,1fr)_7rem]'

type Review = (body: { verdict: 'approve' | 'edit' | 'reject'; action?: string; subject?: string; body?: string; note?: string }) => void

/** One quote Claude made a judgment call on. Closed: who, what we recommend,
 *  how much is at stake. Open: why, the numbers, and an editable draft. */
export function DecisionCard({ p, fresh, bar, scale, focused, k = 1, onReview, onViewQuote }: {
  p: Proposal & { facts: QuoteFacts }
  fresh: boolean
  /** Confidence bar from the scenario eval; report only, never acts. */
  bar: number | null
  /** The margin scale every card on screen shares. */
  scale?: Scale
  /** Focus mode (J/K): this card is the one being worked. */
  focused?: boolean
  /** What-if multiplier on the cost moves; display only. */
  k?: number
  onReview: Review
  onViewQuote: (quoteId: string) => void
}) {
  const f = p.facts
  const shown = whatIf(f, k)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!focused) return
    setOpen(true)
    ref.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }, [focused])
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
    <article
      ref={ref}
      className={`relative scroll-mt-32 border-t border-rule first:border-t-0 ${fresh ? 'mg-arrive' : ''} ${open ? 'bg-sheet-2/60' : ''} ${focused ? 'outline-2 -outline-offset-2 outline-attn' : ''}`}
    >
      {/* Catalogue thumb-index tab: the family of the material that moved. */}
      <span aria-hidden title={familyOf(f.material_id)} className={`absolute inset-y-0 left-0 w-1.5 ${FAMILY_BG[familyOf(f.material_id)] ?? FAMILY_BG.other}`} />
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className={`grid w-full grid-cols-[1fr_auto] items-center gap-x-6 gap-y-3 py-3.5 pl-6 pr-5 text-left hover:bg-sheet-2/40 ${QUEUE_COLS}`}>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-[15px] font-semibold text-ink-bright">{f.customer_name}</span>
            {f.customer_tier === 'key' ? (
              <span className="rounded-sm border border-rule-bright px-1.5 py-px font-label text-[12px] tracking-wider text-ink">KEY ACCOUNT</span>
            ) : null}
            {f.contract_note ? (
              <span className="rounded border border-attn/40 px-1.5 py-px font-label text-[12px] tracking-wider text-attn">CONTRACT NOTE</span>
            ) : null}
          </div>
          <p className={`mt-1 text-sm ${escalated ? 'text-stop' : 'text-ink-bright'}`}>{ACTION_TEXT[p.action].verb}</p>
          <p className="mt-0.5 whitespace-nowrap font-label text-[13px] text-ink-dim">{f.quote_id} · {usd(f.quote_value_usd)}</p>
        </div>
        <div className="col-span-2 min-w-0 md:col-span-1">
          <CostChanges f={f} />
        </div>
        <div className="col-span-2 md:col-span-1">
          <MarginBar before={shown.margin_before} after={shown.margin_after} floor={shown.margin_floor} scale={scale} />
        </div>
        <div className="row-start-1 text-right md:row-start-auto">
          <div className="font-label text-xl font-semibold text-ink-bright">{usd(shown.exposure_usd)}</div>
          <div className="font-label text-[12px] uppercase tracking-[0.08em] text-ink-dim">{k === 1 ? 'at risk' : `at risk if ×${k}`}</div>
        </div>
      </button>

      {open ? (
        <div className="space-y-5 border-t border-rule py-5 pl-6 pr-5">
          <div className="flex gap-3">
            <span className="mt-0.5 font-label text-[12px] uppercase tracking-wider text-claude">
              {escalated ? 'Error' : `Claude · ${Math.round((p.confidence ?? 0) * 100)}% sure`}
            </span>
            <p className="flex-1 text-sm leading-relaxed text-ink">{p.rationale}</p>
          </div>
          {bar != null && !escalated ? (
            <p className="font-label text-[12px] text-ink-dim">
              {(p.confidence ?? 0) >= bar
                ? `Clears the ${bar.toFixed(2)} confidence bar: in testing, every call this sure was right. You still approve it.`
                : `Below the ${bar.toFixed(2)} confidence bar: Claude is less sure than usual. Read this one carefully.`}
            </p>
          ) : null}

          {f.restated ? (
            <p className="rounded border border-rule-bright bg-sheet-2 px-3 py-2 text-sm text-ink">
              <span className="font-label text-[12px] uppercase tracking-wider text-ink-dim">Restated · </span>
              {f.restated.reason.replace(/^restated: the/, 'The')}. The numbers here include it.
            </p>
          ) : null}
          {f.contract_note ? (
            <p className="rounded border border-attn/30 bg-attn/4 px-3 py-2 text-sm text-ink">
              <span className="font-label text-[12px] uppercase tracking-wider text-attn">Contract note · </span>
              {f.contract_note}
            </p>
          ) : null}

          <LinesTable f={f} />
          <button type="button" onClick={() => onViewQuote(f.quote_id)} className="font-label text-[12px] text-ink-dim underline-offset-2 hover:text-ink hover:underline">
            View {f.quote_id} in Data
          </button>

          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-label text-[12px] uppercase tracking-wider text-ink-dim">Action</span>
              {CHOOSABLE.map((a) => (
                <button
                  key={a}
                  type="button"
                  onClick={() => setAction(a)}
                  className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                    action === a ? 'border-ink bg-ink/10 text-ink-bright' : 'border-rule text-ink-dim hover:border-rule-bright'
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
                  className="w-full rounded border border-rule bg-sheet-2 px-3 py-2 text-sm text-ink-bright outline-none focus:border-attn/70"
                />
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  rows={9}
                  className="w-full resize-y rounded border border-rule bg-sheet-2 px-3 py-2 text-sm leading-relaxed text-ink outline-none focus:border-attn/70"
                />
              </>
            ) : null}
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Note for the record (optional, but it teaches the system)"
              className="w-full rounded border border-rule bg-sheet-2 px-3 py-2 text-sm text-ink outline-none focus:border-rule-bright"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button tone="go" disabled={sending || escalated && !changed || needsDraft && !body.trim()} onClick={() => act(changed ? 'edit' : 'approve')}>
              {changed ? 'SAVE CHANGES & APPROVE' : 'APPROVE'}
            </Button>
            <Button tone="stop" disabled={sending} onClick={() => act('reject')}>REJECT</Button>
            <span className="ml-auto font-label text-[12px] text-ink-dim">
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
