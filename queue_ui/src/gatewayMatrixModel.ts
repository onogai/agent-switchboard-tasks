import type { GatewayTool, GatewaySource } from './adminApi'

export const MATRIX_PROFILES = [
  { id: 'unattended', label: 'Unattended' },
  { id: 'interactive', label: 'Interactive' },
  { id: 'local-interactive', label: 'Local interactive' },
] as const

export type MatrixAccess = 'all' | 'granted' | 'ungranted' | 'review'
export type MatrixFilters = {
  query: string
  sourceId: string
  profile: string
  access: MatrixAccess
}
export type ToolGroup = {
  id: string
  enabled: boolean
  status: string
  tools: GatewayTool[]
}

/** Reject late preview responses after filters change, including within one request. */
export function createBulkPreviewGuard() {
  let revision = 0
  return {
    begin: () => ++revision,
    invalidate: () => { revision += 1 },
    accepts: (issued: number) => issued === revision,
  }
}

export function updatedGrants(grants: readonly string[], profile: string, enabled: boolean): string[] {
  const next = new Set(grants)
  if (enabled) next.add(profile)
  else next.delete(profile)
  return [...next].sort()
}

export function groupGatewayTools(
  tools: readonly GatewayTool[],
  sources: readonly GatewaySource[],
  filters: MatrixFilters,
): ToolGroup[] {
  const query = filters.query.trim().toLocaleLowerCase()
  const sourceById = new Map(sources.map(source => [source.id, source]))
  const filtered = tools.filter(tool => {
    if (filters.sourceId !== 'all' && tool.source_id !== filters.sourceId) return false
    if (filters.profile !== 'all' && !tool.grants.includes(filters.profile)) return false
    if (filters.access === 'granted' && tool.grants.length === 0) return false
    if (filters.access === 'ungranted' && tool.grants.length !== 0) return false
    if (filters.access === 'review' && tool.status === 'active') return false
    if (!query) return true
    return [tool.public_name, tool.title || '', tool.id, tool.description, tool.effects, tool.source_id]
      .some(value => value.toLocaleLowerCase().includes(query))
  })
  const groups = new Map<string, ToolGroup>()
  for (const tool of filtered) {
    const source = sourceById.get(tool.source_id)
    let group = groups.get(tool.source_id)
    if (!group) {
      group = {
        id: tool.source_id,
        enabled: source?.enabled ?? tool.source_enabled,
        status: source?.status ?? tool.source_status,
        tools: [],
      }
      groups.set(tool.source_id, group)
    }
    group.tools.push(tool)
  }
  return [...groups.values()]
    .sort((a, b) => a.id.localeCompare(b.id))
    .map(group => ({ ...group, tools: group.tools.sort((a, b) => a.public_name.localeCompare(b.public_name)) }))
}
