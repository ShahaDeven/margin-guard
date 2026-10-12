import type {
  DataCustomer, DataMaterial, DataQuote, DemoEmail, Email, Material, OutboxItem, Overview, Proposal, QuoteDetail,
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

const post = <T>(path: string, body: unknown = {}) => call<T>(path, { method: 'POST', body: JSON.stringify(body) })

export type Lane = 'decide' | 'rules' | 'done' | 'data'

export const api = {
  overview: () => call<Overview>('/api/overview'),
  queue: (lane: Lane, email?: string | null) =>
    call<Proposal[]>(`/api/queue?lane=${lane}${email ? `&email=${encodeURIComponent(email)}` : ''}`),
  inbox: () => call<Email[]>('/api/inbox'),
  materials: () => call<Material[]>('/api/materials'),
  outbox: () => call<OutboxItem[]>('/api/outbox'),
  demoEmails: () => call<DemoEmail[]>('/api/demo-emails'),
  dataQuotes: () => call<DataQuote[]>('/api/data/quotes'),
  dataQuote: (id: string) => call<QuoteDetail>(`/api/data/quotes/${encodeURIComponent(id)}`),
  dataCustomers: () => call<DataCustomer[]>('/api/data/customers'),
  dataMaterials: () => call<DataMaterial[]>('/api/data/materials'),

  review: (id: number, body: { verdict: 'approve' | 'edit' | 'reject'; action?: string; subject?: string; body?: string; note?: string }) =>
    post<Proposal>(`/api/proposals/${id}/review`, body),
  reopen: (id: number) => post<Proposal>(`/api/proposals/${id}/reopen`),
  confirmRules: (eventId: number) => post<{ confirmed: number }>(`/api/events/${eventId}/confirm-rules`),
  resolve: (id: number, materialId: string) => post<{ event_id: number }>(`/api/proposals/${id}/resolve`, { material_id: materialId }),
  dismiss: (id: number, note?: string) => post<Proposal>(`/api/proposals/${id}/dismiss`, { note }),
  sendDemoEmail: (demoId: string) => post<{ email_id: string }>('/api/inbox', { demo_id: demoId }),
}
