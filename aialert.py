"""OpenAI 충전금·키 알림: 충전금이 바닥나거나(429 insufficient_quota) 키가 막히면(401) 관리자 화면 맨 위에 알림을 띄운다.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다.
- companydesk.post_json으로 가는 OpenAI 호출(생활정보 글·소보루 레터·법률 질문·AI 일러스트·제보 분류)을 모두 지켜본다.
- 글쓰기는 따로 도는 프로세스(soboru-writer 타이머)라서 상태는 DB(soboru_settings 'ai_alert')에 둔다.
- 충전한 뒤 OpenAI 호출이 한 번 성공하면 알림은 저절로 사라진다.
"""
import datetime, json

KEY = 'ai_alert'
WHERE = (('/chat/completions', 'AI 글쓰기·답변'), ('/images/', 'AI 일러스트'), ('/embeddings', '법령 검색'))


def kind_of(status, res):
    """OpenAI 응답 → 'quota'(충전금 없음) / 'key'(키 문제) / None"""
    err = (res or {}).get('error') or {} if isinstance(res, dict) else {}
    code = str(err.get('code') or err.get('type') or '')
    if status == 429 and ('insufficient_quota' in code or 'billing' in code): return 'quota'
    if status == 401 or code in ('invalid_api_key', 'account_deactivated'): return 'key'
    return None


def install(S):
    app = S.app; conn = S.conn; desk = S.companydesk

    def load():
        try:
            with conn() as db: row = db.execute('SELECT value FROM soboru_settings WHERE key=?', (KEY,)).fetchone()
            return json.loads(row[0]) if row else None
        except Exception: return None

    def save(value):
        with conn() as db:
            if value is None: db.execute('DELETE FROM soboru_settings WHERE key=?', (KEY,))
            else: db.execute('INSERT OR REPLACE INTO soboru_settings(key,value) VALUES(?,?)', (KEY, json.dumps(value, ensure_ascii=False)))

    def watch(url, status, res):
        if 'api.openai.com' not in url: return
        kind = kind_of(status, res)
        if kind:
            old = load() or {}
            where = next((name for part, name in WHERE if part in url), 'AI')
            save({'kind': kind, 'since': old.get('since') if old.get('kind') == kind else datetime.datetime.now().isoformat(timespec='minutes'),
                  'last': datetime.datetime.now().isoformat(timespec='minutes'), 'where': where})
        elif status == 200 and load(): save(None)  # 충전 뒤 첫 성공에서 알림 지움

    desk.AI_WATCH.append(watch)
    app.jinja_env.globals.update(ai_alert=lambda: load() if S.admin_active() else None)
    app.extensions['aialert'] = {'load': load, 'watch': watch}
