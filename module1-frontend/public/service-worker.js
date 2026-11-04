/**
 * Task 1.8 - Offline-First PWA Capabilities.
 * Component tree Section 2.1: "service-worker.js [SW registration + caching - Task 1.8]"
 *
 * Caching strategy (IMPLEMENTATION_PLAN.html Section 4, Task 1.8 / Decision 4):
 *   - Cache-First:            static assets (JS, CSS, images, fonts, icons, manifest)
 *   - Stale-While-Revalidate: GET /sessions*
 *   - Network-First:          GET /checkins/my-checkins (must be fresh to hide checked-in sessions)
 *   - Network-Only:           /auth/*, any non-GET request (incl. POST /checkins/)
 *
 * Section 7 Risk Analysis: "Service Worker Cache Poisoning" -> mitigated by the strict
 * Network-Only rule for auth + mutating endpoints, plus a versioned cache name that is
 * fully purged on activate.
 */

importScripts('/offline.js')

const CACHE_VERSION = 'v2'
const STATIC_CACHE = `saiv-static-${CACHE_VERSION}`
const READS_CACHE = `saiv-reads-${CACHE_VERSION}`
const PAGES_CACHE = `saiv-pages-${CACHE_VERSION}`
const CURRENT_CACHES = [STATIC_CACHE, READS_CACHE, PAGES_CACHE]

const APP_SHELL_PAGES = ['/', '/auth/login', '/dashboard', '/dashboard/checkin', '/dashboard/history', '/dashboard/settings']

const PRECACHE_URLS = [
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => caches.open(PAGES_CACHE))
      .then((cache) => Promise.all(APP_SHELL_PAGES.map((page) => precachePage(cache, page))))
      .then(() => self.skipWaiting())
  )
})

const PAGE_ASSET_PATTERN = /\/_next\/static\/[^"'\s)\\]+/g

/** Caches the scripts and styles a page's HTML references, so the page can start offline. */
async function cachePageAssets(response) {
  try {
    const html = await response.text()
    const urls = Array.from(new Set(html.match(PAGE_ASSET_PATTERN) || []))
    const cache = await caches.open(STATIC_CACHE)
    await Promise.all(urls.map((asset) => cache.match(asset).then((hit) => hit || cache.add(asset)).catch(() => undefined)))
  } catch (err) {
    return undefined
  }
}

/** Precaches one app-shell page and its assets; a missing page never blocks install. */
async function precachePage(cache, page) {
  try {
    await cache.add(page)
    const response = await cache.match(page)
    if (response) await cachePageAssets(response)
  } catch (err) {
    return undefined
  }
}

/** Serves a page network-first and, when it loads, keeps its assets cached for offline starts. */
async function handleNavigation(event) {
  const response = await self.networkFirst(event.request, PAGES_CACHE)
  if (response && response.ok) {
    try {
      event.waitUntil(cachePageAssets(response.clone()))
    } catch (err) {
      return response
    }
  }
  return response
}

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => !CURRENT_CACHES.includes(key))
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  )
})

const NETWORK_ONLY_PATTERNS = [/\/auth\//]

function isNetworkOnly(request, url) {
  if (request.method !== 'GET') return true
  return NETWORK_ONLY_PATTERNS.some((pattern) => pattern.test(url.pathname))
}

function isStaleWhileRevalidate(url) {
  return /\/sessions(\/|$)/.test(url.pathname)
}

function isNetworkFirst(url) {
  return /\/checkins\/my-checkins/.test(url.pathname)
}

function isStaticAsset(request, url) {
  if (request.destination && ['script', 'style', 'image', 'font'].includes(request.destination)) {
    return true
  }
  return url.origin === self.location.origin && PRECACHE_URLS.includes(url.pathname)
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  const url = new URL(request.url)

  // Never intercept non-HTTP(S) requests (e.g. chrome-extension://).
  if (!url.protocol.startsWith('http')) return

  // Pages: fresh online, cached offline.
  if (request.method === 'GET' && request.mode === 'navigate' && url.origin === self.location.origin) {
    event.respondWith(handleNavigation(event))
    return
  }

  if (isNetworkOnly(request, url)) {
    event.respondWith(self.networkOnly(request))
    return
  }

  if (isNetworkFirst(url)) {
    event.respondWith(self.networkFirst(request, READS_CACHE))
    return
  }

  if (isStaleWhileRevalidate(url)) {
    event.respondWith(self.staleWhileRevalidate(request, READS_CACHE))
    return
  }

  if (isStaticAsset(request, url)) {
    event.respondWith(self.cacheFirst(request, STATIC_CACHE))
    return
  }

  // Default: let the browser handle it normally (no interception).
})
