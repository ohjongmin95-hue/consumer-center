"""첫 화면 아래 '사진으로 보는 제보' (운영자 2026-11-04).

공개 게시된 제보에 붙은 사진을 첫 화면 맨 아래에 가로 카드로 보여 준다.
사진 전체를 모자이크하지 않고, 사람 이름·전화번호·주소·주문번호·계좌번호·얼굴·차 번호판처럼 사람을 알아볼 수 있는 곳만
AI(사진 보기)가 찾아 그 자리만 굵게 모자이크한 사본을 새로 만들어 공개한다 (/shot/<이름>.jpg). 원본은 그대로 비공개.
- AI 키가 없거나 AI가 답하지 않으면 그 사진은 쓰지 않는다 (가리지 않은 사진이 나가지 않게).
- 사람 얼굴은 따로 묻는다 (운영자 2026-11-05: 얼굴은 무조건 모자이크). 얼굴은 넉넉하게 더 굵게 가리고,
  AI가 얼굴이 있다면서 자리를 못 대면 그 사진은 쓰지 않는다.
- 신분증·증명서처럼 개인정보가 대부분인 사진은 AI가 private=true로 답하고, 그런 사진은 빼 둔다.
- 제보가 비공개로 바뀌거나 내려가면 바로 안 보인다. 관리자 > 첫 화면 사진에서 '빼기'를 누르면 다시 들어오지 않는다.
"""
import base64
import io
import json
import random
import re
import secrets
import threading
import time

from flask import abort, redirect, request, send_file, url_for

import companydesk
from hero_photos import PUBLIC, IMAGE_EXT, near, norm_co, phash_bytes, phash_file

VER = 2           # 2: 얼굴 따로 찾기 (운영자 2026-11-05) — 예전 사본은 다시 만듦
SHOW = 12          # 첫 화면에 보이는 카드 수
EVERY = 600        # 새 사진을 찾는 간격(초)
PER_RUN = 4        # 한 번에 AI로 보는 사진 수 (비용)
SW, SH = 640, 480  # 공개 사본 크기 (4:3)
CELLS = 28         # 가린 곳 모자이크 굵기 (사진 가로 칸 수)
PAD = 0.015        # 가린 네모를 조금 넓게
FACE_PAD = 0.25    # 얼굴은 얼굴 크기의 1/4씩 더 넓게 (머리·턱까지)
FACE_CELLS = 16    # 얼굴은 더 굵게
MAX_BOXES = 24
NAME_RE = re.compile(r'[0-9a-f]{24}\.jpg')
PROMPT = ('소비자 피해 제보에 붙은 사진입니다. 이 사진을 누구나 보는 사이트에 올리기 전에, 특정 개인을 알아볼 수 있는 부분만 가리려고 합니다. '
          '가려야 할 것: 사람 이름(받는 사람·보낸 사람·카톡 대화 이름·닉네임 포함), 전화번호, 이메일, 집·배송 주소, 주문번호·송장번호, '
          '계좌·카드번호, 주민등록번호·생년월일, 사람 얼굴, 프로필 사진, 차 번호판, 서명. '
          '업체 이름·상품 이름·가격·날짜·사진 속 물건은 가리지 않습니다. '
          'x·y는 왼쪽 위, w·h는 너비·높이, 모두 사진 전체를 1로 본 비율. 글자 줄 전체를 넉넉하게 감싸 주세요. '
          '사람 얼굴은 boxes가 아니라 faces에 따로 넣습니다. 정면·옆얼굴·얼굴 일부·셀카·피부 트러블처럼 피해 부위를 보여 주는 얼굴 클로즈업, '
          '화면 속·사진 속·포스터 속 얼굴까지 사람 얼굴이면 모두 넣고, 이마부터 턱까지 얼굴 전체를 감싸 주세요. face_count는 사진에 보이는 얼굴 수입니다. '
          '신분증·증명서·계약서 전체처럼 개인정보가 대부분이라 가려도 보여 줄 게 없는 사진이면 private=true. '
          'JSON만: {"boxes": [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.05, "what": "전화번호"}], "faces": [{"x": 0.2, "y": 0.1, "w": 0.5, "h": 0.6}], "face_count": 1, "private": false}.')


def prepared(data):
    """원본 바이트 → (가로 1280 이하로 줄인 RGB 그림, AI에 보낼 JPEG 바이트). 못 열면 (None, b'')."""
    from PIL import Image, ImageOps
    try:
        im = Image.open(io.BytesIO(data))
        if im.width * im.height > 40_000_000: return None, b''
        im = ImageOps.exif_transpose(im).convert('RGB')
    except Exception:
        return None, b''
    im.thumbnail((1280, 1280), Image.LANCZOS)
    out = io.BytesIO(); im.save(out, 'JPEG', quality=85)
    return im, out.getvalue()


def _ratios(items, limit):
    out = []
    for b in (items or [])[:limit + 1] if isinstance(items, list) else []:
        try: x, y, w, h = (min(1.0, max(0.0, float(b[k]))) for k in ('x', 'y', 'w', 'h'))
        except (TypeError, ValueError, KeyError): continue
        if w > 0 and h > 0: out.append((x, y, w, h))
    return out


def find_boxes(jpg):
    """AI가 찾은 가릴 곳 {'boxes': [(x,y,w,h) 비율], 'faces': [...]}. 못 보면 None,
    개인정보가 대부분이면 'private', 얼굴이 있는데 자리를 못 대면 'face'."""
    key = companydesk.ai_key_for('case_shots')
    if not key or not jpg: return None
    body = {'model': companydesk.ai_model(), 'temperature': 0, 'response_format': {'type': 'json_object'},
            'messages': [{'role': 'system', 'content': PROMPT},
                         {'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + base64.b64encode(jpg).decode(), 'detail': 'high'}}]}]}
    st, res = companydesk.post_json('https://api.openai.com/v1/chat/completions', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, 60)
    if st != 200: return None
    try: out = json.loads(res['choices'][0]['message']['content'])
    except Exception: return None
    if not isinstance(out, dict): return None
    if out.get('private'): return 'private'
    boxes, faces = _ratios(out.get('boxes'), MAX_BOXES), _ratios(out.get('faces'), MAX_BOXES)
    if len(boxes) + len(faces) > MAX_BOXES: return 'private'
    try: count = int(out.get('face_count') or 0)
    except (TypeError, ValueError): count = 0
    if count > len(faces): return 'face'  # 얼굴이 있다는데 자리를 다 못 댐 → 안 씀
    return {'boxes': boxes, 'faces': faces}


def make_shot(im, found):
    """가릴 곳만 굵게 모자이크 (얼굴은 더 넓고 더 굵게) → 4:3로 잘라 JPEG 바이트."""
    from PIL import Image, ImageOps
    from hero_photos import mosaic
    W, H = im.size
    boxes, faces = found.get('boxes') or [], found.get('faces') or []
    for items, cells, pad in ((boxes, CELLS, None), (faces, FACE_CELLS, FACE_PAD)):
        if not items: continue
        rough = mosaic(im, cells)
        for x, y, w, h in items:
            px, py = (w * pad, h * pad) if pad else (PAD, PAD)
            box = (max(0, round((x - px) * W)), max(0, round((y - py) * H)), min(W, round((x + w + px) * W)), min(H, round((y + h + py) * H)))
            if box[2] > box[0] and box[3] > box[1]: im.paste(rough.crop(box), box[:2])
    im = ImageOps.fit(im, (SW, SH), Image.LANCZOS)
    out = io.BytesIO(); im.save(out, 'JPEG', quality=82, optimize=True, progressive=True)  # EXIF 없이 새로 저장
    return out.getvalue()


def install(S):
    app, conn = S.app, S.conn
    folder = S.UPLOAD / 'shots'; folder.mkdir(parents=True, exist_ok=True)
    with conn() as db:
        db.execute("CREATE TABLE IF NOT EXISTS case_shots(id INTEGER PRIMARY KEY,attachment_id INTEGER UNIQUE,case_id INTEGER,stored TEXT NOT NULL DEFAULT '',"
                   "boxes INTEGER NOT NULL DEFAULT 0,hidden INTEGER NOT NULL DEFAULT 0,note TEXT NOT NULL DEFAULT '',ver INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL)")
        if 'phash' not in {r['name'] for r in db.execute('PRAGMA table_info(case_shots)')}: db.execute("ALTER TABLE case_shots ADD COLUMN phash TEXT NOT NULL DEFAULT ''")
        for r in db.execute("SELECT stored FROM case_shots WHERE ver<? AND stored!=''", (VER,)).fetchall():  # 얼굴 따로 찾기 전 사본은 지우고 다시 만듦
            if NAME_RE.fullmatch(r['stored']): (folder / r['stored']).unlink(missing_ok=True)
        db.execute("DELETE FROM case_shots WHERE ver<? AND note!='admin'", (VER,))
    state = {'at': 0.0, 'busy': False}
    lock = threading.Lock()

    def fill(limit=PER_RUN):
        """아직 안 본 공개 제보 사진을 AI로 보고 가린 사본을 만듦. 만든 수를 돌려줌."""
        with conn() as db:
            rows = db.execute('SELECT a.id,a.stored,c.id AS case_id FROM attachments a JOIN cases c ON c.id=a.case_id WHERE ' + PUBLIC +
                              ' AND a.id NOT IN (SELECT attachment_id FROM case_shots) AND c.id NOT IN (SELECT case_id FROM case_shots WHERE stored!=\'\')'
                              ' ORDER BY a.id DESC LIMIT 60').fetchall()
            have = [r['phash'] or phash_file(folder / r['stored']) for r in db.execute("SELECT phash,stored FROM case_shots WHERE hidden=0 AND stored!=''")]
        have = [h for h in have if h]
        made, tried, seen = 0, 0, set()
        for r in rows:
            if tried >= limit: break
            if r['case_id'] in seen or not r['stored'].lower().endswith(IMAGE_EXT): continue  # 제보 하나에 한 장
            try: data = (S.UPLOAD / r['stored']).read_bytes()
            except OSError: continue
            im, jpg = prepared(data)
            tried += 1
            boxes = find_boxes(jpg) if im else 'broken'
            if boxes is None: break  # AI를 못 쓰면 다음에 다시 (가리지 않은 사진은 안 냄)
            with conn() as db:
                if isinstance(boxes, str):
                    db.execute('INSERT OR IGNORE INTO case_shots(attachment_id,case_id,hidden,note,ver,created) VALUES(?,?,1,?,?,?)', (r['id'], r['case_id'], boxes, VER, S.now())); continue
                shot = make_shot(im, boxes); n_boxes = len(boxes['boxes']) + len(boxes['faces']); ph = phash_bytes(shot)
                if ph and any(near(ph, h) for h in have):  # 운영자 2026-11-04: 같은 사진은 한 번만 (같은 영수증을 두 제보에 올린 경우 등)
                    db.execute("INSERT OR IGNORE INTO case_shots(attachment_id,case_id,hidden,note,ver,phash,created) VALUES(?,?,1,'dup',?,?,?)", (r['id'], r['case_id'], VER, ph, S.now())); continue
                name = secrets.token_hex(12) + '.jpg'; (folder / name).write_bytes(shot)
                db.execute('INSERT OR IGNORE INTO case_shots(attachment_id,case_id,stored,boxes,ver,phash,created) VALUES(?,?,?,?,?,?,?)', (r['id'], r['case_id'], name, n_boxes, VER, ph, S.now()))
            made += 1; seen.add(r['case_id']); have.append(ph)
        return made

    def kick():
        """첫 화면을 느리게 하지 않게 뒤에서 한 번씩."""
        if state['busy'] or time.time() - state['at'] < EVERY or app.config.get('TESTING'): return
        state['at'] = time.time()
        def go():
            with lock:
                state['busy'] = True
                try: fill()
                except Exception as e: app.logger.warning('case shots fill failed: %s', str(e)[:120])
                finally: state['busy'] = False
        threading.Thread(target=go, daemon=True).start()

    def shots(n=SHOW, shuffle=False):
        """첫 화면 카드: 지금도 공개인 제보만, 제보 하나에 한 장, 최근 것부터 (shuffle이면 최근 것 중에서 섞어서)."""
        kick()
        with conn() as db:
            rows = [dict(r) for r in db.execute('SELECT MIN(s.id) AS id,s.stored,s.phash,s.case_id,c.subject,c.company,c.industry,c.created FROM case_shots s JOIN cases c ON c.id=s.case_id '
                                                "WHERE s.hidden=0 AND s.stored!='' AND " + PUBLIC + ' GROUP BY s.case_id ORDER BY c.id DESC LIMIT ?', (n * 2 if shuffle else n,))]
        out, keys, hashes = [], set(), []
        for r in rows:  # 운영자 2026-11-04: 같은 것 두 번 노출 금지 — 같은 업체·같은 제목, 같은(비슷한) 사진은 하나만
            key = (norm_co(r['company']), ' '.join((r['subject'] or '').split()))
            ph = r['phash'] or phash_file(folder / r['stored'])
            if key in keys or (ph and any(near(ph, h) for h in hashes)): continue
            keys.add(key); hashes.append(ph) if ph else None; out.append(r)
        rows = out
        if shuffle:  # 운영자 2026-11-04: 매번 같은 사진만 보이면 지루함 → 최근 것 중에서 섞어서
            random.shuffle(rows); rows = rows[:n]
        return rows

    app.jinja_env.globals['case_shots'] = shots
    S.case_shots_fill = fill

    @app.route('/shot/<name>')
    def case_shot(name):
        if not NAME_RE.fullmatch(name): abort(404)
        with conn() as db:
            ok = db.execute('SELECT 1 FROM case_shots s JOIN cases c ON c.id=s.case_id WHERE s.stored=? AND s.hidden=0 AND ' + PUBLIC, (name,)).fetchone()
        if not ok: abort(404)
        return send_file(folder / name, mimetype='image/jpeg', max_age=86400)

    @app.route('/admin/case-shots/<int:sid>', methods=['POST'])
    @S.admin_only
    def admin_case_shot_hide(sid):
        """관리자 '빼기': 사본을 지우고 숨김 표시만 남겨 다시 들어오지 않게."""
        with conn() as db:
            r = db.execute('SELECT stored FROM case_shots WHERE id=?', (sid,)).fetchone()
            if not r: abort(404)
            if NAME_RE.fullmatch(r['stored']): (folder / r['stored']).unlink(missing_ok=True)
            db.execute("UPDATE case_shots SET hidden=1,stored='',note='admin' WHERE id=?", (sid,))
        return redirect(url_for('admin_hero_photos') + '#shots')
