import { useEffect, useState } from 'react'

import { api } from '../lib/api'
import { pct, shortDate, unitPrice, usd } from '../lib/format'
import type { CustomerRecord, Outcome, OutcomeBody, OutcomeKind, OutcomesSummary, OutcomeTally, QuoteFacts } from '../lib/types'
import { Button } from './Button'
import { Empty } from './RulesLane'

const head = 'pb-2 font-label text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-dim'
const link = 'font-label text-[13px] font-semibold text-ink-dim underline-offset-2 hover:text-ink-bright hover:underline'

/** The increase a decision asked for over the whole quote (same sum as outcomes.asked on the server). */
export const askedFor = (f: QuoteFacts) =>
  Math.round(f.lines.reduce((s, l) => s + (l.proposed_unit_price - l.unit_price) * l.qty, 0) * 100) / 100

export const OUTCOME_TEXT: Record<OutcomeKind, { label: string; tone: string }> = {
  accepted: { label: 'Accepted', tone: 'text-go border-go/40' },
  negotiated: { label: 'Negotiated', tone: 'text-attn border-attn/40' },
  lost: { label: 'Lost the job', tone: 'text-stop border-stop/40' },
}

export function OutcomeBadge({ o }: { o: Outcome }) {
  const t = OUTCOME_TEXT[o.outcome]
  return <span className={`rounded border px-1.5 py-px font-label text-[12px] uppercase tracking-wider ${t.tone}`}>{t.label}</span>
}

/** One line on a decision card: how this customer has taken increases before. People read it; the model never sees it. */
export function CustomerRecordLine({ r, name }: { r: CustomerRecord | null | undefined; name: string }) {
  if (!r) {
    return (
      <p className="text-[13px] text-ink-dim">
        <span className="font-label text-[12px] uppercase tracking-wider">Customer record · </span>
        No past increases on record for {name}.
      </p>
    )
  }
  const parts = [
    r.accepted ? `${r.accepted} accepted` : '',
    r.negotiated ? `${r.negotiated} negotiated down` : '',
    r.lost ? `${r.lost} lost the job` : '',
  ].filter(Boolean)
  const tone = r.pattern.startsWith('has walked') ? 'text-stop' : r.pattern.includes('pushes back') ? 'text-attn' : 'text-ink-bright'
  return (
    <p className="text-[13px] text-ink">
      <span className="font-label text-[12px] uppercase tracking-wider text-ink-dim">Customer record · </span>
      {r.requests} past increase{r.requests === 1 ? '' : 's'}: {parts.join(', ')}
      {r.kept != null && r.negotiated ? <> (kept {pct(r.kept, 0)} of what was asked)</> : null}
      {' · '}<span className={`font-semibold ${tone}`}>{r.pattern}</span>
      <span className="text-ink-dim"> · last {OUTCOME_TEXT[r.last.outcome].label.toLowerCase()} {shortDate(r.last.date)}</span>
    </p>
  )
}

/** Record what the customer did after an approved reprice or call, or show it with an undo. */
export function OutcomeControl({ proposalId, asked, quoteId, channel, outcome, onRecord, onUndo }: {
  proposalId: number
  asked: number
  quoteId: string
  channel: 'email' | 'call'
  outcome: Outcome | null | undefined
  onRecord: (proposalId: number, body: OutcomeBody) => void
  onUndo: (outcomeId: number) => void
}) {
  const [mode, setMode] = useState<null | 'negotiated' | 'lost'>(null)
  const [amount, setAmount] = useState('')

  if (outcome) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded border border-rule bg-sheet px-3 py-2 text-sm">
        <span className="font-label text-[12px] uppercase tracking-wider text-ink-dim">Customer response</span>
        <OutcomeBadge o={outcome} />
        <span className="text-ink">
          {outcome.outcome === 'lost'
            ? <>{quoteId} marked lost on {shortDate(outcome.outcome_date)}: {usd(outcome.lost_revenue_usd)} of revenue</>
            : <>kept {usd(outcome.recovered_usd, 2)} of the {usd(outcome.asked_usd, 2)} asked, {shortDate(outcome.outcome_date)}
              {outcome.price_changes.length ? <span className="text-ink-dim">
                {' · '}quote price{outcome.price_changes.length === 1 ? '' : 's'} now {outcome.outcome === 'negotiated' ? 'agreed at' : 'at'}{' '}
                {outcome.price_changes.map((c) => unitPrice(c.after)).join(', ')}
              </span> : null}</>}
        </span>
        <span className="ml-auto"><Button small onClick={() => onUndo(outcome.id)}>Undo response</Button></span>
      </div>
    )
  }

  const value = Number(amount)
  const validAmount = amount.trim() !== '' && value > 0 && value < asked
  return (
    <div className="space-y-2 rounded border border-attn/40 bg-attn/5 px-3 py-2.5 text-sm">
      <p className="text-ink-bright">
        What did the customer say to the {usd(asked, 2)} increase{channel === 'call' ? ' on the call' : ''}?
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button small tone="go" onClick={() => onRecord(proposalId, { outcome: 'accepted' })}>Accepted</Button>
        <Button small tone="attn" onClick={() => setMode(mode === 'negotiated' ? null : 'negotiated')}>Negotiated</Button>
        <Button small tone="stop" onClick={() => setMode(mode === 'lost' ? null : 'lost')}>Lost the job</Button>
      </div>
      {mode === null ? (
        <p className="text-xs text-ink-dim">
          {channel === 'call'
            ? 'Accepted or negotiated writes the agreed prices to the quote. Every response can be undone.'
            : 'The revised prices are already on the quote; negotiated lowers them to what was agreed. Every response can be undone.'}
        </p>
      ) : null}
      {mode === 'negotiated' ? (
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-ink" htmlFor={`agreed-${proposalId}`}>They agreed to $</label>
          <input
            id={`agreed-${proposalId}`}
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ''))}
            className="w-28 rounded border border-rule bg-sheet-2 px-2 py-1 font-label text-ink-bright outline-none focus:border-attn/70"
          />
          <span className="text-ink-dim">of the {usd(asked, 2)}{validAmount ? ` (${pct(value / asked, 0)})` : ''}</span>
          <Button small tone="attn" disabled={!validAmount} onClick={() => { onRecord(proposalId, { outcome: 'negotiated', recovered_usd: amount }); setMode(null) }}>
            Save
          </Button>
          <span className="w-full text-xs text-ink-dim">Each line moves by the same share of its increase.</span>
        </div>
      ) : null}
      {mode === 'lost' ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-ink">Mark {quoteId} as lost? It leaves the open quotes, so later price changes skip it.</span>
          <Button small tone="stop" onClick={() => { onRecord(proposalId, { outcome: 'lost' }); setMode(null) }}>Mark lost</Button>
          <Button small onClick={() => setMode(null)}>Cancel</Button>
        </div>
      ) : null}
    </div>
  )
}

type Scope = 'all' | 'console' | 'history'
const SCOPES: { id: Scope; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'console', label: 'Since Margin Guard' },
  { id: 'history', label: 'Before (history)' },
]

/** The owner's view of what happened after increases went out. Every figure is a sum over recorded responses. */
export function OutcomesLane({ version, onViewQuote, onRecord, onUndo }: {
  version: number
  onViewQuote: (quoteId: string) => void
  onRecord: (proposalId: number, body: OutcomeBody) => void
  onUndo: (outcomeId: number) => void
}) {
  const [s, setS] = useState<OutcomesSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [scope, setScope] = useState<Scope>('all')
  const [open, setOpen] = useState<number | null>(null)

  useEffect(() => {
    api.outcomes().then((r) => { setS(r); setError(null) }).catch((e) => setError(String(e)))
  }, [version])

  if (error) return <Empty text={`Could not load outcomes: ${error}`} />
  if (!s) return <Empty text="Loading outcomes…" />
  const t: OutcomeTally = s[scope]
  const recent = s.recent.filter((o) => scope === 'all' || o.source === scope)

  return (
    <div className="space-y-6">
      <section className="rounded-sm border border-rule bg-sheet px-6 py-5">
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Which responses to count">
          {SCOPES.map((x) => (
            <button
              key={x.id}
              type="button"
              aria-pressed={scope === x.id}
              onClick={() => setScope(x.id)}
              className={`rounded-sm border px-2.5 py-0.5 font-label text-[13px] transition-colors ${
                scope === x.id ? 'border-attn bg-attn/15 text-ink-bright' : 'border-rule-bright text-ink-dim hover:text-ink'
              }`}
            >
              {x.label} <span className="text-ink-dim">{s[x.id].requests}</span>
            </button>
          ))}
        </div>
        {t.requests ? (
          <>
            <h2 className="mt-4 font-label text-2xl font-semibold text-ink-bright">
              {usd(t.recovered_usd)} recovered of {usd(t.asked_kept_jobs_usd)} asked on the jobs kept
              {t.kept != null ? <span className="text-go"> · {pct(t.kept, 0)}</span> : null}
            </h2>
            <p className="mt-1 max-w-3xl text-[15px] leading-relaxed text-ink">
              {t.requests} increase{t.requests === 1 ? '' : 's'} with a response: {t.accepted} accepted, {t.negotiated} negotiated
              down, and {t.lost} where the customer walked,{' '}
              <span className={t.lost ? 'font-semibold text-stop' : ''}>{usd(t.lost_revenue_usd)} of revenue</span> on those quotes.
            </p>
          </>
        ) : (
          <p className="mt-4 text-[15px] text-ink">No responses recorded {scope === 'console' ? 'since Margin Guard' : 'here'} yet.</p>
        )}
        <p className="mt-3 text-xs text-ink-dim">
          "Kept" counts only the jobs the customer stayed on; a lost job's cost is its revenue, shown on its own. History is the
          shop's record from before Margin Guard (synthetic in the demo). Responses are shown to people next to each decision and
          are never given to the model.
        </p>
      </section>

      <section className="rounded-sm border border-rule bg-sheet px-5 py-4">
        <h3 className="font-label text-lg font-semibold text-ink-bright">Waiting for the customer</h3>
        <p className="mb-3 text-xs text-ink-dim">Approved reprices and calls with no response recorded. Click one to record it.</p>
        {s.awaiting.length ? (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left">
                <th className={head}>Quote</th><th className={head}>Customer</th><th className={head}>Sent as</th>
                <th className={`${head} text-right`}>Increase asked</th><th className={`${head} pl-4`}>Approved</th>
              </tr>
            </thead>
            <tbody>
              {s.awaiting.map((a) => (
                <WaitingRow key={a.proposal_id} a={a} open={open === a.proposal_id}
                  record={s.customers.find((c) => c.customer_id === a.customer_id)}
                  onToggle={() => setOpen(open === a.proposal_id ? null : a.proposal_id)}
                  onViewQuote={onViewQuote} onRecord={onRecord} onUndo={onUndo} />
              ))}
            </tbody>
          </table>
        ) : <p className="text-sm text-ink-dim">Nothing waiting. Approve a reprice or a call in Decide and it shows up here.</p>}
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <section className="rounded-sm border border-rule bg-sheet px-5 py-4">
          <h3 className="font-label text-lg font-semibold text-ink-bright">By customer</h3>
          <p className="mb-3 text-xs text-ink-dim">All responses, history included: this is the record each decision card shows.</p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left">
                <th className={head}>Customer</th>
                <th className={`${head} text-right`}>Increases</th>
                <th className={`${head} text-right`} title="accepted / negotiated / lost">Acc · Neg · Lost</th>
                <th className={`${head} text-right`}>Kept</th>
                <th className={`${head} pl-4`}>Pattern</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {s.customers.map((c) => (
                <tr key={c.customer_id}>
                  <td className="py-1.5 text-ink-bright">{c.customer_name}</td>
                  <td className="py-1.5 text-right font-label text-ink">{c.requests}</td>
                  <td className="py-1.5 text-right font-label text-ink">
                    <span className="text-go">{c.accepted}</span> · <span className="text-attn">{c.negotiated}</span> · <span className="text-stop">{c.lost}</span>
                  </td>
                  <td className="py-1.5 text-right font-label text-ink">{c.kept != null ? pct(c.kept, 0) : '–'}</td>
                  <td className={`py-1.5 pl-4 text-[13px] ${c.pattern.startsWith('has walked') ? 'text-stop' : c.pattern.includes('pushes') ? 'text-attn' : 'text-ink-dim'}`}>{c.pattern}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="rounded-sm border border-rule bg-sheet px-5 py-4">
          <h3 className="font-label text-lg font-semibold text-ink-bright">Responses</h3>
          <p className="mb-3 text-xs text-ink-dim">Newest first. {scope === 'all' ? 'History rows are marked.' : ''}</p>
          {recent.length ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left">
                  <th className={head}>Date</th><th className={head}>Quote · customer</th><th className={head}>Response</th>
                  <th className={`${head} text-right`}>Kept / lost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rule">
                {recent.slice(0, 40).map((o) => (
                  <tr key={o.id}>
                    <td className="py-1.5 pr-3 font-label text-ink-dim">{shortDate(o.outcome_date)}</td>
                    <td className="py-1.5 pr-3">
                      <button type="button" className={link} onClick={() => onViewQuote(o.quote_id)}>{o.quote_id}</button>
                      <span className="text-ink"> · {o.customer_name}</span>
                      {o.source === 'history' ? <span className="ml-2 font-label text-[11px] uppercase tracking-wider text-ink-dim">history</span> : null}
                    </td>
                    <td className="py-1.5 pr-3"><OutcomeBadge o={o} /></td>
                    <td className="py-1.5 text-right font-label">
                      {o.outcome === 'lost'
                        ? <span className="text-stop">{usd(o.lost_revenue_usd)}</span>
                        : <span className="text-ink">{usd(o.recovered_usd)} <span className="text-ink-dim">of {usd(o.asked_usd)}</span></span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="text-sm text-ink-dim">None yet.</p>}
        </section>
      </div>
    </div>
  )
}

function WaitingRow({ a, open, record, onToggle, onViewQuote, onRecord, onUndo }: {
  a: OutcomesSummary['awaiting'][number]
  open: boolean
  record: CustomerRecord | undefined
  onToggle: () => void
  onViewQuote: (quoteId: string) => void
  onRecord: (proposalId: number, body: OutcomeBody) => void
  onUndo: (outcomeId: number) => void
}) {
  return (
    <>
      <tr className="cursor-pointer border-t border-rule hover:bg-sheet-2" onClick={onToggle}>
        <td className="py-2 pr-3 font-label text-ink-bright">{a.quote_id}</td>
        <td className="py-2 pr-3 text-ink">{a.customer_name}</td>
        <td className="py-2 pr-3 text-ink-dim">{a.channel === 'call' ? 'Call' : 'Email'}</td>
        <td className="py-2 text-right font-label text-ink-bright">{usd(a.asked_usd, 2)}</td>
        <td className="py-2 pl-4 font-label text-ink-dim">{a.reviewed_at ? shortDate(a.reviewed_at) : ''}</td>
      </tr>
      {open ? (
        <tr>
          <td colSpan={5} className="space-y-2 pb-3">
            <CustomerRecordLine r={record} name={a.customer_name} />
            <OutcomeControl proposalId={a.proposal_id} asked={a.asked_usd} quoteId={a.quote_id} channel={a.channel}
              outcome={null} onRecord={onRecord} onUndo={onUndo} />
            <button type="button" className={link} onClick={() => onViewQuote(a.quote_id)}>View {a.quote_id} in Data</button>
          </td>
        </tr>
      ) : null}
    </>
  )
}
