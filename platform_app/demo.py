"""데모 환경: 가입한 회사마다 따로 만드는 연습용 작업 공간 (Gorgias의 데모·샌드박스에 해당).

실제 데이터와 완전히 나눈다.
  · 데모 회사는 status='demo', demo_of=진짜 회사 id. 소비자 검색·접수 화면(status 'active'·'listed'만 봄),
    판매처 자동 가져오기·월간 리포트·알림(status 'active'만 봄)에 절대 잡히지 않는다.
  · 데모 요청은 채널이 '데모'라 고객 알림이 나가지 않고(core.notify_consumer는 직접 등록 채널을 건너뜀), 이메일·전화도 비어 있다.
  · 데모 주문은 데모 회사에만 있어 진짜 주문·환불과 섞이지 않는다.
  · 지우기·다시 만들기는 데모 회사 것만 지운다.
"""
import datetime, secrets
from werkzeug.security import generate_password_hash
import core, chatbot
from core import conn

CHANNEL='데모'

# 견본 요청: (유형, 제목, 내용, 원하는 해결, 상품, 주문번호, 받은 지 며칠, 상태, 결정, 고객 이름)
CASES=[
 ('배송 조회','주문한 지 5일째인데 아직 출발을 안 했어요','지난주 목요일에 주문했는데 아직 배송 준비 중으로만 나와요. 언제 받을 수 있을까요?','배송 확인','리넨 셔츠 (아이보리, M)','DEMO-1001',None,'forwarded','pending','김하늘'),
 ('교환','사이즈가 커서 한 치수 작은 걸로 바꾸고 싶어요','어제 받았는데 M이 커요. S로 교환 가능할까요? 택은 그대로 있어요.','교환','와이드 데님 팬츠 (M)','DEMO-1002',1,'forwarded','pending','이도윤'),
 ('반품·환불','단순 변심으로 반품하고 싶어요','색이 화면과 달라서 반품하고 싶어요. 받은 지 3일 됐어요.','환불','니트 가디건 (베이지)','DEMO-1003',3,'seen','pending','박서준'),
 ('제품 불량','받자마자 단추가 떨어져 있었어요','포장을 열어 보니 두 번째 단추가 떨어져 있었어요. 사진 보내 드릴게요.','교환','옥스퍼드 셔츠 (블루, L)','DEMO-1004',0,'forwarded','pending','최지우'),
 ('고객 응대','전화 상담이 너무 불친절했어요','어제 전화했는데 말을 끊고 짜증을 내셨어요. 사과를 받고 싶어요.','사과·재발 방지','','',None,'seen','pending','정민재'),
 ('기타','세탁기로 빨아도 되나요?','린넨 셔츠를 샀는데 세탁기 사용이 가능한지 궁금해요.','기타','리넨 셔츠 (아이보리, M)','DEMO-1005',2,'answered','direct','한유진'),
 ('교환','교환 상품 잘 받았어요','교환해 주신 상품 잘 받았어요. 감사합니다.','교환','스트라이프 티셔츠 (S)','DEMO-1006',9,'resolved','approved','윤채원'),
 ('반품·환불','환불 계좌를 알려 드려요','반품 보냈는데 환불은 언제 되나요?','환불','코튼 원피스 (네이비)','DEMO-1007',6,'info','info','강하준'),
]
ORDERS=[('DEMO-1001','김하늘','리넨 셔츠 (아이보리, M)',39000,'paid','',''),('DEMO-1002','이도윤','와이드 데님 팬츠 (M)',52000,'delivered','CJ대한통운','612345678901'),
        ('DEMO-1003','박서준','니트 가디건 (베이지)',45000,'delivered','CJ대한통운','612345678902'),('DEMO-1004','최지우','옥스퍼드 셔츠 (블루, L)',42000,'delivered','롯데택배','312345678903'),
        ('DEMO-1005','한유진','리넨 셔츠 (아이보리, M)',39000,'delivered','CJ대한통운','612345678904'),('DEMO-1006','윤채원','스트라이프 티셔츠 (S)',19000,'exchanged','CJ대한통운','612345678905'),
        ('DEMO-1007','강하준','코튼 원피스 (네이비)',58000,'returned','우체국택배','612345678906'),('DEMO-1008','오세린','와이드 데님 팬츠 (L)',52000,'shipped','CJ대한통운','612345678907')]
PRODUCTS=[('리넨 셔츠','39,000원','M·L 있음','린넨 100%. 찬물 손세탁 또는 세탁망에 넣어 울 코스로 세탁해 주세요.'),
          ('와이드 데님 팬츠','52,000원','S·M·L 있음','면 98%, 폴리우레탄 2%. 허리 S 68cm, M 72cm, L 76cm.'),
          ('니트 가디건','45,000원','베이지·그레이','울 30%. 드라이클리닝을 권해요.')]
RULES={'배송 조회':'주문하신 상품은 오늘 출고될 예정이에요. 출고되면 송장번호를 바로 알려 드릴게요.',
       '교환':'교환 접수했어요. 받으신 상품을 아래 주소로 보내 주시면 확인 후 바로 새 상품을 보내 드려요.',
       '반품·환불':'반품 접수했어요. 상품이 도착하면 확인 후 3영업일 안에 환불해 드려요.'}
PROFILE={'brand':'데모 의류 브랜드예요. 실제 회사가 아니에요.','hours':'평일 10시~17시, 주말 휴무','shipping':'오후 2시 전 주문은 당일 출고, CJ대한통운, 5만원 이상 무료배송',
         'returns':'받은 날부터 7일 안에 교환·반품 가능, 단순 변심 왕복 배송비 6,000원','scope':'상품·배송·교환·반품 안내','handoff':'불량·파손, 환불 요청은 담당자에게 넘겨 주세요'}

def of(db,co):
    """진짜 회사의 데모 회사 (없으면 None)."""
    return db.execute("SELECT * FROM companies WHERE demo_of=? AND status='demo'",(co['id'],)).fetchone()

def create(db,co):
    """데모 회사를 만들고 견본을 채운다. 이미 있으면 그대로 돌려준다."""
    d=of(db,co)
    if d:return d
    t=core.iso()
    did=db.execute("""INSERT INTO companies(name,member,status,contact,login_id,pw_hash,biz_no,owner_name,phone,notify_email,industry,created,email_verified,plan,demo_of,return_address,return_courier,tone,report_mail)
        VALUES(?,1,'demo','02-000-0000',NULL,'','',?,'','',?,?,1,'pilot',?,'(데모) 서울시 중구 세종대로 1, 데모상점 반품 담당','CJ대한통운',?,0)""",
        (co['name']+' (데모)',co['owner_name'] or '대표',co['industry'] or '패션·잡화',t,co['id'],co['tone'] or 'polite')).lastrowid
    for cat,reply in RULES.items():db.execute('INSERT OR REPLACE INTO rules(company_id,category,auto,reply) VALUES(?,?,0,?)',(did,cat,reply))
    chatbot.save_profile(db,did,PROFILE)
    for nm,price,stock,info in PRODUCTS:db.execute('INSERT INTO products(company_id,name,price,stock,info,updated) VALUES(?,?,?,?,?,?)',(did,nm,price,stock,info,t))
    today=core.now().date()
    for i,(no,buyer,prod,amt,st,courier,inv) in enumerate(ORDERS):
        db.execute('INSERT INTO orders(company_id,order_no,channel,ordered_on,buyer,phone,address,product,qty,amount,status,courier,invoice,memo,created,updated) VALUES(?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?)',
            (did,no,'직접',(today-datetime.timedelta(days=8-i)).isoformat(),buyer,'','(데모 주소)',prod,amt,st,courier,inv,'데모 주문',t,t))
    for i,(cat,title,body,want,prod,order_no,days,status,decision,name) in enumerate(CASES):
        made=core.now()-datetime.timedelta(hours=(len(CASES)-i)*7)
        due=core.iso(made+datetime.timedelta(days=core.REPLY_DAYS))
        received=(today-datetime.timedelta(days=days)).isoformat() if days is not None else ''
        cid=db.execute('''INSERT INTO cases(no,company_id,company_name,member,category,title,body,want,order_no,name,phone,email,lookup_hash,consent,status,decision,due,created,updated,product,received_on,channel,
            ret_status,refund_status) VALUES(?,?,?,1,?,?,?,?,?,?,'','',?,1,?,?,?,?,?,?,?,?,?,?)''',
            (core.new_case_no(db),did,co['name']+' (데모)',cat,title,body,want,order_no,name,generate_password_hash(secrets.token_hex(8)),status,decision,due,core.iso(made),core.iso(made),prod,received,CHANNEL,
             'sent' if title.startswith('환불 계좌') else '','' )).lastrowid
        ev=lambda kind,text,reply='':db.execute('INSERT INTO events(case_id,kind,text,reply,created,actor) VALUES(?,?,?,?,?,?)',(cid,kind,text,reply,core.iso(made),''))
        ev('me','데모 고객이 접수했어요',body)
        if status in ('seen','answered','resolved','info'):ev('sys','기업이 확인했어요')
        if status=='answered':ev('co','답변을 보냈어요','세탁망에 넣어 울 코스로 찬물 세탁하시면 돼요. 건조기는 피해 주세요.')
        if status=='resolved':ev('co','승인했어요',RULES['교환']);ev('sys','고객이 해결됐다고 알려 주셨어요')
        if status=='info':ev('co','자료 요청: 환불 받으실 계좌를 알려 주세요')
    return core.company(db,did)

def remove(db,co):
    """데모 회사와 그 안의 것만 지운다 (진짜 회사 것은 건드리지 않는다)."""
    d=of(db,co)
    if not d:return
    ids=[r['id'] for r in db.execute('SELECT id FROM cases WHERE company_id=?',(d['id'],)).fetchall()]
    for cid in ids:
        for tbl in ('events','files','notes','tracks','app_push'):
            try:db.execute(f'DELETE FROM {tbl} WHERE case_id=?',(cid,))
            except Exception:pass
    db.execute('DELETE FROM cases WHERE company_id=?',(d['id'],))
    for tbl in ('orders','products','product_private','rules','ai_profile','chat_log','shop_links','shop_seen','staff','macros','biz_alerts'):
        try:db.execute(f'DELETE FROM {tbl} WHERE company_id=?',(d['id'],))
        except Exception:pass
    db.execute("DELETE FROM companies WHERE id=? AND status='demo'",(d['id'],))

def reset(db,co):remove(db,co);return create(db,co)

# ---------- 로그인 없이 둘러보기 (앱 심사·처음 써 보는 사람) ----------
# 진짜 회사 없이 만드는 데모: demo_of가 음수라 어떤 진짜 회사와도 이어지지 않는다. 하루 지나면 sweep_guests가 지운다.
GUEST=dict(name='소보루 둘러보기 상점',owner_name='대표',industry='패션·잡화',tone='polite')
GUEST_HOURS=24
def is_guest(co):return bool(co) and co['status']=='demo' and (co['demo_of'] or 0)<0
def guest(db):
    """둘러보기용 데모 회사를 새로 만든다 (견본은 create와 같다)."""
    while True:
        key=-secrets.randbelow(2**31-1)-1
        if not db.execute('SELECT 1 FROM companies WHERE demo_of=?',(key,)).fetchone():break
    return create(db,dict(GUEST,id=key))
def sweep_guests(db,hours=GUEST_HOURS):
    """만든 지 하루가 지난 둘러보기 회사를 지운다. 진짜 회사의 데모(demo_of>0)와 진짜 회사는 건드리지 않는다."""
    old=core.iso(core.now()-datetime.timedelta(hours=hours));n=0
    for r in db.execute("SELECT demo_of FROM companies WHERE status='demo' AND demo_of<0 AND created<?",(old,)).fetchall():remove(db,{'id':r['demo_of']});n+=1
    return n
