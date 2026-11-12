/**
 * useConsole: all console state in one place.
 *
 * Data comes from plain GETs. The SSE stream (/api/stream) only says that
 * something changed, plus a human-readable line for the activity feed; any
 * message triggers a debounced refetch, so the screen can never drift from
 * the database.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { api, type Lane } from '../lib/api'
import { materialLabel, setFamilies, usd } from '../lib/format'
import type { DemoEmail, Email, FeedItem, Leakage, Material, OutboxItem, Overview, Proposal } from '../lib/types'

type Msg = Record<string, unknown>

function describe(kind: string, d: Msg): Omit<FeedItem, 'id' | 'at'> | null {
  switch (kind) {
    case 'email.received':
      return { tone: 'info', text: `New email from ${d.from}: "${d.subject}"` }
    case 'email.reading':
      return { tone: 'claude', text: `Claude is reading ${d.email_id}…` }
    case 'email.processed': {
      const outcome = String(d.outcome)
      const text: Record<string, string> = {
        detected: 'price change confirmed',
        duplicate: 'already on file, nothing to do',
        needs_review: 'unclear, sent to you for a look',
        ignored: 'not a price change',
        error: 'could not be read',
      }
      const tone = outcome === 'error' ? 'fault' : outcome === 'needs_review' ? 'attention' : 'good'
      return { tone, text: `${d.email_id}: ${text[outcome] ?? outcome}` }
    }
    case 'event.started':
      return d.event_type === 'price_change.detected'
        ? { tone: 'info', text: `Finding open quotes that use ${materialLabel(String(d.label))}…` }
        : null
    case 'decision.started':
      return { tone: 'claude', text: `Claude is deciding ${d.quote_id} (${d.customer})` }
    case 'event.processed': {
      const r = (d.result ?? {}) as Msg
      if (r.error) return { tone: 'fault', text: `Failed on ${d.label}: ${r.error}` }
      if (r.review_reasons) return null
      if (r.note) return { tone: 'good', text: `${materialLabel(String(d.label))}: ${r.note}` }
      const n = Number(r.affected_quotes ?? 0)
      return { tone: 'good', text: `${materialLabel(String(d.label))}: ${n} quote${n === 1 ? '' : 's'} checked, ${usd(Number(r.exposure_usd ?? 0))} exposure` }
    }
    case 'rules.confirmed':
      return { tone: 'good', text: `Confirmed ${d.count} rule decisions` }
    case 'job.failed':
      return { tone: 'fault', text: `Agents stopped: ${d.error}` }
    default:
      return null
  }
}

const LANES: Lane[] = ['home', 'decide', 'rules', 'done', 'quote', 'leakage', 'outcomes', 'inbox', 'imports', 'data']
const laneFromHash = (): Lane | null => {
  const h = window.location.hash.replace('#', '') as Lane
  return LANES.includes(h) ? h : null
}

export function useConsole() {
  // Each view has its own URL (#decide, #leakage, ...), so a view can be linked or reloaded.
  const [lane, setLaneState] = useState<Lane>(() => laneFromHash() ?? 'home')
  const setLane = useCallback((l: Lane) => {
    setLaneState(l)
    if (window.location.hash !== `#${l}`) window.history.replaceState(null, '', `#${l}`)
  }, [])
  useEffect(() => {
    const onHash = () => { const l = laneFromHash(); if (l) setLaneState(l) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  /** Show only the cards that came from one supplier email (null = all). */
  const [emailFilter, setEmailFilter] = useState<string | null>(null)
  /** Quote to open in the Data tab when jumping there from a card. */
  const [focusedQuote, setFocusedQuote] = useState<string | null>(null)
  /** Bumped on every refresh, so the Data tab knows to reload. */
  const [version, setVersion] = useState(0)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [cards, setCards] = useState<Proposal[]>([])
  const [inbox, setInbox] = useState<Email[]>([])
  const [outbox, setOutbox] = useState<OutboxItem[]>([])
  const [materials, setMaterials] = useState<Material[]>([])
  const [demoEmails, setDemoEmails] = useState<DemoEmail[]>([])
  const [feed, setFeed] = useState<FeedItem[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [arrived, setArrived] = useState<Set<number>>(new Set())
  const [leakage, setLeakage] = useState<Leakage | null>(null)

  const laneRef = useRef(lane)
  laneRef.current = lane
  const filterRef = useRef(emailFilter)
  filterRef.current = emailFilter
  const known = useRef<Set<number> | null>(null)
  const seq = useRef(0)
  const timer = useRef<number | undefined>(undefined)

  const refresh = useCallback(async () => {
    try {
      const current = laneRef.current
      const queueLane = current === 'decide' || current === 'rules' || current === 'done' ? current : null
      const [ov, queue, mail, out, leak] = await Promise.all([
        api.overview(),
        queueLane ? api.queue(queueLane, filterRef.current) : Promise.resolve([] as Proposal[]),
        api.inbox(),
        api.outbox(),
        api.leakage().catch(() => null),
      ])
      setVersion((v) => v + 1)
      setOverview(ov)
      setBusy(ov.agents_busy)
      setInbox(mail)
      setOutbox(out)
      setLeakage(leak)
      // Highlight cards that appeared since the last refresh of the (unfiltered) decision lane.
      if (current === 'decide' && !filterRef.current) {
        const ids = new Set(queue.map((p) => p.id))
        if (known.current) setArrived(new Set([...ids].filter((id) => !known.current!.has(id))))
        known.current = ids
      }
      setCards(queue)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  const soon = useCallback(() => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(refresh, 250)
  }, [refresh])

  useEffect(() => {
    refresh()
    api.materials().then((m) => { setFamilies(m); setMaterials(m) }).catch(() => {})
    api.demoEmails().then(setDemoEmails).catch(() => {})
  }, [refresh])

  useEffect(() => {
    setCards([])
    refresh()
  }, [lane, emailFilter, refresh])

  /** Jump from an inbox email to the cards it produced. */
  const focusEmail = useCallback((emailId: string, target: Lane) => {
    setEmailFilter(emailId)
    setLane(target)
  }, [])

  /** Jump from a card to the quote behind it. */
  const focusQuote = useCallback((quoteId: string) => {
    setFocusedQuote(quoteId)
    setLane('data')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  useEffect(() => {
    const es = new EventSource('/api/stream')
    const kinds = ['hello', 'email.received', 'email.reading', 'email.processed', 'event.started', 'decision.started',
      'event.processed', 'proposal.reviewed', 'rules.confirmed', 'outcome.recorded', 'backlog.changed', 'job.started', 'job.finished', 'job.failed']
    const handler = (ev: MessageEvent) => {
      const data = JSON.parse(ev.data) as Msg
      if (ev.type === 'job.started') setBusy(true)
      if (ev.type === 'job.finished' || ev.type === 'job.failed') setBusy(false)
      if (ev.type === 'hello') setBusy(Boolean(data.agents_busy))
      const line = describe(ev.type, data)
      if (line) {
        const at = new Date().toLocaleTimeString('en-US', { hour12: false })
        setFeed((f) => [{ id: ++seq.current, at, ...line }, ...f].slice(0, 60))
      }
      // Progress lines arrive fast; only refetch on messages that change data.
      if (!['email.reading', 'event.started', 'decision.started', 'hello'].includes(ev.type)) soon()
    }
    kinds.forEach((k) => es.addEventListener(k, handler as EventListener))
    return () => es.close()
  }, [soon])

  const run = useCallback(async (fn: () => Promise<unknown>) => {
    try {
      await fn()
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      soon()
    }
  }, [soon])

  return {
    lane, setLane, emailFilter, setEmailFilter, focusEmail, focusedQuote, setFocusedQuote, focusQuote, version,
    overview, cards, inbox, outbox, materials, demoEmails, feed, busy, error, arrived, run, leakage,
  }
}
