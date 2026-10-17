"""AI 소비자 상담 새 버전(/ask): 피해 유형 분류 → 키워드+임베딩 검색 → 근거 원문만으로 답 → 코드로 한 번 더 확인.

app.py 맨 끝에서 lawask.install 다음에 install(사이트 모듈의 이름공간)을 불러 붙인다.
- 켜고 끄기: 관리자 > AI 상담 > 'AI 상담 새 버전' (admin_settings의 ask_v2). 기본은 꺼짐이라 배포해도 손님 화면은 지금 그대로(lawask.py).
  꺼져 있어도 관리자는 /ask?v=2 와 실험실(/admin/ask/lab)에서 미리 볼 수 있다. 끄면 바로 예전 화면으로 돌아간다.
- 법령 모음: lawsync.corpus_v2 (기본 모음 + 올린 PDF + Open API 현행 원문 + 분쟁해결기준 별표). triage는 지금 모음·검색 그대로.
- 검색: 질문을 6가지 피해 유형으로 먼저 나누고, 키워드 검색(law_corpus의 bigram BM25)과 임베딩 검색 순위를 섞은 뒤(RRF)
  그 유형의 법령·별표 줄을 앞에 둔다. 후보는 최대 10개, 법률 조문 / 분쟁해결기준(권고) / 생활법령 해설(효력 없음)로 표시.
  맞는 게 없으면 AI를 부르지 않고 '관련 법령을 찾지 못했어요'와 일반 절차·기관만 안내한다(법적 결론 없음).
- 답: 7가지 부분 중 필요한 것만, 700~1,200자. 인터넷 검색 없음. 사실이 모자라면 확인 질문부터. 최근 6턴을 같이 보낸다.
  코드 확인(verify): 후보에 없는 출처는 버리고, 후보에 없는 법 조항·금액·사건번호·판례가 들어간 문장은 빼고 기록한다.
- 개인정보: 전화·이메일·주민번호·계좌·이름 꼴은 AI에 보내기 전에 지운다(companydesk.scrub + mask_personal + 이름 꼴).
- 기록: ask_logs에 지운 뒤의 상담만 30일 보관하고 자동 삭제. 대표 관리자만 보고, 볼 때마다 열람 기록을 남긴다.
- 제보로 자동으로 넘기지 않는다. '업체와의 협의가 어려우신가요?'는 제보하기 화면으로 가는 링크일 뿐(내용을 채우지 않음).
"""
import datetime, json, logging, os, re, secrets, statistics, threading, time
from flask import abort, flash, g, redirect, render_template, request, url_for
from markupsafe import Markup, escape
import lawsync

LOG = logging.getLogger(__name__)
MIN_Q, MAX_Q = 5, 500
PER_HOUR = 10
KEEP_DAYS = 30              # 상담 기록 보관 (지난 것은 지움)
VIEW_KEEP_DAYS = 365        # 열람 기록 보관
HISTORY_TURNS = 6           # 이어 묻기에 같이 보내는 최근 말 수 (질문·답 합쳐)
MAX_CANDS = 10
MAX_GUIDE, MAX_APPX = 2, 4
RRF = 60                    # 순위 섞기 상수
EMB_MIN = 0.35              # 임베딩만으로 후보에 넣는 코사인 하한
TYPE_BOOST = 1.4
# 1백만 토큰당 달러 (답변 모델·임베딩 기본 단가. 바뀌면 환경변수로 고친다)
PRICE = {'in': float(os.getenv('ASK_PRICE_IN', '0.40')), 'out': float(os.getenv('ASK_PRICE_OUT', '1.60')), 'emb': float(os.getenv('ASK_PRICE_EMB', '0.02'))}
PARTS = ['핵심 결론', '관련 법령', '환불·보상 가능성', '증거', '대응 절차', '신고·상담기관', '출처']
PART_EMOJI = {'핵심 결론': '💡', '관련 법령': '⚖️', '환불·보상 가능성': '💰', '증거': '📋', '대응 절차': '✅', '신고·상담기관': '📞', '출처': '📚'}
LABELS = ('법률 조문', '분쟁해결기준(권고)', '생활법령 해설(효력 없음)')
# 피해 유형: (이름, 이모지, 질문 낱말, 앞에 둘 법령 key, 앞에 둘 별표 품목 낱말)
TYPES = [
    ('온라인 쇼핑', '🛒', ('온라인', '인터넷', '쇼핑몰', '택배', '배송', '주문', '반품', '교환', '청약철회', '직구', '해외구매', '홈쇼핑', '라이브커머스', '광고 사진', '옷', '신발', '안 와', '안와'),
     ('ecom', 'ecom_dec', 'easylaw', 'adlabel'), ('통신판매', '전자상거래', '의류', '신발', '택배', '운송')),
    ('식품·외식', '🍜', ('음식', '배달', '식당', '식품', '이물', '벌레', '바퀴벌레', '머리카락', '식중독', '유통기한', '소비기한', '먹', '음료', '카페', '외식', '알레르기', '원산지', '우유'),
     ('food', 'food_rule', 'foodlabel'), ('식료품', '외식', '음식', '식품', '농산', '수산', '축산', '배달')),
    ('구독·서비스 계약', '📝', ('구독', '정기결제', '멤버십', '자동결제', '자동 결제', '무료체험', '해지', '중도해지', '중도 해지', '위약금', '약정', '헬스', 'PT', '필라테스', '요가', '학원', '회원권', '이용권', '개월권', '계속거래', '정수기', '렌탈', '방문판매'),
     ('terms', 'door', 'installment', 'ecom', 'easylaw'), ('체육시설', '헬스', '학원', '콘텐츠', '회원권', '렌탈', '방문판매', '계속거래', '통신')),
    ('생활서비스', '🏠', ('세탁', '수선', '이사', '인테리어', '미용', '네일', '숙박', '호텔', '펜션', '여행', '항공', '결항', '렌터카', '결혼', '사진', '청소', '수리', 'AS', '에이에스', '자동차', '정비', '가전', '노트북', '휴대폰', '화재', '다쳤', '파손', '불이'),
     ('basic', 'kca', 'pl', 'terms'), ('세탁', '이사', '미용', '숙박', '여행', '항공', '자동차', '수리', '인테리어', '사진', '결혼', '가전', '전자', '컴퓨터', '휴대')),
    ('금융·보험', '💳', ('카드', '할부', '대출', '보험', '은행', '이자', '투자', '펀드', '금리', '보험금', '연체', '신용', '항변', '폐업', '설명을'),
     ('fincon', 'installment'), ('보험', '신용카드', '금융', '할부', '대부')),
    ('플랫폼 거래', '🤝', ('중고', '당근', '번개장터', '중고나라', '플랫폼', '오픈마켓', '중개', '개인 간', '개인간', '배달앱', '숙박앱', '앱마켓', '입점'),
     ('ecom', 'easylaw', 'terms'), ('통신판매중개', '중개', '플랫폼')),
]
TYPE_BY_KEY = {k: name for name, _, _, keys, _ in reversed(TYPES) for k in keys}
# 기관 안내 (법적 판단이 아니라 연락처). 피해 유형마다 더 맞는 곳을 앞에
AGENCIES = {'': [('1372 소비자상담센터', '전화 1372 · ccn.go.kr', 'https://www.ccn.go.kr'), ('한국소비자원 피해구제', 'kca.go.kr', 'https://www.kca.go.kr')],
            '온라인 쇼핑': [('전자문서·전자거래분쟁조정위원회', 'ecmc.or.kr', 'https://www.ecmc.or.kr')],
            '플랫폼 거래': [('전자문서·전자거래분쟁조정위원회', 'ecmc.or.kr', 'https://www.ecmc.or.kr')],
            '식품·외식': [('식품안전정보원 불량식품 신고', '전화 1399', 'https://www.foodsafetykorea.go.kr')],
            '금융·보험': [('금융감독원 금융민원', '전화 1332 · fcsc.kr', 'https://www.fcsc.kr')],
            '구독·서비스 계약': [], '생활서비스': []}
STEPS = ['업체에 문자·게시판·메일처럼 기록이 남는 방법으로 원하는 해결(환불·교환·수리 등)을 먼저 요청해요.',
         '주문·계약 내역, 결제 내역, 사진, 업체와 나눈 대화 화면을 모아 두세요.',
         '업체가 응하지 않으면 1372 소비자상담센터에서 상담을 받고, 필요하면 한국소비자원에 피해구제를 신청할 수 있어요.']
EXAMPLES = ['헬스장 6개월권, 두 달 다니고 해지하면 얼마나 돌려받나요?', '주문한 상품이 2주째 안 와요', '배달 음식에서 이물질이 나왔어요',
            '구독 서비스 중도 해지하는데 위약금을 내래요', '받은 옷이 광고 사진이랑 너무 달라요', '중고거래로 산 물건이 설명과 달라요']
TEST_QUESTIONS = ['배달 음식에서 바퀴벌레 같은 이물질이 나왔어요. 환불이나 보상을 받을 수 있나요?', '구독 서비스를 중도 해지하려는데 위약금을 내라고 해요.',
                  '헬스장 6개월권을 끊었는데 두 달 다니고 중도해지하면 환불받을 수 있나요?', '주문한 상품이 2주째 안 와요. 판매자는 연락도 안 받아요.',
                  '온라인에서 산 옷을 받은 지 5일 됐는데 단순 변심으로 반품할 수 있나요?', '받은 상품이 광고 사진과 너무 달라요. 반품할 수 있나요?',
                  '택배가 분실됐는데 택배사와 판매자가 서로 책임을 미뤄요.', '중고거래 앱에서 산 물건이 설명과 달라요. 플랫폼에도 책임이 있나요?',
                  '무료체험이 끝나고 자동결제가 됐어요. 환불받을 수 있나요?', '노트북 무상 수리 기간인데 수리비를 내라고 해요.',
                  '세탁소에 맡긴 코트가 망가져서 돌아왔어요.', '이사 업체가 옮기다가 가구를 파손했어요.',
                  '항공권이 결항됐는데 여행사가 수수료를 떼고 환불해 준대요.', '신용카드 할부로 산 회원권 업체가 폐업했어요. 남은 할부금을 안 낼 수 있나요?',
                  '보험 가입할 때 설명을 제대로 못 들었어요. 계약을 취소할 수 있나요?', '약관에 환불 불가라고 적혀 있으면 정말 환불이 안 되나요?',
                  '식당에서 먹은 음식 때문에 식중독에 걸렸어요.', '방문판매로 계약한 정수기 렌탈을 취소하고 싶어요.',
                  '전기장판에서 불이 나서 다쳤어요. 제조사에 배상받을 수 있나요?', '편의점에서 유통기한이 지난 우유를 팔았어요.']
SYSTEM = ('너는 소보루의 AI 소비자 상담 도우미다. 상담사가 아니라 AI이고, 법률 자문이 아닌 일반 정보를 준다.\n'
          '[근거]\n- 아래 [근거 후보]의 원문만 근거로 쓴다. 인터넷 검색이나 네가 아는 일반 지식으로 법 내용·기간·금액·예외·판례를 채우지 않는다.\n'
          '- 후보에 없는 법령·조항·고시·판례·사건번호를 쓰지 않는다. 금액·비율은 후보 원문이나 소비자 질문에 적힌 것만 쓴다.\n'
          '- 후보의 종류를 지킨다. (법률 조문)은 법적 효력이 있다. (분쟁해결기준(권고))은 당사자 합의·권고의 기준이라 강제력이 없다. '
          '(생활법령 해설(효력 없음))은 참고용 해설이다. 기준이나 해설을 법처럼 단정하지 않는다.\n'
          '- 후보가 질문을 다루지 않으면 covered를 false로 하고 법적 결론을 내리지 않는다.\n'
          '[확인 질문]\n- 결론을 바꿀 사실(무엇을 어디서 어떻게 샀는지, 언제 받았는지, 계약 기간·금액, 업체의 답 등)이 빠졌으면 need_more를 true로 하고 '
          'questions에 짧은 확인 질문 1~3개를 쓴다. 이때 parts에는 핵심 결론 하나만 "이 점을 알려 주시면 더 정확히 답할 수 있어요" 꼴로 짧게 쓴다.\n'
          '[구성]\n- parts에는 다음 7가지 중 이 질문에 필요한 것만 골라 이 순서로 쓴다: 핵심 결론, 관련 법령, 환불·보상 가능성, 증거, 대응 절차, 신고·상담기관, 출처.\n'
          '- 전체 700~1,200자. 쉬운 해요체, 법률 용어는 풀어 쓴다(예: 청약철회 = 주문 취소·반품). "~할 수 있어요", "~인 경우가 많아요"처럼 단정하지 않는다.\n'
          '- 근거로 쓴 문장 끝에 후보 id를 [c1]처럼 붙인다.\n'
          '- 업체와 협의가 어려우면 1372 소비자상담센터·한국소비자원 같은 기관을 안내한다. 소보루 제보는 소비자가 고를 수 있다고만 알리고 대신 접수하지 않는다.\n'
          'JSON 하나로만 답한다: {"need_more": true|false, "questions": [문자열], "parts": [{"name": 7가지 중 하나, "text": 문자열}], '
          '"refs": [근거로 쓴 후보 id], "covered": true|false}')

# ---- 개인정보 지우기 (AI에 보내기 전·기록하기 전) ------------------------------------------
SURNAMES = '김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예경봉'
NAME_RES = [re.compile(r'(?<![가-힣])([' + SURNAMES + r'][가-힣]{1,2})(?=\s?(?:씨|님|고객님|선생님|대리|과장|팀장|부장|매니저|사장님|기사님|실장))'),
            re.compile(r'((?:제|내|저의|본인)\s?이름은\s?)([가-힣]{2,4}?)(?=이고|이에요|입니다|예요|이라|라고|[이가]\s|\s|[,.]|$)'),
            re.compile(r'(저는\s?)([가-힣]{2,4})(?=(?:이고|입니다|이에요|예요|라고|이라고)(?![가-힣]))')]


def mask_names(text):
    text = NAME_RES[0].sub('[이름 삭제]', text)
    for r in NAME_RES[1:]: text = r.sub(lambda m: m.group(1) + '[이름 삭제]', text)
    return text


# ---- 피해 유형 -------------------------------------------------------------------------------
def classify(text, hits=()):
    """6가지 중 하나. 낱말 점수(긴 낱말일수록 더)로 고르고, 없으면 키워드 검색 첫 조문의 법으로."""
    best, top = '', 0
    for name, _, words, _, _ in TYPES:
        s = sum(len(w) for w in words if w in text)
        if s > top: best, top = name, s
    if best: return best
    for h in hits:
        k = h['ref'].split(':', 1)[0]
        if k in TYPE_BY_KEY: return TYPE_BY_KEY[k]
    return '생활서비스'


def type_info(name): return next((t for t in TYPES if t[0] == name), None)


def kind_label(law):
    k = law.get('kind') or ''
    if law.get('key') == 'easylaw' or '생활법령' in k: return LABELS[2]
    if '고시' in k or '기준' in law.get('name', ''): return LABELS[1]
    return LABELS[0]


# ---- 코드 확인: 출처·조항·금액·사건번호 ------------------------------------------------------------
LAWREF = re.compile(r'([가-힣ㆍ·]+(?:법|법률|기준)(?:\s?시행령|\s?시행규칙)?)\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?')
AMOUNT = re.compile(r'\d[\d,]*(?:\.\d+)?\s*(?:만|천|백|억)?\s*(?:원|달러)|\d+(?:\.\d+)?\s*(?:%|퍼센트)|\d+\s*분의\s*\d+')
CASENO = re.compile(r'\d{2,4}\s*(?:가합|가단|가소|구합|구단|헌가|헌나|헌마|헌바|나|다|라|마|누|두|노|도)\s*\d{2,7}(?!\s*(?:원|일|개|명|%|조))')
CASEWORD = re.compile(r'대법원|판례|판결|선고')
CID = re.compile(r'\[\s*(c\d{1,2})\s*\]', re.I)


def _n(s): return re.sub(r'[\s,ㆍ·]', '', s or '')


def law_ok(m, cards):
    name, art = _n(m[1]), f'제{m[2]}조' + (f'의{m[3]}' if m[3] else '')
    for c in cards:
        if c.get('art') != art: continue
        short, full = _n(c.get('short')), _n(c.get('law'))
        if name == short or name in full or (short and short in name): return True
    return False


def check_sentence(s, cards, src, q):
    """문장 하나에서 근거 원문에 없는 내용 -> [(종류, 글)] (빈 목록이면 통과)."""
    bad = []
    for m in LAWREF.finditer(s):
        if not law_ok(m, cards): bad.append(('law', m.group(0)))
    for m in AMOUNT.finditer(s):
        if _n(m.group(0)) not in src and _n(m.group(0)) not in q: bad.append(('amount', m.group(0)))
    for m in CASENO.finditer(s):
        if _n(m.group(0)) not in src: bad.append(('case', m.group(0)))
    for m in CASEWORD.finditer(s):
        if m.group(0) not in src: bad.append(('case', m.group(0))); break
    return bad


def sentences(text):
    out = []
    for line in re.split(r'\n+', text):
        out += [x for x in re.split(r'(?<=[.!?。])\s+', line.strip()) if x]
        out.append('\n')
    return out[:-1] if out else []


def verify(out, cards, question, scrub=lambda s: s):
    """AI 답(JSON)을 확인해 화면에 쓸 꼴로. cards: 넘겨준 후보 [{id, ref, art, short, law, text}].
    후보에 없는 id는 버리고, 근거 없는 조항·금액·사건번호가 든 문장은 빼고 flags에 남긴다. 형식이 틀리면 ValueError."""
    if not isinstance(out, dict): raise ValueError('AI 응답 형식이 달라요')
    ids = {c['id']: c for c in cards}
    src = _n(' '.join(c['text'] + ' ' + c.get('title', '') for c in cards)); q = _n(question)
    flags, used = [], []
    def keep_ids(s):
        def rep(m):
            i = m.group(1).lower()
            if i in ids:
                if i not in used: used.append(i)
                return f'[{i}]'
            flags.append({'type': 'source', 'text': m.group(0)}); return ''
        return CID.sub(rep, s)
    parts = []; raw = out.get('parts') or []
    if isinstance(raw, dict): raw = [{'name': k, 'text': v} for k, v in raw.items()]
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict): continue
        name = str(p.get('name', '')).strip(); text = p.get('text', '')
        if name not in PARTS: continue
        if isinstance(text, list): text = '\n'.join('- ' + str(x).lstrip('-• ') for x in text)
        text = scrub(str(text).strip()); kept = []
        for s in sentences(text):
            if s == '\n': kept.append(s); continue
            bad = check_sentence(CID.sub('', s), cards, src, q)
            if bad: flags += [{'type': k, 'text': v} for k, v in bad]; continue
            kept.append(keep_ids(s))
        body = re.sub(r'[ \t]+\n', '\n', ' '.join(kept).replace(' \n ', '\n').replace('\n ', '\n')).strip()
        body = re.sub(r'\n{2,}', '\n', body)
        if body and name not in [x[0] for x in parts]: parts.append((name, body[:700]))
    parts.sort(key=lambda x: PARTS.index(x[0]))
    refs = []
    for r in out.get('refs') or []:
        r = str(r).strip().strip('[]').lower()
        if r in ids and r not in refs: refs.append(r)
        elif r not in ids: flags.append({'type': 'source', 'text': str(r)[:40]})
    refs = used + [r for r in refs if r not in used]   # 글에 나온 순서대로, 그다음 refs에만 있는 것
    questions = [scrub(str(x).strip())[:200] for x in (out.get('questions') or []) if str(x).strip()][:3] if isinstance(out.get('questions'), list) else []
    need_more = bool(out.get('need_more')) and bool(questions)
    if not parts and not need_more: raise ValueError('AI가 답을 채우지 못했어요')
    total = 0; clipped = []
    for name, body in parts:   # 전체가 너무 길면 뒤에서 자름
        if total >= 1500: break
        clipped.append((name, body[:1500 - total])); total += len(body)
    return {'parts': clipped, 'refs': refs, 'questions': questions, 'need_more': need_more, 'covered': out.get('covered') is not False, 'flags': flags}


def migrate(db):
    # 개인정보를 지운 상담만. kind: ask(손님) lab(실험실) test(품질 시험) view(열람 기록)
    db.execute('''CREATE TABLE IF NOT EXISTS ask_logs(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,created TEXT NOT NULL,conv TEXT NOT NULL DEFAULT '',batch TEXT NOT NULL DEFAULT '',
        dtype TEXT NOT NULL DEFAULT '',question TEXT NOT NULL DEFAULT '',answer TEXT NOT NULL DEFAULT '',refs TEXT NOT NULL DEFAULT '[]',parts TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT '',model TEXT NOT NULL DEFAULT '',tokens_in INTEGER NOT NULL DEFAULT 0,tokens_out INTEGER NOT NULL DEFAULT 0,emb_tokens INTEGER NOT NULL DEFAULT 0,
        latency_ms INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',flags TEXT NOT NULL DEFAULT '[]',viewer TEXT NOT NULL DEFAULT '',target INTEGER)''')
    db.execute('CREATE INDEX IF NOT EXISTS ask_logs_kind ON ask_logs(kind,created)')


def install(S):
    app = S.app; conn = S.conn; desk = S.companydesk
    store = lawsync.Store(S.UPLOAD / 'laws')
    rc = lawsync.corpus_v2(store); emb = lawsync.Embeddings(store)
    pending = store.dir / 'pending'; pending.mkdir(exist_ok=True)
    lawask_ext = app.extensions['lawask']
    with conn() as db: migrate(db)
    jobs = {}   # 돌고 있는 뒤 작업 {이름: 시작 시각}

    def stamp(): return datetime.datetime.now().isoformat(timespec='seconds')
    def post(*a): return desk.post_json(*a)   # 테스트에서 companydesk.post_json을 바꿔 끼움
    def has_key(): return bool(os.getenv('OPENAI_API_KEY', '').strip())
    def mask(text): return mask_names(desk.scrub(S.mask_personal(text or '')))

    # ---- 켜고 끄기 ---------------------------------------------------------------
    def v2_on(): return S.admin_setting('ask_v2') == '1'
    def set_v2(on):
        with conn() as db:
            db.execute('INSERT INTO admin_settings(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated', ('ask_v2', '1' if on else '0', stamp()))
    def showing_v2(): return v2_on() or (S.admin_active() and request.args.get('v') == '2')
    def ask_label(): return S.soboru.ASK_V2_TEXT['nav'] if v2_on() else S.soboru.ASK_V2_TEXT['old_nav']

    # ---- 후보 찾기 ----------------------------------------------------------------
    _docs = {'db': None, 'docs': []}
    def docs():
        db = rc._load()
        if _docs['db'] is not db: _docs.update(db=db, docs=lawsync.corpus_docs(rc))
        return _docs['docs']

    def status_map(): return store.read(store.status)

    def card(ref, i, status):
        db = rc._load(); key, art = ref.split(':', 1); law = db['laws'][key]; a = law['articles'][art]
        st, day = lawsync.status_of(law, status)
        c = {'id': f'c{i}', 'ref': ref, 'key': key, 'law': law['name'], 'short': law['short'], 'art': art, 'title': a.get('title', ''), 'text': a['text'],
             'label': kind_label(law), 'effective': law.get('effective', ''), 'status': st, 'checked': day, 'source': rc.source(ref), 'page': a.get('page'), 'item': a.get('item', '')}
        if key == lawsync.APPENDIX_KEY:
            c.update(law=a.get('doc') or law['name'], art_label=f"{a.get('appendix', '별표')} · {a.get('item') or '공통'}", title=a.get('title', ''))
        elif key == 'easylaw': c['art_label'] = a.get('title', '')
        else: c['art_label'] = art
        return c

    def retrieve(question, prior=''):
        """(피해 유형, 후보 카드들, 정보{emb_tokens, error}). 맞는 게 없으면 후보는 빈 목록."""
        text = (prior + ' ' + question).strip(); info = {'emb_tokens': 0, 'error': ''}
        kw = rc.search(text, 40)
        dtype = classify(text, kw); t = type_info(dtype)
        kw_ok = rc.strength(kw) >= rc.RELATED
        score, why = {}, {}
        if kw_ok:
            top = kw[0]['score']
            for i, h in enumerate(kw):
                if h['score'] < top * 0.4: break
                if h['match'] < 0.1: continue
                score[h['ref']] = score.get(h['ref'], 0) + 1 / (RRF + i + 1); why[h['ref']] = 'kw'
        if has_key() and emb.load().index:
            try:
                (qv,), n = lawsync.embed([mask(text)[:1000]], post); info['emb_tokens'] = n
                for i, (cos, d) in enumerate(emb.search(qv, docs(), 40)):
                    if cos < EMB_MIN: break
                    score[d['ref']] = score.get(d['ref'], 0) + 1 / (RRF + i + 1); why[d['ref']] = why.get(d['ref'], '') + 'emb'
            except Exception as e:
                info['error'] = str(e)[:160]; LOG.warning('임베딩 검색 실패: %s', info['error'])
        if not score: return dtype, [], info
        laws = rc._load()['laws']
        def boost(ref):
            key, art = ref.split(':', 1); b = 1.0
            if key == lawsync.APPENDIX_KEY:
                item = laws[key]['articles'][art].get('item', '') + laws[key]['articles'][art].get('title', '')
                b *= TYPE_BOOST if t and any(w in item for w in t[4]) else 0.8
            elif t and key in t[3]: b *= TYPE_BOOST
            if key == 'easylaw': b *= 0.9
            if key == 'civil': b *= 0.8
            return b
        ranked = sorted(score, key=lambda r: -score[r] * boost(r))
        out, guides, appx = [], 0, 0
        for r in ranked:
            k = r.split(':', 1)[0]
            if k == 'easylaw':
                if guides >= MAX_GUIDE: continue
                guides += 1
            if k == lawsync.APPENDIX_KEY:
                if appx >= MAX_APPX: continue
                appx += 1
            out.append(r)
            if len(out) >= MAX_CANDS: break
        st = status_map()
        return dtype, [card(r, i + 1, st) for i, r in enumerate(out)], info

    # ---- 답 만들기 ----------------------------------------------------------------
    def cand_block(cards):
        out, used = [], 0
        for c in cards:
            head = f"[{c['id']}] ({c['label']}) {c['short']} {c['art_label']}" + (f" ({c['title']})" if c['title'] and c['key'] not in ('easylaw', lawsync.APPENDIX_KEY) else '')
            head += (f" · 시행 {c['effective']}" if c['effective'] else '') + f" · {c['status']}"
            body = rc.clip(c['text'], 1500)
            if used + len(body) > 12000 and out: break
            out.append(head + '\n' + body); used += len(body)
        return '\n\n'.join(out)

    def ask_ai(question, history, cards):
        key = os.getenv('OPENAI_API_KEY', '').strip()
        msgs = [{'role': 'system', 'content': SYSTEM.replace('소보루', S.notify.site_name())}]
        for h in history[-(HISTORY_TURNS // 2):]:
            msgs += [{'role': 'user', 'content': mask(h['q'])}, {'role': 'assistant', 'content': mask(h['a'])[:900]}]
        msgs.append({'role': 'user', 'content': '[질문]\n' + mask(question) + '\n\n[근거 후보]\n' + cand_block(cards)})
        body = {'model': desk.ai_model(), 'temperature': 0.2, 'response_format': {'type': 'json_object'}, 'messages': msgs}
        st, res = post('https://api.openai.com/v1/chat/completions', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, 45)
        if st != 200: raise RuntimeError(f'AI 응답 오류 ({st}) ' + str(((res or {}).get('error') or {}).get('message', ''))[:120].replace(key, '***'))
        use = res.get('usage') or {}
        try: out = json.loads(res['choices'][0]['message']['content'])
        except (KeyError, IndexError, TypeError, ValueError): raise RuntimeError('AI 응답을 읽지 못했어요')
        return out, {'model': res.get('model') or desk.ai_model(), 'in': int(use.get('prompt_tokens') or 0), 'out': int(use.get('completion_tokens') or 0)}

    def number_refs(text, order):
        return CID.sub(lambda m: f'[{order.index(m.group(1).lower()) + 1}]' if m.group(1).lower() in order else '', text)

    def plain(res):
        """복사·이어 묻기용 글"""
        if res['kind'] == 'ask': body = '\n'.join(f'{n}\n{t}' for n, t in res['parts']) + ('\n' if res['parts'] else '') + '\n'.join('- ' + x for x in res['questions'])
        elif res['kind'] in ('none', 'fallback'): body = res['headline'] + '\n' + '\n'.join('- ' + x for x in STEPS)
        else: body = '\n\n'.join(f'{n}\n{t}' for n, t in res['parts'])
        if res['cards']: body += '\n\n출처\n' + '\n'.join(f"[{i}] {c['law']} {c['art_label']}" + (f" (시행 {c['effective']})" if c['effective'] else '') for i, c in enumerate(res['cards'], 1))
        return body.strip()

    def agencies(dtype): return AGENCIES.get(dtype, []) + AGENCIES['']

    def consult(question, history=(), kind='ask', conv='', batch=''):
        """질문 하나 -> 화면용 결과. 기록도 남긴다(개인정보 지운 것만)."""
        t0 = time.time(); q = mask(question); history = list(history)
        prior = ' '.join(h['q'] for h in history[-(HISTORY_TURNS // 2):])
        meta = {'model': '', 'in': 0, 'out': 0}; error = ''
        try: dtype, cards, info = retrieve(q, prior)
        except Exception as e:
            LOG.warning('상담 후보 찾기 실패: %s', type(e).__name__); dtype, cards, info = classify(q), [], {'emb_tokens': 0, 'error': type(e).__name__}
        res = {'dtype': dtype, 'emoji': (type_info(dtype) or ('', '💬'))[1], 'parts': [], 'questions': [], 'cards': [], 'flags': [], 'agencies': agencies(dtype),
               'headline': '', 'covered': True}
        if not cards:
            res.update(kind='none', headline='관련 법령을 찾지 못했어요'); status = 'no_law'
        elif not has_key():
            res.update(kind='fallback', headline='질문과 가까운 근거 원문을 찾았어요', cards=cards[:4]); status = 'fallback'; error = 'OpenAI 키 없음'
        else:
            try:
                out, meta = ask_ai(question, history, cards)
                v = verify(out, cards, q, mask)
                order = v['refs']; used = [next(c for c in cards if c['id'] == i) for i in order]
                res.update(kind='ask' if v['need_more'] else 'answer', parts=[(n, number_refs(t, order)) for n, t in v['parts']], questions=v['questions'],
                           cards=used, flags=v['flags'], covered=v['covered'])
                status = 'ask_more' if v['need_more'] else 'ok'
            except Exception as e:
                error = str(e)[:200]; LOG.warning('AI 상담 실패: %s', error)
                res.update(kind='fallback', headline='질문과 가까운 근거 원문을 찾았어요', cards=cards[:4]); status = 'error'
        res['text'] = plain(res)
        ms = int((time.time() - t0) * 1000)
        log(kind, conv=conv, batch=batch, dtype=dtype, question=q, answer=json.dumps({'kind': res['kind'], 'parts': res['parts'], 'questions': res['questions'], 'headline': res['headline']}, ensure_ascii=False),
            refs=json.dumps([c['ref'] for c in res['cards']], ensure_ascii=False), parts=json.dumps([n for n, _ in res['parts']], ensure_ascii=False), status=status,
            model=meta['model'], tokens_in=meta['in'], tokens_out=meta['out'], emb_tokens=info.get('emb_tokens', 0), latency_ms=ms,
            error=(error or info.get('error', ''))[:300], flags=json.dumps(res['flags'], ensure_ascii=False))
        res['latency'] = ms; res['status'] = status
        return res

    # ---- 기록 -------------------------------------------------------------------
    def purge(db):
        now = datetime.datetime.now()
        db.execute("DELETE FROM ask_logs WHERE kind!='view' AND created<?", ((now - datetime.timedelta(days=KEEP_DAYS)).isoformat(timespec='seconds'),))
        db.execute("DELETE FROM ask_logs WHERE kind='view' AND created<?", ((now - datetime.timedelta(days=VIEW_KEEP_DAYS)).isoformat(timespec='seconds'),))

    def log(kind, **f):
        cols = ['kind', 'created'] + list(f)
        try:
            with conn() as db:
                purge(db)
                db.execute(f"INSERT INTO ask_logs({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [kind, stamp()] + list(f.values()))
        except Exception as e: LOG.warning('상담 기록 실패: %s', type(e).__name__)

    def read_history(raw):
        try: data = json.loads(raw or '[]')
        except ValueError: return []
        out = []
        for h in data if isinstance(data, list) else []:
            if isinstance(h, dict) and isinstance(h.get('q'), str) and isinstance(h.get('a'), str):
                out.append({'q': mask(h['q'])[:MAX_Q], 'a': mask(h['a'])[:900]})
        return out[-(HISTORY_TURNS // 2):]

    # ---- 손님 화면 -------------------------------------------------------------------
    old_view = app.view_functions['law_ask']

    def v2_page():
        question, result, error, history = '', None, '', []
        conv = request.form.get('conv', '') if re.fullmatch(r'[A-Za-z0-9_-]{8,40}', request.form.get('conv', '')) else secrets.token_urlsafe(9)
        if request.method == 'POST':
            if request.form.get('website'): abort(400)
            history = read_history(request.form.get('history'))
            question = ' '.join((request.form.get('q') or request.form.get('example') or '').split())
            if len(question) < MIN_Q: error = S.ui_text('ask2.err_short', '궁금한 상황을 조금 더 자세히 적어 주세요.')
            elif len(question) > MAX_Q: error = S.ui_text('ask2.err_long', f'질문은 {MAX_Q}자 안으로 줄여 주세요.')
            else:
                with conn() as db:
                    if S.recent_count(db, 'law_questions', 60) >= PER_HOUR: error = S.ui_text('ask2.err_limit', '질문이 많아 잠시 쉬어 가요. 1시간 뒤에 다시 물어봐 주세요.')
                    else:
                        db.execute('DELETE FROM law_questions WHERE created<?', ((datetime.datetime.now() - datetime.timedelta(days=1)).isoformat(timespec='seconds'),))
                        db.execute('INSERT INTO law_questions(ip_hash,created) VALUES(?,?)', (S.ip_hash(), stamp()))
                if not error: result = consult(question, history, 'ask', conv)
        shown_q = mask(question)
        new_hist = history + ([{'q': shown_q, 'a': result['text'][:900]}] if result else [])
        return render_template('soboru_ask_v2.html', question=question, shown_q=shown_q, result=result, error=error, turns=history, conv=conv,
                               history_json=json.dumps(new_hist[-(HISTORY_TURNS // 2):] if result else history, ensure_ascii=False),
                               examples=EXAMPLES, max_q=MAX_Q, min_q=MIN_Q, preview=not v2_on(), result_steps=STEPS)

    def law_ask_switch():
        if not app.jinja_env.globals['ask_on'](): abort(404)
        return v2_page() if showing_v2() else old_view()
    app.view_functions['law_ask'] = law_ask_switch

    # ---- 관리자: 법령 학습에 별표 올리기 ----------------------------------------------------------
    old_laws = app.view_functions['admin_laws']

    def admin_laws_switch():
        act = request.form.get('act', '') if request.method == 'POST' else ''
        if not act.startswith('appendix_'): return old_laws()
        if not S.admin_active(): return redirect(url_for('admin_login'))
        parts = lawsync.appendix_parts(store)
        if act == 'appendix_delete':
            i = request.form.get('index', type=int)
            if i is None or not 0 <= i < len(parts): flash('지울 별표를 찾지 못했어요.')
            else:
                gone = parts.pop(i); lawsync.save_appendix(store, parts); flash(f"{gone.get('doc') or '별표'}을(를) 지웠어요.")
            return redirect(url_for('admin_laws'))
        if act == 'appendix_save':
            token = request.form.get('token', ''); p = pending / ('appx-' + token + '.json')
            if not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', token) or not p.exists(): flash('미리 보기가 끝났어요. PDF를 다시 올려 주세요.'); return redirect(url_for('admin_laws'))
            new = json.loads(p.read_text(encoding='utf-8')); p.unlink()
            for k, x in enumerate(new):
                x['doc'] = ' '.join(request.form.get(f'doc_{k}', '').split())[:80] or x.get('doc') or '소비자분쟁해결기준'
                eff = request.form.get(f'eff_{k}', '').strip()
                if re.fullmatch(r'\d{4}-\d{2}-\d{2}', eff): x['effective'] = eff
                x['added'] = stamp()
                parts = [y for y in parts if not (y.get('doc') == x['doc'] and y.get('appendix') == x.get('appendix'))] + [x]
            lawsync.save_appendix(store, parts); background('embed', build_embeddings)
            flash('별표를 배웠어요: ' + ', '.join(f"{x['doc']} {len(x['rows'])}줄" for x in new) + '. AI 상담 새 버전에서 분쟁해결기준(권고)으로 찾아 써요.')
            return redirect(url_for('admin_laws'))
        files = [f for f in request.files.getlist('pdf') if f and f.filename][:5]
        if not files: flash('별표 PDF 파일을 골라 주세요.'); return redirect(url_for('admin_laws'))
        new, errors = [], []
        for f in files:
            raw = f.read(20 * 1024 * 1024 + 1); name = f.filename
            if not name.lower().endswith('.pdf') or not raw.startswith(b'%PDF-'): errors.append(f'{name}: PDF 파일만 올릴 수 있어요.'); continue
            if len(raw) > 20 * 1024 * 1024: errors.append(f'{name}: 20MB보다 커요.'); continue
            try:
                pages = lawsync.pdf_layout_text(raw)
                if not lawsync.is_appendix(pages): raise ValueError("'분쟁유형'·'해결기준' 표를 찾지 못했어요. 소비자분쟁해결기준 별표 PDF인지 확인해 주세요.")
                x = lawsync.parse_appendix(pages, '소비자분쟁해결기준 [' + '별표' + ']')
                x['doc'] = f"소비자분쟁해결기준 [{x['appendix']}]"; x['file'] = name[:120]; new.append(x)
            except ValueError as e: errors.append(f'{name}: {e}')
        for e in errors: flash(e)
        if not new: return redirect(url_for('admin_laws'))
        token = secrets.token_urlsafe(18)
        (pending / ('appx-' + token + '.json')).write_text(json.dumps(new, ensure_ascii=False), encoding='utf-8')
        return redirect(url_for('admin_laws', appendix=token) + '#appendix')
    app.view_functions['admin_laws'] = admin_laws_switch

    def laws_panel():
        """법령 학습 화면 아래쪽: 현행 여부, 별표 목록·미리 보기 (admin_laws.html이 부름)"""
        status = status_map(); laws = rc._load()['laws']; rows = []
        for key, name, short, target in lawsync.SYNC_LAWS + lawsync.OPTIONAL_LAWS:
            law = laws.get(key) or next((l for l in laws.values() if lawsync.norm_name(l['name']) == lawsync.norm_name(name)), None)
            s = status.get(key) or {}
            if law: st, day = lawsync.status_of(law, status)
            else: st, day = lawsync.UNKNOWN, ''
            rows.append({'short': short, 'name': name, 'have': (law or {}).get('effective', ''), 'current': s.get('current', ''), 'checked': (s.get('checked') or '')[:16].replace('T', ' '),
                         'status': st if law else ('모음에 없음' if not s.get('current') else '받기 전'), 'from': '현행 원문' if (law or {}).get('synced') else '올린 PDF' if (law or {}).get('extra') else '기본 모음' if law else '',
                         'error': s.get('error', '') if not s.get('checked') or (s.get('error_at', '') > s.get('checked', '')) else ''})
        token = request.args.get('appendix', ''); preview = None
        if re.fullmatch(r'[A-Za-z0-9_-]{16,64}', token) and (pending / ('appx-' + token + '.json')).exists():
            preview = json.loads((pending / ('appx-' + token + '.json')).read_text(encoding='utf-8'))
        return {'rows': rows, 'parts': lawsync.appendix_parts(store), 'preview': preview, 'token': token if preview else '', 'oc': bool(lawsync.oc()),
                'flags': lawsync.pdf_flags(store), 'kca': status.get('kca') or {}}

    # ---- 뒤 작업 (임베딩 만들기, 법령 받기, 품질 시험) ------------------------------------------------
    def background(name, fn, *args):
        if name in jobs: return False
        jobs[name] = stamp()
        def run():
            try: fn(*args)
            except Exception as e: LOG.warning('%s 실패: %s', name, str(e)[:200])
            finally: jobs.pop(name, None)
        threading.Thread(target=run, daemon=True).start()
        return True

    def build_embeddings():
        if not has_key(): return
        n, tok = emb.build(docs(), post)
        log('job', status='embed', emb_tokens=tok, question=f'임베딩 {n}개 새로 만듦')

    def run_sync():
        lawsync.sync(store, log=lambda s: LOG.info('법령 받기:%s', s)); rc.reset()
        build_embeddings()

    def run_tests(batch):
        for q in TEST_QUESTIONS: consult(q, (), 'test', batch=batch)

    # ---- 관리자 화면 ----------------------------------------------------------------
    def rows_since(db, kinds, days=KEEP_DAYS):
        since = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat(timespec='seconds')
        return db.execute(f"SELECT * FROM ask_logs WHERE kind IN ({','.join('?' * len(kinds))}) AND created>=? ORDER BY id DESC", (*kinds, since)).fetchall()

    def law_name(ref):
        key = ref.split(':', 1)[0]; laws = rc._load()['laws']
        return laws[key]['short'] if key in laws else key

    def stats(rows):
        n = len(rows); lat = sorted(r['latency_ms'] for r in rows)
        tin = sum(r['tokens_in'] for r in rows); tout = sum(r['tokens_out'] for r in rows); temb = sum(r['emb_tokens'] for r in rows)
        types = {}; lawc = {}; models = {}
        for r in rows:
            types[r['dtype'] or '기타'] = types.get(r['dtype'] or '기타', 0) + 1
            if r['model']: models[r['model']] = models.get(r['model'], 0) + 1
            for ref in json.loads(r['refs'] or '[]'): lawc[law_name(ref)] = lawc.get(law_name(ref), 0) + 1
        fails = [r for r in rows if r['status'] in ('error', 'fallback')]
        return {'n': n, 'types': sorted(types.items(), key=lambda x: -x[1]), 'avg': int(statistics.mean(lat)) if lat else 0,
                'p95': lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else 0, 'models': sorted(models.items(), key=lambda x: -x[1]),
                'tin': tin, 'tout': tout, 'temb': temb, 'cost': (tin * PRICE['in'] + tout * PRICE['out'] + temb * PRICE['emb']) / 1e6,
                'laws': sorted(lawc.items(), key=lambda x: -x[1])[:10], 'fails': fails[:10], 'nfail': len(fails),
                'status': {s: sum(1 for r in rows if r['status'] == s) for s in ('ok', 'ask_more', 'no_law', 'fallback', 'error')},
                'flagged': sum(1 for r in rows if r['flags'] not in ('', '[]'))}

    @app.route('/admin/ask', methods=['GET', 'POST'])
    @S.admin_only
    def admin_ask():
        if request.method == 'POST':
            act = request.form.get('act')
            if act == 'switch':
                on = request.form.get('on') == '1'; set_v2(on)
                flash('AI 상담 새 버전을 켰어요. 손님에게 새 화면이 보여요.' if on else 'AI 상담 새 버전을 껐어요. 손님에게 예전 화면이 보여요.')
            elif act == 'test':
                flash('품질 시험을 시작했어요. 질문 20개를 차례로 묻느라 몇 분 걸려요. 잠시 뒤 새로고침해 주세요.' if background('test', run_tests, stamp()) else '품질 시험이 이미 돌고 있어요.')
            elif act == 'embed':
                if not has_key(): flash('OpenAI 키가 없어 임베딩을 만들 수 없어요.')
                else: flash('임베딩을 만들기 시작했어요. 바뀐 조문만 만들어요.' if background('embed', build_embeddings) else '임베딩을 이미 만들고 있어요.')
            elif act == 'sync':
                if not lawsync.oc(): flash('LAW_OC가 없어요. 서버에서 deploy/set-law.sh로 법제처 인증키를 넣어 주세요.')
                else: flash('법제처에서 현행 법령을 받기 시작했어요. 몇 분 걸려요.' if background('sync', run_sync) else '법령을 이미 받고 있어요.')
            return redirect(url_for('admin_ask'))
        with conn() as db:
            purge(db)
            rows = rows_since(db, ('ask',)); recent = rows[:30]
            last = db.execute("SELECT batch FROM ask_logs WHERE kind='test' ORDER BY id DESC LIMIT 1").fetchone()
            tests = db.execute("SELECT * FROM ask_logs WHERE kind='test' AND batch=? ORDER BY id", (last['batch'],)).fetchall() if last else []
        d = docs(); emb.load(); have = sum(1 for x in d if x['hash'] in emb.index)
        return render_template('admin_ask.html', on=v2_on(), s=stats(rows), recent=recent, tests=tests, test_batch=last['batch'] if last else '', jobs=dict(jobs),
                               test_total=len(TEST_QUESTIONS), emb={'have': have, 'total': len(d)}, keep_days=KEEP_DAYS, price=PRICE, model=desk.ai_model(),
                               embed_model=lawsync.EMBED_MODEL, oc=bool(lawsync.oc()), key=has_key(), loads=json.loads, parts_all=PARTS)

    @app.route('/admin/ask/logs/<int:log_id>')
    @S.admin_only
    def admin_ask_log(log_id):
        with conn() as db:
            purge(db)
            row = db.execute("SELECT * FROM ask_logs WHERE id=? AND kind IN ('ask','lab','test')", (log_id,)).fetchone()
            if not row: abort(404)
            db.execute("INSERT INTO ask_logs(kind,created,question,viewer,target) VALUES('view',?,?,?,?)", (stamp(), f'상담 기록 #{log_id} 열람', '대표 관리자', log_id))
            views = db.execute("SELECT created,viewer FROM ask_logs WHERE kind='view' AND target=? ORDER BY id DESC LIMIT 20", (log_id,)).fetchall()
        LOG.info('상담 기록 #%d 열람 (대표 관리자)', log_id)
        return render_template('admin_ask_log.html', row=row, views=views, loads=json.loads, law_name=law_name, keep_days=KEEP_DAYS)

    @app.route('/admin/ask/lab', methods=['GET', 'POST'])
    @S.admin_only
    def admin_ask_lab():
        question, old, new = '', None, None
        if request.method == 'POST':
            question = ' '.join((request.form.get('q') or '').split())[:MAX_Q]
            if len(question) >= MIN_Q:
                try: old = lawask_ext['answer'](question)
                except Exception as e: old = {'kind': 'error', 'error': type(e).__name__, 'cards': []}
                new = consult(question, (), 'lab')
            else: flash('질문을 조금 더 길게 적어 주세요.')
        return render_template('admin_ask_lab.html', question=question, old=old, new=new, examples=TEST_QUESTIONS[:8], on=v2_on())

    def refs_html(s):
        return Markup(re.sub(r'\[(\d{1,2})\]', r'<sup class="sbv-sup">\1</sup>', str(escape(s))))

    app.jinja_env.filters['askrefs'] = refs_html
    app.jinja_env.globals.update(ask_label=ask_label, ask_v2_on=v2_on, ask_laws_panel=laws_panel, ask_part_emoji=PART_EMOJI)
    app.extensions['lawrag'] = {'consult': consult, 'retrieve': retrieve, 'verify': verify, 'store': store, 'corpus': rc, 'emb': emb, 'mask': mask,
                                'set_v2': set_v2, 'build_embeddings': build_embeddings, 'run_sync': run_sync, 'docs': docs}
