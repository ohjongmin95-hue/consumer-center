"""소보루 레터: 매일 아침 경제·소비자 정보 뉴스레터 (운영자 요청 2026-11-01: 정보성 콘텐츠만, 매일 자동으로).

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다 (soboru_writer.py와 같은 방식).
- 한 호 구성: ① 오늘의 경제 이슈(경제·산업 뉴스 3건 + 정부 정책·제도 변화) ② 숫자로 보는 오늘 ③ 소비자 피해 예방(최근 피해 유형·대응 방법)
  ④ 알아두면 좋은 법률·제도(청약철회·분쟁해결기준·법령 개정 등 LAW_TOPICS를 호마다 돌아가며) ⑤ 오늘의 경제 용어(소비자·경제 사전) ⑥ 발행 정보·수신 거부.
- 호 만들기: 네이버 뉴스 검색(ECON_QUERIES·POLICY_QUERIES·HARM_QUERIES, 제목·요약 조각만)에서 지난 하루(평일만 보내면 월요일은 주말 포함, 매주면 7일) 뉴스를 모아
  여러 기사가 함께 다룬 이슈부터 경제 3건·정책 2건(비슷한 기사는 하나로, 한 분야 2개까지) 고르면 → AI(companydesk.post_json)가
  해요체로 짧은 제목·설명·'나한테는?' 한 줄·관련 법 조문(넘겨 준 후보 중에서만)과 ②③④ 칸을 쓴다. 기사 문장은 옮기지 않게 하고,
  코드로도 원문과 6어절 넘게 겹치는지, 숫자가 그 칸의 자료에 있는지(soboru_writer.check_text) 검사해 '검토 필요'로 표시한다.
  각 뉴스에는 기사 원문(언론사) 링크와 법령 출처를 붙인다. ②③④는 sections에 담고, ⑤와 새 매거진 글은 사전·DB에서.
- 보내기: 관리자 > 소보루 레터에서 운영자가 '보내기'를 누르거나, '자동 보내기'를 켜 두면 검사를 통과한 호만 만든 뒤 바로 보낸다.
  메일은 notify.send_email(SMTP, deploy/set-mail.sh)로 확인을 마친(active) 구독자에게만, 작은 묶음으로 쉬어 가며 뒤에서 보낸다.
  보낸 기록은 letter_sends에 남겨 같은 사람에게 두 번 보내지 않는다(중간에 끊겨도 다시 누르면 남은 사람에게만).
- 구독: 이메일 + 수집·이용 동의 → 확인 메일(/letter/confirm/<token>)을 눌러야 구독(이중 확인). 모든 메일에 한 번에 해지하는
  /letter/unsubscribe/<token> 링크와 List-Unsubscribe 머리글. 해지하면 이메일 주소는 복원할 수 없는 값으로 바꿔 지운다.
  확인하지 않은 신청은 7일 뒤 지운다.
- 예약: deploy/soboru-letter.timer가 매일 아침 7시 30분 `python soboru_letter.py weekly`를 부르면, 관리자가 고른 주기(기본 매일·평일 매일·매주 한 요일)에 맞을 때만 한 호를 만든다.
"""
import datetime, hashlib, hmac, json, os, re, secrets, sys, threading, time, urllib.error, urllib.parse, urllib.request
from flask import Response, abort, flash, g, redirect, render_template, request, url_for
from markupsafe import Markup
import soboru_writer as W

SITE = W.SITE
NAME = '소보루 레터'
DAYS = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']
ITEMS = (3, 6)            # 한 호 '오늘의 뉴스' 최소·최대 개수 — 개수는 고정 아님, 기사가 많이 쏟아진 주요 이슈만 (운영자 2026-11-01)
MIN_COVER = 3             # 같은 소식을 다룬 다른 기사가 이만큼은 있어야 '주요 이슈'로 봄 (최소 개수를 못 채우면 많은 순으로 채움)
NEWS_DAYS = 7             # 매주 보낼 때 뉴스 기간
# 분야별 토스페이스 그림 (메일은 글꼴을 못 받으므로 static/img/tf/*.png 그림으로, 웹은 같은 이모지 글자로)
TOPIC_ICON = {'경제': ('money', '💰'), '산업': ('chart', '📈'), '물가': ('cart', '🛒'), '금리': ('bank', '🏦'), '부동산': ('house', '🏠'), '유통': ('cart', '🛍️'),
              '정부 정책': ('speaker', '📢'), '제도 개선': ('memo', '📝'), '법 개정 시행': ('scale', '⚖️'),
              '소비자 피해': ('shield', '🛡️'), '소비자 주의보': ('siren', '🚨'), '리콜': ('siren', '🚨')}
FREQS = {'weekdays': '평일 매일', 'daily': '매일', 'weekly': '매주 한 번'}
# 한 호 구성 (운영자 요청 2026-11-01, 정보성 콘텐츠만):
#   ① 오늘의 경제 이슈(경제·산업 뉴스 3건 + 정부 정책·제도 변화) ② 숫자로 보는 오늘 ③ 소비자 피해 예방(최근 피해 유형·대응 방법)
#   ④ 알아두면 좋은 법률·제도(청약철회·분쟁해결기준·법령 개정을 호마다 돌아가며) ⑤ 오늘의 경제 용어(사전) ⑥ 발행 정보·수신 거부
ECON_QUERIES = ['경제', '산업', '물가', '금리', '부동산', '유통', '증시', '환율', '수출', '고용']
POLICY_QUERIES = ['정부 정책', '제도 개선', '법 개정 시행']
HARM_QUERIES = ['소비자 피해', '소비자 주의보', '리콜']
TREND_QUERIES = ['소비 트렌드', '인기 상품', '품절 대란', '오픈런', '편의점 신상', '판매량 급증']  # 요즘 뜨는 소비 트렌드 (운영자 2026-11-01)
TREND_N = 5
TREND_DAYS = (0,)        # 소비 트렌드 칸은 일주일에 한 번 — 월요일 호에만, 지난 7일 기사로 (운영자 2026-11-01). 매주 보내기면 늘 넣음
LETTER_QUERIES = ECON_QUERIES   # 갓 구운 뉴스 6 = 진짜 경제 기사만 (운영자 2026-11-01: 법·제도·정책은 아래 칸에서)
KIND_N = {'econ': 6, 'policy': 0}   # 경제 이슈 6건, 정책·제도는 뉴스에 넣지 않음 (운영자 2026-11-01)
HARM_N = 2                          # 피해 예방에 넘기는 뉴스 수
BRIEF_N = 0                         # '한 줄로 보는 경제 뉴스' 수 (자세히 푼 경제 이슈 말고 그날의 다른 경제 뉴스, 운영자 요청 2026-11-01)
# ④ 법률·제도: 호 번호로 돌아가며 (검색어는 법령 모음에서 조문을 찾는 말)
LAW_TOPICS = [('전자상거래 청약철회 기준', '전자상거래 청약철회 7일 반품 비용'), ('소비자분쟁해결기준', '소비자분쟁해결기준 환급 교환 수리'),
              ('방문판매·전화권유 청약철회', '방문판매 청약철회 14일'), ('할부 거래 철회와 항변권', '할부거래 청약철회 항변권'),
              ('중도 해지와 위약금', '계속거래 중도 해지 위약금'), ('불공정 약관', '약관 불공정 무효'),
              ('부당한 표시·광고', '표시광고 부당 광고 금지'), ('제품 결함과 리콜', '제조물 결함 리콜 손해배상')]
# 뉴스 앞 분야 이름 (뉴닉의 '경제ㅣ…'처럼)
CAT = {'경제': '경제', '산업': '산업', '물가': '물가', '금리': '금융', '부동산': '부동산', '유통': '유통', '증시': '증시', '환율': '환율', '수출': '무역', '고용': '고용', '정부 정책': '정책', '제도 개선': '제도', '법 개정 시행': '법·제도'}
MORE_N = 3                # 오늘의 뉴스마다 같이 넘기는 같은 소식 다른 기사 수
CLUSTER_N = 6             # 에디터 코멘트에 넘기는 같은 이슈 기사 수
PER_QUERY = 100           # 분야마다 가져올 기사 수 (네이버 뉴스 검색 최대 100, 기사량으로 주요 이슈를 가리려고 넉넉히)
PER_TOPIC = 2             # 한 분야에서 고를 수 있는 이슈 수
COMMON_SHARE = 0.4        # 모은 기사 제목의 이만큼 넘게 나오는 낱말은 이슈를 가르는 데 안 씀
REVIEW_DAYS = 14
SEND_BATCH = 20           # 한 번에 보내는 메일 수
SEND_PAUSE = 3.0          # 묶음 사이 쉬는 시간(초)
SUB_LIMIT = 5             # 같은 접속지에서 10분 동안 구독 신청 횟수
PENDING_DAYS = 7          # 확인 안 한 신청은 7일 뒤 지움
# 소비 트렌드 칸(일주일에 한 번): 그 주 트렌드 주제에 맞는 가게 하나로 통째 꾸밈 — 지붕 모양(roof)·색·그림이 가게마다 다름 (운영자 2026-11-01)
# roof: awning 줄무늬 차양 · bunting 삼각 깃발 · garland 꽃 줄 · noren 식당 포렴 · board 나무 간판 · neon 편의점 색띠 · bulbs 거울 전구 · rail 옷걸이 · window 화면 창 · ticket 표
def _shop(name, en, ko, roof, main, sub, bg, deep, icons, shelf, roof_icons=(), words=''):
    return {'name': name, 'en': en, 'ko': ko, 'roof': roof, 'main': main, 'sub': sub, 'bg': bg, 'deep': deep, 'icons': icons, 'shelf': shelf, 'roof_icons': roof_icons, 'words': words}


SHOPS = {
    'dessert': _shop('디저트 가게', 'SOBORU DESSERT SHOP', '오늘의 디저트 진열대', 'awning', '#f48fab', '#ffd3df', '#fff0f4', '#c2416a', ('cupcake', 'cake', 'cookie'), ('donut', 'cookie', 'cupcake', 'cake', 'candy'), words='디저트 케이크 과자 아이스크림 초콜릿 쿠키 도넛 간식 탕후루 두쫀쿠'),
    'toy': _shop('완구점', 'SOBORU TOY SHOP', '이번 주 장난감 진열대', 'bunting', '#4c6ef5', '#ffd43b', '#eef3ff', '#3b4fc4', ('teddy', 'gamepad', 'yoyo'), ('balloon', 'teddy', 'kite', 'train', 'yoyo'), ('#ff6b6b', '#ffd43b', '#51cf66', '#4c6ef5', '#cc5de8'), '장난감 완구 게임 피규어 굿즈 캐릭터 팝업 키덜트 콘솔 레고 인형 키링'),
    'flower': _shop('꽃집', 'SOBORU FLOWER SHOP', '이번 주 꽃 진열대', 'garland', '#40a35a', '#ffc9de', '#f2f9ee', '#2b7a3f', ('tulip', 'blossom', 'sunflower'), ('bouquet', 'tulip', 'daisy', 'blossom', 'sunflower'), ('tulip', 'daisy', 'blossom', 'sunflower'), '꽃 선물 기념일 데이트 웨딩 결혼 연말 어버이날 화분 식물 인테리어'),
    'food': _shop('식당', 'SOBORU DINER', '이번 주 맛집 메뉴판', 'noren', '#d9480f', '#ffe3d6', '#fff5f0', '#b23a0b', ('ramen', 'bento', 'dumpling'), ('stew', 'ramen', 'bento', 'dumpling', 'riceball'), ('lantern',), '외식 식당 라면 맛집 배달 치킨 버거 프랜차이즈 밀키트 먹거리 메뉴 뷔페'),
    'bakery': _shop('빵집', 'SOBORU BAKERY', '이번 주 빵 진열대', 'board', '#b8692a', '#f6d2a2', '#fdf5e8', '#8a4a17', ('bread', 'bagel', 'pretzel'), ('baguette', 'bagel', 'bread', 'pretzel', 'donut'), words='빵 베이커리 제과 식빵 소금빵 베이글 성심당'),
    'store': _shop('편의점', 'SOBORU 24 STORE', '이번 주 편의점 신상', 'neon', '#12b886', '#ff922b', '#eefaf5', '#0c8a63', ('store', 'riceball', 'cupdrink'), ('riceball', 'cupdrink', 'ramen', 'cookie', 'candy'), ('#12b886', '#ff922b', '#339af0'), '편의점 CU GS25 세븐일레븐 이마트24 도시락 삼각김밥 편의점 신상'),
    'cafe': _shop('카페', 'SOBORU CAFE', '이번 주 카페 메뉴판', 'awning', '#8c5a3c', '#f3e4d6', '#fbf5ef', '#6b3f22', ('coffee', 'tea', 'cake'), ('coffee', 'tea', 'cookie', 'cake', 'donut'), words='커피 카페 음료 차 라떼 티 저가 커피 디카페인'),
    'beauty': _shop('뷰티숍', 'SOBORU BEAUTY', '이번 주 뷰티 화장대', 'bulbs', '#ae3ec9', '#ffe066', '#f9f0fc', '#862e9c', ('lipstick', 'nail', 'lotion'), ('lotion', 'lipstick', 'nail', 'sparkle', 'lipstick'), words='화장품 뷰티 다이소 올리브영 립 스킨케어 향수 미용 네일 화장'),
    'fashion': _shop('옷 가게', 'SOBORU CLOSET', '이번 주 옷걸이', 'rail', '#3b5bdb', '#dbe4ff', '#f0f4ff', '#2f4ab5', ('dress', 'shirt', 'sneaker'), ('shirt', 'jeans', 'dress', 'sneaker', 'bags'), ('shirt', 'dress', 'jeans', 'shirt', 'dress'), '옷 패션 의류 신발 가방 유니클로 무신사 SPA 아웃도어 패딩'),
    'tech': _shop('전자 매장', 'SOBORU TECH STORE', '이번 주 신제품 진열대', 'window', '#364fc7', '#d0ebff', '#f1f4fa', '#2b3a8f', ('phone', 'laptop', 'headphone'), ('phone', 'headphone', 'watch', 'laptop', 'gamepad'), words='스마트폰 휴대폰 아이폰 갤럭시 가전 노트북 전자 AI 이어폰 태블릿 워치'),
    'grocery': _shop('장보기 마트', 'SOBORU MARKET', '이번 주 장바구니', 'awning', '#5c940d', '#e9fac8', '#f4fbea', '#4a7a0a', ('leafy', 'apple', 'carrot'), ('apple', 'carrot', 'leafy', 'cart', 'apple'), words='마트 장보기 채소 과일 식재료 쌀 고기 계란 신선식품 이마트 홈플러스 김장'),
    'travel': _shop('여행사', 'SOBORU TRAVEL', '이번 주 여행 티켓', 'ticket', '#1c7ed6', '#d0ebff', '#eef7fe', '#1864ab', ('plane', 'luggage', 'beach'), ('plane', 'luggage', 'beach', 'house', 'plane'), words='여행 항공 호텔 숙박 해외 관광 캠핑 레저 공연 축제 연휴'),
    'health': _shop('건강 상점', 'SOBORU WELLNESS', '이번 주 건강 진열대', 'awning', '#0ca678', '#c3fae8', '#effbf6', '#087f5b', ('pill', 'salad', 'muscle'), ('salad', 'pill', 'muscle', 'apple', 'tea'), words='건강 영양제 약 헬스 운동 다이어트 단백질 웰니스 저당 제로'),
    'shop': _shop('잡화점', 'SOBORU SHOP', '이번 주 트렌드 진열대', 'awning', '#EF920E', '#ffe2b0', '#fff7ea', '#b35f00', ('bags', 'cart', 'star'), ('bags', 'cart', 'star', 'party', 'bags')),
}


def guess_shop(text):
    """AI가 고른 가게가 없거나 틀리면 낱말로 고른다 (못 고르면 잡화점)."""
    best, score = 'shop', 0
    for k, v in SHOPS.items():
        n = sum(1 for w in v['words'].split() if w and w.lower() in (text or '').lower())
        if n > score: best, score = k, n
    return best


BOXES = (('number', '숫자로 보는 오늘'), ('buzz', '소비 트렌드'), ('harm', '소비자 피해 예방'), ('lawbox', '법률·제도'))  # 뉴스 말고 AI가 쓰는 칸 (sections에 담음)
COPY_WORDS = 6            # 기사 원문과 이만큼 어절이 그대로 겹치면 '검토 필요'
AI_TIMEOUT = 120
EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')
UNSUB_MARK = '__LETTER_UNSUB__'
STIBEE_UNSUB = '$%unsubscribe%$'      # 스티비에 붙여 넣는 HTML의 수신 거부 치환자 (스티비가 구독자별 링크로 바꿈)
GIF = bytes.fromhex('47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b')  # 1x1 투명 그림
PURPOSE = '경제·소비자 관련 정보 제공'   # ⑥ 발행 정보의 발행 목적

SYSTEM = ('너는 소보루(소비자 정보 플랫폼)의 매일 아침 경제·소비자 뉴스레터 "소보루 레터"를 쓰는 "에디터 크로와상"이다. 바쁜 사람도 5분이면 오늘의 경제 이슈와 내 지갑을 지키는 정보를 따라잡게 정리한다. '
          '친구에게 말하듯 친근한 해요체(~요)로, 어려운 말은 풀어서 쓴다. 광고·홍보·이벤트 문구는 쓰지 않는다(정보만 전한다).\n'
          '이번 호 구성: ① 오늘의 뉴스 — [이번 호 뉴스]를 모두 하나씩, 뉴스 제목처럼 또렷한 제목과 3문장 요약으로 쓴다. ⓪ 크로와상의 깊이 읽기(comment) — [에디터 코멘트 자료](오늘 가장 큰 경제 이슈를 다룬 여러 기사)로 그 이슈를 깊게 풀어 쓴다. ⑤ 요즘 뜨는 소비 트렌드(buzz) — [소비 트렌드 뉴스]로 요즘 소비자들이 무엇을 왜 사는지 짚는다. '
          '② 숫자로 보는 오늘 — [이번 호 뉴스] 하나에 나온 숫자 하나를 골라 그 뜻을 풀어 준다. ③ 소비자 피해 예방 — [피해 예방 뉴스]와 [소보루에 최근 많이 들어온 제보 분야]를 보고 요즘 생기는 피해 유형 하나와 겪었을 때 대응 방법을 쓴다. '
          '④ 알아두면 좋은 법률·제도 — [오늘의 법률·제도 주제]의 조문을 쉬운 말로 풀어 준다.\n'
          '지켜야 할 것:\n'
          '- 숫자가 핵심이다: 모든 칸에 자료에 있는 구체적인 숫자(금액·비율·건수·인원·날짜·순위·증가율)를 최대한 넣는다. 자료에 숫자가 있는데 빼먹지 않는다. "크게 늘었다"보다 "3만 8490명", "18% 늘었다"처럼 쓴다. 여러 기사의 숫자를 모아 써도 된다(단, 숫자를 새로 계산하거나 지어내지는 않는다).\n'
          '- 뉴스마다 제목과 요약 조각만 준다. 기사 문장을 옮기지 말고 반드시 네 말로 새로 풀어 쓴다. 기사에서 그대로 따오는 말은 몇 낱말을 넘지 않게 하고, 따옴표로 인용하지 않는다.\n'
          '- 각 칸은 그 칸에 준 자료([제목]·[요약]·[조문 후보])에 있는 사실과 숫자만 쓴다. 없는 숫자(날짜·금액·비율·건수·기간 모두)는 쓰지 않고, 숫자를 새로 계산하지 않는다. 대응 방법에도 자료에 없는 기간·금액은 쓰지 않는다.\n'
          '- 요약이 말하지 않는 원인·전망·뒷이야기는 짐작하지 않는다. 더 알 수 없으면 "자세한 내용은 기사 원문에서 확인해 보세요"처럼 쓴다.\n'
          '- 기업을 좋다·나쁘다 평가하거나 비난하지 않는다. 피해 예방 칸에서도 특정 기업 이름을 쓰지 않고 피해 유형으로만 쓴다. 정치 이슈는 어느 편도 들지 않고 누가 무엇을 했는지 사실만 쓴다. 사람 이름·연락처 같은 개인정보는 쓰지 않는다(공인이 한 공식 발표는 기관 이름으로 쓴다).\n'
          '- 법 조문은 준 후보 id 가운데 정말 관련 있는 것 하나만 고르고, 맞는 것이 없으면 빈 문자열로 둔다. 법 이야기는 "~할 수 있어요"처럼 단정하지 않게 쓴다. 법률 자문이 아니다. 분쟁해결기준은 강제력 없는 권고 기준이라고 밝힌다.\n'
          '- 링크·출처·주소·HTML·마크다운 기호는 쓰지 않는다(화면에서 따로 붙인다). 목록이나 팁 개수를 숫자로 세지 않는다. "소보루 브리핑" 같은 고정된 이름을 제목에 붙이지 않는다.\n'
          'JSON 객체 하나로만 답한다: {"subject": 메일 제목 30자 안팎(오늘 가장 눈길 끄는 소식), "intro": 여는 글 2~3문장 — "빵순이·빵돌이님,"으로 시작해(독자를 부를 땐 늘 빵순이·빵돌이님, "이웃님"은 쓰지 않는다) 에디터 코멘트 이슈를 우리 생활 장면으로 꺼내고 마지막 문장은 질문으로 끝낸다(예: "…우리는 어떻게 대처해야 할까요?"). 언론·기사·보도·매체 이야기는 하지 않는다, "outro": 맺음말 1~2문장, '
          '"items": [{"no": 뉴스 번호, "title": 뉴스 제목처럼 핵심 숫자·주체를 담은 30~45자 제목(질문형·감탄·따옴표 인용 가능, 어울리면 끝에 이모지 하나, 예 "미국 기준금리 3.75~4.00% 동결, 12월 추가 인상 가능성은? 🏦"), "body": 딱 3문장(150~230자) — 첫 문장은 언제·누가·무엇을 했는지 핵심 숫자와 함께(예 "28일 미국 연방준비제도(연준)가 기준금리를 연 3.75~4.00%로 동결했어요."), 둘째 문장은 배경이나 덧붙일 사실, 셋째 문장은 왜 그런지·무슨 뜻인지 해석("~라는 해석이 나와요", "~라는 계획이에요"). 기관 이름은 처음에 풀어 쓰고 괄호에 줄임말, 해요체로 짧고 또렷하게(그 뉴스와 "같은 소식 다른 기사" 자료만 쓴다), "tip": "", "law": 고른 조문 id 또는 ""}], '
          '"comment": {"photo": 이슈에 어울리는 사진을 Unsplash에서 찾을 영어 검색어 2~3낱말(장면·물건 위주, 사람 이름·회사 이름·로고 X, 예 "grocery shopping cart"), "title": 30~45자 제목(핵심 주체·숫자를 담고 끝에 어울리는 이모지 1~2개 가능), "tags": [이슈를 나타내는 짧은 낱말 2~3개, # 없이], "lead": 3~4문장 — 독자가 겪을 법한 생활 장면으로 시작해 이슈를 꺼내고 마지막은 질문으로 끝낸다, "what": {"body": 언제 누가 무엇을 발표·확인했는지 1~2문장(끝을 "…살펴보면:"처럼 이어 써도 됨), "points": [{"name": 주체·항목 이름 15자 이내, "text": 1~2문장 — 자료에 있는 숫자를 꼭 넣는다}] 3개}, '
          '"why": {"body": 배경·원인 5~7문장(350~550자), 자료의 숫자와 기관 발표를 들어 구체적으로}, "wallet": {"head": 이 칸 소제목 15자 안팎(예 "내 지갑엔 무슨 일이?", "무엇이 문제일까요?"), "body": 1~2문장(끝을 "…이래요:"처럼 이어 써도 됨), "points": [{"name": 15자 이내 + 끝에 어울리는 이모지 하나, "text": 2문장}] 2~3개}, "note": 에디터 크로와상의 한마디 2~3문장(120~220자) — 이 이슈를 두고 독자가 오늘 챙겨 보면 좋을 점을 친구에게 말하듯 따뜻하게(기업 평가·단정 X, 자료에 없는 숫자 X)} (자료가 모자라면 null), '
          '"buzz": {"title": 요즘 소비 트렌드를 담은 25~40자 제목, "body": 트렌드 도입 4~5문장(250~400자) — 요즘 무엇이 왜 뜨는지 생활 장면과 숫자로, '
          '"shop": 이번 트렌드 주제에 가장 어울리는 가게 하나(dessert 디저트·toy 완구·flower 꽃·food 식당·bakery 빵·store 편의점·cafe 카페·beauty 뷰티·fashion 옷·tech 전자·grocery 장보기·travel 여행·health 건강·shop 그 밖), "points": [{"name": 트렌드·상품 이름 15자 이내, "text": 4~5문장(250~380자) — 무엇이 얼마나 팔리는지(판매량·증가율·가격·순위 같은 자료의 숫자를 여럿), 누가 왜 사는지, 업계가 어떻게 움직이는지를 구체적으로}] 3개, '
          '"insight": 이 트렌드를 꿰뚫는 분석 4~5문장(250~400자) — 여러 기사의 흐름을 묶어 소비 심리·물가·세대 같은 배경을 짚는다(자료에 없는 숫자·전망은 짓지 않는다), '
          '"tip": 소비자가 이 트렌드 속에서 챙길 점 2문장(예: 가격 비교, 충동구매 주의, 품절 마케팅 주의)} ([소비 트렌드 뉴스]가 비었으면 null), '
'"number": {"no": 숫자를 고른 뉴스 번호, "value": 그 뉴스 자료에 있는 숫자 그대로(단위 포함, 예 "3.2%"), "label": 무엇의 숫자인지 15자 안팎, "body": 이 숫자가 무슨 뜻인지 1~2문장} (고를 숫자가 없으면 null), '
          '"harm": {"title": 피해 유형 20자 안팎, "body": 요즘 이런 피해가 생기고 있다는 설명 2~4문장, "steps": [겪었을 때 대응 방법 2~4개, 각각 40자 안팎 한 문장 — 증거 남기기, 판매자에게 기록이 남는 방식으로 요청하기, 카드 결제면 카드사에 문의하기, 1372 소비자상담센터 상담처럼 그 피해에 맞는 것], "law": 피해 예방 뉴스 조문 후보 id 또는 ""} (자료가 없으면 null), '
          '"lawbox": {"title": 25자 안팎 제목, "body": 조문을 쉬운 말로 3~4문장, "point": 꼭 기억할 한 줄 50자 이내, "law": 고른 조문 id} (주제가 null이면 null), '
          '"briefs": []}')


# 칸 이름: 뉴닉 문구·이모지를 따라 하지 않고 소보루(빵집)식으로 (운영자 2026-11-01)
HEADS = {'news_eyebrow': 'MORNING BAKERY', 'news_title': '갓 구운 오늘의 뉴스', 'news_emoji': '🥯', 'more': '기사 원문 ›',
         'comment_eyebrow': '오늘의 메인 뉴스', 'comment_kicker': 'TODAY\'S SPECIAL', 'what': '🍞 한 입에 정리하면', 'why': '🔎 왜 이렇게 됐을까요', 'wallet': '👛 내 지갑엔 무슨 일이?',
         'buzz_eyebrow': 'TREND', 'buzz': '요즘 뜨는 소비 트렌드'}

STIBEE_ROOT = 'https://api.stibee.com'
STIBEE_API = STIBEE_ROOT + '/v2'
VIA = {'site': '사이트에서 직접 (Brevo 등 SMTP)', 'stibee': '스티비로 (프로 요금제 API)'}


UNSPLASH_API = 'https://api.unsplash.com'
UTM = '?utm_source=soboru_letter&utm_medium=referral'   # 언스플래시 규칙: 작가·Unsplash 링크에 붙임


def unsplash_call(path, params=None):
    """언스플래시 API (운영자 요청 2026-11-01: 레터 사진은 unsplash.com에서). 키는 서버 설정 UNSPLASH_ACCESS_KEY (deploy/set-unsplash.sh).
    (상태 코드, JSON 또는 None). 테스트에서 바꿔 끼운다."""
    key = os.getenv('UNSPLASH_ACCESS_KEY', '').strip()
    url = (path if path.startswith('http') else UNSPLASH_API + path) + ('?' + urllib.parse.urlencode(params) if params else '')
    req = urllib.request.Request(url, headers={'Authorization': 'Client-ID ' + key, 'Accept-Version': 'v1'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return r.status, json.loads(r.read().decode() or 'null')
    except urllib.error.HTTPError as e: return e.code, None
    except (urllib.error.URLError, OSError, ValueError): return 0, None


def photo_query(q):
    q = re.sub(r'[^A-Za-z ]', ' ', str(q or ''))
    return ' '.join(q.split()[:4]).lower()


def find_photo(q, used):
    """검색어로 가로 사진 하나 (이미 쓴 사진은 건너뜀). 고르면 언스플래시 규칙대로 download 주소를 한 번 불러 준다."""
    q = photo_query(q)
    if not q or not os.getenv('UNSPLASH_ACCESS_KEY', '').strip(): return None
    st, res = unsplash_call('/search/photos', {'query': q, 'orientation': 'landscape', 'per_page': 8, 'content_filter': 'high'})
    if st != 200 or not isinstance(res, dict): return None
    for ph in res.get('results') or []:
        try:
            pid, raw, user = ph['id'], ph['urls']['raw'], ph['user']
            if pid in used: continue
            used.add(pid)
            dl = (ph.get('links') or {}).get('download_location')
            if dl: unsplash_call(dl)
            return {'id': pid, 'url': raw + ('&' if '?' in raw else '?') + 'w=1072&h=600&fit=crop&crop=entropy&auto=format&q=75',
                    'alt': W._plain(ph.get('alt_description') or ph.get('description') or q, 120),
                    'credit': W._plain(user.get('name') or user.get('username'), 60),
                    'credit_url': user['links']['html'] + UTM, 'home': 'https://unsplash.com/' + UTM}
        except (KeyError, TypeError): continue
    return None


def add_photos(items, ex):
    """에디터 코멘트 맨 위 큰 사진 (오늘의 뉴스에는 사진 없음, 운영자 2026-11-01). 키가 없거나 못 찾으면 사진 없이 그대로."""
    used = set()
    c = ex.get('comment')
    if c and c.get('_photo_q'):
        ph = find_photo(c['_photo_q'], used)
        if ph: c['photo'] = ph


MARKET_SRC = [('코스피', 'https://m.stock.naver.com/api/index/KOSPI/basic'), ('코스닥', 'https://m.stock.naver.com/api/index/KOSDAQ/basic'),
              ('원-달러 환율', 'https://m.stock.naver.com/front-api/marketIndex/productDetail?category=exchange&reutersCode=FX_USDKRW')]


def market_call(url):
    """시장 지표 JSON (운영자 요청 2026-11-01: 코스피·코스닥·원-달러를 레터 만들 때의 값으로). 실패하면 None. 테스트에서 바꿔 끼운다."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (soboru-letter)', 'Accept': 'application/json', 'Referer': 'https://m.stock.naver.com/'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r: return json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, ValueError): return None


def _num(v):
    try: return float(str(v).replace(',', '').replace('%', '').replace('+', '').strip())
    except (TypeError, ValueError): return None


def market_row(label, d):
    """네이버 증권 응답 하나 → {label, value, change, pct, dir}. 모양이 다르면 None."""
    if isinstance(d, dict) and isinstance(d.get('result'), dict): d = d['result']
    if not isinstance(d, dict): return None
    value = d.get('closePrice') or d.get('nowValue') or d.get('price')
    change = next((d[k] for k in ('compareToPreviousClosePrice', 'fluctuations', 'change') if d.get(k) not in (None, '')), None)
    pct = next((d[k] for k in ('fluctuationsRatio', 'changeRate') if d.get(k) not in (None, '')), None)
    v, c, r = _num(value), _num(change), _num(pct)
    if v is None or c is None: return None
    kind = (d.get('compareToPreviousPrice') or d.get('fluctuationsType') or {})
    name = kind.get('name', '') if isinstance(kind, dict) else ''
    down = name in ('FALLING', 'LOWER_LIMIT') or str(change).strip().startswith('-')
    up = name in ('RISING', 'UPPER_LIMIT') or (not down and c > 0)
    sign = '-' if down else ('+' if up else '')
    return {'label': label, 'value': str(value).strip(), 'change': f'{abs(c):,.2f}', 'pct': f'{sign}{abs(r):.2f}%' if r is not None else '',
            'dir': 'down' if down else ('up' if up else 'flat'), 'at': str(d.get('localTradedAt') or '')[:10]}


TOP_URL = 'https://m.stock.naver.com/api/stocks/marketValue/KOSPI?page=1&pageSize=10'   # 코스피 시가총액 상위 10 (운영자 요청 2026-11-01)
TOP_N = 10


def fetch_top():
    d = market_call(TOP_URL)
    if isinstance(d, dict): d = d.get('stocks') or d.get('result') or d.get('datas') or []
    out = []
    for x in d if isinstance(d, list) else []:
        name = W._plain((x or {}).get('stockName') or (x or {}).get('itemName'), 30) if isinstance(x, dict) else ''
        r = market_row(name, x) if name else None
        if r: out.append(r)
        if len(out) >= TOP_N: break
    return out


def fetch_market():
    rows = [market_row(label, market_call(url)) for label, url in MARKET_SRC]
    rows = [r for r in rows if r]
    top = fetch_top()
    if not rows and not top: return None
    at = next((r['at'] for r in rows + top if r['at']), '')
    return {'rows': rows, 'top': top, 'at': at}


def stibee_call(method, path, body=None, ctype='application/json', base=None):
    """스티비 API v2 (운영자 요청 2026-11-01). 키는 서버 설정 STIBEE_API_KEY (deploy/set-stibee.sh). (상태 코드, 응답 글자). 테스트에서 바꿔 끼운다."""
    key = os.getenv('STIBEE_API_KEY', '').strip()
    data = None if body is None else (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)).encode()
    req = urllib.request.Request((base or STIBEE_API) + path, data=data, method=method, headers={'AccessToken': key, 'Content-Type': ctype + '; charset=utf-8'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e: return e.code, e.read().decode('utf-8', 'replace')[:300]


def stibee_subs(list_id, emails, on=True):
    """스티비 주소록에 구독자 넣기(on) / 수신 거부(off). 새 키는 v2라 v2 경로를 먼저, 없으면(404·405) 예전 v1 경로로. (성공 여부, 설명)"""
    if not list_id or not emails: return False, '주소록 번호나 메일이 없어요'
    body = {'eventOccuredBy': 'MANUAL', 'confirmEmailYN': 'N', 'subscribers': [{'email': e} for e in emails]} if on else list(emails)
    last = ''
    for ver in ('/v2', '/v1'):
        path = f'/lists/{list_id}/subscribers' + ('' if on else '/unsubscribe')
        st, res = stibee_call('POST' if on else 'PUT', path, body, base=STIBEE_ROOT + ver)
        if st in (200, 201): return True, ''
        last = f'({st}) {res[:120]}'
        if st not in (404, 405): break
    return False, last


class Skip(Exception):
    """지금은 호를 만들 수 없음 (자료 없음·키 없음). 운영자에게 보여 줄 쉬운 말."""


def stamp(): return datetime.datetime.now().isoformat(timespec='seconds')


def site_url(path=''): return (os.getenv('SITE_URL', '').strip() or SITE).rstrip('/') + path


def words(text): return [w for w in re.sub(r'[^\w%]+', ' ', text or '').split() if w]


def copied(text, source, n=COPY_WORDS):
    """AI 글에 기사 제목·요약과 n어절 넘게 그대로 겹치는 부분이 있으면 그 부분."""
    src = words(source); have = {tuple(src[i:i + n]) for i in range(len(src) - n + 1)}
    mine = words(text)
    for i in range(len(mine) - n + 1):
        if tuple(mine[i:i + n]) in have: return ' '.join(mine[i:i + n])
    return ''


def iso_day(s):
    """'2026.10.16' → '2026-10-16' (숫자 검사에서 10·16이 따로 잡히게)."""
    m = re.match(r'(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})', s or '')
    return '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3))) if m else (s or '')


def mask_nick(nick):
    nick = (nick or '').strip() or '익명'
    return nick[:2] + '**' if len(nick) > 2 else nick[:1] + '*'


def gone_email(email): return 'x:' + hashlib.sha256(email.encode()).hexdigest()


def kdate(iso):
    try: d = datetime.date.fromisoformat((iso or '')[:10])
    except ValueError: return ''
    return f"{d.year}. {d.month}. {d.day}. {DAYS[d.weekday()]}"  # 요일은 '일요일'처럼 다 씀 (운영자 2026-11-01)


def install(S):
    app = S.app; conn = S.conn; desk = S.companydesk; notify = S.notify
    corpus = S.triage.corpus
    with conn() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS letters(id INTEGER PRIMARY KEY,no INTEGER NOT NULL UNIQUE,title TEXT NOT NULL,intro TEXT NOT NULL DEFAULT '',
            outro TEXT NOT NULL DEFAULT '',items TEXT NOT NULL DEFAULT '[]',sections TEXT NOT NULL DEFAULT '{}',status TEXT NOT NULL DEFAULT 'draft',
            created TEXT NOT NULL,updated TEXT NOT NULL DEFAULT '',sent_at TEXT,check_ok INTEGER NOT NULL DEFAULT 0,problems TEXT NOT NULL DEFAULT '[]',
            trigger TEXT NOT NULL DEFAULT 'admin',sent_count INTEGER NOT NULL DEFAULT 0,failed INTEGER NOT NULL DEFAULT 0)''')
        db.execute('''CREATE TABLE IF NOT EXISTS letter_subscribers(id INTEGER PRIMARY KEY,email TEXT NOT NULL UNIQUE,token TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending',created TEXT NOT NULL,confirmed TEXT,ip_hash TEXT NOT NULL DEFAULT '',asked TEXT,unsubscribed TEXT,
            place TEXT NOT NULL DEFAULT '')''')
        # 열어 봄·클릭 (운영자 요청 2026-11-01): 한 사람·한 호·종류마다 한 줄 (처음 시각만)
        db.execute('''CREATE TABLE IF NOT EXISTS letter_events(letter_id INTEGER NOT NULL,sub_id INTEGER NOT NULL,kind TEXT NOT NULL,at TEXT NOT NULL,
            PRIMARY KEY(letter_id,sub_id,kind))''')
        # '오늘의 레터는 어땠나요?' 좋았어요/글쎄요 (운영자 2026-11-01)
        db.execute('''CREATE TABLE IF NOT EXISTS letter_feedback(letter_no INTEGER NOT NULL,who TEXT NOT NULL,vote TEXT NOT NULL,at TEXT NOT NULL,PRIMARY KEY(letter_no,who))''')
        db.execute('''CREATE TABLE IF NOT EXISTS letter_sends(letter_id INTEGER NOT NULL,sub_id INTEGER NOT NULL,status TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',
            at TEXT NOT NULL,PRIMARY KEY(letter_id,sub_id))''')
        if 'stibee_id' not in {r[1] for r in db.execute('PRAGMA table_info(letters)')}: db.execute('ALTER TABLE letters ADD COLUMN stibee_id INTEGER')

    def naver(): return app.extensions.get('naverhub') or {}
    def testing(): return bool(app.config.get('TESTING'))

    # ---- 설정 ---------------------------------------------------------------
    def setting(key, default):
        with conn() as db: row = db.execute('SELECT value FROM soboru_settings WHERE key=?', (key,)).fetchone()
        try: return json.loads(row[0]) if row else default
        except ValueError: return default

    def put(key, value):
        with conn() as db: db.execute('INSERT OR REPLACE INTO soboru_settings(key,value) VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))

    def settings():
        s = setting('letter', {})
        sender = (s.get('stibee_sender') or '').strip()
        return {'auto': 1 if s.get('auto') == 1 else 0, 'day': s.get('day') if s.get('day') in range(7) else 0,
                'freq': s.get('freq') if s.get('freq') in FREQS else 'daily', 'via': s.get('via') if s.get('via') in VIA else 'site',
                'stibee_list': s.get('stibee_list') if isinstance(s.get('stibee_list'), int) else 0,
                'stibee_sender': sender if EMAIL_RE.match(sender) else '', 'stibee_name': (s.get('stibee_name') or '').strip()[:40] or NAME}

    def stibee_ready(): return bool(os.getenv('STIBEE_API_KEY', '').strip())

    def stibee_sync(email, on=True):
        """사이트에서 구독·해지가 생기면 스티비 주소록에도 바로 반영 (보내는 곳이 스티비일 때만). 실패해도 사이트 구독은 그대로, 레터 기록에 남김."""
        cfg = settings()
        if cfg['via'] != 'stibee' or not stibee_ready() or not cfg['stibee_list'] or not email or email.startswith('x:'): return

        def job():
            ok, why = stibee_subs(cfg['stibee_list'], [email], on)
            if not ok: log({'status': 'error', 'reason': f"스티비 주소록 {'추가' if on else '수신 거부'} 실패 {notify.mask(email)} {why}"})
        if testing(): job()
        else: threading.Thread(target=lambda: _quiet(job), daemon=True).start()

    def stibee_push_all():
        """관리자 버튼: 사이트에서 구독을 마친 사람 모두를 스티비 주소록에 넣음 (이미 있으면 스티비가 갱신). 한 번에 500명씩."""
        cfg = settings()
        if not stibee_ready(): return False, '스티비 API 키가 없어요 (deploy/set-stibee.sh)'
        if not cfg['stibee_list']: return False, '스티비 주소록 번호를 먼저 저장해 주세요'
        with conn() as db: emails = [r[0] for r in db.execute("SELECT email FROM letter_subscribers WHERE status='active' ORDER BY id")]
        if not emails: return True, '옮길 구독자가 없어요'
        for i in range(0, len(emails), 500):
            ok, why = stibee_subs(cfg['stibee_list'], emails[i:i + 500], True)
            if not ok: return False, f'{i}명까지 옮기고 멈췄어요 {why}'
        return True, f'{len(emails)}명을 스티비 주소록에 넣었어요'

    def stibee_send(L, trigger):
        """스티비에 이메일을 만들고(제목·발신자·주소록) 내용을 넣은 뒤 바로 보냄. 우리 구독자 목록에는 보내지 않음(구독자는 스티비 주소록)."""
        cfg = settings()
        if not stibee_ready(): return {'status': 'error', 'reason': '스티비 API 키가 없어요 (deploy/set-stibee.sh)'}
        if not cfg['stibee_list'] or not cfg['stibee_sender']: return {'status': 'error', 'reason': '스티비 주소록 번호와 발신자 이메일을 설정에 넣어 주세요'}
        eid = L.get('stibee_id')
        if not eid:
            st, res = stibee_call('POST', '/emails', {'listId': cfg['stibee_list'], 'senderEmail': cfg['stibee_sender'], 'senderName': cfg['stibee_name'],
                                                     'subject': f"[{NAME}] {L['title']}"})
            try: eid = int(json.loads(res)['id'])
            except (ValueError, KeyError, TypeError): return {'status': 'error', 'reason': f'스티비에 이메일을 만들지 못했어요 ({st}) {res[:120]}'}
            with conn() as db: db.execute('UPDATE letters SET stibee_id=? WHERE id=?', (eid, L['id']))
        html = '<html><head></head><body>' + stibee_html(L) + '</body></html>'
        st, res = stibee_call('POST', f'/emails/{eid}/content', html, 'text/html')
        if st != 200: return {'status': 'error', 'reason': f'스티비에 내용을 넣지 못했어요 ({st}) {res[:120]}'}
        st, res = stibee_call('POST', f'/emails/{eid}/send')
        if st != 200: return {'status': 'error', 'reason': f'스티비 발송을 시작하지 못했어요 ({st}) {res[:120]}'}
        with conn() as db: db.execute("UPDATE letters SET status='sent',sent_at=?,trigger=?,updated=? WHERE id=?", (stamp(), 'stibee', stamp(), L['id']))
        log({'status': 'sent', 'no': L['no'], 'trigger': trigger, 'reason': f'스티비로 보냄 (이메일 {eid})'})
        return {'status': 'sent', 'reason': ''}

    def news_days(today=None):
        # 매일 보내면 지난 하루치(평일만 보내면 월요일은 주말까지), 매주면 7일치
        cfg = settings(); today = today or datetime.date.today()
        if cfg['freq'] == 'weekly': return NEWS_DAYS
        return 3 if cfg['freq'] == 'weekdays' and today.weekday() == 0 else 1

    def log(entry):
        put('letter_log', ([dict(entry, at=stamp())] + setting('letter_log', []))[:30])

    # ---- 자료 모으기 ----------------------------------------------------------
    def search_pool(queries, since, seen, heads):
        pool = []
        for q in queries:
            for it in naver()['search']('news', q, display=PER_QUERY, sort='date')['items']:
                try: day = datetime.date(*map(int, it['date'].split('.')))
                except (ValueError, TypeError): continue
                head = re.sub(r'\W', '', it['title'])[:14]
                if day < since or it['url'] in seen or head in heads: continue
                seen.add(it['url']); heads.add(head); pool.append(dict(it, topic=q))
        return pool

    def case_trend():
        # ③ 피해 예방에 참고: 최근 2주 소보루에 많이 들어온 제보 분야 (분야 이름만, 건수·내용은 넘기지 않음)
        since = (datetime.datetime.now() - datetime.timedelta(days=14)).isoformat(timespec='seconds')
        try:
            with conn() as db:
                rows = db.execute("SELECT category,COUNT(*) AS n FROM cases WHERE created>=? AND status NOT IN ('반려','중복') GROUP BY category ORDER BY n DESC LIMIT 3", (since,)).fetchall()
        except Exception: return []
        return [r['category'] for r in rows if r['n'] >= 2 and r['category']]

    def law_topic(no):
        name, q = LAW_TOPICS[(no - 1) % len(LAW_TOPICS)]
        hits = corpus.related(q, limit=2)
        cands = [{'id': f'B-L{k}', 'label': h['label'], 'law': h.get('law', ''), 'text': corpus.clip(h['text'], 700), 'url': h.get('source') or ''} for k, h in enumerate(hits, 1)]
        return {'name': name, 'cands': cands} if cands else None

    def word_of(no):
        # ⑤ 오늘의 경제 용어: 소비자·경제 사전(soboru_tools.DICT)에서 호마다 돌아가며 (AI 없이 사전 풀이 그대로)
        import soboru_tools as T
        if not T.DICT: return None
        w, cat, text = T.DICT[((no - 1) * 11) % len(T.DICT)]
        return {'word': w, 'cat': cat, 'text': text, 'url': '/tools/dict?q=' + w}

    def collect_news(no=None):
        """{news: 경제 이슈·정책 뉴스, harm: 피해 예방 뉴스, trend: 많이 들어온 제보 분야, law: 오늘의 법률·제도 주제}"""
        nv = naver()
        if not nv or not nv['ready'](): raise Skip('네이버 API HUB 키가 없어요 (deploy/set-naver.sh)')
        if no is None:
            with conn() as db: no = (db.execute('SELECT MAX(no) FROM letters').fetchone()[0] or 0) + 1
        days = news_days()
        since = datetime.date.today() - datetime.timedelta(days=days)
        seen, heads = set(), set()
        try:
            pool = search_pool(LETTER_QUERIES, since, seen, heads)
            harm_pool = search_pool(HARM_QUERIES, since, seen, heads)
            weekly = settings()['freq'] == 'weekly' or datetime.date.today().weekday() in TREND_DAYS
            trend_pool = search_pool(TREND_QUERIES, datetime.date.today() - datetime.timedelta(days=7), seen, heads) if weekly else []
        except Exception as e:  # 네이버 오류 문구(NaverError)는 그대로, 그 밖은 이름만 (키가 섞이지 않게)
            raise Skip(str(e)[:120] if type(e).__name__ == 'NaverError' else f'뉴스를 가져오지 못했어요 ({type(e).__name__})')
        items = pick_issues(pool, ITEMS[1], None, cover=MIN_COVER)
        if len(items) < ITEMS[0]: raise Skip(f'최근 {days}일 주요 뉴스가 {ITEMS[0]}건보다 적어요')
        scrub = lambda t: W.clean_personal(desk.scrub, t)

        def entry(n, it, pre=''):
            title, summary = scrub(it['title']), scrub(it['summary'])
            hits = corpus.related(title + ' ' + summary, limit=3)
            cands = [{'id': f'{pre}{n}-L{k}', 'label': h['label'], 'law': h.get('law', ''), 'text': corpus.clip(h['text'], 500), 'url': h.get('source') or ''} for k, h in enumerate(hits, 1)]
            return {'no': n, 'title': title, 'summary': summary, 'source': it['source'], 'date': iso_day(it['date']), 'url': it['url'], 'cands': cands,
                    'topic': it.get('topic', ''), 'kind': 'policy' if it.get('topic') in POLICY_QUERIES else 'econ'}
        news = [entry(n, it) for n, it in enumerate(items, 1)]
        picked = {it['url'] for it in items}
        for x, it in zip(news, items):  # 뉴닉처럼 길게 쓸 수 있게 같은 소식을 다룬 다른 기사 요약도 (운영자 2026-11-01: 주요 뉴스가 너무 짧음)
            x['more'] = [{'title': scrub(o['title']), 'summary': scrub(o['summary']), 'source': o['source']}
                         for o in pool if o['url'] not in picked and related(it, o)][:MORE_N]
        harm = [entry(n, it, 'H') for n, it in enumerate(pick_issues(harm_pool, HARM_N, None), 1)]
        main = next((it for it in items if it['topic'] not in POLICY_QUERIES), items[0])
        cluster = [main] + [it for it in pool if it is not main and related(main, it)][:CLUSTER_N - 1]
        comment = [dict(entry(n, it, 'C'), no=f'C{n}', cands=[]) for n, it in enumerate(cluster, 1)]
        used = {it['url'] for it in items}
        rest = [it for it in pool if it['topic'] in ECON_QUERIES and it['url'] not in used]
        briefs = [dict(entry(n, it, 'B'), no=f'B{n}', cands=[]) for n, it in enumerate(pick_issues(rest, BRIEF_N, None), 1)]
        buzz = [dict(entry(n, it, 'T'), no=f'T{n}', cands=[]) for n, it in enumerate(pick_issues(trend_pool, TREND_N, None), 1)]
        for x, it in zip(buzz, [it for it in pick_issues(trend_pool, TREND_N, None)]):
            x['more'] = [{'title': scrub(o['title']), 'summary': scrub(o['summary']), 'source': o['source']} for o in trend_pool if o['url'] != it['url'] and related(it, o)][:MORE_N]
        return {'news': news, 'harm': harm, 'briefs': briefs, 'comment': comment, 'buzz': buzz, 'trend': case_trend(), 'law': law_topic(no)}

    def related(a, b):
        stem = lambda w: w[:-1] if len(w) >= 3 and w[-1] in '은는이가을를의에도로와과만' else w
        bag = lambda it: {stem(w) for w in words(it['title'] + ' ' + it.get('summary', '')) if len(w) >= 2 and not w.isdigit()}
        return len(bag(a) & bag(b)) >= 3

    def pick_issues(pool, limit=ITEMS[1], kinds=KIND_N, cover=None):
        # 주요 이슈 = 여러 기사가 함께 다룬 소식. 제목 낱말이 2개 넘게 겹치는 기사가 많을수록 앞에 둠.
        # 거의 모든 제목에 나오는 낱말(속보·단독 같은 말)은 빼고 셈. 같은 이슈는 하나만, 한 분야는 PER_TOPIC개까지.
        # kinds가 있으면 경제 이슈 3건 + 정책·제도 2건처럼 나눠 고르고, 모자라면 다른 쪽에서 채움. 경제 이슈를 앞에 둠.
        stem = lambda w: w[:-1] if len(w) >= 3 and w[-1] in '은는이가을를의에도로와과만' else w  # '금리가'·'금리는' → '금리'
        bags = [{stem(w) for w in words(it['title']) if len(w) >= 2 and not w.isdigit()} for it in pool]
        df = {}
        for b in bags:
            for w in b: df[w] = df.get(w, 0) + 1
        common = {w for w, n in df.items() if len(pool) >= 5 and n > len(pool) * COMMON_SHARE}
        bags = [b - common for b in bags]
        same = lambda a, b: len(a & b) >= 2
        score = [sum(1 for j, o in enumerate(bags) if j != i and same(b, o)) for i, b in enumerate(bags)]
        kind = lambda i: 'policy' if pool[i]['topic'] in POLICY_QUERIES else 'econ'
        picked, per, per_kind, order = [], {}, {}, sorted(range(len(pool)), key=lambda i: -score[i])  # 점수가 같으면 분야 순서·최신 순 그대로
        if cover is not None:
            # 오늘의 뉴스: 분야를 고루 나누지 않고, 같은 소식을 다룬 기사가 많은(헤드라인) 이슈부터. cover건 넘게 다룬 이슈만 넣고,
            # 그래야 ITEMS[0]개가 안 되면 기사 많은 순으로 채움. 그래서 날마다 3~6개로 달라짐 (운영자 2026-11-01)
            for i in order:
                if len(picked) == limit or (score[i] < cover and len(picked) >= ITEMS[0]): break
                if any(same(bags[i], bags[k]) for k in picked): continue
                picked.append(i)
            return [pool[i] for i in picked]
        for cap, kcap in ((PER_TOPIC, True), (limit, True), (limit, False)):  # 분야를 고루 고르고, 모자라면 한 분야에서 더, 그래도 모자라면 다른 쪽에서
            for i in order:
                t = pool[i]['topic']
                if len(picked) == limit: break
                if i in picked or per.get(t, 0) >= cap or any(same(bags[i], bags[k]) for k in picked): continue
                if kinds and kcap and per_kind.get(kind(i), 0) >= kinds.get(kind(i), limit): continue
                picked.append(i); per[t] = per.get(t, 0) + 1; per_kind[kind(i)] = per_kind.get(kind(i), 0) + 1
        picked.sort(key=lambda i: ((kind(i) == 'policy') if kinds else 0, order.index(i)))
        return [pool[i] for i in picked]

    def ai_facts(news):
        return [{'번호': x['no'], '구분': '정책·제도' if x.get('kind') == 'policy' else '경제 이슈', '제목': x['title'], '요약': x['summary'], '언론사': x['source'], '날짜': x['date'],
                 '같은 소식 다른 기사': [{'제목': o['title'], '요약': o['summary']} for o in x.get('more') or []],
                 '법 조문 후보': [{'id': c['id'], '조문': c['label'], '원문': c['text']} for c in x['cands']]} for x in news]

    def ask_ai(mat, no):
        key = os.getenv('OPENAI_API_KEY', '').strip()
        if not key: raise RuntimeError('OpenAI API 키가 없어요')
        law = mat.get('law')
        dump = lambda v: json.dumps(v, ensure_ascii=False)
        user = (f"[이번 호] {NAME} {no}호 ({datetime.date.today().isoformat()})\n"
                f"[이번 호 뉴스]\n{dump(ai_facts(mat['news']))}\n"
                f"[에디터 코멘트 자료]\n{dump([{'제목': x['title'], '요약': x['summary'], '언론사': x['source'], '날짜': x['date']} for x in mat.get('comment') or []])}\n"
                f"[한 줄 뉴스]\n{dump([{'번호': x['no'], '제목': x['title'], '요약': x['summary']} for x in mat.get('briefs') or []])}\n"
                f"[피해 예방 뉴스]\n{dump(ai_facts(mat['harm']))}\n"
                f"[소비 트렌드 뉴스]\n{dump([{'번호': x['no'], '제목': x['title'], '요약': x['summary'], '날짜': x['date'], '같은 소식 다른 기사': [o['title'] + ' ' + o['summary'] for o in x.get('more') or []]} for x in mat.get('buzz') or []])}\n"
                f"[소보루에 최근 많이 들어온 제보 분야]\n{dump(mat.get('trend') or [])}\n"
                f"[오늘의 법률·제도 주제]\n{dump({'주제': law['name'], '조문 후보': [{'id': c['id'], '조문': c['label'], '원문': c['text']} for c in law['cands']]} if law else None)}")
        body = {'model': desk.ai_model(), 'temperature': 0.5, 'response_format': {'type': 'json_object'}, 'max_tokens': 6500,
                'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}]}
        st, res = desk.post_json('https://api.openai.com/v1/chat/completions', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, AI_TIMEOUT)
        if st != 200: raise RuntimeError(f'AI 응답 오류 ({st}) ' + str((res.get('error') or {}).get('message', ''))[:120].replace(key, '***'))
        try: return json.loads(res['choices'][0]['message']['content'])
        except (KeyError, IndexError, TypeError, ValueError): raise RuntimeError('AI 응답을 읽지 못했어요')

    def item_facts(x, law):
        f = {'제목': x['title'], '요약': x['summary'], '날짜': x['date'], '소비자상담센터 전화번호': '1372'}
        if x.get('more'): f['같은 소식 다른 기사'] = [o['title'] + ' ' + o['summary'] for o in x['more']]
        if law: f['법 조문'] = law['label'] + ' ' + law['text']
        return f

    def law_ref(c): return {'label': c['label'], 'url': c['url'], 'text': c['text']} if c else None

    def assemble(out, mat):
        if not isinstance(out, dict) or not isinstance(out.get('items'), list): raise RuntimeError('AI 응답 형식이 달라요')
        news = mat['news']
        by_no = {x['no']: x for x in news}
        items = []
        for i, it in enumerate(out['items'][:ITEMS[1]]):
            if not isinstance(it, dict): continue
            x = by_no.get(it.get('no')) if isinstance(it.get('no'), int) else None
            x = x or (news[i] if i < len(news) else None)
            if not x or any(y['src']['url'] == x['url'] for y in items): continue
            title, body = W._plain(it.get('title'), 80), W._plain(it.get('body'), 1200)
            tip = re.sub(r'^\s*(이럴 땐 이렇게\s*[:：]?\s*)', '', W._plain(it.get('tip'), 160))
            if not title or not body: continue
            law = next((c for c in x['cands'] if c['id'] == it.get('law')), None)
            items.append({'title': title, 'body': body, 'tip': tip, 'topic': x.get('topic', ''), 'cat': CAT.get(x.get('topic', ''), '경제'), 'kind': x.get('kind', 'econ'), 'law': law_ref(law),
                          'src': {'name': x['source'], 'url': x['url'], 'date': x['date'], 'headline': x['title']},
                          '_facts': item_facts(x, law), '_source': ' '.join([x['title'], x['summary']] + [o['title'] + ' ' + o['summary'] for o in x.get('more') or []])})
        if len(items) < ITEMS[0]: raise RuntimeError('AI가 뉴스를 채우지 못했어요')
        items.sort(key=lambda it: it['kind'] == 'policy')  # 경제 이슈 먼저, 정책·제도 다음
        subject = W._plain(out.get('subject'), 80) or items[0]['title']
        subject = re.sub(r'^\s*\[?소보루\s*(브리핑|레터)\]?\s*[:：\-·]?\s*', '', subject) or items[0]['title']
        intro, outro = W._plain(out.get('intro'), 600), W._plain(out.get('outro'), 400)
        intro, outro = (t.replace('소보루 이웃님', '빵순이·빵돌이님').replace('이웃님', '빵순이·빵돌이님') for t in (intro, outro))
        return subject, intro, outro, items, extras(out, mat)

    def extras(out, mat):
        """② 숫자로 보는 오늘 ③ 피해 예방 ④ 법률·제도 — AI가 못 채웠거나 형식이 다르면 그 칸은 뺌."""
        ex = {}
        n = out.get('number')
        x = next((y for y in mat['news'] if isinstance(n, dict) and y['no'] == n.get('no')), None)
        if x:
            value, label, body = W._plain(n.get('value'), 20), W._plain(n.get('label'), 40), W._plain(n.get('body'), 300)
            if value and re.search(r'\d', value) and label and body:
                ex['number'] = {'value': value, 'label': label, 'body': body, 'src': {'name': x['source'], 'url': x['url'], 'date': x['date']},
                                '_facts': item_facts(x, None), '_source': x['title'] + ' ' + x['summary']}
        h = out.get('harm')
        if isinstance(h, dict) and (mat['harm'] or mat.get('trend')):
            title, body = W._plain(h.get('title'), 60), W._plain(h.get('body'), 700)
            steps = [W._plain(s, 90) for s in (h.get('steps') if isinstance(h.get('steps'), list) else [])][:4]
            steps = [s for s in steps if s]
            cands = [c for y in mat['harm'] for c in y['cands']]
            law = next((c for c in cands if c['id'] == h.get('law')), None)
            if title and body:
                facts = {'피해 예방 뉴스': [item_facts(y, None) for y in mat['harm']], '제보 분야': mat.get('trend') or [], '소비자상담센터 전화번호': '1372'}
                if law: facts['법 조문'] = law['label'] + ' ' + law['text']
                ex['harm'] = {'title': title, 'body': body, 'steps': steps, 'law': law_ref(law),
                              'srcs': [{'name': y['source'], 'url': y['url'], 'date': y['date']} for y in mat['harm']],
                              '_facts': facts, '_source': ' '.join(y['title'] + ' ' + y['summary'] for y in mat['harm'])}
        by_no = {x['no']: x for x in mat.get('briefs') or []}
        briefs = []
        for bi in (out.get('briefs') if isinstance(out.get('briefs'), list) else [])[:BRIEF_N]:
            x = by_no.get(bi.get('no')) if isinstance(bi, dict) else None
            line = W._plain(bi.get('line'), 90) if x else ''
            if x and line and not any(y['src']['url'] == x['url'] for y in briefs):
                briefs.append({'line': line, 'topic': x.get('topic', ''), 'src': {'name': x['source'], 'url': x['url'], 'date': x['date']},
                               '_facts': item_facts(x, None), '_source': x['title'] + ' ' + x['summary']})
        if briefs: ex['briefs'] = briefs
        c, cm = out.get('comment'), mat.get('comment') or []
        if isinstance(c, dict) and cm:
            pts = lambda v: [{'name': W._plain(p.get('name'), 30), 'text': W._plain(p.get('text'), 300)} for p in (v if isinstance(v, list) else [])[:3]
                             if isinstance(p, dict) and W._plain(p.get('name'), 30) and W._plain(p.get('text'), 300)]
            part = lambda k: c.get(k) if isinstance(c.get(k), dict) else {}
            tags = [W._plain(t, 16).lstrip('#') for t in (c.get('tags') if isinstance(c.get('tags'), list) else [])][:3]
            com = {'_photo_q': photo_query(c.get('photo')), 'tags': [t for t in tags if t], 'title': W._plain(c.get('title'), 80), 'lead': W._plain(c.get('lead'), 600),
                   'what': {'body': W._plain(part('what').get('body'), 400), 'points': pts(part('what').get('points'))},
                   'why': {'body': W._plain(part('why').get('body'), 1400)},
                   'wallet': {'head': W._plain(part('wallet').get('head'), 30), 'body': W._plain(part('wallet').get('body'), 300), 'points': pts(part('wallet').get('points'))},
                   'note': W._plain(c.get('note'), 400),
                   'srcs': [{'name': x['source'], 'url': x['url'], 'date': x['date']} for x in cm[:3]],
                   '_facts': {'기사': [item_facts(x, None) for x in cm], '소비자상담센터 전화번호': '1372'}, '_source': ' '.join(x['title'] + ' ' + x['summary'] for x in cm)}
            if com['title'] and com['lead'] and (com['what']['body'] or com['what']['points']): ex['comment'] = com
        z, bz = out.get('buzz'), mat.get('buzz') or []
        if isinstance(z, dict) and bz:
            zp = [{'name': W._plain(p.get('name'), 30), 'text': W._plain(p.get('text'), 700)} for p in (z.get('points') if isinstance(z.get('points'), list) else [])[:3]
                  if isinstance(p, dict) and W._plain(p.get('name'), 30) and W._plain(p.get('text'), 700)]
            title, body = W._plain(z.get('title'), 80), W._plain(z.get('body'), 900)
            insight, tip = W._plain(z.get('insight'), 900), W._plain(z.get('tip'), 300)
            if title and (body or zp):
                k = str(z.get('shop') or '').strip().lower()
                ex['buzz'] = {'title': title, 'body': body, 'points': zp, 'shop': k if k in SHOPS else guess_shop(title + ' ' + body + ' ' + ' '.join(p['name'] + ' ' + p['text'] for p in zp)), 'insight': insight, 'tip': tip, 'srcs': [{'name': x['source'], 'url': x['url'], 'date': x['date']} for x in bz],
                              '_facts': {'기사': [item_facts(x, None) for x in bz]}, '_source': ' '.join([x['title'] + ' ' + x['summary'] for x in bz] + [o['title'] + ' ' + o['summary'] for x in bz for o in x.get('more') or []])}
        b, lt = out.get('lawbox'), mat.get('law')
        if isinstance(b, dict) and lt:
            title, body, point = W._plain(b.get('title'), 60), W._plain(b.get('body'), 800), W._plain(b.get('point'), 120)
            law = next((c for c in lt['cands'] if c['id'] == b.get('law')), lt['cands'][0])
            if title and body:
                ex['lawbox'] = {'topic': lt['name'], 'title': title, 'body': body, 'point': point, 'law': law_ref(law),
                                '_facts': {'법 조문': law['label'] + ' ' + law['text'], '소비자상담센터 전화번호': '1372'}, '_source': ''}
        return ex

    def comment_text(c):
        out = [c.get('title', ''), c.get('lead', ''), c['what']['body'], c['why']['body'], c['wallet']['body'], c.get('note', '')]
        for k in ('what', 'wallet'): out += [p['name'] + ' ' + p['text'] for p in c[k]['points']]
        return '\n'.join(x for x in out if x)

    def box_text(key, b):
        return '\n'.join([b.get('value', ''), b.get('label', ''), b.get('title', ''), b.get('body', ''), b.get('point', '')] + list(b.get('steps') or [])
                         + [p['name'] + ' ' + p['text'] for p in b.get('points') or []] + [b.get('insight', ''), b.get('tip', '')])

    def check(title, intro, outro, items, no, sec=None):
        """[{where, line, numbers|words|copy}] — 자료에 없는 숫자, 기업 평가로 읽힐 말, 기사 원문을 그대로 옮긴 부분."""
        problems = []
        sec = sec or {}
        every = {'뉴스': [it.get('_facts', {}) for it in items], '호': no, '오늘': datetime.date.today().isoformat(), '소비자상담센터 전화번호': '1372'}
        for where, text in (('메일 제목', title), ('첫인사', intro), ('맺음말', outro)):
            problems += [dict(p, where=where) for p in W.check_text(text, every)]
        for i, it in enumerate(items, 1):
            where = f'{i}번 뉴스'
            text = '\n'.join([it['title'], it['body'], it['tip']])
            problems += [dict(p, where=where) for p in W.check_text(text, it.get('_facts', {}))]
            same = copied(text, it.get('_source', ''))
            if same: problems.append({'where': where, 'line': same, 'copy': True})
        if sec.get('comment'):
            c = sec['comment']; text = comment_text(c)
            problems += [dict(p, where='에디터 코멘트') for p in W.check_text(text, c.get('_facts', {}))]
            same = copied(text, c.get('_source', ''))
            if same: problems.append({'where': '에디터 코멘트', 'line': same, 'copy': True})
        for i, b in enumerate(sec.get('briefs') or [], 1):
            where = f'한 줄 뉴스 {i}'
            problems += [dict(p, where=where) for p in W.check_text(b['line'], b.get('_facts', {}))]
            same = copied(b['line'], b.get('_source', ''))
            if same: problems.append({'where': where, 'line': same, 'copy': True})
        for key, where in BOXES:
            b = sec.get(key)
            if not b: continue
            text = box_text(key, b)
            problems += [dict(p, where=where) for p in W.check_text(text, b.get('_facts', {}))]
            same = copied(text, b.get('_source', ''))
            if same: problems.append({'where': where, 'line': same, 'copy': True})
        return problems

    def sections(no=1):
        # 정보성 콘텐츠만 (운영자 2026-11-01): 커뮤니티 리뷰·리뷰 주제는 빼고, 새 매거진 글과 오늘의 경제 용어
        with conn() as db:
            arts = db.execute("SELECT id,title,summary,emoji,category FROM articles WHERE status='published' ORDER BY COALESCE(published_at,created) DESC,id DESC LIMIT 3").fetchall()
        life = [{'id': a['id'], 'title': a['title'], 'summary': ' '.join((a['summary'] or '').split())[:90], 'emoji': a['emoji'] or '📰', 'category': a['category'],
                 'url': f"/life/{a['id']}"} for a in arts]
        return {'life': life, 'word': word_of(no)}

    # ---- 만들기 -----------------------------------------------------------------
    def row_info(r):
        d = dict(r)
        for k, dflt in (('items', []), ('sections', {}), ('problems', [])):
            try: d[k] = json.loads(d[k])
            except (TypeError, ValueError): d[k] = dflt
        return d

    def get(lid=None, no=None):
        with conn() as db:
            r = db.execute('SELECT * FROM letters WHERE ' + ('id=?' if lid is not None else 'no=?'), (lid if lid is not None else no,)).fetchone()
        return row_info(r) if r else None

    def generate(trigger='admin'):
        """{status: made|skip|error, id, no, reason}. 만든 호는 초안(draft)."""
        if not desk.ai_ready(): res = {'status': 'skip', 'reason': 'OpenAI API 키가 없어요'}; log(dict(res, trigger=trigger)); return res
        with conn() as db: no = (db.execute('SELECT MAX(no) FROM letters').fetchone()[0] or 0) + 1
        try:
            mat = collect_news(no)
            title, intro, outro, items, ex = assemble(ask_ai(mat, no), mat)
        except Skip as e: res = {'status': 'skip', 'reason': str(e)}; log(dict(res, trigger=trigger)); return res
        except RuntimeError as e: res = {'status': 'error', 'reason': str(e)}; log(dict(res, trigger=trigger)); return res
        scrub = lambda t: W.clean_personal(desk.scrub, t)
        title, intro, outro = scrub(title), scrub(intro), scrub(outro)
        for it in items: it.update(title=scrub(it['title']), body=scrub(it['body']), tip=scrub(it['tip']))
        for b in ex.get('briefs') or []: b['line'] = scrub(b['line'])
        if ex.get('comment'):
            c = ex['comment']; c['title'], c['lead'] = scrub(c['title']), scrub(c['lead']); c['note'] = scrub(c.get('note', ''))
            for k in ('what', 'why', 'wallet'):
                c[k]['body'] = scrub(c[k]['body'])
                for p in c[k].get('points') or []: p['name'], p['text'] = scrub(p['name']), scrub(p['text'])
        for b in [v for k, v in ex.items() if k not in ('briefs', 'comment')]:
            for k in ('value', 'label', 'title', 'body', 'point', 'insight', 'tip'):
                if k in b: b[k] = scrub(b[k])
            if 'steps' in b: b['steps'] = [scrub(x) for x in b['steps']]
            for pt in b.get('points') or []: pt['name'], pt['text'] = scrub(pt['name']), scrub(pt['text'])
        add_photos(items, ex)
        mk = fetch_market()
        if mk: ex['market'] = mk
        sec = dict(sections(no), **ex)
        problems = check(title, intro, outro, items, no, sec)
        with conn() as db:
            lid = db.execute('INSERT INTO letters(no,title,intro,outro,items,sections,status,created,updated,check_ok,problems,trigger) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                             (no, title, intro, outro, json.dumps(items, ensure_ascii=False), json.dumps(sec, ensure_ascii=False), 'draft', stamp(), stamp(),
                              0 if problems else 1, json.dumps(problems, ensure_ascii=False), trigger)).lastrowid
        res = {'status': 'made', 'id': lid, 'no': no, 'reason': '검토 필요 %d곳' % len(problems) if problems else '', 'ok': not problems}
        log(dict(res, trigger=trigger))
        return res

    def save_edit(lid, form):
        L = get(lid)
        if not L: return None
        items = []
        for i, it in enumerate(L['items']):
            if form.get(f'drop{i}'): continue
            it = dict(it, title=W._plain(form.get(f'title{i}', it['title']), 80), body=' '.join(form.get(f'body{i}', it['body']).split())[:1200],
                      tip=W._plain(form.get(f'tip{i}', it['tip']), 160))
            if form.get(f'nolaw{i}'):
                it['law'] = None; it['_facts'] = {k: v for k, v in it.get('_facts', {}).items() if k != '법 조문'}
            if it['title'] and it['body']: items.append(it)
        title = W._plain(form.get('title', L['title']), 80) or L['title']
        intro, outro = ' '.join(form.get('intro', L['intro']).split())[:800], ' '.join(form.get('outro', L['outro']).split())[:600]
        sec = dict(L['sections'])
        if sec.get('comment'):
            if form.get('drop_comment'): sec.pop('comment')
            else:
                c = dict(sec['comment'])
                if form.get('comment_nophoto'): c.pop('photo', None)
                if 'comment_title' in form: c['title'] = W._plain(form.get('comment_title'), 60) or c['title']
                if 'comment_lead' in form: c['lead'] = ' '.join(form.get('comment_lead', '').split())[:600]
                if 'comment_note' in form: c['note'] = ' '.join(form.get('comment_note', '').split())[:400]
                for k in ('what', 'why', 'wallet'):
                    if f'comment_{k}' in form: c[k] = dict(c[k], body=' '.join(form.get(f'comment_{k}', '').split())[:900])
                sec['comment'] = c
        if sec.get('market') and form.get('drop_market'): sec.pop('market')
        if sec.get('briefs'):
            briefs = []
            for i, b in enumerate(sec['briefs']):
                if form.get(f'drop_brief{i}'): continue
                b = dict(b, line=W._plain(form.get(f'brief{i}', b['line']), 90))
                if b['line']: briefs.append(b)
            if briefs: sec['briefs'] = briefs
            else: sec.pop('briefs')
        for key, _ in BOXES:
            b = sec.get(key)
            if not b: continue
            if form.get(f'drop_{key}'): sec.pop(key); continue
            b = dict(b)
            for k, n in (('value', 20), ('label', 40), ('title', 60), ('point', 120)):
                if k in b and f'{key}_{k}' in form: b[k] = W._plain(form.get(f'{key}_{k}'), n)
            if f'{key}_body' in form: b['body'] = ' '.join(form.get(f'{key}_body', '').split())[:900]
            if 'steps' in b and f'{key}_steps' in form: b['steps'] = [W._plain(x, 90) for x in form.get(f'{key}_steps', '').splitlines() if x.strip()][:4]
            if b.get('body'): sec[key] = b
            else: sec.pop(key)
        problems = check(title, intro, outro, items, L['no'], sec)
        with conn() as db:
            db.execute('UPDATE letters SET title=?,intro=?,outro=?,items=?,sections=?,check_ok=?,problems=?,updated=? WHERE id=?',
                       (title, intro, outro, json.dumps(items, ensure_ascii=False), json.dumps(sec, ensure_ascii=False), 0 if problems else 1, json.dumps(problems, ensure_ascii=False), stamp(), lid))
        return problems

    # ---- 메일 -----------------------------------------------------------------
    def operator():
        c = S.load_content()
        return {'name': c.get('operator.name') or '소보루', 'address': c.get('operator.address') or '', 'biz_no': c.get('operator.biz_no') or '',
                'email': c.get('operator.email') or '', 'phone': c.get('operator.phone') or ''}

    def logo_url():
        for name in ('img/soboru-logo-orange.png', 'img/soboru-logo.png'):
            if os.path.exists(os.path.join(app.static_folder, name)): return site_url('/static/' + name)
        return ''

    def mail_ctx(L, token):
        tf = lambda name: site_url(f'/static/img/tf/{name}.png')
        icons = [tf(TOPIC_ICON.get(it.get('topic', ''), ('news', ''))[0]) for it in L['items']]
        for it, icon in zip(L['items'], icons): it['_icon'] = icon
        return {'L': L, 'items': L['items'], 'econ': [it for it in L['items'] if it.get('kind') != 'policy'], 'policy': [it for it in L['items'] if it.get('kind') == 'policy'],
                'sec': L['sections'], 'H': HEADS, 'purpose': PURPOSE, 'site': site_url(), 'op': operator(), 'logo': logo_url(), 'date': kdate(L.get('sent_at') or L['created']),
                'tf': tf, 'icons': icons, 'SHOPS': SHOPS, 'mark': site_url('/static/img/soboru-wordmark-orange.png') if os.path.exists(os.path.join(app.static_folder, 'img/soboru-wordmark-orange.png')) else '', 'mark_brown': site_url('/static/img/' + ('soboru-logo-brown-h.png' if os.path.exists(os.path.join(app.static_folder, 'img/soboru-logo-brown-h.png')) else 'soboru-wordmark.png')), 'hero': site_url('/static/img/soboru-character-hero.png'), 'peek': site_url('/static/img/soboru-character-peek.png'), 'editor_img': site_url('/static/img/' + ('editor-croissant.png' if os.path.exists(os.path.join(app.static_folder, 'img/editor-croissant.png')) else 'soboru-character-hero.png')), 'cfg': letter_cfg(),
                'unsub': token if token == STIBEE_UNSUB else site_url(f'/letter/unsubscribe/{token}'), 'web': site_url(f"/letter/{L['no']}"), 'name': NAME,
                'stibee': token == STIBEE_UNSUB}

    def link_sig(no, url):
        return hmac.new(app.secret_key.encode(), f'letter:{no}|{url}'.encode(), 'sha256').hexdigest()[:20]

    def tracked(html, no):
        # 구독자에게 보내는 메일만: 링크는 우리 주소를 거쳐 원래 주소로(클릭 수), 맨 아래 1x1 그림(열어 봄). 토큰 자리는 보낼 때 구독자 것으로 바뀜
        unsub = site_url(f'/letter/unsubscribe/{UNSUB_MARK}')
        def wrap(m):
            url = Markup(m.group(1)).unescape()
            if url == unsub or not url.startswith(('http://', 'https://')): return m.group(0)
            q = urllib.parse.urlencode({'u': url, 's': link_sig(no, url)})
            return 'href="%s"' % Markup.escape(site_url(f'/letter/c/{no}/{UNSUB_MARK}?{q}'))
        html = re.sub(r'href="([^"]+)"', wrap, html)
        pixel = f'<img src="{site_url(f"/letter/o/{no}/{UNSUB_MARK}.gif")}" width="1" height="1" alt="" style="display:block;width:1px;height:1px;border:0;">'
        return html.replace('</body>', pixel + '</body>', 1)

    def email_parts(L, token=UNSUB_MARK):
        ctx = mail_ctx(L, token)
        html = app.jinja_env.get_template('letter_email.html').render(**ctx)
        text = app.jinja_env.get_template('letter_email.txt').render(**ctx)
        if token == UNSUB_MARK: html = tracked(html, L['no'])
        return f"[{NAME}] {L['title']}", html, text

    def stibee_html(L):
        """스티비 'HTML 에디터로 만들기'에 붙여 넣을 코드: html·head·body·meta 태그는 스티비가 막으므로 빼고 바탕색은 바깥 div로, 수신 거부는 스티비 치환자."""
        _, html, _ = email_parts(L, STIBEE_UNSUB)
        body = re.search(r'<body[^>]*>(.*)</body>', html, re.S).group(1)
        return '<div style="margin:0;padding:0;background:#ffffff;-webkit-text-size-adjust:100%;word-break:keep-all;">' + body.strip() + '</div>'

    def record(no, token, kind):
        with conn() as db:
            L = db.execute('SELECT id FROM letters WHERE no=?', (no,)).fetchone()
            sub = db.execute('SELECT id FROM letter_subscribers WHERE token=?', ((token or '')[:64],)).fetchone()
            if not L or not sub: return
            for k in (('open', 'click') if kind == 'click' else ('open',)):  # 누른 사람은 연 사람
                db.execute('INSERT OR IGNORE INTO letter_events(letter_id,sub_id,kind,at) VALUES(?,?,?,?)', (L['id'], sub['id'], k, stamp()))

    def stats(lid):
        with conn() as db:
            n = dict(db.execute('SELECT kind,COUNT(*) FROM letter_events WHERE letter_id=? GROUP BY kind', (lid,)).fetchall())
            sent = db.execute("SELECT COUNT(*) FROM letter_sends WHERE letter_id=? AND status='sent'", (lid,)).fetchone()[0]
            fb = dict(db.execute('SELECT f.vote,COUNT(*) FROM letter_feedback f JOIN letters l ON l.no=f.letter_no WHERE l.id=? GROUP BY f.vote', (lid,)).fetchall())
        pct = lambda x: round(100 * x / sent) if sent else 0
        return {'sent': sent, 'open': n.get('open', 0), 'click': n.get('click', 0), 'open_pct': pct(n.get('open', 0)), 'click_pct': pct(n.get('click', 0)), 'good': fb.get('good', 0), 'meh': fb.get('meh', 0)}

    @app.route('/letter/o/<int:no>/<token>.gif')
    def letter_open(no, token):
        try: record(no, token, 'open')
        except Exception: pass  # 통계 때문에 메일 그림이 깨지면 안 됨
        return Response(GIF, mimetype='image/gif', headers={'Cache-Control': 'no-store, max-age=0'})

    @app.route('/letter/c/<int:no>/<token>')
    def letter_click(no, token):
        url, sig = request.args.get('u', ''), request.args.get('s', '')
        if not url.startswith(('http://', 'https://')) or not hmac.compare_digest(sig, link_sig(no, url)): abort(404)  # 서명 없는 주소로는 넘기지 않음 (열린 이동 막기)
        try: record(no, token, 'click')
        except Exception: pass
        return redirect(url, 302)

    def mail_headers(token):
        return {'List-Unsubscribe': f'<{site_url("/letter/unsubscribe/" + token)}>', 'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'}

    def send_one(to, subject, html, text, token):
        notify.send_email(to, subject, text, html=html, headers=mail_headers(token), from_name=os.getenv('LETTER_FROM_NAME', '').strip() or NAME)

    def send_confirm(email, token):
        ctx = {'site': site_url(), 'op': operator(), 'logo': logo_url(), 'name': NAME,
               'confirm': site_url(f'/letter/confirm/{token}'), 'unsub': site_url(f'/letter/unsubscribe/{token}')}
        html = app.jinja_env.get_template('letter_confirm_email.html').render(**ctx)
        text = (f"{NAME} 구독 신청을 받았어요.\n\n아래 주소를 눌러 메일 주소를 확인하면 구독이 시작돼요.\n{ctx['confirm']}\n\n"
                f"직접 신청하지 않았다면 이 메일은 지워 주세요. 확인하지 않으면 구독되지 않고, 신청 정보는 {PENDING_DAYS}일 뒤 지워져요.\n"
                f"신청 취소: {ctx['unsub']}\n\n{ctx['op']['name']} {ctx['op']['address']}")
        job = lambda: send_one(email, f'[{NAME}] 구독 확인을 눌러 주세요', html, text, token)
        if testing(): job()
        else: threading.Thread(target=lambda: _quiet(job), daemon=True).start()

    def _quiet(job):
        try: job()
        except Exception: pass  # 확인 메일 실패는 사용자가 다시 신청하면 됨

    def send_issue(lid, trigger='admin', wait=False):
        """확인을 마친 구독자에게 보냄. 이미 보낸 사람은 건너뜀. {status: sending|sent|error, reason}"""
        L = get(lid)
        if not L: return {'status': 'error', 'reason': '없는 호예요'}
        if L['status'] == 'sent': return {'status': 'error', 'reason': '이미 보낸 호예요'}
        if settings()['via'] == 'stibee': return stibee_send(L, trigger)
        if not notify.email_ready(): return {'status': 'error', 'reason': '메일 발송 설정(SMTP)이 없어요 (deploy/set-mail.sh)'}
        with conn() as db: db.execute("UPDATE letters SET status='scheduled',updated=? WHERE id=?", (stamp(), lid))
        subject, html, text = email_parts(L)

        def run():
            while True:
                with conn() as db:
                    batch = db.execute("""SELECT id,email,token FROM letter_subscribers s WHERE status='active'
                        AND NOT EXISTS(SELECT 1 FROM letter_sends x WHERE x.letter_id=? AND x.sub_id=s.id) ORDER BY id LIMIT ?""", (lid, SEND_BATCH)).fetchall()
                if not batch: break
                for s in batch:
                    try:
                        send_one(s['email'], subject, html.replace(UNSUB_MARK, s['token']), text.replace(UNSUB_MARK, s['token']), s['token'])
                        st, detail = 'sent', ''
                    except Exception as e:  # 한 명 실패는 기록만 하고 계속
                        st, detail = 'failed', str(e)[:200]
                    with conn() as db:
                        db.execute('INSERT OR REPLACE INTO letter_sends(letter_id,sub_id,status,detail,at) VALUES(?,?,?,?,?)', (lid, s['id'], st, detail, stamp()))
                if len(batch) == SEND_BATCH and SEND_PAUSE and not testing(): time.sleep(SEND_PAUSE)
            with conn() as db:
                n = dict(db.execute('SELECT status,COUNT(*) FROM letter_sends WHERE letter_id=? GROUP BY status', (lid,)).fetchall())
                db.execute("UPDATE letters SET status='sent',sent_at=COALESCE(sent_at,?),sent_count=?,failed=?,updated=? WHERE id=?",
                           (stamp(), n.get('sent', 0), n.get('failed', 0), stamp(), lid))
            log({'status': 'sent', 'no': L['no'], 'trigger': trigger, 'reason': f"{n.get('sent', 0)}명에게 보냄" + (f", 실패 {n['failed']}명" if n.get('failed') else '')})

        if wait or testing(): run(); return {'status': 'sent', 'reason': ''}
        threading.Thread(target=run, daemon=True).start()
        return {'status': 'sending', 'reason': ''}

    def cleanup():
        old = (datetime.datetime.now() - datetime.timedelta(days=PENDING_DAYS)).isoformat(timespec='seconds')
        with conn() as db: db.execute("DELETE FROM letter_subscribers WHERE status='pending' AND COALESCE(asked,created)<?", (old,))

    def weekly(today=None, force=False):
        """매일 아침 예약 작업: 고른 주기에 맞는 날이면 한 호를 만들고, 자동 보내기가 켜져 있고 검사를 통과하면 보냄."""
        cfg = settings(); today = today or datetime.date.today()
        cleanup()
        if not force and cfg['freq'] == 'weekly' and today.weekday() != cfg['day']: return {'status': 'not_today', 'reason': f"보내는 날은 {DAYS[cfg['day']]}이에요"}
        if not force and cfg['freq'] == 'weekdays' and today.weekday() >= 5: return {'status': 'not_today', 'reason': '주말에는 쉬어요'}
        start = (today - datetime.timedelta(days=today.weekday())) if cfg['freq'] == 'weekly' else today
        with conn() as db: old = db.execute('SELECT id FROM letters WHERE created>=? ORDER BY id DESC', (start.isoformat(),)).fetchone()
        if old and not force: return {'status': 'exists', 'id': old['id'], 'reason': '이번 주 호가 이미 있어요' if cfg['freq'] == 'weekly' else '오늘 호가 이미 있어요'}
        r = generate('weekly')
        if r['status'] != 'made': return r
        if not cfg['auto']: return dict(r, sent=False, reason=(r['reason'] + ' · ' if r['reason'] else '') + '자동 보내기가 꺼져 있어 운영자를 기다려요')
        if not r['ok']: log({'status': 'held', 'no': r['no'], 'trigger': 'weekly', 'reason': '검토 필요가 있어 자동으로 보내지 않았어요'}); return dict(r, sent=False)
        s = send_issue(r['id'], 'weekly', wait=True)
        return dict(r, sent=s['status'] == 'sent', reason=s['reason'] or r['reason'])

    def counts():
        with conn() as db:
            return dict(db.execute('SELECT status,COUNT(*) FROM letter_subscribers GROUP BY status').fetchall())

    # ---- 공개 화면 -----------------------------------------------------------
    def body_lines(text):
        # 설명은 한 덩어리로 오므로 문장 2~3개씩 문단으로 나눔
        sents = [s for s in re.split(r'(?<=[.!?])\s+', (text or '').strip()) if s]
        return [' '.join(sents[i:i + 2]) for i in range(0, len(sents), 2)] or [text]
    def letter_cfg():
        # 화면 문구용: when='평일 아침마다'·'매일 아침'·'매주 월요일 아침', span='오늘'·'이번 주'
        cfg = settings(); day = DAYS[cfg['day']]
        when = {'weekdays': '평일 아침마다', 'daily': '매일 아침', 'weekly': f'매주 {day} 아침'}[cfg['freq']]
        return dict(cfg, day_name=day, when=when, span='이번 주' if cfg['freq'] == 'weekly' else '오늘')
    app.jinja_env.globals.update(letter_counts=counts, letter_kdate=kdate, letter_cfg=letter_cfg, letter_icon=lambda t: TOPIC_ICON.get(t or '', ('', ''))[1])
    app.jinja_env.filters['letter_paras'] = body_lines

    @app.route('/letter')
    def letter_home():
        with conn() as db:
            rows = [row_info(r) for r in db.execute("SELECT * FROM letters WHERE status='sent' ORDER BY no DESC LIMIT 60")]
        return render_template('letter.html', rows=rows, state=request.args.get('s', ''))

    @app.route('/letter/<int:no>')
    def letter_issue(no):
        L = get(no=no)
        if not L or (L['status'] != 'sent' and not S.admin_active()): abort(404)
        with conn() as db:
            near = {k: db.execute(f"SELECT no,title FROM letters WHERE status='sent' AND no{op}? ORDER BY no {o} LIMIT 1", (no,)).fetchone()
                    for k, op, o in (('prev', '<', 'DESC'), ('next', '>', 'ASC'))}
        return render_template('letter_issue.html', L=L, near=near, H=HEADS, SHOPS=SHOPS)

    @app.route('/letter/<int:no>/fb/<vote>')
    def letter_feedback(no, vote):
        if vote not in ('good', 'meh') or not get(no=no): abort(404)
        who = hashlib.sha256(((request.headers.get('X-Forwarded-For') or request.remote_addr or '') .split(',')[0].strip() + str(no)).encode()).hexdigest()[:24]
        with conn() as db:
            db.execute('INSERT OR REPLACE INTO letter_feedback(letter_no,who,vote,at) VALUES(?,?,?,?)', (no, who, vote, stamp()))
        flash('의견 고마워요! 더 맛있는 레터로 구워 올게요' if vote == 'good' else '알려 줘서 고마워요. 더 좋은 레터로 다듬을게요.')
        return redirect(url_for('letter_issue', no=no))

    def back(code):
        return redirect(url_for('letter_home', s=code) + '#sub')

    @app.route('/letter/subscribe', methods=['POST'])
    def letter_subscribe():
        f = request.form
        if f.get('website'): return back('check')  # 사람 눈에 안 보이는 칸을 채우면 자동 등록 프로그램
        email = (f.get('email') or '').strip().lower()
        if len(email) > 254 or not EMAIL_RE.match(email): return back('email')
        since = (datetime.datetime.now() - datetime.timedelta(minutes=10)).isoformat(timespec='seconds')
        with conn() as db:
            n = db.execute("SELECT COUNT(*) FROM login_attempts WHERE kind='letter' AND ip_hash=? AND created>=?", (S.ip_hash(), since)).fetchone()[0]
            if n >= SUB_LIMIT: return back('limit')
            db.execute("INSERT INTO login_attempts(kind,ip_hash,created) VALUES('letter',?,?)", (S.ip_hash(), stamp()))
        if not notify.email_ready(): return back('nomail')
        place = (f.get('place') or '')[:20]
        with conn() as db:
            row = db.execute('SELECT * FROM letter_subscribers WHERE email IN (?,?)', (email, gone_email(email))).fetchone()
            if row and row['status'] == 'active': return back('check')  # 이미 구독 중이어도 같은 말 (주소가 있는지 알려 주지 않음)
            if row and row['status'] == 'pending' and (row['asked'] or '') > since: return back('check')  # 확인 메일은 10분에 한 번
            token = secrets.token_urlsafe(24)
            if row:
                db.execute("UPDATE letter_subscribers SET email=?,token=?,status='pending',asked=?,ip_hash=?,place=?,unsubscribed=NULL WHERE id=?",
                           (email, token, stamp(), S.ip_hash(), place, row['id']))
            else:
                db.execute("INSERT INTO letter_subscribers(email,token,status,created,ip_hash,asked,place) VALUES(?,?,'pending',?,?,?,?)",
                           (email, token, stamp(), S.ip_hash(), stamp(), place))
        try: send_confirm(email, token)
        except Exception: return back('fail')
        return back('check')

    def msg(kind, **kw):
        return render_template('letter_msg.html', kind=kind, **kw)

    @app.route('/letter/confirm/<token>')
    def letter_confirm(token):
        with conn() as db:
            row = db.execute('SELECT * FROM letter_subscribers WHERE token=?', (token[:64],)).fetchone()
            if not row or row['status'] == 'unsubscribed': return msg('bad'), 404
            if row['status'] == 'active': return msg('already')
            db.execute("UPDATE letter_subscribers SET status='active',confirmed=? WHERE id=?", (stamp(), row['id']))
        stibee_sync(row['email'])
        return msg('confirmed', email=notify.mask(row['email']))

    @app.route('/letter/unsubscribe/<token>', methods=['GET', 'POST'])
    def letter_unsubscribe(token):
        # 메일 속 링크 한 번(GET)으로, 메일 앱의 '구독 취소' 버튼(RFC 8058 POST)으로도 바로 해지. 이메일 주소는 지움
        with conn() as db:
            row = db.execute('SELECT * FROM letter_subscribers WHERE token=?', (token[:64],)).fetchone()
            if not row: return msg('bad')
            gone = row['status'] != 'unsubscribed'
            if gone:
                db.execute("UPDATE letter_subscribers SET status='unsubscribed',unsubscribed=?,email=? WHERE id=?",
                           (stamp(), row['email'] if row['email'].startswith('x:') else gone_email(row['email']), row['id']))
        if gone: stibee_sync(row['email'], False)
        if request.method == 'POST': return 'unsubscribed', 200
        return msg('unsubscribed')

    # 메일 앱이 보내는 한 번 클릭 해지(POST)는 우리 화면에서 온 게 아니라 CSRF 토큰이 없음 → 이 주소만 확인을 건너뜀 (토큰을 아는 사람만 해지 가능)
    funcs = app.before_request_funcs.setdefault(None, [])
    for i, fn in enumerate(funcs):
        if fn.__name__ == 'protect':
            def protect(_orig=fn):
                if request.path.startswith('/letter/unsubscribe/'): return None
                return _orig()
            funcs[i] = protect

    # 사이트맵에 소보루 레터(목록·보낸 호)을 더함
    if 'sitemap_xml' in app.view_functions:
        old_map = app.view_functions['sitemap_xml']
        def sitemap_xml():
            resp = old_map()
            with conn() as db: rows = db.execute("SELECT no,sent_at FROM letters WHERE status='sent' ORDER BY no DESC LIMIT 500").fetchall()
            base = S.canonical_url('')
            extra = ''.join('<url><loc>%s</loc>%s</url>' % (base + u, '<lastmod>%s</lastmod>' % d if d else '')
                            for u, d in [('/letter', None)] + [(f"/letter/{r['no']}", (r['sent_at'] or '')[:10]) for r in rows])
            resp.set_data(resp.get_data(as_text=True).replace('</urlset>', extra + '</urlset>'))
            return resp
        app.view_functions['sitemap_xml'] = sitemap_xml

    # ---- 관리자 화면 -----------------------------------------------------------
    def job_state(): return setting('letter_job', {})

    def admin_ctx():
        with conn() as db:
            rows = [row_info(r) for r in db.execute('SELECT * FROM letters ORDER BY no DESC LIMIT 40')]
            subs = db.execute("SELECT id,email,status,created,confirmed,unsubscribed,place FROM letter_subscribers ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,id DESC LIMIT 200").fetchall()
        for L in rows: L['stats'] = stats(L['id']) if L['status'] == 'sent' else None
        return dict(rows=rows, subs=subs, counts=counts(), cfg=settings(), days=DAYS, freqs=FREQS, vias=VIA, stibee_ready=stibee_ready(), ai_ready=desk.ai_ready(), naver_ready=bool(naver()) and naver()['ready'](),
                    mail_ready=notify.email_ready(), logs=setting('letter_log', [])[:10])

    @app.route('/admin/letter', methods=['GET', 'POST'])
    @S.admin_only
    def admin_letter():
        if request.method == 'POST':
            if not desk.ai_ready(): flash('OpenAI API 키가 없어서 레터를 만들 수 없어요.'); return redirect(url_for('admin_letter'))
            if testing(): return made(generate('admin'))
            j = job_state()
            if j.get('state') == 'running' and j.get('at', '') > (datetime.datetime.now() - datetime.timedelta(minutes=5)).isoformat():
                flash('이번 호를 만들고 있어요. 잠시 뒤 다시 눌러 주세요.'); return redirect(url_for('admin_letter_job'))
            put('letter_job', {'state': 'running', 'at': stamp()})
            def run():
                try: r = generate('admin')
                except Exception as e: r = {'status': 'error', 'reason': f'레터를 만들지 못했어요 ({type(e).__name__})'}
                put('letter_job', dict(r, state='done', at=stamp()))
            threading.Thread(target=run, daemon=True).start()  # AI가 1분 넘게 걸릴 수 있어 뒤에서
            return redirect(url_for('admin_letter_job'))
        return render_template('admin_letter.html', **admin_ctx())

    def made(r):
        if r['status'] == 'made':
            flash(f"{r['no']}호 초안을 만들었어요. 내용을 확인하고 보내 주세요." + (f" ({r['reason']})" if r.get('reason') else ''))
            return redirect(url_for('admin_letter_edit', lid=r['id']))
        flash(('지금은 만들 수 없어요: ' if r['status'] == 'skip' else '레터를 만들지 못했어요: ') + r.get('reason', ''))
        return redirect(url_for('admin_letter'))

    @app.route('/admin/letter/job')
    @S.admin_only
    def admin_letter_job():
        j = job_state()
        if j.get('state') == 'done': put('letter_job', {}); return made(j)
        if j.get('state') != 'running': return redirect(url_for('admin_letter'))
        return render_template('admin_letter.html', waiting=True, **admin_ctx())

    @app.route('/admin/letter/settings', methods=['POST'])
    @S.admin_only
    def admin_letter_settings():
        day, freq = request.form.get('day', type=int), request.form.get('freq', '')
        via, lst = request.form.get('via', 'site'), request.form.get('stibee_list', type=int)
        put('letter', {'auto': 1 if request.form.get('auto') else 0, 'day': day if day in range(7) else 0, 'freq': freq if freq in FREQS else 'daily',
                       'via': via if via in VIA else 'site', 'stibee_list': lst if lst and lst > 0 else 0,
                       'stibee_sender': (request.form.get('stibee_sender') or '').strip()[:120], 'stibee_name': (request.form.get('stibee_name') or '').strip()[:40]})
        flash('레터 설정을 저장했어요.')
        return redirect(url_for('admin_letter'))

    @app.route('/admin/letter/stibee-sync', methods=['POST'])
    @S.admin_only
    def admin_letter_stibee_sync():
        ok, why = stibee_push_all()
        flash(why if ok else '스티비로 옮기지 못했어요: ' + why)
        return redirect(url_for('admin_letter') + '#subs')

    @app.route('/admin/letter/subscribers', methods=['POST'])
    @S.admin_only
    def admin_letter_subs():
        sid = request.form.get('id', type=int)
        with conn() as db:
            row = db.execute('SELECT * FROM letter_subscribers WHERE id=?', (sid,)).fetchone()
            if row and row['status'] != 'unsubscribed':
                db.execute("UPDATE letter_subscribers SET status='unsubscribed',unsubscribed=?,email=? WHERE id=?",
                           (stamp(), row['email'] if row['email'].startswith('x:') else gone_email(row['email']), sid))
                flash(f"{notify.mask(row['email'])} 구독을 해지했어요.")
        if row and row['status'] != 'unsubscribed': stibee_sync(row['email'], False)
        return redirect(url_for('admin_letter') + '#subs')

    @app.route('/admin/letter/<int:lid>', methods=['GET', 'POST'])
    @S.admin_only
    def admin_letter_edit(lid):
        L = get(lid)
        if not L: abort(404)
        if request.method == 'POST':
            act = request.form.get('act', 'save')
            if act == 'delete':
                # 보낸 호도 지울 수 있음 (사이트의 지난 레터에서 사라짐. 이미 받은 메일은 그대로)
                with conn() as db: db.execute('DELETE FROM letters WHERE id=?', (lid,)); db.execute('DELETE FROM letter_sends WHERE letter_id=?', (lid,))
                flash(f"{L['no']}호를 지웠어요."); return redirect(url_for('admin_letter'))
            if L['status'] == 'draft' and act in ('save', 'test', 'send'):
                problems = save_edit(lid, request.form)
                if act == 'save': flash('저장했어요.' + (f' 검토 필요 {len(problems)}곳이 있어요.' if problems else ' 숫자·문장 검사를 통과했어요.'))
                L = get(lid)
            if act == 'test':
                to = (request.form.get('test_to') or '').strip()
                if not EMAIL_RE.match(to): flash('테스트 메일을 받을 주소를 바르게 적어 주세요.')
                elif not notify.email_ready(): flash('메일 발송 설정(SMTP)이 없어 보낼 수 없어요.')
                else:
                    subject, html, text = email_parts(L, 'test')
                    try: send_one(to, '[테스트] ' + subject, html, text, 'test'); flash(f'{to}로 테스트 메일을 보냈어요.')
                    except Exception as e: flash(f'테스트 메일을 보내지 못했어요 ({type(e).__name__})')
            elif act == 'mark_sent' and L['status'] != 'sent':
                # 스티비 등 다른 곳에서 보낸 호: 사이트 '지난 레터'에 올라가게 보낸 호로 표시 (우리 구독자에게는 보내지 않음)
                with conn() as db: db.execute("UPDATE letters SET status='sent',sent_at=?,trigger='stibee',updated=? WHERE id=?", (stamp(), stamp(), lid))
                flash('보낸 호로 표시했어요. 사이트의 지난 레터에 올라가요.')
            elif act == 'send':
                if L['status'] == 'sent': flash('이미 보낸 호예요.')
                elif L['problems'] and not request.form.get('ack'):
                    flash(f"검토 필요 {len(L['problems'])}곳이 있어 보내지 않았어요. 고치거나, 직접 확인했다면 '직접 확인했어요'에 체크하고 보내 주세요.")
                else:
                    r = send_issue(lid, 'admin')
                    flash({'sent': '구독자에게 보냈어요.', 'sending': '보내기 시작했어요. 구독자가 많으면 몇 분 걸려요.'}.get(r['status'], '보내지 못했어요: ' + r['reason']))
            return redirect(url_for('admin_letter_edit', lid=lid))
        subject, html, _ = email_parts(L, 'preview')
        html = html.replace(site_url('/static/'), request.host_url.rstrip('/') + '/static/')  # 미리보기 그림은 지금 서버에서 (운영 메일은 운영 주소)
        with conn() as db:
            sends = dict(db.execute('SELECT status,COUNT(*) FROM letter_sends WHERE letter_id=? GROUP BY status', (lid,)).fetchall())
        return render_template('admin_letter_edit.html', L=L, via=settings()['via'], preview=html, subject=subject, mail_ready=notify.email_ready(), counts=counts(), sends=sends,
                               stats=stats(lid), stibee=stibee_html(L), stibee_subject=f"[{NAME}] {L['title']}",
                               test_to=os.getenv('ADMIN_ALERT_EMAIL', '').split(',')[0].strip())

    def join_consent(email, verified):
        """회원가입 화면의 '[선택] 레터 받기'에 체크한 회원 (운영자 요청 2026-11-01).
        확인된 메일(카카오 등)이면 바로 구독하고 수신 동의 사실·일시를 메일로 알림(정보통신망법 제50조 제8항),
        직접 친 메일이면 남의 주소일 수 있어 지금처럼 확인 메일을 눌러야 구독."""
        email = (email or '').strip().lower()
        if not EMAIL_RE.match(email) or not notify.email_ready(): return
        with conn() as db:
            row = db.execute('SELECT * FROM letter_subscribers WHERE email IN (?,?)', (email, gone_email(email))).fetchone()
            if row and row['status'] == 'active': return
            token = secrets.token_urlsafe(24); state = 'active' if verified else 'pending'; at = stamp()
            if row:
                db.execute("UPDATE letter_subscribers SET email=?,token=?,status=?,asked=?,confirmed=?,ip_hash=?,place='signup',unsubscribed=NULL WHERE id=?",
                           (email, token, state, at, at if verified else None, S.ip_hash(), row['id']))
            else:
                db.execute("INSERT INTO letter_subscribers(email,token,status,created,confirmed,ip_hash,asked,place) VALUES(?,?,?,?,?,?,?,'signup')",
                           (email, token, state, at, at if verified else None, S.ip_hash(), at))
        if not verified: return send_confirm(email, token)
        stibee_sync(email)
        op = operator(); unsub = site_url(f'/letter/unsubscribe/{token}'); when = at.replace('T', ' ')[:16]
        text = (f"{NAME} 수신 동의 안내\n\n회원가입 때 '{NAME} 받기(선택)'에 동의하셔서 {NAME}를 보내 드려요.\n"
                f"- 동의한 날: {when}\n- 받는 내용: 소비자·경제 소식, 소보루 새 글 안내\n\n"
                f"원하지 않으면 언제든 한 번에 그만 받을 수 있어요: {unsub}\n\n{op['name']} {op['address']}")
        html = '<div style="font-family:sans-serif;font-size:15px;line-height:1.7;color:#191f28">' + '<br>'.join(
            str(Markup.escape(l)) for l in text.split('\n')).replace(str(Markup.escape(unsub)), f'<a href="{Markup.escape(unsub)}">{Markup.escape(unsub)}</a>') + '</div>'
        job = lambda: send_one(email, f'[{NAME}] 수신 동의 안내', html, text, token)
        if testing(): job()
        else: threading.Thread(target=lambda: _quiet(job), daemon=True).start()

    app.extensions['soboru_letter'] = {'join': join_consent, 'generate': generate, 'weekly': weekly, 'send': send_issue, 'collect': collect_news, 'settings': settings,
                                      'email_parts': email_parts, 'get': get, 'check': check, 'sections': sections,
                                      'stibee_html': stibee_html, 'stats': stats, 'stibee_push_all': stibee_push_all}


def main(argv):
    """서버 예약 작업: python soboru_letter.py weekly [--force] [--dry]. --dry는 뉴스·법 조문 후보만 모아 보여 줌(AI·저장·발송 없음)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import app as site
    import soboru_letter as mod  # app.py가 붙인 모듈 (이 파일을 바로 부르면 __main__이라 Skip이 다른 클래스)
    L = site.app.extensions['soboru_letter']
    with site.app.app_context():
        if '--dry' in argv:
            try: print(json.dumps(L['collect'](), ensure_ascii=False, indent=1)[:4000])
            except mod.Skip as e: print('건너뜀:', e)
            print('설정:', L['settings']())
            return 0
        if not argv or argv[0] != 'weekly':
            print(main.__doc__); return 1
        r = L['weekly'](force='--force' in argv)
    print(r.get('status'), r.get('no', ''), '보냄' if r.get('sent') else '', r.get('reason', ''))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
