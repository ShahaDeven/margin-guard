import { useEffect, useRef, useState } from 'react'

import type { Lane } from '../lib/api'
import { shortDate } from '../lib/format'
import type { DemoEmail, Email, FeedItem } from '../lib/types'
import { Attachments } from './Attachments'
import { Button } from './Button'

/** One line on what the email led to, e.g. "17 quotes checked, 5 need you". */
function Impact({ m }: { m: Email }) {
  if (!m.quotes_checked && m.alt_supplier_notes.length) {
    return <p className="mt-0.5 text-[13px] text-ink-dim">Alternate supplier, on file. Margins unchanged.</p>
  }
  if (!m.quotes_checked) return null
  return (
    <p className="mt-0.5 text-[13px] text-ink-dim">
      {m.quotes_checked} quote{m.quotes_checked === 1 ? '' : 's'} checked
      {m.needs_you ? <span className="text-attn">, {m.needs_you} need{m.needs_you === 1 ? 's' : ''} you</span> : null}
    </p>
  )
}

/** The way from an email to the decisions it created. */
function Jump({ m, onShowCards }: { m: Email; onShowCards: (emailId: string, lane: Lane) => void }) {
  const link = 'text-[13px] font-medium underline-offset-2 hover:underline'
  if (m.outcome === 'needs_review' && m.review_status === 'pending') {
    return (
      <button type="button" onClick={() => onShowCards(m.id, 'decide')} className={`${link} text-go`}>Answer it</button>
    )
  }
  if (!m.quotes_checked) return null
  return (
    <div className="flex gap-4">
      {m.needs_you ? (
        <button type="button" onClick={() => onShowCards(m.id, 'decide')} className={`${link} text-go`}>
          {m.needs_you} to decide
        </button>
      ) : null}
      {m.rule_pending ? (
        <button type="button" onClick={() => onShowCards(m.id, 'rules')} className={`${link} text-go`}>
          {m.rule_pending} settled by rules
        </button>
      ) : null}
      {!m.needs_you && !m.rule_pending ? (
        <button type="button" onClick={() => onShowCards(m.id, 'done')} className={`${link} text-go`}>All done</button>
      ) : null}
    </div>
  )
}

const OUTCOME: Record<string, { label: string; tone: string }> = {
  detected: { label: 'Price change', tone: 'text-ink-dim' },
  duplicate: { label: 'Already on file', tone: 'text-ink-dim' },
  needs_review: { label: 'Needs a look', tone: 'text-attn' },
  ignored: { label: 'Not a price change', tone: 'text-ink-dim' },
  error: { label: 'Could not read', tone: 'text-attn' },
}

/** The label reflects where the email stands now, not only how it was first read. */
function statusOf(m: Email): { label: string; tone: string } {
  // A failed read leaves no verdict, only status = 'error' (e.g. no API key).
  if (m.status === 'error') return OUTCOME.error
  if (m.outcome === 'needs_review' && m.review_status === 'approved') return { label: 'Resolved', tone: 'text-ink-dim' }
  if (m.outcome === 'needs_review' && m.review_status === 'rejected') return { label: 'Dismissed', tone: 'text-ink-dim' }
  if (m.outcome === 'detected' && !m.quotes_checked && m.alt_supplier_notes.length) return { label: 'Alternate supplier', tone: 'text-ink-dim' }
  return OUTCOME[m.outcome ?? ''] ?? { label: m.status === 'new' ? 'Reading…' : m.status, tone: 'text-ink-dim' }
}

/** The Supplier inbox lane: every supplier email, how it was read, and what it led to. */
export function InboxLane({ inbox, onShowCards }: {
  inbox: Email[]
  onShowCards: (emailId: string, lane: Lane) => void
}) {
  const [open, setOpen] = useState<string | null>(null)
  if (!inbox.length) return <p className="text-ink-dim">No supplier emails yet.</p>
  return (
    <ul className="divide-y divide-rule-soft overflow-hidden rounded-md border border-rule bg-sheet">
      {inbox.map((m) => {
        const o = statusOf(m)
        const waiting = m.outcome === 'needs_review' && m.review_status === 'pending'
        return (
          <li key={m.id}>
            <div className="flex flex-wrap items-start gap-x-6 gap-y-2 px-4 py-3.5">
              <button type="button" onClick={() => setOpen(open === m.id ? null : m.id)} aria-expanded={open === m.id}
                className="min-w-0 flex-1 text-left">
                <span className="font-semibold text-ink">{m.vendor_name ?? m.from_addr}</span>
                <span className="block truncate text-[13px] text-ink-dim">{m.subject}, {shortDate(m.received_at)}</span>
                <Impact m={m} />
              </button>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <span className={`text-[13px] font-medium ${waiting ? 'text-attn' : o.tone}`}>{o.label}</span>
                <Jump m={m} onShowCards={onShowCards} />
              </div>
            </div>
            <Attachments files={m.attachments} className="px-4 pb-3" />
            {open === m.id ? (
              <pre className="whitespace-pre-wrap border-t border-rule-soft bg-ground px-4 py-3 font-sans text-[13px] leading-relaxed text-ink">
                {m.body}
                {m.note ? `\n\n${m.note}` : ''}
                {m.alt_supplier_notes.map((n) => `\n\n${n}`).join('')}
                {m.review_note ? `\n\nYour review: ${m.review_note}` : ''}
              </pre>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}

const FEED_TONE: Record<FeedItem['tone'], string> = {
  info: 'text-ink',
  claude: 'text-ink',
  good: 'text-ink',
  attention: 'text-attn',
  fault: 'text-stop',
}

/** Everything that simulates the shop rather than runs it: the shop date and model, a
 *  pretend supplier email, and the agents' activity. Kept out of the working layout. */
export function DemoDrawer({ open, onClose, asOf, model, demoEmails, feed, busy, onSend }: {
  open: boolean
  onClose: () => void
  asOf: string | null
  model: string | null
  demoEmails: DemoEmail[]
  feed: FeedItem[]
  busy: boolean
  onSend: (demoId: string) => void
}) {
  const [demo, setDemo] = useState('')
  const panel = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!open) return
    panel.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null

  return (
    <div className="fixed inset-0 z-40">
      <div className="absolute inset-0 bg-ground/70" onClick={onClose} aria-hidden />
      <aside ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="demo-title"
        className="outline-none absolute inset-y-0 right-0 flex w-full max-w-md flex-col gap-6 overflow-y-auto border-l border-rule bg-sheet px-6 py-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="demo-title" className="text-xl font-bold text-ink">Demo controls</h2>
            <p className="mt-1 text-[13px] text-ink-dim">
              This is a sample shop with synthetic data. These controls pretend things are happening to it.
            </p>
          </div>
          <Button small onClick={onClose}>Close</Button>
        </div>

        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[13px]">
          <dt className="text-ink-dim">Shop date</dt><dd className="text-ink">{asOf ? shortDate(asOf) : ''}</dd>
          <dt className="text-ink-dim">Model</dt><dd className="text-ink">{model ?? ''}</dd>
        </dl>

        <section className="space-y-2">
          <h3 className="font-semibold text-ink">Send a test supplier email</h3>
          <p className="text-[13px] text-ink-dim">Pretends this email just arrived. The agents read it and update the queue live.</p>
          <select
            value={demo}
            onChange={(e) => setDemo(e.target.value)}
            aria-label="Test email"
            className="w-full rounded-sm border border-rule-bright bg-ground px-2.5 py-2 text-sm text-ink outline-none focus:border-go"
          >
            <option value="">Choose an email…</option>
            {demoEmails.map((d) => (
              <option key={d.id} value={d.id}>{d.label}</option>
            ))}
          </select>
          <Button disabled={!demo || busy} onClick={() => { onSend(demo); setDemo('') }}>
            {busy ? 'Agents working…' : 'Send test email'}
          </Button>
        </section>

        <section className="flex min-h-0 flex-col gap-2">
          <h3 className="flex items-center gap-2 font-semibold text-ink">
            Agent activity
            {busy ? <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-attn mg-breathe" /> : null}
          </h3>
          <ol className="space-y-1.5 rounded-sm bg-ground px-3 py-3" aria-live="polite">
            {feed.length ? feed.map((f) => (
              <li key={f.id} className="mg-arrive flex gap-2 text-[13px] leading-snug">
                <span className="shrink-0 text-ink-dim">{f.at}</span>
                <span className={FEED_TONE[f.tone]}>{f.text}</span>
              </li>
            )) : <li className="text-[13px] text-ink-dim">Quiet. Send a test email to watch the agents work.</li>}
          </ol>
        </section>
      </aside>
    </div>
  )
}
