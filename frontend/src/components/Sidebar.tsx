import { useState } from 'react'

import type { Lane } from '../lib/api'
import type { DemoEmail, Email, FeedItem } from '../lib/types'
import { Attachments } from './Attachments'
import { Button } from './Button'

/** One line on what the email led to, e.g. "17 quotes checked · 5 need you". */
function Impact({ m }: { m: Email }) {
  if (!m.quotes_checked && m.alt_supplier_notes.length) {
    return <p className="mt-0.5 font-label text-[12px] text-ink-dim">Alternate supplier · on file, margins unchanged</p>
  }
  if (!m.quotes_checked) return null
  return (
    <p className="mt-0.5 font-label text-[12px] text-ink-dim">
      {m.quotes_checked} quote{m.quotes_checked === 1 ? '' : 's'} checked
      {m.needs_you ? <span className="text-attn"> · {m.needs_you} need{m.needs_you === 1 ? 's' : ''} you</span> : null}
    </p>
  )
}

/** The way from an email to the decisions it created. */
function Jump({ m, onShowCards }: { m: Email; onShowCards: (emailId: string, lane: Lane) => void }) {
  const link = 'font-label text-[12px] tracking-wide underline-offset-2 hover:underline'
  if (m.outcome === 'needs_review' && m.review_status === 'pending') {
    return (
      <div className="px-4 pb-2.5">
        <button type="button" onClick={() => onShowCards(m.id, 'decide')} className={`${link} text-attn`}>
          ANSWER IT
        </button>
      </div>
    )
  }
  if (!m.quotes_checked) return null
  return (
    <div className="flex gap-4 px-4 pb-2.5">
      {m.needs_you ? (
        <button type="button" onClick={() => onShowCards(m.id, 'decide')} className={`${link} text-attn`}>
          {m.needs_you} TO DECIDE
        </button>
      ) : null}
      {m.rule_pending ? (
        <button type="button" onClick={() => onShowCards(m.id, 'rules')} className={`${link} text-ink-dim`}>
          {m.rule_pending} BY RULES
        </button>
      ) : null}
      {!m.needs_you && !m.rule_pending ? (
        <button type="button" onClick={() => onShowCards(m.id, 'done')} className={`${link} text-ink-dim`}>
          ALL DONE
        </button>
      ) : null}
    </div>
  )
}

const OUTCOME: Record<string, { label: string; tone: string }> = {
  detected: { label: 'price change', tone: 'text-go' },
  duplicate: { label: 'already on file', tone: 'text-ink-dim' },
  needs_review: { label: 'needs a look', tone: 'text-attn' },
  ignored: { label: 'not a price change', tone: 'text-ink-dim' },
  error: { label: 'could not read', tone: 'text-stop' },
}

/** The label reflects where the email stands now, not only how it was first read. */
function statusOf(m: Email): { label: string; tone: string } {
  // A failed read leaves no verdict, only status = 'error' (e.g. no API key).
  if (m.status === 'error') return OUTCOME.error
  if (m.outcome === 'needs_review' && m.review_status === 'approved') return { label: 'resolved', tone: 'text-go' }
  if (m.outcome === 'needs_review' && m.review_status === 'rejected') return { label: 'dismissed', tone: 'text-ink-dim' }
  if (m.outcome === 'detected' && !m.quotes_checked && m.alt_supplier_notes.length) return { label: 'alt supplier', tone: 'text-ink' }
  return OUTCOME[m.outcome ?? ''] ?? { label: m.status === 'new' ? 'reading…' : m.status, tone: 'text-claude' }
}

const FEED_TONE: Record<FeedItem['tone'], string> = {
  info: 'text-ink',
  claude: 'text-claude',
  good: 'text-go',
  attention: 'text-attn',
  fault: 'text-stop',
}

export function Sidebar({
  inbox, demoEmails, feed, busy, onSend, onShowCards,
}: {
  inbox: Email[]
  demoEmails: DemoEmail[]
  feed: FeedItem[]
  busy: boolean
  onSend: (demoId: string) => void
  onShowCards: (emailId: string, lane: Lane) => void
}) {
  const [demo, setDemo] = useState('')
  const [open, setOpen] = useState<string | null>(null)

  return (
    <aside className="flex flex-col gap-6 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)]">
      <section className="flex min-h-0 flex-col rounded-sm border border-rule bg-sheet lg:flex-1">
        <header className="flex items-baseline justify-between border-b border-rule px-4 py-3">
          <h2 className="font-label text-[12px] uppercase tracking-wider text-ink-dim">Supplier inbox</h2>
          <span className="font-label text-[12px] text-ink-dim">{inbox.length} emails · scroll for all</span>
        </header>
        <div className="space-y-2 border-b border-rule px-4 py-3">
          <select
            value={demo}
            onChange={(e) => setDemo(e.target.value)}
            className="w-full rounded border border-rule bg-sheet-2 px-2 py-1.5 text-sm text-ink outline-none focus:border-rule-bright"
          >
            <option value="">Simulate a new supplier email…</option>
            {demoEmails.map((d) => (
              <option key={d.id} value={d.id}>{d.label}</option>
            ))}
          </select>
          <Button tone="claude" small disabled={!demo || busy} onClick={() => { onSend(demo); setDemo('') }}>
            {busy ? 'AGENTS WORKING…' : 'SEND TEST EMAIL'}
          </Button>
          <p className="text-[12px] leading-snug text-ink-dim">
            Pretends this supplier email just arrived. The agents read it and update the queue live.
          </p>
        </div>
        <ul className="max-h-112 divide-y divide-rule overflow-auto pb-6 [mask-image:linear-gradient(to_bottom,black_calc(100%-2.5rem),transparent)] lg:max-h-none lg:min-h-0 lg:flex-1">
          {inbox.map((m) => {
            const o = statusOf(m)
            const waiting = m.outcome === 'needs_review' && m.review_status === 'pending'
            return (
              <li key={m.id} className={waiting ? 'bg-attn/3' : ''}>
                <button type="button" onClick={() => setOpen(open === m.id ? null : m.id)} className="w-full px-4 py-2.5 text-left hover:bg-sheet-2">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-[13px] text-ink-bright">{m.vendor_name ?? m.from_addr}</span>
                    <span className={`shrink-0 font-label text-[12px] ${o.tone}`}>{o.label}</span>
                  </div>
                  <p className="truncate text-xs text-ink-dim">{m.id} · {m.subject}</p>
                  <Impact m={m} />
                </button>
                <Attachments files={m.attachments} className="px-4 pb-2" />
                <Jump m={m} onShowCards={onShowCards} />
                {open === m.id ? (
                  <pre className="whitespace-pre-wrap border-t border-rule/60 bg-sheet-2 px-4 py-3 font-sans text-xs leading-relaxed text-ink">
                    {m.body}
                    {m.note ? `\n\n— ${m.note}` : ''}
                    {m.alt_supplier_notes.map((n) => `\n\n— ${n}`).join('')}
                    {m.review_note ? `\n\n— Your review: ${m.review_note}` : ''}
                  </pre>
                ) : null}
              </li>
            )
          })}
        </ul>
      </section>

      <section className="rounded-sm border border-rule bg-sheet">
        <header className="flex items-center justify-between border-b border-rule px-4 py-3">
          <h2 className="font-label text-[12px] uppercase tracking-wider text-ink-dim">Agent activity</h2>
          {busy ? <span className="h-1.5 w-1.5 rounded-full bg-claude mg-breathe" /> : null}
        </header>
        <ol className="max-h-56 space-y-1.5 overflow-auto px-4 py-3">
          {feed.length ? feed.map((f) => (
            <li key={f.id} className="mg-arrive flex gap-2 text-xs leading-snug">
              <span className="shrink-0 font-label text-[12px] text-ink-dim">{f.at}</span>
              <span className={FEED_TONE[f.tone]}>{f.text}</span>
            </li>
          )) : <li className="text-xs text-ink-dim">Quiet. Deliver a supplier email to watch the agents work.</li>}
        </ol>
      </section>
    </aside>
  )
}
