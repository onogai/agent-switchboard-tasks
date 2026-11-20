import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { loadConfigFromFile } from 'vite'

const configPath = fileURLToPath(new URL('../vite.config.ts', import.meta.url))
const parsed = await loadConfigFromFile({ command: 'build', mode: 'test' }, configPath)
const plugin = parsed?.config.plugins?.find(item => item.name === 'switchboard-locale-catalogs')
assert.ok(plugin, 'Vite must load the locale catalog transform')

function transform(input) {
  const output = plugin.transform(input, fileURLToPath(new URL('./sample.tsx', import.meta.url)))
  return output?.code ?? input
}

test('only display text is translated; MCP and API values remain stable', () => {
  const output = transform(`
    export const Demo = ({status, send, userContent}) =>
      <div>
        <Tab value="Overview">Overview</Tab>
        <Chip label={status === 'active' ? 'Active' : 'Disabled'} />
        <input placeholder="Overview" value="Active" />
        <button onClick={() => send('Active')}>Confirm</button>
        <p>{userContent}</p>
        <span>{status === 'active' ? 'Active' : 'Disabled'}</span>
      </div>
  `)
  assert.match(output, /__tx\(["']Overview["']\)/)
  assert.match(output, /__tx\(["']Confirm["']\)/)
  assert.match(output, /__tx\(["']Overview["']\)/)
  assert.match(output, /value="Overview"/)
  assert.match(output, /value="Active"/)
  assert.match(output, /status === ["']active["']/)
  assert.match(output, /send\(["']Active["']\)/)
  assert.match(output, /\{userContent\}/)
})

test('unrelated constants, callbacks and payloads are never rewritten', () => {
  const code = `
    const payload = { status: 'active', action: 'Approve contracts' }
    export function Demo() {
      return <button onClick={() => mutate({ status: 'active', note: 'Confirm' })}>Confirm</button>
    }
  `
  const output = transform(code)
  assert.match(output, /status: ["']active["']/)
  assert.match(output, /note: ["']Confirm["']/)
  assert.match(output, /__tx\(["']Confirm["']\)/)
  assert.doesNotMatch(output, /note: __tx/)
})
