"""소보루 카드뉴스 만들기: 뉴스 링크 하나로 인스타 카드뉴스(표지 문구 5개 + 본문 + 그림 + 캡션) 초안을 Claude로 만든다.

소보루 사이트와 따로 돌아가는 프로그램이다 (server.py가 화면, 이 파일이 만드는 일).
- 순서: 기사 가져오기 → 같은 뉴스를 다룬 다른 기사 1~2개 찾아 읽기(사실 확인: 네이버 뉴스 검색 먼저, 모자라면 Claude 웹 검색) → 원고(JSON: Claude API·claude.ai 붙여넣기·직접 쓰기) → 이미지(ChatGPT 또는 Claude) → 코드 검사.
- 규칙은 「인스타 수익화 올인원 패키지 3권 · 저작권 기준표」(2026.10)를 따른다:
  사실만 가져오고 기사 문장은 옮기지 않음(띄어쓰기 빼고 18자 넘게 같으면 걸림) · 표지 낚시말(충격·결국·경악) 금지 · '댓글에 ○○' 대신 저장 유도 ·
  기사 사진 안 씀(그림은 새로 그림) · 실존 인물 얼굴·기업 로고·유명 캐릭터 안 그림 · 캡션에 '출처: 매체명 날짜 보도' + 링크.
  다른 기사로 확인하지 못했거나 기사에 없는 숫자가 있으면 '확인 필요'로 두고, '직접 확인했어요'에 체크해야 내려받을 수 있다.
- 이미지: ChatGPT(OpenAI 이미지 API) 또는 Claude(SVG 일러스트)로 자동 (운영자 2026-10-26, 힉스필드 자동은 뺌). 장마다 사진/일러스트를 고르고,
  다른 곳에서 만든 이미지를 올려도 된다. 마지막 장은 소보루 캐릭터(static/soboru-character.png).
- 구성: 캐러셀 레퍼런스북의 경제형(배경→숫자→원인→교훈) / 이슈형(발단→전개→영향→현재) 6장 공식만 쓴다.
- 카드 모양(글자·주황 박스·태그)은 화면(templates/edit.html)이 데이터로 그리고, PNG(1080×1350)와 캡션을 한 번에 내려받는다.
  인스타그램에는 직접 올린다(외부 자동 업로드 봇은 계정 정지 위험).
"""
import datetime, email.utils, html, threading, time, ipaddress, json, re, secrets, socket, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

AI_TIMEOUT = 600
COPY_RUN = 18  # 기사와 띄어쓰기 빼고 이만큼 연달아 같으면 '기사 문장 옮김'
ARROWS = ('up', 'down', '')
KINDS = {'economy': ('배경', '숫자', '원인', '교훈'), 'issue': ('발단', '전개', '영향', '현재')}  # 레퍼런스북 공식: 경제형 / 이슈형
THEMES = ('ref', 'newneek', 'magazine', 'poster', 'clean', 'dark')  # 카드 디자인 (기본: 레퍼런스북식)
ACCENTS = ('tangerine', 'blue', 'green', 'red', 'ink')
ENDS = ('save', 'share')  # 마지막 장 마무리: 저장 유도(기본) / 공유형 (캐러셀 레퍼런스북: 저장이 기본, 공유 명분은 기획에서)
# 저작권 기준표 Ch2·Ch10: 표지 낚시말, 마지막 장 참여 유도, 조심할 정치 말
BAIT = ('충격', '결국', '경악', '소름', '실화냐', '역대급', '난리', '발칵')
ASK_ENGAGE = ('댓글', '좋아요 눌러', '팔로우하면', '공유하면', 'DM 주')
POLITICS = ('대통령', '국회의원', '정당', '후보', '선거', '여당', '야당', '국민의힘', '민주당')
ALWAYS_OK = {'1372'}  # 원고 끝 안내에 늘 쓰는 번호 (소비자상담센터)
# 매일 자동으로 고를 뉴스 주제 (소비자 권익)
DAILY_TOPICS = ('소비자 피해, 환불·위약금 분쟁, 한국소비자원 발표, 공정위 제재, 리콜, 요금·가격 인상, 소비자 주의보, 피해구제, '
                '그리고 유통·생활경제(편의점·마트·이커머스·배달앱·식품 가격)와 금융·부동산·물가·요금·세금·환율 등 경제 섹션 뉴스 전부(분야를 고르게)')

WRITE_SYSTEM = """너는 소비자 권익 서비스 '소보루(SOBORU)'의 인스타그램 카드뉴스 에디터야. 뉴닉처럼 친근하고 쉬운 해요체로 쓴다.
기사 한 편과 같은 뉴스를 다룬 다른 기사를 받는다. 이걸로 카드뉴스 원고를 JSON으로 쓴다.

[저작권 규칙 — 꼭 지킴]
- 사실(날짜·숫자·기관·정책·누가 무엇을)만 가져오고, 기자의 문장·표현·문단 순서는 가져오지 않는다. 모든 문장을 네 말로 새로 쓴다.
- 숫자는 기사에 있는 숫자만 그대로 쓴다. 계산하거나 반올림해서 새 숫자를 만들지 않는다. 기사에 없는 내용은 보태지 않는다.
- 다른 기사와 숫자·사실이 어긋나거나 한 기사에만 있는 중요한 사실은 confirm_needed에 적는다.
- 실존 인물을 조롱·비하하거나 기업을 평가·비난하는 말(악덕, 최악, 갑질 등)은 쓰지 않는다. 사실만 전한다.
- 정치 뉴스는 양쪽 입장을 사실로만 나열하고 '언제부터 / 누가 해당 / 내가 챙길 것'으로 생활 영향만 쓴다. 참사·범죄는 자극적으로 묘사하지 않고 예방·대처 정보 위주.

[구성 — 캐러셀 레퍼런스북 공식, 기사에 맞는 것 하나를 골라 kind에 적고 꼭 그 순서로 6장]
kind='economy' (경제) — 뿌리: 욕망 충족(돈 벌고 싶다·아끼고 싶다). 기업·돈·가격·금리·유통 이야기를 뉴스보다 쉽고 재밌게.
 1장 표지 → 2장 배경(처음엔 어땠나) → 3장 숫자(꺾인·바뀐 시점의 숫자 하나) → 4장 원인(결정적 이유 세 가지) → 5장 교훈(우리가 배울 점 한 줄) → 6장 마무리(출처 · 저장해 두고 다시 보기)
 예: '잘나가던 ○○는 왜 망했을까' → '처음엔 이렇게 잘됐다' → '매출이 꺾인 시점' → '결정적 실수 세 가지' → '우리가 배울 점 한 줄'
 주의: 특정 종목·상품 투자를 권하는 것처럼 보이면 안 된다(투자 자문 아님). 숫자·날짜는 기사에 있는 그대로만.
kind='issue' (이슈) — 뿌리: 흥미 유발. 화제가 된 뉴스를 사실만 골라 내 문장으로 정리.
 1장 표지 → 2장 발단(무슨 일이 있었나) → 3장 전개(논란이 커진 이유) → 4장 영향(내 생활에 뭐가 달라지나) → 5장 현재(지금 상황 · 확인된 사실만) → 6장 마무리(출처 · 헷갈리면 저장)
 예: '지금 난리 난 ○○, 내 월급엔 무슨 일?' → '무슨 일이 있었나' → '논란이 커진 이유' → '내 생활에 뭐가 달라지나' → '지금 상황 · 확인된 사실만'
 주의: 확인되지 않은 일은 쓰지 않는다. 한쪽 주장만 사실처럼 쓰지 않는다.
고르는 법: 기업 실적·가격·금리·돈의 흐름이 중심이면 economy, 사건·논란·화제가 중심이면 issue.
둘 다 한 장에 메시지 하나. 출처는 꼭 남긴다.

[1장 표지]
- topic: 맨 위 작은 줄. '주제어 | 한 줄 설명' (예: '유통 | 편의점 도시락 평균 가격 300원 올라'). 40자 안팎.
- emoji: topic 끝에 붙일 이모지 1개.
- covers: 표지 문구 후보 정확히 5개. 각 후보는 두 줄(line1, line2), 한 줄 15자 안쪽.
  궁금한 한 줄 + 크게 박은 숫자 하나. line1은 궁금증(질문이나 말 걸기), line2는 핵심 숫자나 사실.
  기사 제목을 그대로 쓰지 말고 '내 월급·내 통장·내 장바구니' 얘기로 바꾼다 (예: '○○ 매출 감소' 대신 '잘나가던 ○○, 왜 꺾였을까?').
  결론은 숨기고 다음 장이 궁금하게 ('…알고 보니 ○○' 처럼 제목에 답을 다 주지 않는다). 단, 답은 반드시 본문에 있어야 한다.
  5개는 후킹 틀 6가지 중 서로 다른 것으로: 후회·경험 / 변화·비포애프터 / 경고·금지 / 쉬운 방법·지름길 / 비밀·희소 / 원칙·권위.
  저장되는 제목 패턴도 하나쯤: '저장해 두면 도움 되는 ○○', '○○ 총정리', 'N가지'.
  '충격·결국·경악·소름·역대급' 같은 낚시말 금지.
- cover_tags: 표지에 크게 박을 숫자 태그 1개(+ 보조 1개까지). 예: {"text":"매출 32% 감소","dir":"down"}. dir은 up/down/'' 중 하나. 12자 안쪽.
- cover_scene: 표지 장면을 영어로 묘사 (강렬한 장면 하나, 사람은 뒷모습·손·흐릿하게만, 실존 인물·기업 로고·브랜드·글자 없이).

[2~5장 cards] 정확히 4장, kicker는 고른 kind의 이름 그대로 이 순서로.
 economy: '배경', '숫자', '원인', '교훈'
 - 배경: '처음엔 이렇게 잘됐다'처럼 전 상황. / 숫자: 꺾인·바뀐 시점 한 줄, tags 첫 번째에 핵심 숫자 하나를 꼭(크게 보여 줌).
 - 원인: '결정적 이유 세 가지'처럼, body는 '① … ② … ③ …'로 짧게. / 교훈: '우리가 배울 점 한 줄', 내 돈·내 생활에 가져갈 한 줄.
 issue: '발단', '전개', '영향', '현재'
 - 발단: 무슨 일이 있었나(언제·누가·무엇을). / 전개: 논란이 커진 이유(양쪽 사실만).
 - 영향: 내 생활에 뭐가 달라지나, tags 첫 번째에 생활에 닿는 숫자 하나. / 현재: 지금 상황, 확인된 사실만 (확인 안 된 건 '아직 정해지지 않았어요').
- 각 장: kicker(위 이름 그대로), title(제목, 한 줄 16자 안쪽, 두 줄이면 줄바꿈 \\n 하나), body(2~4문장, 120자 안쪽),
  tags(수치 태그 0~2개, cover_tags와 같은 모양), scene(그 장 이미지 장면을 영어로: 내용이 떠오르는 사물·장소, 글자·숫자·로고 없이).

[6장 마무리]
- tips: 소비자가 실제로 할 수 있는 행동 팁 정확히 3개 (각 30자 안쪽, 예: '1372 소비자상담센터에 먼저 물어보기').
- 마무리는 저장 유도가 기본 (화면이 economy는 '저장해 두고 다시 보세요', issue는 '헷갈리면 저장해 두세요'를 붙임). '댓글에 ○○ 남기면' 같은 참여 유도는 넣지 않는다.
- share_line: 공유형 마무리 한 줄 (가끔 씀. 이 정보가 꼭 필요한 '누구'에게 보내라는 말, 20자 안쪽, 예: '이번 달 카드값 걱정인 친구한테').

[캡션]
- caption: 인스타 캡션 본문. 공감형으로 짧게 ('나도 그래' 싶게), 3~5줄 + 행동 팁 한 줄. 출처 줄은 쓰지 마 (화면이 자동으로 붙임). 참여 유도 금지.
- hashtags: 5~8개, '#' 빼고 (예: '소비자권익', '소보루').

[출처]
- source_media: 기사 매체명, source_date: 보도 날짜 YYYY.MM.DD (기사에서 못 찾으면 빈칸).
- facts_used: 원고에 쓴 사실을 기사에서 확인할 수 있는 짧은 메모 목록."""

FIND_SYSTEM = """You help fact-check Korean news for consumer card news. Use web search, then answer with JSON only (no other text)."""

ITEM_TAG = {'type': 'object', 'properties': {'text': {'type': 'string'}, 'dir': {'type': 'string', 'enum': list(ARROWS)}}, 'required': ['text', 'dir'], 'additionalProperties': False}
WRITE_SCHEMA = {'type': 'object', 'additionalProperties': False,
    'required': ['kind', 'topic', 'emoji', 'covers', 'cover_tags', 'cover_scene', 'cards', 'tips', 'share_line', 'caption', 'hashtags', 'source_media', 'source_date', 'facts_used', 'confirm_needed'],
    'properties': {
        'kind': {'type': 'string', 'enum': ['economy', 'issue']}, 'topic': {'type': 'string'}, 'emoji': {'type': 'string'},
        'covers': {'type': 'array', 'items': {'type': 'object', 'properties': {'line1': {'type': 'string'}, 'line2': {'type': 'string'}}, 'required': ['line1', 'line2'], 'additionalProperties': False}},
        'cover_tags': {'type': 'array', 'items': ITEM_TAG}, 'cover_scene': {'type': 'string'},
        'cards': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['kicker', 'title', 'body', 'tags', 'scene'],
                  'properties': {'kicker': {'type': 'string'}, 'title': {'type': 'string'}, 'body': {'type': 'string'}, 'tags': {'type': 'array', 'items': ITEM_TAG}, 'scene': {'type': 'string'}}}},
        'tips': {'type': 'array', 'items': {'type': 'string'}}, 'share_line': {'type': 'string'}, 'caption': {'type': 'string'}, 'hashtags': {'type': 'array', 'items': {'type': 'string'}},
        'source_media': {'type': 'string'}, 'source_date': {'type': 'string'},
        'facts_used': {'type': 'array', 'items': {'type': 'string'}}, 'confirm_needed': {'type': 'array', 'items': {'type': 'string'}}}}


def stamp(): return datetime.datetime.now().isoformat(timespec='seconds')


# ---- Claude ---------------------------------------------------------------------
def _client(key):
    import anthropic
    return anthropic, anthropic.Anthropic(api_key=key, timeout=AI_TIMEOUT, max_retries=2)


def _errors(anthropic, fn):
    try: return fn()
    except anthropic.AuthenticationError: raise RuntimeError('Claude API 키가 맞지 않아요 (설정에서 다시 넣어 주세요)')
    except anthropic.PermissionDeniedError: raise RuntimeError('이 API 키로는 쓸 수 없는 기능이에요 (Claude 콘솔에서 웹 검색이 켜져 있는지 확인)')
    except anthropic.RateLimitError: raise RuntimeError('Claude 사용량 한도에 걸렸어요. 잠시 뒤 다시 해 주세요')
    except anthropic.APIStatusError as e: raise RuntimeError(f'Claude 응답 오류 ({e.status_code})')
    except anthropic.APIConnectionError: raise RuntimeError('Claude에 연결하지 못했어요 (인터넷 연결 확인)')


def claude(cfg, system, user, schema, max_tokens, effort='medium'):
    """Claude에 한 번 묻고 JSON으로 받음. 테스트에서 바꿔 끼운다."""
    anthropic, client = _client(cfg['key'])
    def run():
        # 원고·그림이 길어 스트리밍으로 받음. 안전 거절이면 서버가 알아서 다른 모델로 다시 씀(fallbacks)
        with client.beta.messages.stream(model=cfg['model'], max_tokens=max_tokens, system=system, messages=[{'role': 'user', 'content': user}],
                                         output_config={'effort': effort, 'format': {'type': 'json_schema', 'schema': schema}},
                                         betas=['server-side-fallback-2026-07-01'], fallbacks='default') as s:
            return s.get_final_message()
    msg = _errors(anthropic, run)
    if msg.stop_reason == 'refusal': raise RuntimeError('Claude가 이 기사로는 만들지 않겠다고 했어요')
    if msg.stop_reason == 'max_tokens': raise RuntimeError('Claude 답이 너무 길어 잘렸어요')
    try: return json.loads(next(b.text for b in msg.content if b.type == 'text'))
    except (StopIteration, ValueError): raise RuntimeError('Claude 응답을 읽지 못했어요')


def search(cfg, question, max_uses=4):
    """Claude 웹 검색으로 묻기 → (Claude 답 글, 검색 결과로 실제로 본 [{url,title}]). 테스트에서 바꿔 끼운다."""
    anthropic, client = _client(cfg['key'])
    messages = [{'role': 'user', 'content': question}]
    seen, text = [], ''
    for _ in range(3):  # 검색이 길면 pause_turn으로 멈춤: 받은 그대로 다시 보내면 이어서 함
        msg = _errors(anthropic, lambda: client.beta.messages.create(
            model=cfg['model'], max_tokens=8000, system=FIND_SYSTEM, messages=messages, output_config={'effort': 'low'},
            tools=[{'type': 'web_search_20260209', 'name': 'web_search', 'max_uses': max_uses, 'user_location': {'type': 'approximate', 'country': 'KR', 'timezone': 'Asia/Seoul'}}],
            betas=['server-side-fallback-2026-07-01'], fallbacks='default'))
        for b in msg.content:
            if b.type == 'web_search_tool_result' and isinstance(b.content, list):
                seen += [{'url': r.url, 'title': getattr(r, 'title', '') or ''} for r in b.content if getattr(r, 'url', '')]
            if b.type == 'text': text += b.text
        if msg.stop_reason != 'pause_turn': break
        messages = [messages[0], {'role': 'assistant', 'content': msg.content}]
    if msg.stop_reason == 'refusal': raise RuntimeError('Claude가 이 검색은 하지 않겠다고 했어요')
    return text, seen


def json_in(text):
    """Claude 답 글 속 JSON 하나 (앞뒤 말·```이 붙어도). 못 찾으면 {}"""
    m = re.search(r'\{.*\}', text or '', re.S)
    try: return json.loads(m.group()) if m else {}
    except ValueError: return {}


# ---- 기사 읽기 -------------------------------------------------------------------
def _public_host(url):
    """http(s)이고 내 컴퓨터·사설망 주소가 아닌지 (뉴스 링크로 안쪽 주소를 열지 않게)"""
    u = urllib.parse.urlparse(url or '')
    if u.scheme not in ('http', 'https') or not u.hostname: return False
    try: addrs = {a[4][0] for a in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == 'https' else 80), proto=socket.IPPROTO_TCP)}
    except (socket.gaierror, UnicodeError, ValueError): return False
    return bool(addrs) and all(ipaddress.ip_address(a.split('%')[0]).is_global for a in addrs)


class _NoRedirectToPrivate(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _public_host(newurl): return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_page(url, timeout=10, limit=2_000_000):
    """기사 HTML. 못 읽으면 ''. 테스트에서 바꿔 끼운다."""
    if not _public_host(url): return ''
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36',  # 봇처럼 보이면 막는 언론사가 많음
                                                'Accept': 'text/html', 'Accept-Language': 'ko-KR,ko;q=0.9'})
    try:
        with urllib.request.build_opener(_NoRedirectToPrivate).open(req, timeout=timeout) as r:
            if 'html' not in (r.headers.get('Content-Type') or 'text/html'): return ''
            raw = r.read(limit); cs = r.headers.get_content_charset()
    except (urllib.error.URLError, OSError, ValueError): return ''
    if not cs:
        m = re.search(rb'charset=["\']?([\w-]+)', raw[:4000], re.I); cs = m.group(1).decode() if m else 'utf-8'
    try: return raw.decode(cs, 'replace')
    except LookupError: return raw.decode('utf-8', 'replace')


def _meta(page, *names):
    for n in names:
        m = (re.search(r'<meta[^>]+(?:property|name|itemprop)=["\']%s["\'][^>]*content=["\']([^"\']+)' % re.escape(n), page, re.I)
             or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name|itemprop)=["\']%s["\']' % re.escape(n), page, re.I))
        if m: return ' '.join(html.unescape(m.group(1)).split())
    return ''


def article_text(page, limit=9000):
    """기사 HTML → 본문 글 (<article>이 있으면 그 안, 없으면 문단·줄). 출처·저작권 안내 줄은 뺌."""
    t = re.sub(r'(?is)<(script|style|noscript|header|footer|nav|aside|form|figure|figcaption|button|iframe)[^>]*>.*?</\1>', ' ', page or '')
    m = re.search(r'(?is)<article[^>]*>(.*?)</article>', t)
    if m and len(re.sub(r'<[^>]+>', '', m.group(1))) > 200: t = m.group(1)
    t = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>', '\n', t)
    t = html.unescape(re.sub(r'<[^>]+>', ' ', t))
    out = []
    for line in t.split('\n'):
        line = ' '.join(line.split())
        if len(line) < 25 or not re.search(r'[가-힣]{2}', line): continue
        if re.search(r'무단|전재|재배포|Copyright|ⓒ|©|구독|기자\s*=|\w+@\w+', line, re.I) and len(line) < 120: continue
        if line not in out: out.append(line)
    return '\n'.join(out)[:limit]


def article_date(page):
    d = _meta(page, 'article:published_time', 'og:article:published_time', 'datePublished', 'pubdate', 'date')
    m = re.search(r'(20\d\d)[-./](\d{1,2})[-./](\d{1,2})', d or '') or re.search(r'(?:입력|등록|기사입력|발행)\s*[:：]?\s*(20\d\d)[-./](\d{1,2})[-./](\d{1,2})', page or '')
    return '%s.%02d.%02d' % (m.group(1), int(m.group(2)), int(m.group(3))) if m else ''


def read_article(page, url):
    title = _meta(page, 'og:title', 'twitter:title') or ' '.join(html.unescape((re.search(r'(?is)<title[^>]*>(.*?)</title>', page or '') or [None, ''])[1]).split())
    return {'url': url, 'title': title[:200], 'media': _meta(page, 'og:site_name', 'twitter:site').lstrip('@')[:40], 'date': article_date(page), 'text': article_text(page)}


def host(url): return re.sub(r'^www\.', '', urllib.parse.urlparse(url or '').hostname or '')


NAVER = {'hub': ('https://naverapihub.apigw.ntruss.com/search/v1/news', 'X-NCP-APIGW-API-KEY-ID', 'X-NCP-APIGW-API-KEY'),   # 네이버 클라우드 API HUB
         'dev': ('https://openapi.naver.com/v1/search/news.json', 'X-Naver-Client-Id', 'X-Naver-Client-Secret')}         # 네이버 개발자센터 검색 API


NAVER_ERR = {'msg': ''}
NAVER_LINK = {}  # 언론사 기사 주소 → 같은 기사의 네이버 뉴스 주소 (언론사 페이지를 못 읽으면 여기서 읽음)
_NAVER_GAP = {'lock': threading.Lock(), 'last': 0.0}


def _naver_wait():
    """네이버 검색은 1초에 10번쯤까지라, 물어보는 사이를 0.12초 이상 띄움 (하루 25,000번 무료라 횟수는 걱정 없음)"""
    with _NAVER_GAP['lock']:
        gap = _NAVER_GAP['last'] + 0.12 - time.monotonic()
        if gap > 0: time.sleep(gap)
        _NAVER_GAP['last'] = time.monotonic()


def _naver_get(cfg, kind, q, display, sort):
    """네이버에 한 번 물어봄 → (상태 코드, 답 dict). 1초에 너무 많이 물어 잠깐 막히면(429) 쉬었다 다시."""
    base, hid, hsec = NAVER[kind]
    req = urllib.request.Request(base + '?' + urllib.parse.urlencode({'query': q, 'display': display, 'sort': sort}),
                                 headers={hid: cfg['naver_id'], hsec: cfg['naver_secret']})
    for n in range(4):
        _naver_wait()
        try:
            with urllib.request.urlopen(req, timeout=10) as r: return 200, json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            if e.code == 429 and n < 3: time.sleep(0.8 * (n + 1)); continue
            try: body = json.loads(e.read().decode('utf-8') or '{}')
            except (ValueError, OSError): body = {}
            return e.code, body if isinstance(body, dict) else {}
        except (urllib.error.URLError, OSError, ValueError): return 0, {}
    return 429, {}


def naver_news(cfg, q, display=10, sort='sim'):
    """네이버 뉴스 검색 [{title,url,summary,date(YYYY-MM-DD)}]. 키가 없거나 실패하면 []. 테스트에서 바꿔 끼운다.
    키 종류(개발자센터 / API HUB)를 잘못 골라 거절(401)되면 다른 종류로 한 번 더 물어보고, 되면 그 종류를 NAVER_ERR['kind']에 남김."""
    if not (cfg.get('naver_id') and cfg.get('naver_secret')): return []
    kind = NAVER_ERR.get('kind') or (cfg.get('naver_kind') if cfg.get('naver_kind') in NAVER else 'dev')
    st, res = _naver_get(cfg, kind, q, display, sort)
    if st in (401, 403) and not NAVER_ERR.get('kind'):
        other = 'hub' if kind == 'dev' else 'dev'
        st2, res2 = _naver_get(cfg, other, q, display, sort)
        if st2 == 200: st, res = st2, res2; NAVER_ERR['kind'] = other
    if st != 200:
        why = ' · '.join(str(x) for x in (res.get('errorMessage') or res.get('message') or (res.get('error') or {}).get('message', ''), res.get('errorCode') or (res.get('error') or {}).get('errorCode', '')) if x)
        NAVER_ERR['msg'] = ({401: '네이버가 키를 받아 주지 않았어요', 403: '네이버 앱에 검색 API 권한이 없어요', 429: '네이버가 잠깐 막았어요. 1분 뒤 새로고침해 주세요',
                             0: '네이버에 연결하지 못했어요 (인터넷 확인)'}.get(st, f'네이버 검색 오류 {st}') + (f' (네이버: {why})' if why else '') + (f' [{st}]' if st else ''))
        return []
    NAVER_ERR['msg'] = ''
    clean = lambda t: ' '.join(html.unescape(re.sub(r'<[^>]+>', '', t or '')).split())
    out = []
    for it in res.get('items') or []:
        url = it.get('originallink') or it.get('link') or ''
        if not re.match(r'https?://', url): continue
        try: day = email.utils.parsedate_to_datetime(it.get('pubDate', '')).date().isoformat()  # 윈도우 한국어 설정에서도 되게 (strptime %a·%b는 언어를 탐)
        except (TypeError, ValueError, IndexError): day = ''
        if 'n.news.naver.com' in (it.get('link') or ''): NAVER_LINK[url] = it['link']
        out.append({'title': clean(it.get('title')), 'url': url, 'summary': clean(it.get('description')), 'date': day})
    return out


def search_words(title):
    """다른 기사를 찾을 검색어: 제목에서 괄호·따옴표·언론사 꼬리 빼고 앞쪽 말 몇 개"""
    t = re.sub(r'\[[^\]]*\]|\([^)]*\)|<[^>]*>|[\'"“”‘’…·|]|\s[-–|]\s.*$', ' ', title or '')
    return ' '.join([w for w in t.split() if len(w) > 1][:5])


def find_others(cfg, art, n=2):
    """같은 뉴스를 다룬 다른 언론사 기사 n개 {media,title,url,text,via}.
    네이버 키가 있으면 네이버 뉴스 검색을 먼저, 모자라면 Claude 웹 검색으로 채움. Claude 쪽은 실제 검색 결과에 있던 주소만 열어 읽음."""
    out = []
    def add(url, media, title, via):
        if len(out) >= n or host(url) in (host(art['url']), '') or any(host(url) == host(x['url']) for x in out): return  # 같은 언론사는 뺌
        page = fetch_page(url); body = article_text(page, 4000) if page else ''
        if len(body) >= 150: out.append({'media': (media or _meta(page, 'og:site_name') or host(url))[:40], 'title': title[:200], 'url': url, 'text': body, 'via': via})
    for it in naver_news(cfg, search_words(art['title'])): add(it['url'], '', it['title'], '네이버')
    if len(out) < n and cfg.get('web_search', 1) and cfg.get('key'):  # 키가 없으면(붙여넣기 방식) 네이버로만
        q = (f"이 한국 뉴스와 같은 사건을 보도한 '다른 언론사' 기사 {n}개를 웹 검색으로 찾아 줘 ({host(art['url'])} 기사는 빼고).\n"
             f"제목: {art['title']}\n매체: {art['media']} · 날짜: {art['date']}\n본문 앞부분: {art['text'][:600]}\n\n"
             '답은 JSON만: {"others": [{"url": "...", "media": "언론사 이름", "title": "기사 제목"}]}')
        try: text, seen = search(cfg, q)
        except RuntimeError: text, seen = '', []
        real = {r['url'] for r in seen}
        for o in json_in(text).get('others') or []:
            if str(o.get('url') or '') in real: add(str(o['url']), str(o.get('media') or ''), str(o.get('title') or ''), 'Claude 웹 검색')  # 지어낸 주소는 뺌
    return out


# 네이버 검색 API는 '경제 섹션'을 바로 고를 수 없어서, 경제 섹션 전체(생활경제·유통·금융·부동산·산업·경제일반)를 덮는 검색어로 찾는다.
# 묶음끼리는 똑같이: 소비자 → 유통 → 금융·부동산 → 이슈 → 경제 → … 돌아가며 하나씩 (카드뉴스는 경제형·이슈형 두 공식으로만)
NEWS_GROUPS = [
    ('소비자', ['소비자 피해', '한국소비자원', '환불 분쟁', '공정위 과징금', '리콜', '소비자 주의보', '피해구제', '요금 인상']),
    ('유통', ['유통업계', '편의점', '대형마트', '이커머스', '배달앱', '백화점', '식품 가격', '외식 가격', '할인 행사', '홈쇼핑']),
    ('금융·부동산', ['금리', '대출', '예금', '카드 혜택', '보험료', '전세', '월세', '아파트 분양']),
    ('이슈', ['개인정보 유출', '서비스 장애', '먹통', '집단소송', '불매', '논란 해명', '과태료', '소비자 분통']),
    ('경제', ['물가', '공공요금', '전기요금', '통신비', '기름값', '환율', '세금', '연말정산', '최저임금', '고용', '소상공인', '수출', '자동차', '항공권']),
]
# 카드뉴스로 안 쓰는 기사: 퀴즈 정답·운세·로또·부고·인사·포토, 그리고 정치(중립 원칙)
JUNK = re.compile(r'정답|퀴즈|운세|로또|부고|별세|\[인사\]|인사\s*\]|\[포토|포토\]|\[사진|오늘의\s*날씨|민주당|국민의힘|대통령|국회의원|여당|야당|탄핵|선거|총선|대선|지방선거|북한')
QUERY_GROUP = {q: g for g, qs in NEWS_GROUPS for q in qs}
DAILY_QUERIES = [qs[i] for i in range(max(len(qs) for _, qs in NEWS_GROUPS)) for _, qs in NEWS_GROUPS if i < len(qs)]  # 묶음을 번갈아


RANK_SYSTEM = """너는 소비자 경제 인스타 카드뉴스 '소보루'의 기획자야. 캐러셀 레퍼런스북의 소재 고르기 체크 3개로 오늘 만들 기사를 고른다.
1 공감 — 읽자마자 "어, 내 얘기네?" 싶은가 (내 월급·통장·장바구니·생활에 닿나). 남 얘기·신기하기만 한 건 안 고름.
2 관심 — 이미 많은 사람이 보는 큰 뉴스인가 (여러 언론이 다루는 사건, 많이 쓰는 서비스·회사·가격).
3 궁금 — 제목만 봐도 다음이 궁금한가. 제목에 결론이 다 나온 건 안 고름.
그리고 경제형(기업·돈·가격·금리·유통의 흐름) 또는 이슈형(화제·논란·사건)으로 카드뉴스를 만들 수 있어야 한다. 정치·선거·참사·연예는 고르지 않는다.
셋을 모두 통과한 것만, 좋은 순서로 최대 8개. 답은 JSON만."""
RANK_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['picks'],
               'properties': {'picks': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False, 'required': ['i', 'kind', 'why'],
                   'properties': {'i': {'type': 'integer'}, 'kind': {'type': 'string', 'enum': ['economy', 'issue']}, 'why': {'type': 'string'}}}}}}


def rank_news(cfg, items):
    """후보 기사를 공감·관심·궁금 체크로 골라 좋은 순서로 (Claude 키가 있을 때). 키가 없거나 실패하면 그대로."""
    if not cfg.get('key') or len(items) < 2: return items
    lst = '\n'.join(f"{i}. [{it.get('topic', '')}] {it['title']} — {it.get('summary', '')[:90]}" for i, it in enumerate(items[:30]))
    try: res = claude(cfg, RANK_SYSTEM, '오늘 후보 기사:\n' + lst, RANK_SCHEMA, 2000, effort='low')
    except RuntimeError: return items
    picked = [items[p['i']] for p in res.get('picks') or [] if isinstance(p.get('i'), int) and 0 <= p['i'] < len(items[:30])]
    out = []
    for x in picked:
        if x not in out: out.append(x)
    return out or items


def find_news(cfg, n, avoid=()):
    """알아서 고르기·매일 자동: 최근 이틀 네이버 뉴스(경제 섹션 전체)에서 공감·관심·궁금 체크로 고른 기사 주소. 모자라면 Claude 웹 검색."""
    urls = [it['url'] for it in rank_news(cfg, news_list(cfg, avoid, k=30))]
    if len(urls) < n + 2 and cfg.get('web_search', 1) and cfg.get('key'):
        q = (f'오늘은 {datetime.date.today().isoformat()}이야. 최근 이틀 안에 나온 한국 소비자 권익 뉴스 기사 {n + 3}개를 웹 검색으로 찾아 줘. '
             f'주제: {DAILY_TOPICS}. 고르는 기준: 읽자마자 "내 얘기네" 싶은 것(공감), 많이 보거나 댓글이 많은 것(관심), 제목만 봐도 다음이 궁금한 것(궁금). '
             '서로 다른 사건으로, 언론사 기사 페이지 주소(목록·포털 첫 화면 말고)만.\n'
             '답은 JSON만: {"news": [{"url": "...", "title": "기사 제목"}]}')
        try: text, seen = search(cfg, q, max_uses=5)
        except RuntimeError: text, seen = '', []
        real = {r['url'] for r in seen}
        for o in json_in(text).get('news') or []:
            url = str(o.get('url') or '')
            if url in real and url not in avoid and url not in urls: urls.append(url)
    return urls[:n + 3]


def news_list(cfg, avoid=(), k=40):
    """첫 화면 '오늘의 뉴스': 네이버 뉴스에서 최근 이틀 경제 섹션 전체를 묶음끼리 똑같이, 검색어마다 고르게 섞어
    [{title,url,summary,date,host,topic,group}]. 검색어가 많아서 한꺼번에 물어본다."""
    from concurrent.futures import ThreadPoolExecutor
    since = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
    with ThreadPoolExecutor(4) as ex: found = list(ex.map(lambda q: naver_news(cfg, q, display=5, sort='date'), DAILY_QUERIES))
    per = [[dict(it, topic=q, group=QUERY_GROUP[q], host=urllib.parse.urlparse(it['url']).netloc.removeprefix('www.')) for it in lst
            if it['date'] >= since and it['url'] not in avoid and not JUNK.search(it['title'])] for q, lst in zip(DAILY_QUERIES, found)]
    out, seen = [], set()
    for i in range(5):  # 검색어를 돌아가며 하나씩 (같은 사건은 제목 앞부분으로 거름)
        for lst in per:
            if i < len(lst):
                it = lst[i]; key = re.sub(r'\W', '', it['title'])[:14]
                if it['url'] in seen or key in seen: continue
                seen.update((it['url'], key)); out.append(it)
    return out[:k]


# ---- 검사 -----------------------------------------------------------------------
NUM = re.compile(r'\d[\d,]*(?:\.\d+)?')


def numbers(text):
    """글 속 숫자 (1,200 → 1200, 0.10 → 0.1)"""
    out = set()
    for m in NUM.finditer(text or ''):
        v = m.group().replace(',', '').rstrip('.')
        if '.' in v: v = v.rstrip('0').rstrip('.')
        out.add(v)
    return out


def odd_numbers(text, sources):
    """원고에 있는데 기사(들)에 없는 숫자. 1372 같은 안내 번호는 통과."""
    have = set(ALWAYS_OK)
    for s in sources: have |= numbers(s)
    return sorted(numbers(text) - have, key=lambda x: (len(x), x))


def copied(text, source, run=COPY_RUN):
    """원고 줄 중 기사와 띄어쓰기 빼고 run자 넘게 연달아 같은 줄"""
    src = re.sub(r'\s+', '', source or ''); out = []
    for line in (text or '').splitlines():
        flat = re.sub(r'\s+', '', line)
        if len(flat) >= run and any(flat[i:i + run] in src for i in range(len(flat) - run + 1)): out.append(line.strip()[:200])
    return out


def card_text(d):
    """검사할 원고 글 전부 (줄마다 하나)"""
    covers = d.get('covers') or [{}]
    pick = covers[min(d.get('cover_pick', 0), len(covers) - 1)]
    lines = [d.get('topic', ''), pick.get('line1', ''), pick.get('line2', '')] + [t['text'] for t in d.get('cover_tags') or []]
    for c in d.get('cards') or []:
        lines += [c.get('kicker', ''), c.get('title', '').replace('\n', ' '), c.get('body', '')] + [t['text'] for t in c.get('tags') or []]
    lines.append(d.get('share_line', '') if d.get('end') == 'share' else '')
    return '\n'.join(x for x in lines + list(d.get('tips') or []) + (d.get('caption') or '').splitlines() if x and x.strip())


def run_checks(d, facts):
    """올리기 전 10초 체크리스트(저작권 기준표 Ch10). [{label, ok, note}]. ok: True 통과 / False 걸림 / None 사람이 눈으로 볼 것."""
    text = card_text(d); covers = d.get('covers') or []
    others = facts.get('others') or []
    odd = odd_numbers(text, [facts.get('text', '')] + [o.get('text', '') for o in others])
    copy = copied(text, facts.get('text', ''))
    bait = sorted({w for c in covers for w in BAIT if w in c.get('line1', '') + c.get('line2', '')})
    engage = sorted({w for w in ASK_ENGAGE if w in text})
    pol = sorted({w for w in POLITICS if w in text})
    sl = slots(d)
    arts = [x['photo'] for _, _, x in sl]
    up = [n for n, _, x in sl if x['photo'] and x.get('src') == 'upload']
    real = [n for n, _, x in sl if x['photo'] and x.get('src') == 'openai' and x.get('style') == 'photo']  # 진짜 사진처럼 보이는 AI 이미지 (ChatGPT 사진)
    src_ok = bool((d.get('source') or {}).get('media') and (d.get('source') or {}).get('date'))
    need = d.get('confirm_needed') or []
    return [
        {'label': '이미지: 기사 사진 없이 새로 만들었나', 'ok': None if not all(arts) or up else True,
         'note': "이미지가 빠진 장이 있어요. AI로 만들거나 새로 만든 이미지를 올려 주세요" if not all(arts) else
                 ('올린 이미지가 AI로 새로 만든 것(기사 사진·남의 사진 아님)인지 봐 주세요' if up else '모든 이미지를 AI로 새로 만들었어요')},
        {'label': "인스타: 실제 사진 같은 AI 이미지면 'AI 레이블' 켜기", 'ok': None if real else True,
         'note': "사진 스타일 AI 이미지가 있어요. 인스타에 올릴 때 마지막 화면 '고급 설정 → AI 레이블 추가'를 켜 주세요 (캡션에는 안 적어도 돼요)" if real else '사진 같은 AI 이미지가 없어요 (일러스트는 안 켜도 돼요)'},
        {'label': '사람: 실존 인물 얼굴이 없나', 'ok': None, 'note': '그림에 실존 인물·기업 로고가 없는지 눈으로 한 번 봐 주세요'},
        {'label': '글: 기사 문장을 옮기지 않았나', 'ok': not copy, 'note': '기사와 너무 비슷한 줄: ' + ' / '.join(copy[:3]) if copy else '기사 문장과 겹치는 줄이 없어요'},
        {'label': '사실: 기사 2개 이상에서 확인했나', 'ok': bool(others) and not need,
         'note': (f'다른 기사 {len(others)}개와 맞춰 봤어요' if others else '같은 뉴스를 다룬 다른 기사를 찾지 못했어요') + (' · 확인할 것: ' + ' / '.join(need[:3]) if need else '')},
        {'label': '숫자: 기사에 있는 숫자만 썼나', 'ok': not odd, 'note': '기사에서 못 찾은 숫자: ' + ', '.join(odd[:12]) if odd else '모든 숫자가 기사에 있어요'},
        {'label': '표지: 낚시말 없이 본문에 답이 있나', 'ok': not bait and len(covers) == 5, 'note': '낚시말: ' + ', '.join(bait) if bait else (f'표지 문구 후보가 {len(covers)}개예요' if len(covers) != 5 else '낚시말이 없어요')},
        {'label': '마지막 장: 참여 유도 대신 저장 유도인가', 'ok': not engage, 'note': '참여 유도 말: ' + ', '.join(engage) if engage else ('공유형 한 줄로 끝나요' if d.get('end') == 'share' else '저장 유도로 끝나요')},
        {'label': '주제: 정치·참사를 자극적으로 다루지 않았나', 'ok': None if pol else True, 'note': '정치 말이 있어요(' + ', '.join(pol) + '). 중립인지, 선거 90일 전~선거일이 아닌지 봐 주세요' if pol else '정치 소재가 아니에요'},
        {'label': '글꼴: 상업 이용 가능한 글꼴인가', 'ok': True, 'note': 'Pretendard (SIL Open Font License)'},
        {'label': "캡션: '출처: 매체명·날짜'가 있나", 'ok': src_ok, 'note': '출처 매체명·날짜를 채워 주세요' if not src_ok else '캡션 끝에 출처와 링크를 붙여요'},
    ]


def status_of(checks): return 'ready' if all(c['ok'] is not False for c in checks) else 'check'


# ---- 원고 다듬기 ------------------------------------------------------------------
def tidy(raw, art):
    """Claude 원고 → 화면이 그리는 카드 데이터 (길이·개수 맞추기)"""
    clip = lambda s, n: ' '.join(str(s or '').split())[:n]
    tags = lambda xs: [{'text': clip(t.get('text'), 16), 'dir': t.get('dir') if t.get('dir') in ARROWS else ''} for t in (xs or [])[:2] if clip(t.get('text'), 16)]
    cards = []
    for c in (raw.get('cards') or [])[:4]:
        title = '\n'.join(clip(x, 18) for x in str(c.get('title') or '').split('\n')[:2] if x.strip())
        cards.append({'kicker': clip(c.get('kicker'), 30), 'title': title, 'body': clip(c.get('body'), 160), 'tags': tags(c.get('tags')), 'scene': clip(c.get('scene'), 400)})
    return {'kind': raw.get('kind') if raw.get('kind') in KINDS else 'economy', 'topic': clip(raw.get('topic'), 60), 'emoji': clip(raw.get('emoji'), 4),
            'covers': [{'line1': clip(c.get('line1'), 18), 'line2': clip(c.get('line2'), 18)} for c in (raw.get('covers') or [])[:5]], 'cover_pick': 0,
            'cover_tags': tags(raw.get('cover_tags')), 'cover_scene': clip(raw.get('cover_scene'), 400), 'cards': cards,
            'tips': [clip(t, 40) for t in (raw.get('tips') or [])[:3]], 'end': 'save', 'share_line': clip(raw.get('share_line'), 30) or '꼭 필요한 친구한테 보내 주세요', 'caption': str(raw.get('caption') or '').strip()[:1500],
            'hashtags': [re.sub(r'[#\s]', '', h)[:20] for h in (raw.get('hashtags') or [])[:8] if re.sub(r'[#\s]', '', h)],
            'source': {'media': clip(raw.get('source_media') or art.get('media'), 30), 'date': clip(raw.get('source_date') or art.get('date'), 12), 'title': art.get('title', ''), 'url': art.get('url', '')},
            'facts_used': [clip(f, 200) for f in (raw.get('facts_used') or [])[:12]], 'confirm_needed': [clip(f, 200) for f in (raw.get('confirm_needed') or [])[:6]]}


def caption_full(d):
    """인스타에 붙여 넣을 캡션: 본문 + 출처 줄(저작권 기준표 Ch3) + 해시태그"""
    s = d.get('source') or {}
    src = ' '.join(x for x in ('출처:', s.get('media') or '기사', s.get('date') or '', '보도') if x) + ('\n' + s['url'] if s.get('url') else '')
    return '\n\n'.join(x for x in [d.get('caption', '').strip(), src, ' '.join('#' + h for h in d.get('hashtags') or [])] if x)


# ---- 이미지 (ChatGPT 또는 Claude) ---------------------------------------------------------
# ChatGPT: OpenAI 이미지 API (platform.openai.com의 API 키, ChatGPT 구독과는 따로 결제) → 사진·일러스트 JPG
# Claude: 사진은 못 만들고, 일러스트를 SVG(벡터 그림)로 직접 그림 → 설정의 Claude API 키로
IMG_ENGINES = (('auto', '자동 — 사진은 ChatGPT, 일러스트는 Claude (기본)'), ('openai', 'ChatGPT (OpenAI 이미지) — 사진·일러스트 모두'), ('claude', 'Claude — 모두 Claude가 그림 (사진 장은 사실적인 그림)'))
OPENAI_MODEL = 'gpt-image-1'
# 이미지 스타일: 사진 / 일러스트. 일러스트는 소보루 색(주황·크림·갈색)
STYLES = {'photo': ('사진', 'Photorealistic editorial news photo for a Korean consumer news card, natural light, clean composition, portrait 3:4, main subject in the lower half, calm uncluttered upper third (headline text goes there). Scene: {scene}. '),
          'illust': ('일러스트', 'Flat vector illustration for a Korean consumer news card, clean geometric shapes, soft shading, warm palette of orange #EF920E, '
                     'cream #F7D49E, dark brown #652D1C with sky blue and white accents, portrait 3:4, main subject in the lower half, calm uncluttered upper third, friendly and simple. Scene: {scene}. ')}
SAFE = 'No text, no letters, no numbers, no logos, no brand names, no real or famous people; people only from behind, hands only, or out of focus.'
MIXES = {'mix': ('photo', 'illust'), 'photo': ('photo', 'photo'), 'illust': ('illust', 'illust')}  # 기본 스타일: (표지, 본문)


def slots(d, mix='mix'):
    """이미지 자리마다 [(이름, 장면 설명, 자리 dict)]. 자리: {'photo': 파일 이름, 'src': 'openai'|'claude'|'upload', 'style': 'photo'|'illust'}
    mix: 자리가 처음 생길 때의 기본 스타일 (설정 '기본 이미지 스타일')"""
    cover, body = MIXES.get(mix, MIXES['mix'])
    d.setdefault('cover_img', {'photo': '', 'style': cover}).setdefault('style', cover)
    out = [('cover', d.get('cover_scene') or d.get('topic', ''), d['cover_img'])]
    for i, c in enumerate(d.get('cards') or []):
        c.setdefault('img', {'photo': '', 'style': body}).setdefault('style', body)
        out.append((f'card{i}', c.get('scene') or c.get('title', ''), c['img']))
    return out


def photo_prompt(scene, style='photo'):
    """이미지 AI에 줄 설명 (사진/일러스트). ChatGPT 앱 등에 직접 붙여 넣어도 됨"""
    return STYLES.get(style, STYLES['photo'])[1].format(scene=scene or 'a calm everyday consumer scene') + SAFE


def img_ready(cfg):
    """이미지를 만들 수 있는 키가 있나 (고른 AI 기준, 자동이면 둘 중 하나)"""
    eng = cfg.get('img_engine', 'auto')
    if eng == 'openai': return bool(cfg.get('openai_key'))
    if eng == 'claude': return bool(cfg.get('key'))
    return bool(cfg.get('openai_key') or cfg.get('key'))


def make_image(cfg, scene, style='photo'):
    """장면 설명 → (이미지 바이트, 'jpg'|'svg', 만든 AI 'openai'|'claude'). 테스트에서 바꿔 끼운다.
    자동: 사진 장은 ChatGPT(진짜 사진처럼), 일러스트 장은 Claude. 키가 하나만 있으면 그쪽으로."""
    eng = cfg.get('img_engine', 'auto')
    if eng == 'auto': eng = 'openai' if cfg.get('openai_key') and (style == 'photo' or not cfg.get('key')) else 'claude'
    if eng == 'claude': return claude_svg(cfg, scene, realistic=style == 'photo'), 'svg', 'claude'
    return openai_image(cfg, scene, style), 'jpg', 'openai'


def openai_image(cfg, scene, style='photo'):
    """OpenAI 이미지 API로 세로 이미지 (PNG/JPEG 바이트)"""
    import base64
    if not cfg.get('openai_key'): raise RuntimeError("ChatGPT(OpenAI) API 키가 없어요. '설정'에서 넣어 주세요")
    body = json.dumps({'model': cfg.get('openai_model') or OPENAI_MODEL, 'prompt': photo_prompt(scene, style), 'size': '1024x1536', 'n': 1}).encode()
    req = urllib.request.Request('https://api.openai.com/v1/images/generations', data=body, method='POST',
                                 headers={'Authorization': 'Bearer ' + cfg['openai_key'], 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=240) as r: res = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try: err = (json.loads(e.read().decode('utf-8') or '{}').get('error') or {})
        except (ValueError, OSError): err = {}
        msg, code = str(err.get('message') or '')[:160], str(err.get('code') or err.get('type') or '')
        if e.code == 401: raise RuntimeError('ChatGPT(OpenAI) API 키가 맞지 않아요 (설정에서 다시 넣어 주세요)')
        if 'quota' in code or 'billing' in code or 'quota' in msg.lower(): raise RuntimeError('OpenAI API 잔액이 없어요. ChatGPT 구독과 별개로 platform.openai.com → Billing에서 충전해야 해요')
        if e.code == 403: raise RuntimeError('OpenAI가 이 이미지 모델을 막았어요: ' + (msg or '조직 인증(Verify organization)이 필요할 수 있어요'))
        if e.code == 429: raise RuntimeError('OpenAI 요청이 많아 잠깐 막혔어요. 조금 뒤 다시 해 주세요')
        if 'safety' in msg.lower() or 'moderation' in code: raise RuntimeError('OpenAI가 안전 기준에 걸린다고 이미지를 만들지 않았어요')
        raise RuntimeError(f'OpenAI 이미지 오류 ({e.code}): {msg}')
    except (urllib.error.URLError, OSError, ValueError) as e: raise RuntimeError(f'OpenAI에 연결하지 못했어요 ({type(e).__name__})')
    item = (res.get('data') or [{}])[0]
    if item.get('b64_json'): return base64.b64decode(item['b64_json'])
    if str(item.get('url', '')).startswith('https://'):
        with urllib.request.urlopen(item['url'], timeout=60) as r: return r.read(25_000_000)
    raise RuntimeError('OpenAI 답에 이미지가 없어요')


SVG_SYSTEM = """You are an illustrator for SOBORU, a Korean consumer-news Instagram account. Draw ONE flat vector illustration as a single SVG.
Rules: <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1350">, portrait card. Fill the whole canvas with a background.
Clean geometric shapes, soft gradients allowed, warm palette: orange #EF920E, cream #F7D49E / #FFF6E6, dark brown #652D1C, with sky blue and white accents.
Main subject in the lower 60%; keep the top third calm and simple (headline text is placed there later).
Absolutely no text, letters, numbers, logos, brand names, real or famous people (people only as simple silhouettes from behind or hands).
Only basic SVG elements (rect, circle, ellipse, path, polygon, line, g, defs, linearGradient, radialGradient, stop). No script, no images, no external links, no filters heavier than a soft blur.
Answer with JSON only: {"svg": "<svg ...>...</svg>"}"""


REAL = ('\nThis slide wants a PHOTO-LIKE look: instead of flat shapes, paint it as realistically as SVG allows — natural perspective and proportions, '
        'layered gradients for light and shadow, soft highlights, depth of field (blurred background shapes), realistic materials and colors of the actual objects '
        '(not limited to the brand palette). Still no text, no logos, no real people.')


def claude_svg(cfg, scene, realistic=False):
    """Claude가 그림을 SVG로 직접 그림 (진짜 사진은 못 만듦, realistic이면 빛·그림자를 살린 사실적인 그림) → 안전하게 다듬은 SVG 바이트"""
    if not cfg.get('key'): raise RuntimeError("Claude API 키가 없어요. '설정'에서 넣어 주세요")
    res = claude(cfg, SVG_SYSTEM + (REAL if realistic else ''), 'Scene: ' + (scene or 'a calm everyday consumer scene'), {'type': 'object', 'additionalProperties': False, 'required': ['svg'], 'properties': {'svg': {'type': 'string'}}}, 16000)
    return clean_svg(res.get('svg', ''))


def clean_svg(text, limit=400_000):
    """SVG 글 → 안전한 SVG 바이트 (스크립트·바깥 링크·이벤트 속성 제거, 크기 고정). 그림이 아니면 ValueError."""
    t = str(text or '')
    m = re.search(r'(?is)<svg\b.*</svg>', t)
    if not m or len(m.group(0)) > limit: raise ValueError('Claude가 그림(SVG)을 제대로 주지 않았어요. 다시 해 주세요')
    t = m.group(0)
    t = re.sub(r'(?is)<(script|foreignObject|iframe|object|embed|image|use|a|style)\b.*?(</\1>|/>)', '', t)
    t = re.sub(r'(?is)<(script|foreignObject|iframe|object|embed|image|use|a|style)\b[^>]*>', '', t)
    t = re.sub(r'(?i)\s(on\w+|href|xlink:href|src)\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', '', t)
    t = re.sub(r'(?i)url\(\s*([^#)\s][^)]*)\)', 'none', t)  # 바깥 주소는 지우고 #그라데이션만 남김
    if re.search(r'(?i)javascript:|<!entity|<!doctype', t): raise ValueError('그림에 쓸 수 없는 내용이 있어요')
    t = re.sub(r'(?is)^<svg\b[^>]*>', '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1350" width="1080" height="1350" preserveAspectRatio="xMidYMid slice">', t, count=1)
    return t.encode('utf-8')


def clean_photo(raw, max_side=1600):
    """올린·받은 사진 → 다시 저장한 JPEG 바이트 (사진 속 위치 정보 등은 지움). 사진이 아니면 ValueError."""
    import io
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(raw)); im.verify(); im = Image.open(io.BytesIO(raw))
        from PIL import ImageOps
        im = ImageOps.exif_transpose(im).convert('RGB')
    except Exception: raise ValueError('사진 파일이 아니에요 (JPG·PNG·WEBP)')
    im.thumbnail((max_side, max_side))
    out = io.BytesIO(); im.save(out, 'JPEG', quality=88, optimize=True)
    return out.getvalue()


# ---- 만들기 ---------------------------------------------------------------------
def given_article(text, title='', media='', date='', url=''):
    """직접 붙여 넣은 기사 글 → 기사 자료 (링크 없이도 됨)"""
    lines = [' '.join(x.split()) for x in str(text or '').splitlines()]
    body = '\n'.join(x for x in lines if x)[:9000]
    first = next((x for x in lines if x), '')
    return {'url': (url or '').strip() if re.match(r'https?://', (url or '').strip()) else '', 'title': (title or first)[:200].strip(),
            'media': (media or '')[:40].strip(), 'date': (date or '')[:12].strip(), 'text': body}


def read(cfg, url, art=None):
    """뉴스 링크(또는 붙여 넣은 기사 art) → ((기사, 다른 기사들, 사실 자료), '') 또는 (None, 이유)"""
    if art is None:
        url = (url or '').strip()
        if not re.match(r'https?://', url): return None, '뉴스 링크(https://로 시작)를 넣거나 기사 글을 붙여 넣어 주세요'
        page = fetch_page(url)
        art = read_article(page, url) if page else {}
        if len(art.get('text', '')) < 200 and NAVER_LINK.get(url):  # 언론사가 막으면 네이버 뉴스에 실린 같은 기사로 (출처는 언론사 주소 그대로)
            page = fetch_page(NAVER_LINK[url]); nav = read_article(page, url) if page else {}
            if len(nav.get('text', '')) >= 200:
                media = re.split(r'\s*\|\s*', _meta(page, 'og:article:author') or '')[0] if page else ''
                art = dict(nav, media=media if media and '네이버' not in media else (art.get('media') or host(url)), title=art.get('title') or nav['title'])
        if len(art.get('text', '')) < 200: return None, '기사 본문을 읽지 못했어요. 기사 글을 직접 붙여 넣어 주세요'
    elif len(art.get('text', '')) < 100: return None, '붙여 넣은 기사 글이 너무 짧아요'
    url = art.get('url', '')
    others = find_others(cfg, art)  # 사실 확인을 못 해도 원고는 쓰고 '확인 필요'로 남김
    return (art, others, {'title': art['title'], 'media': art['media'], 'date': art['date'], 'url': url, 'text': art['text'], 'others': others}), ''


def write_request(art, others):
    """Claude에게 줄 기사 자료 글"""
    return (f"[기사] {art['title']}\n매체: {art['media'] or '(모름)'} · 날짜: {art['date'] or '(모름)'}\n\n{art['text']}\n\n"
            + ''.join(f"[같은 뉴스, 다른 기사 {i + 1}] {o['media']} · {o['title']}\n{o['text'][:2500]}\n\n" for i, o in enumerate(others))
            + ('' if others else '[다른 기사] 찾지 못했어요. 한 기사에만 있는 사실은 confirm_needed에 적어 주세요.\n'))


def make(cfg, url, art=None):
    """뉴스 링크(또는 붙여 넣은 기사) → {'status': 'made', 'data', 'facts', 'checks'} 또는 {'status': 'skip'|'error', 'reason'} (Claude API 키로 자동)"""
    if not cfg.get('key'): return {'status': 'skip', 'reason': "Claude API 키가 없어요. 'claude.ai에 붙여넣기'나 '직접 쓰기'를 고르거나, '설정'에서 키를 넣어 주세요"}
    got, why = read(cfg, url, art)
    if not got: return {'status': 'skip', 'reason': why}
    art, others, facts = got
    try:
        d = tidy(claude(cfg, WRITE_SYSTEM, write_request(art, others), WRITE_SCHEMA, 32000), art)
        if len(d['covers']) < 5 or len(d['cards']) < 2: raise RuntimeError('원고가 모자라게 왔어요 (표지 5개·본문 2장 이상)')
        note = ''
    except RuntimeError as e: return {'status': 'error', 'reason': str(e)}
    return {'status': 'made', 'data': d, 'facts': facts, 'checks': run_checks(d, facts), 'reason': note}


# ---- 키 없이: claude.ai(구독) 채팅에 붙여 넣는 방식 ------------------------------------------
# 프로그램이 요청 글을 만들고 → 사람이 claude.ai에 붙여 넣고 → Claude 답(JSON)을 다시 붙여 넣으면 같은 검사·카드로 이어짐
def _skeleton(schema):
    """JSON 모양 예시 (스키마에서)"""
    t = schema.get('type')
    if t == 'object': return {k: _skeleton(v) for k, v in schema['properties'].items()}
    if t == 'array': return [_skeleton(schema['items'])]
    return '…' if t == 'string' else None


def paste_prompt(art, others):
    """claude.ai에 붙여 넣을 원고 요청 글 (규칙 + 기사 + 답 모양)"""
    return (WRITE_SYSTEM + '\n\n[답하는 법] 설명 없이 아래 모양의 JSON 하나만 ```json 코드 블록으로 답해 줘. covers는 5개, kind는 economy 또는 issue, cards는 정확히 4개(그 kind의 순서대로), tips는 3개.\n```json\n'
            + json.dumps(_skeleton(WRITE_SCHEMA), ensure_ascii=False, indent=1) + '\n```\n\n' + write_request(art, others))


def from_paste(text, art):
    """붙여 넣은 Claude 답 → 카드 데이터. 못 읽으면 ValueError(이유)"""
    raw = json_in(text)
    if not raw.get('covers') or not raw.get('cards'): raise ValueError("Claude 답에서 원고(JSON)를 찾지 못했어요. 답 전체를 복사해서 붙여 넣어 주세요")
    d = tidy(raw, art)
    if len(d['cards']) < 2: raise ValueError('본문이 2장보다 적어요. Claude에게 다시 써 달라고 해 주세요')
    return d


def blank(art):
    """직접 쓰기: 빈 원고 (레퍼런스북 경제 공식: 표지 5개 · 배경·숫자·원인·교훈 · 팁 3개 칸)"""
    return tidy({'topic': '', 'covers': [{'line1': '', 'line2': ''} for _ in range(5)],
                 'cards': [{'kicker': k, 'title': '', 'body': '', 'tags': [], 'scene': ''} for k in KINDS['economy']],
                 'tips': ['', '', ''], 'caption': '', 'hashtags': ['소보루', '소비자권익']}, art) | {'covers': [{'line1': '', 'line2': ''} for _ in range(5)], 'tips': ['', '', '']}
