// Service Worker — F&O Morning Screener PWA
// Enables offline support with cache-first strategy for static assets,
// network-first for Google Sheets data

const CACHE_VERSION = "fo-screener-v1";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const DATA_CACHE   = `${CACHE_VERSION}-data`;

const STATIC_FILES = [
  "/",
  "/index.html",
  "/manifest.json",
];

const SHEETS_API_PATTERN = "sheets.googleapis.com";

// ── Install: cache static assets ──────────────────────────────
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then(cache => {
      return cache.addAll(STATIC_FILES).catch(() => {
        // Non-fatal — may fail in dev
      });
    })
  );
  self.skipWaiting();
});

// ── Activate: clean old caches ─────────────────────────────────
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k.startsWith("fo-screener-") && k !== STATIC_CACHE && k !== DATA_CACHE)
          .map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ── Fetch: strategy based on request type ─────────────────────
self.addEventListener("fetch", event => {
  const url = event.request.url;

  // Google Sheets API → network-first, fall back to cache
  if (url.includes(SHEETS_API_PATTERN) || url.includes("docs.google.com")) {
    event.respondWith(
      caches.open(DATA_CACHE).then(async cache => {
        try {
          const response = await fetch(event.request);
          if (response.ok) {
            cache.put(event.request, response.clone());
          }
          return response;
        } catch {
          const cached = await cache.match(event.request);
          return cached || new Response(
            JSON.stringify({ error: "offline", cached: false }),
            { headers: { "Content-Type": "application/json" } }
          );
        }
      })
    );
    return;
  }

  // Static assets → cache-first
  event.respondWith(
    caches.match(event.request).then(cached => {
      return cached || fetch(event.request).then(response => {
        if (response.ok) {
          caches.open(STATIC_CACHE).then(cache => {
            cache.put(event.request, response.clone());
          });
        }
        return response;
      });
    })
  );
});

// ── Background sync: refresh data when online ─────────────────
self.addEventListener("sync", event => {
  if (event.tag === "refresh-data") {
    event.waitUntil(
      self.clients.matchAll().then(clients => {
        clients.forEach(client => {
          client.postMessage({ type: "REFRESH_DATA" });
        });
      })
    );
  }
});
