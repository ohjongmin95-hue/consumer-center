"""대화로 제보하기 (/report/talk).

운영자 2026-11-03: 휴대폰으로 긴 글을 치기 어려우니, 제보하기부터 AI와 대화하며 버튼을 톡톡 눌러 쓰게.
- 무슨 일인지 말하듯 적거나(마이크) 사진을 올리면 AI(GPT-6 Luna)가 업종·유형·업체·제목·내용·원하는 해결을 채우고,
  모자란 것만 버튼 달린 짧은 질문으로 다시 물음. "이런 제보시군요, 맞나요?"로 확인받음.
- 지역·성별·연령대·공개 여부는 버튼으로. 이름·전화번호는 로그인 정보로 채움.
- 접수는 기존 양식과 똑같이 POST /report 로 보냄 (검증·동의·첨부·알림을 그대로 씀). 이 모듈은 초안만 만듦.
- AI가 안 되면(키 없음·오류) 화면은 적은 글을 그대로 내용 칸에 넣고 나머지를 버튼으로 묻는 식으로 이어감.
"""
import base64
import datetime
import json
import os
import re

from flask import abort, g, jsonify, render_template, request

MODEL = 'gpt-6-luna'  # 매거진·소보루CS와 같은 루나 (싸고 빠름). REPORT_TALK_MODEL로 바꿀 수 있음
PER_HOUR = 40  # 한 사람(IP)이 1시간에 부르는 AI 횟수 (한 제보에 보통 2~4번)
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 1_500_000  # 화면에서 1024px JPEG로 줄여 보내므로 넉넉함
MAX_STORY = 2000
MAX_QA = 8
IMAGE_TYPES = {b'\xff\xd8\xff': 'image/jpeg', b'\x89PNG': 'image/png', b'RIFF': 'image/webp'}

SYSTEM = """너는 소비자 피해 제보 사이트 {site}의 접수 도우미다. 소비자가 말하듯 적은 글(받아쓰기라 맞춤법이 틀릴 수 있음)과 사진, 앞서 주고받은 질문·답을 보고 제보서 초안을 만든다.
반드시 아래 JSON 하나만 답한다.
{{"summary": "확인 질문 한 문장. 예: 'OO에서 산 운동화 환불을 거절당한 일로 제보하시는 거죠?'",
 "industry": "업종 목록 중 하나(모르면 빈 문자열)", "category": "유형 목록 중 하나(모르면 빈 문자열)",
 "company": "업체·서비스 이름(모르면 빈 문자열)", "occurred_on": "YYYY-MM-DD(글에 날짜가 있을 때만, 아니면 빈 문자열)",
 "subject": "제목 한 줄, 40자 안", "description": "피해 내용. 제보자 1인칭 존댓말(~했어요), 있었던 일을 시간 순서로 4~8문장, 금액·날짜·주고받은 말 등 사실 위주. 지어내지 말 것",
 "request_text": "원하는 해결 한두 문장(글에 없으면 상황에 맞게 짐작)", "request_options": ["원하는 해결 후보 2~4개, 각 8자 안. 예: 전액 환불, 교환, 수리, 사과"],
 "questions": [{{"q": "짧은 질문", "options": ["버튼 2~4개, 각 12자 안"]}}]}}
규칙:
- questions는 제보에 꼭 필요한데 모르는 것만, 최대 2개. 1순위 업체 이름, 2순위 무슨 일이 있었는지 핵심(무엇을·언제·얼마), 3순위 업체에 이미 연락해 봤는지. 이미 답한 것은 다시 묻지 않는다. 충분하면 빈 배열.
- 업체 이름을 묻는 질문의 options는 빈 배열로 둔다(직접 입력). 다른 질문은 고르기 쉬운 버튼을 준다.
- 사진 속 이름·전화번호·주소·주문번호·카드번호 같은 개인정보는 옮겨 적지 않는다.
- 욕설·비방은 사실만 남기고 차분한 말로 바꾼다. 업체를 '사기꾼'처럼 단정하지 않는다.
업종 목록: {industries}
유형 목록: {categories}"""


def install(S):
    app, conn, desk = S.app, S.conn, S.companydesk

    with conn() as db:
        db.execute('CREATE TABLE IF NOT EXISTS report_talk_hits(id INTEGER PRIMARY KEY,ip_hash TEXT NOT NULL,created TEXT NOT NULL)')

    def ai_key(): return os.getenv('OPENAI_API_KEY', '').strip()

    @app.route('/report/talk')
    def report_talk():
        me = g.get('user')
        return render_template('report_talk.html', categories=S.report_categories(), industries=S.report_industries(), sido=S.SIDO, genders=S.GENDERS,
                               ages=S.AGE_GROUPS, intake_enabled=os.getenv('ENABLE_INTAKE') == '1', max_files=S.MAX_FILES, today=datetime.date.today().isoformat(),
                               ai_on=bool(ai_key()), me=me)

    def read_images():
        out = []
        for f in request.files.getlist('photo')[:MAX_IMAGES]:
            data = f.read(MAX_IMAGE_BYTES + 1)
            if not data or len(data) > MAX_IMAGE_BYTES: continue
            kind = next((t for sig, t in IMAGE_TYPES.items() if data.startswith(sig)), None)
            if kind: out.append('data:%s;base64,%s' % (kind, base64.b64encode(data).decode()))
        return out

    def pick(value, options):
        value = str(value or '').strip()
        if value in options: return value
        return next((o for o in options if value and (value in o or o in value)), '')

    def clean(out):
        if not isinstance(out, dict): raise ValueError
        s = lambda v, n: desk.scrub(' '.join(str(v or '').split()))[:n]
        industries, categories = S.report_industries(), S.report_categories()
        day = str(out.get('occurred_on') or '')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day) or day > datetime.date.today().isoformat(): day = ''
        qs = []
        for q in out.get('questions') or []:
            if isinstance(q, dict) and str(q.get('q') or '').strip():
                qs.append({'q': s(q['q'], 80), 'options': [s(o, 20) for o in (q.get('options') or []) if str(o).strip()][:4]})
        desc = desk.scrub(str(out.get('description') or '').strip())[:3000]
        return {'summary': s(out.get('summary'), 160), 'industry': pick(out.get('industry'), industries), 'category': pick(out.get('category'), categories),
                'company': s(out.get('company'), 60), 'occurred_on': day, 'subject': s(out.get('subject'), 80), 'description': desc,
                'request_text': s(out.get('request_text'), 300), 'request_options': [s(o, 16) for o in (out.get('request_options') or []) if str(o).strip()][:4],
                'questions': qs[:2]}

    def ask(story, qa, images):
        key = ai_key()
        if not key: raise RuntimeError('no key')
        model = os.getenv('REPORT_TALK_MODEL', '').strip() or MODEL
        system = SYSTEM.format(site=S.notify.site_name(), industries=', '.join(S.report_industries()), categories=', '.join(S.report_categories()))
        text = '[제보자가 적은 글]\n' + desk.scrub(story) + ''.join('\n\n[질문] %s\n[답] %s' % (desk.scrub(x['q']), desk.scrub(x['a'])) for x in qa)
        text += '\n\n[오늘] ' + datetime.date.today().isoformat()
        def call(with_images):
            content = [{'type': 'text', 'text': text}] + ([{'type': 'image_url', 'image_url': {'url': u, 'detail': 'low'}} for u in images] if with_images else [])
            opts = {'max_completion_tokens': 2500, 'reasoning_effort': 'low'} if re.match(r'(gpt-([5-9]|\d\d)|o\d)', model) else {'max_tokens': 1200, 'temperature': 0.3}
            body = {'model': model, 'response_format': {'type': 'json_object'}, **opts,
                    'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}]}
            return desk.post_json('https://api.openai.com/v1/chat/completions', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, 45)
        st, res = call(bool(images))
        if st != 200 and images: st, res = call(False)  # 사진을 못 받는 모델이면 글만으로 다시
        if st != 200: raise RuntimeError('AI %s' % st)
        return clean(json.loads(res['choices'][0]['message']['content']))

    @app.route('/report/talk/ai', methods=['POST'])
    def report_talk_ai():
        if request.form.get('website'): abort(400)
        story = ' '.join((request.form.get('story') or '').split())[:MAX_STORY]
        try: qa = [{'q': str(x.get('q', ''))[:120], 'a': str(x.get('a', ''))[:400]} for x in json.loads(request.form.get('qa') or '[]')[:MAX_QA] if isinstance(x, dict)]
        except ValueError: qa = []
        images = read_images()
        if len(story) < 2 and not images: return jsonify(ok=False, error='empty'), 400
        with conn() as db:
            if S.recent_count(db, 'report_talk_hits', 60) >= PER_HOUR: return jsonify(ok=False, error='limit'), 429
            db.execute('DELETE FROM report_talk_hits WHERE created<?', ((datetime.datetime.now() - datetime.timedelta(days=1)).isoformat(timespec='seconds'),))
            db.execute('INSERT INTO report_talk_hits(ip_hash,created) VALUES(?,?)', (S.ip_hash(), datetime.datetime.now().isoformat(timespec='seconds')))
        try: draft = ask(story, qa, images)
        except Exception as e:  # 키 없음·오류·형식 이상: 화면이 버튼으로 이어 감
            app.logger.warning('report talk AI failed: %s', str(e)[:120])
            return jsonify(ok=False, error='ai')
        return jsonify(ok=True, draft=draft)
