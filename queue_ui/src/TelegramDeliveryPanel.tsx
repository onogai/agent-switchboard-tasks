import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress,
  Dialog, DialogActions, DialogContent, DialogTitle, Divider,
  MenuItem, Stack, Tab, Tabs, TextField, Typography,
} from '@mui/material'
import { adminApi, type TelegramDiscoveredChat, type TelegramDestination, type TelegramDestinationImpact } from './adminApi'

function message(error: unknown) { return error instanceof Error ? error.message : String(error) }
function suggestedSlug(title: string) {
  return title.toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64)
}

export function TelegramDeliveryPanel() {
  const client = useQueryClient()
  const [tab, setTab] = useState(0)
  const status = useQuery({ queryKey: ['telegram-delivery', 'status'], queryFn: adminApi.telegramDeliveryStatus, retry: false })
  const bots = useQuery({ queryKey: ['telegram-delivery', 'bots'], queryFn: adminApi.telegramBots, enabled: !!status.data, retry: false })
  const targets = useQuery({ queryKey: ['telegram-delivery', 'destinations'], queryFn: adminApi.telegramDestinations, enabled: !!status.data, retry: false })
  const discovered = useQuery({ queryKey: ['telegram-delivery', 'discovered'], queryFn: adminApi.telegramDiscovered, enabled: !!status.data, retry: false, refetchInterval: tab === 0 ? 15000 : false })
  const history = useQuery({ queryKey: ['telegram-delivery', 'history'], queryFn: adminApi.telegramRecentDeliveries, enabled: !!status.data && tab === 2, retry: false })

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [candidate, setCandidate] = useState<TelegramDiscoveredChat | null>(null)
  const [slug, setSlug] = useState('')
  const [label, setLabel] = useState('')
  const [manual, setManual] = useState(false)
  const [chatId, setChatId] = useState('')
  const [botId, setBotId] = useState('')
  const [botLabel, setBotLabel] = useState('')
  const [botToken, setBotToken] = useState('')
  const [testDestination, setTestDestination] = useState('')
  const [testMessage, setTestMessage] = useState('')
  const [confirmTest, setConfirmTest] = useState(false)
  const [showIgnored, setShowIgnored] = useState(false)
  const [summaryDestination, setSummaryDestination] = useState('')
  const [summaryKey, setSummaryKey] = useState('')
  const [summaryInfo, setSummaryInfo] = useState('')
  const [confirmPin, setConfirmPin] = useState(false)
  const [lifecycle, setLifecycle] = useState<'delete' | 'rebind' | null>(null)
  const [selectedRoute, setSelectedRoute] = useState<TelegramDestination | null>(null)
  const [impact, setImpact] = useState<TelegramDestinationImpact | null>(null)
  const [selectedChat, setSelectedChat] = useState('')
  const [newLabel, setNewLabel] = useState('')

  const refresh = () => client.invalidateQueries({ queryKey: ['telegram-delivery'] })
  const action = async (fn: () => Promise<unknown>, success: string): Promise<boolean> => {
    setBusy(true); setError(''); setNotice('')
    try { await fn(); await refresh(); setNotice(success); return true }
    catch (err) { setError(message(err)); return false }
    finally { setBusy(false) }
  }
  const active = targets.data?.destinations.filter(d => d.enabled && d.bot_enabled) || []
  const pending = discovered.data?.chats.filter(c => !c.ignored && c.present) || []
  const other = discovered.data?.chats.filter(c => c.ignored || !c.present) || []
  const openLifecycle = async (mode: 'delete' | 'rebind', dest: TelegramDestination) => {
    setError(''); setBusy(true)
    try {
      const summary = await adminApi.telegramDestinationImpact(dest.slug)
      if (summary.binding_id !== dest.binding_id) throw new Error('Destination змінився. Онови список.')
      setImpact(summary); setSelectedRoute(dest); setLifecycle(mode)
      setSelectedChat(''); setNewLabel(dest.label)
    } catch (err) { setError(message(err)) }
    finally { setBusy(false) }
  }
  const openCandidate = (chat: TelegramDiscoveredChat) => {
    setCandidate(chat); setSlug(suggestedSlug(chat.title)); setLabel(chat.title); setError('')
  }

  return <Stack spacing={2}>
    <Box>
      <Typography variant="h4" fontWeight={750}>Telegram Hub</Typography>
      <Typography color="text.secondary">Підключені чати, дозволені маршрути доставки та керування ботами.</Typography>
    </Box>
    {status.isLoading ? <CircularProgress size={24} /> : status.error ?
      <Alert severity="warning">Telegram Hub недоступний: {message(status.error)}. Legacy Telegram працює окремо.</Alert> :
      <>
        <Stack direction="row" gap={1} flexWrap="wrap" alignItems="center">
          <Chip color="success" size="small" label="Hub online" />
          <Chip size="small" label={String(active.length) + ' активних destinations'} />
          <Chip size="small" color={pending.length ? 'info' : 'default'} label={String(pending.length) + ' знайдено'} />
          <Chip size="small" label={String(bots.data?.bots.length || 0) + ' ботів'} />
          <Button size="small" onClick={() => void refresh()}>Оновити</Button>
        </Stack>
        {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}
        {notice && <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
        <Tabs value={tab} onChange={(_, v: number) => setTab(v)}>
          <Tab label="Destinations" /><Tab label="Bots" /><Tab label="Activity" />
        </Tabs>
        {tab === 0 && <Stack spacing={2}>
          <Card variant="outlined"><CardContent><Stack spacing={1.5}>
            <Typography variant="h6" fontWeight={700}>Знайдені чати {pending.length ? '(' + pending.length + ')' : ''}</Typography>
            <Typography variant="body2" color="text.secondary">
              Додай бота до групи або каналу. Для вже доданого бота надішли /register@BotUsername у групі.
              Новий чат з'явиться тут після опитування Telegram — агенти не отримають доступ без твого підтвердження.
            </Typography>
            {discovered.error && <Alert severity="warning">{message(discovered.error)}</Alert>}
            {Object.entries(discovered.data?.receivers || {}).map(([id, receiver]) =>
              <Typography variant="caption" color={receiver.state === 'polling' ? 'text.secondary' : 'warning.main'} key={id}>
                @{bots.data?.bots.find(b => b.id === id)?.username || id}: {receiver.state}
                {receiver.detail ? ' · ' + receiver.detail : ''}
              </Typography>)}
            {!pending.length && <Typography color="text.secondary">Нових чатів поки немає. Перевір статус receiver у вкладці Bots.</Typography>}
            {pending.map(chat => <Stack key={chat.bot_id + chat.chat_id} direction="row" alignItems="center" gap={1} flexWrap="wrap" sx={{ py: 0.75 }}>
              <Box sx={{ flex: 1, minWidth: 180 }}>
                <Typography fontWeight={650}>{chat.title}</Typography>
                <Typography variant="caption" color="text.secondary">{chat.chat_type} · @{chat.bot_username} · {chat.source}</Typography>
              </Box>
              <Button size="small" variant="contained" disabled={busy || !chat.bot_enabled} onClick={() => openCandidate(chat)}>Дозволити</Button>
              <Button size="small" disabled={busy} onClick={() => void action(() => adminApi.telegramIgnoreDiscovered(chat.bot_id, chat.chat_id, true), 'Чат приховано')}>Ігнорувати</Button>
            </Stack>)}
            {other.length > 0 && <>
              <Button size="small" onClick={() => setShowIgnored(!showIgnored)}>{showIgnored ? 'Приховати' : 'Показати'} інші ({other.length})</Button>
              {showIgnored && other.map(chat => <Stack key={chat.bot_id + chat.chat_id} direction="row" gap={1} alignItems="center" flexWrap="wrap">
                <Typography sx={{ flex: 1 }}>{chat.title} · {chat.present ? 'ігноровано' : 'бот залишив чат'}</Typography>
                {chat.ignored && <Button size="small" disabled={busy} onClick={() => void action(() => adminApi.telegramIgnoreDiscovered(chat.bot_id, chat.chat_id, false), 'Чат відновлено')}>Відновити</Button>}
              </Stack>)}
            </>}
          </Stack></CardContent></Card>
          <Card variant="outlined"><CardContent><Stack spacing={1.5}>
            <Typography variant="h6" fontWeight={700}>Дозволені destinations</Typography>
            {!targets.data?.destinations.length && <Typography color="text.secondary">Поки немає дозволених маршрутів.</Typography>}
            {targets.data?.destinations.map(dest => <Stack key={dest.slug} direction="row" gap={1} alignItems="center" flexWrap="wrap" sx={{ py: 0.5 }}>
              <Box sx={{ flex: 1, minWidth: 190 }}>
                <Typography fontWeight={650}>{dest.label} <Typography component="span" color="text.secondary" variant="caption">({dest.slug})</Typography></Typography>
                <Typography variant="caption" color="text.secondary">{dest.chat_type} · bot {bots.data?.bots.find(b => b.id === dest.bot_id)?.username || dest.bot_id}</Typography>
              </Box>
              <Chip size="small" color={dest.enabled && dest.bot_enabled ? 'success' : 'default'} label={dest.enabled && dest.bot_enabled ? 'Активний' : 'Вимкнений'} />
              <Button size="small" disabled={busy} onClick={() => void action(() => adminApi.telegramSetDestination(dest.slug, !dest.enabled), 'Маршрут оновлено')}>{dest.enabled ? 'Вимкнути' : 'Увімкнути'}</Button>
              <Button size="small" disabled={!dest.enabled || !dest.bot_enabled} onClick={() => { setTestDestination(dest.slug); setTestMessage(''); setConfirmTest(true) }}>Тест</Button>
              <Button size="small" disabled={busy} onClick={() => void openLifecycle('rebind', dest)}>Переприв'язати</Button>
              <Button size="small" color="error" disabled={busy} onClick={() => void openLifecycle('delete', dest)}>Видалити</Button>
            </Stack>)}
            <Divider />
            <Button size="small" onClick={() => setManual(!manual)}>{manual ? 'Сховати' : 'Ручне додавання за chat ID (резервний спосіб)'}</Button>
            {manual && <Stack spacing={1}>
              <TextField size="small" label="Slug" value={slug} onChange={e => setSlug(e.target.value)} helperText="Стабільна назва маршруту: news, cars, notifications" />
              <TextField size="small" label="Назва" value={label} onChange={e => setLabel(e.target.value)} />
              <TextField size="small" label="Числовий Telegram chat ID" value={chatId} onChange={e => setChatId(e.target.value)} />
              <TextField select size="small" label="Бот" value={botId} onChange={e => setBotId(e.target.value)}>
                {(bots.data?.bots || []).filter(b => b.enabled).map(b => <MenuItem key={b.id} value={b.id}>{b.label} (@{b.username})</MenuItem>)}
              </TextField>
              <Button variant="outlined" disabled={busy || !slug || !label || !botId || !chatId} onClick={() => void action(() => adminApi.telegramAddDestination({ slug, label, bot_id: botId, chat_id: chatId }), 'Destination додано')}>Додати вручну</Button>
            </Stack>}
          </Stack></CardContent></Card>
        </Stack>}
        {tab === 1 && <Stack spacing={2}>
          <Card variant="outlined"><CardContent><Stack spacing={1.5}>
            <Typography variant="h6" fontWeight={700}>Боти та receiver</Typography>
            {bots.data?.bots.map(bot => <Stack key={bot.id} direction="row" alignItems="center" gap={1} flexWrap="wrap">
              <Box sx={{ flex: 1, minWidth: 200 }}>
                <Typography fontWeight={650}>{bot.label} (@{bot.username})</Typography>
                <Typography variant="caption" color="text.secondary">Receiver: {discovered.data?.receivers[bot.id]?.state || (bot.enabled ? 'очікує опитування' : 'вимкнений')}</Typography>
              </Box>
              <Chip size="small" color={bot.enabled ? 'success' : 'default'} label={bot.enabled ? 'Активний' : 'Вимкнений'} />
              <Button size="small" disabled={busy} onClick={() => void action(() => adminApi.telegramSetBot(bot.id, !bot.enabled), 'Стан бота оновлено')}>{bot.enabled ? 'Вимкнути' : 'Увімкнути'}</Button>
            </Stack>)}
            <Divider />
            <Typography variant="subtitle1" fontWeight={650}>Додати бота</Typography>
            <TextField size="small" label="Назва" value={botLabel} onChange={e => setBotLabel(e.target.value)} />
            <TextField size="small" label="BotFather token" type="password" autoComplete="off" value={botToken} onChange={e => setBotToken(e.target.value)} helperText="Зберігається зашифрованим; не відображається після збереження." />
            <Button variant="outlined" disabled={busy || !botLabel.trim() || !botToken.trim()} onClick={() => void (async () => {
              const ok = await action(() => adminApi.telegramAddBot({ label: botLabel, token: botToken }), 'Бота додано')
              setBotToken(''); if (ok) setBotLabel('')
            })()}>Додати бота</Button>
          </Stack></CardContent></Card>
        </Stack>}
        {tab === 2 && <Stack spacing={2}>
          <Card variant="outlined"><CardContent><Stack spacing={1.5}>
            <Typography variant="h6" fontWeight={700}>Діагностика денного summary</Typography>
            <Typography variant="body2" color="text.secondary">
              Перевірити права або повторити лише pin існуючого повідомлення. Новий текст чи повідомлення не створюються.
            </Typography>
            <TextField select size="small" label="Destination" value={summaryDestination} onChange={e => { setSummaryDestination(e.target.value); setSummaryInfo('') }}>
              {active.map(dest => <MenuItem key={dest.slug} value={dest.slug}>{dest.label} ({dest.slug})</MenuItem>)}
            </TextField>
            <TextField size="small" label="Summary key" value={summaryKey} onChange={e => { setSummaryKey(e.target.value); setSummaryInfo('') }} placeholder="news:YYYY-MM-DD" />
            <Stack direction="row" gap={1} flexWrap="wrap">
              <Button size="small" variant="outlined" disabled={busy || !summaryDestination || !summaryKey.trim()}
                onClick={() => void action(async () => {
                  const state = await adminApi.telegramSummaryStatus(summaryDestination, summaryKey)
                  setSummaryInfo('Message ' + state.message_id + ' · ' + (state.pinned ? 'закріплено' : 'не закріплено'))
                }, 'Summary знайдено')}>Перевірити summary</Button>
              <Button size="small" variant="outlined" disabled={busy || !summaryDestination || !summaryKey.trim()}
                onClick={() => void action(async () => {
                  const rights = await adminApi.telegramSummaryPermissions(summaryDestination, summaryKey)
                  setSummaryInfo(rights.bot_status + ' · ' + (rights.required_right || 'спеціальне право не визначено') + ': ' +
                    (rights.can_pin === null ? 'невідомо' : rights.can_pin ? 'дозволено' : 'немає права'))
                }, 'Права перевірено')}>Права бота</Button>
              <Button size="small" color="warning" variant="outlined" disabled={busy || !summaryDestination || !summaryKey.trim()}
                onClick={() => setConfirmPin(true)}>Повторити лише pin</Button>
            </Stack>
            {summaryInfo && <Typography variant="body2">{summaryInfo}</Typography>}
          </Stack></CardContent></Card>
          <Card variant="outlined"><CardContent><Stack spacing={1}>
          <Typography variant="h6" fontWeight={700}>Останні доставки</Typography>
          {!history.data?.deliveries.length && <Typography color="text.secondary">Поки немає доставок.</Typography>}
          {history.data?.deliveries.slice(0, 30).map(row => <Stack key={row.delivery_id} direction="row" gap={1} alignItems="center">
            <Typography sx={{ flex: 1 }} variant="body2">{row.destination} · {row.operation}</Typography>
            <Chip size="small" label={row.status} color={row.status === 'accepted' ? 'success' : 'warning'} />
            {row.error_code && <Typography variant="caption" color="error">{row.error_code}</Typography>}
          </Stack>)}
        </Stack></CardContent></Card></Stack>}
      </>
    }
    <Dialog open={confirmPin} onClose={() => { if (!busy) setConfirmPin(false) }} fullWidth maxWidth="sm">
      <DialogTitle>Повторити закріплення?</DialogTitle>
      <DialogContent><Typography variant="body2">
        Telegram Hub спробує закріпити лише вже збережений summary <b>{summaryKey}</b> у <b>{summaryDestination}</b>.
        Нове повідомлення не створюватиметься.
      </Typography></DialogContent>
      <DialogActions>
        <Button disabled={busy} onClick={() => setConfirmPin(false)}>Скасувати</Button>
        <Button disabled={busy} color="warning" variant="contained" onClick={() => void (async () => {
          await action(async () => {
            const result = await adminApi.telegramSummaryPin(summaryDestination, summaryKey)
            setSummaryInfo('Message ' + result.message_id + ' · pin: ' + result.pin_status +
              (result.description ? ' · ' + result.description : ''))
            if (result.status !== 'accepted') throw new Error(result.description || result.pin_status)
            setConfirmPin(false)
          }, 'Закріплення підтверджено')
        })()}>Закріпити</Button>
      </DialogActions>
    </Dialog>
    <Dialog open={!!lifecycle} onClose={() => { if (!busy) setLifecycle(null) }} fullWidth maxWidth="sm">
      <DialogTitle>{lifecycle === 'rebind' ? 'Переприв’язати destination' : 'Видалити destination'}</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
        <Typography><b>{selectedRoute?.slug}</b> · {selectedRoute?.label}</Typography>
        <Typography variant="body2" color="text.secondary">
          Поточний чат: {selectedRoute?.chat_id} · binding {selectedRoute?.binding_id}
        </Typography>
        <Alert severity="warning">
          Історія доставок збережеться, але прив'язка до цього чату завершиться.
          {impact?.summary_count ? ' Активних summary: ' + impact.summary_count + ' (будуть архівовані).' : ' Активних summary немає.'}
          {' Доставок у поточній прив’язці: ' + (impact?.delivery_count ?? 0) + '.'}
        </Alert>
        {impact?.queue_scan === 'unavailable' && <Alert severity="warning">
          Не вдалося перевірити Task Queue — можливі залежності невідомі.
        </Alert>}
        {(impact?.queue_matches_total ?? 0) > 0 && <Alert severity="warning">
          Можливі посилання в активних Task Queue rules ({impact?.queue_matches_total}):
          {impact?.queue_rules?.map(r => ' ' + r.title).join(';')}
          . Ці правила не змінюватимуться.
        </Alert>}
        {lifecycle === 'delete'
          ? <Alert severity="info">Slug стане доступним для нового destination. Повідомлення в Telegram не видаляються.</Alert>
          : <>
              <Typography variant="body2">Вибери новий виявлений чат. Старі message ID та ключі ідемпотентності до нього не переноситимуться.</Typography>
              <TextField select fullWidth label="Новий чат" value={selectedChat} onChange={e => setSelectedChat(e.target.value)}>
                {pending.filter(chat => chat.bot_enabled && chat.bot_id + ':' + chat.chat_id !== selectedRoute?.bot_id + ':' + selectedRoute?.chat_id)
                  .map(chat => <MenuItem key={chat.bot_id + ':' + chat.chat_id} value={chat.bot_id + ':' + chat.chat_id}>
                    {chat.title} · {chat.chat_type} · @{chat.bot_username}
                  </MenuItem>)}
              </TextField>
              <TextField label="Назва destination" fullWidth value={newLabel} onChange={e => setNewLabel(e.target.value)} />
              {!pending.length && <Alert severity="info">Спочатку додай бота до нової групи та дочекайся Chat Discovery.</Alert>}
            </>}
      </Stack></DialogContent>
      <DialogActions>
        <Button disabled={busy} onClick={() => setLifecycle(null)}>Скасувати</Button>
        <Button color={lifecycle === 'delete' ? 'error' : 'warning'} variant="contained"
          disabled={busy || !selectedRoute || !impact || (lifecycle === 'rebind' && (!selectedChat || !newLabel.trim()))}
          onClick={() => void (async () => {
            if (!selectedRoute || !impact) return
            const dest = selectedRoute
            const currentImpact = impact
            const operation = lifecycle
            const candidate = pending.find(chat => chat.bot_id + ':' + chat.chat_id === selectedChat)
            if (operation === 'rebind' && !candidate) { setError('Вибери знайдений чат'); return }
            const ok = await action(async () => {
              if (operation === 'delete') {
                await adminApi.telegramDeleteDestination(dest.slug, currentImpact.binding_id)
              } else if (candidate) {
                await adminApi.telegramRebindDestination(dest.slug, currentImpact.binding_id, candidate, newLabel)
              }
            }, operation === 'delete' ? 'Destination видалено, історію збережено' : 'Destination переприв’язано')
            if (ok) setLifecycle(null)
          })()}>
          {lifecycle === 'delete' ? 'Підтвердити видалення' : 'Підтвердити переприв’язку'}
        </Button>
      </DialogActions>
    </Dialog>
    <Dialog open={!!candidate} onClose={() => { if (!busy) setCandidate(null) }} fullWidth maxWidth="sm">
      <DialogTitle>Дозволити доставку в чат</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
        <Typography>{candidate?.title} · {candidate?.chat_type} · @{candidate?.bot_username}</Typography>
        <Typography color="text.secondary" variant="body2">Після підтвердження агенти з профілем, що має доступ до Telegram Hub, зможуть надсилати сюди повідомлення за slug.</Typography>
        <TextField label="Slug" value={slug} onChange={e => setSlug(e.target.value)} helperText="Латинські малі літери, цифри, дефіс або _" />
        <TextField label="Назва destination" value={label} onChange={e => setLabel(e.target.value)} />
      </Stack></DialogContent>
      <DialogActions><Button disabled={busy} onClick={() => setCandidate(null)}>Скасувати</Button>
        <Button variant="contained" disabled={busy || !candidate || !/^[a-z][a-z0-9_-]{1,63}$/.test(slug) || !label.trim()} onClick={() => void (async () => {
          if (!candidate) return
          const ok = await action(() => adminApi.telegramApproveDiscovered(candidate.bot_id, candidate.chat_id, slug, label), 'Destination дозволено')
          if (ok) setCandidate(null)
        })()}>Дозволити</Button>
      </DialogActions>
    </Dialog>
    <Dialog open={confirmTest} onClose={() => { if (!busy) setConfirmTest(false) }} fullWidth maxWidth="sm">
      <DialogTitle>Тестове повідомлення</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
        <Typography variant="body2">Реальна доставка до <b>{testDestination}</b>. Підтверди текст.</Typography>
        <TextField multiline minRows={2} label="Текст" value={testMessage} onChange={e => setTestMessage(e.target.value)} />
      </Stack></DialogContent>
      <DialogActions><Button disabled={busy} onClick={() => setConfirmTest(false)}>Скасувати</Button>
        <Button variant="contained" color="warning" disabled={busy || !testMessage.trim()} onClick={() => void (async () => {
          const ok = await action(async () => {
            const result = await adminApi.telegramDeliveryTestSend(testDestination, testMessage)
            if (result.status !== 'accepted') throw new Error(result.status + (result.error_code ? ': ' + result.error_code : ''))
          }, 'Telegram прийняв повідомлення')
          if (ok) setConfirmTest(false)
        })()}>Надіслати</Button>
      </DialogActions>
    </Dialog>
  </Stack>
}
