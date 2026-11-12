import { useEffect, useState } from 'react'

import { api } from '../lib/api'
import { pct, shortDate, unitPrice, usd } from '../lib/format'
import type { CustomerRecord, Outcome, OutcomeBody, OutcomeKind, OutcomesSummary, OutcomeTally, QuoteFacts } from '../lib/types'
import { Button } from './Button'
import { FIGURE } from './MarginBar'
import { Empty } from './RulesLane'

const head = 'border-b border-rule px-4 py-2.5 text-[13px] font-medium text-ink-dim'
const cell = 'border-b border-rule-soft px-4 py-2.5 align-top'
const link = 'text-[13px] text-go hover:text-go-soft'
const panel = 'rounded-md border border-rule bg-sheet'

/** The increase a decision asked for over the whole quote (same sum as outcomes.asked on the server). */
export const askedFor = (f: QuoteFacts) =>
  Math.round(f.lines.reduce((s, l) => s + (l.proposed_unit_price - l.unit_price) * l.qty, 0) * 100) / 100

export const OUTCOME_TEXT: Record<OutcomeKind, { label: string; tone: string }> = {
  accepted: { label: 'Accepted', tone: 'text-ink' },
  negotiated: { label: 'Negotiated', tone: 'text-ink' },
  lost: { label: 'Walked', tone: 'text-stop' },
}

export function OutcomeBadge({ o }: { o: Outcome }) {
  const t = OUTCOME_TEXT[o.outcome]
  return <span className={`text-[13px] font-medium ${t.tone}`}>{t.label}</span>
}

/** Only "has walked" is coloured; a customer who pushes back is information, not an alarm. */
const patternTone = (pattern: string) => (pattern.startsWith('has walked') ? 'text-stop' : 'text-ink-dim')

/** One line on a decision card: how this customer has taken increases before. People read it; the model never sees it. */
export function CustomerRecordLine({ r, name }: { r: CustomerRecord | null | undefined; name: string }) {
  if (!r) {
    return (
      <p className="text-[13px] text-ink-dim">No past increases on record for {name}.</p>
    )
  }
  const parts = [
    r.accepted ? `${r.accepted} accepted` : '',
    r.negotiated ? `${r.negotiated} negotiated down` : '',
    r.lost ? `${r.lost} walked` : '',
  ].filter(Boolean)
  const tone = r.pattern.startsWith('has walked') ? 'text-stop' : 'text-ink'
  return (
    <p className="text-[13px] text-ink">
      {name} {r.pattern === 'too few increases to say' ? 'has' : <span className={`font-semibold ${tone}`}>{r.pattern}</span>}
      {r.pattern === 'too few increases to say' ? '' : ':'} {r.requests} past increase{r.requests === 1 ? '' : 's'}, {parts.join(', ')}
      {r.kept != null && r.negotiated ? <> (kept {pct(r.kept, 0)} of what was asked)</> : null}.
      <span className="text-ink-dim"> The last one {OUTCOME_TEXT[r.last.outcome].label.toLowerCase()}, {shortDate(r.last.date)}.</span>
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
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-sm border border-rule bg-sheet px-3 py-2 text-sm">
        <span className="text-ink-dim">Customer response:</span>
        <OutcomeBadge o={outcome} />
        <span className="text-ink">
          {outcome.outcome === 'lost'
            ? <>{quoteId} marked lost on {shortDate(outcome.outcome_date)}: {usd(outcome.lost_revenue_usd)} of revenue</>
            : <>kept {usd(outcome.recovered_usd, 2)} of the {usd(outcome.asked_usd, 2)} asked, {shortDate(outcome.outcome_date)}
              {outcome.price_changes.length ? <span className="text-ink-dim">
                {'. '}Quote price{outcome.price_changes.length === 1 ? '' : 's'} now {outcome.outcome === 'negotiated' ? 'agreed at' : 'at'}{' '}
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
    <div className="space-y-2 rounded-sm border border-rule bg-sheet px-3 py-2.5 text-sm">
      <p className="text-ink">
        What did the customer say to the {usd(asked, 2)} increase{channel === 'call' ? ' on the call' : ''}?
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button small onClick={() => onRecord(proposalId, { outcome: 'accepted' })}>Accepted</Button>
        <Button small onClick={() => setMode(mode === 'negotiated' ? null : 'negotiated')}>Negotiated</Button>
        <Button small onClick={() => setMode(mode === 'lost' ? null : 'lost')}>Walked</Button>
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
            className="w-28 rounded-sm border border-rule-bright bg-ground px-2 py-1 text-ink outline-none focus:border-go"
          />
          <span className="text-ink-dim">of the {usd(asked, 2)}{validAmount ? ` (${pct(value / asked, 0)})` : ''}</span>
          <Button small disabled={!validAmount} onClick={() => { onRecord(proposalId, { outcome: 'negotiated', recovered_usd: amount }); setMode(null) }}>
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

  const historyOnly = s.console.requests === 0 && s.history.requests > 0
  const mixed = scope === 'all' && s.console.requests > 0 && s.history.requests > 0

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="inline-flex rounded-sm border border-rule-bright p-0.5" role="group" aria-label="Which responses to count">
          {SCOPES.map((x) => (
            <button
              key={x.id}
              type="button"
              aria-pressed={scope === x.id}
              onClick={() => setScope(x.id)}
              className={`rounded-[4px] px-3 py-1.5 text-[13px] transition-colors ${
                scope === x.id ? 'bg-nav-active font-semibold text-go-soft' : 'text-ink hover:text-go-soft'
              }`}
            >
              {x.label} <span className="text-ink-dim">{s[x.id].requests}</span>
            </button>
          ))}
        </div>
        {historyOnly ? (
          <p className="text-[13px] text-ink-dim">
            All {s.history.requests} responses are from before Margin Guard, synthetic in the demo.
          </p>
        ) : null}
      </div>

      <section>
        {t.requests ? (
          <>
            <h2 className="text-xl font-semibold text-ink">
              <span className={`${FIGURE} text-[28px]`}>{usd(t.recovered_usd)}</span> recovered of {usd(t.asked_kept_jobs_usd)} asked
              on the jobs kept{t.kept != null ? `, ${pct(t.kept, 0)}` : ''}
            </h2>
            <p className="mt-1 max-w-3xl text-ink">
              {t.requests} increase{t.requests === 1 ? '' : 's'} with a response: {t.accepted} accepted, {t.negotiated} negotiated
              down, and {t.lost} where the customer walked, with{' '}
              <span className={t.lost ? 'text-stop' : ''}>{usd(t.lost_revenue_usd)} of revenue lost</span>.
            </p>
          </>
        ) : (
          <p className="text-ink">No responses recorded {scope === 'console' ? 'since Margin Guard' : 'here'} yet.</p>
        )}
        <p className="mt-2 max-w-3xl text-[13px] text-ink-dim">
          "Kept" counts only the jobs the customer stayed on; a lost job's cost is its revenue, counted on its own. Responses are
          shown to people next to each decision and are never given to the model.
        </p>
      </section>

      {s.awaiting.length ? (
        <section className="flex flex-col gap-2">
          <h3 className="text-lg font-semibold text-ink">Waiting for the customer</h3>
          <p className="text-[13px] text-ink-dim">Approved reprices and calls with no response recorded. Click one to record it.</p>
          <div className={`${panel} overflow-x-auto`}>
            <table className="w-full min-w-[520px] border-collapse text-sm">
              <thead>
                <tr className="text-left">
                  <th className={head}>Customer</th><th className={head}>Sent as</th>
                  <th className={`${head} text-right`}>Increase asked</th><th className={head}>Approved</th>
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
          </div>
        </section>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <section className="flex min-w-0 flex-col gap-2">
          <h3 className="text-lg font-semibold text-ink">By customer</h3>
          <p className="text-[13px] text-ink-dim">Every response, history included: the record each decision card shows.</p>
          <div className={`${panel} overflow-x-auto`}>
            <table className="w-full min-w-[560px] border-collapse text-sm">
              <thead>
                <tr className="text-left">
                  <th className={head}>Customer</th>
                  <th className={`${head} text-right`}>Increases</th>
                  <th className={`${head} text-right`}>Accepted</th>
                  <th className={`${head} text-right`}>Negotiated</th>
                  <th className={`${head} text-right`}>Walked</th>
                  <th className={`${head} text-right`}>Kept</th>
                  <th className={head}>Pattern</th>
                </tr>
              </thead>
              <tbody>
                {s.customers.map((c) => (
                  <tr key={c.customer_id}>
                    <td className={`${cell} text-ink`}>{c.customer_name}</td>
                    <td className={`${cell} text-right`}>{c.requests}</td>
                    <td className={`${cell} text-right`}>{c.accepted}</td>
                    <td className={`${cell} text-right`}>{c.negotiated}</td>
                    <td className={`${cell} text-right ${c.lost ? 'text-stop' : ''}`}>{c.lost}</td>
                    <td className={`${cell} text-right`}>{c.kept != null ? pct(c.kept, 0) : '–'}</td>
                    <td className={`${cell} text-[13px] ${patternTone(c.pattern)}`}>{c.pattern.charAt(0).toUpperCase() + c.pattern.slice(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="flex min-w-0 flex-col gap-2">
          <h3 className="text-lg font-semibold text-ink">Responses</h3>
          <p className="text-[13px] text-ink-dim">Newest first.{mixed ? ' Responses from before Margin Guard are marked.' : ''}</p>
          {recent.length ? (
            <div className={`${panel} overflow-x-auto`}>
              <table className="w-full min-w-[420px] border-collapse text-sm">
                <thead>
                  <tr className="text-left">
                    <th className={head}>Date</th><th className={head}>Customer</th><th className={head}>Response</th>
                    <th className={`${head} text-right`}>Kept</th>
                  </tr>
                </thead>
                <tbody>
                  {recent.slice(0, 40).map((o) => (
                    <tr key={o.id}>
                      <td className={`${cell} whitespace-nowrap text-ink-dim`}>{shortDate(o.outcome_date)}</td>
                      <td className={cell}>
                        <div className="text-ink">{o.customer_name}</div>
                        <button type="button" className={link} onClick={() => onViewQuote(o.quote_id)}>{o.quote_id}</button>
                        {mixed && o.source === 'history' ? <span className="ml-2 text-[13px] text-ink-dim">before Margin Guard</span> : null}
                      </td>
                      <td className={cell}><OutcomeBadge o={o} /></td>
                      <td className={`${cell} text-right`}>
                        {o.outcome === 'lost'
                          ? <span className="text-stop">{usd(o.lost_revenue_usd)} lost</span>
                          : <>{usd(o.recovered_usd)} <span className="text-ink-dim">of {usd(o.asked_usd)}</span></>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
      <tr className={`cursor-pointer ${open ? 'bg-sheet-2' : 'hover:bg-sheet-2/50'}`} onClick={onToggle}>
        <td className={cell}><div className="text-ink">{a.customer_name}</div><div className="text-[13px] text-ink-dim">{a.quote_id}</div></td>
        <td className={`${cell} text-ink-dim`}>{a.channel === 'call' ? 'Call' : 'Email'}</td>
        <td className={`${cell} text-right`}>{usd(a.asked_usd, 2)}</td>
        <td className={`${cell} text-ink-dim`}>{a.reviewed_at ? shortDate(a.reviewed_at) : ''}</td>
      </tr>
      {open ? (
        <tr>
          <td colSpan={4} className="space-y-2 border-b border-rule-soft bg-ground/40 px-4 pb-3 pt-2">
            <CustomerRecordLine r={record} name={a.customer_name} />
            <OutcomeControl proposalId={a.proposal_id} asked={a.asked_usd} quoteId={a.quote_id} channel={a.channel}
              outcome={null} onRecord={onRecord} onUndo={onUndo} />
            <button type="button" className={link} onClick={() => onViewQuote(a.quote_id)}>Open {a.quote_id} in shop data</button>
          </td>
        </tr>
      ) : null}
    </>
  )
}
