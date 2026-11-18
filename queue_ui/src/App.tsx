import { useEffect, useMemo, useState } from 'react'
import { Link as RouterLink, NavLink, Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { DataGrid, type GridColDef } from '@mui/x-data-grid'
import {
  Alert, AppBar, Box, Button, Card, CardContent, Chip, CircularProgress, Container,
  Dialog, DialogActions, DialogContent, DialogTitle, Divider, Drawer, FormControl,
  FormHelperText, IconButton, InputLabel, MenuItem, Paper, Select, Slider, Stack,
  Tab, Tabs, TextField, Toolbar, Tooltip, Typography, useMediaQuery, useTheme,
} from '@mui/material'
import {
  AddRounded, ArrowBackRounded, AssignmentRounded, DashboardRounded,
  EditRounded, MenuRounded, PauseRounded, PlayArrowRounded, RefreshRounded,
  RuleRounded,
} from '@mui/icons-material'
import { api, clearCsrf } from './api'
import { adminApi, clearAdminCsrf, type AdminSession } from './adminApi'
import { GatewayPage, SecurityPage, TelegramPage } from './AdminPages'
import type { Definition, DefinitionInput, Instance, MissPolicy, Proposal, ScheduleKind, Status } from './types'

const statuses: Status[] = ['future', 'ready', 'leased', 'succeeded', 'failed', 'skipped', 'merged', 'cancelled']
const legacyQueue = window.location.pathname.startsWith('/queue')
const statusLabel: Record<Status, string> = {
  future: 'Майбутня', ready: 'Готова', leased: 'Виконується', succeeded: 'Виконана',
  failed: 'Помилка', skipped: 'Пропущена', merged: 'Об’єднана', cancelled: 'Скасована',
}
const statusColor: Record<Status, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  future: 'default', ready: 'info', leased: 'warning', succeeded: 'success',
  failed: 'error', skipped: 'default', merged: 'default', cancelled: 'default',
}

function dateTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('uk-UA', {
    dateStyle: 'medium', timeStyle: 'short',
  }).format(date)
}

function StatusChip({ status }: { status: Status }) {
  return <Chip size="small" label={statusLabel[status]} color={statusColor[status]} variant={status === 'future' ? 'outlined' : 'filled'} />
}

function Loading() { return <Box sx={{ display: 'flex', justifyContent: 'center', p: 8 }}><CircularProgress /></Box> }
function ErrorBox({ error }: { error: unknown }) { return <Alert severity="error">{error instanceof Error ? error.message : 'Не вдалося завантажити дані.'}</Alert> }
function Empty({ text }: { text: string }) { return <Paper variant="outlined" sx={{ p: 4, textAlign: 'center', color: 'text.secondary' }}>{text}</Paper> }

function PageTitle({ title, description, action }: { title: string; description?: string; action?: React.ReactNode }) {
  return <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', sm: 'center' }} gap={2} sx={{ mb: 3 }}>
    <Box><Typography variant="h4" fontWeight={750} sx={{ letterSpacing: '-.035em' }}>{title}</Typography>{description && <Typography color="text.secondary" sx={{ mt: .5 }}>{description}</Typography>}</Box>
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
      <DialogTitle>Підтвердити дію</DialogTitle><DialogContent><Typography>{message}</Typography></DialogContent>
      <DialogActions><Button onClick={() => setOpen(false)}>Назад</Button><Button color={color} variant="contained" onClick={() => { setOpen(false); onConfirm() }}>Підтвердити</Button></DialogActions>
    </Dialog>
  </>
}

const nav = [
  { to: '/', text: 'Огляд', icon: <DashboardRounded fontSize="small" /> },
  { to: '/queue', text: 'Черга', icon: <AssignmentRounded fontSize="small" /> },
  { to: '/rules', text: 'Правила', icon: <RuleRounded fontSize="small" /> },
  { to: '/proposals', text: 'Пропозиції', icon: <AssignmentRounded fontSize="small" /> },
]

function Shell() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const queryClient = useQueryClient()
  const theme = useTheme()
  const mobile = useMediaQuery(theme.breakpoints.down('md'))
  const content = <Box sx={{ p: 2.5, height: '100%' }}>
    <Box sx={{ px: 1, pb: 3 }}><Typography variant="overline" color="primary" fontWeight={800} letterSpacing={2}>NOGAI</Typography><Typography variant="h6" fontWeight={750}>Менеджер задач</Typography><Typography variant="body2" color="text.secondary">Локальна черга агента</Typography></Box>
    <Stack gap={.5}>{nav.map(item => <Box key={item.to} component={NavLink} end={item.to === '/'} to={item.to} onClick={() => setMobileOpen(false)} sx={{ textDecoration: 'none', color: 'text.secondary', display: 'flex', alignItems: 'center', gap: 1.5, px: 2, py: 1.3, borderRadius: 2, '&.active': { bgcolor: '#e9f0fb', color: 'primary.main', fontWeight: 700 }, '&:hover': { bgcolor: '#f0f4fa' } }}>{item.icon}{item.text}</Box>)}</Stack>
    <Divider sx={{ my: 3 }} /><Button sx={{ mx: 1 }} onClick={async () => { await api.logout(); clearCsrf(); queryClient.clear(); window.location.assign('/queue/') }}>Вийти</Button><Typography variant="caption" color="text.secondary" sx={{ px: 1 }}>Доступно в локальній мережі</Typography>
  </Box>
  return <Box sx={{ display: 'flex', minHeight: '100vh' }}>
    {mobile ? <><AppBar position="fixed" color="inherit" elevation={0} sx={{ borderBottom: 1, borderColor: 'divider' }}><Toolbar><IconButton onClick={() => setMobileOpen(true)} aria-label="Відкрити меню"><MenuRounded /></IconButton><Typography fontWeight={700} sx={{ ml: 1 }}>Менеджер задач</Typography></Toolbar></AppBar><Drawer open={mobileOpen} onClose={() => setMobileOpen(false)} PaperProps={{ sx: { width: 250 } }}>{content}</Drawer></> : <Drawer variant="permanent" PaperProps={{ sx: { width: 250, borderRight: 1, borderColor: 'divider' } }}>{content}</Drawer>}
    <Box component="main" sx={{ flex: 1, minWidth: 0, ml: mobile ? 0 : '250px', pt: mobile ? 10 : 5, pb: 7 }}><Container maxWidth="xl"><AutoApprovalBanner /><Routes>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/queue" element={<QueuePage />} />
      <Route path="/tasks/:id" element={<TaskPage />} />
      <Route path="/rules" element={<RulesPage />} />
      <Route path="/rules/new" element={<RuleFormPage />} />
      <Route path="/rules/:id" element={<RuleFormPage />} />
      <Route path="/proposals" element={<ProposalsPage />} />
      <Route path="*" element={<Empty text="Сторінку не знайдено." />} />
    </Routes></Container></Box>
  </Box>
}

function Metric({ label, value, note, color }: { label: string; value: string | number; note?: string; color?: string }) {
  return <Card><CardContent sx={{ p: 2.5 }}><Typography variant="body2" color="text.secondary">{label}</Typography><Typography variant="h3" sx={{ fontWeight: 750, color: color || 'text.primary', my: .6 }}>{value}</Typography><Typography variant="caption" color="text.secondary">{note || ' '}</Typography></CardContent></Card>
}

function TaskList({ tasks, empty }: { tasks: Instance[]; empty: string }) {
  if (!tasks.length) return <Empty text={empty} />
  return <Paper variant="outlined" sx={{ overflow: 'hidden' }}>{tasks.map((task, index) => <Box key={task.id} component={RouterLink} to={`/tasks/${task.id}`} sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 2, p: 2, textDecoration: 'none', color: 'text.primary', borderBottom: index < tasks.length - 1 ? 1 : 0, borderColor: 'divider', '&:hover': { bgcolor: '#f8faff' } }}><Box sx={{ minWidth: 0 }}><Typography fontWeight={650} noWrap>{task.title_snapshot}</Typography><Typography variant="caption" color="text.secondary">{dateTime(task.scheduled_at)} · Пріоритет {task.priority_snapshot}</Typography></Box><StatusChip status={task.status} /></Box>)}</Paper>
}

function DashboardPage() {
  const client = useQueryClient()
  const overview = useQuery({ queryKey: ['overview'], queryFn: api.overview, refetchInterval: 30_000 })
  const rules = useQuery({ queryKey: ['definitions'], queryFn: api.definitions, refetchInterval: 30_000 })
  if (overview.isLoading || rules.isLoading) return <Loading />
  if (overview.error || rules.error) return <ErrorBox error={overview.error || rules.error} />
  const data = overview.data!
  return <>
    <PageTitle title="Огляд черги" description="Поточний стан задач та найближчі запуски" action={<Stack direction="row" gap={1}><Tooltip title="Оновити"><IconButton onClick={() => client.invalidateQueries()}><RefreshRounded /></IconButton></Tooltip><Button component={RouterLink} to="/rules/new" variant="contained" startIcon={<AddRounded />}>Нове правило</Button></Stack>} />
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', lg: 'repeat(4,1fr)' }, gap: 2, mb: 3 }}>
      <Metric label="Доступні агенту зараз" value={data.claimable_count} note="Готові до отримання" color="#2456a7" />
      <Metric label="Майбутні" value={data.counts.future || 0} note="Створені наперед" />
      <Metric label="Виконуються" value={data.counts.leased || 0} note="Зарезервовані агентом" />
      <Metric label="Активні правила" value={data.active_rule_count} note={`Усього правил: ${data.rule_count}`} />
    </Box>
    <Alert severity={data.claimable_count ? 'info' : 'success'} sx={{ mb: 3 }}>
      {data.claimable_count ? `Агент може взяти ${data.claimable_count} задач(у) зараз.` : 'Зараз готових задач немає.'}
      {data.next_due_at ? ` Наступна запланована на ${dateTime(data.next_due_at)}.` : ''} Майбутні задачі стають доступними лише у свій час.
    </Alert>
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: '1fr 1fr' }, gap: 3 }}>
      <Box><SectionHeading title="Готові зараз" to="/queue?status=ready" /><TaskList tasks={data.claimable} empty="Готових задач немає." /></Box>
      <Box><SectionHeading title="Наступні запуски" to="/queue?status=future" /><TaskList tasks={data.upcoming.slice(0, 6)} empty="Майбутніх задач немає." /></Box>
      <Box><SectionHeading title="Останні результати" to="/queue?status=succeeded" /><TaskList tasks={data.recent.slice(0, 6)} empty="Поки немає завершених задач." /></Box>
      <Box><SectionHeading title="Правила" to="/rules" /><Paper variant="outlined">{rules.data!.definitions.slice(0, 6).map((rule, index) => <Box key={rule.id} component={RouterLink} to={`/rules/${rule.id}`} sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, p: 2, color: 'text.primary', textDecoration: 'none', borderBottom: index < Math.min(rules.data!.definitions.length, 6) - 1 ? 1 : 0, borderColor: 'divider', '&:hover': { bgcolor: '#f8faff' } }}><Typography fontWeight={650}>{rule.title}</Typography><Chip size="small" color={rule.is_active && !rule.archived_at ? 'success' : 'default'} label={rule.archived_at ? 'Архів' : rule.is_active ? 'Активне' : 'Пауза'} /></Box>)}{!rules.data!.definitions.length && <Box p={3}>Правил ще немає.</Box>}</Paper></Box>
    </Box>
  </>
}

function SectionHeading({ title, to }: { title: string; to: string }) { return <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}><Typography variant="h6" fontWeight={700}>{title}</Typography><Button component={RouterLink} to={to} size="small">Усі</Button></Stack> }

function QueuePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const status = searchParams.get('status') || ''
  const [search, setSearch] = useState('')
  const query = useQuery({ queryKey: ['instances', status], queryFn: () => api.instances(status), refetchInterval: 30_000 })
  const overview = useQuery({ queryKey: ['overview'], queryFn: api.overview, refetchInterval: 30_000 })
  const rows = useMemo(() => (query.data?.instances || []).filter(row => row.title_snapshot.toLowerCase().includes(search.toLowerCase()) || row.id.includes(search)), [query.data, search])
  const columns: GridColDef<Instance>[] = [
    { field: 'title_snapshot', headerName: 'Задача', flex: 2, minWidth: 220, renderCell: p => <RouterLink to={`/tasks/${p.row.id}`} style={{ color: '#2456a7', fontWeight: 650, textDecoration: 'none' }}>{p.value}</RouterLink> },
    { field: 'status', headerName: 'Стан', width: 150, renderCell: p => <StatusChip status={p.value as Status} /> },
    { field: 'scheduled_at', headerName: 'Заплановано', width: 190, valueFormatter: value => dateTime(value as string) },
    { field: 'priority_snapshot', headerName: 'Пріоритет', width: 110 },
    { field: 'attempt_count', headerName: 'Спроби', width: 100 },
  ]
  return <>
    <PageTitle title="Черга задач" description="Сортуйте та фільтруйте екземпляри. Час відображається у вашому часовому поясі." action={<Button component={RouterLink} to="/rules/new" variant="contained" startIcon={<AddRounded />}>Нове правило</Button>} />
    {overview.data && <Alert severity="info" sx={{ mb: 2 }}>Доступні агенту зараз: <strong>{overview.data.claimable_count}</strong>. Майбутні задачі вже створені, але ще не можуть бути взяті.</Alert>}
    <Paper variant="outlined" sx={{ p: 2 }}><Stack direction={{ xs: 'column', sm: 'row' }} gap={2} sx={{ mb: 2 }}>
      <FormControl size="small" sx={{ minWidth: 190 }}><InputLabel>Стан</InputLabel><Select label="Стан" value={status} onChange={e => setSearchParams(e.target.value ? { status: e.target.value } : {})}><MenuItem value="">Усі стани</MenuItem>{statuses.map(item => <MenuItem key={item} value={item}>{statusLabel[item]}</MenuItem>)}</Select></FormControl>
      <TextField size="small" label="Пошук за назвою або ID" value={search} onChange={e => setSearch(e.target.value)} sx={{ flex: 1 }} />
      <Tooltip title="Оновити"><IconButton onClick={() => { query.refetch(); overview.refetch() }}><RefreshRounded /></IconButton></Tooltip>
    </Stack>
    {query.error && <ErrorBox error={query.error} />}
    <Box sx={{ height: 610, width: '100%' }}><DataGrid rows={rows} columns={columns} loading={query.isLoading} disableRowSelectionOnClick pageSizeOptions={[10, 25, 50, 100]} initialState={{ pagination: { paginationModel: { pageSize: 25, page: 0 } }, sorting: { sortModel: [{ field: 'scheduled_at', sort: 'asc' }] } }} sx={{ border: 0, '& .MuiDataGrid-columnHeaders': { bgcolor: '#f8faff' } }} /></Box></Paper>
  </>
}

function RulesPage() {
  const query = useQuery({ queryKey: ['definitions'], queryFn: api.definitions, refetchInterval: 30_000 })
  const rows = query.data?.definitions || []
  const columns: GridColDef<Definition>[] = [
    { field: 'title', headerName: 'Правило', flex: 2, minWidth: 220, renderCell: p => <RouterLink to={`/rules/${p.row.id}`} style={{ color: '#2456a7', fontWeight: 650, textDecoration: 'none' }}>{p.value}</RouterLink> },
    { field: 'schedule_kind', headerName: 'Розклад', width: 150, renderCell: p => p.row.one_shot_at ? 'Один раз' : ({ manual: 'Ручний', one_shot: 'Один раз', interval: 'Інтервал', daily: 'Щодня' })[p.value as ScheduleKind] },
    { field: 'priority', headerName: 'Пріоритет', width: 110 },
    { field: 'is_active', headerName: 'Стан', width: 130, renderCell: p => <Chip size="small" label={p.row.archived_at ? 'Архів' : p.value ? 'Активне' : 'Пауза'} color={p.value && !p.row.archived_at ? 'success' : 'default'} /> },
    { field: 'next_visible_at', headerName: 'Найближча задача', width: 210, valueFormatter: value => dateTime(value as string | null) },
    { field: 'id', headerName: '', width: 100, sortable: false, renderCell: p => <Button component={RouterLink} to={`/rules/${p.value}`} size="small">Відкрити</Button> },
  ]
  return <><PageTitle title="Правила" description="Цілі, розклади та політики пропусків" action={<Button component={RouterLink} to="/rules/new" variant="contained" startIcon={<AddRounded />}>Нове правило</Button>} />{query.error && <ErrorBox error={query.error} />}<Paper variant="outlined" sx={{ height: 650 }}><DataGrid rows={rows} columns={columns} loading={query.isLoading} disableRowSelectionOnClick pageSizeOptions={[10, 25, 50]} sx={{ border: 0 }} /></Paper></>
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
  const save = useMutation({ mutationFn: () => edit ? api.update(id!, form, query.data!.definition.version) : api.create(form), onSuccess: result => { client.invalidateQueries(); navigate(`/rules/${result.id}`); setMessage('Правило збережено.') }, onError: e => setError((e as Error).message) })
  const toggle = useMutation({ mutationFn: () => api.toggle(id!, !Boolean(query.data!.definition.is_active), query.data!.definition.version), onSuccess: () => { client.invalidateQueries(); query.refetch(); setMessage('Стан правила оновлено.') }, onError: e => setError((e as Error).message) })
  const archive = useMutation({ mutationFn: () => api.archive(id!, query.data!.definition.version), onSuccess: () => { client.invalidateQueries(); navigate('/rules') }, onError: e => setError((e as Error).message) })
  const trigger = useMutation({ mutationFn: () => api.trigger(id!), onSuccess: result => { client.invalidateQueries(); navigate(`/tasks/${result.id}`) }, onError: e => setError((e as Error).message) })
  const set = <K extends keyof DefinitionInput>(key: K, value: DefinitionInput[K]) => setForm(current => ({ ...current, [key]: value }))
  if (edit && query.isLoading) return <Loading />
  if (query.error) return <ErrorBox error={query.error} />
  return <>
    <Button component={RouterLink} to="/rules" startIcon={<ArrowBackRounded />} sx={{ mb: 2 }}>До правил</Button>
    <PageTitle title={edit ? 'Редагувати правило' : 'Нове правило'} description="Визначте, що робити агенту і коли задача стане доступною." action={edit && !query.data?.definition.archived_at && <Stack direction="row" gap={1} flexWrap="wrap"><ConfirmButton label={query.data?.definition.is_active ? 'Пауза' : 'Відновити'} message={query.data?.definition.is_active ? 'Нові задачі цього правила не видаватимуться агенту. Продовжити?' : 'Відновити правило?'} onConfirm={() => toggle.mutate()} icon={<PauseRounded />} /><Button variant="outlined" disabled={!query.data?.definition.is_active} startIcon={<PlayArrowRounded />} onClick={() => trigger.mutate()}>Запустити зараз</Button><ConfirmButton label="Архівувати" color="error" message="Архівувати правило та скасувати задачі без lease?" onConfirm={() => archive.mutate()} /></Stack>} />
    {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}
    {message && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMessage('')}>{message}</Alert>}
    {query.data?.definition.archived_at && <Alert severity="info" sx={{ mb: 2 }}>Правило архівовано. Історія доступна лише для перегляду.</Alert>}
    <Box component="form" onSubmit={event => { event.preventDefault(); setError(''); save.mutate() }}>
      <Card sx={{ mb: 2 }}><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Задача</Typography><Stack gap={2.5}>
        <TextField label="Назва" value={form.title} onChange={e => set('title', e.target.value)} required inputProps={{ maxLength: 200 }} helperText="Так агент і ви побачите задачу в черзі." />
        <TextField label="Інструкції для агента" value={form.instructions} onChange={e => set('instructions', e.target.value)} required multiline minRows={7} helperText="Опишіть очікувану дію та результат. Інструкції потраплять у кожен екземпляр задачі." />
      </Stack></CardContent></Card>
      <Card sx={{ mb: 2 }}><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Розклад</Typography><Stack gap={2.5}>
        <FormControl fullWidth><InputLabel>Коли запускати</InputLabel><Select label="Коли запускати" value={form.schedule_kind} onChange={e => { const kind = e.target.value as ScheduleKind; setForm(current => ({ ...current, schedule_kind: kind, one_shot_at: kind === 'one_shot' ? current.one_shot_at : null, miss_policy: kind === 'manual' || kind === 'one_shot' && current.miss_policy === 'merge_next' ? 'run_late' : current.miss_policy })) }}><MenuItem value="manual">Лише вручну</MenuItem><MenuItem value="one_shot">Один раз</MenuItem><MenuItem value="interval">Кожні N хвилин</MenuItem><MenuItem value="daily">Щодня о заданій годині</MenuItem></Select></FormControl>
        {form.schedule_kind === 'manual' && <Alert severity="info">Задача з’явиться в черзі після натискання «Запустити зараз».</Alert>}
        {form.schedule_kind === 'one_shot' && <TextField label="Один запуск (ISO 8601 із часовим поясом)" value={form.one_shot_at || ''} onChange={e => set('one_shot_at', e.target.value || null)} placeholder="2026-11-11T10:00:00+01:00" required helperText="Укажіть місцевий час із UTC-зміщенням, наприклад +01:00." />}
        {form.schedule_kind === 'interval' && <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2 }}><TextField label="Повторювати кожні (хвилини)" type="number" value={form.interval_minutes ?? ''} onChange={e => set('interval_minutes', Number(e.target.value))} required inputProps={{ min: 1, step: 1 }} helperText="Наприклад, 60 — щогодини." /><TextField label="Початкова точка UTC (необов’язково)" value={form.interval_anchor_at || ''} onChange={e => set('interval_anchor_at', e.target.value || null)} placeholder="2026-11-04T10:00:00+00:00" helperText="Залиште порожнім, щоб відраховувати від створення правила." /></Box>}
        {form.schedule_kind === 'daily' && <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2 }}><TextField label="Місцевий час" type="time" value={form.daily_time_local || ''} onChange={e => set('daily_time_local', e.target.value)} required InputLabelProps={{ shrink: true }} helperText="Коли задача стає доступною щодня." /><TextField label="Часовий пояс" value={form.timezone_name || ''} onChange={e => set('timezone_name', e.target.value)} required helperText="Наприклад, Europe/Madrid. Перехід на літній час враховується." /></Box>}
      </Stack></CardContent></Card>
      <Card sx={{ mb: 3 }}><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Поведінка черги</Typography><Box sx={{ maxWidth: 440, mb: 2 }}><Typography gutterBottom>Пріоритет: <strong>{form.priority}</strong></Typography><Slider min={0} max={9} marks value={form.priority} onChange={(_, value) => set('priority', value as number)} valueLabelDisplay="auto" /><FormHelperText>9 — найвищий, 0 — найнижчий.</FormHelperText></Box>
        {form.schedule_kind !== 'manual' && <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2, mb: 2 }}><FormControl fullWidth><InputLabel>Якщо запуск пропущено</InputLabel><Select label="Якщо запуск пропущено" value={form.miss_policy} onChange={e => set('miss_policy', e.target.value as MissPolicy)}><MenuItem value="run_late">Виконати із запізненням</MenuItem><MenuItem value="skip">Пропустити</MenuItem>{form.schedule_kind !== 'one_shot' && <MenuItem value="merge_next">Об’єднати з наступним</MenuItem>}</Select></FormControl></Box>}
        {form.schedule_kind !== 'manual' && <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2 }}><TextField label="Можна почати раніше (хвилини)" type="number" value={form.window_before_minutes} onChange={e => set('window_before_minutes', Number(e.target.value))} inputProps={{ min: 0 }} /><TextField label="Можна почати пізніше (хвилини)" type="number" value={form.max_lateness_minutes} onChange={e => set('max_lateness_minutes', Number(e.target.value))} inputProps={{ min: 0 }} /></Box>}
        <Box component="details" sx={{ pt: 1 }}><Box component="summary" sx={{ cursor: 'pointer', color: 'primary.main', fontWeight: 650, mb: 2 }}>Додаткові параметри виконання</Box><Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2 }}><TextField label="Резервування агентом (секунди)" type="number" value={form.lease_seconds} onChange={e => set('lease_seconds', Number(e.target.value))} inputProps={{ min: 1 }} helperText="Час до повторної видачі задачі, якщо агент зникне." /><TextField label="Максимум спроб" type="number" value={form.max_attempts} onChange={e => set('max_attempts', Number(e.target.value))} inputProps={{ min: 1 }} helperText="Разом із першою спробою." /></Box></Box>
      </CardContent></Card>
      <Stack direction="row" gap={1}><Button type="submit" variant="contained" size="large" disabled={save.isPending || Boolean(query.data?.definition.archived_at)}>{save.isPending ? 'Зберігаю…' : 'Зберегти правило'}</Button><Button component={RouterLink} to="/rules">Скасувати</Button></Stack>
    </Box>
    {edit && query.data && <Box sx={{ mt: 5 }}><Typography variant="h6" fontWeight={700} gutterBottom>Історія правила</Typography><Paper variant="outlined">{query.data.events.map(event => <Box key={event.id} sx={{ p: 1.5, borderBottom: 1, borderColor: 'divider' }}><Typography variant="body2"><strong>{event.action}</strong> · {dateTime(event.occurred_at)} · {event.actor}</Typography></Box>)}</Paper></Box>}
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
    <Button component={RouterLink} to="/queue" startIcon={<ArrowBackRounded />} sx={{ mb: 2 }}>До черги</Button>
    <PageTitle title={task.title_snapshot} description={`Задача ${task.id}`} action={<Stack direction="row" gap={1}><StatusChip status={task.status} />{(['future', 'ready', 'leased'] as Status[]).includes(task.status) && <ConfirmButton label="Скасувати" color="error" message="Скасувати цей екземпляр задачі? Агент із чинною орендою може вже виконувати роботу." onConfirm={() => cancel.mutate()} />}{(['failed', 'cancelled'] as Status[]).includes(task.status) && rule.data?.definition.is_active && !rule.data.definition.archived_at && <Button variant="outlined" onClick={() => retry.mutate()}>Повторити</Button>}</Stack>} />
    {error && <ErrorBox error={new Error(error)} />}
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'minmax(0,2fr) minmax(300px,1fr)' }, gap: 3 }}>
      <Stack gap={3}><Card><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Інструкції агенту</Typography><Typography sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{task.instructions_snapshot}</Typography></CardContent></Card>
        {(task.result_json || task.last_error) && <Card><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Результат</Typography>{task.last_error && <Alert severity="error" sx={{ mb: 2 }}>{task.last_error}</Alert>}{result && <Typography component="pre" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontFamily: 'inherit', m: 0 }}>{result}</Typography>}</CardContent></Card>}
        <Card><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Події</Typography>{query.data!.events.map(event => <Box key={event.id} sx={{ py: 1.2, borderBottom: 1, borderColor: 'divider' }}><Typography fontWeight={650}>{event.action}</Typography><Typography variant="body2" color="text.secondary">{dateTime(event.occurred_at)} · {event.actor}{event.reason ? ` · ${event.reason}` : ''}</Typography></Box>)}</CardContent></Card>
      </Stack>
      <Stack gap={3}><Card><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Деталі</Typography>{([['Заплановано', dateTime(task.scheduled_at)], ['Доступна з', dateTime(task.ready_at)], ['Пріоритет', task.priority_snapshot], ['Спроб', task.attempt_count], ['Початок охоплення', dateTime(task.coverage_start)], ['Кінець охоплення', dateTime(task.coverage_end)], ['Створено', dateTime(task.created_at)]] as [string, string | number][]).map(([label, value]) => <Box key={label} sx={{ py: 1, borderBottom: 1, borderColor: 'divider' }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography>{value}</Typography></Box>)}<Button component={RouterLink} to={`/rules/${task.definition_id}`} startIcon={<EditRounded />} sx={{ mt: 2 }}>Відкрити правило</Button></CardContent></Card>
        <Card><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} gutterBottom>Спроби</Typography>{query.data!.attempts.length ? query.data!.attempts.map(attempt => <Box key={attempt.id} sx={{ py: 1.2, borderBottom: 1, borderColor: 'divider' }}><Typography fontWeight={650}>Спроба {attempt.attempt_number} · {attempt.outcome || 'триває'}</Typography><Typography variant="body2" color="text.secondary">{dateTime(attempt.claimed_at)}{attempt.completed_at ? ` → ${dateTime(attempt.completed_at)}` : ''}</Typography>{attempt.error && <Typography color="error">{attempt.error}</Typography>}</Box>) : <Typography color="text.secondary">Спроб ще немає.</Typography>}</CardContent></Card>
      </Stack>
    </Box>
  </>
}

function AutoApprovalBanner() {
  const state = useQuery({ queryKey: ['autoApproval'], queryFn: api.autoApproval, refetchInterval: 30_000 })
  if (!state.data?.enabled) return null
  return <Alert severity="warning" sx={{ mb: 3 }}>Автоматичне затвердження MCP-пропозицій увімкнене до {dateTime(state.data.until)}. <Button component={RouterLink} to="/proposals" size="small">Керувати</Button></Alert>
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
    if (p.operation === 'create_rule') return 'Створить правило та його актуальні запуски.'
    if (p.operation === 'run_rule') return 'Створить один позачерговий ручний запуск.'
    if (p.operation === 'cancel_instance') return `Скасує екземпляр у стані ${i?.current_status || 'невідомо'}.`
    if (p.operation === 'retry_instance') return `Створить новий ручний retry для екземпляра у стані ${i?.current_status || 'невідомо'}.`
    if (p.operation === 'archive_rule') return `Скасує ${i?.unleased ?? 0} незарезервованих екземплярів; ${i?.leased ?? 0} активних lease збережуться.`
    if (p.payload.is_active === false) return `Пауза скасує ${i?.unstarted ?? 0} незарезервованих автоматичних запусків і ${i?.queued_retries ?? 0} очікуваних автоматичних retries.`
    if (['schedule_kind', 'interval_minutes', 'interval_anchor_at', 'daily_time_local', 'timezone_name', 'one_shot_at'].some(key => key in p.payload)) return `Перебудує до ${i?.unstarted ?? 0} автоматичних запусків без спроб; активні lease збережуться.`
    return `Оновить до ${i?.unstarted ?? 0} автоматичних запусків без спроб; ${i?.queued_retries ?? 0} очікуваних retries збережуть старі параметри.`
  }
  const card = (proposal: Proposal) => <Card key={proposal.id} sx={{ mb: 2 }}><CardContent><Stack direction="row" justifyContent="space-between" gap={2}><Box><Typography fontWeight={700}>{proposal.operation}</Typography><Typography variant="body2" color="text.secondary">{dateTime(proposal.created_at)} · {proposal.target_id || 'Нове правило'} · {proposal.status}</Typography></Box>{proposal.status === 'pending' && <Stack direction="row" gap={1}><Button variant="contained" disabled={decision.isPending} onClick={() => decision.mutate({ id: proposal.id, approve: true })}>Approve</Button><Button variant="outlined" disabled={decision.isPending} onClick={() => decision.mutate({ id: proposal.id, approve: false })}>Reject</Button></Stack>}</Stack><Typography variant="caption" color="text.secondary">Версія правила: {proposal.expected_version ?? '—'}</Typography>{proposal.status === 'pending' && <Typography variant="body2" sx={{ mt: 1 }}>{impactText(proposal)}</Typography>}<Box component="pre" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', bgcolor: '#f5f7fb', p: 2, borderRadius: 1, fontSize: 13 }}>{JSON.stringify(proposal.payload, null, 2)}</Box>{proposal.result && <Typography variant="body2">Результат: {JSON.stringify(proposal.result)}</Typography>}{proposal.reason && <Alert severity="warning">{proposal.reason}</Alert>}</CardContent></Card>
  return <><PageTitle title="Пропозиції агента" description="Перегляньте запропоновані зміни перед застосуванням." />{error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}<Card sx={{ mb: 3 }}><CardContent><Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems="center" gap={2}><Box><Typography fontWeight={700}>Автоматичне затвердження</Typography><Typography variant="body2" color="text.secondary">{auto.data?.enabled ? `Увімкнено до ${dateTime(auto.data.until)}` : 'Вимкнено. Нові MCP-пропозиції очікують рішення.'}</Typography></Box><Button variant={auto.data?.enabled ? 'outlined' : 'contained'} color={auto.data?.enabled ? 'error' : 'primary'} disabled={toggleAuto.isPending || !auto.data} onClick={() => toggleAuto.mutate(!auto.data!.enabled)}>{auto.data?.enabled ? 'Вимкнути' : 'Увімкнути на годину'}</Button></Stack></CardContent></Card><Typography variant="h6" sx={{ mb: 2 }}>Очікують рішення</Typography>{pending.isLoading ? <Loading /> : pending.error ? <ErrorBox error={pending.error} /> : pending.data?.proposals.length ? pending.data.proposals.map(card) : <Empty text="Пропозицій немає." />}<Typography variant="h6" sx={{ mt: 4, mb: 2 }}>Останні рішення</Typography>{recent.data?.proposals.filter(p => p.status !== 'pending').slice(0, 20).map(card)}</>
}

function AuthGate() {
  const client = useQueryClient()
  const session = useQuery({ queryKey: ['session', legacyQueue ? 'legacy' : 'admin'], queryFn: legacyQueue ? api.session : adminApi.session, refetchInterval: 30_000 })
  const [pin, setPin] = useState('')
  const login = useMutation({ mutationFn: () => legacyQueue ? api.login(pin) : adminApi.login(pin), onSuccess: () => { clearCsrf(); clearAdminCsrf(); setPin(''); client.invalidateQueries() } })
  if (session.isLoading) return <Loading />
  if (session.error) return <ErrorBox error={session.error} />
  if (session.data?.authenticated) return legacyQueue ? <Shell /> : <InfrastructureShell modules={(session.data as AdminSession).modules} />
  return <Container maxWidth="xs" sx={{ pt: 12 }}><Card><CardContent sx={{ p: 4 }}><Typography variant="h5" fontWeight={700} gutterBottom>{legacyQueue ? 'Вхід до черги задач' : 'Infrastructure Admin'}</Typography><Typography color="text.secondary" sx={{ mb: 3 }}>Уведіть шість цифр PIN.</Typography><Box component="form" onSubmit={e => { e.preventDefault(); login.mutate() }}><TextField label="PIN" type="password" value={pin} onChange={e => setPin(e.target.value)} inputProps={{ maxLength: 6, inputMode: 'numeric', pattern: '[0-9]{6}' }} fullWidth required autoFocus /><Button type="submit" variant="contained" fullWidth sx={{ mt: 2 }} disabled={login.isPending || !/^[0-9]{6}$/.test(pin)}>Увійти</Button></Box>{login.error && <Alert severity="error" sx={{ mt: 2 }}>{(login.error as Error).message}</Alert>}</CardContent></Card></Container>
}

function InfrastructureShell({ modules }: { modules: AdminSession['modules'] }) {
  const location = useLocation()
  const client = useQueryClient()
  const queueSection = ['/queue', '/rules', '/tasks', '/proposals'].some(path => location.pathname === path || location.pathname.startsWith(path + '/'))
  const tab = queueSection ? '/queue' : location.pathname.startsWith('/telegram') ? '/telegram' : location.pathname.startsWith('/security') ? '/security' : '/gateway'
  const logout = async () => {
    await adminApi.logout(); clearAdminCsrf(); clearCsrf(); client.clear(); window.location.assign('/admin/')
  }
  return <Box sx={{ minHeight: '100vh' }}>
    <AppBar position="sticky" color="inherit" elevation={0} sx={{ borderBottom: 1, borderColor: 'divider' }}>
      <Toolbar sx={{ gap: 2 }}><Typography variant="h6" fontWeight={750} sx={{ flexGrow: 1 }}>Infrastructure Admin</Typography><Button onClick={logout}>Вийти</Button></Toolbar>
      <Tabs value={tab} variant="scrollable" scrollButtons="auto" sx={{ px: { xs: 1, md: 3 } }}>
        <Tab label="Безпека" value="/security" component={RouterLink} to="/security" />
        <Tab label="Gateway" value="/gateway" component={RouterLink} to="/gateway" />
        {modules.queue && <Tab label="Черга" value="/queue" component={RouterLink} to="/queue" />}
        {modules.telegram && <Tab label="Telegram" value="/telegram" component={RouterLink} to="/telegram" />}
      </Tabs>
    </AppBar>
    <Container maxWidth="xl" sx={{ py: 4 }}>
      {modules.queue && queueSection && <Tabs value={location.pathname.startsWith('/rules') ? '/rules' : location.pathname.startsWith('/proposals') ? '/proposals' : '/queue'} variant="scrollable" scrollButtons="auto" sx={{ mb: 3, borderBottom: 1, borderColor: 'divider' }}><Tab label="Огляд" value="/queue" component={RouterLink} to="/queue" /><Tab label="Правила" value="/rules" component={RouterLink} to="/rules" /><Tab label="Пропозиції" value="/proposals" component={RouterLink} to="/proposals" /></Tabs>}
      <Routes>
        <Route path="/" element={<Navigate to="/gateway" replace />} />
        <Route path="/security" element={<SecurityPage />} />
        <Route path="/gateway" element={<GatewayPage />} />
        {modules.queue && <>
          <Route path="/queue" element={<><AutoApprovalBanner /><DashboardPage /></>} />
          <Route path="/tasks/:id" element={<><AutoApprovalBanner /><TaskPage /></>} />
          <Route path="/rules" element={<><AutoApprovalBanner /><RulesPage /></>} />
          <Route path="/rules/new" element={<><AutoApprovalBanner /><RuleFormPage /></>} />
          <Route path="/rules/:id" element={<><AutoApprovalBanner /><RuleFormPage /></>} />
          <Route path="/proposals" element={<><AutoApprovalBanner /><ProposalsPage /></>} />
        </>}
        {modules.telegram && <Route path="/telegram" element={<TelegramPage />} />}
        <Route path="*" element={<Empty text="Сторінку не знайдено." />} />
      </Routes>
    </Container>
  </Box>
}

export default function App() { return <AuthGate /> }
