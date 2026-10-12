import { useState } from 'react'

import { ACTION_TEXT, usd } from '../lib/format'
import type { OutboxItem, Proposal, QuoteFacts, ReviewFacts } from '../lib/types'
import { Button } from './Button'
import { MarginBar } from './MarginBar'
import { Contact, CostChanges, LinesTable } from './QuoteParts'
import { Empty } from './RulesLane'

const STATUS_TONE: Record<string, string> = {
  approved: 'text-cyan border-cyan/40',
  edited: 'text-purple border-purple/40',
  rejected: 'text-signal border-signal/40',
}

/** The record: what each person decided next to what was proposed, plus what
 *  went out. Any row opens to the full detail and can be undone. */
export function DoneLane({ cards, outbox, onReopen, onViewQuote }: {
  cards: Proposal[]
  outbox: OutboxItem[]
  onReopen: (id: number) => void
  onViewQuote: (quoteId: string) => void
}) {
  const [openId, setOpenId] = useState<number | null>(null)
  const [openMail, setOpenMail] = useState<number | null>(null)

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
      <section>
        <h3 className="mb-3 font-mono text-[11px] uppercase tracking-wider text-silver-dim">Decisions</h3>
        {cards.length ? (
          <ul className="divide-y divide-line rounded-lg border border-line bg-panel">
            {cards.map((p) => (
              <DoneRow key={p.id} p={p} open={openId === p.id} onToggle={() => setOpenId(openId === p.id ? null : p.id)} onReopen={() => onReopen(p.id)} onViewQuote={onViewQuote} />
            ))}
          </ul>
        ) : <Empty text="Nothing decided yet." />}
      </section>

      <section>
        <h3 className="mb-3 font-mono text-[11px] uppercase tracking-wider text-silver-dim">Outbox (not really sent)</h3>
        {outbox.length ? (
          <ul className="space-y-3">
            {outbox.map((o) => {
              const open = openMail === o.id
              return (
                <li key={o.id} className={`rounded-lg border bg-panel ${open ? 'border-line-bright' : 'border-line'}`}>
                  <button type="button" onClick={() => setOpenMail(open ? null : o.id)} className="w-full px-4 py-3 text-left">
                    <p className="font-mono text-[10px] uppercase tracking-wider text-silver-dim">
                      {o.kind === 'customer_email' ? 'Email to' : 'Call task'} · {o.recipient}
                    </p>
                    <p className="mt-1 text-sm font-semibold text-silver-bright">{o.subject}</p>
                    <p className={`mt-1 whitespace-pre-wrap text-[13px] leading-relaxed text-silver ${open ? '' : 'line-clamp-3'}`}>{o.body}</p>
                    {!open ? <p className="mt-1 font-mono text-[10px] text-silver-dim">click to read all</p> : null}
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

function DoneRow({ p, open, onToggle, onReopen, onViewQuote }: {
  p: Proposal
  open: boolean
  onToggle: () => void
  onReopen: () => void
  onViewQuote: (quoteId: string) => void
}) {
  const isQuote = p.kind === 'quote_action'
  const f = p.facts as QuoteFacts
  const label = isQuote ? `${p.quote_id} · ${f.customer_name}` : `Supplier email ${(p.facts as ReviewFacts).email_id}`
  const final = p.final_action ?? p.action
  const changedAction = p.final_action && p.final_action !== p.action
  const body = p.final_body ?? p.draft_body
  const subject = p.final_subject ?? p.draft_subject
  const rewrote = p.status === 'edited' && (p.final_body !== p.draft_body || p.final_subject !== p.draft_subject)

  return (
    <li>
      <button type="button" onClick={onToggle} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-left text-sm hover:bg-panel-2">
        <span className={`rounded border px-1.5 py-px font-mono text-[10px] uppercase tracking-wider ${STATUS_TONE[p.status] ?? ''}`}>{p.status}</span>
        <span className="text-silver">{label}</span>
        <span className="text-silver-dim">
          {changedAction
            ? <>proposed {ACTION_TEXT[p.action].short} → <span className="text-purple">{ACTION_TEXT[p.final_action!].short}</span></>
            : ACTION_TEXT[final].short}
        </span>
        <span className="ml-auto font-mono text-[10px] text-silver-dim">{p.decided_by === 'rule' ? 'rule' : p.decided_by === 'llm' ? 'Claude' : ''}</span>
        {p.reviewer_note ? <span className="w-full text-xs italic text-silver-dim">“{p.reviewer_note}”</span> : null}
      </button>

      {open ? (
        <div className="space-y-4 border-t border-line bg-panel-2/40 px-4 py-4">
          {isQuote ? (
            <>
              <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
                <div className="min-w-0 flex-1 text-xs"><CostChanges f={f} /></div>
                <div className="w-56"><MarginBar before={f.margin_before} after={f.margin_after} floor={f.margin_floor} /></div>
                <span className="font-mono text-sm text-silver-bright">{usd(f.exposure_usd)} <span className="text-[10px] text-silver-dim">at risk</span></span>
              </div>
              <p className="text-sm leading-relaxed text-silver">
                <span className="font-mono text-[10px] uppercase tracking-wider text-purple">
                  {p.decided_by === 'llm' ? `Claude · ${Math.round((p.confidence ?? 0) * 100)}% sure · ` : 'Rule · '}
                </span>
                {p.rationale}
              </p>
              <Contact f={f} action={final} />
              <LinesTable f={f} revisedLabel={final === 'reprice' && p.status !== 'rejected' ? 'Now' : 'Revised'} />
              {body ? (
                <div className="rounded border border-line bg-panel px-3 py-2">
                  <p className="font-mono text-[10px] uppercase tracking-wider text-silver-dim">
                    {p.status === 'rejected' ? 'Draft (not sent)' : rewrote ? 'Message as rewritten by the reviewer' : 'Message as approved'}
                  </p>
                  <p className="mt-1 text-sm font-semibold text-silver-bright">{subject}</p>
                  <p className="mt-1 whitespace-pre-wrap text-[13px] leading-relaxed text-silver">{body}</p>
                </div>
              ) : null}
              {rewrote && p.draft_body ? (
                <details className="text-xs text-silver-dim">
                  <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-wider">Claude's original draft</summary>
                  <p className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed">{p.draft_body}</p>
                </details>
              ) : null}
              <div className="flex items-center gap-3">
                <Button tone="hiviz" small onClick={onReopen}>UNDO &amp; REVIEW AGAIN</Button>
                <Button small onClick={() => onViewQuote(f.quote_id)}>VIEW QUOTE</Button>
                <span className="font-mono text-[10px] text-silver-dim">
                  {final === 'reprice' && p.status !== 'rejected'
                    ? 'Restores the original quote prices and withdraws the email.'
                    : 'Puts the card back in the queue.'}
                </span>
              </div>
            </>
          ) : (
            <p className="text-sm text-silver">{p.rationale}</p>
          )}
        </div>
      ) : null}
    </li>
  )
}
