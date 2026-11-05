"""소보루 매거진 에디터 (운영자 2026-11-05).

- 기사마다 쓴 에디터 이름을 붙임 ('소보루 에디터' 대신 '에디터 이지우'). 따로 고르지 않은 기사는 에디터들이 번갈아 맡음
- 에디터 계정: 관리자 > 소보루 매거진 > 에디터에서 만들고, 에디터는 /editor/login 으로 들어와 기사를 쓰고 '승인 요청'
- 승인: 에디터가 올린 기사(승인 대기)를 관리자가 게시하거나 돌려보냄
- 통계: 기사·분야·에디터별 조회수
"""
import datetime
import functools
import re

from flask import abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

FIRST_EDITORS = ['이지우', '오후']  # 운영자 2026-11-05: 지금 쓴 글들은 두 에디터가 번갈아


def install(S):
    app, conn = S.app, S.conn

    def stamp(): return datetime.datetime.now().isoformat(timespec='seconds')

    with conn() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS mag_editors(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, login TEXT UNIQUE,
            pw_hash TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, ver INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL)''')
        db.execute('CREATE TABLE IF NOT EXISTS article_editor(article_id INTEGER PRIMARY KEY, editor_id INTEGER NOT NULL)')
        if not db.execute('SELECT 1 FROM mag_editors').fetchone():
            for n in FIRST_EDITORS: db.execute('INSERT INTO mag_editors(name,created) VALUES(?,?)', (n, stamp()))

    # ---- 기사 ↔ 에디터 ------------------------------------------------------------
    def editors(active_only=False):
        with conn() as db:
            return db.execute('SELECT * FROM mag_editors' + (' WHERE active=1' if active_only else '') + ' ORDER BY id').fetchall()

    def editor_of(article_id):
        """기사를 쓴 에디터 (따로 정한 사람, 없으면 첫 에디터들이 번호 순서로 번갈아)."""
        with conn() as db:
            row = db.execute('SELECT e.* FROM article_editor a JOIN mag_editors e ON e.id=a.editor_id WHERE a.article_id=?', (article_id,)).fetchone()
            if row: return row
            base = db.execute('SELECT * FROM mag_editors WHERE name IN (%s) ORDER BY id' % ','.join('?' * len(FIRST_EDITORS)), FIRST_EDITORS).fetchall() \
                or db.execute('SELECT * FROM mag_editors WHERE active=1 ORDER BY id').fetchall()
        return base[(int(article_id) - 1) % len(base)] if base else None

    def editor_name(article_id):
        e = editor_of(article_id)
        return e['name'] if e else '소보루 매거진'

    def set_editor(article_id, editor_id):
        with conn() as db:
            if db.execute('SELECT 1 FROM mag_editors WHERE id=?', (editor_id,)).fetchone():
                db.execute('INSERT OR REPLACE INTO article_editor VALUES(?,?)', (article_id, editor_id))

    # ---- 에디터 로그인 -------------------------------------------------------------
    def me():
        """지금 로그인한 에디터 (관리자는 None)."""
        if 'me_editor' in g: return g.me_editor
        eid, ver = session.get('mag_editor'), session.get('mag_editor_v')
        row = None
        if eid:
            with conn() as db: row = db.execute('SELECT * FROM mag_editors WHERE id=? AND active=1', (eid,)).fetchone()
            if not row or row['ver'] != ver: session.pop('mag_editor', None); session.pop('mag_editor_v', None); row = None
        g.me_editor = row
        return row

    def editor_mode():
        """에디터로 매거진 관리자를 쓰는 중 (관리자 로그인은 아님)."""
        return bool(g.get('mag_editor_pass')) and me() is not None

    app.jinja_env.globals.update(mag_editor_name=editor_name, mag_editor_of=editor_of, mag_editors=editors, mag_me_editor=lambda: me() if editor_mode() else None)

    def editor_only(f):
        """에디터 화면: 에디터나 관리자. 에디터면 이 요청 동안만 매거진 관리자 틀을 씀."""
        @functools.wraps(f)
        def wrapped(*a, **kw):
            if S.admin_active(): return f(*a, **kw)
            if not me(): return redirect(url_for('editor_login'))
            g.mag_editor_pass = True
            return f(*a, **kw)
        return wrapped

    @app.route('/editor/login', methods=['GET', 'POST'])
    def editor_login():
        if request.method == 'POST':
            if S.too_many_attempts('editor'):
                flash('로그인을 너무 많이 시도했어요. 10분 뒤 다시 해 주세요.'); return render_template('mag_editor_login.html'), 429
            login = request.form.get('login', '').strip().lower()
            with conn() as db: row = db.execute('SELECT * FROM mag_editors WHERE login=? AND active=1', (login,)).fetchone()
            if row and row['pw_hash'] and check_password_hash(row['pw_hash'], request.form.get('password', '')):
                session['mag_editor'] = row['id']; session['mag_editor_v'] = row['ver']
                return redirect(url_for('mag_mine'))
            S.note_attempt('editor'); flash('아이디나 비밀번호가 맞지 않아요.')
        return render_template('mag_editor_login.html')

    @app.route('/editor/logout', methods=['POST'])
    def editor_logout():
        session.pop('mag_editor', None); session.pop('mag_editor_v', None)
        return redirect(url_for('editor_login'))

    @app.route('/editor')
    def editor_home(): return redirect(url_for('mag_mine'))

    # ---- 에디터가 쓰는 기사 화면: 관리자 기사 화면을 그대로 쓰되, 게시는 '승인 요청'으로 -------------
    def wrap(endpoint):
        old = app.view_functions[endpoint]

        def view(*a, **kw):
            if S.admin_active():
                resp = old(*a, **kw)
                if request.method == 'POST' and request.form.get('editor_id', '').isdigit():
                    aid = kw.get('article_id') or _aid(resp)
                    if aid and request.form.get('act') != 'delete': set_editor(aid, int(request.form['editor_id']))
                return resp
            e = me()
            if not e: return old(*a, **kw)  # 로그인 화면으로
            aid = kw.get('article_id')
            if endpoint == 'admin_life' and request.method == 'GET' and not request.args.get('new'): return redirect(url_for('mag_mine'))
            if aid:
                ed = editor_of(aid)
                with conn() as db: st = db.execute('SELECT status FROM articles WHERE id=?', (aid,)).fetchone()
                if not st or not ed or ed['id'] != e['id'] or st['status'] not in ('draft', 'pending'):
                    flash('내가 쓴 초안과 승인 대기 기사만 고칠 수 있어요.'); return redirect(url_for('mag_mine'))
            if request.method == 'POST' and request.form.get('act') in ('delete', 'schedule', 'unpublish'): abort(403)
            g.mag_editor_pass = True
            want = request.method == 'POST' and (request.form.get('act') == 'publish' or request.form.get('publish'))
            resp = old(*a, **kw) if not want else _as_pending(old, a, kw)
            if request.method == 'POST':
                aid = aid or _aid(resp)
                if aid:
                    set_editor(aid, e['id'])
                    with conn() as db: db.execute('UPDATE articles SET featured=0 WHERE id=?', (aid,))
            return resp
        view.__name__ = old.__name__
        app.view_functions[endpoint] = view

    def _aid(resp):
        m = re.search(r'/admin/life/(\d+)', resp.headers.get('Location', '') if hasattr(resp, 'headers') else '')
        return int(m[1]) if m else None

    def _as_pending(old, a, kw):
        """에디터의 '승인 요청': 초안으로 저장한 뒤 상태만 승인 대기로."""
        form = request.form.copy(); form.pop('publish', None)
        if form.get('act') == 'publish': form['act'] = 'save'
        request.form = form  # noqa: 이 요청 안에서만
        resp = old(*a, **kw)
        aid = kw.get('article_id') or _aid(resp)
        if aid:
            with conn() as db: db.execute("UPDATE articles SET status='pending',published_at=NULL,updated=? WHERE id=? AND status IN ('draft','pending')", (stamp(), aid))
            session.pop('_flashes', None); flash('승인을 요청했어요. 편집장이 확인하면 게시돼요.')
        return resp

    wrap('admin_life'); wrap('admin_life_edit')
    if 'mag_body_upload' in app.view_functions:  # 본문 사진 올리기
        up = app.view_functions['mag_body_upload']
        def body_upload():
            if S.admin_active(): return up()
            if not me(): abort(403)
            g.mag_editor_pass = True
            return up()
        app.view_functions['mag_body_upload'] = body_upload

    # ---- 내 기사 (에디터) ----------------------------------------------------------
    @app.route('/admin/magazine/mine')
    @editor_only
    def mag_mine():
        e = me() if editor_mode() else None
        with conn() as db:
            rows = db.execute('SELECT id,title,status,category,published_at,created,views FROM articles ORDER BY id DESC LIMIT 500').fetchall()
        if e: rows = [r for r in rows if (editor_of(r['id']) or {'id': 0})['id'] == e['id']]
        return render_template('mag_admin_mine.html', rows=rows, who=e)

    # ---- 승인 (관리자) ------------------------------------------------------------
    @app.route('/admin/magazine/approve', methods=['GET', 'POST'])
    @S.admin_only
    def mag_approve():
        if request.method == 'POST':
            aid = request.form.get('id', type=int); act = request.form.get('act')
            with conn() as db:
                if act == 'ok':
                    db.execute("UPDATE articles SET status='published',published_at=?,updated=? WHERE id=? AND status='pending'", (stamp(), stamp(), aid)); flash('승인해서 게시했어요.')
                elif act == 'back':
                    db.execute("UPDATE articles SET status='draft',updated=? WHERE id=? AND status='pending'", (stamp(), aid)); flash('에디터에게 돌려보냈어요. 초안으로 남아 있어요.')
            return redirect(url_for('mag_approve'))
        with conn() as db: rows = db.execute("SELECT id,title,summary,category,updated FROM articles WHERE status='pending' ORDER BY updated").fetchall()
        return render_template('mag_admin_approve.html', rows=rows)

    def pending_count():
        with conn() as db: return db.execute("SELECT COUNT(*) FROM articles WHERE status='pending'").fetchone()[0]
    app.jinja_env.globals['mag_pending'] = pending_count

    # ---- 에디터 관리 (관리자) -------------------------------------------------------
    @app.route('/admin/magazine/editors', methods=['GET', 'POST'])
    @S.admin_only
    def mag_editors_admin():
        if request.method == 'POST':
            act = request.form.get('act'); eid = request.form.get('id', type=int)
            name = request.form.get('name', '').strip()[:20]
            login = request.form.get('login', '').strip().lower()[:40]
            pw = request.form.get('password', '')
            if login and not re.fullmatch(r'[a-z0-9_.-]{3,40}', login): flash('아이디는 영어 소문자·숫자로 3자 이상 적어 주세요.'); return redirect(url_for('mag_editors_admin'))
            if pw and len(pw) < 6: flash('비밀번호는 6자 이상으로 정해 주세요.'); return redirect(url_for('mag_editors_admin'))
            with conn() as db:
                try:
                    if act == 'add':
                        if not name: flash('에디터 이름을 적어 주세요.'); return redirect(url_for('mag_editors_admin'))
                        db.execute('INSERT INTO mag_editors(name,login,pw_hash,created) VALUES(?,?,?,?)', (name, login or None, generate_password_hash(pw) if pw else '', stamp()))
                        flash(f'에디터 {name} 계정을 만들었어요.')
                    elif act == 'save' and eid:
                        cur = db.execute('SELECT * FROM mag_editors WHERE id=?', (eid,)).fetchone()
                        if not cur: abort(404)
                        db.execute('UPDATE mag_editors SET name=?,login=?,pw_hash=?,ver=? WHERE id=?',
                                   (name or cur['name'], login or cur['login'], generate_password_hash(pw) if pw else cur['pw_hash'], cur['ver'] + (1 if pw else 0), eid))
                        flash('저장했어요.')
                    elif act in ('off', 'on') and eid:
                        db.execute('UPDATE mag_editors SET active=?,ver=ver+1 WHERE id=?', (1 if act == 'on' else 0, eid))
                        flash('계정을 멈췄어요. 이미 쓴 기사의 이름은 그대로예요.' if act == 'off' else '계정을 다시 켰어요.')
                except Exception:
                    flash('같은 이름이나 아이디가 이미 있어요.')
            return redirect(url_for('mag_editors_admin'))
        rows = editors()
        with conn() as db: ids = [r[0] for r in db.execute("SELECT id FROM articles WHERE status='published'")]
        count = {}
        for i in ids:
            e = editor_of(i)
            if e: count[e['id']] = count.get(e['id'], 0) + 1
        return render_template('mag_admin_editors.html', rows=rows, count=count, login_url=url_for('editor_login', _external=True))

    # ---- 통계 (관리자) ------------------------------------------------------------
    @app.route('/admin/magazine/stats')
    @S.admin_only
    def mag_stats():
        with conn() as db:
            arts = db.execute("SELECT id,title,category,views,published_at FROM articles WHERE status='published' ORDER BY views DESC").fetchall()
        total = sum(r['views'] or 0 for r in arts)
        by_cat, by_ed = {}, {}
        for r in arts:
            c = by_cat.setdefault(r['category'], [0, 0]); c[0] += 1; c[1] += r['views'] or 0
            n = editor_name(r['id']); d = by_ed.setdefault(n, [0, 0]); d[0] += 1; d[1] += r['views'] or 0
        return render_template('mag_admin_stats.html', total=total, n=len(arts), top=arts[:10],
                               by_cat=sorted(by_cat.items(), key=lambda x: -x[1][1]), by_ed=sorted(by_ed.items(), key=lambda x: -x[1][1]))
