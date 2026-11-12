import type {
  Backlog, DataCustomer, DataMaterial, DataQuote, DemoEmail, Email, ImportHistoryRow, ImportPreview, ImportResult, Leakage, Material, Part,
  OutcomeBody, OutcomesSummary, QuoteCheck, StagedImport, Vendor, OutboxItem, Overview, Proposal, QuoteDetail,
} from './types'

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    let detail = `${res.status}`
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* not JSON */
    }
    throw new Error(detail)
  }
  return res.json()
}

export type ImportPlan = {
  mapping: Record<string, string | null>
  suppliers: Record<string, string>
  matches: Record<string, string>
  remember: boolean
}

const post = <T>(path: string, body: unknown = {}) => call<T>(path, { method: 'POST', body: JSON.stringify(body) })

export type Lane = 'decide' | 'rules' | 'done' | 'outcomes' | 'quote' | 'leakage' | 'inbox' | 'imports' | 'data'

export const api = {
  overview: () => call<Overview>('/api/overview'),
  queue: (lane: Lane, email?: string | null) =>
    call<Proposal[]>(`/api/queue?lane=${lane}${email ? `&email=${encodeURIComponent(email)}` : ''}`),
  inbox: () => call<Email[]>('/api/inbox'),
  materials: () => call<Material[]>('/api/materials'),
  outbox: () => call<OutboxItem[]>('/api/outbox'),
  outcomes: () => call<OutcomesSummary>('/api/outcomes'),
  backlog: () => call<Backlog>('/api/backlog'),
  buyNow: (quoteId: string) => post<unknown>(`/api/backlog/${encodeURIComponent(quoteId)}/buy-now`),
  undoBuy: (quoteId: string) => post<unknown>(`/api/backlog/${encodeURIComponent(quoteId)}/undo-buy`),
  recordOutcome: (proposalId: number, body: OutcomeBody) => post<unknown>(`/api/proposals/${proposalId}/outcome`, body),
  undoOutcome: (outcomeId: number) => post<unknown>(`/api/outcomes/${outcomeId}/undo`),
  demoEmails: () => call<DemoEmail[]>('/api/demo-emails'),
  dataQuotes: () => call<DataQuote[]>('/api/data/quotes'),
  dataQuote: (id: string) => call<QuoteDetail>(`/api/data/quotes/${encodeURIComponent(id)}`),
  dataCustomers: () => call<DataCustomer[]>('/api/data/customers'),
  dataMaterials: () => call<DataMaterial[]>('/api/data/materials'),
  leakage: () => call<Leakage>('/api/leakage'),
  parts: () => call<Part[]>('/api/parts'),
  vendors: () => call<Vendor[]>('/api/vendors'),
  importHistory: () => call<ImportHistoryRow[]>('/api/imports'),
  demoImport: (name: string) => call<{ filename: string; text: string }>(`/api/imports/demo/${encodeURIComponent(name)}`),
  stageInvoices: (filename: string, text: string) => post<StagedImport>('/api/imports/invoices', { filename, text }),
  previewImport: (id: number, plan: ImportPlan) => post<ImportPreview>(`/api/imports/${id}/preview`, plan),
  commitImport: (id: number, plan: ImportPlan) => post<ImportResult>(`/api/imports/${id}/commit`, plan),
  discardImport: (id: number) => post<{ status: string }>(`/api/imports/${id}/discard`),
  quoteCheck: (body: { customer_id: string; valid_days: number; margin_floor: number; lines: { part_id: string; qty: number; unit_price: number }[] }) =>
    post<QuoteCheck>('/api/quote-check', body),

  review: (id: number, body: { verdict: 'approve' | 'edit' | 'reject'; action?: string; subject?: string; body?: string; note?: string }) =>
    post<Proposal>(`/api/proposals/${id}/review`, body),
  reopen: (id: number) => post<Proposal>(`/api/proposals/${id}/reopen`),
  confirmRules: (eventId: number) => post<{ confirmed: number }>(`/api/events/${eventId}/confirm-rules`),
  resolve: (id: number, materialId: string) => post<{ event_id: number }>(`/api/proposals/${id}/resolve`, { material_id: materialId }),
  dismiss: (id: number, note?: string) => post<Proposal>(`/api/proposals/${id}/dismiss`, { note }),
  redecide: (id: number) => post<{ event_id: number }>(`/api/proposals/${id}/redecide`),
  sendDemoEmail: (demoId: string) => post<{ email_id: string }>('/api/inbox', { demo_id: demoId }),
}
