/* Registrar Service Worker cuando el navegador lo permite.
   No guardamos información de clientes o facturas sin conexión. */
if ('serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', {scope: '/'})
      .catch((error) => console.info('PWA no disponible en este navegador:', error));
  });
}
