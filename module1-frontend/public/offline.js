/**
 * Task 1.8 - PWA Offline Capabilities.
 * Component tree Section 2.1: "offline.js [SW logic: Cache-First, Stale-While-Revalidate]"
 *
 * Pure caching-strategy helpers, loaded into service-worker.js via importScripts() so
 * they share the same `self`/`caches` global scope.
 *
 * Decision 4 (Section 9): "Service Worker Cache: Cache-First (assets) +
 * Stale-While-Revalidate (reads) + Network-Only (auth/mutations)"
 */

/** Cache-First: serve from cache if present, otherwise fetch + populate cache. */
async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName)
  const cached = await cache.match(request)
  if (cached) return cached

  try {
    const response = await fetch(request)
    if (response && response.ok) {
      cache.put(request, response.clone())
    }
    return response
  } catch (err) {
    if (cached) return cached
    throw err
  }
}

/**
 * Stale-While-Revalidate: return the cached response immediately (if any) while
 * kicking off a background fetch to refresh the cache for next time. Used for
 * GET /sessions and GET /checkins/my-checkins per Task 1.8.
 */
async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName)
  const cached = await cache.match(request)

  const networkFetch = fetch(request)
    .then((response) => {
      if (response && response.ok) {
        cache.put(request, response.clone())
      }
      return response
    })
    .catch(() => undefined)

  return cached || (await networkFetch) || Response.error()
}

/** Network-Only: never touch the cache. Used for /auth/* and all mutating requests. */
async function networkOnly(request) {
  return fetch(request)
}

// Expose on self for service-worker.js (classic worker scripts share global scope, but
// being explicit keeps this file understandable if inlined/refactored later).
self.cacheFirst = cacheFirst
self.staleWhileRevalidate = staleWhileRevalidate
self.networkOnly = networkOnly
