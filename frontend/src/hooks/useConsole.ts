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
import { materialLabel, usd } from '../lib/format'
import type { DemoEmail, Email, FeedItem, Material, OutboxItem, Overview, Proposal } from '../lib/types'

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
      return { tone: outcome === 'needs_review' ? 'attention' : 'good', text: `${d.email_id}: ${text[outcome] ?? outcome}` }
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

export function useConsole() {
  const [lane, setLane] = useState<Lane>('decide')
  /** Show only the cards that came from one supplier email (null = all). */
  const [emailFilter, setEmailFilter] = useState<string | null>(null)
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
      const [ov, queue, mail, out] = await Promise.all([
        api.overview(), api.queue(current, filterRef.current), api.inbox(), api.outbox(),
      ])
      setOverview(ov)
      setBusy(ov.agents_busy)
      setInbox(mail)
      setOutbox(out)
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
    api.materials().then(setMaterials).catch(() => {})
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

  useEffect(() => {
    const es = new EventSource('/api/stream')
    const kinds = ['hello', 'email.received', 'email.reading', 'email.processed', 'event.started', 'decision.started',
      'event.processed', 'proposal.reviewed', 'rules.confirmed', 'job.started', 'job.finished', 'job.failed']
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
    lane, setLane, emailFilter, setEmailFilter, focusEmail,
    overview, cards, inbox, outbox, materials, demoEmails, feed, busy, error, arrived, run,
  }
}
