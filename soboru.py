"""소보루 브랜드: 설정 하나로 이름·로고·메인 화면을 소보루로 바꾸기, 생활정보(매거진), 이달의 기업 답변 순위.

- 관리자 > 숨은 문구·설정 > '브랜드'에 소보루라고 적으면 사이트 이름·로고·메인 화면·메일 머리말이 소보루로 바뀜.
  비우면 지금 그대로 소비자제보센터. 주소·데이터는 그대로라 언제든 오갈 수 있음.
- 관리자는 바꾸기 전에 아무 주소 뒤에 ?brand=soboru 를 붙여 미리 볼 수 있음 (?brand=off 로 끔). 방문자에게는 안 보임.
- 생활정보(/life): 운영자가 쓰거나, 나중에 공공데이터 자동 수집이 초안으로 넣는 글. 게시한 글만 보임.
"""
import datetime, re, statistics
from flask import abort, flash, g, has_request_context, redirect, render_template, request, session, url_for
from markupsafe import Markup, escape

OLD_NAME = '소비자제보센터'
NEW_NAME = '소보루'
BRAND_VALUES = {'소보루', 'soboru', 'SOBORU'}
# 소보루로 바꿀 때 덮어쓰는 문구 (관리자가 적어 둔 값보다 앞섬)
SOBORU_TEXT = {
    'site.name': NEW_NAME,
    'seo.home_title': '소보루 - 소비자 생활정보·커뮤니티·제보',
    'seo.description': '알아 두면 돈 버는 소비자 생활정보, 소비자끼리 나누는 경험, 억울한 일 제보까지. 기업 답변과 해결 과정을 한곳에서 확인하세요.',
    'site.logo_accent': '', 'site.logo_rest': NEW_NAME, 'site.logo_by': '',
}
LIFE_CATEGORIES = ['쇼핑', '통신', '여행', '음식', '금융', '자동차', '생활', '리콜']
LIFE_TONES = ['t1', 't2', 't3', 't4', 't5', 't6']  # 대표 그림 바탕색
LIFE_PAGE = 12
RANK_DAYS = 30


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS articles(id INTEGER PRIMARY KEY,title TEXT NOT NULL,summary TEXT NOT NULL DEFAULT '',body TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT '생활',emoji TEXT NOT NULL DEFAULT '',tone TEXT NOT NULL DEFAULT 't1',source_name TEXT NOT NULL DEFAULT '',source_url TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'draft',origin TEXT NOT NULL DEFAULT 'manual',ext_key TEXT,featured INTEGER NOT NULL DEFAULT 0,views INTEGER NOT NULL DEFAULT 0,
        created TEXT NOT NULL,updated TEXT NOT NULL,published_at TEXT)''')
    # 공공데이터 자동 수집이 같은 항목을 두 번 넣지 않게
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS articles_ext_key ON articles(ext_key) WHERE ext_key IS NOT NULL')


def ago_text(stamp):
    try:
        s = (datetime.datetime.now() - datetime.datetime.fromisoformat(stamp[:19])).total_seconds()
    except (TypeError, ValueError):
        return ''
    if s < 3600: return f'{max(1, int(s // 60))}분 전'
    if s < 86400: return f'{int(s // 3600)}시간 전'
    if s < 86400 * 2: return '어제'
    if s < 86400 * 7: return f'{int(s // 86400)}일 전'
    if s < 86400 * 31: return f'{int(s // (86400 * 7))}주 전'
    return stamp[:10].replace('-', '.')


def install(S):
    app = S.app; conn = S.conn; notify = S.notify; jebo = S.jebo; now = S.now
    with conn() as db: migrate(db)

    # ---- 브랜드 ---------------------------------------------------------
    def saved_brand(value):
        return 'soboru' if (value or '').strip() in BRAND_VALUES else 'jebo'

    def brand():
        if has_request_context() and 'brand' in g: return g.brand
        with conn() as db:
            row = db.execute("SELECT value FROM site_content WHERE key='site.brand'").fetchone()
        return saved_brand(row[0] if row else '')

    def is_soboru(): return brand() == 'soboru'

    @app.before_request
    def apply_brand():
        if request.endpoint == 'static' or 'content' not in g: return
        pick = request.args.get('brand')
        if pick in ('soboru', 'off') and S.admin_active():
            if pick == 'soboru': session['brand_preview'] = 'soboru'
            else: session.pop('brand_preview', None)
        g.brand = 'soboru' if session.get('brand_preview') == 'soboru' and S.admin_active() else saved_brand(g.content.get('site.brand'))
        g.brand_preview = g.brand == 'soboru' and saved_brand(g.content.get('site.brand')) != 'soboru'
        if g.brand == 'soboru':
            for k, v in g.content.items():
                if OLD_NAME in v: g.content[k] = v.replace(OLD_NAME, NEW_NAME)
            g.content.update(SOBORU_TEXT)

    def site_name():
        """메일·알림·AI 초안에 쓰는 사이트 이름 (요청 밖에서도 DB 설정을 읽음)."""
        if has_request_context() and 'content' in g: return g.content.get('site.name') or OLD_NAME
        with conn() as db:
            rows = {r[0]: r[1] for r in db.execute("SELECT key,value FROM site_content WHERE key IN ('site.brand','site.name')")}
        if saved_brand(rows.get('site.brand')) == 'soboru': return NEW_NAME
        return rows.get('site.name') or OLD_NAME
    notify.site_name = site_name

    def branded(value):
        # 템플릿에 적힌 기본 문구 속 이름도 지금 브랜드로 (Markup은 Markup 그대로)
        return value.replace(OLD_NAME, site_name()) if is_soboru() and value else value
    app.jinja_env.filters['branded'] = branded

    # ---- 생활정보 --------------------------------------------------------
    def life_rows(limit=12, offset=0, category=None, exclude=()):
        where, args = ["status='published'"], []
        if category: where.append('category=?'); args.append(category)
        if exclude: where.append('id NOT IN (%s)' % ','.join('?' * len(exclude))); args += list(exclude)
        with conn() as db:
            return db.execute('SELECT * FROM articles WHERE ' + ' AND '.join(where) + ' ORDER BY featured DESC, published_at DESC, id DESC LIMIT ? OFFSET ?',
                              args + [limit, offset]).fetchall()

    def life_body(text):
        # 본문: 빈 줄은 문단, "## "는 소제목, "- "는 목록. HTML은 쓰지 않음.
        out, items = [], []
        def flush():
            if items: out.append(Markup('<ul>') + Markup('').join(Markup('<li>%s</li>') % i for i in items) + Markup('</ul>')); items.clear()
        for block in re.split(r'\n\s*\n', (text or '').strip()):
            lines = [l.strip() for l in block.split('\n') if l.strip()]
            for line in lines:
                if line.startswith('- '): items.append(line[2:]); continue
                flush()
                if line.startswith('## '): out.append(Markup('<h2>%s</h2>') % line[3:])
                else: out.append(Markup('<p>%s</p>') % line)
            flush()
        return Markup('\n').join(out)

    # ---- 이달의 기업 답변 순위 (숫자로만) ------------------------------------
    def company_rank(limit=5, days=RANK_DAYS):
        since = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat(timespec='seconds')
        with conn() as db:
            rows = db.execute("""SELECT c.id,c.company_id,c.status,c.review,c.reviewed_at,c.created,c.forwarded_at,co.name FROM cases c
                JOIN companies co ON co.id=c.company_id WHERE co.status IN ('active','listed') AND c.forwarded_at IS NOT NULL AND c.created>=?""", (since,)).fetchall()
            good = [r for r in rows if jebo.valid(r)]
            first = jebo.first_answers(db, [r['id'] for r in good])
        per = {}
        for r in good:
            p = per.setdefault(r['company_id'], {'id': r['company_id'], 'name': r['name'], 'n': 0, 'answered': 0, 'waits': []})
            p['n'] += 1
            if r['id'] in first:
                p['answered'] += 1
                h = jebo.hours(r['forwarded_at'], first[r['id']])
                if h is not None and h >= 0: p['waits'].append(h)
        out = []
        for p in per.values():
            if p['n'] < jebo.MIN_N: continue
            p['rate'] = round(100 * p['answered'] / p['n'])
            p['median_h'] = statistics.median(p['waits']) if p['waits'] else None
            p['median'] = jebo.fmt_hours(p['median_h'])
            p['waiting'] = p['n'] - p['answered']
            out.append(p)
        best = sorted([p for p in out if p['answered']], key=lambda p: (-p['rate'], p['median_h'] if p['median_h'] is not None else 1e9, -p['n']))[:limit]
        wait = sorted([p for p in out if p['waiting']], key=lambda p: (-p['waiting'], p['rate'], -p['n']))[:limit]
        return {'best': best, 'wait': wait, 'days': days, 'min_n': jebo.MIN_N}

    app.jinja_env.globals.update(brand=brand, is_soboru=is_soboru, site_name=site_name, life_rows=life_rows, life_body=life_body, company_rank=company_rank,
                                 ago_text=ago_text, LIFE_CATEGORIES=LIFE_CATEGORIES)

    # ---- 메인 화면: 소보루면 새 홈 ------------------------------------------
    old_home = app.view_functions['home']
    def home():
        if not is_soboru(): return old_home()
        lead = life_rows(1)
        side = life_rows(3, exclude=[a['id'] for a in lead])
        more = life_rows(6, exclude=[a['id'] for a in lead + side])
        return render_template('soboru_home.html', lead=lead[0] if lead else None, side=side, more=more, rank=company_rank(4),
                               cases=S.report_rows(limit=6), posts=S.recent_posts(4))
    app.view_functions['home'] = home

    # ---- 생활정보 화면 ----------------------------------------------------
    @app.route('/life')
    def life():
        cat = request.args.get('category', '')
        cat = cat if cat in LIFE_CATEGORIES else ''
        page = max(1, request.args.get('page', 1, type=int))
        with conn() as db:
            total = db.execute("SELECT COUNT(*) FROM articles WHERE status='published'" + (' AND category=?' if cat else ''), (cat,) if cat else ()).fetchone()[0]
        rows = life_rows(LIFE_PAGE, (page - 1) * LIFE_PAGE, cat or None)
        return render_template('life.html', rows=rows, cat=cat, page=page, pages=max(1, -(-total // LIFE_PAGE)), total=total)

    @app.route('/life/<int:article_id>')
    def life_article(article_id):
        with conn() as db:
            a = db.execute('SELECT * FROM articles WHERE id=?', (article_id,)).fetchone()
            if not a or (a['status'] != 'published' and not S.admin_active()): abort(404)
            if a['status'] == 'published': db.execute('UPDATE articles SET views=views+1 WHERE id=?', (article_id,))
        related = life_rows(3, category=a['category'], exclude=[a['id']])
        return render_template('life_article.html', a=a, related=related)

    # ---- 관리자: 생활정보 글 쓰기·게시 ----------------------------------------
    def form_values():
        f = request.form
        tone = f.get('tone', 't1')
        return {'title': f.get('title', '').strip()[:120], 'summary': f.get('summary', '').strip()[:400], 'body': f.get('body', '').strip()[:20000],
                'category': f.get('category') if f.get('category') in LIFE_CATEGORIES else '생활', 'emoji': f.get('emoji', '').strip()[:8],
                'tone': tone if tone in LIFE_TONES else 't1', 'source_name': f.get('source_name', '').strip()[:120],
                'source_url': f.get('source_url', '').strip()[:500] if f.get('source_url', '').strip().startswith(('http://', 'https://')) else '',
                'featured': 1 if f.get('featured') else 0}

    @app.route('/admin/life', methods=['GET', 'POST'])
    @S.admin_only
    def admin_life():
        if request.method == 'POST':
            v = form_values()
            if not v['title']: flash('제목을 적어 주세요.'); return redirect(url_for('admin_life'))
            status = 'published' if request.form.get('publish') else 'draft'
            with conn() as db:
                cur = db.execute('INSERT INTO articles(title,summary,body,category,emoji,tone,source_name,source_url,featured,status,created,updated,published_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                 (v['title'], v['summary'], v['body'], v['category'], v['emoji'], v['tone'], v['source_name'], v['source_url'], v['featured'], status, now(), now(), now() if status == 'published' else None))
            flash('글을 게시했어요.' if status == 'published' else '초안으로 저장했어요.')
            return redirect(url_for('admin_life_edit', article_id=cur.lastrowid))
        view = request.args.get('view', '')
        with conn() as db:
            rows = db.execute('SELECT * FROM articles' + (" WHERE status='draft'" if view == 'draft' else '') + ' ORDER BY id DESC LIMIT 200').fetchall()
            n_draft = db.execute("SELECT COUNT(*) FROM articles WHERE status='draft'").fetchone()[0]
        return render_template('admin_life.html', rows=rows, a=None, view=view, n_draft=n_draft, categories=LIFE_CATEGORIES, tones=LIFE_TONES)

    @app.route('/admin/life/<int:article_id>', methods=['GET', 'POST'])
    @S.admin_only
    def admin_life_edit(article_id):
        with conn() as db:
            a = db.execute('SELECT * FROM articles WHERE id=?', (article_id,)).fetchone()
            if not a: abort(404)
            if request.method == 'POST':
                act = request.form.get('act', 'save')
                if act == 'delete':
                    db.execute('DELETE FROM articles WHERE id=?', (article_id,)); flash('글을 지웠어요.'); return redirect(url_for('admin_life'))
                v = form_values()
                if not v['title']: flash('제목을 적어 주세요.'); return redirect(url_for('admin_life_edit', article_id=article_id))
                status = {'publish': 'published', 'unpublish': 'draft'}.get(act, a['status'])
                published_at = a['published_at'] or (now() if status == 'published' else None)
                db.execute('UPDATE articles SET title=?,summary=?,body=?,category=?,emoji=?,tone=?,source_name=?,source_url=?,featured=?,status=?,updated=?,published_at=? WHERE id=?',
                           (v['title'], v['summary'], v['body'], v['category'], v['emoji'], v['tone'], v['source_name'], v['source_url'], v['featured'], status, now(), published_at, article_id))
                flash({'publish': '게시했어요.', 'unpublish': '게시를 내렸어요. 초안으로 남아 있어요.'}.get(act, '저장했어요.'))
                return redirect(url_for('admin_life_edit', article_id=article_id))
            rows = db.execute('SELECT * FROM articles ORDER BY id DESC LIMIT 200').fetchall()
            n_draft = db.execute("SELECT COUNT(*) FROM articles WHERE status='draft'").fetchone()[0]
        return render_template('admin_life.html', rows=rows, a=a, view='', n_draft=n_draft, categories=LIFE_CATEGORIES, tones=LIFE_TONES)

    S.life_rows = life_rows; S.company_rank = company_rank; S.is_soboru = is_soboru
