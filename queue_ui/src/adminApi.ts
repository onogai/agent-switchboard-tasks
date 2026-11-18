export type TelegramDestination = {
  slug: string; bot_id: string; chat_id: string; label: string
  chat_type: string; enabled: boolean; bot_enabled: boolean; binding_id: string
}
export type TelegramDestinationImpact = {
  slug: string; binding_id: string; bot_id: string; chat_id: string
  summary_count: number; delivery_count: number
  queue_rules?: { id: string; title: string }[]
  queue_matches_total?: number; queue_scan?: 'advisory' | 'unavailable'
}

export type TelegramDiscoveredChat = {
  bot_id: string; bot_username: string; bot_label: string; bot_enabled: boolean
  chat_id: string; title: string; chat_type: string; source: string
  present: boolean; ignored: boolean; first_seen: string; last_seen: string
}

export type AdminSession = {
  authenticated: boolean
  csrf_token: string
  modules: { queue: boolean; telegram: boolean }
}

export type GatewaySource = {
  id: string
  kind: string
  url: string | null
  enabled: boolean
  status: string
  error: string | null
  auth_type: 'none' | 'bearer' | 'coches_env'
  auth_configured: boolean
}

export type GatewayTool = {
  id: string
  source_id: string
  upstream_name: string
  parent_id: string | null
  public_name: string
  title: string | null
  description: string
  effects: string
  status: string
  aliases: string[]
  grants: string[]
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown> | null
  annotations: Record<string, unknown> | null
  meta: Record<string, unknown> | null
  observed: Record<string, unknown>
  fixed_args: Record<string, unknown>
  source_enabled: boolean
  source_status: string
}

export type BulkOperation = 'approve' | 'assign' | 'revoke' | 'approve_assign'
export type BulkRequest = {
  ids: string[]
  operation: BulkOperation
  profiles: string[]
  adopt_observed?: boolean
}
export type BulkPreview = {
  operation: BulkOperation
  profiles: string[]
  snapshot: string
  applied: boolean
  adopt_observed: boolean
  counts: {
    requested: number
    will_change: number
    will_approve: number
    will_adopt: number
    will_assign: number
    will_revoke: number
    unchanged: number
    blocked: number
  }
  blocked: { id: string; reason: string }[]
  changes: { id: string; before: { status: string; grants: string[] }; after: { status: string; grants: string[] }; contract_fields?: string[] }[]
}

export type AuditEvent = {
  id: number
  at: string
  actor: string
  action: string
  target: string
  before_json: string | null
  after_json: string | null
}

const root = '/admin/api'
let csrf: string | null = null

export function clearAdminCsrf() { csrf = null }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(root + path, { credentials: 'same-origin', cache: 'no-store', ...init })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`)
  return body as T
}

async function mutate<T>(path: string, method: 'POST' | 'PUT', body: object): Promise<T> {
  if (!csrf) csrf = (await request<AdminSession>('/session')).csrf_token
  const send = () => request<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf! },
    body: JSON.stringify(body),
  })
  try {
    return await send()
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('Invalid CSRF')) {
      csrf = (await request<AdminSession>('/session')).csrf_token
      return send()
    }
    throw error
  }
}

const toolPath = (id: string) => id.split('/').map(encodeURIComponent).join('/')

export const adminApi = {
  session: () => request<AdminSession>('/session'),
  login: (pin: string) => mutate<AdminSession>('/login', 'POST', { pin }),
  logout: () => mutate<{ authenticated: false }>('/logout', 'POST', {}),
  changePin: (current_pin: string, new_pin: string) =>
    mutate<{ authenticated: false }>('/security/pin', 'POST', { current_pin, new_pin }),
  sources: () => request<{ sources: GatewaySource[] }>('/gateway/sources'),
  setSource: (id: string, value: { enabled: boolean; url?: string; auth_type: 'none' | 'bearer' | 'coches_env'; bearer_token?: string }) =>
    mutate<GatewaySource>(`/gateway/sources/${encodeURIComponent(id)}`, 'PUT', value),
  tools: () => request<{ tools: GatewayTool[] }>('/gateway/tools'),
  bulkPreview: (value: BulkRequest) => mutate<BulkPreview>('/gateway/tools/bulk/preview', 'POST', value),
  bulkApply: (value: BulkRequest & { snapshot: string; confirm: true }) =>
    mutate<BulkPreview>('/gateway/tools/bulk/apply', 'POST', value),
  setTool: (id: string, value: object) =>
    mutate<GatewayTool>(`/gateway/tools/${toolPath(id)}`, 'PUT', value),
  createVariant: (id: string, value: object) =>
    mutate<GatewayTool>(`/gateway/tools/${toolPath(id)}/variants`, 'POST', value),
  audit: () => request<{ events: AuditEvent[] }>('/gateway/audit'),
  refresh: () => mutate<{ requested: true }>('/gateway/refresh', 'POST', {}),

  telegramDeliveryStatus: () => request<{ configured: boolean; bots: number; destinations: number }>('/telegram-delivery/status'),
  telegramBots: () => request<{ bots: { id: string; username: string; label: string; enabled: boolean }[] }>('/telegram-delivery/bots'),
  telegramAddBot: (value: { token: string; label: string }) => mutate<{ id: string }>('/telegram-delivery/bots', 'POST', value),
  telegramSetBot: (id: string, enabled: boolean) => mutate<{ id: string }>('/telegram-delivery/bots/' + encodeURIComponent(id), 'PUT', { enabled }),
  telegramDiscovered: () => request<{ chats: TelegramDiscoveredChat[]; receivers: Record<string, { state: string; detail?: string; checked_at?: string }> }>('/telegram-delivery/discovered'),
  telegramIgnoreDiscovered: (botId: string, chatId: string, ignored: boolean) =>
    mutate<{ ignored: boolean }>(`/telegram-delivery/discovered/${encodeURIComponent(botId)}/${encodeURIComponent(chatId)}`, 'PUT', { ignored }),
  telegramApproveDiscovered: (botId: string, chatId: string, slug: string, label: string) =>
    mutate<{ slug: string }>(`/telegram-delivery/discovered/${encodeURIComponent(botId)}/${encodeURIComponent(chatId)}/approve`, 'POST', { slug, label }),
  telegramDestinations: () => request<{ destinations: TelegramDestination[] }>('/telegram-delivery/destinations'),
  telegramDestinationImpact: (slug: string) =>
    request<TelegramDestinationImpact>('/telegram-delivery/destinations/' + encodeURIComponent(slug) + '/impact'),
  telegramDeleteDestination: (slug: string, expected_binding_id: string) =>
    mutate<{ deleted: boolean; slug: string; archived_summaries: number }>(
      '/telegram-delivery/destinations/' + encodeURIComponent(slug) + '/delete',
      'POST', { expected_binding_id, confirm: true }),
  telegramRebindDestination: (slug: string, expected_binding_id: string, chat: TelegramDiscoveredChat, label: string) =>
    mutate<TelegramDestination>('/telegram-delivery/destinations/' + encodeURIComponent(slug) + '/rebind',
      'POST', { expected_binding_id, bot_id: chat.bot_id, chat_id: chat.chat_id, label, confirm: true }),
  telegramAddDestination: (value: { slug: string; bot_id: string; chat_id: string; label: string }) =>
    mutate<{ slug: string }>('/telegram-delivery/destinations', 'POST', value),
  telegramSetDestination: (slug: string, enabled: boolean) =>
    mutate<{ slug: string }>('/telegram-delivery/destinations/' + encodeURIComponent(slug), 'PUT', { enabled }),
  telegramDeliveryTestSend: (destination: string, text: string) =>
    mutate<{ delivery_id: string; status: string; error_code?: string }>('/telegram-delivery/test-send', 'POST', { destination, text, confirm: true }),
  telegramSummaryStatus: (destination: string, key: string) =>
    mutate<{ destination: string; key: string; message_id: string; content_saved: boolean; pinned: boolean }>('/telegram-delivery/summary/status', 'POST', { destination, key }),
  telegramSummaryPermissions: (destination: string, key: string) =>
    mutate<{ destination: string; chat_type: string; bot_status: string; required_right: string | null; can_pin: boolean | null }>('/telegram-delivery/summary/permissions', 'POST', { destination, key }),
  telegramSummaryPin: (destination: string, key: string) =>
    mutate<{ status: string; message_id: string; content_saved: boolean; pin_status: string; error_code?: number; description?: string }>('/telegram-delivery/summary/pin', 'POST', { destination, key, confirm: true }),
  telegramRecentDeliveries: () => request<{ deliveries: { delivery_id: string; destination: string; status: string; operation: string; parts_sent: number; error_code?: string }[] }>('/telegram-delivery/deliveries'),
  telegramStatus: () => request<{ configured: boolean; recipient: string | null }>('/telegram/status'),
  telegramTestSend: (message: string) =>
    mutate<{ message_id: string }>('/telegram/test-send', 'POST', { message, confirm: true }),
}
