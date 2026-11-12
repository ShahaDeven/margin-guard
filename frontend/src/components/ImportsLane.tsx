import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../lib/api'
import { materialLabel, shortDate, usd } from '../lib/format'
import type { ImportHistoryRow, ImportPreview, ImportResult, StagedImport, Vendor } from '../lib/types'
import { Button } from './Button'

const head = 'border-b border-rule px-3 py-2.5 text-[13px] font-medium text-ink-dim'
const cell = 'border-b border-rule-soft px-3 py-2 align-top'
const field = 'w-full rounded-sm border border-rule-bright bg-ground px-2.5 py-2 text-sm text-ink outline-none focus:border-go'
const panel = 'rounded-md border border-rule bg-sheet px-5 py-4'
const stepTitle = 'text-lg font-semibold text-ink'
const NOT_STOCKED = ''

/** Billed above the price on file is money lost; everything else is plain. */
const STATUS: Record<string, { label: string; tone: string }> = {
  at_price: { label: 'At price', tone: 'text-ink' },
  above: { label: 'Billed above', tone: 'text-stop' },
  below: { label: 'Billed below', tone: 'text-ink' },
  not_judged: { label: 'Not judged', tone: 'text-ink-dim' },
  already_on_file: { label: 'Already checked', tone: 'text-ink-dim' },
}

/** "Nov 12, 5:47 am" from a stored UTC timestamp. */
const when = (iso: string) => {
  const d = new Date(`${iso.replace(' ', 'T')}${/[zZ+]/.test(iso.slice(10)) ? '' : 'Z'}`)
  return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}, ${d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).toLowerCase()}`
}

/** Invoice import, three steps on one page: match the columns (left), check the live dry run
 *  (right), then import. Every step runs margin_guard/imports.py; nothing is written until
 *  "Import". */
export function ImportsLane({ onOpenDecide }: { onOpenDecide: () => void }) {
  const [history, setHistory] = useState<ImportHistoryRow[]>([])
  const [vendors, setVendors] = useState<Vendor[]>([])
  const [staged, setStaged] = useState<StagedImport | null>(null)
  const [mapping, setMapping] = useState<Record<string, string | null>>({})
  const [suppliers, setSuppliers] = useState<Record<string, string>>({})
  const [matches, setMatches] = useState<Record<string, string>>({})
  const [remember, setRemember] = useState(true)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadHistory = useCallback(() => { api.importHistory().then(setHistory).catch(() => {}) }, [])
  useEffect(() => { loadHistory(); api.vendors().then(setVendors).catch(() => {}) }, [loadHistory])

  const reset = () => { setStaged(null); setPreview(null); setResult(null); setSuppliers({}); setMatches({}); setError(null) }

  const stage = async (filename: string, text: string) => {
    reset()
    setBusy(true)
    try {
      const s = await api.stageInvoices(filename, text)
      setStaged(s)
      setMapping(s.mapping)
      loadHistory()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const plan = useMemo(() => ({ mapping, suppliers, matches, remember }), [mapping, suppliers, matches, remember])

  // The check re-runs on every change: a column, a supplier or an item match.
  useEffect(() => {
    if (!staged || result) return
    const t = window.setTimeout(() => {
      api.previewImport(staged.import_id, plan).then((p) => { setPreview(p); setError(null) })
        .catch((e) => setError(e instanceof Error ? e.message : String(e)))
    }, 250)
    return () => window.clearTimeout(t)
  }, [staged, plan, result])

  const commit = async () => {
    if (!staged) return
    setBusy(true)
    try {
      setResult(await api.commitImport(staged.import_id, plan))
      loadHistory()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const discard = async () => {
    if (!staged) return
    await api.discardImport(staged.import_id).catch(() => {})
    reset()
    loadHistory()
  }

  return (
    <div className="flex flex-col gap-6">
      {error ? <p className="rounded-sm border border-stop/50 px-4 py-2 text-sm text-stop">{error}</p> : null}

      {!staged ? <Upload busy={busy} onStage={stage} /> : null}

      {staged && !result ? (
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
          <section className={panel} aria-label="Step 1, match columns">
            <h2 className={stepTitle}>1 Match columns</h2>
            <p className="mb-4 text-[13px] text-ink-dim">
              {staged.filename}, {staged.row_count} lines. Suggested from the file's headers; change any that are wrong.
            </p>
            <div className="flex flex-col gap-3.5">
              {staged.fields.map((f) => {
                const col = mapping[f.key]
                const idx = col ? staged.headers.indexOf(col) : -1
                const values = idx >= 0 ? staged.sample.slice(0, 3).map((r) => r[idx] ?? '').filter(Boolean) : []
                return (
                  <label key={f.key} className="block">
                    <span className="mb-1 block text-[13px] text-ink-dim">{f.label}{f.required ? '' : ' (optional)'}</span>
                    <select value={col ?? ''} onChange={(e) => setMapping((m) => ({ ...m, [f.key]: e.target.value || null }))}
                      className={`${field} ${f.required && !col ? 'border-attn' : ''}`}>
                      <option value="">{f.required ? 'Choose a column…' : 'Not in this file'}</option>
                      {staged.headers.map((h) => <option key={h} value={h}>{h}</option>)}
                    </select>
                    <span className="mt-1 block truncate text-[13px] text-ink-dim">{values.length ? values.join(', ') : ' '}</span>
                  </label>
                )
              })}
            </div>
          </section>

          <div className="flex min-w-0 flex-col gap-6">
            <section className={panel} aria-label="Step 2, check" aria-live="polite">
              <h2 className={stepTitle}>2 Check</h2>
              <Check preview={preview} vendors={vendors} suppliers={suppliers} setSuppliers={setSuppliers}
                matches={matches} setMatches={setMatches} remember={remember} setRemember={setRemember} />
            </section>

            <section className={panel} aria-label="Step 3, import">
              <h2 className={stepTitle}>3 Import</h2>
              <ImportStep preview={preview} busy={busy} onCommit={commit} onDiscard={discard} />
            </section>
          </div>
        </div>
      ) : null}

      {result ? (
        <section className={panel}>
          <h2 className="text-xl font-semibold text-ink">Imported {result.summary.lines} invoice lines</h2>
          <p className="mt-1 text-ink">
            {result.summary.at_price} at price, {result.summary.above} above quoted cost, {result.summary.below} below, and{' '}
            {result.summary.not_judged} not judged{result.summary.already_on_file ? `; ${result.summary.already_on_file} were already checked before` : ''}.
            {result.summary.drifts.length
              ? <> {decisions(result.summary.cards_new, result.summary.cards_merged)}, <span className="text-stop">{usd(result.summary.overpaid_usd, 2)} overpaid</span>.</>
              : ' Nothing was billed above the price on file.'}
          </p>
          {result.summary.remembered?.length ? <p className="mt-1 text-sm text-ink-dim">Remembered: {result.summary.remembered.join(', ')}</p> : null}
          <div className="mt-3 flex flex-wrap gap-2">
            {result.summary.drifts.length ? <Button tone="go" className="font-semibold" onClick={onOpenDecide}>Open them in To decide</Button> : null}
            <Button onClick={reset}>Import another file</Button>
          </div>
        </section>
      ) : null}

      <History rows={history} />
    </div>
  )
}

const decisions = (created: number, added: number) =>
  [created ? `${created} new decision${created === 1 ? '' : 's'}` : '', added ? `${added} added to decisions already open` : '']
    .filter(Boolean).join(' and ')

/** The empty state: one filled button, and a link to the two sample files. */
function Upload({ busy, onStage }: { busy: boolean; onStage: (filename: string, text: string) => void }) {
  const [menu, setMenu] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!menu) return
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setMenu(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [menu])
  const demo = (name: string) => { setMenu(false); api.demoImport(name).then((d) => onStage(d.filename, d.text)) }

  return (
    <section className={`${panel} py-6`}>
      <p className="max-w-2xl text-ink">A CSV from your accounts-payable system, one row per invoice line.</p>
      <div className="mt-4 flex flex-wrap items-center gap-4">
        <label className={`inline-flex min-h-11 cursor-pointer items-center rounded-sm bg-go px-4 font-semibold text-ground hover:bg-go-soft ${busy ? 'pointer-events-none opacity-40' : ''}`}>
          Choose a CSV file
          <input type="file" accept=".csv,text/csv" className="sr-only" disabled={busy}
            onChange={async (e) => { const f = e.target.files?.[0]; if (f) onStage(f.name, await f.text()); e.target.value = '' }} />
        </label>
        <div ref={ref} className="relative">
          <button type="button" aria-expanded={menu} onClick={() => setMenu(!menu)} className="text-go hover:text-go-soft">or try a sample file</button>
          {menu ? (
            <div role="menu" className="absolute left-0 z-30 mt-2 w-72 rounded-md border border-rule bg-sheet p-1.5 shadow-[0_12px_32px_rgba(0,0,0,0.35)]">
              <button type="button" role="menuitem" disabled={busy} onClick={() => demo('invoices_ap_export.csv')}
                className="block w-full rounded-sm px-2.5 py-2 text-left text-sm text-ink hover:bg-nav-active">
                Messy accounts-payable export<span className="block text-[13px] text-ink-dim">Its own column names; some suppliers and items need matching</span>
              </button>
              <button type="button" role="menuitem" disabled={busy} onClick={() => demo('invoices_demo.csv')}
                className="block w-full rounded-sm px-2.5 py-2 text-left text-sm text-ink hover:bg-nav-active">
                Clean demo file<span className="block text-[13px] text-ink-dim">Matches by itself</span>
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  )
}

/** Step 2: what the import would do, a supplier or item match where one is needed, and the rows. */
function Check({ preview, vendors, suppliers, setSuppliers, matches, setMatches, remember, setRemember }: {
  preview: ImportPreview | null
  vendors: Vendor[]
  suppliers: Record<string, string>
  setSuppliers: (fn: (m: Record<string, string>) => Record<string, string>) => void
  matches: Record<string, string>
  setMatches: (fn: (m: Record<string, string>) => Record<string, string>) => void
  remember: boolean
  setRemember: (v: boolean) => void
}) {
  if (!preview) return <p className="text-sm text-ink-dim">Checking…</p>
  const s = preview.summary
  const unplacedSuppliers = (preview.suppliers ?? []).filter((x) => !x.auto)
  const unplacedItems = [...(preview.items ?? [])].filter((it) => !it.auto)

  return (
    <div className="mt-1 flex flex-col gap-4">
      {preview.stage === 'ready' && s ? (
        <p className="text-ink">
          <span className="font-semibold">
            {s.lines} lines, {s.above} above quoted cost, <span className={s.overpaid_usd ? 'text-stop' : ''}>{usd(s.overpaid_usd, 2)} overpaid</span>.
          </span>{' '}
          {s.at_price} at price, {s.below} below, {s.not_judged} not judged{s.already_on_file ? `, ${s.already_on_file} already checked in an earlier import` : ''}.
        </p>
      ) : (
        <div className="rounded-sm border border-attn/60 px-3 py-2 text-sm text-ink">
          {preview.stage === 'errors' ? 'These rows need fixing in the file before it can be imported:' : 'Before this can be checked:'}
          <ul className="mt-1 list-disc pl-5">{preview.problems.slice(0, 20).map((p) => <li key={p}>{p}</li>)}</ul>
          {preview.problems.length > 20 ? <p className="mt-1 text-ink-dim">and {preview.problems.length - 20} more</p> : null}
        </div>
      )}

      {preview.suppliers?.length && (unplacedSuppliers.length || Object.keys(suppliers).length) ? (
        <div>
          <h3 className="mb-1 font-semibold text-ink">Suppliers</h3>
          <p className="mb-2 text-[13px] text-ink-dim">Each name in the file must be a supplier on file.</p>
          <div className="flex flex-col gap-2">
            {preview.suppliers.filter((x) => !x.auto || suppliers[x.text]).map((x) => (
              <label key={x.text} className="grid items-center gap-2 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)]">
                <span className="text-ink">
                  {x.text}
                  {suppliers[x.text] ? <span className="ml-2 text-[13px] text-ink-dim">matched by you</span>
                    : <span className="ml-2 text-[13px] text-attn">needs a match</span>}
                </span>
                <select value={suppliers[x.text] ?? x.auto ?? ''} onChange={(e) => setSuppliers((m) => ({ ...m, [x.text]: e.target.value }))}
                  className={`${field} ${x.vendor_id ? '' : 'border-attn'}`}>
                  <option value="">Choose a supplier…</option>
                  {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                </select>
              </label>
            ))}
          </div>
        </div>
      ) : null}

      {unplacedItems.length ? (
        <div>
          <h3 className="mb-1 font-semibold text-ink">Items</h3>
          <p className="mb-2 text-[13px] text-ink-dim">
            A matched item is judged against that supplier's price on file. Anything left unmatched is listed as not judged, never guessed.
          </p>
          <div className="flex flex-col gap-2">
            {unplacedItems.map((it) => {
              const value = matches[it.key] ?? '__none'
              const open = matches[it.key] === undefined
              return (
                <label key={it.key} className="grid items-center gap-2 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)]">
                  <span className="text-ink">
                    {it.item}
                    <span className="block text-[13px] text-ink-dim">
                      {vendors.find((v) => v.id === it.vendor_id)?.name ?? 'Supplier'}
                      {open ? <span className="text-attn">, {it.method === 'ambiguous' ? `could be ${it.candidates.map(materialLabel).join(' or ')}` : 'no match'}</span> : null}
                    </span>
                  </span>
                  <select value={value} onChange={(e) => {
                    const v = e.target.value
                    setMatches((m) => {
                      const next = { ...m }
                      if (v === '__none') delete next[it.key]      // back to "leave unmatched"
                      else next[it.key] = v
                      return next
                    })
                  }} className={`${field} ${open ? 'border-attn' : ''}`}>
                    <option value="__none">Leave unmatched (not judged)</option>
                    <option value={NOT_STOCKED}>Not an item we stock</option>
                    {it.options.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                  </select>
                </label>
              )
            })}
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm text-ink">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="accent-go" />
            Remember the items I matched, so they match by themselves next time
          </label>
        </div>
      ) : null}

      {preview.stage === 'ready' && preview.lines?.length ? (
        <div className="-mx-5 overflow-x-auto px-5">
          <table className="w-full min-w-[40rem] border-collapse text-sm">
            <thead><tr className="text-left">
              <th className={head}>Invoice</th><th className={head}>Item</th><th className={head}>Material</th>
              <th className={`${head} text-right`}>Billed $/lb</th><th className={`${head} text-right`}>On file</th><th className={head}>Result</th>
            </tr></thead>
            <tbody>
              {[...preview.lines].sort((a, b) => Number(b.status === 'above') - Number(a.status === 'above')).map((l) => (
                <tr key={`${l.invoice_no}-${l.line_no}`}>
                  <td className={cell}><div className="text-ink">{l.invoice_no}, line {l.line_no}</div><div className="text-[13px] text-ink-dim">{shortDate(l.date)}</div></td>
                  <td className={`${cell} text-ink`}>{l.item}</td>
                  <td className={cell}>{l.material_id ? materialLabel(l.material_id) : <span className="text-ink-dim">–</span>}</td>
                  <td className={`${cell} text-right`}>{l.billed_cost_per_lb != null ? `$${l.billed_cost_per_lb.toFixed(4)}` : '–'}</td>
                  <td className={`${cell} text-right text-ink-dim`}>{l.expected_cost_per_lb != null ? `$${l.expected_cost_per_lb.toFixed(4)}` : '–'}</td>
                  <td className={`${cell} ${STATUS[l.status]?.tone ?? ''}`}>
                    {STATUS[l.status]?.label ?? l.status}{l.pct != null && l.status === 'above' ? `, +${(l.pct * 100).toFixed(1)}%` : ''}
                    {l.note ? <span className="block text-[13px] text-ink-dim">{l.note}</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}

/** Step 3: the one filled button, and what pressing it writes. */
function ImportStep({ preview, busy, onCommit, onDiscard }: { preview: ImportPreview | null; busy: boolean; onCommit: () => void; onDiscard: () => void }) {
  const s = preview?.stage === 'ready' ? preview.summary : undefined
  const n = s ? s.lines - s.already_on_file : 0
  return (
    <div className="mt-1 flex flex-col gap-3">
      <p className="text-ink">
        {s
          ? <>Importing writes {n} invoice line{n === 1 ? '' : 's'}{s.drifts.length ? ` and creates ${decisions(s.cards_new, s.cards_merged)}` : ', and creates no decisions'}. Nothing has been written yet.</>
          : <span className="text-ink-dim">Finish steps 1 and 2 first.</span>}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button tone="go" className="font-semibold" disabled={!s || busy} onClick={onCommit}>Import{s ? ` ${n} lines` : ''}</Button>
        <Button disabled={busy} onClick={onDiscard}>Discard this file</Button>
      </div>
    </div>
  )
}

function History({ rows }: { rows: ImportHistoryRow[] }) {
  const STATUS_WORD: Record<string, string> = { staged: 'Staged', committed: 'Imported', discarded: 'Discarded' }
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-lg font-semibold text-ink">Earlier imports</h2>
      {!rows.length ? <p className="text-sm text-ink-dim">None yet.</p> : (
        // Sized to its content rather than stretched across the page.
        <div className="w-fit max-w-full overflow-x-auto rounded-md border border-rule bg-sheet">
          <table className="border-collapse text-sm">
            <thead><tr className="text-left">
              <th className={head}>When</th><th className={head}>File</th><th className={head}>Status</th>
              <th className={`${head} text-right`}>Lines</th><th className={`${head} text-right`}>Above quoted cost</th>
              <th className={`${head} text-right`}>Decisions created</th><th className={`${head} text-right`}>Overpaid amount</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className={`${cell} whitespace-nowrap`}>{when(r.committed_at ?? r.created_at)}</td>
                  <td className={`${cell} text-ink`}>{r.filename}</td>
                  <td className={`${cell} ${r.status === 'committed' ? 'text-ink' : 'text-ink-dim'}`}>{STATUS_WORD[r.status] ?? r.status}</td>
                  <td className={`${cell} text-right`}>{r.summary ? r.summary.lines : r.row_count}</td>
                  <td className={`${cell} text-right`}>{r.summary ? r.summary.above : '–'}</td>
                  <td className={`${cell} text-right`}>{r.summary ? r.summary.cards_new + r.summary.cards_merged : '–'}</td>
                  <td className={`${cell} text-right ${r.summary?.overpaid_usd ? 'text-stop' : ''}`}>{r.summary ? usd(r.summary.overpaid_usd, 2) : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
