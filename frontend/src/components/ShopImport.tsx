import { useEffect, useMemo, useState } from 'react'

import { api } from '../lib/api'
import { shortDate } from '../lib/format'
import type { ShopCheck, ShopCreated } from '../lib/types'
import { Button } from './Button'

const panel = 'rounded-md border border-rule bg-sheet px-5 py-4'
const stepTitle = 'text-lg font-semibold text-ink'
const field = 'w-full rounded-sm border border-rule-bright bg-ground px-2.5 py-2 text-sm text-ink outline-none focus:border-go'
const fileButton = 'inline-flex min-h-11 cursor-pointer items-center rounded-sm px-4'

const readAll = async (list: FileList) =>
  Object.fromEntries(await Promise.all([...list].map(async (f) => [f.name, await f.text()] as const)))

/** A whole shop from nine CSV files, three steps on one page: the files matched to the nine
 *  kinds (left), the check of every row (right), then load as a new shop. The check is
 *  margin_guard/importer.py's, run as a dry run; nothing is written until "Load". */
export function ShopImport({ asOf }: { asOf: string | null }) {
  const [files, setFiles] = useState<Record<string, string>>({})
  const [slots, setSlots] = useState<Record<string, string | null>>({})
  const [check, setCheck] = useState<ShopCheck | null>(null)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState<ShopCreated | null>(null)
  const names = useMemo(() => Object.keys(files).sort(), [files])

  // The check re-runs whenever a file is added or a slot is pointed at another file.
  useEffect(() => {
    if (!names.length) return
    const t = window.setTimeout(() => {
      api.checkShop(files, slots).then((r) => { setCheck(r); setError(null) })
        .catch((e) => setError(e instanceof Error ? e.message : String(e)))
    }, 250)
    return () => window.clearTimeout(t)
  }, [files, slots, names.length])

  const add = (more: Record<string, string>, replace = false) => {
    setFiles((f) => (replace ? more : { ...f, ...more }))
    if (replace) setSlots({})
    setLoaded(null)
  }
  const sample = (mistakes: boolean) => api.sampleShopFiles(mistakes).then((r) => {
    add(r.files, true)
    setName(mistakes ? 'Sample shop, with mistakes' : 'Sample shop copy')
  })
  const reset = () => { setFiles({}); setSlots({}); setCheck(null); setName(''); setError(null) }

  const load = async () => {
    setBusy(true)
    try {
      setLoaded(await api.createShop(name, files, slots))
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (loaded) {
    const q = loaded.rows
    return (
      <section className={`${panel} py-6`}>
        <h2 className="text-xl font-semibold text-ink">{loaded.name} is loaded</h2>
        <p className="mt-1 text-ink">
          {q['quotes.csv']} quotes with {q['quote_lines.csv']} lines, {q['customers.csv']} customers, {q['materials.csv']} materials
          and {q['vendors.csv']} suppliers, in a database of its own. The console now runs on it; the sample shop is unchanged,
          and you can switch back from the sidebar.
        </p>
        <div className="mt-4">
          <Button tone="go" className="font-semibold" onClick={() => { window.location.hash = 'home'; window.location.reload() }}>
            Open {loaded.name}
          </Button>
        </div>
      </section>
    )
  }

  if (!names.length) return <Upload onFiles={(f) => add(f, true)} onSample={sample} />

  const problems = check?.problems ?? []
  const byFile = problems.reduce<Record<string, typeof problems>>((acc, p) => {
    const k = p.file ?? 'Across files'
    ;(acc[k] ??= []).push(p)
    return acc
  }, {})

  return (
    <div className="flex flex-col gap-6">
      {error ? <p className="rounded-sm border border-stop/50 px-4 py-2 text-sm text-stop">{error}</p> : null}
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,30rem)_minmax(0,1fr)]">
        <section className={panel} aria-label="Step 1, the files">
          <h2 className={stepTitle}>1 The files</h2>
          <p className="mb-3 text-[13px] text-ink-dim">Matched by name. Point any of the nine at another file if the match is wrong.</p>
          <ul className="flex flex-col">
            {(check?.slots ?? []).map((s) => (
              <li key={s.file} className="grid grid-cols-[minmax(0,1fr)_minmax(0,11rem)] items-center gap-3 border-b border-rule-soft py-2.5 last:border-b-0">
                <div className="min-w-0">
                  <div className="text-ink">{s.label} <span className="text-[13px] text-ink-dim">{s.file}</span></div>
                  <div className="text-[13px] text-ink-dim">
                    {s.uploaded ? `${s.rows ?? 0} row${s.rows === 1 ? '' : 's'}` : <span className="text-attn">No file</span>}, {s.holds}
                  </div>
                </div>
                <select aria-label={`File for ${s.label}`} value={s.uploaded ?? ''} className={`${field} ${s.uploaded ? '' : 'border-attn'}`}
                  onChange={(e) => setSlots((m) => ({ ...m, [s.file]: e.target.value || null }))}>
                  <option value="">Not chosen</option>
                  {names.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </li>
            ))}
          </ul>
          {check?.unused.length ? <p className="mt-3 text-[13px] text-ink-dim">Not used: {check.unused.join(', ')}.</p> : null}
          <div className="mt-4 flex flex-wrap items-center gap-4">
            <label className={`${fileButton} border border-rule-bright text-ink hover:border-go`}>
              Add or replace files
              <input type="file" accept=".csv,text/csv" multiple className="sr-only"
                onChange={async (e) => { if (e.target.files?.length) add(await readAll(e.target.files)); e.target.value = '' }} />
            </label>
            <button type="button" onClick={reset} className="text-go hover:text-go-soft">Start over</button>
          </div>
        </section>

        <section className={panel} aria-label="Step 2, the check" aria-live="polite">
          <h2 className={stepTitle}>2 Check every row</h2>
          {!check ? <p className="text-sm text-ink-dim">Checking…</p> : check.valid && check.summary ? (
            <>
              <p className="mb-3 text-[13px] text-ink-dim">Every row of all nine files, and every reference between them.</p>
              <p className="text-ink">All nine files check out.</p>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink">
                <li>
                  {check.summary.quotes.open} open quotes, {check.summary.quotes.won} won, {check.summary.quotes.lost} lost
                  {check.summary.quotes.expired ? `, ${check.summary.quotes.expired} expired` : ''}, quoted
                  {' '}{shortDate(check.summary.first_quote)} to {shortDate(check.summary.last_quote)}.
                </li>
                <li>
                  {check.summary.rows['customers.csv']} customers, {check.summary.rows['materials.csv']} materials from
                  {' '}{check.summary.rows['vendors.csv']} suppliers, {check.summary.rows['parts.csv']} parts.
                </li>
                {check.summary.computed_bases ? (
                  <li>{check.summary.computed_bases} quote line{check.summary.computed_bases === 1 ? ' has' : 's have'} no material cost; it
                    will be worked out from the BOM and the price on the quote date.</li>
                ) : null}
              </ul>
              {asOf ? (
                <p className="mt-3 text-[13px] text-ink-dim">
                  The console works as of {shortDate(asOf)}: a quote is at risk from a price change that lands before it expires.
                </p>
              ) : null}
            </>
          ) : (
            <>
              <p className="mb-3 text-[13px] text-ink-dim">
                {problems.length} problem{problems.length === 1 ? '' : 's'}. Nothing is loaded until every one is fixed: a partial
                shop would show margins that look right and aren't. Fix the file, then add it again.
              </p>
              <div className="flex flex-col gap-4">
                {Object.entries(byFile).map(([file, ps]) => (
                  <div key={file}>
                    <h3 className="font-medium text-ink">{file} <span className="text-[13px] font-normal text-ink-dim">{ps.length}</span></h3>
                    <ul className="mt-1 flex flex-col gap-1 text-sm">
                      {ps.map((p, i) => (
                        <li key={i} className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] gap-3">
                          <span className="text-ink-dim">{p.row ? `Row ${p.row}` : 'File'}{p.column ? `, ${p.column}` : ''}</span>
                          <span className="text-attn">{p.message.charAt(0).toUpperCase() + p.message.slice(1)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </>
          )}
        </section>
      </div>

      <section className={panel} aria-label="Step 3, load">
        <h2 className={stepTitle}>3 Load as a new shop</h2>
        <p className="mb-3 text-[13px] text-ink-dim">Loaded into a database of its own, all or nothing. The sample shop is never written over.</p>
        <div className="flex flex-wrap items-end gap-3">
          <label className="block w-full max-w-sm">
            <span className="mb-1 block text-[13px] text-ink-dim">Shop name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Acme Molding" className={field} />
          </label>
          <Button tone="go" className="font-semibold" disabled={busy || !check?.valid || !name.trim()} onClick={load}>
            {busy ? 'Loading…' : 'Load as a new shop'}
          </Button>
        </div>
      </section>
    </div>
  )
}

/** The empty state: one filled button, the templates, and two ways to try it. */
function Upload({ onFiles, onSample }: { onFiles: (f: Record<string, string>) => void; onSample: (mistakes: boolean) => void }) {
  return (
    <section className={`${panel} py-6`}>
      <p className="max-w-3xl text-ink">
        A shop is nine CSV files: suppliers, materials, who supplies what, price history, parts, bills of materials,
        customers, quotes and quote lines. Choose all of them at once; each is matched by its name.
      </p>
      <p className="mt-1 max-w-3xl text-[13px] text-ink-dim">
        The <a href="/api/shops/templates.zip" className="text-go hover:text-go-soft">templates</a> hold the sample shop, so each
        file shows its columns and format. Dates are YYYY-MM-DD, costs are USD per lb, margins are fractions (0.25 is 25%).
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
        <label className={`${fileButton} bg-go font-semibold text-ground hover:bg-go-soft`}>
          Choose the CSV files
          <input type="file" accept=".csv,text/csv" multiple className="sr-only"
            onChange={async (e) => { if (e.target.files?.length) onFiles(await readAll(e.target.files)); e.target.value = '' }} />
        </label>
        <span className="text-ink-dim">or try it with</span>
        <button type="button" onClick={() => onSample(false)} className="text-go hover:text-go-soft">the sample shop's files</button>
        <button type="button" onClick={() => onSample(true)} className="text-go hover:text-go-soft">the same files with four mistakes</button>
      </div>
    </section>
  )
}
