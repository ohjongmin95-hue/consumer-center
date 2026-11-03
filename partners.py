"""협력 기관 로고·배너 (운영자 2026-11-03: 검은고양이 '합작기구'처럼 옆에 협력 기관, 제보팀장처럼 로고 띠).
- 관리자 > 제보 > 협력 기관·배너에서 이름·링크·그림을 넣는다. 그림은 서버에서 새로 그려 저장(PNG, 투명 유지)하므로 올린 파일 그대로 나가지 않는다.
- 로고(partner): 첫 화면 '함께하는 기관' 띠(천천히 흐름)와 제보 목록 오른쪽 '협력 기관' 칸에 나온다.
- 배너(banner): 제보 목록 오른쪽 칸 아래에 넓은 그림으로 나온다.
- 하나도 없으면 띠·칸 모두 안 보인다. 숨기기·순서 바꾸기·빼기 가능.
"""
import datetime, io, re, uuid

from flask import abort, flash, redirect, render_template, request, send_file, url_for

KINDS = {'partner': '협력 기관 로고', 'banner': '배너'}
NAME_RE = re.compile(r'[0-9a-f]{32}\.png')
MAX_BYTES = 5 * 1024 * 1024
LOGO_H, BANNER_W = 160, 1200


def shrink(data, kind):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    im.load()
    im = im.convert('RGBA')
    box = im.getbbox()
    if box and kind == 'partner': im = im.crop(box)  # 로고 둘레 빈 곳은 잘라 크기를 맞춤
    if kind == 'partner' and im.height > LOGO_H: im = im.resize((max(1, round(im.width * LOGO_H / im.height)), LOGO_H), Image.LANCZOS)
    if kind == 'banner' and im.width > BANNER_W: im = im.resize((BANNER_W, max(1, round(im.height * BANNER_W / im.width))), Image.LANCZOS)
    out = io.BytesIO(); im.save(out, 'PNG', optimize=True)
    return out.getvalue()


def safe_link(v):
    v = (v or '').strip()[:300]
    return v if re.match(r'https?://[^\s"<>]+$', v) else ''


def install(S):
    app, conn = S.app, S.conn
    folder = S.UPLOAD / 'partners'; folder.mkdir(parents=True, exist_ok=True)
    with conn() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS partners(id INTEGER PRIMARY KEY,kind TEXT NOT NULL DEFAULT 'partner',name TEXT NOT NULL,
            link TEXT NOT NULL DEFAULT '',stored TEXT NOT NULL,width INTEGER NOT NULL DEFAULT 0,height INTEGER NOT NULL DEFAULT 0,
            sort INTEGER NOT NULL DEFAULT 0,hidden INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL)""")

    def rows(kind=None, all_=False):
        with conn() as db:
            q = 'SELECT * FROM partners' + (' WHERE 1=1' if all_ else ' WHERE hidden=0') + (' AND kind=?' if kind else '') + ' ORDER BY sort,id'
            return [dict(r) for r in db.execute(q, (kind,) if kind else ())]

    app.jinja_env.globals['partners'] = lambda: rows('partner')
    app.jinja_env.globals['partner_banners'] = lambda: rows('banner')

    @app.route('/partner/<name>')
    def partner_image(name):
        if not NAME_RE.fullmatch(name) or not (folder / name).exists(): abort(404)
        return send_file(folder / name, mimetype='image/png', max_age=86400 * 30)

    @app.route('/admin/partners', methods=['GET', 'POST'])
    @S.admin_only
    def admin_partners():
        if request.method == 'POST':
            kind = request.form.get('kind') if request.form.get('kind') in KINDS else 'partner'
            name = ' '.join((request.form.get('name') or '').split())[:60]
            f = request.files.get('image')
            data = f.read(MAX_BYTES + 1) if f else b''
            if not name or not data: flash('이름과 그림을 넣어 주세요.'); return redirect(url_for('admin_partners'))
            if len(data) > MAX_BYTES: flash('그림은 5MB까지 올릴 수 있어요.'); return redirect(url_for('admin_partners'))
            try: png = shrink(data, kind)
            except Exception: flash('그림 파일(PNG·JPG·WEBP)만 올릴 수 있어요.'); return redirect(url_for('admin_partners'))
            from PIL import Image
            w, h = Image.open(io.BytesIO(png)).size
            stored = uuid.uuid4().hex + '.png'; (folder / stored).write_bytes(png)
            with conn() as db:
                top = db.execute('SELECT COALESCE(MAX(sort),0) FROM partners').fetchone()[0]
                db.execute('INSERT INTO partners(kind,name,link,stored,width,height,sort,created) VALUES(?,?,?,?,?,?,?,?)',
                           (kind, name, safe_link(request.form.get('link')), stored, w, h, top + 1, datetime.datetime.now().isoformat(timespec='seconds')))
            flash('넣었어요.'); return redirect(url_for('admin_partners'))
        return render_template('admin_partners.html', items=rows(all_=True), kinds=KINDS)

    @app.route('/admin/partners/<int:pid>', methods=['POST'])
    @S.admin_only
    def admin_partner_edit(pid):
        act = request.form.get('act')
        with conn() as db:
            r = db.execute('SELECT * FROM partners WHERE id=?', (pid,)).fetchone()
            if not r: abort(404)
            if act == 'delete':
                db.execute('DELETE FROM partners WHERE id=?', (pid,))
                if NAME_RE.fullmatch(r['stored']): (folder / r['stored']).unlink(missing_ok=True)
            elif act == 'save':
                db.execute('UPDATE partners SET name=?,link=? WHERE id=?', (' '.join((request.form.get('name') or r['name']).split())[:60], safe_link(request.form.get('link')), pid))
            elif act == 'hide': db.execute('UPDATE partners SET hidden=1-hidden WHERE id=?', (pid,))
            elif act in ('up', 'down'):
                same = [x['id'] for x in db.execute('SELECT id FROM partners WHERE kind=? ORDER BY sort,id', (r['kind'],))]
                i = same.index(pid); j = i - 1 if act == 'up' else i + 1
                if 0 <= j < len(same):
                    same[i], same[j] = same[j], same[i]
                    for n, x in enumerate(same): db.execute('UPDATE partners SET sort=? WHERE id=?', (n, x))
        return redirect(url_for('admin_partners'))
