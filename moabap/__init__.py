"""모아밥: 핀하오판식 모아배달 (운영자 2026-11-11).

가게가 전용 세트를 고정 공급가로 올리고, 손님은 도착 시간(슬롯)과 받는 곳(건물 로비·단지 정문)을 골라 주문한다.
마감 시간이 지나면 같은 슬롯·같은 받는 곳 주문이 한 묶음이 되어 배달대행 한 명이 한 번에 돌린다.
- 손님: /  /set/<id>  /order(POST)  /o/<code>
- 가게: /s/<token>  (시간별로 만들 수량, '다 만들었어요')
- 운영자: /admin  (묶음·입금 확인·픽업·도착), /admin/menu (가게·세트·받는 곳·시간)
결제: PG 계약 전에는 계좌이체(MOABAP_BANK) + 운영자가 입금 확인. 리뷰 앱은 나중 (운영자: 핀하오판 국내판부터).

소보루 서버(app.py) 안에서 따로 돈다: MOABAP_HOST 주소로 들어오면 이 앱이 받고,
MOABAP_PREVIEW=1이면 아무 주소의 /moabap 아래에서도 열린다 (도메인 연결 전 확인용). DB는 따로 (MOABAP_DB).
"""
import contextlib
import datetime
import hmac
import os
import re
import secrets
import sqlite3
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

BASE = Path(__file__).parent
STEPS = ('wait', 'paid', 'ready', 'picked', 'done')  # 입금 대기 → 주문 확정 → 조리 완료 → 픽업 → 도착
STEP_NAMES = {'wait': '입금 확인 중', 'paid': '주문 확정', 'ready': '조리 완료', 'picked': '배달 중', 'done': '도착', 'cancel': '취소'}
CATS = [('한식', '🍱'), ('분식', '🌶️'), ('면', '🍜'), ('덮밥', '🍚'), ('버거', '🍔'), ('중식', '🥡'), ('샐러드', '🥗'), ('치킨', '🍗'), ('카페', '🧋')]
PRICES = (5900, 7900, 9900)
SCHEMA = """
CREATE TABLE IF NOT EXISTS shops(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT DEFAULT '', hygiene TEXT DEFAULT '', token TEXT UNIQUE, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS sets(id INTEGER PRIMARY KEY, shop_id INTEGER, name TEXT NOT NULL, cat TEXT DEFAULT '한식', emoji TEXT DEFAULT '🍱',
  price INTEGER NOT NULL, orig INTEGER DEFAULT 0, supply INTEGER DEFAULT 0, cap INTEGER DEFAULT 50, cook_min INTEGER DEFAULT 15, note TEXT DEFAULT '', active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS places(id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT DEFAULT '오피스', note TEXT DEFAULT '', active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS slots(id INTEGER PRIMARY KEY, at TEXT NOT NULL, cutoff INTEGER DEFAULT 40, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, code TEXT UNIQUE, day TEXT, slot TEXT, place_id INTEGER, detail TEXT DEFAULT '',
  set_id INTEGER, qty INTEGER DEFAULT 1, unit INTEGER, discount INTEGER DEFAULT 0, amount INTEGER, name TEXT, phone TEXT, memo TEXT DEFAULT '',
  status TEXT DEFAULT 'wait', created TEXT, paid_at TEXT DEFAULT '', done_at TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS orders_day ON orders(day, slot);
CREATE INDEX IF NOT EXISTS orders_phone ON orders(phone);
"""


def now():
    return datetime.datetime.now()


def won(n):
    return f'{int(n or 0):,}원'


def phone_norm(p):
    d = re.sub(r'\D', '', p or '')
    return d if re.fullmatch(r'01\d{8,9}', d) else ''


def create_app(db_path=None):
    moa = Flask(__name__, template_folder=str(BASE / 'templates'), static_folder=str(BASE / 'static'), static_url_path='/static')
    moa.secret_key = os.getenv('SECRET_KEY') or secrets.token_hex(32)
    moa.config.update(SESSION_COOKIE_NAME='moabap', SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.getenv('HTTPS_ONLY') == '1')
    DB = Path(db_path or os.getenv('MOABAP_DB', str(BASE.parent / 'moabap.sqlite3')))
    FIRST_COUPON = int(os.getenv('MOABAP_FIRST_COUPON', '2000'))
    AREA = os.getenv('MOABAP_AREA', '광교중앙역 주변')

    @contextlib.contextmanager
    def conn():
        db = sqlite3.connect(DB, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def init():
        with conn() as db:
            db.executescript(SCHEMA)
            have = {r[1] for r in db.execute('PRAGMA table_info(shops)')}
            for col in ('owner', 'biz_no', 'address'):  # 통신판매중개: 판매자(가게) 정보 표시
                if col not in have:
                    db.execute(f"ALTER TABLE shops ADD COLUMN {col} TEXT DEFAULT ''")
            if not db.execute('SELECT 1 FROM slots').fetchone():  # 처음: 점심·저녁 30분 간격 (운영자가 /admin/menu에서 바꿈)
                db.executemany('INSERT INTO slots(at,cutoff) VALUES(?,40)', [(t,) for t in ('12:00', '12:30', '13:00', '18:00', '18:30', '19:00')])
    init()
    moa.conn = conn

    # ── 공통 ─────────────────────────────────────────
    def csrf():
        if '_csrf' not in session:
            session['_csrf'] = secrets.token_urlsafe(24)
        return session['_csrf']

    @moa.before_request
    def check_csrf():
        if request.method == 'POST' and not (session.get('_csrf') and hmac.compare_digest(request.form.get('_csrf', ''), session['_csrf'])):
            abort(400, '화면을 새로고침한 뒤 다시 해 주세요.')

    @moa.context_processor
    def ctx():
        return dict(csrf=csrf, won=won, area=AREA, step_names=STEP_NAMES, bank=os.getenv('MOABAP_BANK', ''),
                    biz=os.getenv('MOABAP_BIZ', ''), contact=os.getenv('MOABAP_CONTACT', ''), first_coupon=FIRST_COUPON, cats=CATS)

    def slot_dt(day, at):
        h, m = map(int, at.split(':'))
        return datetime.datetime.combine(day, datetime.time(h, m))

    def open_slots(db, day=None):
        """주문 받을 수 있는 시간: 오늘 마감 전인 것. 오늘 다 지났으면 내일 것."""
        t = now()
        rows = db.execute('SELECT * FROM slots WHERE active=1 ORDER BY at').fetchall()
        for d in ([day] if day else [t.date(), t.date() + datetime.timedelta(days=1)]):
            out = [dict(r, day=d.isoformat(), close=slot_dt(d, r['at']) - datetime.timedelta(minutes=r['cutoff'])) for r in rows]
            out = [s for s in out if s['close'] > t]
            if out:
                return out
        return []

    def joined(db, day):
        """세트별 오늘 모인 사람 수 (취소 빼고)."""
        return {r[0]: r[1] for r in db.execute("SELECT set_id,COUNT(DISTINCT phone) FROM orders WHERE day=? AND status!='cancel' GROUP BY set_id", (day,))}

    def again_rate(db):
        """세트별 재주문율: 두 번 이상 시킨 사람 / 시킨 사람. 10명 이상일 때만."""
        out = {}
        for r in db.execute("SELECT set_id,COUNT(*) AS n,SUM(c>=2) AS a FROM (SELECT set_id,phone,COUNT(*) AS c FROM orders WHERE status!='cancel' GROUP BY set_id,phone) GROUP BY set_id"):
            if r['n'] >= 10:
                out[r['set_id']] = round(100 * r['a'] / r['n'])
        return out

    def sets_q(db, where='1=1', args=()):
        return db.execute(f'SELECT s.*,h.name AS shop,h.hygiene,h.owner,h.biz_no,h.address FROM sets s JOIN shops h ON h.id=s.shop_id WHERE s.active=1 AND h.active=1 AND {where} ORDER BY s.sort,s.id', args).fetchall()

    # ── 손님 ─────────────────────────────────────────
    @moa.get('/')
    def home():
        cat, price = request.args.get('cat', ''), request.args.get('p', type=int)
        with conn() as db:
            slots = open_slots(db)
            day = slots[0]['day'] if slots else now().date().isoformat()
            allsets = sets_q(db)
            items = [s for s in allsets if (not cat or s['cat'] == cat) and (not price or s['price'] == price)]
            data = dict(sets=items, joined=joined(db, day), again=again_rate(db), next_slot=slots[0] if slots else None,
                        cats_on=[c for c in CATS if any(s['cat'] == c[0] for s in allsets)], prices=[p for p in PRICES if any(s['price'] == p for s in allsets)])
        return render_template('moa_home.html', cat=cat, price=price, **data)

    @moa.get('/set/<int:sid>')
    def set_page(sid):
        with conn() as db:
            rows = sets_q(db, 's.id=?', (sid,))
            if not rows:
                abort(404)
            s = rows[0]
            slots = open_slots(db)
            day = slots[0]['day'] if slots else ''
            counts = {r[0]: r[1] for r in db.execute("SELECT slot,COUNT(*) FROM orders WHERE day=? AND status!='cancel' GROUP BY slot", (day,))}
            left = {r[0]: s['cap'] - r[1] for r in db.execute("SELECT slot,COALESCE(SUM(qty),0) FROM orders WHERE day=? AND set_id=? AND status!='cancel' GROUP BY slot", (day, sid))}
            places = db.execute('SELECT * FROM places WHERE active=1 ORDER BY kind,name').fetchall()
            j = joined(db, day).get(sid, 0)
            again = again_rate(db).get(sid)
        return render_template('moa_set.html', tomorrow=bool(slots) and slots[0]['day'] != now().date().isoformat(), s=s, slots=slots, counts=counts, left=left, places=places, joined=j, again=again)

    @moa.post('/order')
    def order():
        f = request.form
        phone = phone_norm(f.get('phone'))
        name = (f.get('name') or '').strip()[:20]
        detail = (f.get('detail') or '').strip()[:60]
        qty = max(1, min(3, f.get('qty', type=int) or 1))
        sid = f.get('set_id', type=int)
        back = url_for('set_page', sid=sid or 0)
        if not (phone and name and f.get('agree')):
            flash('이름, 휴대폰 번호, 개인정보 동의를 확인해 주세요.')
            return redirect(back)
        with conn() as db:
            rows = sets_q(db, 's.id=?', (sid,))
            place = db.execute('SELECT * FROM places WHERE id=? AND active=1', (f.get('place_id', type=int),)).fetchone()
            slot = next((x for x in open_slots(db) if x['at'] == f.get('slot')), None)
            if not rows or not place or not slot:
                flash('도착 시간이 마감됐거나 받는 곳이 없어요. 다시 골라 주세요.')
                return redirect(back)
            s = rows[0]
            used = db.execute("SELECT COALESCE(SUM(qty),0) FROM orders WHERE day=? AND slot=? AND set_id=? AND status!='cancel'", (slot['day'], slot['at'], sid)).fetchone()[0]
            if used + qty > s['cap']:
                flash('이 시간은 다 팔렸어요. 다른 시간을 골라 주세요.')
                return redirect(back)
            first = not db.execute("SELECT 1 FROM orders WHERE phone=? AND status!='cancel'", (phone,)).fetchone()
            disc = FIRST_COUPON if first else 0
            code = secrets.token_urlsafe(6).replace('-', 'x').replace('_', 'y')
            db.execute('INSERT INTO orders(code,day,slot,place_id,detail,set_id,qty,unit,discount,amount,name,phone,memo,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (code, slot['day'], slot['at'], place['id'], detail, sid, qty, s['price'], disc, max(0, s['price'] * qty - disc), name, phone,
                        (f.get('memo') or '').strip()[:100], now().isoformat(timespec='seconds')))
        mine = session.get('orders', [])
        session['orders'] = ([code] + [c for c in mine if c != code])[:20]
        return redirect(url_for('order_page', code=code))

    @moa.get('/o/<code>')
    def order_page(code):
        with conn() as db:
            o = db.execute('SELECT o.*,s.name AS set_name,s.emoji,h.name AS shop,p.name AS place FROM orders o JOIN sets s ON s.id=o.set_id JOIN shops h ON h.id=s.shop_id JOIN places p ON p.id=o.place_id WHERE o.code=?', (code,)).fetchone()
            if not o:
                abort(404)
            together = db.execute("SELECT COUNT(*) FROM orders WHERE day=? AND slot=? AND place_id=? AND status!='cancel'", (o['day'], o['slot'], o['place_id'])).fetchone()[0]
            cutoff = db.execute('SELECT cutoff FROM slots WHERE at=?', (o['slot'],)).fetchone()
        close = slot_dt(datetime.date.fromisoformat(o['day']), o['slot']) - datetime.timedelta(minutes=cutoff[0] if cutoff else 40)
        return render_template('moa_order.html', o=o, together=together, close=close, closed=now() >= close)

    @moa.get('/orders')
    def my_orders():
        codes = session.get('orders', [])
        with conn() as db:
            rows = db.execute(f"SELECT o.*,s.name AS set_name,s.emoji FROM orders o JOIN sets s ON s.id=o.set_id WHERE o.code IN ({','.join('?' * len(codes))}) ORDER BY o.id DESC", codes).fetchall() if codes else []
        return render_template('moa_orders.html', rows=rows)

    @moa.get('/refund')
    def refund():
        return render_template('moa_refund.html')

    @moa.get('/privacy')
    def privacy():
        return render_template('moa_privacy.html')

    # ── 가게 ─────────────────────────────────────────
    @moa.route('/s/<token>', methods=['GET', 'POST'])
    def shop_page(token):
        with conn() as db:
            shop = db.execute('SELECT * FROM shops WHERE token=? AND active=1', (token,)).fetchone()
            if not shop:
                abort(404)
            day = request.values.get('day') or now().date().isoformat()
            if request.method == 'POST':  # 이 시간 몫을 다 만들었어요 → 확정된 주문을 조리 완료로
                db.execute("UPDATE orders SET status='ready' WHERE day=? AND slot=? AND status='paid' AND set_id IN (SELECT id FROM sets WHERE shop_id=?)", (day, request.form.get('slot'), shop['id']))
                flash(f"{request.form.get('slot')} 도착분을 조리 완료로 바꿨어요.")
                return redirect(url_for('shop_page', token=token, day=day))
            rows = db.execute("""SELECT o.slot,s.name,SUM(o.qty) AS n,SUM(o.status='paid') AS todo,s.supply FROM orders o JOIN sets s ON s.id=o.set_id
                WHERE o.day=? AND s.shop_id=? AND o.status IN ('paid','ready','picked','done') GROUP BY o.slot,s.id ORDER BY o.slot""", (day, shop['id'])).fetchall()
        by = {}
        for r in rows:
            by.setdefault(r['slot'], []).append(r)
        return render_template('moa_shop.html', shop=shop, day=day, by=by, total=sum(r['n'] * r['supply'] for r in rows))

    # ── 운영자 ───────────────────────────────────────
    def admin_ok():
        return session.get('moa_admin') is True

    @moa.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        pw = os.getenv('MOABAP_ADMIN_PASSWORD', '')
        if request.method == 'POST':
            if pw and hmac.compare_digest(request.form.get('pw', ''), pw):
                session['moa_admin'] = True
                return redirect(url_for('admin'))
            flash('비밀번호가 맞지 않아요.' if pw else '서버에 MOABAP_ADMIN_PASSWORD가 아직 없어요.')
        return render_template('moa_login.html')

    @moa.before_request
    def guard():
        if request.path.startswith('/admin') and request.endpoint != 'admin_login' and not admin_ok():
            return redirect(url_for('admin_login'))

    @moa.route('/admin', methods=['GET', 'POST'])
    def admin():
        day = request.values.get('day') or now().date().isoformat()
        with conn() as db:
            if request.method == 'POST':
                act, ids = request.form.get('act'), request.form.getlist('id', type=int)
                q = ','.join('?' * len(ids))
                if ids and act == 'paid':
                    db.execute(f"UPDATE orders SET status='paid',paid_at=? WHERE status='wait' AND id IN ({q})", [now().isoformat(timespec='seconds')] + ids)
                elif ids and act in ('ready', 'picked', 'done'):
                    db.execute(f"UPDATE orders SET status=?,done_at=CASE WHEN ?='done' THEN ? ELSE done_at END WHERE status IN ('paid','ready','picked') AND id IN ({q})",
                               [act, act, now().isoformat(timespec='seconds')] + ids)
                elif ids and act == 'cancel':
                    db.execute(f"UPDATE orders SET status='cancel' WHERE id IN ({q})", ids)
                return redirect(url_for('admin', day=day))
            rows = db.execute("""SELECT o.*,s.name AS set_name,h.name AS shop,p.name AS place,p.kind FROM orders o JOIN sets s ON s.id=o.set_id JOIN shops h ON h.id=s.shop_id
                JOIN places p ON p.id=o.place_id WHERE o.day=? ORDER BY o.slot,p.name,o.id""", (day,)).fetchall()
        slots = {}
        for r in rows:
            slots.setdefault(r['slot'], {}).setdefault(r['place'], []).append(r)
        live = [r for r in rows if r['status'] != 'cancel']
        stat = dict(n=len(live), paid=sum(r['status'] != 'wait' for r in live), amount=sum(r['amount'] for r in live if r['status'] != 'wait'),
                    batches=len({(r['slot'], r['place']) for r in live}))
        return render_template('moa_admin.html', day=day, slots=slots, stat=stat)

    @moa.route('/admin/menu', methods=['GET', 'POST'])
    def admin_menu():
        with conn() as db:
            if request.method == 'POST':
                f, kind = request.form, request.form.get('kind')
                if kind == 'shop':
                    vals = (f['name'].strip(), f.get('phone', ''), f.get('hygiene', ''), f.get('owner', '').strip(), f.get('biz_no', '').strip(), f.get('address', '').strip())
                    if f.get('id'):
                        db.execute('UPDATE shops SET name=?,phone=?,hygiene=?,owner=?,biz_no=?,address=? WHERE id=?', vals + (f.get('id', type=int),))
                    else:
                        db.execute('INSERT INTO shops(name,phone,hygiene,owner,biz_no,address,token) VALUES(?,?,?,?,?,?,?)', vals + (secrets.token_urlsafe(12),))
                elif kind == 'set':
                    vals = (f.get('shop_id', type=int), f['name'].strip(), f.get('cat', '한식'), f.get('emoji') or '🍱', f.get('price', type=int) or 0, f.get('orig', type=int) or 0,
                            f.get('supply', type=int) or 0, f.get('cap', type=int) or 50, f.get('cook_min', type=int) or 15, f.get('note', ''))
                    if f.get('id'):
                        db.execute('UPDATE sets SET shop_id=?,name=?,cat=?,emoji=?,price=?,orig=?,supply=?,cap=?,cook_min=?,note=? WHERE id=?', vals + (f.get('id', type=int),))
                    else:
                        db.execute('INSERT INTO sets(shop_id,name,cat,emoji,price,orig,supply,cap,cook_min,note) VALUES(?,?,?,?,?,?,?,?,?,?)', vals)
                elif kind == 'place':
                    db.execute('INSERT INTO places(name,kind,note) VALUES(?,?,?)', (f['name'].strip(), f.get('pkind', '오피스'), f.get('note', '')))
                elif kind == 'slot' and re.fullmatch(r'\d\d:\d\d', f.get('at', '')):
                    db.execute('INSERT INTO slots(at,cutoff) VALUES(?,?)', (f['at'], f.get('cutoff', type=int) or 40))
                elif kind == 'toggle' and f.get('table') in ('shops', 'sets', 'places', 'slots'):
                    db.execute(f"UPDATE {f['table']} SET active=1-active WHERE id=?", (f.get('id', type=int),))
                return redirect(url_for('admin_menu') + '#' + (kind or ''))
            data = {t: db.execute(f'SELECT * FROM {t} ORDER BY {o}').fetchall() for t, o in (('shops', 'id'), ('places', 'kind,name'), ('slots', 'at'))}
            data['sets'] = db.execute('SELECT s.*,h.name AS shop FROM sets s LEFT JOIN shops h ON h.id=s.shop_id ORDER BY s.sort,s.id').fetchall()
        return render_template('moa_menu.html', edit=request.args.get('edit', type=int), eshop=request.args.get('eshop', type=int), **data)

    @moa.get('/admin/logout')
    def admin_logout():
        session.pop('moa_admin', None)
        return redirect(url_for('home'))

    @moa.errorhandler(404)
    def nf(e):
        return render_template('moa_msg.html', title='찾는 화면이 없어요', body='주소를 다시 확인해 주세요.'), 404

    @moa.errorhandler(400)
    def bad(e):
        return render_template('moa_msg.html', title='다시 해 주세요', body=getattr(e, 'description', '')), 400

    return moa


def mount(main_wsgi):
    """소보루 서버 앞에서 주소를 보고 나눔: MOABAP_HOST로 오면 모아밥, MOABAP_PREVIEW=1이면 /moabap 아래도 모아밥."""
    hosts = {h.strip().lower() for x in os.getenv('MOABAP_HOST', '').split(',') if x.strip() for h in (x, 'www.' + x.strip())}
    preview = os.getenv('MOABAP_PREVIEW') == '1'
    if not hosts and not preview:
        return main_wsgi
    moa = create_app()
    moa_wsgi = moa.wsgi_app
    if os.getenv('TRUST_PROXY') == '1':
        from werkzeug.middleware.proxy_fix import ProxyFix
        moa_wsgi = ProxyFix(moa_wsgi, x_for=1, x_proto=1, x_host=1)

    def app(environ, start_response):
        host = (environ.get('HTTP_X_FORWARDED_HOST') or environ.get('HTTP_HOST') or '').split(',')[0].split(':')[0].strip().lower()
        if host in hosts:
            return moa_wsgi(environ, start_response)
        path = environ.get('PATH_INFO', '')
        if preview and (path == '/moabap' or path.startswith('/moabap/')):
            if hosts:  # 도메인을 연결한 뒤에는 /moabap 주소(앱 첫 화면 포함)를 새 주소로 넘김
                q = environ.get('QUERY_STRING', '')
                loc = 'https://' + sorted(hosts, key=len)[0] + (path[len('/moabap'):] or '/') + ('?' + q if q else '')
                start_response('302 Found', [('Location', loc), ('Content-Length', '0')])
                return [b'']
            environ = dict(environ, SCRIPT_NAME=environ.get('SCRIPT_NAME', '') + '/moabap', PATH_INFO=path[len('/moabap'):] or '/')
            return moa_wsgi(environ, start_response)
        return main_wsgi(environ, start_response)
    return app
