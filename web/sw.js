/* Service worker Sporia — PWA « coquille seule ».
   Met en cache l'app (HTML/CSS/JS/vendor/icônes) pour un démarrage instantané et
   une ouverture hors-ligne. Ne met JAMAIS en cache les données (/api) ni les
   tuiles carto → pas de péremption trompeuse. */
const CACHE = "sporia-shell-v2";
const PRECACHE = [
  "/",
  "/static/vendor/leaflet/leaflet.js",
  "/static/vendor/leaflet/leaflet.css",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // Cross-origin (tuiles CARTO/IGN, WMS…), API et overlays PNG : réseau seulement.
  if (url.origin !== location.origin ||
      url.pathname.startsWith("/api/") ||
      url.pathname.startsWith("/overlays/")) return;
  // Navigation (le document "/") : network-first, repli sur le cache hors-ligne.
  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req)
        .then((r) => { const cp = r.clone(); caches.open(CACHE).then((c) => c.put("/", cp)); return r; })
        .catch(() => caches.match("/"))
    );
    return;
  }
  // Assets statiques same-origin : cache-first + mise à jour en arrière-plan.
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(
      caches.match(req).then((cached) =>
        cached || fetch(req).then((r) => {
          const cp = r.clone();
          caches.open(CACHE).then((c) => c.put(req, cp));
          return r;
        })
      )
    );
  }
});
