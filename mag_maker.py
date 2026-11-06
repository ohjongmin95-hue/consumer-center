"""카드뉴스·릴스 만들기 (운영자 2026-11-05: '매번 시키지 말고 카드뉴스 프로그램처럼 하나 만들어 줘').

Magazine Studio > 카드뉴스·릴스 만들기 (/admin/magazine/maker)
- 카드뉴스: 브라우저가 그림(static/maker.js, canvas)을 그려 PNG로 내려받음. 서버는 안 거침.
- 릴스: 장면마다 [사진·영상 + 디자인 + 글]. 브라우저가 장면별 글씨 판(투명 PNG 1080x1920)을 그려 보내면
  서버 ffmpeg가 사진·영상 배치(흐린 배경·꽉 채움·단색 + 가운데 영상)와 글씨 판을 겹쳐 MP4(1080x1920, 30fps, H.264)로 만듦.
  끝에는 귤색 마무리 화면. 만든 영상은 본문 영상과 같은 곳(/art/video/)에 저장돼 '릴스' 메뉴에 바로 올릴 수 있음.
사진·영상은 기사 본문용 올리기(/admin/magazine/photo, /admin/magazine/video/*)를 그대로 씀.
카드뉴스 그림 (운영자 2026-11-05, 카드뉴스 원칙): 기사 사진·캡처는 쓰지 않고, AI가 짠 장면 설명(scene)으로 OpenAI가 새로 그림
(/admin/magazine/maker/draw, 세로 1024x1536 → 본문 사진과 같은 곳). 실제 사람 얼굴·로고·글자는 그리지 않음.
네이버 경제 뉴스 (운영자 2026-11-05: '네이버에 댓글 많은 경제 뉴스 위주로 기사 링크 고를 수 있게'):
네이버 뉴스 경제 섹션(news.naver.com/section/101) 기사들의 댓글 수를 네이버 댓글 API로 세어 많은 순 20개 (/admin/magazine/maker/naver, 30분 저장).
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
import urllib.error
import urllib.request
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


NAVER_SECTION = 'https://news.naver.com/section/101'
# 경제 아래 분야 최신 기사 목록 (금융·증권·산업/재계·중기/벤처·부동산·글로벌 경제·생활경제·경제 일반) — 첫 화면만으로는 댓글 많은 기사가 빠져서 넓게 셈
NAVER_SUBS = ['https://news.naver.com/breakingnews/section/101/' + c for c in ('259', '258', '261', '771', '260', '262', '310', '263')]
NAVER_ART = re.compile(r'https://n\.news\.naver\.com/(?:mnews/)?article/(?:comment/)?(\d{3})/(\d{10})')
NAVER_COUNT = ('https://apis.naver.com/commentBox/cbox/web_naver_list_jsonp.json?ticket=news&templateId=default_economy&pool=cbox5&lang=ko&country=KR'
               '&objectId=news{oid}%2C{aid}&pageSize=1&page=1&sort=FAVORITE&_callback=cb')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'


def _get(url, referer=''):
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': referer or 'https://news.naver.com/', 'Accept-Language': 'ko-KR,ko;q=0.9'})
    with urllib.request.urlopen(req, timeout=8) as r: return r.read(3_000_000).decode('utf-8', 'replace')


def naver_section_articles(page):
    """경제 섹션 화면에서 기사 (oid, aid, 제목) — 같은 기사 링크가 여럿이면 가장 긴 글을 제목으로."""
    import html as H
    found = {}
    for m in re.finditer(r'(?is)<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page):
        a = NAVER_ART.match(H.unescape(m[1]))
        if not a: continue
        t = ' '.join(H.unescape(re.sub(r'<[^>]+>', ' ', m[2])).split())
        k = (a[1], a[2])
        if len(t) > len(found.get(k, '')): found[k] = t
    return [(o, a, t) for (o, a), t in found.items() if len(t) >= 8 and not re.match(r'\[\s*(?:인사|부고|게시판|알림|포토|화보)', t) and not re.search(r'\w+\s*=\s*["\']|^["\'\s>]+$|[<>]', t)]


def naver_comment_count(oid, aid):
    try: txt = _get(NAVER_COUNT.format(oid=oid, aid=aid), f'https://n.news.naver.com/mnews/article/{oid}/{aid}')
    except Exception: return -1
    m = re.search(r'"comment"\s*:\s*(\d+)', txt) or re.search(r'"count"\s*:\s*\{[^}]*"total"\s*:\s*(\d+)', txt)
    return int(m[1]) if m else -1


def scene_filter(i, m, p, kind, lay, dur, speed, audio, voice=None, tempo=1.0):
    """장면 하나의 필터: [m] 사진·영상, [p] 글씨 판 → [v{i}][a{i}]. voice: 나레이션 입력 번호(있으면 영상 소리 대신 씀)."""
    bg, fg = LAYOUTS[lay]
    src = f'[{m}:v]' + (f'setpts={speed}*(PTS-STARTPTS),' if kind == 'video' else '') + f'fps={FPS},setsar=1'
    cover = f'scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}'
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
        parts.append(f'{fg_in}scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}[f{i}]')
        parts.append(f'[bg{i}][f{i}]overlay={x}:{y}:shortest=1[c{i}]')
        base = f'[c{i}]'
    parts.append(f'{base}[{p}:v]overlay=0:0:shortest=1,trim=duration={dur},setpts=PTS-STARTPTS,format=yuv420p,setsar=1[v{i}]')
    if voice is not None:
        speedup = f'atempo={tempo:.3f},' if tempo > 1 else ''
        parts.append(f'[{voice}:a]asetpts=PTS-STARTPTS,{speedup}aresample=44100,aformat=sample_rates=44100:channel_layouts=stereo,apad,atrim=duration={dur}[a{i}]')
    elif audio and speed == 1:
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
        voice = None
        if s.get('voice'):
            cmd += ['-i', str(s['voice'])]
            voice = n + 2
        filt += scene_filter(i, n, n + 1, s['kind'], s['layout'], s['dur'], s['speed'], s['audio'], voice, s.get('tempo', 1.0))
        n += 3 if voice is not None else 2
    k = len(scenes)
    cmd += ['-loop', '1', '-t', f'{OUTRO_SEC + 0.5}', '-i', str(outro_png)]
    filt.append(f'color=c=0xEF920E:s={W}x{H}:r={FPS}:d={OUTRO_SEC}[ob]')
    filt.append(f'[ob][{n}:v]overlay=0:0:shortest=1,trim=duration={OUTRO_SEC},format=yuv420p,setsar=1[v{k}]')
    filt.append(f'anullsrc=r=44100:cl=stereo,atrim=duration={OUTRO_SEC}[a{k}]')
    filt.append(''.join(f'[v{j}][a{j}]' for j in range(k + 1)) + f'concat=n={k + 1}:v=1:a=1[v][a]')
    cmd += ['-filter_complex', ';'.join(filt), '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '16', '-profile:v', 'high',
            '-pix_fmt', 'yuv420p', '-r', str(FPS), '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', '-f', 'mp4', str(out)]
    return cmd


def has_audio(path):
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', str(path)], capture_output=True, text=True, timeout=30)
        return bool(r.stdout.strip())
    except Exception:
        return False


# 나레이션 (운영자 2026-11-06: 앵커 말고 20대 여성이 소개하듯, 너무 빠르지 않게) — OpenAI 음성. 장면 글을 mp3로 받아 영상 소리 대신 넣음. 장면보다 길면 살짝만 빠르게 읽힘
TTS_URL = 'https://api.openai.com/v1/audio/speech'
TTS_MODELS = ('gpt-4o-mini-tts', 'tts-1')
TTS_VOICE = 'nova'
TTS_STYLE = '20대 한국 여성이 친구에게 요즘 소식을 소개하듯 밝고 자연스럽게 말한다. 뉴스 앵커처럼 딱딱하게 읽지 않는다. 서두르지 말고 여유 있는 속도로, 문장 사이를 살짝 쉬어 가며 말하고, 숫자는 또박또박 읽는다.'
NARRATION_MAX = 300
TEMPO_MAX = 1.1


def speak(text, path, key, voice=None):
    """글을 mp3로 저장. 앞 모델을 못 쓰는 키면 다음 모델로."""
    last = None
    for model in TTS_MODELS:
        body = {'model': model, 'voice': voice or TTS_VOICE, 'input': text, 'response_format': 'mp3'}
        if model != 'tts-1': body['instructions'] = TTS_STYLE
        req = urllib.request.Request(TTS_URL, data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=120) as r: data = r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 403, 404): continue
            raise
        if not data: raise RuntimeError('음성이 비어 있어요')
        Path(path).write_bytes(data)
        return
    raise last or RuntimeError('음성을 만들지 못했어요')


def audio_len(path):
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)], capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def fit_tempo(length, dur):
    """장면 길이에 맞추는 빠르기 (1 이상, 너무 빨라지지 않게 TEMPO_MAX까지. 그래도 길면 잘림)."""
    if length <= 0 or dur <= 0: return 1.0
    return round(min(TEMPO_MAX, max(1.0, length / dur)), 3)


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

    naver_cache = {'at': 0, 'items': []}

    @app.route('/admin/magazine/maker/naver')
    @S.admin_only
    def mag_maker_naver():
        if time.time() - naver_cache['at'] < 1800 and naver_cache['items']: return jsonify(ok=True, items=naver_cache['items'])
        from concurrent.futures import ThreadPoolExecutor
        def page(u):
            try: return naver_section_articles(_get(u))
            except Exception: return []
        with ThreadPoolExecutor(9) as ex: pages = list(ex.map(page, [NAVER_SECTION] + NAVER_SUBS))
        arts, seen = [], set()
        for pg in pages:
            for x in pg:
                if (x[0], x[1]) not in seen: seen.add((x[0], x[1])); arts.append(x)
        arts = arts[:160]
        if not arts: return jsonify(ok=False, error='네이버 경제 뉴스를 불러오지 못했어요. 잠시 뒤 다시 해 주세요.'), 502
        with ThreadPoolExecutor(12) as ex: counts = list(ex.map(lambda x: naver_comment_count(x[0], x[1]), arts))
        items = sorted(({'url': f'https://n.news.naver.com/mnews/article/{o}/{a}', 'title': t[:80], 'comments': c} for (o, a, t), c in zip(arts, counts)),
                       key=lambda x: -x['comments'])[:20]
        naver_cache.update(at=time.time(), items=items)
        return jsonify(ok=True, items=items)

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
                           'audio': kind == 'video' and has_audio(f), 'narration': ' '.join(str(s.get('narration') or '').split())[:NARRATION_MAX]})
            total += dur
        if total > 90: shutil.rmtree(jd, ignore_errors=True); return jsonify(ok=False, error='릴스는 90초까지 만들 수 있어요. 장면을 줄여 주세요.'), 400
        (jd / 'outro.png').write_bytes(outro)
        name = f'video-{datetime.datetime.now():%Y%m%d%H%M%S}-{int(time.time() * 1000) % 1000:03d}.mp4'
        part = jd / 'out.part'
        tts_key = ''
        if any(s['narration'] for s in scenes):
            import companydesk as desk
            tts_key = desk.ai_key_for('mag_maker')
            if not tts_key: shutil.rmtree(jd, ignore_errors=True); return jsonify(ok=False, error='OpenAI 키가 없어 나레이션을 만들 수 없어요.'), 503
        (jd / 'state').write_text('running')
        meta = {k: str(d.get(k) or '') for k in ('title', 'caption', 'source')}

        def run():
            try:
                for i, s in enumerate(scenes):
                    if not s['narration']: continue
                    s['voice'] = jd / f'n{i}.mp3'
                    speak(s['narration'], s['voice'], tts_key)
                    s['tempo'] = fit_tempo(audio_len(s['voice']), s['dur'])
                r = subprocess.run(build(scenes, jd / 'outro.png', part), capture_output=True, timeout=1800)
                ok = r.returncode == 0 and part.exists() and part.stat().st_size > 0
                if ok:
                    shutil.move(str(part), str(folder / name)); (jd / 'state').write_text('done:' + name)
                    save = app.extensions.get('made_save_reel')  # 운영자 2026-11-05: 만든 릴스는 보관함에도 (mag_made.py)
                    if save:
                        try: save(folder / name, meta['title'], meta['caption'], meta['source'])
                        except Exception: app.logger.exception('릴스 보관함 저장 실패')
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
