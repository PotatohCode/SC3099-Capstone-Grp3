import { readFileSync } from 'fs'
import { join } from 'path'
import { runInNewContext } from 'vm'

type Handler = (event: { request: FakeRequest; respondWith: (p: Promise<unknown>) => void }) => void

interface FakeRequest {
  url: string
  method: string
  destination: string
}

function loadWorker(network: (url: string) => Promise<{ ok: boolean; body: string; clone: () => unknown }>) {
  const store = new Map<string, unknown>()
  const listeners: Record<string, Handler> = {}
  const cache = {
    match: async (req: FakeRequest) => store.get(req.url),
    put: async (req: FakeRequest, res: unknown) => {
      store.set(req.url, res)
    },
    addAll: async () => undefined,
  }
  const self: Record<string, unknown> = {
    location: { origin: 'https://app.test' },
    addEventListener: (name: string, fn: Handler) => {
      listeners[name] = fn
    },
  }
  const context: Record<string, unknown> = {
    self,
    caches: { open: async () => cache, keys: async () => [], delete: async () => true },
    fetch: (req: FakeRequest) => network(req.url),
    URL,
    Response: { error: () => ({ ok: false, body: 'error' }) },
    importScripts: () => runInNewContext(readFileSync(join(process.cwd(), 'public/offline.js'), 'utf8'), context),
  }
  self.self = self
  context.self = self
  runInNewContext(readFileSync(join(process.cwd(), 'public/service-worker.js'), 'utf8'), context)
  async function get(url: string) {
    let pending: Promise<unknown> | undefined
    listeners.fetch({ request: { url, method: 'GET', destination: '' }, respondWith: (p) => (pending = p) })
    return pending
  }
  return { get, store }
}

function reply(body: string) {
  const res = { ok: true, body, clone: () => res }
  return res
}

describe('service worker caching for check-in history', () => {
  const url = 'https://app.test/api/v1/checkins/my-checkins?limit=100'

  it('returns fresh my-checkins data instead of an older cached copy', async () => {
    let version = 'old'
    const { get } = loadWorker(async () => reply(version))
    expect(await get(url)).toMatchObject({ body: 'old' })
    version = 'new'
    expect(await get(url)).toMatchObject({ body: 'new' })
  })

  it('falls back to the cached my-checkins copy when offline', async () => {
    let online = true
    const { get } = loadWorker(async () => {
      if (!online) throw new TypeError('Failed to fetch')
      return reply('cached')
    })
    await get(url)
    online = false
    expect(await get(url)).toMatchObject({ body: 'cached' })
  })
})
