import { useEffect, useState } from 'react'

import { api } from '../lib/api'
import type { ErpStatus } from '../lib/types'
import { Button } from './Button'
import { Empty } from './RulesLane'

const head = 'border-b border-rule px-4 py-2.5 text-[13px] font-medium text-ink-dim'
const cell = 'border-b border-rule-soft px-4 py-2.5 align-top'
const panel = 'rounded-md border border-rule bg-sheet'

const STATUS: Record<string, { label: string; tone: string }> = {
  pending: { label: 'Waiting to be written', tone: 'text-ink' },
  sent: { label: 'Written', tone: 'text-ink-dim' },
  conflict: { label: 'Stopped: Odoo changed first', tone: 'text-attn' },
  failed: { label: 'Failed, will retry', tone: 'text-stop' },
  cancelled: { label: 'Cancelled (decision undone)', tone: 'text-ink-dim' },
}

/** "Nov 14, 5:47 pm" from a stored UTC timestamp. */
const when = (iso: string | null) => {
  if (!iso) return ''
  const d = new Date(`${iso.replace(' ', 'T')}${/[zZ+]/.test(iso.slice(10)) ? '' : 'Z'}`)
  return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}, ${d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).toLowerCase()}`
}

/** One sync, in one sentence: what came in, what it raised, what needs a look. */
function syncSentence(s: ErpStatus['syncs'][number]['summary']): string {
  const k = s.kinds ?? {}
  const changed = Object.values(k).reduce((n, c) => n + (c.applied ?? 0) + (c.added ?? 0) + (c.line_applied ?? 0) + (c.line_added ?? 0), 0)
  const parts = [
    changed ? `${changed} change${changed === 1 ? '' : 's'} applied` : 'nothing new to apply',
    s.events?.length ? `${s.events.length} new supplier price${s.events.length === 1 ? '' : 's'} sent to the agents` : '',
    s.invoice?.lines ? `${s.invoice.lines} vendor bill line${s.invoice.lines === 1 ? '' : 's'} checked, ${s.invoice.drifts} drift question${s.invoice.drifts === 1 ? '' : 's'}` : '',
  ].filter(Boolean)
  const text = parts.join(', ')
  return `${text[0].toUpperCase()}${text.slice(1)}.`
}

/** The ERP connection: whether Odoo is reachable, what is linked, what came in and what went out. */
export function ErpLane({ version, busy, run }: { version: number; busy: boolean; run: (fn: () => Promise<unknown>) => void }) {
  const [s, setS] = useState<ErpStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<number | null>(null)

  useEffect(() => {
    api.erp().then((r) => { setS(r); setError(null) }).catch((e) => setError(String(e)))
  }, [version])

  if (error) return <Empty text={`Could not load the ERP connection: ${error}`} />
  if (!s) return <Empty text="Checking the connection…" />
  const waiting = (s.write_counts.pending ?? 0) + (s.write_counts.failed ?? 0)
  const linked = s.linked.reduce((n, l) => n + l.count, 0)

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <section className={`${panel} px-5 py-4`}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-xl font-semibold text-ink">
              {s.reachable ? 'Connected to Odoo' : s.configured ? 'Odoo is not reachable' : 'Not set up'}
            </h2>
            <p className="mt-1 text-ink-dim">
              {s.reachable ? `${s.url}, database ${s.database}. Odoo 19 Community, through its JSON-2 API.`
                : s.configured ? <>Start it with <code className="text-ink">docker compose -f docker-compose.odoo.yml start</code>. {s.problem}</>
                  : <>Run <code className="text-ink">python -m margin_guard.erp setup</code> to start a local Odoo with the demo shop.</>}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button tone="go" className="font-semibold" disabled={!s.reachable || busy} onClick={() => run(api.erpSync)}>Sync now</Button>
            <Button disabled={!s.reachable || busy || !waiting} onClick={() => run(api.erpPush)}>
              Send approved writes{waiting ? ` (${waiting})` : ''}
            </Button>
          </div>
        </div>
        <p className="mt-3 max-w-3xl text-[13px] text-ink-dim">
          Margin Guard reads the shop from Odoo (suppliers, prices, BOMs, quotes, vendor bills) and writes back only what a person
          approved here: revised quote prices, call tasks and supplier prices. Every write is checked against what Odoo holds first;
          if Odoo changed, the write stops and becomes a question in To decide.
        </p>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        <section className="flex min-w-0 flex-col gap-2">
          <h3 className="text-lg font-semibold text-ink">Linked records</h3>
          <p className="text-[13px] text-ink-dim">{linked ? 'Each one tied to its Odoo record.' : 'Nothing linked yet: run a sync.'}</p>
          <table className={`${panel} w-full border-separate border-spacing-0 overflow-hidden text-sm`}>
            <tbody>
              {s.linked.map((l) => (
                <tr key={l.kind}>
                  <td className={cell}>{l.label}</td>
                  <td className={`${cell} text-right`}>{l.count.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="flex min-w-0 flex-col gap-2">
          <h3 className="text-lg font-semibold text-ink">Syncs</h3>
          <p className="text-[13px] text-ink-dim">What came in from Odoo, newest first. Click one for its conflicts and notes.</p>
          {s.syncs.length ? (
            <ul className={`${panel} overflow-hidden`}>
              {s.syncs.map((x) => {
                const conflicts = x.summary.conflicts ?? []
                const notes = x.summary.notes ?? []
                const isOpen = open === x.id
                return (
                  <li key={x.id} className="border-b border-rule-soft last:border-b-0">
                    <button type="button" onClick={() => setOpen(isOpen ? null : x.id)} aria-expanded={isOpen}
                      className={`flex w-full flex-wrap justify-between gap-x-4 gap-y-1 px-4 py-2.5 text-left ${isOpen ? 'bg-sheet-2' : 'hover:bg-sheet-2/50'}`}>
                      <span className="text-ink">{syncSentence(x.summary)}</span>
                      <span className="text-[13px] text-ink-dim">
                        {conflicts.length ? <span className="text-attn">{conflicts.length} conflict{conflicts.length === 1 ? '' : 's'}, </span> : null}
                        {when(x.finished_at)}
                      </span>
                    </button>
                    {isOpen && (conflicts.length || notes.length) ? (
                      <div className="space-y-2 bg-ground/40 px-4 py-3 text-[13px]">
                        {conflicts.length ? (
                          <div><p className="font-medium text-ink">Conflicts, Margin Guard's kept</p>
                            <ul className="list-disc pl-5 text-ink-dim">{conflicts.map((c) => <li key={c}>{c}</li>)}</ul></div>
                        ) : null}
                        {notes.length ? (
                          <div><p className="font-medium text-ink">Notes</p>
                            <ul className="list-disc pl-5 text-ink-dim">{notes.map((n) => <li key={n}>{n}</li>)}</ul></div>
                        ) : null}
                      </div>
                    ) : isOpen ? <p className="bg-ground/40 px-4 py-3 text-[13px] text-ink-dim">No conflicts or notes.</p> : null}
                  </li>
                )
              })}
            </ul>
          ) : <p className="text-sm text-ink-dim">No syncs yet.</p>}
        </section>
      </div>

      <section className="flex min-w-0 flex-col gap-2">
        <h3 className="text-lg font-semibold text-ink">Writes to Odoo</h3>
        <p className="text-[13px] text-ink-dim">Queued when a person approves, sent by "Send approved writes". Newest first.</p>
        {s.writes.length ? (
          <div className={`${panel} overflow-x-auto`}>
            <table className="w-full min-w-[640px] border-collapse text-sm">
              <thead>
                <tr className="text-left">
                  <th className={head}>Queued</th><th className={head}>What</th><th className={head}>Status</th><th className={head}>Detail</th>
                  <th className={head}><span className="sr-only">Action</span></th>
                </tr>
              </thead>
              <tbody>
                {s.writes.map((w) => (
                  <tr key={w.id}>
                    <td className={`${cell} whitespace-nowrap text-ink-dim`}>{when(w.created_at)}</td>
                    <td className={`${cell} text-ink`}>{w.label}</td>
                    <td className={`${cell} whitespace-nowrap ${STATUS[w.status]?.tone ?? ''}`}>{STATUS[w.status]?.label ?? w.status}</td>
                    <td className={`${cell} text-[13px] text-ink-dim`}>{w.detail ?? ''}</td>
                    <td className={`${cell} whitespace-nowrap text-right`}>
                      {w.status === 'conflict' ? (
                        <Button small disabled={!s.reachable || busy} onClick={() => run(() => api.erpForce(w.id))}>Write it anyway</Button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="text-sm text-ink-dim">Nothing written yet. Approving a reprice or a call in To decide queues a write here.</p>}
      </section>
    </div>
  )
}
