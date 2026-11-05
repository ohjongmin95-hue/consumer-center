"""만든 카드뉴스·릴스 보관함 (운영자 2026-11-05).

카드뉴스·릴스 만들기에서 만든 것과, 클로드가 시간마다 자동으로 만들어 보내는 것을 서버에 저장해 두고
관리자 > 매거진 > '만든 것 보관함'에서 목록으로 본다. 사라져 버리지 않게.

- 저장: private_uploads/made/<번호>/ 에 파일 (카드 01.png… / 릴스 reel.mp4), 표에는 제목·캡션·출처·만든 이.
- 관리자 화면에서 만든 것: 카드는 '내려받기'를 누를 때, 릴스는 영상이 다 만들어질 때 저장된다.
- 자동으로 만드는 쪽(클로드 예약 작업)은 /api/maker/... 로 보낸다. 서버 /etc/soboru.env 의 MAKER_API_TOKEN을
  'Authorization: Bearer <토큰>' 으로 붙인다 (deploy/set-maker-token.sh 로 만든다).
    1) POST /api/maker/items            JSON {kind: card|reel, title, caption, source}  → {id}
    2) POST /api/maker/items/<id>/file?name=01.png   본문 = 파일 바이트 (8MB까지; 큰 영상은 part=0,1,2… 로 나눠 같은 이름에 이어 붙임)
    3) POST /api/maker/items/<id>/done                 → 보관함 목록에 보임
    GET  /api/maker/items?limit=30                    최근 것 (같은 기사를 또 만들지 않게 확인용)
"""
import datetime
import hmac
import io
import json
import os
import re
import secrets
import shutil
import zipfile

from flask import abort, flash, jsonify, redirect, render_template, request, send_file, url_for

KINDS = {'card': '카드뉴스', 'reel': '릴스'}
NAME = re.compile(r'(?:\d{2}\.(?:png|jpg|webp)|reel\.mp4)')
CHUNK = 8 * 1024 * 1024
MAX_CARD = 20
MAX_REEL = 300 * 1024 * 1024
MIME = {'png': 'image/png', 'jpg': 'image/jpeg', 'webp': 'image/webp', 'mp4': 'video/mp4'}
MAGIC = {'png': (b'\x89PNG',), 'jpg': (b'\xff\xd8\xff',), 'webp': (b'RIFF',)}


def install(S):
    app, conn = S.app, S.conn
    root = S.UPLOAD / 'made'; root.mkdir(parents=True, exist_ok=True)
    art = S.UPLOAD / 'art'
    with conn() as db:
        db.execute("CREATE TABLE IF NOT EXISTS made_items(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,title TEXT NOT NULL DEFAULT '',caption TEXT NOT NULL DEFAULT '',"
                   "source TEXT NOT NULL DEFAULT '',maker TEXT NOT NULL DEFAULT 'admin',files TEXT NOT NULL DEFAULT '[]',done INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL)")

    def clean(v, n): return ' '.join(str(v or '').split())[:n] if n < 200 else str(v or '').strip()[:n]

    def create(kind, title, caption, source, maker):
        if kind not in KINDS: return None
        with conn() as db:
            # 하루 넘게 다 못 올린 것은 치움
            old = (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat(timespec='seconds')
            for r in db.execute('SELECT id FROM made_items WHERE done=0 AND created<?', (old,)).fetchall():
                shutil.rmtree(root / str(r[0]), ignore_errors=True); db.execute('DELETE FROM made_items WHERE id=?', (r[0],))
            i = db.execute('INSERT INTO made_items(kind,title,caption,source,maker,created) VALUES(?,?,?,?,?,?)',
                           (kind, clean(title, 120), clean(caption, 4000), clean(source, 300), maker, S.now())).lastrowid
        (root / str(i)).mkdir(exist_ok=True)
        return i

    def item(i, done=None):
        with conn() as db:
            r = db.execute('SELECT * FROM made_items WHERE id=?', (i,)).fetchone()
        if not r or (done is not None and bool(r['done']) != done): return None
        r = dict(r); r['files'] = json.loads(r['files'] or '[]'); return r

    def add_file(i, name, data, part=0):
        """파일 한 개(또는 영상 한 조각)를 붙임. 잘못되면 오류 글, 되면 ''."""
        r = item(i, done=False)
        if not r: return '없는 항목이에요.'
        if not NAME.fullmatch(name or ''): return '파일 이름은 01.png·02.jpg… 또는 reel.mp4 로 보내 주세요.'
        ext = name.rsplit('.', 1)[1]
        if (ext == 'mp4') != (r['kind'] == 'reel'): return '카드뉴스는 그림, 릴스는 reel.mp4 하나만 보내 주세요.'
        if not data or len(data) > CHUNK: return '파일이 비었거나 한 번에 8MB를 넘어요. 나눠서 보내 주세요.'
        f = root / str(i) / name
        if part == 0:
            if ext != 'mp4' and not data.startswith(MAGIC[ext]): return '그림 파일이 아니에요.'
            if ext != 'mp4' and len(set(r['files']) | {name}) > MAX_CARD: return f'카드는 {MAX_CARD}장까지예요.'
            f.write_bytes(data)
        else:
            if not f.is_file() or f.stat().st_size + len(data) > MAX_REEL: return '영상 앞 조각이 없거나 너무 커요.'
            with f.open('ab') as out: out.write(data)
        if name not in r['files']:
            with conn() as db: db.execute('UPDATE made_items SET files=? WHERE id=?', (json.dumps(sorted(r['files'] + [name])), i))
        return ''

    def finish(i):
        r = item(i, done=False)
        if not r: return '없는 항목이에요.'
        if not r['files']: return '파일을 먼저 보내 주세요.'
        if r['kind'] == 'reel' and not (root / str(i) / 'reel.mp4').read_bytes()[4:8] == b'ftyp': return 'MP4 영상이 아니에요.'
        with conn() as db: db.execute('UPDATE made_items SET done=1 WHERE id=?', (i,))
        return ''

    def save_reel(video, title, caption, source, maker='admin'):
        """만들기에서 다 만든 릴스 영상을 보관함에도 넣음 (원본 영상은 그대로 두고 복사)."""
        i = create('reel', title, caption, source, maker)
        if not i: return None
        dst = root / str(i) / 'reel.mp4'
        try: os.link(video, dst)
        except OSError: shutil.copyfile(video, dst)
        with conn() as db: db.execute("UPDATE made_items SET files='[\"reel.mp4\"]',done=1 WHERE id=?", (i,))
        return i
    S.made_save_reel = save_reel
    app.extensions['made_save_reel'] = save_reel

    # ---- 자동으로 만드는 쪽 (토큰) ----------------------------------------------------
    def token_ok():
        want = os.getenv('MAKER_API_TOKEN', '')
        got = request.headers.get('Authorization', '')
        return len(want) >= 24 and hmac.compare_digest(got.encode(), ('Bearer ' + want).encode())

    def api(fn):
        def wrap(*a, **k):
            if not token_ok(): return jsonify(ok=False, error='토큰이 맞지 않아요.'), 401
            return fn(*a, **k)
        wrap.__name__ = fn.__name__; return wrap

    @app.route('/api/maker/items', methods=['GET', 'POST'])
    @api
    def made_api_items():
        if request.method == 'GET':
            n = min(100, max(1, request.args.get('limit', 30, type=int)))
            with conn() as db:
                rows = db.execute('SELECT id,kind,title,source,maker,created FROM made_items WHERE done=1 ORDER BY id DESC LIMIT ?', (n,)).fetchall()
            return jsonify(ok=True, items=[dict(r) for r in rows])
        d = request.get_json(silent=True) or {}
        i = create(d.get('kind'), d.get('title'), d.get('caption'), d.get('source'), 'auto')
        if not i: return jsonify(ok=False, error='kind는 card 또는 reel 이에요.'), 400
        return jsonify(ok=True, id=i)

    @app.route('/api/maker/items/<int:i>/file', methods=['POST'])
    @api
    def made_api_file(i):
        err = add_file(i, request.args.get('name', ''), request.get_data(), request.args.get('part', 0, type=int))
        return (jsonify(ok=False, error=err), 400) if err else jsonify(ok=True)

    @app.route('/api/maker/items/<int:i>/done', methods=['POST'])
    @api
    def made_api_done(i):
        err = finish(i)
        return (jsonify(ok=False, error=err), 400) if err else jsonify(ok=True, url=url_for('mag_made_view', i=i, _external=True))

    # ---- 관리자 화면 ------------------------------------------------------------------
    @app.route('/admin/magazine/made/new', methods=['POST'])
    @S.admin_only
    def mag_made_new():
        d = request.get_json(silent=True) or {}
        i = create(d.get('kind'), d.get('title'), d.get('caption'), d.get('source'), 'admin')
        return jsonify(ok=True, id=i) if i else (jsonify(ok=False, error='저장하지 못했어요.'), 400)

    @app.route('/admin/magazine/made/<int:i>/file', methods=['POST'])
    @S.admin_only
    def mag_made_file_up(i):
        err = add_file(i, request.args.get('name', ''), request.get_data(), request.args.get('part', 0, type=int))
        return (jsonify(ok=False, error=err), 400) if err else jsonify(ok=True)

    @app.route('/admin/magazine/made/<int:i>/done', methods=['POST'])
    @S.admin_only
    def mag_made_done(i):
        err = finish(i)
        return (jsonify(ok=False, error=err), 400) if err else jsonify(ok=True, url=url_for('mag_made_view', i=i))

    @app.route('/admin/magazine/made')
    @S.admin_only
    def mag_made_list():
        kind = request.args.get('kind', '')
        kind = kind if kind in KINDS else ''
        who = request.args.get('by', '')
        who = who if who in ('auto', 'admin') else ''
        q, args = 'SELECT * FROM made_items WHERE done=1', []
        if kind: q += ' AND kind=?'; args.append(kind)
        if who: q += ' AND maker=?'; args.append(who)
        with conn() as db:
            rows = [dict(r) for r in db.execute(q + ' ORDER BY id DESC LIMIT 300', args)]
            counts = {r['kind']: r['n'] for r in db.execute('SELECT kind,COUNT(*) AS n FROM made_items WHERE done=1 GROUP BY kind')}
        for r in rows: r['files'] = json.loads(r['files'] or '[]')
        return render_template('mag_admin_made.html', rows=rows, kind=kind, who=who, counts=counts, kinds=KINDS,
                               has_token=len(os.getenv('MAKER_API_TOKEN', '')) >= 24)

    @app.route('/admin/magazine/made/<int:i>')
    @S.admin_only
    def mag_made_view(i):
        r = item(i, done=True)
        if not r: abort(404)
        return render_template('mag_admin_made_view.html', r=r, kinds=KINDS)

    @app.route('/admin/magazine/made/<int:i>/<name>')
    @S.admin_only
    def mag_made_file(i, name):
        if not NAME.fullmatch(name): abort(404)
        f = root / str(i) / name
        if not f.is_file(): abort(404)
        dl = request.args.get('dl') == '1'
        return send_file(f, mimetype=MIME[name.rsplit('.', 1)[1]], conditional=True, as_attachment=dl,
                         download_name=f'soboru-{"reel" if name.endswith("mp4") else "card"}-{i}-{name}')

    @app.route('/admin/magazine/made/<int:i>.zip')
    @S.admin_only
    def mag_made_zip(i):
        r = item(i, done=True)
        if not r: abort(404)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
            for n in r['files']:
                f = root / str(i) / n
                if f.is_file(): z.write(f, f'soboru-card-{i}-{n}')
            if r['caption']: z.writestr('caption.txt', r['caption'])
        buf.seek(0)
        return send_file(buf, mimetype='application/zip', as_attachment=True, download_name=f'soboru-card-{i}.zip')

    @app.route('/admin/magazine/made/<int:i>/act', methods=['POST'])
    @S.admin_only
    def mag_made_act(i):
        r = item(i, done=True)
        if not r: abort(404)
        act = request.form.get('act')
        if act == 'del':
            shutil.rmtree(root / str(i), ignore_errors=True)
            with conn() as db: db.execute('DELETE FROM made_items WHERE id=?', (i,))
            flash('지웠어요.'); return redirect(url_for('mag_made_list'))
        if act == 'save':
            with conn() as db: db.execute('UPDATE made_items SET title=?,caption=? WHERE id=?', (clean(request.form.get('title'), 120), clean(request.form.get('caption'), 4000), i))
            flash('저장했어요.')
        if act == 'reel' and r['kind'] == 'reel':  # 매거진 첫 화면 REELS 칸에 올림 — 영상을 기사 영상 폴더로 복사
            name = f'video-{datetime.datetime.now():%Y%m%d%H%M%S}-{secrets.randbelow(1000):03d}.mp4'
            art.mkdir(parents=True, exist_ok=True)
            try: os.link(root / str(i) / 'reel.mp4', art / name)
            except OSError: shutil.copyfile(root / str(i) / 'reel.mp4', art / name)
            with conn() as db:
                low = db.execute('SELECT MIN(sort) FROM mag_reels').fetchone()[0]
                db.execute('INSERT INTO mag_reels(title,video,ig,sort,created) VALUES(?,?,?,?,?)', (r['title'][:60], url_for('mag_body_video', name=name), '', (low or 0) - 1, S.now()))
            flash('매거진 첫 화면 릴스 칸 맨 앞에 올렸어요.')
        return redirect(url_for('mag_made_view', i=i))
