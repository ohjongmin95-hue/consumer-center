"""AI 사용량 기록: 기능별(AI 대화 제보, AI 상담, 제보 분류 등) OpenAI 호출 횟수와 토큰을 날마다 쌓아 관리자 화면에 보여 준다.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다.
- companydesk.post_json을 거치는 모든 OpenAI 호출을 기록한다 (따로 도는 글쓰기 프로세스도 같은 DB에 씀).
- 기능은 부른 파일 이름으로 정한다 (companydesk.AI_FEATURES).
- 기능별로 키를 나누려면 서버 설정에 OPENAI_API_KEY_<기능 이름 대문자>를 넣는다. 없으면 OPENAI_API_KEY를 쓴다.
  OpenAI에서 기능마다 프로젝트를 따로 만들고 그 프로젝트의 키를 넣으면, 금액도 OpenAI 화면에서 프로젝트별로 보인다.
"""
import datetime, os
from flask import render_template, request

SCHEMA = '''CREATE TABLE IF NOT EXISTS ai_usage(day TEXT NOT NULL, feature TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
  calls INTEGER NOT NULL DEFAULT 0, fails INTEGER NOT NULL DEFAULT 0, prompt INTEGER NOT NULL DEFAULT 0,
  cached INTEGER NOT NULL DEFAULT 0, completion INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(day, feature, model))'''


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
    with conn() as db: db.execute(SCHEMA)

    def record(feature, url, model, status, res):
        p, ca, c = tokens(res)
        ok = 200 <= int(status or 0) < 300
        with conn() as db:
            db.execute(SCHEMA)
            db.execute('''INSERT INTO ai_usage(day,feature,model,calls,fails,prompt,cached,completion) VALUES(?,?,?,?,?,?,?,?)
              ON CONFLICT(day,feature,model) DO UPDATE SET calls=calls+excluded.calls, fails=fails+excluded.fails,
              prompt=prompt+excluded.prompt, cached=cached+excluded.cached, completion=completion+excluded.completion''',
                       (datetime.date.today().isoformat(), feature, (model or '')[:60], 1, 0 if ok else 1, p, ca, c))

    desk.AI_USAGE.append(record)

    @app.route('/admin/ai-usage')
    @S.admin_only
    def admin_ai_usage():
        days = request.args.get('days', type=int) or 30
        days = days if days in (1, 7, 30, 90) else 30
        since = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
        with conn() as db:
            rows = [dict(r) for r in db.execute('''SELECT feature, model, SUM(calls) calls, SUM(fails) fails, SUM(prompt) prompt,
                SUM(cached) cached, SUM(completion) completion FROM ai_usage WHERE day>=? GROUP BY feature, model
                ORDER BY SUM(prompt)+SUM(completion) DESC, SUM(calls) DESC''', (since,))]
            daily = [dict(r) for r in db.execute('''SELECT day, SUM(calls) calls, SUM(prompt)+SUM(completion) tok FROM ai_usage
                WHERE day>=? GROUP BY day ORDER BY day''', (since,))]
        names = desk.AI_FEATURES
        for r in rows:
            r['name'] = names.get(r['feature'], '기타')
            r['own_key'] = bool(os.getenv('OPENAI_API_KEY_' + r['feature'].upper(), '').strip())
            r['per_call'] = round((r['prompt'] + r['completion']) / r['calls']) if r['calls'] else 0
        total = {k: sum(r[k] for r in rows) for k in ('calls', 'fails', 'prompt', 'cached', 'completion')}
        peak = max([d['tok'] for d in daily] or [0]) or 1
        keys = [(f, n, bool(os.getenv('OPENAI_API_KEY_' + f.upper(), '').strip())) for f, n in names.items()]
        return render_template('admin_ai_usage.html', rows=rows, total=total, daily=daily, peak=peak, days=days, keys=keys)
