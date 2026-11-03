"""사기 전에 확인 (/check). 운영자 2026-11-03: 헤이마오 '먀오이옌(한눈에 보기)'처럼
업종별로 실제 제보에서 자주 나온 피해와 피하는 법을 정리한 글.
- 관리자 > 제보 > 사기 전에 확인 에서 글을 쓰고 고친 뒤 '공개'로 바꾸면 보인다.
- 'AI로 초안 쓰기'를 누르면 루나(GPT-6 Luna)가 그 업종의 실제 제보(유형별 건수, 가린 요약)를 보고 초안을 쓴다.
  업체 이름은 넣지 않고(단정·비방 방지) 소비자가 무엇을 확인하면 되는지 위주로.
- 글 아래에 그 업종 최근 1년 제보 유형 통계와 제보 목록 링크가 자동으로 붙는다.
"""
import datetime, os, re

from flask import abort, flash, redirect, render_template, request, url_for
from markupsafe import Markup, escape

MODEL = 'gpt-6-luna'
STATUSES = {'draft': '초안', 'published': '공개'}

PROMPT = """너는 소비자 피해 제보 사이트 {site}의 편집자다. '{industry}' 업종에서 물건·서비스를 사기 전에 소비자가 알아 두면 좋은 주의 글을 쓴다.
아래 [실제 제보 통계]와 [제보 요약]만 근거로 쓴다. 없는 사실·숫자는 지어내지 않는다.
- 업체·브랜드 이름은 쓰지 않는다. 특정 업체를 사기꾼처럼 단정하지 않는다.
- 해요체(~해요), 능동형, 쉬운 말. '~합니다', '되어요'(→ 돼요), '~시겠어요/~시나요' 같은 과한 경어, '잔액 부족으로' 같은 명사 나열은 쓰지 않는다(docs/ux-writing.md). 법 조문 번호나 어려운 말은 꼭 필요할 때만.
- 형식: 첫 줄은 제목(30자 안, '#' 없이). 빈 줄 다음 두세 문장 도입. 그다음 '## 자주 들어온 피해' (항목은 '- '로 3~5개, 각 한두 문장),
  '## 사기 전에 확인할 것' ('- '로 4~6개, 바로 해볼 수 있는 행동), '## 이미 피해를 봤다면' ('- '로 2~4개, 증거 남기기·업체에 먼저 요청·소비자제보센터에 제보 등).
- 전체 900자 안팎."""


def render_body(text):
    """'## 소제목', '- 항목', 빈 줄 문단만 쓰는 간단한 글을 HTML로. 나머지는 모두 글자 그대로(escape)."""
    # 운영자 2026-11-03: 토스 콘텐츠처럼. 소제목마다 묶고, 항목은 소제목 뜻에 따라 점·체크·번호 줄로
    out, items, head = [], [], ['']
    def flush():
        if not items: return
        h = head[0]
        kind = 'steps' if re.search(r'봤다면|했다면|당했다면|대처|이렇게', h) else 'check' if '확인' in h or '체크' in h else 'dots'
        tag = 'ol' if kind == 'steps' else 'ul'
        out.append('<%s class="ck-%s">%s</%s>' % (tag, kind, ''.join('<li><span>%s</span></li>' % escape(i) for i in items), tag)); items.clear()
    sec = False
    for line in (text or '').splitlines():
        t = line.strip()
        if t.startswith('- '): items.append(t[2:].strip()); continue
        flush()
        if not t: continue
        if t.startswith('## '):
            if sec: out.append('</section>')
            head[0] = t[3:].strip(); sec = True
            out.append('<section class="ck-sec"><h2><i class="tf" aria-hidden="true">%s</i>%s</h2>' % (sec_emoji(head[0]), escape(head[0])))
        else: out.append('<p>%s</p>' % escape(t))
    flush()
    if sec: out.append('</section>')
    return Markup(''.join(out))


IND_EMOJI = (('식품', '🍔'), ('외식', '🍔'), ('의약', '💊'), ('의료', '💊'), ('쇼핑', '🛍️'), ('유통', '🛍️'), ('가전', '💻'), ('전자', '💻'),
             ('자동차', '🚗'), ('통신', '📱'), ('인터넷', '📱'), ('금융', '💳'), ('보험', '💳'), ('게임', '🎮'), ('앱', '🎮'),
             ('건설', '🏠'), ('인테리어', '🏠'), ('여행', '✈️'), ('항공', '✈️'))


def ind_emoji(name):
    """운영자 2026-11-03: 글씨만 있으면 아쉬움 → 업종마다 토스페이스 그림 하나 (모르는 업종은 상자)."""
    return next((e for k, e in IND_EMOJI if k in (name or '')), '📦')


def sec_emoji(head):
    return '🛡️' if re.search(r'봤다면|했다면|당했다면|대처', head) else '🔍' if '확인' in head or '체크' in head else '🚨'


def excerpt(text, n=90):
    t = ' '.join(l.strip() for l in (text or '').splitlines() if l.strip() and not l.strip().startswith(('## ', '- ')))
    return t[:n] + ('…' if len(t) > n else '')


def install(S):
    app, conn, desk = S.app, S.conn, S.companydesk
    with conn() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS buy_guides(id INTEGER PRIMARY KEY,industry TEXT NOT NULL DEFAULT '',title TEXT NOT NULL,body TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',created TEXT NOT NULL,updated TEXT NOT NULL)""")

    def now(): return datetime.datetime.now().isoformat(timespec='seconds')

    def stats(db, industry):
        since = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
        rows = db.execute("SELECT category,COUNT(*) AS n FROM cases WHERE industry=? AND created>=? AND " + S.PUBLIC_VALID + " GROUP BY category ORDER BY n DESC",
                          (industry, since)).fetchall()
        by = {}
        for r in rows:
            m = S.cat_split(r['category']); k = m[0] if m else r['category']
            by[k] = by.get(k, 0) + r['n']
        return sorted(by.items(), key=lambda x: -x[1])

    app.jinja_env.filters['guide_body'] = render_body
    app.jinja_env.filters['ind_emoji'] = ind_emoji

    @app.route('/check')
    def check_list():
        ind = request.args.get('ind', '')
        inds = S.report_industries()
        if ind not in inds: ind = ''
        with conn() as db:
            rows = db.execute("SELECT * FROM buy_guides WHERE status='published'" + (' AND industry=?' if ind else '') + ' ORDER BY updated DESC', (ind,) if ind else ()).fetchall()
            have = {r[0] for r in db.execute("SELECT DISTINCT industry FROM buy_guides WHERE status='published'")}
        guides = [dict(r, excerpt=excerpt(r['body'])) for r in rows]
        return render_template('check_list.html', guides=guides, ind=ind, inds=[i for i in inds if i in have])

    @app.route('/check/<int:gid>')
    def check_page(gid):
        with conn() as db:
            r = db.execute('SELECT * FROM buy_guides WHERE id=?', (gid,)).fetchone()
            if not r or (r['status'] != 'published' and not S.admin_active()): abort(404)
            st = stats(db, r['industry']) if r['industry'] else []
            more = db.execute("SELECT id,title,industry FROM buy_guides WHERE status='published' AND id!=? ORDER BY (industry=?) DESC,updated DESC LIMIT 4", (gid, r['industry'])).fetchall()
        return render_template('check_page.html', g_=r, stats=st, top=max([n for _, n in st] + [1]), more=more)

    def draft(industry):
        key = os.getenv('OPENAI_API_KEY', '').strip()
        if not key: raise RuntimeError('OpenAI 키가 없어요.')
        with conn() as db:
            st = stats(db, industry)
            cases = db.execute("SELECT category,subject,public_subject,description FROM cases WHERE industry=? AND " + S.PUBLIC_VALID + " ORDER BY id DESC LIMIT 25", (industry,)).fetchall()
        if not cases: raise RuntimeError('이 업종 제보가 아직 없어요.')
        text = '[실제 제보 통계 (최근 1년, 유형: 건수)]\n' + '\n'.join('%s: %d' % x for x in st)
        text += '\n\n[제보 요약]\n' + '\n'.join('- (%s) %s / %s' % (c['category'], desk.scrub(S.mask_personal(c['public_subject'] or c['subject'])), desk.scrub(S.mask_personal(c['description']))[:220]) for c in cases)
        model = os.getenv('CHECK_MODEL', '').strip() or MODEL
        opts = {'max_completion_tokens': 3000, 'reasoning_effort': 'low'} if re.match(r'(gpt-([5-9]|\d\d)|o\d)', model) else {'max_tokens': 1500, 'temperature': 0.4}
        body = {'model': model, **opts, 'messages': [{'role': 'system', 'content': PROMPT.format(site=S.notify.site_name(), industry=industry)}, {'role': 'user', 'content': text}]}
        st_code, res = desk.post_json('https://api.openai.com/v1/chat/completions', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, 60)
        if st_code != 200: raise RuntimeError('AI 오류 %s' % st_code)
        out = (res['choices'][0]['message']['content'] or '').strip()
        title, _, rest = out.partition('\n')
        return title.strip().lstrip('#').strip()[:60] or industry + ' 사기 전에 확인', rest.strip()

    @app.route('/admin/check', methods=['GET', 'POST'])
    @S.admin_only
    def admin_check():
        if request.method == 'POST':
            ind = request.form.get('industry', '')
            if ind not in S.report_industries(): flash('업종을 골라 주세요.'); return redirect(url_for('admin_check'))
            if request.form.get('ai'):
                try: title, body = draft(ind)
                except Exception as e: flash('AI 초안을 못 만들었어요: %s' % str(e)[:80]); return redirect(url_for('admin_check'))
            else: title, body = ind + ' 사기 전에 확인', ''
            with conn() as db:
                gid = db.execute('INSERT INTO buy_guides(industry,title,body,created,updated) VALUES(?,?,?,?,?)', (ind, title, body, now(), now())).lastrowid
            flash('초안을 만들었어요. 읽어 보고 고친 뒤 공개해 주세요.')
            return redirect(url_for('admin_check_edit', gid=gid))
        with conn() as db: rows = db.execute('SELECT * FROM buy_guides ORDER BY updated DESC').fetchall()
        return render_template('admin_check.html', rows=rows, inds=S.report_industries(), statuses=STATUSES, ai=bool(os.getenv('OPENAI_API_KEY', '').strip()))

    @app.route('/admin/check/<int:gid>', methods=['GET', 'POST'])
    @S.admin_only
    def admin_check_edit(gid):
        with conn() as db:
            r = db.execute('SELECT * FROM buy_guides WHERE id=?', (gid,)).fetchone()
            if not r: abort(404)
            if request.method == 'POST':
                act = request.form.get('act')
                if act == 'delete':
                    db.execute('DELETE FROM buy_guides WHERE id=?', (gid,)); flash('지웠어요.'); return redirect(url_for('admin_check'))
                ind = request.form.get('industry', '') if request.form.get('industry', '') in S.report_industries() else r['industry']
                status = request.form.get('status') if request.form.get('status') in STATUSES else r['status']
                title = ' '.join((request.form.get('title') or r['title']).split())[:80]
                db.execute('UPDATE buy_guides SET industry=?,title=?,body=?,status=?,updated=? WHERE id=?', (ind, title, (request.form.get('body') or '')[:8000], status, now(), gid))
                flash('저장했어요.'); return redirect(url_for('admin_check_edit', gid=gid))
        return render_template('admin_check_edit.html', r=r, inds=S.report_industries(), statuses=STATUSES)
