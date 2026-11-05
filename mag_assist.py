"""매거진 기사 쓰기 AI 도움 (운영자 2026-11-05: '기사 작성에도 AI 도움 받게 해줘').

기사 쓰기 화면의 'AI 도움'에서 고름:
- draft    메모·자료를 붙여 넣으면 제목·요약·본문 초안
- rewrite  다른 기사(주소나 글)를 주면 소보루 매거진 기사로 새로 쓰기 (운영자 2026-11-05)
- polish   고른 문장(없으면 본문 전체)을 매거진 문체로 다듬기
- proof    맞춤법·띄어쓰기만 고치기
- titles   제목 후보 다섯 개
- summary  요약 2~3줄

숫자는 지어내지 않게: 다듬기·맞춤법·요약·제목에서 원문에 없는 숫자가 나오면 그 답은 버림.
사용량은 'mag_assist'(기사 쓰기 AI 도움)로 따로 쌓이고, OPENAI_API_KEY_MAG_ASSIST가 있으면 그 키를 씀.
"""
import html
import json
import os
import re

from flask import jsonify, request

import companydesk as desk
import soboru_writer

desk.AI_FEATURES.setdefault('mag_assist', '기사 쓰기 AI 도움')
LIMIT = 12000  # 한 번에 보내는 글자 수

BASE = ('너는 소보루 매거진(소비자 라이프스타일 매거진)의 편집 데스크다. 에디터가 쓰는 기사를 돕는다.\n'
        '잡지 기사체(평서문 ~다)로 쓰고, 해요체·친구 말투·앱 안내문 말투(토스식)·AI 티 나는 꾸밈(이모지, 굵은 글씨, "결론적으로")은 쓰지 않는다.\n'
        + soboru_writer.STYLE + soboru_writer.SOURCE +
        '숫자를 지키는 법:\n'
        '- 에디터가 준 글·메모에 있는 사실과 숫자만 쓴다. 없는 숫자(날짜·금액·비율·건수·순위·기간)는 절대 만들지 않는다.\n'
        '- 숫자는 붙어 있던 대상·기간·단위와 함께 그대로 옮기고, 새로 계산하지 않는다.\n'
        '- 출처(기관·통계 이름과 기준 연도)가 있으면 문장 안에 그대로 남긴다. 언론사 이름·"보도에 따르면"은 출처로 쓰지 않는다.\n'
        '본문 형식: 문단은 빈 줄로 나눈다. 소제목은 줄 맨 앞에 "## "를 붙인다. [사진 ...]·[영상 ...] 줄은 그 자리에 그대로 둔다.\n')

ASKS = {
    'draft': ('아래 [메모]로 기사 초안을 쓴다. 소제목 3~4개, 소제목마다 문단 2개 안팎. 메모에 없는 내용은 채우지 않고, 모자라면 짧게 쓴다.\n'
              'JSON으로만 답한다: {"title": 제목(30자 안팎), "summary": 요약(2~3문장), "body": 본문}'),
    'rewrite': ('아래 [원문 기사]는 다른 매체의 기사다. 여기 담긴 사실을 바탕으로 소보루 매거진 피처 기사를 새로 쓴다.\n'
                '- 원문 문장을 그대로 옮기지 않는다. 구성·도입·소제목·문장을 모두 새로 짜고, 독자가 왜 이 일을 알아야 하는지 매거진의 시선으로 풀어 쓴다.\n'
                '- 사람이 한 말(따옴표 인용)은 말한 사람과 함께 그대로 옮겨도 된다.\n'
                '- 원문 매체 이름, 기자 이름, "보도에 따르면", "~가 전했다"는 쓰지 않는다. 사실은 말한 주체(기관·업체·당사자)를 밝혀 쓴다.\n'
                '- 원문에 없는 사실·숫자·추측은 더하지 않는다. 의혹은 의혹으로, 확인되지 않은 것은 확인되지 않았다고 쓴다.\n'
                '- 소제목 3~4개, 소제목마다 문단 2개 안팎. 원문이 짧으면 짧게 쓴다.\n'
                'JSON으로만 답한다: {"title": 제목(30자 안팎, 원문 제목과 다르게), "summary": 요약(2~3문장), "body": 본문}'),
    'polish': ('아래 [글]을 매거진 문체로 다듬는다. 뜻·사실·숫자·순서는 그대로 두고 문장만 고친다. 소제목·[사진]·[영상] 줄도 그대로 둔다.\n'
               'JSON으로만 답한다: {"text": 다듬은 글}'),
    'proof': ('아래 [글]의 맞춤법·띄어쓰기·문장부호만 고친다. 낱말과 문체는 바꾸지 않는다.\n'
              'JSON으로만 답한다: {"text": 고친 글, "fixes": [고친 곳을 "틀린 말 → 고친 말" 꼴로, 많으면 10개까지]}'),
    'titles': ('아래 [글]에 붙일 매거진 제목 후보 다섯 개를 만든다. 30자 안팎, 낚시·과장 없이, 서로 다른 각도로. 숫자는 글에 있는 것만.\n'
               'JSON으로만 답한다: {"titles": [제목 다섯 개]}'),
    'summary': ('아래 [글]의 요약을 2~3문장으로 쓴다. 기사 목록과 첫 화면에 보이는 글이다. 숫자는 글에 있는 것만.\n'
                'JSON으로만 답한다: {"summary": 요약}'),
}


ARTICLE_BOX = (r'id=["\']article-view-content-div["\']', r'itemprop=["\']articleBody["\']', r'id=["\']articleBody["\']', r'id=["\']dic_area["\']',
               r'class=["\'][^"\']*(?:article[_-]?body|news[_-]?body|article[_-]?content|article[_-]?txt|view[_-]?content)[^"\']*["\']', r'<article\b')


def page_text(chunk):
    chunk = re.sub(r'(?is)<(script|style|noscript|figure|figcaption|button|iframe)[^>]*>.*?</\1>', ' ', chunk)
    chunk = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</h\d>|</li>', '\n', chunk)
    chunk = html.unescape(re.sub(r'<[^>]+>', ' ', chunk))
    lines = [re.sub(r'[ \t\u00a0]+', ' ', x).strip() for x in chunk.split('\n')]
    return '\n'.join(x for x in lines if x)


def read_article(url):
    """기사 주소에서 제목과 본문 글만 뽑음. 못 읽으면 ''."""
    import company_web_email
    try: page = company_web_email.get(url)
    except Exception: return ''
    if not page: return ''
    m = re.search(r'(?is)<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', page) or re.search(r'(?is)<title[^>]*>(.*?)</title>', page)
    title = html.unescape(m[1]).strip() if m else ''
    body = ''
    for pat in ARTICLE_BOX:
        b = re.search(pat, page, re.I)
        if b:
            body = page_text(page[b.start():b.start() + 120000])
            if len(body) > 100: break
    if len(body) <= 100: body = '\n'.join(page_text(p) for p in re.findall(r'(?is)<p\b[^>]*>.*?</p>', page))
    body = re.split(r'(?:^|\n)(?:저작권자|Copyright|ⓒ|©|<저작권|무단\s*전재)', body, maxsplit=1)[0].strip()
    if len(re.sub(r'\s', '', body)) < 100: return ''
    return ((title + '\n\n') if title else '') + body[:LIMIT]


def numbers(s):
    return {n.replace(',', '') for n in re.findall(r'\d[\d,]*(?:\.\d+)?', s or '')}


def install(S):
    app = S.app

    def chat(system, user, max_tokens):
        key = desk.ai_key_for('mag_assist')
        if not key: raise RuntimeError('OpenAI 키가 없어 AI 도움을 쓸 수 없어요.')
        model = os.getenv('MAG_ASSIST_MODEL', '').strip() or os.getenv('WRITER_MODEL', '').strip() or soboru_writer.WRITER_MODEL
        if re.match(r'(gpt-([5-9]|\d\d)|o\d)', model): opts = {'max_completion_tokens': max_tokens + 1500, 'reasoning_effort': 'low'}
        else: opts = {'max_tokens': max_tokens, 'temperature': 0.5}
        body = {'model': model, 'response_format': {'type': 'json_object'}, **opts,
                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
        st, res = desk.post_json('https://api.openai.com/v1/chat/completions', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, 90)
        if st != 200: raise RuntimeError('AI가 지금 답하지 못했어요. 잠시 뒤 다시 해 주세요.')
        try: out = json.loads(res['choices'][0]['message']['content'])
        except (KeyError, IndexError, TypeError, ValueError): raise RuntimeError('AI 답을 읽지 못했어요. 다시 해 주세요.')
        if not isinstance(out, dict): raise RuntimeError('AI 답을 읽지 못했어요. 다시 해 주세요.')
        return out

    @app.route('/admin/magazine/assist', methods=['POST'])
    @S.admin_only
    def mag_assist():
        d = request.get_json(silent=True) or {}
        act = d.get('act')
        if act not in ASKS: return jsonify(ok=False, error='무엇을 도와드릴지 골라 주세요.'), 400
        title, summary, body = (str(d.get(k) or '')[:LIMIT] for k in ('title', 'summary', 'body'))
        text, note = str(d.get('text') or '')[:LIMIT], str(d.get('note') or '')[:LIMIT]
        if act == 'draft':
            if len(note.strip()) < 20: return jsonify(ok=False, error='메모나 자료를 조금 더 붙여 주세요.'), 400
            src, user = note, '[메모]\n' + note
        elif act == 'rewrite':
            note = note.strip()
            if re.fullmatch(r'https?://\S+', note):
                note = read_article(note)
                if not note: return jsonify(ok=False, error='이 주소에서 기사를 읽지 못했어요. 기사 글을 복사해서 붙여 넣어 주세요.'), 400
            if len(re.sub(r'\s', '', note)) < 100: return jsonify(ok=False, error='기사 주소나 기사 글 전체를 붙여 넣어 주세요.'), 400
            src, user = note, '[원문 기사]\n' + note
        else:
            src = text or body
            if act in ('titles', 'summary'): src = '\n'.join(x for x in (title, summary, body) if x)
            if len(re.sub(r'\s', '', src)) < 20: return jsonify(ok=False, error='본문을 조금 더 쓴 다음에 해 주세요.'), 400
            user = '[글]\n' + src
        try: out = chat(BASE + '\n' + ASKS[act], user, 3500 if act in ('draft', 'rewrite', 'polish', 'proof') else 700)
        except RuntimeError as e: return jsonify(ok=False, error=str(e)), 502
        have = numbers(src)

        def safe(s):  # 원문에 없는 숫자가 나온 답은 쓰지 않음
            return bool(s) and numbers(s) <= have

        if act in ('draft', 'rewrite'):
            res = {k: str(out.get(k) or '').strip() for k in ('title', 'summary', 'body')}
            if not res['body']: return jsonify(ok=False, error='초안을 만들지 못했어요. 다시 해 주세요.'), 502
            extra = sorted(numbers(' '.join(res.values())) - have)
            return jsonify(ok=True, **res, warn=(('메모' if act == 'draft' else '원문')+'에 없는 숫자가 들어갔어요: ' + ', '.join(extra[:5]) + '. 꼭 확인해 주세요.') if extra else '')
        if act in ('polish', 'proof'):
            t = str(out.get('text') or '').strip()
            if not safe(t): return jsonify(ok=False, error='다듬는 중에 숫자가 바뀌어서 쓰지 않았어요. 다시 해 주세요.'), 502
            fixes = [str(x)[:80] for x in (out.get('fixes') or [])][:10] if act == 'proof' else []
            return jsonify(ok=True, text=t, fixes=fixes)
        if act == 'titles':
            ts = [str(x).strip()[:60] for x in (out.get('titles') or []) if str(x).strip()]
            ts = [t for t in ts if numbers(t) <= have][:5]
            if not ts: return jsonify(ok=False, error='제목을 만들지 못했어요. 다시 해 주세요.'), 502
            return jsonify(ok=True, titles=ts)
        s = str(out.get('summary') or '').strip()[:400]
        if not safe(s): return jsonify(ok=False, error='요약을 만들지 못했어요. 다시 해 주세요.'), 502
        return jsonify(ok=True, summary=s)
