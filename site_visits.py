"""방문 통계 (운영자 요청 2026-11-01): 소보루(soboru.co.kr)와 소비자고발제보센터(consumerjebo.co.kr)를 나눠, 날마다 방문자 · 들어온 곳 · 많이 본 화면.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다.
- 방문자: 광고 효과(ad_events)와 같은 무작위 쿠키 번호의 해시로만 구분(IP·개인정보 없음). 한 사람은 사이트마다 하루에 한 번.
- 들어온 곳: 그날 처음 들어올 때의 utm_source, 없으면 앞 화면 주소(Referer)의 도메인으로 네이버·구글·카카오… 로 나눔. 소보루 앱은 '소보루 앱'.
- 화면: 글 번호 같은 숫자는 *로 묶어 셈(/reports/12 → /reports/*). HTML 화면(200)만, 관리자·검색 봇은 세지 않음.
- 기록은 400일이 지나면 지움.
"""
import datetime, re, secrets, urllib.parse
from flask import flash, g, redirect, render_template, request, session, url_for

KEEP_DAYS = 400
SITES = {'soboru': '소보루', 'jebo': '소비자고발제보센터'}
BOT = re.compile(r'bot|crawl|spider|slurp|yeti|daum(?!apps)|preview|externalhit|headless|python|curl|wget|lighthouse', re.I)
# (Referer 도메인에 들어 있으면, 이름) — 위에서부터 먼저 맞는 것
REFERRERS = [
    ('search.naver.com', '네이버 검색'), ('blog.naver.com', '네이버 블로그'), ('cafe.naver.com', '네이버 카페'), ('naver.com', '네이버'), ('naver.me', '네이버'),
    ('google.', '구글'), ('daum.net', '다음'), ('kakao.com', '카카오'), ('kakao.co', '카카오'), ('bing.com', '빙'), ('zum.com', '줌'),
    ('instagram.com', '인스타그램'), ('facebook.com', '페이스북'), ('fb.me', '페이스북'), ('threads.', '스레드'), ('youtube.com', '유튜브'), ('youtu.be', '유튜브'),
    ('t.co', 'X(트위터)'), ('x.com', 'X(트위터)'), ('twitter.com', 'X(트위터)'), ('chatgpt.com', 'ChatGPT'), ('perplexity.ai', '퍼플렉시티'),
]
# 화면 주소 앞부분 → 이름 (많이 본 화면 표). 긴 것부터 맞춤
PAGES = [
    ('/', '홈'), ('/reports/*', '제보 글'), ('/reports', '제보 목록'), ('/report', '제보하기'), ('/companies', '기업 답변'), ('/company', '기업 페이지'),
    ('/board/*', '커뮤니티 글'), ('/board', '커뮤니티 전체 글'), ('/feed', '내돈내산 후기'), ('/vs', '골라주세요'), ('/suda', '수다방'), ('/owners', '사장님 소식'),
    ('/life/*', '매거진 글'), ('/life', '매거진'), ('/letter', '소보루 레터'), ('/scam', '사기 주의'), ('/town', '우리 동네'), ('/jobs', '동네일자리'),
    ('/ask', 'AI 소비자 상담'), ('/tools', '계산기·사전·법령'), ('/search', '검색'), ('/login', '로그인'), ('/signup', '회원가입'), ('/me', 'MY'),
    ('/lookup', '내 제보 조회'), ('/u/*', '이웃 페이지'), ('/faq', '자주 묻는 질문'), ('/guide', '이용 안내'), ('/process', '처리 절차'),
]


def migrate(db):
    db.execute("CREATE TABLE IF NOT EXISTS site_visits(day TEXT NOT NULL,site TEXT NOT NULL,visitor_hash TEXT NOT NULL,source TEXT NOT NULL DEFAULT '',PRIMARY KEY(day,site,visitor_hash))")
    db.execute('CREATE TABLE IF NOT EXISTS page_views(day TEXT NOT NULL,site TEXT NOT NULL,page TEXT NOT NULL,n INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(day,site,page))')


def page_key(path):
    """/reports/12 → /reports/*, 길이는 80자까지."""
    # 숫자가 든 칸(글 번호 등)과 긴 칸(기업 답변 링크의 비밀 토큰 등)은 *로: 토큰이 통계에 남지 않게
    parts = [('*' if re.search(r'\d', p) or len(p) >= 16 else p) for p in (path or '/').split('/')]
    return ('/'.join(parts).rstrip('/') or '/')[:80]


def page_name(key):
    """화면 이름: 같은 주소 → 글 번호 묶음(/reports/*) → 그 아래 화면(/reports/…) 순서로 찾음."""
    for prefix, name in PAGES:
        if key == prefix: return name
    for prefix, name in PAGES:
        if prefix.endswith('/*') and key.startswith(prefix[:-1]): return name
    for prefix, name in PAGES:
        if prefix != '/' and not prefix.endswith('*') and key.startswith(prefix + '/'): return name
    return ''


def source_of(referrer, own_hosts, ua='', utm=''):
    if utm: return utm[:40]
    if 'SoboruApp/' in ua: return '소보루 앱'
    if 'KAKAOTALK' in ua: return '카카오톡'
    if 'Instagram' in ua: return '인스타그램'
    host = (urllib.parse.urlsplit(referrer or '').hostname or '').lower()
    if not host: return '직접·즐겨찾기'
    if host in own_hosts: return '사이트 안'
    for part, name in REFERRERS:
        if part in host: return name
    return host.removeprefix('www.')[:40]


def install(S):
    app = S.app; conn = S.conn
    with conn() as db: migrate(db)
    own = set(S.LIVE_HOSTS) | set(S.JEBO_HOSTS)

    with conn() as db: db.execute('CREATE TABLE IF NOT EXISTS soboru_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')

    def skip_ips():
        # 운영자 2026-11-04: 관리자가 들어가도 세지 않게. 관리자에서 등록한 IP(사무실·집)는 로그인 안 해도 세지 않음
        with conn() as db: row = db.execute("SELECT value FROM soboru_settings WHERE key='visit_skip_ips'").fetchone()
        return {x.strip() for x in (row[0] if row else '').split() if x.strip()}

    def site_now():
        return 'jebo' if S.current_face() == 'jebo' else 'soboru'

    @app.after_request
    def count_visit(resp):
        try:
            if session.get('admin'):
                # 관리자로 한 번 로그인한 기기는 로그아웃해도 1년 동안 세지 않음
                if request.cookies.get('sv_off') != '1': resp.set_cookie('sv_off', '1', max_age=365 * 86400, httponly=True, samesite='Lax', secure=request.is_secure)
                return resp
            if request.cookies.get('sv_off') == '1' or (request.remote_addr or '') in skip_ips(): return resp
            if (request.method != 'GET' or resp.status_code != 200 or resp.mimetype != 'text/html' or request.endpoint in (None, 'static')
                    or request.path.startswith(('/admin', '/staff', '/reporter', '/biz', '/hook', '/api')) or session.get('admin')
                    or BOT.search(request.headers.get('User-Agent', ''))):
                return resp
            site = site_now(); day = S.today_str()
            with conn() as db:
                db.execute('INSERT INTO page_views(day,site,page,n) VALUES(?,?,?,1) ON CONFLICT(day,site,page) DO UPDATE SET n=n+1', (day, site, page_key(request.path)))
                vh = S.ad_visitor()
                if vh and session.get('sv_' + site) != day:
                    session['sv_' + site] = day
                    src = source_of(request.referrer, own, request.headers.get('User-Agent', ''), S.ad_clean(request.args.get('utm_source')))
                    if db.execute('INSERT OR IGNORE INTO site_visits(day,site,visitor_hash,source) VALUES(?,?,?,?)', (day, site, vh, src)).rowcount and secrets.randbelow(200) == 0:
                        old = (datetime.date.today() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
                        db.execute('DELETE FROM site_visits WHERE day<?', (old,)); db.execute('DELETE FROM page_views WHERE day<?', (old,))
        except Exception:
            app.logger.exception('visit count failed')  # 통계 때문에 화면이 깨지면 안 됨
        return resp

    @app.route('/admin/visits', methods=['GET', 'POST'])
    @S.admin_only
    def admin_visits():
        if request.method == 'POST':
            ips = ' '.join(x for x in (request.form.get('ips') or '').replace(',', ' ').split() if re.fullmatch(r'[0-9a-fA-F:.]{3,45}', x))
            with conn() as db: db.execute("INSERT OR REPLACE INTO soboru_settings(key,value) VALUES('visit_skip_ips',?)", (ips,))
            flash('저장했어요.'); return redirect(url_for('admin_visits'))
        site = 'jebo'  # 운영자 2026-11-03: '소보루는 이제 없다' → 소비자고발제보센터만 셈
        today = datetime.date.today()
        d = lambda n: (today - datetime.timedelta(days=n)).isoformat()
        where, args = ('AND site=?', (site,)) if site else ('', ())
        with conn() as db:
            def uniq(since, until=None):
                q = f'SELECT COUNT(DISTINCT visitor_hash) FROM site_visits WHERE day>=? AND day<=? {where}'
                return db.execute(q, (since, until or d(0), *args)).fetchone()[0]
            def views(since, until=None):
                return db.execute(f'SELECT COALESCE(SUM(n),0) FROM page_views WHERE day>=? AND day<=? {where}', (since, until or d(0), *args)).fetchone()[0]
            kpi = [('오늘', uniq(d(0)), views(d(0))), ('어제', uniq(d(1), d(1)), views(d(1), d(1))), ('최근 7일', uniq(d(6)), views(d(6))), ('최근 30일', uniq(d(29)), views(d(29)))]
            by_day = {}
            for r in db.execute('SELECT day,site,COUNT(*) AS n FROM site_visits WHERE day>=? GROUP BY day,site', (d(29),)):
                by_day.setdefault(r['day'], dict.fromkeys(SITES, 0))[r['site']] = r['n']
            daily = [{'day': d(i), **by_day.get(d(i), dict.fromkeys(SITES, 0))} for i in range(29, -1, -1)]
            for row in daily: row['all'] = sum(row[k] for k in SITES)
            first = next((i for i, row in enumerate(daily) if row['jebo']), len(daily) - 7)
            daily = daily[min(first, len(daily) - 7):]  # 기록이 생기기 전 날짜는 보여 주지 않음 (최소 7일)
            sources = db.execute(f'SELECT source,COUNT(*) AS n FROM site_visits WHERE day>=? {where} GROUP BY source ORDER BY n DESC LIMIT 20', (d(29), *args)).fetchall()
            pages = db.execute(f'SELECT page,SUM(n) AS n FROM page_views WHERE day>=? {where} GROUP BY page ORDER BY n DESC LIMIT 20', (d(29), *args)).fetchall()
            split = {k: db.execute('SELECT COUNT(DISTINCT visitor_hash) FROM site_visits WHERE day>=? AND site=?', (d(29), k)).fetchone()[0] for k in SITES}
        top = max([r[site] if site else r['all'] for r in daily] + [1])
        src_total = sum(r['n'] for r in sources) or 1
        return render_template('admin_visits.html', site=site, sites=SITES, kpi=kpi, daily=daily, top=top, sources=sources, src_total=src_total,
                               pages=[{'page': r['page'], 'name': page_name(r['page']), 'n': r['n']} for r in pages], split=split,
                               skip='\n'.join(sorted(skip_ips())), my_ip=request.remote_addr or '')
