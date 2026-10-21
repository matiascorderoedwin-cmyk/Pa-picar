/* Pa Picar PWA — sin almacenamiento offline de sesiones, ventas ni pedidos.
   Solo se guardan elementos públicos de diseño para acelerar su carga.
   Cualquier página o respuesta de Flask requiere conexión al servidor. */
const CACHE = 'pa-picar-assets-v1';
const PUBLIC_ASSETS = [
  '/static/logo-pa-picar.png',
  '/static/pa-picar-marca.css',
  '/static/pwa/register.js'
];
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PUBLIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key.startsWith('pa-picar-assets-') && key !== CACHE)
          .map((key) => caches.delete(key))
    )).then(() => self.clients.claim())
  );
});
self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET' || request.mode === 'navigate') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith('/static/')) return;
  event.respondWith(
    fetch(request).then((response) => {
      if (response.ok && response.type === 'basic') {
        const copy = response.clone();
        event.waitUntil(caches.open(CACHE).then((cache) => cache.put(request, copy)));
      }
      return response;
    }).catch(() => caches.match(request))
  );
});
