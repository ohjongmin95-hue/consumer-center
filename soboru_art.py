"""AI 일러스트: 제보·생활정보 카드에 붙일 단순한 그림을 OpenAI로 그림.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다.
- 생활정보 글을 만들거나 게시하면 그림이 없을 때 자동으로 그려서 바로 붙인다(뒤에서 그려서 저장은 기다리지 않음).
- 공개 제보도 게시되는 순간(접수 즉시 공개·관리자 게시) 같은 방식으로 자동으로 그린다.
- 관리자 > AI 일러스트에서 다시 그리기·내리기·지우기. 손으로 '그리기'한 그림은 '게시'를 눌러야 보인다.
- AI에는 분야와 공개용 제목만 보낸다(개인정보·업체명은 지움). 본문·제보자 정보는 보내지 않는다.
- 그림이 없거나 내리면 지금처럼 글자 카드가 나온다. AI 그림 오른쪽 아래에는 아주 작은 'AI' 글자만 옅게 붙인다(운영자 요청, 2026-10-17).
- 키는 사이트가 이미 쓰는 OPENAI_API_KEY, 모델은 OPENAI_IMAGE_MODEL(기본 gpt-image-1-mini), 품질은 OPENAI_IMAGE_QUALITY(기본 medium).
"""
import base64
import datetime
import os
import re
import threading
from flask import abort, flash, g, redirect, render_template, request, send_file, url_for

KINDS = ('report', 'life')
PHOTO = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}
# 매거진 그림 (운영자 2026-10-24: 3D 아이콘 대신 2D 일러스트, 색은 소보루 색에 묶지 말고 기사와 어울리게)
# 뉴닉·잡지 기사 그림처럼 평면 일러스트로 기사 내용을 보여 주는 작은 장면. 그림체를 바꾸면 STYLE_V를 올림(관리자 화면에서 옛 그림 다시 그리기)
STYLE_V = 3
STYLE = ('A flat 2D editorial illustration for a Korean consumer-life magazine article, in the style of modern Korean newsletter and magazine illustrations: '
         'simple geometric shapes, clean confident lines, flat color fills with a subtle paper grain texture, no 3D, no gloss, no gradients, no photorealism. '
         'Show a small, warm everyday scene or a clear arrangement of two or three objects that explains the topic at a glance. '
         'Choose a harmonious palette of 3 to 5 colors that fits the mood of this topic (for example cool blues for travel, fresh greens for food, '
         'calm navy and mint for money and finance, warm reds for safety warnings); {bg}. '
         'Generous empty space, the main subject centered and about half the image height, plain light background in one color that suits the palette. '
         'People may appear as simple stylized figures without detailed faces. Friendly and calm, never scary or gory. '
         'Absolutely no text, no letters, no numbers, no logos, no brand names, no speech bubbles with writing.')
BGS = ('keep it light and airy', 'use one bold accent color', 'use soft muted tones', 'use bright cheerful tones', 'use a calm cool palette', 'use a cozy warm palette')


def image_model(): return os.getenv('OPENAI_IMAGE_MODEL', '').strip() or 'gpt-image-1-mini'
def image_quality(): return os.getenv('OPENAI_IMAGE_QUALITY', '').strip() or 'medium'


def make_prompt(category, title, extra=(), seed=0):
    from companydesk import scrub
    clean = lambda t: re.sub(r'\[[^\]]*삭제\]', '', scrub(t or '', extra)).strip()
    return (STYLE.format(bg=BGS[seed % len(BGS)]) + '\nIllustrate what this Korean consumer article is about, so a reader can guess the topic from the picture '
            '(for example a person checking a long card statement for subscriptions, a delivery box with a broken corner for damaged parcels, '
            'a suitcase and a hotel key with a price tag for travel fees). Do not write the headline words. '
            f'Category "{clean(category)}", headline "{clean(title)}".')


def install(S):
    app = S.app; conn = S.conn; desk = S.companydesk
    folder = S.UPLOAD / 'art'; folder.mkdir(parents=True, exist_ok=True)
    with conn() as db:
        db.execute("CREATE TABLE IF NOT EXISTS soboru_art(kind TEXT NOT NULL,target_id INTEGER NOT NULL,file TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',"
                   "created TEXT NOT NULL,PRIMARY KEY(kind,target_id))")
        # 대표 사진: 관리자가 제보 첨부 사진 중 하나를 골라 공개 (기본은 모두 비공개)
        if 'cover' not in {r['name'] for r in db.execute('PRAGMA table_info(attachments)')}:
            db.execute('ALTER TABLE attachments ADD COLUMN cover INTEGER NOT NULL DEFAULT 0')
        if 'style' not in {r['name'] for r in db.execute('PRAGMA table_info(soboru_art)')}:
            db.execute('ALTER TABLE soboru_art ADD COLUMN style INTEGER NOT NULL DEFAULT 1')

    def now(): return datetime.datetime.now().isoformat(timespec='seconds')

    def live():
        # 요청마다 한 번만 읽음 {(종류, 번호): 파일 이름}
        if g.get('_art_live') is None:
            with conn() as db:
                g._art_live = {(r['kind'], r['target_id']): r['file'] for r in db.execute("SELECT * FROM soboru_art WHERE status='live'")}
        return g._art_live

    def covers():
        # 공개·게시된 제보의 대표 사진 {제보 번호: 첨부 번호}
        if g.get('_art_cover') is None:
            with conn() as db:
                g._art_cover = {r['case_id']: r['id'] for r in db.execute(
                    "SELECT a.id,a.case_id FROM attachments a JOIN cases c ON c.id=a.case_id WHERE a.cover=1 AND c.public_consent=1 AND c.published=1 AND c.review NOT IN ('rejected','duplicate')")}
        return g._art_cover

    def art_url(kind, target_id):
        if kind == 'report' and target_id in covers():
            return url_for('report_cover', case_id=target_id, v=covers()[target_id])
        f = live().get((kind, target_id))
        return url_for('art_image', kind=kind, target_id=target_id, v=f[-12:-5]) if f else ''

    def target(kind, target_id):
        """(분야, 공개용 제목, 지울 말) — 없으면 None."""
        with conn() as db:
            if kind == 'life':
                a = db.execute('SELECT * FROM articles WHERE id=?', (target_id,)).fetchone()
                return (a['category'], a['title'], ()) if a else None
            c = db.execute("SELECT * FROM cases WHERE id=? AND public_consent=1 AND published=1 AND review NOT IN ('rejected','duplicate')", (target_id,)).fetchone()
        if not c: return None
        text = S.jebo.pub(c, S.mask_personal)
        return S.jebo.cat_label(c['category']), text['subject'], [c['company'], c['reporter_name']]

    def draw(kind, target_id, keep=False):
        key = os.getenv('OPENAI_API_KEY', '').strip()
        if not key: raise RuntimeError('OpenAI API 키가 없어요')
        t = target(kind, target_id)
        if not t: raise RuntimeError('그릴 글을 찾지 못했어요')
        body = {'model': image_model(), 'prompt': make_prompt(*t, seed=target_id), 'size': '1536x1024', 'quality': image_quality(), 'output_format': 'webp', 'n': 1}
        st, res = desk.post_json('https://api.openai.com/v1/images/generations', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, 150)
        if st != 200: raise RuntimeError(f'AI 응답 오류 ({st}) ' + str((res.get('error') or {}).get('message', ''))[:160].replace(key, '***'))
        try: data = base64.b64decode(res['data'][0]['b64_json'])
        except (KeyError, IndexError, TypeError, ValueError): raise RuntimeError('AI 그림을 읽지 못했어요')
        name = f'{kind}-{target_id}-{datetime.datetime.now():%Y%m%d%H%M%S}.webp'
        (folder / name).write_bytes(data)
        with conn() as db:
            old = db.execute('SELECT file,status FROM soboru_art WHERE kind=? AND target_id=?', (kind, target_id)).fetchone()
            # keep: 게시 중인 그림을 새 그림체로 바꿀 때는 게시 상태 그대로
            status = old['status'] if keep and old else 'draft'
            db.execute('INSERT OR REPLACE INTO soboru_art(kind,target_id,file,status,created,style) VALUES(?,?,?,?,?,?)', (kind, target_id, name, status, now(), STYLE_V))
        if old and old['file'] != name: (folder / old['file']).unlink(missing_ok=True)

    def auto(kind, target_id, wait=False):
        # 그림이 없을 때만, 키가 있을 때만. 실패하면 조용히 넘어가고 글자 카드가 그대로 나옴
        if not desk.ai_ready(): return
        with conn() as db:
            if db.execute('SELECT 1 FROM soboru_art WHERE kind=? AND target_id=?', (kind, target_id)).fetchone(): return
        def run():
            try:
                draw(kind, target_id)
                with conn() as db: db.execute("UPDATE soboru_art SET status='live' WHERE kind=? AND target_id=?", (kind, target_id))
            except Exception as e: app.logger.warning('AI 일러스트 자동 그리기 실패: %s', str(e)[:200])
        if wait or app.config.get('TESTING'): run()
        else: threading.Thread(target=run, daemon=True).start()

    @app.route('/art/<kind>/<int:target_id>.webp')
    def art_image(kind, target_id):
        with conn() as db:
            r = db.execute('SELECT * FROM soboru_art WHERE kind=? AND target_id=?', (kind, target_id)).fetchone()
        # 게시 전 그림은 관리자만 볼 수 있음
        if not r or (r['status'] != 'live' and not S.admin_active()) or not (folder / r['file']).is_file(): abort(404)
        resp = send_file(folder / r['file'], mimetype='image/webp', max_age=86400 if r['status'] == 'live' else 0)
        return resp

    @app.route('/reports/<int:case_id>/cover')
    def report_cover(case_id):
        fid = covers().get(case_id)
        if not fid: abort(404)
        with conn() as db: f = db.execute('SELECT * FROM attachments WHERE id=?', (fid,)).fetchone()
        ext = os.path.splitext(f['stored'])[1].lower()
        if ext not in PHOTO or not (S.UPLOAD / f['stored']).is_file(): abort(404)
        return send_file(S.UPLOAD / f['stored'], mimetype=PHOTO[ext], max_age=86400)

    @app.route('/admin/reports/<int:case_id>/cover', methods=['POST'])
    @S.admin_only
    def admin_report_cover(case_id):
        fid = request.form.get('file_id', type=int) or 0
        with conn() as db:
            if fid:
                f = db.execute('SELECT * FROM attachments WHERE id=? AND case_id=?', (fid, case_id)).fetchone()
                if not f or os.path.splitext(f['stored'])[1].lower() not in PHOTO: abort(400)
            db.execute('UPDATE attachments SET cover=CASE WHEN id=? THEN 1 ELSE 0 END WHERE case_id=?', (fid, case_id))
            S.log_case(db, case_id, '대표 사진 공개' if fid else '대표 사진 내림')
        flash('이 사진을 대표 사진으로 공개했어요. 제보 카드와 상세 화면에 보여요.' if fid else '대표 사진을 내렸어요.')
        return redirect(url_for('admin_report', case_id=case_id) + '#files')

    @app.route('/admin/art')
    @S.admin_only
    def admin_art():
        kind = request.args.get('kind') if request.args.get('kind') in KINDS else 'report'
        with conn() as db:
            arts = {r['target_id']: r for r in db.execute('SELECT * FROM soboru_art WHERE kind=?', (kind,))}
            if kind == 'life':
                rows = [{'id': a['id'], 'title': a['title'], 'label': a['category'], 'note': '게시 중' if a['status'] == 'published' else '초안'}
                        for a in db.execute('SELECT * FROM articles ORDER BY id DESC LIMIT 60')]
            else:
                rows = [{'id': c['id'], 'title': S.jebo.pub(c, S.mask_personal)['subject'], 'label': S.jebo.cat_label(c['category']), 'note': c['status']}
                        for c in db.execute("SELECT * FROM cases WHERE public_consent=1 AND published=1 AND review NOT IN ('rejected','duplicate') ORDER BY id DESC LIMIT 60")]
            old = db.execute('SELECT COUNT(*) FROM soboru_art WHERE kind=? AND style<?', (kind, STYLE_V)).fetchone()[0]
        for r in rows:
            a = arts.get(r['id'])
            r['art'] = a['status'] if a else ''
            r['src'] = url_for('art_image', kind=kind, target_id=r['id'], v=a['file'][-12:-5]) if a else ''
        return render_template('admin_art.html', rows=rows, kind=kind, ready=desk.ai_ready(), model=image_model(), old=old)

    @app.route('/admin/art/fill', methods=['POST'])
    @S.admin_only
    def admin_art_fill():
        # 그림 없는 최근 글을 한 번에 최대 20개 (뒤에서 하나씩 그림)
        kind = request.form.get('kind') if request.form.get('kind') in KINDS else 'report'
        if not desk.ai_ready(): flash('OpenAI API 키가 없어서 그릴 수 없어요.'); return redirect(url_for('admin_art', kind=kind))
        with conn() as db:
            redo = request.form.get('mode') == 'old'
            have = {r[0] for r in db.execute('SELECT target_id FROM soboru_art WHERE kind=?', (kind,))}
            old = [r[0] for r in db.execute('SELECT target_id FROM soboru_art WHERE kind=? AND style<? ORDER BY target_id DESC', (kind, STYLE_V))]
            sql = ('SELECT id FROM articles ORDER BY id DESC LIMIT 200' if kind == 'life' else
                   "SELECT id FROM cases WHERE public_consent=1 AND published=1 AND review NOT IN ('rejected','duplicate') ORDER BY id DESC LIMIT 200")
            ids = old[:20] if redo else [r[0] for r in db.execute(sql) if r[0] not in have][:20]
        def run():
            for i in ids:
                if not redo: auto(kind, i, wait=True); continue
                try: draw(kind, i, keep=True)
                except Exception as e: app.logger.warning('AI 일러스트 다시 그리기 실패: %s', str(e)[:200])
        if app.config.get('TESTING'): run()
        else: threading.Thread(target=run, daemon=True).start()
        what = '옛 그림체 그림' if redo else '그림 없는 글'
        flash(f'{what} {len(ids)}개를 그리기 시작했어요. 하나에 30초쯤 걸려요. 잠시 뒤 새로 고침해 보세요.' if ids else f'{what}이 없어요.')
        return redirect(url_for('admin_art', kind=kind))

    @app.route('/admin/art/<kind>/<int:target_id>', methods=['POST'])
    @S.admin_only
    def admin_art_action(kind, target_id):
        if kind not in KINDS: abort(404)
        act = request.form.get('act')
        back = redirect(url_for('admin_art', kind=kind) + '#art-%d' % target_id)
        if act == 'draw':
            try: draw(kind, target_id); flash('그림을 그렸어요. 보고 괜찮으면 게시를 눌러 주세요.')
            except RuntimeError as e: flash(str(e))
            return back
        with conn() as db:
            r = db.execute('SELECT * FROM soboru_art WHERE kind=? AND target_id=?', (kind, target_id)).fetchone()
            if not r: abort(404)
            if act == 'publish': db.execute("UPDATE soboru_art SET status='live' WHERE kind=? AND target_id=?", (kind, target_id)); flash('그림을 게시했어요.')
            elif act == 'hide': db.execute("UPDATE soboru_art SET status='draft' WHERE kind=? AND target_id=?", (kind, target_id)); flash('그림을 내렸어요. 글자 카드가 다시 보여요.')
            elif act == 'delete':
                db.execute('DELETE FROM soboru_art WHERE kind=? AND target_id=?', (kind, target_id)); (folder / r['file']).unlink(missing_ok=True); flash('그림을 지웠어요.')
            else: abort(400)
        return back

    def og_photo(case_id):
        # 공유 미리보기용 제보 대표 사진: 네이버·카카오가 확실히 읽는 JPG·PNG만 (AI 그림은 webp라 제외)
        fid = covers().get(case_id)
        if not fid: return ''
        with conn() as db: f = db.execute('SELECT stored FROM attachments WHERE id=?', (fid,)).fetchone()
        if not f or os.path.splitext(f['stored'])[1].lower() not in ('.jpg', '.jpeg', '.png'): return ''
        return S.canonical_url(url_for('report_cover', case_id=case_id, v=fid))

    app.jinja_env.globals.update(og_photo=og_photo, art_url=art_url, art_photo=lambda stored: os.path.splitext(stored)[1].lower() in PHOTO)
    S.art_draw = draw; S.art_auto = auto
    app.extensions['soboru_art'] = {'auto': auto, 'draw': draw}
