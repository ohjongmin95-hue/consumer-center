"""믿고가게: 광고나 이벤트 없는 진짜 후기 (운영자 2026-11-15).

가게에 붙은 스티커 QR(/q/<번호>)을 찍고 24시간 안에 쓴 후기에는 '방문 인증'이 붙는다.
따종디앤핑식 동네 랭킹 + Yelp식 사장님 답글. 독립 플랫폼이라 화면에 다른 회사·언론 이름을 넣지 않는다.
- 손님: /  /s/<id>  /s/<id>/review  /q/<번호>(스티커)  /about  /join
- 사장님: /owner/<token> (후기 보기·답글·가게 정보)
- 운영자: /admin (가게·후기·신고·신청·설정·스티커)
원칙: 사장님은 후기를 지울 수 없고 신고만. 별점이 낮은 후기(기본 3점 이하)는 사장님께 먼저(기본 48시간) 보여 준 뒤 공개.
       돈을 내도 별점·순서·랭킹은 바뀌지 않는다. 체험단·후기 이벤트 금지.
소보루 서버(app.py) 안에서 따로 돈다: MITGO_HOST 주소로 오면 이 앱, MITGO_PREVIEW=1이면 /mitgo 아래에서도 열림. DB는 따로 (MITGO_DB).
"""
import contextlib
import datetime
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, send_from_directory, session, url_for

BASE = Path(__file__).parent
CATS = [('미용', '💇'), ('세탁', '🧺'), ('운동', '🏋️'), ('수리', '🔧'), ('학원', '📚'), ('병원·약국', '🏥'), ('반려동물', '🐶'), ('그 밖의 가게', '🏪')]
CAT_EMOJI = dict(CATS)
GOOD = ['설명이 꼼꼼해요', '실력이 좋아요', '친절해요', '가격이 정직해요', '깨끗해요', '약속을 잘 지켜요', '기다림이 짧아요', '다시 갈래요']
BAD = ['설명이 부족해요', '가격이 예상과 달라요', '기다림이 길어요', '불친절해요', '결과가 아쉬워요']
STAR_WORD = {1: '별로였어요', 2: '아쉬웠어요', 3: '보통이에요', 4: '좋았어요', 5: '최고예요'}
VISIT_HOURS = 24  # 스티커를 찍고 이 시간 안에 쓰면 방문 인증
# 업종별 세부 별점 (따종디앤핑의 맛·환경·서비스처럼): 후기 쓸 때 고르면 가게 화면에 항목별 평균
SUBS = {'미용': ('실력', '친절', '청결', '가격'), '세탁': ('품질', '속도', '친절', '가격'), '운동': ('시설', '지도', '청결', '가격'),
        '수리': ('실력', '속도', '설명', '가격'), '학원': ('수업', '관리', '시설', '가격'), '병원·약국': ('진료', '설명', '대기', '친절'),
        '반려동물': ('실력', '설명', '청결', '가격'), '그 밖의 가게': ('품질', '친절', '청결', '가격')}
LEVELS = ((10, 'Lv.3 동네 단골'), (3, 'Lv.2 동네 탐험가'), (1, 'Lv.1 새내기'))  # 쓴 후기 수
SORTS = (('best', '추천순'), ('stars', '별점순'), ('many', '후기 많은 순'), ('near', '내 주변'))
NO_REVIEW_DEAL = re.compile(r'후기|리뷰|별점|평점|사진\s*인증')  # 혜택에 후기 조건을 걸 수 없음 (진짜 후기 원칙)
DEFAULTS = {'hold_hours': '48', 'hold_below': '3', 'pro_price': '19900', 'area': '광교', 'pick_n': '5', 'pick_avg': '4.5', 'pick_v': '3'}
SCHEMA = """
CREATE TABLE IF NOT EXISTS stores(id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT NOT NULL, cat TEXT DEFAULT '그 밖의 가게', area TEXT DEFAULT '',
  addr TEXT DEFAULT '', phone TEXT DEFAULT '', hours TEXT DEFAULT '', intro TEXT DEFAULT '', photo TEXT DEFAULT '',
  owner_phone TEXT DEFAULT '', token TEXT UNIQUE, pro INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL, stars INTEGER NOT NULL, chips TEXT DEFAULT '', body TEXT DEFAULT '',
  nick TEXT DEFAULT '', visited INTEGER DEFAULT 0, private INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0, who TEXT DEFAULT '',
  reply TEXT DEFAULT '', reply_at TEXT DEFAULT '', created TEXT);
CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, review_id INTEGER, reason TEXT, by_owner INTEGER DEFAULT 0, done INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY, store_id INTEGER, at TEXT);
CREATE TABLE IF NOT EXISTS applies(id INTEGER PRIMARY KEY, store TEXT, cat TEXT, name TEXT, phone TEXT, addr TEXT, created TEXT, done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS conf(k TEXT PRIMARY KEY, v TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS saves(uid TEXT, store_id INTEGER, created TEXT, PRIMARY KEY(uid, store_id));
CREATE TABLE IF NOT EXISTS helpful(uid TEXT, review_id INTEGER, PRIMARY KEY(uid, review_id));
CREATE TABLE IF NOT EXISTS offers(id INTEGER PRIMARY KEY, store_id INTEGER, title TEXT, body TEXT DEFAULT '', until TEXT DEFAULT '', active INTEGER DEFAULT 1, created TEXT);
CREATE TABLE IF NOT EXISTS claims(id INTEGER PRIMARY KEY, offer_id INTEGER, uid TEXT, code TEXT, created TEXT, UNIQUE(offer_id, uid));
CREATE INDEX IF NOT EXISTS reviews_store ON reviews(store_id, created);
CREATE INDEX IF NOT EXISTS scans_store ON scans(store_id, at);
"""


def now():
    return datetime.datetime.now()


def ts(d=None):
    return (d or now()).strftime('%Y-%m-%d %H:%M:%S')


def parse(s):
    try:
        return datetime.datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return now()


def phone_norm(p):
    d = re.sub(r'\D', '', p or '')
    return d if re.fullmatch(r'01\d{8,9}', d) else ''


def ago(s):
    d = now() - parse(s)
    m = int(d.total_seconds() // 60)
    if m < 1:
        return '방금'
    if m < 60:
        return f'{m}분 전'
    if m < 1440:
        return f'{m // 60}시간 전'
    if d.days < 7:
        return '어제' if d.days == 1 else f'{d.days}일 전'
    return parse(s).strftime('%-m월 %-d일')


def create_app(db_path=None):
    mg = Flask(__name__, template_folder=str(BASE / 'templates'), static_folder=str(BASE / 'static'), static_url_path='/static')
    mg.secret_key = os.getenv('SECRET_KEY') or secrets.token_hex(32)
    mg.config.update(SESSION_COOKIE_NAME='mitgo', SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                     SESSION_COOKIE_SECURE=os.getenv('HTTPS_ONLY') == '1', PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=180))
    DB = Path(db_path or os.getenv('MITGO_DB', str(BASE.parent / 'mitgo.sqlite3')))
    IMG = DB.parent / 'mitgo-img'
    mg.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024
    mg.config['SEND_FILE_MAX_AGE_DEFAULT'] = 7 * 86400

    @contextlib.contextmanager
    def conn():
        db = sqlite3.connect(DB, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    with conn() as db:
        db.executescript(SCHEMA)
        for t, col in (('stores', 'lat REAL'), ('stores', 'lng REAL'), ('stores', "reserve_url TEXT DEFAULT ''"), ('stores', "tags TEXT DEFAULT ''"),
                       ('reviews', 's1 INTEGER DEFAULT 0'), ('reviews', 's2 INTEGER DEFAULT 0'), ('reviews', 's3 INTEGER DEFAULT 0'),
                       ('reviews', 's4 INTEGER DEFAULT 0'), ('reviews', "photos TEXT DEFAULT ''"), ('reviews', 'helpful INTEGER DEFAULT 0')):
            if col.split()[0] not in [r[1] for r in db.execute(f'PRAGMA table_info({t})')]:
                db.execute(f'ALTER TABLE {t} ADD COLUMN {col}')
    mg.conn = conn

    def conf():
        with conn() as db:
            got = {r['k']: r['v'] for r in db.execute('SELECT k,v FROM conf')}
        return {k: got.get(k) or v for k, v in DEFAULTS.items()} | {k: v for k, v in got.items() if k not in DEFAULTS}

    def num(v, d):
        try:
            return int(v)
        except (TypeError, ValueError):
            return d

    # ── 공통 ─────────────────────────────────────────
    def csrf():
        if '_csrf' not in session:
            session['_csrf'] = secrets.token_urlsafe(24)
        return session['_csrf']

    @mg.before_request
    def check_csrf():
        if request.method == 'POST' and not (session.get('_csrf') and hmac.compare_digest(request.form.get('_csrf', ''), session['_csrf'])):
            abort(400, '화면을 새로고침한 뒤 다시 해 주세요.')

    def css_v():
        try:
            return int((BASE / 'static' / 'mitgo.css').stat().st_mtime)
        except OSError:
            return 0

    @mg.context_processor
    def ctx():
        c = conf()
        return {'csrf': csrf, 'cats': CATS, 'cat_emoji': CAT_EMOJI, 'area': c['area'], 'css_v': css_v(), 'ago': ago,
                'naver_code': c.get('naver_code', ''), 'google_code': c.get('google_code', ''), 'footer': c.get('footer', ''),
                'contact': c.get('contact', '') or os.getenv('MITGO_CONTACT', '')}

    def who():
        """같은 사람이 한 가게에 후기를 몰아 쓰지 못하게: 브라우저 표시 + IP를 섞은 값."""
        if 'uid' not in session:
            session['uid'] = secrets.token_hex(8)
            session.permanent = True
        ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()
        return session['uid'], hashlib.sha256(('mitgo:' + ip).encode()).hexdigest()[:16]

    def is_public(r, c):
        """사장님께만 / 숨김이 아니고, 낮은 별점은 대기 시간이 지났거나 사장님이 답했을 때 공개."""
        if r['hidden'] or r['private']:
            return False
        if r['stars'] > num(c['hold_below'], 3) or r['reply']:
            return True
        return now() >= parse(r['created']) + datetime.timedelta(hours=num(c['hold_hours'], 48))

    def stats(db, store_ids=None, c=None):
        """가게별 공개 후기 점수. 방문 인증 후기는 1, 아닌 후기는 0.5만큼 센다. 순위용 점수는 베이즈 평균(4.0을 3개 깔고 시작)."""
        c = c or conf()
        q = 'SELECT * FROM reviews' + (f" WHERE store_id IN ({','.join('?' * len(store_ids))})" if store_ids else '')
        out = {}
        for r in db.execute(q, tuple(store_ids or ())):
            if not is_public(r, c):
                continue
            s = out.setdefault(r['store_id'], {'n': 0, 'v': 0, 'sum': 0.0, 'w': 0.0, 'chips': {}})
            w = 1.0 if r['visited'] else 0.5
            s['n'] += 1
            s['v'] += r['visited']
            s['sum'] += r['stars']
            s['w'] += w
            s['ws'] = s.get('ws', 0.0) + w * r['stars']
            for ch in filter(None, (r['chips'] or '').split('|')):
                s['chips'][ch] = s['chips'].get(ch, 0) + 1
            for i in range(4):
                v = r[f's{i + 1}']
                if v:
                    s.setdefault('sub', [[0, 0] for _ in range(4)])[i][0] += v
                    s['sub'][i][1] += 1
        pn, pa, pv = num(c['pick_n'], 5), float(c['pick_avg'] or 4.5), num(c['pick_v'], 3)
        for s in out.values():
            s['avg'] = round(s['sum'] / s['n'], 1)
            s['rank'] = (s['ws'] + 12.0) / (s['w'] + 3.0)
            s['top'] = sorted(s['chips'].items(), key=lambda x: -x[1])[:4]
            s['subs'] = [round(a / b, 1) if b else None for a, b in s.get('sub', [[0, 0]] * 4)]
            s['pick'] = s['n'] >= pn and s['avg'] >= pa and s['v'] >= pv  # '믿고 갈 가게': 후기·방문 인증이 쌓이고 별점이 높은 곳만 자동
        return out

    def level(n):
        return next((name for k, name in LEVELS if n >= k), '')

    def levels(db, rows):
        """후기 쓴 사람(브라우저)별 후기 수 → 등급. who = 'uid:ip' 앞부분으로 셈."""
        uids = {(r['who'] or '').split(':')[0] for r in rows if r['who']}
        out = {}
        for u in uids:
            n = db.execute('SELECT COUNT(*), SUM(visited) FROM reviews WHERE who LIKE ? AND hidden=0', (u + ':%',)).fetchone()
            out[u] = {'n': n[0], 'v': n[1] or 0, 'lv': level(n[0])}
        return out

    def uid():
        if 'uid' not in session:
            session['uid'] = secrets.token_hex(8)
            session.permanent = True
        return session['uid']

    def dist_km(s, lat, lng):
        if s['lat'] is None or s['lng'] is None or lat is None:
            return None
        import math
        dy = (s['lat'] - lat) * 111.0
        dx = (s['lng'] - lng) * 111.0 * math.cos(math.radians(lat))
        return round((dx * dx + dy * dy) ** .5, 1)

    def store_or_404(db, sid):
        s = db.execute('SELECT * FROM stores WHERE id=? AND hidden=0', (sid,)).fetchone()
        if not s:
            abort(404)
        return s

    def scanned(sid):
        t = (session.get('scan') or {}).get(str(sid))
        return bool(t) and now() - parse(t) < datetime.timedelta(hours=VISIT_HOURS)

    @mg.after_request
    def squeeze(resp):
        mt = resp.mimetype or ''
        if (resp.status_code != 200 or 'gzip' not in request.headers.get('Accept-Encoding', '') or resp.headers.get('Content-Encoding')
                or not (mt.startswith('text/') or mt in ('application/javascript', 'application/xml', 'application/json'))):
            return resp
        resp.direct_passthrough = False
        data = resp.get_data()
        if len(data) > 1024:
            import gzip
            resp.set_data(gzip.compress(data, 6))
            resp.headers['Content-Encoding'] = 'gzip'
            resp.headers['Vary'] = 'Accept-Encoding'
        return resp

    def msg(title, text, link=None, label=None):
        return render_template('mg_msg.html', title=title, text=text, link=link, label=label)

    # ── 손님 ─────────────────────────────────────────
    @mg.get('/')
    def home():
        """첫 화면 (따종디앤핑식): 업종 아이콘 + 믿고 갈 가게 + 순위 다섯 + 2열 사진 후기 피드. 광고 카드는 없음."""
        if request.args.get('q') or request.args.get('cat') or request.args.get('sort'):
            return redirect(url_for('rank', **request.args))
        c = conf()
        with conn() as db:
            stores = db.execute('SELECT * FROM stores WHERE hidden=0').fetchall()
            st = stats(db, None, c) if stores else {}
            feed = []
            for r in db.execute('SELECT r.*, s.name sname, s.cat scat, s.photo sphoto FROM reviews r JOIN stores s ON s.id=r.store_id '
                                'WHERE s.hidden=0 ORDER BY (r.photos != \'\') DESC, r.visited DESC, r.created DESC LIMIT 200'):
                if is_public(r, c) and ((r['body'] or '').strip() or r['photos']):
                    feed.append(r)
            feed = sorted(feed, key=lambda r: r['created'], reverse=True)[:40]
            lv = levels(db, feed)
        g = lambda s, k, d=0: st.get(s['id'], {}).get(k, d)  # noqa: E731
        top = sorted(stores, key=lambda s: (-g(s, 'rank'), -g(s, 'n'), s['id']))
        picks = [s for s in top if g(s, 'pick')][:10]
        return render_template('mg_home.html', st=st, top=top[:5], picks=picks, feed=feed, lv=lv)

    @mg.get('/rank')
    def rank():
        cat = request.args.get('cat', '')
        q = (request.args.get('q') or '').strip()[:40]
        c = conf()
        with conn() as db:
            sql, args = 'SELECT * FROM stores WHERE hidden=0', []
            if cat in CAT_EMOJI:
                sql += ' AND cat=?'
                args.append(cat)
            if q:
                sql += ' AND (name LIKE ? OR addr LIKE ? OR cat LIKE ? OR intro LIKE ?)'
                args += ['%' + q + '%'] * 4
            stores = db.execute(sql, args).fetchall()
            st = stats(db, [s['id'] for s in stores], c) if stores else {}
            recent = []
            for r in db.execute('SELECT r.*, s.name sname, s.cat scat FROM reviews r JOIN stores s ON s.id=r.store_id '
                                'WHERE s.hidden=0 ORDER BY r.created DESC LIMIT 60'):
                if is_public(r, c) and (r['body'] or '').strip():
                    recent.append(r)
                if len(recent) >= 6:
                    break
            lv = levels(db, recent)
            offers = {r['store_id'] for r in db.execute("SELECT store_id FROM offers WHERE active=1 AND (until='' OR until>=?)", (ts()[:10],))}
        sort = request.args.get('sort', 'best')
        only_v = request.args.get('v') == '1'
        lat, lng = (lambda a, b: (a, b) if a is not None and b is not None else (None, None))(
            *(float(request.args[k]) if re.fullmatch(r'-?\d{1,3}(\.\d+)?', request.args.get(k, '')) else None for k in ('lat', 'lng')))
        if sort == 'near' and lat is None:
            sort = 'best'
        g = lambda s, k, d=0: st.get(s['id'], {}).get(k, d)  # noqa: E731
        if only_v:
            stores = [s for s in stores if g(s, 'v')]
        far = {s['id']: dist_km(s, lat, lng) for s in stores}
        key = {'best': lambda s: (-g(s, 'rank'), -g(s, 'n'), s['id']),
               'stars': lambda s: (-g(s, 'avg'), -g(s, 'n'), s['id']),
               'many': lambda s: (-g(s, 'n'), -g(s, 'rank'), s['id']),
               'near': lambda s: (far[s['id']] is None, far[s['id']] or 0, -g(s, 'rank'))}.get(sort)
        ranked = sorted(stores, key=key or (lambda s: (-g(s, 'rank'), s['id'])))
        picks = [s for s in sorted(stores, key=lambda s: -g(s, 'rank')) if g(s, 'pick')][:10]
        return render_template('mg_rank.html', stores=ranked[:30], st=st, cat=cat, q=q, recent=recent, lv=lv, picks=picks,
                               sort=sort, sorts=SORTS, only_v=only_v, far=far, lat=lat, lng=lng, offers=offers)

    @mg.get('/s/<int:sid>')
    def store(sid):
        c = conf()
        order = request.args.get('o', 'v')
        with conn() as db:
            s = store_or_404(db, sid)
            st = stats(db, [sid], c).get(sid)
            rows = [r for r in db.execute('SELECT * FROM reviews WHERE store_id=? ORDER BY visited DESC, helpful DESC, id DESC', (sid,)) if is_public(r, c)]
            lv = levels(db, rows)
            offers = db.execute("SELECT * FROM offers WHERE store_id=? AND active=1 AND (until='' OR until>=?) ORDER BY id DESC", (sid, ts()[:10])).fetchall()
            saved = bool(db.execute('SELECT 1 FROM saves WHERE uid=? AND store_id=?', (session.get('uid', ''), sid)).fetchone())
            mine = {r[0] for r in db.execute('SELECT review_id FROM helpful WHERE uid=?', (session.get('uid', ''),))}
        if order == 'new':
            rows.sort(key=lambda r: r['created'], reverse=True)
        elif order == 'low':
            rows.sort(key=lambda r: (r['stars'], r['created']))
        elif order == 'photo':
            rows = [r for r in rows if r['photos']]
        dist = {k: 0 for k in range(5, 0, -1)}
        for r in rows:
            dist[r['stars']] += 1
        photos = ([s['photo']] if s['photo'] else []) + [p for r in rows for p in (r['photos'] or '').split('|') if p]
        return render_template('mg_store.html', s=s, st=st, reviews=rows[:50], dist=dist, from_qr=scanned(sid), lv=lv, offers=offers,
                               saved=saved, mine=mine, photos=photos[:12], subs=SUBS.get(s['cat'], SUBS['그 밖의 가게']), order=order)

    @mg.post('/s/<int:sid>/save')
    def save(sid):
        u = uid()
        with conn() as db:
            store_or_404(db, sid)
            if db.execute('DELETE FROM saves WHERE uid=? AND store_id=?', (u, sid)).rowcount == 0:
                db.execute('INSERT INTO saves(uid,store_id,created) VALUES(?,?,?)', (u, sid, ts()))
                flash('찜했어요. 내 활동에서 다시 볼 수 있어요.')
        return redirect(url_for('store', sid=sid))

    @mg.post('/r/<int:rid>/helpful')
    def helpful(rid):
        u = uid()
        with conn() as db:
            r = db.execute('SELECT store_id, who FROM reviews WHERE id=?', (rid,)).fetchone()
            if not r:
                abort(404)
            if not (r['who'] or '').startswith(u + ':'):  # 내 후기에는 못 누름
                if db.execute('DELETE FROM helpful WHERE uid=? AND review_id=?', (u, rid)).rowcount:
                    db.execute('UPDATE reviews SET helpful=MAX(0,helpful-1) WHERE id=?', (rid,))
                else:
                    db.execute('INSERT INTO helpful(uid,review_id) VALUES(?,?)', (u, rid))
                    db.execute('UPDATE reviews SET helpful=helpful+1 WHERE id=?', (rid,))
        return redirect(url_for('store', sid=r['store_id']) + f'#r{rid}')

    @mg.post('/offer/<int:oid>')
    def offer_claim(oid):
        """사장님 혜택 받기: 후기와 상관없이 누구나. 직원에게 보여 줄 번호를 줌."""
        u = uid()
        with conn() as db:
            o = db.execute("SELECT o.*, s.name sname FROM offers o JOIN stores s ON s.id=o.store_id WHERE o.id=? AND o.active=1", (oid,)).fetchone()
            if not o:
                abort(404)
            got = db.execute('SELECT code FROM claims WHERE offer_id=? AND uid=?', (oid, u)).fetchone()
            code = got['code'] if got else f'{secrets.randbelow(9000) + 1000}'
            if not got:
                db.execute('INSERT INTO claims(offer_id,uid,code,created) VALUES(?,?,?,?)', (oid, u, code, ts()))
        return render_template('mg_offer.html', o=o, code=code)

    @mg.get('/my')
    def my():
        u = session.get('uid', '')
        c = conf()
        with conn() as db:
            saved = db.execute('SELECT s.* FROM saves v JOIN stores s ON s.id=v.store_id WHERE v.uid=? AND s.hidden=0 ORDER BY v.created DESC', (u,)).fetchall()
            ids = [int(k) for k in (session.get('scan') or {})]
            been = db.execute(f"SELECT * FROM stores WHERE hidden=0 AND id IN ({','.join('?' * len(ids)) or 'NULL'})", ids).fetchall() if ids else []
            mine = db.execute('SELECT r.*, s.name sname FROM reviews r JOIN stores s ON s.id=r.store_id WHERE r.who LIKE ? ORDER BY r.id DESC', (u + ':%',)).fetchall() if u else []
            deals = db.execute('SELECT c.code, o.title, s.name sname, s.id sid FROM claims c JOIN offers o ON o.id=c.offer_id JOIN stores s ON s.id=o.store_id '
                               'WHERE c.uid=? ORDER BY c.id DESC', (u,)).fetchall() if u else []
            st = stats(db, list({s['id'] for s in saved + been}) or None, c) if (saved or been) else {}
        n = len(mine)
        nxt = next(((k, name) for k, name in reversed(LEVELS) if n < k), None)
        return render_template('mg_my.html', saved=saved, been=been, mine=mine, deals=deals, st=st, n=n, v=sum(r['visited'] for r in mine),
                               lv=level(n) or '아직 후기가 없어요', nxt=nxt, is_public=lambda r: is_public(r, c))

    @mg.get('/q/<code>')
    def sticker(code):
        code = re.sub(r'[^0-9A-Za-z]', '', code)[:20]
        if not code:
            abort(404)
        with conn() as db:
            s = db.execute('SELECT * FROM stores WHERE code=?', (code,)).fetchone()
            if s and not s['hidden']:
                db.execute('INSERT INTO scans(store_id,at) VALUES(?,?)', (s['id'], ts()))
        if s and not s['hidden']:
            sc = dict(session.get('scan') or {})
            sc[str(s['id'])] = ts()
            session['scan'] = dict(sorted(sc.items(), key=lambda x: x[1])[-30:])
            session.permanent = True
            return redirect(url_for('store', sid=s['id']))
        if s:
            abort(404)
        return redirect(url_for('claim', code=code))

    @mg.route('/q/<code>/start', methods=['GET', 'POST'])
    def claim(code):
        """아직 등록 안 된 스티커: 처음 찍은 사장님이 가게를 등록 (사장님 화면 주소를 바로 줌)."""
        code = re.sub(r'[^0-9A-Za-z]', '', code)[:20]
        with conn() as db:
            if db.execute('SELECT 1 FROM stores WHERE code=?', (code,)).fetchone():
                return redirect(url_for('sticker', code=code))
        if request.method == 'POST':
            f = request.form
            name, cat = f.get('name', '').strip()[:40], f.get('cat', '')
            ph = phone_norm(f.get('phone'))
            if not name or cat not in CAT_EMOJI or not ph or f.get('agree') != '1':
                flash('가게 이름, 분야, 휴대폰 번호를 넣고 약속에 체크해 주세요.')
                return render_template('mg_claim.html', code=code, f=f)
            tok = secrets.token_urlsafe(16)
            with conn() as db:
                try:
                    db.execute('INSERT INTO stores(code,name,cat,area,addr,owner_phone,token,created) VALUES(?,?,?,?,?,?,?,?)',
                               (code, name, cat, conf()['area'], f.get('addr', '').strip()[:80], ph, tok, ts()))
                except sqlite3.IntegrityError:
                    return redirect(url_for('sticker', code=code))
            session.setdefault('owner', [])
            session['owner'] = (session['owner'] + [tok])[-5:]
            return redirect(url_for('owner', tok=tok, new=1))
        return render_template('mg_claim.html', code=code, f={})

    @mg.route('/s/<int:sid>/review', methods=['GET', 'POST'])
    def review(sid):
        with conn() as db:
            s = store_or_404(db, sid)
        visited = scanned(sid)
        if request.method == 'POST':
            f = request.form
            stars = num(f.get('stars'), 0)
            if stars not in range(1, 6):
                flash('별점을 골라 주세요.')
                return render_template('mg_review.html', s=s, visited=visited, f=f, subs=SUBS.get(s['cat'], SUBS['그 밖의 가게']))
            if f.get('honest') != '1':
                flash('대가 없이 직접 이용하고 쓰는 후기인지 체크해 주세요.')
                return render_template('mg_review.html', s=s, visited=visited, f=f, subs=SUBS.get(s['cat'], SUBS['그 밖의 가게']))
            chips = [ch for ch in f.getlist('chip') if ch in GOOD + BAD][:5]
            body = re.sub(r'\s+\n', '\n', (f.get('body') or '').strip())[:600]
            uid, iph = who()
            key = uid + ':' + iph
            with conn() as db:
                week = ts(now() - datetime.timedelta(days=7))
                if db.execute('SELECT 1 FROM reviews WHERE store_id=? AND created>? AND (who LIKE ? OR who LIKE ?)',
                              (sid, week, uid + ':%', '%:' + iph)).fetchone():
                    return msg('이미 후기를 남겼어요', '같은 가게 후기는 일주일에 한 번만 쓸 수 있어요.', url_for('store', sid=sid), '가게로 돌아가기')
                subs = [min(5, max(0, num(f.get(f's{i}'), 0))) for i in range(1, 5)]
                photos = [p for p in (save_photo(fs) for fs in request.files.getlist('photos')[:3]) if p]
                db.execute('INSERT INTO reviews(store_id,stars,chips,body,nick,visited,private,who,created,s1,s2,s3,s4,photos) '
                           'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (sid, stars, '|'.join(chips), body, (f.get('nick') or '').strip()[:12], 1 if visited else 0,
                            1 if f.get('private') == '1' else 0, key, ts(), *subs, '|'.join(photos)))
            c = conf()
            if f.get('private') == '1':
                t = '사장님께만 전했어요. 다른 사람에게는 보이지 않아요.'
            elif stars <= num(c['hold_below'], 3):
                t = f"사장님이 먼저 보고 답할 수 있게 {num(c['hold_hours'], 48)}시간 뒤에 공개돼요."
            else:
                t = '후기가 바로 올라갔어요. 고마워요.'
            return msg('후기를 남겼어요', t, url_for('store', sid=sid), '가게로 돌아가기')
        return render_template('mg_review.html', s=s, visited=visited, f={}, subs=SUBS.get(s['cat'], SUBS['그 밖의 가게']))

    @mg.post('/r/<int:rid>/report')
    def report(rid):
        reason = (request.form.get('reason') or '').strip()[:200] or '신고'
        with conn() as db:
            r = db.execute('SELECT store_id FROM reviews WHERE id=?', (rid,)).fetchone()
            if not r:
                abort(404)
            db.execute('INSERT INTO reports(review_id,reason,created) VALUES(?,?,?)', (rid, reason, ts()))
        return msg('신고를 받았어요', '운영자가 살펴보고 규칙에 맞지 않으면 내려요.', url_for('store', sid=r['store_id']), '가게로 돌아가기')

    @mg.get('/about')
    def about():
        return render_template('mg_about.html')

    @mg.route('/join', methods=['GET', 'POST'])
    def join():
        c = conf()
        if request.method == 'POST':
            f = request.form
            ph = phone_norm(f.get('phone'))
            if not f.get('store', '').strip() or not ph:
                flash('가게 이름과 휴대폰 번호를 넣어 주세요.')
                return render_template('mg_join.html', f=f, price=num(c['pro_price'], 19900))
            with conn() as db:
                db.execute('INSERT INTO applies(store,cat,name,phone,addr,created) VALUES(?,?,?,?,?,?)',
                           (f.get('store', '').strip()[:40], f.get('cat', '')[:20], f.get('name', '').strip()[:20], ph, f.get('addr', '').strip()[:80], ts()))
            return msg('신청을 받았어요', '스티커를 보내 드리기 전에 연락드릴게요.', url_for('home'), '처음으로')
        return render_template('mg_join.html', f={}, price=num(c['pro_price'], 19900))

    @mg.get('/policy')
    def policy():
        return render_template('mg_policy.html', c=conf())

    @mg.get('/img/<name>')
    def img(name):
        if not re.fullmatch(r'[0-9a-f]{24}\.jpg', name):
            abort(404)
        return send_from_directory(IMG, name, max_age=30 * 86400)

    def save_photo(fs):
        if not fs or not fs.filename:
            return ''
        from PIL import Image, ImageOps
        try:
            im = ImageOps.exif_transpose(Image.open(fs.stream)).convert('RGB')
        except Exception:
            return ''
        im.thumbnail((1200, 1200))
        IMG.mkdir(parents=True, exist_ok=True)
        name = secrets.token_hex(12) + '.jpg'
        im.save(IMG / name, 'JPEG', quality=84)
        return name

    def coords(v, s=None):
        """'37.2886, 127.0507' 처럼 붙여 넣은 좌표 (네이버·카카오 지도에서 복사). 비우면 그대로."""
        m = re.search(r'(3[3-8]\.\d+)\s*,\s*(12[4-9]\.\d+)', v or '')
        if m:
            return float(m.group(1)), float(m.group(2))
        return (s['lat'], s['lng']) if s is not None else (None, None)

    # ── 사장님 ───────────────────────────────────────
    def owner_store(db, tok):
        s = db.execute('SELECT * FROM stores WHERE token=?', (tok,)).fetchone()
        if not s:
            abort(404)
        return s

    @mg.get('/owner/<tok>')
    def owner(tok):
        c = conf()
        with conn() as db:
            s = owner_store(db, tok)
            rows = db.execute('SELECT * FROM reviews WHERE store_id=? AND hidden=0 ORDER BY id DESC LIMIT 100', (s['id'],)).fetchall()
            week = ts(now() - datetime.timedelta(days=7))
            scans = db.execute('SELECT COUNT(*) FROM scans WHERE store_id=? AND at>?', (s['id'], week)).fetchone()[0]
            st = stats(db, [s['id']], c).get(s['id'])
            offers = db.execute('SELECT o.*, (SELECT COUNT(*) FROM claims WHERE offer_id=o.id) n FROM offers o WHERE store_id=? ORDER BY active DESC, id DESC',
                                (s['id'],)).fetchall()
            saves = db.execute('SELECT COUNT(*) FROM saves WHERE store_id=?', (s['id'],)).fetchone()[0]
        hold = num(c['hold_hours'], 48)
        items = []
        for r in rows:
            left = None
            if not r['private'] and not is_public(r, c):
                left = max(1, int((parse(r['created']) + datetime.timedelta(hours=hold) - now()).total_seconds() // 3600))
            items.append((r, left))
        new_week = sum(1 for r in rows if r['created'] > week)
        waiting = sum(1 for r, _ in items if not r['reply'] and not r['private'])
        return render_template('mg_owner.html', s=s, items=items, scans=scans, st=st, new_week=new_week, waiting=waiting,
                               held=sum(1 for _, x in items if x), tok=tok, new=request.args.get('new'), offers=offers, saves=saves,
                               subs=SUBS.get(s['cat'], SUBS['그 밖의 가게']))

    @mg.post('/owner/<tok>/offer')
    def owner_offer(tok):
        """사장님 혜택(쿠폰·묶음 할인): 후기·별점 조건은 못 걺. 손님 누구나 받을 수 있게."""
        f = request.form
        with conn() as db:
            s = owner_store(db, tok)
            if f.get('id'):
                db.execute('UPDATE offers SET active=1-active WHERE id=? AND store_id=?', (num(f.get('id'), 0), s['id']))
                return redirect(url_for('owner', tok=tok) + '#offers')
            title, body = f.get('title', '').strip()[:40], f.get('body', '').strip()[:200]
            until = f.get('until', '') if re.fullmatch(r'\d{4}-\d{2}-\d{2}', f.get('until', '')) else ''
            if not title:
                flash('혜택 이름을 넣어 주세요.')
            elif NO_REVIEW_DEAL.search(title + ' ' + body):
                flash('후기·별점을 조건으로 거는 혜택은 올릴 수 없어요. 믿고가게는 광고나 이벤트 없는 진짜 후기만 받아요.')
            else:
                db.execute('INSERT INTO offers(store_id,title,body,until,created) VALUES(?,?,?,?,?)', (s['id'], title, body, until, ts()))
                flash('혜택을 올렸어요. 후기와 상관없이 누구나 받을 수 있어요.')
        return redirect(url_for('owner', tok=tok) + '#offers')

    @mg.post('/owner/<tok>/reply/<int:rid>')
    def owner_reply(tok, rid):
        text = (request.form.get('reply') or '').strip()[:400]
        with conn() as db:
            s = owner_store(db, tok)
            db.execute("UPDATE reviews SET reply=?, reply_at=? WHERE id=? AND store_id=?", (text, ts() if text else '', rid, s['id']))
        flash('답글을 달았어요.' if text else '답글을 지웠어요.')
        return redirect(url_for('owner', tok=tok) + f'#r{rid}')

    @mg.post('/owner/<tok>/report/<int:rid>')
    def owner_report(tok, rid):
        with conn() as db:
            s = owner_store(db, tok)
            if not db.execute('SELECT 1 FROM reviews WHERE id=? AND store_id=?', (rid, s['id'])).fetchone():
                abort(404)
            db.execute('INSERT INTO reports(review_id,reason,by_owner,created) VALUES(?,?,1,?)', (rid, (request.form.get('reason') or '')[:200] or '사장님 신고', ts()))
        flash('신고했어요. 운영자가 살펴볼게요. 후기는 그동안 그대로 있어요.')
        return redirect(url_for('owner', tok=tok))

    @mg.post('/owner/<tok>/edit')
    def owner_edit(tok):
        f = request.form
        with conn() as db:
            s = owner_store(db, tok)
            photo = save_photo(request.files.get('photo')) or s['photo']
            url = f.get('reserve_url', '').strip()[:300]
            if url and not re.match(r'https?://', url):
                url = ''
            db.execute('UPDATE stores SET name=?, cat=?, addr=?, phone=?, hours=?, intro=?, photo=?, reserve_url=?, tags=?, lat=?, lng=? WHERE id=?',
                       ((f.get('name') or s['name']).strip()[:40], f.get('cat') if f.get('cat') in CAT_EMOJI else s['cat'],
                        f.get('addr', '').strip()[:80], f.get('phone', '').strip()[:20], f.get('hours', '').strip()[:60],
                        f.get('intro', '').strip()[:300], photo, url, ' '.join(re.findall(r'[^\s#,]+', f.get('tags', '')))[:100],
                        *coords(f.get('loc', ''), s), s['id']))
        flash('가게 정보를 고쳤어요.')
        return redirect(url_for('owner', tok=tok))

    # ── 운영자 ───────────────────────────────────────
    def admin_ok():
        return session.get('mg_admin') is True

    @mg.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        pw = os.getenv('MITGO_ADMIN_PASSWORD', '')
        if request.method == 'POST':
            if pw and hmac.compare_digest(request.form.get('pw', ''), pw):
                session['mg_admin'] = True
                return redirect(url_for('admin'))
            flash('비밀번호가 맞지 않아요.' if pw else '서버에 MITGO_ADMIN_PASSWORD가 아직 없어요.')
        return render_template('mg_login.html')

    @mg.before_request
    def admin_gate():
        if request.path.startswith('/admin') and request.endpoint != 'admin_login' and not admin_ok():
            return redirect(url_for('admin_login'))

    @mg.route('/admin', methods=['GET', 'POST'])
    def admin():
        tab = request.args.get('tab', 'stores')
        if request.method == 'POST':
            f = request.form
            act = f.get('act')
            with conn() as db:
                if act == 'store_add':
                    name, cat = f.get('name', '').strip()[:40], f.get('cat')
                    code = re.sub(r'[^0-9A-Za-z]', '', f.get('code', ''))[:20] or None
                    if name and cat in CAT_EMOJI:
                        try:
                            db.execute('INSERT INTO stores(code,name,cat,area,addr,phone,owner_phone,token,created,lat,lng) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                       (code, name, cat, conf()['area'], f.get('addr', '').strip()[:80], f.get('phone', '').strip()[:20],
                                        phone_norm(f.get('owner_phone')), secrets.token_urlsafe(16), ts(), *coords(f.get('loc', ''))))
                            flash('가게를 넣었어요.')
                        except sqlite3.IntegrityError:
                            flash('그 스티커 번호는 이미 다른 가게에 있어요.')
                elif act == 'store_hide':
                    db.execute('UPDATE stores SET hidden=1-hidden WHERE id=?', (num(f.get('id'), 0),))
                elif act == 'store_code':
                    code = re.sub(r'[^0-9A-Za-z]', '', f.get('code', ''))[:20] or None
                    try:
                        db.execute('UPDATE stores SET code=? WHERE id=?', (code, num(f.get('id'), 0)))
                    except sqlite3.IntegrityError:
                        flash('그 스티커 번호는 이미 다른 가게에 있어요.')
                elif act == 'store_pro':
                    db.execute('UPDATE stores SET pro=1-pro WHERE id=?', (num(f.get('id'), 0),))
                elif act == 'review_hide':
                    db.execute('UPDATE reviews SET hidden=1-hidden WHERE id=?', (num(f.get('id'), 0),))
                    db.execute('UPDATE reports SET done=1 WHERE review_id=?', (num(f.get('id'), 0),))
                elif act == 'report_done':
                    db.execute('UPDATE reports SET done=1 WHERE id=?', (num(f.get('id'), 0),))
                elif act == 'apply_done':
                    db.execute('UPDATE applies SET done=1 WHERE id=?', (num(f.get('id'), 0),))
                elif act == 'conf':
                    for k in ('hold_hours', 'hold_below', 'pro_price', 'pick_n', 'pick_v'):
                        v = num(f.get(k), None)
                        if v is not None and v >= 0:
                            db.execute('INSERT OR REPLACE INTO conf(k,v) VALUES(?,?)', (k, str(v)))
                    if re.fullmatch(r'[0-5](\.\d)?', f.get('pick_avg', '')):
                        db.execute("INSERT OR REPLACE INTO conf(k,v) VALUES('pick_avg',?)", (f['pick_avg'],))
                    for k in ('area', 'footer', 'contact', 'naver_code', 'google_code'):
                        v = (f.get(k) or '').strip()[:300]
                        if k.endswith('_code'):
                            m = re.search(r'content=["\']([^"\']+)', v)
                            v = re.sub(r'[^0-9A-Za-z_-]', '', m.group(1) if m else v)[:100]
                        db.execute('INSERT OR REPLACE INTO conf(k,v) VALUES(?,?)', (k, v))
                    flash('설정을 바꿨어요. 바로 적용돼요.')
            return redirect(url_for('admin', tab=tab))
        c = conf()
        with conn() as db:
            stores = db.execute('SELECT * FROM stores ORDER BY id DESC').fetchall()
            st = stats(db, None, c)
            reviews = db.execute('SELECT r.*, s.name sname FROM reviews r JOIN stores s ON s.id=r.store_id ORDER BY r.id DESC LIMIT 200').fetchall()
            reports = db.execute('SELECT p.*, r.body, r.stars, r.hidden rhidden, s.name sname FROM reports p JOIN reviews r ON r.id=p.review_id '
                                 'JOIN stores s ON s.id=r.store_id WHERE p.done=0 ORDER BY p.id DESC').fetchall()
            applies = db.execute('SELECT * FROM applies ORDER BY done, id DESC LIMIT 200').fetchall()
        return render_template('mg_admin.html', tab=tab, stores=stores, st=st, reviews=reviews, reports=reports, applies=applies, c=c,
                               is_public=lambda r: is_public(r, c))

    @mg.get('/admin/stickers')
    def admin_stickers():
        """스티커 인쇄: 번호 범위를 넣으면 QR이 든 스티커 판을 만든다 (A4, 80×110mm)."""
        a, b = num(request.args.get('from'), 0), num(request.args.get('to'), 0)
        items = []
        if a and b and 0 <= b - a < 200:
            try:
                import segno
            except ImportError:
                return 'QR을 만드는 부품(segno)이 서버에 없어요. 업데이트 파일을 한 번 더 돌려 주세요.', 503
            root = request.url_root.rstrip('/')
            items = [(i, segno.make(f'{root}/q/{i}', error='m').svg_inline(border=0, omitsize=True)) for i in range(a, b + 1)]
        return render_template('mg_stickers.html', items=items, a=a, b=b)

    @mg.get('/admin/logout')
    def admin_logout():
        session.pop('mg_admin', None)
        return redirect(url_for('home'))

    @mg.get('/robots.txt')
    def robots():
        body = 'User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /owner/\nDisallow: /q/\n\nSitemap: ' + url_for('sitemap', _external=True) + '\n'
        return mg.response_class(body, mimetype='text/plain')

    @mg.get('/sitemap.xml')
    def sitemap():
        with conn() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM stores WHERE hidden=0')]
        urls = [url_for('home', _external=True), url_for('about', _external=True)] + [url_for('store', sid=i, _external=True) for i in ids]
        body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{u}</loc></url>' for u in urls) + '</urlset>'
        return mg.response_class(body, mimetype='application/xml')

    @mg.errorhandler(404)
    def nf(e):
        return render_template('mg_msg.html', title='찾을 수 없어요', text='주소가 바뀌었거나 내려간 가게예요.', link=url_for('home'), label='처음으로'), 404

    mg.jinja_env.globals.update(GOOD=GOOD, BAD=BAD, STAR_WORD=STAR_WORD)
    return mg


def mount(main_wsgi):
    """소보루 서버 앞에서 주소를 보고 나눔: MITGO_HOST로 오면 믿고가게, MITGO_PREVIEW=1이면 /mitgo 아래도 믿고가게."""
    hosts = {h.strip().lower() for x in os.getenv('MITGO_HOST', '').split(',') if x.strip() for h in (x, 'www.' + x.strip())}
    preview = os.getenv('MITGO_PREVIEW') == '1'
    if not hosts and not preview:
        return main_wsgi
    try:
        mg = create_app()
    except Exception as e:  # 믿고가게가 못 떠도 다른 사이트는 그대로
        import sys
        print(f'[mitgo] 시작 실패, 꺼 둠: {e!r}', file=sys.stderr, flush=True)
        return main_wsgi
    mg_wsgi = mg.wsgi_app
    if os.getenv('TRUST_PROXY') == '1':
        from werkzeug.middleware.proxy_fix import ProxyFix
        mg_wsgi = ProxyFix(mg_wsgi, x_for=1, x_proto=1, x_host=1)

    def app(environ, start_response):
        host = (environ.get('HTTP_X_FORWARDED_HOST') or environ.get('HTTP_HOST') or '').split(',')[0].split(':')[0].strip().lower()
        if host in hosts:
            return mg_wsgi(environ, start_response)
        path = environ.get('PATH_INFO', '')
        if preview and (path == '/mitgo' or path.startswith('/mitgo/')):
            if hosts:
                q = environ.get('QUERY_STRING', '')
                loc = 'https://' + sorted(hosts, key=len)[0] + (path[len('/mitgo'):] or '/') + ('?' + q if q else '')
                start_response('302 Found', [('Location', loc), ('Content-Length', '0')])
                return [b'']
            environ = dict(environ, SCRIPT_NAME=environ.get('SCRIPT_NAME', '') + '/mitgo', PATH_INFO=path[len('/mitgo'):] or '/')
            return mg_wsgi(environ, start_response)
        return main_wsgi(environ, start_response)
    return app
