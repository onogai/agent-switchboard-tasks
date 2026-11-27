export type Status = 'future' | 'ready' | 'leased' | 'succeeded' | 'failed' | 'skipped' | 'merged' | 'cancelled'
export type ScheduleKind = 'manual' | 'one_shot' | 'interval' | 'daily'
export type MissPolicy = 'run_late' | 'skip' | 'merge_next'

export interface Definition {
  id: string
  version: number
  execution_version: number
  group: string | null
  title: string
  instructions: string
  is_active: number
  priority: number
  schedule_kind: ScheduleKind
  interval_minutes: number | null
  interval_anchor_at: string | null
  daily_time_local: string | null
  timezone: string | null
  miss_policy: MissPolicy
  max_lateness_minutes: number
  window_after_minutes: number
  window_before_minutes: number
  one_shot_at: string | null
  archived_at: string | null
  lease_seconds: number
  max_attempts: number
  next_scheduled_at: string | null
  next_visible_at?: string | null
}

export interface Instance {
  id: string
  definition_id: string
  title_snapshot: string
  instructions_snapshot: string
  priority_snapshot: number
  status: Status
  scheduled_at: string
  ready_at: string
  coverage_start: string | null
  coverage_end: string | null
  attempt_count: number
  lease_expires_at: string | null
  result_json: string | null
  last_error: string | null
  retry_of_id: string | null
  created_at: string
  updated_at: string
}

export interface QueueEvent {
  id: number
  occurred_at: string
  action: string
  actor: string
  reason: string | null
}

export interface Attempt {
  id: number
  attempt_number: number
  claimed_at: string
  completed_at: string | null
  outcome: string | null
  error: string | null
}

export interface Overview {
  now: string
  counts: Partial<Record<Status, number>>
  claimable_count: number
  active_rule_count: number
  rule_count: number
  next_due_at: string | null
  claimable: Instance[]
  upcoming: Instance[]
  recent: Instance[]
}

export interface DefinitionInput {
  group: string | null
  title: string
  instructions: string
  schedule_kind: ScheduleKind
  priority: number
  miss_policy: MissPolicy
  max_lateness_minutes: number
  window_before_minutes: number
  one_shot_at: string | null
  lease_seconds: number
  max_attempts: number
  interval_minutes: number | null
  interval_anchor_at: string | null
  daily_time_local: string | null
  timezone_name: string | null
}

export interface Proposal {
  id: string
  operation: string
  target_title?: string
  summary?: string
  impact_summary?: string | null
  target_id: string | null
  payload: Record<string, unknown>
  expected_version: number | null
  status: 'pending' | 'approved' | 'rejected' | 'stale'
  created_at: string
  decided_at: string | null
  reason: string | null
  result: Record<string, unknown> | null
  decision_source: string | null
  impact: { metadata_only?: boolean; unstarted?: number; unleased?: number; leased?: number; queued_retries?: number; current_status?: string | null } | null
}
