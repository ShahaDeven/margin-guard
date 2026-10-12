import { DataLane } from './components/DataLane'
import { DecisionCard } from './components/DecisionCard'
import { DoneLane } from './components/DoneLane'
import { ReviewCard } from './components/ReviewCard'
import { Empty, RulesLane } from './components/RulesLane'
import { Sidebar } from './components/Sidebar'
import { useConsole } from './hooks/useConsole'
import { api, type Lane } from './lib/api'
import { shortDate, usd } from './lib/format'
import { isQuote, type Overview } from './lib/types'

function App() {
  const c = useConsole()
  const ov = c.overview
  const quoteCards = c.cards.filter(isQuote)
  const reviewCards = c.cards.filter((p) => p.kind === 'event_review')

  return (
    <div className="mx-auto flex min-h-full max-w-7xl flex-col px-6 py-8">
      <Header ov={ov} busy={c.busy} />
      {ov ? <Stats ov={ov} /> : null}

      {c.error ? (
        <p className="mt-4 rounded border border-signal/40 bg-signal/5 px-4 py-2 font-mono text-xs text-signal">{c.error}</p>
      ) : null}

      <div className="mt-6 grid flex-1 gap-6 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <Sidebar
          inbox={c.inbox}
          demoEmails={c.demoEmails}
          feed={c.feed}
          busy={c.busy}
          onSend={(id) => c.run(() => api.sendDemoEmail(id))}
          onShowCards={c.focusEmail}
        />

        <main>
          <Tabs lane={c.lane} setLane={c.setLane} ov={ov} />
          {c.emailFilter && c.lane !== 'data' ? (
            <FilterChip
              email={c.inbox.find((m) => m.id === c.emailFilter)?.subject}
              id={c.emailFilter}
              onClear={() => c.setEmailFilter(null)}
            />
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
                {quoteCards.map((p) => (
                  <DecisionCard
                    key={p.id}
                    p={p}
                    fresh={c.arrived.has(p.id)}
                    onReview={(body) => c.run(() => api.review(p.id, body))}
                    onViewQuote={c.focusQuote}
                  />
                ))}
                {!c.cards.length ? <Empty text="Nothing needs you right now." /> : null}
              </>
            ) : null}
            {c.lane === 'rules' ? (
              <RulesLane cards={quoteCards} onConfirm={(eventId) => c.run(() => api.confirmRules(eventId))} />
            ) : null}
            {c.lane === 'done' ? (
              <DoneLane cards={c.cards} outbox={c.outbox} onReopen={(id) => c.run(() => api.reopen(id))} onViewQuote={c.focusQuote} />
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

      <footer className="mt-10 border-t border-line pt-4 font-mono text-[10px] text-silver-dim">
        Rules decide the clear cases. Claude decides the judgment calls and drafts the message. Code does every
        number. A person approves everything.
      </footer>
    </div>
  )
}

function FilterChip({ id, email, onClear }: { id: string; email?: string; onClear: () => void }) {
  return (
    <div className="mt-3 flex items-center gap-3 rounded border border-purple/40 bg-purple/5 px-3 py-2 text-sm">
      <span className="font-mono text-[10px] uppercase tracking-wider text-purple">Filtered</span>
      <span className="text-silver">
        Only cards from <span className="text-silver-bright">{id}</span>
        {email ? <span className="text-silver-dim"> · {email}</span> : null}
      </span>
      <button type="button" onClick={onClear} className="ml-auto font-mono text-[11px] text-silver-dim hover:text-silver-bright">
        SHOW ALL ✕
      </button>
    </div>
  )
}

function Header({ ov, busy }: { ov: Overview | null; busy: boolean }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
      <div>
        <h1 className="font-mono text-lg font-semibold tracking-[0.18em] text-silver-bright">
          MARGIN<span className="text-purple">GUARD</span>
        </h1>
        <p className="mt-1 text-sm text-silver-dim">When a supplier changes a price, see which open quotes it hurts and what to do.</p>
      </div>
      <div className="flex items-center gap-3 font-mono text-[11px] tracking-wider text-silver-dim">
        {ov ? <span>SHOP DATE {shortDate(ov.as_of).toUpperCase()} · {ov.model}</span> : null}
        <span className={`inline-flex items-center gap-2 rounded-full border border-line bg-panel px-3 py-1 ${busy ? 'text-purple' : 'text-cyan'}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${busy ? 'bg-purple mg-breathe' : 'bg-cyan'}`} />
          {busy ? 'AGENTS WORKING' : 'AGENTS IDLE'}
        </span>
      </div>
    </header>
  )
}

function Stats({ ov }: { ov: Overview }) {
  const items = [
    { label: 'Need your decision', value: String(ov.needs_you), sub: `${usd(ov.needs_you_exposure)} at risk`, tone: 'text-hiviz' },
    { label: 'Settled by rules', value: String(ov.rule_pending), sub: 'confirm in bulk', tone: 'text-silver-bright' },
    { label: 'Total exposure', value: usd(ov.live_exposure), sub: 'on open cards', tone: 'text-silver-bright' },
    { label: 'Done', value: String(ov.done), sub: `${ov.outbox} in outbox`, tone: 'text-cyan' },
  ]
  return (
    <div className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line md:grid-cols-4">
      {items.map((s) => (
        <div key={s.label} className="bg-panel px-5 py-4">
          <p className="font-mono text-[10px] uppercase tracking-wider text-silver-dim">{s.label}</p>
          <p className={`mt-1 font-mono text-2xl ${s.tone}`}>{s.value}</p>
          <p className="text-xs text-silver-dim">{s.sub}</p>
        </div>
      ))}
    </div>
  )
}

function Tabs({ lane, setLane, ov }: { lane: Lane; setLane: (l: Lane) => void; ov: Overview | null }) {
  const tabs: { id: Lane; label: string; count?: number }[] = [
    { id: 'decide', label: 'Needs your decision', count: ov?.needs_you },
    { id: 'rules', label: 'Settled by rules', count: ov?.rule_pending },
    { id: 'done', label: 'Done', count: ov?.done },
    { id: 'data', label: 'Data' },
  ]
  return (
    <nav className="flex gap-1 border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => setLane(t.id)}
          className={`-mb-px border-b-2 px-4 py-2.5 text-sm transition-colors ${
            lane === t.id ? 'border-purple text-silver-bright' : 'border-transparent text-silver-dim hover:text-silver'
          }`}
        >
          {t.label}
          {t.count != null ? <span className="ml-2 font-mono text-xs text-silver-dim">{t.count}</span> : null}
        </button>
      ))}
    </nav>
  )
}

export default App
