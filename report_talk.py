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
import secrets
import urllib.error
import urllib.request

import company_fix
from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for

MODEL = 'gpt-6-luna'  # 매거진·소보루CS와 같은 루나 (싸고 빠름). REPORT_TALK_MODEL로 바꿀 수 있음
PER_HOUR = 40  # 한 사람(IP)이 1시간에 부르는 AI 횟수 (한 제보에 보통 2~4번)
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 1_500_000  # 화면에서 1024px JPEG로 줄여 보내므로 넉넉함
MAX_STORY = 2000
MAX_QA = 8
STT_MODEL = 'gpt-4o-mini-transcribe'  # 말로 입력: 휴대폰 브라우저 받아쓰기는 네이버 앱 등에서 안 돼서 녹음 파일을 서버에서 글로 바꿈. REPORT_STT_MODEL로 바꿀 수 있음
MAX_AUDIO = 8_000_000
AUDIO_EXT = ('webm', 'mp4', 'm4a', 'ogg', 'wav', 'mp3', 'aac')
KNOWN = {'company': '업체', 'occurred_on': '발생일', 'industry': '업종', 'category': '유형', 'request_text': '원하는 해결', 'description': '앞서 쓴 본문'}
IMAGE_TYPES = {b'\xff\xd8\xff': 'image/jpeg', b'\x89PNG': 'image/png', b'RIFF': 'image/webp'}

SYSTEM = """너는 소비자 피해 제보 사이트 {site}의 접수 도우미다. 소비자가 말하듯 적은 글(받아쓰기라 맞춤법이 틀릴 수 있음)과 사진, 앞서 주고받은 질문·답을 보고 제보서 초안을 만든다.
반드시 아래 JSON 하나만 답한다.
{{"summary": "확인 질문 한 문장. 예: 'OO에서 산 운동화 환불을 거절당한 일로 제보하시는 거죠?'",
 "industry": "업종 목록 중 하나(모르면 빈 문자열)", "category": "유형 목록 중 하나(모르면 빈 문자열)",
 "company": "업체·서비스 이름(모르면 빈 문자열)", "occurred_on": "YYYY-MM-DD(글에 날짜가 있을 때만, 아니면 빈 문자열)",
 "subject": "제목 한 줄, 40자 안. 소비자가 게시판에 직접 쓴 글 제목처럼 자연스러운 해요체. 업체와 무슨 일인지가 드러나게. 예: '쿠팡에서 주문한 운동화가 2주째 안 와요'", "description": "게시글 본문. 제보자가 커뮤니티에 자기 일을 털어놓듯 1인칭 해요체로, 겪은 순서대로 4~8문장. 어디서·언제·무엇을 얼마에·무슨 일이·업체는 뭐라고 했는지가 모두 자연스럽게 들어가게. 사진에서 읽은 사실(상품명·금액·날짜·파손 모습)도 넣을 것. 지어내지 말 것",
 "issues": ["사진·글에서 드러난 문제를 짧게 1~4개, 각 30자 안. 예: '주문 2주째 배송 안 됨', '환불 요청 3번 거절'"],
 "request_text": "원하는 해결 한두 문장(글에 없으면 상황에 맞게 짐작)", "request_options": ["원하는 해결 후보 2~4개, 각 8자 안. 예: 전액 환불, 교환, 수리, 사과"],
 "questions": [{{"q": "짧은 질문", "options": ["버튼 2~4개, 각 12자 안"]}}]}}
규칙:
- 제보 글에는 다섯 가지가 꼭 들어가야 한다 (운영자 2026-11-03, 제보하기 화면의 '이렇게 말하면 정확해요'와 같음): ① 어디서(업체·서비스 이름) ② 언제(산 날, 일이 생긴 날) ③ 무엇을 얼마에(상품과 금액) ④ 무슨 일이(겪은 일을 순서대로) ⑤ 업체는(연락했을 때 업체가 한 말). 글·사진·지난 답에서 이 다섯 가지를 먼저 찾아 채운다.
- questions는 다섯 가지 중 아직 모르는 것만, 위 순서대로 최대 2개 묻는다. 이미 답한 것은 다시 묻지 않는다. 다섯 가지가 다 있으면 빈 배열. 금액·날짜처럼 제보자가 정말 모를 수 있는 것은 '기억 안 나요' 버튼을 준다.
- 받아쓰기처럼 제보자 글을 그대로 옮기지 않는다. 맞춤법·띄어쓰기를 고치고 같은 말 반복은 줄이되, 말투는 딱딱하게 다듬지 않는다. 질문·답에서 알게 된 사실을 모두 넣고, 없는 사실은 지어내지 않는다.
- 제목과 본문은 일반 소비자가 커뮤니티 게시판에 직접 올린 글처럼 쓴다 (운영자 2026-11-03: '정리는 잘하는데 딱딱해'). 편하게 말하듯 쓴 해요체 문장으로, '~했는데요', '~더라고요', '~하네요', '진짜 답답해요' 같은 말이 자연스럽게 섞여도 좋다. 짧은 문장과 긴 문장을 섞고, 겪은 순서대로 이야기한다. 예: '지난달 20일에 소보루몰에서 운동화를 89,000원 주고 샀어요. 받아 보니 밑창이 떨어져 있더라고요. 고객센터에 사진까지 보냈는데 착용 흔적이 있어서 환불이 안 된대요. 한 번도 안 신었는데 너무 황당하네요.'
- 머리말·소제목·번호·글머리표·'요약하면', '정리하면', '다음과 같아요', '해당 업체', '상기', '본인은', '~한 상황입니다' 같은 보고서·민원서 말투는 쓰지 않는다. 항목을 나열하지 말고 이어지는 이야기 한 문단(길면 두 문단)으로 쓴다. 반말·비속어만 빼고 제보자 표현과 느낌은 살린다.
- 글이 짧으면(예: '배송이 안 와', '환불 안 해줌') 초안을 억지로 채우지 말고 꼭 되묻는다. 예: 배송 문제면 '어디서 무엇을 주문하셨어요?'(업체), '주문한 지 얼마나 됐어요?'(options: 3일 안, 1주일쯤, 2주 넘게, 한 달 넘게), '업체에 연락해 보셨어요?'(options: 연락 안 됨, 기다리래요, 아직 안 해봤어요).
- 업체 이름을 묻는 질문의 options는 빈 배열로 둔다(직접 입력). 다른 질문은 고르기 쉬운 버튼을 준다.
- 사진 속 이름·전화번호·주소·주문번호·카드번호 같은 개인정보는 옮겨 적지 않는다.
- 문장은 해요체·능동형으로 쓴다. '~습니다', '되어요'(→ 돼요), 명사만 늘어놓는 말('환불 거부 발생')은 쓰지 않는다. summary와 questions는 '~시겠어요?' 같은 과한 경어 없이 짧게 묻는다(예: '언제 주문했어요?'). 단 '어떤 일을 겪으셨나요?'처럼 제보자 상황을 묻는 말은 경어를 써도 된다.
- 욕설·비방은 사실만 남기고 차분한 말로 바꾼다. 업체를 '사기꾼'처럼 단정하지 않는다.
업종 목록: {industries}
유형 목록: {categories}"""


def install(S):
    app, conn, desk = S.app, S.conn, S.companydesk

    with conn() as db:
        db.execute('CREATE TABLE IF NOT EXISTS report_talk_hits(id INTEGER PRIMARY KEY,ip_hash TEXT NOT NULL,created TEXT NOT NULL)')

    def ai_key(): return desk.ai_key_for('report_talk')

    @app.route('/report/talk')
    def report_talk():
        if S.report_login_needed():
            return redirect(url_for('login', next=request.full_path.rstrip('?')))
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
                'company': company_fix.fix(s(out.get('company'), 60)), 'occurred_on': day, 'subject': s(out.get('subject'), 80), 'description': desc,
                'request_text': s(out.get('request_text'), 300), 'request_options': [s(o, 16) for o in (out.get('request_options') or []) if str(o).strip()][:4],
                'issues': [s(x, 40) for x in (out.get('issues') or []) if str(x).strip()][:4],
                'questions': qs[:2]}

    def parse(text):
        """JSON만 꺼냄 (```json 감싸기·앞뒤 말이 붙어도)."""
        text = (text or '').strip()
        a, b = text.find('{'), text.rfind('}')
        return json.loads(text[a:b + 1] if a > -1 and b > a else text)

    def ask(story, qa, images, known=None):
        key = ai_key()
        if not key: raise RuntimeError('no key')
        model = os.getenv('REPORT_TALK_MODEL', '').strip() or MODEL
        system = SYSTEM.format(site=S.notify.site_name(), industries=', '.join(S.report_industries()), categories=', '.join(S.report_categories()))
        text = '[제보자가 적은 글]\n' + desk.scrub(story)
        if known:  # 운영자 2026-11-03: 지난 답에서 정리된 정보 (사진에서 읽은 사실 포함) + 최근 대화만 → 입력 토큰 절약
            text += '\n\n[지금까지 정리된 정보]\n' + '\n'.join('%s: %s' % (KNOWN[k], desk.scrub(str(v))) for k, v in known.items() if v)
        text += ''.join('\n\n[질문] %s\n[답] %s' % (desk.scrub(x['q']), desk.scrub(x['a'])) for x in qa)
        text += '\n\n[오늘] ' + datetime.date.today().isoformat()
        def call(with_images, model, as_json):
            content = [{'type': 'text', 'text': text}] + ([{'type': 'image_url', 'image_url': {'url': u, 'detail': 'low'}} for u in images] if with_images else [])
            opts = {'max_completion_tokens': 2500, 'reasoning_effort': 'low'} if re.match(r'(gpt-([5-9]|\d\d)|o\d)', model) else {'max_tokens': 1200, 'temperature': 0.3}
            body = {'model': model, **({'response_format': {'type': 'json_object'}} if as_json else {}), **opts,
                    'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}]}
            return desk.post_json('https://api.openai.com/v1/chat/completions', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, 45)
        # 운영자 2026-11-03: 실제 사이트에서 AI가 실패해 받아쓰기 그대로 나옴 → 한 번 실패해도 다른 방법으로 다시
        tries = [(model, bool(images), True)]
        if images: tries.append((model, False, True))
        tries += [(model, False, False), (desk.ai_model(), False, True)]
        last = ''
        for m, with_images, as_json in tries:
            st, res = call(with_images, m, as_json)
            if st == 200:
                try: return clean(parse(res['choices'][0]['message']['content']))
                except Exception as e: last = 'parse %s' % str(e)[:60]; continue
            last = '%s %s %s' % (m, st, str((res or {}).get('error', {}).get('message', '') if isinstance(res, dict) else '')[:120])
            app.logger.warning('report talk AI try failed: %s', last)
        raise RuntimeError('AI ' + last)

    @app.route('/report/talk/stt', methods=['POST'])
    def report_talk_stt():
        """마이크로 녹음한 말을 글로 바꿈 (운영자 2026-11-03: 네이버 앱에서 음성 입력이 안 됨)."""
        if S.report_login_needed(): return jsonify(ok=False, error='login'), 403
        f = request.files.get('audio')
        if not f: return jsonify(ok=False, error='empty'), 400
        data = f.read(MAX_AUDIO + 1)
        if len(data) > MAX_AUDIO: return jsonify(ok=False, error='big'), 413
        if len(data) < 800: return jsonify(ok=False, error='short'), 400
        key = ai_key()
        if not key: return jsonify(ok=False, error='ai')
        with conn() as db:
            if S.recent_count(db, 'report_talk_hits', 60) >= PER_HOUR: return jsonify(ok=False, error='limit'), 429
            db.execute('INSERT INTO report_talk_hits(ip_hash,created) VALUES(?,?)', (S.ip_hash(), datetime.datetime.now().isoformat(timespec='seconds')))
        ext = (f.filename or '').rsplit('.', 1)[-1].lower()
        if ext not in AUDIO_EXT: ext = 'webm'
        model = os.getenv('REPORT_STT_MODEL', '').strip() or STT_MODEL
        b = '----sb' + secrets.token_hex(12)
        parts = []
        for k, v in (('model', model), ('language', 'ko'), ('response_format', 'json'), ('prompt', '소비자 피해 제보. 업체 이름, 날짜, 금액, 환불, 배송, 교환, 고객센터.')):
            parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (b, k, v)).encode())
        parts.append(('--%s\r\nContent-Disposition: form-data; name="file"; filename="voice.%s"\r\nContent-Type: application/octet-stream\r\n\r\n' % (b, ext)).encode() + data + b'\r\n')
        body = b''.join(parts) + ('--%s--\r\n' % b).encode()
        req = urllib.request.Request('https://api.openai.com/v1/audio/transcriptions', data=body, method='POST',
                                     headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'multipart/form-data; boundary=' + b})
        try:
            with urllib.request.urlopen(req, timeout=60) as r: res = json.loads(r.read().decode('utf-8'))
            desk.record_ai('report_talk_stt', req.full_url, model, 200, {'audio_bytes': len(data)})
        except urllib.error.HTTPError as e:
            desk.record_ai('report_talk_stt', req.full_url, model, e.code, {})
            app.logger.warning('report talk STT failed: %s %s', e.code, e.read()[:200]); return jsonify(ok=False, error='ai')
        except Exception as e:
            app.logger.warning('report talk STT failed: %s', str(e)[:120]); return jsonify(ok=False, error='ai')
        text = ' '.join(str(res.get('text', '')).split())[:MAX_STORY]
        return jsonify(ok=bool(text), text=text)

    @app.route('/report/talk/ai', methods=['POST'])
    def report_talk_ai():
        if request.form.get('website'): abort(400)
        if S.report_login_needed(): return jsonify(ok=False, error='login'), 403
        story = ' '.join((request.form.get('story') or '').split())[:MAX_STORY]
        try: qa = [{'q': str(x.get('q', ''))[:120], 'a': str(x.get('a', ''))[:400]} for x in json.loads(request.form.get('qa') or '[]')[:MAX_QA] if isinstance(x, dict)]
        except ValueError: qa = []
        try: kn = json.loads(request.form.get('known') or '{}')
        except ValueError: kn = {}
        known = {k: str(kn.get(k) or '')[:700 if k == 'description' else 120] for k in KNOWN} if isinstance(kn, dict) else {}
        known = {k: v for k, v in known.items() if v.strip()}
        if known: qa = qa[-4:]
        images = [] if known else read_images()
        if len(story) < 2 and not images: return jsonify(ok=False, error='empty'), 400
        with conn() as db:
            if S.recent_count(db, 'report_talk_hits', 60) >= PER_HOUR: return jsonify(ok=False, error='limit'), 429
            db.execute('DELETE FROM report_talk_hits WHERE created<?', ((datetime.datetime.now() - datetime.timedelta(days=1)).isoformat(timespec='seconds'),))
            db.execute('INSERT INTO report_talk_hits(ip_hash,created) VALUES(?,?)', (S.ip_hash(), datetime.datetime.now().isoformat(timespec='seconds')))
        try: draft = ask(story, qa, images, known)
        except Exception as e:  # 키 없음·오류·형식 이상: 화면이 버튼으로 이어 감
            app.logger.warning('report talk AI failed: %s', str(e)[:120])
            return jsonify(ok=False, error='ai')
        return jsonify(ok=True, draft=draft)
