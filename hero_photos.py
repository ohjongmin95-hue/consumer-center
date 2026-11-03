"""첫 화면 배경 사진 (운영자 2026-11-03: 소비자제보센터 첫 화면 뒤에 실제 제보 사진을).

- 관리자 > 제보 > 첫 화면 사진에서 제보에 붙은 사진(또는 직접 올린 사진)을 골라 넣는다.
- 원본은 그대로 비공개로 두고, 3:4로 자르고 줄인 '가린 사본'만 새로 만들어 공개한다 (/hero/<이름>.jpg).
  가리는 방법: 사진 전체를 잘게 모자이크(기본) 하거나, 관리자가 네모로 칠한 곳만 굵게 모자이크.
  이름·전화번호·주소·주문번호·얼굴처럼 알아볼 수 있는 것은 관리자가 미리 보기로 확인하고 넣는다.
- 사진이 3장 이상이면 제보센터 첫 화면의 큰 제목 칸(hero) 뒤에 사진 벽이 깔린다. 적으면 예전 그림 그대로.
- 운영자 2026-11-03: 관리자가 고르지 않아도 공개 게시된 제보의 사진을 자동으로 넣는다 (사진 전체 모자이크).
  제보가 비공개로 바뀌거나 내려가면 첫 화면에서도 빠진다. 관리자가 '빼기'를 누른 자동 사진은 다시 들어오지 않는다.
"""
import io
import json
import re
import secrets
import time

from flask import abort, flash, redirect, render_template, request, send_file, url_for

W, H = 600, 800  # 공개 사본 크기 (3:4)
FINE = 120       # 전체 모자이크: 가로 칸 수. 운영자 2026-11-03: 물건이 뭔지는 보이게 약하게 (작은 글씨만 안 읽힘)
AUTO_VER = 3     # 3: 겹치는 사진 빼고 업체·업종을 골고루 (운영자 2026-11-03)
# 자동 사본 만드는 방식이 바뀌면 올림 → 예전 자동 사본을 지우고 새로 만듦
COARSE = 14      # 네모 칠한 곳: 가로 칸 수 (사진 전체 기준, 굵게)
MAX_PHOTOS = 18
MIN_PHOTOS = 3
IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.webp')
NAME_RE = re.compile(r'[0-9a-f]{24}\.jpg')
AUTO_MAX = 12      # 자동으로 넣는 사진 수
AUTO_EVERY = 600   # 자동 사진을 찾는 간격(초)
AUTO_PER_RUN = 4   # 한 번에 새로 만드는 사본 수 (첫 화면이 느려지지 않게)
PUBLIC = "c.public_consent=1 AND c.published=1 AND c.review NOT IN ('rejected','duplicate')"


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


def norm_co(name):
    return re.sub(r'[\s()㈜주식회사]', '', name or '').lower()


def phash_bytes(data):
    """사진 모양 지문 (16x16 밝기 평균보다 밝은 칸). 같은 사진·조금 자른 사진을 알아봄."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data)).convert('L').resize((16, 16), Image.BOX)
    except Exception:
        return ''
    px = list(im.getdata()); avg = sum(px) / len(px)
    return '%064x' % int(''.join('1' if p > avg else '0' for p in px), 2)


def phash_file(path):
    try: return phash_bytes(path.read_bytes())
    except OSError: return ''


def near(a, b, limit=32):
    """256칸 중 다른 칸이 limit개 이하면 같은 사진으로 봄."""
    return bin(int(a, 16) ^ int(b, 16)).count('1') <= limit


def install(S):
    app, conn = S.app, S.conn
    folder = S.UPLOAD / 'hero'; folder.mkdir(parents=True, exist_ok=True)
    with conn() as db:
        db.execute("CREATE TABLE IF NOT EXISTS hero_photos(id INTEGER PRIMARY KEY,stored TEXT NOT NULL,attachment_id INTEGER,case_id INTEGER,caption TEXT NOT NULL DEFAULT '',sort INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL)")
        cols = {r['name'] for r in db.execute('PRAGMA table_info(hero_photos)')}
        for c in ('auto', 'hidden', 'ver'):
            if c not in cols: db.execute(f'ALTER TABLE hero_photos ADD COLUMN {c} INTEGER NOT NULL DEFAULT 0')
        if 'phash' not in cols: db.execute("ALTER TABLE hero_photos ADD COLUMN phash TEXT NOT NULL DEFAULT ''")
        for r in db.execute('SELECT stored FROM hero_photos WHERE auto=1 AND hidden=0 AND ver<?', (AUTO_VER,)).fetchall():  # 예전 방식 자동 사본은 새로 만듦
            if NAME_RE.fullmatch(r['stored']): (folder / r['stored']).unlink(missing_ok=True)
        db.execute('DELETE FROM hero_photos WHERE auto=1 AND hidden=0 AND ver<?', (AUTO_VER,))
    last = {'at': 0.0}

    def photos():
        """보이는 사진: 관리자가 고른 것 먼저, 그다음 자동 사진(최근 것부터). 자동 사진은 제보가 지금도 공개일 때만."""
        with conn() as db:
            return [dict(r) for r in db.execute('SELECT h.id,h.stored,h.caption,h.auto FROM hero_photos h LEFT JOIN cases c ON c.id=h.case_id WHERE h.hidden=0 AND (h.auto=0 OR (' + PUBLIC + ')) ORDER BY h.auto,h.sort,h.id DESC LIMIT ?', (MAX_PHOTOS,))]

    def auto_fill(force=False):
        """공개 게시된 제보의 사진 중 아직 안 쓴 것을 약한 모자이크 사본으로 만들어 넣음.
        운영자 2026-11-03: 겹치지 않게, 다채롭게. 제보 하나에 한 장, 같은(비슷한) 사진은 한 번만,
        업체·업종이 이미 있는 것보다 새 업체·새 업종 사진을 먼저. 실제 제보 사진만 (AI 그림 없음)."""
        if not force and time.time() - last['at'] < AUTO_EVERY: return
        last['at'] = time.time()
        with conn() as db:
            cur = db.execute('SELECT h.id,h.stored,h.phash,c.company,c.industry FROM hero_photos h JOIN cases c ON c.id=h.case_id WHERE h.hidden=0 AND (h.auto=0 OR ' + PUBLIC + ')').fetchall()
            have = sum(1 for _ in db.execute('SELECT 1 FROM hero_photos h JOIN cases c ON c.id=h.case_id WHERE h.auto=1 AND h.hidden=0 AND ' + PUBLIC))
            if have >= AUTO_MAX: return
            rows = db.execute('SELECT a.id,a.stored,c.id AS case_id,c.company,c.industry,c.category FROM attachments a JOIN cases c ON c.id=a.case_id WHERE ' + PUBLIC +
                              ' AND a.id NOT IN (SELECT attachment_id FROM hero_photos WHERE attachment_id IS NOT NULL) AND c.id NOT IN (SELECT case_id FROM hero_photos WHERE auto=1 AND case_id IS NOT NULL) ORDER BY a.id DESC LIMIT 200').fetchall()
        hashes = []
        for h in cur:  # 지금 보이는 사진의 모양 (겹침 확인용)
            ph = h['phash'] or (phash_file(folder / h['stored']) if h['stored'] else '')
            if ph: hashes.append(ph)
        cos = {norm_co(h['company']) for h in cur}
        inds = {}
        for h in cur: inds[h['industry']] = inds.get(h['industry'], 0) + 1
        # 새 업체 먼저, 그다음 덜 나온 업종, 그다음 최근 것
        rows = [r for r in rows if r['stored'].lower().endswith(IMAGE_EXT)]
        made, seen = 0, set()
        limit = min(AUTO_MAX if force else AUTO_PER_RUN, AUTO_MAX - have)
        while rows and made < limit:
            rows.sort(key=lambda r: (norm_co(r['company']) in cos, inds.get(r['industry'], 0), -r['id']))
            r = rows.pop(0)
            if r['case_id'] in seen: continue  # 한 제보에서는 한 장만
            try: data = (S.UPLOAD / r['stored']).read_bytes()
            except OSError: continue
            jpg = make_copy(data, 'all', [])
            ph = phash_bytes(jpg) if jpg else ''
            dup = bool(ph) and any(near(ph, x) for x in hashes)
            with conn() as db:
                if not jpg or dup:  # 못 여는 사진·이미 있는 사진과 같은 사진은 다시 보지 않게 숨김 표시만
                    db.execute("INSERT INTO hero_photos(stored,attachment_id,case_id,auto,hidden,ver,phash,created) VALUES('',?,?,1,1,?,?,?)", (r['id'], r['case_id'], AUTO_VER, ph, S.now())); continue
                name = secrets.token_hex(12) + '.jpg'; (folder / name).write_bytes(jpg)
                cap = ' · '.join(x for x in (r['industry'], r['category']) if x)[:40]
                db.execute('INSERT INTO hero_photos(stored,attachment_id,case_id,caption,auto,ver,phash,created) VALUES(?,?,?,?,1,?,?,?)', (name, r['id'], r['case_id'], cap, AUTO_VER, ph, S.now()))
            made += 1; seen.add(r['case_id']); hashes.append(ph); cos.add(norm_co(r['company'])); inds[r['industry']] = inds.get(r['industry'], 0) + 1

    def wall():
        """첫 화면에 깔 사진 (모자라면 빈 목록 → 예전 그림)."""
        try: auto_fill()
        except Exception as e: app.logger.warning('hero auto fill failed: %s', str(e)[:120])
        rows = photos()
        return rows if len(rows) >= MIN_PHOTOS else []

    app.jinja_env.globals['hero_wall'] = wall

    @app.route('/hero/<name>')
    def hero_photo(name):
        if not NAME_RE.fullmatch(name): abort(404)
        if name not in {p['stored'] for p in photos()}: abort(404)  # 지금 보이는 사진만 (제보가 비공개로 바뀌면 바로 막힘)
        r = send_file(folder / name, mimetype='image/jpeg', max_age=86400 * 30)
        return r

    def candidates(used):
        with conn() as db:
            rows = db.execute('SELECT a.id,a.original,a.stored,c.id AS case_id,c.subject,c.industry,c.category,c.created FROM attachments a JOIN cases c ON c.id=a.case_id ORDER BY a.id DESC LIMIT 400').fetchall()
        return [dict(r) for r in rows if r['stored'].lower().endswith(IMAGE_EXT) and r['id'] not in used][:80]

    @app.route('/admin/hero-photos')
    @S.admin_only
    def admin_hero_photos():
        try: auto_fill(force=True)
        except Exception as e: app.logger.warning('hero auto fill failed: %s', str(e)[:120])
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
        if sum(1 for p in photos() if not p['auto']) >= MAX_PHOTOS:
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
            if act == 'delete':  # 자동 사진은 숨김 표시로 남겨 다시 들어오지 않게
                if row['auto']: db.execute("UPDATE hero_photos SET hidden=1,stored='' WHERE id=?", (pid,))
                else: db.execute('DELETE FROM hero_photos WHERE id=?', (pid,))
                if NAME_RE.fullmatch(row['stored']): (folder / row['stored']).unlink(missing_ok=True)
            elif act in ('up', 'down'):
                ids = [r[0] for r in db.execute('SELECT id FROM hero_photos WHERE auto=0 AND hidden=0 ORDER BY sort,id')]
                if pid not in ids: return redirect(url_for('admin_hero_photos'))
                i = ids.index(pid); j = i - 1 if act == 'up' else i + 1
                if 0 <= j < len(ids): ids[i], ids[j] = ids[j], ids[i]
                for n, x in enumerate(ids): db.execute('UPDATE hero_photos SET sort=? WHERE id=?', (n, x))
            elif act == 'caption':
                db.execute('UPDATE hero_photos SET caption=? WHERE id=?', (' '.join((request.form.get('caption') or '').split())[:40], pid))
        return redirect(url_for('admin_hero_photos'))
