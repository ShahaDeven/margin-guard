import type { QuoteFacts } from './types'

/** What if the cost moves behind a card came in at `k` times their size?
 *
 *  A lens for the estimator, never a decision input: it scales each line's added
 *  unit cost and recomputes margin after and dollars at risk the same way
 *  impact.py does (quantity-weighted, replacement cost). k = 1 returns the facts as
 *  they are. Approving always uses the real numbers. */
export function whatIf(f: QuoteFacts, k: number): QuoteFacts {
  if (k === 1) return f
  let revenue = 0
  let before = 0
  let after = 0
  for (const ln of f.lines) {
    const scaled = ln.unit_cost_before + (ln.unit_cost_after - ln.unit_cost_before) * k
    revenue += ln.qty * ln.unit_price
    before += ln.qty * ln.unit_cost_before
    after += ln.qty * scaled
  }
  if (!revenue) return f
  return {
    ...f,
    margin_after: 1 - after / revenue,
    exposure_usd: f.can_accept_after_change ? Math.round((after - before) * 100) / 100 : 0,
  }
}
