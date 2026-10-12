import { useState } from 'react'

import { materialLabel, shortDate } from '../lib/format'
import type { Email, Material, Proposal, ReviewFacts } from '../lib/types'
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
    <article className="rounded-lg border border-hiviz/40 bg-hiviz/[0.03]">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-hiviz/15 px-5 py-3">
        <div className="flex items-center gap-2.5">
          <span className="h-1.5 w-1.5 rounded-full bg-hiviz mg-breathe" />
          <span className="font-mono text-[11px] font-semibold tracking-wider text-hiviz">SUPPLIER EMAIL NEEDS A LOOK</span>
        </div>
        <span className="font-mono text-[11px] text-silver-dim">{f.email_id} · {email?.vendor_name ?? email?.from_addr ?? 'unknown sender'}</span>
      </div>
      <div className="space-y-4 px-5 py-4">
        <div>
          <p className="text-[15px] font-semibold text-silver-bright">{email?.subject ?? p.event.email_subject}</p>
          <ul className="mt-1.5 space-y-0.5 text-sm text-silver">
            {(f.review_reasons ?? []).map((r) => (
              <li key={r}>· {r}</li>
            ))}
          </ul>
        </div>
        {email ? (
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded border border-line bg-panel px-3 py-2 font-sans text-[13px] leading-relaxed text-silver">
            {email.body}
          </pre>
        ) : null}

        {canResolve && candidates.length ? (
          <div className="space-y-2">
            <p className="text-sm text-silver">
              ${f.new_cost_per_lb?.toFixed(2)}/lb from {shortDate(f.effective_date)}. Which material is "{f.material_text}"?
            </p>
            <div className="flex flex-wrap gap-2">
              {candidates.map((id) => (
                <Button key={id} tone="hiviz" disabled={sending} onClick={() => { setSending(true); onResolve(id) }}>
                  It's {name(id)}
                </Button>
              ))}
              <Button disabled={sending} onClick={() => { setSending(true); onDismiss() }}>Neither, dismiss</Button>
            </div>
            <p className="font-mono text-[10px] text-silver-dim">Your answer becomes a price change, and the agents check every open quote that uses it.</p>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <Button disabled={sending} onClick={() => { setSending(true); onDismiss() }}>Noted, dismiss</Button>
            <span className="font-mono text-[10px] text-silver-dim">No exact price and date to apply, so there's nothing for the agents to act on yet.</span>
          </div>
        )}
      </div>
    </article>
  )
}
