import { useEffect, useState, type ReactNode } from 'react'

import { api } from '../lib/api'
import { materialLabel, pct, shortDate, usd } from '../lib/format'
import type { Backlog, Leakage, Overview, Proposal } from '../lib/types'
import { isQuote } from '../lib/types'

const monthLabel = (m: string) => new Date(`${m}-15T12:00:00`).toLocaleDateString('en-US', { month: 'short' })
const monthName = (m: string) => new Date(`${m}-15T12:00:00`).toLocaleDateString('en-US', { month: 'long' })
const weekday = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString('en-US', { weekday: 'long' })

/** Where a Home link goes: a lane, and what to show there first. */
export type HomeTarget =
  | { lane: 'decide'; filter?: 'questions' | `customer:${string}` }
  | { lane: 'rules' | 'done' }
  | { lane: 'leakage'; tab: 'orders' | 'leaked'; material?: string; quote?: string }

const link = 'shrink-0 text-go hover:text-go-soft'

/** One kind of work waiting: a count, a sentence, a dollar line, and the button to start it. */
function NeedRow({ n, title, sub, subTone = 'text-ink-dim', action, primary, onClick }: {
  n: number; title: string; sub: string; subTone?: string; action: string; primary: boolean; onClick: () => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-rule-soft px-5 py-[18px] last:border-b-0 sm:flex-nowrap">
      <div className="min-w-11 text-2xl font-semibold text-ink">{n}</div>
      <div className="min-w-0 flex-[1_1_14rem]">
        <div className="font-semibold text-ink">{title}</div>
        <div className={`text-[13px] ${subTone}`}>{sub}</div>
      </div>
      <button type="button" onClick={onClick}
        className={`min-h-11 shrink-0 whitespace-nowrap rounded-sm px-[18px] transition-colors ${primary
          ? 'bg-go font-semibold text-ground hover:bg-go-soft'
          : 'border border-rule-bright text-ink hover:border-ink-dim'}`}>
        {action}
      </button>
    </div>
  )
}

function Insight({ children, action, onClick }: { children: ReactNode; action: string; onClick: () => void }) {
  return (
    <div className="flex flex-wrap justify-between gap-x-5 gap-y-1.5 border-t border-rule py-3.5 last:border-b">
      <span className="min-w-0 flex-[1_1_380px]">{children}</span>
      <button type="button" onClick={onClick} className={link}>{action}</button>
    </div>
  )
}

/** The landing page, for the owner: what needs a person now, a few facts worth knowing,
 *  and where margin has leaked. Every sentence is computed here from existing endpoints. */
export function HomeLane({ ov, leak, version, go }: {
  ov: Overview
  leak: Leakage | null
  version: number
  go: (t: HomeTarget) => void
}) {
  const [cards, setCards] = useState<Proposal[] | null>(null)
  const [backlog, setBacklog] = useState<Backlog | null>(null)
  useEffect(() => {
    api.queue('decide').then(setCards).catch(() => setCards([]))
    api.backlog().then(setBacklog).catch(() => setBacklog(null))
  }, [version])

  const quotes = (cards ?? []).filter(isQuote)
  const below = quotes.filter((p) => p.facts.margin_after < p.facts.margin_floor)
  const belowUsd = below.reduce((s, p) => s + p.facts.exposure_usd, 0)
  const questions = (cards ?? []).filter((p) => p.kind === 'event_review')

  type Need = { key: string; n: number; title: string; sub: string; subTone?: string; action: string; to: HomeTarget }
  const allNeeds: Need[] = [
    { key: 'below', n: below.length, title: `Quote${below.length === 1 ? '' : 's'} fell below ${below.length === 1 ? 'its' : 'their'} margin floor`,
      sub: `${usd(belowUsd)} at risk if ${below.length === 1 ? 'it is' : 'they are'} accepted as quoted`, subTone: 'text-stop',
      action: 'Start deciding', to: { lane: 'decide' } },
    { key: 'questions', n: questions.length, title: `Supplier ${questions.length === 1 ? 'question needs' : 'questions need'} an answer`,
      sub: 'The agents will not guess, so these wait for you', action: 'Answer', to: { lane: 'decide', filter: 'questions' } },
    { key: 'backlog', n: backlog?.orders_absorbing ?? 0,
      title: `Won order${backlog?.orders_absorbing === 1 ? '' : 's'} will absorb ${usd(backlog?.absorbing_usd ?? 0)} of increases`,
      sub: backlog?.buy_now_saves_usd ? `Buying their material now saves ${usd(backlog.buy_now_saves_usd)}` : 'Their prices are fixed, so the increases come out of margin',
      action: 'Review orders', to: { lane: 'leakage', tab: 'orders' } },
    { key: 'rules', n: ov.rule_pending, title: `Quote${ov.rule_pending === 1 ? ' was' : 's were'} settled by rules`,
      sub: 'Honor or absorb, ready to confirm in bulk', action: 'Confirm', to: { lane: 'rules' } },
  ]
  const needs = allNeeds.filter((x) => x.n > 0)

  // Worth knowing: each one is a sum or a maximum over rows the console already has.
  const material = leak?.by_material.find((m) => m.leak_usd > 0)
  const byCustomer = new Map<string, { id: string; name: string; n: number; usd: number }>()
  for (const p of below) {
    const c = byCustomer.get(p.facts.customer_id) ?? { id: p.facts.customer_id, name: p.facts.customer_name, n: 0, usd: 0 }
    c.n += 1
    c.usd += p.facts.exposure_usd
    byCustomer.set(c.id, c)
  }
  const customer = [...byCustomer.values()].sort((a, b) => b.usd - a.usd)[0]
  const months = [...(leak?.by_month ?? [])].filter((m) => m.leak_usd > 0).sort((a, b) => b.leak_usd - a.leak_usd).slice(0, 2)
    .sort((a, b) => a.month.localeCompare(b.month))
  const buy = [...(backlog?.orders ?? [])].filter((o) => o.buy_now_saves_usd > 0).sort((a, b) => b.buy_now_saves_usd - a.buy_now_saves_usd)[0]

  const allMonths = leak?.by_month ?? []
  const peak = Math.max(...allMonths.map((m) => m.leak_usd), 1)
  const top = [...allMonths].filter((m) => m.leak_usd > 0).sort((a, b) => b.leak_usd - a.leak_usd).slice(0, 3)
  const materials = (leak?.by_material ?? []).filter((m) => m.leak_usd > 0).slice(0, 5)
  const widest = Math.max(...materials.map((m) => m.leak_usd), 1)

  return (
    // One column up to 1280px wide; past that, the work on the left and where margin leaked on the right,
    // so a wide screen is filled instead of leaving a narrow strip in the middle.
    <div className="mx-auto flex max-w-[760px] flex-col gap-7 xl:max-w-[1280px]">
      <div>
        <h1 className="text-[28px] font-bold text-ink">Home</h1>
        <p className="mt-1 text-ink-dim">{weekday(ov.as_of)}, {shortDate(ov.as_of)}. Here is what changed and what needs you.</p>
      </div>

      <div className="grid gap-7 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] xl:items-start">
      <div className="flex min-w-0 flex-col gap-7">
      <section className="flex flex-col gap-2.5">
        <h2 className="text-base font-semibold text-ink">Needs you</h2>
        {cards === null ? <p className="text-ink-dim">Loading…</p> : needs.length ? (
          <div className="rounded-lg border border-rule bg-sheet">
            {needs.map((x, i) => (
              <NeedRow key={x.key} n={x.n} title={x.title} sub={x.sub} subTone={x.subTone} action={x.action} primary={i === 0} onClick={() => go(x.to)} />
            ))}
          </div>
        ) : (
          <p className="text-ink">
            Nothing needs you right now. <button type="button" className={link} onClick={() => go({ lane: 'done' })}>See what was decided</button>
          </p>
        )}
      </section>

      {material || customer || months.length === 2 || buy ? (
        <section className="flex flex-col gap-2.5">
          <h2 className="text-base font-semibold text-ink">Worth knowing</h2>
          <div className="flex flex-col">
            {material ? (
              <Insight action="See those jobs" onClick={() => go({ lane: 'leakage', tab: 'leaked', material: material.material_id })}>
                {materialLabel(material.material_id)} has leaked the most: {usd(material.leak_usd)} across {material.jobs} won job{material.jobs === 1 ? '' : 's'}.
              </Insight>
            ) : null}
            {customer ? (
              <Insight action={customer.n === 1 ? 'Open it' : customer.n === 2 ? 'Open both' : `Open all ${customer.n}`}
                onClick={() => go({ lane: 'decide', filter: `customer:${customer.id}` })}>
                {customer.name} has {customer.n} quote{customer.n === 1 ? '' : 's'} below floor, {usd(customer.usd)} at risk.
              </Insight>
            ) : null}
            {months.length === 2 && leak ? (
              <Insight action="See by month" onClick={() => go({ lane: 'leakage', tab: 'leaked' })}>
                {monthName(months[0].month)} and {monthName(months[1].month)} account for {usd(months[0].leak_usd + months[1].leak_usd)} of
                the {usd(leak.leaked_usd)} leaked this year.
              </Insight>
            ) : null}
            {buy ? (
              <Insight action="Review order" onClick={() => go({ lane: 'leakage', tab: 'orders', quote: buy.quote_id })}>
                Buying material for {buy.customer_name}'s order now saves {usd(buy.buy_now_saves_usd)}, the largest single saving.
              </Insight>
            ) : null}
          </div>
        </section>
      ) : null}
      </div>

      {/* Lines up with the top of the Needs you box (its heading is 24px plus a 10px gap). */}
      <div className="flex min-w-0 flex-col gap-4 xl:pt-[34px]">
      {leak?.period ? (
        <button type="button" onClick={() => go({ lane: 'leakage', tab: 'leaked' })}
          className="flex flex-wrap items-end justify-between gap-5 rounded-lg bg-sheet p-5 text-left transition-colors hover:bg-sheet-2">
          <div className="flex flex-col gap-7">
            <div>
              <div className="font-semibold text-stop">Leaked on won jobs</div>
              <div className="text-[13px] text-ink-dim">{leak.jobs_leaked} of {leak.won_jobs} jobs since {shortDate(leak.period.from)}, by order month</div>
            </div>
            <div>
              <div className="text-[34px] font-semibold leading-none text-ink">{usd(leak.leaked_usd)}</div>
              <div className="pt-1.5 text-[13px] text-ink-dim">Margin went from {pct(leak.margin_quoted)} as quoted to {pct(leak.margin_realized)} as ordered</div>
            </div>
          </div>
          <div role="img" className="flex h-[120px] min-w-[16rem] flex-1 items-end justify-between gap-1.5"
            aria-label={`Leakage by order month. ${top.map((m, i) => `${i === 0 ? '' : i === top.length - 1 ? 'and ' : ''}${monthName(m.month)} ${i === 0 ? 'was highest at ' : 'at '}${usd(m.leak_usd)}`).join(', ')}.`}>
            {allMonths.map((m) => (
              <div key={m.month} className="flex flex-1 flex-col items-center gap-1.5" title={`${monthName(m.month)}: ${usd(m.leak_usd)} on ${m.jobs} job${m.jobs === 1 ? '' : 's'}`}>
                <div className="w-full max-w-[26px] rounded-[2px] bg-stop" style={{ height: `${Math.max(1, Math.round((Math.max(m.leak_usd, 0) / peak) * 94))}px` }} />
                <div className="text-xs text-ink-dim">{monthLabel(m.month)}</div>
              </div>
            ))}
          </div>
        </button>
      ) : null}

      {materials.length ? (
        <section className="flex flex-col gap-3.5 rounded-lg bg-sheet p-5">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="font-semibold text-ink">Where it leaked</h2>
            <button type="button" onClick={() => go({ lane: 'leakage', tab: 'leaked' })} className={link}>See every job</button>
          </div>
          <ul className="flex flex-col gap-3.5">
            {materials.map((m) => (
              <li key={m.material_id} className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_4.5rem] items-center gap-3.5 sm:grid-cols-[190px_minmax(0,1fr)_64px] xl:grid-cols-[minmax(0,8rem)_minmax(0,1fr)_4.5rem]">
                <span className="truncate" title={m.material_name}>{materialLabel(m.material_id)}</span>
                <span className="h-3.5 rounded-[2px] bg-rule-soft" aria-hidden>
                  <span className="block h-3.5 rounded-[2px] bg-stop" style={{ width: `${(m.leak_usd / widest) * 100}%` }} />
                </span>
                <span className="text-right font-semibold tabular-nums">{usd(m.leak_usd)}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      </div>
      </div>
    </div>
  )
}
