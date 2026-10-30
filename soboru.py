"""소보루: 사이트 브랜드(소보루 하나), 메인 화면, 생활정보(매거진), 이달의 기업 답변 순위.

- 예전 소비자제보센터 화면은 2026-10-17에 뺐음. 그 완성본은 태그 jebo-center-final에 있음 (docs/JEBO_CENTER_RESTORE.md).
- 저장해 둔 문구 속 '소비자제보센터'는 화면에 낼 때 '소보루'로 바꿔 보여 줌.
- 생활정보(/life): 운영자가 쓰거나, 나중에 공공데이터 자동 수집이 초안으로 넣는 글. 게시한 글만 보임.
"""
import datetime, json, os, re, statistics, urllib.parse
import site_content
import soboru_writer
from flask import abort, flash, g, has_request_context, redirect, render_template, request, session, url_for
from markupsafe import Markup, escape

OLD_NAME = '소비자제보센터'
NEW_NAME = '소보루'
# 소보루로 바꿀 때 덮어쓰는 문구 (관리자가 적어 둔 값보다 앞섬)
# 예전 브랜드 시절 소보루로 덮어쓰던 문구. 소보루 하나만 쓰면서 기본값이 소보루 문구가 됐으니, 그때 저장해 둔 값(화면에 안 보이던 값)은 한 번 지움
RETIRED_KEYS = ('site.brand', 'site.name', 'seo.home_title', 'seo.description', 'board.title')
# 소비자제보센터 화면(consumerjebo.co.kr): 소보루와 같은 제보·게시판·관리자를 쓰고, 이름·제목만 이 칸의 값으로 바꿔 보여 줌
LOGIN_TO_WRITE = ('report', 'board_write', 'board_comment', 'case_comment')  # 소보루 화면에서 로그인해야 쓰는 곳
SOBORU_ONLY = ('/life', '/letter', '/pick/', '/ask', '/feed', '/vs', '/suda', '/editor', '/me/saved', '/owners', '/u/', '/people/', '/me/following', '/me/people')
JEBO_KEYS = {'site.name': 'jebo.site_name', 'seo.home_title': 'jebo.home_title', 'seo.description': 'jebo.description', 'board.title': 'jebo.board_title'}

# AI 소비자 상담 새 버전(lawrag.py)을 켰을 때만 쓰는 메뉴·제목 문구. 꺼져 있으면 old_nav 그대로
ASK_V2_TEXT = {'nav': 'AI 소비자 상담', 'old_nav': '법률 질문', 'title': 'AI 소비자 상담', 'h1': '소비자 피해, AI에게 편하게 물어보세요',
               'notice': '상담사가 아닌 AI가 제공하는 일반 정보예요', 'cta': '업체와의 협의가 어려우신가요?'}
# 검색·공유용 페이지 제목과 설명 (소보루일 때만). 키는 화면 이름, 안내·약관 화면은 '화면:쪽'
SEO_PAGES = {
    'report': ('소비자 피해 제보하기 | 소보루', '겪은 소비자 피해를 소보루에 제보하세요. 기업에 전달해 답변을 받고 해결을 돕는 중재를 해요. 제보와 답변 기록은 기사로 다뤄질 수 있어요.'),
    'reports': ('소비자 제보 목록 | 소보루', '소비자들이 직접 올린 피해 제보와 기업 답변을 분야별로 모아 볼 수 있어요. 같은 일을 겪었다면 함께 목소리를 내요.'),
    'board': ('제품·업체 리뷰와 추천 | 소보루', '직접 써 본 소비자가 남긴 제품·업체 리뷰와 추천을 모았어요. 광고 없이 솔직한 후기와 살까 말까 고민될 때의 질문까지 나눠요.'),
    'law_ask': ('AI 소비자 상담 | 소보루', '환불·해지·배송·품질 같은 소비자 피해를 AI에게 편하게 물어보세요. 법령 원문을 근거로 소비자 권리와 대응 방법을 안내해 드려요.'),
    'info_page:faq': ('자주 묻는 질문 | 소보루', '제보 방법, 처리 절차, 공개 범위, 기업 답변까지 소보루 이용자들이 자주 묻는 질문을 모았어요.'),
    'info_page:guide': ('이용 안내 | 소보루', '소보루에서 제보하고, 리뷰를 쓰고, 생활정보를 찾아보는 방법을 한눈에 안내해 드려요.'),
    'info_page:process': ('제보 처리 절차 | 소보루', '제보 접수부터 검토, 기업 전달, 답변 도착, 종결까지 소보루가 제보를 처리하는 과정을 알려 드려요.'),
    'takedown': ('권리침해 신고 및 임시조치 안내 | 소보루', '소보루 게시물로 권리를 침해당했다면 신고할 수 있어요. 임시조치 절차와 이의 제기 방법을 안내해 드려요.'),
    'policy_page:terms': ('이용약관 | 소보루', '소보루 서비스 이용 조건과 이용자·운영자의 권리와 의무를 정한 이용약관이에요.'),
    'policy_page:privacy': ('개인정보 처리방침 | 소보루', '소보루가 어떤 개인정보를 왜 모으고, 얼마나 보관하고, 어떻게 보호하는지 알려 드려요.'),
    'policy_page:youth': ('청소년보호정책 | 소보루', '청소년이 유해한 정보에 노출되지 않도록 소보루가 지키는 원칙과 책임자를 안내해요.'),
}
# 공유 미리보기 기본 그림: 주소 앞부분별로 다른 그림 (글 자체 사진이 있으면 그 사진이 먼저)
OG_SECTIONS = [('/reports', 'report'), ('/report', 'report'), ('/companies', 'report'), ('/life', 'life'), ('/board', 'pick'), ('/ask', 'ask')]
LIFE_CATEGORIES = ['쇼핑', '통신', '여행', '음식', '금융', '자동차', '생활', '리콜']
LIFE_EMOJI = {'쇼핑': '🛒', '통신': '📱', '여행': '✈️', '음식': '🍜', '금융': '💰', '자동차': '🚗', '생활': '🏠', '리콜': '🚨'}  # 생활정보 분야 칩
GUIDE_EMOJI = {'write': '📝', 'attach': '📋', 'ticket': '🧾', 'lock': '🔒', 'search': '🔍', 'chat': '💬', 'check': '✅', 'bell': '🔔'}  # 이용 안내 단계 아이콘 자리
LIFE_TONES = ['t1', 't2', 't3', 't4', 't5', 't6']  # 대표 그림 바탕색
LIFE_PAGE = 12
RANK_DAYS = 30
# 화면 편집 (관리자 > 화면 편집): 페이지마다 큰 묶음(블록)의 순서와 보이기. 잘게 나누지 않고 화면에서 한눈에 보이는 덩어리 단위
PAGE_BLOCKS = {
    'home': ('홈', [('intro', '맨 위 소개 (소보루 큰 문구 · 제보하기 버튼)'), ('live', '소비자의 소리 (실시간 제보)'),
                   ('pick', '커뮤니티 (추천 TOP 5 · 최신 글 · 글쓰기)'), ('talk', '골라주세요 · 수다방'), ('quick', '소보루는 이런 곳 (제보 · 후기 · 골라주세요 · 수다방)'),
                   ('letter', '소보루 레터 구독'), ('life', '알아 두면 돈 버는 소비 이야기'), ('answer', '기업 답변'), ('faq', '자주 묻는 질문 (AI 검색용 FAQ 포함)')]),
    'life': ('생활정보', [('head', '제목 · 소개 · 분야'), ('list', '생활정보 글 목록'), ('news', '요즘 소비자 뉴스'), ('letter', '소보루 레터 구독')]),
    'board': ('커뮤니티', [('head', '제목 · 소개 · 검색'), ('campaign', '이번 주 리뷰 주제'), ('pick', '무엇을 올릴까요? (글쓰기 고르기)'),
                         ('feed', '글 목록 · 이번 주 인기 · 리뷰 모아 보기'), ('foot', '맨 아래 안내')]),
    'letter': ('소보루 레터', [('hero', '맨 위 구독 신청'), ('feats', '레터에 담기는 것 (3가지)'), ('archive', '지난 레터')]),
}
# 예전 '메인 화면 순서' 저장값(top·life·rank 켜고 끄기)을 새 묶음으로 옮길 때
BLOCKS_OFF = {'home': ('quick',)}  # 처음엔 숨겨 두는 묶음 (관리자 > 화면 편집에서 다시 켤 수 있음). '이런 곳' 소개는 제보·픽이 먼저 보이니 빼 둠 (운영자 2026-10-24)
# 숨길 수 있는 작은 꾸밈 조각: 키 → (이름, 기본으로 보이기). OH 2026-10-29: 셋 다 처음부터 숨김
PIECES = {'home.live_tag': ('소비자의 소리 옆 빨간 점 꼬리표', False),
          'home.vs_box': ('골라주세요 위 "고민될 땐" 안내 상자', False),
          'home.suda_box': ('수다방 위 "오늘의 수다" 상자', False),
          'home.campaign': ('커뮤니티 위 "이번 주 리뷰 주제" 상자', False)}  # OH 2026-10-29: 지움
OLD_HOME_SECTIONS = {'top': ('intro', 'quick', 'live'), 'life': ('life',), 'rank': ('pick', 'talk', 'answer')}
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


def clean_blocks(page, raw):
    # 저장된 값이 이상해도 화면이 깨지지 않게: 모르는 묶음은 빼고, 빠진 묶음(새로 생긴 묶음)은 켜서
    # 기본 순서에서 바로 앞 묶음 뒤에 붙임 (앞 묶음이 없으면 맨 뒤)
    names = dict(PAGE_BLOCKS[page][1]); order = list(names)
    seen, out = set(), []
    for item in raw or []:
        if isinstance(item, (list, tuple)) and len(item) == 2 and item[0] in names and item[0] not in seen:
            seen.add(item[0]); out.append([item[0], 1 if item[1] else 0])
    for n, k in enumerate(order):
        if k in seen: continue
        prev = order[n - 1] if n else None
        at = next((i + 1 for i, (b, _) in enumerate(out) if b == prev), len(out))
        out.insert(at, [k, 0 if k in BLOCKS_OFF.get(page, ()) else 1]); seen.add(k)
    return out


def move_block(rows, key, act):
    """묶음 하나를 위·아래로 옮기거나 숨기기·보이기. rows는 clean_blocks 결과."""
    i = next((n for n, (k, _) in enumerate(rows) if k == key), None)
    if i is None: return rows
    rows = [list(r) for r in rows]
    if act == 'up' and i > 0: rows[i - 1], rows[i] = rows[i], rows[i - 1]
    elif act == 'down' and i < len(rows) - 1: rows[i + 1], rows[i] = rows[i], rows[i + 1]
    elif act in ('top', 'bottom'): rows.insert(0 if act == 'top' else len(rows), rows.pop(i))
    elif act in ('hide', 'show'): rows[i][1] = 1 if act == 'show' else 0
    return rows


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS articles(id INTEGER PRIMARY KEY,title TEXT NOT NULL,summary TEXT NOT NULL DEFAULT '',body TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT '생활',emoji TEXT NOT NULL DEFAULT '',tone TEXT NOT NULL DEFAULT 't1',source_name TEXT NOT NULL DEFAULT '',source_url TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'draft',origin TEXT NOT NULL DEFAULT 'manual',ext_key TEXT,featured INTEGER NOT NULL DEFAULT 0,views INTEGER NOT NULL DEFAULT 0,
        created TEXT NOT NULL,updated TEXT NOT NULL,published_at TEXT)''')
    # 공공데이터 자동 수집이 같은 항목을 두 번 넣지 않게
    db.execute('CREATE TABLE IF NOT EXISTS soboru_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS articles_ext_key ON articles(ext_key) WHERE ext_key IS NOT NULL')
    if not db.execute("SELECT 1 FROM soboru_settings WHERE key='brand_only'").fetchone():
        db.execute('DELETE FROM site_content WHERE key IN (%s)' % ','.join('?' * len(RETIRED_KEYS)), RETIRED_KEYS)
        db.execute("INSERT INTO soboru_settings(key,value) VALUES('brand_only','1')")


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
    # 들어온 주소로 정함: JEBO_HOST(consumerjebo.co.kr)면 소비자제보센터 화면, 그 밖은 소보루. 제보·회원·게시판 데이터는 하나라 양쪽에 같이 보임.
    # 관리자는 /?face=jebo 로 소비자제보센터 화면을 미리 볼 수 있음 (/?face=off 로 끔)
    def brand():
        return g.get('brand', 'soboru') if has_request_context() else 'soboru'

    def is_soboru(): return brand() == 'soboru'

    def seo_page(field):
        if not has_request_context() or not is_soboru(): return ''
        page = (request.view_args or {}).get('page')
        row = SEO_PAGES.get(f'{request.endpoint}:{page}' if page else request.endpoint)
        return row[0 if field == 'title' else 1] if row else ''

    def og_default():
        if not is_soboru(): return 'og-image.png'
        path = request.path
        for prefix, name in OG_SECTIONS:
            if path == prefix or path.startswith(prefix + '/'): return f'soboru-og-{name}.png'
        return 'soboru-og.png'
    app.jinja_env.globals.update(seo_page=seo_page, og_default=og_default)

    @app.before_request
    def apply_brand():
        if request.endpoint == 'static' or 'content' not in g: return
        jebo_face = S.current_face() == 'jebo'  # 주소·관리자 미리보기로 정함 (app.py current_face)
        g.brand = 'jebo' if jebo_face else 'soboru'
        # 소보루에만 있는 화면(생활정보·레터·리뷰 주제·AI 상담)은 소비자제보센터 주소로 들어와도 soboru.co.kr로
        if request.host.split(':')[0].lower() in S.JEBO_HOSTS and S.main_host() not in S.JEBO_HOSTS and request.path.startswith(SOBORU_ONLY):
            return redirect('https://' + S.main_host() + request.full_path.rstrip('?'), 301)
        if jebo_face:
            for key, jkey in JEBO_KEYS.items(): g.content[key] = g.content.get(jkey) or OLD_NAME
            for key in ('seo.naver_verification', 'seo.google_verification', 'seo.facebook_verification'):  # 검색엔진 소유확인은 주소마다 따로
                g.content[key] = g.content.get(key.replace('seo.', 'jebo.'), '')
            return
        for k, v in g.content.items():  # 예전에 저장해 둔 문구 속 옛 이름도 소보루로
            if OLD_NAME in v: g.content[k] = v.replace(OLD_NAME, NEW_NAME)
        # 소보루는 로그인해야 글을 씀 (운영자 2026-10-24: 제보·후기·수다·댓글 모두). 소비자제보센터 주소는 지금처럼 비회원도 제보
        if request.endpoint in LOGIN_TO_WRITE and not g.get('user') and os.getenv('SOBORU_GUEST_WRITE') != '1':
            flash(S.ui_text('sb.login_to_write', '소보루는 로그인하면 글을 쓸 수 있어요. 카카오로 3초 만에 시작해요.'))
            back = request.full_path.rstrip('?') if request.method == 'GET' else urllib.parse.urlsplit(request.referrer or '').path or '/'
            return redirect(url_for('login', next=back if back.startswith('/') and not back.startswith('//') else '/'))

    def site_name():
        """메일·알림·AI 초안에 쓰는 사이트 이름 (요청 밖에서도 DB 설정을 읽음)."""
        if has_request_context() and 'content' in g: return g.content.get('site.name') or NEW_NAME
        with conn() as db:
            row = db.execute("SELECT value FROM site_content WHERE key='site.name'").fetchone()
        return (row[0] if row else '') or NEW_NAME
    notify.site_name = site_name

    def branded(value):
        # 템플릿에 적힌 기본 문구 속 이름도 지금 브랜드로 (Markup은 Markup 그대로)
        return value.replace(OLD_NAME, site_name()) if value and is_soboru() else value
    app.jinja_env.filters['branded'] = branded

    # 홈 구조화 데이터(AI 검색용): 매거진 글 목록 → Article ItemList, (질문, 답) → FAQPage 질문들
    def slice_items(rows):
        org = {'@id': S.canonical_url('/') + '#organization'}
        return [{'@type': 'ListItem', 'position': i + 1, 'item': {'@type': 'Article', '@id': S.canonical_url(r['url']) + '#article', 'url': S.canonical_url(r['url']), 'headline': r['title'][:110],
                 'datePublished': (r.get('stamp') or '')[:19], 'author': org, 'publisher': org}} for i, r in enumerate(rows)]

    def faq_items(pairs):
        return [{'@type': 'Question', 'name': str(q), 'acceptedAnswer': {'@type': 'Answer', 'text': str(a)}} for q, a in pairs]
    app.jinja_env.filters.update(slice_items=slice_items, faq_items=faq_items)

    # ---- 생활정보 --------------------------------------------------------
    def life_rows(limit=12, offset=0, category=None, exclude=()):
        where, args = ["status='published'"], []
        if category: where.append('category=?'); args.append(category)
        if exclude: where.append('id NOT IN (%s)' % ','.join('?' * len(exclude))); args += list(exclude)
        with conn() as db:
            return db.execute('SELECT * FROM articles WHERE ' + ' AND '.join(where) + ' ORDER BY featured DESC, published_at DESC, id DESC LIMIT ? OFFSET ?',
                              args + [limit, offset]).fetchall()

    BODY_EMOJI = set(soboru_writer.EMOJI) | {'☕', '📨'}  # 토스페이스 글꼴에 있는 것만 이모지 칸으로
    LIFE_DEFAULT_EMOJI = ('📌', '🔍', '💬', '📊', '👀')

    def life_body(text):
        # 본문: 빈 줄은 문단, "## "는 소제목(앞에 이모지), "### "는 번호 붙은 요점, "※ 낱말: 풀이"는 용어 풀이, "- "는 목록, "> "는 '핵심만 쏙' 상자. HTML은 쓰지 않음.
        # 매거진처럼 (운영자 2026-10-24: 토스처럼 깔끔하게): 소제목은 큰 글씨에 작은 이모지, 이어진 용어 풀이는 상자 하나로, 소제목마다 차례용 id(s1, s2…).
        out, items, terms, n_head, check, n_point, sec = [], [], [], 0, False, 0, 0
        points = [0]  # 소제목(## )마다 요점(### ) 수
        for l in (text or '').split('\n'):
            if l.strip().startswith('## '): points.append(0)
            elif l.strip().startswith('### '): points[-1] += 1
        def flush():
            nonlocal check
            if items:
                out.append(Markup('<ul class="sb-check">' if check else '<ul>') + Markup('').join(Markup('<li>%s</li>') % hl(i) for i in items) + Markup('</ul>'))
                items.clear()
            if terms:
                out.append(Markup('<dl class="sb-terms"><p class="sb-terms-h">%s</p>') % S.ui_text('life.terms', '용어 풀이')
                           + Markup('').join((Markup('<div><dt>%s</dt><dd>%s</dd></div>') % (w, m)) if m else Markup('<div><dd>%s</dd></div>') % w for w, m in terms) + Markup('</dl>'))
                terms.clear()
        for block in re.split(r'\n\s*\n', (text or '').strip()):
            lines = [l.strip() for l in block.split('\n') if l.strip()]
            for line in lines:
                if line.startswith('- '):
                    if terms: flush()
                    items.append(line[2:]); continue
                if line.startswith('※ '):  # 용어 풀이: 이어진 것끼리 상자 하나
                    if items: flush()
                    word, _, mean = line[2:].partition(':'); terms.append((word.strip(), mean.strip())); continue
                flush()
                if line.startswith('### '):  # 요점: 소제목 안에 요점이 둘 이상일 때만 1, 2, 3… 번호 (하나뿐이면 번호 없이 굵은 제목)
                    n_point += 1
                    if points[sec] > 1: out.append(Markup('<h3 class="sb-point"><span class="sb-point-n" aria-hidden="true">%d</span>%s</h3>') % (n_point, line[4:].strip()))
                    else: out.append(Markup('<h3 class="sb-point">%s</h3>') % line[4:].strip())
                elif line.startswith('## '):
                    n_point = 0; sec += 1
                    emo, head = life_head(line, n_head)
                    n_head += 1; check = emo == '✅'
                    out.append(Markup('<h2 class="sb-h" id="s%d"><span class="sb-h-emo" aria-hidden="true">%s</span><span class="sb-h-t"><small>%02d</small>%s</span></h2>') % (n_head, emo, n_head, head))
                elif line.startswith('> '):
                    note = line[2:].strip(); emo = note[:1] if note[:1] in BODY_EMOJI else '💡'
                    if note[:1] in BODY_EMOJI: note = note[1:].strip()
                    out.append(Markup('<aside class="sb-callout"><span class="sb-h-emo" aria-hidden="true">%s</span><div><b>%s</b><p>%s</p></div></aside>') % (emo, S.ui_text('life.callout', '핵심만 쏙'), note))
                else: out.append(Markup('<p>%s</p>') % hl(line))
            flush()
        return Markup('\n').join(out)

    def hl(text):
        # **말** -> 형광펜 강조 (뉴닉처럼). 글은 먼저 이스케이프하고 강조만 태그로
        return Markup(re.sub(r'\*\*(.{1,60}?)\*\*', r'<strong class="sb-hl">\1</strong>', str(escape(text)))).replace('**', '')

    def life_head(line, n):
        head = line[3:].strip(); emo = head[:1]
        if emo in BODY_EMOJI: return emo, head[1:].lstrip('\ufe0f').strip()  # ⚖️처럼 뒤에 붙는 글자 모양 표시는 제목에서 뺌
        return ('✅' if '이렇게 하세요' in head else LIFE_DEFAULT_EMOJI[n % len(LIFE_DEFAULT_EMOJI)]), head

    def life_toc(text):
        # 차례: 소제목 (번호, 이모지, 제목). life_body의 id(s1, s2…)와 같은 순서
        heads = [l.strip() for l in (text or '').split('\n') if l.strip().startswith('## ')]
        return [(i + 1,) + life_head(h, i) for i, h in enumerate(heads)]

    # ---- 이달의 기업 답변 순위 (숫자로만) ------------------------------------
    def company_rank(limit=5, days=RANK_DAYS):
        since = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat(timespec='seconds')
        with conn() as db:
            # 제보 많은 기업: 승인 전이라도 기업별로 바로 셈 (운영자 요청 2026-10-29: 관리자가 안 넘겨도 수치가 보이게). 전체 기간 누적, 반려·중복은 뺌
            bad = tuple(jebo.NOT_VALID)
            most = [dict(r) for r in db.execute("""SELECT co.id,co.name,co.logo,co.logo_at,COUNT(*) AS n FROM cases c JOIN companies co ON co.id=c.company_id
                WHERE co.status IN ('active','listed') AND c.review NOT IN (%s) GROUP BY co.id ORDER BY n DESC, MAX(c.created) DESC LIMIT ?""" % ','.join('?' * len(bad)),
                bad + (limit,)).fetchall()]
            rows = db.execute("""SELECT c.id,c.company_id,c.status,c.review,c.reviewed_at,c.created,c.forwarded_at,co.name,co.logo,co.logo_at FROM cases c
                JOIN companies co ON co.id=c.company_id WHERE co.status IN ('active','listed') AND c.forwarded_at IS NOT NULL AND c.created>=?""", (since,)).fetchall()
            good = [r for r in rows if jebo.valid(r)]
            first = jebo.first_answers(db, [r['id'] for r in good])
        per = {}
        for r in good:
            p = per.setdefault(r['company_id'], {'id': r['company_id'], 'name': r['name'], 'logo': r['logo'], 'logo_at': r['logo_at'], 'n': 0, 'answered': 0, 'waits': []})
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
        return {'best': best, 'wait': wait, 'most': most, 'days': days, 'min_n': jebo.MIN_N}

    app.jinja_env.globals.update(brand=brand, is_soboru=is_soboru, site_name=site_name, life_rows=life_rows, life_body=life_body, life_toc=life_toc, company_rank=company_rank,
                                 ago_text=ago_text, LIFE_CATEGORIES=LIFE_CATEGORIES, LIFE_EMOJI=LIFE_EMOJI, GUIDE_EMOJI=GUIDE_EMOJI,
                                 report_look=report_look, life_art=lambda cat: LIFE_ART.get(cat, 'other'), report_art=lambda ind: report_art(ind, S.items('guide_industries')))

    # ---- 화면 편집: 페이지별 큰 묶음 순서·보이기 ---------------------------------
    def page_blocks(page):
        """[[묶음, 켬], ...] 저장된 순서 (없으면 기본 순서)."""
        with conn() as db:
            row = db.execute('SELECT value FROM soboru_settings WHERE key=?', ('blocks:' + page,)).fetchone()
            old = db.execute("SELECT value FROM soboru_settings WHERE key='home'").fetchone() if page == 'home' and not row else None
        try: saved = json.loads(row[0]) if row else []
        except ValueError: saved = []
        if old:  # 예전 '메인 화면 순서'에서 끈 묶음은 계속 꺼 둠
            try: off = {k for k, on in json.loads(old[0]).get('sections', []) if not on}
            except (ValueError, AttributeError, TypeError): off = set()
            saved = [[b, 0 if any(b in OLD_HOME_SECTIONS.get(k, ()) for k in off) else 1] for b, _ in PAGE_BLOCKS['home'][1]]
        if page == 'home' and row and saved and not any(isinstance(x, list) and x[:1] == ['_v2'] for x in saved):
            # 2026-10-24 운영자 요청: 제보·픽을 소개 바로 아래로 (검은고양이처럼). 예전에 저장한 순서도 한 번만 새 순서로, 켜고 끈 건 그대로
            on = {x[0]: x[1] for x in saved if isinstance(x, list) and len(x) == 2}
            saved = [[b, 0 if b in BLOCKS_OFF['home'] else on.get(b, 1)] for b, _ in PAGE_BLOCKS['home'][1]]
            with conn() as db:
                db.execute('INSERT OR REPLACE INTO soboru_settings(key,value) VALUES(?,?)', ('blocks:home', json.dumps(clean_blocks('home', saved) + [['_v2', 1]])))
        return clean_blocks(page, saved)

    def save_blocks(page, rows):
        with conn() as db:
            db.execute('INSERT OR REPLACE INTO soboru_settings(key,value) VALUES(?,?)', ('blocks:' + page, json.dumps(clean_blocks(page, rows) + ([['_v2', 1]] if page == 'home' else []))))

    def blocks(page):
        # 템플릿: {% for b in blocks('home') %} 순서대로 켠 묶음만. 요청마다 한 번만 읽음
        cache = g.setdefault('page_blocks', {}) if has_request_context() else {}
        if page not in cache: cache[page] = page_blocks(page)
        return [k for k, on in cache[page] if on]

    def ed_block(page, key):
        # 편집 모드에서 묶음 위에 붙는 작은 막대: 이름 · 위로 · 아래로 · 숨기기
        if not S.editing(): return ''
        names = dict(PAGE_BLOCKS[page][1]); keys = blocks(page)
        btn = lambda act, label, off=False: Markup('<button type="button" data-act="%s"%s>%s</button>') % (act, Markup(' disabled') if off else '', label)
        return (Markup('<div class="ed-blockbar" data-page="%s" data-block="%s"><b>%s</b>') % (page, key, names.get(key, key))
                + btn('up', '▲ 위로', keys[:1] == [key]) + btn('down', '▼ 아래로', keys[-1:] == [key]) + btn('hide', '숨기기') + Markup('</div>'))

    def ed_hidden_blocks(page):
        # 편집 모드에서 페이지 맨 아래: 숨긴 묶음을 다시 보이게
        if not S.editing(): return ''
        names = dict(PAGE_BLOCKS[page][1])
        off = [k for k, on in page_blocks(page) if not on]
        if not off: return ''
        return (Markup('<div class="ed-hiddenblocks"><b>숨긴 묶음</b>')
                + Markup('').join(Markup('<span class="ed-blockbar" data-page="%s" data-block="%s">%s <button type="button" data-act="show">보이기</button></span>') % (page, k, names[k]) for k in off)
                + Markup('</div>'))
    # ---- 작은 꾸밈 조각(꼬리표·안내 상자) 숨기기: 편집 모드에서 조각마다 숨기기/보이기 -------------
    def pieces():
        cache = g.setdefault('pieces', None) if has_request_context() else None
        if cache is None:
            with conn() as db: row = db.execute("SELECT value FROM soboru_settings WHERE key='pieces'").fetchone()
            try: saved = json.loads(row[0]) if row else {}
            except ValueError: saved = {}
            cache = {k: bool(saved.get(k, on)) for k, (_, on) in PIECES.items()}
            if has_request_context(): g.pieces = cache
        return cache

    def piece_on(key):
        # 템플릿: {% if piece_on('home.vs_box') %}...{% endif %}{{ ed_piece('home.vs_box') }}
        return pieces().get(key, True)

    def ed_piece(key):
        if not S.editing() or key not in PIECES: return ''
        on = piece_on(key)
        return (Markup('<span class="ed-blockbar ed-piece%s" data-page="_piece" data-block="%s"><b>%s</b><button type="button" data-act="%s">%s</button></span>')
                % ('' if on else ' off', key, PIECES[key][0] + ('' if on else ' (지움)'), 'hide' if on else 'show', '✕ 지우기' if on else '＋ 넣기'))

    def save_piece(key, on):
        cur = dict(pieces()); cur[key] = bool(on)
        with conn() as db: db.execute('INSERT OR REPLACE INTO soboru_settings(key,value) VALUES(?,?)', ('pieces', json.dumps({k: int(v) for k, v in cur.items()})))
    app.jinja_env.globals.update(blocks=blocks, ed_block=ed_block, ed_hidden_blocks=ed_hidden_blocks, piece_on=piece_on, ed_piece=ed_piece)

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

    jebo_home = app.view_functions['home']
    app.view_functions['home'] = lambda: home_nn() if is_soboru() else jebo_home()  # 소비자제보센터 주소면 예전 메인(index.html)

    def live_cards(n):
        """홈 '소비자의 소리' 카드 (운영자 요청 2026-10-30: 검은고양이처럼 콘텐츠 보듯이): 공개 제보는 본문 앞부분(개인정보 가림)과
        '나도 겪었어요'·댓글 수, 기업 답변 여부까지. 비밀글·공개 전 제보는 제목·업체·단계만 (본문 없음)"""
        cases = [dict(c, look=report_look(c['cat'])) for c in S.report_rows(limit=n)]
        ids = [c['no'] for c in cases]
        if not ids: return cases
        q = ','.join('?' * len(ids))
        with conn() as db:
            rows = {r['id']: r for r in db.execute(f'SELECT id,public_consent,published,public_body,description FROM cases WHERE id IN ({q})', ids)}
            first = jebo.first_answers(db, ids)
        tc = app.jinja_env.globals.get('talk_counts')  # casetalk.py가 붙임 (소보루 모듈보다 나중에 설치돼서 S에는 없음)
        talk = tc(ids) if tc else {}
        for c in cases:
            r = rows.get(c['no'])
            open_ = bool(r and r['public_consent'] and r['published'] and c['title'])
            body = ' '.join((r['public_body'] or S.mask_personal(r['description'] or '')).split()) if open_ else ''
            c.update(open=open_, excerpt=body[:140], answered=c['no'] in first, metoo=talk.get(c['no'], (0, 0))[0], comments=talk.get(c['no'], (0, 0))[1])
        return cases

    def home_reviews(n=4):
        # 홈 '내돈내산 후기'(운영자 요청, 2026-10-30): 최근 30일 반응 많은 후기 먼저, 모자라면 최신 후기
        since = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat(timespec='seconds')
        nb = S.not_blocked()
        with conn() as db:
            rows = db.execute(f"SELECT {S.FEED_COLS} FROM posts WHERE kind='review' AND hidden=0{nb} AND created>=? ORDER BY likes*2+comments DESC,id DESC LIMIT ?", (since, n)).fetchall()
            if len(rows) < n:
                seen = {r['id'] for r in rows}
                rows += [r for r in db.execute(f"SELECT {S.FEED_COLS} FROM posts WHERE kind='review' AND hidden=0{nb} ORDER BY id DESC LIMIT ?", (n * 2,)) if r['id'] not in seen][:n - len(rows)]
        return rows

    def home_nn():
        # 뉴닉식 홈(운영자 요청, 2026-10-17): 맨 위는 소보루 소개만(건수 없음), 바로 아래 실시간 제보.
        # 묶음 순서·보이기는 관리자 > 화면 편집 (PAGE_BLOCKS['home'])
        lifes = [life_item(a) for a in life_rows(8)]
        reps = [r for r in report_items(6) if r['title']]
        for r in reps:  # '[품질·하자] 물건이나…' → '품질·하자'
            m = re.match(r'\[([^\]]+)\]', r['label'] or ''); r['label'] = m.group(1) if m else r['label']
        feed = []
        while lifes or reps:
            feed += lifes[:2]; lifes = lifes[2:]
            if reps: feed.append(reps.pop(0))
        cats = [c for c in LIFE_CATEGORIES if any(x['kind'] == 'life' and x['label'] == c for x in feed)]
        # 소보루 픽: 리뷰를 대상(제품·업체)별로 묶어 '추천해요'와 별점으로 순위. 소보루 에디터 리뷰는 소비자 순위에 넣지 않음
        with conn() as db:
            picks = [dict(r) for r in db.execute("""SELECT target,MAX(company_id) AS company_id,COUNT(*) AS n,ROUND(AVG(rating),1) AS avg,SUM(recommend=1) AS rec
                FROM posts WHERE kind='review' AND hidden=0 AND editor=0 AND target!='' GROUP BY target ORDER BY rec DESC,avg DESC,n DESC LIMIT 5""")]
        return render_template('soboru_home_nn.html', cases=live_cards(6), feed=feed[:10], cats=cats,
                               rank=company_rank(5), posts=home_reviews(4), picks=picks)

    @app.route('/admin/home-plan')
    @S.admin_only
    def admin_home_plan():  # 예전 '메인 화면 순서' 주소 → 화면 편집
        return redirect(url_for('admin_screens', _anchor='page-home'))

    # 관리자 > 화면 편집: 페이지별로 '화면에서 바로 고치기' 열기, 묶음 순서·보이기, 그 페이지 문구 전체
    SCREENS = [  # (키, 이름, 주소 만드는 함수, 문구를 모을 템플릿 파일)
        ('home', '홈', lambda: url_for('home'), ['soboru_home_nn.html', 'letter_macros.html']),
        ('life', '매거진', lambda: url_for('life'), ['life.html', 'life_article.html', 'soboru_life_macros.html', 'life_tabs.html', 'life_search.html', 'life_trend.html', 'life_shopping.html', 'life_nv_macros.html']),
        ('board', '커뮤니티', lambda: url_for('board'), ['board.html', 'soboru_board.html', 'soboru_board_post.html', 'soboru_board_write.html', 'board_post.html', 'board_write.html', 'community_macros.html']),
        ('report', '제보', lambda: url_for('report'), ['report.html', 'reports.html', 'report_rows.html', 'public_case.html', 'soboru_case.html', 'case_talk.html', 'success.html', 'lookup.html', 'case.html', 'guide.html', 'info.html', 'process_cards.html']),
        ('company', '기업', lambda: url_for('companies'), ['companies.html', 'company_page.html', 'company_grade.html']),
        ('scam', '사기 주의', lambda: url_for('scam_home'), ['scam.html', 'scam_new.html']),
        ('ask', '법률 질문', lambda: url_for('law_ask'), ['soboru_ask.html', 'soboru_ask_v2.html']),
        ('letter', '소보루 레터', lambda: url_for('letter_home'), ['letter.html', 'letter_issue.html', 'letter_msg.html', 'letter_macros.html']),
        ('common', '공통 머리글·바닥글', lambda: url_for('home'), ['base.html', 'soboru_header.html', 'soboru_tabbar.html']),
    ]
    SCREEN_SKIP = {'site.name'}  # 사이트 이름은 문구 고치기에서

    def screen_keys(files):
        keys = []
        for f in files:
            for k in site_content.UI_FILES.get(f, []):
                if k in site_content.FIELDS and k not in keys and k not in SCREEN_SKIP and not site_content.FIELDS[k].get('doc'): keys.append(k)
        return keys

    @app.route('/admin/screens', methods=['GET', 'POST'])
    @S.admin_only
    def admin_screens():
        if request.method == 'POST':
            f = request.form; page = f.get('page', '')
            if f.get('act') == 'texts':  # 그 페이지 문구 한 번에 저장 (관리자 > 문구 고치기과 같은 규칙)
                files = next((x[3] for x in SCREENS if x[0] == page), None)
                if files is None: abort(400)
                stamp = now()
                with conn() as db:
                    for key in screen_keys(files):
                        if key not in f: continue
                        field = site_content.FIELDS[key]
                        value = f[key].replace('\r\n', '\n').strip()
                        if len(value) > site_content.MAX_LENGTH: abort(400)
                        if not field.get('multiline'): value = ' '.join(value.split())
                        if value == field['default'] or (not value and not field.get('optional')): db.execute('DELETE FROM site_content WHERE key=?', (S.db_key(key),))
                        else: db.execute('INSERT INTO site_content(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated', (S.db_key(key), value, stamp))
                flash('문구를 저장했어요.')
                return redirect(url_for('admin_screens', _anchor='page-' + page))
            if page == '_piece':  # 작은 꾸밈 조각 숨기기·보이기
                if f.get('block') not in PIECES or f.get('act') not in ('hide', 'show'): abort(400)
                save_piece(f['block'], f['act'] == 'show')
                if f.get('ajax'): return {'ok': True}
                flash('%s을(를) %s.' % (PIECES[f['block']][0], '넣었어요' if f['act'] == 'show' else '지웠어요'))
                return redirect(url_for('admin_screens', _anchor='page-' + f['block'].split('.')[0]))
            if page not in PAGE_BLOCKS: abort(400)
            if f.get('act') == 'order':  # 순서표 통째로 저장 (끌어서 옮기기·숫자)
                keys = [k for k in f.getlist('block') if k in dict(PAGE_BLOCKS[page][1])]
                save_blocks(page, [[k, 1 if f.get('show_' + k) else 0] for k in keys])
            else:
                save_blocks(page, move_block(page_blocks(page), f.get('block', ''), f.get('act', '')))
            if f.get('ajax'): return {'ok': True}
            flash('%s 묶음 순서를 저장했어요.' % PAGE_BLOCKS[page][0])
            return redirect(url_for('admin_screens', _anchor='page-' + page))
        changed = S.saved_keys('site_content')
        screens = [{'key': k, 'name': n, 'url': u(), 'texts': screen_keys(files), 'blocks': page_blocks(k) if k in PAGE_BLOCKS else None,
                    'names': dict(PAGE_BLOCKS[k][1]) if k in PAGE_BLOCKS else {},
                    'pieces': [(pk, PIECES[pk][0], piece_on(pk)) for pk in PIECES if pk.split('.')[0] == k]} for k, n, u, files in SCREENS]
        return render_template('admin_screens.html', screens=screens, fields=site_content.FIELDS, content=S.load_content(), changed=changed)

    # ---- 생활정보 화면 ----------------------------------------------------
    @app.route('/life')
    def life():
        cat = request.args.get('category', '')
        cat = cat if cat in LIFE_CATEGORIES else ''
        page = max(1, request.args.get('page', 1, type=int))
        with conn() as db:
            total = db.execute("SELECT COUNT(*) FROM articles WHERE status='published'" + (' AND category=?' if cat else ''), (cat,) if cat else ()).fetchone()[0]
        rows = life_rows(LIFE_PAGE, (page - 1) * LIFE_PAGE, cat or None)
        if page > 1 and page > -(-total // LIFE_PAGE): abort(404)  # 없는 쪽 번호는 빈 화면(200) 대신 404
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

    def delete_article(db, article_id):
        # 글과 딸린 AI 기록·일러스트 기록까지 함께 지움
        db.execute('DELETE FROM articles WHERE id=?', (article_id,))
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'ai_articles' in tables: db.execute('DELETE FROM ai_articles WHERE article_id=?', (article_id,))
        if 'soboru_art' in tables: db.execute("DELETE FROM soboru_art WHERE kind='life' AND target_id=?", (article_id,))

    @app.route('/admin/life/<int:article_id>/delete', methods=['POST'])
    @S.admin_only
    def admin_life_delete(article_id):
        # 관리자 목록·글 화면의 '지우기'
        with conn() as db:
            if not db.execute('SELECT 1 FROM articles WHERE id=?', (article_id,)).fetchone(): abort(404)
            delete_article(db, article_id)
        flash('글을 지웠어요.')
        back = S.safe_back(url_for('admin_life'))
        return redirect(url_for('life') if back.startswith('/life/') else back)

    @app.route('/admin/life/<int:article_id>', methods=['GET', 'POST'])
    @S.admin_only
    def admin_life_edit(article_id):
        with conn() as db:
            a = db.execute('SELECT * FROM articles WHERE id=?', (article_id,)).fetchone()
            if not a: abort(404)
            if request.method == 'POST':
                act = request.form.get('act', 'save')
                if act == 'delete':
                    delete_article(db, article_id); flash('글을 지웠어요.'); return redirect(url_for('admin_life'))
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
    app.extensions['soboru'] = {'page_blocks': page_blocks, 'blocks': blocks, 'report_items': report_items}
