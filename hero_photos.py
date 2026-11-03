"""첫 화면 배경 사진 (운영자 2026-11-03: 소비자제보센터 첫 화면 뒤에 실제 제보 사진을).

- 관리자 > 제보 > 첫 화면 사진에서 제보에 붙은 사진(또는 직접 올린 사진)을 골라 넣는다.
- 원본은 그대로 비공개로 두고, 3:4로 자르고 줄인 '가린 사본'만 새로 만들어 공개한다 (/hero/<이름>.jpg).
  가리는 방법: 사진 전체를 잘게 모자이크(기본) 하거나, 관리자가 네모로 칠한 곳만 굵게 모자이크.
  이름·전화번호·주소·주문번호·얼굴처럼 알아볼 수 있는 것은 관리자가 미리 보기로 확인하고 넣는다.
- 사진이 3장 이상이면 제보센터 첫 화면의 큰 제목 칸(hero) 뒤에 사진 벽이 깔린다. 적으면 예전 그림 그대로.
"""
import io
import json
import re
import secrets

from flask import abort, flash, redirect, render_template, request, send_file, url_for

W, H = 600, 800  # 공개 사본 크기 (3:4)
FINE = 64        # 전체 모자이크: 가로 칸 수 (사물은 보이고 글씨는 못 읽음)
COARSE = 14      # 네모 칠한 곳: 가로 칸 수 (사진 전체 기준, 굵게)
MAX_PHOTOS = 18
MIN_PHOTOS = 3
IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.webp')
NAME_RE = re.compile(r'[0-9a-f]{24}\.jpg')


def cover(im):
    """가운데를 3:4로 잘라 W×H로."""
    from PIL import Image
    w, h = im.size
    if w * H > h * W:
        nw = h * W // H; im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = w * H // W; im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    return im.resize((W, H), Image.LANCZOS)


def mosaic(im, cells):
    from PIL import Image
    w, h = im.size
    small = im.resize((cells, max(1, round(cells * h / w))), Image.BOX)
    return small.resize((w, h), Image.NEAREST)


def clean_boxes(text):
    """[[x,y,w,h], ...] (0~1 비율) → 픽셀 네모 목록."""
    try: raw = json.loads(text or '[]')
    except ValueError: return []
    out = []
    for b in raw[:30] if isinstance(raw, list) else []:
        try: x, y, w, h = (min(1.0, max(0.0, float(v))) for v in b)
        except (TypeError, ValueError): continue
        if w > 0.005 and h > 0.005:
            out.append((round(x * W), round(y * H), round(min(1, x + w) * W), round(min(1, y + h) * H)))
    return out


def make_copy(data, mode, boxes):
    """원본 바이트 → 가린 사본 JPEG 바이트 (못 열면 b'')."""
    from PIL import Image, ImageOps
    try:
        im = Image.open(io.BytesIO(data))
        if im.width * im.height > 40_000_000: return b''
        im = cover(ImageOps.exif_transpose(im).convert('RGB'))
    except Exception:
        return b''
    if mode == 'boxes':  # 칠한 곳만 (안 칠하면 그대로: 관리자가 미리 보기로 확인)
        rough = mosaic(im, COARSE)
        for box in boxes: im.paste(rough.crop(box), box[:2])
    else:
        im = mosaic(im, FINE)
    out = io.BytesIO(); im.save(out, 'JPEG', quality=82, optimize=True, progressive=True)  # EXIF 없이 새로 저장
    return out.getvalue()


def install(S):
    app, conn = S.app, S.conn
    folder = S.UPLOAD / 'hero'; folder.mkdir(parents=True, exist_ok=True)
    with conn() as db:
        db.execute("CREATE TABLE IF NOT EXISTS hero_photos(id INTEGER PRIMARY KEY,stored TEXT NOT NULL,attachment_id INTEGER,case_id INTEGER,caption TEXT NOT NULL DEFAULT '',sort INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL)")

    def photos():
        with conn() as db:
            return [dict(r) for r in db.execute('SELECT id,stored,caption FROM hero_photos ORDER BY sort,id LIMIT ?', (MAX_PHOTOS,))]

    def wall():
        """첫 화면에 깔 사진 (모자라면 빈 목록 → 예전 그림)."""
        rows = photos()
        return rows if len(rows) >= MIN_PHOTOS else []

    app.jinja_env.globals['hero_wall'] = wall

    @app.route('/hero/<name>')
    def hero_photo(name):
        if not NAME_RE.fullmatch(name): abort(404)
        with conn() as db:
            if not db.execute('SELECT 1 FROM hero_photos WHERE stored=?', (name,)).fetchone(): abort(404)
        r = send_file(folder / name, mimetype='image/jpeg', max_age=86400 * 30)
        return r

    def candidates(used):
        with conn() as db:
            rows = db.execute('SELECT a.id,a.original,a.stored,c.id AS case_id,c.subject,c.industry,c.category,c.created FROM attachments a JOIN cases c ON c.id=a.case_id ORDER BY a.id DESC LIMIT 400').fetchall()
        return [dict(r) for r in rows if r['stored'].lower().endswith(IMAGE_EXT) and r['id'] not in used][:80]

    @app.route('/admin/hero-photos')
    @S.admin_only
    def admin_hero_photos():
        with conn() as db:
            used = {r[0] for r in db.execute('SELECT attachment_id FROM hero_photos WHERE attachment_id IS NOT NULL')}
        return render_template('admin_hero_photos.html', photos=photos(), cands=candidates(used), min_photos=MIN_PHOTOS, max_photos=MAX_PHOTOS)

    @app.route('/admin/hero-photos/src/<int:att_id>')
    @S.admin_only
    def admin_hero_src(att_id):
        """관리자만: 원본을 줄여서 (가릴 곳 고르는 화면용)."""
        from PIL import Image, ImageOps
        with conn() as db: f = db.execute('SELECT stored FROM attachments WHERE id=?', (att_id,)).fetchone()
        if not f or not f['stored'].lower().endswith(IMAGE_EXT): abort(404)
        try:
            im = cover(ImageOps.exif_transpose(Image.open(S.UPLOAD / f['stored'])).convert('RGB'))
        except Exception:
            abort(404)
        out = io.BytesIO(); im.save(out, 'JPEG', quality=80); out.seek(0)
        r = send_file(out, mimetype='image/jpeg'); r.headers['Cache-Control'] = 'private, no-store'; return r

    @app.route('/admin/hero-photos/add', methods=['POST'])
    @S.admin_only
    def admin_hero_add():
        if len(photos()) >= MAX_PHOTOS:
            flash(f'첫 화면 사진은 {MAX_PHOTOS}장까지 넣을 수 있어요. 하나를 빼고 넣어 주세요.'); return redirect(url_for('admin_hero_photos'))
        att_id, case_id, caption = None, None, ' '.join((request.form.get('caption') or '').split())[:40]
        up = request.files.get('photo')
        if up and up.filename:
            data = up.read(S.BOARD_PHOTO_MAX + 1)
            if len(data) > S.BOARD_PHOTO_MAX: data = b''
        else:
            try: att_id = int(request.form.get('attachment_id') or 0)
            except ValueError: att_id = 0
            with conn() as db:
                f = db.execute('SELECT a.stored,c.id AS case_id,c.industry,c.category FROM attachments a JOIN cases c ON c.id=a.case_id WHERE a.id=?', (att_id,)).fetchone()
            if not f or not f['stored'].lower().endswith(IMAGE_EXT): abort(404)
            data = (S.UPLOAD / f['stored']).read_bytes(); case_id = f['case_id']
            if not caption: caption = ' · '.join(x for x in (f['industry'], f['category']) if x)[:40]
        mode = 'boxes' if request.form.get('mode') == 'boxes' else 'all'
        jpg = make_copy(data, mode, clean_boxes(request.form.get('boxes')))
        if not jpg:
            flash('사진을 열지 못했어요. JPG·PNG·WEBP 사진인지 확인해 주세요.'); return redirect(url_for('admin_hero_photos'))
        name = secrets.token_hex(12) + '.jpg'; (folder / name).write_bytes(jpg)
        with conn() as db:
            top = db.execute('SELECT COALESCE(MAX(sort),0)+1 FROM hero_photos').fetchone()[0]
            db.execute('INSERT INTO hero_photos(stored,attachment_id,case_id,caption,sort,created) VALUES(?,?,?,?,?,?)', (name, att_id, case_id, caption, top, S.now()))
        flash('첫 화면 사진에 넣었어요.' + ('' if len(photos()) >= MIN_PHOTOS else f' {MIN_PHOTOS}장부터 첫 화면에 보여요.'))
        return redirect(url_for('admin_hero_photos'))

    @app.route('/admin/hero-photos/<int:pid>', methods=['POST'])
    @S.admin_only
    def admin_hero_edit(pid):
        act = request.form.get('act')
        with conn() as db:
            row = db.execute('SELECT * FROM hero_photos WHERE id=?', (pid,)).fetchone()
            if not row: abort(404)
            if act == 'delete':
                db.execute('DELETE FROM hero_photos WHERE id=?', (pid,))
                if NAME_RE.fullmatch(row['stored']): (folder / row['stored']).unlink(missing_ok=True)
            elif act in ('up', 'down'):
                ids = [r[0] for r in db.execute('SELECT id FROM hero_photos ORDER BY sort,id')]
                i = ids.index(pid); j = i - 1 if act == 'up' else i + 1
                if 0 <= j < len(ids): ids[i], ids[j] = ids[j], ids[i]
                for n, x in enumerate(ids): db.execute('UPDATE hero_photos SET sort=? WHERE id=?', (n, x))
            elif act == 'caption':
                db.execute('UPDATE hero_photos SET caption=? WHERE id=?', (' '.join((request.form.get('caption') or '').split())[:40], pid))
        return redirect(url_for('admin_hero_photos'))
