// Minimal service worker — enables PWA install prompt.
// No caching: all requests pass through to the network normally.
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });
