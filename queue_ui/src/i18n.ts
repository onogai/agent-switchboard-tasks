import uk from './locales/uk.json'
import esES from './locales/es-ES.json'

export type UiLanguage = 'en' | 'uk' | 'es-ES'
export const UI_LANGUAGE_KEY = 'switchboard.admin.locale'
export const UI_LANGUAGES: ReadonlyArray<{ code: UiLanguage; label: string }> = [
  { code: 'en', label: 'English' },
  { code: 'uk', label: 'Українська' },
  { code: 'es-ES', label: 'Español (España)' },
]
const catalogs: Record<Exclude<UiLanguage, 'en'>, Record<string, string>> = {
  uk, 'es-ES': esES,
}
export function getUiLanguage(): UiLanguage {
  if (typeof window === 'undefined') return 'en'
  try {
    const saved = window.localStorage.getItem(UI_LANGUAGE_KEY)
    return saved === 'uk' || saved === 'es-ES' ? saved : 'en'
  } catch { return 'en' }
}
export function setUiLanguage(language: UiLanguage) {
  if (typeof window === 'undefined') return
  try { window.localStorage.setItem(UI_LANGUAGE_KEY, language) } catch { /* private mode */ }
  window.location.reload()
}
export function languageTag(): string {
  return getUiLanguage() === 'uk' ? 'uk-UA' : getUiLanguage() === 'es-ES' ? 'es-ES' : 'en-GB'
}
/** English is the source/fallback. Catalogs contain presentation copy only. */
export function tx(english: string, params?: Record<string, string | number>): string {
  const lang = getUiLanguage()
  let localized = lang === 'en' ? english : (catalogs[lang][english] || english)
  if (params) for (const [key, value] of Object.entries(params)) {
    localized = localized.replaceAll('{' + key + '}', String(value))
  }
  return localized
}
