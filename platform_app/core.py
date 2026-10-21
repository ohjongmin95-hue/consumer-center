"""SOBORU 플랫폼 공통: DB, 처리 규칙(플레이북), 사건 처리 동작, 보안 도우미.

소비자용 고객센터(소보루 CS)과 기업용(소보루 CS)이 같은 DB의 같은 사건을 다룬다.
홈페이지(소비자제보센터, 저장소 최상위 app.py)와는 DB도 서비스도 따로 쓴다.
"""
import os, re, sqlite3, secrets, hashlib, hmac, datetime, contextlib, smtplib, threading, json, urllib.request, urllib.error
import html as _html
from pathlib import Path
from email.message import EmailMessage
from flask import session, request, abort, g, has_request_context
from markupsafe import Markup, escape
import law

BASE=Path(__file__).parent
DB=Path(os.getenv('PLATFORM_DATABASE_PATH',str(BASE/'platform.sqlite3')))
UPLOAD=Path(os.getenv('PLATFORM_UPLOAD_DIR',str(BASE/'private_uploads')))
UPLOAD.mkdir(parents=True,exist_ok=True)
SECRET=os.getenv('SECRET_KEY') or secrets.token_hex(32)
CONSUMER_HOST=os.getenv('CONSUMER_HOST','').strip().lower()
BUSINESS_HOST=os.getenv('BUSINESS_HOST','').strip().lower()
PILOT=os.getenv('PLATFORM_MODE','pilot')!='live'
CNAME=os.getenv('CONSUMER_NAME','소보루 CS')  # 소비자 서비스 이름 (로고·제목·메일)
BNAME=os.getenv('BUSINESS_NAME','소보루 CS')
COPY_SITES={'me':'고객센터','biz':'기업용','all':'두 곳 모두'}  # 문구 고치기 적용 범위  # 기업 서비스 이름
# 개인정보 처리방침에 적는 운영 주체 (개인정보 보호법 제30조). 보호책임자는 대표자 (같은 법 제31조, 시행령 제32조제2항제2호가목)
OPERATOR={'name':'소보루','ceo':'오규섭','biz_no':'129-14-81596','address':'서울시 강남구 논현로 310-1 4층(역삼동, 정송빌딩)','manager':'오민주','phone':'02-749-7515','mail_order':''}  # mail_order: 통신판매업 신고번호 (신고하면 넣는다, 비어 있으면 안 보임)
PRIVACY_SINCE='2026년 10월 12일'
TERMS_SINCE='2026년 10월 13일'  # 소보루 CS 기업 회원 이용약관 시행일
REFUND_SINCE='2026년 10월 18일'  # 환불 정책 시행일
RETENTION_YEARS=3  # 마지막 처리일부터 이 기간이 지난 요청은 purge_old()가 파기
# 검색 노출: 이 화면들만 검색에 나오고 나머지(내 접수, 요청, 운영 등)는 noindex
INDEXABLE={'me':{'home','guide','privacy','company_page'},'biz':{'decide','login','signup','terms','refund_policy','pricing','mk.tour','mk.shop_page','mk.industries','mk.industry','mk.calculator','sl.consult','cms.blog','cms.blog_post','cms.help_home','cms.help_post','cms.stories','cms.story','gr.apply','sec.page'}}
DESCRIPTION={'me':CNAME+'에 한 번만 접수하면 기업 답변과 처리 과정까지 한곳에서 확인해요. 배송·교환·환불·제품 불량 등 소비자 불편 접수.',
             'biz':BNAME+'는 고객 요청을 한 화면에서 승인하고 반복 요청은 자동으로 처리하는 기업용 CS 운영 도구예요.'}
class _Verify(dict):
    """검색엔진 소유 확인 코드: 운영 화면 서비스 키(또는 서버 설정)에서 그때그때 읽는다. 직접 넣은 값이 있으면 그것을."""
    def __init__(self,me,biz):super().__init__();self.keys={'me':me,'biz':biz}
    def __getitem__(self,site):return dict.get(self,site) or secret(self.keys[site])
VERIFY=_Verify('NAVER_SITE_VERIFICATION','NAVER_SITE_VERIFICATION_BIZ')
GOOGLE_VERIFY=_Verify('GOOGLE_SITE_VERIFICATION','GOOGLE_SITE_VERIFICATION_BIZ')
DAUM_ROBOTS={'me':os.getenv('DAUM_WEBMASTER',''),'biz':os.getenv('DAUM_WEBMASTER_BIZ','')}  # 다음 웹마스터도구가 robots.txt에 넣으라는 줄
def robots_txt(kind,disallow):
    lines=['User-agent: *','Allow: /']+['Disallow: '+p for p in disallow]+['','Sitemap: '+site_url(kind,'/sitemap.xml')]
    if DAUM_ROBOTS[kind]:lines.insert(0,DAUM_ROBOTS[kind] if DAUM_ROBOTS[kind].startswith('#') else '#'+DAUM_ROBOTS[kind])
    return '\n'.join(lines)+'\n'
MAIL_ASYNC=True  # 테스트에서는 False

CATS=['배송 조회','주문 취소','주문 변경','교환','반품·환불','제품 불량','고객 응대','기타']
CAT_HINT={'배송 조회':'배송이 안 오거나 늦어요','주문 취소':'받기 전에 주문을 취소하고 싶어요','주문 변경':'주소·수량·옵션을 바꾸고 싶어요','교환':'사이즈·색상을 바꾸고 싶어요','반품·환불':'돌려보내고 환불받고 싶어요',
          '제품 불량':'고장 나거나 망가져서 왔어요','고객 응대':'응대가 불편했어요','기타':'그 밖의 문의'}
# 접수 화면 셋째 질문: 유형마다 요청에 맞게 묻는다 (제목, 한 줄 요약 예시, 자세한 내용 예시)
ASK={'배송 조회':('어떤 주문의 배송이\n궁금하세요?','예: 10월 7일 주문한 크림이 아직 안 왔어요','주문한 날과 상품, 지금 상황 (송장번호가 있으면 함께)'),
     '주문 취소':('어떤 주문을\n취소할까요?','예: 크림 2개 주문 취소해 주세요','주문한 날과 상품'),
     '주문 변경':('무엇을\n바꿔 드릴까요?','예: 배송지를 회사 주소로 바꿔 주세요','바꿀 내용 (새 주소·수량·옵션)을 정확히 적어 주세요'),
     '교환':('무엇으로\n바꿔 드릴까요?','예: 사이즈 M을 L로 교환해 주세요','바꾸고 싶은 사이즈·색상'),
     '반품·환불':('어떤 상품을\n반품할까요?','예: 크림 1개 반품하고 환불받고 싶어요','반품할 상품과 이유'),
     '제품 불량':('어떤 문제가\n있나요?','예: 크림 용기가 깨져서 왔어요','더 알려 주실 내용'),
     '고객 응대':('어떤 점이\n불편하셨나요?','예: 문의에 3일째 답이 없어요','더 알려 주실 내용'),
     '기타':('무엇을\n도와드릴까요?','한 줄로 요약해 주세요','궁금하거나 요청할 내용을 적어 주세요')}
ORDER_CATS=('주문 취소','주문 변경')  # 주문번호가 꼭 있어야 처리할 수 있는 유형
# 접수할 때 버튼으로 고르는 사유. 고르면 긴 글을 안 써도 된다.
REASONS={'배송 조회':['아직 안 왔어요','배송이 멈춰 있어요','배송 완료인데 못 받았어요','송장번호를 모르겠어요'],
         '주문 취소':['단순 변심','잘못 주문했어요','배송이 너무 늦어요','다른 상품으로 다시 주문할게요'],
         '주문 변경':['배송지','수량','옵션 (색상·사이즈)','받는 분 정보'],
         '교환':['사이즈가 안 맞아요','색상을 바꾸고 싶어요','다른 상품이 왔어요'],
         '반품·환불':['단순 변심','상품이 설명과 달라요','다른 상품이 왔어요','배송이 너무 늦어요'],
         '제품 불량':['깨지거나 파손됐어요','작동이 안 돼요','구성품이 빠졌어요','얼룩·오염이 있어요'],
         '고객 응대':['답변이 없어요','응대가 불친절했어요','안내가 틀렸어요']}
# 유형마다 접수 화면에 보이는 칸. 여기 없는 칸은 숨긴다 (필요한 것만 묻기).
FIELDS={'배송 조회':('order_no',),'주문 취소':('order_no',),'주문 변경':('order_no','body'),'교환':('order_no','received_on','body'),
        '반품·환불':('order_no','received_on'),'제품 불량':('files','body'),'고객 응대':('body',),'기타':('body','files')}
TEXT_CATS=('주문 변경','기타')  # 버튼만으로는 처리할 수 없어 내용을 꼭 적어야 하는 유형
# 유형만 보면 원하는 처리가 정해지는 경우 (이때는 '원하는 처리' 질문을 건너뛴다)
WANT_OF={'배송 조회':'배송 확인','주문 취소':'환불','주문 변경':'기타','교환':'교환','반품·환불':'환불','고객 응대':'사과·재발 방지'}
WANTS=['교환','환불','배송 확인','사과·재발 방지','수리·A/S','기타']
# 유형별 추천 조치. 승인(또는 자동 처리)하면 steps를 차례로 기록하고 reply를 소비자에게 보낸다.
# 기업은 자동 처리 규칙 화면에서 reply 문구를 자기 회사 말로 바꿀 수 있다.
PLAYBOOK={
  '배송 조회':{'title':'송장 확인 안내','steps':['배송 문의 접수','송장 확인 안내'],'reply':'배송 문의 확인했습니다. 송장번호로 택배사 홈페이지에서 지금 위치를 바로 확인하실 수 있어요. 송장번호를 모르시거나 배송이 멈춰 있으면 이 화면에 주문번호를 남겨 주세요. 확인해서 다시 알려 드릴게요.','auto_ok':True},
  '주문 취소':{'title':'발송 전 주문 취소 + 결제 취소','steps':['취소 요청 확인','발송 전 주문 취소','결제 취소(환불)'],'reply':'주문 취소 요청 확인했습니다. 아직 보내기 전이라 주문을 취소했고, 결제하신 수단으로 3영업일 안에 환불해 드릴게요. 계좌로 결제하셨다면 이 화면에서 환불 받을 계좌를 등록해 주세요.','auto_ok':False},
  '주문 변경':{'title':'배송지·옵션 변경 접수','steps':['변경 내용 확인','주문 정보 수정','변경 완료 안내'],'reply':'주문 변경 요청 확인했습니다. 말씀하신 내용으로 주문 정보를 바꿔 드렸어요. 이미 보낸 뒤라 바꿀 수 없는 경우에는 따로 연락드릴게요.','auto_ok':False},
  '교환':{'title':'교환 접수 + 반품 주소 안내','steps':['교환 접수','반품 주소 안내','도착 확인 후 새 상품 발송'],'reply':'교환 접수가 완료되었습니다. 기존 상품을 보내 주시면 도착을 확인한 뒤 새 상품을 바로 보내드릴게요.','auto_ok':True},
  '반품·환불':{'title':'반품 접수 + 도착 후 환불','steps':['반품 접수','반품 주소 안내','도착 확인 후 환불'],'reply':'반품 접수가 완료되었습니다. 상품을 보내 주시면 도착을 확인한 날부터 3영업일 안에 결제하신 수단으로 환불해 드릴게요. 계좌로 결제하셨다면 이 화면에서 환불 받을 계좌를 등록해 주세요.','auto_ok':True},
  '제품 불량':{'title':'무상 교환 (배송비 업체 부담)','steps':['불량 확인','무상 교환 접수','반품 주소 안내'],'reply':'불편을 드려 죄송합니다. 보내주신 내용으로 불량을 확인했고, 배송비 없이 새 상품으로 교환해 드리겠습니다. 상품을 보내 주시면 도착을 확인한 뒤 새 상품을 바로 보내드릴게요.','auto_ok':False},
  '고객 응대':{'title':'사과 답변 + 담당자 연락','steps':['사과 답변','담당자 확인'],'reply':'응대 과정에서 불쾌하셨던 점 진심으로 사과드립니다. 담당자가 직접 연락드려 자세히 듣고 바로잡겠습니다.','auto_ok':False},
  '기타':{'title':'담당자 직접 답변','steps':['담당자 확인','직접 답변'],'reply':'','auto_ok':False},
}
# 판매처·메일·DM에서 온 요청을 승인할 때 기본 문구 대신 보내는 말: 아직 하지 않은 일을 했다고 하지 않고, 고객에게 없는 화면을 안내하지 않는다
EXT_REPLY={
  '주문 취소':'주문 취소 요청 확인했습니다. 취소를 진행하고, 끝나면 다시 알려 드릴게요. 결제하신 수단으로 환불돼요.',
  '주문 변경':'주문 변경 요청 확인했습니다. 바꿀 수 있는지 확인해서 처리한 뒤 다시 알려 드릴게요. 이미 보낸 뒤라면 다른 방법을 안내해 드릴게요.',
  '반품·환불':'반품 접수가 완료되었습니다. 상품을 보내 주시면 도착을 확인한 날부터 3영업일 안에 결제하신 수단으로 환불해 드릴게요.',
}
# 상담창(자동응답): 고객이 편하게 쓴 문장에서 이 단어들을 찾아 유형을 짐작한다. 띄어쓰기는 무시한다.
# 앞에 있는 유형일수록 같은 점수일 때 우선한다 (불량이면서 반품을 원하는 경우 불량으로).
INTENTS={
  '제품 불량':['불량','고장','깨져','깨진','깨졌','파손','찢어','찢긴','망가','작동','안켜','안 켜져','하자','오염','얼룩','누락','빠져있','구멍','터져','녹슬','유통기한','상했'],
  '주문 취소':['주문취소','주문 취소','취소하고','취소해','취소할','취소하려','결제취소','결제 취소','주문 안 할','주문안할'],
  '주문 변경':['주소변경','주소 변경','주소를 바꾸','주소 바꾸','배송지','수량','옵션 변경','옵션변경','주문 변경','주문변경','잘못 입력','잘못입력','받는 사람'],
  '반품·환불':['반품','환불','돌려보','반송','마음에안','마음에 들지','변심','필요없','잘못주문','잘못 샀'],
  '교환':['교환','사이즈','색상','컬러','바꾸','바꿔','작아','커서','너무커','안맞','맞지않','다른걸로'],
  '배송 조회':['배송','안와','안 왔','안왔','언제와','언제 오','도착','송장','택배','출고','발송','늦어','배달','운송장','못받','아직'],
  '고객 응대':['응대','불친절','상담원','직원','무시','연락이없','답이없','답변이없','전화를안','태도','기분나'],
}
# 상담창에서 유형을 알아들었을 때 먼저 보여 주는 안내. 기업은 자동 처리 화면에서 자기 회사 문구로 바꿀 수 있다.
CHAT_FAQ={
  '배송 조회':'배송 상황은 송장번호로 택배사 홈페이지에서 바로 확인할 수 있어요. 송장번호를 모르시거나 배송이 너무 늦어지면 접수해 주세요. 확인해서 알려 드릴게요.',
  '주문 취소':'아직 보내기 전이면 바로 취소하고 결제하신 수단으로 환불해 드려요. 이미 보낸 뒤라면 받으신 다음 반품으로 도와드려요. 주문번호와 함께 접수해 주세요.',
  '주문 변경':'보내기 전이면 배송지·수량·옵션을 바꿀 수 있어요. 주문번호와 바꿀 내용을 적어 접수해 주세요. 이미 보낸 뒤라면 따로 안내드릴게요.',
  '교환':'사이즈나 색상 교환은 상품을 받은 날부터 7일 안에 신청해 주세요. 상품 태그와 포장은 그대로 두시면 돼요.',
  '반품·환불':'상품을 받은 날부터 7일 안이면 단순 변심이어도 반품할 수 있어요. 상품이 도착하면 확인 후 결제하신 수단으로 환불해 드려요. 계좌로 결제하셨다면 접수 후 환불 받을 계좌를 등록해 주세요.',
  '제품 불량':'불편을 드려 죄송해요. 문제가 있는 부분 사진을 함께 접수해 주시면 확인 후 교환이나 환불로 도와드려요. 이때 배송비는 저희가 부담해요.',
  '고객 응대':'불쾌하셨던 점 죄송해요. 어떤 일이 있었는지 접수해 주시면 담당자가 직접 확인하고 연락드릴게요.',
  '기타':'궁금하신 내용을 접수해 주시면 담당자가 확인하고 답변드릴게요.',
}
def classify(text):
    """고객 문장 -> 가장 그럴듯한 유형. 아무 단어도 못 찾으면 None."""
    t=re.sub(r'\s+','',text or '')
    best,score=None,0
    for cat,words in INTENTS.items():
        n=sum(re.sub(r'\s+','',w) in t for w in words)
        if n>score:best,score=cat,n
    return best
COND={'':'항상','within7':'받은 지 7일 이내일 때만'}  # 자동 처리 조건 (교환·반품에만)

STEPS=['접수','기업 전달','기업 확인','답변·조치','결과 확인']
STATUS={'received':('접수됨','gray',0),'forwarded':('기업 전달','acc',1),'seen':('기업 확인 중','wait',2),'info':('추가 자료 요청','wait',2),
        'answered':('답변·조치 완료','done',3),'resolved':('해결','done',4),'unresolved':('미해결','bad',4),
        'closed':('종료','done',4),'withdrawn':('접수 취소','gray',4)}
FINAL=('resolved','unresolved','closed','withdrawn')  # 더 처리하지 않는 상태
CLOSE_DAYS=7  # 답변 후 이 기간 동안 소비자가 아무 응답이 없으면 자동 종료
OPEN_STATUSES=('received','forwarded','seen','info')
DECISION={'pending':'승인 대기','approved':'승인됨','auto':'자동 처리','hold':'보류','info':'추가 확인','direct':'직접 답변','ai':'AI 확인 중'}
REPLY_DAYS=2  # 입점 기업 답변 목표일 (전달 후 n일)
# 기업이 전화·쇼핑몰 문의 등으로 받은 요청을 직접 등록할 때 고르는 채널 ('한큐'는 소비자가 직접 접수한 것)
CHANNELS=['전화','쇼핑몰 문의','카카오톡','인스타그램 DM','이메일','기타']
# 반품 안내에 쓰는 택배사 소개. 연동은 하지 않고 이름과 공식 홈페이지만 안내한다.
COURIERS={'CJ대한통운':'https://www.cjlogistics.com','우체국택배':'https://service.epost.go.kr','롯데택배':'https://www.lotteglogis.com',
          '한진택배':'https://www.hanjin.com','로젠택배':'https://www.ilogen.com','GS Postbox 편의점택배':'https://www.cvsnet.co.kr','CU 편의점택배':'https://www.cupost.co.kr'}
# 환불 계좌: 계좌로 결제한 고객이 등록하면 기업이 직접 입금하고 '환불 완료'를 누른다. 완료하면 계좌 정보는 바로 지운다.
BANKS=['KB국민은행','신한은행','우리은행','하나은행','NH농협은행','IBK기업은행','카카오뱅크','토스뱅크','케이뱅크','SC제일은행','iM뱅크(대구)','부산은행','경남은행','광주은행','전북은행','제주은행','새마을금고','신협','우체국','수협은행','KDB산업은행','씨티은행']
def refund_case(c):
    """환불 계좌를 받을 수 있는 요청: 입점 기업에 소비자가 직접 접수했고 환불을 원하는 경우."""
    return bool(c['member'] and c['consent'] and not is_direct(c) and (c['category'] in ('반품·환불','주문 취소') or c['want']=='환불'))
def mask_account(a):
    d=digits(a);return ('*'*max(len(d)-4,0))+d[-4:] if d else ''
RET_STATUS={'guided':'반품 안내함','sent':'소비자 발송','received':'회수 확인'}
INDUSTRIES=['패션·잡화','뷰티','식품','생활·주방','가전·디지털','가구·인테리어','유아·출산','스포츠·레저','반려동물','도서·문구','서비스','기타']
TONES={'polite':'정중하게','friendly':'친근하게','brief':'짧고 분명하게'}
ALLOWED_EXT={'.jpg','.jpeg','.png','.gif','.webp','.heic','.pdf'}
MAX_FILES=3

def now():return datetime.datetime.now().replace(microsecond=0)
def iso(dt=None):return (dt or now()).isoformat(sep=' ')

@contextlib.contextmanager
def conn():
    db=sqlite3.connect(DB,timeout=30);db.row_factory=sqlite3.Row  # 다른 쓰기가 끝나길 30초까지 기다린다
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:yield db
    finally:db.close()

def init():
    with sqlite3.connect(DB,timeout=30) as db:db.execute('PRAGMA journal_mode=WAL')  # 쓰는 중에도 읽기(상담방 새 말 받기·알림)가 기다리지 않게. 파일에 남는 설정
    with conn() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS companies(id INTEGER PRIMARY KEY,name TEXT NOT NULL,member INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'listed',contact TEXT NOT NULL DEFAULT '',login_id TEXT UNIQUE,pw_hash TEXT NOT NULL DEFAULT '',
          biz_no TEXT NOT NULL DEFAULT '',owner_name TEXT NOT NULL DEFAULT '',phone TEXT NOT NULL DEFAULT '',notify_email TEXT NOT NULL DEFAULT '',
          created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS companies_name ON companies(name);
        CREATE TABLE IF NOT EXISTS rules(company_id INTEGER NOT NULL,category TEXT NOT NULL,auto INTEGER NOT NULL DEFAULT 0,reply TEXT,
          PRIMARY KEY(company_id,category),FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS cases(id INTEGER PRIMARY KEY,no TEXT UNIQUE NOT NULL,company_id INTEGER,company_name TEXT NOT NULL,
          member INTEGER NOT NULL DEFAULT 0,category TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,want TEXT NOT NULL,
          order_no TEXT NOT NULL DEFAULT '',name TEXT NOT NULL DEFAULT '',phone TEXT NOT NULL DEFAULT '',email TEXT NOT NULL DEFAULT '',
          lookup_hash TEXT NOT NULL,consent INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL,decision TEXT NOT NULL DEFAULT '',
          info_ask TEXT NOT NULL DEFAULT '',due TEXT NOT NULL DEFAULT '',attempts INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL,updated TEXT NOT NULL,
          FOREIGN KEY(company_id) REFERENCES companies(id));
        CREATE INDEX IF NOT EXISTS cases_company ON cases(company_id,status);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,reply TEXT NOT NULL DEFAULT '',
          created TEXT NOT NULL,FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL,event_id INTEGER,stored TEXT NOT NULL,original TEXT NOT NULL,
          FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS attempts(key TEXT NOT NULL,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS mail_log(id INTEGER PRIMARY KEY,target TEXT NOT NULL,subject TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL);
        ''')
        # 나중에 더한 칸: 이미 있는 DB에도 붙인다
        cols={r[1] for r in db.execute('PRAGMA table_info(cases)')}
        if 'late_sent' not in cols:db.execute("ALTER TABLE cases ADD COLUMN late_sent TEXT NOT NULL DEFAULT ''")
        for col in ('received_on','product','channel','ret_status','ret_courier','ret_tracking','refund_bank','refund_account','refund_holder','refund_status','out_courier','out_tracking','comp','comp_status','ai_tried','order_by','ai_draft','ai_why','ai_hold'):  # order_by 'shop': 판매처가 붙여 준 주문 (회원 본인 주문). '': 고객이 적은 번호. ai_draft·ai_why: AI가 넘길 때 남긴 답변 초안과 넘긴 이유 (승인 카드에 보인다). ai_hold '1': AI는 초안만 (연결 전에 받은 메일)
            if col not in cols:db.execute(f"ALTER TABLE cases ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        cols={r[1] for r in db.execute('PRAGMA table_info(companies)')}
        for col,kind in (('industry',"TEXT NOT NULL DEFAULT ''"),('tone',"TEXT NOT NULL DEFAULT 'polite'"),('return_address',"TEXT NOT NULL DEFAULT ''"),
                         ('return_courier',"TEXT NOT NULL DEFAULT ''"),('return_memo',"TEXT NOT NULL DEFAULT ''"),('kakao',"INTEGER NOT NULL DEFAULT 0"),('report_mail',"INTEGER NOT NULL DEFAULT 1"),
                         ('widget_seen',"TEXT NOT NULL DEFAULT ''"),('widget_host',"TEXT NOT NULL DEFAULT ''"),
                         ('ai_reply',"TEXT NOT NULL DEFAULT ''"),('alert_prefs',"TEXT NOT NULL DEFAULT ''")):  # alert_prefs: 알림 종류별 받을 곳(JSON, ALERTS 기본값을 덮는다). ai_reply: 'AI 자동 답변'을 켠 때 ('' = 꺼짐). 켠 뒤에 들어온 문의에만 답한다
            if col not in cols:db.execute(f'ALTER TABLE companies ADD COLUMN {col} {kind}')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS biz_alerts(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,kind TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL DEFAULT '',
          case_id INTEGER,path TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,read_at TEXT NOT NULL DEFAULT '',FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS biz_alerts_co ON biz_alerts(company_id,id);
        CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY,title TEXT NOT NULL,body TEXT NOT NULL,source_url TEXT NOT NULL,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sent_marks(kind TEXT NOT NULL,company_id INTEGER NOT NULL,key TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(kind,company_id,key));
        CREATE TABLE IF NOT EXISTS copy_edits(id INTEGER PRIMARY KEY,site TEXT NOT NULL,src TEXT NOT NULL,dst TEXT NOT NULL,created TEXT NOT NULL,UNIQUE(site,src));
        CREATE TABLE IF NOT EXISTS copy_page_edits(id INTEGER PRIMARY KEY,site TEXT NOT NULL,tpl TEXT NOT NULL,src TEXT NOT NULL,dst TEXT NOT NULL,created TEXT NOT NULL,UNIQUE(site,tpl,src));
        CREATE TABLE IF NOT EXISTS copy_moves(id INTEGER PRIMARY KEY,tpl TEXT NOT NULL,sel TEXT NOT NULL,dev TEXT NOT NULL,dx INTEGER NOT NULL,dy INTEGER NOT NULL,created TEXT NOT NULL,UNIQUE(tpl,sel,dev));
        CREATE TABLE IF NOT EXISTS chat_log(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,category TEXT NOT NULL,outcome TEXT NOT NULL,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS app_push(case_id INTEGER NOT NULL,token TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(case_id,token),
          FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS biz_push(token TEXT PRIMARY KEY,company_id INTEGER NOT NULL,created TEXT NOT NULL,
          FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,name TEXT NOT NULL,price TEXT NOT NULL DEFAULT '',
          stock TEXT NOT NULL DEFAULT '',info TEXT NOT NULL DEFAULT '',updated TEXT NOT NULL,FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,order_no TEXT NOT NULL,channel TEXT NOT NULL DEFAULT '',
          ordered_on TEXT NOT NULL DEFAULT '',buyer TEXT NOT NULL DEFAULT '',phone TEXT NOT NULL DEFAULT '',address TEXT NOT NULL DEFAULT '',
          product TEXT NOT NULL DEFAULT '',qty INTEGER NOT NULL DEFAULT 1,amount INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'paid',
          courier TEXT NOT NULL DEFAULT '',invoice TEXT NOT NULL DEFAULT '',memo TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,updated TEXT NOT NULL,
          UNIQUE(company_id,order_no),FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS orders_phone ON orders(company_id,phone);
        CREATE TABLE IF NOT EXISTS tracks(fid TEXT PRIMARY KEY,case_id INTEGER NOT NULL,kind TEXT NOT NULL,courier TEXT NOT NULL,invoice TEXT NOT NULL,
          level INTEGER NOT NULL DEFAULT 0,place TEXT NOT NULL DEFAULT '',at TEXT NOT NULL DEFAULT '',note TEXT NOT NULL DEFAULT '',updated TEXT NOT NULL,
          FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE);
        ''')
        # AI 상담: 사업자별 상담 설정, 상품의 공개 상세(detail)와 내부 정보(공급가 등, 상담에 절대 쓰지 않음)는 다른 표에 둔다
        db.executescript('''
        CREATE TABLE IF NOT EXISTS ai_profile(company_id INTEGER PRIMARY KEY,brand TEXT NOT NULL DEFAULT '',hours TEXT NOT NULL DEFAULT '',shipping TEXT NOT NULL DEFAULT '',
          returns TEXT NOT NULL DEFAULT '',scope TEXT NOT NULL DEFAULT '',faq TEXT NOT NULL DEFAULT '',handoff TEXT NOT NULL DEFAULT '',guide TEXT NOT NULL DEFAULT '',updated TEXT NOT NULL,
          FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS product_private(product_id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,data TEXT NOT NULL,updated TEXT NOT NULL,
          FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS product_imports(token TEXT PRIMARY KEY,company_id INTEGER NOT NULL,filename TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'running',
          items TEXT NOT NULL DEFAULT '[]',error TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,
          FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE);
        ''')
        if 'detail' not in {r[1] for r in db.execute('PRAGMA table_info(products)')}:db.execute("ALTER TABLE products ADD COLUMN detail TEXT NOT NULL DEFAULT ''")
        cols={r[1] for r in db.execute('PRAGMA table_info(rules)')}
        if 'faq' not in cols:db.execute('ALTER TABLE rules ADD COLUMN faq TEXT')
        if 'cond' not in cols:db.execute("ALTER TABLE rules ADD COLUMN cond TEXT NOT NULL DEFAULT ''")
        if 'ai_ok' not in cols:db.execute("ALTER TABLE rules ADD COLUMN ai_ok TEXT NOT NULL DEFAULT ''")  # AI 자동 답변: '1' AI가 바로 답함, '0' 사장님 승인 후, '' 기본값
        if 'actor' not in {r[1] for r in db.execute('PRAGMA table_info(events)')}:db.execute("ALTER TABLE events ADD COLUMN actor TEXT NOT NULL DEFAULT ''")
        if 'assignee' not in {r[1] for r in db.execute('PRAGMA table_info(cases)')}:db.execute("ALTER TABLE cases ADD COLUMN assignee TEXT NOT NULL DEFAULT ''")
        if 'comp' not in cols:db.execute("ALTER TABLE rules ADD COLUMN comp TEXT NOT NULL DEFAULT ''")
        if not db.execute("SELECT 1 FROM settings WHERE key='ai_ok_v2'").fetchone():  # 예전 기본값을 그대로 저장한 '0'(승인 후)을 새 기본값(AI 안내)으로 한 번 되돌린다
            db.execute("UPDATE rules SET ai_ok='' WHERE ai_ok='0' AND category IN ('주문 취소','주문 변경','교환','반품·환불','제품 불량')")
            db.execute("INSERT INTO settings(key,value,updated) VALUES('ai_ok_v2','1',?)",(iso(),))
        # 받은 요청함 도구(inbox.py): 우선순위, 미루기, 합친 곳
        ccols={r[1] for r in db.execute('PRAGMA table_info(cases)')}
        for col,kind in (('priority',"TEXT NOT NULL DEFAULT 'normal'"),('snooze_until',"TEXT NOT NULL DEFAULT ''"),('merged_into',"INTEGER NOT NULL DEFAULT 0")):
            if col not in ccols:db.execute(f'ALTER TABLE cases ADD COLUMN {col} {kind}')
init()

# 외부 서비스 키: 운영 화면에서 넣은 값이 있으면 그것을, 없으면 서버 설정(/etc/soboru-platform.env)을 쓴다.
SECRETS={'SWEETTRACKER_T_KEY':('택배 조회 키','스마트택배(tracking.sweettracker.co.kr)에서 받은 무료 조회 키(t_key)'),
         'OPENAI_API_KEY':('AI 상담 키 (OpenAI)','OpenAI(platform.openai.com) > API keys에서 만든 키. sk-로 시작해요. GPT-6 Luna로 상담창·자동 답변·답변 초안·PDF 상품 등록에 써요. 넣은 뒤 운영 > AI 모델에서 연결 시험을 눌러 확인해요'),
         'ANTHROPIC_API_KEY':('AI 상담 키 (Anthropic, 예비)','Anthropic 콘솔(console.anthropic.com)에서 만든 API 키. OpenAI 키가 없을 때만 써요'),
         'NAVER_SEARCH_ID':('네이버 검색 Client ID','네이버 개발자센터(developers.naver.com) > 애플리케이션 등록 > 사용 API "검색"으로 받은 Client ID. 넣으면 AI 상담이 네이버에서 검색해요'),
         'NAVER_SEARCH_SECRET':('네이버 검색 Client Secret','위 애플리케이션의 Client Secret'),
         'NTS_API_KEY':('국세청 사업자 상태조회 키','공공데이터포털(data.go.kr) "국세청_사업자등록정보 진위확인 및 상태조회 서비스" 일반 인증키(Decoding). 넣으면 가입할 때 사업자 상태를 자동으로 확인해 바로 인증해요'),
         'GOOGLE_CLIENT_ID':('구글 로그인 클라이언트 ID','Google Cloud 콘솔 > API 및 서비스 > 사용자 인증 정보 > OAuth 클라이언트 ID(웹). 승인된 리디렉션 URI에 기업 주소/auth/google/callback 을 넣어요'),
         'GOOGLE_CLIENT_SECRET':('구글 로그인 클라이언트 보안 비밀','위 OAuth 클라이언트의 보안 비밀번호'),
         'CAFE24_CLIENT_ID':('카페24 앱 Client ID','카페24 개발자센터(developers.cafe24.com) > 앱 만들기 > 앱 정보의 Client ID. Redirect URI에 기업 주소/connect/cafe24/callback 을 넣어요. 넣으면 사장님 화면의 카페24 연결이 열려요'),
         'CAFE24_CLIENT_SECRET':('카페24 앱 Client Secret','위 앱의 Client Secret Key'),
         'CAFE24_WEBHOOK_KEY':('카페24 웹훅 인증정보','카페24 개발자센터 > 앱 > WebHook 화면 아래 인증정보. 수신 URL에 기업 주소/hook/cafe24 를 넣고 이벤트는 \'앱 삭제(90077)\'를 골라요'),
         'PORTONE_STORE_ID':('포트원 상점 아이디','포트원 관리자콘솔 > 연동 정보 > 식별코드·API Keys의 상점 아이디 (store-로 시작). 정기결제용'),
         'PORTONE_CHANNEL_KEY':('포트원 채널 키','포트원 관리자콘솔 > 연동 정보 > 채널 관리에서 정기결제(빌링키) 채널의 채널 키 (channel-key-로 시작). 시험 채널 키로는 실제 돈이 나가지 않아요'),
         'PORTONE_API_SECRET':('포트원 API 시크릿','포트원 관리자콘솔 > 연동 정보 > 식별코드·API Keys의 V2 API Secret'),
         'NAVER_SITE_VERIFICATION_BIZ':('네이버 서치어드바이저 소유 확인 (기업 사이트)','searchadvisor.naver.com > 사이트 등록 > HTML 태그 방식의 content 값만 넣어요'),
         'GOOGLE_SITE_VERIFICATION_BIZ':('구글 서치 콘솔 소유 확인 (기업 사이트)','search.google.com/search-console > URL 접두어 > HTML 태그 방식의 content 값만 넣어요')}
def secret(name):
    try:
        with conn() as db:r=db.execute('SELECT value FROM settings WHERE key=?',(name,)).fetchone()
    except Exception:r=None
    return (r['value'] if r and r['value'] else os.getenv(name,'')).strip()
def secret_source(name):
    """'ops'(운영 화면에서 넣음) | 'env'(서버 설정) | ''(없음)"""
    with conn() as db:r=db.execute('SELECT value FROM settings WHERE key=?',(name,)).fetchone()
    return 'ops' if r and r['value'] else ('env' if os.getenv(name,'').strip() else '')

# ---------- 보안 ----------
def csrf_token():
    if 'csrf' not in session:session['csrf']=secrets.token_urlsafe(24)
    return session['csrf']
def check_csrf():
    if request.method=='POST':
        tok=session.get('csrf','')
        if not tok or not hmac.compare_digest(request.form.get('csrf',''),tok):abort(400)
def bad_request():
    """영어 'Bad Request' 대신 우리말 안내. 대개 오래 열어 둔 화면에서 보냈을 때."""
    from flask import jsonify, render_template
    if request.path.startswith('/api/'):return jsonify(error='요청을 확인해 주세요.'),400
    return render_template('c_error.html',msg='화면을 오래 열어 두어서 처리하지 못했어요. 새로고침한 뒤 다시 해 주세요.'),400
def client_key(prefix):
    ip=request.headers.get('X-Forwarded-For',request.remote_addr or '').split(',')[0].strip() if os.getenv('TRUST_PROXY')=='1' else (request.remote_addr or '')
    return prefix+':'+hashlib.sha256((SECRET+ip).encode()).hexdigest()[:24]
def throttled(prefix,limit=10,minutes=10):
    """같은 곳에서 짧은 시간에 너무 많이 시도하면 True. 시도 1회를 기록한다."""
    key=client_key(prefix);since=iso(now()-datetime.timedelta(minutes=minutes))
    with conn() as db:
        db.execute('DELETE FROM attempts WHERE created<?',(iso(now()-datetime.timedelta(days=1)),))
        n=db.execute('SELECT COUNT(*) FROM attempts WHERE key=? AND created>=?',(key,since)).fetchone()[0]
        if n>=limit:return True
        db.execute('INSERT INTO attempts(key,created) VALUES(?,?)',(key,iso()))
    return False
def digits(s):return ''.join(c for c in s or '' if c.isdigit())
def mask_phone(p):
    d=digits(p);return d[:3]+'-****-'+d[-4:] if len(d)>=10 else ('****' if d else '')
def clean(s,limit):return (s or '').strip()[:limit]
BIG=50000  # 요청 제목·내용은 글자 수 제한 없이 받는다 (아주 큰 입력만 막는 안전선)

# ---------- 표시 도우미 (템플릿 전역) ----------
def status_label(s):return STATUS.get(s,STATUS['received'])[0]
def status_tone(s):return STATUS.get(s,STATUS['received'])[1]
def step_index(s):return STATUS.get(s,STATUS['received'])[2]
def parse(ts):
    try:return datetime.datetime.fromisoformat(ts)
    except (TypeError,ValueError):return None
def overdue(c):
    d=parse(c['due']);return bool(d and now()>d and c['status'] in ('forwarded','seen','info'))
def fmt(ts):
    d=parse(ts);return f'{d.month}.{d.day} {d:%H:%M}' if d else ''
def fmt_day(ts):
    d=parse(ts);return f'{d.month}월 {d.day}일' if d else ''
def fmt_phone(p):
    d=digits(p);return f'{d[:3]}-{d[3:-4]}-{d[-4:]}' if len(d) in (10,11) else (p or '')
def nl2br(s):return Markup(str(escape(s or '')).replace('\n','<br>'))
TEMPLATE_GLOBALS=dict(csrf_token=csrf_token,status_label=status_label,status_tone=status_tone,step_index=step_index,overdue=overdue,fmt=fmt,fmt_day=fmt_day,
    STEPS=STEPS,FINAL=FINAL,CATS=CATS,CHANNELS=CHANNELS,COURIERS=COURIERS,RET_STATUS=RET_STATUS,BANKS=BANKS,refund_case=lambda c:refund_case(c),mask_account=mask_account,INDUSTRIES=INDUSTRIES,TONES=TONES,COND=COND,COPY_SITES=COPY_SITES,CAT_HINT=CAT_HINT,ASK=ASK,ORDER_CATS=ORDER_CATS,REASONS=REASONS,FIELDS=FIELDS,TEXT_CATS=TEXT_CATS,WANT_OF=WANT_OF,WANTS=WANTS,PLAYBOOK=PLAYBOOK,DECISION=DECISION,PILOT=PILOT,OPERATOR=OPERATOR,site_url=lambda k,p:site_url(k,p),CNAME=CNAME,BNAME=BNAME,INDEXABLE=INDEXABLE,DESCRIPTION=DESCRIPTION,VERIFY=VERIFY,GOOGLE_VERIFY=GOOGLE_VERIFY,mask_phone=mask_phone,fmt_phone=fmt_phone)

# ---------- 기업 ----------
def company(db,cid):return db.execute('SELECT * FROM companies WHERE id=?',(cid,)).fetchone() if cid else None
def active_member(co):return bool(co and co['member'] and co['status']=='active')
def find_company(db,name):return db.execute('SELECT * FROM companies WHERE lower(name)=lower(?) ORDER BY member DESC,id LIMIT 1',(name.strip(),)).fetchone()
def search_companies(q,limit=6):
    q=q.strip()
    if not q:return []
    with conn() as db:
        return [dict(id=r['id'],name=r['name'],member=active_member(r)) for r in db.execute(
            "SELECT * FROM companies WHERE status IN ('active','listed') AND name LIKE ? ESCAPE '\\' ORDER BY member DESC,length(name) LIMIT ?",
            ('%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%',limit))]
# 상품정보: 상담창 AI가 가격·재고·사용법 문의에 답할 때 본다. 기업이 자동 처리 화면에서 등록한다.
STOCKS={'':'정하지 않음','있음':'판매 중','품절':'품절'}
MAX_PRODUCTS=300
def products(db,cid):return db.execute('SELECT * FROM products WHERE company_id=? ORDER BY name,id',(cid,)).fetchall()
def rule_for(db,cid,cat):
    r=db.execute('SELECT * FROM rules WHERE company_id=? AND category=?',(cid,cat)).fetchone()
    pb=PLAYBOOK.get(cat,PLAYBOOK['기타'])
    return {'auto':bool(r and r['auto']),'reply':(r['reply'] if r and r['reply'] is not None else pb['reply']),
            'faq':(r['faq'] if r and r['faq'] is not None else CHAT_FAQ.get(cat,CHAT_FAQ['기타'])),'cond':(r['cond'] if r and r['cond'] in COND else ''),
            'comp':(r['comp'] if r else ''),
            'ai_ok':r['ai_ok']!='0' if r else True}
# AI 자동 답변 기본값: 모든 유형에 AI가 바로 안내한다. 취소·교환·반품·환불처럼 실제 처리가 필요하면 안내는 보내고 처리 결정만 사장님께 (chatbot.action).
# 사장님이 '답도 내 승인 후'로 고른 유형만 답까지 기다린다 (운영자 결정 2026-10-18: "안내는 다 하고 결정만 물어봐").
# 예전 기본값은 취소·변경·교환·반품·환불·불량을 '승인 후'로 두었다. 그때 저장된 '0'은 init()에서 한 번 새 기본값으로 되돌린다 (ai_ok_v2)

# 보상: 기업이 유형별로 정해 둔 보상(예: 적립금 3,000원)을 요청마다 추천하고, 사장님이 승인해야 고객에게 간다. 자동으로 주지는 않는다.
COMP_CATS=('배송 조회','제품 불량','고객 응대')  # 정해 둔 보상이 없어도 보상 칸을 보여 주는 유형 (불만이 큰 유형)
COMP_EXAMPLES=['적립금 3,000원','다음 주문 10% 할인 쿠폰','왕복 배송비 환불']
def comp_rules(db,cid):return {r['category']:r['comp'] for r in db.execute("SELECT category,comp FROM rules WHERE company_id=? AND comp!=''",(cid,))}
def comp_open(c):
    """보상을 아직 정하지 않았고 정할 수 있는 요청 (고객이 직접 접수했고 철회하지 않음)."""
    return bool(c['member'] and not c['comp_status'] and c['status']!='withdrawn')
def comp_pending(c,comps):
    """정해 둔 보상이 있어 사장님 승인을 기다리는 요청."""
    return comp_open(c) and bool(comps.get(c['category']))
def auto_ok(db,c):
    """이 요청을 사람 손 없이 바로 처리해도 되는지: 자동 처리가 켜져 있고, 조건이 있으면 조건도 맞아야 한다."""
    rule=rule_for(db,c['company_id'],c['category'])
    if not rule['auto']:return False
    if rule['cond']=='within7':
        chk=law.check(c);return bool(chk and chk['within'])
    return True

# ---------- 사건 ----------
def new_case_no(db):
    while True:
        no='H'+now().strftime('%y%m%d')+'-'+''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(5))
        if not db.execute('SELECT 1 FROM cases WHERE no=?',(no,)).fetchone():return no
def add_event(db,case_id,kind,text,reply=''):
    # 기업 화면에서 직원이 한 일이면 누가 했는지 남긴다 (business.py가 요청마다 g.actor를 정한다). 고객 화면에는 보이지 않는다.
    actor=(getattr(g,'actor','') or '') if has_request_context() and kind!='me' else ''
    cur=db.execute('INSERT INTO events(case_id,kind,text,reply,created,actor) VALUES(?,?,?,?,?,?)',(case_id,kind,text,reply,iso(),actor))
    # 고객이 새로 글을 남기면 미뤄 둔 요청도 다시 '답변 전'으로 나온다
    db.execute("UPDATE cases SET updated=?"+(",snooze_until=''" if kind=='me' else '')+" WHERE id=?",(iso(),case_id))
    return cur.lastrowid
def events(db,case_id):return db.execute('SELECT * FROM events WHERE case_id=? ORDER BY id',(case_id,)).fetchall()
def case_files(db,case_id):return db.execute('SELECT * FROM files WHERE case_id=? ORDER BY id',(case_id,)).fetchall()
def run_playbook(db,c,how,send=None):
    """추천 조치를 실행: 후속 업무를 차례로 기록하고 기업 답변을 남긴다. how: 'auto' | 'approved'
    send: 주면 판매처·DM·메일로 보내는 일을 여기서 기다리지 않고 send(답)에 맡긴다 (화면이 몇 초씩 멈추지 않게)."""
    pb=PLAYBOOK.get(c['category'],PLAYBOOK['기타']);rule=rule_for(db,c['company_id'],c['category'])
    if how=='approved' and not (rule['reply'] or '').strip() and not (c['ai_draft'] or '').strip():return None  # 보낼 답변이 없으면 승인만으로는 처리하지 않는다 (직접 답변해야 함)
    add_event(db,c['id'],'sys',('자동 처리 규칙 실행: ' if how=='auto' else '대표 승인: ')+pb['title'])
    for s in pb['steps']:add_event(db,c['id'],'sys','✓ '+s)
    reply=(rule['reply'] or '').strip()
    ext=bool(db.execute('SELECT 1 FROM shop_seen WHERE company_id=? AND case_id=?',(c['company_id'],c['id'])).fetchone())  # 판매처·메일·DM에서 온 요청 (고객에게 접수 화면이 없다)
    if ext and (c['ai_draft'] or '').strip():reply=c['ai_draft'].strip()  # AI가 써 둔 초안을 승인한 것 (이 문의에 맞춘 답)
    elif ext and reply==pb['reply'] and c['category'] in EXT_REPLY:reply=EXT_REPLY[c['category']]  # 기본 문구는 '취소했어요'·'이 화면에서 계좌 등록'처럼 소보루 접수 화면 기준이라 바꿔 보낸다
    guide=return_guide(company(db,c['company_id']),ext) if c['category'] in ('교환','반품·환불','제품 불량') and not c['ret_status'] else ''
    if reply and guide:reply+='\n\n'+guide;db.execute("UPDATE cases SET ret_status='guided' WHERE id=?",(c['id'],))
    elif reply and c['category'] in ('교환','반품·환불','제품 불량') and not c['ret_status']:
        # 반품 주소를 아직 안 정했어도 회수 단계(송장 입력, 회수 확인)는 열어 둔다
        reply+='\n\n보내실 곳은 따로 안내드릴게요.';db.execute("UPDATE cases SET ret_status='guided' WHERE id=?",(c['id'],))
    if reply:add_event(db,c['id'],'co','답변을 보냈어요.',reply)
    db.execute('UPDATE cases SET status=?,decision=?,info_ask=? WHERE id=?',('answered' if reply else 'seen',how,'',c['id']))
    if reply and how=='approved' and send:send(reply)
    elif reply and how=='approved' and deliver_reply(db,c,reply)[1]=='error':  # 사람이 승인했을 때만: 인스타그램·메일·판매처에서 온 요청이면 그곳으로도 보낸다
        db.execute("UPDATE cases SET status='seen',decision='pending' WHERE id=?",(c['id'],))  # 못 보냈으면 '완료'로 두지 않는다 (진행 기록에 이유가 남음)
    if c['category']=='주문 취소':
        import orders;o=orders.for_case(db,c)
        if o and 'src' in o.keys() and o['src']=='cafe24':  # 카페24 주문은 카페24에서 취소해야 결제도 취소된다. 여기서 '취소'로만 바꾸면 카페24 취소 버튼이 사라진다
            add_event(db,c['id'],'sys',f"카페24 주문 {o['order_no']}은 주문 화면의 '카페24에서 주문 취소'를 눌러야 카페24에서도 취소돼요")
        else:orders.sync_case(db,c,'cancel')  # 이어진 주문도 '취소'로
    return bool(reply)

VIA={'email':'메일로','instagram':'인스타그램 DM으로'}
def deliver_reply(db,c,text):
    """답변 하나를 요청이 들어온 곳(판매처·메일·인스타그램)으로 보낸다. 그런 곳이 없으면 ("",""). -> (안내, ok|error)"""
    r=db.execute('SELECT shop FROM shop_seen WHERE company_id=? AND case_id=? ORDER BY rowid LIMIT 1',(c['company_id'],c['id'])).fetchone()
    if not r:return '',''
    import shops
    e=shops.post_reply(db,company(db,c['company_id']),c,text);via=VIA.get(r['shop'])
    if e:add_event(db,c['id'],'sys',(f'{via} 보내지 못했어요: ' if via else f"{c['channel']}에 답변을 올리지 못했어요: ")+e);return e,'error'
    done=f'{via} 답변을 보냈어요' if via else f"{c['channel']}에 답변을 올렸어요"
    add_event(db,c['id'],'sys',done);return done,'ok'
def return_guide(co,ext=False):
    """설정에 반품 주소가 있으면 소비자에게 보낼 반품 안내 문구. 택배사는 소개만 하고 연동하지 않는다. ext: 판매처·메일·DM 고객 (접수 화면이 없음)"""
    if not co or not co['return_address']:return ''
    lines=['[반품 보내실 곳]',co['return_address']]
    if co['return_courier'] in COURIERS:lines.append(f"이용 택배사: {co['return_courier']} ({COURIERS[co['return_courier']]})")
    if co['return_memo']:lines.append(co['return_memo'])
    lines.append('보내신 뒤 택배사와 송장번호를 이 글에 남겨 주세요.' if ext else '보내신 뒤 접수 화면에서 택배사와 송장번호를 입력해 주세요.')
    return '\n'.join(lines)
def is_direct(c):return bool(c['channel']) and c['channel']!='한큐'  # 기업이 직접 등록한 요청 (소비자는 한큐에서 볼 수 없음)

FOLLOW_UP_HOURS=24  # 다시 요청은 하루에 한 번
def last_follow_up(db,case_id):
    r=db.execute("SELECT created FROM events WHERE case_id=? AND kind='me' AND text LIKE '다시 요청%' ORDER BY id DESC LIMIT 1",(case_id,)).fetchone()
    return parse(r['created']) if r else None
def can_follow_up(db,c):
    """답변이 늦거나, 답변을 받았지만 해결이 안 됐을 때 기업에 다시 요청할 수 있다."""
    if not (overdue(c) or c['status'] in ('answered','unresolved','closed')):return False
    last=last_follow_up(db,c['id'])
    return not last or now()-last>=datetime.timedelta(hours=FOLLOW_UP_HOURS)

def close_idle(today=None):
    """답변 후 CLOSE_DAYS일 동안 소비자가 해결 여부를 알려 주지 않은 요청을 종료한다. cron에서 부른다."""
    cut=iso((today or now())-datetime.timedelta(days=CLOSE_DAYS));n=0
    with conn() as db:
        for c in db.execute("SELECT id FROM cases WHERE status='answered' AND updated<?",(cut,)).fetchall():
            db.execute("UPDATE cases SET status='closed' WHERE id=?",(c['id'],))
            add_event(db,c['id'],'sys',f'답변 후 {CLOSE_DAYS}일 동안 응답이 없어 종료했어요. 해결되지 않았다면 다시 요청할 수 있어요.');n+=1
    return n
def site_or_blank(kind,path):
    host=BUSINESS_HOST if kind=='biz' else CONSUMER_HOST
    return 'https://'+host+path if host else ''
def purge_old(today=None):
    """마지막 처리일부터 RETENTION_YEARS년이 지난 요청과 첨부 파일, 같은 기간이 지난 메일 기록을 파기한다. cron에서 부른다."""
    cut=iso((today or now())-datetime.timedelta(days=365*RETENTION_YEARS));n=0
    with conn() as db:
        for c in db.execute('SELECT id FROM cases WHERE updated<?',(cut,)).fetchall():
            for f in db.execute('SELECT stored FROM files WHERE case_id=?',(c['id'],)).fetchall():
                try:(UPLOAD/f['stored']).unlink()
                except FileNotFoundError:pass
            db.execute('DELETE FROM cases WHERE id=?',(c['id'],));n+=1
        db.execute('DELETE FROM mail_log WHERE created<?',(cut,))
        db.execute('DELETE FROM orders WHERE updated<?',(cut,))  # 기업이 올린 주문(구매자 정보 포함)도 같은 기간 뒤 파기
        db.execute('DELETE FROM biz_alerts WHERE created<?',(iso((today or now())-datetime.timedelta(days=ALERT_KEEP_DAYS)),))  # 사장님 알림 목록은 90일만
    return n

def notify_late():
    """답변 목표일이 지난 입점 기업 요청을 소비자와 기업에 한 번씩 알린다. cron에서 부른다."""
    n=0
    with conn() as db:
        for c in db.execute("SELECT * FROM cases WHERE member=1 AND consent=1 AND due!='' AND status IN ('forwarded','seen','info') AND title NOT LIKE '[시험 문의]%' AND company_id IN (SELECT id FROM companies WHERE status='active')").fetchall():  # 데모·시험 문의는 빼고
            if not overdue(c) or c['late_sent']==c['due']:continue
            if not is_direct(c):send_mail(c['email'],f'[{CNAME}] 기업 답변이 늦어지고 있어요',f"{c['company_name']}의 답변이 아직 없어요.\n접수 화면에서 기업에 다시 요청하거나 공식 피해구제 절차를 확인할 수 있어요.\n\n■ 접수번호: {c['no']}\n{site_or_blank('me','/mine')}")
            co=company(db,c['company_id'])
            if co:alert(co,'late','답변 기한이 지났어요',short(c['title'],60),case_id=c['id'],db=db,
                mail=(f"[{BNAME}] 답변 기한이 지났습니다: {c['title']}",f"소비자에게 답변 지연을 알렸습니다. 지금 답변해 주세요.\n{site_or_blank('biz','/case/%d'%c['id'])}"))
            add_event(db,c['id'],'sys','답변 목표일이 지나 소비자와 기업에 알렸어요')
            db.execute('UPDATE cases SET late_sent=? WHERE id=?',(c['due'],c['id']));n+=1
    return n

def save_files(db,case_id,uploads,event_id=None):
    saved=0
    for f in uploads:
        if not f or not f.filename:continue
        ext=Path(f.filename).suffix.lower()
        if ext not in ALLOWED_EXT or saved>=MAX_FILES:continue
        stored=secrets.token_hex(16)+ext;f.save(UPLOAD/stored)
        db.execute('INSERT INTO files(case_id,event_id,stored,original) VALUES(?,?,?,?)',(case_id,event_id,stored,clean(f.filename,120)));saved+=1
    return saved
def files_ok(uploads):
    picked=[f for f in uploads if f and f.filename]
    if len(picked)>MAX_FILES:return f'첨부는 {MAX_FILES}개까지 올릴 수 있어요.'
    for f in picked:
        if Path(f.filename).suffix.lower() not in ALLOWED_EXT:return '사진(jpg, png, gif, webp, heic)이나 PDF만 올릴 수 있어요.'
    return ''

# ---------- 새 요청 알림 ----------
# 알림톡 템플릿: BIZ_KAKAO_TPL_NEW(기업에 새 요청), CS_KAKAO_TPL_REPLY(소비자에게 기업 답변·진행 알림)
def kakao_ready(tpl='BIZ_KAKAO_TPL_NEW'):return bool(os.getenv('SOLAPI_API_KEY') and os.getenv('SOLAPI_API_SECRET') and os.getenv('SOLAPI_PFID') and os.getenv(tpl))
def send_kakao(phone,variables,tpl='BIZ_KAKAO_TPL_NEW',label='새 요청 알림톡'):
    """솔라피로 카카오 알림톡 1건. 문구는 카카오 심사를 받은 템플릿과 같아야 한다 -> docs/platform.md"""
    phone=digits(phone)
    if not phone.startswith('01') or not kakao_ready(tpl):return
    def job():
        try:
            date=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds');salt=secrets.token_hex(16)
            sig=hmac.new(os.getenv('SOLAPI_API_SECRET').encode(),(date+salt).encode(),hashlib.sha256).hexdigest()
            msg={'to':phone,'kakaoOptions':{'pfId':os.getenv('SOLAPI_PFID'),'templateId':os.getenv(tpl),'disableSms':True,'variables':variables}}
            if os.getenv('SOLAPI_SENDER'):msg['from']=digits(os.getenv('SOLAPI_SENDER'))
            req=urllib.request.Request('https://api.solapi.com/messages/v4/send',data=json.dumps({'message':msg}).encode(),method='POST',
                headers={'Content-Type':'application/json','Authorization':f"HMAC-SHA256 apiKey={os.getenv('SOLAPI_API_KEY')}, date={date}, salt={salt}, signature={sig}"})
            with urllib.request.urlopen(req,timeout=15) as r:res=json.loads(r.read().decode() or '{}')
            code=str(res.get('statusCode',''));status='sent' if not code or code in ('2000','3000','4000') else 'failed: '+code
        except Exception as e:status='failed: '+type(e).__name__
        with conn() as db:db.execute('INSERT INTO mail_log(target,subject,status,created) VALUES(?,?,?,?)',('kakao:'+phone[:3]+'****'+phone[-4:],label,status,iso()))
    threading.Thread(target=job,daemon=True).start() if MAIL_ASYNC else job()
def signer(salt):
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(SECRET,salt=salt)
def short(text,limit=30):
    text=' '.join((text or '').split());return text if len(text)<=limit else text[:limit-1]+'…'
def notify_consumer(c,subject,text):
    """소비자에게 진행 알림: 이메일(적었으면), 그리고 알림톡(CS_KAKAO_TPL_REPLY가 있으면, 접수 때 받은 휴대폰으로)."""
    if is_direct(c):return  # 직접 등록한 요청은 기업이 원래 채널로 전한다
    send_mail(c['email'],subject,f"{text}\n\n■ 접수번호: {c['no']}\n■ 요약: {c['title']}\n\n{site_url('me','/mine')}")
    send_kakao(c['phone'],{'#{회사}':short(c['company_name'],20),'#{내용}':short(text.split('\n')[0],40),'#{접수번호}':c['no'],'#{링크}':site_url('me','/mine')},'CS_KAKAO_TPL_REPLY','소비자 알림톡')
    send_push(c['id'],c['company_name'],text.split('\n')[0])
def send_push(case_id,title,body):
    """소보루 CS 앱에서 이 요청을 열어 둔 휴대폰에 알림 (Expo 푸시). 앱을 안 쓰면 아무것도 안 한다."""
    with conn() as db:toks=[r[0] for r in db.execute('SELECT token FROM app_push WHERE case_id=?',(case_id,))]
    expo_push(toks,title,body,{'case_id':case_id},'app_push')
def send_biz_push(company_id,title,body,case_id):
    """사장님 앱에 로그인해 둔 휴대폰에 알림 (새 요청 등). 누르면 그 요청 화면으로."""
    with conn() as db:toks=[r[0] for r in db.execute('SELECT token FROM biz_push WHERE company_id=?',(company_id,))]
    expo_push(toks,title,body,{'case_id':case_id},'biz_push')
def expo_push(toks,title,body,data,table):
    if not toks or os.getenv('APP_PUSH','1')=='0':return
    def job():
        try:
            msgs=[{'to':t,'title':title,'body':body,'sound':'default','data':data} for t in toks]
            req=urllib.request.Request('https://exp.host/--/api/v2/push/send',data=json.dumps(msgs).encode(),method='POST',headers={'Content-Type':'application/json','Accept':'application/json'})
            with urllib.request.urlopen(req,timeout=15) as r:res=json.loads(r.read().decode() or '{}')
            bad=[t for t,d in zip(toks,res.get('data',[])) if d.get('details',{}).get('error')=='DeviceNotRegistered']
        except Exception as e:bad,status=[],'failed: '+type(e).__name__
        else:status='sent'
        try:
            with conn() as db:
                db.executemany(f'DELETE FROM {table} WHERE token=?',[(t,) for t in bad])  # 앱을 지운 휴대폰
                db.execute('INSERT INTO mail_log(target,subject,status,created) VALUES(?,?,?,?)',('push:%d대'%len(toks),title,status,iso()))
        except sqlite3.OperationalError:pass  # 부른 쪽이 아직 쓰는 중이면 기록만 건너뛴다
    threading.Thread(target=job,daemon=True).start() if MAIL_ASYNC else job()
_msg_push={}
def notify_company_msg(db,case_id,text):
    """고객이 진행 중인 요청에 말을 더 하면 사장님께 알림 (같은 요청은 1분에 한 번만)."""
    c=db.execute('SELECT id,company_id,member,consent,title FROM cases WHERE id=?',(case_id,)).fetchone()
    if not c or not c['company_id'] or not (c['member'] and c['consent']):return
    t=now().timestamp()
    if t-_msg_push.get(case_id,0)<60:return
    _msg_push[case_id]=t
    co=company(db,c['company_id'])
    if co:alert(co,'msg','고객 메시지: '+short(c['title'],24),short(text,60),case_id=c['id'],db=db,
        mail=(f"[{BNAME}] 고객의 새 메시지: {c['title']}",f"{short(text,200)}\n\n{site_url('biz','/case/%d'%c['id'])}"))
def notify_company_new(co,c,db=None):
    """입점 기업에 새 요청 알림: 알림 목록, 앱 알림·이메일(알림 설정대로), 켜 두었으면 휴대폰 알림톡(누르면 승인 화면)."""
    if c['decision']=='ai':return  # AI가 먼저 보는 문의: 사장님께 넘길 때 알린다 (chatbot._to_owner)
    link=site_url('biz','/case/%d'%c['id'])
    alert(co,'new',f"승인할 문의: {c['category']}",short(c['title'],60),case_id=c['id'],db=db,
        mail=(f"[{BNAME}] 새 요청: {c['title']}",f"{co['name']}에 새 요청이 들어왔습니다.\n\n■ 유형: {c['category']}\n■ 요약: {c['title']}\n\n요약과 처리 방법을 보고 승인해 주세요.\n{link}"))
    if co['kakao']:send_kakao(co['phone'],{'#{회사}':short(co['name'],20),'#{유형}':c['category'],'#{요약}':short(c['title']),'#{링크}':link})

def notify_company_link_broken(co,what,why,path,db=None):
    """판매처·카페24 연결이 막 끊겼을 때 한 번 알린다 (계속 실패해도 다시 보내지 않는다)."""
    alert(co,'link',f"{what} 연결이 멈췄어요",why,path=path,db=db,
        mail=(f"[{BNAME}] {what} 연결을 확인해 주세요",f"{co['name']}의 {what} 연결이 멈췄어요. 그동안 새 문의·주문을 가져오지 못해요.\n\n■ 이유: {why}\n\n아래에서 다시 연결해 주세요.\n{site_url('biz',path)}"))

# ---------- 사장님 알림 (알림 목록 + 종류별 받을 곳) ----------
# 알림은 모두 알림 목록(웹 /alerts, 앱 알림 화면)에 남고, 앱 알림·이메일은 회사가 고른 종류만 보낸다. 알림톡은 '새 요청'에만 (설정 화면의 알림톡 스위치).
ALERTS=(('new','승인할 문의','AI가 넘기거나 사장님 승인이 필요한 새 문의',dict(push=1,email=1)),
        ('msg','고객의 새 메시지','진행 중인 문의에 고객이 말을 더 했을 때',dict(push=1,email=0)),
        ('ai','AI가 답한 문의','AI가 단순 문의에 답했을 때 (목록에서 확인)',dict(push=0,email=0)),
        ('late','답변 기한','답변 기한이 지났을 때',dict(push=1,email=1)),
        ('link','연결 끊김','카페24·인스타그램·이메일 연결이 멈췄을 때',dict(push=1,email=1)),
        ('plan','상담 건수','이번 달 상담이 요금 구간의 80%·100%에 닿았을 때',dict(push=1,email=1)))
ALERT_KEEP_DAYS=90
def alert_prefs(co):
    """{종류: {'push':0|1,'email':0|1}} — 저장한 값이 없으면 기본값."""
    try:saved=json.loads(co['alert_prefs'] or '{}')
    except (ValueError,TypeError,IndexError,KeyError):saved={}
    out={}
    for k,_,_,d in ALERTS:
        v=saved.get(k) if isinstance(saved.get(k),dict) else {}
        out[k]={ch:int(bool(v.get(ch,d[ch]))) for ch in ('push','email')}
    return out
def save_alert_prefs(db,co,f):
    """f: {'new.push':'1', ...} 처럼 켠 칸만 온다 (웹 폼·앱 공용). 없는 칸은 끔."""
    on=lambda k:str(f.get(k)) in ('1','True','true','on')
    prefs={k:{ch:int(on(f'{k}.{ch}')) for ch in ('push','email')} for k,_,_,_ in ALERTS}
    db.execute('UPDATE companies SET alert_prefs=? WHERE id=?',(json.dumps(prefs),co['id']));return prefs
def alert(co,kind,title,body='',case_id=None,path='',mail=None,db=None):
    """알림 하나: 목록에 남기고, 설정대로 앱 알림·이메일. db를 주면 그 거래 안에서 쓴다 (부른 쪽이 쓰는 중일 때 잠금을 피하려고)."""
    def put(d):
        d.execute('INSERT INTO biz_alerts(company_id,kind,title,body,case_id,path,created) VALUES(?,?,?,?,?,?,?)',(co['id'],kind,title,body,case_id,path,iso()))
    try:
        if db is not None:put(db)
        else:
            with conn() as d:put(d)
    except sqlite3.OperationalError:pass  # 목록 기록이 막혀도 알림은 보낸다
    p=alert_prefs(co).get(kind,{})
    if p.get('email') and mail:send_mail(co['notify_email'],*mail)
    if p.get('push'):send_biz_push(co['id'],title,body,case_id)
def unread_alerts(db,cid):
    return db.execute("SELECT COUNT(*) FROM biz_alerts WHERE company_id=? AND read_at=''",(cid,)).fetchone()[0]
def list_alerts(db,cid,limit=100):
    return db.execute('SELECT * FROM biz_alerts WHERE company_id=? ORDER BY id DESC LIMIT ?',(cid,limit)).fetchall()
def read_alerts(db,cid,case_id=None):
    """다 읽음 (case_id를 주면 그 문의 알림만: 문의를 열었을 때)."""
    if case_id is None:db.execute("UPDATE biz_alerts SET read_at=? WHERE company_id=? AND read_at=''",(iso(),cid))
    else:db.execute("UPDATE biz_alerts SET read_at=? WHERE company_id=? AND case_id=? AND read_at=''",(iso(),cid,case_id))

# ---------- 문구 고치기 (운영 화면 /ops/copy) ----------
# 운영자가 화면 문구를 바꾸거나 지우면, 페이지를 내보내기 직전에 글자 부분(태그 사이 글자와 입력칸 안내 글)만 바꾼다.
# 템플릿 파일은 그대로 둔다. 저장한 문구는 다시 고칠 수 있다. 운영 화면(/ops)에는 적용하지 않는다.
_TEXT=re.compile(r'(<script\b.*?</script>|<style\b.*?</style>|<[^>]*>)|([^<]+)',re.S|re.I)
_ATTR=re.compile(r'(\s(?:placeholder|aria-label|title|alt)=")([^"]*)(")')
_ENT={"'":"(?:'|&#39;|&#x27;)",'"':'(?:"|&#34;|&quot;)','&':'&amp;','<':'&lt;','>':'&gt;'}
def _copy_pattern(src):
    """화면 글자에서 문구를 찾는 패턴. 줄바꿈·띄어쓰기 차이와 따옴표가 &#39;로 바뀐 것도 같은 문구로 본다."""
    out=[]
    for tok in re.split(r'(\s+)',src.strip()):
        if not tok:continue
        out.append(r'\s+' if tok.isspace() else ''.join(_ENT.get(ch) or re.escape(ch) for ch in tok))
    return re.compile(''.join(out))
def _key(t):return ' '.join(_html.unescape(t).split())
def copy_edits(site,tpl=None):
    """이 화면에 쓸 바꾼 문구. 화면 보며 고친 글자(page)는 그 화면에서만, 문구 고치기 목록에서 고친 글자(all)는 모든 화면에."""
    with conn() as db:
        rows=db.execute("SELECT src,dst FROM copy_edits WHERE site IN (?,'all')",(site,)).fetchall()
        page=db.execute('SELECT src,dst FROM copy_page_edits WHERE site=? AND tpl=?',(site,tpl)).fetchall() if tpl else []
    esc=lambda t:t.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&#34;')
    # 고친 문구의 줄바꿈은 화면에서 <br>로 (입력칸 안내 글에서는 띄어쓰기로)
    one=lambda r:(esc(r['dst']).replace('\n','<br>'),esc(' '.join(r['dst'].split())),r['dst'])
    rows=[r for r in rows if r['src'].strip()]
    exact={_key(r['src']):one(r) for r in rows}
    exact.update({_key(r['src']):one(r) for r in page if r['src'].strip()})  # 이 화면에서 고친 것이 먼저
    rows.sort(key=lambda r:-len(r['src']))  # 긴 문구가 먼저 잡히게
    part=re.compile('|'.join('(%s)'%_copy_pattern(r['src']).pattern for r in rows)) if rows else None
    return dict(exact=exact,part=part,parts=[one(r) for r in rows])
_GONE='\x00'  # 지운 글자 자리 표시. 지운 줄의 줄바꿈(<br>)도 같이 없애서 빈 줄이 남지 않게 한다
_GONE_BR=re.compile(r'\x00[ \t\r\n]*<br\s*/?>|<br\s*/?>[ \t\r\n]*\x00',re.I)
def apply_copy(html,edits,seen=None):
    """글자 조각(태그 사이 글자)이 바꾼 문구와 통째로 같으면 그 조각을 바꾸고, 아니면 안에 든 문구를 한 번에 바꾼다.
    바꾼 결과를 다시 바꾸지 않는다. seen이 있으면 {화면에 보이는 글자: (원래 글자, 바꾼 문구)}를 모은다(화면 보며 고치기용)."""
    if not edits or not (edits['exact'] or edits['part']):return html
    ex,part,parts=edits['exact'],edits['part'],edits['parts']
    def sub(t,attr=False):
        k=_key(t)
        if not k:return t
        e=ex.get(k)
        if e:
            out=(e[1] if attr else e[0]) or ('' if attr else _GONE)
            if not attr:out=t[:len(t)-len(t.lstrip())]+out+t[len(t.rstrip()):]
        elif part:out=part.sub(lambda m:(parts[m.lastindex-1][1] if attr else parts[m.lastindex-1][0]) or ('' if attr else _GONE),t)
        else:return t
        if seen is not None and out!=t:
            shown=_key(out.replace(_GONE,'')) if attr else None
            d=e[2] if e else _html.unescape(_key(out.replace(_GONE,'')))
            for line in ([shown] if attr else [x for x in (' '.join(l.split()) for l in d.split('\n')) if x]):seen.setdefault(line,(k,d))
        return out
    def tag(m):
        if m.group(1) is None:return sub(m.group(2))
        t=m.group(1)
        if re.match(r'<(script|style)\b',t,re.I):return t
        return _ATTR.sub(lambda a:a.group(1)+sub(a.group(2),True)+a.group(3),t)
    html=_TEXT.sub(tag,html)
    if _GONE in html:html=_GONE_BR.sub('',html).replace(_GONE,'')
    return html
# 문장 위치 옮기기: 운영 화면(/ops/visual)에서 끌어 옮긴 문장은 화면(템플릿)·요소·기기(PC/모바일)별로 저장해 두고,
# 페이지를 내보낼 때 <style>로 그만큼 옮긴다. 옆 문장 자리는 그대로 두도록 position:relative로만 옮긴다.
# PC에서 옮긴 위치는 모바일에도 그대로 따라간다(가로는 화면 폭 비율만큼 줄여서). 모바일에서 따로 옮기면 모바일만 그 위치를 쓴다.
MOVE_SEL=re.compile(r'^[a-z0-9#>:()\- _]{1,400}$')
MOVE_MEDIA={'pc':'(min-width:768px)','m':'(max-width:767.98px)'}
MOVE_PC_W=1280  # PC 기준 폭: 모바일에서는 가로 이동을 (화면 폭/1280)만큼 줄인다
def copy_moves(tpl):
    with conn() as db:return db.execute('SELECT sel,dev,dx,dy FROM copy_moves WHERE tpl=?',(tpl,)).fetchall()
def moves_style(rows):
    rows=[r for r in rows if r['dev'] in MOVE_MEDIA and MOVE_SEL.match(r['sel'])];mob={r['sel'] for r in rows if r['dev']=='m'}
    m=MOVE_MEDIA['m'];css=''
    for r in rows:
        if r['dev']=='pc':
            css+='%s{position:relative;left:%dpx;top:%dpx}'%(r['sel'],r['dx'],r['dy'])
            if r['sel'] not in mob:css+='@media %s{%s{left:calc(%d * 100vw / %d)}}'%(m,r['sel'],r['dx'],MOVE_PC_W)
    for r in rows:
        if r['dev']=='m':css+='@media %s{%s{position:relative;left:%dpx;top:%dpx}}'%(m,r['sel'],r['dx'],r['dy'])
    data=json.dumps([dict(sel=r['sel'],dev=r['dev'],dx=r['dx'],dy=r['dy']) for r in rows],ensure_ascii=False).replace('&','&amp;').replace("'",'&#39;').replace('<','&lt;')
    return "<style id=\"cp-moves\" data-moves='%s'>%s</style>"%(data,css)
def copy_after_request(site):
    def hook(r):
        if r.mimetype=='text/html' and not r.direct_passthrough and not request.path.startswith('/ops'):
            tpl=g.get('cp_tpl')
            editor=request.headers.get('X-Cp-Editor')=='1'
            try:edits=copy_edits(site,tpl);moves=copy_moves(tpl) if tpl else []
            except Exception:return r
            if edits['exact'] or moves or editor:
                html=r.get_data(as_text=True);seen={} if editor else None
                html=apply_copy(html,edits,seen)
                if moves:html=html.replace('</head>',moves_style(moves)+'</head>',1)
                if editor:  # 화면 보며 고치기: 지금 보이는 글자가 원래 어떤 글자였는지 알려 줘서, 바꾼 글자를 다시 고쳐도 제대로 저장되게
                    data=json.dumps({k:{'o':o,'d':d} for k,(o,d) in seen.items()},ensure_ascii=False).replace('<','\\u003c')
                    html=html.replace('</body>','<script type="application/json" id="cp-map">'+data+'</script></body>',1)
                r.set_data(html)
            if tpl and request.headers.get('X-Cp-Editor')=='1':r.headers['X-Cp-Tpl']=tpl
        return r
    return hook
def track_template(app):
    """이 요청에서 그린 화면(템플릿) 이름을 기억한다. 문장 위치를 화면별로 저장하기 위해."""
    from flask import template_rendered
    def rec(sender,template,context,**extra):
        if 'cp_tpl' not in g:g.cp_tpl=template.name
    template_rendered.connect(rec,app,weak=False)
_TPL_SITE=lambda f:'me' if f.startswith(('c_','_c','_chat')) else 'biz' if f.startswith(('b_','_b')) else 'all' if f=='base.html' else None
_PY_SITE={'consumer.py':'me','business.py':'biz','law.py':'biz','insights.py':'biz','core.py':'all'}
def _norm(t):return ' '.join(t.split()).strip(" ·,|/()'")
def _py_texts(path):
    """파이썬 파일 안의 한글 문구 (안내 메시지, 응대 가이드 등). 설명용 주석 문자열은 뺀다."""
    import ast
    tree=ast.parse(open(path,encoding='utf-8').read());docs=set()
    for n in ast.walk(tree):
        if isinstance(n,(ast.Module,ast.FunctionDef,ast.ClassDef)) and n.body and isinstance(n.body[0],ast.Expr) and isinstance(getattr(n.body[0],'value',None),ast.Constant):docs.add(id(n.body[0].value))
        if isinstance(n,ast.JoinedStr):docs.update(id(v) for v in n.values)
    return [n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str) and id(n) not in docs and '\n' not in n.value]
def copy_catalog():
    """화면에 나오는 한글 문구 목록 (운영자가 찾아서 바꿀 수 있게). [(site, 문구, [파일들])]"""
    here=os.path.dirname(os.path.abspath(__file__));tdir=os.path.join(here,'templates');found={}
    def add(site,t,f):
        t=_norm(t)
        if re.search('[가-힣]',t) and len(t)>=2 and '{{' not in t and '{%' not in t:found.setdefault((site,t),set()).add(f)
    for f in sorted(os.listdir(tdir)):
        site=_TPL_SITE(f)
        if not site:continue
        src=re.sub(r'<script\b.*?</script>|<style\b.*?</style>|\{#.*?#\}','',open(os.path.join(tdir,f),encoding='utf-8').read(),flags=re.S)
        parts=[m.group(2) for m in re.finditer(r'(<[^>]*>)|([^<]+)',src) if m.group(2)]
        parts+=re.findall(r'placeholder="([^"{]+)"',src)
        for p in parts:
            for t in re.split(r'\{\{.*?\}\}|\{%.*?%\}',p,flags=re.S):
                if '{' not in t and '}' not in t:add(site,t,f)
        # {% for q,a in [('질문','답')] %}처럼 템플릿 코드 안에 적힌 문구
        for blk in re.findall(r'\{\{.*?\}\}|\{%.*?%\}',src,flags=re.S):
            for lit in re.findall(r"'((?:[^'\\]|\\.)*)'",blk):add(site,re.sub(r"\\(.)",r"\1",lit),f)
    for f,site in _PY_SITE.items():
        for t in _py_texts(os.path.join(here,f)):
            if len(t)<=600:add(site,t,f)
    return sorted(((s,t,sorted(fs)) for (s,t),fs in found.items()),key=lambda x:(x[0]!='me',x[1]))

# ---------- 메일 ----------
def mail_ready():return bool(os.getenv('SMTP_HOST') and os.getenv('SMTP_USER') and os.getenv('SMTP_PASSWORD'))
def send_mail(to,subject,body):
    """SMTP 설정이 있을 때만 보냄. 결과는 mail_log에 남김. 화면이 느려지지 않게 뒤에서 보냄."""
    to=(to or '').strip()
    if not to or '@' not in to or not mail_ready():return
    def job():
        try:
            msg=EmailMessage();msg['Subject']=subject;msg['From']=os.getenv('SMTP_FROM') or os.getenv('SMTP_USER');msg['To']=to;msg.set_content(body)
            port=int(os.getenv('SMTP_PORT','465'))
            with (smtplib.SMTP_SSL if port==465 else smtplib.SMTP)(os.getenv('SMTP_HOST'),port,timeout=20) as s:
                if port!=465:s.starttls()
                s.login(os.getenv('SMTP_USER'),os.getenv('SMTP_PASSWORD'));s.send_message(msg)
            status='sent'
        except Exception as e:status='failed: '+type(e).__name__
        with conn() as db:db.execute('INSERT INTO mail_log(target,subject,status,created) VALUES(?,?,?,?)',(to[:2]+'***@'+to.partition('@')[2],subject,status,iso()))
    threading.Thread(target=job,daemon=True).start() if MAIL_ASYNC else job()
def site_url(kind,path):
    host=BUSINESS_HOST if kind=='biz' else CONSUMER_HOST
    if not host and not has_request_context():return path  # cron 등 요청 밖에서 주소 설정이 없을 때
    return ('https://'+host if host else request.host_url.rstrip('/')+('/biz' if kind=='biz' and not BUSINESS_HOST else ''))+path
