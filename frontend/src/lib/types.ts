export type Action = 'honor' | 'absorb' | 'reprice' | 'contact_customer' | 'escalate' | 'resolve_event'
export type Status = 'pending' | 'approved' | 'edited' | 'rejected' | 'superseded'

export interface Line {
  line_id: number
  part_id: string
  part_name: string
  uses_changed_material: boolean
  changed_materials?: string[]
  qty: number
  unit_price: number
  unit_cost_before: number
  unit_cost_after: number
  proposed_unit_price: number
}

export interface QuoteFacts {
  quote_id: string
  customer_id: string
  customer_name: string
  customer_tier: 'key' | 'standard'
  price_lock_until: string | null
  contract_note: string | null
  buyer?: { name: string | null; phone: string | null; email: string | null }
  account_manager?: { name: string | null; phone: string | null }
  issued_date: string
  valid_until: string
  material_id: string
  material_pct_change: number | null
  effective_date: string
  quote_value_usd: number
  margin_floor: number
  margin_before: number
  margin_after: number
  can_accept_after_change: boolean
  exposure_usd: number
  /** Every cost that moved since the quote went out, trigger first. */
  cost_changes?: CostChange[]
  lines: Line[]
  /** Set when an earlier-dated change arrived later and this card was recomputed. */
  restated?: { replaces_card: number; reason: string }
}

export interface CostChange {
  material_id: string
  cost_when_quoted: number
  cost_after: number
  pct_change: number
  effective_date: string | null
}

/** Payload of a vendor email that needs a person (ambiguous material, advisory, ...). */
export interface ReviewFacts {
  /** 'invoice_drift' when the question comes from an invoice, not an email. */
  kind?: 'invoice_drift'
  email_id: string | null
  vendor_name?: string
  material_id?: string | null
  old_cost_per_lb?: number | null
  pct_change?: number | null
  overpaid_usd?: number
  invoices?: { invoice_no: string; line_no: number; date: string; overpaid_usd: number }[]
  expected_row?: { id: number; effective_date: string; email_id: string | null } | null
  vendor_id: string | null
  material_text?: string
  match_candidates?: string[]
  new_cost_per_lb?: number | null
  effective_date?: string | null
  review_reasons?: string[]
  summary?: string
}

export interface Proposal {
  id: number
  event_id: number
  quote_id: string | null
  kind: 'quote_action' | 'event_review'
  action: Action
  decided_by: 'rule' | 'llm' | 'error'
  rule_id: string | null
  confidence: number | null
  rationale: string
  draft_subject: string | null
  draft_body: string | null
  facts: QuoteFacts | ReviewFacts
  exposure_usd: number
  status: Status
  final_action: Action | null
  final_subject: string | null
  final_body: string | null
  reviewer_note: string | null
  reviewed_at: string | null
  event: {
    material_id: string | null
    effective_date: string | null
    pct_change: number | null
    email_subject: string | null
    vendor_name: string | null
  }
}

export interface Overview {
  as_of: string
  model: string
  agents_busy: boolean
  needs_you: number
  needs_you_exposure: number
  rule_pending: number
  live_exposure: number
  done: number
  outbox: number
  /** Report only: judgment calls that clear the confidence bar the scenario eval found error-free. */
  autonomy: { threshold: number | null; model: string; would_clear: number; eval_runs?: number } | null
}

export interface Email {
  id: string
  from_addr: string
  subject: string
  body: string
  received_at: string
  status: 'new' | 'processed' | 'error'
  outcome: 'detected' | 'duplicate' | 'needs_review' | 'ignored' | 'error' | null
  note: string | null
  error: string | null
  vendor_name: string | null
  /** For "needs a look" emails: where the person's review stands now. */
  review_status: 'pending' | 'approved' | 'rejected' | null
  review_note: string | null
  /** What the email led to. */
  quotes_checked: number
  needs_you: number
  rule_pending: number
  /** Prices from a supplier the material isn't costed at: recorded, no cards. */
  alt_supplier_notes: string[]
  /** Price lists and letters that came with the email. */
  attachments: Attachment[]
}

export interface Material {
  id: string
  name: string
  /** Catalogue family: elastomer, filler, metal, ... */
  category: string
  cost_per_lb: number
}

export interface LeakageJob {
  quote_id: string
  customer_id: string
  customer_name: string
  issued_date: string
  ordered_date: string
  revenue_usd: number
  margin_floor: number
  margin_quoted: number
  margin_realized: number
  leak_usd: number
  below_floor: boolean
  by_material: Record<string, number>
  /** Quoted basis vs price history at the quote date (rounding, or an estimator's own number). */
  basis_difference_usd: number
  /** The customer's price lock covers the order date: the leak was locked in, not recoverable. */
  price_locked: boolean
  price_lock_until: string | null
  /** The calculation row by row: one entry per quote line x material. */
  trace: LeakageTrace[]
}

export interface HistoryRow {
  id: number
  cost_per_lb: number
  effective_date: string
  vendor_id: string | null
  vendor_name: string | null
  /** Supplier email the price came from; null for seeded or imported history. */
  email_id: string | null
}

export interface LeakageTrace {
  line_id: number
  part_id: string
  part_name: string
  qty: number
  material_id: string
  lb_per_unit: number
  scrap_rate: number
  cost_at_quote: number
  cost_at_order: number
  quote_row: HistoryRow | null
  order_row: HistoryRow | null
  leak_usd: number
}

export interface Leakage {
  assumption: string
  period: { from: string; to: string } | null
  won_jobs: number
  skipped_jobs: { quote_id: string; materials: string[] }[]
  jobs_with_cost_moves: number
  jobs_leaked: number
  revenue_usd: number
  leaked_usd: number
  gained_usd: number
  net_leaked_usd: number
  /** Leaked on jobs a revised quote could have saved; the rest was fixed by customer price locks. */
  recoverable_usd: number
  locked_usd: number
  jobs_locked: number
  margin_quoted: number
  margin_realized: number
  below_floor_jobs: number
  by_material: { material_id: string; material_name: string; leak_usd: number; jobs: number }[]
  by_customer: { customer_id: string; customer_name: string; leak_usd: number; jobs: number }[]
  by_month: { month: string; leak_usd: number; jobs: number; revenue_usd: number }[]
  top_jobs: LeakageJob[]
  jobs: LeakageJob[]
}

export interface OutboxItem {
  id: number
  proposal_id: number
  kind: 'customer_email' | 'call_task'
  recipient: string
  subject: string
  body: string
  created_at: string
}

export interface DemoEmail {
  id: string
  label: string
  from: string
  subject: string
}

export interface FeedItem {
  id: number
  at: string
  tone: 'info' | 'claude' | 'good' | 'attention' | 'fault'
  text: string
}

// ---------------------------------------------------------------- data tab

export interface DataQuote {
  id: string
  customer_id: string
  customer_name: string
  tier: 'key' | 'standard'
  status: 'open' | 'won' | 'lost' | 'expired'
  issued_date: string
  valid_until: string
  margin_floor: number
  value_usd: number
  margin: number
  lines: number
  revisions: number
  open_cards: number
}

export interface QuoteDetail {
  id: string
  customer_name: string
  tier: 'key' | 'standard'
  status: string
  issued_date: string
  valid_until: string
  margin_floor: number
  price_lock_until: string | null
  contract_note: string | null
  buyer_name: string | null
  buyer_phone: string | null
  buyer_email: string | null
  account_manager: string | null
  account_manager_phone: string | null
  lines: {
    id: number
    part_id: string
    part_name: string
    qty: number
    unit_price: number
    material_cost_basis: number
    conversion_cost: number
    materials: string
  }[]
  revisions: { id: number; part_name: string; old_price: number; new_price: number; created_at: string }[]
  cards: {
    id: number
    action: Action
    final_action: Action | null
    status: Status
    decided_by: 'rule' | 'llm' | 'error'
    exposure_usd: number
    material_id: string | null
    email_id: string | null
  }[]
}

export interface DataCustomer {
  id: string
  name: string
  tier: 'key' | 'standard'
  price_lock_until: string | null
  contract_note: string | null
  buyer_name: string
  buyer_phone: string
  buyer_email: string
  account_manager: string
  account_manager_phone: string
  open_quotes: number
  open_value_usd: number
  won_quotes: number
}

export interface DataMaterial {
  id: string
  name: string
  category: string
  cost_per_lb: number
  aliases: string[]
  history: { cost_per_lb: number; effective_date: string; vendor_name: string | null; email_id: string | null }[]
  parts: string[]
}

export const isQuote = (p: Proposal): p is Proposal & { facts: QuoteFacts } => p.kind === 'quote_action'

export interface Attachment {
  id: number
  filename: string
  content_type: string
  /** Why the file was cut or could not be read (e.g. a scan with no text layer). */
  note: string | null
}
