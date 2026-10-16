"""AI 일러스트: 제보·생활정보 카드에 붙일 단순한 그림을 OpenAI로 그림.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다.
- 생활정보 글을 만들거나 게시하면 그림이 없을 때 자동으로 그려서 바로 붙인다(뒤에서 그려서 저장은 기다리지 않음).
- 관리자 > AI 일러스트에서 다시 그리기·내리기·지우기, 제보는 '그리기' 후 '게시'를 눌러야 보인다.
- AI에는 분야와 공개용 제목만 보낸다(개인정보·업체명은 지움). 본문·제보자 정보는 보내지 않는다.
- 그림이 없거나 내리면 지금처럼 글자 카드가 나온다. 그림에는 'AI 일러스트'라고 작게 표시한다.
- 키는 사이트가 이미 쓰는 OPENAI_API_KEY, 모델은 OPENAI_IMAGE_MODEL(기본 gpt-image-1-mini).
"""
import base64
import datetime
import os
import re
import threading
from flask import abort, flash, g, redirect, render_template, request, send_file, url_for

KINDS = ('report', 'life')
# 토스 피드 그림 느낌: 단색 배경 + 부드러운 입체 물건 한두 개(때로는 손), 글자 없음
STYLE = ('Soft 3D illustration in the style of a Korean fintech app feed thumbnail: smooth matte clay-like objects with gentle gradients and soft shadows, '
         'one or two everyday objects (sometimes simple stylized hands, no faces) floating in the center, slightly tilted, generous empty space, '
         'flat solid {bg} background filling the whole image, a limited palette that harmonizes with the background. '
         'Absolutely no text, no letters, no numbers, no logos, no brand names, no real people.')
BGS = ('soft sky blue (#9dbcef)', 'deep teal (#2b9db5)', 'bright blue (#3a8ef6)', 'warm apricot (#ffb56b)', 'fresh mint (#7fd1ae)', 'soft lavender (#b7a6f0)')


def image_model(): return os.getenv('OPENAI_IMAGE_MODEL', '').strip() or 'gpt-image-1-mini'


def make_prompt(category, title, extra=(), seed=0):
    from companydesk import scrub
    clean = lambda t: re.sub(r'\[[^\]]*삭제\]', '', scrub(t or '', extra)).strip()
    return STYLE.format(bg=BGS[seed % len(BGS)]) + f'\nTopic (Korean consumer issue, draw the situation, do not write it): category "{clean(category)}", headline "{clean(title)}".'


def install(S):
    app = S.app; conn = S.conn; desk = S.companydesk
    folder = S.UPLOAD / 'art'; folder.mkdir(parents=True, exist_ok=True)
    with conn() as db:
        db.execute("CREATE TABLE IF NOT EXISTS soboru_art(kind TEXT NOT NULL,target_id INTEGER NOT NULL,file TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',"
                   "created TEXT NOT NULL,PRIMARY KEY(kind,target_id))")

    def now(): return datetime.datetime.now().isoformat(timespec='seconds')

    def live():
        # 요청마다 한 번만 읽음 {(종류, 번호): 파일 이름}
        if g.get('_art_live') is None:
            with conn() as db:
                g._art_live = {(r['kind'], r['target_id']): r['file'] for r in db.execute("SELECT * FROM soboru_art WHERE status='live'")}
        return g._art_live

    def art_url(kind, target_id):
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

    def draw(kind, target_id):
        key = os.getenv('OPENAI_API_KEY', '').strip()
        if not key: raise RuntimeError('OpenAI API 키가 없어요')
        t = target(kind, target_id)
        if not t: raise RuntimeError('그릴 글을 찾지 못했어요')
        body = {'model': image_model(), 'prompt': make_prompt(*t, seed=target_id), 'size': '1536x1024', 'quality': 'low', 'output_format': 'webp', 'n': 1}
        st, res = desk.post_json('https://api.openai.com/v1/images/generations', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, 150)
        if st != 200: raise RuntimeError(f'AI 응답 오류 ({st}) ' + str((res.get('error') or {}).get('message', ''))[:160].replace(key, '***'))
        try: data = base64.b64decode(res['data'][0]['b64_json'])
        except (KeyError, IndexError, TypeError, ValueError): raise RuntimeError('AI 그림을 읽지 못했어요')
        name = f'{kind}-{target_id}-{datetime.datetime.now():%Y%m%d%H%M%S}.webp'
        (folder / name).write_bytes(data)
        with conn() as db:
            old = db.execute('SELECT file FROM soboru_art WHERE kind=? AND target_id=?', (kind, target_id)).fetchone()
            db.execute("INSERT OR REPLACE INTO soboru_art(kind,target_id,file,status,created) VALUES(?,?,?,'draft',?)", (kind, target_id, name, now()))
        if old and old['file'] != name: (folder / old['file']).unlink(missing_ok=True)

    def auto(kind, target_id):
        # 그림이 없을 때만, 키가 있을 때만. 실패하면 조용히 넘어가고 글자 카드가 그대로 나옴
        if not desk.ai_ready(): return
        with conn() as db:
            if db.execute('SELECT 1 FROM soboru_art WHERE kind=? AND target_id=?', (kind, target_id)).fetchone(): return
        def run():
            try:
                draw(kind, target_id)
                with conn() as db: db.execute("UPDATE soboru_art SET status='live' WHERE kind=? AND target_id=?", (kind, target_id))
            except Exception as e: app.logger.warning('AI 일러스트 자동 그리기 실패: %s', str(e)[:200])
        if app.config.get('TESTING'): run()
        else: threading.Thread(target=run, daemon=True).start()

    @app.route('/art/<kind>/<int:target_id>.webp')
    def art_image(kind, target_id):
        with conn() as db:
            r = db.execute('SELECT * FROM soboru_art WHERE kind=? AND target_id=?', (kind, target_id)).fetchone()
        # 게시 전 그림은 관리자만 볼 수 있음
        if not r or (r['status'] != 'live' and not S.admin_active()) or not (folder / r['file']).is_file(): abort(404)
        resp = send_file(folder / r['file'], mimetype='image/webp', max_age=86400 if r['status'] == 'live' else 0)
        return resp

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
        for r in rows:
            a = arts.get(r['id'])
            r['art'] = a['status'] if a else ''
            r['src'] = url_for('art_image', kind=kind, target_id=r['id'], v=a['file'][-12:-5]) if a else ''
        return render_template('admin_art.html', rows=rows, kind=kind, ready=desk.ai_ready(), model=image_model())

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

    app.jinja_env.globals.update(art_url=art_url)
    S.art_draw = draw; S.art_auto = auto
    app.extensions['soboru_art'] = {'auto': auto, 'draw': draw}
