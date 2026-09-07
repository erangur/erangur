/* Service worker for the Lightning Blackjack web app.
 *
 * The app is a single self-contained page that runs entirely in the browser
 * (the solver is in-page JS; there are no API calls). This worker makes the
 * Add-to-Home-Screen app work offline while still picking up new versions:
 *
 *   - the page itself (navigations): NETWORK-FIRST — when online you always get
 *     the latest build; when offline you get the cached copy.
 *   - everything else (manifest, …): cache-first.
 *
 * Bump CACHE on every release so the old cache is purged on activate. */
const CACHE = "lbj-v5";
// Relative to the worker's scope, so this works whether the app is served from
// "/" (localhost) or a project subpath like "/erangur/" (GitHub Pages).
const ASSETS = ["./", "./index.html", "./manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(ASSETS))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())   // never block install if a fetch fails
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;

  // The page: network-first, so a new build shows as soon as you're online.
  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => { c.put("./", copy); }).catch(() => {});
          return res;
        })
        .catch(() => caches.match("./").then((h) => h || caches.match("./index.html")))
    );
    return;
  }

  // Other same-origin GETs: cache-first, populate on miss.
  e.respondWith(
    caches.match(req, { ignoreSearch: true }).then((hit) => {
      if (hit) return hit;
      return fetch(req).then((res) => {
        try {
          const url = new URL(req.url);
          if (url.origin === self.location.origin && res && res.status === 200) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
        } catch (_) { /* ignore */ }
        return res;
      }).catch(() => undefined);
    })
  );
});
