import { useEffect, useState } from 'react'

import { api } from '../lib/api'
import { shortDate, usd } from '../lib/format'
import type { Backlog, Leakage, Overview, Proposal } from '../lib/types'
import { isQuote } from '../lib/types'
import { FIGURE } from './MarginBar'

const monthLabel = (m: string) => new Date(`${m}-15T12:00:00`).toLocaleDateString('en-US', { month: 'short' })
const monthName = (m: string) => new Date(`${m}-15T12:00:00`).toLocaleDateString('en-US', { month: 'long' })
const weekday = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString('en-US', { weekday: 'long' })

/** Where a Home link goes: a lane, and what to show there first. */
export type HomeTarget =
  | { lane: 'decide'; filter?: 'questions' | `customer:${string}` }
  | { lane: 'rules' | 'done' }
  | { lane: 'leakage'; tab: 'orders' | 'leaked'; material?: string; quote?: string }

const link = 'shrink-0 text-go hover:text-go-soft'

/** One kind of work waiting: a count, a sentence, a figure line, and the button to start it. */
function NeedRow({ n, title, sub, subTone = 'text-ink-dim', action, primary, onClick }: {
  n: number; title: string; sub: string; subTone?: string; action: string; primary: boolean; onClick: () => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-rule-soft px-5 py-[18px] last:border-b-0 sm:flex-nowrap">
      <div className={`${FIGURE} min-w-11 text-[28px] leading-none text-ink`}>{n}</div>
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

/** The owner's landing page, answering four questions at a glance: how much margin is at
 *  risk, which decisions need attention, which won orders will absorb increases, and how
 *  much has already leaked. Everything else lives in the reports. */
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
  // The same count Leakage leads with: won orders still to buy that absorb increases.
  const absorbing = backlog?.orders_absorbing ?? 0

  type Need = { key: string; n: number; title: string; sub: string; subTone?: string; action: string; to: HomeTarget }
  const allNeeds: Need[] = [
    { key: 'below', n: below.length, title: `Quote${below.length === 1 ? '' : 's'} fell below ${below.length === 1 ? 'its' : 'their'} margin floor`,
      sub: `${usd(belowUsd)} at risk if accepted as quoted`, subTone: 'text-stop',
      action: 'Start deciding', to: { lane: 'decide' } },
    { key: 'questions', n: questions.length, title: `Supplier email${questions.length === 1 ? ' needs' : 's need'} an answer`,
      sub: 'The agents will not guess, so these wait for you', action: 'Answer', to: { lane: 'decide', filter: 'questions' } },
    { key: 'backlog', n: absorbing,
      title: `Won order${absorbing === 1 ? '' : 's'} will absorb ${usd(backlog?.absorbing_usd ?? 0)} of increases`,
      sub: backlog?.buy_now_saves_usd ? `Buying their material now saves ${usd(backlog.buy_now_saves_usd)}` : 'Their prices are fixed, so the increases come out of margin',
      action: 'Review orders', to: { lane: 'leakage', tab: 'orders' } },
    { key: 'rules', n: ov.rule_pending, title: `Quote${ov.rule_pending === 1 ? ' was' : 's were'} settled by rules`,
      sub: 'Ready to confirm in bulk', action: 'Confirm', to: { lane: 'rules' } },
  ]
  const needs = allNeeds.filter((x) => x.n > 0)

  // One computed line, kept only because it leads to an action: the customer with the most
  // at risk below floor, when that is more than one quote.
  const byCustomer = new Map<string, { id: string; name: string; n: number; usd: number }>()
  for (const p of below) {
    const c = byCustomer.get(p.facts.customer_id) ?? { id: p.facts.customer_id, name: p.facts.customer_name, n: 0, usd: 0 }
    c.n += 1
    c.usd += p.facts.exposure_usd
    byCustomer.set(c.id, c)
  }
  const customer = [...byCustomer.values()].filter((c) => c.n > 1).sort((a, b) => b.usd - a.usd)[0]

  const months = leak?.by_month ?? []
  const peak = Math.max(...months.map((m) => m.leak_usd), 1)
  const top = [...months].filter((m) => m.leak_usd > 0).sort((a, b) => b.leak_usd - a.leak_usd).slice(0, 3)

  return (
    <div className="mx-auto flex max-w-[760px] flex-col gap-7">
      <div>
        <h1 className="text-[28px] font-bold text-ink">Home</h1>
        <p className="mt-1 text-ink-dim">{weekday(ov.as_of)}, {shortDate(ov.as_of)}. Here is what needs you.</p>
      </div>

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
        {customer ? (
          <p className="flex flex-wrap justify-between gap-x-5 gap-y-1 px-1 pt-1 text-ink">
            <span>{customer.name} has {customer.n} quotes below floor, {usd(customer.usd)} at risk.</span>
            <button type="button" className={link} onClick={() => go({ lane: 'decide', filter: `customer:${customer.id}` })}>
              {customer.n === 2 ? 'Open both' : `Open all ${customer.n}`}
            </button>
          </p>
        ) : null}
      </section>

      {leak?.period ? (
        <section className="flex flex-col gap-2.5">
          <h2 className="text-base font-semibold text-ink">Already leaked</h2>
          <div className="flex flex-wrap items-end justify-between gap-5 rounded-lg bg-sheet p-5">
            <div className="flex flex-col gap-7">
              <div>
                <div className="font-semibold text-stop">Leaked on won jobs</div>
                <div className="text-[13px] text-ink-dim">{leak.jobs_leaked} of {leak.won_jobs} won jobs since {shortDate(leak.period.from)}</div>
              </div>
              <div>
                <div className={`${FIGURE} text-[34px] leading-none text-ink`}>{usd(leak.leaked_usd)}</div>
                <button type="button" className={`${link} mt-2 text-[13px]`} onClick={() => go({ lane: 'leakage', tab: 'leaked' })}>See leakage</button>
              </div>
            </div>
            <div role="img" className="flex h-[120px] min-w-[16rem] flex-1 items-end justify-between gap-1.5"
              aria-label={`Leakage by order month. ${top.map((m, i) => `${i === 0 ? '' : i === top.length - 1 ? 'and ' : ''}${monthName(m.month)} ${i === 0 ? 'was highest at ' : 'at '}${usd(m.leak_usd)}`).join(', ')}.`}>
              {months.map((m) => (
                <div key={m.month} className="flex flex-1 flex-col items-center gap-1.5" title={`${monthName(m.month)}: ${usd(m.leak_usd)} on ${m.jobs} job${m.jobs === 1 ? '' : 's'}`}>
                  <div className="w-full max-w-[26px] rounded-[2px] bg-stop" style={{ height: `${Math.max(1, Math.round((Math.max(m.leak_usd, 0) / peak) * 94))}px` }} />
                  <div className="text-xs text-ink-dim">{monthLabel(m.month)}</div>
                </div>
              ))}
            </div>
          </div>
        </section>
      ) : null}
    </div>
  )
}
