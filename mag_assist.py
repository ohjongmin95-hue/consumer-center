"""매거진 기사 쓰기 AI 도움 (운영자 2026-11-05: '기사 작성에도 AI 도움 받게 해줘').

기사 쓰기 화면의 'AI 도움'에서 고름:
- draft    메모·자료를 붙여 넣으면 제목·요약·본문 초안
- rewrite  다른 기사(주소나 글)를 주면 소보루 매거진 기사로 새로 쓰기 (운영자 2026-11-05)
- polish   고른 문장(없으면 본문 전체)을 매거진 문체로 다듬기
- proof    맞춤법·띄어쓰기만 고치기
- titles   제목 후보 다섯 개
- summary  요약 2~3줄
- cards    기사 하나로 카드뉴스 장 구성 (운영자 2026-11-05: '기사 넣으면 만들어지게' — 카드뉴스·릴스 만들기에서 씀)
- reel     기사 하나로 릴스 장면 구성 (디자인·제목·자막·길이)
  cards·reel은 소보루 레터 한 꼭지로도 짬 (운영자 2026-11-05: '뉴스레터 하나를 만들고 그 내용을 여러 SNS 콘텐츠로 쪼개서 반복 홍보'):
  레터 한 호를 꼭지(오늘의 뉴스 하나하나·메인 뉴스·숫자·소비 트렌드·피해 예방·법률)로 나눠 꼭지마다 게시물 하나.
  끝에 레터 구독 안내 장을 붙이고, 인스타 캡션도 같이 써 줌 (구독은 프로필 링크로).

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
    'cards': ('아래 [기사]로 인스타그램 카드뉴스 5~7장을 짠다. 넘기며 읽는 글이라 한 장에 한 가지만 담고, 문장은 짧게 끊는다.\n'
              '- 1장 = 표지(design "clean"): title은 기사 핵심을 2줄(줄 바꿈은 \\n)로, 한 줄 12자 안. sub는 비운다.\n'
              '- 2장부터 = 속 장(design "text"): title은 소제목 한 줄(14자 안), items는 짧은 문단 1~2개(문단은 빈 줄로 나누고 각 110자 안). 핵심 숫자·말은 **굵게** 감싼다.\n'
              '- 기사에 사람이 한 말(따옴표)이 있으면 한 장은 인용(design "quote"): title = 말 자체(40자 안, 줄 바꿈 \\n으로 2~3줄), sub = 말한 사람.\n'
              '- 마지막 장(design "text")은 독자가 알아 둘 것 한 가지로 맺는다.\n'
              '- 기사에 있는 사실·숫자만 쓴다. 의혹은 의혹으로 쓴다. 해요체·이모지 금지, 매거진 평서문.\n'
              'JSON으로만 답한다: {"tag": 분야를 영문 대문자 한 단어로(FOOD, SHOPPING, BEAUTY, LIFE, MONEY, TELECOM, TRAVEL, CAR, RECALL 중), '
              '"slides": [{"design": "clean"|"text"|"quote", "title": 제목, "sub": 부제, "items": 글}]}'),
    'reel': ('아래 [기사]로 인스타그램 릴스(세로 영상) 장면 4~6개를 짠다. 전체 25~45초. 보는 사람은 소리 없이 자막만 읽으니 장면마다 글은 짧게.\n'
             '장면 design: "wide"(흐린 배경 위 사진·영상 + 위 큰 제목 + 아래 사실 상자·말풍선, 기본), "full"(사진·영상 꽉 채우고 큰 제목, 훅용), '
             '"chat"(말풍선 대화, 당사자·목격자 말이 여럿일 때), "quote"(한 사람 말 클로즈업), "clean"(사진 꽉 + 제목 한 줄, 마무리용).\n'
             '- 1번 장면은 훅: title은 궁금하게 만드는 질문형 2줄(줄 바꿈 \\n, 한 줄 10자 안), sub는 ": "로 시작하는 한 줄 부제(20자 안). design은 full 또는 wide.\n'
             '- 2번부터: title은 그 장면의 핵심 한 줄(2줄까지), items는 자막 2~3줄. items 쓰는 법: 한 줄에 하나. "#글"은 사실 상자(때·곳·수치), "!글"은 강조 상자, "이름 : 말"은 말풍선(예: 운전자 A씨 : 피할 수 없었다). 한 줄 36자 안.\n'
             '- quote 장면은 title = 말 자체(2~3줄, 줄 바꿈 \\n), sub = 말한 사람. chat 장면은 items를 "이름 : 말" 줄 3~4개로.\n'
             '- 마지막 장면(design "clean")은 아직 확인되지 않은 것 또는 독자가 알아 둘 것 한 줄로 맺는다.\n'
             '- dur는 장면 길이(초)로 3~8 사이 정수. 글이 많은 장면은 길게.\n'
             '- 기사에 있는 사실·숫자만 쓴다. 의혹은 의혹으로, 확인되지 않은 것은 확인되지 않았다고 쓴다. 해요체·이모지 금지.\n'
             'JSON으로만 답한다: {"tag": "○○ 이슈 · 지역"꼴 짧은 태그(18자 안), '
             '"scenes": [{"design": "wide"|"full"|"chat"|"quote"|"clean", "title": 제목, "sub": 부제, "items": 자막 줄들, "dur": 초}]}'),
}
LETTER_ASK = ('\n[기사] 자리에는 매일 아침 메일로 나가는 뉴스레터 \'소보루 레터\'의 한 꼭지가 들어온다. 이 게시물의 목적은 레터를 알리고 구독자를 늘리는 것이다.\n'
              '- 꼭지의 핵심만 빠르게 보여 주고, 자세한 이야기는 레터에 있다는 느낌으로 맺는다. 구독 안내 장·장면은 따로 붙이니 만들지 않는다.\n'
              '- JSON에 "caption"도 넣는다: 인스타그램 캡션. 해요체, 4~6줄, 줄마다 맨 앞에 이모지 하나, 꼭지의 사실만. 영상·카드 설명 같은 메타 문장은 쓰지 않는다. '
              '구독 안내 줄과 해시태그는 붙이지 않는다(따로 붙임).')
LETTER_CTA = {'cards': {'design': 'text', 'title': '매일 아침 받아 보는\n소보루 레터', 'sub': '',
                        'items': '오늘의 소비·경제 뉴스를 한 통에 담아 메일로 보내 드려요.\n\n**프로필 링크에서 무료로 구독**할 수 있어요.'}}
# 릴스는 끝의 귤색 마무리 화면이 레터 구독 안내로 바뀜 (maker.js REEL.outro)
LETTER_TAIL = '📮 매일 아침 받아 보는 소보루 레터 · 구독은 프로필 링크에서\n\n#소보루레터 #소보루매거진 #뉴스레터 #경제뉴스 #소비트렌드'


def _t(v, n=1500): return ' '.join(str(v or '').split())[:n]


def letter_pieces(L):
    """레터 한 호를 SNS 게시물로 쪼갤 꼭지들: [{key, label, text}]. 글이 너무 짧은 꼭지는 뺌."""
    sec, out = L.get('sections') or {}, []
    def add(key, label, *parts):
        text = '\n'.join(p for p in parts if p)
        if len(re.sub(r'\s', '', text)) >= 40: out.append({'key': key, 'label': label, 'text': text[:LIMIT]})
    items = L.get('items') or []
    add('all', '이번 호 한눈에 (뉴스 모아 보기)', '소보루 레터 오늘의 뉴스 모음', _t(L.get('intro'), 600),
        *['%d. %s — %s' % (i + 1, _t(it.get('title'), 80), _t(it.get('body'), 400)) for i, it in enumerate(items)])
    for i, it in enumerate(items):
        add('news:%d' % i, '뉴스 · ' + _t(it.get('title'), 40), _t(it.get('title'), 80), _t(it.get('body')), ('이럴 땐 이렇게: ' + _t(it.get('tip'), 200)) if it.get('tip') else '',
            '출처: ' + _t((it.get('src') or {}).get('name'), 40) if (it.get('src') or {}).get('name') else '')
    c = sec.get('comment') if isinstance(sec.get('comment'), dict) else None
    if c:
        pts = lambda k: ['%s: %s' % (_t(p.get('name'), 30), _t(p.get('text'), 300)) for p in ((c.get(k) or {}).get('points') or []) if isinstance(p, dict)]
        add('comment', '메인 뉴스 · ' + _t(c.get('title'), 40), _t(c.get('title'), 80), _t(c.get('lead'), 600), _t((c.get('what') or {}).get('body'), 400), *pts('what'),
            _t((c.get('why') or {}).get('body')), _t((c.get('wallet') or {}).get('body'), 300), *pts('wallet'))
    n = sec.get('number') if isinstance(sec.get('number'), dict) else None
    if n: add('number', '숫자로 보는 오늘 · ' + _t(n.get('value'), 20), '숫자로 보는 오늘: %s %s' % (_t(n.get('value'), 20), _t(n.get('label'), 40)), _t(n.get('body'), 300))
    z = sec.get('buzz') if isinstance(sec.get('buzz'), dict) else None
    if z: add('buzz', '소비 트렌드 · ' + _t(z.get('title'), 40), _t(z.get('title'), 80), _t(z.get('body'), 900),
              *['%s: %s' % (_t(p.get('name'), 30), _t(p.get('text'), 700)) for p in (z.get('points') or []) if isinstance(p, dict)], _t(z.get('insight'), 900), _t(z.get('tip'), 300))
    h = sec.get('harm') if isinstance(sec.get('harm'), dict) else None
    if h: add('harm', '피해 예방 · ' + _t(h.get('title'), 40), _t(h.get('title'), 60), _t(h.get('body'), 700), *[_t(x, 90) for x in (h.get('steps') or [])])
    b = sec.get('lawbox') if isinstance(sec.get('lawbox'), dict) else None
    if b: add('lawbox', '알아 두면 좋은 법 · ' + _t(b.get('title'), 40), _t(b.get('title'), 60), _t(b.get('body'), 800), _t(b.get('point'), 120))
    return out


def letter_photos(L, key):
    c = (L.get('sections') or {}).get('comment')
    u = (c.get('photo') or {}).get('url') if key == 'comment' and isinstance(c, dict) and isinstance(c.get('photo'), dict) else ''
    return [u] if isinstance(u, str) and u.startswith('https://') else []


MAKER = {'cards': ('slides', ('clean', 'text', 'quote'), 'text'), 'reel': ('scenes', ('wide', 'full', 'chat', 'quote', 'clean'), 'wide')}
MEDIA = re.compile(r'^\[(사진|영상) ([^\s|\]]+)', re.M)


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


def maker_plan(act, out):
    """AI가 짠 카드·장면을 만들기 화면이 쓰는 꼴로 정리. 이상한 값은 버리거나 기본값."""
    key, designs, default = MAKER[act]
    plan = []
    for s in (out.get(key) or [])[:8]:
        if not isinstance(s, dict): continue
        p = {k: str(s.get(k) or '').strip()[:600 if k == 'items' else 120] for k in ('title', 'sub', 'items')}
        if not (p['title'] or p['items']): continue
        p['design'] = s.get('design') if s.get('design') in designs else default
        if act == 'reel':
            try: p['dur'] = min(8, max(3, int(float(s.get('dur') or 4))))
            except (TypeError, ValueError): p['dur'] = 4
        plan.append(p)
    return plan


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

    def article_text(d):
        """만들기 화면이 준 기사: 기사 번호(art)면 DB에서, 아니면 note(기사 주소나 글). (글, 사진들, 영상들)"""
        note = str(d.get('note') or '')[:LIMIT].strip()
        if d.get('art'):
            try: aid = int(d['art'])
            except (TypeError, ValueError): return '', [], []
            with S.conn() as db:
                r = db.execute('SELECT title,summary,body,category FROM articles WHERE id=?', (aid,)).fetchone()
            if not r: return '', [], []
            body = r['body'] or ''
            media = MEDIA.findall(body)
            text = '\n\n'.join(x for x in (r['title'], '분야: ' + (r['category'] or ''), r['summary'], body) if x)
            return text[:LIMIT], [u for k, u in media if k == '사진'], [u for k, u in media if k == '영상']
        if re.fullmatch(r'https?://\S+', note): note = read_article(note)
        return note, [], []

    def letter_of(d):
        """만들기 화면이 고른 레터 꼭지 'L<호 id>:<꼭지>' → (레터, 꼭지) 또는 (None, None)"""
        m = re.fullmatch(r'L(\d+):([a-z]+(?::\d+)?)', str(d.get('letter') or ''))
        get = (app.extensions.get('soboru_letter') or {}).get('get')
        L = get(lid=int(m.group(1))) if m and get else None
        piece = next((p for p in letter_pieces(L) if p['key'] == m.group(2)), None) if L else None
        return (L, piece) if piece else (None, None)

    @app.route('/admin/magazine/assist', methods=['POST'])
    @S.admin_only
    def mag_assist():
        d = request.get_json(silent=True) or {}
        act = d.get('act')
        if act not in ASKS: return jsonify(ok=False, error='무엇을 도와드릴지 골라 주세요.'), 400
        title, summary, body = (str(d.get(k) or '')[:LIMIT] for k in ('title', 'summary', 'body'))
        text, note = str(d.get('text') or '')[:LIMIT], str(d.get('note') or '')[:LIMIT]
        if act in MAKER:
            L, piece = letter_of(d) if d.get('letter') else (None, None)
            if d.get('letter') and not piece: return jsonify(ok=False, error='이 레터 꼭지를 찾지 못했어요. 다시 골라 주세요.'), 400
            src, photos, videos = (piece['text'], letter_photos(L, piece['key']), []) if piece else article_text(d)
            if len(re.sub(r'\s', '', src)) < (40 if piece else 100): return jsonify(ok=False, error='기사를 고르거나, 기사 주소나 기사 글 전체를 붙여 넣어 주세요.'), 400
            try: out = chat(BASE + '\n' + ASKS[act] + (LETTER_ASK if piece else ''), '[기사]\n' + src, 2500)
            except RuntimeError as e: return jsonify(ok=False, error=str(e)), 502
            plan = maker_plan(act, out)
            if len(plan) < 2: return jsonify(ok=False, error='구성을 짜지 못했어요. 다시 해 주세요.'), 502
            caption = ''
            if piece:
                if act in LETTER_CTA: plan = plan[:7] + [dict(LETTER_CTA[act])]
                caption = '\n'.join(l.strip() for l in str(out.get('caption') or '').strip().splitlines() if l.strip())[:900]
                caption = (caption + '\n\n' if caption else '') + LETTER_TAIL
            extra = sorted(numbers(' '.join(p['title'] + ' ' + p['sub'] + ' ' + p['items'] for p in plan) + ' ' + caption) - numbers(src) - numbers(LETTER_TAIL + str(LETTER_CTA)))
            return jsonify(ok=True, tag=str(out.get('tag') or '').strip()[:40], photos=photos[:10], videos=videos[:4], caption=caption, letter=bool(piece),
                           **{MAKER[act][0]: plan}, warn=(('레터' if piece else '기사') + '에 없는 숫자가 들어갔어요: ' + ', '.join(extra[:5]) + '. 꼭 확인해 주세요.') if extra else '')
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
