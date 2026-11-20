// 4S CRM shell service worker — caches ONLY the tiny app shell so the branded
// splash / offline screen opens without a connection. CRM data is never cached:
// the dashboard itself always loads live from Streamlit.
// CACHE is stamped per deploy by .github/workflows/deploy-crm-web-app.yaml.
const CACHE = 'crm-shell-dev';
const SHELL = ['./', 'index.html', 'manifest.webmanifest', 'logo.png', 'icon-192.png', 'favicon-32.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Network-first for same-origin shell files (always fresh when online),
// falling back to the cache when offline. version.json is never cached.
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.endsWith('/version.json')) return;
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match('index.html')))
  );
});
