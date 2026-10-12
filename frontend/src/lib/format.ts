import type { Action } from './types'

export const usd = (n: number, digits = 0) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: digits, maximumFractionDigits: digits })

export const unitPrice = (n: number) => `$${n.toFixed(n < 10 ? 4 : 2)}`

export const pct = (n: number, digits = 1) => `${(n * 100).toFixed(digits)}%`

export const signedPct = (n: number | null | undefined) =>
  n == null ? '' : `${n >= 0 ? '+' : ''}${(n * 100).toFixed(1)}%`

export const shortDate = (iso: string | null | undefined) =>
  iso ? new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : ''

/** Material ids are for machines; estimators see "EPDM 70". */
export const materialLabel = (id: string | null | undefined) =>
  id ? id.replace(/^MAT-/, '').replace(/-/g, ' ').replace(/^STL 1018$/, '1018 steel').replace(/^CB N550$/, 'Carbon black N550') : '?'

/** What each action means, in the words an estimator would use. */
export const ACTION_TEXT: Record<Action, { verb: string; short: string }> = {
  reprice: { verb: 'Send a revised quote', short: 'Revise quote' },
  contact_customer: { verb: 'Call the customer first', short: 'Call first' },
  absorb: { verb: 'Absorb the increase', short: 'Absorb' },
  honor: { verb: 'Honor the quote as issued', short: 'Honor' },
  escalate: { verb: 'Needs your call', short: 'Escalated' },
  resolve_event: { verb: 'Check the supplier email', short: 'Check email' },
}

export const CHOOSABLE: Action[] = ['reprice', 'contact_customer', 'absorb', 'honor']
