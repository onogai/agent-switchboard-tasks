import { Fragment, useRef, useState } from 'react'
import {
  Alert, Box, Button, Checkbox, Chip, CircularProgress, Dialog, DialogActions,
  DialogContent, DialogTitle, FormControlLabel, IconButton, MenuItem,
  Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  TextField, Tooltip, Typography,
} from '@mui/material'
import { KeyboardArrowDownRounded, KeyboardArrowRightRounded } from '@mui/icons-material'
import { adminApi, type BulkOperation, type BulkPreview, type BulkRequest, type GatewaySource, type GatewayTool } from './adminApi'
import { createBulkPreviewGuard, groupGatewayTools, MATRIX_PROFILES, type MatrixAccess, type MatrixFilters } from './gatewayMatrixModel'

type Props = {
  tools: GatewayTool[]
  sources: GatewaySource[]
  savingToolId: string | null
  onChangeGrant: (tool: GatewayTool, profile: string, enabled: boolean) => Promise<void>
  onEdit: (tool: GatewayTool) => void
  onBulkApplied: () => void
}

const emptyFilters: MatrixFilters = { query: '', sourceId: 'all', profile: 'all', access: 'all' }

export function GatewayToolMatrix({ tools, sources, savingToolId, onChangeGrant, onEdit, onBulkApplied }: Props) {
  const [filters, setFilters] = useState<MatrixFilters>(emptyFilters)
  const [collapsed, setCollapsed] = useState<string[]>([])
  const [saveError, setSaveError] = useState('')
  const [bulkOperation, setBulkOperation] = useState<BulkOperation>('approve_assign')
  const [bulkProfiles, setBulkProfiles] = useState<string[]>(['interactive'])
  const [adoptObserved, setAdoptObserved] = useState(false)
  const [bulkBusy, setBulkBusy] = useState(false)
  const [bulkPreview, setBulkPreview] = useState<BulkPreview | null>(null)
  const [bulkRequest, setBulkRequest] = useState<BulkRequest | null>(null)
  const [bulkNotice, setBulkNotice] = useState('')
  const previewGuard = useRef(createBulkPreviewGuard())
  const groups = groupGatewayTools(tools, sources, filters)
  const visibleCount = groups.reduce((sum, group) => sum + group.tools.length, 0)
  const sourceIds = [...new Set([...sources.map(item => item.id), ...tools.map(item => item.source_id)])].sort()
  const invalidateBulkPreview = () => {
    previewGuard.current.invalidate()
    setBulkPreview(null)
    setBulkRequest(null)
  }
  const setFilter = <K extends keyof MatrixFilters,>(key: K, value: MatrixFilters[K]) => {
    invalidateBulkPreview()
    setFilters(current => ({ ...current, [key]: value }))
  }
  const toggleGroup = (id: string) => setCollapsed(current =>
    current.includes(id) ? current.filter(value => value !== id) : [...current, id])
  const bulkNeedsProfiles = bulkOperation !== 'approve'
  const toggleBulkProfile = (profile: string, enabled: boolean) =>
    setBulkProfiles(current => enabled
      ? [...new Set([...current, profile])]
      : current.filter(value => value !== profile))
  const previewBulk = async () => {
    const ids = groups.flatMap(group => group.tools.map(tool => tool.id))
    if (!ids.length || bulkBusy || (bulkNeedsProfiles && !bulkProfiles.length)) return
    const value: BulkRequest = {
      ids, operation: bulkOperation,
      profiles: bulkNeedsProfiles ? bulkProfiles : [],
      adopt_observed: bulkOperation === 'approve' || bulkOperation === 'approve_assign' ? adoptObserved : false,
    }
    setSaveError('')
    setBulkNotice('')
    const issued = previewGuard.current.begin()
    setBulkBusy(true)
    try {
      const preview = await adminApi.bulkPreview(value)
      if (!previewGuard.current.accepts(issued)) return
      setBulkRequest(value)
      setBulkPreview(preview)
    } catch (error) {
      if (previewGuard.current.accepts(issued)) {
        setSaveError(`Bulk preview не вдалося: ${error instanceof Error ? error.message : String(error)}`)
      }
    } finally {
      setBulkBusy(false)
    }
  }
  const applyBulk = async () => {
    if (!bulkRequest || !bulkPreview || bulkPreview.counts.blocked || bulkBusy) return
    setBulkBusy(true)
    setSaveError('')
    try {
      const result = await adminApi.bulkApply({ ...bulkRequest, snapshot: bulkPreview.snapshot, confirm: true })
      setBulkNotice(`Bulk operation застосовано: ${result.counts.will_change} змінено, ${result.counts.unchanged} без змін.`)
      setBulkPreview(null)
      setBulkRequest(null)
      onBulkApplied()
    } catch (error) {
      setSaveError(`Bulk operation не виконано: ${error instanceof Error ? error.message : String(error)}. Оновіть preview.`)
      setBulkPreview(null)
      setBulkRequest(null)
      onBulkApplied()
    } finally {
      setBulkBusy(false)
    }
  }
  const changeGrant = async (tool: GatewayTool, profile: string, enabled: boolean) => {
    setSaveError('')
    try {
      await onChangeGrant(tool, profile, enabled)
    } catch (error) {
      setSaveError(`Не вдалося змінити доступ ${tool.public_name}: ${error instanceof Error ? error.message : String(error)}`)
    }
  }

  return <Box>
    <Stack direction={{ xs: 'column', md: 'row' }} alignItems={{ md: 'center' }} justifyContent="space-between" gap={2} sx={{ mb: 2 }}>
      <Box>
        <Typography variant="h6" fontWeight={700}>Tools × Profiles</Typography>
        <Typography variant="body2" color="text.secondary">
          Один інструмент — один рядок. Права зберігаються одразу; контракт змінюється тільки через «Деталі».
        </Typography>
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
        Показано {visibleCount} із {tools.length}
      </Typography>
    </Stack>
    <Stack direction={{ xs: 'column', sm: 'row' }} gap={1.5} flexWrap="wrap" sx={{ mb: 2 }}>
      <TextField label="Пошук інструмента" size="small" value={filters.query}
        onChange={event => setFilter('query', event.target.value)} sx={{ flex: '2 1 220px' }}/>
      <TextField select label="Upstream" size="small" value={filters.sourceId}
        onChange={event => setFilter('sourceId', event.target.value)} sx={{ flex: '1 1 150px' }}>
        <MenuItem value="all">Усі upstream</MenuItem>
        {sourceIds.map(id => <MenuItem key={id} value={id}>{id}</MenuItem>)}
      </TextField>
      <TextField select label="Профіль" size="small" value={filters.profile}
        onChange={event => setFilter('profile', event.target.value)} sx={{ flex: '1 1 150px' }}>
        <MenuItem value="all">Усі профілі</MenuItem>
        {MATRIX_PROFILES.map(profile => <MenuItem key={profile.id} value={profile.id}>{profile.label}</MenuItem>)}
      </TextField>
      <TextField select label="Швидкий фільтр" size="small" value={filters.access}
        onChange={event => setFilter('access', event.target.value as MatrixAccess)} sx={{ flex: '1 1 150px' }}>
        <MenuItem value="all">Усі інструменти</MenuItem>
        <MenuItem value="granted">З призначеннями</MenuItem>
        <MenuItem value="ungranted">Без призначень</MenuItem>
        <MenuItem value="review">Потребують перевірки</MenuItem>
      </TextField>
      <Button size="small" onClick={() => { invalidateBulkPreview(); setFilters(emptyFilters) }}
        disabled={Object.keys(emptyFilters).every(key => filters[key as keyof MatrixFilters] === emptyFilters[key as keyof MatrixFilters])}>
        Скинути
      </Button>
    </Stack>
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Stack gap={1.5}>
        <Stack direction={{ xs: 'column', md: 'row' }} alignItems={{ md: 'center' }} gap={1.5}>
          <Box sx={{ flex: 1 }}>
            <Typography variant="subtitle2" fontWeight={700}>Bulk actions · {visibleCount} tools</Typography>
            <Typography variant="caption" color="text.secondary">
              Усі результати активних фільтрів, включно зі згорнутими групами. Одна атомарна операція.
            </Typography>
          </Box>
          <TextField select size="small" label="Дія" value={bulkOperation} sx={{ minWidth: 215 }}
            disabled={bulkBusy || Boolean(bulkPreview)}
            onChange={event => setBulkOperation(event.target.value as BulkOperation)}>
            <MenuItem value="approve_assign">Approve & assign</MenuItem>
            <MenuItem value="approve">Approve contracts</MenuItem>
            <MenuItem value="assign">Assign profiles</MenuItem>
            <MenuItem value="revoke">Revoke profiles</MenuItem>
          </TextField>
          <Button variant="contained" disabled={bulkBusy || savingToolId !== null ||
            visibleCount === 0 || visibleCount > 2000 || (bulkNeedsProfiles && !bulkProfiles.length)}
            onClick={() => { void previewBulk() }}>
            {bulkBusy ? 'Обробка…' : `Preview · ${visibleCount}`}
          </Button>
        </Stack>
        {(bulkOperation === 'approve' || bulkOperation === 'approve_assign') &&
          <FormControlLabel
            label="Прийняти поточні схеми upstream (замінити публічний контракт)"
            control={<Checkbox checked={adoptObserved} disabled={bulkBusy || Boolean(bulkPreview)}
              onChange={event => setAdoptObserved(event.target.checked)} />} />}
        {bulkNeedsProfiles && <Stack direction="row" gap={1.5} flexWrap="wrap">
          {MATRIX_PROFILES.map(profile =>
            <FormControlLabel key={profile.id} label={profile.label}
              control={<Checkbox size="small" disabled={bulkBusy || Boolean(bulkPreview)}
                checked={bulkProfiles.includes(profile.id)}
                onChange={event => toggleBulkProfile(profile.id, event.target.checked)} />}/>)}
        </Stack>}
      </Stack>
    </Paper>
    {bulkNotice && <Alert severity="success" onClose={() => setBulkNotice('')} sx={{ mb: 2 }}>{bulkNotice}</Alert>}
    {saveError && <Alert severity="error" onClose={() => setSaveError('')} sx={{ mb: 2 }}>{saveError}</Alert>}
    <Dialog open={bulkPreview !== null} onClose={() => { if (!bulkBusy) { setBulkPreview(null); setBulkRequest(null) } }}
      fullWidth maxWidth="sm">
      <DialogTitle>Підтвердити bulk operation</DialogTitle>
      <DialogContent>
        {bulkPreview && <Stack gap={1.5} sx={{ pt: 1 }}>
          <Typography><strong>Дія:</strong> {bulkPreview.operation}</Typography>
          <Typography><strong>Профілі:</strong> {bulkPreview.profiles.join(', ') || 'Не змінюються'}</Typography>
          {bulkPreview.adopt_observed && <Alert severity="warning">
            Прийняти поточні схеми upstream: для інструментів у review замінити inputSchema, outputSchema та annotations.
            Локальні назви, описи, aliases, effects, meta та grants зберігаються.
            Зміни контрактів перевірте нижче перед підтвердженням.
          </Alert>}
          <Typography><strong>Вибрано:</strong> {bulkPreview.counts.requested} tools за активними фільтрами</Typography>
          <Typography><strong>Буде змінено:</strong> {bulkPreview.counts.will_change} tools</Typography>
          <Typography variant="body2">Контрактів до погодження: {bulkPreview.counts.will_approve}.
            Контрактів до синхронізації: {bulkPreview.counts.will_adopt}.
            Нових grants: {bulkPreview.counts.will_assign}. Видалених grants: {bulkPreview.counts.will_revoke}.
            Без змін: {bulkPreview.counts.unchanged}.</Typography>
          {bulkPreview.blocked.length > 0 &&
            <Alert severity="error">
              Заблоковано {bulkPreview.blocked.length} tools. Операція не виконується частково.
              <Box component="ul" sx={{ pl: 2, mb: 0, maxHeight: 160, overflowY: 'auto' }}>
                {bulkPreview.blocked.map(item => <li key={item.id}>{item.id}: {item.reason}</li>)}
              </Box>
            </Alert>}
          <Typography variant="caption" color="text.secondary">
            Перевірте обсяг операції та право доступу. Якщо дані змінилися з моменту preview,
            сервер відхилить підтвердження без часткових змін.
          </Typography>
          <Box component="details">
            <Box component="summary" sx={{ cursor: 'pointer' }}>Переглянути {bulkPreview.changes.length} змін</Box>
            <Box sx={{ maxHeight: 210, overflowY: 'auto', mt: 1 }}>
              {bulkPreview.changes.map(change =>
                <Typography key={change.id} variant="caption" sx={{ display: 'block', overflowWrap: 'anywhere' }}>
                  {change.id}: {change.before.status} → {change.after.status};
                  [{change.before.grants.join(', ')}] → [{change.after.grants.join(', ')}]
                  {change.contract_fields?.length ? ` · upstream replaces: ${change.contract_fields.join(', ')}` : ''}
                </Typography>)}
            </Box>
          </Box>
        </Stack>}
      </DialogContent>
      <DialogActions>
        <Button disabled={bulkBusy} onClick={() => { setBulkPreview(null); setBulkRequest(null) }}>Скасувати</Button>
        <Button variant="contained" color={bulkOperation === 'revoke' ? 'error' : 'primary'}
          disabled={bulkBusy || !bulkPreview || bulkPreview.counts.blocked > 0 || bulkPreview.counts.will_change === 0}
          onClick={() => { void applyBulk() }}>
          {bulkBusy ? 'Застосування…' : 'Підтвердити й застосувати'}
        </Button>
      </DialogActions>
    </Dialog>
    <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 680 }}>
      <Table size="small" stickyHeader aria-label="Матриця доступу інструментів до профілів" sx={{ minWidth: 810 }}>
        <TableHead>
          <TableRow>
            <TableCell sx={{ minWidth: 280 }}>Інструмент</TableCell>
            <TableCell sx={{ minWidth: 110 }}>Стан</TableCell>
            {MATRIX_PROFILES.map(profile =>
              <TableCell key={profile.id} align="center" sx={{ minWidth: 122 }}>{profile.label}</TableCell>)}
            <TableCell align="right">Контракт</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {groups.map(group => {
            const isCollapsed = collapsed.includes(group.id)
            const granted = group.tools.filter(tool => tool.grants.length).length
            return <Fragment key={group.id}>
              <TableRow sx={{ bgcolor: 'action.hover' }}>
                <TableCell colSpan={6} sx={{ py: 0.7, borderBottom: 1, borderColor: 'divider' }}>
                  <Stack direction="row" alignItems="center" gap={1} flexWrap="wrap">
                    <IconButton size="small" aria-label={`${isCollapsed ? 'Розгорнути' : 'Згорнути'} ${group.id}`}
                      onClick={() => toggleGroup(group.id)}>
                      {isCollapsed ? <KeyboardArrowRightRounded fontSize="small"/> : <KeyboardArrowDownRounded fontSize="small"/>}
                    </IconButton>
                    <Typography fontWeight={700} variant="body2">{group.id}</Typography>
                    <Chip size="small" label={group.enabled ? group.status : 'disabled'}
                      color={!group.enabled || group.status === 'offline' ? 'error' : group.status === 'online' ? 'success' : 'default'}
                      variant="outlined"/>
                    <Typography variant="caption" color="text.secondary">
                      {group.tools.length} інструментів · {granted} з призначеннями
                    </Typography>
                  </Stack>
                </TableCell>
              </TableRow>
              {!isCollapsed && group.tools.map(tool => {
                const pending = savingToolId === tool.id
                const inactive = tool.status !== 'active' || !tool.source_enabled || tool.source_status === 'offline'
                return <TableRow key={tool.id} hover>
                  <TableCell>
                    <Stack direction="row" alignItems="center" gap={1}>
                      <Box sx={{ minWidth: 0 }}>
                        <Typography variant="body2" fontWeight={600} sx={{ overflowWrap: 'anywhere' }}>{tool.public_name}</Typography>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', overflowWrap: 'anywhere' }}>
                          {tool.parent_id ? 'Variant · ' : ''}{tool.description.slice(0, 110)}
                        </Typography>
                      </Box>
                      {pending && <CircularProgress size={16} aria-label="Збереження доступів"/>}
                    </Stack>
                  </TableCell>
                  <TableCell>
                    <Chip size="small" label={inactive && tool.status === 'active' ? 'unavailable' : tool.status}
                      color={tool.status === 'review' ? 'warning' : tool.status === 'missing' || inactive ? 'error' : 'success'}
                      variant="outlined"/>
                  </TableCell>
                  {MATRIX_PROFILES.map(profile => {
                    const checked = tool.grants.includes(profile.id)
                    return <TableCell key={profile.id} align="center" sx={{ p: 0.5 }}>
                      <Tooltip title={inactive ? 'Grant можна зберегти, але інструмент не працюватиме до активації / review upstream.' : checked ? 'Забрати доступ' : 'Надати доступ'}>
                        <span>
                          <Checkbox size="small" checked={checked} disabled={savingToolId !== null}
                            onChange={event => { void changeGrant(tool, profile.id, event.target.checked) }}
                            inputProps={{ 'aria-label': `${tool.public_name}: ${profile.label}` }}/>
                        </span>
                      </Tooltip>
                    </TableCell>
                  })}
                  <TableCell align="right"><Button size="small" onClick={() => onEdit(tool)}>Деталі</Button></TableCell>
                </TableRow>
              })}
            </Fragment>
          })}
          {groups.length === 0 && <TableRow><TableCell colSpan={6}>
            <Typography variant="body2" color="text.secondary" sx={{ py: 3, textAlign: 'center' }}>
              {tools.length ? 'За цими фільтрами інструментів немає.' : 'Інструменти ще не виявлені.'}
            </Typography>
          </TableCell></TableRow>}
        </TableBody>
      </Table>
    </TableContainer>
    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
      Позначка означає збережений grant, а не гарантію доступності: стан review, missing, disabled або offline блокує виконання.
    </Typography>
  </Box>
}
