import type { Definition, DefinitionInput, Instance, Overview, QueueEvent, Attempt, Proposal } from './types'

import { queueMount } from './layoutMode'

const mount = queueMount(window.location.pathname)
const base = mount === '/queue' ? '/queue/api'
  : mount === '/admin/queue' ? '/admin/api/queue'
    : mount + '/api'
const sessionPath = mount === '/queue' ? '/queue/api/session' : '/admin/api/session'
let csrfToken: string | null = null

export function clearCsrf() { csrfToken = null }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${base}${path}`, { credentials: 'same-origin', cache: 'no-store', ...init })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`)
  return body as T
}

async function mutate<T>(path: string, method: 'POST' | 'PUT', data: object = {}): Promise<T> {
  if (!csrfToken) csrfToken = (await fetch(sessionPath, { credentials: 'same-origin', cache: 'no-store' }).then(r => r.json()) as { csrf_token: string }).csrf_token
  const send = () => request<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken! },
    body: JSON.stringify(data),
  })
  try {
    return await send()
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('Invalid CSRF token')) {
      csrfToken = (await fetch(sessionPath, { credentials: 'same-origin', cache: 'no-store' }).then(r => r.json()) as { csrf_token: string }).csrf_token
      return send()
    }
    throw error
  }
}

export const api = {
  overview: () => request<Overview>('/overview'),
  session: () => request<{ authenticated: boolean; csrf_token: string }>('/session'),
  login: (pin: string) => mutate<{ authenticated: boolean; csrf_token: string }>('/login', 'POST', { pin }),
  logout: () => mutate<{ authenticated: boolean }>('/logout', 'POST'),
  definitions: () => request<{ definitions: Definition[] }>('/definitions'),
  definition: (id: string) => request<{ definition: Definition; events: QueueEvent[] }>(`/definitions/${id}`),
  instances: (status?: string) => request<{ instances: Instance[] }>(`/instances${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  instance: (id: string) => request<{ instance: Instance; attempts: Attempt[]; events: QueueEvent[] }>(`/instances/${id}`),
  create: (data: DefinitionInput) => mutate<{ id: string }>('/definitions', 'POST', data),
  update: (id: string, data: DefinitionInput, expectedVersion: number) => mutate<{ id: string }>(`/definitions/${id}`, 'PUT', { ...data, expected_version: expectedVersion }),
  toggle: (id: string, isActive: boolean, expectedVersion: number) => mutate<{ id: string; is_active: boolean }>(`/definitions/${id}/toggle`, 'POST', { is_active: isActive, expected_version: expectedVersion }),
  archive: (id: string, expectedVersion: number) => mutate<{ id: string }>(`/definitions/${id}/archive`, 'POST', { expected_version: expectedVersion }),
  trigger: (id: string) => mutate<{ id: string }>(`/definitions/${id}/trigger`, 'POST'),
  cancel: (id: string) => mutate<{ id: string }>(`/instances/${id}/cancel`, 'POST'),
  retry: (id: string) => mutate<{ id: string }>(`/instances/${id}/retry`, 'POST'),
  proposals: (status?: string) => request<{ proposals: Proposal[] }>(`/proposals${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  proposal: (id: string) => request<Proposal>(`/proposals/${id}`),
  decideProposal: (id: string, approve: boolean) => mutate<Proposal>(`/proposals/${id}/${approve ? 'approve' : 'reject'}`, 'POST'),
  autoApproval: () => request<{ enabled: boolean; until: string | null }>('/auto-approval'),
  setAutoApproval: (enabled: boolean) => mutate<{ enabled: boolean; until: string | null }>('/auto-approval', 'POST', { enabled }),
}
