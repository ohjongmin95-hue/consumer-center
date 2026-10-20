"""소보루 AI 분석 기사: 이미 연결된 데이터로 AI가 뉴닉 말투 분석 기사 초안을 쓰고, 운영자가 '게시하기'를 눌러야만 올라간다.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다 (naverhub·lawask 다음).
- 글 종류(KINDS)마다 '자료 모으기(collector) + 프롬프트'. 자료 모으기는 {facts, sources, ...}를 돌려주고, AI에는 facts만 넘긴다.
  검색 추이(네이버 데이터랩 검색어트렌드) · 쇼핑 관심도(쇼핑인사이트) · 소비자 뉴스 해설(뉴스 검색 + 법령 모음 조문) ·
  소보루 제보 동향(공개·게시된 제보 집계만) · 법 바뀐 것(법제처 Open API, LAW_OC가 있을 때만).
- 숫자 지키기: AI 글의 모든 숫자는 facts 안에 있어야 한다(1,234=1234, 12.0=12, 3만=30000, 반올림 정도만 같은 숫자로 봄).
  없는 숫자가 있으면 초안은 '검토 필요'로 남기고 그 줄을 보여 준다. 기업을 평가·비난하는 말(BANNED)도 같이 잡는다.
  검토 필요 초안은 '숫자를 직접 확인했어요'에 체크해야 게시된다. 운영자가 고쳐 저장하면 같은 facts로 다시 검사한다.
- 저장: articles에 status='draft', origin='ai', ext_key='ai:종류:날짜'(같은 날 같은 종류는 한 번). 자료·출처·검사 결과는 ai_articles에.
  게시는 관리자 > 생활정보 글에서 운영자만. 이 모듈은 어떤 경우에도 published로 바꾸지 않는다.
- 하루 세 번(아침 7시·오후 1시·저녁 7시, SLOTS): deploy/soboru-writer.timer가 `python -m soboru_writer`를 부르면 그때마다 몇 편(기본 5개, 하루 15개)을
  종류·주제를 돌아가며 만든다. 남는 몫은 '소보루 기획 기사'(feature)가 채운다: 최근 소비자 뉴스 제목에서 AI가 기획 주제(야마)를 고르고,
  그 주제의 뉴스·검색 추이 통계·법 조문을 엮어 잡지 기사 한 편으로 쓴다. 같은 주제는 30일, 같은 제목은 30일 안에 다시 쓰지 않는다.
  데이터가 연결되지 않은 종류(키 없음)는 건너뛴다. 관리자 > AI 기사 만들기에서 자동 쓰기를 끌 수 있다.
- 공공데이터(data.go.kr 리콜 등)는 아직 키가 없다. 키가 생기면 SOURCES에 준비 확인을, KINDS에 collector 하나를 더하면 된다
  (plans/소보루_매일콘텐츠_공공데이터.md). 리콜처럼 사실만 옮기는 글도 처음에는 초안으로 쌓는다.
"""
import datetime, json, os, re, statistics, sys, threading, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from flask import abort, flash, g, redirect, render_template, request, url_for

SITE = 'https://' + (os.getenv('CANONICAL_HOST') or 'consumerjebo.co.kr').strip().lower()
TREND_WORDS = ['환불', '위약금', '리콜', '택배 분실', '구독 해지']  # 네이버 검색어트렌드는 한 번에 5묶음까지
NEWS_QUERIES = ['소비자 피해', '환불 분쟁', '리콜']
NEWS_DAYS = 7
# 법제처 목록에서 소비자와 닿는 법만 고름 (법령 이름에 이 말이 있으면)
LAW_WORDS = ('소비자', '전자상거래', '약관', '표시', '광고', '할부', '방문판매', '식품', '화장품', '제조물', '개인정보', '전기통신', '통신', '여객',
             '택배', '화물', '의료기기', '약사', '위생', '제품안전', '자동차', '금융소비자', '전자금융', '여신전문', '주택임대차', '공정거래', '가맹', '대리점',
             '건강기능', '어린이', '전기용품', '생활용품', '관광', '체육시설', '학원')
# 기업에 대한 평가·비난으로 읽힐 말 (숫자만 전하는 원칙)
BANNED = ('악덕', '최악', '사기꾼', '먹튀', '갑질', '양심 없', '양심없', '블랙기업', '불매', '무책임한 기업', '나쁜 기업', '믿을 수 없는 기업')
CONST = {'소비자상담센터 전화번호': '1372'}  # 글 끝 안내에 늘 쓰는 번호는 자료에 같이 넣음
AI_TIMEOUT = 90
# 소제목에 붙이는 이모지: 사이트의 토스페이스 글꼴(static/fonts/tossface-soboru.woff2)에 들어 있는 것만
EMOJI = '📊📈📉🔍💡📌📦🛒💳💰💸🧾📱🚗✈🏠🍔🩺💊⚖📢📣📰🔔⚠🚨✅📝📋🤝🙋💬👀🔥✨⏰📅🛡🔒🧸🧴🎁'
SLOTS = (7, 13, 19)  # 하루 세 번 쓰는 때 (한국 시각, 아침·오후·저녁). deploy/soboru-writer.timer와 같게 둠
PER_RUN = (1, 2, 3, 4, 5, 6, 8, 10)
DEFAULT_PER_RUN = 5  # 운영자 요청 2026-10-20: 아침·오후·저녁 5개씩, 하루 15개
FEATURE_FRESH = 30   # 기획 기사는 같은 주제를 이 기간 안에 다시 쓰지 않음 (다른 종류가 쓴 주제도)
# 기획 주제(야마)를 고를 때 훑어보는 소비자 뉴스 검색어
FEATURE_QUERIES = ['소비자 피해', '한국소비자원', '공정위 과징금', '환불 분쟁', '리콜', '요금 인상', '가격 인상', '구독료', '수수료 인상', '불공정 약관',
                   '개인정보 유출', '소비자 주의보', '피해구제', '집단분쟁조정', '과대광고']
# 기획 주제 후보 (분야별). 뉴스로 고른 주제가 모자라면 여기서, 최근 글이 적은 분야부터 고름 (운영자 요청 2026-10-20: 분야를 고르게)
CATS = ('쇼핑', '통신', '여행', '음식', '금융', '자동차', '생활', '리콜')
FEATURE_TOPICS = {
    '쇼핑': ['배달앱 수수료', '해외직구 가품', '명품 리셀', '라이브커머스 환불', '공동구매 사기', '중고거래 사기', '새벽배송 포장', '명절 선물세트 포장', '무인점포 결제'],
    '통신': ['알뜰폰 요금제', 'OTT 요금', '구독료 인상', '인터넷 결합상품 해지', '휴대폰 할부 수수료', '스마트폰 수리비', '앱 자동결제', '게임 아이템 환불'],
    '여행': ['항공권 유류할증료', '숙박앱 취소 수수료', '여행사 패키지 취소', '해외여행자 보험', '항공 지연 보상', '렌터카 사고 수리비', '캠핑장 예약 취소'],
    '음식': ['음식점 원산지 표시', '식품 소비기한', '편의점 도시락', '건강기능식품 과대광고', '다이어트 식품', '배달 음식 이물질', '반려동물 사료'],
    '금융': ['보험 해지 환급금', '카드 포인트 소멸', '간편결제 사기', '상조 해약', '주택 임대차 보증금', '대출 중도상환 수수료', '예금자 보호'],
    '자동차': ['중고차 허위매물', '전기차 충전 요금', '자동차 보험료', '자동차 정비 과잉수리', '전동킥보드 사고', '차량 무상수리'],
    '생활': ['전기요금', '가스요금', '관리비', '이사 파손', '택배 분실', '헬스장 폐업', '필라테스 환불', '학원 교습비', '산후조리원 계약', '동물병원 진료비',
           '장례 서비스 계약', '결혼준비 대행', '정수기 렌탈 위약금', '온라인 강의 환불', '키오스크 이용'],
    '리콜': ['어린이 제품 리콜', '자동차 리콜', '가전 리콜', '화장품 회수', '식품 회수', '캠핑용품 안전', '키즈카페 안전'],
}
FRESH_DAYS = 14      # 주제별 글(EXTRA)은 같은 주제를 이 기간 안에 다시 쓰지 않음
# 주제별 깊이 보기 글의 주제 후보
RIGHTS_TOPICS = ['온라인 쇼핑 청약철회', '반품 배송비 부담', '환불 지연 배상', '제품 하자 교환 환불', '불공정 약관 조항', '방문판매 청약철회',
                 '숙박 예약 취소 환불', '택배 분실 배상', '식품 이물질', '식품 소비기한 표시', '화장품 표시 사항', '건강기능식품 광고', '과장 광고',
                 '해외직구 반품', '개인정보 유출', '학원비 환불', '소비자분쟁조정 신청', '소비자 피해구제 신청', '통신판매업자 신원 정보']
WORD_TOPICS = {'택배 분실': ['택배 파손', '택배 지연', '택배 보상'], '구독 해지': ['정기결제 해지', '자동결제 해지', '구독 환불'],
               '중고거래 사기': ['직거래 사기', '안전거래', '사기 조회'], '항공권 환불': ['항공권 취소 수수료', '항공 지연 보상', '수하물 분실'],
               '헬스장 환불': ['헬스장 양도', 'PT 환불', '필라테스 환불'], '위약금': ['인터넷 위약금', '휴대폰 위약금', '렌탈 위약금'],
               '리콜': ['자동차 리콜', '제품 리콜', '무상수리'], '해외직구': ['해외직구 관세', '해외직구 반품', '해외직구 사기'],
               '숙소 환불': ['호텔 취소', '펜션 환불', '숙박 예약 취소'], '개인정보 유출': ['유출 조회', '스미싱', '보이스피싱'],
               '식품 이물질': ['음식 이물질', '배달 음식 이물질', '식중독'], '허위광고': ['과대광고', '뒷광고', '광고 신고'],
               '소비기한': ['유통기한', '소비기한 지난', '유통기한 지난'], '보증기간': ['무상 AS', '유상 수리', 'AS 거부'],
               '웨딩홀 위약금': ['스드메 환불', '웨딩 계약 해지', '예식장 계약']}

# 글 종류: 이름, 필요한 자료(SOURCES), 기본 분야·그림·바탕색, AI에게 줄 설명
KINDS = {
    'trend': dict(name='검색 추이 분석', needs=('naver',), category='생활', emoji='📈', tone='t2',
                  about='네이버 검색어 추이로 요즘 소비자들이 어떤 피해·분쟁을 많이 찾아보는지 분석하고, 그런 일을 겪었을 때 할 일을 알려 준다.'),
    'shopping': dict(name='쇼핑 관심도 분석', needs=('naver',), category='쇼핑', emoji='🛍️', tone='t4',
                     about='네이버 쇼핑인사이트의 분야별 클릭 추이로 요즘 어떤 쇼핑 분야에 관심이 몰리는지 분석하고, 그 분야를 살 때 소비자가 챙길 점을 알려 준다.'),
    'news': dict(name='이번 주 소비자 뉴스 해설', needs=('naver',), category='생활', emoji='📰', tone='t1',
                 about='이번 주 소비자 뉴스를 쉽게 풀어 주고, 함께 준 법 조문을 근거로 소비자가 알아 둘 권리를 설명한다. 뉴스에 없는 내용은 보태지 않는다.'),
    'reports': dict(name='소보루 제보 동향', needs=('site',), category='생활', emoji='📊', tone='t3', every=7,  # 30일 집계라 매일 쓰면 같은 글이 됨: 1주에 한 번
                    about='소보루에 공개·게시된 제보 집계로 최근 어떤 피해 제보가 많았는지, 기업 답변은 어땠는지 숫자로만 전한다.'),
    'law': dict(name='법 바뀐 것 해설', needs=('law',), category='생활', emoji='⚖️', tone='t5',
                about='최근 시행됐거나 곧 시행되는 소비자 관련 법령을 쉽게 풀어 준다. 시행일·개정 이유는 자료 그대로 전한다.'),
    # 주제별 깊이 보기 (topics=True): 하루 몫이 남으면 주제를 바꿔 가며 여러 편
    'rights': dict(name='소비자 권리 깊이 보기', needs=(), category='생활', emoji='💡', tone='t5', topics=True,
                   about='[주제] 하나를 골라, 함께 준 법 조문 원문을 근거로 소비자가 가진 권리와 사업자의 의무를 깊이 풀어 준다. 조문에 없는 기간·금액은 쓰지 않고, 주제와 맞지 않는 조문은 쓰지 않는다.'),
    'word': dict(name='검색어 깊이 보기', needs=('naver',), category='생활', emoji='🔍', tone='t2', topics=True,
                 about='[주제] 검색어와 그 곁 검색어의 1년 검색 추이를 견주어 언제 왜 관심이 몰렸는지(자료로 알 수 있는 만큼만) 분석하고, 최근 뉴스와 법 조문으로 소비자가 할 일을 알려 준다.'),
    'shopcat': dict(name='쇼핑 분야 깊이 보기', needs=('naver',), category='쇼핑', emoji='🛒', tone='t4', topics=True,
                    about='[주제] 쇼핑 분야 하나의 클릭 추이와 성별·연령·기기별 비중, 다른 분야와 견준 순위를 깊이 분석하고, 그 분야를 살 때 소비자가 챙길 점을 알려 준다.'),
    # 기획 기사 (운영자 요청 2026-10-20): 뉴스·통계·법령을 엮은 잡지 기사. 주제는 최근 뉴스에서 AI가 고른 '야마'
    'feature': dict(name='소보루 기획 기사', needs=('naver',), category='생활', emoji='📌', tone='t1', topics=True, long=True,
                    about='[주제]를 소비자 잡지의 기획 기사로 깊이 쓴다. 최근 뉴스(무슨 일이 있었는지), 검색 추이 같은 통계(얼마나 관심이 몰리는지), '
                          '법 조문(소비자에게 어떤 권리가 있는지)을 엮어 하나의 이야기로 쓰고, 그래서 소비자는 무엇을 하면 되는지로 마무리한다. '
                          '[기획 각도]가 있으면 그 각도로 쓴다. 자료에 없는 사실은 보태지 않는다.'),
}
ORDER = ['trend', 'reports', 'news', 'shopping', 'law']  # 하루 한 번씩 쓰는 종류 (돌아가며 시작하는 순서)
PAUSED = {'reports'}  # 운영자 요청 2026-10-18: 제보로 쓰는 글은 아직 쓰지 않음 (매일·관리자 버튼 모두). 다시 쓰려면 여기서 뺌
EXTRA = ['feature', 'rights', 'word', 'feature', 'shopcat']  # ORDER를 한 바퀴 돈 뒤 몫이 남으면 돌아가며 채우는 주제별 글 (기획 기사를 더 자주)

SYSTEM = ('너는 소보루(소비자 정보 플랫폼)의 에디터다. 뉴닉처럼 친구에게 말하듯 친근한 해요체(~요)로, 어려운 말은 풀어서 소비자에게 쓸모 있는 분석 기사를 쓴다.\n'
          '지켜야 할 것:\n'
          '- [자료]에 있는 사실과 숫자만 쓴다. 자료에 없는 숫자(날짜·금액·비율·건수·순위·기간 모두)는 절대 쓰지 않는다.\n'
          '- 숫자를 새로 계산하지 않는다(더하기·빼기·몇 배·평균 금지). 자료에 계산돼 있는 값을 그대로 옮긴다.\n'
          '- 숫자는 자료에서 그 숫자가 붙어 있는 대상(회사·기관·지역·상품)·기간·단위와 함께 그대로 옮긴다. 여러 대상을 "각각"으로 묶을 때는 대상마다 자료의 숫자를 다시 확인한다.\n'
          '- 뉴스끼리 숫자가 다르면 한쪽을 고르지 말고 "보도마다 달라요"라고 쓰거나 그 숫자를 뺀다.\n'
          '- 뉴스 요약은 중간에 잘려 "..."로 끝날 수 있다. 잘린 문장의 숫자는 누구의 숫자인지 끝까지 보이지 않으면 쓰지 않는다(예: "국민은행과 하나은행은 각각 119명..."은 하나은행 숫자가 잘린 것이니 각각의 숫자를 쓰지 않는다).\n'
          "- 날짜는 '10월 17일'처럼 풀어 쓴다.\n"
          "- 목록이나 팁 개수를 숫자로 세지 않는다('3가지' 대신 '이렇게').\n"
          '- 인터넷 검색이나 네가 알고 있는 지식으로 사실을 보태지 않는다. 자료가 말하지 않는 원인·전망은 짐작하지 말고 필요하면 "자료만으로는 알 수 없어요"라고 쓴다.\n'
          '- 기업은 자료의 숫자만 전하고 좋다·나쁘다·악덕·갑질 같은 평가나 비난을 하지 않는다. 사람 이름·연락처 같은 개인정보는 쓰지 않는다.\n'
          '- 법 이야기는 자료의 조문·법령 정보만 근거로, "~할 수 있어요"처럼 단정하지 않게 쓴다. 법률 자문이 아니다.\n'
          '- 출처·링크·주소는 본문에 쓰지 않는다(화면에서 따로 붙인다). HTML·마크다운 기호는 쓰지 않는다.\n'
          'JSON 객체 하나로만 답한다: {"title": 40자 안팎 제목, "summary": [세 줄 요약, 문자열 3개], '
          '"highlight": 글 전체에서 가장 중요한 한 문장(자료의 사실·숫자로만), '
          '"sections": [{"emoji": 아래 이모지 중 소제목에 어울리는 것 하나, "heading": 소제목, "paragraphs": [문단 2~4개]}] 4~6개, '
          '"tips": ["이렇게 하세요"에 넣을 행동 요령 2~4개], "category": 분야 목록 중 하나}\n'
          '심층 분석 기사다: 숫자를 나열만 하지 말고 무엇이 눈에 띄는지, 소비자에게 어떤 뜻인지를 문단마다 풀어 쓴다(자료 안에서만).\n'
          '쓸 수 있는 이모지: ' + EMOJI)


class Skip(Exception):
    """이 종류는 지금 만들 수 없음 (자료 없음·키 없음). 운영자에게 보여 줄 쉬운 말."""


# ---- 숫자 검사 ---------------------------------------------------------------
NUM = re.compile(r'\d+(?:,\d{3})*(?:\.\d+)?')


def norm(s):
    """'1,234' '01' '12.50' → '1234' '1' '12.5'"""
    s = str(s).replace(',', '')
    if '.' in s:
        ip, fp = s.split('.', 1); fp = fp.rstrip('0')
        return (ip.lstrip('0') or '0') + ('.' + fp if fp else '')
    return s.lstrip('0') or '0'


def _variants(x):
    # 반올림·버림·소수 한 자리까지는 같은 숫자로 봄
    out = {norm(repr(x) if isinstance(x, float) else str(x))}
    out |= {norm(str(int(round(x)))), norm(str(int(x))), norm('%.1f' % x)}
    return out


def fact_numbers(facts):
    """자료 속 숫자 모음 {(숫자, 단위)}. 단위 없는 숫자는 단위 ''. 20261017 같은 날짜는 2026·10·17로도.
    단위: 글자 속 숫자는 바로 뒤 글자(30% → %, 3만 원 → 30000 원), 값은 키 이름(증감률(%) → %, 공개 제보(건) → 건, 위 단계 키까지)."""
    out = set()
    def add(x, unit):
        for n in _variants(x): out.add((n, '')); out.add((n, unit)) if unit else None
    def text(s):
        for m in NUM.finditer(s):
            raw = m.group(); v = float(raw.replace(',', ''))
            out.add((norm(raw), '')); add(v, '')
            u = unit_after(s, m.end())
            if u: out.add((norm(raw), u[0])); add(v * u[1], u[0])
            if re.fullmatch(r'(19|20)\d{6}', raw): out.update({(norm(raw[:4]), ''), (norm(raw[4:6]), ''), (norm(raw[6:]), '')})
    def walk(v, unit):
        if isinstance(v, bool) or v is None: return
        if isinstance(v, (int, float)): add(abs(v), unit); return
        if isinstance(v, str): text(v); return
        if isinstance(v, dict):
            for k, x in v.items(): text(str(k)); walk(x, key_unit(str(k)) or unit)
            return
        if isinstance(v, (list, tuple)):
            for x in v: walk(x, unit)
    walk(facts, '')
    return out


# 이런 단위가 붙은 숫자는 자료에서도 같은 단위로 나와야 함 ('2배'는 자료 어딘가에 2가 있어도 안 됨)
UNITS = ('%', '배', '건', '명', '원', '위')
MULT = {'만': 10000, '억': 100000000, '천': 1000}


def unit_after(s, i):
    """숫자 뒤 단위 → (단위, 곱할 수) 또는 None. '3만 원' → ('원', 10000), '30 %' → ('%', 1)"""
    rest = s[i:i + 6]
    m = re.match(r'\s?([만억천])?\s?(%|배|건|명|원|위)', rest)
    if not m: return None
    return m.group(2), MULT.get(m.group(1), 1)


def key_unit(k):
    if '%' in k or '률' in k or '비중' in k: return '%'
    for u, words in (('건', ('건',)), ('명', ('명',)), ('원', ('원', '금액', '가격'))):
        if any(w in k for w in words): return u
    return ''


def check_text(text, facts):
    """[{line, numbers|words}] — 자료에 없는 숫자, 기업 평가로 읽힐 말."""
    allowed = fact_numbers(facts); problems = []
    for line in (text or '').splitlines():
        if not line.strip(): continue
        bad = []
        for m in NUM.finditer(line):
            v = float(m.group().replace(',', ''))
            u = unit_after(line, m.end())
            if u:
                if any((n, u[0]) in allowed for n in _variants(v * u[1])): continue
            elif (norm(m.group()), '') in allowed or (line[m.end():m.end() + 1] in MULT and any((n, '') in allowed for n in _variants(v * MULT[line[m.end()]]))):
                continue
            bad.append(m.group() + (line[m.end():m.end() + 1] if u and u[1] == 1 and line[m.end():m.end() + 1] in UNITS else ''))
        words = [w for w in BANNED if w in line]
        if bad: problems.append({'line': line.strip()[:300], 'numbers': bad})
        if words: problems.append({'line': line.strip()[:300], 'words': words})
    return problems


# ---- AI 글 → 화면 글 -----------------------------------------------------------
def _plain(s, n=2000):
    s = re.sub(r'https?://\S+', '', str(s or ''))           # 링크는 화면에서 따로
    s = re.sub(r'[<>*#`]', '', s)
    return ' '.join(s.split())[:n]


def assemble(out, kind):
    """AI JSON → (제목, 요약 세 줄, 본문, 분야). 형식이 틀리면 RuntimeError."""
    if not isinstance(out, dict): raise RuntimeError('AI 응답 형식이 달라요')
    title = _plain(out.get('title'), 120)
    summary = out.get('summary') or []
    if isinstance(summary, str): summary = [x for x in re.split(r'\n+', summary)]
    summary = [_plain(x, 130) for x in summary if _plain(x)][:3]
    parts = []
    for sec in (out.get('sections') or [])[:7]:
        if not isinstance(sec, dict): continue
        paras = sec.get('paragraphs') or []
        if isinstance(paras, str): paras = re.split(r'\n\s*\n|\n', paras)
        paras = [_plain(p) for p in paras if _plain(p)][:5]
        if not paras: continue
        head = _plain(sec.get('heading'), 60)
        emo = str(sec.get('emoji') or '').strip().replace('\ufe0f', '')
        if head and emo and emo in EMOJI and len(emo) <= 2: head = emo + ' ' + head  # 글꼴에 있는 이모지만
        parts.append(('## ' + head + '\n\n' if head else '') + '\n\n'.join(paras))
    tips = out.get('tips') or []
    if isinstance(tips, str): tips = tips.split('\n')
    tips = [re.sub(r'^\s*(\d+[.)]|[-•·])\s*', '', _plain(t, 300)) for t in tips if _plain(t)][:5]
    if tips: parts.append('## ✅ 이렇게 하세요\n' + '\n'.join('- ' + t for t in tips))
    hl = _plain(out.get('highlight'), 200)
    if hl and parts: parts.insert(0, '> 💡 ' + hl)  # 맨 앞 '핵심만 쏙' 상자
    if not title or not parts: raise RuntimeError('AI가 기사를 채우지 못했어요')
    cat = out.get('category') if out.get('category') in CATS else KINDS[kind]['category']
    return title, '\n'.join(summary), '\n\n'.join(parts), cat


def clean_personal(scrub, text):
    """연락처·이메일처럼 보이는 것은 지우되(companydesk.scrub), 2026-10-17 같은 날짜는 계좌번호로 잘못 지우지 않게 지켜 둠."""
    keep = []
    def hold(m): keep.append(m.group()); return '\ue010%d\ue011' % (len(keep) - 1)
    text = re.sub(r'(?<!\d)(19|20)\d\d[-.]\d{1,2}[-.]\d{1,2}(?!\d)', hold, text or '')
    return re.sub('\ue010(\\d+)\ue011', lambda m: keep[int(m.group(1))], scrub(text))


def http_get(url, timeout=15):
    """(상태 코드, 글). 테스트에서 바꿔 끼운다."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 soboru'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e: return e.code, ''


def law_oc(): return os.getenv('LAW_OC', '').strip()


def stamp(): return datetime.datetime.now().isoformat(timespec='seconds')


def install(S):
    app = S.app; conn = S.conn; desk = S.companydesk; jebo = S.jebo
    corpus = S.triage.corpus
    with conn() as db:
        # 더하기만 하는 변경: AI 기사의 자료·출처·검사 결과 (articles 표는 그대로)
        db.execute('''CREATE TABLE IF NOT EXISTS ai_articles(article_id INTEGER PRIMARY KEY,kind TEXT NOT NULL,facts TEXT NOT NULL,sources TEXT NOT NULL,
            check_ok INTEGER NOT NULL DEFAULT 0,problems TEXT NOT NULL DEFAULT '[]',trigger TEXT NOT NULL DEFAULT 'admin',created TEXT NOT NULL,checked TEXT NOT NULL)''')

    def naver(): return app.extensions.get('naverhub') or {}

    # 자료가 연결됐는지: (켜짐, 꺼졌을 때 이유). 공공데이터는 키가 생기면 여기에 'datago'를 더함
    SOURCES = {
        'naver': lambda: (bool(naver()) and naver()['ready'](), '네이버 API HUB 키가 없어요 (deploy/set-naver.sh)'),
        'law': lambda: (bool(law_oc()), '법제처 인증키(LAW_OC)가 없어요 (deploy/set-law.sh)'),
        'site': lambda: (True, ''),
    }

    def kind_ready(kind):
        for need in KINDS[kind]['needs']:
            ok, why = SOURCES[need]()
            if not ok: return False, why
        return True, ''

    def src(name, url): return {'name': name, 'url': url if str(url).startswith(('https://', 'http://')) else '', 'fetched_at': stamp()}

    # ---- 자료 모으기 ----------------------------------------------------------
    def collect_trend():
        import naverhub
        series = naver()['trend'](TREND_WORDS, 3)
        start, end, unit = naverhub.periods(3)
        rows = []
        for name, s in series:
            vals = [v for _, v in s]
            if len(vals) < 8: continue
            last, prev = statistics.mean(vals[-4:]), statistics.mean(vals[-8:-4])
            peak = max(s, key=lambda p: p[1])
            rows.append({'검색어': name, '최근 4주 평균 지수': round(last, 1), '그 전 4주 평균 지수': round(prev, 1),
                         '증감률(%)': round((last - prev) / prev * 100) if prev else None, '가장 많이 찾은 주': peak[0], '그 주 지수': round(peak[1], 1),
                         '주별 지수': [[p, round(v, 1)] for p, v in s[-8:]]})
        if not rows: raise Skip('검색 추이 자료가 모자라요')
        rows.sort(key=lambda r: -(r['증감률(%)'] if r['증감률(%)'] is not None else -1e9))
        facts = {'자료': '네이버 데이터랩 검색어트렌드', '기간': f'{start} ~ {end}', '단위': '주',
                 '지수 설명': '검색량 그대로가 아니라 기간 안에서 가장 많이 찾은 때를 100으로 둔 상대 지수예요. 검색어끼리 같은 기준이라 견줄 수 있어요.',
                 '검색어별 추이(증감률 큰 순)': rows, '가장 많이 오른 검색어': rows[0]['검색어']}
        return {'facts': facts, 'sources': [src('네이버 데이터랩 검색어트렌드 (NAVER API HUB)', 'https://datalab.naver.com/keyword/trendSearch.naver')],
                'topic': rows[0]['검색어']}

    def collect_shopping():
        import naverhub
        nv = naver(); rows = nv['shop_overview'](3)
        rows = [r for r in rows if r['change'] is not None]
        if len(rows) < 3: raise Skip('쇼핑 관심도 자료가 모자라요')
        start, end, unit = naverhub.periods(3)
        n = max(1, max(len(r['series']) for r in rows) // 4)
        top = rows[0]
        labels = {'f': '여성', 'm': '남성', 'pc': 'PC', 'mo': '모바일'}
        split = {}
        for what, label in (('gender', '성별 클릭 비중(%)'), ('age', '연령별 클릭 비중(%)'), ('device', '기기별 클릭 비중(%)')):
            got = nv['shop_split'](top['code'], what, 3)
            split[label] = {(labels.get(k) or (dict(naverhub.AGES).get(k) or k)): v for k, v in got.items()}
        facts = {'자료': '네이버 데이터랩 쇼핑인사이트 (분야별 클릭 추이)', '기간': f'{start} ~ {end}', '단위': '주',
                 '증감 기준': f'최근 {n}주 평균 클릭 지수를 그 전 {n}주 평균과 견준 증감률이에요',
                 '분야별 증감률(%) (큰 순)': [{'분야': r['name'], '증감률(%)': r['change']} for r in rows],
                 '가장 많이 오른 분야': top['name'], f"{top['name']} 클릭 비중": split}
        return {'facts': facts, 'sources': [src('네이버 데이터랩 쇼핑인사이트 (NAVER API HUB)', 'https://datalab.naver.com/shoppingInsight/sCategory.naver')],
                'topic': top['name'], 'category': '쇼핑'}

    def collect_news():
        nv = naver(); items, seen = [], set()
        since = datetime.date.today() - datetime.timedelta(days=NEWS_DAYS)
        for q in NEWS_QUERIES:
            for it in nv['search']('news', q, display=10, sort='date')['items']:
                try: day = datetime.date(*map(int, it['date'].split('.')))
                except (ValueError, TypeError): continue
                if day < since or it['url'] in seen: continue
                seen.add(it['url']); items.append(it)
        items = items[:6]
        if len(items) < 2: raise Skip(f'최근 {NEWS_DAYS}일 소비자 뉴스가 모자라요')
        scrub = lambda t: clean_personal(desk.scrub, t)
        hits = corpus.related(' '.join(i['title'] + ' ' + i['summary'] for i in items[:3]), limit=3)
        facts = {'자료': '네이버 뉴스 검색 (제목·요약만)', '기간': f'{since.isoformat()} ~ {datetime.date.today().isoformat()}',
                 '뉴스': [{'제목': scrub(i['title']), '요약': scrub(i['summary']), '언론사': i['source'], '날짜': i['date']} for i in items],
                 '관련 법 조문(법령 원문)': [{'조문': h['label'], '원문': corpus.clip(h['text'], 700)} for h in hits]}
        sources = [src(f"{i['source']} · {i['title'][:40]}", i['url']) for i in items] + [src(f"국가법령정보센터 · {h['label']}", h['source']) for h in hits]
        return {'facts': facts, 'sources': sources, 'topic': items[0]['title']}

    def collect_reports(days=30):
        # 공개 동의 + 게시된 제보만 (비밀글·게시 전·반려·중복은 숫자에도 넣지 않음). 제목·내용은 쓰지 않고 집계만.
        today = datetime.datetime.now()
        a = (today - datetime.timedelta(days=days)).isoformat(timespec='seconds'); b = (today - datetime.timedelta(days=2 * days)).isoformat(timespec='seconds')
        with conn() as db:
            rows = db.execute("""SELECT c.id,c.category,c.company_id,c.status,c.review,c.reviewed_at,c.created,c.forwarded_at,co.name AS co_name,co.status AS co_status
                FROM cases c LEFT JOIN companies co ON co.id=c.company_id
                WHERE c.public_consent=1 AND c.published=1 AND c.review NOT IN ('rejected','duplicate') AND c.created>=?""", (b,)).fetchall()
            recent = [r for r in rows if r['created'] >= a]
            fwd = [r for r in recent if r['forwarded_at'] and r['company_id'] and r['co_status'] in ('active', 'listed') and jebo.valid(r)]
            first = jebo.first_answers(db, [r['id'] for r in fwd])
        if len(recent) < jebo.MIN_N: raise Skip(f'최근 {days}일 공개 제보가 {jebo.MIN_N}건보다 적어요')
        cats = {}
        for r in rows:
            c = cats.setdefault(jebo.cat_label(r['category']), [0, 0])
            c[0 if r['created'] >= a else 1] += 1
        by_cat = sorted(([k, v[0], v[1]] for k, v in cats.items() if v[0]), key=lambda x: -x[1])
        per = {}
        for r in fwd:
            p = per.setdefault(r['company_id'], {'기업': r['co_name'], 'n': 0, 'answered': 0, 'waits': []})
            p['n'] += 1
            if r['id'] in first:
                p['answered'] += 1; h = jebo.hours(r['forwarded_at'], first[r['id']])
                if h is not None and h >= 0: p['waits'].append(h)
        cos = []
        for p in sorted(per.values(), key=lambda p: -p['n']):
            if p['n'] < jebo.MIN_N: continue  # 표본이 적으면 비율을 내지 않음 (기업 페이지와 같은 기준)
            cos.append({'기업': p['기업'], '기업에 전달된 공개 제보(건)': p['n'], '답변한 제보(건)': p['answered'], '답변률(%)': round(100 * p['answered'] / p['n']),
                        '첫 답변까지 걸린 시간(중앙값)': jebo.fmt_hours(statistics.median(p['waits'])) if p['waits'] else '–'})
        facts = {'자료': '소보루에 공개·게시된 제보 집계 (비공개 제보 제외, 중복·반려 제외)', '집계 기간': f'최근 {days}일 ({a[:10]} ~ {today:%Y-%m-%d})',
                 '최근 공개 제보(건)': len(recent), f'그 전 {days}일 공개 제보(건)': len(rows) - len(recent),
                 '유형별 공개 제보 [유형, 최근(건), 그 전(건)] (많은 순)': by_cat,
                 '기업별 답변 (공개 제보 %d건 이상인 기업만, 많은 순)' % jebo.MIN_N: cos[:5],
                 '기업 숫자 안내': '숫자만 전하고 기업을 평가하지 않아요. 답변률은 기업이 답변을 1번 이상 단 제보 ÷ 기업에 전달된 공개 제보예요.'}
        return {'facts': facts, 'sources': [src('소보루 공개 제보 통계', SITE + '/reports')], 'topic': by_cat[0][0] if by_cat else ''}

    def law_xml(path, params):
        last = None
        for base in ('http://www.law.go.kr', 'https://www.law.go.kr'):
            try:
                st, body = http_get(base + path + '?' + urllib.parse.urlencode(dict(OC=law_oc(), type='XML', **params)), 20)
                if st == 200 and body.strip().startswith('<'): return ET.fromstring(body.encode('utf-8'))
                last = st
            except (OSError, ET.ParseError) as e: last = type(e).__name__
        raise Skip(f'법제처 응답을 받지 못했어요 ({last})')

    def collect_law(back=14, ahead=30):
        today = datetime.date.today()
        d0, d1 = today - datetime.timedelta(days=back), today + datetime.timedelta(days=ahead)
        root = law_xml('/DRF/lawSearch.do', {'target': 'law', 'display': 100, 'efYd': f'{d0:%Y%m%d}~{d1:%Y%m%d}'})
        iso = lambda s: f'{s[:4]}-{s[4:6]}-{s[6:8]}' if re.fullmatch(r'\d{8}', s or '') else (s or '')
        laws = []
        for el in root.iter('law'):
            t = lambda k: (el.findtext(k) or '').strip()
            name = t('법령명한글')
            if not name or not any(w in name for w in LAW_WORDS): continue
            laws.append({'법령': name, '구분': t('법령구분명'), '제정·개정': t('제개정구분명'), '공포일': iso(t('공포일자')), '시행일': iso(t('시행일자')),
                         '소관 부처': t('소관부처명'), '_mst': t('법령일련번호')})
        if not laws: raise Skip('최근·곧 시행되는 소비자 관련 법령이 없어요')
        # 오늘과 가까운 시행일 먼저 (곧 시행 → 막 시행)
        laws.sort(key=lambda l: abs((datetime.date.fromisoformat(l['시행일']) - today).days) if re.fullmatch(r'\d{4}-\d\d-\d\d', l['시행일']) else 999)
        laws = laws[:3]
        for l in laws:
            mst = l.pop('_mst')
            if not mst: continue
            try: d = law_xml('/DRF/lawService.do', {'target': 'law', 'MST': mst})
            except Skip: continue
            why = ' '.join(' '.join(x.itertext()) for x in d.iter('제개정이유내용')).strip() or ' '.join(' '.join(x.itertext()) for x in d.iter('개정문내용')).strip()
            if why: l['개정 이유(원문 일부)'] = corpus.clip(' '.join(why.split()), 1500)
        facts = {'자료': '법제처 국가법령정보 Open API', '오늘': today.isoformat(), '찾은 범위(시행일)': f'{d0.isoformat()} ~ {d1.isoformat()}', '법령': laws}
        sources = [src(f"국가법령정보센터 · {l['법령']}", 'https://www.law.go.kr/법령/' + l['법령']) for l in laws]
        return {'facts': facts, 'sources': sources, 'topic': laws[0]['법령']}

    # ---- 주제별 깊이 보기 ------------------------------------------------------
    def recent_news(q, days=30, n=4):
        if not SOURCES['naver']()[0]: return []
        since = datetime.date.today() - datetime.timedelta(days=days); out = []
        try: items = naver()['search']('news', q, display=10, sort='date')['items']
        except Exception: return []  # 뉴스는 곁들이는 자료라 못 가져와도 글은 씀
        for it in items:
            try: day = datetime.date(*map(int, it['date'].split('.')))
            except (ValueError, TypeError): continue
            if day >= since: out.append(it)
        return out[:n]

    def news_facts(items):
        scrub = lambda t: clean_personal(desk.scrub, t)
        return [{'제목': scrub(i['title']), '요약': scrub(i['summary']), '언론사': i['source'], '날짜': i['date']} for i in items]

    def collect_rights(topic):
        hits = corpus.related(topic, limit=5)
        if len(hits) < 2: raise Skip(f'"{topic}"와 맞는 법 조문을 찾지 못했어요')
        news = recent_news(topic)
        facts = {'자료': '소보루 법령 원문 모음 (국가법령정보센터 법령·소비자분쟁해결기준·찾기 쉬운 생활법령정보)', '주제': topic,
                 '관련 법 조문(원문)': [{'조문': h['label'], '원문': corpus.clip(h['text'], 900)} for h in hits]}
        if news: facts['최근 관련 뉴스(제목·요약만)'] = news_facts(news)
        sources = [src(f"국가법령정보센터 · {h['label']}", h['source']) for h in hits] + [src(f"{i['source']} · {i['title'][:40]}", i['url']) for i in news]
        return {'facts': facts, 'sources': sources, 'topic': topic}

    def collect_word(topic):
        import naverhub
        words = [topic] + WORD_TOPICS[topic][:4]
        series = naver()['trend'](words, 12)
        start, end, unit = naverhub.periods(12)
        partial = (datetime.date.fromisoformat(end) + datetime.timedelta(days=1)).day != 1  # 이번 달이 덜 찼으면 마지막 달은 뺌
        month = lambda p: f'{p[:4]}년 {int(p[5:7])}월'
        rows = []
        for name, s in series:
            s = s[:-1] if partial and s else s
            vals = [v for _, v in s]
            if len(vals) < 6: continue
            last, prev = statistics.mean(vals[-3:]), statistics.mean(vals[-6:-3])
            peak = max(s, key=lambda p: p[1])
            rows.append({'검색어': name, '최근 3달 평균 지수': round(last, 1), '그 전 3달 평균 지수': round(prev, 1),
                         '증감률(%)': round((last - prev) / prev * 100) if prev else None, '가장 많이 찾은 달': month(peak[0]), '그 달 지수': round(peak[1], 1),
                         '달별 지수': [[month(p), round(v, 1)] for p, v in s]})
        if not rows or rows[0]['검색어'] != topic: raise Skip(f'"{topic}" 검색 추이 자료가 모자라요')
        news = recent_news(topic)
        hits = corpus.related(' '.join(words), limit=3)
        facts = {'자료': '네이버 데이터랩 검색어트렌드', '주제 검색어': topic, '기간': f'{start} ~ {end}', '단위': '달',
                 '지수 설명': '검색량 그대로가 아니라 기간 안에서 다섯 검색어 가운데 가장 많이 찾은 때를 100으로 둔 상대 지수예요. 검색어끼리 견줄 수 있어요.',
                 '검색어별 추이': rows}
        if news: facts['최근 관련 뉴스(제목·요약만)'] = news_facts(news)
        if hits: facts['관련 법 조문(원문)'] = [{'조문': h['label'], '원문': corpus.clip(h['text'], 600)} for h in hits]
        sources = ([src('네이버 데이터랩 검색어트렌드 (NAVER API HUB)', 'https://datalab.naver.com/keyword/trendSearch.naver')]
                   + [src(f"{i['source']} · {i['title'][:40]}", i['url']) for i in news] + [src(f"국가법령정보센터 · {h['label']}", h['source']) for h in hits])
        return {'facts': facts, 'sources': sources, 'topic': topic}

    def collect_shopcat(topic):
        import naverhub
        nv = naver(); rows = nv['shop_overview'](3)
        ranked = [r for r in rows if r['change'] is not None]
        me = next((r for r in ranked if r['name'] == topic), None)
        if not me or len(me['series']) < 8: raise Skip(f'{topic} 쇼핑 관심도 자료가 모자라요')
        start, end, unit = naverhub.periods(3)
        n = max(1, len(me['series']) // 4)
        labels = {'f': '여성', 'm': '남성', 'pc': 'PC', 'mo': '모바일'}
        facts = {'자료': '네이버 데이터랩 쇼핑인사이트 (분야별 클릭 추이)', '분야': topic, '기간': f'{start} ~ {end}', '단위': '주',
                 '증감 기준': f'최근 {n}주 평균 클릭 지수를 그 전 {n}주 평균과 견준 증감률이에요',
                 f'{topic} 증감률(%)': me['change'], '증감률 순위': f'{len(ranked)}개 분야 가운데 {ranked.index(me) + 1}위',
                 f'{topic} 주별 클릭 지수': [[p, round(v, 1)] for p, v in me['series'][-12:]],
                 '다른 분야 증감률(%)': [{'분야': r['name'], '증감률(%)': r['change']} for r in ranked if r is not me]}
        for what, label in (('gender', '성별 클릭 비중(%)'), ('age', '연령별 클릭 비중(%)'), ('device', '기기별 클릭 비중(%)')):
            got = nv['shop_split'](me['code'], what, 3)
            facts[label] = {(labels.get(k) or (dict(naverhub.AGES).get(k) or k)): v for k, v in got.items()}
        return {'facts': facts, 'sources': [src('네이버 데이터랩 쇼핑인사이트 (NAVER API HUB)', 'https://datalab.naver.com/shoppingInsight/sCategory.naver')],
                'topic': topic, 'category': '쇼핑'}

    # ---- 기획 기사: 주제(야마) 고르기 · 자료 모으기 ------------------------------------
    def chat(system, user, max_tokens, timeout=AI_TIMEOUT):
        key = os.getenv('OPENAI_API_KEY', '').strip()
        if not key: raise RuntimeError('OpenAI API 키가 없어요')
        body = {'model': desk.ai_model(), 'temperature': 0.4, 'response_format': {'type': 'json_object'}, 'max_tokens': max_tokens,
                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
        st, res = desk.post_json('https://api.openai.com/v1/chat/completions', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, timeout)
        if st != 200: raise RuntimeError(f'AI 응답 오류 ({st}) ' + str((res.get('error') or {}).get('message', ''))[:120].replace(key, '***'))
        try: return json.loads(res['choices'][0]['message']['content'])
        except (KeyError, IndexError, TypeError, ValueError): raise RuntimeError('AI 응답을 읽지 못했어요')

    def clean_topic(t): return ' '.join(re.sub(r'[:\n\r]', ' ', str(t or '')).split())[:24]

    def feature_ideas(day):
        """최근 사흘 소비자 뉴스 제목에서 AI가 기획 주제를 고름: [{topic, angle, category}]. 뉴스·AI가 안 되면 []."""
        if not SOURCES['naver']()[0] or not desk.ai_ready(): return []
        heads, seen = [], set()
        for q in FEATURE_QUERIES:
            for it in recent_news(q, days=3, n=10):
                t = clean_personal(desk.scrub, it['title'])
                if t not in seen: seen.add(t); heads.append(t)
        if len(heads) < 5: return []
        since = (datetime.date.fromisoformat(day) - datetime.timedelta(days=FEATURE_FRESH)).isoformat()
        with conn() as db: titles = [r[0] for r in db.execute("SELECT title FROM articles WHERE origin='ai' AND substr(created,1,10)>=? ORDER BY id DESC LIMIT 80", (since,))]
        user = ('[최근 소비자 뉴스 제목]\n' + '\n'.join('- ' + h for h in heads[:80]) + '\n[최근 우리가 쓴 기사 제목]\n' + '\n'.join('- ' + t for t in titles))
        system = ('너는 소비자 잡지 소보루의 편집장이다. 뉴스 제목들을 보고 소비자에게 쓸모 있고 읽고 싶어질 기획 기사 주제(야마)를 12개 고른다.\n'
                  '- 같은 일을 다룬 뉴스는 하나의 주제로 묶는다. 우리가 최근 쓴 기사와 겹치는 주제는 고르지 않는다. 주제끼리도 겹치지 않게 한다.\n'
                  '- topic은 뉴스 검색에 넣을 2~12자 낱말(예: 배달앱 수수료), angle은 기사의 각도 한 문장(숫자 없이), category는 '
                  + ', '.join(CATS) + ' 가운데 하나. 분야가 한쪽으로 몰리지 않게 고르게 고른다.\n'
                  'JSON으로만 답한다: {"ideas": [{"topic": ..., "angle": ..., "category": ...}]}')
        try: out = chat(system, user, 1500)
        except Exception: return []  # 주제 고르기가 안 되면 분야별 기본 주제로
        ideas, seen = [], set()
        for i in (out.get('ideas') or [])[:16] if isinstance(out, dict) else []:
            if not isinstance(i, dict): continue
            t = clean_topic(i.get('topic'))
            if len(t) < 2 or t in seen: continue
            angle = _plain(i.get('angle'), 120)
            seen.add(t); ideas.append({'topic': t, 'angle': '' if re.search(r'\d', angle) else angle,  # 각도에 숫자가 있으면 지어낸 숫자일 수 있어 뺌
                                       'category': i.get('category') if i.get('category') in CATS else '생활'})
        return ideas

    def feature_pool(day):
        """오늘의 기획 주제 후보: 뉴스로 고른 것(하루 한 번 만들어 둠) + 분야별 기본 주제"""
        saved = setting('writer_feature_pool', {})
        if not (isinstance(saved, dict) and saved.get('day') == day):
            saved = {'day': day, 'ideas': feature_ideas(day)}; put('writer_feature_pool', saved)
        return (saved.get('ideas') or []) + [{'topic': t, 'angle': '', 'category': c} for c, ts in FEATURE_TOPICS.items() for t in ts]

    def cat_counts(day, days=7):
        """최근 며칠 사이 분야별 생활정보 글 수 (게시·초안 모두)"""
        since = (datetime.date.fromisoformat(day) - datetime.timedelta(days=days - 1)).isoformat()
        got = {c: 0 for c in CATS}
        with conn() as db:
            for r in db.execute("SELECT category,COUNT(*) FROM articles WHERE substr(created,1,10)>=? GROUP BY category", (since,)):
                if r[0] in got: got[r[0]] = r[1]
        return got

    def collect_feature(topic):
        today = datetime.date.today().isoformat()
        idea = next((i for i in feature_pool(today) if i['topic'] == topic), {'angle': '', 'category': '생활'})
        news = recent_news(topic, days=30, n=6)
        hits = corpus.related((topic + ' ' + idea['angle']).strip(), limit=4)
        if len(news) < 2 and len(hits) < 2: raise Skip(f'"{topic}" 뉴스와 법 조문이 모자라요')
        facts = {'자료': '네이버 뉴스 검색(제목·요약만) · 네이버 데이터랩 검색어트렌드 · 소보루 법령 원문 모음', '주제': topic}
        if idea['angle']: facts['기획 각도'] = idea['angle']
        if news: facts['최근 관련 뉴스(제목·요약만)'] = news_facts(news)
        sources = [src(f"{i['source']} · {i['title'][:40]}", i['url']) for i in news]
        try:
            import naverhub
            series = naver()['trend']([topic], 12); start, end, unit = naverhub.periods(12)
            vals = series[0][1] if series else []
            if len(vals) >= 6:
                v = [x for _, x in vals]; last, prev = statistics.mean(v[-3:]), statistics.mean(v[-6:-3]); peak = max(vals, key=lambda p: p[1])
                facts['검색 추이(네이버 데이터랩)'] = {'기간': f'{start} ~ {end}', '단위': '달', '지수 설명': '기간 안에서 가장 많이 찾은 달을 100으로 둔 상대 지수예요',
                                              '최근 3달 평균 지수': round(last, 1), '그 전 3달 평균 지수': round(prev, 1),
                                              '증감률(%)': round((last - prev) / prev * 100) if prev else None, '가장 많이 찾은 달': f'{peak[0][:4]}년 {int(peak[0][5:7])}월'}
                sources.append(src('네이버 데이터랩 검색어트렌드 (NAVER API HUB)', 'https://datalab.naver.com/keyword/trendSearch.naver'))
        except Exception: pass  # 통계는 곁들이는 자료라 못 가져와도 글은 씀
        if hits:
            facts['관련 법 조문(원문)'] = [{'조문': h['label'], '원문': corpus.clip(h['text'], 700)} for h in hits]
            sources += [src(f"국가법령정보센터 · {h['label']}", h['source']) for h in hits]
        return {'facts': facts, 'sources': sources, 'topic': topic, 'category': idea['category']}

    def topic_list(kind):
        import naverhub
        if kind == 'feature': return [i['topic'] for i in feature_pool(datetime.date.today().isoformat())]
        return {'rights': RIGHTS_TOPICS, 'word': list(WORD_TOPICS), 'shopcat': [n for _, n in naverhub.SHOP_CATS]}[kind]

    def pick_topic(kind, day, avoid=()):
        """FRESH_DAYS 안에 쓰지 않은 주제 가운데 가장 오래전에 쓴(또는 한 번도 안 쓴) 것. 없으면 None.
        기획 기사는 30일 안에 어느 종류로든 쓴 주제를 빼고, 최근 글이 적은 분야의 주제부터 (뉴스로 고른 주제가 먼저)."""
        feature = kind == 'feature'
        since = (datetime.date.fromisoformat(day) - datetime.timedelta(days=(FEATURE_FRESH if feature else FRESH_DAYS) - 1)).isoformat(); last = {}
        with conn() as db:
            for r in db.execute('SELECT ext_key,created FROM articles WHERE ext_key LIKE ?', ('ai:%' if feature else f'ai:{kind}:%',)):
                parts = r['ext_key'].split(':')
                if len(parts) >= 4: last[parts[2]] = max(last.get(parts[2], ''), r['created'][:10])
        if feature:
            n = cat_counts(day); pool = feature_pool(day)
            free = [(n.get(i['category'], 0), k, i['topic']) for k, i in enumerate(pool) if last.get(i['topic'], '') < since and i['topic'] not in avoid]
            return min(free)[2] if free else None
        free = [t for t in topic_list(kind) if last.get(t, '') < since and t not in avoid]
        return min(free, key=lambda t: last.get(t, '')) if free else None

    COLLECT = {'trend': collect_trend, 'shopping': collect_shopping, 'news': collect_news, 'reports': collect_reports, 'law': collect_law,
               'rights': collect_rights, 'word': collect_word, 'shopcat': collect_shopcat, 'feature': collect_feature}

    def collect(kind, topic=None):
        ok, why = kind_ready(kind)
        if not ok: raise Skip(why)
        if KINDS[kind].get('topics') and not topic:
            topic = pick_topic(kind, datetime.date.today().isoformat())
            if not topic: raise Skip(f'최근 {FRESH_DAYS}일 안에 주제를 다 썼어요')
        try: got = COLLECT[kind](topic) if KINDS[kind].get('topics') else COLLECT[kind]()
        except Skip: raise
        except Exception as e:  # 네이버 오류 문구(NaverError)는 그대로, 그 밖은 이름만 (키가 섞이지 않게)
            raise Skip(str(e)[:120] if type(e).__name__ == 'NaverError' else f'자료를 가져오지 못했어요 ({type(e).__name__})')
        got['facts'] = dict(got['facts'], **CONST)
        return got

    # ---- 설정 ---------------------------------------------------------------
    def setting(key, default):
        with conn() as db: row = db.execute('SELECT value FROM soboru_settings WHERE key=?', (key,)).fetchone()
        try: return json.loads(row[0]) if row else default
        except ValueError: return default

    def put(key, value):
        with conn() as db: db.execute('INSERT OR REPLACE INTO soboru_settings(key,value) VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))

    def settings():
        s = setting('writer', {})
        # publish: 자동으로 쓴 글 중 숫자 검사를 통과한 글은 관리자 승인 없이 바로 게시 (운영자 요청 2026-10-17, 관리자에서 멈출 수 있음)
        # per_run: 아침·오후·저녁 한 번에 쓰는 글 수. 하루 한 번 쓰던 때(v 3 전) 저장한 값은 새 기본(5개씩)으로
        per = s.get('per_run') if s.get('v') == 3 and s.get('per_run') in PER_RUN else DEFAULT_PER_RUN
        return {'auto': 0 if s.get('auto') == 0 else 1, 'per_run': per, 'per_day': per * len(SLOTS), 'publish': 0 if s.get('publish') == 0 else 1}

    def save_settings(auto, per_run, publish):
        put('writer', {'auto': auto, 'per_run': per_run if per_run in PER_RUN else DEFAULT_PER_RUN, 'publish': publish, 'v': 3})

    def log(entry):
        rows = setting('writer_log', [])
        put('writer_log', ([dict(entry, at=stamp())] + rows)[:30])

    # ---- AI로 쓰기 · 저장 -------------------------------------------------------
    def ask_ai(kind, facts, topic=None):
        k = KINDS[kind]
        long = ("[분량] 잡지 기획 기사다. 소제목 5~6개, 소제목마다 문단 3~4개로 넉넉히 쓴다. 뉴스(무슨 일)·통계(얼마나)·법 조문(어떤 권리)을 "
                "한 이야기로 엮고, 마지막 소제목은 소비자가 할 일로 마무리한다.\n") if k.get('long') else ''
        user = (f"[글 종류] {k['name']}: {k['about']}\n" + (f"[주제] {topic}\n" if topic else '') + long + "[분야 목록] " + ', '.join(CATS) + "\n"
                f"[자료]\n{json.dumps(facts, ensure_ascii=False, indent=1)}")
        return chat(SYSTEM, user, 6000 if k.get('long') else 4500, AI_TIMEOUT * 2 if k.get('long') else AI_TIMEOUT)

    def save_check(db, article_id, title, summary, body, facts):
        problems = check_text('\n'.join([title, summary, body]), facts)
        db.execute('UPDATE ai_articles SET check_ok=?,problems=?,checked=? WHERE article_id=?', (0 if problems else 1, json.dumps(problems, ensure_ascii=False), stamp(), article_id))
        return problems

    PAIR_SYSTEM = ('너는 잡지 교열 기자야. [자료]와 [글]을 비교해서, 글 속 숫자가 자료와 다른 대상·기간·단위에 붙은 문장만 찾아. '
                   '예: 자료는 "국민 119명, 하나 89명"인데 글은 "국민은행과 하나은행이 각각 119명". 뉴스 요약이 "..."로 잘려 대상과 숫자의 짝이 끝까지 보이지 않는데 글이 짝을 지어 쓴 문장도 찾아. 숫자가 자료에 있는지가 아니라 누구의·무엇의 숫자인지가 맞는지를 봐. '
                   '문제가 없으면 빈 목록. JSON만: {"problems": [{"line": "글의 그 문장", "why": "자료에서는 무엇이 몇인지 짧게"}]}')

    def pair_check(title, summary, body, facts):
        """숫자가 맞는 대상에 붙었는지 AI 교열 (숫자 검사는 자료에 그 숫자가 있는지만 봐서, 은행 A의 숫자를 은행 B에 붙여도 통과함).
        문제 [{line, pair}]. 교열을 못 하면 바로 게시하지 않게 문제 하나로 돌려줌."""
        text = '\n'.join([title, summary, body])
        if not NUM.search(text): return []
        user = '[자료]\n' + json.dumps(facts, ensure_ascii=False)[:12000] + '\n\n[글]\n' + text[:12000]
        try: got = chat(PAIR_SYSTEM, user, 1500)
        except RuntimeError as e: return [{'line': '숫자 짝 검사를 못 했어요', 'pair': str(e)[:120]}]
        out = []
        for p in (got.get('problems') or [])[:10] if isinstance(got, dict) else []:
            if isinstance(p, dict) and str(p.get('line', '')).strip():
                out.append({'line': _plain(p['line'], 300), 'pair': _plain(p.get('why', ''), 200) or '숫자가 다른 대상에 붙었어요'})
        return out

    def generate(kind, trigger='admin', force=False, day=None, topic=None, avoid=()):
        """{status: made|exists|skip|error, id, reason, published}. 관리자가 만든 글은 초안(draft). 매일 자동으로 쓴 글은
        '바로 게시'가 켜져 있고 숫자 검사를 통과하면 게시하고, 아니면 초안으로 남긴다."""
        if kind not in KINDS: return {'status': 'error', 'reason': '모르는 글 종류예요'}
        today = day or datetime.date.today().isoformat()
        if KINDS[kind].get('topics'):  # 주제별 글은 주제마다 하루 한 번 (같은 주제는 FRESH_DAYS 동안 다시 안 씀)
            topic = topic or pick_topic(kind, today, avoid)
            if not topic:
                res = {'status': 'skip', 'reason': f'최근 {FRESH_DAYS}일 안에 주제를 다 썼어요'}; log(dict(res, kind=kind, trigger=trigger)); return res
            key = f'ai:{kind}:{topic}:{today}'
        else: key = f'ai:{kind}:{today}'
        with conn() as db: old = db.execute('SELECT id,status FROM articles WHERE ext_key=?', (key,)).fetchone()
        if old and (not force or old['status'] != 'draft'): return {'status': 'exists', 'id': old['id'], 'reason': '오늘 이미 만든 초안이 있어요'}
        every = KINDS[kind].get('every', 1)
        if trigger == 'daily' and every > 1:
            since = (datetime.date.fromisoformat(day or datetime.date.today().isoformat()) - datetime.timedelta(days=every - 1)).isoformat()
            with conn() as db:
                recent = db.execute("SELECT 1 FROM ai_articles x JOIN articles a ON a.id=x.article_id WHERE x.kind=? AND substr(x.created,1,10)>=?", (kind, since)).fetchone()
            if recent:
                res = {'status': 'skip', 'reason': '%d일에 한 번만 써요' % every}; log(dict(res, kind=kind, trigger=trigger)); return res
        try:
            got = collect(kind, topic)
            title, summary, body, cat = assemble(ask_ai(kind, got['facts'], topic), kind)
        except Skip as e: res = {'status': 'skip', 'reason': str(e), 'topic': topic}; log(dict(res, kind=kind, trigger=trigger)); return res
        except RuntimeError as e: res = {'status': 'error', 'reason': str(e), 'topic': topic}; log(dict(res, kind=kind, trigger=trigger)); return res
        title, summary, body = (clean_personal(desk.scrub, t) for t in (title, summary, body))  # 연락처처럼 보이는 것은 지움
        if trigger == 'daily':  # 최근 30일 안에 같은 제목 글이 있으면 또 올리지 않음
            since = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
            with conn() as db:
                same = [r['id'] for r in db.execute('SELECT id,title FROM articles WHERE substr(created,1,10)>=?', (since,)) if ''.join(r['title'].split()) == ''.join(title.split()) and (not old or r['id'] != old['id'])]
            if same:
                res = {'status': 'skip', 'reason': '같은 제목의 글이 이미 있어요', 'topic': topic}; log(dict(res, kind=kind, trigger=trigger)); return res
        k = KINDS[kind]; cat = got.get('category') or cat; first = got['sources'][0] if got['sources'] else {'name': '', 'url': ''}
        facts_s, sources_s = json.dumps(got['facts'], ensure_ascii=False), json.dumps(got['sources'], ensure_ascii=False)
        with conn() as db:
            if old:
                aid = old['id']
                db.execute("UPDATE articles SET title=?,summary=?,body=?,category=?,source_name=?,source_url=?,status='draft',updated=? WHERE id=?",
                           (title, summary, body, cat, first['name'][:120], first['url'][:500], stamp(), aid))
            else:
                aid = db.execute("INSERT INTO articles(title,summary,body,category,emoji,tone,source_name,source_url,status,origin,ext_key,created,updated) VALUES(?,?,?,?,?,?,?,?,'draft','ai',?,?,?)",
                                 (title, summary, body, cat, k['emoji'], k['tone'], first['name'][:120], first['url'][:500], key, stamp(), stamp())).lastrowid
            db.execute('INSERT OR REPLACE INTO ai_articles(article_id,kind,facts,sources,trigger,created,checked) VALUES(?,?,?,?,?,?,?)',
                       (aid, kind, facts_s, sources_s, trigger, stamp(), stamp()))
            problems = save_check(db, aid, title, summary, body, got['facts'])
        if not problems:  # 숫자가 다 자료에 있어도, 누구의 숫자인지 바뀌었으면 초안으로 (운영자 지적 2026-10-20: 하나은행 89명 → 119명)
            problems = pair_check(title, summary, body, got['facts'])
            if problems:
                with conn() as db: db.execute('UPDATE ai_articles SET check_ok=0,problems=? WHERE article_id=?', (json.dumps(problems, ensure_ascii=False), aid))
        with conn() as db:
            published = trigger == 'daily' and not problems and settings()['publish'] == 1
            if published: db.execute("UPDATE articles SET status='published',published_at=?,updated=? WHERE id=?", (stamp(), stamp(), aid))
        art = app.extensions.get('soboru_art')  # 저장한 글처럼 AI 일러스트 자동 그리기 (키가 있을 때만)
        if art: art['auto']('life', aid, wait=trigger == 'daily')
        res = {'status': 'made', 'id': aid, 'published': published, 'reason': '숫자 검토 필요 %d곳' % len(problems) if problems else ('바로 게시했어요' if published else '')}
        log(dict(res, kind=kind, trigger=trigger))
        return res

    def slots_passed(now=None):
        """오늘 지난 쓰기 때 수 (아침 7시 전에 손으로 돌려도 한 번 몫은 씀)"""
        try:
            from zoneinfo import ZoneInfo
            now = now or datetime.datetime.now(ZoneInfo('Asia/Seoul'))
        except Exception: now = now or datetime.datetime.now()
        return max(1, sum(1 for h in SLOTS if now.hour >= h))

    def daily(today=None, now=None):
        """아침·오후·저녁마다 per_run개씩 (ORDER 한 바퀴 → 남으면 EXTRA 주제별 글). 지난 때 몫까지 채움(서버가 꺼져 있었을 때).
        꺼 뒀거나 AI 키가 없으면 아무것도 안 함. 게시 여부는 generate가 정함."""
        cfg = settings(); day = today or datetime.date.today().isoformat()
        if not cfg['auto']: return [{'status': 'off', 'reason': '자동 쓰기를 꺼 두었어요'}]
        if not desk.ai_ready(): log({'status': 'skip', 'kind': '', 'trigger': 'daily', 'reason': 'OpenAI API 키가 없어요'}); return [{'status': 'skip', 'reason': 'OpenAI API 키가 없어요'}]
        with conn() as db:
            done = db.execute("SELECT COUNT(*) FROM ai_articles x JOIN articles a ON a.id=x.article_id WHERE x.trigger='daily' AND substr(x.created,1,10)=?", (day,)).fetchone()[0]
        want = cfg['per_run'] * slots_passed(now) - done; turn = setting('writer_turn', 0)
        turn = turn if isinstance(turn, int) else 0
        if want <= 0: return []  # 오늘 몫은 이미 다 씀 (순서도 그대로)
        out = []
        for i in range(len(ORDER)):
            if want <= 0: break
            kind = ORDER[(turn + i) % len(ORDER)]
            if kind in PAUSED: continue
            ok, why = kind_ready(kind)
            if not ok: out.append({'status': 'skip', 'kind': kind, 'reason': why}); continue
            r = dict(generate(kind, 'daily', day=day), kind=kind); out.append(r)
            if r['status'] == 'made': want -= 1
        put('writer_turn', (turn + 1) % len(ORDER))
        # 아직 하루 몫이 남으면 주제별 깊이 보기 글로 돌아가며 채움 (실패가 이어져도 AI를 끝없이 부르지 않게 횟수를 막음)
        xturn = setting('writer_xturn', 0); xturn = xturn if isinstance(xturn, int) else 0
        dead, tried = set(), set()  # tried: 이번에 못 쓴 주제 (같은 제목·자료 모자람) — 같은 주제로 AI를 다시 부르지 않게
        nxt = xturn
        for i in range(want + len(EXTRA) * 2):
            if want <= 0 or len(dead) == len(EXTRA): break
            kind = EXTRA[(xturn + i) % len(EXTRA)]
            if kind in dead: continue
            ok, why = kind_ready(kind)
            if not ok: dead.add(kind); out.append({'status': 'skip', 'kind': kind, 'reason': why}); continue
            r = dict(generate(kind, 'daily', day=day, avoid=tried), kind=kind); out.append(r)
            nxt = xturn + i + 1
            if r['status'] == 'made': want -= 1
            elif r['status'] == 'skip' and '주제를 다 썼어요' in r.get('reason', ''): dead.add(kind)
            elif r.get('topic'): tried.add(r['topic'])
        put('writer_xturn', nxt % len(EXTRA))  # 다음 때는 이번에 멈춘 바로 다음 종류부터
        return out

    # ---- 화면에서 쓰는 정보 ------------------------------------------------------
    def ai_info(row):
        try: problems = json.loads(row['problems'])
        except ValueError: problems = []
        try: sources = json.loads(row['sources'])
        except ValueError: sources = []
        return {'kind': row['kind'], 'kind_name': KINDS.get(row['kind'], {}).get('name', row['kind']), 'ok': bool(row['check_ok']), 'problems': problems,
                'sources': sources, 'facts': row['facts'], 'trigger': row['trigger'], 'created': row['created'], 'checked': row['checked']}

    def ai_article(article_id):
        with conn() as db:
            row = db.execute("SELECT x.* FROM ai_articles x JOIN articles a ON a.id=x.article_id AND a.origin='ai' WHERE x.article_id=?", (article_id,)).fetchone()
        return ai_info(row) if row else None

    def ai_marks():
        if g.get('_ai_marks') is None:
            with conn() as db:
                g._ai_marks = {r['article_id']: ai_info(r) for r in db.execute("SELECT x.* FROM ai_articles x JOIN articles a ON a.id=x.article_id AND a.origin='ai'")}
        return g._ai_marks
    app.jinja_env.globals.update(ai_article=ai_article, ai_marks=ai_marks)

    # ---- 관리자 화면 -----------------------------------------------------------
    def job_state(): return setting('writer_job', {})

    @app.route('/admin/life/ai', methods=['GET', 'POST'])
    @S.admin_only
    def admin_life_ai():
        if request.method == 'POST':
            kind = request.form.get('kind', '')
            if kind not in KINDS: abort(400)
            if kind in PAUSED: flash('이 글 종류는 지금 쓰지 않도록 멈춰 두었어요.'); return redirect(url_for('admin_life_ai'))
            if not desk.ai_ready(): flash('OpenAI API 키가 없어서 기사를 쓸 수 없어요.'); return redirect(url_for('admin_life_ai'))
            ok, why = kind_ready(kind)
            if not ok: flash(why); return redirect(url_for('admin_life_ai'))
            force = request.form.get('force') == '1'
            if app.config.get('TESTING'):
                r = generate(kind, 'admin', force)
                return done(r)
            if job_state().get('state') == 'running' and job_state().get('at', '') > (datetime.datetime.now() - datetime.timedelta(minutes=5)).isoformat():
                flash('다른 기사를 쓰고 있어요. 잠시 뒤 다시 눌러 주세요.'); return redirect(url_for('admin_life_ai_job'))
            put('writer_job', {'state': 'running', 'kind': kind, 'at': stamp()})
            def run():
                try: r = generate(kind, 'admin', force)
                except Exception as e: r = {'status': 'error', 'reason': f'기사를 쓰지 못했어요 ({type(e).__name__})'}
                put('writer_job', dict(r, state='done', kind=kind, at=stamp()))
            threading.Thread(target=run, daemon=True).start()  # AI가 1분 가까이 걸릴 수 있어 뒤에서 (서버 응답 시간 제한)
            return redirect(url_for('admin_life_ai_job'))
        with conn() as db:
            rows = db.execute("SELECT a.id,a.title,a.status,a.category,a.created,x.* FROM ai_articles x JOIN articles a ON a.id=x.article_id AND a.origin='ai' ORDER BY a.id DESC LIMIT 60").fetchall()
        kinds = [dict(KINDS[k], key=k, ready=kind_ready(k)[0], why=kind_ready(k)[1]) for k in dict.fromkeys(ORDER + EXTRA) if k not in PAUSED]
        items = [dict(ai_info(r), id=r['id'], title=r['title'], status=r['status'], category=r['category']) for r in rows]
        return render_template('admin_life_ai.html', kinds=kinds, items=items, cfg=settings(), ai_ready=desk.ai_ready(), logs=setting('writer_log', [])[:10],
                               per_run=PER_RUN, sources={k: f()[0] for k, f in SOURCES.items()})

    def done(r):
        if r['status'] in ('made', 'exists'):
            flash({'made': '초안을 만들었어요. 내용과 숫자를 확인하고 게시해 주세요.' + (f" ({r['reason']})" if r.get('reason') else ''),
                   'exists': '오늘 이미 만든 초안이 있어 그 글을 열었어요. 새로 쓰려면 \'다시 쓰기\'를 눌러 주세요.'}[r['status']])
            return redirect(url_for('admin_life_edit', article_id=r['id']))
        flash(('지금은 만들 수 없어요: ' if r['status'] == 'skip' else '기사를 쓰지 못했어요: ') + r.get('reason', ''))
        return redirect(url_for('admin_life_ai'))

    @app.route('/admin/life/ai/job')
    @S.admin_only
    def admin_life_ai_job():
        j = job_state()
        if j.get('state') == 'done':
            put('writer_job', {}); return done(j)
        if j.get('state') != 'running': return redirect(url_for('admin_life_ai'))
        return render_template('admin_life_ai.html', waiting=KINDS.get(j.get('kind'), {}).get('name', ''), kinds=[], items=[], cfg=settings(), ai_ready=True, logs=[], per_run=PER_RUN, sources={})

    @app.route('/admin/life/ai/settings', methods=['POST'])
    @S.admin_only
    def admin_life_ai_settings():
        per = request.form.get('per_run', type=int)
        if request.form.get('act') in ('stop', 'start'):   # 맨 위 '자동 게시 멈추기·다시 켜기' 버튼: 쓰기는 계속, 게시만 켜고 끔
            on = request.form.get('act') == 'start'; save_settings(1, settings()['per_run'], int(on))
            flash('자동 게시를 다시 켰어요. 검사를 통과한 글은 바로 올라가요.' if on else '자동 게시를 멈췄어요. 글은 계속 써서 올릴 글(초안)에 쌓아 둬요.')
            return redirect(url_for('admin_life_ai'))
        save_settings(1 if request.form.get('auto') else 0, per, 1 if request.form.get('publish') else 0)
        flash('자동 쓰기 설정을 저장했어요.')
        return redirect(url_for('admin_life_ai'))

    # 생활정보 글 고치기: AI 글은 저장할 때 같은 자료로 숫자를 다시 검사하고, 검토 필요 글은 확인 체크 없이는 게시하지 않음
    old_edit = app.view_functions['admin_life_edit']
    def admin_life_edit(article_id):
        if request.method == 'POST' and S.admin_active():
            act = request.form.get('act', 'save')
            with conn() as db:
                x = db.execute("SELECT x.facts FROM ai_articles x JOIN articles a ON a.id=x.article_id AND a.origin='ai' WHERE x.article_id=?", (article_id,)).fetchone()
                if act == 'delete': db.execute('DELETE FROM ai_articles WHERE article_id=?', (article_id,))
                elif x:
                    f = request.form
                    problems = save_check(db, article_id, f.get('title', ''), f.get('summary', ''), f.get('body', ''), json.loads(x['facts']))
                    if act == 'publish' and problems and not f.get('ack_numbers'):
                        db.commit()
                        flash(f'자료에 없는 숫자·표현이 {len(problems)}곳 있어 게시하지 않았어요. 고치거나, 직접 확인했다면 \'숫자를 직접 확인했어요\'에 체크하고 게시해 주세요.')
                        return redirect(url_for('admin_life_edit', article_id=article_id))
        return old_edit(article_id)
    app.view_functions['admin_life_edit'] = admin_life_edit  # 원래 함수가 이미 admin_only라 로그인 확인은 그쪽에서

    FIX_SYSTEM = ('너는 잡지 교열 기자야. [문제]에 적힌 문장을 [자료]대로 고쳐. 자료에 없는 숫자는 새로 넣지 말고, 맞는 숫자를 자료에서 찾을 수 없으면 그 숫자 부분을 빼고 문장을 자연스럽게 다듬어. '
                  '말투(해요체)와 나머지 내용은 그대로 둬. JSON만: {"fixes": [{"before": "글에 있는 문장 그대로(한 글자도 바꾸지 말고)", "after": "고친 문장"}]}')

    def proofread(article_id):
        """재교열: 숫자 검사 + 숫자 짝 검사 → 걸린 문장을 AI가 자료대로 고쳐 저장 → 다시 검사.
        다시 검사해도 문제가 남으면 게시 중인 글은 초안으로 내림. {status: ok|fixed|left|error, fixed: [...], problems: [...]}"""
        with conn() as db:
            r = db.execute("SELECT a.id,a.title,a.summary,a.body,a.status,x.facts FROM articles a JOIN ai_articles x ON x.article_id=a.id WHERE a.id=?", (article_id,)).fetchone()
        if not r: return {'status': 'error', 'reason': 'AI 글이 아니에요'}
        facts = json.loads(r['facts']); parts = {'title': r['title'] or '', 'summary': r['summary'] or '', 'body': r['body'] or ''}
        def check(p):
            got = check_text('\n'.join(p.values()), facts)
            return got + [x for x in pair_check(p['title'], p['summary'], p['body'], facts) if x not in got]
        problems = check(parts)
        if any(x.get('line') == '숫자 짝 검사를 못 했어요' for x in problems): return {'status': 'error', 'reason': problems[0].get('pair', 'AI 교열을 못 했어요')}
        fixed = []
        if problems:
            user = ('[자료]\n' + json.dumps(facts, ensure_ascii=False)[:12000] + '\n\n[문제]\n' + json.dumps(problems, ensure_ascii=False)
                    + '\n\n[글]\n' + '\n'.join(parts.values())[:12000])
            try: got = chat(FIX_SYSTEM, user, 2500)
            except RuntimeError as e: return {'status': 'error', 'reason': str(e)}
            for f in (got.get('fixes') or [])[:15] if isinstance(got, dict) else []:
                if not isinstance(f, dict): continue
                before, after = str(f.get('before', '')).strip(), str(f.get('after', '')).strip()
                if not before or before == after: continue
                for k in parts:
                    if before in parts[k]: parts[k] = parts[k].replace(before, clean_personal(desk.scrub, after)); fixed.append({'before': before[:300], 'after': after[:300]}); break
            if fixed: problems = check(parts)
        with conn() as db:
            if fixed: db.execute('UPDATE articles SET title=?,summary=?,body=?,updated=? WHERE id=?', (parts['title'][:120], parts['summary'], parts['body'], stamp(), article_id))
            db.execute('UPDATE ai_articles SET check_ok=?,problems=?,checked=? WHERE article_id=?', (0 if problems else 1, json.dumps(problems, ensure_ascii=False), stamp(), article_id))
            if problems and r['status'] == 'published': db.execute("UPDATE articles SET status='draft',updated=? WHERE id=?", (stamp(), article_id))
        return {'status': 'left' if problems else ('fixed' if fixed else 'ok'), 'fixed': fixed, 'problems': problems, 'unpublished': bool(problems and r['status'] == 'published')}

    @app.route('/admin/life/<int:article_id>/proofread', methods=['POST'])
    @S.admin_only
    def admin_life_proofread(article_id):
        """관리자 글 화면 '재교열하기' 버튼. AI를 두세 번 불러 오래 걸릴 수 있어 뒤에서 돌리고 글 화면에 결과를 보여 줌."""
        if not desk.ai_ready(): flash('OpenAI API 키가 없어서 재교열할 수 없어요.'); return redirect(url_for('admin_life_edit', article_id=article_id))
        def run():
            try: res = proofread(article_id)
            except Exception as e: res = {'status': 'error', 'reason': f'재교열하지 못했어요 ({type(e).__name__})'}
            jobs = setting('writer_proof', {}); jobs = jobs if isinstance(jobs, dict) else {}
            jobs[str(article_id)] = dict(res, state='done', at=stamp()); put('writer_proof', jobs)
        jobs = setting('writer_proof', {}); jobs = jobs if isinstance(jobs, dict) else {}
        jobs[str(article_id)] = {'state': 'running', 'at': stamp()}; put('writer_proof', jobs)
        if app.config.get('TESTING'): run()
        else: threading.Thread(target=run, daemon=True).start()
        return redirect(url_for('admin_life_edit', article_id=article_id) + '#ai-check')

    def proof_state(article_id):
        """글 화면에 보여 줄 재교열 결과 (한 번 보여 주면 지움, 돌고 있으면 그대로)"""
        jobs = setting('writer_proof', {}); jobs = jobs if isinstance(jobs, dict) else {}
        j = jobs.get(str(article_id))
        if not j: return None
        if j.get('state') == 'running' and j.get('at', '') < (datetime.datetime.now() - datetime.timedelta(minutes=5)).isoformat():
            j = {'state': 'done', 'status': 'error', 'reason': '시간이 너무 걸려서 멈췄어요. 다시 눌러 주세요.'}
        if j.get('state') == 'done': jobs.pop(str(article_id), None); put('writer_proof', jobs)
        return j
    app.jinja_env.globals.update(proof_state=proof_state)

    def recheck(days=7):
        """최근 days일에 게시된 AI 글을 숫자 검사 + 숫자 짝 검사로 다시 봄. 걸린 글은 초안으로 돌리고 어디가 문제인지 남김
        (관리자 > 생활정보 글에서 고치고 다시 게시). [{id, title, problems}]"""
        since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        with conn() as db:
            rows = db.execute("SELECT a.id,a.title,a.summary,a.body,x.facts FROM articles a JOIN ai_articles x ON x.article_id=a.id "
                              "WHERE a.origin='ai' AND a.status='published' AND substr(a.created,1,10)>=? ORDER BY a.id", (since,)).fetchall()
        out = []
        for r in rows:
            try: facts = json.loads(r['facts'])
            except ValueError: continue
            problems = check_text('\n'.join([r['title'], r['summary'] or '', r['body'] or '']), facts) or pair_check(r['title'], r['summary'] or '', r['body'] or '', facts)
            if not problems or problems[0].get('line') == '숫자 짝 검사를 못 했어요': continue  # 검사를 못 한 글은 그대로 둠
            with conn() as db:
                db.execute("UPDATE articles SET status='draft',updated=? WHERE id=?", (stamp(), r['id']))
                db.execute('UPDATE ai_articles SET check_ok=0,problems=?,checked=? WHERE article_id=?', (json.dumps(problems, ensure_ascii=False), stamp(), r['id']))
            out.append({'id': r['id'], 'title': r['title'], 'problems': problems})
        log({'status': 'recheck', 'kind': '', 'trigger': 'recheck', 'reason': f'최근 {days}일 게시 글 {len(rows)}개 중 {len(out)}개를 초안으로 돌렸어요'})
        return out

    app.extensions['soboru_writer'] = {'recheck': recheck, 'proofread': proofread, 'generate': generate, 'daily': daily, 'collect': collect, 'kind_ready': kind_ready, 'settings': settings, 'check_text': check_text}
    S.writer_daily = daily


def main(argv):
    """서버 예약 작업: python -m soboru_writer [--kind 종류] [--dry] [--recheck 일수]. --recheck는 게시된 글을 다시 검사해 걸린 글을 초안으로, --dry는 자료만 모아 보여 줌(AI·저장 없음)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import app as site
    import soboru_writer as mod  # app.py가 붙인 모듈 (python -m으로 부르면 이 파일은 __main__이라 Skip이 다른 클래스)
    Skip = mod.Skip
    w = site.app.extensions['soboru_writer']
    with site.app.app_context():
        if '--dry' in argv:
            for k in ([argv[argv.index('--kind') + 1]] if '--kind' in argv else dict.fromkeys(ORDER + EXTRA)):
                try: print(k, json.dumps(w['collect'](k), ensure_ascii=False, indent=1)[:3000])
                except Skip as e: print(k, '건너뜀:', e)
            return 0
        if '--recheck' in argv:  # 게시된 글 다시 검사: python -m soboru_writer --recheck [일수]
            i = argv.index('--recheck'); days = int(argv[i + 1]) if len(argv) > i + 1 and argv[i + 1].isdigit() else 7
            got = w['recheck'](days)
            for r in got: print('초안으로', r['id'], r['title'], '·', '; '.join(p.get('pair') or ', '.join(p.get('numbers') or p.get('words') or []) for p in r['problems']))
            print(f'{len(got)}개를 초안으로 돌렸어요')
            return 0
        if '--kind' in argv:
            out = [dict(w['generate'](argv[argv.index('--kind') + 1], 'daily'), kind=argv[argv.index('--kind') + 1])]
        else:
            out = w['daily']()
    for r in out: print(r.get('kind', ''), r['status'], r.get('id', ''), r.get('reason', ''))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
