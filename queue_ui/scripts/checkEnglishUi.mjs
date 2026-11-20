import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'

const root = new URL('../src/', import.meta.url).pathname
const violations = []
function inspect(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      // Additional language packs will live in src/locales/.
      if (entry.name !== 'locales') inspect(join(directory, entry.name))
      continue
    }
    if (!/\.(tsx?|jsx?)$/.test(entry.name) || /\.test\./.test(entry.name)) continue
    const path = join(directory, entry.name)
    readFileSync(path, 'utf8').split('\n').forEach((line, i) => {
      if (/[\u0400-\u052F]/.test(line)) violations.push(`${relative(root, path)}:${i + 1}`)
    })
  }
}
inspect(root)
if (violations.length) {
  process.stderr.write('Untranslated Cyrillic UI strings in source:\n' + violations.join('\n') + '\n')
  process.exitCode = 1
}
