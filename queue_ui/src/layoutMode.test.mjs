import assert from 'node:assert/strict'
import test from 'node:test'
import { queueLayout } from './layoutMode.ts'

test('embedded Queue keeps shared Manager navigation', () => {
  assert.deepEqual(queueLayout('/admin/queue/', true),
    { managed: true, embedded: true })
  assert.deepEqual(queueLayout('/admin/queue/rules/my-rule', true),
    { managed: true, embedded: true })
})

test('Queue opened directly retains standalone sidebar and Manager return link', () => {
  assert.deepEqual(queueLayout('/admin/queue/', false),
    { managed: true, embedded: false })
  assert.deepEqual(queueLayout('/queue/', false),
    { managed: false, embedded: false })
})

test('standalone Queue remains standalone even when framed', () => {
  assert.deepEqual(queueLayout('/queue/rules', true),
    { managed: false, embedded: false })
  assert.deepEqual(queueLayout('/admin/queue-unrelated', true),
    { managed: false, embedded: false })
})
