import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const root = new URL('../src/locales/', import.meta.url)
const required = ["Language","Overview","Queue","Rules","Proposals","Task Manager","Task Queue sign-in","Cancel","Confirm action","Scheduled","Ready","Approve","Reject","New rule","Run now"]
let failures = 0
for (const language of ['uk', 'es-ES']) {
  const path = fileURLToPath(new URL(language + '.json', root))
  const catalog = JSON.parse(readFileSync(path, 'utf8'))
  for (const key of required) {
    if (typeof catalog[key] !== 'string' || !catalog[key].trim()) {
      console.error(language + ': missing UI translation for ' + key)
      failures++
    }
  }
  for (const [key, value] of Object.entries(catalog)) {
    if (typeof value !== 'string' || !value.trim() || !key.trim()) {
      console.error(language + ': empty or invalid translation key')
      failures++
    }
    if (language === 'es-ES' && /[\u0400-\u052f]/.test(value)) {
      console.error(language + ': Cyrillic text remains in Spanish translation: ' + key)
      failures++
    }
  }
  console.log(language + ': checked ' + Object.keys(catalog).length + ' translations')
}
if (failures) process.exitCode = 1
