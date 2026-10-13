"""SOBORU 플랫폼 공통: DB, 처리 규칙(플레이북), 사건 처리 동작, 보안 도우미.

소비자용 고객센터(소보루 CS)과 기업용(소보루 CS)이 같은 DB의 같은 사건을 다룬다.
홈페이지(소비자제보센터, 저장소 최상위 app.py)와는 DB도 서비스도 따로 쓴다.
"""
import os, re, sqlite3, secrets, hashlib, hmac, datetime, contextlib, smtplib, threading, json, urllib.request, urllib.error
from pathlib import Path
from email.message import EmailMessage
from flask import session, request, abort, g
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
OPERATOR={'name':'소보루','ceo':'오규섭','biz_no':'129-14-81596','address':'서울시 강남구 논현로 310-1 4층(역삼동, 정송빌딩)','manager':'오민주'}
PRIVACY_SINCE='2026년 10월 12일'
TERMS_SINCE='2026년 10월 13일'  # 소보루 CS 기업 회원 이용약관 시행일
RETENTION_YEARS=3  # 마지막 처리일부터 이 기간이 지난 요청은 purge_old()가 파기
# 검색 노출: 이 화면들만 검색에 나오고 나머지(내 접수, 요청, 운영 등)는 noindex
INDEXABLE={'me':{'home','guide','privacy','company_page'},'biz':{'decide','login','signup','terms'}}
DESCRIPTION={'me':CNAME+'에 한 번만 접수하면 기업 답변과 처리 과정까지 한곳에서 확인해요. 배송·교환·환불·제품 불량 등 소비자 불편 접수.',
             'biz':BNAME+'는 고객 요청을 한 화면에서 승인하고 반복 요청은 자동으로 처리하는 기업용 CS 운영 도구예요.'}
VERIFY={'me':os.getenv('NAVER_SITE_VERIFICATION',''),'biz':os.getenv('NAVER_SITE_VERIFICATION_BIZ','')}
GOOGLE_VERIFY={'me':os.getenv('GOOGLE_SITE_VERIFICATION',''),'biz':os.getenv('GOOGLE_SITE_VERIFICATION_BIZ','')}
DAUM_ROBOTS={'me':os.getenv('DAUM_WEBMASTER',''),'biz':os.getenv('DAUM_WEBMASTER_BIZ','')}  # 다음 웹마스터도구가 robots.txt에 넣으라는 줄
def robots_txt(kind,disallow):
    lines=['User-agent: *','Allow: /']+['Disallow: '+p for p in disallow]+['','Sitemap: '+site_url(kind,'/sitemap.xml')]
    if DAUM_ROBOTS[kind]:lines.insert(0,DAUM_ROBOTS[kind] if DAUM_ROBOTS[kind].startswith('#') else '#'+DAUM_ROBOTS[kind])
    return '\n'.join(lines)+'\n'
MAIL_ASYNC=True  # 테스트에서는 False

CATS=['배송 조회','교환','반품·환불','제품 불량','고객 응대','기타']
CAT_HINT={'배송 조회':'배송이 안 오거나 늦어요','교환':'사이즈·색상을 바꾸고 싶어요','반품·환불':'돌려보내고 환불받고 싶어요',
          '제품 불량':'고장 나거나 망가져서 왔어요','고객 응대':'응대가 불편했어요','기타':'그 밖의 문의'}
WANTS=['교환','환불','배송 확인','사과·재발 방지','수리·A/S','기타']
# 유형별 추천 조치. 승인(또는 자동 처리)하면 steps를 차례로 기록하고 reply를 소비자에게 보낸다.
# 기업은 자동 처리 규칙 화면에서 reply 문구를 자기 회사 말로 바꿀 수 있다.
PLAYBOOK={
  '배송 조회':{'title':'송장 확인 안내','steps':['배송 문의 접수','송장 확인 안내'],'reply':'배송 문의 확인했습니다. 송장번호로 택배사 홈페이지에서 지금 위치를 바로 확인하실 수 있어요. 송장번호를 모르시거나 배송이 멈춰 있으면 이 화면에 주문번호를 남겨 주세요. 확인해서 다시 알려 드릴게요.','auto_ok':True},
  '교환':{'title':'교환 접수 + 반품 주소 안내','steps':['교환 접수','반품 주소 안내','도착 확인 후 새 상품 발송'],'reply':'교환 접수가 완료되었습니다. 기존 상품을 보내 주시면 도착을 확인한 뒤 새 상품을 바로 보내드릴게요.','auto_ok':True},
  '반품·환불':{'title':'반품 접수 + 도착 후 환불','steps':['반품 접수','반품 주소 안내','도착 확인 후 환불'],'reply':'반품 접수가 완료되었습니다. 상품을 보내 주시면 도착을 확인한 날부터 3영업일 안에 결제하신 수단으로 환불해 드릴게요. 계좌로 결제하셨다면 이 화면에서 환불 받을 계좌를 등록해 주세요.','auto_ok':True},
  '제품 불량':{'title':'무상 교환 (배송비 업체 부담)','steps':['불량 확인','무상 교환 접수','반품 주소 안내'],'reply':'불편을 드려 죄송합니다. 보내주신 내용으로 불량을 확인했고, 배송비 없이 새 상품으로 교환해 드리겠습니다. 상품을 보내 주시면 도착을 확인한 뒤 새 상품을 바로 보내드릴게요.','auto_ok':False},
  '고객 응대':{'title':'사과 답변 + 담당자 연락','steps':['사과 답변','담당자 확인'],'reply':'응대 과정에서 불쾌하셨던 점 진심으로 사과드립니다. 담당자가 직접 연락드려 자세히 듣고 바로잡겠습니다.','auto_ok':False},
  '기타':{'title':'담당자 직접 답변','steps':['담당자 확인','직접 답변'],'reply':'','auto_ok':False},
}
# 상담창(자동응답): 고객이 편하게 쓴 문장에서 이 단어들을 찾아 유형을 짐작한다. 띄어쓰기는 무시한다.
# 앞에 있는 유형일수록 같은 점수일 때 우선한다 (불량이면서 반품을 원하는 경우 불량으로).
INTENTS={
  '제품 불량':['불량','고장','깨져','깨진','깨졌','파손','찢어','찢긴','망가','작동','안켜','안 켜져','하자','오염','얼룩','누락','빠져있','구멍','터져','녹슬','유통기한','상했'],
  '반품·환불':['반품','환불','취소','돌려보','반송','마음에안','마음에 들지','변심','필요없','잘못주문','잘못 샀'],
  '교환':['교환','사이즈','색상','컬러','바꾸','바꿔','작아','커서','너무커','안맞','맞지않','다른걸로'],
  '배송 조회':['배송','안와','안 왔','안왔','언제와','언제 오','도착','송장','택배','출고','발송','늦어','배달','운송장','못받','아직'],
  '고객 응대':['응대','불친절','상담원','직원','무시','연락이없','답이없','답변이없','전화를안','태도','기분나'],
}
# 상담창에서 유형을 알아들었을 때 먼저 보여 주는 안내. 기업은 자동 처리 화면에서 자기 회사 문구로 바꿀 수 있다.
CHAT_FAQ={
  '배송 조회':'배송 상황은 송장번호로 택배사 홈페이지에서 바로 확인할 수 있어요. 송장번호를 모르시거나 배송이 너무 늦어지면 접수해 주세요. 확인해서 알려 드릴게요.',
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
DECISION={'pending':'승인 대기','approved':'승인됨','auto':'자동 처리','hold':'보류','info':'추가 확인','direct':'직접 답변'}
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
    return bool(c['member'] and not is_direct(c) and (c['category']=='반품·환불' or c['want']=='환불'))
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
    db=sqlite3.connect(DB,timeout=10);db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:yield db
    finally:db.close()

def init():
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
        for col in ('received_on','product','channel','ret_status','ret_courier','ret_tracking','refund_bank','refund_account','refund_holder','refund_status','out_courier','out_tracking'):
            if col not in cols:db.execute(f"ALTER TABLE cases ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        cols={r[1] for r in db.execute('PRAGMA table_info(companies)')}
        for col,kind in (('industry',"TEXT NOT NULL DEFAULT ''"),('tone',"TEXT NOT NULL DEFAULT 'polite'"),('return_address',"TEXT NOT NULL DEFAULT ''"),
                         ('return_courier',"TEXT NOT NULL DEFAULT ''"),('return_memo',"TEXT NOT NULL DEFAULT ''"),('kakao',"INTEGER NOT NULL DEFAULT 0"),('report_mail',"INTEGER NOT NULL DEFAULT 1")):
            if col not in cols:db.execute(f'ALTER TABLE companies ADD COLUMN {col} {kind}')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY,title TEXT NOT NULL,body TEXT NOT NULL,source_url TEXT NOT NULL,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sent_marks(kind TEXT NOT NULL,company_id INTEGER NOT NULL,key TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(kind,company_id,key));
        CREATE TABLE IF NOT EXISTS copy_edits(id INTEGER PRIMARY KEY,site TEXT NOT NULL,src TEXT NOT NULL,dst TEXT NOT NULL,created TEXT NOT NULL,UNIQUE(site,src));
        CREATE TABLE IF NOT EXISTS copy_moves(id INTEGER PRIMARY KEY,tpl TEXT NOT NULL,sel TEXT NOT NULL,dev TEXT NOT NULL,dx INTEGER NOT NULL,dy INTEGER NOT NULL,created TEXT NOT NULL,UNIQUE(tpl,sel,dev));
        CREATE TABLE IF NOT EXISTS chat_log(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,category TEXT NOT NULL,outcome TEXT NOT NULL,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS app_push(case_id INTEGER NOT NULL,token TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(case_id,token),
          FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS biz_push(token TEXT PRIMARY KEY,company_id INTEGER NOT NULL,created TEXT NOT NULL,
          FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE);
        ''')
        cols={r[1] for r in db.execute('PRAGMA table_info(rules)')}
        if 'faq' not in cols:db.execute('ALTER TABLE rules ADD COLUMN faq TEXT')
        if 'cond' not in cols:db.execute("ALTER TABLE rules ADD COLUMN cond TEXT NOT NULL DEFAULT ''")
init()

# ---------- 보안 ----------
def csrf_token():
    if 'csrf' not in session:session['csrf']=secrets.token_urlsafe(24)
    return session['csrf']
def check_csrf():
    if request.method=='POST':
        tok=session.get('csrf','')
        if not tok or not hmac.compare_digest(request.form.get('csrf',''),tok):abort(400)
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
    STEPS=STEPS,FINAL=FINAL,CATS=CATS,CHANNELS=CHANNELS,COURIERS=COURIERS,RET_STATUS=RET_STATUS,BANKS=BANKS,refund_case=lambda c:refund_case(c),mask_account=mask_account,INDUSTRIES=INDUSTRIES,TONES=TONES,COND=COND,COPY_SITES=COPY_SITES,CAT_HINT=CAT_HINT,WANTS=WANTS,PLAYBOOK=PLAYBOOK,DECISION=DECISION,PILOT=PILOT,OPERATOR=OPERATOR,site_url=lambda k,p:site_url(k,p),CNAME=CNAME,BNAME=BNAME,INDEXABLE=INDEXABLE,DESCRIPTION=DESCRIPTION,VERIFY=VERIFY,GOOGLE_VERIFY=GOOGLE_VERIFY,mask_phone=mask_phone,fmt_phone=fmt_phone)

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
def rule_for(db,cid,cat):
    r=db.execute('SELECT * FROM rules WHERE company_id=? AND category=?',(cid,cat)).fetchone()
    pb=PLAYBOOK.get(cat,PLAYBOOK['기타'])
    return {'auto':bool(r and r['auto']),'reply':(r['reply'] if r and r['reply'] is not None else pb['reply']),
            'faq':(r['faq'] if r and r['faq'] is not None else CHAT_FAQ.get(cat,CHAT_FAQ['기타'])),'cond':(r['cond'] if r and r['cond'] in COND else '')}
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
    cur=db.execute('INSERT INTO events(case_id,kind,text,reply,created) VALUES(?,?,?,?,?)',(case_id,kind,text,reply,iso()))
    db.execute('UPDATE cases SET updated=? WHERE id=?',(iso(),case_id))
    return cur.lastrowid
def events(db,case_id):return db.execute('SELECT * FROM events WHERE case_id=? ORDER BY id',(case_id,)).fetchall()
def case_files(db,case_id):return db.execute('SELECT * FROM files WHERE case_id=? ORDER BY id',(case_id,)).fetchall()
def run_playbook(db,c,how):
    """추천 조치를 실행: 후속 업무를 차례로 기록하고 기업 답변을 남긴다. how: 'auto' | 'approved'"""
    pb=PLAYBOOK.get(c['category'],PLAYBOOK['기타']);rule=rule_for(db,c['company_id'],c['category'])
    add_event(db,c['id'],'sys',('자동 처리 규칙 실행: ' if how=='auto' else '대표 승인: ')+pb['title'])
    for s in pb['steps']:add_event(db,c['id'],'sys','✓ '+s)
    reply=(rule['reply'] or '').strip()
    guide=return_guide(company(db,c['company_id'])) if c['category'] in ('교환','반품·환불','제품 불량') and not c['ret_status'] else ''
    if reply and guide:reply+='\n\n'+guide;db.execute("UPDATE cases SET ret_status='guided' WHERE id=?",(c['id'],))
    elif reply and c['category'] in ('교환','반품·환불','제품 불량') and not c['ret_status']:
        # 반품 주소를 아직 안 정했어도 회수 단계(송장 입력, 회수 확인)는 열어 둔다
        reply+='\n\n보내실 곳은 따로 안내드릴게요.';db.execute("UPDATE cases SET ret_status='guided' WHERE id=?",(c['id'],))
    if reply:add_event(db,c['id'],'co','답변을 보냈어요.',reply)
    db.execute('UPDATE cases SET status=?,decision=?,info_ask=? WHERE id=?',('answered' if reply else 'seen',how,'',c['id']))
    return bool(reply)

def return_guide(co):
    """설정에 반품 주소가 있으면 소비자에게 보낼 반품 안내 문구. 택배사는 소개만 하고 연동하지 않는다."""
    if not co or not co['return_address']:return ''
    lines=['[반품 보내실 곳]',co['return_address']]
    if co['return_courier'] in COURIERS:lines.append(f"이용 택배사: {co['return_courier']} ({COURIERS[co['return_courier']]})")
    if co['return_memo']:lines.append(co['return_memo'])
    lines.append('보내신 뒤 접수 화면에서 택배사와 송장번호를 입력해 주세요.')
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
    return n

def notify_late():
    """답변 목표일이 지난 입점 기업 요청을 소비자와 기업에 한 번씩 알린다. cron에서 부른다."""
    n=0
    with conn() as db:
        for c in db.execute("SELECT * FROM cases WHERE member=1 AND consent=1 AND due!='' AND status IN ('forwarded','seen','info')").fetchall():
            if not overdue(c) or c['late_sent']==c['due']:continue
            send_mail(c['email'],f'[{CNAME}] 기업 답변이 늦어지고 있어요',f"{c['company_name']}의 답변이 아직 없어요.\n접수 화면에서 기업에 다시 요청하거나 공식 피해구제 절차를 확인할 수 있어요.\n\n■ 접수번호: {c['no']}\n{site_or_blank('me','/mine')}")
            co=company(db,c['company_id'])
            if co:send_mail(co['notify_email'],f"[{BNAME}] 답변 기한이 지났습니다: {c['title']}",f"소비자에게 답변 지연을 알렸습니다. 지금 답변해 주세요.\n{site_or_blank('biz','/case/%d'%c['id'])}")
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
def notify_company_new(co,c):
    """입점 기업에 새 요청 알림: 이메일, 그리고 켜 두었으면 휴대폰 알림톡(누르면 승인 화면)."""
    link=site_url('biz','/case/%d'%c['id'])
    send_mail(co['notify_email'],f"[{BNAME}] 새 요청: {c['title']}",
        f"{co['name']}에 새 요청이 들어왔습니다.\n\n■ 유형: {c['category']}\n■ 요약: {c['title']}\n\n요약과 처리 방법을 보고 승인해 주세요.\n{link}")
    if co['kakao']:send_kakao(co['phone'],{'#{회사}':short(co['name'],20),'#{유형}':c['category'],'#{요약}':short(c['title']),'#{링크}':link})
    send_biz_push(co['id'],f"새 요청: {c['category']}",short(c['title']),c['id'])

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
def copy_edits(site):
    with conn() as db:
        rows=db.execute("SELECT src,dst FROM copy_edits WHERE site IN (?,'all')",(site,)).fetchall()
    esc=lambda t:t.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
    # 긴 문구부터 바꿔서 짧은 문구가 긴 문구 안을 먼저 건드리지 않게
    return [(_copy_pattern(r['src']),esc(r['dst'])) for r in sorted(rows,key=lambda r:-len(r['src'])) if r['src'].strip()]
def apply_copy(html,edits):
    if not edits:return html
    def sub(t):
        for a,b in edits:t=a.sub(lambda m:b,t)
        return t
    def tag(m):
        if m.group(1) is None:return sub(m.group(2))
        t=m.group(1)
        if re.match(r'<(script|style)\b',t,re.I):return t
        return _ATTR.sub(lambda a:a.group(1)+sub(a.group(2))+a.group(3),t)
    return _TEXT.sub(tag,html)
# 문장 위치 옮기기: 운영 화면(/ops/visual)에서 끌어 옮긴 문장은 화면(템플릿)·요소·기기(PC/모바일)별로 저장해 두고,
# 페이지를 내보낼 때 <style>로 그만큼 옮긴다. 옆 문장 자리는 그대로 두도록 position:relative로만 옮긴다.
MOVE_SEL=re.compile(r'^[a-z0-9#>:()\- _]{1,400}$')
MOVE_MEDIA={'pc':'(min-width:768px)','m':'(max-width:767.98px)'}
def copy_moves(tpl):
    with conn() as db:return db.execute('SELECT sel,dev,dx,dy FROM copy_moves WHERE tpl=?',(tpl,)).fetchall()
def moves_style(rows):
    css=''.join('@media %s{%s{position:relative;left:%dpx;top:%dpx}}'%(MOVE_MEDIA[r['dev']],r['sel'],r['dx'],r['dy']) for r in rows if r['dev'] in MOVE_MEDIA and MOVE_SEL.match(r['sel']))
    data=json.dumps([dict(sel=r['sel'],dev=r['dev'],dx=r['dx'],dy=r['dy']) for r in rows],ensure_ascii=False).replace('&','&amp;').replace("'",'&#39;').replace('<','&lt;')
    return "<style id=\"cp-moves\" data-moves='%s'>%s</style>"%(data,css)
def copy_after_request(site):
    def hook(r):
        if r.mimetype=='text/html' and not r.direct_passthrough and not request.path.startswith('/ops'):
            tpl=g.get('cp_tpl')
            try:edits=copy_edits(site);moves=copy_moves(tpl) if tpl else []
            except Exception:return r
            if edits or moves:
                html=r.get_data(as_text=True)
                if edits:html=apply_copy(html,edits)
                if moves:html=html.replace('</head>',moves_style(moves)+'</head>',1)
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
    return ('https://'+host if host else request.host_url.rstrip('/')+('/biz' if kind=='biz' and not BUSINESS_HOST else ''))+path
