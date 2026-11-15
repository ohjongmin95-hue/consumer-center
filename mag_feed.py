"""소보루 매거진(soboru.co.kr)에 소비자를위한신문(consumertimes.kr) 기사 자동 연동 (운영자 요청 2026-11-15).

- 신문 RSS(ND소프트 기본 주소 /rss/allArticle.xml)를 30분마다 읽어 새 기사를 매거진 기사 목록에 '게시 중'으로 넣음 (origin='newspaper').
  누가 매거진 화면을 열 때 서버가 뒤에서 알아서 가져옴(따로 타이머 X). 관리자 > 기사 목록 위 '신문 기사 지금 가져오기'로 바로 가져올 수도 있음.
- 매거진 첫 화면·목록에는 다른 기사처럼 카드로 보이고, 누르면 신문 원문 주소로 바로 감 (같은 글이 두 사이트에 있지 않게: 검색 중복 X).
  그래서 매거진 사이트맵·RSS·레터 매거진 칸에는 넣지 않음.
- 사진은 기사 화면의 og:image(신문 사진)를 그대로 씀. 분야는 제목·요약의 낱말로 고름(못 고르면 '생활').
- 매거진 자체 글은 지금처럼 관리자에서 쓰면 함께 섞여 최신순으로 보임.
- 서버 설정 NEWSPAPER_RSS로 주소를 바꿀 수 있음, NEWSPAPER_FEED=0이면 끔.
"""
import datetime, email.utils, html, os, re, threading, time, urllib.request
import xml.etree.ElementTree as ET

ORIGIN = 'newspaper'
NAME = '소비자를위한신문'
RSS = 'https://www.consumertimes.kr/rss/allArticle.xml'
EVERY = 30 * 60
UA = 'Mozilla/5.0 (compatible; SoboruMagazine/1.0; +https://soboru.co.kr)'
CATS = [('리콜', ('리콜', '회수', '판매 중단', '판매중단', '부적합')), ('금융', ('금융', '은행', '보험', '카드', '대출', '금리', '증권', '코인', '예금', '연금')),
        ('통신', ('통신', '요금제', '알뜰폰', 'SKT', 'KT', 'LG유플러스', '이동통신')), ('자동차', ('자동차', '차량', '전기차', '타이어', '중고차')),
        ('여행', ('여행', '항공', '호텔', '숙박', '패키지')), ('음식', ('식품', '음식', '외식', '배달', '프랜차이즈', '커피', '라면', '과자', '식당')),
        ('뷰티', ('화장품', '뷰티', '미용', '피부')), ('쇼핑', ('쇼핑', '이커머스', '쿠팡', '오픈마켓', '플랫폼', '직구', '할인', '유통', '편의점', '백화점', '마트'))]


def http(url, timeout=15):
    """(상태, 본문 bytes). 테스트에서 바꿔 끼운다."""
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, r.read(3_000_000)
    except Exception:
        return 0, b''


def clean(text, n=400):
    t = html.unescape(re.sub(r'<[^>]+>', ' ', text or ''))
    t = re.sub(r'\s+', ' ', t).strip()
    return t[:n].rstrip() + ('…' if len(t) > n else '')


def pick_cat(text):
    for cat, words in CATS:
        if any(w in text for w in words): return cat
    return '생활'


def when(raw):
    try: d = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError): d = None
    if not d:
        m = re.match(r'(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(:\d{2})?)', raw or '')
        return (m.group(1) + 'T' + (m.group(2) + ':00')[:8]) if m else datetime.datetime.now().isoformat(timespec='seconds')
    if d.tzinfo: d = d.astimezone(datetime.timezone(datetime.timedelta(hours=9))).replace(tzinfo=None)
    return d.isoformat(timespec='seconds')


def parse(xml):
    """RSS 2.0 → [{title, link, summary, image, at}]"""
    try: root = ET.fromstring(xml)
    except ET.ParseError: return []
    out = []
    for it in root.iter('item'):
        g = lambda tag: (it.findtext(tag) or '').strip()
        link, title = g('link'), clean(g('title'), 120)
        if not link.startswith(('http://', 'https://')) or not title: continue
        desc = g('description')
        img = ''
        enc = it.find('enclosure')
        if enc is not None and (enc.get('type') or '').startswith('image'): img = enc.get('url') or ''
        if not img:
            for el in it.iter():
                if el.tag.endswith('}content') or el.tag.endswith('}thumbnail'):
                    if el.get('url'): img = el.get('url'); break
        if not img:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)', html.unescape(desc))
            if m: img = m.group(1)
        out.append({'title': title, 'link': link, 'summary': clean(desc, 300), 'image': img, 'at': when(g('pubDate') or g('{http://purl.org/dc/elements/1.1/}date'))})
    return out


def og(page):
    """기사 화면에서 og:image·og:description"""
    t = page.decode('utf-8', 'replace') if isinstance(page, bytes) else (page or '')
    def meta(prop):
        m = re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*content=["\']([^"\']*)' % re.escape(prop), t) or \
            re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']%s["\']' % re.escape(prop), t)
        return html.unescape(m.group(1)).strip() if m else ''
    return meta('og:image'), meta('og:description')


def install(S):
    app, conn = S.app, S.conn
    from flask import request, redirect, flash, url_for, abort
    with conn() as db:
        db.execute('CREATE TABLE IF NOT EXISTS article_photo_url(article_id INTEGER PRIMARY KEY, url TEXT NOT NULL)')
    state = {'busy': False, 'last': 0.0}
    lock = threading.Lock()

    def on():
        return os.getenv('NEWSPAPER_FEED', '1') != '0'

    def pull():
        """새 기사만 넣고 넣은 수를 돌려줌"""
        code, body = http(os.getenv('NEWSPAPER_RSS', '').strip() or RSS)
        if code != 200 or not body: return 0
        items = parse(body)
        with conn() as db:
            have = {r[0] for r in db.execute("SELECT ext_key FROM articles WHERE origin=?", (ORIGIN,))}
        n = 0
        for it in sorted(items, key=lambda x: x['at']):
            key = 'ct:' + it['link']
            if key in have: continue
            img, desc = it['image'], it['summary']
            if not img or len(desc) < 40:
                c, page = http(it['link'], 10)
                if c == 200:
                    oi, od = og(page)
                    img = img or oi; desc = desc if len(desc) >= 40 else (clean(od, 300) or desc)
            with conn() as db:
                try:
                    cur = db.execute('INSERT INTO articles(title,summary,body,category,source_name,source_url,status,origin,ext_key,created,updated,published_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                                     (it['title'], desc, desc, pick_cat(it['title'] + ' ' + desc), NAME, it['link'], 'published', ORIGIN, key, it['at'], it['at'], it['at']))
                except Exception:
                    continue  # 같은 주소가 동시에 들어온 경우(ext_key 유일)
                if img.startswith(('http://', 'https://')): db.execute('INSERT OR REPLACE INTO article_photo_url(article_id,url) VALUES(?,?)', (cur.lastrowid, img))
            n += 1
        return n

    def kick(force=False):
        if not on(): return
        with lock:
            if state['busy'] or (not force and time.time() - state['last'] < EVERY): return
            state['busy'] = True; state['last'] = time.time()
        def run():
            try: pull()
            finally: state['busy'] = False
        if app.config.get('TESTING'): run()
        else: threading.Thread(target=run, daemon=True).start()

    @app.before_request
    def newspaper_feed_tick():
        # 매거진 화면(첫 화면·목록·기사)을 누가 열면 30분에 한 번 뒤에서 가져옴
        if request.method == 'GET' and S.letter_alone() and (request.path in ('/', '/life', '/letter') or request.path.startswith('/life')):
            kick()

    @app.before_request
    def newspaper_article_out():
        # 신문 기사 카드는 원문으로 (매거진 안에 같은 글을 두지 않음)
        m = re.fullmatch(r'/life/(\d+)', request.path)
        if not m or request.method != 'GET': return None
        with conn() as db:
            a = db.execute('SELECT origin,source_url FROM articles WHERE id=?', (int(m.group(1)),)).fetchone()
        if a and a['origin'] == ORIGIN and (a['source_url'] or '').startswith(('http://', 'https://')):
            with conn() as db: db.execute('UPDATE articles SET views=views+1 WHERE id=?', (int(m.group(1)),))
            return redirect(a['source_url'], 302)
        return None

    def photo_url(article_id):
        with conn() as db:
            r = db.execute('SELECT url FROM article_photo_url WHERE article_id=?', (article_id,)).fetchone()
        return r[0] if r else ''

    @app.route('/admin/life/newspaper', methods=['POST'])
    @S.admin_only
    def admin_life_newspaper():
        n = pull() if on() else 0
        state['last'] = time.time()
        flash(f'소비자를위한신문 새 기사 {n}개를 가져왔어요.' if n else '새로 올라온 신문 기사가 없어요.')
        return redirect(url_for('admin_life'))

    app.jinja_env.globals['newspaper_on'] = on
    S.newspaper_photo = photo_url
    app.extensions['mag_feed'] = {'pull': pull, 'kick': kick, 'photo': photo_url}
