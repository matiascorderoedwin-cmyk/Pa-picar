/* Pa Picar PWA — sin almacenamiento offline de sesiones, ventas ni pedidos.
   Solo se guardan elementos públicos de diseño para acelerar su carga.
   Cualquier página o respuesta de Flask requiere conexión al servidor. */
const CACHE = 'pa-picar-assets-v2';
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


/* Web Push: mostrar siempre un aviso visible, requisito de iOS/WebKit. */
self.addEventListener('push', event => {
  let datos = {};
  try { datos = event.data ? event.data.json() : {}; } catch (_) { datos = {}; }
  const titulo = String(datos.title || 'Pa Picar').slice(0,95);
  const mensaje = String(datos.body || 'Tienes un aviso nuevo.').slice(0,250);
  const destino = String(datos.url || '/');
  event.waitUntil(self.registration.showNotification(titulo,{
    body:mensaje,
    icon:'/app-icon/192.png',
    badge:'/app-icon/192.png',
    tag:'pa-picar-aviso-'+Date.now(),
    data:{url:destino}
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const destino=new URL(event.notification.data?.url||'/',self.location.origin);
  if (destino.origin!==self.location.origin) return;
  event.waitUntil((async () => {
    const existentes=await self.clients.matchAll({type:'window',includeUncontrolled:true});
    const ventana=existentes.find(c=>c.url.startsWith(self.location.origin));
    if (ventana) {
      if ('navigate' in ventana) await ventana.navigate(destino.href);
      return ventana.focus();
    }
    return self.clients.openWindow(destino.href);
  })());
});
