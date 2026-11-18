import assert from 'node:assert/strict'
import test from 'node:test'
import { createBulkPreviewGuard, groupGatewayTools, updatedGrants } from './gatewayMatrixModel.ts'

const tool = (source, name, grants = [], status = 'active') => ({
  id: `${source}/${name}`, source_id: source, public_name: name, title: null,
  description: 'A tool', effects: 'none', status, grants,
  source_enabled: true, source_status: 'online',
})
const sources = [
  { id: 'zeta', enabled: true, status: 'online' },
  { id: 'alpha', enabled: false, status: 'offline' },
]
const tools = [
  tool('zeta', 'weather', ['interactive']),
  tool('alpha', 'inspect', ['unattended', 'interactive'], 'review'),
  tool('alpha', 'analyze'),
  tool('zeta', 'fetch', ['local-interactive']),
]
const all = { query: '', sourceId: 'all', profile: 'all', access: 'all' }

test('source grouping is stable and sorted and retains source status', () => {
  const grouped = groupGatewayTools(tools, sources, all)
  assert.deepEqual(grouped.map(g => g.id), ['alpha', 'zeta'])
  assert.deepEqual(grouped[0].tools.map(t => t.public_name), ['analyze', 'inspect'])
  assert.equal(grouped[0].enabled, false)
  assert.equal(grouped[0].status, 'offline')
  assert.equal(tools[0].public_name, 'weather') // input order not mutated
})

test('quick filters combine query, upstream and profile', () => {
  const grouped = groupGatewayTools(tools, sources, {
    query: 'INS', sourceId: 'alpha', profile: 'interactive', access: 'granted',
  })
  assert.deepEqual(grouped.map(g => g.tools.map(t => t.public_name)), [['inspect']])
  assert.deepEqual(groupGatewayTools(tools, sources, { ...all, profile: 'local-interactive' })
    .flatMap(g => g.tools.map(t => t.public_name)), ['fetch'])
})

test('ungranted and needs-review selections are separate', () => {
  assert.deepEqual(groupGatewayTools(tools, sources, { ...all, access: 'ungranted' })
    .flatMap(g => g.tools.map(t => t.public_name)), ['analyze'])
  assert.deepEqual(groupGatewayTools(tools, sources, { ...all, access: 'review' })
    .flatMap(g => g.tools.map(t => t.public_name)), ['inspect'])
})

test('grant changes are immutable, idempotent and preserve other profiles', () => {
  const old = ['interactive', 'future-profile']
  assert.deepEqual(updatedGrants(old, 'unattended', true), ['future-profile', 'interactive', 'unattended'])
  assert.deepEqual(updatedGrants(old, 'interactive', false), ['future-profile'])
  assert.deepEqual(updatedGrants(old, 'interactive', true), ['future-profile', 'interactive'])
  assert.deepEqual(old, ['interactive', 'future-profile'])
})

test('unknown source in tools does not disappear', () => {
  const groups = groupGatewayTools([tool('new', 'hello')], sources, all)
  assert.equal(groups.length, 1)
  assert.equal(groups[0].id, 'new')
})

test('late preview response is rejected when the filtered selection changes', async () => {
  const guard = createBulkPreviewGuard()
  const issued = guard.begin()
  let resolveRequest
  const request = new Promise(resolve => { resolveRequest = resolve })
  let shownPreview = null
  const onResponse = request.then(result => {
    if (guard.accepts(issued)) shownPreview = result
  })
  guard.invalidate() // user changed the upstream/search/status filter
  resolveRequest({ ids: ['alpha/inspect'] })
  await onResponse
  assert.equal(shownPreview, null)

  const newer = guard.begin()
  assert.equal(guard.accepts(issued), false)
  assert.equal(guard.accepts(newer), true)
  guard.invalidate() // reset filters must invalidate as well
  assert.equal(guard.accepts(newer), false)
})
