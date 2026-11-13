"""소보루고발 앱 전용 화면 (운영자 2026-11-11: 헤이마오터우쑤 기능을 앱에, 배치는 헤이마오·세부는 토스 TDS).

앱(사용자 에이전트 'SoboruApp/버전 (ios|android)')으로 소비자고발제보센터 주소를 열었을 때만 바뀌고, 웹사이트는 그대로다.
- 홈(/): 헤이마오 首页. 전체·오늘 고발 숫자 + 고발하기, 최근 기업 답변·해결 한 줄, 사기 전에 확인해 보세요(瞄一眼, /check 글),
  함께 대응하고 있어요(集体投诉, /groups), 고발 목록 탭(인기·최신·답변 완료·해결됨).
- 기업 순위(/companies/rank): 헤이마오 红黑榜. 업종별 2열 카드에 잘 답하는 곳·아쉬운 곳·답변 빠른 곳(回复效率).
- 공동 대응(/groups): 모인 사람 수 순·최신 순 카드.
이모지는 토스페이스(앱 바닥글에 출처). 버튼은 #CE6719.
"""
import datetime
import html
import os
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET

from flask import abort, redirect, render_template, request, url_for

TABS = {'hot': '인기', 'new': '최신', 'answer': '답변 완료', 'done': '해결됨'}
RANK_TABS = {'good': '잘 답하는 곳', 'bad': '아쉬운 곳', 'fast': '답변 빠른 곳'}
PERIODS = {'week': ('주간', 7), 'month': ('월간', 30), 'all': ('전체', 0)}
CARD_N = 5      # 업종 카드 한 장에 보이는 기업 수
ONE_IND_N = 10  # 업종 하나만 볼 때
NEWS_HOME = 'https://www.consumertimes.kr'
NEWS_N = 12          # 가져오는 기사 수 (첫 화면 칸은 5개, 둘러보기 탭은 전부)
NEWS_TTL = 30 * 60   # 기사 목록을 다시 가져오는 간격(초)
_news = {'at': 0, 'items': [], 'busy': False}


def news_rss():
    # 소비자를위한신문(ND소프트) 전체 기사 RSS. 주소가 바뀌면 서버 설정 SOBORU_NEWS_RSS로
    return os.getenv('SOBORU_NEWS_RSS', NEWS_HOME + '/rss/allArticle.xml')


def parse_news(xml_bytes, limit=NEWS_N):
    """RSS에서 (제목, 링크, 날짜, 사진). 사진은 enclosure·media·본문 첫 그림 순으로"""
    out = []
    root = ET.fromstring(xml_bytes)
    for it in root.iter('item'):
        title = re.sub(r'<[^>]+>', '', html.unescape((it.findtext('title') or '').strip())).strip()
        link = (it.findtext('link') or '').strip()
        if not title or not link.startswith(('http://', 'https://')): continue
        img = ''
        for el in it:
            tag = el.tag.split('}')[-1]
            if tag in ('enclosure', 'content', 'thumbnail') and (el.get('url') or '').startswith('http') and 'image' in (el.get('type') or 'image'):
                img = el.get('url'); break
        if not img:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)', html.unescape(it.findtext('description') or ''))
            if m and m.group(1).startswith('http'): img = m.group(1)
        when = ''
        raw = (it.findtext('pubDate') or '').strip()
        for fmt in ('%a, %d %b %Y %H:%M:%S %z', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S%z'):
            try: dt = datetime.datetime.strptime(raw, fmt); when = dt.strftime('%m.%d'); break
            except ValueError: pass
        out.append(dict(title=title, link=link, date=when, img=img, new=bool(when) and when == datetime.date.today().strftime('%m.%d')))
        if len(out) >= limit: break
    return out


def refresh_news():
    try:
        req = urllib.request.Request(news_rss(), headers={'User-Agent': 'Mozilla/5.0 (SoboruJebo)'})
        with urllib.request.urlopen(req, timeout=6) as r: items = parse_news(r.read(2_000_000))
        if items: _news['items'] = items
    except Exception:
        pass
    finally:
        _news['at'] = time.time(); _news['busy'] = False


def soboru_news():
    """앱 홈 '소보루 기사' (운영자 2026-11-13). 화면을 기다리게 하지 않게 뒤에서 새로 가져오고, 그동안은 가져온 목록을 씀"""
    if time.time() - _news['at'] > NEWS_TTL and not _news['busy']:
        _news['busy'] = True
        th = threading.Thread(target=refresh_news, daemon=True); th.start()
        if not _news['items']: th.join(4)  # 서버를 막 켰을 때 첫 화면부터 기사가 보이게 (최대 4초)
    return _news['items']



# ── 앱 안에서 기사 읽기 (운영자 2026-11-13: 기사를 누르면 신문 사이트로 넘어가지 않고 앱 안에서) ──
READ_TTL = 30 * 60
_read = {}


def news_host_ok(url):
    import urllib.parse
    u = urllib.parse.urlsplit(url or '')
    home = urllib.parse.urlsplit(NEWS_HOME).hostname or ''
    return u.scheme in ('http', 'https') and (u.hostname or '') in (home, home.removeprefix('www.'))


def _txt(chunk):
    chunk = re.sub(r'(?is)<(script|style|noscript|button|iframe)[^>]*>.*?</\1>', ' ', chunk)
    chunk = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</h\d>|</li>', '\n', chunk)
    chunk = html.unescape(re.sub(r'<[^>]+>', ' ', chunk))
    return [x for x in (re.sub(r'[ \t\u00a0]+', ' ', y).strip() for y in chunk.split('\n')) if x]


def parse_article(page, url):
    """ND소프트 기사 화면 → 제목·날짜·기자·[('p', 글) | ('img', 주소, 설명)]. 본문을 못 찾으면 None. 글과 사진 주소만 뽑아 쓰고 원래 HTML은 쓰지 않음"""
    import urllib.parse
    from mag_assist import ARTICLE_BOX
    meta = lambda prop: (re.search(r'(?is)<meta[^>]+(?:property|name)=["\']' + prop + r'["\'][^>]+content=["\']([^"\']*)', page) or [None, ''])[1]
    title = html.unescape(meta('og:title')).split(' - ')[0].strip()
    if not title:
        m = re.search(r'(?is)<title[^>]*>(.*?)</title>', page); title = html.unescape(m[1]).split(' - ')[0].strip() if m else ''
    day = meta('article:published_time')[:10].replace('-', '.')
    if not day:
        m = re.search(r'(\d{4})[.-](\d{2})[.-](\d{2}) \d{2}:\d{2}', page); day = '.'.join(m.groups()) if m else ''
    by = html.unescape(meta('og:article:author') or meta('dable:author') or '').strip()
    start = None
    for pat in ARTICLE_BOX:
        b = re.search(pat, page, re.I)
        if b: start = page.find('>', b.end() - 1) + 1; break  # 본문 상자 여는 태그 다음부터
    if start is None: return None
    chunk = page[start:start + 150000]
    end = re.search(r'저작권자|무단\s*전재|</article>', chunk)
    if end: chunk = chunk[:end.start()]
    blocks, pos = [], 0
    for m in re.finditer(r'(?is)<img\b[^>]*?\bsrc=["\']([^"\']+)["\'][^>]*>(?:\s*</?[a-z][^>]*>)*?\s*(?:<figcaption[^>]*>(.*?)</figcaption>)?', chunk):
        blocks += [('p', t) for t in _txt(re.sub(r'(?is)<figcaption[^>]*>.*?</figcaption>', ' ', chunk[pos:m.start()]))]
        src = urllib.parse.urljoin(url, html.unescape(m[1]))
        if src.startswith(('https://', 'http://')) and not re.search(r'(?i)icon|logo|banner|\.gif$', src):
            blocks.append(('img', src, ' '.join(_txt(m[2] or ''))))
        pos = m.end()
    blocks += [('p', t) for t in _txt(re.sub(r'(?is)<figcaption[^>]*>.*?</figcaption>', ' ', chunk[pos:]))]
    if sum(len(b[1]) for b in blocks if b[0] == 'p') < 80: return None
    return dict(title=title, day=day, by=by, blocks=blocks[:200], url=url)


def read_news(url):
    hit = _read.get(url)
    if hit and time.time() - hit[0] < READ_TTL: return hit[1]
    import company_web_email
    try: page = company_web_email.get(url)
    except Exception: page = ''
    art = parse_article(page, url) if page else None
    if len(_read) > 300: _read.clear()
    _read[url] = (time.time(), art)
    return art

WANTS = ('환불', '교환', '수리', '해지', '배상', '보상', '사과', '취소', '재발 방지')  # 공동 대응 '요구' 태그: 관련 고발의 요청 사항에 이 말이 있으면


def install(S):
    app = S.app
    jebo = S.jebo

    def in_app():
        try: is_sb = app.jinja_env.globals['is_soboru']()
        except Exception: is_sb = False
        return bool(S.appready.app_client()) and not is_sb

    app.jinja_env.globals['app_jebo'] = in_app

    def soboru_av(seed):
        # 운영자 2026-11-13: 프로필 사진이 없으면 토스처럼 단순한 새 5가지 중 하나 (고발 = 알리는 역할). 같은 사람은 늘 같은 새
        n = seed if isinstance(seed, int) else sum(ord(ch) * (i + 1) for i, ch in enumerate(str(seed or '')))
        return url_for('static', filename='img/av/bird-%d.svg' % (n % 5 + 1))
    app.jinja_env.globals['soboru_av'] = soboru_av
    app.jinja_env.globals['app_wants'] = lambda text: [w for w in WANTS if w in (text or '')]

    # ── 홈 ─────────────────────────────────────────────
    def ticker(db):
        """최근에 실제로 일어난 좋은 소식 한 줄씩: 기업이 답했거나, 제보자가 해결됐다고 알린 고발."""
        out = []
        for r in db.execute("""SELECT c.id,c.company,c.company_hidden,c.company_id,MAX(m.created) AS at FROM messages m JOIN cases c ON c.id=m.case_id
                WHERE m.author='기업 답변' AND m.public=1 AND c.public_consent=1 AND c.published=1 GROUP BY c.id ORDER BY at DESC LIMIT 6"""):
            co = S.pub_company(r); out.append((r['at'], co[:1], f"{co}이(가) 고발에 답했어요", r['id'], 'ans'))
        for r in db.execute("""SELECT c.id,c.company,c.company_hidden,c.confirmed_at AS at,c.rating_note,u.nickname FROM cases c LEFT JOIN users u ON u.id=c.user_id AND u.status='active'
                WHERE c.outcome='resolved' AND c.public_consent=1 AND c.published=1
                AND COALESCE(c.confirmed_at,'')<>'' ORDER BY c.confirmed_at DESC LIMIT 6"""):
            nick = r['nickname'] or '소비자'
            note = S.mask_personal(r['rating_note'] or '')  # 운영자 2026-11-13: 해결한 사람이 남긴 한마디 (헤이마오 만족도 한마디)
            out.append((r['at'], nick[:1], note or f"{S.pub_company(r)} 고발 해결됐어요, 고마워요!", r['id'], 'done'))
        if len(out) < 3:  # 운영자 2026-11-13: 소식 줄은 늘 움직이게. 답변·해결 소식이 적으면 새로 올라온 고발로 채움
            for r in db.execute("SELECT c.id,c.company,c.company_hidden,c.created AS at FROM cases c "
                                "WHERE c.public_consent=1 AND c.published=1 ORDER BY c.id DESC LIMIT 6"):
                out.append((r['at'], '', f"{S.pub_company(r)} 고발이 올라왔어요", r['id'], 'new'))
        out.sort(key=lambda x: x[0] or '', reverse=True)
        return out[:6]

    def guides(db, limit=3):
        try:
            rows = db.execute("SELECT id,industry,title,updated FROM buy_guides WHERE status='published' ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
        except Exception: return []
        new = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        emo = app.jinja_env.filters.get('ind_emoji', lambda x: '📦')
        return [dict(id=r['id'], title=r['title'], emo=emo(r['industry']), new=(r['updated'] or '') >= new) for r in rows]

    def open_groups(db, limit=2):
        if not S.GROUPS_ON: return []
        return db.execute("""SELECT g.id,g.title,g.company,(SELECT COUNT(*) FROM group_members m WHERE m.group_id=g.id) AS n
            FROM damage_groups g WHERE g.status IN ('open','active') ORDER BY n DESC,g.id DESC LIMIT ?""", (limit,)).fetchall()

    def feed(rows):
        """헤이마오 목록처럼 글쓴이(닉네임·얼굴)와 본문 미리보기를 붙임 (홈·고발 목록 app_feed.html). 사진은 템플릿에서 og_photo로 (가린 사본만)"""
        rows = [dict(r) for r in rows]
        ids = [r['no'] for r in rows]
        if not ids: return rows
        with S.conn() as db:
            who = {r['id']: r for r in db.execute("SELECT c.*,u.id AS uid,u.nickname FROM cases c LEFT JOIN users u ON u.id=c.user_id AND u.status='active' WHERE c.id IN (%s)" % ','.join('?' * len(ids)), ids)}
        for r in rows:
            w = who.get(r['no']); r['uid'] = w['uid'] if w else None; r['nick'] = (w['nickname'] if w else '') or ''
            # 운영자 2026-11-11: 커뮤니티라 목록에서도 본문이 보여야 함 (공개 글만, 개인정보 가린 본문)
            r['body'] = S.jebo.pub(w, S.mask_personal)['body'] if w and r.get('title') and not r.get('secret') and not r.get('pending') else ''
            # 운영자 2026-11-13: 헤이마오 集体投诉 카드처럼. 업체 로고·이름, 이 업체 고발 수·기업 처리율, 피해·요구 태그
            r['wants'] = [x for x in WANTS if w and x in (w['request_text'] or '')][:3] if r.get('body') else []
            r['co'] = None
            if w and w['company_id'] and not w['company_hidden'] and r.get('company'):
                with S.conn() as db:
                    co = db.execute('SELECT id,name,logo,logo_at FROM companies WHERE id=?', (w['company_id'],)).fetchone()
                    if co:
                        n, ans = db.execute("""SELECT COUNT(*),SUM(CASE WHEN c.status IN ('기업 답변 도착','종결') OR EXISTS(SELECT 1 FROM messages m WHERE m.case_id=c.id AND m.author='기업 답변') THEN 1 ELSE 0 END)
                            FROM cases c WHERE c.company_id=? AND c.public_consent=1 AND c.published=1""", (co['id'],)).fetchone()
                        r['co'] = dict(id=co['id'], logo=S.co_logo(co) if getattr(S, 'co_logo', None) else '', n=n or 0, rate=round(100 * (ans or 0) / n) if n else 0)
        return rows

    app.jinja_env.globals['app_feed'] = feed

    HOT_TOPICS = ('환불 거부', '택배 분실', '중도 해지', '개인정보 유출', '위약금')
    def app_hot():
        """운영자 2026-11-13: 검색칸 안내 문구는 헤이마오처럼 몇 초마다 바뀜. 요즘 많이 고발된 업체 + 많이 찾는 말.
        한 줄에 다 보이게 7글자 이하만 (잘리는 건 넣지 않음)."""
        out = []
        try:
            with S.conn() as db:
                for r in db.execute("""SELECT company FROM cases WHERE public_consent=1 AND published=1 AND COALESCE(company_hidden,0)=0
                        AND COALESCE(company,'')<>'' AND created >= date('now','-30 day') GROUP BY company ORDER BY COUNT(*) DESC, MAX(id) DESC LIMIT 8"""):
                    n = S.mask_personal(r['company'] or '').strip()
                    if 0 < len(n) <= 7 and n not in out: out.append(n)
        except Exception:
            pass
        out = out[:4]
        for t in HOT_TOPICS:
            if len(out) >= 6: break
            out.append(t)
        return out
    app.jinja_env.globals['app_hot'] = app_hot
    app.jinja_env.globals['app_hot_topics'] = HOT_TOPICS

    def home_list(tab):
        if tab == 'hot': rows = S.report_rows(order=S.HOT_ORDER, limit=6)
        elif tab in ('answer', 'done'): rows = S.report_rows(S.REPORT_STAGES[tab][1], (), 6)
        else: rows = S.report_rows(limit=6)
        return rows

    def app_home():
        tab = request.args.get('t', 'hot')
        if tab not in TABS: tab = 'hot'
        with S.conn() as db:
            data = dict(tick=ticker(db), guides=guides(db, 5), groups=open_groups(db), news=soboru_news()[:5], news_home=NEWS_HOME)
        return render_template('app_home.html', summary=S.report_summary(), tab=tab, tabs=TABS, cases=home_list(tab), **data)

    # ── 기업 순위 ────────────────────────────────────────
    def ranked(db, since=''):
        # since: 주간·월간이면 그 기간에 고발이 전달된 기업만 (운영자 2026-11-13: 헤이마오 周榜처럼)
        rows = db.execute("""SELECT co.*,(SELECT c.industry FROM cases c WHERE c.company_id=co.id AND c.industry!='' GROUP BY c.industry ORDER BY COUNT(*) DESC LIMIT 1) AS top_ind
            FROM companies co WHERE co.status IN ('active','listed') AND EXISTS(SELECT 1 FROM cases c WHERE c.company_id=co.id AND c.forwarded_at!='' AND c.forwarded_at>=?)""", (since,)).fetchall()
        out = []
        for co in rows:  # 운영자 2026-11-11: 앱 순위는 '5건 이상' 조건 없이 첫 고발부터. 등급 점수가 없으면 답변 비율로 줄 세움
            gr = dict(jebo.company_grade(db, co['id']))
            if not gr['scored']: continue  # 아직 답할 기한 안이고 답도 없는 기업은 셀 것이 없음
            if gr['score'] is None: gr['score'] = round(100 * gr['answered'] / gr['scored'])
            out.append((co, gr))
        return out

    def rank_pick(items, tab):
        """잘 답하는 곳 = 점수 높은 위 절반, 아쉬운 곳 = 아래 절반(낮은 순), 답변 빠른 곳 = 보통 답변 시간 짧은 순.
        기업이 적어도 한 기업이 '잘'과 '아쉬운'에 같이 나오지 않게 전체를 먼저 반으로 나눔 (웹 순위와 같은 기준)."""
        order = sorted(items, key=lambda x: (-x[1]['score'], -x[1]['scored'], x[0]['name']))
        half = -(-len(order) // 2)
        if tab == 'good': return order[:half]
        if tab == 'bad': return order[half:][::-1]
        return sorted([x for x in items if x[1]['med'] is not None], key=lambda x: (x[1]['med'], -x[1]['score']))

    def app_rank():
        tab = request.args.get('tab', 'good')
        if tab not in RANK_TABS: tab = 'good'
        ind = request.args.get('ind', '')
        inds = S.report_industries()
        if ind not in inds: ind = ''
        period = request.args.get('p', 'all')
        if period not in PERIODS: period = 'all'
        since = (datetime.date.today() - datetime.timedelta(days=PERIODS[period][1])).isoformat() if PERIODS[period][1] else ''
        with S.conn() as db: items = ranked(db, since)
        picked = rank_pick(items, tab)
        cards = []
        for i in ([ind] if ind else inds):
            rows = [x for x in picked if x[0]['top_ind'] == i][:ONE_IND_N if ind else CARD_N]
            if rows: cards.append((i, rows))
        return render_template('app_rank.html', cards=cards, tab=tab, tabs=RANK_TABS, ind=ind, inds=inds, n=len(items), period=period, periods=PERIODS,
                               min_n=jebo.MIN_N, days=jebo.ANSWER_DAYS, fmt_hours=jebo.fmt_hours)

    # ── 둘러보기 ─────────────────────────────────────────
    def app_explore():
        """헤이마오 发现 배치 (운영자 2026-11-13: 캡처 그대로, 디자인은 토스식).
        사기 전에 확인(瞄一眼) → AI 상담 카드 → 두 칸 바로가기(분쟁·대응, 소보루 자문단) → 탭 목록(소보루 아티클·공감 많은 고발·대응 방법)"""
        with S.conn() as db:
            g5 = guides(db, 5)
            try: hows = db.execute("SELECT id,emoji,title,topic FROM howto_guides WHERE status='published' ORDER BY sort,id LIMIT 8").fetchall()
            except Exception: hows = []
            try: scams = db.execute("SELECT id,kind,title,region,created FROM scam_reports WHERE status='public' ORDER BY id DESC LIMIT 8").fetchall()
            except Exception: scams = []
            try: g10 = guides(db, 10)
            except Exception: g10 = []
        hot = S.report_rows("public_consent=1 AND published=1 AND title_hidden=0 AND " + S.PUBLIC_VALID, (), 6, 0, S.HOT_ORDER)
        return render_template('app_explore.html', guides=g5, guides_all=g10, scams=scams, news=soboru_news(), news_home=NEWS_HOME, hows=hows, cases=hot)

    # ── 기사 읽기 ────────────────────────────────────────
    app.jinja_env.globals['news_link'] = lambda link: url_for('news_read', u=link) if news_host_ok(link) else link

    @app.route('/news/read')
    def news_read():
        u = request.args.get('u', '').strip()
        if not news_host_ok(u): abort(404)
        art = read_news(u)
        if not art: return redirect(u)  # 못 읽으면 원래 기사로
        return render_template('app_news.html', a=art, news_home=NEWS_HOME)

    # ── 공동 대응 ────────────────────────────────────────
    def app_groups():
        sort = 'new' if request.args.get('sort') == 'new' else 'many'
        order = 'g.id DESC' if sort == 'new' else 'n_members DESC,g.id DESC'
        with S.conn() as db:
            rows = db.execute(f"""SELECT g.*,(SELECT COUNT(*) FROM group_members m WHERE m.group_id=g.id) AS n_members,
                (SELECT COUNT(*) FROM cases c WHERE c.group_id=g.id) AS n_cases,
                (SELECT COUNT(*) FROM cases c WHERE c.group_id=g.id AND (c.status='기업 답변 도착' OR EXISTS(SELECT 1 FROM messages m WHERE m.case_id=c.id AND m.author='기업 답변' AND m.public=1))) AS n_answer
                FROM damage_groups g WHERE g.status IN ('open','active','closed')
                ORDER BY CASE g.status WHEN 'closed' THEN 1 ELSE 0 END,{order}""").fetchall()
            extra = {}
            for g_ in rows:
                cs = db.execute('SELECT id,category,request_text FROM cases WHERE group_id=?', (g_['id'],)).fetchall()
                ids = [c['id'] for c in cs]
                q = ','.join('?' * len(ids))
                like = db.execute(f"SELECT COUNT(*) FROM board_votes WHERE kind='metoo' AND target IN ({q})", ['case:%d' % i for i in ids]).fetchone()[0] if ids else 0
                talk = db.execute(f'SELECT COUNT(*) FROM case_comments WHERE hidden=0 AND case_id IN ({q})', ids).fetchone()[0] if ids else 0
                cats = []
                for c in cs:
                    lab = jebo.cat_label(c['category'])
                    if lab and lab not in cats: cats.append(lab)
                wants = [w for w in WANTS if any(w in (c['request_text'] or '') for c in cs)]
                rate = round(100 * g_['n_answer'] / g_['n_cases']) if g_['n_cases'] else 0
                extra[g_['id']] = dict(cats=cats[:3], wants=wants[:3], like=like, talk=talk, rate=rate)
        return render_template('app_groups.html', groups=rows, sort=sort, statuses=S.GROUP_STATUSES, extra=extra)

    def wrap(name, view):
        old = app.view_functions[name]
        def new(*a, **kw): return view() if in_app() else old(*a, **kw)
        app.view_functions[name] = new

    # 운영자 2026-11-13: 앱에서 로그인 안 한 채 '내 정보' 탭(앱은 /lookup을 엶)을 누르면 제보 조회가 아니라 로그인 화면으로.
    # 예전 비회원 제보를 찾을 때만 /lookup?old=1
    old_lookup = app.view_functions['lookup']
    def lookup_in_app(*a, **kw):
        from flask import g
        if in_app() and request.method == 'GET' and not g.get('user') and not request.args.get('old'):
            return redirect(url_for('login', next='/me'))
        return old_lookup(*a, **kw)
    app.view_functions['lookup'] = lookup_in_app
    wrap('home', app_home)
    if 'explore' in app.view_functions: wrap('explore', app_explore)
    wrap('companies_rank', app_rank)
    if S.GROUPS_ON: wrap('groups', app_groups)
    S.app_home, S.app_rank = app_home, app_rank
