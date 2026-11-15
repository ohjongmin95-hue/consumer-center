"""소보루 매거진(soboru.co.kr)에 소비자를위한신문(consumertimes.kr) 기사 자동 연동 (운영자 요청 2026-11-15).

- 신문 RSS(ND소프트 기본 주소 /rss/allArticle.xml)를 30분마다 읽어 새 기사를 매거진 기사 목록에 '게시 중'으로 넣음 (origin='newspaper').
  누가 매거진 화면을 열 때 서버가 뒤에서 알아서 가져옴(따로 타이머 X). 관리자 > 기사 목록 위 '신문 기사 지금 가져오기'로 바로 가져올 수도 있음.
- 매거진 첫 화면·목록에는 다른 기사처럼 카드로 보이고, 누르면 매거진 안에서 기사 화면으로 열림 (운영자 2026-11-15, 본문은 신문 기사 화면에서 꺼냄).
  기사 아래 출처에 원문 링크, 대표 주소(canonical)는 신문 원문이라 검색 중복 X. 매거진 사이트맵·RSS·레터 매거진 칸에는 넣지 않음.
- 사진은 기사 화면의 og:image(신문 사진)를 그대로 씀. 분야는 제목·요약의 낱말로 고름(못 고르면 '생활').
- 매거진 자체 글은 지금처럼 관리자에서 쓰면 함께 섞여 최신순으로 보임.
- 서버 설정 NEWSPAPER_RSS로 주소를 바꿀 수 있음, NEWSPAPER_FEED=0이면 끔.
"""
import datetime, email.utils, html, json, os, re, threading, time, urllib.request
import xml.etree.ElementTree as ET
import io

ORIGIN = 'newspaper'
NAME = '소비자를위한신문'
RSS = 'https://www.consumertimes.kr/rss/allArticle.xml'
EVERY = 30 * 60
UA = 'Mozilla/5.0 (compatible; SoboruMagazine/1.0; +https://soboru.co.kr)'
# 분야 고르기 (운영자 2026-11-15: '피트니스가 무슨 푸드야'): 제목 낱말은 3점, 요약 낱말은 1점. 가장 높은 분야, 2점이 안 되면 '생활'
CATS = {
    '리콜': ('리콜', '회수 명령', '회수명령', '판매 중단', '판매중단', '부적합 판정', '부적합', '결함'),
    '금융': ('금융', '은행', '보험', '카드사', '신용카드', '대출', '금리', '증권', '코인', '가상자산', '예금', '적금', '연금', '저축', '이자', '보이스피싱'),
    '통신': ('통신사', '이동통신', '요금제', '알뜰폰', 'SKT', 'SK텔레콤', 'KT', 'LG유플러스', '유심', '휴대폰', '스마트폰', '인터넷 요금', '단말기'),
    '자동차': ('자동차', '차량', '전기차', '타이어', '중고차', '렌터카', '완성차', '주유'),
    '여행': ('여행', '항공', '항공권', '호텔', '숙박', '패키지', '여행사', '리조트', '펜션', '면세'),
    '음식': ('식품', '음식', '외식', '배달앱', '배달 음식', '프랜차이즈 치킨', '커피', '라면', '과자', '식당', '맛집', '음료', '주류', '식재료', '도시락', '빵'),
    '뷰티': ('화장품', '뷰티', '미용실', '피부과', '성형', '헤어', '향수', '네일'),
    '쇼핑': ('쇼핑', '이커머스', '쿠팡', '오픈마켓', '온라인몰', '직구', '할인', '유통', '편의점', '백화점', '대형마트', '홈쇼핑', '택배', '반품', '환불'),
    '생활': ('피트니스', '헬스장', '헬스', '필라테스', '요가', '회원권', '학원', '이사', '세탁', '가전', '렌탈', '정수기', '부동산', '전세', '월세', '관리비', '공연', '예식', '상조', '병원', '약국'),
}


CAT_HELP = {'쇼핑': '온라인몰·이커머스·유통·편의점·백화점·택배·반품·환불 등 물건 사기', '통신': '이동통신·요금제·알뜰폰·인터넷·휴대폰', '여행': '항공·숙박·여행상품·면세',
            '음식': '식품·외식·배달음식·음료·식당 (먹고 마시는 것만)', '뷰티': '화장품·미용·피부·헤어', '금융': '은행·카드·보험·대출·투자·결제·금융사기',
            '자동차': '자동차·중고차·렌터카·정비·주유', '생활': '헬스·피트니스·학원·가전·렌탈·주거·관리비·공연·병원 등 그 밖의 생활 서비스', '리콜': '제품 회수·리콜·판매중단·안전 부적합'}


def ai_cat(post_json, title, text):
    """싼 AI(OPENAI_MODEL, 기본 gpt-4.1-mini)가 제목과 본문 앞부분을 읽고 분야를 고름. 키가 없거나 실패하면 None (운영자 2026-11-15: '알아서 읽고 자동으로 잘 해야지')"""
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if not key: return None
    guide = '\n'.join(f'- {k}: {v}' for k, v in CAT_HELP.items())
    plain = re.sub(r'\[사진[^\]]*\]', '', text or '')[:900]
    body = {'model': os.getenv('OPENAI_MODEL', '').strip() or 'gpt-4.1-mini', 'temperature': 0, 'max_tokens': 30, 'response_format': {'type': 'json_object'},
            'messages': [{'role': 'system', 'content': '소비자 매거진 기사의 분야를 하나만 고른다. 기사가 실제로 다루는 업종·상품 기준으로 고르고, 글에 스친 낱말에 끌려가지 않는다. 분야:\n' + guide + '\nJSON {"category": "분야"}로만 답한다.'},
                         {'role': 'user', 'content': '제목: ' + title + '\n본문: ' + plain}]}
    try:
        st, res = post_json('https://api.openai.com/v1/chat/completions', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, 20)
        cat = json.loads(res['choices'][0]['message']['content']).get('category', '').strip() if st == 200 else ''
    except Exception:
        return None
    return cat if cat in CAT_HELP else None


def pick_cat(title, summary=''):
    score = {}
    for cat, words in CATS.items():
        n = sum(3 for w in words if w in title) + sum(1 for w in words if w in summary)
        if n: score[cat] = n
    if not score: return '생활'
    cat, n = max(score.items(), key=lambda kv: (kv[1], kv[0] == '생활'))
    return cat if n >= 2 else '생활'


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


def article_body(page, base='https://www.consumertimes.kr', skip_img=''):
    """신문 기사 화면(ND소프트)에서 본문만 꺼내 매거진 본문 글로: 문단은 빈 줄, 소제목은 ## , 사진은 [사진 주소 | 설명].
    운영자 2026-11-15: 카드를 누르면 원문으로 넘기지 말고 매거진 안에서 기사 화면으로. 못 찾으면 None"""
    t = page.decode('utf-8', 'replace') if isinstance(page, bytes) else (page or '')
    m = re.search(r'<(article|div)[^>]+id=["\']article-view-content-div["\'][^>]*>(.*?)</\1>', t, re.S)
    if not m: return None
    raw = re.sub(r'<(script|style|iframe|ins)[^>]*>.*?</\1>', ' ', m.group(2), flags=re.S | re.I)
    out = []
    def src_of(tag):
        mm = re.search(r'\s(?:data-src|src)=["\']([^"\']+)', tag)
        if not mm: return ''
        u = html.unescape(mm.group(1)).strip()
        if u.startswith('//'): u = 'https:' + u
        elif u.startswith('/'): u = base + u
        return u if u.startswith(('http://', 'https://')) else ''
    for tok in re.finditer(r'<figure[^>]*>.*?</figure>|<img[^>]*>|<h[1-6][^>]*>.*?</h[1-6]>|<p[^>]*>.*?</p>|<div[^>]*>(?:(?!<div).)*?</div>', raw, re.S | re.I):
        x = tok.group(0); low = x[:8].lower()
        if low.startswith(('<figure', '<img')):
            u = src_of(x if low.startswith('<img') else (re.search(r'<img[^>]*>', x, re.I) or tok).group(0))
            if not u or (skip_img and u.split('?')[0] == skip_img.split('?')[0]): continue
            cap = clean((re.search(r'<figcaption[^>]*>(.*?)</figcaption>', x, re.S | re.I) or [None, ''])[1], 120).replace('|', '·').replace(']', ')')
            out.append('[사진 %s%s]' % (u, ' | ' + cap if cap else ''))
            continue
        imgs = re.findall(r'<img[^>]*>', x, re.I)
        for im in imgs:
            u = src_of(im)
            if u and not (skip_img and u.split('?')[0] == skip_img.split('?')[0]): out.append('[사진 %s]' % u)
        text = clean(x, 5000)
        if not text: continue
        if re.search(r'저작권자|무단\s*전재|재배포\s*금지|기자\s*\S*@|ⓒ|©', text) and len(text) < 160: continue
        if low.startswith('<h') or (re.fullmatch(r'<p[^>]*>\s*<(?:b|strong)[^>]*>.*?</(?:b|strong)>\s*</p>', x, re.S | re.I) and len(text) <= 50):
            out.append('## ' + text.lstrip('#■▶◆●○△▲□- ').strip())
        else:
            out.append(text)
    body = '\n\n'.join(dict.fromkeys(out))  # 같은 줄 두 번 X
    return body if len(re.sub(r'\[사진[^\]]*\]', '', body)) >= 80 else None


def focus(data):
    """사진에서 세로 카드로 자를 때 가운데 둘 곳(가로 %, 세로 %). 운영자 2026-11-15: '이상하게 자르면 안 예뻐 보이니까'
    얼굴·사람(피부색)과 글자·물건 경계가 많은 곳을 찾아 그쪽을 남김. 읽지 못하면 None(가운데)."""
    try:
        from PIL import Image, ImageFilter
        im = Image.open(io.BytesIO(data)).convert('RGB')
    except Exception:
        return None
    w, h = im.size
    if not w or not h: return None
    small = im.resize((96, max(1, round(96 * h / w))))
    sw, sh = small.size
    edge = list(small.convert('L').filter(ImageFilter.FIND_EDGES).getdata())
    edge = [0 if (i % sw in (0, sw - 1) or i // sw in (0, sh - 1)) else e for i, e in enumerate(edge)]  # 필터가 테두리에 만드는 가짜 경계는 뺌
    skin = [1 if (77 <= cb <= 127 and 133 <= cr <= 173 and y > 60) else 0 for y, cb, cr in small.convert('YCbCr').getdata()]
    wt = [e + 90 * k for e, k in zip(edge, skin)]  # 사람 얼굴·피부를 크게 쳐 줌
    col = [sum(wt[y * sw + x] for y in range(sh)) for x in range(sw)]
    row = [sum(wt[y * sw:(y + 1) * sw]) for y in range(sh)]
    def best(line, win):
        win = max(1, min(len(line), win)); n = len(line) - win
        if n <= 0: return 50
        sums, run = [], sum(line[:win])
        for i in range(n + 1):
            if i: run += line[i + win - 1] - line[i - 1]
            sums.append(run)
        # 고르게 바쁜 사진(진열대 등)은 끝으로 치우치지 않게 가운데 쪽에 가산점
        at = max(range(n + 1), key=lambda i: (sums[i] * (1 - 0.3 * abs(2 * i / n - 1)), -abs(2 * i / n - 1)))
        return round(100 * at / n)  # object-position %: 0=왼쪽 끝, 100=오른쪽 끝
    card = 0.8  # 매거진 카드 가로:세로 4:5
    x = best(col, round(sh * card)) if sw / sh > card else 50
    y = best(row, round(sw / card)) if sw / sh < card else 40
    return max(0, min(100, x)), max(0, min(100, y))


def install(S):
    app, conn = S.app, S.conn
    from flask import request, redirect, flash, url_for, abort
    with conn() as db:
        db.execute('CREATE TABLE IF NOT EXISTS article_photo_url(article_id INTEGER PRIMARY KEY, url TEXT NOT NULL)')
        if 'pos' not in {r[1] for r in db.execute('PRAGMA table_info(article_photo_url)')}:
            db.execute("ALTER TABLE article_photo_url ADD COLUMN pos TEXT NOT NULL DEFAULT ''")
    def recat():
        # 운영자 2026-11-15: 분야 고르기를 고친 뒤, 이미 들어온 신문 기사 중 관리자가 손대지 않은 것(updated=created)은 AI로 다시 고름 (한 번만, 뒤에서)
        with conn() as db:
            if db.execute("SELECT 1 FROM soboru_settings WHERE key='newspaper_cat_v2'").fetchone(): return
            db.execute("INSERT OR REPLACE INTO soboru_settings(key,value) VALUES('newspaper_cat_v2','1')")
            rows = db.execute("SELECT id,title,summary,body FROM articles WHERE origin=? AND updated=created", (ORIGIN,)).fetchall()
        for r in rows:
            cat = ai_cat(S.companydesk.post_json, r['title'], r['body'] or r['summary']) or pick_cat(r['title'], r['summary'] or '')
            with conn() as db: db.execute('UPDATE articles SET category=? WHERE id=?', (cat, r['id']))
    if app.config.get('TESTING'): recat()
    else: threading.Thread(target=recat, daemon=True).start()
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
            img, desc, full = it['image'], it['summary'], None
            c, page = http(it['link'], 10)
            if c == 200:
                oi, od = og(page)
                img = img or oi; desc = desc if len(desc) >= 40 else (clean(od, 300) or desc)
                full = article_body(page, skip_img=img)
            with conn() as db:
                try:
                    cur = db.execute('INSERT INTO articles(title,summary,body,category,source_name,source_url,status,origin,ext_key,created,updated,published_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                                     (it['title'], desc, full or desc, ai_cat(S.companydesk.post_json, it['title'], full or desc) or pick_cat(it['title'], desc), NAME, it['link'], 'published', ORIGIN, key, it['at'], it['at'], it['at']))
                except Exception:
                    continue  # 같은 주소가 동시에 들어온 경우(ext_key 유일)
                if img.startswith(('http://', 'https://')):
                    c2, data = http(img, 10)
                    f = focus(data) if c2 == 200 and data else None
                    pos = '%d,%d' % f if f else ''
                    db.execute('INSERT OR REPLACE INTO article_photo_url(article_id,url,pos) VALUES(?,?,?)', (cur.lastrowid, img, pos))
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
    def newspaper_article_fill():
        # 운영자 2026-11-15: 신문 기사도 매거진 안에서 기사 화면으로 (원문 링크는 아래 출처). 본문을 아직 못 받은 기사(예전에 들어온 것)는 열 때 받아 채움
        m = re.fullmatch(r'/life/(\d+)', request.path)
        if not m or request.method != 'GET': return None
        aid = int(m.group(1))
        with conn() as db:
            a = db.execute('SELECT origin,source_url,body,summary FROM articles WHERE id=?', (aid,)).fetchone()
        if not a or a['origin'] != ORIGIN or not (a['source_url'] or '').startswith(('http://', 'https://')) or a['body'] != a['summary']: return None
        c, page = http(a['source_url'], 10)
        full = article_body(page, skip_img=photo_url(aid).split('#')[0]) if c == 200 else None
        if full:
            with conn() as db: db.execute('UPDATE articles SET body=? WHERE id=?', (full, aid))
        return None

    def photo_url(article_id):
        with conn() as db:
            r = db.execute('SELECT url,pos FROM article_photo_url WHERE article_id=?', (article_id,)).fetchone()
        if not r: return ''
        return r[0] + ('#fp=' + r[1] if r[1] else '')  # 자를 곳은 주소 뒤 #fp=가로,세로 → base.html이 object-position으로

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
