const C = "signaly-v5";
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {       // síť má přednost, cache jen jako záloha offline; cizí API (Binance, Yahoo…) se nechají prohlížeči
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;
  const key = u.origin + u.pathname;
  e.respondWith(fetch(e.request).then(r => { if (r.ok) { const k = r.clone(); caches.open(C).then(c => c.put(key, k)); } return r; })
    .catch(() => caches.match(key)));
});
