import { FormControl, MenuItem, Select, Stack, Typography } from '@mui/material'
import { getUiLanguage, setUiLanguage, tx, UI_LANGUAGES, type UiLanguage } from './i18n'

/** Reloading also refreshes the independent Queue iframe after a language change. */
export function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  return <Stack direction="row" alignItems="center" gap={0.75}>
    {!compact && <Typography variant="caption" color="text.secondary">{tx('Language')}</Typography>}
    <FormControl size="small" sx={{ minWidth: compact ? 118 : 155 }}>
      <Select value={getUiLanguage()}
        inputProps={{ 'aria-label': tx('Language') }}
        onChange={event => setUiLanguage(event.target.value as UiLanguage)}
        sx={{ fontSize: 13, '& .MuiSelect-select': { py: 0.75, px: 1.25 } }}>
        {UI_LANGUAGES.map(item =>
          <MenuItem key={item.code} value={item.code}>{item.label}</MenuItem>)}
      </Select>
    </FormControl>
  </Stack>
}
