"""소보루 통합 검색 (운영자 요청 2026-10-24): 머리글 돋보기를 누르면 그 자리에서 검색창이 열리고,
/search?q= 한 화면에서 제보 · 기업 · 커뮤니티 글 · 매거진 · 동네일자리 · 소비자·경제 사전을 같이 찾는다.

- 공개 승인된 제보(public_consent=1, published=1)만, 제목은 jebo.pub()로 가린 공개 제목을 보여 준다.
- 커뮤니티 글은 숨김(hidden=0)이 아닌 것만, 매거진은 게시된 글만.
- 일자리는 soboru_jobs의 search()를, 사전은 soboru_tools.DICT를 그대로 쓴다. 기업은 이름·브랜드·상호·다른 이름에서 찾는다.
"""
import re
from markupsafe import Markup, escape
from werkzeug.datastructures import MultiDict
from flask import render_template, request

import jebo

SECTIONS = [('report', '소비자 제보', '📣'), ('company', '기업', '🏢'), ('post', '커뮤니티', '💬'), ('life', '매거진', '📰'), ('town', '우리 동네 정보', '📍'), ('job', '동네일자리', '💼'), ('dict', '소비자·경제 사전', '📚')]
POPULAR = ['환불', '헬스장', '택배 분실', '청약철회', '구독 해지', '중고거래']


def like(q):
    return '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def snippet(text, q, n=70):
    """찾은 낱말 둘레만 잘라 보여 줌"""
    t = ' '.join((text or '').split())
    i = t.find(q)
    if i < 0 or len(t) <= n: return t[:n] + ('…' if len(t) > n else '')
    a = max(0, i - n // 3)
    return ('…' if a else '') + t[a:a + n] + ('…' if a + n < len(t) else '')


def hl(text, q):
    """찾은 낱말에 형광펜 (글자는 먼저 escape)"""
    s = str(escape(text or ''))
    if not q: return Markup(s)
    return Markup(re.sub(re.escape(str(escape(q))), lambda m: '<mark>' + m.group(0) + '</mark>', s))


def install(S):
    app, conn = S.app, S.conn
    app.jinja_env.globals.update(SEARCH_POPULAR=POPULAR)
    app.jinja_env.filters['hl'] = hl

    # 사이트맵에 새로 생긴 소보루 화면(커뮤니티·골라주세요·수다방·사장님 소식·우리 동네·동네일자리·계산기·사전·법령)을 더함 (2026-10-28 SEO 점검)
    if 'sitemap_xml' in app.view_functions:
        old_map = app.view_functions['sitemap_xml']

        def sitemap_xml():
            resp = old_map()
            from flask import url_for
            eps = [e for e in ('feed', 'vs_home', 'suda', 'owners', 'town', 'jobs', 'tools', 'calc_home', 'dictionary', 'law_find') if e in app.view_functions]
            pages = [(url_for(e), None) for e in eps]
            if 'calc' in app.view_functions:
                import soboru_tools
                pages += [(url_for('calc', slug=c['slug']), None) for c in soboru_tools.CALCS]
            with conn() as db:
                if 'vs_post' in app.view_functions:
                    pages += [(url_for('vs_post', poll_id=r['id']), r['created'][:10]) for r in db.execute('SELECT id,created FROM vs_polls WHERE hidden=0 ORDER BY id DESC LIMIT 2000')]
                if 'town_place' in app.view_functions:
                    pages += [(url_for('town_place', place_id=r['id']), r['created'][:10]) for r in db.execute('SELECT id,created FROM town_places WHERE hidden=0 ORDER BY id DESC LIMIT 5000')]
                if 'job' in app.view_functions:  # 마감·숨김 공고는 빼기
                    pages += [(url_for('job', job_id=r['id']), r['updated'][:10]) for r in db.execute("SELECT id,updated FROM jobs WHERE status='open' AND hidden=0 ORDER BY id DESC LIMIT 5000")]
            base = S.canonical_url('')
            extra = ''.join('<url><loc>%s</loc>%s</url>' % (escape(base + u), '<lastmod>%s</lastmod>' % d if d else '')
                            for u, d in pages if S.own_page(base + u))
            resp.set_data(resp.get_data(as_text=True).replace('</urlset>', extra + '</urlset>'))
            return resp
        app.view_functions['sitemap_xml'] = sitemap_xml

    # AI 검색(ChatGPT·Perplexity·Claude 등)이 사이트를 한눈에 알아보게 /llms.txt (2026-10-28 AI 검색 친화)
    @app.route('/llms.txt')
    def llms_txt():
        from flask import url_for
        base = S.canonical_url('')
        g_ = S.g
        lines = [f"# {g_.content.get('site.name', '') or '소보루'}", '', f"> {g_.content.get('seo.description', '')}", '',
                 '소보루는 소비자가 겪은 피해를 제보하고, 직접 돈 내고 산 물건·다녀온 곳의 후기를 나누고, 환불·해지·계약 같은 소비자 권리를 쉽게 풀어 주는 한국어 소비자 정보 플랫폼이에요. '
                 '제보는 개인정보를 가린 뒤 공개 동의한 것만 보여 주고, 기업 답변이 오면 함께 실어요.', '', '## 주요 화면', '']
        main = [('reports', '소비자 제보 목록', '소비자가 직접 올린 피해 제보와 기업 답변'), ('life', '매거진', '환불·해지·리콜 등 알아 두면 돈 버는 소비 생활 기사'),
                ('feed', '내돈내산 후기', '직접 산 물건·다녀온 장소의 후기'), ('companies', '기업 정보', '기업별 제보 현황과 공식 답변'),
                ('law_ask', 'AI 소비자 상담', '소비자 피해 질문에 법령·분쟁해결기준을 근거로 답변'), ('tools', '계산기', '헬스장·학원 환불, 청약철회 기한, 할부 이자 계산'),
                ('dictionary', '소비자·경제 사전', '청약철회·위약금·DSR 같은 말 풀이'), ('law_find', '법령 찾기', '소비자 관련 법령 조문 찾기'),
                ('town', '우리 동네 정보', '이웃이 추천하는 동네 병원·시장·맛집'), ('jobs', '동네일자리', '동네 사장님이 올린 알바·일자리'),
                ('vs_home', '골라주세요', '살까 말까 소비 고민 투표'), ('guide', '이용 안내', None), ('faq', '자주 묻는 질문', None)]
        for ep, name, desc in main:
            if ep in ('guide', 'faq'): u = url_for('info_page', page=ep)
            elif ep in app.view_functions: u = url_for(ep)
            else: continue
            if S.own_page(base + u): lines.append(f'- [{name}]({base + u})' + (f': {desc}' if desc else ''))
        with conn() as db:
            arts = db.execute("SELECT id,title,summary FROM articles WHERE status='published' ORDER BY id DESC LIMIT 30").fetchall() if 'life_article' in app.view_functions else []
        if arts:
            lines += ['', '## 최근 매거진 기사', '']
            for a in arts:
                u = base + url_for('life_article', article_id=a['id'])
                if S.own_page(u): lines.append(f"- [{a['title']}]({u})" + (': ' + ' · '.join(x.strip() for x in a['summary'].splitlines() if x.strip())[:160] if a['summary'] else ''))
        lines += ['', '## 더 보기', '', f'- [사이트맵]({base}/sitemap.xml)', f'- [RSS]({base}/rss.xml)', '']
        return app.response_class('\n'.join(lines), mimetype='text/plain; charset=utf-8')

    def find(q, only=''):
        per = 20 if only else 5
        out = {k: [] for k, n, e in SECTIONS}
        lk = like(q)
        with conn() as db:
            if only in ('', 'report'):
                for r in db.execute("""SELECT * FROM cases WHERE public_consent=1 AND published=1 AND (public_subject LIKE ? ESCAPE '\\' OR (public_subject='' AND subject LIKE ? ESCAPE '\\')
                        OR company LIKE ? ESCAPE '\\') ORDER BY id DESC LIMIT ?""", (lk, lk, lk, per)):
                    t = jebo.pub(r, S.mask_personal)
                    out['report'].append({'href': f'/reports/{r["id"]}', 'title': t['subject'], 'sub': S.mask_personal(r['company']), 'text': snippet(t['body'], q), 'tag': jebo.cat_label(r['category'])})
            if only in ('', 'company'):
                for c in db.execute("""SELECT co.*,(SELECT COUNT(*) FROM cases c WHERE c.company_id=co.id AND c.public_consent=1 AND c.published=1) AS n_public FROM companies co
                        WHERE co.status IN ('active','listed') AND (co.name LIKE ? ESCAPE '\\' OR co.brand LIKE ? ESCAPE '\\' OR co.biz_name LIKE ? ESCAPE '\\' OR co.aliases LIKE ? ESCAPE '\\')
                        ORDER BY n_public DESC,co.name LIMIT ?""", (lk, lk, lk, lk, per)):
                    out['company'].append({'href': f'/companies/{c["id"]}', 'title': c['name'], 'sub': ' · '.join(x for x in (c['brand'], c['biz_name']) if x and x != c['name']),
                                           'text': f"공개 제보 {c['n_public']}건", 'tag': '입점 기업' if c['status'] == 'active' else ''})
            if only in ('', 'post'):
                for r in db.execute("SELECT id,kind,category,title,body,created,likes,comments FROM posts WHERE hidden=0 AND (title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\') ORDER BY id DESC LIMIT ?", (lk, lk, per)):
                    kind = {'review': '내돈내산 후기', 'suda': '수다방', 'question': '질문', 'tip': '꿀팁'}.get(r['kind'], r['category'])
                    out['post'].append({'href': f'/board/{r["id"]}', 'title': r['title'], 'sub': f"공감 {r['likes']} · 댓글 {r['comments']}", 'text': snippet(S.mask_personal(r['body']), q), 'tag': kind})
            if only in ('', 'life'):
                for r in db.execute("SELECT id,title,summary,body,category,emoji FROM articles WHERE status='published' AND (title LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\') ORDER BY published_at DESC LIMIT ?", (lk, lk, lk, per)):
                    out['life'].append({'href': f'/life/{r["id"]}', 'title': r['title'], 'sub': '', 'text': snippet(r['summary'] or re.sub(r'[#*>\[\]]', '', r['body']), q), 'tag': r['category']})
        if only in ('', 'job') and 'soboru_jobs' in app.extensions:
            rows, total, f = app.extensions['soboru_jobs']['search'](MultiDict({'q': q}), 1, per)
            for j in rows:
                out['job'].append({'href': f'/jobs/{j["id"]}', 'title': j['title'], 'sub': f"{j['company']} · {j['place']}", 'text': j['pay_label'], 'tag': j['source']})
        if only in ('', 'town') and 'soboru_town' in app.extensions:
            for p in app.extensions['soboru_town']['search'](q, per):
                out['town'].append({'href': f'/town/{p["id"]}', 'title': p['name'], 'sub': f"{p['sido']} {p['area']}", 'text': snippet(p['tip'], q), 'tag': p['cat']})
        if only in ('', 'dict'):
            try:
                import soboru_tools
                words = [w for w in soboru_tools.DICT if q in w[0] or q in w[2]][:per]
            except ImportError: words = []
            for word, cat, mean in words:
                out['dict'].append({'href': '/tools/dict?q=' + word, 'title': word, 'sub': '', 'text': snippet(mean, q, 90), 'tag': cat})
        return out

    @app.route('/search')
    def site_search():
        q = ' '.join(request.args.get('q', '').split())[:40]
        only = request.args.get('t', ''); only = only if only in dict((k, 1) for k, n, e in SECTIONS) else ''
        res = find(q, only) if q else {k: [] for k, n, e in SECTIONS}
        total = sum(len(v) for v in res.values())
        return render_template('soboru_search.html', q=q, only=only, res=res, total=total, sections=SECTIONS,
                               more={'report': '/reports?q=', 'company': '/companies?q=', 'post': '/board?q=', 'job': '/jobs?q=', 'dict': '/tools/dict?q='})

    app.extensions['soboru_search'] = {'find': find}
