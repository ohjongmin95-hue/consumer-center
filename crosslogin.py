"""소비자제보센터(consumerjebo.co.kr)와 소보루(soboru.co.kr) 로그인 하나로 (운영자 요청 2026-10-17).

회원 저장소는 원래 하나라 두 사이트 어디서든 같은 아이디로 가입·로그인한다. 다만 주소가 달라 로그인 쿠키는 따로 붙으므로,
한쪽에서 로그인(가입·소셜 로그인 포함)하면 다른 쪽에도 일회용 표(1분, 한 번만)를 넘겨 함께 로그인시킨다. 로그아웃도 같이.

  A에서 로그인 → B /sso/begin (B에 상태값 저장) → A /sso/issue (표 발급) → B /sso/in (상태값·표 확인 후 로그인) → A 원래 화면
"""
import datetime, hashlib, secrets, urllib.parse

from flask import abort, g, redirect, request, session

TICKET_SECONDS = 60


def install(S):
    app = S.app; conn = S.conn

    with conn() as db:
        db.execute('CREATE TABLE IF NOT EXISTS sso_tickets(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,expires TEXT NOT NULL)')

    def host(): return request.host.split(':')[0].lower().removeprefix('www.')

    def sites():
        # 서로 표를 주고받는 두 주소: 대표 주소(소보루)와 서버 설정 JEBO_HOST. 이 둘 말고는 표를 보내지 않음
        jebo = sorted(h for h in S.JEBO_HOSTS if not h.startswith('www.'))
        main = S.main_host()
        return (main, jebo[0]) if jebo and main not in S.JEBO_HOSTS else ()

    def partner():
        pair = sites()
        return pair[1] if pair and host() == pair[0] else pair[0] if pair and host() == pair[1] else ''

    def back_ok(url):
        # 돌아갈 주소는 상대 사이트(https)의 경로만
        p = urllib.parse.urlsplit(url or '')
        return p.scheme == 'https' and p.netloc == partner() and (p.path or '/').startswith('/') and not p.path.startswith('//')

    def here(path):
        return 'https://' + host() + path

    def to_partner(path, **q):
        return redirect('https://' + partner() + path + '?' + urllib.parse.urlencode(q))

    @app.after_request
    def follow_partner(resp):
        # 이 요청에서 로그인·로그아웃했으면 상대 사이트도 맞춰 줌 (표를 받아 로그인한 요청은 다시 넘기지 않음)
        if not partner() or g.get('sso_hop') or resp.status_code not in (301, 302, 303): return resp
        loc = resp.headers.get('Location', '/')
        back = loc if loc.startswith('https://') else here(loc if loc.startswith('/') else '/')
        if urllib.parse.urlsplit(back).netloc != host(): return resp
        if g.get('signed_in'): return to_partner('/sso/begin', back=back)
        if g.get('signed_out'): return to_partner('/sso/out', back=back)
        return resp

    @app.route('/sso/begin')
    def sso_begin():
        # 표를 받을 쪽: 이 브라우저에서 시작했다는 표시를 남기고 로그인한 쪽에 표를 달라고 함
        back = request.args.get('back', '')
        if not back_ok(back): abort(404)
        state = secrets.token_urlsafe(16); session['sso_state'] = state
        return to_partner('/sso/issue', s=state, back=back)

    @app.route('/sso/issue')
    def sso_issue():
        if not partner(): abort(404)
        back = request.args.get('back', '')
        if urllib.parse.urlsplit(back).netloc != host(): back = here('/')
        if not g.get('user'): return redirect(back)
        token = secrets.token_urlsafe(32)
        expires = (datetime.datetime.now() + datetime.timedelta(seconds=TICKET_SECONDS)).isoformat(timespec='seconds')
        with conn() as db:
            db.execute('DELETE FROM sso_tickets WHERE expires<?', (S.now(),))
            db.execute('INSERT INTO sso_tickets(token_hash,user_id,expires) VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), g.user['id'], expires))
        return to_partner('/sso/in', t=token, s=request.args.get('s', '')[:64], back=back)

    @app.route('/sso/in')
    def sso_in():
        back = request.args.get('back', '')
        if not back_ok(back): abort(404)
        g.sso_hop = True
        # 남이 만든 표로 남의 계정에 로그인되지 않게: 이 브라우저에서 시작한 상태값과 같아야 함
        state = session.pop('sso_state', None)
        token_hash = hashlib.sha256(request.args.get('t', '').encode()).hexdigest()
        with conn() as db:
            row = db.execute('SELECT * FROM sso_tickets WHERE token_hash=?', (token_hash,)).fetchone()
            db.execute('DELETE FROM sso_tickets WHERE token_hash=?', (token_hash,))
            ok = row and row['expires'] >= S.now() and state and secrets.compare_digest(str(state), request.args.get('s', ''))
            user = db.execute("SELECT * FROM users WHERE id=? AND status='active'", (row['user_id'],)).fetchone() if ok else None
        if user: S.sign_in(user, True)
        return redirect(back)

    @app.route('/sso/out')
    def sso_out():
        back = request.args.get('back', '')
        if not back_ok(back): abort(404)
        g.sso_hop = True
        for k in ('uid', 'uv', 'case_id'): session.pop(k, None)
        return redirect(back)
