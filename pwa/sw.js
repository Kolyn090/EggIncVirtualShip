// App assets only. Plans and checklist progress are a single IndexedDB record;
// app-shell updates never replace, migrate, or delete that active plan.
const CACHE = 'egginc-mission-shell-ffc6f4c4beaa0517';
const ASSETS = ['./', './index.html', './app.css', './app.mjs', './plan.mjs', './store.mjs',
  './frame.mjs', './checklist.mjs', './dashboard-template.mjs', './manifest.webmanifest', './icon.svg'];
const urls = ASSETS.map(path => new URL(path, self.registration.scope).href);
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(urls.map(url => new Request(url, {cache: 'reload'}))))
    .then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('egginc-mission-shell-') && key !== CACHE)
    .map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || new URL(event.request.url).origin !== self.location.origin) return;
  if (event.request.mode === 'navigate') {
    event.respondWith(caches.open(CACHE).then(cache => cache.match(new URL('./index.html', self.registration.scope).href))
      .then(cached => cached || fetch(event.request)));
  } else if (urls.includes(event.request.url)) {
    event.respondWith(caches.open(CACHE).then(cache => cache.match(event.request)).then(cached => cached || fetch(event.request)));
  }
});
