// 网络优先：在线总是拿最新页面/样式/脚本，断网才用缓存兜底。
// （避免旧的「缓存优先」导致更新后还显示旧样式）
const CACHE = 'gongkao-v26';

self.addEventListener('install', e => { self.skipWaiting(); });

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;          // 写操作直接走网络
  if (url.pathname.startsWith('/api/')) return;     // API 直接走网络
  e.respondWith(
    fetch(e.request).then(resp => {
      if (resp && resp.ok && url.origin === location.origin) {
        const copy = resp.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {});
      }
      return resp;
    }).catch(() => caches.match(e.request).then(hit => hit || caches.match('index.html')))
  );
});
