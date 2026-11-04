import { readFileSync } from 'fs'
import { join } from 'path'
import { runInNewContext } from 'vm'

type Handler = (event: { request: FakeRequest; respondWith: (p: Promise<unknown>) => void }) => void

interface FakeRequest {
  url: string
  method: string
  destination: string
  mode?: string
}

type FakeResponse = { ok: boolean; body: string; clone: () => unknown; text?: () => Promise<string> }

function loadWorker(network: (url: string) => Promise<FakeResponse>) {
  const store = new Map<string, unknown>()
  const listeners: Record<string, Handler> = {}
  const key = (req: FakeRequest | string) => new URL(typeof req === 'string' ? req : req.url, 'https://app.test').href
  const cache = {
    match: async (req: FakeRequest | string) => store.get(key(req)),
    put: async (req: FakeRequest | string, res: unknown) => {
      store.set(key(req), res)
    },
    add: async (req: string) => {
      store.set(key(req), await network(key(req)))
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
  const background: Promise<unknown>[] = []
  async function get(url: string, mode?: string) {
    let pending: Promise<unknown> | undefined
    listeners.fetch({
      request: { url, method: 'GET', destination: '', mode },
      respondWith: (p) => (pending = p),
      waitUntil: (p: Promise<unknown>) => background.push(p),
    } as Parameters<Handler>[0])
    const result = await pending
    await Promise.all(background)
    return result
  }
  return { get, store }
}

function reply(body: string) {
  const res: FakeResponse = { ok: true, body, clone: () => res, text: async () => body }
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

describe('service worker caching for app pages', () => {
  const page = 'https://app.test/dashboard/settings'
  const html = '<script src="/_next/static/chunks/app/dashboard/settings/page-abc.js"></script><link href="/_next/static/css/x.css">'

  it('caches a page and the scripts and styles it references, then serves them offline', async () => {
    let online = true
    const { get, store } = loadWorker(async (url) => {
      if (!online) throw new TypeError('Failed to fetch')
      return reply(url === page ? html : `asset ${url}`)
    })
    expect(await get(page, 'navigate')).toMatchObject({ body: html })
    expect(store.has('https://app.test/_next/static/chunks/app/dashboard/settings/page-abc.js')).toBe(true)
    expect(store.has('https://app.test/_next/static/css/x.css')).toBe(true)
    online = false
    expect(await get(page, 'navigate')).toMatchObject({ body: html })
  })

  it('serves the login page offline even though /auth/ API calls stay network-only', async () => {
    let online = true
    const { get } = loadWorker(async (url) => {
      if (!online) throw new TypeError('Failed to fetch')
      return reply(`body ${url}`)
    })
    await get('https://app.test/auth/login', 'navigate')
    online = false
    expect(await get('https://app.test/auth/login', 'navigate')).toMatchObject({ body: 'body https://app.test/auth/login' })
    await expect(get('https://app.test/api/v1/auth/me')).rejects.toThrow('Failed to fetch')
  })
})
