"""매장 QR (운영자 2026-11-08): 가게에 붙인 스티커 QR을 찍으면 /q/<번호> 한 장짜리 화면이 열린다.
- 손님은 별점 하나 누르고, 고른 별점에 맞는 칩(좋았던 점·아쉬운 점)을 고르면 끝. 글은 안 써도 된다.
- 좋았던 후기는 손님이 '가게 후기로 보여줘도 돼요'를 켰을 때만 공개 후보가 된다. 아쉬운 점은 사장님과 소보루만 본다.
- 번호는 10001부터. 관리자 > 매장 QR에서 가게를 넣으면 번호가 붙는다.
- 공개 제보(소비자제보센터)와는 따로 저장한다. 화면 맨 아래 글 링크로만 제보하기를 알린다.
"""
import datetime, hashlib, hmac, json

from flask import abort, flash, redirect, render_template, request, url_for

GOOD = ['친절해요', '맛있어요', '깨끗해요', '빨리 나와요', '가격이 좋아요', '분위기가 좋아요', '또 올래요']
BAD = ['오래 기다렸어요', '불친절했어요', '주문이 틀렸어요', '청결이 아쉬워요', '가격이 비싸요', '안내가 부족해요', '시끄러웠어요']
FIRST_ID = 10001


def install(S):
    app, conn = S.app, S.conn
    with conn() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS qr_stores(id INTEGER PRIMARY KEY,name TEXT NOT NULL,area TEXT NOT NULL DEFAULT '',
            hidden INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS qr_feedback(id INTEGER PRIMARY KEY,store_id INTEGER NOT NULL,rating INTEGER NOT NULL,
            chips TEXT NOT NULL DEFAULT '[]',body TEXT NOT NULL DEFAULT '',public_ok INTEGER NOT NULL DEFAULT 0,contact TEXT NOT NULL DEFAULT '',
            ip_hash TEXT NOT NULL DEFAULT '',created TEXT NOT NULL)""")
        db.execute('CREATE INDEX IF NOT EXISTS qr_feedback_store ON qr_feedback(store_id,created)')

    def now(): return datetime.datetime.now().isoformat(timespec='seconds')

    def store(sid):
        with conn() as db:
            r = db.execute('SELECT * FROM qr_stores WHERE id=? AND hidden=0', (sid,)).fetchone()
        if not r: abort(404)
        return r

    @app.route('/q/<int:sid>', methods=['GET', 'POST'])
    def qr_store(sid):
        s = store(sid)
        if request.method == 'POST':
            rating = request.form.get('rating', type=int) or 0
            if not 1 <= rating <= 5: flash('별점을 먼저 골라 주세요.'); return redirect(url_for('qr_store', sid=sid))
            allowed = set(GOOD + BAD)
            chips = [c for c in request.form.getlist('chip') if c in allowed][:7]
            body = ' '.join((request.form.get('body') or '').split())[:500]
            contact = ''.join(ch for ch in (request.form.get('contact') or '') if ch.isdigit())[:11] if rating <= 3 else ''
            public_ok = 1 if rating >= 4 and request.form.get('public_ok') else 0
            iph = S.ip_hash()
            since = (datetime.datetime.now() - datetime.timedelta(minutes=10)).isoformat(timespec='seconds')
            with conn() as db:
                if db.execute('SELECT COUNT(*) FROM qr_feedback WHERE ip_hash=? AND store_id=? AND created>=?', (iph, sid, since)).fetchone()[0] >= 3:
                    return render_template('qr_store.html', s=s, done=True, GOOD=GOOD, BAD=BAD)  # 도배는 조용히 고맙다고만
                db.execute('INSERT INTO qr_feedback(store_id,rating,chips,body,public_ok,contact,ip_hash,created) VALUES(?,?,?,?,?,?,?,?)',
                           (sid, rating, json.dumps(chips, ensure_ascii=False), body, public_ok, contact, iph, now()))
            return redirect(url_for('qr_store', sid=sid, done=1))
        return render_template('qr_store.html', s=s, done=request.args.get('done') == '1', GOOD=GOOD, BAD=BAD)

    @app.route('/admin/qr', methods=['GET', 'POST'])
    @S.admin_only
    def admin_qr():
        if request.method == 'POST':
            name = ' '.join((request.form.get('name') or '').split())[:40]
            area = ' '.join((request.form.get('area') or '').split())[:40]
            if not name: flash('가게 이름을 넣어 주세요.'); return redirect(url_for('admin_qr'))
            with conn() as db:
                nid = max(FIRST_ID - 1, db.execute('SELECT COALESCE(MAX(id),0) FROM qr_stores').fetchone()[0]) + 1
                db.execute('INSERT INTO qr_stores(id,name,area,created) VALUES(?,?,?,?)', (nid, name, area, now()))
            flash('%s 번호 %d을 만들었어요.' % (name, nid)); return redirect(url_for('admin_qr'))
        with conn() as db:
            stores = [dict(r) for r in db.execute("""SELECT s.*,COUNT(f.id) n,ROUND(AVG(f.rating),1) avg,SUM(f.rating<=3) low
                FROM qr_stores s LEFT JOIN qr_feedback f ON f.store_id=s.id GROUP BY s.id ORDER BY s.id DESC""")]
            recent = [dict(r) | {'chips': json.loads(r['chips'] or '[]')} for r in db.execute(
                'SELECT f.*,s.name store FROM qr_feedback f JOIN qr_stores s ON s.id=f.store_id ORDER BY f.id DESC LIMIT 50')]
        return render_template('admin_qr.html', stores=stores, recent=recent, base=S.canonical_url('/q/'))
