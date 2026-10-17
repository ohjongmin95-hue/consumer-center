"""앱 포장 준비: 서비스 워커·오프라인 화면, 앱 링크 확인 파일, 회원 알림함, 웹 푸시.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 주소를 붙인다.
- /sw.js: 정적 파일(/static, 주소에 v= 붙은 것)만 캐시하고, 화면은 늘 서버에서 받되 끊기면 /offline 안내만 보여 줌.
  회원 화면·관리자 화면·글 내용은 기기에 저장하지 않는다 (개인정보가 휴대폰 캐시에 남지 않게).
- /.well-known/assetlinks.json: 안드로이드 앱(TWA)이 이 사이트 주인임을 확인하는 파일. ANDROID_SHA256이 없으면 404.
- /.well-known/apple-app-site-association: 나중에 아이폰 앱의 유니버설 링크용. APPLE_TEAM_ID가 없으면 404.
- 알림함(/me/alerts): 내 글 댓글, 내 질문 답변, 답변한 질문 해결, 회원으로 접수한 제보의 진행 소식.
- 웹 푸시: VAPID 키(VAPID_PUBLIC_KEY·VAPID_PRIVATE_KEY·VAPID_SUBJECT, deploy/set-push.sh)가 있을 때만 켜짐.
  구독 정보(브라우저가 준 주소·암호 키)만 저장하고, 탈퇴하거나 구독을 끄면 바로 지운다.
"""
import datetime, json, os, re, threading
from flask import Response, abort, after_this_request, g, has_request_context, jsonify, redirect, render_template, request, url_for

ASYNC = True  # 푸시는 뒤에서 보냄 (시험에서는 끔)
ANDROID_DEFAULT = 'kr.co.consumerjebo.soboru'
FINGERPRINT_RE = re.compile(r'^([0-9A-F]{2}:){31}[0-9A-F]{2}$')
B64URL_RE = re.compile(r'^[A-Za-z0-9_\-=]{8,200}$')
ALERT_KEEP_DAYS = 90
ALERT_PAGE = 50
SUBS_PER_USER = 10
CASE_EVENTS = {'status': ('alert.case_status', '내 제보 진행 단계가 바뀌었어요'), 'company': ('alert.case_company', '내 제보에 기업 답변이 도착했어요'),
               'message': ('alert.case_message', '소보루가 내 제보에 메시지를 남겼어요')}
ALERT_ICONS = {'comment': 'chat', 'answer': 'chat', 'solved': 'check', 'case': 'doc'}


def env(name, default=''): return os.getenv(name, '').strip() or default
def push_ready(): return bool(env('VAPID_PUBLIC_KEY') and env('VAPID_PRIVATE_KEY'))
def android_fingerprints():
    return [f for f in (x.strip().upper() for x in env('ANDROID_SHA256').split(',')) if FINGERPRINT_RE.match(f)]


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS member_alerts(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,kind TEXT NOT NULL,body TEXT NOT NULL,link TEXT NOT NULL DEFAULT '',
        created TEXT NOT NULL,read_at TEXT NOT NULL DEFAULT '')''')
    db.execute('CREATE INDEX IF NOT EXISTS member_alerts_user ON member_alerts(user_id,read_at)')
    db.execute('''CREATE TABLE IF NOT EXISTS push_subscriptions(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,endpoint TEXT NOT NULL UNIQUE,p256dh TEXT NOT NULL,auth TEXT NOT NULL,
        created TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS push_subscriptions_user ON push_subscriptions(user_id)')


def webpush_send(sub, payload, log):
    """푸시 한 건 보내기 → (보냄, 구독을 지울지). 시험에서 바꿔 끼운다."""
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        log.warning('웹 푸시 보내기 생략: pywebpush가 설치돼 있지 않아요 (pip install -r requirements.txt)'); return False, False
    try:
        webpush(subscription_info={'endpoint': sub['endpoint'], 'keys': {'p256dh': sub['p256dh'], 'auth': sub['auth']}}, data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=env('VAPID_PRIVATE_KEY'), vapid_claims={'sub': env('VAPID_SUBJECT', 'mailto:help@consumerjebo.co.kr')}, ttl=86400, timeout=10)
        return True, False
    except WebPushException as e:
        code = getattr(getattr(e, 'response', None), 'status_code', 0)
        return False, code in (404, 410)  # 브라우저가 구독을 끊었으면 지움
    except Exception as e:  # 네트워크 오류 등: 알림함에는 남아 있으니 기록만
        log.warning('웹 푸시 실패: %s', type(e).__name__); return False, False


def install(S):
    app = S.app; conn = S.conn; now = S.now; ui_text = S.ui_text
    with conn() as db: migrate(db)
    log = app.logger

    def run_later(fn):
        if ASYNC: threading.Thread(target=fn, daemon=True).start()
        else: fn()

    def send_push(uid, payload):
        with conn() as db: subs = db.execute('SELECT * FROM push_subscriptions WHERE user_id=?', (uid,)).fetchall()
        gone = []
        for sub in subs:
            ok, drop = webpush_send(sub, payload, log)
            if drop: gone.append(sub['id'])
        if gone:
            with conn() as db: db.executemany('DELETE FROM push_subscriptions WHERE id=?', [(i,) for i in gone])

    def push_payload(body, link): return {'title': S.notify.site_name(), 'body': body, 'url': link or '/me/alerts'}

    def keep_since(): return (datetime.datetime.now() - datetime.timedelta(days=ALERT_KEEP_DAYS)).isoformat(timespec='seconds')

    def member_alert(db, uid, kind, body, link='', push=True):
        """알림함에 한 줄 넣기. 푸시가 켜져 있으면 저장(커밋)이 끝난 뒤 그 회원 기기로도 보냄."""
        if not uid: return
        db.execute('INSERT INTO member_alerts(user_id,kind,body,link,created) VALUES(?,?,?,?,?)', (uid, kind, body[:200], link[:300], now()))
        db.execute('DELETE FROM member_alerts WHERE created<?', (keep_since(),))  # 90일 지난 알림은 파기 (개인정보 처리방침)
        if not push or not push_ready(): return
        payload = push_payload(body, link)
        if has_request_context():
            @after_this_request
            def go(resp):
                run_later(lambda: send_push(uid, payload)); return resp
        else: run_later(lambda: send_push(uid, payload))
    S.member_alert = member_alert

    def case_alert(case, event):
        """회원 계정에 연결된 제보의 진행 소식 (제보 알림 notify_later가 커밋 뒤에 부름)."""
        if not case['user_id'] or event not in CASE_EVENTS: return
        key, default = CASE_EVENTS[event]
        body = f"{ui_text(key, default)}: {(case['subject'] or '')[:40]}"
        link = url_for('my_case', case_id=case['id']) if has_request_context() else ''
        with conn() as db: member_alert(db, case['user_id'], 'case', body, link, push=False)
        if push_ready(): run_later(lambda: send_push(case['user_id'], push_payload(body, link)))
    S.case_alert = case_alert

    def delete_app_extras(db, uid):
        # 탈퇴: 알림함·푸시 구독을 바로 지움
        db.execute('DELETE FROM member_alerts WHERE user_id=?', (uid,))
        db.execute('DELETE FROM push_subscriptions WHERE user_id=?', (uid,))
    S.delete_app_extras = delete_app_extras

    def alert_unread():
        """머리글 종 모양에 붙는 안 읽은 알림 수 (요청마다 한 번만 셈)."""
        if not has_request_context() or not g.get('user'): return 0
        if 'alert_unread' not in g:
            with conn() as db: g.alert_unread = db.execute("SELECT COUNT(*) FROM member_alerts WHERE user_id=? AND read_at=''", (g.user['id'],)).fetchone()[0]
        return g.alert_unread
    app.jinja_env.globals.update(alert_unread=alert_unread, push_on=push_ready, push_public_key=lambda: env('VAPID_PUBLIC_KEY') if push_ready() else '', ALERT_ICONS=ALERT_ICONS)

    # ---- 서비스 워커·오프라인 화면 ----------------------------------------------
    @app.route('/sw.js')
    def service_worker():
        # 사이트 전체(/)를 맡는 서비스 워커. 디자인 버전(css_v)이 바뀌면 캐시 이름도 바뀌어 예전 파일을 지움
        src = (S.BASE / 'static' / 'sw.js').read_text(encoding='utf-8').replace('__VERSION__', app.jinja_env.globals.get('css_v', '1'))
        resp = Response(src, mimetype='application/javascript')
        resp.headers['Service-Worker-Allowed'] = '/'; resp.headers['Cache-Control'] = 'no-cache'
        return resp

    @app.route('/offline')
    def offline():
        # 인터넷이 끊겼을 때 서비스 워커가 보여 주는 화면. 회원 정보가 없는 단독 화면이라 기기에 저장해도 안전
        resp = app.make_response(render_template('offline.html'))
        resp.headers['Cache-Control'] = 'no-cache'
        return resp

    # ---- 앱 링크 확인 파일 ----------------------------------------------------
    @app.route('/.well-known/assetlinks.json')
    def assetlinks():
        fps = android_fingerprints()
        if not fps: abort(404)
        data = [{'relation': ['delegate_permission/common.handle_all_urls'],
                 'target': {'namespace': 'android_app', 'package_name': env('ANDROID_PACKAGE', ANDROID_DEFAULT), 'sha256_cert_fingerprints': fps}}]
        resp = Response(json.dumps(data, indent=2), mimetype='application/json')
        resp.headers['Cache-Control'] = 'public, max-age=3600'
        return resp

    @app.route('/.well-known/apple-app-site-association')
    def apple_app_site_association():
        team = env('APPLE_TEAM_ID')
        if not re.fullmatch(r'[A-Z0-9]{10}', team): abort(404)
        app_id = f"{team}.{env('IOS_BUNDLE_ID', ANDROID_DEFAULT)}"
        skip = [{'/': p, 'exclude': True} for p in ('/admin*', '/reporter*', '/biz*', '/staff*')]  # 운영 화면은 앱 대신 브라우저로
        data = {'applinks': {'details': [{'appIDs': [app_id], 'components': skip + [{'/': '*'}]}]}, 'webcredentials': {'apps': [app_id]}}
        resp = Response(json.dumps(data), mimetype='application/json')
        resp.headers['Cache-Control'] = 'public, max-age=3600'
        return resp

    # ---- 알림함 ---------------------------------------------------------------
    @app.route('/me/alerts')
    @S.member_only
    def me_alerts():
        uid = g.user['id']
        with conn() as db:
            db.execute('DELETE FROM member_alerts WHERE user_id=? AND created<?', (uid, keep_since()))
            rows = db.execute('SELECT * FROM member_alerts WHERE user_id=? ORDER BY created DESC,id DESC LIMIT ?', (uid, ALERT_PAGE)).fetchall()
            db.execute("UPDATE member_alerts SET read_at=? WHERE user_id=? AND read_at=''", (now(), uid))  # 열어 보면 모두 읽음
            subs = db.execute('SELECT COUNT(*) FROM push_subscriptions WHERE user_id=?', (uid,)).fetchone()[0]
        g.alert_unread = 0
        return render_template('me_alerts.html', rows=rows, subs=subs)

    @app.route('/me/alerts/go/<int:alert_id>')
    @S.member_only
    def alert_go(alert_id):
        with conn() as db: row = db.execute('SELECT link FROM member_alerts WHERE id=? AND user_id=?', (alert_id, g.user['id'])).fetchone()
        link = row['link'] if row else ''
        return redirect(link if link.startswith('/') and not link.startswith('//') else url_for('me_alerts'))

    # ---- 웹 푸시 구독 ---------------------------------------------------------
    @app.route('/me/push/subscribe', methods=['POST'])
    @S.member_only
    def push_subscribe():
        if not push_ready(): return jsonify(ok=False, error=ui_text('push.off', '지금은 푸시 알림을 쓸 수 없어요.')), 503
        f = {k: request.form.get(k, '').strip() for k in ('endpoint', 'p256dh', 'auth')}
        if not (f['endpoint'].startswith('https://') and len(f['endpoint']) <= 600 and B64URL_RE.match(f['p256dh']) and B64URL_RE.match(f['auth'])):
            return jsonify(ok=False, error=ui_text('push.bad', '이 브라우저에서는 푸시 알림을 켤 수 없어요.')), 400
        with conn() as db:
            db.execute('DELETE FROM push_subscriptions WHERE endpoint=?', (f['endpoint'],))  # 같은 기기에서 다른 회원으로 로그인하면 새 회원에게 옮김
            db.execute('INSERT INTO push_subscriptions(user_id,endpoint,p256dh,auth,created) VALUES(?,?,?,?,?)', (g.user['id'], f['endpoint'], f['p256dh'], f['auth'], now()))
            db.execute('DELETE FROM push_subscriptions WHERE user_id=? AND id NOT IN (SELECT id FROM push_subscriptions WHERE user_id=? ORDER BY id DESC LIMIT ?)', (g.user['id'], g.user['id'], SUBS_PER_USER))
        return jsonify(ok=True)

    @app.route('/me/push/unsubscribe', methods=['POST'])
    @S.member_only
    def push_unsubscribe():
        endpoint = request.form.get('endpoint', '').strip()
        with conn() as db:
            if endpoint: db.execute('DELETE FROM push_subscriptions WHERE user_id=? AND endpoint=?', (g.user['id'], endpoint))
            else: db.execute('DELETE FROM push_subscriptions WHERE user_id=?', (g.user['id'],))  # 이 브라우저 정보가 없으면 내 기기 전부 끔
        return jsonify(ok=True)
