// 소보루 서비스 워커 (/sw.js 주소로 나감, __VERSION__ 자리에 디자인 버전이 들어감)
// - 화면(HTML)은 늘 서버에서 새로 받고 기기에 저장하지 않아요. 인터넷이 끊기면 /offline 안내만 보여 줘요.
// - 기기에 저장하는 건 주소에 v= 가 붙은 /static 파일(글꼴·그림·CSS)뿐이에요. 버전이 바뀌면 예전 파일은 지워요.
// - 관리자·기자·기업·내 정보·제보 화면, POST 요청, 다른 사이트 파일은 손대지 않아요.
var VERSION = '__VERSION__';
var STATIC_CACHE = 'sb-static-' + VERSION;
var PAGE_CACHE = 'sb-offline-' + VERSION;
var OFFLINE_URL = '/offline';
var OFFLINE_FILES = [OFFLINE_URL, '/static/img/soboru-character-hero.png?v=' + VERSION];
var STATIC_MAX = 120;

self.addEventListener('install', function (event) {
  event.waitUntil(caches.open(PAGE_CACHE).then(function (cache) {
    return cache.addAll(OFFLINE_FILES.map(function (u) { return new Request(u, { credentials: 'omit' }); }));
  }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k.indexOf('sb-') === 0 && k !== STATIC_CACHE && k !== PAGE_CACHE; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

function trim(cache) {
  // 저장한 정적 파일이 너무 많아지면 오래된 것부터 지움
  return cache.keys().then(function (keys) {
    if (keys.length <= STATIC_MAX) return;
    return Promise.all(keys.slice(0, keys.length - STATIC_MAX).map(function (k) { return cache.delete(k); }));
  });
}

self.addEventListener('fetch', function (event) {
  var req = event.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  // 버전이 붙은 정적 파일: 저장해 둔 게 있으면 바로, 없으면 받아서 저장
  if (url.pathname.indexOf('/static/') === 0 && url.searchParams.has('v')) {
    event.respondWith(caches.match(req).then(function (hit) {
      return hit || fetch(req).then(function (res) {
        if (res.ok && res.type === 'basic') {
          var copy = res.clone();
          caches.open(STATIC_CACHE).then(function (cache) { return cache.put(req, copy).then(function () { return trim(cache); }); });
        }
        return res;
      });
    }));
    return;
  }
  // 화면 이동: 서버에서 받고(저장 안 함), 끊겼을 때만 오프라인 안내
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(function () {
      return caches.match(OFFLINE_URL).then(function (hit) { return hit || new Response('오프라인이에요. 인터넷 연결을 확인해 주세요.', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } }); });
    }));
  }
});

// 웹 푸시: 서버가 보낸 {title, body, url}을 알림으로 띄우고, 누르면 그 화면을 엶
self.addEventListener('push', function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || '소보루', {
    body: data.body || '새 알림이 있어요.', icon: '/static/soboru-app-192.png', badge: '/static/soboru-favicon.png', data: { url: data.url || '/me/alerts' }, lang: 'ko'
  }));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var target = new URL((event.notification.data && event.notification.data.url) || '/me/alerts', self.location.origin);
  if (target.origin !== self.location.origin) target = new URL('/me/alerts', self.location.origin);
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (list) {
    for (var i = 0; i < list.length; i++) { if ('focus' in list[i] && list[i].url.indexOf(self.location.origin) === 0) { list[i].navigate(target.href); return list[i].focus(); } }
    return self.clients.openWindow(target.href);
  }));
});
