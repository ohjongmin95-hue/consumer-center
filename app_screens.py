"""소보루고발 앱 전용 화면 (운영자 2026-11-11: 헤이마오터우쑤 기능을 앱에, 배치는 헤이마오·세부는 토스 TDS).

앱(사용자 에이전트 'SoboruApp/버전 (ios|android)')으로 소비자고발제보센터 주소를 열었을 때만 바뀌고, 웹사이트는 그대로다.
- 홈(/): 헤이마오 首页. 전체·오늘 고발 숫자 + 고발하기, 최근 기업 답변·해결 한 줄, 사기 전에 확인해 보세요(瞄一眼, /check 글),
  함께 대응하고 있어요(集体投诉, /groups), 고발 목록 탭(인기·최신·답변 완료·해결됨).
- 기업 순위(/companies/rank): 헤이마오 红黑榜. 업종별 2열 카드에 잘 답하는 곳·아쉬운 곳·답변 빠른 곳(回复效率).
- 공동 대응(/groups): 모인 사람 수 순·최신 순 카드.
이모지는 토스페이스(앱 바닥글에 출처). 버튼은 #CE6719.
"""
import datetime

from flask import render_template, request

TABS = {'hot': '인기', 'new': '최신', 'answer': '답변 완료', 'done': '해결됨'}
RANK_TABS = {'good': '잘 답하는 곳', 'bad': '아쉬운 곳', 'fast': '답변 빠른 곳'}
CARD_N = 5      # 업종 카드 한 장에 보이는 기업 수
ONE_IND_N = 10  # 업종 하나만 볼 때
WANTS = ('환불', '교환', '수리', '해지', '배상', '보상', '사과', '취소', '재발 방지')  # 공동 대응 '요구' 태그: 관련 고발의 요청 사항에 이 말이 있으면


def install(S):
    app = S.app
    jebo = S.jebo

    def in_app():
        try: is_sb = app.jinja_env.globals['is_soboru']()
        except Exception: is_sb = False
        return bool(S.appready.app_client()) and not is_sb

    app.jinja_env.globals['app_jebo'] = in_app

    # ── 홈 ─────────────────────────────────────────────
    def ticker(db):
        """최근에 실제로 일어난 좋은 소식 한 줄씩: 기업이 답했거나, 제보자가 해결됐다고 알린 고발."""
        out = []
        for r in db.execute("""SELECT c.id,c.company,c.company_hidden,c.company_id,MAX(m.created) AS at FROM messages m JOIN cases c ON c.id=m.case_id
                WHERE m.author='기업 답변' AND m.public=1 AND c.public_consent=1 AND c.published=1 GROUP BY c.id ORDER BY at DESC LIMIT 6"""):
            co = S.pub_company(r); out.append((r['at'], co[:1], f"{co}이(가) 고발에 답했어요", r['id'], 'ans'))
        for r in db.execute("""SELECT c.id,c.company,c.company_hidden,c.confirmed_at AS at,u.nickname FROM cases c LEFT JOIN users u ON u.id=c.user_id AND u.status='active'
                WHERE c.outcome='resolved' AND c.public_consent=1 AND c.published=1
                AND COALESCE(c.confirmed_at,'')<>'' ORDER BY c.confirmed_at DESC LIMIT 6"""):
            nick = r['nickname'] or '소비자'
            out.append((r['at'], nick[:1], f"{S.pub_company(r)} 고발 해결됐어요, 고마워요!", r['id'], 'done'))
        out.sort(key=lambda x: x[0] or '', reverse=True)
        return out[:6]

    def guides(db):
        try:
            rows = db.execute("SELECT id,industry,title,updated FROM buy_guides WHERE status='published' ORDER BY updated DESC LIMIT 3").fetchall()
        except Exception: return []
        new = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        emo = app.jinja_env.filters.get('ind_emoji', lambda x: '📦')
        return [dict(id=r['id'], title=r['title'], emo=emo(r['industry']), new=(r['updated'] or '') >= new) for r in rows]

    def open_groups(db, limit=2):
        if not S.GROUPS_ON: return []
        return db.execute("""SELECT g.id,g.title,g.company,(SELECT COUNT(*) FROM group_members m WHERE m.group_id=g.id) AS n
            FROM damage_groups g WHERE g.status IN ('open','active') ORDER BY n DESC,g.id DESC LIMIT ?""", (limit,)).fetchall()

    def home_list(tab):
        if tab == 'hot': rows = S.report_rows(order=S.HOT_ORDER, limit=6)
        elif tab in ('answer', 'done'): rows = S.report_rows(S.REPORT_STAGES[tab][1], (), 6)
        else: rows = S.report_rows(limit=6)
        # 헤이마오 목록처럼 글쓴이(닉네임·얼굴)와 공감·댓글 수를 붙임. 사진은 템플릿에서 og_photo로 (가린 사본만)
        ids = [r['no'] for r in rows]
        if ids:
            with S.conn() as db:
                who = {r['id']: r for r in db.execute("SELECT c.id,u.id AS uid,u.nickname FROM cases c LEFT JOIN users u ON u.id=c.user_id AND u.status='active' WHERE c.id IN (%s)" % ','.join('?' * len(ids)), ids)}
            for r in rows:
                w = who.get(r['no']); r['uid'] = w['uid'] if w else None; r['nick'] = (w['nickname'] if w else '') or ''
        return rows

    def app_home():
        tab = request.args.get('t', 'hot')
        if tab not in TABS: tab = 'hot'
        with S.conn() as db:
            data = dict(tick=ticker(db), guides=guides(db), groups=open_groups(db))
        return render_template('app_home.html', summary=S.report_summary(), tab=tab, tabs=TABS, cases=home_list(tab), **data)

    # ── 기업 순위 ────────────────────────────────────────
    def ranked(db):
        rows = db.execute("""SELECT co.*,(SELECT c.industry FROM cases c WHERE c.company_id=co.id AND c.industry!='' GROUP BY c.industry ORDER BY COUNT(*) DESC LIMIT 1) AS top_ind
            FROM companies co WHERE co.status IN ('active','listed') AND EXISTS(SELECT 1 FROM cases c WHERE c.company_id=co.id AND c.forwarded_at!='')""").fetchall()
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
        with S.conn() as db: items = ranked(db)
        picked = rank_pick(items, tab)
        cards = []
        for i in ([ind] if ind else inds):
            rows = [x for x in picked if x[0]['top_ind'] == i][:ONE_IND_N if ind else CARD_N]
            if rows: cards.append((i, rows))
        return render_template('app_rank.html', cards=cards, tab=tab, tabs=RANK_TABS, ind=ind, inds=inds, n=len(items),
                               min_n=jebo.MIN_N, days=jebo.ANSWER_DAYS, fmt_hours=jebo.fmt_hours)

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

    wrap('home', app_home)
    wrap('companies_rank', app_rank)
    if S.GROUPS_ON: wrap('groups', app_groups)
    S.app_home, S.app_rank = app_home, app_rank
