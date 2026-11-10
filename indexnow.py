# IndexNow: 제보를 사이트에 게시하면 네이버·빙에 "새 글 생겼어요"를 바로 알려 검색에 빨리 실리게 함 (운영자 2026-11-10)
# 키는 INDEXNOW_KEY 환경 변수, 없으면 SECRET_KEY에서 만든 고정 값. 키 파일은 /<키>.txt 로 보여 줌 (app.py)
import hashlib, json, os, threading, urllib.parse, urllib.request

ENDPOINTS = ('https://searchadvisor.naver.com/indexnow', 'https://api.indexnow.org/indexnow')


def key():
    k = os.getenv('INDEXNOW_KEY', '').strip()
    if k:
        return k
    secret = os.getenv('SECRET_KEY', '')
    return hashlib.sha256(('indexnow:' + secret).encode()).hexdigest()[:32] if secret else ''


def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
    with urllib.request.urlopen(req, timeout=8) as r:
        return r.status


def ping(urls, background=True):
    """운영 주소(https)만 알림. 실패해도 게시에는 영향 없음."""
    urls = [u for u in urls if u.startswith('https://')]
    k = key()
    if not urls or not k or os.getenv('INDEXNOW_OFF') == '1':
        return []
    host = urllib.parse.urlsplit(urls[0]).netloc
    payload = {'host': host, 'key': k, 'keyLocation': f'https://{host}/{k}.txt', 'urlList': urls[:100]}

    def run():
        out = []
        for ep in ENDPOINTS:
            try:
                out.append((ep, post(ep, payload)))
            except Exception as e:  # noqa: BLE001 - 알림 실패는 조용히
                out.append((ep, str(e)[:80]))
        return out
    if background:
        threading.Thread(target=run, daemon=True).start()
        return []
    return run()
