// Service worker minimal : rend l'application installable (Chrome/Android)
// et permet de rouvrir la page hors ligne. Les données (/api/…, data/…)
// passent toujours par le réseau — on ne met en cache que l'enveloppe.
const CACHE = "prix-pv-v1";
const SHELL = [
  "./",
  "index.html",
  "manifest.webmanifest",
  "icons/gc-logo.png",
  "icons/gc-energie.png",
  "icons/icon-192.png",
  "icons/icon-512.png",
  "icons/favicon-32.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
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
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.includes("/api/") || url.pathname.includes("/data/")) return;

  // Réseau d'abord (pour toujours servir la dernière version), cache en secours.
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req, { ignoreSearch: true }).then((r) => r || caches.match("index.html")))
  );
});
