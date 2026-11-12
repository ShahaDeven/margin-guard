import { useCallback, useEffect, useMemo, useState } from 'react'

import { api } from '../lib/api'
import { materialLabel, shortDate, usd } from '../lib/format'
import type { ImportHistoryRow, ImportPreview, ImportResult, StagedImport, Vendor } from '../lib/types'
import { Button } from './Button'
import { Family } from './QuoteParts'

const head = 'pb-2 font-label text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-dim'
const field = 'w-full rounded-sm border border-rule bg-sheet-2 px-2.5 py-1.5 text-sm text-ink-bright outline-none focus:border-attn/70'
const section = 'rounded-sm border border-rule bg-sheet px-5 py-4'
const NOT_STOCKED = ''

const STATUS: Record<string, { label: string; tone: string }> = {
  at_price: { label: 'at price', tone: 'text-go' },
  above: { label: 'billed above', tone: 'text-attn' },
  below: { label: 'billed below', tone: 'text-ink' },
  not_judged: { label: 'not judged', tone: 'text-ink-dim' },
  already_on_file: { label: 'already checked', tone: 'text-ink-dim' },
}

/** Invoice import for an estimator: upload, match columns, suppliers and items, check the
 *  dry run, then write it in one step. Every step runs margin_guard/imports.py; nothing is
 *  written until "Import". */
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

  // The preview re-runs on every change: mapping, a supplier or item match.
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
    <div className="space-y-5">
      {error ? <p className="rounded-sm border border-stop/50 bg-stop/5 px-4 py-2 text-sm text-stop">{error}</p> : null}

      {!staged ? <Upload busy={busy} onStage={stage} /> : null}

      {staged && !result ? (
        <>
          <section className={section}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-label text-lg font-semibold text-ink-bright">1 · Match the columns</h2>
              <span className="font-label text-[13px] text-ink-dim">{staged.filename} · {staged.row_count} lines</span>
            </div>
            <p className="mb-3 text-xs text-ink-dim">Suggested from the file's headers. Change any that are wrong; the example is from the first line.</p>
            <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2 xl:grid-cols-3">
              {staged.fields.map((f) => {
                const col = mapping[f.key]
                const idx = col ? staged.headers.indexOf(col) : -1
                return (
                  <label key={f.key} className="block">
                    <span className="font-label text-[13px] text-ink">{f.label}{f.required ? '' : ' (optional)'}</span>
                    <select value={col ?? ''} onChange={(e) => setMapping((m) => ({ ...m, [f.key]: e.target.value || null }))}
                      className={`${field} ${f.required && !col ? 'border-attn/70' : ''}`}>
                      <option value="">{f.required ? 'Choose a column…' : 'Not in this file'}</option>
                      {staged.headers.map((h) => <option key={h} value={h}>{h}</option>)}
                    </select>
                    <span className="mt-0.5 block truncate font-label text-[12px] text-ink-dim">{idx >= 0 ? `e.g. ${staged.sample[0]?.[idx] ?? ''}` : ' '}</span>
                  </label>
                )
              })}
            </div>
          </section>

          {preview?.suppliers?.length ? (
            <section className={section}>
              <h2 className="font-label text-lg font-semibold text-ink-bright">2 · Match the suppliers</h2>
              <p className="mb-3 text-xs text-ink-dim">Each name in the file must be a supplier on file. Names it couldn't place are marked.</p>
              <table className="w-full max-w-2xl text-sm">
                <thead><tr className="text-left"><th className={head}>In the file</th><th className={head}>Supplier on file</th></tr></thead>
                <tbody>
                  {preview.suppliers.map((s) => (
                    <tr key={s.text} className="border-t border-rule">
                      <td className="py-1.5 pr-4 text-ink-bright">{s.text}{s.auto ? null : suppliers[s.text]
                        ? <span className="ml-2 font-label text-[12px] text-ink-dim">matched by you</span>
                        : <span className="ml-2 font-label text-[12px] text-attn">needs a match</span>}</td>
                      <td className="py-1.5">
                        <select value={suppliers[s.text] ?? s.auto ?? ''} onChange={(e) => setSuppliers((m) => ({ ...m, [s.text]: e.target.value }))}
                          className={`${field} ${s.vendor_id ? '' : 'border-attn/70'}`}>
                          <option value="">Choose a supplier…</option>
                          {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ) : null}

          {preview?.items?.length ? (
            <section className={section}>
              <h2 className="font-label text-lg font-semibold text-ink-bright">3 · Match the items</h2>
              <p className="mb-3 text-xs text-ink-dim">
                Items matched to a material are judged against that supplier's price on file. Anything left unmatched is listed as
                not judged, never guessed.
              </p>
              <table className="w-full text-sm">
                <thead><tr className="text-left"><th className={head}>Item as billed</th><th className={head}>Supplier</th><th className={head}>Material</th></tr></thead>
                <tbody>
                  {[...preview.items].sort((a, b) => Number(!!a.auto) - Number(!!b.auto)).map((it) => {
                    const value = matches[it.key] ?? it.auto ?? '__none'
                    const open = !it.auto && matches[it.key] === undefined
                    return (
                      <tr key={it.key} className="border-t border-rule">
                        <td className="py-1.5 pr-4 text-ink-bright">{it.item}
                          {open ? <span className="ml-2 font-label text-[12px] text-attn">{it.method === 'ambiguous' ? `could be ${it.candidates.map(materialLabel).join(' or ')}` : 'no match'}</span> : null}
                        </td>
                        <td className="py-1.5 pr-4 font-label text-ink">{vendors.find((v) => v.id === it.vendor_id)?.name ?? it.vendor_id}</td>
                        <td className="py-1.5">
                          <select value={value} onChange={(e) => {
                            const v = e.target.value
                            setMatches((m) => {
                              const next = { ...m }
                              if (v === '__none') delete next[it.key]      // back to "leave unmatched"
                              else next[it.key] = v
                              return next
                            })
                          }}
                            className={`${field} ${open ? 'border-attn/70' : ''}`}>
                            {it.auto ? null : <option value="__none">Leave unmatched (not judged)</option>}
                            <option value={NOT_STOCKED}>Not an item we stock</option>
                            {it.options.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                          </select>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <label className="mt-3 flex items-center gap-2 text-sm text-ink">
                <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="accent-ink-dim" />
                Remember the items I matched, so they match by themselves next time
              </label>
            </section>
          ) : null}

          <Check preview={preview} busy={busy} onCommit={commit} onDiscard={discard} />
        </>
      ) : null}

      {result ? (
        <section className={section}>
          <h2 className="font-label text-[22px] font-semibold text-go">
            Imported {result.summary.lines} invoice lines
          </h2>
          <p className="mt-1 text-[15px] text-ink">
            {result.summary.at_price} at price · {result.summary.above} billed above · {result.summary.below} below ·{' '}
            {result.summary.not_judged} not judged{result.summary.already_on_file ? ` · ${result.summary.already_on_file} already checked before` : ''}.
            {result.summary.drifts.length ? ` ${result.summary.cards_new} new card${result.summary.cards_new === 1 ? '' : 's'}, ${result.summary.cards_merged} added to open cards, ${usd(result.summary.overpaid_usd, 2)} overpaid.` : ' Nothing billed above the price on file.'}
          </p>
          {result.summary.remembered?.length ? <p className="mt-1 text-sm text-ink-dim">Remembered: {result.summary.remembered.join(', ')}</p> : null}
          <div className="mt-3 flex flex-wrap gap-2">
            {result.summary.drifts.length ? <Button tone="attn" onClick={onOpenDecide}>Open the cards in Decide</Button> : null}
            <Button onClick={reset}>Import another file</Button>
          </div>
        </section>
      ) : null}

      <History rows={history} />
    </div>
  )
}

function Upload({ busy, onStage }: { busy: boolean; onStage: (filename: string, text: string) => void }) {
  const demo = (name: string) => api.demoImport(name).then((d) => onStage(d.filename, d.text))
  return (
    <section className={section}>
      <h2 className="font-label text-lg font-semibold text-ink-bright">Bring in an invoice export</h2>
      <p className="mt-1 max-w-3xl text-sm text-ink">
        A CSV from your accounts-payable system, one row per invoice line. Nothing is written until you've matched the columns,
        checked the result and pressed Import.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label className={`inline-flex cursor-pointer items-center rounded-sm border border-attn/70 px-4 py-2 font-label text-[13px] font-semibold uppercase tracking-[0.06em] text-attn hover:bg-attn/10 ${busy ? 'opacity-40' : ''}`}>
          Choose a CSV file
          <input type="file" accept=".csv,text/csv" className="sr-only" disabled={busy}
            onChange={async (e) => { const f = e.target.files?.[0]; if (f) onStage(f.name, await f.text()); e.target.value = '' }} />
        </label>
        <span className="text-sm text-ink-dim">or try a sample:</span>
        <Button small disabled={busy} onClick={() => demo('invoices_ap_export.csv')}>AP export (needs matching)</Button>
        <Button small disabled={busy} onClick={() => demo('invoices_demo.csv')}>Clean demo file</Button>
      </div>
    </section>
  )
}

function Check({ preview, busy, onCommit, onDiscard }: { preview: ImportPreview | null; busy: boolean; onCommit: () => void; onDiscard: () => void }) {
  if (!preview) return <p className="text-sm text-ink-dim">Checking…</p>
  const ready = preview.stage === 'ready' && preview.summary
  const s = preview.summary
  return (
    <section className={section}>
      <h2 className="font-label text-lg font-semibold text-ink-bright">4 · Check before anything is written</h2>
      {!ready ? (
        <div className="mt-2 rounded-sm border border-attn/50 bg-attn/3 px-3 py-2 text-sm text-ink">
          {preview.stage === 'errors' ? 'These rows need fixing in the file before it can be imported; nothing will be written:' : 'Before this can be checked:'}
          <ul className="mt-1 list-disc pl-5">{preview.problems.slice(0, 20).map((p) => <li key={p}>{p}</li>)}</ul>
          {preview.problems.length > 20 ? <p className="mt-1 text-ink-dim">and {preview.problems.length - 20} more</p> : null}
        </div>
      ) : (
        <>
          <p className="mt-1 text-[15px] text-ink">
            <span className="font-semibold text-ink-bright">Importing will write {s!.lines - s!.already_on_file} invoice line{s!.lines - s!.already_on_file === 1 ? '' : 's'}</span>
            {s!.already_on_file ? `, skip ${s!.already_on_file} already checked in an earlier import` : ''}
            {s!.drifts.length
              ? `, ${[s!.cards_new ? `raise ${s!.cards_new} new card${s!.cards_new === 1 ? '' : 's'}` : '', s!.cards_merged ? `add to ${s!.cards_merged} open card${s!.cards_merged === 1 ? '' : 's'}` : ''].filter(Boolean).join(' and ')} (${usd(s!.overpaid_usd, 2)} overpaid)`
              : ', and raise no cards'}.
            {' '}Nothing has been written yet.
          </p>
          <div className="mt-3 -mx-5 overflow-x-auto px-5">
            <table className="w-full min-w-[46rem] text-sm">
              <thead><tr className="text-left">
                <th className={head}>Row</th><th className={head}>Invoice</th><th className={head}>Item</th><th className={head}>Material</th>
                <th className={`${head} pr-3 text-right`}>Billed $/lb</th><th className={`${head} pr-4 text-right`}>On file</th><th className={head}>Result</th>
              </tr></thead>
              <tbody>
                {preview.lines!.map((l) => (
                  <tr key={`${l.invoice_no}-${l.line_no}`} className="border-t border-rule align-top">
                    <td className="py-1.5 pr-3 font-label text-ink-dim">{l.row}</td>
                    <td className="py-1.5 pr-3 font-label text-ink">{l.invoice_no}/{l.line_no} <span className="text-ink-dim">{shortDate(l.date)}</span></td>
                    <td className="py-1.5 pr-3 text-ink-bright">{l.item}</td>
                    <td className="py-1.5 pr-3 font-label">{l.material_id ? <Family id={l.material_id} /> : <span className="text-ink-dim">-</span>}</td>
                    <td className="py-1.5 pr-3 text-right font-label text-ink">{l.billed_cost_per_lb != null ? `$${l.billed_cost_per_lb.toFixed(4)}` : '-'}</td>
                    <td className="py-1.5 pr-4 text-right font-label text-ink-dim">{l.expected_cost_per_lb != null ? `$${l.expected_cost_per_lb.toFixed(4)}` : '-'}</td>
                    <td className={`py-1.5 font-label ${STATUS[l.status]?.tone ?? ''}`}>
                      {STATUS[l.status]?.label ?? l.status}{l.pct != null && l.status === 'above' ? ` +${(l.pct * 100).toFixed(1)}%` : ''}
                      {l.note ? <span className="block text-[12px] text-ink-dim">{l.note}</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button tone="go" disabled={!ready || busy} onClick={onCommit}>Import {ready ? `${s!.lines - s!.already_on_file} lines` : ''}</Button>
        <Button disabled={busy} onClick={onDiscard}>Discard this file</Button>
      </div>
    </section>
  )
}

function History({ rows }: { rows: ImportHistoryRow[] }) {
  return (
    <section className={section}>
      <h2 className="mb-2 font-label text-lg font-semibold text-ink-bright">Earlier imports</h2>
      {!rows.length ? <p className="text-sm text-ink-dim">None yet.</p> : (
        <div className="-mx-5 overflow-x-auto px-5">
          <table className="w-full min-w-[40rem] text-sm">
            <thead><tr className="text-left">
              <th className={head}>When</th><th className={head}>File</th><th className={head}>Status</th>
              <th className={`${head} text-right`}>Lines</th><th className={`${head} text-right`}>Above</th><th className={`${head} text-right`}>Cards</th><th className={`${head} text-right`}>Overpaid</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-rule">
                  <td className="py-1.5 pr-3 font-label text-ink">{(r.committed_at ?? r.created_at).slice(0, 16).replace('T', ' ')}</td>
                  <td className="py-1.5 pr-3 text-ink-bright">{r.filename}</td>
                  <td className={`py-1.5 pr-3 font-label ${r.status === 'committed' ? 'text-go' : 'text-ink-dim'}`}>{r.status}</td>
                  <td className="py-1.5 text-right font-label text-ink">{r.summary ? r.summary.lines : r.row_count}</td>
                  <td className="py-1.5 text-right font-label text-ink">{r.summary ? r.summary.above : '-'}</td>
                  <td className="py-1.5 text-right font-label text-ink">{r.summary ? `${r.summary.cards_new} new · ${r.summary.cards_merged} added` : '-'}</td>
                  <td className="py-1.5 text-right font-label text-ink-bright">{r.summary ? usd(r.summary.overpaid_usd, 2) : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
