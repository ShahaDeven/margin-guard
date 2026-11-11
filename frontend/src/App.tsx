import { useEffect, useMemo, useRef, useState } from 'react'

import { DataLane } from './components/DataLane'
import { DecisionCard, QUEUE_COLS } from './components/DecisionCard'
import { DoneLane } from './components/DoneLane'
import { LeakageLane } from './components/LeakageLane'
import { QuoteCheckLane } from './components/QuoteCheckLane'
import { sharedScale } from './components/MarginBar'
import { ReviewCard } from './components/ReviewCard'
import { Empty, RulesLane } from './components/RulesLane'
import { Sidebar } from './components/Sidebar'
import { useConsole } from './hooks/useConsole'
import { api, type Lane } from './lib/api'
import { pct, shortDate, usd } from './lib/format'
import { isQuote, type Leakage, type Overview } from './lib/types'
import { whatIf } from './lib/whatif'

const WHAT_IF = [1, 1.25, 1.5, 2]

function App() {
  const c = useConsole()
  const ov = c.overview
  const quoteCards = c.cards.filter(isQuote)
  const reviewCards = c.cards.filter((p) => p.kind === 'event_review')
  const [k, setK] = useState(1)
  const [focus, setFocus] = useState<number | null>(null)

  const scale = useMemo(() => sharedScale(quoteCards.map((p) => whatIf(p.facts, k))), [quoteCards, k])
  const withInbox = c.lane === 'decide' || c.lane === 'rules' || c.lane === 'done'

  // Focus mode: J / K walk the decision queue, Esc leaves it.
  useEffect(() => {
    if (c.lane !== 'decide') return
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.closest('input, textarea, select, [contenteditable]') || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === 'j') setFocus((i) => Math.min((i ?? -1) + 1, quoteCards.length - 1))
      else if (e.key === 'k') setFocus((i) => Math.max((i ?? 1) - 1, 0))
      else if (e.key === 'Escape') setFocus(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [c.lane, quoteCards.length])

  useEffect(() => setFocus(null), [c.lane, c.emailFilter])

  return (
    <div className="flex min-h-full flex-col">
      <NavBand lane={c.lane} setLane={c.setLane} ov={ov} leak={c.leakage} busy={c.busy} />

      <div className="mx-auto w-full max-w-[96rem] flex-1 px-4 pb-10 sm:px-6">
        {ov ? <Figures ov={ov} leak={c.leakage} setLane={c.setLane} /> : null}

        {c.error ? (
          <p className="mt-4 rounded-sm border border-stop/50 bg-stop/5 px-4 py-2 text-sm text-stop">{c.error}</p>
        ) : null}

        <div className={`mt-6 grid gap-6 ${withInbox ? 'lg:grid-cols-[20rem_minmax(0,1fr)]' : ''}`}>
          {withInbox ? (
            <div className="order-last lg:order-first">
            <Sidebar
              inbox={c.inbox}
              demoEmails={c.demoEmails}
              feed={c.feed}
              busy={c.busy}
              onSend={(id) => c.run(() => api.sendDemoEmail(id))}
              onShowCards={c.focusEmail}
            />
            </div>
          ) : null}

          <main className="min-w-0">
            <ViewHeading lane={c.lane} ov={ov} />
            {c.emailFilter && withInbox ? (
              <FilterChip
                email={c.inbox.find((m) => m.id === c.emailFilter)?.subject}
                id={c.emailFilter}
                onClear={() => c.setEmailFilter(null)}
              />
            ) : null}

            {c.lane === 'decide' && quoteCards.length ? (
              <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 border-y border-rule py-2.5">
                <div className="flex items-center gap-2" role="group" aria-label="What if the cost moves were larger">
                  <span className="font-label text-[13px] text-ink">What if these increases were</span>
                  {WHAT_IF.map((v) => (
                    <button
                      key={v}
                      type="button"
                      aria-pressed={k === v}
                      onClick={() => setK(v)}
                      className={`whitespace-nowrap rounded-sm border px-2.5 py-0.5 font-label text-[13px] transition-colors ${
                        k === v ? 'border-attn bg-attn/15 text-ink-bright' : 'border-rule-bright text-ink-dim hover:text-ink'
                      }`}
                    >
                      {v === 1 ? 'as announced' : `×${v}`}
                    </button>
                  ))}
                </div>
                <span className="font-label text-[13px] text-ink-dim">
                  <kbd className="rounded-sm border border-rule-bright px-1 text-ink">J</kbd> <kbd className="rounded-sm border border-rule-bright px-1 text-ink">K</kbd> step through cards
                </span>
                {k !== 1 ? (
                  <span className="w-full text-[13px] text-attn">
                    Hypothetical: margins and dollars at risk show the cost moves at ×{k}. Approving always uses the real numbers.
                  </span>
                ) : null}
              </div>
            ) : null}

            <div className="mt-4 space-y-3">
              {c.lane === 'decide' ? (
                <>
                  {reviewCards.map((p) => (
                    <ReviewCard
                      key={p.id}
                      p={p}
                      email={c.inbox.find((m) => m.id === (p.facts as { email_id: string }).email_id)}
                      materials={c.materials}
                      onResolve={(mat) => c.run(() => api.resolve(p.id, mat))}
                      onDismiss={() => c.run(() => api.dismiss(p.id))}
                    />
                  ))}
                  {quoteCards.length ? (
                  <div className="rounded-sm border border-rule bg-sheet">
                    <div className={`hidden items-end gap-x-6 border-b border-rule-bright py-2 pl-6 pr-5 font-label text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-dim md:grid ${QUEUE_COLS}`}>
                      <span>Customer · recommended action</span>
                      <span>Cost that moved · $/lb</span>
                      <span className="normal-case tracking-normal">
                        <span className="uppercase tracking-[0.08em]">Margin vs floor</span>
                        {scale ? <span className="font-normal"> · scale {pct(scale.lo, 0)}–{pct(scale.hi, 0)}</span> : null}
                        <span className="mt-1 flex items-center gap-3 font-normal">
                          <span className="inline-flex items-center gap-1"><svg width="10" height="10" aria-hidden><circle cx="5" cy="5" r="3.5" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>quoted</span>
                          <span className="inline-flex items-center gap-1"><svg width="10" height="10" aria-hidden><path d="M1 5 L9 1 L9 9 Z" fill="currentColor" /></svg>now</span>
                          <span className="inline-flex items-center gap-1"><span className="inline-block h-2.5 w-3 bg-stop/25" />below floor</span>
                        </span>
                      </span>
                      <span className="text-right">At risk</span>
                    </div>
                  {quoteCards.map((p, i) => (
                    <DecisionCard
                      key={p.id}
                      p={p}
                      fresh={c.arrived.has(p.id)}
                      bar={ov?.autonomy?.threshold ?? null}
                      scale={scale}
                      focused={focus === i}
                      k={k}
                      onReview={(body) => c.run(() => api.review(p.id, body))}
                      onViewQuote={c.focusQuote}
                    />
                  ))}
                  </div>
                  ) : null}
                  {!c.cards.length ? <Empty text="Nothing needs you right now." /> : null}
                </>
              ) : null}
              {c.lane === 'rules' ? (
                <RulesLane cards={quoteCards} onConfirm={(eventId) => c.run(() => api.confirmRules(eventId))} />
              ) : null}
              {c.lane === 'done' ? (
                <DoneLane cards={c.cards} outbox={c.outbox} onReopen={(id) => c.run(() => api.reopen(id))} onViewQuote={c.focusQuote} />
              ) : null}
              {c.lane === 'quote' ? <QuoteCheckLane onAnswer={() => c.setLane('decide')} /> : null}
              {c.lane === 'leakage' ? <LeakageLane r={c.leakage} onViewQuote={c.focusQuote} /> : null}
              {c.lane === 'data' && ov ? (
                <DataLane
                  asOf={ov.as_of}
                  version={c.version}
                  focusedQuote={c.focusedQuote}
                  onFocusHandled={() => c.setFocusedQuote(null)}
                />
              ) : null}
            </div>
          </main>
        </div>
      </div>

      <footer className="border-t border-rule px-6 py-4 text-center text-xs text-ink-dim">
        Rules decide the clear cases. Claude decides the judgment calls and drafts the message. Code does every number.
        A person approves everything. All shop data is synthetic.
      </footer>
    </div>
  )
}

const VIEWS: { id: Lane; label: string; short?: string; count?: (ov: Overview, leak: Leakage | null) => number | null }[] = [
  { id: 'decide', label: 'Decide', count: (ov) => ov.needs_you },
  { id: 'rules', label: 'Settled by rules', short: 'Rules', count: (ov) => ov.rule_pending },
  { id: 'done', label: 'Done', count: (ov) => ov.done },
  { id: 'quote', label: 'Quote check', short: 'Quote' },
  { id: 'leakage', label: 'Leakage', count: (_ov, leak) => leak?.jobs_leaked ?? null },
  { id: 'data', label: 'Data' },
]

/** The catalogue-green band: brand, the views, and what the shop and agents are doing. */
function NavBand({ lane, setLane, ov, leak, busy }: { lane: Lane; setLane: (l: Lane) => void; ov: Overview | null; leak: Leakage | null; busy: boolean }) {
  const active = useRef<HTMLButtonElement>(null)
  useEffect(() => { active.current?.scrollIntoView({ inline: 'nearest', block: 'nearest' }) }, [lane])
  return (
    <header className="sticky top-0 z-20 bg-shell shadow-[0_1px_0_#0e2a1e,0_6px_18px_rgba(0,0,0,0.35)]">
      <div className="mx-auto flex h-14 max-w-[96rem] items-stretch gap-4 px-4 sm:gap-8 sm:px-6">
        <div className="flex shrink-0 items-center font-label text-[17px] font-bold tracking-[0.12em] text-shell-ink sm:text-[19px]">
          MARGIN<span className="text-attn">GUARD</span>
        </div>
        <nav aria-label="Views" className="-mr-4 flex min-w-0 items-stretch overflow-x-auto [scrollbar-width:none] sm:mr-0">
          {VIEWS.map((v) => {
            const on = lane === v.id
            const n = ov && v.count ? v.count(ov, leak) : null
            return (
              <button
                key={v.id}
                ref={on ? active : undefined}
                type="button"
                aria-current={on ? 'page' : undefined}
                onClick={() => setLane(v.id)}
                className={`relative flex shrink-0 items-center gap-2 whitespace-nowrap px-3 text-[15px] font-medium transition-colors sm:px-4 ${
                  on ? 'bg-shell-2 text-shell-ink' : 'text-shell-dim hover:bg-shell-2/60 hover:text-shell-ink'
                }`}
              >
                {v.short ? <><span className="sm:hidden">{v.short}</span><span className="hidden sm:inline">{v.label}</span></> : v.label}
                {n != null ? (
                  <span className={`rounded-sm px-1.5 font-label text-[12px] font-semibold ${on ? 'bg-attn text-ground' : 'bg-ground/30 text-shell-ink'}`}>{n}</span>
                ) : null}
                {on ? <span aria-hidden className="absolute inset-x-0 bottom-0 h-[3px] bg-attn" /> : null}
              </button>
            )
          })}
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-4 font-label text-[13px] text-shell-dim">
          {ov ? <span className="hidden lg:inline">Shop date {shortDate(ov.as_of)} · {ov.model}</span> : null}
          <span className={`inline-flex items-center gap-2 rounded-sm bg-ground/30 px-2.5 py-1 ${busy ? 'text-claude' : 'text-shell-ink'}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${busy ? 'bg-claude mg-breathe' : 'bg-go'}`} />
            <span className="hidden sm:inline">{busy ? 'Agents working' : 'Agents idle'}</span>
            <span className="sr-only sm:hidden">{busy ? 'Agents working' : 'Agents idle'}</span>
          </span>
        </div>
      </div>
    </header>
  )
}

/** Four figures, each naming the rows it came from. Click one to open its view. */
function Figures({ ov, leak, setLane }: { ov: Overview; leak: Leakage | null; setLane: (l: Lane) => void }) {
  const items: { lane: Lane; value: string; label: string; source: string; tone: string }[] = [
    { lane: 'decide', value: usd(ov.live_exposure), label: 'at risk on open quotes', source: 'sum of every live card · impact on quote lines', tone: 'text-ink-bright' },
    {
      lane: 'decide', value: String(ov.needs_you), label: 'need your decision', tone: 'text-attn',
      source: ov.autonomy?.threshold != null
        ? `${usd(ov.needs_you_exposure)} at risk · ${ov.autonomy.would_clear} clear the ${ov.autonomy.threshold.toFixed(2)} confidence bar`
        : `${usd(ov.needs_you_exposure)} at risk`,
    },
    { lane: 'rules', value: String(ov.rule_pending), label: 'settled by rules', source: 'honor or absorb · confirm in bulk', tone: 'text-ink-bright' },
    {
      lane: 'leakage', value: leak ? usd(leak.leaked_usd) : '–', label: 'leaked on won jobs', tone: 'text-stop',
      source: leak?.period ? `${leak.jobs_leaked} of ${leak.won_jobs} jobs since ${shortDate(leak.period.from)} · price history` : 'won quotes vs price history',
    },
  ]
  return (
    <div className="mt-5 grid grid-cols-1 border-y border-rule sm:grid-cols-2 xl:grid-cols-4">
      {items.map((s) => (
        <button
          key={s.label}
          type="button"
          onClick={() => setLane(s.lane)}
          className="border-rule px-4 py-3 text-left transition-colors hover:bg-sheet sm:border-l sm:first:border-l-0 xl:[&:nth-child(3)]:border-l"
        >
          <p className="flex items-baseline gap-2">
            <span className={`font-label text-[26px] font-semibold leading-none ${s.tone}`}>{s.value}</span>
            <span className="text-[15px] text-ink">{s.label}</span>
          </p>
          <p className="mt-1.5 font-label text-[12px] text-ink-dim">{s.source}</p>
        </button>
      ))}
    </div>
  )
}

function ViewHeading({ lane, ov }: { lane: Lane; ov: Overview | null }) {
  const text: Record<Lane, [string, string]> = {
    decide: ['Needs your decision', 'Judgment calls Claude made and supplier emails it would not guess on, largest dollars first.'],
    rules: ['Settled by rules', 'Honor and absorb decisions the policy settles by itself, grouped by price change.'],
    done: ['Done', 'What each person decided next to what was proposed, and the outbox. Every decision can be undone.'],
    quote: ['Quote check', 'Before a quote goes out: will a price change already on file land while it is still valid?'],
    leakage: ['Leakage', 'Margin won jobs already lost because costs moved between quote and order.'],
    data: ['Data', `Quotes, customers and materials behind every number${ov ? `, as of ${shortDate(ov.as_of)}` : ''}.`],
  }
  const [title, sub] = text[lane]
  return (
    <div>
      <h1 className="font-label text-[26px] font-semibold text-ink-bright">{title}</h1>
      <p className="mt-0.5 text-[15px] text-ink-dim">{sub}</p>
    </div>
  )
}

function FilterChip({ id, email, onClear }: { id: string; email?: string; onClear: () => void }) {
  return (
    <div className="mt-3 flex items-center gap-3 rounded-sm border border-rule-bright bg-sheet px-3 py-2 text-sm">
      <span className="text-ink">
        Only cards from <span className="font-semibold text-ink-bright">{id}</span>
        {email ? <span className="text-ink-dim"> · {email}</span> : null}
      </span>
      <button type="button" onClick={onClear} className="ml-auto font-label text-[13px] font-semibold text-ink-dim hover:text-ink-bright">
        Show all
      </button>
    </div>
  )
}

export default App
