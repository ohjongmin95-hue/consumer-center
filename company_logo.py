"""기업 로고 (운영자 요청 2026-10-29: 유명 기업은 로고를 자동으로).
기업에 공식 홈페이지 주소(도메인)가 있으면 그 사이트의 아이콘(apple-touch-icon → 사이트 아이콘)을 한 번 받아
128px PNG로 저장해 두고(/co/<id>/logo.png) 기업 이름 옆에 보여 준다. 못 받으면 이름 첫 글자 동그라미.
도메인은 data/companies_seed.csv(큰 기업)와 관리자 > 기업 화면에서 넣는다. 도메인을 비우면 로고도 지운다.
"""
import io, ipaddress, re, socket, threading, time, urllib.parse, urllib.request
from html.parser import HTMLParser

DOMAIN_RE = re.compile(r'^(?=.{4,100}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$')
UA = 'Mozilla/5.0 (compatible; SoboruBot/1.0; +https://soboru.co.kr)'
MAX_BYTES = 1_000_000
SIZE = 128
RETRY_DAYS = 7


def clean_domain(text):
    """'https://www.Coupang.com/np' → 'coupang.com'. 이상하면 ''."""
    t = (text or '').strip().lower()
    if not t: return ''
    host = urllib.parse.urlsplit(t if '//' in t else '//' + t).hostname or ''
    host = host[4:] if host.startswith('www.') else host
    return host if DOMAIN_RE.match(host) else ''


def public_host(host):
    try:
        for info in socket.getaddrinfo(host, 443):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast: return False
        return True
    except Exception:
        return False


def get(url, limit=MAX_BYTES):
    host = urllib.parse.urlsplit(url).hostname or ''
    if not url.startswith('https://') or not public_host(host): return b''
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=6) as r:
        return r.read(limit + 1)[:limit + 1]


class Icons(HTMLParser):
    def __init__(self):
        super().__init__(); self.found = []

    def handle_starttag(self, tag, attrs):
        if tag != 'link': return
        a = dict(attrs); rel = (a.get('rel') or '').lower()
        if 'icon' in rel and a.get('href'):
            m = re.search(r'(\d+)x\d+', a.get('sizes') or '')
            self.found.append(((2 if 'apple' in rel else 1), int(m.group(1)) if m else 0, a['href']))


def to_png(data):
    from PIL import Image
    if not data or len(data) > MAX_BYTES: return b''
    try:
        im = Image.open(io.BytesIO(data))
        if getattr(im, 'n_frames', 1) > 1 and im.format == 'ICO':  # .ico 안에서 가장 큰 그림
            im = max((im.ico.getimage(s) for s in im.ico.sizes()), key=lambda x: x.size[0])
        im = im.convert('RGBA')
    except Exception:
        return b''
    if min(im.size) < 32: return b''  # 너무 작은 아이콘은 흐려 보여서 안 씀
    im.thumbnail((SIZE, SIZE))
    out = io.BytesIO(); im.save(out, 'PNG'); return out.getvalue()


def fetch(domain):
    """도메인의 로고 PNG (못 찾으면 b'')."""
    base = 'https://' + domain
    tries = []
    for home in (base + '/', 'https://www.' + domain + '/'):
        try:
            html = get(home, 400_000).decode('utf-8', 'replace')
            p = Icons(); p.feed(html)
            tries += [urllib.parse.urljoin(home, h) for _, _, h in sorted(p.found, reverse=True)]
            break
        except Exception:
            continue
    tries += [base + '/apple-touch-icon.png', 'https://www.' + domain + '/apple-touch-icon.png',
              'https://www.google.com/s2/favicons?' + urllib.parse.urlencode({'domain': domain, 'sz': SIZE})]
    for url in dict.fromkeys(tries):
        if url.startswith('data:'): continue
        try:
            png = to_png(get(url))
            if png: return png
        except Exception:
            continue
    return b''


def install(S):
    app, conn = S.app, S.conn
    folder = S.UPLOAD / 'logos'; folder.mkdir(parents=True, exist_ok=True)
    with conn() as db:
        cols = {r['name'] for r in db.execute('PRAGMA table_info(companies)')}
        for c in ('domain', 'logo', 'logo_at'):
            if c not in cols: db.execute(f"ALTER TABLE companies ADD COLUMN {c} TEXT NOT NULL DEFAULT ''")

    def save_logo(cid, domain):
        png = fetch(domain) if domain else b''
        name = f'{cid}.png' if png else ''
        if png: (folder / name).write_bytes(png)
        with conn() as db:
            db.execute('UPDATE companies SET logo=?,logo_at=? WHERE id=? AND domain=?', (name, S.now(), cid, domain))
        return bool(png)

    def refresh(limit=60):
        """도메인은 있는데 로고가 없는 기업 (실패한 곳은 7일 뒤 다시)."""
        since = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(time.time() - RETRY_DAYS * 86400))
        with conn() as db:
            rows = db.execute("SELECT id,domain FROM companies WHERE domain!='' AND logo='' AND (logo_at='' OR logo_at<?) LIMIT ?", (since, limit)).fetchall()
        return sum(save_logo(r['id'], r['domain']) for r in rows)

    def set_domain(db, cid, text):
        """관리자가 고친 도메인 저장. 바뀌면 로고를 지우고 다시 받음."""
        d = clean_domain(text)
        old = db.execute('SELECT domain,logo FROM companies WHERE id=?', (cid,)).fetchone()
        if old and old['domain'] != d:
            if old['logo']: (folder / old['logo']).unlink(missing_ok=True)
            db.execute("UPDATE companies SET domain=?,logo='',logo_at='' WHERE id=?", (d, cid))
            if d and not app.config.get('TESTING'): threading.Thread(target=lambda: time.sleep(1) or save_logo(cid, d), daemon=True).start()
        return d

    @app.route('/co/<int:cid>/logo.png')
    def company_logo(cid):
        from flask import abort, send_file
        with conn() as db: r = db.execute('SELECT logo FROM companies WHERE id=?', (cid,)).fetchone()
        if not r or not r['logo'] or not (folder / r['logo']).is_file(): abort(404)
        return send_file(folder / r['logo'], mimetype='image/png', max_age=86400)

    def co_logo(co):
        """기업 행(또는 dict) → 로고 주소. 없으면 ''."""
        try: return f"/co/{co['id']}/logo.png?v={(co['logo_at'] or '')[:10]}" if co['logo'] else ''
        except (KeyError, IndexError, TypeError): return ''

    app.jinja_env.globals.update(co_logo=co_logo)
    S.company_logo_refresh, S.company_set_domain, S.co_logo = refresh, set_domain, co_logo
    if not app.config.get('TESTING') and __import__('os').getenv('SOBORU_LOGO_FETCH', '1') != '0':  # 배포 뒤 남은 로고를 천천히 받아 둠 (사이트 뜨는 것과 따로)
        threading.Thread(target=lambda: time.sleep(20) or refresh(), daemon=True).start()
