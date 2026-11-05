"""소보루 매거진 관리자 (운영자 2026-11-05).

관리자 화면 하나 안에서 위쪽 전환 버튼으로 '소비자제보센터'와 '소보루 매거진'을 오가고, 두 쪽 메뉴는 겹치지 않는다.
매거진 쪽에 있는 것:
- 매거진 홈: 게시·초안·예약 글 수, 최근 글
- 기사(CMS): 예전 생활정보 글 화면(admin_life)을 그대로 쓰되 대표 사진 올리기, 본문 사진 끼워 넣기, 예약 게시를 더함
- 첫 화면 편집: 표지 사진 바꾸기, HOT ISSUE 네 개 직접 고르기
"""
import datetime
import json
import re
import time
from flask import abort, flash, jsonify, redirect, render_template, request, send_file, url_for

# 매거진 쪽 메뉴에 속하는 화면 (나머지는 모두 소비자제보센터 쪽)
MAG_ENDPOINTS = {'admin_art'}  # 이름이 mag_·admin_life·admin_letter로 시작하는 화면도 매거진 쪽
MAG_GROUPS = [
    ('', [('mag_home', 'home', '매거진 홈')]),
    ('기사', [('admin_life', 'edit', '기사 쓰기·고치기'), ('admin_life_ai', 'text', 'AI 기사')]),
    ('화면', [('mag_front', 'layers', '첫 화면 편집'), ('admin_art', 'image', '기사 사진')]),
    ('구독', [('admin_letter', 'mail', '소보루 레터')]),
]
PHOTO_TYPES = ('image/jpeg', 'image/png', 'image/webp')


def install(S):
    app, conn = S.app, S.conn
    folder = S.UPLOAD / 'art'; folder.mkdir(parents=True, exist_ok=True)
    with conn() as db:
        db.execute('CREATE TABLE IF NOT EXISTS soboru_settings(key TEXT PRIMARY KEY, value TEXT)')

    def setting(key, default):
        with conn() as db: row = db.execute('SELECT value FROM soboru_settings WHERE key=?', (key,)).fetchone()
        try: return json.loads(row[0]) if row else default
        except ValueError: return default

    def put(key, value):
        with conn() as db: db.execute('INSERT OR REPLACE INTO soboru_settings(key,value) VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))

    def stamp(): return datetime.datetime.now().isoformat(timespec='seconds')

    def admin_space():
        """지금 관리자 화면이 어느 쪽인지: 'mag' 또는 'jebo'. 레터의 하위 화면처럼 이름이 admin_letter로 시작하면 매거진."""
        ep = request.endpoint or ''
        return 'mag' if ep in MAG_ENDPOINTS or ep.startswith(('mag_', 'admin_letter', 'admin_life')) else 'jebo'
    app.jinja_env.globals.update(admin_space=admin_space, mag_groups=MAG_GROUPS)

    # ---- 사진 저장 (대표 사진·본문 사진·표지 사진) ---------------------------------
    def read_photo(f, size=2400):
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(f.stream)).convert('RGB'); im.thumbnail((size, size))
        return im

    def save_cover(article_id, f):
        """기사 대표 사진: AI 그림 화면의 '사진 올리기'와 같은 자리(soboru_art, '-photo-')에 저장해 매거진이 바로 씀."""
        im = read_photo(f)
        name = f'life-{article_id}-photo-{datetime.datetime.now():%Y%m%d%H%M%S}.webp'
        im.save(folder / name, 'WEBP', quality=84)
        with conn() as db:
            old = db.execute("SELECT file FROM soboru_art WHERE kind='life' AND target_id=?", (article_id,)).fetchone()
            db.execute("INSERT OR REPLACE INTO soboru_art(kind,target_id,file,status,created,style) VALUES('life',?,?,'live',?,0)", (article_id, name, stamp()))
        if old and old['file'] != name: (folder / old['file']).unlink(missing_ok=True)

    @app.route('/art/body/<name>')
    def mag_body_image(name):
        if not re.fullmatch(r'body-\d{14}-\d{3}\.webp', name) or not (folder / name).is_file(): abort(404)
        return send_file(folder / name, mimetype='image/webp', max_age=86400 * 30)

    @app.route('/art/front/hero.webp')
    def mag_hero_image():
        name = setting('mag_hero', {}).get('file', '')
        if not name or not (folder / name).is_file(): abort(404)
        return send_file(folder / name, mimetype='image/webp', max_age=3600)

    def mag_hero_url():
        h = setting('mag_hero', {})
        if h.get('file') and (folder / h['file']).is_file(): return url_for('mag_hero_image', v=h['file'][-19:-5])
        return S.asset('img/mag-hero.jpg')

    def mag_hot(mag):
        """첫 화면 HOT ISSUE 네 개: 운영자가 고른 글(게시 중인 것만) 먼저, 모자라면 최신 글로 채움."""
        picks = [i for i in setting('mag_hot', []) if isinstance(i, int)][:4]
        rows = []
        if picks:
            with conn() as db:
                got = {r['id']: r for r in db.execute('SELECT * FROM articles WHERE status=? AND id IN (%s)' % ','.join('?' * len(picks)), ['published', *picks])}
            rows = [got[i] for i in picks if i in got]
        for r in list(mag)[1:]:
            if len(rows) >= 4: break
            if r['id'] not in {x['id'] for x in rows}: rows.append(r)
        return rows[:4]
    app.jinja_env.globals.update(mag_hero_url=mag_hero_url, mag_hot=mag_hot)

    # ---- 예약 게시: 정한 때가 지난 예약 글을 게시로 (1분에 한 번만 확인) ------------------
    last_check = {'at': 0}

    @app.before_request
    def mag_publish_due():
        if time.time() - last_check['at'] < 60: return
        last_check['at'] = time.time()
        try:
            with conn() as db:
                db.execute("UPDATE articles SET status='published' WHERE status='scheduled' AND published_at<=?", (stamp(),))
        except Exception as e: app.logger.warning('예약 게시 확인 실패: %s', e)

    # 기사 화면(admin_life·admin_life_edit)에 대표 사진·예약 게시를 더함: 원래 함수를 감싸서, 저장한 다음에 붙임
    def wrap(endpoint):
        old = app.view_functions[endpoint]
        def view(*a, **kw):
            if request.method != 'POST' or not S.admin_active(): return old(*a, **kw)
            act = request.form.get('act', '')
            when = request.form.get('publish_at', '').strip()
            resp = old(*a, **kw)
            aid = kw.get('article_id')
            if aid is None:  # 새 글: 저장 뒤 옮겨 가는 주소에서 번호를 얻음
                m = re.search(r'/admin/life/(\d+)', resp.headers.get('Location', '') if hasattr(resp, 'headers') else '')
                aid = int(m[1]) if m else None
            if aid is None or act == 'delete': return resp
            f = request.files.get('cover')
            if f and f.filename:
                if f.mimetype not in PHOTO_TYPES: flash('대표 사진은 JPG·PNG·WEBP 파일만 올릴 수 있어요.')
                else:
                    try: save_cover(aid, f); flash('대표 사진을 바꿨어요.')
                    except Exception: flash('대표 사진을 읽지 못했어요. 다른 파일로 올려 주세요.')
            if act == 'publish':  # 예약해 둔 글을 지금 바로 게시하면 게시 시각도 지금으로
                with conn() as db: db.execute("UPDATE articles SET published_at=? WHERE id=? AND published_at>?", (stamp(), aid, stamp()))
            if act == 'schedule':
                try: at = datetime.datetime.fromisoformat(when)
                except ValueError: flash('예약할 날짜와 시각을 골라 주세요.'); return resp
                if at <= datetime.datetime.now(): flash('예약 시각은 지금보다 뒤로 골라 주세요.'); return resp
                with conn() as db: db.execute("UPDATE articles SET status='scheduled',published_at=? WHERE id=?", (at.isoformat(timespec='seconds'), aid))
                flash(f'{at:%m월 %d일 %H:%M}에 게시되도록 예약했어요.')
            return resp
        view.__name__ = old.__name__
        app.view_functions[endpoint] = view
    wrap('admin_life'); wrap('admin_life_edit')

    @app.route('/admin/magazine/photo', methods=['POST'])
    @S.admin_only
    def mag_body_upload():
        """본문에 끼워 넣을 사진: 올리면 주소를 돌려주고, 화면에서 본문 커서 자리에 [사진] 줄을 넣음."""
        f = request.files.get('photo')
        if not f or not f.filename or f.mimetype not in PHOTO_TYPES: return jsonify(ok=False, error='JPG·PNG·WEBP 사진을 골라 주세요.'), 400
        try: im = read_photo(f, 2000)
        except Exception: return jsonify(ok=False, error='사진을 읽지 못했어요.'), 400
        name = f'body-{datetime.datetime.now():%Y%m%d%H%M%S}-{int(time.time() * 1000) % 1000:03d}.webp'
        im.save(folder / name, 'WEBP', quality=84)
        return jsonify(ok=True, url=url_for('mag_body_image', name=name))

    # ---- 매거진 홈 -------------------------------------------------------------
    @app.route('/admin/magazine')
    @S.admin_only
    def mag_home():
        with conn() as db:
            n = {s: db.execute('SELECT COUNT(*) FROM articles WHERE status=?', (s,)).fetchone()[0] for s in ('published', 'draft', 'scheduled')}
            recent = db.execute('SELECT id,title,status,category,published_at,created,views FROM articles ORDER BY id DESC LIMIT 8').fetchall()
            top = db.execute("SELECT id,title,views FROM articles WHERE status='published' ORDER BY views DESC LIMIT 5").fetchall()
            scheduled = db.execute("SELECT id,title,published_at FROM articles WHERE status='scheduled' ORDER BY published_at LIMIT 5").fetchall()
        return render_template('mag_admin_home.html', n=n, recent=recent, top=top, scheduled=scheduled)

    # ---- 첫 화면 편집 ----------------------------------------------------------
    @app.route('/admin/magazine/front', methods=['GET', 'POST'])
    @S.admin_only
    def mag_front():
        if request.method == 'POST':
            act = request.form.get('act')
            if act == 'hero':
                f = request.files.get('hero')
                if not f or not f.filename or f.mimetype not in PHOTO_TYPES: flash('표지 사진은 JPG·PNG·WEBP 파일로 골라 주세요.'); return redirect(url_for('mag_front'))
                try: im = read_photo(f, 2400)
                except Exception: flash('사진을 읽지 못했어요.'); return redirect(url_for('mag_front'))
                old = setting('mag_hero', {}).get('file')
                name = f'mag-hero-{datetime.datetime.now():%Y%m%d%H%M%S}.webp'
                im.save(folder / name, 'WEBP', quality=86)
                put('mag_hero', {'file': name, 'at': stamp()})
                if old and old != name: (folder / old).unlink(missing_ok=True)
                flash('표지 사진을 바꿨어요.')
            elif act == 'hero_reset':
                old = setting('mag_hero', {}).get('file')
                if old: (folder / old).unlink(missing_ok=True)
                put('mag_hero', {}); flash('표지 사진을 처음 사진(초콜릿)으로 되돌렸어요.')
            elif act == 'hot':
                ids = []
                for k in ('hot1', 'hot2', 'hot3', 'hot4'):
                    v = request.form.get(k, type=int)
                    if v and v not in ids: ids.append(v)
                put('mag_hot', ids); flash('HOT ISSUE를 저장했어요.' if ids else 'HOT ISSUE를 최신 글 순서로 되돌렸어요.')
            return redirect(url_for('mag_front'))
        with conn() as db:
            rows = db.execute("SELECT id,title,category,published_at FROM articles WHERE status='published' ORDER BY published_at DESC, id DESC LIMIT 200").fetchall()
        picks = setting('mag_hot', [])
        return render_template('mag_admin_front.html', rows=rows, picks=picks + [None] * (4 - len(picks)), hero=mag_hero_url(), custom=bool(setting('mag_hero', {}).get('file')))
