"""AI 사용량 기록: 기능별(AI 대화 제보, AI 상담, 제보 분류 등) OpenAI 호출 횟수와 토큰을 날마다 쌓아 관리자 화면에 보여 준다.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다.
- companydesk.post_json을 거치는 모든 OpenAI 호출을 기록한다 (따로 도는 글쓰기 프로세스도 같은 DB에 씀).
- 기능은 부른 파일 이름으로 정한다 (companydesk.AI_FEATURES).
- 기능별로 키를 나누려면 서버 설정에 OPENAI_API_KEY_<기능 이름 대문자>를 넣는다. 없으면 OPENAI_API_KEY를 쓴다.
  OpenAI에서 기능마다 프로젝트를 따로 만들고 그 프로젝트의 키를 넣으면, 금액도 OpenAI 화면에서 프로젝트별로 보인다.
"""
import datetime, os
from flask import render_template, request

# 100만 토큰당 달러 (입력, 캐시 입력, 출력). OpenAI 가격표 2026-10 (소보루CS platform_app/ai.py와 같은 값). 새 모델은 여기에 더함
PRICES = {'gpt-6-luna': (0.10, 0.01, 0.50), 'gpt-6.1-sol': (2.00, 0.10, 10.00), 'gpt-6-sol': (2.00, 0.10, 10.00),
          'gpt-4.1-mini': (0.40, 0.10, 1.60), 'gpt-4.1': (2.00, 0.50, 8.00), 'gpt-4o-mini': (0.15, 0.075, 0.60),
          'text-embedding-3-small': (0.02, 0.02, 0), 'text-embedding-3-large': (0.13, 0.13, 0),
          'gpt-image-1-mini': (2.00, 0.20, 8.00), 'gpt-image-1': (5.00, 1.25, 40.00)}
PER_MINUTE = {'gpt-4o-mini-transcribe': 0.003, 'gpt-4o-transcribe': 0.006, 'whisper-1': 0.006}  # 음성 받아쓰기: 1분당 달러
AUDIO_BYTES_PER_SEC = 4000  # 휴대폰 녹음(opus 약 32kbps) 크기로 길이를 어림


def usd_krw():
    try: return float(os.getenv('USD_KRW', '') or 1400)
    except ValueError: return 1400.0


def cost_usd(model, prompt, cached, completion, audio_sec=0):
    """그 모델 가격표로 계산한 달러. 가격을 모르는 모델은 None"""
    if model in PER_MINUTE: return audio_sec / 60 * PER_MINUTE[model]
    p = PRICES.get(model) or next((v for k, v in PRICES.items() if model.startswith(k)), None)
    if not p: return None
    return ((prompt - cached) * p[0] + cached * p[1] + completion * p[2]) / 1e6

SCHEMA = '''CREATE TABLE IF NOT EXISTS ai_usage(day TEXT NOT NULL, feature TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
  calls INTEGER NOT NULL DEFAULT 0, fails INTEGER NOT NULL DEFAULT 0, prompt INTEGER NOT NULL DEFAULT 0,
  cached INTEGER NOT NULL DEFAULT 0, completion INTEGER NOT NULL DEFAULT 0, audio_sec INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(day, feature, model))'''


def tokens(res):
    """OpenAI 응답의 usage → (입력, 그중 캐시, 출력)"""
    u = (res or {}).get('usage') if isinstance(res, dict) else None
    if not isinstance(u, dict): return 0, 0, 0
    p = u.get('prompt_tokens', u.get('input_tokens', 0)) or 0
    c = u.get('completion_tokens', u.get('output_tokens', 0)) or 0
    d = u.get('prompt_tokens_details') or u.get('input_tokens_details') or {}
    return int(p), int((d or {}).get('cached_tokens', 0) or 0), int(c)


def install(S):
    app, conn, desk = S.app, S.conn, S.companydesk
    def ensure(db):
        db.execute(SCHEMA)
        if 'audio_sec' not in {r[1] for r in db.execute('PRAGMA table_info(ai_usage)')}:
            db.execute('ALTER TABLE ai_usage ADD COLUMN audio_sec INTEGER NOT NULL DEFAULT 0')
    with conn() as db: ensure(db)

    def record(feature, url, model, status, res):
        p, ca, c = tokens(res)
        ok = 200 <= int(status or 0) < 300
        sec = round((res or {}).get('audio_bytes', 0) / AUDIO_BYTES_PER_SEC) if isinstance(res, dict) and ok else 0
        with conn() as db:
            ensure(db)
            db.execute('''INSERT INTO ai_usage(day,feature,model,calls,fails,prompt,cached,completion,audio_sec) VALUES(?,?,?,?,?,?,?,?,?)
              ON CONFLICT(day,feature,model) DO UPDATE SET calls=calls+excluded.calls, fails=fails+excluded.fails,
              prompt=prompt+excluded.prompt, cached=cached+excluded.cached, completion=completion+excluded.completion, audio_sec=audio_sec+excluded.audio_sec''',
                       (datetime.date.today().isoformat(), feature, (model or '')[:60], 1, 0 if ok else 1, p, ca, c, sec))

    desk.AI_USAGE.append(record)

    @app.route('/admin/ai-usage')
    @S.admin_only
    def admin_ai_usage():
        days = request.args.get('days', type=int) or 30
        days = days if days in (1, 7, 30, 90) else 30
        since = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
        with conn() as db:
            ensure(db)
            rows = [dict(r) for r in db.execute('''SELECT feature, model, SUM(calls) calls, SUM(fails) fails, SUM(prompt) prompt,
                SUM(cached) cached, SUM(completion) completion, SUM(audio_sec) audio_sec FROM ai_usage WHERE day>=? GROUP BY feature, model''', (since,))]
            raw = [dict(r) for r in db.execute('SELECT * FROM ai_usage WHERE day>=?', (since,))]
        rate = usd_krw()
        for r in rows: r['usd'] = cost_usd(r['model'], r['prompt'], r['cached'], r['completion'], r['audio_sec'])
        rows.sort(key=lambda r: (-(r['usd'] or 0), -r['calls']))
        by_day = {}
        for r in raw:
            d = by_day.setdefault(r['day'], {'day': r['day'], 'calls': 0, 'usd': 0.0})
            d['calls'] += r['calls']; d['usd'] += cost_usd(r['model'], r['prompt'], r['cached'], r['completion'], r['audio_sec']) or 0
        daily = sorted(by_day.values(), key=lambda d: d['day'])
        today = by_day.get(datetime.date.today().isoformat(), {'usd': 0.0, 'calls': 0})
        names = desk.AI_FEATURES
        for r in rows:
            r['name'] = names.get(r['feature'], '기타')
            r['own_key'] = bool(os.getenv('OPENAI_API_KEY_' + r['feature'].upper(), '').strip())
            r['per_call'] = round((r['prompt'] + r['completion']) / r['calls']) if r['calls'] else 0
        total = {k: sum(r[k] for r in rows) for k in ('calls', 'fails', 'prompt', 'cached', 'completion')}
        total['usd'] = sum(r['usd'] or 0 for r in rows); total['unknown'] = [r['model'] for r in rows if r['usd'] is None]
        peak = max([d['usd'] for d in daily] or [0]) or 1
        keys = [(f, n, bool(os.getenv('OPENAI_API_KEY_' + f.upper(), '').strip())) for f, n in names.items()]
        return render_template('admin_ai_usage.html', rows=rows, total=total, daily=daily, peak=peak, days=days, keys=keys, rate=rate, today=today,
                               now=datetime.datetime.now().strftime('%H:%M:%S'))
