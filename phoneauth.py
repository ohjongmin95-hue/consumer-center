"""휴대폰 번호로 시작하기 (/start/phone).

운영자 2026-11-03: 가입·로그인은 카카오 아니면 휴대폰 번호. 아이디·비밀번호 없이 문자 인증번호로.
- 번호를 넣으면 6자리 인증번호를 문자로 보냄 (알리고·솔라피, bizmsg.sms). 5분 안에 넣어야 하고 5번 틀리면 다시 받음.
- 그 번호로 인증한 회원이 있으면 바로 로그인. 없으면 닉네임(비우면 '고소한소보루27'처럼 자동)과 약관 동의만 받고 가입.
- 회원 정보의 phone_verified에 인증한 번호를 둠. 예전에 손으로 적은 번호(phone)만으로는 로그인되지 않음 (남의 번호를 적었을 수 있어서).
- 같은 번호로 1시간에 5번, 같은 곳(IP)에서 1시간에 10번까지만 보냄.
- 문자 키가 없으면 버튼을 숨김. 시험 서버는 PHONE_AUTH_TEST=1이면 인증번호를 화면에 띄움.
"""
import datetime, hashlib, hmac, os, secrets
import bizmsg
from flask import abort, flash, g, jsonify, redirect, render_template, request, session, url_for

CODE_MIN = 5
MAX_TRIES = 5
PER_PHONE = 5
PER_IP = 10


def install(S):
    app, conn, members, ui_text = S.app, S.conn, S.members, S.ui_text
    def ensure(db):
        db.execute('''CREATE TABLE IF NOT EXISTS phone_codes(id INTEGER PRIMARY KEY, phone TEXT NOT NULL, code_hash TEXT NOT NULL,
          expires TEXT NOT NULL, tries INTEGER NOT NULL DEFAULT 0, ip_hash TEXT NOT NULL DEFAULT '', created TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS phone_codes_phone ON phone_codes(phone, created)')
        if 'phone_verified' not in {r[1] for r in db.execute('PRAGMA table_info(users)')}:
            db.execute("ALTER TABLE users ADD COLUMN phone_verified TEXT NOT NULL DEFAULT ''")
        db.execute("CREATE INDEX IF NOT EXISTS users_phone_verified ON users(phone_verified)")
    with conn() as db: ensure(db)

    def now(): return datetime.datetime.now().isoformat(timespec='seconds')
    def ago(**kw): return (datetime.datetime.now() - datetime.timedelta(**kw)).isoformat(timespec='seconds')
    def digest(phone, code): return hmac.new(app.secret_key.encode() if isinstance(app.secret_key, str) else app.secret_key, (phone + ':' + code).encode(), hashlib.sha256).hexdigest()
    def test_mode(): return os.getenv('PHONE_AUTH_TEST') == '1'
    def phone_ready(): return test_mode() or (bizmsg.keys_ready() and bool(bizmsg.sender()))
    app.jinja_env.globals['phone_login_ready'] = phone_ready

    def view(step, **kw):
        return render_template('phone_start.html', step=step, phone=session.get('ph_phone', ''), next=session.get('ph_next', ''), min=CODE_MIN, **kw)

    @app.route('/start/phone', methods=['GET', 'POST'])
    def phone_start():
        if g.user: return redirect(S.safe_next())
        if not phone_ready() or not S.members_enabled(): abort(404)
        if request.method == 'GET':
            if request.args.get('next'): session['ph_next'] = S.safe_next()
            if request.args.get('again'): session.pop('ph_phone', None); session.pop('ph_ok', None)
            if session.get('ph_ok'): return view('join', nick='')
            return view('code' if session.get('ph_phone') else 'phone')
        if request.form.get('website'): abort(400)
        with conn() as db: ensure(db)  # 시험 서버처럼 DB 파일을 바꿔 끼운 경우에도
        step = request.form.get('step')
        if step == 'phone': return send_code()
        if step == 'code': return check_code()
        if step == 'join': return join()
        abort(400)

    def send_code():
        phone = members.kr_phone(request.form.get('phone', ''))
        if not phone:
            flash(ui_text('msg.phone_bad', '휴대폰 번호를 확인해 주세요. (예: 010-1234-5678)')); return view('phone'), 400
        with conn() as db:
            if db.execute('SELECT COUNT(*) FROM phone_codes WHERE phone=? AND created>=?', (phone, ago(hours=1))).fetchone()[0] >= PER_PHONE or \
               db.execute('SELECT COUNT(*) FROM phone_codes WHERE ip_hash=? AND created>=?', (S.ip_hash(), ago(hours=1))).fetchone()[0] >= PER_IP:
                flash(ui_text('msg.code_limit', '인증번호를 너무 많이 받았어요. 1시간 뒤 다시 해 주세요.')); return view('phone'), 429
            code = '%06d' % secrets.randbelow(1000000)
            db.execute('DELETE FROM phone_codes WHERE created<?', (ago(days=1),))
            db.execute('INSERT INTO phone_codes(phone,code_hash,expires,ip_hash,created) VALUES(?,?,?,?,?)',
                       (phone, digest(phone, code), (datetime.datetime.now() + datetime.timedelta(minutes=CODE_MIN)).isoformat(timespec='seconds'), S.ip_hash(), now()))
        text = '[%s] 인증번호 %s\n%d분 안에 입력해 주세요.' % (S.notify.site_name(), code, CODE_MIN)
        if test_mode() and not bizmsg.keys_ready(): flash('시험 서버라 문자 대신 여기에 보여요: ' + code)
        else:
            try: bizmsg.sms(phone, text)
            except Exception as e:
                app.logger.warning('phone code SMS failed: %s', str(e)[:160])
                flash(ui_text('msg.code_fail', '문자를 보내지 못했어요. 잠시 뒤 다시 해 주세요.')); return view('phone'), 502
        session['ph_phone'] = phone; session.pop('ph_ok', None)
        return redirect(url_for('phone_start'))

    # ── 앱 로그인 화면 (운영자 2026-11-13: 헤이마오 账号登录처럼 한 화면에서 번호·인증번호, 처음이면 바로 가입) ──
    @app.route('/start/phone/send', methods=['POST'])
    def phone_send_api():
        if not phone_ready() or not S.members_enabled(): return jsonify(ok=False, msg='지금은 휴대폰 로그인을 쓸 수 없어요.'), 404
        if request.form.get('website'): abort(400)
        with conn() as db: ensure(db)
        res = send_code()
        msgs = [m for m in session.pop('_flashes', []) if m]  # send_code가 남긴 안내를 JSON으로
        text = ' '.join(m[1] if isinstance(m, (list, tuple)) else str(m) for m in msgs)
        ok = session.get('ph_phone') == members.kr_phone(request.form.get('phone', ''))
        return jsonify(ok=ok, msg=text or ('인증번호를 보냈어요.' if ok else '인증번호를 보내지 못했어요.')), (200 if ok else 400)

    @app.route('/start/phone/verify', methods=['POST'])
    def phone_verify_api():
        if not phone_ready() or not S.members_enabled(): return jsonify(ok=False, msg='지금은 휴대폰 로그인을 쓸 수 없어요.'), 404
        phone = session.get('ph_phone', '')
        if not phone: return jsonify(ok=False, msg='먼저 인증번호를 받아 주세요.'), 400
        code = ''.join(c for c in request.form.get('code', '') if c.isdigit())
        nxt = request.form.get('next', '')
        nxt = nxt if nxt.startswith('/') and not nxt.startswith('//') else url_for('home')
        with conn() as db:
            row = db.execute('SELECT * FROM phone_codes WHERE phone=? ORDER BY id DESC LIMIT 1', (phone,)).fetchone()
            if not row or row['expires'] < now() or row['tries'] >= MAX_TRIES: return jsonify(ok=False, msg=ui_text('msg.code_expired', '인증번호가 만료됐어요. 다시 받아 주세요.')), 400
            if not hmac.compare_digest(row['code_hash'], digest(phone, code)):
                db.execute('UPDATE phone_codes SET tries=tries+1 WHERE id=?', (row['id'],))
                return jsonify(ok=False, msg=ui_text('msg.code_wrong', '인증번호가 맞지 않아요.')), 400
            user = db.execute("SELECT * FROM users WHERE phone_verified=? ORDER BY id LIMIT 1", (phone,)).fetchone()
            if user and user['status'] != 'active': return jsonify(ok=False, msg=ui_text('msg.m29', '이용이 제한된 계정이에요. 운영자에게 문의해 주세요.')), 403
            if not user:
                # 처음 쓰는 번호는 바로 가입 (약관·개인정보·만 14세 동의는 화면 아래 한 칸으로 받음)
                if not request.form.get('agree'): return jsonify(ok=False, msg='처음이면 아래 약관 동의에 체크해 주세요.', need_agree=True), 400
                if db.execute('SELECT COUNT(*) FROM users WHERE ip_hash=? AND created>=?', (S.ip_hash(), ago(hours=1))).fetchone()[0] >= 3:
                    return jsonify(ok=False, msg=ui_text('msg.m27', '잠시 후 다시 가입해 주세요.')), 429
                nick = members.auto_nickname(db)
                for _ in range(5):
                    login_id = 'p_' + secrets.token_hex(5)
                    if not db.execute('SELECT 1 FROM users WHERE login_id=?', (login_id,)).fetchone(): break
                cur = db.execute("INSERT INTO users(login_id,pw_hash,nickname,email,terms_version,agreed_at,ip_hash,created,phone,phone_verified) VALUES(?,'',?,'',?,?,?,?,?,?)",
                                 (login_id, nick, S.TERMS_VERSION, now(), S.ip_hash(), now(), phone, phone))
                user = db.execute('SELECT * FROM users WHERE id=?', (cur.lastrowid,)).fetchone()
                S.ad_event('signup', db)
                joined = True
            else:
                db.execute("UPDATE users SET failed=0,locked_until='',last_login=? WHERE id=?", (now(), user['id']))
                joined = False
            db.execute('DELETE FROM phone_codes WHERE phone=?', (phone,))
        for k in ('ph_phone', 'ph_ok', 'ph_next'): session.pop(k, None)
        S.sign_in(user, True)
        if joined: flash(user['nickname'] + ui_text('msg.welcome', '님, 가입을 환영해요!'))
        return jsonify(ok=True, go=nxt)

    def check_code():
        phone = session.get('ph_phone', '')
        code = ''.join(c for c in request.form.get('code', '') if c.isdigit())
        if not phone: return redirect(url_for('phone_start'))
        with conn() as db:
            row = db.execute('SELECT * FROM phone_codes WHERE phone=? ORDER BY id DESC LIMIT 1', (phone,)).fetchone()
            if not row or row['expires'] < now() or row['tries'] >= MAX_TRIES:
                flash(ui_text('msg.code_expired', '인증번호가 만료됐어요. 다시 받아 주세요.')); return view('code'), 400
            if not hmac.compare_digest(row['code_hash'], digest(phone, code)):
                db.execute('UPDATE phone_codes SET tries=tries+1 WHERE id=?', (row['id'],))
                flash(ui_text('msg.code_wrong', '인증번호가 맞지 않아요.')); return view('code'), 400
            db.execute('DELETE FROM phone_codes WHERE phone=?', (phone,))
            user = db.execute("SELECT * FROM users WHERE phone_verified=? ORDER BY id LIMIT 1", (phone,)).fetchone()
            if user:
                if user['status'] != 'active':
                    flash(ui_text('msg.m29', '이용이 제한된 계정이에요. 운영자에게 문의해 주세요.')); return view('phone'), 403
                db.execute("UPDATE users SET failed=0,locked_until='',last_login=? WHERE id=?", (now(), user['id']))
        if user:
            nxt = session.get('ph_next', '')
            S.sign_in(user, True)
            return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else url_for('home'))
        session['ph_ok'] = phone
        return redirect(url_for('phone_start'))

    def join():
        phone = session.get('ph_ok', '')
        if not phone: return redirect(url_for('phone_start'))
        nick = request.form.get('nickname', '').strip()
        with conn() as db:
            errors = [] if all(request.form.get(k) for k in ('agree_terms', 'agree_privacy', 'agree_age')) else [ui_text('msg.m17', '필수 동의 항목을 모두 확인해 주세요.')]
            if nick and S.nickname_error(db, nick): errors.append(S.nickname_error(db, nick))
            if not errors and db.execute('SELECT COUNT(*) FROM users WHERE ip_hash=? AND created>=?', (S.ip_hash(), ago(hours=1))).fetchone()[0] >= 3:
                errors.append(ui_text('msg.m27', '잠시 후 다시 가입해 주세요.'))
            if errors:
                for e in errors: flash(e)
                return view('join', nick=nick), 400
            nick = nick or members.auto_nickname(db)
            for _ in range(5):  # 휴대폰 회원도 아이디를 쓰지 않음. 겹치지 않는 내부 아이디만
                login_id = 'p_' + secrets.token_hex(5)
                if not db.execute('SELECT 1 FROM users WHERE login_id=?', (login_id,)).fetchone(): break
            cur = db.execute("INSERT INTO users(login_id,pw_hash,nickname,email,terms_version,agreed_at,ip_hash,created,phone,phone_verified) VALUES(?,'',?,'',?,?,?,?,?,?)",
                             (login_id, nick, S.TERMS_VERSION, now(), S.ip_hash(), now(), phone, phone))
            user = db.execute('SELECT * FROM users WHERE id=?', (cur.lastrowid,)).fetchone()
            S.ad_event('signup', db)
        nxt = session.get('ph_next', '')
        for k in ('ph_phone', 'ph_ok', 'ph_next'): session.pop(k, None)
        S.sign_in(user, True)
        flash(user['nickname'] + ui_text('msg.welcome', '님, 가입을 환영해요!'))
        return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') and nxt != '/' else url_for('mypage'))
