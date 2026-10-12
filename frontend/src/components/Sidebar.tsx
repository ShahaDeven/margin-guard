import { useState } from 'react'

import type { Lane } from '../lib/api'
import type { DemoEmail, Email, FeedItem } from '../lib/types'
import { Button } from './Button'

/** One line on what the email led to, e.g. "17 quotes checked · 5 need you". */
function Impact({ m }: { m: Email }) {
  if (!m.quotes_checked) return null
  return (
    <p className="mt-0.5 font-mono text-[10px] text-silver-dim">
      → {m.quotes_checked} quote{m.quotes_checked === 1 ? '' : 's'} checked
      {m.needs_you ? <span className="text-hiviz"> · {m.needs_you} need{m.needs_you === 1 ? 's' : ''} you</span> : null}
    </p>
  )
}

/** The way from an email to the decisions it created. */
function Jump({ m, onShowCards }: { m: Email; onShowCards: (emailId: string, lane: Lane) => void }) {
  const link = 'font-mono text-[10px] tracking-wide underline-offset-2 hover:underline'
  if (m.outcome === 'needs_review' && m.review_status === 'pending') {
    return (
      <div className="px-4 pb-2.5">
        <button type="button" onClick={() => onShowCards(m.id, 'decide')} className={`${link} text-hiviz`}>
          ANSWER IT →
        </button>
      </div>
    )
  }
  if (!m.quotes_checked) return null
  return (
    <div className="flex gap-4 px-4 pb-2.5">
      {m.needs_you ? (
        <button type="button" onClick={() => onShowCards(m.id, 'decide')} className={`${link} text-hiviz`}>
          {m.needs_you} TO DECIDE →
        </button>
      ) : null}
      {m.rule_pending ? (
        <button type="button" onClick={() => onShowCards(m.id, 'rules')} className={`${link} text-silver-dim`}>
          {m.rule_pending} BY RULES →
        </button>
      ) : null}
      {!m.needs_you && !m.rule_pending ? (
        <button type="button" onClick={() => onShowCards(m.id, 'done')} className={`${link} text-silver-dim`}>
          ALL DONE →
        </button>
      ) : null}
    </div>
  )
}

const OUTCOME: Record<string, { label: string; tone: string }> = {
  detected: { label: 'price change', tone: 'text-cyan' },
  duplicate: { label: 'already on file', tone: 'text-silver-dim' },
  needs_review: { label: 'needs a look', tone: 'text-hiviz' },
  ignored: { label: 'not a price change', tone: 'text-silver-dim' },
  error: { label: 'could not read', tone: 'text-signal' },
}

/** The label reflects where the email stands now, not only how it was first read. */
function statusOf(m: Email): { label: string; tone: string } {
  // A failed read leaves no verdict, only status = 'error' (e.g. no API key).
  if (m.status === 'error') return OUTCOME.error
  if (m.outcome === 'needs_review' && m.review_status === 'approved') return { label: 'resolved', tone: 'text-cyan' }
  if (m.outcome === 'needs_review' && m.review_status === 'rejected') return { label: 'dismissed', tone: 'text-silver-dim' }
  return OUTCOME[m.outcome ?? ''] ?? { label: m.status === 'new' ? 'reading…' : m.status, tone: 'text-purple' }
}

const FEED_TONE: Record<FeedItem['tone'], string> = {
  info: 'text-silver',
  claude: 'text-purple',
  good: 'text-cyan',
  attention: 'text-hiviz',
  fault: 'text-signal',
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
    <aside className="flex flex-col gap-6">
      <section className="rounded-lg border border-line bg-panel">
        <header className="border-b border-line px-4 py-3">
          <h2 className="font-mono text-[11px] uppercase tracking-wider text-silver-dim">Supplier inbox</h2>
        </header>
        <div className="space-y-2 border-b border-line px-4 py-3">
          <select
            value={demo}
            onChange={(e) => setDemo(e.target.value)}
            className="w-full rounded border border-line bg-panel-2 px-2 py-1.5 text-sm text-silver outline-none focus:border-line-bright"
          >
            <option value="">Simulate a new supplier email…</option>
            {demoEmails.map((d) => (
              <option key={d.id} value={d.id}>{d.label}</option>
            ))}
          </select>
          <Button tone="purple" small disabled={!demo || busy} onClick={() => { onSend(demo); setDemo('') }}>
            {busy ? 'AGENTS WORKING…' : 'SEND TEST EMAIL'}
          </Button>
          <p className="text-[11px] leading-snug text-silver-dim">
            Pretends this supplier email just arrived. The agents read it and update the queue live.
          </p>
        </div>
        <ul className="max-h-112 divide-y divide-line overflow-auto">
          {inbox.map((m) => {
            const o = statusOf(m)
            const waiting = m.outcome === 'needs_review' && m.review_status === 'pending'
            return (
              <li key={m.id} className={waiting ? 'bg-hiviz/3' : ''}>
                <button type="button" onClick={() => setOpen(open === m.id ? null : m.id)} className="w-full px-4 py-2.5 text-left hover:bg-panel-2">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-[13px] text-silver-bright">{m.vendor_name ?? m.from_addr}</span>
                    <span className={`shrink-0 font-mono text-[10px] ${o.tone}`}>{o.label}</span>
                  </div>
                  <p className="truncate text-xs text-silver-dim">{m.id} · {m.subject}</p>
                  <Impact m={m} />
                </button>
                <Jump m={m} onShowCards={onShowCards} />
                {open === m.id ? (
                  <pre className="whitespace-pre-wrap border-t border-line/60 bg-panel-2 px-4 py-3 font-sans text-xs leading-relaxed text-silver">
                    {m.body}
                    {m.note ? `\n\n— ${m.note}` : ''}
                    {m.review_note ? `\n\n— Your review: ${m.review_note}` : ''}
                  </pre>
                ) : null}
              </li>
            )
          })}
        </ul>
      </section>

      <section className="rounded-lg border border-line bg-panel">
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="font-mono text-[11px] uppercase tracking-wider text-silver-dim">Agent activity</h2>
          {busy ? <span className="h-1.5 w-1.5 rounded-full bg-purple mg-breathe" /> : null}
        </header>
        <ol className="max-h-80 space-y-1.5 overflow-auto px-4 py-3">
          {feed.length ? feed.map((f) => (
            <li key={f.id} className="mg-arrive flex gap-2 text-xs leading-snug">
              <span className="shrink-0 font-mono text-[10px] text-silver-dim">{f.at}</span>
              <span className={FEED_TONE[f.tone]}>{f.text}</span>
            </li>
          )) : <li className="text-xs text-silver-dim">Quiet. Deliver a supplier email to watch the agents work.</li>}
        </ol>
      </section>
    </aside>
  )
}
