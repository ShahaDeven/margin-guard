import { pct, shortDate, unitPrice } from '../lib/format'
import type { SyncChange, SyncField } from '../lib/types'

/** What a sync did to one record, in words: applied, added, kept ours, sent to the agents. */
const OUTCOME: Record<string, { label: string; tone: string }> = {
  applied: { label: 'Updated from Odoo', tone: 'text-ink' },
  added: { label: 'New from Odoo', tone: 'text-ink' },
  removed: { label: 'Removed in Odoo', tone: 'text-ink' },
  conflict: { label: "Changed on both sides: kept Margin Guard's", tone: 'text-attn' },
  new_price: { label: 'New supplier price: sent to the agents', tone: 'text-ink' },
  already_on_file: { label: 'Supplier price already on file (came by email)', tone: 'text-ink-dim' },
  no_effect: { label: "Changed in Odoo, in nothing Margin Guard reads", tone: 'text-ink-dim' },
}

/** A field's value the way the rest of the console writes it. */
function value(f: SyncField, v: unknown): string {
  if (v === null || v === undefined || v === '') return 'none'
  if (f.field === 'unit_price' && typeof v === 'number') return unitPrice(v)
  if (f.field === 'cost_per_lb' && typeof v === 'number') return `$${v.toFixed(v < 10 ? 4 : 2)}/lb`
  if (/date|until|ordered|issued/.test(f.field) && typeof v === 'string') return shortDate(v)
  if (f.field === 'qty' && typeof v === 'number') return v.toLocaleString()
  if (f.field === 'lines' && Array.isArray(v)) return v.map((x) => (Array.isArray(x) ? `${x[0]} ${x[1]} lb` : String(x))).join(', ')
  return String(v)
}

function Fields({ fields }: { fields: SyncField[] }) {
  return (
    <ul className="space-y-0.5">
      {fields.map((f) => (
        <li key={f.field}>
          <span className="text-ink-dim">{f.label}:</span> <span className="text-ink-dim line-through decoration-rule-bright">{value(f, f.from)}</span>
          {' '}<span aria-hidden className="text-ink-dim">→</span><span className="sr-only">to</span> <span className="text-ink">{value(f, f.to)}</span>
        </li>
      ))}
    </ul>
  )
}

/** Every change a sync made, each with where it landed. `onViewQuote` opens a quote in Shop
 *  data; `onOpenLane` goes to the view a change feeds (a new price goes to the agents). */
export function ChangeList({ changes, onViewQuote, onOpenLane, showRecord = true }: {
  changes: SyncChange[]
  onViewQuote?: (quoteId: string) => void
  onOpenLane?: (lane: 'decide' | 'data', material?: string) => void
  showRecord?: boolean
}) {
  return (
    <ul className="flex flex-col divide-y divide-rule-soft">
      {changes.map((c, i) => {
        const o = OUTCOME[c.outcome] ?? { label: c.outcome, tone: 'text-ink' }
        const m = c.margin
        const below = m && m.floor != null && m.to != null && m.to < m.floor
        return (
          <li key={`${c.kind}-${c.ref}-${i}`} className="py-2.5 first:pt-0 last:pb-0">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
              {showRecord ? <span className="font-medium text-ink">{c.record}</span> : null}
              <span className={`text-[13px] ${o.tone}`}>{o.label}</span>
            </div>
            <div className="mt-1 space-y-1.5 text-[13px]">
              {c.fields.length ? <Fields fields={c.fields} /> : null}
              {c.lines?.map((ln, j) => (
                <div key={j}>
                  <span className="text-ink">{ln.record}</span>
                  {ln.outcome !== 'applied' ? <span className={`ml-2 ${OUTCOME[ln.outcome]?.tone ?? ''}`}>{OUTCOME[ln.outcome]?.label ?? ln.outcome}</span> : null}
                  <div className="pl-3"><Fields fields={ln.fields} /></div>
                </div>
              ))}
              {m && m.from != null && m.to != null ? (
                <p>
                  <span className="text-ink-dim">Quoted margin:</span> <span className="text-ink-dim">{pct(m.from)}</span>
                  {' '}<span aria-hidden className="text-ink-dim">→</span><span className="sr-only">to</span>{' '}
                  <span className={below ? 'font-medium text-stop' : 'text-ink'}>{pct(m.to)}</span>
                  {m.floor != null ? <span className="text-ink-dim">{below ? `, below its ${pct(m.floor, 0)} floor` : `, floor ${pct(m.floor, 0)}`}</span> : null}
                </p>
              ) : null}
              {c.outcome === 'no_effect' && c.reads?.length ? (
                <p className="text-ink-dim">Margin Guard reads only: {c.reads.join(', ').toLowerCase()}.</p>
              ) : null}
              {c.where?.quote && onViewQuote ? (
                <button type="button" onClick={() => onViewQuote(c.where!.quote!)} className="text-go hover:text-go-soft">
                  Open {c.where.quote} in Shop data
                </button>
              ) : null}
              {c.where?.lane === 'decide' && onOpenLane ? (
                <button type="button" onClick={() => onOpenLane('decide', c.where!.material ?? c.ref.split(':')[0])}
                  className="text-go hover:text-go-soft">
                  See the quotes it hits in To decide
                </button>
              ) : null}
            </div>
          </li>
        )
      })}
    </ul>
  )
}
