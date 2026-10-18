"""공개 마케팅 화면: 제품 둘러보기, 판매처별·업종별 소개, CS 절감 계산기 (Gorgias의 Product tour·통합 페이지·업종 페이지·ROI 계산기에 해당).

원칙
  · 지금 실제로 되는 기능만 '지금 됨'으로 적는다. 키·승인이 필요한 것은 '연동 대기', 아직 안 만든 것은 '개발 예정'.
  · 고객 수·성과 숫자·후기를 지어내지 않는다. 계산기는 사장님이 넣은 값으로만 계산하고 가정을 밝힌다.
  · 둘러보기 화면은 실제 화면을 견본 데이터로 찍은 것이다 (tools/tour_shots.js로 다시 찍는다).
"""
import json
from pathlib import Path
from flask import Blueprint, render_template, request, abort, session, url_for
import core, funnel, shops

bp=Blueprint('mk',__name__)
STATIC=Path(__file__).parent/'static'

# ---------- 상태 표시 ----------
STATE={'on':('지금 됨','ok'),'beta':('시험 운영','blue'),'wait':('연동 대기','gray'),'soon':('개발 예정','gray')}

# ---------- 판매처별 ----------
SHOP_PAGES={
 'smartstore':dict(name='네이버 스마트스토어',short='스마트스토어',shop='naver',
   lead='스마트스토어 고객 문의와 주문을 소보루 한 화면으로 가져와 승인·답변·교환·반품까지 처리해요.',
   how='사장님이 네이버 커머스API센터에서 직접 발급한 애플리케이션 ID·시크릿을 넣으면 연결돼요. 소보루가 네이버와 따로 계약하지 않아요.',
   items=[('문의 가져오기','답하지 않은 고객 문의(1:1)를 10분마다 가져와 요청으로 만들어요','on'),
          ('주문 가져오기','주문·배송 상태와 송장을 주문 장부로 가져와 문의와 이어 줘요','on'),
          ('답변 올리기','소보루에서 보낸 답변을 스마트스토어 문의에 바로 올려요','beta'),
          ('상품 문의(Q&A)','상품 상세 페이지의 문의 게시판 연동','soon'),
          ('톡톡 상담','네이버 톡톡 대화 연동','soon')],
   steps=['커머스API센터에서 애플리케이션 등록 (판매자 직접 사용)','API 호출 IP에 소보루 서버 IP 등록','소보루 서비스 연동 화면에 ID·시크릿 넣기']),
 'coupang':dict(name='쿠팡',short='쿠팡',shop='coupang',
   lead='쿠팡 상품 문의와 고객센터 이관 문의, 주문을 가져와 한곳에서 처리해요.',
   how='쿠팡 Wing에서 사장님이 직접 발급한 OPEN API 키(업체코드·Access Key·Secret Key)를 넣으면 연결돼요.',
   items=[('문의 가져오기','답하지 않은 상품 문의와 쿠팡 고객센터 이관 문의를 10분마다 가져와요','on'),
          ('주문 가져오기','발주서(주문)와 배송 상태·송장을 가져와요','on'),
          ('답변 올리기','소보루에서 보낸 답변을 쿠팡 문의에 올려요 (Wing 로그인 아이디 필요)','beta'),
          ('반품·교환 접수 연동','쿠팡 반품·교환 요청 처리 연동','soon')],
   steps=['Wing > 판매자 정보 > 추가판매정보 > OPEN API 키 발급','허용 IP에 소보루 서버 IP 등록','소보루 서비스 연동 화면에 업체코드·키 넣기']),
 'cafe24':dict(name='카페24',short='카페24',shop='',
   lead='카페24 쇼핑몰의 주문·상품·게시판 문의를 소보루로 모으고, 단순 문의는 AI가 바로 답글로 답해요. 취소·반품·환불처럼 사장님이 판단할 문의만 승인 목록에 남아요.',
   how='카페24 관리자 계정으로 로그인해 권한에 동의하면 연결돼요(OAuth). 소보루는 카페24 비밀번호를 받지 않아요.',
   items=[('문의하기 버튼','쇼핑몰 HTML에 스크립트 한 줄을 넣으면 오른쪽 아래에 문의 버튼이 생겨요','on'),
          ('주문 엑셀 올리기','카페24 주문 엑셀(CSV)을 올리면 주문 장부에 들어가요','on'),
          ('앱 설치·연결','카페24 관리자 로그인과 권한 동의로 쇼핑몰 연결 (OAuth)','on'),
          ('주문·상품·게시판 문의 자동 가져오기','주문과 상품, Q&A·1:1 게시판 문의를 자동으로 가져와요','on'),
          ('AI 자동 답변','상품정보·배송 정책·소비자 법령을 보고 단순 문의엔 AI가 바로 답글을 달아요','on'),
          ('취소·반품 접수','사장님이 주문 화면에서 누르면 카페24에 취소·반품을 접수해요','on')],
   steps=['소보루 CS 가입 후 서비스 연동 > 카페24','카페24 쇼핑몰 아이디 입력 후 카페24 관리자로 로그인·권한 동의','자동 처리 화면에서 AI 상담 설정과 승인 받을 유형 정하기']),
}

# ---------- 업종별 ----------
# 업종 이름은 core.INDUSTRIES와 같게 쓴다 (가입·설정의 업종과 이어진다). 숫자는 넣지 않는다.
INDUSTRY_PAGES={
 'fashion':dict(name='패션·잡화',title='패션·의류 쇼핑몰',lead='사이즈 교환과 단순 변심 반품이 많은 패션 쇼핑몰에 맞춰 교환·반품을 빠르게 처리해요.',
   asks=['사이즈가 안 맞아 교환하고 싶어요','색이 화면과 달라요','언제 출고되나요','세탁 방법이 궁금해요'],
   feats=[('교환 흐름','교환 승인 → 반품 주소 안내 → 회수 확인 → 새 상품 송장 알림까지 한 요청 안에서'),('자동 답변','배송 조회·세탁 방법처럼 같은 질문은 정해 둔 답으로 바로'),('7일 기준 표시','받은 날부터 며칠째인지 요청마다 보여 줘요 (전자상거래법 제17조)')],
   tip='택을 떼거나 착용 흔적이 있으면 반품을 거절할 수 있는지는 상품 가치가 크게 줄었는지에 따라 달라요. 응대 가이드에서 조문을 함께 확인하세요.'),
 'beauty':dict(name='뷰티',title='화장품·뷰티 브랜드',lead='피부 트러블·용기 파손·성분 문의가 많은 뷰티 브랜드에 맞춰 사진 자료 요청과 무상 교환을 정리해요.',
   asks=['바르고 트러블이 났어요','용기가 깨져서 왔어요','성분에 ○○가 들어 있나요','유통기한이 언제까지인가요'],
   feats=[('자료 요청','트러블·파손은 사진을 요청하고 받은 자료를 요청에 함께 모아요'),('AI 상담','상품 정보를 넣어 두면 성분·사용법 문의에 AI가 먼저 답해요'),('보상 승인','정해 둔 보상(샘플·적립금 등)을 승인 한 번으로 안내')],
   tip='효능을 단정하는 답변은 피해야 해요. AI 응대 지침에 "효능을 단정하지 말 것"을 넣어 두세요.'),
 'food':dict(name='식품',title='식품 쇼핑몰',lead='배송 지연과 신선도·이물 문의가 많은 식품 쇼핑몰에 맞춰 빠른 확인과 보상 처리를 도와요.',
   asks=['배송이 늦어 상했어요','이물질이 나왔어요','유통기한이 짧아요','개봉했는데 반품되나요'],
   feats=[('배송 조회','송장으로 택배 위치를 보여 주고 배송 조회 문의에 자동으로 답해요'),('제품 불량 처리','사진 요청 → 교환·환불 승인 → 고객 알림'),('반품 제한 안내','개봉 후 가치가 크게 줄어드는 상품의 청약철회 제한 근거를 함께 보여 줘요')],
   tip='청약철회를 제한하려면 그 사실을 상품 페이지 등에 미리 분명히 알려야 해요 (전자상거래법 제17조제6항).'),
 'living':dict(name='생활·주방',title='생활용품·주방용품',lead='파손·구성품 누락·사용법 문의가 많은 생활용품 판매자에게 맞춘 처리 흐름이에요.',
   asks=['받았는데 깨져 있어요','구성품이 빠졌어요','사용법을 알려 주세요','다른 색으로 바꿀 수 있나요'],
   feats=[('사진 자료 요청','파손·누락 확인용 사진을 받아 요청에 모아요'),('주문 연결','주문번호로 주문·송장을 바로 찾아 함께 보여 줘요'),('상품 정보 AI','사용법·규격을 넣어 두면 AI 상담이 답해요')],
   tip='배송 중 파손은 판매자가 비용을 부담하는 교환이 원칙이에요. 처리 방법 카드에 미리 정리되어 있어요.'),
 'digital':dict(name='가전·디지털',title='전자제품·디지털 기기',lead='초기 불량·A/S·사용법 문의가 많은 전자제품 판매자에게 맞춰 불량 확인과 A/S 안내를 정리해요.',
   asks=['전원이 안 켜져요','A/S는 어디서 받나요','충전기가 빠졌어요','설치는 어떻게 하나요'],
   feats=[('불량 접수','증상·사진 자료 요청과 교환·수리 승인을 한 요청에서'),('A/S 안내 자동 답변','자주 묻는 A/S 문의는 정해 둔 답으로'),('담당자 배정','기술 문의는 담당 직원에게 배정하고 내부 메모로 공유')],
   tip='소비자분쟁해결기준의 품목별 기준(구입 후 10일 이내 하자 시 교환·환불 등)을 응대 가이드에서 확인할 수 있어요.'),
 'furniture':dict(name='가구·인테리어',title='가구·인테리어',lead='배송·설치 일정과 파손, 부피 큰 상품의 반품 비용 문의가 많은 판매자를 위한 흐름이에요.',
   asks=['설치 기사님은 언제 오나요','배송 중 긁혔어요','반품 배송비가 얼마인가요','조립 설명서가 없어요'],
   feats=[('일정 문의 자동 답변','배송·설치 일정 안내 문구를 정해 두고 바로 답해요'),('파손 처리','사진 자료 요청 → 교환·부분 보상 승인'),('직원 나눠 맡기','설치·배송 문의는 담당 직원에게 배정')],
   tip='반품 배송비는 단순 변심이면 소비자가, 상품 하자면 판매자가 부담하는 것이 원칙이에요.'),
 'kids':dict(name='유아·출산',title='유아·출산용품',lead='안전·성분 문의와 불량 확인이 중요한 유아용품 판매자를 위해 꼼꼼한 확인 흐름을 만들어요.',
   asks=['KC 인증을 받았나요','몇 개월부터 쓸 수 있나요','부품이 떨어졌어요','교환할 수 있나요'],
   feats=[('상품 정보 AI','인증·사용 연령을 넣어 두면 AI가 정확히 안내해요'),('불량 접수','사진 요청과 교환 승인'),('담당자에게 넘기기','안전 관련 문의는 AI가 담당자에게 넘기도록 정해요')],
   tip='안전 관련 문의는 AI가 답하지 말고 담당자에게 넘기도록 AI 상담 설정에 적어 두세요.'),
 'sports':dict(name='스포츠·레저',title='스포츠·레저',lead='사이즈·사용법·시즌 상품 배송 문의가 많은 판매자를 위한 흐름이에요.',
   asks=['사이즈 표가 어떻게 되나요','캠핑 전에 받을 수 있나요','교환하고 싶어요','부품만 따로 살 수 있나요'],
   feats=[('배송 조회','송장 위치 안내와 자동 답변'),('교환 흐름','반품 주소 안내부터 새 상품 발송까지'),('AI 상담','사이즈표·사용법 안내')],
   tip='사이즈 문의는 상품 정보에 사이즈표를 넣어 두면 AI가 바로 답해요.'),
 'pet':dict(name='반려동물',title='반려동물용품',lead='사료 급여량·성분, 배송 문의가 많은 반려동물용품 판매자를 위한 흐름이에요.',
   asks=['하루에 얼마나 먹이나요','알레르기 성분이 있나요','정기 배송을 바꾸고 싶어요','포장이 터져서 왔어요'],
   feats=[('상품 정보 AI','급여량·성분 안내'),('파손 처리','사진 요청과 교환'),('자동 답변','배송 문의 자동 처리')],
   tip='건강 관련 질문은 수의사 상담을 권하도록 AI 응대 지침에 적어 두세요.'),
 'books':dict(name='도서·문구',title='도서·문구',lead='파손·오배송·재고 문의가 많은 도서·문구 판매자를 위한 흐름이에요.',
   asks=['다른 책이 왔어요','표지가 찢어져 왔어요','재입고는 언제인가요','대량 구매가 되나요'],
   feats=[('오배송 처리','교환 승인과 회수·재발송'),('재고 문의 AI','상품 재고를 넣어 두면 AI가 답해요'),('대량 문의 넘기기','대량 구매는 담당자에게')],
   tip='대량 구매 문의는 AI가 담당자에게 넘기도록 정해 두면 놓치지 않아요.'),
 'service':dict(name='서비스',title='서비스업',lead='예약 변경·취소·환불 문의를 한곳에서 정리해요.',
   asks=['예약을 바꾸고 싶어요','취소하면 환불되나요','영수증을 받을 수 있나요','담당자와 통화하고 싶어요'],
   feats=[('직접 등록','전화·카카오톡으로 받은 문의도 직접 등록해 같은 화면에서'),('담당자 배정','직원에게 나눠 맡기기'),('답변 초안','회사 말투로 답변 초안 만들기')],
   tip='전화로 받은 문의도 직접 등록해 두면 기록이 남고 통계에 함께 잡혀요.'),
}

# ---------- 절감 계산기 ----------
MIN_WAGE_2026=10320  # 2026년 최저임금 (시간급, 고용노동부 고시)
CALC_DEFAULT=dict(inquiries=300,minutes=6,wage=MIN_WAGE_2026,auto=30)
CALC_LIMIT=dict(inquiries=(1,1000000),minutes=(1,240),wage=(1000,200000),auto=(0,100))
def num(v,lo,hi,dflt):
    try:x=float(str(v).replace(',',''))
    except (TypeError,ValueError):return dflt
    return max(lo,min(hi,x))
def calc(args):
    """넣은 값만으로 계산한다. 결과는 원 단위로 반올림."""
    v={k:num(args.get(k),*CALC_LIMIT[k],d) for k,d in CALC_DEFAULT.items()}
    hours=v['inquiries']*v['minutes']/60
    saved_h=hours*v['auto']/100
    month=round(saved_h*v['wage'])
    return dict(v=v,hours=round(hours,1),saved_h=round(saved_h,1),month=month,year=month*12,cost=round(hours*v['wage']))

# ---------- 제품 둘러보기 ----------
# (그림 키, 제목, 설명, 덧붙임). 3분 안팎으로 읽히게 8단계.
TOUR=[('home','오늘 먼저 볼 일만 모아요','로그인하면 승인할 요청, 답할 요청, 기한이 지난 요청 수와 소보루 브리핑이 먼저 보여요. 브리핑은 실제 요청·주문 숫자로 만들어요.',''),
      ('inbox','모든 채널의 문의가 한 목록으로','고객센터 접수, 스마트스토어·쿠팡 문의, 전화·카카오톡으로 받아 직접 등록한 문의까지 한 목록에서 상태별로 봐요. 내 담당·담당자 없음으로도 걸러요.',''),
      ('case','요약과 처리 방법, 답변 초안까지','요청을 열면 고객이 원하는 해결, 주문 정보, 받은 지 며칠째인지(7일 기준)와 처리 방법 카드가 함께 보여요. 초안 만들기를 누르면 회사 말투로 답변 초안을 써 줘요.','AI 키가 없으면 유형별 기본 문구로 초안을 만들어요.'),
      ('rules','반복 문의는 자동으로','배송 조회·교환 방법처럼 같은 질문은 규칙을 한 번 정해 두면 들어오는 즉시 정해 둔 답으로 처리해요. 조건(주문 상태 등)을 붙일 수도 있어요.',''),
      ('chat','고객센터 화면의 AI 상담','쇼핑몰에 붙인 문의 버튼을 누르면 이 화면이 열려요. 회사 소개·배송·반품 규정·상품 정보를 바탕으로 AI가 먼저 답하고, 정해 둔 경우에는 담당자에게 넘겨요.',''),
      ('returns','교환·반품을 단계별로','교환·반품 요청은 반품 안내 → 고객 발송 → 회수 확인 → 새 상품 발송·환불 완료까지 단계가 보여요. 승인과 환불 완료는 대표·관리자만 할 수 있어요.',''),
      ('assign','직원에게 나눠 맡기기','요청마다 담당자를 정하고, 고객에게 보이지 않는 내부 메모로 의견을 나눠요. @이름을 쓰면 그 직원에게 알림이 가요. 직원 수로 요금을 받지 않아요.',''),
      ('stats','숫자로 보는 CS','받은 요청, 자동 처리율, 해결률, 기한 지난 요청과 유형별 비율을 주 단위로 봐요. 실제로 들어온 요청으로만 계산해요.','')]
def tour_steps():
    """TOUR 글 + static/tour/tour.json(실제 화면을 견본 데이터로 찍은 그림과 짚어 줄 위치 %). 그림이 없는 단계는 뺀다."""
    try:shots=json.loads((STATIC/'tour'/'tour.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):shots={}
    return [dict(shots[k],key=k,title=t,text=x,note=n) for k,t,x,n in TOUR if shots.get(k,{}).get('d')]

PUBLIC={'decide','signup','terms','refund_policy','pricing'}  # 로그인 전 방문을 세는 화면 (mk.* 전부 포함)
@bp.before_app_request
def count_visit():
    if request.method!='GET' or session.get('co_id') or session.get('ops') or request.path.startswith('/ops'):return  # 운영자·로그인한 회사는 방문으로 세지 않는다
    ep=request.endpoint or ''
    if ep.startswith(('mk.','cms.')) or ep in PUBLIC:funnel.visit()

def nav():
    return [('mk.tour','제품 둘러보기'),('mk.shop_page','판매처 연결'),('mk.industries','업종별'),('mk.calculator','절감 계산기')]

@bp.route('/tour')
def tour():
    funnel.track('tour')
    return render_template('m_tour.html',steps=tour_steps(),tab='mk.tour')

@bp.route('/for')
@bp.route('/for/<slug>')
def shop_page(slug='smartstore'):
    p=SHOP_PAGES.get(slug)
    if not p:abort(404)
    return render_template('m_shop.html',p=p,slug=slug,pages=SHOP_PAGES,STATE=STATE,ip=shops.server_ip(),tab='mk.shop_page')

@bp.route('/industries')
def industries():
    return render_template('m_industries.html',pages=INDUSTRY_PAGES,tab='mk.industries')
@bp.route('/industries/<slug>')
def industry(slug):
    p=INDUSTRY_PAGES.get(slug)
    if not p:abort(404)
    return render_template('m_industry.html',p=p,slug=slug,pages=INDUSTRY_PAGES,tab='mk.industries')

@bp.route('/calculator')
def calculator():
    r=calc(request.args)
    if any(k in request.args for k in CALC_DEFAULT):funnel.track('calc',detail=f"{int(r['v']['inquiries'])}건")
    return render_template('m_calc.html',r=r,MIN_WAGE=MIN_WAGE_2026,LIMIT=CALC_LIMIT,tab='mk.calculator')

def sitemap_paths():
    return ['/tour','/calculator','/industries']+['/for/'+k for k in SHOP_PAGES]+['/industries/'+k for k in INDUSTRY_PAGES]
