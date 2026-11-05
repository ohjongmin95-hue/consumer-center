"""카드뉴스·릴스 만들기 (운영자 2026-11-05: '매번 시키지 말고 카드뉴스 프로그램처럼 하나 만들어 줘').

Magazine Studio > 카드뉴스·릴스 만들기 (/admin/magazine/maker)
- 카드뉴스: 브라우저가 그림(static/maker.js, canvas)을 그려 PNG로 내려받음. 서버는 안 거침.
- 릴스: 장면마다 [사진·영상 + 디자인 + 글]. 브라우저가 장면별 글씨 판(투명 PNG 1080x1920)을 그려 보내면
  서버 ffmpeg가 사진·영상 배치(흐린 배경·꽉 채움·단색 + 가운데 영상)와 글씨 판을 겹쳐 MP4(1080x1920, 30fps, H.264)로 만듦.
  끝에는 귤색 마무리 화면. 만든 영상은 본문 영상과 같은 곳(/art/video/)에 저장돼 '릴스' 메뉴에 바로 올릴 수 있음.
사진·영상은 기사 본문용 올리기(/admin/magazine/photo, /admin/magazine/video/*)를 그대로 씀.
카드뉴스 그림 (운영자 2026-11-05, 카드뉴스 원칙): 기사 사진·캡처는 쓰지 않고, AI가 짠 장면 설명(scene)으로 OpenAI가 새로 그림
(/admin/magazine/maker/draw, 세로 1024x1536 → 본문 사진과 같은 곳). 실제 사람 얼굴·로고·글자는 그리지 않음.
"""
import base64
import datetime
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from flask import abort, jsonify, render_template, request, url_for

W, H, FPS = 1080, 1920, 30
MAX_SCENES = 12
MAX_PNG = 4 * 1024 * 1024
OUTRO_SEC = 2.6
VIDEO = re.compile(r'/art/video/(video-\d{14}-\d{3}\.(?:mp4|webm))')
PHOTO = re.compile(r'/art/body/(body-\d{14}-\d{3}\.webp)')
# 장면 배치: 배경(blur 흐리게 / cover 꽉 채움 / 색) + 가운데 영상 자리(x, y, w, h)
LAYOUTS = {
    'wide': ('blur', (0, 620, 1080, 608)),
    'full': ('cover', None),
    'chat': ('#15120f', (60, 460, 960, 540)),
    'quote': ('blur', None),
    'clean': ('cover', None),
}


DRAW = ('Photorealistic editorial photo for a Korean consumer news Instagram card, natural light, clean composition, portrait, '
        'main subject in the lower half, calm uncluttered upper part (headline text goes there). Scene: {scene}. '
        'People only from behind, as hands, or softly blurred, never a recognizable face or a real person. '
        'No company logos, no brand names, no text, no letters, no numbers, no watermarks.')


def scene_filter(i, m, p, kind, lay, dur, speed, audio):
    """장면 하나의 필터: [m] 사진·영상, [p] 글씨 판 → [v{i}][a{i}]."""
    bg, fg = LAYOUTS[lay]
    src = f'[{m}:v]' + (f'setpts={speed}*(PTS-STARTPTS),' if kind == 'video' else '') + f'fps={FPS},setsar=1'
    cover = f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}'
    parts = []
    if bg.startswith('#'):
        parts.append(f'color=c=0x{bg[1:]}:s={W}x{H}:r={FPS}:d={dur}[bg{i}]')
        parts.append(f'{src}[s{i}]')
        fg_in = f'[s{i}]'
    else:
        look = cover + (',boxblur=36:2,eq=brightness=-0.45:saturation=0.6' if bg == 'blur' else '')
        if fg:
            parts.append(f'{src},split[s{i}][t{i}]')
            parts.append(f'[s{i}]{look}[bg{i}]')
            fg_in = f'[t{i}]'
        else:
            parts.append(f'{src},{look}[bg{i}]')
            fg_in = None
    base = f'[bg{i}]'
    if fg:
        x, y, w, h = fg
        parts.append(f'{fg_in}scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}[f{i}]')
        parts.append(f'[bg{i}][f{i}]overlay={x}:{y}:shortest=1[c{i}]')
        base = f'[c{i}]'
    parts.append(f'{base}[{p}:v]overlay=0:0:shortest=1,trim=duration={dur},setpts=PTS-STARTPTS,format=yuv420p,setsar=1[v{i}]')
    if audio and speed == 1:
        parts.append(f'[{m}:a]asetpts=PTS-STARTPTS,aformat=sample_rates=44100:channel_layouts=stereo,apad,atrim=duration={dur}[a{i}]')
    else:
        parts.append(f'anullsrc=r=44100:cl=stereo,atrim=duration={dur}[a{i}]')
    return parts


def build(scenes, outro_png, out):
    """scenes: [{kind, file, start, dur, speed, layout, png, audio}] → ffmpeg 명령."""
    cmd, filt, n = ['ffmpeg', '-v', 'error', '-y'], [], 0
    for i, s in enumerate(scenes):
        if s['kind'] == 'video':
            cmd += ['-ss', f"{s['start']:.3f}", '-t', f"{s['dur'] / s['speed']:.3f}", '-i', str(s['file'])]
        else:
            cmd += ['-loop', '1', '-t', f"{s['dur']:.3f}", '-i', str(s['file'])]
        cmd += ['-loop', '1', '-t', f"{s['dur'] + 0.5:.3f}", '-i', str(s['png'])]
        filt += scene_filter(i, n, n + 1, s['kind'], s['layout'], s['dur'], s['speed'], s['audio'])
        n += 2
    k = len(scenes)
    cmd += ['-loop', '1', '-t', f'{OUTRO_SEC + 0.5}', '-i', str(outro_png)]
    filt.append(f'color=c=0xEF920E:s={W}x{H}:r={FPS}:d={OUTRO_SEC}[ob]')
    filt.append(f'[ob][{n}:v]overlay=0:0:shortest=1,trim=duration={OUTRO_SEC},format=yuv420p,setsar=1[v{k}]')
    filt.append(f'anullsrc=r=44100:cl=stereo,atrim=duration={OUTRO_SEC}[a{k}]')
    filt.append(''.join(f'[v{j}][a{j}]' for j in range(k + 1)) + f'concat=n={k + 1}:v=1:a=1[v][a]')
    cmd += ['-filter_complex', ';'.join(filt), '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
            '-pix_fmt', 'yuv420p', '-r', str(FPS), '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', '-f', 'mp4', str(out)]
    return cmd


def has_audio(path):
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', str(path)], capture_output=True, text=True, timeout=30)
        return bool(r.stdout.strip())
    except Exception:
        return False


def png_bytes(data):
    if not isinstance(data, str) or not data.startswith('data:image/png;base64,'): return None
    try: raw = base64.b64decode(data.split(',', 1)[1], validate=True)
    except Exception: return None
    return raw if raw[:8] == b'\x89PNG\r\n\x1a\n' and len(raw) <= MAX_PNG else None


def install(S):
    app, conn = S.app, S.conn
    folder = S.UPLOAD / 'art'
    work = Path(tempfile.gettempdir()) / 'soboru-maker'

    def job_dir(job):
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,40}', job or ''): abort(404)
        return work / job

    def sweep():
        if not work.is_dir(): return
        for d in work.iterdir():
            try:
                if time.time() - d.stat().st_mtime > 6 * 3600: shutil.rmtree(d, ignore_errors=True)
            except OSError: pass

    def media_file(url):
        url = str(url or '')
        for rx, kind in ((VIDEO, 'video'), (PHOTO, 'image')):
            m = rx.fullmatch(url)
            if m and (folder / m[1]).is_file(): return kind, folder / m[1]
        return None, None

    @app.route('/admin/magazine/maker')
    @S.admin_only
    def mag_maker():
        with conn() as db:
            rows = db.execute("SELECT id,title,summary,body,category FROM articles WHERE status IN ('published','scheduled','draft') ORDER BY id DESC LIMIT 40").fetchall()
        arts = [{'id': r['id'], 'title': r['title'] or '', 'summary': r['summary'] or '', 'body': (r['body'] or '')[:4000], 'category': r['category'] or ''} for r in rows]
        return render_template('mag_admin_maker.html', arts=arts, letters=letter_list(), can_video=bool(shutil.which('ffmpeg')))

    def letter_list():
        """소보루 레터 최근 호와 꼭지들 — 한 호를 꼭지마다 게시물로 쪼개 올림 (운영자 2026-11-05)"""
        import mag_assist
        get = (app.extensions.get('soboru_letter') or {}).get('get')
        if not get: return []
        with conn() as db: ids = [r[0] for r in db.execute('SELECT id FROM letters ORDER BY no DESC LIMIT 7').fetchall()]
        out = []
        for lid in ids:
            L = get(lid=lid)
            pieces = mag_assist.letter_pieces(L) if L else []
            if pieces: out.append({'id': lid, 'no': L['no'], 'title': (L['title'] or '')[:30], 'sent': L['status'] == 'sent',
                                   'pieces': [{'key': p['key'], 'label': p['label']} for p in pieces]})
        return out

    @app.route('/admin/magazine/maker/draw', methods=['POST'])
    @S.admin_only
    def mag_maker_draw():
        import companydesk as desk, soboru_art
        scene = ' '.join(str((request.get_json(silent=True) or {}).get('scene') or '').split())[:400]
        if len(scene) < 3: return jsonify(ok=False, error='그림 장면을 적어 주세요.'), 400
        key = desk.ai_key_for('mag_maker')
        if not key: return jsonify(ok=False, error='OpenAI 키가 없어 그림을 그릴 수 없어요.'), 503
        body = {'model': soboru_art.image_model(), 'prompt': DRAW.format(scene=scene), 'size': '1024x1536', 'quality': soboru_art.image_quality(), 'output_format': 'webp', 'n': 1}
        st, res = desk.post_json('https://api.openai.com/v1/images/generations', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, 150)
        try: data = base64.b64decode(res['data'][0]['b64_json']) if st == 200 else b''
        except (KeyError, IndexError, TypeError, ValueError): data = b''
        if not data: return jsonify(ok=False, error='그림을 그리지 못했어요. 잠시 뒤 다시 해 주세요.'), 502
        name = f'body-{datetime.datetime.now():%Y%m%d%H%M%S}-{secrets.randbelow(1000):03d}.webp'
        (folder / name).write_bytes(data)
        return jsonify(ok=True, url=url_for('mag_body_image', name=name))

    @app.route('/admin/magazine/maker/render', methods=['POST'])
    @S.admin_only
    def mag_maker_render():
        if not shutil.which('ffmpeg'): return jsonify(ok=False, error='서버에 영상 만드는 프로그램(ffmpeg)이 아직 없어요.'), 503
        d = request.get_json(silent=True) or {}
        raw = d.get('scenes') or []
        if not isinstance(raw, list) or not raw: return jsonify(ok=False, error='장면을 하나 이상 만들어 주세요.'), 400
        if len(raw) > MAX_SCENES: return jsonify(ok=False, error=f'장면은 {MAX_SCENES}개까지 만들 수 있어요.'), 400
        outro = png_bytes(d.get('outro'))
        if not outro: return jsonify(ok=False, error='마무리 화면을 그리지 못했어요. 다시 해 주세요.'), 400
        work.mkdir(exist_ok=True); sweep()
        job = secrets.token_urlsafe(18); jd = job_dir(job); jd.mkdir()
        scenes, total = [], OUTRO_SEC
        for i, s in enumerate(raw):
            s = s if isinstance(s, dict) else {}
            kind, f = media_file(s.get('media'))
            png = png_bytes(s.get('png'))
            lay = s.get('layout') if s.get('layout') in LAYOUTS else 'wide'
            if not f: shutil.rmtree(jd, ignore_errors=True); return jsonify(ok=False, error=f'{i + 1}번 장면에 사진이나 영상을 넣어 주세요.'), 400
            if not png: shutil.rmtree(jd, ignore_errors=True); return jsonify(ok=False, error=f'{i + 1}번 장면 글씨 판을 그리지 못했어요.'), 400
            try:
                start = max(0.0, float(s.get('start') or 0)); dur = float(s.get('dur') or 0)
            except (TypeError, ValueError):
                start, dur = 0.0, 0.0
            speed = 2 if s.get('slow') and kind == 'video' else 1
            if not 0.5 <= dur <= 60: shutil.rmtree(jd, ignore_errors=True); return jsonify(ok=False, error=f'{i + 1}번 장면 길이는 0.5초에서 60초 사이로 정해 주세요.'), 400
            (jd / f'p{i}.png').write_bytes(png)
            scenes.append({'kind': kind, 'file': f, 'start': start, 'dur': round(dur, 3), 'speed': speed, 'layout': lay, 'png': jd / f'p{i}.png',
                           'audio': kind == 'video' and has_audio(f)})
            total += dur
        if total > 90: shutil.rmtree(jd, ignore_errors=True); return jsonify(ok=False, error='릴스는 90초까지 만들 수 있어요. 장면을 줄여 주세요.'), 400
        (jd / 'outro.png').write_bytes(outro)
        name = f'video-{datetime.datetime.now():%Y%m%d%H%M%S}-{int(time.time() * 1000) % 1000:03d}.mp4'
        part = jd / 'out.part'
        cmd = build(scenes, jd / 'outro.png', part)
        (jd / 'state').write_text('running')

        def run():
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=1800)
                ok = r.returncode == 0 and part.exists() and part.stat().st_size > 0
                if ok:
                    shutil.move(str(part), str(folder / name)); (jd / 'state').write_text('done:' + name)
                else:
                    app.logger.warning('릴스 만들기 실패: %s', r.stderr.decode('utf-8', 'replace')[-2000:]); (jd / 'state').write_text('error')
            except Exception:
                app.logger.exception('릴스 만들기 실패'); (jd / 'state').write_text('error')
        threading.Thread(target=run, daemon=True).start()
        return jsonify(ok=True, job=job, seconds=round(total, 1))

    @app.route('/admin/magazine/maker/status')
    @S.admin_only
    def mag_maker_status():
        jd = job_dir(request.args.get('job', ''))
        st = (jd / 'state').read_text() if (jd / 'state').is_file() else 'error'
        if st.startswith('done:'):
            return jsonify(state='done', url=url_for('mag_body_video', name=st[5:]))
        return jsonify(state=st)
