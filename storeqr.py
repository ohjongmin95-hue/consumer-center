"""매장 QR (운영자 2026-11-08): 가게에 붙인 스티커 QR을 찍으면 /q/<번호> 한 장짜리 화면이 열린다.
- 손님은 별점 하나 누르고, 고른 별점에 맞는 칩(좋았던 점·아쉬운 점)을 고르면 끝. 글은 안 써도 된다.
- 좋았던 후기는 손님이 '가게 후기로 보여줘도 돼요'를 켰을 때만 공개 후보가 된다. 아쉬운 점은 사장님과 소보루만 본다.
- 번호는 10001부터. 관리자 > 매장 QR에서 가게를 넣으면 번호가 붙는다.
- 공개 제보(소비자제보센터)와는 따로 저장한다. 사장님이 붙이기 싫어하지 않게 제보 링크는 두지 않는다 (OH 11/08).
- /qr = 사장님용 소개·신청 페이지.
"""
import datetime, hashlib, hmac, json, threading

from flask import abort, flash, redirect, render_template, request, url_for

GOOD = ['맛있어요', '친절해요', '깨끗해요', '빨리 나와요', '양이 넉넉해요', '가격이 좋아요', '분위기가 좋아요', '또 올래요']
BAD = ['맛이 아쉬워요', '불친절했어요', '오래 기다렸어요', '주문이 틀렸어요', '청결이 아쉬워요', '양이 적어요', '가격이 비싸요', '시끄러웠어요']
FIRST_ID = 10001
FIRST_BATCH = (20001, 20500)  # 첫 묶음 500장 (OH 11/08). 인쇄 파일을 미리 만들어 두었으니 서버에도 늘 있게 함
BIZ = ['음식점', '카페·디저트', '술집', '미용·뷰티', '병원·약국', '학원', '가게·마트', '그 밖의 가게']


def install(S):
    app, conn = S.app, S.conn
    with conn() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS qr_stores(id INTEGER PRIMARY KEY,name TEXT NOT NULL,area TEXT NOT NULL DEFAULT '',
            hidden INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS qr_feedback(id INTEGER PRIMARY KEY,store_id INTEGER NOT NULL,rating INTEGER NOT NULL,
            chips TEXT NOT NULL DEFAULT '[]',body TEXT NOT NULL DEFAULT '',public_ok INTEGER NOT NULL DEFAULT 0,contact TEXT NOT NULL DEFAULT '',
            ip_hash TEXT NOT NULL DEFAULT '',created TEXT NOT NULL)""")
        db.execute('CREATE INDEX IF NOT EXISTS qr_feedback_store ON qr_feedback(store_id,created)')
        have = {r[1] for r in db.execute('PRAGMA table_info(qr_stores)')}
        for col in ('naver_url', 'kakao_url', 'owner_phone', 'biz'):
            if col not in have: db.execute("ALTER TABLE qr_stores ADD COLUMN %s TEXT NOT NULL DEFAULT ''" % col)
        db.execute("""CREATE TABLE IF NOT EXISTS qr_apply(id INTEGER PRIMARY KEY,name TEXT NOT NULL,area TEXT NOT NULL DEFAULT '',biz TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL,addr TEXT NOT NULL DEFAULT '',store_id INTEGER,ip_hash TEXT NOT NULL DEFAULT '',created TEXT NOT NULL)""")
        if 'sent' not in {r[1] for r in db.execute('PRAGMA table_info(qr_apply)')}:
            db.execute("ALTER TABLE qr_apply ADD COLUMN sent TEXT NOT NULL DEFAULT ''")
        # 묶음 인쇄 (OH 11/08 '스티커 매번 인쇄 못 해'): 번호만 다른 스티커를 한 번에 찍어 두고, 사장님이 처음 찍을 때 자기 가게로 등록
        db.execute('CREATE TABLE IF NOT EXISTS qr_batches(id INTEGER PRIMARY KEY,first INTEGER NOT NULL,last INTEGER NOT NULL,created TEXT NOT NULL)')
        if not db.execute('SELECT 1 FROM qr_batches WHERE first=?', (FIRST_BATCH[0],)).fetchone():
            db.execute('INSERT INTO qr_batches(first,last,created) VALUES(?,?,?)', (*FIRST_BATCH, datetime.datetime.now().isoformat(timespec='seconds')))

    def now(): return datetime.datetime.now().isoformat(timespec='seconds')

    def store(sid):
        with conn() as db:
            r = db.execute('SELECT * FROM qr_stores WHERE id=? AND hidden=0', (sid,)).fetchone()
        if not r: abort(404)
        return r

    def next_free(db):
        """미리 발급해 둔 묶음에서 아직 가게가 안 붙은 가장 작은 번호"""
        for b in db.execute('SELECT first,last FROM qr_batches ORDER BY first'):
            used = {r[0] for r in db.execute('SELECT id FROM qr_stores WHERE id BETWEEN ? AND ?', (b['first'], b['last']))}
            for i in range(b['first'], b['last'] + 1):
                if i not in used: return i
        return None

    def issued(sid):
        with conn() as db:
            return db.execute('SELECT 1 FROM qr_batches WHERE ?>=first AND ?<=last', (sid, sid)).fetchone() is not None

    @app.route('/q/<int:sid>', methods=['GET', 'POST'])
    def qr_store(sid):
        with conn() as db:
            row = db.execute('SELECT * FROM qr_stores WHERE id=?', (sid,)).fetchone()
        if not row and issued(sid): return qr_claim(sid)  # 아직 가게가 안 붙은 스티커: 사장님 등록 화면
        s = store(sid)
        if request.method == 'POST':
            rating = request.form.get('rating', type=int) or 0
            if not 1 <= rating <= 5: flash('별점을 먼저 골라 주세요.'); return redirect(url_for('qr_store', sid=sid))
            allowed = set(GOOD + BAD)
            chips = [c for c in request.form.getlist('chip') if c in allowed][:8]
            body = ' '.join((request.form.get('body') or '').split())[:500]
            contact = ''  # 답 받을 번호 기능은 뺐다 (OH 11/08)
            public_ok = 1 if rating >= 4 and request.form.get('public_ok') else 0
            iph = S.ip_hash()
            since = (datetime.datetime.now() - datetime.timedelta(minutes=10)).isoformat(timespec='seconds')
            with conn() as db:
                if db.execute('SELECT COUNT(*) FROM qr_feedback WHERE ip_hash=? AND store_id=? AND created>=?', (iph, sid, since)).fetchone()[0] >= 3:
                    return render_template('qr_store.html', s=s, done=True, GOOD=GOOD, BAD=BAD)  # 도배는 조용히 고맙다고만
                db.execute('INSERT INTO qr_feedback(store_id,rating,chips,body,public_ok,contact,ip_hash,created) VALUES(?,?,?,?,?,?,?,?)',
                           (sid, rating, json.dumps(chips, ensure_ascii=False), body, public_ok, contact, iph, now()))
            if rating <= 2 and s['owner_phone']:  # 아쉬운 후기는 그 자리에서 사장님 폰으로 (OH 11/08)
                txt = '[소보루] %s 아쉬운 후기 (별 %d개)\n%s%s' % (s['name'], rating, ', '.join(chips) or '', ('\n"' + body[:60] + '"') if body else '')
                try: threading.Thread(target=S.notify.send_sms, args=(s['owner_phone'], txt), daemon=True).start()
                except Exception: app.logger.exception('qr low alert')
            return redirect(url_for('qr_store', sid=sid, done=1))
        return render_template('qr_store.html', s=s, done=request.args.get('done') == '1', GOOD=GOOD, BAD=BAD)

    def clean(k, n): return ' '.join((request.form.get(k) or '').split())[:n]

    def qr_claim(sid):
        """사장님이 받은 스티커를 처음 찍었을 때: 가게 이름·휴대폰만 넣으면 이 번호가 그 가게 QR이 된다."""
        f = {}
        if request.method == 'POST':
            f = {k: clean(k, n) for k, n in (('name', 40), ('area', 40), ('biz', 20), ('phone', 20))}
            phone = ''.join(c for c in f['phone'] if c.isdigit())
            if not f['name'] or not phone.startswith('01') or len(phone) not in (10, 11) or not request.form.get('agree'):
                flash('가게 이름과 휴대폰 번호를 넣고 개인정보 수집에 동의해 주세요.')
                return render_template('qr_claim.html', sid=sid, f=f, BIZ=BIZ), 400
            with conn() as db:
                if S.recent_count(db, 'qr_apply', 60) >= 5: abort(429)
                if db.execute('SELECT 1 FROM qr_stores WHERE id=?', (sid,)).fetchone(): return redirect(url_for('qr_store', sid=sid))
                db.execute('INSERT INTO qr_stores(id,name,area,owner_phone,biz,created) VALUES(?,?,?,?,?,?)', (sid, f['name'], f['area'], phone, f['biz'], now()))
                a = db.execute("SELECT id FROM qr_apply WHERE phone=? AND store_id IS NULL ORDER BY id DESC", (phone,)).fetchone()
                if a: db.execute('UPDATE qr_apply SET store_id=? WHERE id=?', (sid, a['id']))
                else: db.execute('INSERT INTO qr_apply(name,area,biz,phone,addr,store_id,ip_hash,created) VALUES(?,?,?,?,?,?,?,?)',
                                 (f['name'], f['area'], f['biz'], phone, '', sid, S.ip_hash(), now()))
            try:
                emails, _, _ = S.notify.admin_targets()
                for e in emails:
                    S.notify.send_email(e, '[매장 QR] %d번 스티커 등록: %s %s' % (sid, f['name'], f['area']),
                                        '가게: %s %s\n업종: %s\n연락처: %s\n\n관리자 > 계정 > 매장 QR에서 네이버 지도·카카오맵 주소를 넣어 주세요.' % (f['name'], f['area'], f['biz'], S.notify.fmt_phone(phone)))
            except Exception: app.logger.exception('qr claim mail')
            return render_template('qr_claim.html', sid=sid, f=f, BIZ=BIZ, done=True)
        return render_template('qr_claim.html', sid=sid, f=f, BIZ=BIZ)

    @app.route('/admin/qr/batch', methods=['GET', 'POST'])
    @S.admin_only
    def admin_qr_batch():
        """스티커 묶음: 아직 안 쓴 번호부터 N장을 한 파일(한 쪽에 한 장)로. 인쇄소 '가변 인쇄'에 그대로 보냄."""
        try:
            import segno
        except ImportError:
            return 'QR을 만드는 부품(segno)이 서버에 없어요. 업데이트 파일을 한 번 더 돌려 주세요.', 503
        bid = request.args.get('id', type=int)
        with conn() as db:
            if request.method == 'POST':
                n = max(1, min(1000, request.form.get('count', type=int) or 100))
                top = db.execute('SELECT MAX(x) FROM (SELECT MAX(last) x FROM qr_batches UNION ALL SELECT MAX(id) FROM qr_stores)').fetchone()[0] or 0
                first = max(FIRST_ID, top + 1)
                bid = db.execute('INSERT INTO qr_batches(first,last,created) VALUES(?,?,?)', (first, first + n - 1, now())).lastrowid
                return redirect(url_for('admin_qr_batch', id=bid))
            b = db.execute('SELECT * FROM qr_batches WHERE id=?', (bid,)).fetchone()
        if not b: abort(404)
        items = [(i, segno.make('https://consumerjebo.co.kr/q/%d' % i, error='m').svg_inline(border=0, omitsize=True, svgclass='segno', lineclass='qrline'))
                 for i in range(b['first'], b['last'] + 1)]
        return render_template('qr_sticker.html', items=items, batch=b)

    @app.route('/qr', methods=['GET', 'POST'])
    def qr_apply():
        """사장님용 소개·신청 한 장 (OH 11/08). 신청이 들어오면 관리자 > 매장 QR 맨 위에 쌓이고 운영자에게 메일이 간다."""
        if request.method == 'POST':
            f = {k: clean(k, n) for k, n in (('name', 40), ('area', 40), ('biz', 20), ('phone', 20), ('addr', 120))}
            phone = ''.join(c for c in f['phone'] if c.isdigit())
            if not f['name'] or not phone.startswith('01') or len(phone) not in (10, 11) or not f['addr'] or not request.form.get('agree'):
                flash('가게 이름, 휴대폰 번호, 받을 주소를 넣고 개인정보 수집에 동의해 주세요.')
                return render_template('qr_apply.html', f=f, BIZ=BIZ), 400
            iph = S.ip_hash()
            with conn() as db:
                if S.recent_count(db, 'qr_apply', 60) >= 5: return redirect(url_for('qr_apply', done=1))
                db.execute('INSERT INTO qr_apply(name,area,biz,phone,addr,ip_hash,created) VALUES(?,?,?,?,?,?,?)',
                           (f['name'], f['area'], f['biz'], phone, f['addr'], iph, now()))
            try:
                emails, _, _ = S.notify.admin_targets()
                for e in emails:
                    S.notify.send_email(e, '[매장 QR] 새 신청: %s %s' % (f['name'], f['area']),
                                        '가게: %s %s\n업종: %s\n연락처: %s\n주소: %s\n\n관리자 > 매장 QR에서 번호를 만들어 주세요.'
                                        % (f['name'], f['area'], f['biz'], S.notify.fmt_phone(phone), f['addr']))
            except Exception: S.app.logger.exception('qr apply mail')
            return redirect(url_for('qr_apply', done=1))
        return render_template('qr_apply.html', f={}, BIZ=BIZ, done=request.args.get('done') == '1')

    @app.route('/admin/qr/<int:sid>/sticker')
    @S.admin_only
    def admin_qr_sticker(sid):
        """가게 전용 QR이 찍힌 인쇄용 스티커 한 장. 브라우저 인쇄로 'PDF로 저장'하면 84×114mm(칼선 80×110) 파일이 된다."""
        with conn() as db:
            s = db.execute('SELECT * FROM qr_stores WHERE id=?', (sid,)).fetchone()
        if not s: abort(404)
        url = 'https://consumerjebo.co.kr/q/%d' % sid  # 스티커 QR은 늘 대표 주소로 고정
        try:
            import segno  # 서버에 없으면 업데이트 파일이 venv에 깔아 둔다
        except ImportError:
            return 'QR을 만드는 부품(segno)이 서버에 없어요. 업데이트 파일을 한 번 더 돌려 주세요.', 503
        qr = segno.make(url, error='m').svg_inline(border=0, omitsize=True, svgclass='segno', lineclass='qrline')
        return render_template('qr_sticker.html', s=s, url=url, items=[(sid, qr)])

    @app.route('/admin/qr', methods=['GET', 'POST'])
    @S.admin_only
    def admin_qr():
        if request.method == 'POST':
            name = ' '.join((request.form.get('name') or '').split())[:40]
            area = ' '.join((request.form.get('area') or '').split())[:40]
            def url(k):
                v = (request.form.get(k) or '').strip()[:300]
                return v if v.startswith(('https://', 'http://')) else ''
            naver, kakao = url('naver'), url('kakao')
            owner_phone = ''.join(c for c in (request.form.get('owner_phone') or '') if c.isdigit())[:11]
            biz = ''
            edit = request.form.get('edit', type=int)
            if edit:
                with conn() as db: db.execute('UPDATE qr_stores SET naver_url=?,kakao_url=?,owner_phone=? WHERE id=?', (naver, kakao, owner_phone, edit))
                flash('저장했어요.'); return redirect(url_for('admin_qr', tab='stores'))
            sent = request.form.get('sent', type=int)
            if sent:
                with conn() as db: db.execute('UPDATE qr_apply SET sent=? WHERE id=?', (now(), sent))
                flash('보냄으로 표시했어요. 사장님이 스티커를 처음 찍으면 가게가 자동으로 붙어요.'); return redirect(url_for('admin_qr', tab='apply'))
            app_id = request.form.get('apply', type=int)
            with conn() as db:
                if app_id:
                    a = db.execute('SELECT * FROM qr_apply WHERE id=? AND store_id IS NULL', (app_id,)).fetchone()
                    if not a: return redirect(url_for('admin_qr'))
                    name, area, owner_phone, biz = a['name'], a['area'], a['phone'], a['biz']
            if not name: flash('가게 이름을 넣어 주세요.'); return redirect(url_for('admin_qr'))
            with conn() as db:
                nid = request.form.get('no', type=int)
                if nid and not (db.execute('SELECT 1 FROM qr_batches WHERE ?>=first AND ?<=last', (nid, nid)).fetchone()
                                and not db.execute('SELECT 1 FROM qr_stores WHERE id=?', (nid,)).fetchone()):
                    flash('%d번은 없는 번호이거나 이미 쓴 번호예요.' % nid); return redirect(url_for('admin_qr', tab='stores'))
                nid = nid or next_free(db) or max(FIRST_ID - 1, db.execute('SELECT MAX(COALESCE((SELECT MAX(id) FROM qr_stores),0),COALESCE((SELECT MAX(last) FROM qr_batches),0))').fetchone()[0]) + 1
                db.execute('INSERT INTO qr_stores(id,name,area,naver_url,kakao_url,owner_phone,biz,created) VALUES(?,?,?,?,?,?,?,?)', (nid, name, area, naver, kakao, owner_phone, biz, now()))
                if app_id: db.execute('UPDATE qr_apply SET store_id=? WHERE id=?', (nid, app_id))
            flash('%s에 %d번을 붙였어요. 스티커를 받아 보내 주세요.' % (name, nid)); return redirect(url_for('admin_qr', tab='stores'))
        with conn() as db:
            stores = [dict(r) for r in db.execute("""SELECT s.*,COUNT(f.id) n,ROUND(AVG(f.rating),1) avg,SUM(f.rating<=3) low
                FROM qr_stores s LEFT JOIN qr_feedback f ON f.store_id=s.id GROUP BY s.id ORDER BY s.id DESC""")]
            recent = [dict(r) | {'chips': json.loads(r['chips'] or '[]')} for r in db.execute(
                'SELECT f.*,s.name store FROM qr_feedback f JOIN qr_stores s ON s.id=f.store_id ORDER BY f.id DESC LIMIT 50')]
            applies = [dict(r) for r in db.execute('SELECT * FROM qr_apply ORDER BY store_id IS NOT NULL, id DESC LIMIT 100')]
            batches = [dict(r) | {'used': db.execute('SELECT COUNT(*) FROM qr_stores WHERE id BETWEEN ? AND ?', (r['first'], r['last'])).fetchone()[0]}
                       for r in db.execute('SELECT * FROM qr_batches ORDER BY id DESC')]
            week = (datetime.date.today() - datetime.timedelta(days=6)).isoformat()
            wk = db.execute('SELECT COUNT(*) n,ROUND(AVG(rating),1) a,SUM(rating<=2) low FROM qr_feedback WHERE created>=?', (week,)).fetchone()
            nxt = next_free(db)
            kpi = {'next': nxt, 'free': sum(b['last'] - b['first'] + 1 - b['used'] for b in batches), 'stores': len(stores), 'week': wk['n'] or 0, 'avg': wk['a'], 'low': wk['low'] or 0,
                   'waiting': sum(1 for a in applies if not a['store_id'] and not a['sent'])}
        tab = request.args.get('tab') if request.args.get('tab') in ('stores', 'apply', 'reviews', 'print') else ('apply' if kpi['waiting'] else 'stores')
        return render_template('admin_qr.html', batches=batches, tab=tab, kpi=kpi, stores=stores, recent=recent, applies=applies, fmt_phone=S.notify.fmt_phone, base=S.canonical_url('/q/'))


def weekly_text(db, s, today=None):
    """사장님께 보내는 주간 요약 한 통 (OH 11/08). 지난 7일 후기가 없으면 None."""
    today = today or datetime.date.today()
    since = (today - datetime.timedelta(days=7)).isoformat()
    rows = db.execute('SELECT rating,chips FROM qr_feedback WHERE store_id=? AND created>=?', (s['id'], since)).fetchall()
    if not rows: return None
    avg = sum(r['rating'] for r in rows) / len(rows)
    cnt = {}
    for r in rows:
        for c in json.loads(r['chips'] or '[]'): cnt[c] = cnt.get(c, 0) + 1
    top = lambda pool: max(((n, c) for c, n in cnt.items() if c in pool), default=None)
    good, bad = top(GOOD), top(BAD)
    lines = ['[소보루] %s 이번 주 후기' % s['name'], '후기 %d개, 평균 별 %.1f개예요.' % (len(rows), avg)]
    if good: lines.append("가장 많이 들은 칭찬은 '%s'(%d번)예요." % (good[1], good[0]))
    if bad: lines.append("'%s'가 %d번 있었어요." % (bad[1], bad[0]))
    peer = db.execute("""SELECT AVG(f.rating) a,COUNT(DISTINCT f.store_id) n FROM qr_feedback f JOIN qr_stores x ON x.id=f.store_id
        WHERE f.created>=? AND x.id<>? AND x.hidden=0 AND (?='' OR x.biz=?)""", (since, s['id'], s['biz'], s['biz'])).fetchone()
    if peer['a'] is not None and peer['n'] >= 3:
        who = '같은 업종(%s)' % s['biz'] if s['biz'] else '매장 QR 가게'
        diff = avg - peer['a']
        lines.append('%s 평균 별 %.1f개보다 %s.' % (who, peer['a'], '높아요' if diff >= 0.05 else '조금 낮아요' if diff <= -0.05 else '와 비슷해요'))
    return '\n'.join(lines)


def main(argv):
    """서버 예약 작업: python storeqr.py weekly [--dry]. 매주 월요일 아침 soboru-qrweekly.timer가 부름."""
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import app as site
    sent = 0
    with site.conn() as db:
        stores = db.execute("SELECT * FROM qr_stores WHERE hidden=0 AND owner_phone<>''").fetchall()
        for s in stores:
            txt = weekly_text(db, s)
            if not txt: continue
            if '--dry' in argv: print(txt, '\n'); continue
            try: site.notify.send_sms(s['owner_phone'], txt); sent += 1
            except Exception as e: print('보내지 못함', s['id'], e)
    print('주간 요약 보냄: %d곳' % sent)
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv[1:]))
