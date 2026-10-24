"""민주의 카드뉴스 제작 프로그램 화면 (내 컴퓨터에서만 열림: http://127.0.0.1:5050). 만드는 카드뉴스의 브랜드는 소보루(SOBORU).

실행: MinjuCardNews.exe(윈도우) 더블클릭 (build.py로 만든 실행 파일), 또는 python server.py
- 데이터: 개발할 때는 이 폴더의 data/, 실행 파일은 '문서/민주의 카드뉴스 제작 프로그램' 폴더 (실행 파일을 지우거나 새 버전으로 바꿔도 남음).
  cards.sqlite3(만든 카드뉴스), config.json(API 키·설정), secret.key(화면 보호용 비밀키).
- 브라우저가 아니라 프로그램 창(pywebview·Edge WebView2)으로 열린다. 창을 닫으면 꺼진다. 창을 못 열면 브라우저로 연다(--browser로 일부러도).
- 처음 켤 때 바탕화면에 바로가기를 만든다. 이미 켜져 있을 때 또 누르면 창만 하나 더 연다.
- 켜져 있는 동안 매일 아침 8시(설정에서 바꿈)가 지나면 소비자 뉴스로 초안을 만든다. 꺼져 있던 날은 다음에 켤 때 한 번 만든다.
- 만드는 일은 cards.py. 이 파일은 화면·저장·예약만.
"""
import datetime, json, os, re, secrets, socket, sqlite3, sys, threading, time, webbrowser
from pathlib import Path
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for
import cards, kakao

NAME = '민주의 카드뉴스 제작 프로그램'
SHORT = '민주의 카드뉴스'  # 바탕화면 바로가기 이름 (토스POS처럼 짧게)
HERE = Path(__file__).resolve().parent
FROZEN = getattr(sys, 'frozen', False)  # PyInstaller로 만든 실행 파일
RES = Path(getattr(sys, '_MEIPASS', HERE))  # 화면 파일(templates·static) 있는 곳


def data_dir():
    if os.getenv('CARDNEWS_DATA'): return Path(os.getenv('CARDNEWS_DATA'))
    if not FROZEN: return HERE / 'data'
    base = Path.home() / 'Documents'
    base = base if base.is_dir() else Path.home()
    new, old = base / NAME, base / '소보루 카드뉴스'  # 예전 이름 폴더(키·카드뉴스)가 있으면 새 이름으로 옮김
    if old.is_dir() and not new.exists():
        try: old.rename(new)
        except OSError: return old
    return new


DATA = data_dir()
PORT = int(os.getenv('CARDNEWS_PORT') or 5050)
PER_DAY = (1, 2, 3, 4, 5)
MODELS = (('claude-opus-5-5', 'Claude Opus 5.5 (기본, 가장 꼼꼼)'), ('claude-sonnet-5-5', 'Claude Sonnet 5.5 (더 싸고 빠름)'))
DEFAULTS = {'key': '', 'model': 'claude-opus-5-5', 'auto': 0, 'per_day': 3, 'hour': 8, 'web_search': 1,
            'naver_kind': 'dev', 'naver_id': '', 'naver_secret': '', 'hf_id': '', 'hf_secret': '', 'hf_model': cards.HF_MODELS[0][0], 'img_style': 'mix', 'hf_auto': 0,
            'kakao_key': '', 'kakao_secret': '', 'kakao_token': {}, 'kakao_auto': 1}
SECRETS = ('key', 'naver_secret', 'hf_secret', 'kakao_secret')  # 화면에 다시 보여 주지 않는 값
IMG_STYLES = (('mix', '표지는 사진, 본문은 일러스트'), ('photo', '모두 사진'), ('illust', '모두 일러스트'))

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


app.jinja_env.globals.update(csrf_token=csrf_token, app_name=NAME)


@app.context_processor
def sidebar():
    """왼쪽 사이드바: 만든 카드뉴스 목록·연결 상태 (모든 화면)"""
    if request.endpoint in ('static', 'img', None): return {}
    with conn() as db: rows = db.execute('SELECT id,title,status,trigger,created,data FROM cards ORDER BY id DESC LIMIT 60').fetchall()
    items = []
    for r in rows:
        d = json.loads(r['data']); cs = d.get('covers') or [{}]; c = cs[min(d.get('cover_pick', 0), len(cs) - 1)]
        cover = 'claude.ai 답을 기다려요' if d.get('pending') else (c.get('line1', '') + ' ' + c.get('line2', '')).strip()
        items.append({'id': r['id'], 'cover': cover or r['title'] or '(제목 없음)', 'status': r['status'], 'created': r['created'], 'daily': r['trigger'] == 'daily'})
    cfg = config()
    return {'side_items': items, 'side_cfg': {'claude': bool(cfg['key']), 'hf': bool(cfg['hf_id'] and cfg['hf_secret']), 'naver': bool(cfg['naver_id'] and cfg['naver_secret'])},
            'side_cid': (request.view_args or {}).get('cid')}


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
    slot.update(photo=name, src=src)


def hf_photos(d, which=None):
    """힉스필드로 이미지 만들기 (API 크레딧). which: 자리 이름 목록 (None이면 설정 '새 카드뉴스 만들 때 힉스필드로 자동'이 켜졌을 때 전부).
    자리마다 고른 스타일(사진/일러스트)로. 못 만든 자리는 비워 두고 이유를 돌려줌."""
    cfg = config()
    cards.slots(d, cfg['img_style'])  # 새 카드뉴스면 기본 스타일을 정해 둠
    if which is None and not cfg['hf_auto']: return []
    if not cards.hf_ready(cfg): return ['힉스필드 키가 없어요']
    want = which if which is not None else [n for n, _, _ in cards.slots(d)]
    errs = []
    for name, scene, slot in cards.slots(d):
        if name not in want: continue
        try: save_photo(cards.higgsfield_photo(cfg, scene, slot['style']), slot, 'hf')
        except (RuntimeError, ValueError) as e: errs.append(str(e))
    return errs[:1]


def make(url, trigger='manual', art=None):
    r = cards.make(config(), url, art)
    if r['status'] != 'made': log(f"{'자동 · ' if trigger == 'daily' else ''}못 만듦: {r['reason']} ({(url or (art or {}).get('title', ''))[:80]})"); return r
    errs = hf_photos(r['data'])
    if errs: r['reason'] = ' · '.join(filter(None, [r.get('reason'), f'사진: {errs[0]}']))
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
    made = []
    for url in urls:
        if done >= c['per_day']: break
        r = make(url, 'daily')
        if r.get('status') == 'made': done += 1; made.append(r['id'])
    if made and c['kakao_auto'] and kakao.ready(c):  # 아침 초안이 생겼다고 내 카톡으로
        with conn() as db: rows = [db.execute('SELECT title FROM cards WHERE id=?', (i,)).fetchone()[0] for i in made]
        try: kakao.send_note(c, save_kakao, f'☀️ 오늘의 카드뉴스 초안 {len(made)}개가 만들어졌어요\n' + '\n'.join('· ' + t[:40] for t in rows) + '\n\n프로그램에서 확인하고 올려 주세요.')
        except RuntimeError as e: log(f'카톡 알림 실패: {e}')


def used_urls():
    with conn() as db: return {r[0] for r in db.execute('SELECT url FROM cards')}


def auto_pick():
    """'알아서 골라 만들기': 네이버 뉴스에서 아직 안 만든 소비자 뉴스를 골라 끝까지 자동으로 (안 되면 다음 기사)"""
    urls = cards.find_news(config(), 1, used_urls())
    if not urls: return {'status': 'skip', 'reason': '네이버 뉴스에서 고를 기사를 찾지 못했어요. 설정에 네이버 키를 넣거나 링크를 직접 넣어 주세요.'}
    r = {}
    for url in urls[:3]:
        r = make(url)
        if r.get('status') == 'made' or r.get('status') == 'skip': break
    return r


NEWS = {'at': 0, 'items': []}


@app.route('/news')
def news():
    """첫 화면 오른쪽 '오늘의 소비자 뉴스' (네이버, 10분 동안 기억)"""
    c = config()
    if not (c['naver_id'] and c['naver_secret']): return jsonify(ok=False, items=[])
    if time.time() - NEWS['at'] > 600 or request.args.get('fresh'): NEWS.update(at=time.time(), items=cards.news_list(c))
    used = used_urls()
    if not NEWS['items']: NEWS['at'] = 0  # 못 찾았으면 다음에 다시 물어봄
    return jsonify(ok=True, error=cards.NAVER_ERR['msg'], items=[dict(it, made=it['url'] in used) for it in NEWS['items']])


def save_kakao(tok):
    c = config(); c['kakao_token'] = tok; save_config(c)


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
        f = request.form; pick = f.get('pick', '').strip()
        url = pick if pick.startswith(('http://', 'https://')) else f.get('url', '').strip()
        mode = f.get('mode') if f.get('mode') in MODES else ('auto' if config()['key'] else 'paste')
        # 기사 글을 붙여 넣었으면 그걸 쓰고(링크는 출처로만), 아니면 링크에서 읽어 옴
        art = cards.given_article(f.get('text', ''), f.get('title', ''), f.get('media', ''), f.get('date', ''), url) if f.get('text', '').strip() and not pick else None
        if not url and not art:  # 링크도 글도 없으면: 네이버 뉴스에서 오늘의 소비자 뉴스를 알아서 고름
            if mode == 'auto':
                if not background('네이버 뉴스에서 고른 기사', auto_pick): flash('다른 카드뉴스를 만들고 있어요. 다 되면 다시 눌러 주세요.')
                return redirect(url_for('job'))
            urls = cards.find_news(config(), 1, used_urls())
            if not urls: flash('네이버 뉴스에서 고를 기사를 찾지 못했어요. 설정에 네이버 키를 넣거나 링크를 직접 넣어 주세요.'); return redirect(url_for('home'))
            url = urls[0]
        if mode == 'auto':
            if app.config.get('TESTING'): return finish(make(url, art=art))
            if not background('새 카드뉴스', lambda: make(url, art=art)): flash('다른 카드뉴스를 만들고 있어요. 다 되면 다시 눌러 주세요.')
            return redirect(url_for('job'))
        got, why = cards.read(config(), url, art)  # 키 없는 방법: 기사 읽기·다른 기사 찾기(네이버 키가 있을 때)만
        if not got: flash(why); return redirect(url_for('home'))
        a, others, facts = got
        if mode == 'manual':
            d = cards.blank(a); cards.slots(d, config()['img_style']); cid = store({'data': d, 'facts': facts, 'checks': cards.run_checks(d, facts)}, 'manual')
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
    return render_template('home.html', rows=rows, cfg=cfg, logs=logs, naver=bool(cfg['naver_id'] and cfg['naver_secret']), out=str(OUT))


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
        if act == 'delete':
            with conn() as db: db.execute('DELETE FROM cards WHERE id=?', (cid,))
            flash('카드뉴스를 지웠어요.'); return redirect(url_for('home'))
        if act == 'upload':  # 힉스필드 사이트에서 만든 이미지 올리기 (비용 없음)
            slot = dict((n, x) for n, _, x in cards.slots(c['data'])).get(request.form.get('slot', ''))
            f = request.files.get('photo')
            if slot is None or not f: abort(400)
            try: save_photo(f.read(), slot, 'upload')
            except ValueError as e: flash(str(e)); return redirect(url_for('card', cid=cid))
            resave(cid, c['data'], c['facts'], c['confirmed']); flash('사진을 넣었어요.'); return redirect(url_for('card', cid=cid))
        if act == 'hf':
            name, style = request.form.get('slot', ''), request.form.get('style', '')
            if name not in [n for n, _, _ in cards.slots(c['data'])]: abort(400)
            def photo():
                cur = load(cid)
                if style in cards.STYLES: dict((n, x) for n, _, x in cards.slots(cur['data']))[name]['style'] = style  # 화면에서 막 고른 스타일로
                errs = hf_photos(cur['data'], [name])
                if errs: return {'status': 'error', 'reason': errs[0]}
                resave(cid, cur['data'], cur['facts'], cur['confirmed']); return {'status': 'made', 'id': cid}
            if app.config.get('TESTING'): return finish(photo())
            if not background('힉스필드 이미지 만들기', photo): flash('다른 작업을 하고 있어요. 다 되면 다시 눌러 주세요.')
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
        for (_, _, slot), ns in zip(cards.slots(d), newslots):  # 사진/일러스트 고르기만 (이미지 파일은 올리기·힉스필드로만 바뀜)
            if ns.get('style') in cards.STYLES: slot['style'] = ns['style']
        d['caption'] = s(new.get('caption'), 1500)
        d['hashtags'] = [re.sub(r'[#\s]', '', str(h))[:20] for h in (new.get('hashtags') or [])[:8] if re.sub(r'[#\s]', '', str(h))]
        src = new.get('source') or {}; d['source'].update(media=s(src.get('media'), 30), date=s(src.get('date'), 12))
        status = resave(cid, d, c['facts'], 1 if request.form.get('confirmed') else 0)
        flash('저장했어요.' + (' 체크리스트에 걸린 항목이 있어요.' if status == 'check' else ''))
        return redirect(url_for('card', cid=cid))
    sl = [(n, '표지' if n == 'cover' else f'{int(n[4:]) + 2}번째 장', x, {k: cards.photo_prompt(scene, k) for k in cards.STYLES})
          for n, scene, x in cards.slots(c['data'], config()['img_style'])]
    return render_template('edit.html', c=c, d=c['data'], caption=cards.caption_full(c['data']), slots=sl, hf=cards.hf_ready(config()),
                           key=bool(config()['key']), styles=cards.STYLES, saved=str(out_dir(c)) if out_dir(c).is_dir() else '')


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
        flash('카드뉴스를 만들었어요. 이미지는 아래 \'이미지 (힉스필드)\'에서 넣어 주세요.' + (f' (힉스필드: {errs[0]})' if errs else ''))
        return redirect(url_for('card', cid=cid))
    return render_template('paste.html', c=c, prompt=c['data']['prompt'])


OUT = DATA / '카드뉴스'  # 다 만든 카드뉴스 PNG·캡션 (카드뉴스마다 폴더 하나)


def out_dir(c):
    """카드뉴스 저장 폴더: 번호_표지 첫 줄 (윈도우 파일 이름에 못 쓰는 글자는 뺌)"""
    d = c['data']; cs = d.get('covers') or [{}]; head = cs[min(d.get('cover_pick', 0), len(cs) - 1)].get('line1') or c['title'] or '카드뉴스'
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '', head).strip(' .')[:40] or '카드뉴스'
    return OUT / f"{c['id']:03d}_{name}"


def open_in_explorer(path):
    if sys.platform.startswith('win'): os.startfile(str(path))  # noqa: 윈도우 탐색기로 열기
    elif sys.platform == 'darwin': os.system(f'open "{path}"')


@app.route('/card/<int:cid>/files', methods=['POST'])
def save_files(cid):
    """화면이 만든 PNG들 + 캡션 → 내 컴퓨터 폴더에 파일로 저장 (같은 카드뉴스는 같은 폴더에 덮어씀)"""
    c = load(cid)
    if c['data'].get('pending') or not (c['status'] == 'ready' or c['confirmed']): abort(400)
    pngs = request.files.getlist('png')
    if not pngs or len(pngs) > 12: abort(400)
    blobs = [f.read() for f in pngs]
    if any(not b.startswith(b'\x89PNG\r\n\x1a\n') for b in blobs): abort(400)
    folder = out_dir(c)
    for old in OUT.glob(f"{cid:03d}_*"):  # 표지 문구를 바꿨으면 예전 폴더 이름을 새 이름으로
        if old != folder and old.is_dir(): old.rename(folder) if not folder.exists() else None
    folder.mkdir(parents=True, exist_ok=True)
    for p in folder.glob('soboru-card-*.png'): p.unlink()
    for i, b in enumerate(blobs): (folder / f'soboru-card-{i + 1:02d}.png').write_bytes(b)
    (folder / 'caption.txt').write_text(request.form.get('caption', '')[:5000], encoding='utf-8-sig')  # 메모장에서 한글이 안 깨지게
    log(f'폴더에 저장 #{cid} ({len(blobs)}장)')
    return jsonify(folder=str(folder), count=len(blobs))


@app.route('/card/<int:cid>/open', methods=['POST'])
def open_folder(cid):
    folder = out_dir(load(cid))
    if folder.is_dir() and not app.config.get('TESTING'): open_in_explorer(folder)
    return ('', 204)


@app.route('/open', methods=['POST'])
def open_all():
    OUT.mkdir(parents=True, exist_ok=True)
    if not app.config.get('TESTING'): open_in_explorer(OUT)
    return redirect(url_for('home', skip=1))


@app.route('/kakao/login')
def kakao_login():
    c = config()
    if not c['kakao_key']: flash('카카오 REST API 키를 먼저 넣고 저장해 주세요.'); return redirect(url_for('settings'))
    session['kakao_state'] = secrets.token_urlsafe(16)
    return redirect(kakao.login_url(c, PORT, session['kakao_state']))


@app.route('/kakao/callback')
def kakao_callback():
    if request.args.get('error'): flash('카카오 로그인을 취소했어요.'); return redirect(url_for('settings'))
    if not request.args.get('state') or request.args.get('state') != session.pop('kakao_state', None): abort(400)
    c = config()
    try: c['kakao_token'] = kakao.exchange(c, request.args.get('code', ''), PORT)
    except RuntimeError as e: flash(str(e)); return redirect(url_for('settings'))
    save_config(c)
    try: kakao.send_note(c, save_kakao, '✅ 민주의 카드뉴스 제작 프로그램과 연결됐어요. 앞으로 카드뉴스를 이 채팅으로 보내 드릴게요.')
    except RuntimeError as e: flash(f'연결은 됐는데 시험 메시지를 못 보냈어요: {e}'); return redirect(url_for('settings'))
    flash('카카오톡을 연결했어요. 내 카톡(나와의 채팅)에 시험 메시지를 보냈어요.'); return redirect(url_for('settings'))


@app.route('/card/<int:cid>/kakao', methods=['POST'])
def kakao_card(cid):
    """카드뉴스를 내 카톡으로: 화면이 만든 표지 PNG(있으면) + 캡션"""
    c = load(cid); cfg = config()
    if c['data'].get('pending'): abort(400)
    if not kakao.ready(cfg): return jsonify(error="카카오톡이 아직 연결되지 않았어요. '설정'에서 연결해 주세요"), 400
    f = request.files.get('png'); png = f.read() if f else None
    if png and not png.startswith(b'\x89PNG\r\n\x1a\n'): abort(400)
    d = c['data']; cs = d.get('covers') or [{}]; cv = cs[min(d.get('cover_pick', 0), len(cs) - 1)]
    title = (cv.get('line1', '') + ' ' + cv.get('line2', '')).strip() or c['title']
    try: with_img = kakao.send_card(cfg, save_kakao, title, cards.caption_full(d), d.get('source', {}).get('url') or c['url'], png)
    except RuntimeError as e: return jsonify(error=str(e)), 400
    log(f'카톡으로 보냄 #{cid}')
    return jsonify(ok=True, image=with_img)


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
        if f.get('kakao_key', '').strip(): c['kakao_key'] = f.get('kakao_key').strip()
        if f.get('clear_kakao'): c['kakao_key'] = c['kakao_secret'] = ''; c['kakao_token'] = {}
        c['kakao_auto'] = 1 if f.get('kakao_auto') else 0
        c['img_style'] = f.get('img_style') if f.get('img_style') in dict(IMG_STYLES) else 'mix'
        c['hf_auto'] = 1 if f.get('hf_auto') else 0
        if c['key'] and not c['key'].startswith('sk-ant-'): flash("Claude API 키는 'sk-ant-'로 시작해요. 다시 확인해 주세요."); return redirect(url_for('settings'))
        c['model'] = f.get('model') if f.get('model') in dict(MODELS) else DEFAULTS['model']
        c['naver_kind'] = f.get('naver_kind') if f.get('naver_kind') in cards.NAVER else 'dev'
        c['auto'] = 1 if f.get('auto') else 0; c['web_search'] = 1 if f.get('web_search') else 0
        c['per_day'] = f.get('per_day', type=int) if f.get('per_day', type=int) in PER_DAY else 3
        c['hour'] = min(max(f.get('hour', type=int) or 8, 0), 23)
        save_config(c); flash('설정을 저장했어요.'); return redirect(url_for('settings'))
    mask = lambda v: (v[:7] + '…' + v[-4:]) if len(v) > 14 else ('있음' if v else '')
    return render_template('settings.html', cfg=c, masked={k: mask(c[k]) for k in SECRETS}, models=MODELS, per_day=PER_DAY, hf_models=cards.HF_MODELS, img_styles=IMG_STYLES,
                           env_key=bool(os.getenv('ANTHROPIC_API_KEY')), data_dir=str(DATA),
                           kakao_ok=kakao.ready(c), kakao_redirect=kakao.redirect_uri(PORT))


@app.route('/quit', methods=['POST'])
def quit_app():
    WIN['quit'] = True
    if not app.config.get('TESTING'): threading.Timer(1.2, lambda: os._exit(0)).start()  # '종료하는 중' 화면을 잠깐 보여 주고 끔
    return render_template('base.html', bye=True)


WIN = {'quit': False}


@app.route('/start')
def start():
    """켤 때 잠깐 보이는 첫 화면 (토스 포스처럼 로고 + 켜는 중)"""
    return render_template('start.html')


def running():
    """이미 켜져 있는지 (같은 칸을 누가 쓰고 있는지)"""
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', PORT)) == 0


def app_window(url):
    """브라우저 대신 프로그램 창으로 열기 (윈도우의 Edge WebView2). 창을 닫을 때까지 기다림. 못 열면 False."""
    try:
        import webview
        webview.settings['ALLOW_DOWNLOADS'] = True  # zip 내려받기
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True  # 기사·claude.ai·힉스필드 링크는 브라우저로
        w = webview.create_window(NAME, url + '/start', width=1320, height=820, min_size=(1000, 640), maximized=True, background_color='#F2F4F6')  # 토스 포스처럼 화면 가득
        def closing():  # 창의 ✕를 눌러도 바로 끄지 않고 토스처럼 '종료할까요?'를 물어봄
            if WIN['quit']: return True
            def ask():
                try: shown = w.evaluate_js("typeof cnQuit==='function'?(cnQuit(),1):0")
                except Exception: shown = 0
                if not shown: WIN['quit'] = True; w.destroy()
            threading.Thread(target=ask, daemon=True).start()
            return False
        w.events.closing += closing
        webview.start()
        return True
    except Exception as e:
        log(f'프로그램 창을 못 열어 브라우저로 열었어요 ({type(e).__name__})')
        return False


def desktop_shortcut():
    """처음 켤 때 한 번: 바탕화면에 바로가기 (윈도우 실행 파일일 때만)"""
    mark = DATA / 'shortcut-made-2'  # 아이콘·이름을 바꿔서(토스POS처럼) 한 번 더 만듦
    if not (FROZEN and sys.platform.startswith('win')) or mark.exists(): return
    if (Path(sys.executable).parent / 'unins000.exe').exists(): return  # 설치 프로그램으로 깔았으면 바로가기는 설치가 만듦
    exe = sys.executable.replace("'", "''")
    old = "$o=Join-Path $d '" + NAME + ".lnk';if(Test-Path $o){Remove-Item $o};"  # 예전 긴 이름 바로가기는 지움
    ps = ("$d=[Environment]::GetFolderPath('Desktop');" + old + "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d '" + SHORT + ".lnk'));"
          f"$s.TargetPath='{exe}';$s.WorkingDirectory=(Split-Path '{exe}');$s.IconLocation='{exe},0';$s.Save()")
    try:
        import subprocess
        subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps], timeout=20, creationflags=0x08000000)  # 창 안 띄움
        mark.write_text(cards.stamp())
    except Exception: pass


def main():
    url = f'http://127.0.0.1:{PORT}'
    if sys.stdout is None: sys.stdout = sys.stderr = open(os.devnull, 'w')  # 검은 창 없는 실행 파일: 출력할 곳이 없음
    if FROZEN:  # 실행 파일 안의 Python은 컴퓨터의 인증서 목록을 못 찾을 수 있어 기사 읽기용으로 함께 넣은 목록을 씀
        import certifi
        os.environ.setdefault('SSL_CERT_FILE', certifi.where())
    if '--check' in sys.argv:  # 빌드 확인용: 창 엔진을 불러올 수 있는지만 보고 끝
        import webview  # noqa: F401
        return
    browser = '--browser' in sys.argv
    if running():  # 이미 켜져 있으면 새로 켜지 않고 창(또는 브라우저)만 하나 더
        if browser or not app_window(url): webbrowser.open(url)
        return
    desktop_shortcut()
    threading.Thread(target=scheduler, daemon=True).start()
    print(f'\n  {NAME}을 켰어요 → {url}\n  끄려면 화면 위 [끄기]를 누르거나 창을 닫으세요.\n  데이터: {DATA}\n')
    if '--no-browser' in sys.argv: return app.run(host='127.0.0.1', port=PORT, debug=False, threaded=True)
    from werkzeug.serving import make_server
    srv = make_server('127.0.0.1', PORT, app, threaded=True)
    if browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start(); return srv.serve_forever()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if app_window(url): os._exit(0)  # 프로그램 창을 닫으면 끝
    webbrowser.open(url); srv_thread_wait()


def srv_thread_wait():
    """프로그램 창을 못 열어 브라우저로 열었을 때: '끄기'를 누를 때까지 켜 둠"""
    while True: time.sleep(3600)


if __name__ == '__main__':
    main()
