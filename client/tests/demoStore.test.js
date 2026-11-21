import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import { createContext, SourceTextModule } from 'node:vm'
import { randomUUID } from 'node:crypto'

const source = await readFile(new URL('../src/data/demoStore.js', import.meta.url), 'utf8')

// Independent module instances represent tabs sharing one browser storage area.
function browser({ blocked = false, initial } = {}) {
  const values = new Map(initial)
  const tabs = []
  return {
    async tab() {
      const current = { onStorage: null }
      tabs.push(current)
      const context = createContext({
        crypto: { randomUUID },
        localStorage: {
          getItem(key) {
            if (blocked) throw new Error('Storage blocked')
            return values.get(key) ?? null
          },
          setItem(key, value) {
            if (blocked) throw new Error('Storage blocked')
            values.set(key, value)
            for (const tab of tabs) {
              if (tab !== current) tab.onStorage?.({ key })
            }
          },
        },
        window: { addEventListener: (type, handler) => {
          if (type === 'storage') current.onStorage = handler
        } },
      })
      const module = new SourceTextModule(source, { context })
      await module.link(() => { throw new Error('Unexpected dependency') })
      await module.evaluate()
      return module.namespace.demoStore
    },
  }
}

test('simulation syncs to another tab, with stable snapshots and subscriptions', async () => {
  const shared = browser()
  const today = await shared.tab()
  const family = await shared.tab()
  let updates = 0
  const unsubscribe = today.subscribe(() => updates++)
  assert.equal(today.getSnapshot(), today.getSnapshot())
  family.simulateOffRoute()
  const id = today.getSnapshot().checkIn.id
  assert.equal(id, family.getSnapshot().checkIn.id)
  assert.equal(updates, 1)
  family.simulateOffRoute()
  assert.equal(today.getSnapshot().checkIn.id, id)
  unsubscribe()
  const before = updates
  family.reset()
  assert.equal(updates, before)
})

test('all choices sync, contact requests are idempotent, and reset persists', async () => {
  const shared = browser()
  const today = await shared.tab()
  const family = await shared.tab()
  family.simulateOffRoute()
  for (const response of ['continue', 'directions', 'contact']) {
    today.respond(response)
    assert.equal(family.getSnapshot().checkIn.response, response)
  }
  const request = family.getSnapshot().contactRequest.createdAt
  assert.ok(Number.isFinite(Date.parse(request)))
  today.respond('contact')
  assert.equal(family.getSnapshot().contactRequest.createdAt, request)
  const refreshed = await shared.tab()
  assert.equal(refreshed.getSnapshot().contactRequest.createdAt, request)
  family.reset()
  assert.equal(today.getSnapshot().checkIn, null)
  assert.equal(today.getSnapshot().contactRequest, null)
  assert.equal((await shared.tab()).getSnapshot().checkIn, null)
})

test('choices without a check-in and unknown responses do not create requests', async () => {
  const store = await browser().tab()
  store.respond('contact')
  assert.equal(store.getSnapshot().contactRequest, null)
  store.simulateOffRoute()
  store.respond('unknown')
  assert.equal(store.getSnapshot().checkIn.response, null)
})

test('unavailable storage is exposed to the UI without throwing', async () => {
  const store = await browser({ blocked: true }).tab()
  assert.equal(store.getSnapshot().storageError, true)
  assert.doesNotThrow(() => store.simulateOffRoute())
  assert.equal(store.getSnapshot().storageError, true)
})

test('unrecognized stored versions recover to a fresh demo', async () => {
  const store = await browser({ initial: [['whats-next-demo-v1', '{"version":0}']] }).tab()
  assert.equal(store.getSnapshot().checkIn, null)
  store.simulateOffRoute()
  assert.ok(store.getSnapshot().checkIn.id)
})
