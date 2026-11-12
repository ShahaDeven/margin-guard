import { useState } from 'react'

import { ACTION_TEXT, usd } from '../lib/format'
import type { OutboxItem, OutcomeBody, Proposal, QuoteFacts, ReviewFacts } from '../lib/types'
import { Button } from './Button'
import { MarginBar } from './MarginBar'
import { askedFor, CustomerRecordLine, OutcomeBadge, OutcomeControl } from './Outcomes'
import { Contact, CostChanges, LinesTable } from './QuoteParts'
import { Empty } from './RulesLane'

const STATUS_TONE: Record<string, string> = {
  approved: 'text-go border-go/40',
  edited: 'text-ink-bright border-rule-bright',
  rejected: 'text-stop border-stop/40',
}

/** The record: what each person decided next to what was proposed, plus what
 *  went out. Any row opens to the full detail and can be undone. */
export function DoneLane({ cards, outbox, onReopen, onViewQuote, onRecord, onUndoOutcome }: {
  cards: Proposal[]
  outbox: OutboxItem[]
  onReopen: (id: number) => void
  onViewQuote: (quoteId: string) => void
  onRecord: (proposalId: number, body: OutcomeBody) => void
  onUndoOutcome: (outcomeId: number) => void
}) {
  const [openId, setOpenId] = useState<number | null>(null)
  const [openMail, setOpenMail] = useState<number | null>(null)

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
      <section>
        <h3 className="mb-3 font-label text-[12px] uppercase tracking-wider text-ink-dim">Decisions</h3>
        {cards.length ? (
          <ul className="divide-y divide-rule rounded-sm border border-rule bg-sheet">
            {cards.map((p) => (
              <DoneRow key={p.id} p={p} open={openId === p.id} onToggle={() => setOpenId(openId === p.id ? null : p.id)} onReopen={() => onReopen(p.id)} onViewQuote={onViewQuote} onRecord={onRecord} onUndoOutcome={onUndoOutcome} />
            ))}
          </ul>
        ) : <Empty text="Nothing decided yet." />}
      </section>

      <section>
        <h3 className="mb-3 font-label text-[12px] uppercase tracking-wider text-ink-dim">Outbox (not really sent)</h3>
        {outbox.length ? (
          <ul className="space-y-3">
            {outbox.map((o) => {
              const open = openMail === o.id
              return (
                <li key={o.id} className={`rounded-sm border bg-sheet ${open ? 'border-rule-bright' : 'border-rule'}`}>
                  <button type="button" onClick={() => setOpenMail(open ? null : o.id)} className="w-full px-4 py-3 text-left">
                    <p className="font-label text-[12px] uppercase tracking-wider text-ink-dim">
                      {o.kind === 'customer_email' ? 'Email to' : 'Call task'} · {o.recipient}
                    </p>
                    <p className="mt-1 text-sm font-semibold text-ink-bright">{o.subject}</p>
                    <p className={`mt-1 whitespace-pre-wrap text-[13px] leading-relaxed text-ink ${open ? '' : 'line-clamp-3'}`}>{o.body}</p>
                    {!open ? <p className="mt-1 font-label text-[12px] text-ink-dim">click to read all</p> : null}
                  </button>
                </li>
              )
            })}
          </ul>
        ) : <Empty text="Approved emails and call tasks land here." />}
      </section>
    </div>
  )
}

function DoneRow({ p, open, onToggle, onReopen, onViewQuote, onRecord, onUndoOutcome }: {
  p: Proposal
  open: boolean
  onToggle: () => void
  onReopen: () => void
  onViewQuote: (quoteId: string) => void
  onRecord: (proposalId: number, body: OutcomeBody) => void
  onUndoOutcome: (outcomeId: number) => void
}) {
  const isQuote = p.kind === 'quote_action'
  const f = p.facts as QuoteFacts
  const label = isQuote ? `${p.quote_id} · ${f.customer_name}` : `Supplier email ${(p.facts as ReviewFacts).email_id}`
  const final = p.final_action ?? p.action
  const changedAction = p.final_action && p.final_action !== p.action
  const body = p.final_body ?? p.draft_body
  const subject = p.final_subject ?? p.draft_subject
  const rewrote = p.status === 'edited' && (p.final_body !== p.draft_body || p.final_subject !== p.draft_subject)
  // A reprice or a call asks the customer for money, so it has a response to record.
  const asksCustomer = isQuote && p.status !== 'rejected' && (final === 'reprice' || final === 'contact_customer')
  const awaiting = asksCustomer && !p.outcome

  return (
    <li>
      <button type="button" onClick={onToggle} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-left text-sm hover:bg-sheet-2">
        <span className={`rounded border px-1.5 py-px font-label text-[12px] uppercase tracking-wider ${STATUS_TONE[p.status] ?? ''}`}>{p.status}</span>
        <span className="text-ink">{label}</span>
        <span className="text-ink-dim">
          {changedAction
            ? <>proposed {ACTION_TEXT[p.action].short} → <span className="font-semibold text-ink-bright">{ACTION_TEXT[p.final_action!].short}</span></>
            : ACTION_TEXT[final].short}
        </span>
        {p.outcome ? <OutcomeBadge o={p.outcome} /> : awaiting ? <span className="font-label text-[12px] text-attn">waiting for the customer</span> : null}
        <span className="ml-auto font-label text-[12px] text-ink-dim">{p.decided_by === 'rule' ? 'rule' : p.decided_by === 'llm' ? 'Claude' : ''}</span>
        {p.reviewer_note ? <span className="w-full text-xs italic text-ink-dim">“{p.reviewer_note}”</span> : null}
      </button>

      {open ? (
        <div className="space-y-4 border-t border-rule bg-sheet-2/40 px-4 py-4">
          {isQuote ? (
            <>
              <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
                <div className="min-w-0 flex-1 text-xs"><CostChanges f={f} /></div>
                <div className="w-56"><MarginBar before={f.margin_before} after={f.margin_after} floor={f.margin_floor} /></div>
                <span className="font-label text-sm text-ink-bright">{usd(f.exposure_usd)} <span className="text-[12px] text-ink-dim">at risk</span></span>
              </div>
              <p className="text-sm leading-relaxed text-ink">
                <span className={`font-label text-[12px] uppercase tracking-wider ${p.decided_by === 'llm' ? 'text-claude' : 'text-ink-dim'}`}>
                  {p.decided_by === 'llm' ? `Claude · ${Math.round((p.confidence ?? 0) * 100)}% sure · ` : 'Rule · '}
                </span>
                {p.rationale}
              </p>
              {asksCustomer ? (
                <div className="space-y-2">
                  <OutcomeControl proposalId={p.id} asked={askedFor(f)} quoteId={f.quote_id} channel={final === 'reprice' ? 'email' : 'call'}
                    outcome={p.outcome} onRecord={onRecord} onUndo={onUndoOutcome} />
                  <CustomerRecordLine r={p.customer_record} name={f.customer_name} />
                </div>
              ) : null}
              <Contact f={f} action={final} />
              <LinesTable f={f} revisedLabel={
                // After a negotiation the quote holds the agreed prices, not these; the response box lists them.
                p.outcome?.outcome === 'negotiated' ? 'Asked'
                  : p.status !== 'rejected' && (final === 'reprice' || p.outcome?.outcome === 'accepted') ? 'Now' : 'Revised'} />
              {body ? (
                <div className="rounded border border-rule bg-sheet px-3 py-2">
                  <p className="font-label text-[12px] uppercase tracking-wider text-ink-dim">
                    {p.status === 'rejected' ? 'Draft (not sent)' : rewrote ? 'Message as rewritten by the reviewer' : 'Message as approved'}
                  </p>
                  <p className="mt-1 text-sm font-semibold text-ink-bright">{subject}</p>
                  <p className="mt-1 whitespace-pre-wrap text-[13px] leading-relaxed text-ink">{body}</p>
                </div>
              ) : null}
              {rewrote && p.draft_body ? (
                <details className="text-xs text-ink-dim">
                  <summary className="cursor-pointer font-label text-[12px] uppercase tracking-wider">Claude's original draft</summary>
                  <p className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed">{p.draft_body}</p>
                </details>
              ) : null}
              <div className="flex items-center gap-3">
                <Button tone="attn" small disabled={Boolean(p.outcome)} onClick={onReopen}>UNDO &amp; REVIEW AGAIN</Button>
                <Button small onClick={() => onViewQuote(f.quote_id)}>VIEW QUOTE</Button>
                <span className="font-label text-[12px] text-ink-dim">
                  {p.outcome
                    ? 'Undo the customer response first.'
                    : final === 'reprice' && p.status !== 'rejected'
                    ? 'Restores the original quote prices and withdraws the email.'
                    : 'Puts the card back in the queue.'}
                </span>
              </div>
            </>
          ) : (
            <p className="text-sm text-ink">{p.rationale}</p>
          )}
        </div>
      ) : null}
    </li>
  )
}
