import { useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, NavLink, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { DataGrid, type GridColDef } from '@mui/x-data-grid'
import {
  Alert, AppBar, Box, Button, Card, CardContent, Chip, CircularProgress, Container,
  Dialog, DialogActions, DialogContent, DialogTitle, Divider, Drawer, FormControl,
  FormHelperText, IconButton, InputLabel, MenuItem, Paper, Select, Slider, Stack, Tab, Tabs,
  TextField, Toolbar, Tooltip, Typography, useMediaQuery, useTheme,
} from '@mui/material'
import {
  AddRounded, ArrowBackRounded, AssignmentRounded, DashboardRounded,
  EditRounded, MenuRounded, PauseRounded, PlayArrowRounded, RefreshRounded,
  RuleRounded,
} from '@mui/icons-material'
import { api, clearCsrf } from './api'
import { queueLayout } from './layoutMode'
import type { Definition, DefinitionInput, Instance, MissPolicy, Proposal, ScheduleKind, Status } from './types'

const statuses: Status[] = ['future', 'ready', 'leased', 'succeeded', 'failed', 'skipped', 'merged', 'cancelled']
// The Manager owns the one shared top-level navigation. Queue keeps its own
// standalone UI, but supplies only a compact sub-navigation when embedded.
const { managed: managedQueue, embedded: embeddedQueue } = queueLayout(
  window.location.pathname, window.self !== window.top,
)
const statusLabel: Record<Status, string> = {
  future: 'Scheduled', ready: 'Ready', leased: 'Running', succeeded: 'Completed',
  failed: 'Failed', skipped: 'Skipped', merged: 'Merged', cancelled: 'Cancelled',
}
const statusColor: Record<Status, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  future: 'default', ready: 'info', leased: 'warning', succeeded: 'success',
  failed: 'error', skipped: 'default', merged: 'default', cancelled: 'default',
}

function dateTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('en-GB', {
    dateStyle: 'medium', timeStyle: 'short',
  }).format(date)
}

function StatusChip({ status }: { status: Status }) {
  return <Chip size="small" label={statusLabel[status]} color={statusColor[status]} variant={status === 'future' ? 'outlined' : 'filled'} />
}

function Loading() { return <Box sx={{ display: 'flex', justifyContent: 'center', p: 8 }}><CircularProgress /></Box> }
function ErrorBox({ error }: { error: unknown }) { return <Alert severity="error">{error instanceof Error ? error.message : 'Unable to load data.'}</Alert> }
function Empty({ text }: { text: string }) { return <Paper variant="outlined" sx={{ p: 4, textAlign: 'center', color: 'text.secondary' }}>{text}</Paper> }

function PageTitle({ title, description, action }: { title: string; description?: string; action?: React.ReactNode }) {
  return <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', sm: 'center' }} gap={1.5} sx={{ mb: 2 }}>
    <Box><Typography variant={embeddedQueue ? 'h6' : 'h4'} fontWeight={750}
      sx={{ letterSpacing: '-.025em' }}>{title}</Typography>{description &&
      <Typography variant={embeddedQueue ? 'body2' : 'body1'} color="text.secondary" sx={{ mt: .25 }}>
        {description}
      </Typography>}</Box>
    {action}
  </Stack>
}

function ConfirmButton({ label, message, onConfirm, color = 'primary', icon }: {
  label: string; message: string; onConfirm: () => void; color?: 'primary' | 'error'; icon?: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  return <>
    <Button variant="outlined" color={color} startIcon={icon} onClick={() => setOpen(true)}>{label}</Button>
    <Dialog open={open} onClose={() => setOpen(false)}>
      <DialogTitle>Confirm action</DialogTitle><DialogContent><Typography>{message}</Typography></DialogContent>
      <DialogActions><Button onClick={() => setOpen(false)}>Back</Button><Button color={color} variant="contained" onClick={() => { setOpen(false); onConfirm() }}>Confirm</Button></DialogActions>
    </Dialog>
  </>
}

const nav = [
  { to: '/', text: 'Overview', icon: <DashboardRounded fontSize="small" /> },
  { to: '/queue', text: 'Queue', icon: <AssignmentRounded fontSize="small" /> },
  { to: '/rules', text: 'Rules', icon: <RuleRounded fontSize="small" /> },
  { to: '/proposals', text: 'Proposals', icon: <AssignmentRounded fontSize="small" /> },
]

function Shell() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const queryClient = useQueryClient()
  const location = useLocation()
  const theme = useTheme()
  const mobile = useMediaQuery(theme.breakpoints.down('md'))
  const routes = <Routes>
    <Route path="/" element={<DashboardPage />} />
    <Route path="/queue" element={<QueuePage />} />
    <Route path="/tasks/:id" element={<TaskPage />} />
    <Route path="/rules" element={<RulesPage />} />
    <Route path="/rules/new" element={<RuleFormPage />} />
    <Route path="/rules/:id" element={<RuleFormPage />} />
    <Route path="/proposals" element={<ProposalsPage />} />
    <Route path="*" element={<Empty text="Page not found." />} />
  </Routes>
  if (embeddedQueue) {
    const active = location.pathname.startsWith('/tasks/') || location.pathname.startsWith('/queue')
      ? '/queue' : location.pathname.startsWith('/rules') ? '/rules'
        : location.pathname.startsWith('/proposals') ? '/proposals' : '/'
    return <Box sx={{ minHeight: '100%', bgcolor: 'background.default' }}>
      <Box sx={{ position: 'sticky', top: 0, zIndex: 5, borderBottom: 1,
        borderColor: 'divider', bgcolor: 'background.default', px: { xs: 1, sm: 2.5 } }}>
        <Tabs value={active} variant="scrollable" scrollButtons="auto"
          aria-label="Queue sections" sx={{ minHeight: 42,
            '& .MuiTab-root': { minHeight: 42, px: 1.5, py: 0, fontSize: 13 },
          }}>
          <Tab label="Overview" value="/" component={RouterLink} to="/" />
          <Tab label="Queue" value="/queue" component={RouterLink} to="/queue" />
          <Tab label="Rules" value="/rules" component={RouterLink} to="/rules" />
          <Tab label="Proposals" value="/proposals" component={RouterLink} to="/proposals" />
        </Tabs>
      </Box>
      <Box component="main" sx={{ px: { xs: 2, md: 3 }, pt: 2, pb: 3 }}>
        <AutoApprovalBanner />
        {routes}
      </Box>
    </Box>
  }
  const content = <Box sx={{ p: 2.5, height: '100%' }}>
    <Box sx={{ px: 1, pb: 3 }}><Typography variant="overline" color="primary" fontWeight={800} letterSpacing={2}>NOGAI</Typography><Typography variant="h6" fontWeight={750}>Task Manager</Typography><Typography variant="body2" color="text.secondary">Local agent task queue</Typography></Box>
    <Stack gap={.5}>{nav.map(item => <Box key={item.to} component={NavLink} end={item.to === '/'} to={item.to} onClick={() => setMobileOpen(false)} sx={{ textDecoration: 'none', color: 'text.secondary', display: 'flex', alignItems: 'center', gap: 1.5, px: 2, py: 1.3, borderRadius: 2, '&.active': { bgcolor: '#e9f0fb', color: 'primary.main', fontWeight: 700 }, '&:hover': { bgcolor: '#f0f4fa' } }}>{item.icon}{item.text}</Box>)}</Stack>
    <Divider sx={{ my: 3 }} />{managedQueue ? <Button sx={{ mx: 1 }} href="/admin/">Back to Switchboard</Button> : <Button sx={{ mx: 1 }} onClick={async () => { await api.logout(); clearCsrf(); queryClient.clear(); window.location.assign('/queue/') }}>Log out</Button>}<Typography variant="caption" color="text.secondary" sx={{ px: 1 }}>{managedQueue ? 'Protected by Switchboard session' : 'Available on the local network'}</Typography>
  </Box>
  return <Box sx={{ display: 'flex', minHeight: '100vh' }}>
    {mobile ? <><AppBar position="fixed" color="inherit" elevation={0} sx={{ borderBottom: 1, borderColor: 'divider' }}><Toolbar><IconButton onClick={() => setMobileOpen(true)} aria-label="Open menu"><MenuRounded /></IconButton><Typography fontWeight={700} sx={{ ml: 1 }}>Task Manager</Typography></Toolbar></AppBar><Drawer open={mobileOpen} onClose={() => setMobileOpen(false)} PaperProps={{ sx: { width: 250 } }}>{content}</Drawer></> : <Drawer variant="permanent" PaperProps={{ sx: { width: 250, borderRight: 1, borderColor: 'divider' } }}>{content}</Drawer>}
    <Box component="main" sx={{ flex: 1, minWidth: 0, ml: mobile ? 0 : '250px', pt: mobile ? 10 : 5, pb: 7 }}><Container maxWidth="xl"><AutoApprovalBanner />{routes}</Container></Box>
  </Box>
}

function Metric({ label, value, note, color }: { label: string; value: string | number; note?: string; color?: string }) {
  return <Card><CardContent sx={{ p: embeddedQueue ? 2 : 2.5, '&:last-child': { pb: embeddedQueue ? 2 : 2.5 } }}>
    <Typography variant="body2" color="text.secondary">{label}</Typography>
    <Typography variant={embeddedQueue ? 'h5' : 'h3'}
      sx={{ fontWeight: 750, color: color || 'text.primary', my: embeddedQueue ? .25 : .6,
        fontVariantNumeric: 'tabular-nums' }}>{value}</Typography>
    <Typography variant="caption" color="text.secondary">{note || ' '}</Typography>
  </CardContent></Card>
}

function TaskList({ tasks, empty }: { tasks: Instance[]; empty: string }) {
  if (!tasks.length) return <Empty text={empty} />
  return <Paper variant="outlined" sx={{ overflow: 'hidden' }}>{tasks.map((task, index) => <Box key={task.id} component={RouterLink} to={`/tasks/${task.id}`} sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2, p: 2, textDecoration: 'none', color: 'text.primary', borderBottom: index < tasks.length - 1 ? 1 : 0, borderColor: 'divider', '&:hover': { bgcolor: '#f8faff' } }}><Box sx={{ minWidth: 0 }}><Typography fontWeight={650} noWrap>{task.title_snapshot}</Typography><Typography variant="caption" color="text.secondary">{dateTime(task.scheduled_at)} · Priority {task.priority_snapshot}</Typography></Box><StatusChip status={task.status} /></Box>)}</Paper>
}

function DashboardPage() {
  const client = useQueryClient()
  const overview = useQuery({ queryKey: ['overview'], queryFn: api.overview, refetchInterval: 30_000 })
  const rules = useQuery({ queryKey: ['definitions'], queryFn: api.definitions, refetchInterval: 30_000 })
  if (overview.isLoading || rules.isLoading) return <Loading />
  if (overview.error || rules.error) return <ErrorBox error={overview.error || rules.error} />
  const data = overview.data!
  return <>
    <PageTitle title="Queue overview" description="Current task status and upcoming runs" action={<Stack direction="row" gap={1}><Tooltip title="Refresh"><IconButton onClick={() => client.invalidateQueries()}><RefreshRounded /></IconButton></Tooltip><Button component={RouterLink} to="/rules/new" variant="contained" startIcon={<AddRounded />}>New rule</Button></Stack>} />
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', lg: 'repeat(4,1fr)' }, gap: 1.5, mb: 2 }}>
      <Metric label="Ready for agents now" value={data.claimable_count} note="Available to claim" color="#2456a7" />
      <Metric label="Upcoming" value={data.counts.future || 0} note="Created ahead of time" />
      <Metric label="Running" value={data.counts.leased || 0} note="Claimed by an agent" />
      <Metric label="Active rules" value={data.active_rule_count} note={`Total rules: ${data.rule_count}`} />
    </Box>
    <Alert severity={data.claimable_count ? 'info' : 'success'} sx={{ mb: 2 }}>
      {data.claimable_count ? `An agent can claim ${data.claimable_count} tasks now.` : 'No tasks are ready right now.'}
      {data.next_due_at ? ` Next scheduled for ${dateTime(data.next_due_at)}.` : ''} Future tasks become available at their scheduled time.
    </Alert>
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '1fr 1fr' }, gap: 3 }}>
      <Box><SectionHeading title="Ready now" to="/queue?status=ready" /><TaskList tasks={data.claimable} empty="No ready tasks." /></Box>
      <Box><SectionHeading title="Upcoming runs" to="/queue?status=future" /><TaskList tasks={data.upcoming.slice(0, 6)} empty="No scheduled tasks." /></Box>
      <Box><SectionHeading title="Recent results" to="/queue?status=succeeded" /><TaskList tasks={data.recent.slice(0, 6)} empty="No completed tasks yet." /></Box>
      <Box><SectionHeading title="Rules" to="/rules" /><Paper variant="outlined">{rules.data!.definitions.slice(0, 6).map((rule, index) => <Box key={rule.id} component={RouterLink} to={`/rules/${rule.id}`} sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, p: 2, color: 'text.primary', textDecoration: 'none', borderBottom: index < Math.min(rules.data!.definitions.length, 6) - 1 ? 1 : 0, borderColor: 'divider', '&:hover': { bgcolor: '#f8faff' } }}><Typography fontWeight={650}>{rule.title}</Typography><Chip size="small" color={rule.is_active && !rule.archived_at ? 'success' : 'default'} label={rule.archived_at ? 'Archived' : rule.is_active ? 'Active' : 'Paused'} /></Box>)}{!rules.data!.definitions.length && <Box p={3}>No rules yet.</Box>}</Paper></Box>
    </Box>
  </>
}

function SectionHeading({ title, to }: { title: string; to: string }) { return <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}><Typography variant="h6" fontWeight={700}>{title}</Typography><Button component={RouterLink} to={to} size="small">All</Button></Stack> }

function QueuePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const status = searchParams.get('status') || ''
  const [search, setSearch] = useState('')
  const query = useQuery({ queryKey: ['instances', status], queryFn: () => api.instances(status), refetchInterval: 30_000 })
  const overview = useQuery({ queryKey: ['overview'], queryFn: api.overview, refetchInterval: 30_000 })
  const rows = useMemo(() => (query.data?.instances || []).filter(row => row.title_snapshot.toLowerCase().includes(search.toLowerCase()) || row.id.includes(search)), [query.data, search])
  const columns: GridColDef<Instance>[] = [
    { field: 'title_snapshot', headerName: 'Task', flex: 2, minWidth: 220, renderCell: p => <RouterLink to={`/tasks/${p.row.id}`} style={{ color: '#2456a7', fontWeight: 650, textDecoration: 'none' }}>{p.value}</RouterLink> },
    { field: 'status', headerName: 'Status', width: 150, renderCell: p => <StatusChip status={p.value as Status} /> },
    { field: 'scheduled_at', headerName: 'Scheduled for', width: 190, valueFormatter: value => dateTime(value as string) },
    { field: 'priority_snapshot', headerName: 'Priority', width: 110 },
    { field: 'attempt_count', headerName: 'Attempts', width: 100 },
  ]
  return <>
    <PageTitle title="Task queue" description="Sort and filter task instances. Dates use your local time zone." action={<Button component={RouterLink} to="/rules/new" variant="contained" startIcon={<AddRounded />}>New rule</Button>} />
    {overview.data && <Alert severity="info" sx={{ mb: 2 }}>Available to agents now: <strong>{overview.data.claimable_count}</strong>. Future tasks have been created but cannot be claimed yet.</Alert>}
    <Paper variant="outlined" sx={{ p: 2 }}><Stack direction={{ xs: 'column', sm: 'row' }} gap={2} sx={{ mb: 2 }}>
      <FormControl size="small" sx={{ minWidth: 190 }}><InputLabel>Status</InputLabel><Select label="Status" value={status} onChange={e => setSearchParams(e.target.value ? { status: e.target.value } : {})}><MenuItem value="">All statuses</MenuItem>{statuses.map(item => <MenuItem key={item} value={item}>{statusLabel[item]}</MenuItem>)}</Select></FormControl>
      <TextField size="small" label="Search by title or ID" value={search} onChange={e => setSearch(e.target.value)} sx={{ flex: 1 }} />
      <Tooltip title="Refresh"><IconButton onClick={() => { query.refetch(); overview.refetch() }}><RefreshRounded /></IconButton></Tooltip>
    </Stack>
    {query.error && <ErrorBox error={query.error} />}
    <Box sx={{ height: 610, width: '100%' }}><DataGrid rows={rows} columns={columns} loading={query.isLoading} disableRowSelectionOnClick pageSizeOptions={[10, 25, 50, 100]} initialState={{ pagination: { paginationModel: { pageSize: 25, page: 0 } }, sorting: { sortModel: [{ field: 'scheduled_at', sort: 'asc' }] } }} sx={{ border: 0, '& .MuiDataGrid-columnHeaders': { bgcolor: '#f8faff' } }} /></Box></Paper>
  </>
}

function RulesPage() {
  const query = useQuery({ queryKey: ['definitions'], queryFn: api.definitions, refetchInterval: 30_000 })
  const rows = query.data?.definitions || []
  const columns: GridColDef<Definition>[] = [
    { field: 'title', headerName: 'Rule', flex: 2, minWidth: 220, renderCell: p => <RouterLink to={`/rules/${p.row.id}`} style={{ color: '#2456a7', fontWeight: 650, textDecoration: 'none' }}>{p.value}</RouterLink> },
    { field: 'schedule_kind', headerName: 'Schedule', width: 150, renderCell: p => p.row.one_shot_at ? 'Once' : ({ manual: 'Manual', one_shot: 'Once', interval: 'Interval', daily: 'Daily' })[p.value as ScheduleKind] },
    { field: 'priority', headerName: 'Priority', width: 110 },
    { field: 'is_active', headerName: 'Status', width: 130, renderCell: p => <Chip size="small" label={p.row.archived_at ? 'Archived' : p.value ? 'Active' : 'Paused'} color={p.value && !p.row.archived_at ? 'success' : 'default'} /> },
    { field: 'next_visible_at', headerName: 'Next task', width: 210, valueFormatter: value => dateTime(value as string | null) },
    { field: 'id', headerName: '', width: 100, sortable: false, renderCell: p => <Button component={RouterLink} to={`/rules/${p.value}`} size="small">Open</Button> },
  ]
  return <><PageTitle title="Rules" description="Goals, schedules and missed-run policies" action={<Button component={RouterLink} to="/rules/new" variant="contained" startIcon={<AddRounded />}>New rule</Button>} />{query.error && <ErrorBox error={query.error} />}<Paper variant="outlined" sx={{ height: 650 }}><DataGrid rows={rows} columns={columns} loading={query.isLoading} disableRowSelectionOnClick pageSizeOptions={[10, 25, 50]} sx={{ border: 0 }} /></Paper></>
}

const freshForm = (): DefinitionInput => ({
  title: '', instructions: '', schedule_kind: 'manual', priority: 5,
  miss_policy: 'run_late', max_lateness_minutes: 30, window_before_minutes: 0,
  one_shot_at: null, lease_seconds: 1800,
  max_attempts: 3, interval_minutes: 60, interval_anchor_at: null,
  daily_time_local: '10:00', timezone_name: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Europe/Madrid',
})

function RuleFormPage() {
  const { id } = useParams()
  const edit = Boolean(id)
  const navigate = useNavigate()
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['definition', id], queryFn: () => api.definition(id!), enabled: edit })
  const [form, setForm] = useState<DefinitionInput>(freshForm)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  useEffect(() => { if (query.data) { const row = query.data.definition; setForm({ title: row.title, instructions: row.instructions, schedule_kind: row.one_shot_at ? 'one_shot' : row.schedule_kind, priority: row.priority, miss_policy: row.miss_policy, max_lateness_minutes: row.max_lateness_minutes, window_before_minutes: row.window_before_minutes, one_shot_at: row.one_shot_at, lease_seconds: row.lease_seconds, max_attempts: row.max_attempts, interval_minutes: row.interval_minutes || 60, interval_anchor_at: row.interval_anchor_at, daily_time_local: row.daily_time_local || '10:00', timezone_name: row.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'Europe/Madrid' }) } }, [query.data])
  const save = useMutation({ mutationFn: () => edit ? api.update(id!, form, query.data!.definition.version) : api.create(form), onSuccess: result => { client.invalidateQueries(); navigate(`/rules/${result.id}`); setMessage('Rule saved.') }, onError: e => setError((e as Error).message) })
  const toggle = useMutation({ mutationFn: () => api.toggle(id!, !Boolean(query.data!.definition.is_active), query.data!.definition.version), onSuccess: () => { client.invalidateQueries(); query.refetch(); setMessage('Rule status updated.') }, onError: e => setError((e as Error).message) })
  const archive = useMutation({ mutationFn: () => api.archive(id!, query.data!.definition.version), onSuccess: () => { client.invalidateQueries(); navigate('/rules') }, onError: e => setError((e as Error).message) })
  const trigger = useMutation({ mutationFn: () => api.trigger(id!), onSuccess: result => { client.invalidateQueries(); navigate(`/tasks/${result.id}`) }, onError: e => setError((e as Error).message) })
  const set = <K extends keyof DefinitionInput>(key: K, value: DefinitionInput[K]) => setForm(current => ({ ...current, [key]: value }))
  if (edit && query.isLoading) return <Loading />
  if (query.error) return <ErrorBox error={query.error} />
  return <>
    <Button component={RouterLink} to="/rules" startIcon={<ArrowBackRounded />} sx={{ mb: 2 }}>Back to rules</Button>
    <PageTitle title={edit ? 'Edit rule' : 'New rule'} description="Define what the agent should do and when the task becomes available." action={edit && !query.data?.definition.archived_at && <Stack direction="row" gap={1} flexWrap="wrap"><ConfirmButton label={query.data?.definition.is_active ? 'Paused' : 'Resume'} message={query.data?.definition.is_active ? 'New tasks for this rule will not be made available to agents. Continue?' : 'Resume this rule?'} onConfirm={() => toggle.mutate()} icon={<PauseRounded />} /><Button variant="outlined" disabled={!query.data?.definition.is_active} startIcon={<PlayArrowRounded />} onClick={() => trigger.mutate()}>Run now</Button><ConfirmButton label="Archive" color="error" message="Archive this rule and cancel tasks that have not been leased?" onConfirm={() => archive.mutate()} /></Stack>} />
    {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}
    {message && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMessage('')}>{message}</Alert>}
    {query.data?.definition.archived_at && <Alert severity="info" sx={{ mb: 2 }}>This rule is archived. Its history is read-only.</Alert>}
    <Box component="form" onSubmit={event => { event.preventDefault(); setError(''); save.mutate() }}>
      <Card sx={{ mb: 2 }}><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Task</Typography><Stack gap={2.5}>
        <TextField label="Title" value={form.title} onChange={e => set('title', e.target.value)} required inputProps={{ maxLength: 200 }} helperText="This title will appear in the queue for you and the agent." />
        <TextField label="Instructions for the agent" value={form.instructions} onChange={e => set('instructions', e.target.value)} required multiline minRows={7} helperText="Describe the expected action and outcome. These instructions are included in every task instance." />
      </Stack></CardContent></Card>
      <Card sx={{ mb: 2 }}><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Schedule</Typography><Stack gap={2.5}>
        <FormControl fullWidth><InputLabel>When to run</InputLabel><Select label="When to run" value={form.schedule_kind} onChange={e => { const kind = e.target.value as ScheduleKind; setForm(current => ({ ...current, schedule_kind: kind, one_shot_at: kind === 'one_shot' ? current.one_shot_at : null, miss_policy: kind === 'manual' || kind === 'one_shot' && current.miss_policy === 'merge_next' ? 'run_late' : current.miss_policy })) }}><MenuItem value="manual">Manually only</MenuItem><MenuItem value="one_shot">Once</MenuItem><MenuItem value="interval">Every N minutes</MenuItem><MenuItem value="daily">Daily at a set time</MenuItem></Select></FormControl>
        {form.schedule_kind === 'manual' && <Alert severity="info">The task enters the queue after you click Run now.</Alert>}
        {form.schedule_kind === 'one_shot' && <TextField label="One-time run (ISO 8601 with time zone)" value={form.one_shot_at || ''} onChange={e => set('one_shot_at', e.target.value || null)} placeholder="2026-11-11T10:00:00+01:00" required helperText="Enter local time with a UTC offset, for example +01:00." />}
        {form.schedule_kind === 'interval' && <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2 }}><TextField label="Repeat every (minutes)" type="number" value={form.interval_minutes ?? ''} onChange={e => set('interval_minutes', Number(e.target.value))} required inputProps={{ min: 1, step: 1 }} helperText="For example, 60 means hourly." /><TextField label="UTC anchor (optional)" value={form.interval_anchor_at || ''} onChange={e => set('interval_anchor_at', e.target.value || null)} placeholder="2026-11-04T10:00:00+00:00" helperText="Leave blank to count from rule creation." /></Box>}
        {form.schedule_kind === 'daily' && <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2 }}><TextField label="Local time" type="time" value={form.daily_time_local || ''} onChange={e => set('daily_time_local', e.target.value)} required InputLabelProps={{ shrink: true }} helperText="When the task becomes available each day." /><TextField label="Time zone" value={form.timezone_name || ''} onChange={e => set('timezone_name', e.target.value)} required helperText="For example, Europe/Madrid. Daylight saving time is handled automatically." /></Box>}
      </Stack></CardContent></Card>
      <Card sx={{ mb: 3 }}><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Queue behavior</Typography><Box sx={{ maxWidth: 440, mb: 2 }}><Typography gutterBottom>Priority: <strong>{form.priority}</strong></Typography><Slider min={0} max={9} marks value={form.priority} onChange={(_, value) => set('priority', value as number)} valueLabelDisplay="auto" /><FormHelperText>9 is highest, 0 is lowest.</FormHelperText></Box>
        {form.schedule_kind !== 'manual' && <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2, mb: 2 }}><FormControl fullWidth><InputLabel>If a run is missed</InputLabel><Select label="If a run is missed" value={form.miss_policy} onChange={e => set('miss_policy', e.target.value as MissPolicy)}><MenuItem value="run_late">Run late</MenuItem><MenuItem value="skip">Skip</MenuItem>{form.schedule_kind !== 'one_shot' && <MenuItem value="merge_next">Merge into next</MenuItem>}</Select></FormControl></Box>}
        {form.schedule_kind !== 'manual' && <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2 }}><TextField label="Early start window (minutes)" type="number" value={form.window_before_minutes} onChange={e => set('window_before_minutes', Number(e.target.value))} inputProps={{ min: 0 }} /><TextField label="Late start window (minutes)" type="number" value={form.max_lateness_minutes} onChange={e => set('max_lateness_minutes', Number(e.target.value))} inputProps={{ min: 0 }} /></Box>}
        <Box component="details" sx={{ pt: 1 }}><Box component="summary" sx={{ cursor: 'pointer', color: 'primary.main', fontWeight: 650, mb: 2 }}>Advanced execution settings</Box><Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2 }}><TextField label="Agent lease (seconds)" type="number" value={form.lease_seconds} onChange={e => set('lease_seconds', Number(e.target.value))} inputProps={{ min: 1 }} helperText="Time before a task may be reassigned if its agent disappears." /><TextField label="Maximum attempts" type="number" value={form.max_attempts} onChange={e => set('max_attempts', Number(e.target.value))} inputProps={{ min: 1 }} helperText="Includes the first attempt." /></Box></Box>
      </CardContent></Card>
      <Stack direction="row" gap={1}><Button type="submit" variant="contained" size="large" disabled={save.isPending || Boolean(query.data?.definition.archived_at)}>{save.isPending ? 'Saving…' : 'Save rule'}</Button><Button component={RouterLink} to="/rules">Cancel</Button></Stack>
    </Box>
    {edit && query.data && <Box sx={{ mt: 5 }}><Typography variant="h6" fontWeight={700} gutterBottom>Rule history</Typography><Paper variant="outlined">{query.data.events.map(event => <Box key={event.id} sx={{ p: 1.5, borderBottom: 1, borderColor: 'divider' }}><Typography variant="body2"><strong>{event.action}</strong> · {dateTime(event.occurred_at)} · {event.actor}</Typography></Box>)}</Paper></Box>}
  </>
}

function TaskPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['instance', id], queryFn: () => api.instance(id!), refetchInterval: 30_000 })
  const rule = useQuery({ queryKey: ['taskRule', query.data?.instance.definition_id], queryFn: () => api.definition(query.data!.instance.definition_id), enabled: Boolean(query.data) })
  const [error, setError] = useState('')
  const cancel = useMutation({ mutationFn: () => api.cancel(id!), onSuccess: () => { client.invalidateQueries(); query.refetch() }, onError: e => setError((e as Error).message) })
  const retry = useMutation({ mutationFn: () => api.retry(id!), onSuccess: result => { client.invalidateQueries(); navigate(`/tasks/${result.id}`) }, onError: e => setError((e as Error).message) })
  if (query.isLoading) return <Loading />
  if (query.error) return <ErrorBox error={query.error} />
  const task = query.data!.instance
  let result = task.result_json || ''
  try { if (result) result = JSON.parse(result) } catch { /* Show original text. */ }
  return <>
    <Button component={RouterLink} to="/queue" startIcon={<ArrowBackRounded />} sx={{ mb: 2 }}>Back to queue</Button>
    <PageTitle title={task.title_snapshot} description={`Task ${task.id}`} action={<Stack direction="row" gap={1}><StatusChip status={task.status} />{(['future', 'ready', 'leased'] as Status[]).includes(task.status) && <ConfirmButton label="Cancel" color="error" message="Cancel this task instance? An agent holding a lease may already be working." onConfirm={() => cancel.mutate()} />}{(['failed', 'cancelled'] as Status[]).includes(task.status) && rule.data?.definition.is_active && !rule.data.definition.archived_at && <Button variant="outlined" onClick={() => retry.mutate()}>Retry</Button>}</Stack>} />
    {error && <ErrorBox error={new Error(error)} />}
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'minmax(0,2fr) minmax(300px,1fr)' }, gap: 3 }}>
      <Stack gap={3}><Card><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Agent instructions</Typography><Typography sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{task.instructions_snapshot}</Typography></CardContent></Card>
        {(task.result_json || task.last_error) && <Card><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Result</Typography>{task.last_error && <Alert severity="error" sx={{ mb: 2 }}>{task.last_error}</Alert>}{result && <Typography component="pre" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontFamily: 'inherit', m: 0 }}>{result}</Typography>}</CardContent></Card>}
        <Card><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Events</Typography>{query.data!.events.map(event => <Box key={event.id} sx={{ py: 1.2, borderBottom: 1, borderColor: 'divider' }}><Typography fontWeight={650}>{event.action}</Typography><Typography variant="body2" color="text.secondary">{dateTime(event.occurred_at)} · {event.actor}{event.reason ? ` · ${event.reason}` : ''}</Typography></Box>)}</CardContent></Card>
      </Stack>
      <Stack gap={3}><Card><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Details</Typography>{([['Scheduled for', dateTime(task.scheduled_at)], ['Available from', dateTime(task.ready_at)], ['Priority', task.priority_snapshot], ['Attempts', task.attempt_count], ['Coverage start', dateTime(task.coverage_start)], ['Coverage end', dateTime(task.coverage_end)], ['Created', dateTime(task.created_at)]] as [string, string | number][]).map(([label, value]) => <Box key={label} sx={{ py: 1, borderBottom: 1, borderColor: 'divider' }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography>{value}</Typography></Box>)}<Button component={RouterLink} to={`/rules/${task.definition_id}`} startIcon={<EditRounded />} sx={{ mt: 2 }}>Open rule</Button></CardContent></Card>
        <Card><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Attempts</Typography>{query.data!.attempts.length ? query.data!.attempts.map(attempt => <Box key={attempt.id} sx={{ py: 1.2, borderBottom: 1, borderColor: 'divider' }}><Typography fontWeight={650}>Attempt {attempt.attempt_number} · {attempt.outcome || 'in progress'}</Typography><Typography variant="body2" color="text.secondary">{dateTime(attempt.claimed_at)}{attempt.completed_at ? ` → ${dateTime(attempt.completed_at)}` : ''}</Typography>{attempt.error && <Typography color="error">{attempt.error}</Typography>}</Box>) : <Typography color="text.secondary">No attempts yet.</Typography>}</CardContent></Card>
      </Stack>
    </Box>
  </>
}

function AutoApprovalBanner() {
  const state = useQuery({ queryKey: ['autoApproval'], queryFn: api.autoApproval, refetchInterval: 30_000 })
  if (!state.data?.enabled) return null
  return <Alert severity="warning" sx={{ mb: 3 }}>Automatic approval of MCP proposals is enabled until {dateTime(state.data.until)}. <Button component={RouterLink} to="/proposals" size="small">Manage</Button></Alert>
}

function ProposalsPage() {
  const client = useQueryClient()
  const [error, setError] = useState('')
  const pending = useQuery({ queryKey: ['proposals', 'pending'], queryFn: () => api.proposals('pending'), refetchInterval: 20_000 })
  const recent = useQuery({ queryKey: ['proposals', 'decided'], queryFn: () => api.proposals(), refetchInterval: 30_000 })
  const auto = useQuery({ queryKey: ['autoApproval'], queryFn: api.autoApproval, refetchInterval: 20_000 })
  const decision = useMutation({ mutationFn: ({ id, approve }: { id: string; approve: boolean }) => api.decideProposal(id, approve), onSuccess: () => client.invalidateQueries(), onError: e => setError((e as Error).message) })
  const toggleAuto = useMutation({ mutationFn: (enabled: boolean) => api.setAutoApproval(enabled), onSuccess: () => client.invalidateQueries(), onError: e => setError((e as Error).message) })
  const impactText = (p: Proposal) => {
    const i = p.impact
    if (p.operation === 'create_rule') return 'Creates a rule and its current scheduled runs.'
    if (p.operation === 'run_rule') return 'Creates one additional manual run.'
    if (p.operation === 'cancel_instance') return `Cancels an instance in state ${i?.current_status || 'unknown'}.`
    if (p.operation === 'retry_instance') return `Creates a new manual retry for an instance in state ${i?.current_status || 'unknown'}.`
    if (p.operation === 'archive_rule') return `Cancels ${i?.unleased ?? 0} unleased instances; ${i?.leased ?? 0} active leases will be preserved.`
    if (p.payload.is_active === false) return `Pausing will cancel ${i?.unstarted ?? 0} unleased automatic runs and ${i?.queued_retries ?? 0} pending automatic retries.`
    if (['schedule_kind', 'interval_minutes', 'interval_anchor_at', 'daily_time_local', 'timezone_name', 'one_shot_at'].some(key => key in p.payload)) return `Rebuilds up to ${i?.unstarted ?? 0} automatic runs without attempts; active leases remain.`
    return `Updates up to ${i?.unstarted ?? 0} automatic runs without attempts; ${i?.queued_retries ?? 0} pending retries retain their existing parameters.`
  }
  const card = (proposal: Proposal) => <Card key={proposal.id} sx={{ mb: 2 }}><CardContent><Stack direction="row" justifyContent="space-between" gap={2}><Box><Typography fontWeight={700}>{proposal.operation}</Typography><Typography variant="body2" color="text.secondary">{dateTime(proposal.created_at)} · {proposal.target_id || 'New rule'} · {proposal.status}</Typography></Box>{proposal.status === 'pending' && <Stack direction="row" gap={1}><Button variant="contained" disabled={decision.isPending} onClick={() => decision.mutate({ id: proposal.id, approve: true })}>Approve</Button><Button variant="outlined" disabled={decision.isPending} onClick={() => decision.mutate({ id: proposal.id, approve: false })}>Reject</Button></Stack>}</Stack><Typography variant="caption" color="text.secondary">Rule version: {proposal.expected_version ?? '—'}</Typography>{proposal.status === 'pending' && <Typography variant="body2" sx={{ mt: 1 }}>{impactText(proposal)}</Typography>}<Box component="pre" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', bgcolor: '#f5f7fb', p: 2, borderRadius: 1, fontSize: 13 }}>{JSON.stringify(proposal.payload, null, 2)}</Box>{proposal.result && <Typography variant="body2">Result: {JSON.stringify(proposal.result)}</Typography>}{proposal.reason && <Alert severity="warning">{proposal.reason}</Alert>}</CardContent></Card>
  return <><PageTitle title="Agent proposals" description="Review proposed changes before applying them." />{error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}<Card sx={{ mb: 3 }}><CardContent><Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems="center" gap={2}><Box><Typography fontWeight={700}>Automatic approval</Typography><Typography variant="body2" color="text.secondary">{auto.data?.enabled ? `Enabled until ${dateTime(auto.data.until)}` : 'Disabled. New MCP proposals await a decision.'}</Typography></Box><Button variant={auto.data?.enabled ? 'outlined' : 'contained'} color={auto.data?.enabled ? 'error' : 'primary'} disabled={toggleAuto.isPending || !auto.data} onClick={() => toggleAuto.mutate(!auto.data!.enabled)}>{auto.data?.enabled ? 'Disable' : 'Enable for one hour'}</Button></Stack></CardContent></Card><Typography variant="h6" sx={{ mb: 2 }}>Pending approval</Typography>{pending.isLoading ? <Loading /> : pending.error ? <ErrorBox error={pending.error} /> : pending.data?.proposals.length ? pending.data.proposals.map(card) : <Empty text="No proposals." />}<Typography variant="h6" sx={{ mt: 4, mb: 2 }}>Recent decisions</Typography>{recent.data?.proposals.filter(p => p.status !== 'pending').slice(0, 20).map(card)}</>
}

function AuthGate() {
  const client = useQueryClient()
  const session = useQuery({
    queryKey: ['queue-auth', managedQueue ? 'managed' : 'standalone'],
    queryFn: managedQueue
      ? async () => {
          const response = await fetch('/admin/api/session', { credentials: 'same-origin', cache: 'no-store' })
          if (!response.ok) throw new Error('Manager session unavailable')
          return response.json() as Promise<{ authenticated: boolean; csrf_token: string }>
        }
      : api.session,
    refetchInterval: 30_000,
  })
  const [pin, setPin] = useState('')
  const login = useMutation({
    mutationFn: () => api.login(pin),
    onSuccess: () => { clearCsrf(); setPin(''); client.invalidateQueries() },
  })
  useEffect(() => {
    if (managedQueue && session.data && !session.data.authenticated) window.location.assign('/admin/')
  }, [session.data])
  if (session.isLoading || (managedQueue && session.data && !session.data.authenticated)) return <Loading />
  if (session.error) return <ErrorBox error={session.error} />
  if (session.data?.authenticated) return <Shell />
  return <Container maxWidth="xs" sx={{ pt: 12 }}><Card><CardContent sx={{ p: 4 }}>
    <Typography variant="h5" fontWeight={700} gutterBottom>Task Queue sign-in</Typography>
    <Typography color="text.secondary" sx={{ mb: 3 }}>Enter your six-digit PIN.</Typography>
    <Box component="form" onSubmit={event => { event.preventDefault(); login.mutate() }}>
      <TextField label="PIN" type="password" value={pin} onChange={event => setPin(event.target.value)}
        inputProps={{ maxLength: 6, inputMode: 'numeric', pattern: '[0-9]{6}' }} fullWidth required autoFocus />
      <Button type="submit" variant="contained" fullWidth sx={{ mt: 2 }}
        disabled={login.isPending || !/^[0-9]{6}$/.test(pin)}>Sign in</Button>
    </Box>
    {login.error && <Alert severity="error" sx={{ mt: 2 }}>{login.error.message}</Alert>}
  </CardContent></Card></Container>
}

export default function App() { return <AuthGate /> }
