/* Apitou! — service worker (base PWA pras lojas)
   Estratégia conservadora pra NUNCA servir dado velho:
   · shell (html) e dados.js: rede primeiro, cache só como fallback offline
   · imagens (escudos/fotos via proxy): cache primeiro (mudam raramente)  */
const CACHE = "apitou-v1";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;

  // escudos e fotos: cache-first
  if (url.pathname.startsWith("/media/") || url.pathname.startsWith("/smimg/") ||
      url.pathname.endsWith(".png") || url.pathname.endsWith(".svg")){
    e.respondWith(
      caches.open(CACHE).then(async c => {
        const hit = await c.match(e.request);
        if (hit) return hit;
        const resp = await fetch(e.request);
        if (resp.ok) c.put(e.request, resp.clone());
        return resp;
      })
    );
    return;
  }

  // shell + dados: network-first com fallback offline
  e.respondWith(
    fetch(e.request).then(resp => {
      if (resp.ok){
        const clone = resp.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
      }
      return resp;
    }).catch(() => caches.match(e.request, { ignoreSearch: true }))
  );
});
