/* Service worker for the Lightning Blackjack web app.
 *
 * The app is a single self-contained page that runs entirely in the browser
 * (the solver is in-page JS; there are no API calls). This worker precaches
 * that page on first load so the Add-to-Home-Screen app keeps working offline
 * — even when the little Python loader that first served it is long gone. */
const CACHE = "lbj-v1";
const ASSETS = ["/", "/index.html", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(ASSETS))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())   // manifest optional; never block install
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
      }).catch(() =>
        caches.match("/").then((h) => h || caches.match("/index.html"))
      );
    })
  );
});
