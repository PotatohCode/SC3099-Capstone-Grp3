/**
 * Task 1.8 - Offline-First PWA Capabilities.
 * Component tree Section 2.1: "service-worker.js [SW registration + caching - Task 1.8]"
 *
 * Caching strategy (IMPLEMENTATION_PLAN.html Section 4, Task 1.8 / Decision 4):
 *   - Cache-First:            static assets (JS, CSS, images, fonts, icons, manifest)
 *   - Stale-While-Revalidate: GET /sessions*, GET /checkins/my-checkins
 *   - Network-Only:           /auth/*, any non-GET request (incl. POST /checkins/)
 *
 * Section 7 Risk Analysis: "Service Worker Cache Poisoning" -> mitigated by the strict
 * Network-Only rule for auth + mutating endpoints, plus a versioned cache name that is
 * fully purged on activate.
 */

importScripts('/offline.js')

const CACHE_VERSION = 'v1'
const STATIC_CACHE = `saiv-static-${CACHE_VERSION}`
const READS_CACHE = `saiv-reads-${CACHE_VERSION}`
const CURRENT_CACHES = [STATIC_CACHE, READS_CACHE]

const PRECACHE_URLS = [
  '/',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  )
})

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
  return (
    /\/sessions(\/|$)/.test(url.pathname) ||
    /\/checkins\/my-checkins/.test(url.pathname)
  )
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

  if (isNetworkOnly(request, url)) {
    event.respondWith(self.networkOnly(request))
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
