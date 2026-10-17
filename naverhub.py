"""네이버 API HUB(NAVER Cloud Platform) 연동: 생활정보의 통합 검색·검색어 추이·쇼핑 관심도.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다.
- 공식 문서(api.ncloud-docs.com, naver-api-hub-*) 기준. 호스트 https://naverapihub.apigw.ntruss.com,
  인증 헤더 X-NCP-APIGW-API-KEY-ID(Client ID)·X-NCP-APIGW-API-KEY(Client Secret).
  검색: GET /search/v1/{news,blog,cafearticle,kin}, 검색어 트렌드: POST /search-trend/v1/search,
  쇼핑인사이트: POST /shopping/v1/categories, /shopping/v1/category/{gender,age,device,keywords}.
- 키는 서버 환경변수 NAVER_HUB_CLIENT_ID·NAVER_HUB_CLIENT_SECRET에만 둔다. 화면(HTML·JS)에는 절대 내보내지 않고, 모든 호출은 서버에서 한다.
- 호출 한도: 검색은 하루 25,000번(문서), 트렌드·쇼핑은 달 50,000번 → 우리 쪽에서 하루 NAVER_HUB_DAILY_SEARCH(기본 20,000)·
  NAVER_HUB_DAILY_DATALAB(기본 1,500)까지만 부르고, 같은 요청은 잠깐 저장해 둔 결과(검색 30분·추이 12시간)를 다시 쓴다.
  방문자 한 명(IP)이 1분에 검색 20번을 넘으면 잠시 막는다.
- 검색 결과는 제목·요약·출처·원문 링크만 보여 주고 원문 링크로 보낸다. 결과는 위 시간만큼만 임시로 두고(만료 뒤 하루 안에 지움)
  따로 쌓거나 다시 퍼뜨리지 않는다. 화면에 '검색 결과 제공: NAVER'를 표시한다.
"""
import datetime
import email.utils
import hashlib
import html
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from urllib.parse import urlparse

from flask import abort, render_template, request, url_for
from markupsafe import Markup, escape

BASE = 'https://naverapihub.apigw.ntruss.com'
SEARCH = {'news': ('뉴스', '/search/v1/news'), 'blog': ('블로그', '/search/v1/blog'), 'cafe': ('카페', '/search/v1/cafearticle'), 'kin': ('지식iN', '/search/v1/kin')}
TTL = {'search': 1800, 'datalab': 43200}
STALE = 86400          # 만료 뒤에도 이만큼은 오류 때 대신 보여 줌, 그 뒤엔 지움
PER_MIN = 20           # 방문자 한 명이 1분에 할 수 있는 검색
# 쇼핑인사이트 1분류 (네이버쇼핑 cat_id)
SHOP_CATS = [('50000000', '패션의류'), ('50000001', '패션잡화'), ('50000002', '화장품/미용'), ('50000003', '디지털/가전'), ('50000004', '가구/인테리어'),
             ('50000005', '출산/육아'), ('50000006', '식품'), ('50000007', '스포츠/레저'), ('50000008', '생활/건강'), ('50000009', '여가/생활편의'), ('50005542', '도서')]
TREND_PRESET = ['환불', '택배 분실', '중고거래 사기', '구독 해지', '리콜']
AGES = [('10', '10대'), ('20', '20대'), ('30', '30대'), ('40', '40대'), ('50', '50대'), ('60', '60대 이상')]
COLORS = ['#ef7300', '#3182f6', '#00b386', '#8b5cf6', '#f04452']


class NaverError(Exception):
    """방문자에게 그대로 보여 줘도 되는 말 (키·내부 정보 없음)."""


def keys():
    return os.getenv('NAVER_HUB_CLIENT_ID', '').strip(), os.getenv('NAVER_HUB_CLIENT_SECRET', '').strip()


def ready(): return all(keys())


def caps(): return {'search': int(os.getenv('NAVER_HUB_DAILY_SEARCH') or 20000), 'datalab': int(os.getenv('NAVER_HUB_DAILY_DATALAB') or 1500)}


def http(method, url, headers, body, timeout):
    """(상태 코드, JSON). 테스트에서 바꿔 끼운다."""
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode() or '{}')
        except Exception: return e.code, {}


def clean(s):
    """네이버가 붙인 <b> 같은 태그·HTML 문자를 지운 글자."""
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', '', s or '')).split())


def item_date(kind, it):
    try:
        if kind == 'news': return email.utils.parsedate_to_datetime(it['pubDate']).strftime('%Y.%m.%d')
        if kind == 'blog' and len(it.get('postdate', '')) == 8: d = it['postdate']; return f'{d[:4]}.{d[4:6]}.{d[6:]}'
    except (KeyError, TypeError, ValueError): pass
    return ''


def item_source(kind, it):
    if kind == 'news':
        host = urlparse(it.get('originallink') or it.get('link') or '').netloc
        return re.sub(r'^(www|m|news)\.', '', host) or '뉴스'
    if kind == 'blog': return clean(it.get('bloggername')) or '블로그'
    if kind == 'cafe': return clean(it.get('cafename')) or '카페'
    return '지식iN'


def safe_url(u):
    return u if isinstance(u, str) and u.startswith(('https://', 'http://')) else ''


def periods(months):
    end = datetime.date.today() - datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=int(months * 30.4))
    unit = 'date' if months <= 1 else ('week' if months <= 6 else 'month')
    return start.isoformat(), end.isoformat(), unit


def change(data):
    """최근 몫 평균과 그 앞 같은 길이 평균을 견준 증감률(%). 비율 값이라 묶음마다 기준이 달라도 견줄 수 있음."""
    v = [d['ratio'] for d in data]
    n = max(1, len(v) // 4)
    if len(v) < 2 * n: return None
    a, b = sum(v[-2 * n:-n]) / n, sum(v[-n:]) / n
    return round((b - a) / a * 100) if a else None


def chart(series, w=640, h=220, axis=True):
    """[(이름, [(기간, 값)])] → 꺾은선 SVG (서버에서 그림, 자바스크립트 없음)."""
    pts = [p for _, s in series for p in s]
    if not pts: return Markup('')
    top = max(v for _, v in pts) or 1
    labels = [p for p, _ in max((s for _, s in series), key=len)]
    n = max(2, len(labels))
    px, py, pb = (8, 12, 26) if axis else (3, 4, 4)
    x = lambda i: px + (w - 2 * px) * i / (n - 1)
    y = lambda v: py + (h - py - pb) * (1 - v / top)
    out = [f'<svg class="nv-chart" viewBox="0 0 {w} {h}" role="img" aria-label="검색 추이 그래프" preserveAspectRatio="none">']
    for g in ((0, .5, 1) if axis else ()): out.append(f'<line x1="{px}" x2="{w - px}" y1="{y(top * g):.1f}" y2="{y(top * g):.1f}" class="nv-grid"/>')
    for k, (name, s) in enumerate(series):
        d = ' '.join(f'{"M" if i == 0 else "L"}{x(i):.1f},{y(v):.1f}' for i, (_, v) in enumerate(s))
        out.append(f'<path d="{d}" fill="none" stroke="{COLORS[k % len(COLORS)]}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"><title>{escape(name)}</title></path>')
    fmt = lambda p: p[2:].replace('-', '.')
    if not axis: return Markup(''.join(out) + '</svg>')
    out.append(f'<text x="{px}" y="{h - 6}" class="nv-ax">{escape(fmt(labels[0]))}</text><text x="{w - px}" y="{h - 6}" class="nv-ax" text-anchor="end">{escape(fmt(labels[-1]))}</text></svg>')
    return Markup(''.join(out))


def install(S):
    app = S.app; conn = S.conn
    hits = defaultdict(deque)
    with conn() as db:
        db.execute('CREATE TABLE IF NOT EXISTS naver_cache(key TEXT PRIMARY KEY,value TEXT NOT NULL,expires REAL NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS naver_usage(day TEXT NOT NULL,api TEXT NOT NULL,n INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(day,api))')

    def today(): return datetime.date.today().isoformat()

    def usage():
        with conn() as db:
            got = {r['api']: r['n'] for r in db.execute('SELECT api,n FROM naver_usage WHERE day=?', (today(),))}
        return {k: (got.get(k, 0), v) for k, v in caps().items()}

    def call(group, method, path, params=None, body=None):
        """같은 요청은 저장해 둔 결과를 다시 씀. 실패하면 NaverError(방문자용 문구)."""
        if not ready(): raise NaverError('아직 네이버 검색이 연결되지 않았어요.')
        key = hashlib.sha256(json.dumps([method, path, params, body], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        now = time.time()
        with conn() as db:
            row = db.execute('SELECT value,expires FROM naver_cache WHERE key=?', (key,)).fetchone()
            if row and row['expires'] > now: return json.loads(row['value'])
            if random.random() < .05: db.execute('DELETE FROM naver_cache WHERE expires<?', (now - STALE,))
            n = (db.execute('SELECT n FROM naver_usage WHERE day=? AND api=?', (today(), group)).fetchone() or [0])[0]
            if n >= caps()[group]:
                if row: return json.loads(row['value'])
                raise NaverError('오늘 쓸 수 있는 검색을 모두 썼어요. 내일 다시 찾아봐 주세요.')
            db.execute('INSERT INTO naver_usage(day,api,n) VALUES(?,?,1) ON CONFLICT(day,api) DO UPDATE SET n=n+1', (today(), group))
        cid, secret = keys()
        headers = {'X-NCP-APIGW-API-KEY-ID': cid, 'X-NCP-APIGW-API-KEY': secret}
        if body is not None: headers['Content-Type'] = 'application/json'
        url = BASE + path + ('?' + urllib.parse.urlencode(params) if params else '')
        try: st, res = http(method, url, headers, body, 10)
        except Exception as e:
            app.logger.warning('네이버 API 연결 실패 %s: %s', path, type(e).__name__); st, res = 0, {}
        if st == 200 and isinstance(res, dict):
            with conn() as db:
                db.execute('INSERT OR REPLACE INTO naver_cache(key,value,expires) VALUES(?,?,?)', (key, json.dumps(res, ensure_ascii=False), now + TTL[group]))
            return res
        code = str(res.get('errorCode') or (res.get('error') or {}).get('errorCode') or '') if isinstance(res, dict) else ''
        app.logger.warning('네이버 API 오류 %s: %s %s', path, st, code[:20])
        if row: return json.loads(row['value'])  # 조금 지난 결과라도 보여 줌
        if st in (401, 403): raise NaverError('네이버 검색 연결을 확인하고 있어요. 잠시 뒤 다시 찾아봐 주세요.')
        if st == 429: raise NaverError('찾는 분이 많아 잠시 쉬고 있어요. 조금 뒤 다시 찾아봐 주세요.')
        if st == 400: raise NaverError('검색어를 조금 바꿔서 다시 찾아봐 주세요.')
        raise NaverError('네이버 검색이 잠시 응답하지 않아요. 조금 뒤 다시 찾아봐 주세요.')

    def throttle():
        # 방문자가 직접 넣은 검색어만 막음 (기본 화면은 저장해 둔 결과라 괜찮음)
        q = hits[S.ip_hash()]; now = time.time()
        while q and q[0] < now - 60: q.popleft()
        if len(q) >= PER_MIN: raise NaverError('검색을 너무 자주 했어요. 1분 뒤 다시 찾아봐 주세요.')
        q.append(now)
        if len(hits) > 5000: hits.clear()

    def search(kind, q, start=1, display=10, sort='sim'):
        params = {'query': q, 'display': display, 'start': start}
        if kind == 'news': params['sort'] = sort if sort in ('sim', 'date') else 'sim'
        res = call('search', 'GET', SEARCH[kind][1], params=params)
        items = []
        for it in res.get('items') or []:
            url = safe_url(it.get('originallink') if kind == 'news' else None) or safe_url(it.get('link'))
            if not url: continue
            items.append({'title': clean(it.get('title')), 'summary': clean(it.get('description')), 'source': item_source(kind, it), 'date': item_date(kind, it), 'url': url})
        return {'total': min(int(res.get('total') or 0), 1000), 'items': items}

    def trend(words, months):
        start, end, unit = periods(months)
        body = {'startDate': start, 'endDate': end, 'timeUnit': unit, 'keywordGroups': [{'groupName': w, 'keywords': [w]} for w in words[:5]]}
        res = call('datalab', 'POST', '/search-trend/v1/search', body=body)
        return [(r.get('title', ''), [(d['period'], float(d['ratio'])) for d in r.get('data') or []]) for r in res.get('results') or []]

    def shop_overview(months):
        start, end, unit = periods(months)
        rows = []
        for i in range(0, len(SHOP_CATS), 3):
            part = SHOP_CATS[i:i + 3]
            res = call('datalab', 'POST', '/shopping/v1/categories', body={'startDate': start, 'endDate': end, 'timeUnit': unit,
                                                                          'category': [{'name': n, 'param': [c]} for c, n in part]})
            by = {r.get('title'): r.get('data') or [] for r in res.get('results') or []}
            for c, n in part:
                data = by.get(n, [])
                rows.append({'code': c, 'name': n, 'series': [(d['period'], float(d['ratio'])) for d in data], 'change': change(data)})
        return sorted(rows, key=lambda r: (r['change'] is None, -(r['change'] or 0)))

    def shop_split(code, what, months):
        # 성별·연령·기기 몫: 기간 전체 비율을 더해 백분율로
        start, end, unit = periods(months)
        res = call('datalab', 'POST', f'/shopping/v1/category/{what}', body={'startDate': start, 'endDate': end, 'timeUnit': unit, 'category': code})
        tot = defaultdict(float)
        for r in res.get('results') or []:
            for d in r.get('data') or []: tot[str(d.get('group'))] += float(d.get('ratio') or 0)
        s = sum(tot.values()) or 1
        return {k: round(v / s * 100) for k, v in tot.items()}

    def shop_keywords(code, words, months):
        start, end, unit = periods(months)
        body = {'startDate': start, 'endDate': end, 'timeUnit': unit, 'category': code, 'keyword': [{'name': w, 'param': [w]} for w in words[:5]]}
        res = call('datalab', 'POST', '/shopping/v1/category/keywords', body=body)
        return [(r.get('title', ''), [(d['period'], float(d['ratio'])) for d in r.get('data') or []]) for r in res.get('results') or []]

    def query_text(name='q', n=50):
        return ' '.join((request.args.get(name) or '').split())[:n]

    def words_arg():
        raw = request.args.getlist('k') or (request.args.get('ks') or '').split(',')
        out = []
        for w in raw:
            w = ' '.join(w.split())[:20]
            if w and w not in out: out.append(w)
        return out[:5]

    def months_arg():
        m = request.args.get('months', 3, type=int)
        return m if m in (1, 3, 12) else 3

    def own_life(q, n=3):
        like = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        with conn() as db:
            return db.execute("SELECT * FROM articles WHERE status='published' AND (title LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\') ORDER BY id DESC LIMIT ?", (like, like, n)).fetchall()

    def latest_news():
        """생활정보 첫 화면의 '요즘 소비자 뉴스' (키가 없거나 실패하면 빈 목록)."""
        if not ready(): return []
        try: return search('news', '소비자 피해', display=5, sort='date')['items']
        except NaverError: return []

    @app.route('/life/search')
    def life_search():
        q = query_text(); tab = request.args.get('tab') if request.args.get('tab') in SEARCH else 'all'
        page = min(max(1, request.args.get('page', 1, type=int)), 50); sort = 'date' if request.args.get('sort') == 'date' else 'sim'
        results, error, own, total = {}, '', [], 0
        if q:
            own = own_life(q) if tab == 'all' and page == 1 else []
            try:
                throttle()
                if tab == 'all':
                    for k in SEARCH: results[k] = search(k, q, display=4, sort=sort)
                else:
                    results[tab] = search(tab, q, start=(page - 1) * 10 + 1, display=10, sort=sort)
                    total = results[tab]['total']
            except NaverError as e: error = str(e)
        pages = min(100, max(1, -(-total // 10)))
        return render_template('life_search.html', q=q, tab=tab, page=page, pages=pages, sort=sort, results=results, own=own, error=error,
                               kinds=SEARCH, ready=ready(), nv_tab='search')

    @app.route('/life/trend')
    def life_trend():
        words = words_arg(); months = months_arg(); custom = bool(words)
        words = words or TREND_PRESET
        series, error = [], ''
        if ready():
            try:
                if custom: throttle()
                series = trend(words, months)
            except NaverError as e: error = str(e)
        rows = [{'name': n, 'color': COLORS[i % len(COLORS)], 'change': change([{'ratio': v} for _, v in s]), 'last': s[-1][1] if s else 0} for i, (n, s) in enumerate(series)]
        return render_template('life_trend.html', words=words, custom=custom, months=months, svg=chart(series), rows=rows, error=error, ready=ready(),
                               preset=TREND_PRESET, nv_tab='trend')

    @app.route('/life/shopping')
    def life_shopping():
        months = months_arg(); code = request.args.get('cat', '')
        cat = dict(SHOP_CATS).get(code)
        if code and not cat: abort(404)
        words = words_arg() if cat else []
        rows, detail, error = [], {}, ''
        if ready():
            try:
                if cat:
                    if words: throttle()
                    detail = {'gender': shop_split(code, 'gender', months), 'age': shop_split(code, 'age', months), 'device': shop_split(code, 'device', months)}
                    if words: detail['kw'] = shop_keywords(code, words, months); detail['svg'] = chart(detail['kw'])
                else: rows = shop_overview(months)
            except NaverError as e: error = str(e)
        return render_template('life_shopping.html', months=months, code=code, cat=cat, rows=rows, detail=detail, words=words, error=error, ready=ready(),
                               cats=SHOP_CATS, ages=AGES, chart=chart, colors=COLORS, nv_tab='shopping')

    app.jinja_env.globals.update(naver_ready=ready, naver_news=latest_news, naver_usage=usage)
    S.naver_search = search; S.naver_trend = trend; S.naver_ready = ready
    # AI 분석 기사(soboru_writer.py)가 같은 호출·저장·한도를 그대로 씀
    app.extensions['naverhub'] = {'ready': ready, 'search': search, 'trend': trend, 'shop_overview': shop_overview, 'shop_split': shop_split}
