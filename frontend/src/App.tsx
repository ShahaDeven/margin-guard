import { useState } from 'react'

import { DataLane } from './components/DataLane'
import { DecideLane, type DecideFilter } from './components/DecideLane'
import { DoneLane } from './components/DoneLane'
import { ImportsLane } from './components/ImportsLane'
import { HomeLane, type HomeTarget } from './components/HomeLane'
import { LeakagePage, type LeakageTab } from './components/LeakageLane'
import { NavSidebar } from './components/NavSidebar'
import { OutcomesLane } from './components/Outcomes'
import { QuoteCheckLane } from './components/QuoteCheckLane'
import { RulesLane } from './components/RulesLane'
import { DemoDrawer, InboxLane } from './components/Sidebar'
import { useConsole } from './hooks/useConsole'
import { api, type Lane } from './lib/api'
import { shortDate } from './lib/format'
import { isQuote, type Overview } from './lib/types'

function App() {
  const c = useConsole()
  const ov = c.overview
  const quoteCards = c.cards.filter(isQuote)
  const [demoOpen, setDemoOpen] = useState(false)
  const [decideFilter, setDecideFilter] = useState<DecideFilter>('all')
  const [leakTab, setLeakTab] = useState<LeakageTab>('orders')
  const [leakFocus, setLeakFocus] = useState<{ material?: string; quote?: string }>({})
  /** Follow a Home link: open the lane with the right filter or tab already set. */
  const go = (t: HomeTarget) => {
    if (t.lane === 'decide') setDecideFilter(t.filter ?? 'all')
    if (t.lane === 'leakage') { setLeakTab(t.tab); setLeakFocus({ material: t.material, quote: t.quote }) }
    c.setLane(t.lane)
    window.scrollTo({ top: 0 })
  }
  const queue = c.lane === 'decide' || c.lane === 'rules' || c.lane === 'done'
  const chip = c.emailFilter && queue ? (
    <FilterChip
      email={c.inbox.find((m) => m.id === c.emailFilter)?.subject}
      id={c.emailFilter}
      onClear={() => c.setEmailFilter(null)}
    />
  ) : null

  return (
    <div className="flex min-h-full flex-col lg:flex-row">
      <NavSidebar lane={c.lane} setLane={c.setLane} ov={ov} busy={c.busy} onOpenDemo={() => setDemoOpen(true)} />
      <DemoDrawer
        open={demoOpen}
        onClose={() => setDemoOpen(false)}
        asOf={ov?.as_of ?? null}
        model={ov?.model ?? null}
        demoEmails={c.demoEmails}
        feed={c.feed}
        busy={c.busy}
        onSend={(id) => c.run(() => api.sendDemoEmail(id))}
      />

      <div className="flex min-w-0 flex-1 flex-col">
      <div className="mx-auto w-full max-w-[96rem] flex-1 px-4 pb-10 pt-7 sm:px-7">
        {ov?.data_problems?.length ? (
          <div className="mt-4 rounded-sm border border-stop/50 bg-stop/5 px-4 py-2 text-sm text-ink">
            <span className="font-semibold text-stop">Costing data needs fixing.</span> Margins for these materials ignore every
            supplier's price until each has exactly one costing supplier:
            <ul className="mt-1 list-disc pl-5">{ov.data_problems.map((d) => <li key={d}>{d}</li>)}</ul>
          </div>
        ) : null}
        {c.error ? (
          <p className="mt-4 rounded-sm border border-stop/50 bg-stop/5 px-4 py-2 text-sm text-stop">{c.error}</p>
        ) : null}

        <div className="mt-6">
          <main className="min-w-0">
            {/* Home and To decide set their own headers. */}
            {c.lane !== 'decide' && c.lane !== 'home' ? <ViewHeading lane={c.lane} ov={ov} /> : null}
            {c.lane !== 'decide' ? chip : null}

            <div className="mt-4 space-y-3">
              {c.lane === 'decide' ? (
                <DecideLane
                  cards={c.cards}
                  inbox={c.inbox}
                  materials={c.materials}
                  arrived={c.arrived}
                  bar={ov?.autonomy?.threshold ?? null}
                  notice={chip}
                  filter={decideFilter}
                  setFilter={setDecideFilter}
                  onReview={(id) => (body) => c.run(() => api.review(id, body))}
                  onResolve={(id, mat) => c.run(() => api.resolve(id, mat))}
                  onDismiss={(id, note) => c.run(() => api.dismiss(id, note))}
                  onRedecide={(id) => c.run(() => api.redecide(id))}
                  onViewQuote={c.focusQuote}
                />
              ) : null}
              {c.lane === 'home' && ov ? <HomeLane ov={ov} leak={c.leakage} version={c.version} go={go} /> : null}
              {c.lane === 'inbox' ? <InboxLane inbox={c.inbox} onShowCards={c.focusEmail} /> : null}
              {c.lane === 'rules' ? (
                <RulesLane cards={quoteCards} onConfirm={(eventId) => c.run(() => api.confirmRules(eventId))} />
              ) : null}
              {c.lane === 'done' ? (
                <DoneLane cards={c.cards} outbox={c.outbox} onReopen={(id) => c.run(() => api.reopen(id))} onViewQuote={c.focusQuote}
                  onRecord={(id, body) => c.run(() => api.recordOutcome(id, body))} onUndoOutcome={(id) => c.run(() => api.undoOutcome(id))} />
              ) : null}
              {c.lane === 'outcomes' ? (
                <OutcomesLane version={c.version} onViewQuote={c.focusQuote}
                  onRecord={(id, body) => c.run(() => api.recordOutcome(id, body))} onUndo={(id) => c.run(() => api.undoOutcome(id))} />
              ) : null}
              {c.lane === 'imports' ? <ImportsLane onOpenDecide={() => c.setLane('decide')} /> : null}
              {c.lane === 'quote' ? <QuoteCheckLane inbox={c.inbox} onAnswer={() => go({ lane: 'decide', filter: 'questions' })} /> : null}
              {c.lane === 'leakage' ? (
                <LeakagePage tab={leakTab} setTab={(t) => { setLeakTab(t); setLeakFocus({}) }} r={c.leakage} version={c.version}
                  run={c.run} onViewQuote={c.focusQuote} focusMaterial={leakFocus.material} focusQuote={leakFocus.quote} />
              ) : null}
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
    </div>
  )
}

function ViewHeading({ lane, ov }: { lane: Lane; ov: Overview | null }) {
  const text: Record<Lane, [string, string]> = {
    decide: ['Needs your decision', 'Judgment calls Claude made and supplier emails it would not guess on, largest dollars first.'],
    rules: ['Settled by rules', 'Honor and absorb decisions the policy settles by itself, grouped by price change.'],
    done: ['Done', 'What each person decided next to what was proposed, and the outbox. Every decision can be undone.'],
    home: ['Home', ''],
    inbox: ['Supplier inbox', 'Every supplier email, how the agents read it, and what it led to.'],
    outcomes: ['Outcomes', 'What customers did after an increase went out: what was kept, what was negotiated away, which jobs walked.'],
    quote: ['Quote check', 'Before a quote goes out: will a price change already on file land while it is still valid?'],
    leakage: ['Leakage', 'Margin won jobs are about to absorb, and margin they have already lost, because costs moved after the quote.'],
    imports: ['Imports', 'Bring in an invoice export: match it, check it, then write it in one step.'],
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
