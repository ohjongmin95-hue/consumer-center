"""소보루 브랜드: 설정 하나로 이름·로고·메인 화면을 소보루로 바꾸기, 생활정보(매거진), 이달의 기업 답변 순위.

- 관리자 > 숨은 문구·설정 > '브랜드'에 소보루라고 적으면 사이트 이름·로고·메인 화면·메일 머리말이 소보루로 바뀜.
  비우면 지금 그대로 소비자제보센터. 주소·데이터는 그대로라 언제든 오갈 수 있음.
- 관리자는 바꾸기 전에 아무 주소 뒤에 ?brand=soboru 를 붙여 미리 볼 수 있음 (?brand=off 로 끔). 방문자에게는 안 보임.
- 생활정보(/life): 운영자가 쓰거나, 나중에 공공데이터 자동 수집이 초안으로 넣는 글. 게시한 글만 보임.
"""
import datetime, json, re, statistics
import site_content
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
# 메인 화면 순서 (관리자 > 메인 화면 순서)
HOME_SECTIONS = [('top', '맨 위 큰 카드'), ('box', '제보하기 상자'), ('cases', '새로 올라온 제보'), ('rank', '이달의 기업 답변 · 커뮤니티 인기글'),
                 ('life', '알아 두면 돈 버는 생활정보')]  # 제보 안내 바로가기는 '소비자 제보' 메뉴 안으로 옮김
HOME_KINDS = {'report': '소비자 제보', 'life': '생활정보'}
HOME_PERIODS = [(1, '1시간'), (3, '3시간'), (6, '6시간'), (12, '12시간'), (24, '하루')]
HOME_DEFAULT = {'slots': ['report', 'life'], 'hours': 6, 'pins': [], 'sections': [[k, 1] for k, _ in HOME_SECTIONS]}
# 제보 카드 대표 그림: 제보 유형별 이모지·바탕색
REPORT_EMOJI = {'배송·교환·환불': '📦', '계약·해지': '📝', '요금·결제': '💳', '품질·하자·AS': '🛠️', '허위·과장 광고': '📢',
                '고객 응대': '☎️', '개인정보': '🔐', '안전·위해': '⚠️'}
REPORT_TONE = {'배송·교환·환불': 't1', '계약·해지': 't5', '요금·결제': 't4', '품질·하자·AS': 't2', '허위·과장 광고': 't6',
               '고객 응대': 't3', '개인정보': 't5', '안전·위해': 't6'}

# 관리자가 분야 이름을 바꿔도(예: 요금·환불, 정보·안전) 맞는 그림이 나오게 낱말로도 찾음. 앞에 있는 낱말이 먼저.
REPORT_WORDS = [('안전', '⚠️', 't6'), ('위해', '⚠️', 't6'), ('개인정보', '🔐', 't5'), ('환불', '📦', 't1'), ('배송', '📦', 't1'), ('교환', '📦', 't1'),
                ('품질', '🛠️', 't2'), ('하자', '🛠️', 't2'), ('AS', '🛠️', 't2'), ('요금', '💳', 't4'), ('결제', '💳', 't4'), ('광고', '📢', 't6'),
                ('표시', '📢', 't6'), ('계약', '📝', 't5'), ('해지', '📝', 't5'), ('응대', '☎️', 't3')]
# 제보 업종 → 이용 안내의 업종 그림(static/img/guide-ind-<이름>.svg)
ART_WORDS = [('식품', 'food'), ('외식', 'food'), ('음식', 'food'), ('의약', 'medical'), ('의료', 'medical'), ('병원', 'medical'), ('쇼핑', 'commerce'),
             ('유통', 'commerce'), ('가전', 'appliance'), ('전자', 'appliance'), ('자동차', 'car'), ('통신', 'telecom'), ('금융', 'finance'),
             ('보험', 'finance'), ('카드', 'finance'), ('게임', 'game'), ('건설', 'building'), ('부동산', 'building'), ('인테리어', 'building'),
             ('가구', 'building')]
INDUSTRY_ART = {name: art for name, art, *_ in site_content.INDUSTRIES}
LIFE_ART = {'쇼핑': 'commerce', '통신': 'telecom', '음식': 'food', '금융': 'finance', '자동차': 'car', '리콜': 'appliance'}


def report_look(cat):
    """분야 이름 → (이모지, 바탕색 번호)."""
    if cat in REPORT_EMOJI: return REPORT_EMOJI[cat], REPORT_TONE[cat]
    for word, emoji, tone in REPORT_WORDS:
        if word in (cat or ''): return emoji, tone
    return '📣', 't1'


def report_art(industry, extra=()):
    """제보 업종 → 업종 그림 이름. 관리자가 이용 안내 업종 카드에 그림을 골라 뒀으면 그걸 먼저 씀."""
    industry = industry or ''
    for it in extra:
        if it.get('name') == industry and it.get('icon'): return it['icon']
    if industry in INDUSTRY_ART: return INDUSTRY_ART[industry]
    for word, art in ART_WORDS:
        if word in industry: return art
    return 'other'


def clean_plan(raw):
    # 저장된 값이 이상해도 메인 화면이 깨지지 않게 기본값으로 메움
    slots = [k for k in (raw.get('slots') or []) if k in HOME_KINDS][:6] or list(HOME_DEFAULT['slots'])
    hours = raw.get('hours') if raw.get('hours') in [h for h, _ in HOME_PERIODS] else HOME_DEFAULT['hours']
    pins = [p for p in (raw.get('pins') or []) if isinstance(p, int) and p > 0][:12]
    seen, sections = set(), []
    for item in raw.get('sections') or []:
        if isinstance(item, (list, tuple)) and len(item) == 2 and item[0] in dict(HOME_SECTIONS) and item[0] not in seen:
            seen.add(item[0]); sections.append([item[0], 1 if item[1] else 0])
    sections += [[k, 1] for k, _ in HOME_SECTIONS if k not in seen]
    return {'slots': slots, 'hours': hours, 'pins': pins, 'sections': sections}


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS articles(id INTEGER PRIMARY KEY,title TEXT NOT NULL,summary TEXT NOT NULL DEFAULT '',body TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT '생활',emoji TEXT NOT NULL DEFAULT '',tone TEXT NOT NULL DEFAULT 't1',source_name TEXT NOT NULL DEFAULT '',source_url TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'draft',origin TEXT NOT NULL DEFAULT 'manual',ext_key TEXT,featured INTEGER NOT NULL DEFAULT 0,views INTEGER NOT NULL DEFAULT 0,
        created TEXT NOT NULL,updated TEXT NOT NULL,published_at TEXT)''')
    # 공공데이터 자동 수집이 같은 항목을 두 번 넣지 않게
    db.execute('CREATE TABLE IF NOT EXISTS soboru_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
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
                                 ago_text=ago_text, LIFE_CATEGORIES=LIFE_CATEGORIES,
                                 report_look=report_look, life_art=lambda cat: LIFE_ART.get(cat, 'other'), report_art=lambda ind: report_art(ind, S.items('guide_industries')))

    # ---- 메인 화면: 소보루면 새 홈 ------------------------------------------
    # 관리자 > 메인 화면 순서에서 맨 위 큰 카드에 무엇을 어떤 순서·주기로 띄울지, 아래 묶음 순서를 정함.
    def home_plan():
        with conn() as db:
            row = db.execute("SELECT value FROM soboru_settings WHERE key='home'").fetchone()
        try: saved = json.loads(row[0]) if row else {}
        except ValueError: saved = {}
        return clean_plan(saved)

    def report_items(limit=12, pins=()):
        # 공개 동의 + 게시된 제보만 (비밀글·게시 전·반려·중복은 메인 카드에 안 나감)
        sql = ("SELECT c.*,EXISTS(SELECT 1 FROM messages m WHERE m.case_id=c.id AND m.author='기업 답변' AND m.public=1) AS answered FROM cases c "
               "WHERE c.public_consent=1 AND c.published=1 AND c.review NOT IN ('rejected','duplicate')")
        with conn() as db:
            if pins:
                rows = {r['id']: r for r in db.execute(sql + ' AND c.id IN (%s)' % ','.join('?' * len(pins)), list(pins))}
                rows = [rows[i] for i in pins if i in rows]
            else:
                rows = db.execute(sql + ' ORDER BY c.id DESC LIMIT ?', (limit,)).fetchall()
        out = []; arts = S.items('guide_industries') if has_request_context() and g.get('lists') is not None else []
        for r in rows:
            text = jebo.pub(r, S.mask_personal)
            body = ' '.join((text['body'] or '').split())
            cat = jebo.cat_label(r['category'])
            out.append({'kind': 'report', 'id': r['id'], 'url': url_for('public_case', case_id=r['id']), 'title': text['subject'],
                        'summary': body[:110] + ('…' if len(body) > 110 else ''), 'label': cat, 'company': S.mask_personal(r['company']),
                        'status': r['status'], 'answered': bool(r['answered']), 'stamp': r['created'],
                        'emoji': report_look(cat)[0], 'tone': report_look(cat)[1], 'art': report_art(r['industry'], arts)})
        return out

    def life_item(a):
        return {'kind': 'life', 'id': a['id'], 'url': url_for('life_article', article_id=a['id']), 'title': a['title'], 'summary': a['summary'],
                'label': a['category'], 'stamp': a['published_at'] or a['created'], 'emoji': a['emoji'] or '📰', 'tone': a['tone'] or 't1', 'art': LIFE_ART.get(a['category'], 'other')}

    def plan_tick(plan, at=None):
        # 주기 번호: 서버 시각(한국 시각) 0시 기준으로 hours마다 1씩 오름
        at = at or datetime.datetime.now()
        secs = (at - datetime.datetime(2026, 1, 1)).total_seconds()
        step = plan['hours'] * 3600
        tick = int(secs // step)
        return tick, datetime.datetime(2026, 1, 1) + datetime.timedelta(seconds=(tick + 1) * step)

    def pick_top(plan, at=None):
        """맨 위 큰 카드 1개 + 옆 목록 3개. 순서표(slots)를 주기마다 한 칸씩 넘기고, 같은 종류 안에서도 돌아가며 보여 줌."""
        featured = [life_item(a) for a in life_rows(12) if a['featured']]
        pools = {'life': featured or [life_item(a) for a in life_rows(12)], 'report': report_items(12, plan['pins'])}
        slots = plan['slots']
        tick, _ = plan_tick(plan, at)
        i = tick % len(slots)
        kind = slots[i]
        if not pools[kind]: kind = 'life' if kind == 'report' else 'report'  # 그 종류가 아직 없으면 다른 종류로
        pool = pools[kind]
        if not pool: return None, []
        nth = (tick // len(slots)) * max(1, slots.count(kind)) + slots[:i].count(kind)
        lead = pool[nth % len(pool)]
        # 옆 목록: 다른 종류부터 번갈아 3개
        other = 'life' if kind == 'report' else 'report'
        rest = {'life': [life_item(a) for a in life_rows(4, exclude=[lead['id']] if kind == 'life' else ())],
                'report': [x for x in pools['report'] if x is not lead]}
        side, order = [], [other, kind]
        while len(side) < 3 and (rest['life'] or rest['report']):
            for k in order:
                if rest[k] and len(side) < 3: side.append(rest[k].pop(0))
        return lead, side

    old_home = app.view_functions['home']
    def home():
        if not is_soboru(): return old_home()
        if request.args.get('look') != 'old': return home_nn()  # 예전 홈은 /?look=old 로 비교용
        plan = home_plan()
        lead, side = pick_top(plan)
        shown = [x['id'] for x in ([lead] if lead else []) + side if x['kind'] == 'life']
        more = life_rows(6, exclude=shown) or life_rows(6)
        return render_template('soboru_home.html', plan=plan, lead=lead, side=side, more=more, rank=company_rank(4),
                               cases=S.report_rows(limit=6), posts=S.community_feed(4))
    app.view_functions['home'] = home

    def home_nn():
        # 뉴닉식 홈(운영자 요청, 2026-10-17): 맨 위는 소보루 소개만(건수 없음), 바로 아래 실시간 제보.
        # 관리자 > 메인 화면 순서의 켜고 끄기를 따름: top=소개·실시간 제보, life=소비 이야기, rank=소보루 픽·기업 답변 기록
        lifes = [life_item(a) for a in life_rows(8)]
        reps = [r for r in report_items(6) if r['title']]
        feed = []
        while lifes or reps:
            feed += lifes[:2]; lifes = lifes[2:]
            if reps: feed.append(reps.pop(0))
        cats = [c for c in LIFE_CATEGORIES if any(x['kind'] == 'life' and x['label'] == c for x in feed)]
        # 소보루 픽: 리뷰를 대상(제품·업체)별로 묶어 '추천해요'와 별점으로 순위
        with conn() as db:
            picks = [dict(r) for r in db.execute("""SELECT target,MAX(company_id) AS company_id,COUNT(*) AS n,ROUND(AVG(rating),1) AS avg,SUM(recommend=1) AS rec
                FROM posts WHERE kind='review' AND hidden=0 AND target!='' GROUP BY target ORDER BY rec DESC,avg DESC,n DESC LIMIT 5""")]
        show = {k: on for k, on in home_plan()['sections']}
        return render_template('soboru_home_nn.html', show=show, cases=[dict(c, look=report_look(c['cat'])) for c in S.report_rows(limit=6)], feed=feed[:10], cats=cats,
                               rank=company_rank(5), posts=S.community_feed(4), picks=picks)

    @app.route('/admin/home-plan', methods=['GET', 'POST'])
    @S.admin_only
    def admin_home_plan():
        if request.method == 'POST':
            f = request.form
            pins = [int(x) for x in re.findall(r'\d+', f.get('pins', ''))]
            order = sorted(HOME_SECTIONS, key=lambda s: f.get('order_' + s[0], type=int) or 99)
            plan = clean_plan({'slots': f.getlist('slot'), 'hours': f.get('hours', type=int), 'pins': pins,
                               'sections': [[k, 1 if f.get('show_' + k) else 0] for k, _ in order]})
            with conn() as db:
                db.execute('INSERT OR REPLACE INTO soboru_settings(key,value) VALUES(?,?)', ('home', json.dumps(plan, ensure_ascii=False)))
            flash('메인 화면 순서를 저장했어요.')
            return redirect(url_for('admin_home_plan'))
        plan = home_plan()
        lead, side = pick_top(plan)
        _, next_at = plan_tick(plan)
        found = {r['id'] for r in report_items(pins=plan['pins'])} if plan['pins'] else set()
        return render_template('admin_home_plan.html', plan=plan, lead=lead, side=side, next_at=next_at, kinds=HOME_KINDS, periods=HOME_PERIODS,
                               sections=dict(HOME_SECTIONS), missing=[p for p in plan['pins'] if p not in found],
                               n_life=len(life_rows(50)), n_report=len(report_items(50)))

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
            auto_art(cur.lastrowid)
            flash('글을 게시했어요.' if status == 'published' else '초안으로 저장했어요.')
            return redirect(url_for('admin_life_edit', article_id=cur.lastrowid))
        view = request.args.get('view', '')
        with conn() as db:
            rows = db.execute('SELECT * FROM articles' + (" WHERE status='draft'" if view == 'draft' else '') + ' ORDER BY id DESC LIMIT 200').fetchall()
            n_draft = db.execute("SELECT COUNT(*) FROM articles WHERE status='draft'").fetchone()[0]
        return render_template('admin_life.html', rows=rows, a=None, view=view, n_draft=n_draft, categories=LIFE_CATEGORIES, tones=LIFE_TONES)

    def auto_art(article_id):
        # AI 일러스트 자동 그리기 (soboru_art.py가 붙어 있고 키가 있을 때만)
        art = app.extensions.get('soboru_art')
        if art: art['auto']('life', article_id)

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
                db.commit(); auto_art(article_id)
                flash({'publish': '게시했어요.', 'unpublish': '게시를 내렸어요. 초안으로 남아 있어요.'}.get(act, '저장했어요.'))
                return redirect(url_for('admin_life_edit', article_id=article_id))
            rows = db.execute('SELECT * FROM articles ORDER BY id DESC LIMIT 200').fetchall()
            n_draft = db.execute("SELECT COUNT(*) FROM articles WHERE status='draft'").fetchone()[0]
        return render_template('admin_life.html', rows=rows, a=a, view='', n_draft=n_draft, categories=LIFE_CATEGORIES, tones=LIFE_TONES)

    S.life_rows = life_rows; S.company_rank = company_rank; S.is_soboru = is_soboru
    app.extensions['soboru'] = {'home_plan': home_plan, 'pick_top': pick_top, 'report_items': report_items}
