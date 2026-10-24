"""소보루 카드뉴스 만들기 화면 (내 컴퓨터에서만 열림: http://127.0.0.1:5050).

실행: 시작하기.command(맥) / 시작하기.bat(윈도우), 또는 python server.py
- 데이터는 이 폴더의 data/ 안에만 둔다: cards.sqlite3(만든 카드뉴스), config.json(API 키·설정), secret.key(화면 보호용 비밀키).
- 켜져 있는 동안 매일 아침 8시(설정에서 바꿈)가 지나면 소비자 뉴스로 초안을 만든다. 꺼져 있던 날은 다음에 켤 때 한 번 만든다.
- 만드는 일은 cards.py. 이 파일은 화면·저장·예약만.
"""
import datetime, json, os, re, secrets, sqlite3, sys, threading, time, webbrowser
from pathlib import Path
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
import cards

HERE = Path(__file__).resolve().parent
DATA = Path(os.getenv('CARDNEWS_DATA') or HERE / 'data')
PORT = int(os.getenv('CARDNEWS_PORT') or 5050)
PER_DAY = (1, 2, 3, 4, 5)
MODELS = (('claude-opus-5-5', 'Claude Opus 5.5 (기본, 가장 꼼꼼)'), ('claude-sonnet-5-5', 'Claude Sonnet 5.5 (더 싸고 빠름)'))
DEFAULTS = {'key': '', 'model': 'claude-opus-5-5', 'art': 'claude', 'auto': 0, 'per_day': 3, 'hour': 8, 'web_search': 1,
            'naver_kind': 'dev', 'naver_id': '', 'naver_secret': ''}
SECRETS = ('key', 'naver_secret')  # 화면에 다시 보여 주지 않는 값

DATA.mkdir(parents=True, exist_ok=True)
app = Flask(__name__)
key_file = DATA / 'secret.key'
if not key_file.exists(): key_file.write_text(secrets.token_hex(32))
app.secret_key = key_file.read_text().strip()
app.config.update(SESSION_COOKIE_SAMESITE='Strict', MAX_CONTENT_LENGTH=4 * 1024 * 1024)


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
def store(r, trigger):
    with conn() as db:
        return db.execute('INSERT INTO cards(url,title,status,data,facts,checks,trigger,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                          (r['facts']['url'], r['facts']['title'], cards.status_of(r['checks']), json.dumps(r['data'], ensure_ascii=False),
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


def make(url, trigger='manual'):
    r = cards.make(config(), url)
    if r['status'] != 'made': log(f"{'자동 · ' if trigger == 'daily' else ''}못 만듦: {r['reason']} ({url[:80]})"); return r
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
        url = request.form.get('url', '')
        if app.config.get('TESTING'): return finish(make(url))
        if not background('새 카드뉴스', lambda: make(url)): flash('다른 카드뉴스를 만들고 있어요. 다 되면 다시 눌러 주세요.')
        return redirect(url_for('job'))
    with conn() as db:
        rows = [dict(r) for r in db.execute('SELECT id,url,title,status,trigger,created,data FROM cards ORDER BY id DESC LIMIT 100')]
        logs = [dict(r) for r in db.execute('SELECT at,what FROM log ORDER BY id DESC LIMIT 8')]
    for r in rows:
        d = json.loads(r.pop('data')); cs = d.get('covers') or [{}]; c = cs[min(d.get('cover_pick', 0), len(cs) - 1)]
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
    if request.method == 'POST':
        act = request.form.get('act', 'save')
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
        d['caption'] = s(new.get('caption'), 1500)
        d['hashtags'] = [re.sub(r'[#\s]', '', str(h))[:20] for h in (new.get('hashtags') or [])[:8] if re.sub(r'[#\s]', '', str(h))]
        src = new.get('source') or {}; d['source'].update(media=s(src.get('media'), 30), date=s(src.get('date'), 12))
        status = resave(cid, d, c['facts'], 1 if request.form.get('confirmed') else 0)
        flash('저장했어요.' + (' 체크리스트에 걸린 항목이 있어요.' if status == 'check' else ''))
        return redirect(url_for('card', cid=cid))
    return render_template('edit.html', c=c, d=c['data'], caption=cards.caption_full(c['data']))


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    c = config()
    if request.method == 'POST':
        f = request.form
        for k in SECRETS + ('naver_id',):
            v = f.get(k, '').strip()
            if v or f.get('clear_' + k): c[k] = '' if f.get('clear_' + k) else v  # 비워 두면 그대로, '지우기'를 고르면 지움
        if f.get('clear_naver_id'): c['naver_secret'] = ''
        if c['key'] and not c['key'].startswith('sk-ant-'): flash("Claude API 키는 'sk-ant-'로 시작해요. 다시 확인해 주세요."); return redirect(url_for('settings'))
        c['model'] = f.get('model') if f.get('model') in dict(MODELS) else DEFAULTS['model']
        c['art'] = f.get('art') if f.get('art') in cards.ARTISTS else 'claude'
        c['naver_kind'] = f.get('naver_kind') if f.get('naver_kind') in cards.NAVER else 'dev'
        c['auto'] = 1 if f.get('auto') else 0; c['web_search'] = 1 if f.get('web_search') else 0
        c['per_day'] = f.get('per_day', type=int) if f.get('per_day', type=int) in PER_DAY else 3
        c['hour'] = min(max(f.get('hour', type=int) or 8, 0), 23)
        save_config(c); flash('설정을 저장했어요.'); return redirect(url_for('settings'))
    mask = lambda v: (v[:7] + '…' + v[-4:]) if len(v) > 14 else ('있음' if v else '')
    return render_template('settings.html', cfg=c, masked={k: mask(c[k]) for k in SECRETS}, models=MODELS, artists=list(cards.ARTISTS), per_day=PER_DAY,
                           env_key=bool(os.getenv('ANTHROPIC_API_KEY')))


if __name__ == '__main__':
    threading.Thread(target=scheduler, daemon=True).start()
    print(f'\n  소보루 카드뉴스 만들기를 켰어요 → http://127.0.0.1:{PORT}\n  끄려면 이 창에서 Ctrl+C 를 누르거나 창을 닫으세요.\n')
    if '--no-browser' not in sys.argv: threading.Timer(1.2, lambda: webbrowser.open(f'http://127.0.0.1:{PORT}')).start()
    app.run(host='127.0.0.1', port=PORT, debug=False, threaded=True)
