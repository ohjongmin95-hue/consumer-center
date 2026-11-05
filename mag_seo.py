"""소보루 매거진 검색 노출 (운영자 2026-11-05: '매거진 검색 최적화 다 해줘').

soboru.co.kr 주소로 들어온 검색 로봇에게 매거진만의 정보를 준다.
- 첫 화면 제목·설명: 관리자 > 소보루 매거진 > 검색 노출에서 고침 (기본 'SOBORU 소보루 매거진')
- 사이트맵 soboru.co.kr/sitemap.xml: 첫 화면, 전체 기사, 분야별 목록, 기사, 지난 레터 (기사 사진 포함)
- RSS soboru.co.kr/rss.xml: 최신 기사 30개 (네이버 서치어드바이저 RSS 제출용)
- 네이버·구글 소유확인 코드: 소비자제보센터와 따로 (주소가 달라서 확인도 따로 받음)
구조화 데이터(Organization·WebSite·분야 메뉴)는 templates/mag_seo_head.html.
"""
import datetime
import json
import re
import urllib.parse
from xml.sax.saxutils import escape

from flask import Response, flash, redirect, render_template, request, url_for

DEFAULTS = {
    'title': 'SOBORU 소보루 매거진',
    'description': '소비를 보는 새로운 루트, 소보루 매거진. 쇼핑, 통신, 여행, 음식, 금융까지 사고, 쓰고, 고르는 매일의 소비를 소비자의 눈으로 보는 소비자 라이프스타일 매거진이에요.',
    'naver': '',
    'google': '',
}
SITE = 'https://soboru.co.kr'


def install(S):
    app, conn = S.app, S.conn
    from soboru import LIFE_CATEGORIES
    with conn() as db:
        db.execute('CREATE TABLE IF NOT EXISTS soboru_settings(key TEXT PRIMARY KEY, value TEXT)')

    def load():
        with conn() as db: row = db.execute("SELECT value FROM soboru_settings WHERE key='mag_seo'").fetchone()
        try: saved = json.loads(row[0]) if row else {}
        except ValueError: saved = {}
        return {k: (saved.get(k) or v) for k, v in DEFAULTS.items()}

    def mag_seo_text(key):
        return load().get(key, '')

    def mag_verification(key):
        return _code(load().get(key, ''))

    def published(limit=None):
        with conn() as db:
            return db.execute("SELECT id,title,summary,body,category,published_at,updated,created FROM articles WHERE status='published' ORDER BY published_at DESC, id DESC" + (' LIMIT %d' % limit if limit else '')).fetchall()

    def mag_categories():
        with conn() as db:
            have = {r[0] for r in db.execute("SELECT DISTINCT category FROM articles WHERE status='published'")}
        return [c for c in LIFE_CATEGORIES if c in have]

    EN = {'쇼핑': 'SHOPPING', '통신': 'MOBILE', '여행': 'TRAVEL', '음식': 'FOOD', '금융': 'MONEY', '자동차': 'CAR', '생활': 'LIVING', '뷰티': 'BEAUTY', '리콜': 'RECALL'}

    def mag_nav_ld():
        # 검색 결과 아래 바로가기 링크(사이트링크) 후보: 전체 기사 + 분야별 목록
        nav = [('전체 기사', SITE + '/life')] + [('%s %s' % (c, EN.get(c, '')), SITE + '/life?category=' + urllib.parse.quote(c)) for c in mag_categories()]
        return {'@context': 'https://schema.org', '@type': 'ItemList', 'name': '소보루 매거진 메뉴',
                'itemListElement': [{'@type': 'SiteNavigationElement', 'position': i + 1, 'name': n.strip(), 'url': u} for i, (n, u) in enumerate(nav)]}

    # 운영자 2026-11-05: 첫 화면 'Aisles'에 생활(LIVING)·금융(MONEY)까지 모든 분야를 보여 줌 (글이 아직 없는 분야도)
    MAG_ORDER = ['쇼핑', '뷰티', '음식', '생활', '금융', '통신', '여행', '자동차', '리콜']
    mag_aisles = [c for c in MAG_ORDER if c in LIFE_CATEGORIES] + [c for c in LIFE_CATEGORIES if c not in MAG_ORDER]
    app.jinja_env.globals.update(mag_aisles=mag_aisles, mag_seo_text=mag_seo_text, mag_verification=mag_verification, mag_categories=mag_categories, mag_nav_ld=mag_nav_ld)

    def day(ts):
        return (ts or '')[:10] or datetime.date.today().isoformat()

    def sitemap():
        rows = published()
        photo = app.jinja_env.globals.get('mag_photo')
        newest = day(rows[0]['updated'] or rows[0]['published_at']) if rows else datetime.date.today().isoformat()
        out = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">']

        def add(loc, mod=None, img=None):
            out.append('<url><loc>%s</loc>%s%s</url>' % (escape(loc), '<lastmod>%s</lastmod>' % mod if mod else '',
                       '<image:image><image:loc>%s</image:loc></image:image>' % escape(img) if img else ''))
        add(SITE + '/', newest)
        add(SITE + '/life', newest)
        for c in mag_categories(): add(SITE + '/life?category=' + urllib.parse.quote(c))
        for r in rows:
            img = ''
            if photo:
                try: img = photo(r['id'], 1200) or ''
                except Exception: img = ''
            if img.startswith('/'): img = SITE + img
            add('%s/life/%d' % (SITE, r['id']), day(r['updated'] or r['published_at']), img)
        try:
            with conn() as db: letters = db.execute("SELECT no,sent_at FROM letters WHERE status='sent' ORDER BY no DESC LIMIT 500").fetchall()
        except Exception: letters = []
        for L in letters: add('%s/letter/%d' % (SITE, L['no']), day(L['sent_at']))
        out.append('</urlset>')
        return Response('\n'.join(out) + '\n', mimetype='application/xml')

    def rss():
        def date(ts):
            try: return datetime.datetime.fromisoformat((ts or '')[:19]).strftime('%a, %d %b %Y %H:%M:%S +0900')
            except ValueError: return ''
        cfg = load()
        items = []
        for r in published(30):
            link = '%s/life/%d' % (SITE, r['id'])
            desc = (r['summary'] or '').strip() or (r['body'] or '')[:200]
            items.append('<item><title>%s</title><link>%s</link><guid isPermaLink="true">%s</guid><category>%s</category><description>%s</description><pubDate>%s</pubDate></item>'
                         % (escape(r['title']), link, link, escape(r['category'] or ''), escape(desc), date(r['published_at'] or r['created'])))
        body = ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>%s</title><link>%s/</link><description>%s</description><language>ko</language>%s</channel></rss>\n'
                % (escape(cfg['title']), SITE, escape(cfg['description']), ''.join(items)))
        return Response(body, mimetype='application/rss+xml')

    @app.before_request
    def mag_seo_files():
        if request.path not in ('/', '/sitemap.xml', '/rss.xml') or not S.letter_host(request.host.split(':')[0].lower()): return None
        if request.path == '/': return app.view_functions['letter_home']()  # 매거진 첫 화면 대표 주소 = soboru.co.kr/
        return sitemap() if request.path == '/sitemap.xml' else rss()

    @app.route('/admin/magazine/seo', methods=['GET', 'POST'])
    @S.admin_only
    def mag_seo_admin():
        if request.method == 'POST':
            cfg = {k: request.form.get(k, '').strip()[:300] for k in DEFAULTS}
            with conn() as db: db.execute('INSERT OR REPLACE INTO soboru_settings(key,value) VALUES(?,?)', ('mag_seo', json.dumps(cfg, ensure_ascii=False)))
            flash('검색 노출 설정을 저장했어요.')
            return redirect(url_for('mag_seo_admin'))
        with conn() as db: n = db.execute("SELECT COUNT(*) FROM articles WHERE status='published'").fetchone()[0]
        return render_template('mag_admin_seo.html', cfg=load(), defaults=DEFAULTS, cats=mag_categories(), n=n, site=SITE)


def _code(value):
    # 코드만 넣어도, 검색엔진이 준 <meta ...> 줄을 통째로 붙여도 content 값만 씀
    found = re.search(r'content=["\']([^"\']+)', value or '')
    return (found.group(1) if found else (value or '')).strip()
