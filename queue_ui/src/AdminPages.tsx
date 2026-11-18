import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Box, Button, Card, CardContent, Checkbox, Chip, CircularProgress,
  Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Paper,
  Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  TextField, Typography,
} from '@mui/material'
import { adminApi, clearAdminCsrf, type AuditEvent, type BulkPreview, type GatewaySource, type GatewayTool } from './adminApi'
import { GatewayToolMatrix } from './GatewayToolMatrix'
import { updatedGrants } from './gatewayMatrixModel'
import { TelegramDeliveryPanel } from './TelegramDeliveryPanel'

function ErrorNotice({ error }: { error: unknown }) {
  return <Alert severity="error" sx={{ my: 2 }}>{error instanceof Error ? error.message : String(error)}</Alert>
}

function Loading() { return <Box sx={{ display: 'flex', justifyContent: 'center', p: 8 }}><CircularProgress /></Box> }

function pretty(value: unknown) { return JSON.stringify(value, null, 2) }

function auditValue(value: string | null) {
  if (!value) return '—'
  try { return pretty(JSON.parse(value)) } catch { return value }
}

export function SecurityPage() {
  const client = useQueryClient()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const change = async (event: React.FormEvent) => {
    event.preventDefault()
    if (next !== repeat) { setError(new Error('Новий PIN і повтор не збігаються.')); return }
    setBusy(true); setError(null)
    try {
      await adminApi.changePin(current, next)
      clearAdminCsrf(); client.clear(); window.location.assign('/admin/')
    } catch (failure) { setError(failure) } finally { setBusy(false) }
  }
  return <Stack spacing={3}>
    <Box><Typography variant="h4" fontWeight={750}>Безпека</Typography><Typography color="text.secondary">Один PIN і одна сесія для всіх модулів Infrastructure Admin.</Typography></Box>
    <Card><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700}>Змінити PIN</Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>Зміна PIN завершить усі активні адмін-сесії.</Typography>
      <Box component="form" onSubmit={change} sx={{ maxWidth: 400 }}>
        <Stack spacing={2}>
          <TextField label="Поточний PIN" type="password" value={current} onChange={e => setCurrent(e.target.value)} inputProps={{ maxLength: 6, inputMode: 'numeric', pattern: '[0-9]{6}' }} required />
          <TextField label="Новий PIN" type="password" value={next} onChange={e => setNext(e.target.value)} inputProps={{ maxLength: 6, inputMode: 'numeric', pattern: '[0-9]{6}' }} required />
          <TextField label="Повторіть новий PIN" type="password" value={repeat} onChange={e => setRepeat(e.target.value)} inputProps={{ maxLength: 6, inputMode: 'numeric', pattern: '[0-9]{6}' }} required />
          <Button type="submit" variant="contained" disabled={busy || current.length !== 6 || next.length !== 6 || repeat.length !== 6}>Змінити PIN</Button>
        </Stack>
      </Box>{error !== null && <ErrorNotice error={error} />}
    </CardContent></Card>
  </Stack>
}

type SourceForm = { id: string; url: string; enabled: boolean; auth_type: 'none' | 'bearer' | 'coches_env'; bearer_token: string }
type ToolForm = {
  public_name: string; title: string; description: string; effects: string; aliases: string
  input_schema: string; output_schema: string; annotations: string; meta: string
  unattended: boolean; interactive: boolean; localInteractive: boolean; review: boolean
}

function toolForm(tool: GatewayTool): ToolForm {
  return {
    public_name: tool.public_name, title: tool.title || '', description: tool.description,
    effects: tool.effects, aliases: tool.aliases.join(', '),
    input_schema: pretty(tool.input_schema), output_schema: pretty(tool.output_schema),
    annotations: pretty(tool.annotations), meta: pretty(tool.meta),
    unattended: tool.grants.includes('unattended'),
    interactive: tool.grants.includes('interactive'),
    localInteractive: tool.grants.includes('local-interactive'), review: false,
  }
}

export function GatewayPage() {
  const client = useQueryClient()
  const sources = useQuery({ queryKey: ['gateway-sources'], queryFn: adminApi.sources })
  const tools = useQuery({ queryKey: ['gateway-tools'], queryFn: adminApi.tools })
  const audit = useQuery({ queryKey: ['gateway-audit'], queryFn: adminApi.audit })
  const [source, setSource] = useState<GatewaySource | 'new' | null>(null)
  const [sourceForm, setSourceForm] = useState<SourceForm>({ id: '', url: '', enabled: true, auth_type: 'none', bearer_token: '' })
  const [tool, setTool] = useState<GatewayTool | null>(null)
  const [form, setForm] = useState<ToolForm | null>(null)
  const [variant, setVariant] = useState<GatewayTool | null>(null)
  const [variantName, setVariantName] = useState('')
  const [variantDescription, setVariantDescription] = useState('')
  const [variantSchema, setVariantSchema] = useState('{}')
  const [variantArgs, setVariantArgs] = useState('{}')
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [savingGrantId, setSavingGrantId] = useState<string | null>(null)
  const [manualAdoptPreview, setManualAdoptPreview] = useState<BulkPreview | null>(null)
  const refreshData = () => {
    client.invalidateQueries({ queryKey: ['gateway-sources'] })
    client.invalidateQueries({ queryKey: ['gateway-tools'] })
    client.invalidateQueries({ queryKey: ['gateway-audit'] })
  }
  const openSource = (value: GatewaySource | 'new') => {
    setSource(value); setSourceForm(value === 'new'
      ? { id: '', url: '', enabled: true, auth_type: 'none', bearer_token: '' }
      : { id: value.id, url: '', enabled: value.enabled, auth_type: value.auth_type, bearer_token: '' }); setError(null)
  }
  const closeSource = () => {
    setSource(null)
    setSourceForm(current => ({ ...current, bearer_token: '' }))
  }
  const saveSource = async () => {
    setBusy(true); setError(null)
    try {
      await adminApi.setSource(sourceForm.id, {
        enabled: sourceForm.enabled, auth_type: sourceForm.auth_type,
        ...(sourceForm.url.trim() ? { url: sourceForm.url.trim() } : {}),
        ...(sourceForm.auth_type === 'bearer' && sourceForm.bearer_token ? { bearer_token: sourceForm.bearer_token } : {}),
      })
      closeSource(); setNotice('Upstream збережено. Discovery запущено.'); refreshData()
    } catch (failure) { setError(failure) } finally { setBusy(false) }
  }
  const openTool = (value: GatewayTool) => {
    setManualAdoptPreview(null); setTool(value); setForm(toolForm(value)); setError(null)
  }
  const previewManualAdopt = async () => {
    if (!tool || tool.parent_id || tool.status !== 'review') return
    setBusy(true); setError(null)
    try {
      const preview = await adminApi.bulkPreview({
        ids: [tool.id], operation: 'approve', profiles: [], adopt_observed: true,
      })
      setManualAdoptPreview(preview)
    } catch (failure) { setError(failure) } finally { setBusy(false) }
  }
  const applyManualAdopt = async () => {
    if (!tool || !manualAdoptPreview || manualAdoptPreview.counts.blocked) return
    setBusy(true); setError(null)
    try {
      await adminApi.bulkApply({
        ids: [tool.id], operation: 'approve', profiles: [], adopt_observed: true,
        snapshot: manualAdoptPreview.snapshot, confirm: true,
      })
      setManualAdoptPreview(null); setTool(null)
      setNotice('Контракт upstream прийнято й погоджено.'); refreshData()
    } catch (failure) {
      setManualAdoptPreview(null); setError(failure); refreshData()
    } finally { setBusy(false) }
  }
  const saveTool = async () => {
    if (!tool || !form) return
    setBusy(true); setError(null)
    try {
      await adminApi.setTool(tool.id, {
        public_name: form.public_name.trim(), title: form.title.trim() || null,
        description: form.description, effects: form.effects,
        aliases: form.aliases.split(',').map(x => x.trim()).filter(Boolean),
        input_schema: JSON.parse(form.input_schema), output_schema: JSON.parse(form.output_schema),
        annotations: JSON.parse(form.annotations), meta: JSON.parse(form.meta),
        grants: ['unattended', 'interactive', 'local-interactive'].filter(profile =>
          profile === 'unattended' ? form.unattended :
          profile === 'interactive' ? form.interactive : form.localInteractive),
        review: form.review,
      })
      setTool(null); setNotice('Контракт і grants збережено.'); refreshData()
    } catch (failure) { setError(failure) } finally { setBusy(false) }
  }
  const saveGrant = async (value: GatewayTool, profile: string, enabled: boolean): Promise<void> => {
    setSavingGrantId(value.id)
    try {
      // A grants-only request must never resubmit or implicitly approve the public contract.
      const updated = await adminApi.setTool(value.id, {
        grants: updatedGrants(value.grants, profile, enabled),
      })
      client.setQueryData<{ tools: GatewayTool[] }>(['gateway-tools'], current =>
        current ? { ...current, tools: current.tools.map(item => item.id === updated.id ? updated : item) } : current)
      await client.invalidateQueries({ queryKey: ['gateway-tools'] })
      void client.invalidateQueries({ queryKey: ['gateway-audit'] })
    } finally {
      setSavingGrantId(null)
    }
  }
  const openVariant = (value: GatewayTool) => {
    setVariant(value); setVariantName(''); setVariantDescription('');
    setVariantSchema(pretty(value.input_schema)); setVariantArgs('{}'); setError(null)
  }
  const saveVariant = async () => {
    if (!variant) return
    setBusy(true); setError(null)
    try {
      await adminApi.createVariant(variant.id, {
        public_name: variantName.trim(), description: variantDescription,
        input_schema: JSON.parse(variantSchema), fixed_args: JSON.parse(variantArgs),
      })
      setVariant(null); setNotice('Варіант створено без grants. Призначте профіль після перевірки.'); refreshData()
    } catch (failure) { setError(failure) } finally { setBusy(false) }
  }
  const requestRefresh = async () => {
    setError(null)
    try { await adminApi.refresh(); setNotice('Discovery запитано. Оновіть список за кілька секунд.') }
    catch (failure) { setError(failure) }
  }
  return <Stack spacing={3}>
    <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'start', sm: 'center' }} gap={2}>
      <Box><Typography variant="h4" fontWeight={750}>Gateway</Typography><Typography color="text.secondary">Публічні контракти, upstream та профілі доступу агентів.</Typography></Box>
      <Button variant="outlined" onClick={requestRefresh}>Оновити discovery</Button>
    </Stack>
    {notice && <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
    {error !== null && !source && !tool && !variant && <ErrorNotice error={error} />}
    <Card><CardContent sx={{ p: 3 }}><Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}><Typography variant="h6" fontWeight={700}>Upstream MCP</Typography><Button onClick={() => openSource('new')}>Додати upstream</Button></Stack>
      {sources.isLoading ? <Loading /> : sources.error ? <ErrorNotice error={sources.error} /> :
        <TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow><TableCell>ID</TableCell><TableCell>Endpoint</TableCell><TableCell>Auth</TableCell><TableCell>Стан</TableCell><TableCell>Доступ</TableCell><TableCell /></TableRow></TableHead><TableBody>
          {sources.data?.sources.map(item => <TableRow key={item.id}><TableCell><code>{item.id}</code></TableCell><TableCell sx={{ overflowWrap: 'anywhere' }}>{item.url || 'Локальний'}</TableCell><TableCell>{item.auth_type === 'coches_env' ? 'Env (legacy)' : item.auth_type === 'bearer' ? (item.auth_configured ? 'Bearer ✓' : 'Bearer —') : 'None'}</TableCell><TableCell><Chip size="small" label={item.status} color={item.status === 'offline' ? 'error' : item.status === 'pending' ? 'warning' : 'default'} /> {item.error}</TableCell><TableCell>{item.enabled ? 'Увімкнено' : 'Вимкнено'}</TableCell><TableCell><Button size="small" onClick={() => openSource(item)}>Налаштувати</Button></TableCell></TableRow>)}
        </TableBody></Table></TableContainer>}
    </CardContent></Card>
    <Card><CardContent sx={{ p: 3 }}>
      {tools.isLoading || sources.isLoading ? <Loading /> : tools.error || sources.error ?
        <ErrorNotice error={tools.error || sources.error} /> :
        <GatewayToolMatrix tools={tools.data?.tools || []} sources={sources.data?.sources || []}
          savingToolId={savingGrantId} onChangeGrant={saveGrant} onEdit={openTool}
          onBulkApplied={refreshData}/>}
    </CardContent></Card>
    <Card><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700} sx={{ mb: 2 }}>Історія змін</Typography>
      {audit.isLoading ? <Loading /> : audit.error ? <ErrorNotice error={audit.error} /> :
        <TableContainer component={Paper} variant="outlined"><Table size="small"><TableHead><TableRow><TableCell>Час</TableCell><TableCell>Дія</TableCell><TableCell>Ціль</TableCell><TableCell>Сесія</TableCell><TableCell>Зміна</TableCell></TableRow></TableHead><TableBody>
          {audit.data?.events.map((event: AuditEvent) => <TableRow key={event.id}><TableCell>{event.at}</TableCell><TableCell>{event.action}</TableCell><TableCell><code>{event.target}</code></TableCell><TableCell>{event.actor}</TableCell><TableCell><details><summary>Деталі</summary><Box component="pre" sx={{ maxWidth: 480, overflow: 'auto', fontSize: 12 }}>{auditValue(event.before_json)}{'\n→\n'}{auditValue(event.after_json)}</Box></details></TableCell></TableRow>)}
        </TableBody></Table></TableContainer>}
    </CardContent></Card>
    <Dialog open={Boolean(source)} onClose={closeSource} fullWidth maxWidth="sm">
      <DialogTitle>{source === 'new' ? 'Додати upstream' : `Upstream ${sourceForm.id}`}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="ID" value={sourceForm.id} disabled={source !== 'new'}
            onChange={e => setSourceForm({ ...sourceForm, id: e.target.value })} required />
          <TextField label="Endpoint URL" value={sourceForm.url}
            onChange={e => setSourceForm({ ...sourceForm, url: e.target.value })}
            placeholder={source === 'new' ? 'http://moodle/local/mcp/server.php' : 'Залиште порожнім без змін'} />
          <Typography variant="body2" color="text.secondary">
            URL після збереження відображається замаскованим. При зміні хоста або протоколу захищеного upstream введіть новий Bearer-токен.
          </Typography>
          <TextField select label="Authentication" value={sourceForm.auth_type}
            disabled={Boolean(source && source !== 'new' && source.kind !== 'http')}
            onChange={e => setSourceForm({ ...sourceForm, auth_type: e.target.value as SourceForm['auth_type'], bearer_token: '' })}>
            <MenuItem value="none">None</MenuItem>
            <MenuItem value="bearer">Bearer token</MenuItem>
            {source && source !== 'new' && source.id === 'coches' && <MenuItem value="coches_env">Coches env (legacy)</MenuItem>}
          </TextField>
          {sourceForm.auth_type === 'bearer' && (
            <TextField label="Bearer token" type="password" autoComplete="new-password"
              value={sourceForm.bearer_token}
              onChange={e => setSourceForm({ ...sourceForm, bearer_token: e.target.value })}
              placeholder={source && source !== 'new' && source.auth_configured
                ? 'Залиште порожнім, щоб зберегти поточний' : 'Введіть токен'}
              helperText={source && source !== 'new' && source.auth_configured
                ? 'Токен налаштовано. Значення не повертається з API.'
                : 'Токен буде збережено зашифрованим у SQLite.'} />
          )}
          <FormControlLabel control={<Checkbox checked={sourceForm.enabled}
            onChange={e => setSourceForm({ ...sourceForm, enabled: e.target.checked })} />} label="Увімкнено" />
          {error !== null && <ErrorNotice error={error} />}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={closeSource}>Скасувати</Button>
        <Button variant="contained" disabled={busy || !sourceForm.id || (source === 'new' && !sourceForm.url)
          || (sourceForm.auth_type === 'bearer' && !sourceForm.bearer_token
            && !(source && source !== 'new' && source.auth_configured))}
          onClick={saveSource}>Зберегти</Button>
      </DialogActions>
    </Dialog>
    <Dialog open={Boolean(tool)} onClose={() => setTool(null)} fullWidth maxWidth="md"><DialogTitle>{tool?.public_name}</DialogTitle><DialogContent>{tool && form && <Stack spacing={2} sx={{ pt: 1 }}><Typography variant="body2" color="text.secondary">{tool.id} · upstream: {tool.upstream_name} · стан: {tool.status}</Typography><TextField label="Публічна назва" value={form.public_name} onChange={e => setForm({ ...form, public_name: e.target.value })} /><TextField label="Назва для UI" value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /><TextField label="Опис" multiline minRows={2} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /><TextField label="Побічні ефекти" multiline minRows={2} value={form.effects} onChange={e => setForm({ ...form, effects: e.target.value })} /><TextField label="Aliases (через кому)" value={form.aliases} onChange={e => setForm({ ...form, aliases: e.target.value })} /><TextField label="Публічна схема параметрів (JSON)" multiline minRows={4} value={form.input_schema} onChange={e => setForm({ ...form, input_schema: e.target.value })} InputProps={{ sx: { fontFamily: 'monospace' } }} /><TextField label="Публічна схема результату (JSON або null)" multiline minRows={3} value={form.output_schema} onChange={e => setForm({ ...form, output_schema: e.target.value })} InputProps={{ sx: { fontFamily: 'monospace' } }} /><TextField label="Анотації MCP (JSON або null)" multiline minRows={3} value={form.annotations} onChange={e => setForm({ ...form, annotations: e.target.value })} InputProps={{ sx: { fontFamily: 'monospace' } }} /><TextField label="Метадані MCP (JSON або null)" multiline minRows={3} value={form.meta} onChange={e => setForm({ ...form, meta: e.target.value })} InputProps={{ sx: { fontFamily: 'monospace' } }} /><Stack direction="row" gap={2}><FormControlLabel control={<Checkbox checked={form.unattended} onChange={e => setForm({ ...form, unattended: e.target.checked })} />} label="Unattended" /><FormControlLabel control={<Checkbox checked={form.interactive} onChange={e => setForm({ ...form, interactive: e.target.checked })} />} label="Interactive" /><FormControlLabel control={<Checkbox checked={form.localInteractive} onChange={e => setForm({ ...form, localInteractive: e.target.checked })} />} label="Local interactive" /></Stack><FormControlLabel control={<Checkbox checked={form.review} onChange={e => setForm({ ...form, review: e.target.checked })} />} label="Підтвердити поточний контракт і дозволити виконання" /><details><summary>Спостережені дані upstream</summary><Box component="pre" sx={{ overflow: 'auto', fontSize: 12 }}>{pretty({ contract: tool.observed, meta: tool.meta })}</Box></details>{tool.status === 'review' && !tool.parent_id && <Button variant="outlined" disabled={busy} onClick={() => { void previewManualAdopt() }}>Прийняти контракт upstream…</Button>}{!tool.parent_id && <Button variant="outlined" onClick={() => { setTool(null); openVariant(tool) }}>Створити обмежений варіант</Button>}{error !== null && <ErrorNotice error={error} />}</Stack>}</DialogContent><DialogActions><Button onClick={() => setTool(null)}>Скасувати</Button><Button variant="contained" disabled={busy} onClick={saveTool}>Зберегти</Button></DialogActions></Dialog>
    <Dialog open={manualAdoptPreview !== null} onClose={() => { if (!busy) setManualAdoptPreview(null) }} fullWidth maxWidth="sm">
      <DialogTitle>Прийняти контракт upstream?</DialogTitle>
      <DialogContent>
        {manualAdoptPreview && <Stack gap={1.5} sx={{ pt: 1 }}>
          <Alert severity="warning">Буде замінено публічні схеми та анотації поточного інструмента актуальними даними discovery. Профілі, назва, опис та інші локальні налаштування збережуться. Незбережені зміни форми не застосовуються.</Alert>
          <Typography>Інструмент: {tool?.public_name}</Typography>
          <Typography>Контрактних змін: {manualAdoptPreview.counts.will_adopt}</Typography>
          <Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>Поля: {manualAdoptPreview.changes.flatMap(change => change.contract_fields || []).join(', ') || 'Без змін у схемах'}</Typography>
          {manualAdoptPreview.blocked.length > 0 && <Alert severity="error">
            {manualAdoptPreview.blocked.map(item => `${item.id}: ${item.reason}`).join('; ')}
          </Alert>}
        </Stack>}
      </DialogContent>
      <DialogActions>
        <Button disabled={busy} onClick={() => setManualAdoptPreview(null)}>Скасувати</Button>
        <Button variant="contained" disabled={busy || !manualAdoptPreview || manualAdoptPreview.counts.blocked > 0 ||
          manualAdoptPreview.counts.will_change === 0} onClick={() => { void applyManualAdopt() }}>
          Підтвердити й погодити
        </Button>
      </DialogActions>
    </Dialog>
    <Dialog open={Boolean(variant)} onClose={() => setVariant(null)} fullWidth maxWidth="md"><DialogTitle>Обмежений варіант {variant?.public_name}</DialogTitle><DialogContent><Stack spacing={2} sx={{ pt: 1 }}><Typography color="text.secondary">Фіксовані параметри додає Gateway; агент не може змінити їх. Приберіть ці параметри з публічної схеми.</Typography><TextField label="Публічна назва" value={variantName} onChange={e => setVariantName(e.target.value)} /><TextField label="Опис" multiline minRows={2} value={variantDescription} onChange={e => setVariantDescription(e.target.value)} /><TextField label="Публічна схема параметрів (JSON)" multiline minRows={5} value={variantSchema} onChange={e => setVariantSchema(e.target.value)} InputProps={{ sx: { fontFamily: 'monospace' } }} /><TextField label="Фіксовані параметри (JSON)" multiline minRows={3} value={variantArgs} onChange={e => setVariantArgs(e.target.value)} InputProps={{ sx: { fontFamily: 'monospace' } }} />{error !== null && <ErrorNotice error={error} />}</Stack></DialogContent><DialogActions><Button onClick={() => setVariant(null)}>Скасувати</Button><Button variant="contained" disabled={busy || !variantName} onClick={saveVariant}>Створити</Button></DialogActions></Dialog>
  </Stack>
}

export function TelegramPage() {
  // Legacy test sender remains available during migration; the new service uses its own API.
  const status = useQuery({ queryKey: ['telegram-status'], queryFn: adminApi.telegramStatus })
  const [message, setMessage] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [sent, setSent] = useState('')
  const send = async () => {
    setBusy(true); setError(null)
    try {
      const result = await adminApi.telegramTestSend(message)
      setConfirm(false); setMessage(''); setSent(result.message_id)
    } catch (failure) { setError(failure) } finally { setBusy(false) }
  }
  return <Stack spacing={3}>
    <TelegramDeliveryPanel />
    <Box><Typography variant="h4" fontWeight={750}>Legacy Telegram</Typography><Typography color="text.secondary">Стан інтеграції та контрольне повідомлення фіксованому адресату.</Typography></Box>
    {status.isLoading ? <Loading /> : status.error ? <ErrorNotice error={status.error} /> : <Card><CardContent sx={{ p: 3 }}><Stack direction="row" gap={2} alignItems="center"><Chip label={status.data?.configured ? 'Налаштовано' : 'Не налаштовано'} color={status.data?.configured ? 'success' : 'warning'} /><Typography>Адресат: {status.data?.recipient || '—'}</Typography></Stack></CardContent></Card>}
    <Card><CardContent sx={{ p: 3 }}><Typography variant="h6" fontWeight={700}>Надіслати контрольне повідомлення</Typography><Typography color="text.secondary" sx={{ mb: 2 }}>Це реальне повідомлення. Перевірте текст і підтвердьте надсилання.</Typography><TextField label="Текст повідомлення" multiline minRows={3} fullWidth value={message} onChange={e => setMessage(e.target.value)} inputProps={{ maxLength: 4096 }} /><Button variant="contained" sx={{ mt: 2 }} disabled={!status.data?.configured || !message.trim()} onClick={() => setConfirm(true)}>Перевірити й надіслати</Button>{sent && <Alert severity="success" sx={{ mt: 2 }}>Повідомлення надіслано, ID {sent}.</Alert>}</CardContent></Card>
    <Dialog open={confirm} onClose={() => setConfirm(false)} fullWidth maxWidth="sm"><DialogTitle>Підтвердити надсилання</DialogTitle><DialogContent><Typography sx={{ mb: 2 }}>Адресат: {status.data?.recipient || '—'}</Typography><Paper variant="outlined" sx={{ p: 2, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{message}</Paper>{error !== null && <ErrorNotice error={error} />}</DialogContent><DialogActions><Button onClick={() => setConfirm(false)}>Скасувати</Button><Button color="warning" variant="contained" disabled={busy} onClick={send}>Надіслати повідомлення</Button></DialogActions></Dialog>
  </Stack>
}
