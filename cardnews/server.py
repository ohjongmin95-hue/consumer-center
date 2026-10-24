"""소보루 카드뉴스 만들기 화면 (내 컴퓨터에서만 열림: http://127.0.0.1:5050).

실행: 소보루카드뉴스.exe(윈도우)·소보루카드뉴스.app(맥) 더블클릭 (build.py로 만든 실행 파일), 또는 python server.py
- 데이터: 개발할 때는 이 폴더의 data/, 실행 파일은 '문서/소보루 카드뉴스' 폴더 (실행 파일을 지우거나 새 버전으로 바꿔도 남음).
  cards.sqlite3(만든 카드뉴스), config.json(API 키·설정), secret.key(화면 보호용 비밀키).
- 이미 켜져 있을 때 또 누르면 새로 켜지 않고 브라우저만 연다. 끌 때는 화면 위 '끄기'.
- 켜져 있는 동안 매일 아침 8시(설정에서 바꿈)가 지나면 소비자 뉴스로 초안을 만든다. 꺼져 있던 날은 다음에 켤 때 한 번 만든다.
- 만드는 일은 cards.py. 이 파일은 화면·저장·예약만.
"""
import datetime, json, os, re, secrets, socket, sqlite3, sys, threading, time, webbrowser
from pathlib import Path
from flask import Flask, abort, flash, redirect, render_template, request, send_from_directory, session, url_for
import cards

HERE = Path(__file__).resolve().parent
FROZEN = getattr(sys, 'frozen', False)  # PyInstaller로 만든 실행 파일
RES = Path(getattr(sys, '_MEIPASS', HERE))  # 화면 파일(templates·static) 있는 곳


def data_dir():
    if os.getenv('CARDNEWS_DATA'): return Path(os.getenv('CARDNEWS_DATA'))
    if not FROZEN: return HERE / 'data'
    docs = Path.home() / 'Documents'
    return (docs if docs.is_dir() else Path.home()) / '소보루 카드뉴스'


DATA = data_dir()
PORT = int(os.getenv('CARDNEWS_PORT') or 5050)
PER_DAY = (1, 2, 3, 4, 5)
MODELS = (('claude-opus-5-5', 'Claude Opus 5.5 (기본, 가장 꼼꼼)'), ('claude-sonnet-5-5', 'Claude Sonnet 5.5 (더 싸고 빠름)'))
DEFAULTS = {'key': '', 'model': 'claude-opus-5-5', 'art': 'claude', 'auto': 0, 'per_day': 3, 'hour': 8, 'web_search': 1,
            'naver_kind': 'dev', 'naver_id': '', 'naver_secret': '', 'hf_id': '', 'hf_secret': '', 'hf_model': cards.HF_MODELS[0][0], 'img_default': 'art'}
SECRETS = ('key', 'naver_secret', 'hf_secret')  # 화면에 다시 보여 주지 않는 값
IMG_DEFAULTS = (('art', '모두 그림 (힉스필드 크레딧 안 듦)'), ('cover_photo', '표지만 사진 (힉스필드), 나머지는 그림'), ('photo', '모두 사진 (힉스필드)'))

DATA.mkdir(parents=True, exist_ok=True)
app = Flask(__name__, template_folder=str(RES / 'templates'), static_folder=str(RES / 'static'))
key_file = DATA / 'secret.key'
if not key_file.exists(): key_file.write_text(secrets.token_hex(32))
app.secret_key = key_file.read_text().strip()
app.config.update(SESSION_COOKIE_SAMESITE='Strict', MAX_CONTENT_LENGTH=20 * 1024 * 1024)
IMAGES = DATA / 'images'; IMAGES.mkdir(exist_ok=True)  # 사진(힉스필드로 만든 것·직접 올린 것)


def conn():
    db = sqlite3.connect(DATA / 'cards.sqlite3', timeout=30); db.row_factory = sqlite3.Row
    return db


with conn() as db:
    db.execute('''CREATE TABLE IF NOT EXISTS cards(id INTEGER PRIMARY KEY AUTOINCREMENT,url TEXT NOT NULL,title TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'check',data TEXT NOT NULL,facts TEXT NOT NULL,checks TEXT NOT NULL,
        trigger TEXT NOT NULL DEFAULT 'manual',confirmed INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL,updated TEXT NOT NULL)''')
    db.execute('CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT NOT NULL,what TEXT NOT NULL)')


# ---- 설정 (data/config.json) --------------------------------------------------------
def config():
    try: c = json.loads((DATA / 'config.json').read_text())
    except (OSError, ValueError): c = {}
    c = {k: c.get(k, v) for k, v in DEFAULTS.items()}
    if os.getenv('ANTHROPIC_API_KEY'): c['key'] = os.getenv('ANTHROPIC_API_KEY').strip()  # 환경변수가 있으면 그걸 씀
    return c


def save_config(c):
    path = DATA / 'config.json'
    path.write_text(json.dumps({k: c[k] for k in DEFAULTS}, ensure_ascii=False, indent=1))
    try: os.chmod(path, 0o600)
    except OSError: pass


def log(what):
    with conn() as db:
        db.execute('INSERT INTO log(at,what) VALUES(?,?)', (cards.stamp(), what[:300]))
        db.execute('DELETE FROM log WHERE id NOT IN (SELECT id FROM log ORDER BY id DESC LIMIT 50)')


# ---- 화면 보호: 다른 웹사이트가 내 컴퓨터의 이 화면으로 몰래 요청을 보내지 못하게 ---------------------
def csrf_token():
    if '_csrf' not in session: session['_csrf'] = secrets.token_urlsafe(24)
    return session['_csrf']


@app.before_request
def guard():
    if request.host.split(':')[0] not in ('127.0.0.1', 'localhost'): abort(403)  # 주소를 바꿔 들어오는 요청(DNS 리바인딩) 막기
    if request.method == 'POST' and not secrets.compare_digest(str(request.form.get('_csrf', '')), csrf_token()): abort(400)


app.jinja_env.globals.update(csrf_token=csrf_token)


# ---- 저장 ------------------------------------------------------------------------
MODES = ('auto', 'paste', 'manual')  # 글 쓰는 방법: Claude API 키로 자동 / claude.ai(구독)에 붙여넣기 / 직접 쓰기


def store(r, trigger, status=None):
    with conn() as db:
        return db.execute('INSERT INTO cards(url,title,status,data,facts,checks,trigger,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                          (r['facts']['url'], r['facts']['title'], status or cards.status_of(r['checks']), json.dumps(r['data'], ensure_ascii=False),
                           json.dumps(r['facts'], ensure_ascii=False), json.dumps(r['checks'], ensure_ascii=False), trigger, cards.stamp(), cards.stamp())).lastrowid


def load(cid):
    with conn() as db: row = db.execute('SELECT * FROM cards WHERE id=?', (cid,)).fetchone()
    if not row: abort(404)
    return dict(row, data=json.loads(row['data']), facts=json.loads(row['facts']), checks=json.loads(row['checks']))


def resave(cid, d, facts, confirmed):
    checks = cards.run_checks(d, facts)
    with conn() as db:
        db.execute('UPDATE cards SET data=?,checks=?,status=?,confirmed=?,updated=? WHERE id=?',
                   (json.dumps(d, ensure_ascii=False), json.dumps(checks, ensure_ascii=False), cards.status_of(checks), confirmed, cards.stamp(), cid))
    return cards.status_of(checks)


def save_photo(raw, slot, src):
    """사진 바이트 → images/에 저장하고 자리에 붙임 (ValueError: 사진이 아님)"""
    name = secrets.token_hex(8) + '.jpg'
    (IMAGES / name).write_bytes(cards.clean_photo(raw))
    slot.update(mode='photo', photo=name, src=src)


def hf_photos(d, which=None):
    """힉스필드로 사진 만들기. which: 자리 이름 목록 (None이면 설정 '사진 기본값'대로). 못 만든 자리는 그림으로 남기고 이유를 돌려줌."""
    cfg = config()
    if not cards.hf_ready(cfg): return ['힉스필드 키가 없어 사진은 건너뛰었어요']
    want = which if which is not None else {'art': [], 'cover_photo': ['cover'], 'photo': [n for n, _, _ in cards.slots(d)]}[cfg['img_default']]
    errs = []
    for name, scene, slot in cards.slots(d):
        if name not in want: continue
        try: save_photo(cards.higgsfield_photo(cfg, scene), slot, 'hf')
        except (RuntimeError, ValueError) as e: errs.append(str(e))
    return errs[:1]


def make(url, trigger='manual', art=None):
    r = cards.make(config(), url, art)
    if r['status'] != 'made': log(f"{'자동 · ' if trigger == 'daily' else ''}못 만듦: {r['reason']} ({(url or (art or {}).get('title', ''))[:80]})"); return r
    errs = hf_photos(r['data'])
    if config()['img_default'] != 'art' and errs: r['reason'] = ' · '.join(filter(None, [r.get('reason'), f'사진: {errs[0]}']))
    r['checks'] = cards.run_checks(r['data'], r['facts'])
    cid = store(r, trigger)
    log(f"{'자동 · ' if trigger == 'daily' else ''}만듦 #{cid}" + (f" · {r['reason']}" if r.get('reason') else ''))
    return {'status': 'made', 'id': cid}


def daily():
    """매일 몫: 오늘 자동으로 만든 게 per_day보다 적으면 채움"""
    c = config()
    if not c['key']: return
    today = datetime.date.today().isoformat()
    with conn() as db:
        done = db.execute("SELECT COUNT(*) FROM cards WHERE trigger='daily' AND created>=?", (today,)).fetchone()[0]
        used = {r[0] for r in db.execute('SELECT url FROM cards')}
    if done >= c['per_day']: return
    try: urls = cards.find_news(c, c['per_day'] - done, used)
    except RuntimeError as e: log(f'자동 · 뉴스를 고르지 못했어요: {e}'); return
    if not urls: log('자동 · 새로 만들 소비자 뉴스를 찾지 못했어요'); return
    for url in urls:
        if done >= c['per_day']: break
        if make(url, 'daily').get('status') == 'made': done += 1


# ---- 뒤에서 하는 일 (Claude가 몇 분 걸려서) ------------------------------------------------
JOB = {'state': '', 'what': '', 'result': None}
LOCK = threading.Lock()


def background(what, fn):
    with LOCK:
        if JOB['state'] == 'running': return False
        JOB.update(state='running', what=what, result=None)
    def run():
        try: r = fn()
        except Exception as e: r = {'status': 'error', 'reason': f'만들지 못했어요 ({type(e).__name__})'}
        JOB.update(state='done', result=r or {'status': 'error', 'reason': ''})
    threading.Thread(target=run, daemon=True).start()
    return True


def scheduler():
    """켜져 있는 동안 1분마다: 자동 만들기가 켜져 있고 정한 시각이 지났으면 오늘 몫을 만듦"""
    while True:
        try:
            c = config()
            if c['auto'] and datetime.datetime.now().hour >= c['hour'] and JOB['state'] != 'running':
                with conn() as db: done = db.execute("SELECT COUNT(*) FROM cards WHERE trigger='daily' AND created>=?", (datetime.date.today().isoformat(),)).fetchone()[0]
                tried = (DATA / 'last-daily').read_text().strip() if (DATA / 'last-daily').exists() else ''
                if done < c['per_day'] and tried != datetime.date.today().isoformat():
                    (DATA / 'last-daily').write_text(datetime.date.today().isoformat())  # 하루 한 번만 시도 (실패해도 계속 돌지 않게)
                    background('오늘의 자동 카드뉴스', daily)
        except Exception as e: log(f'자동 예약 오류: {type(e).__name__}')
        time.sleep(60)


def finish(r):
    if r.get('status') == 'made': flash('카드뉴스를 만들었어요. 넘겨 보며 확인하고 고쳐 주세요.'); return redirect(url_for('card', cid=r['id']))
    flash(('지금은 만들 수 없어요: ' if r.get('status') == 'skip' else '만들지 못했어요: ') + (r.get('reason') or ''))
    return redirect(url_for('home'))


# ---- 화면 ------------------------------------------------------------------------
@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        f = request.form; url = f.get('url', '').strip()
        mode = f.get('mode') if f.get('mode') in MODES else ('auto' if config()['key'] else 'paste')
        # 기사 글을 붙여 넣었으면 그걸 쓰고(링크는 출처로만), 아니면 링크에서 읽어 옴
        art = cards.given_article(f.get('text', ''), f.get('title', ''), f.get('media', ''), f.get('date', ''), url) if f.get('text', '').strip() else None
        if mode == 'auto':
            if app.config.get('TESTING'): return finish(make(url, art=art))
            if not background('새 카드뉴스', lambda: make(url, art=art)): flash('다른 카드뉴스를 만들고 있어요. 다 되면 다시 눌러 주세요.')
            return redirect(url_for('job'))
        got, why = cards.read(config(), url, art)  # 키 없는 방법: 기사 읽기·다른 기사 찾기(네이버 키가 있을 때)만
        if not got: flash(why); return redirect(url_for('home'))
        a, others, facts = got
        if mode == 'manual':
            d = cards.blank(a); cid = store({'data': d, 'facts': facts, 'checks': cards.run_checks(d, facts)}, 'manual')
            log(f'직접 쓰기 #{cid}'); flash('빈 카드뉴스를 만들었어요. 오른쪽 칸에 글을 써 주세요.'); return redirect(url_for('card', cid=cid))
        cid = store({'data': {'pending': True, 'prompt': cards.paste_prompt(a, others), 'art': a}, 'facts': facts, 'checks': []}, 'manual', status='paste')
        return redirect(url_for('paste', cid=cid))
    with conn() as db:
        rows = [dict(r) for r in db.execute('SELECT id,url,title,status,trigger,created,data FROM cards ORDER BY id DESC LIMIT 100')]
        logs = [dict(r) for r in db.execute('SELECT at,what FROM log ORDER BY id DESC LIMIT 8')]
    for r in rows:
        d = json.loads(r.pop('data')); cs = d.get('covers') or [{}]
        if d.get('pending'): r['cover'] = 'claude.ai 답을 붙여 넣어 주세요'; r['media'] = d['art'].get('media', ''); continue
        c = cs[min(d.get('cover_pick', 0), len(cs) - 1)]
        r['cover'] = (c.get('line1', '') + ' ' + c.get('line2', '')).strip(); r['media'] = (d.get('source') or {}).get('media', '')
    cfg = config()
    return render_template('home.html', rows=rows, cfg=cfg, logs=logs, naver=bool(cfg['naver_id'] and cfg['naver_secret']))


@app.route('/job')
def job():
    if JOB['state'] == 'done':
        r = JOB['result']; JOB.update(state='', result=None); return finish(r)
    if JOB['state'] != 'running': return redirect(url_for('home'))
    return render_template('home.html', waiting=JOB['what'], rows=[], cfg=config(), logs=[], naver=True)


@app.route('/card/<int:cid>', methods=['GET', 'POST'])
def card(cid):
    c = load(cid)
    if c['data'].get('pending') and not (request.method == 'POST' and request.form.get('act') == 'delete'): return redirect(url_for('paste', cid=cid))
    if request.method == 'POST':
        act = request.form.get('act', 'save')
        if act == 'artpaste':  # 키 없이 그림: claude.ai가 준 SVG를 붙여 넣음
            n = cards.art_from_paste(request.form.get('answer', ''), c['data'])
            if not n: flash('붙여 넣은 글에서 그림(SVG)을 찾지 못했어요. Claude 답 전체를 복사해 주세요.'); return redirect(url_for('card', cid=cid))
            for _, _, slot in cards.slots(c['data']): slot['mode'] = slot['mode'] if slot.get('photo') else 'art'
            resave(cid, c['data'], c['facts'], c['confirmed']); flash(f'그림 {n}개를 넣었어요.'); return redirect(url_for('card', cid=cid))
        if act == 'delete':
            with conn() as db: db.execute('DELETE FROM cards WHERE id=?', (cid,))
            flash('카드뉴스를 지웠어요.'); return redirect(url_for('home'))
        if act == 'art':
            def redraw():
                cur = load(cid); cfg = config()
                try: d = cards.ARTISTS.get(cfg['art'], cards.draw_claude)(cfg, cur['data'])
                except RuntimeError as e: return {'status': 'error', 'reason': str(e)}
                resave(cid, d, cur['facts'], cur['confirmed']); return {'status': 'made', 'id': cid}
            if app.config.get('TESTING'): return finish(redraw())
            if not background('그림 다시 그리기', redraw): flash('다른 작업을 하고 있어요. 다 되면 다시 눌러 주세요.')
            return redirect(url_for('job'))
        if act == 'upload':  # 직접 올린 사진 (힉스필드 사이트에서 만든 것 등)
            slot = dict((n, x) for n, _, x in cards.slots(c['data'])).get(request.form.get('slot', ''))
            f = request.files.get('photo')
            if slot is None or not f: abort(400)
            try: save_photo(f.read(), slot, 'upload')
            except ValueError as e: flash(str(e)); return redirect(url_for('card', cid=cid))
            resave(cid, c['data'], c['facts'], c['confirmed']); flash('사진을 넣었어요.'); return redirect(url_for('card', cid=cid))
        if act == 'hf':
            name = request.form.get('slot', '')
            if name not in [n for n, _, _ in cards.slots(c['data'])]: abort(400)
            def photo():
                cur = load(cid); errs = hf_photos(cur['data'], [name])
                if errs: return {'status': 'error', 'reason': errs[0]}
                resave(cid, cur['data'], cur['facts'], cur['confirmed']); return {'status': 'made', 'id': cid}
            if app.config.get('TESTING'): return finish(photo())
            if not background('힉스필드 사진 만들기', photo): flash('다른 작업을 하고 있어요. 다 되면 다시 눌러 주세요.')
            return redirect(url_for('job'))
        try: new = json.loads(request.form.get('data', ''))
        except ValueError: abort(400)
        d = c['data']  # 화면에서 고칠 수 있는 글만 받음 (그림·출처 링크·검사 메모는 저장된 것 그대로)
        s = lambda v, n: str(v if v is not None else '')[:n]
        d['topic'] = s(new.get('topic'), 60); d['emoji'] = s(new.get('emoji'), 4)
        d['covers'] = [{'line1': s(x.get('line1'), 20), 'line2': s(x.get('line2'), 20)} for x in (new.get('covers') or d['covers'])[:5]]
        try: d['cover_pick'] = min(max(int(new.get('cover_pick') or 0), 0), max(len(d['covers']) - 1, 0))
        except (TypeError, ValueError): d['cover_pick'] = 0
        for old, nc in zip(d['cards'], new.get('cards') or []): old.update(kicker=s(nc.get('kicker'), 30), title=s(nc.get('title'), 40), body=s(nc.get('body'), 200))
        d['tips'] = [s(t, 40) for t in (new.get('tips') or d['tips'])[:3]]
        d['end'] = new.get('end') if new.get('end') in cards.ENDS else 'save'; d['share_line'] = s(new.get('share_line'), 30)
        newslots = [new.get('cover_img') or {}] + [(nc.get('img') or {}) for nc in (new.get('cards') or [])]
        for (_, _, slot), ns in zip(cards.slots(d), newslots):  # 그림/사진 고르기만 (사진 파일은 올리기로만 바뀜)
            slot['mode'] = 'photo' if ns.get('mode') == 'photo' and slot.get('photo') else 'art'
        d['caption'] = s(new.get('caption'), 1500)
        d['hashtags'] = [re.sub(r'[#\s]', '', str(h))[:20] for h in (new.get('hashtags') or [])[:8] if re.sub(r'[#\s]', '', str(h))]
        src = new.get('source') or {}; d['source'].update(media=s(src.get('media'), 30), date=s(src.get('date'), 12))
        status = resave(cid, d, c['facts'], 1 if request.form.get('confirmed') else 0)
        flash('저장했어요.' + (' 체크리스트에 걸린 항목이 있어요.' if status == 'check' else ''))
        return redirect(url_for('card', cid=cid))
    sl = [(n, '표지' if n == 'cover' else f'{int(n[4:]) + 2}번째 장', x) for n, _, x in cards.slots(c['data'])]
    return render_template('edit.html', c=c, d=c['data'], caption=cards.caption_full(c['data']), slots=sl, hf=cards.hf_ready(config()),
                           key=bool(config()['key']), art_prompt=cards.art_prompt(c['data']))


@app.route('/card/<int:cid>/paste', methods=['GET', 'POST'])
def paste(cid):
    """키 없이: 요청 글 복사 → claude.ai에 붙여 넣기 → Claude 답 붙여 넣기"""
    c = load(cid)
    if not c['data'].get('pending'): return redirect(url_for('card', cid=cid))
    if request.method == 'POST':
        try: d = cards.from_paste(request.form.get('answer', ''), c['data']['art'])
        except ValueError as e: flash(str(e)); return redirect(url_for('paste', cid=cid))
        errs = hf_photos(d)
        resave(cid, d, c['facts'], 0); log(f'붙여넣기로 만듦 #{cid}')
        flash('카드뉴스를 만들었어요. 그림은 아래 \'그림 · 사진\'에서 사진을 올리거나 claude.ai로 받아 넣어 주세요.' + (f' (사진: {errs[0]})' if errs and config()['img_default'] != 'art' else ''))
        return redirect(url_for('card', cid=cid))
    return render_template('paste.html', c=c, prompt=c['data']['prompt'])


@app.route('/img/<name>')
def img(name):
    if not re.fullmatch(r'[0-9a-f]{16}\.jpg', name): abort(404)
    return send_from_directory(IMAGES, name, max_age=86400)


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    c = config()
    if request.method == 'POST':
        f = request.form
        for k in SECRETS + ('naver_id', 'hf_id'):
            v = f.get(k, '').strip()
            if v or f.get('clear_' + k): c[k] = '' if f.get('clear_' + k) else v  # 비워 두면 그대로, '지우기'를 고르면 지움
        if f.get('clear_naver_id'): c['naver_secret'] = ''
        if f.get('clear_hf_id'): c['hf_secret'] = ''
        c['hf_model'] = f.get('hf_model') if f.get('hf_model') in dict(cards.HF_MODELS) else cards.HF_MODELS[0][0]
        c['img_default'] = f.get('img_default') if f.get('img_default') in dict(IMG_DEFAULTS) else 'art'
        if c['key'] and not c['key'].startswith('sk-ant-'): flash("Claude API 키는 'sk-ant-'로 시작해요. 다시 확인해 주세요."); return redirect(url_for('settings'))
        c['model'] = f.get('model') if f.get('model') in dict(MODELS) else DEFAULTS['model']
        c['art'] = f.get('art') if f.get('art') in cards.ARTISTS else 'claude'
        c['naver_kind'] = f.get('naver_kind') if f.get('naver_kind') in cards.NAVER else 'dev'
        c['auto'] = 1 if f.get('auto') else 0; c['web_search'] = 1 if f.get('web_search') else 0
        c['per_day'] = f.get('per_day', type=int) if f.get('per_day', type=int) in PER_DAY else 3
        c['hour'] = min(max(f.get('hour', type=int) or 8, 0), 23)
        save_config(c); flash('설정을 저장했어요.'); return redirect(url_for('settings'))
    mask = lambda v: (v[:7] + '…' + v[-4:]) if len(v) > 14 else ('있음' if v else '')
    return render_template('settings.html', cfg=c, masked={k: mask(c[k]) for k in SECRETS}, models=MODELS, artists=list(cards.ARTISTS), per_day=PER_DAY, hf_models=cards.HF_MODELS, img_defaults=IMG_DEFAULTS,
                           env_key=bool(os.getenv('ANTHROPIC_API_KEY')), data_dir=str(DATA))


@app.route('/quit', methods=['POST'])
def quit_app():
    if not app.config.get('TESTING'): threading.Timer(0.5, lambda: os._exit(0)).start()
    return render_template('base.html', bye=True)


def running():
    """이미 켜져 있는지 (같은 칸을 누가 쓰고 있는지)"""
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', PORT)) == 0


def main():
    url = f'http://127.0.0.1:{PORT}'
    if sys.stdout is None: sys.stdout = sys.stderr = open(os.devnull, 'w')  # 검은 창 없는 실행 파일: 출력할 곳이 없음
    if FROZEN:  # 실행 파일 안의 Python은 컴퓨터의 인증서 목록을 못 찾을 수 있어 기사 읽기용으로 함께 넣은 목록을 씀
        import certifi
        os.environ.setdefault('SSL_CERT_FILE', certifi.where())
    if running():  # 두 번 눌렀으면 브라우저만 다시 열기
        webbrowser.open(url); return
    threading.Thread(target=scheduler, daemon=True).start()
    print(f'\n  소보루 카드뉴스 만들기를 켰어요 → {url}\n  끄려면 화면 위 [끄기]를 누르거나 이 창을 닫으세요.\n  데이터: {DATA}\n')
    if '--no-browser' not in sys.argv: threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host='127.0.0.1', port=PORT, debug=False, threaded=True)


if __name__ == '__main__':
    main()
