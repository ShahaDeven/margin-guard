import { useState } from 'react'

import { materialLabel, shortDate } from '../lib/format'
import type { Email, Material, Proposal, ReviewFacts } from '../lib/types'
import { Attachments } from './Attachments'
import { Button } from './Button'

/** A supplier email the system would not guess on. The person answers the one
 *  question it couldn't (which material?), or dismisses it. */
export function ReviewCard({
  p, email, materials, onResolve, onDismiss,
}: {
  p: Proposal
  email?: Email
  materials: Material[]
  onResolve: (materialId: string) => void
  onDismiss: () => void
}) {
  const f = p.facts as ReviewFacts
  const [sending, setSending] = useState(false)
  const candidates = f.match_candidates?.length ? f.match_candidates : []
  const canResolve = f.new_cost_per_lb != null && !!f.effective_date
  const name = (id: string) => materials.find((m) => m.id === id)?.name ?? materialLabel(id)

  return (
    <article className="rounded-sm border border-attn/50 bg-attn/3">
      <div className="space-y-4 px-5 py-4">
        <div>
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h2 className="text-[16px] font-semibold text-ink-bright">
              <span className="mr-2 rounded-sm bg-attn px-1.5 py-px align-[1px] font-label text-[12px] font-semibold text-ground">Needs a look</span>
              {email?.subject ?? p.event.email_subject}
            </h2>
            <span className="font-label text-[13px] text-ink-dim">{f.email_id} · {email?.vendor_name ?? email?.from_addr ?? 'unknown sender'}</span>
          </div>
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-ink marker:text-attn">
            {(f.review_reasons ?? []).map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
        {email ? (
          <details className="group">
            <summary className="inline-flex cursor-pointer select-none items-center gap-1.5 font-label text-[13px] font-semibold text-ink-dim hover:text-ink-bright">
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
                <Button key={id} tone="attn" disabled={sending} onClick={() => { setSending(true); onResolve(id) }}>
                  It's {name(id)}
                </Button>
              ))}
              <Button disabled={sending} onClick={() => { setSending(true); onDismiss() }}>Neither, dismiss</Button>
            </div>
            <p className="font-label text-[12px] text-ink-dim">Your answer becomes a price change, and the agents check every open quote that uses it.</p>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <Button disabled={sending} onClick={() => { setSending(true); onDismiss() }}>Noted, dismiss</Button>
            <span className="font-label text-[12px] text-ink-dim">No exact price and date to apply, so there's nothing for the agents to act on yet.</span>
          </div>
        )}
      </div>
    </article>
  )
}
