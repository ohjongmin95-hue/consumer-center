"""제품 둘러보기 영상을 찍기 위한 개발용 서버 (실제 서버에서 쓰지 않는다). tour_server.py를 바탕으로 했다.

임시 DB에 견본 회사(인증 완료) 하나를 만들고 영상용 상담(카페24·인스타그램 DM·이메일·상담창)을 채워 127.0.0.1:8823(VIDEO_PORT)에 띄운다.
AI는 키가 없으므로 이 서버 안에서만 정해 둔 한국어 답으로 바꿔 끼운다.
  python tools/video_server.py  &  node tools/tour_video.js
"""
import os, sys, tempfile, datetime, json, secrets
from pathlib import Path
from werkzeug.security import generate_password_hash
d=tempfile.mkdtemp()
os.environ.update(PLATFORM_DATABASE_PATH=d+'/p.sqlite3',PLATFORM_UPLOAD_DIR=d+'/up',SECRET_KEY='tour-video-only-'+os.urandom(8).hex(),
                  OPS_PASSWORD_HASH=generate_password_hash(os.getenv('TOUR_OPS_PW') or os.urandom(8).hex()),CONSUMER_HOST='',BUSINESS_HOST='',PLATFORM_MODE='pilot')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hanq, core, demo, chatbot, ai, business
core.throttled=lambda *a,**k:False
business.CH_MARK['인스타그램 DM']=business.CH_MARK['인스타그램']  # 인스타그램 문의 채널 이름('인스타그램 DM')에도 아이콘

# ---------- 정해 둔 AI 답 (이 개발 서버에서만) ----------
CANNED=[
 (('배송','언제','도착','출발','오나요','와요'),'배송 조회','주문하신 리넨 셔츠(아이보리, M)는 어제 CJ대한통운으로 출고됐어요. 내일(목) 도착 예정이에요. 송장번호는 주문 조회에서 바로 확인하실 수 있어요.'),
 (('사이즈','교환'),'교환','받으신 날부터 7일 안에 교환할 수 있어요. 택을 떼지 않은 상태로 보내 주시면 확인 후 S 사이즈로 바로 보내 드려요.'),
 (('세탁','빨아'),'기타','린넨 100%라 찬물 손세탁이나 세탁망에 넣어 울 코스로 빨아 주세요. 건조기는 줄어들 수 있어 피해 주세요.'),
 (('반품','환불'),'반품·환불','받은 날부터 7일 안에 반품할 수 있어요. 단순 변심은 왕복 배송비 6,000원이 들어요. 환불은 담당자가 확인한 뒤 진행해 드려요.'),
]
def canned(text):
    t=text or ''
    for keys,cat,ans in CANNED:
        if any(k in t for k in keys):return cat,ans
    return '기타','문의 주셔서 감사해요. 확인해서 바로 안내해 드릴게요.'
def fake_answer(co,facts,text,history=None,meta=None,asks=None):
    cat,ans=canned(text)
    return {'answer':ans,'category':cat if cat in core.CATS else None,'handoff':False,'action':cat=='반품·환불','lookup':False,'summary':'','tier':'fast','promise':False}
def fake_chat(system,messages,**kw):
    cat,ans=canned(messages[-1]['content'] if messages else '')
    return json.dumps({'answer':ans,'category':cat},ensure_ascii=False) if kw.get('json_mode') else ans
chatbot.answer=fake_answer;chatbot.ready=lambda:True;ai.ready=lambda:True;ai.chat=fake_chat

with core.conn() as db:
    cid=db.execute("""INSERT INTO companies(name,member,status,contact,login_id,pw_hash,biz_no,owner_name,phone,notify_email,industry,created,email_verified,biz_status,plan,plan_since,setup,ai_reply)
      VALUES('소보루 견본상점',1,'active','02-000-0000','tour@example.com',?,'0000000000','김대표','','','패션·잡화',?,1,'01','pilot',?,'{"company":"done","shop":"done","center":"done","policy":"done","connect":"done","ai":"done","widget":"done","test":"done"}',?)""",
      (generate_password_hash('tourpassword1'),core.iso(),core.iso(),core.iso(core.now()-datetime.timedelta(days=12)))).lastrowid
    co=core.company(db,cid);dm=demo.create(db,co)
    for t in ('orders','products','rules'):db.execute(f'UPDATE {t} SET company_id=? WHERE company_id=?',(cid,dm['id']))
    # 견본 요청은 지우고 영상용 상담을 새로 넣는다
    for r in db.execute('SELECT id FROM cases WHERE company_id=?',(dm['id'],)).fetchall():db.execute('DELETE FROM events WHERE case_id=?',(r['id'],))
    db.execute('DELETE FROM cases WHERE company_id=?',(dm['id'],))
    db.execute('DELETE FROM ai_profile WHERE company_id=?',(dm['id'],));db.execute('DELETE FROM companies WHERE id=?',(dm['id'],))
    chatbot.save_profile(db,cid,dict(demo.PROFILE,brand='매일 입기 좋은 린넨·코튼 옷을 만드는 의류 브랜드예요.'))
    # 주문번호·메모에서 '데모'를 뺀다
    for o in db.execute('SELECT id,order_no FROM orders WHERE company_id=?',(cid,)).fetchall():
        db.execute("UPDATE orders SET order_no=?,memo='',address='서울시 마포구 연남로 12',channel='자사몰' WHERE id=?",('20261020-000'+o['order_no'][-4:],o['id']))
    db.execute("UPDATE orders SET status='shipped',courier='CJ대한통운',invoice='612345678900' WHERE company_id=? AND order_no='20261020-0001001'",(cid,))
    db.execute("UPDATE orders SET phone='01012345678' WHERE company_id=? AND order_no='20261020-0001001'",(cid,))
    oc={r[1] for r in db.execute('PRAGMA table_info(orders)')}
    if 'src' in oc:db.execute("UPDATE orders SET src='cafe24' WHERE company_id=?",(cid,))
    now=core.now()
    # (채널, 유형, 제목, 내용, 상품, 주문번호, 상태, 결정, 이름, 몇 분 전, AI 답, 사장님 결정 이유)
    CASES=[
     ('이메일','배송 조회','주소를 바꿀 수 있을까요?','어제 주문했는데 배송지를 회사 주소로 바꾸고 싶어요.','와이드 데님 팬츠 (L)','20261020-0001008','answered','auto','오세린',300,
      '아직 출고 전이라 배송지를 바꿀 수 있어요. 바꾸실 주소를 이 메일에 답장으로 남겨 주시면 바로 반영해 드릴게요.',''),
     ('이메일','제품 불량','받자마자 단추가 떨어져 있었어요','포장을 열어 보니 두 번째 단추가 떨어져 있었어요. 사진 첨부합니다.','옥스퍼드 셔츠 (블루, L)','20261020-0001004','seen','pending','최지우',240,
      '불편을 드려 정말 죄송해요. 보내 주신 사진은 담당자가 확인하고 새 상품 교환으로 바로 안내해 드릴게요.','불량 확인이 필요해요. AI가 먼저 사과하고 안내했어요. 교환할지 정해 주세요'),
     ('인스타그램 DM','기타','린넨 셔츠 세탁기 돼요?','린넨 셔츠 세탁기로 빨아도 되나요?','리넨 셔츠 (아이보리, M)','','answered','auto','한유진',190,
      '린넨 100%라 찬물 손세탁이나 세탁망에 넣어 울 코스로 빨아 주세요. 건조기는 줄어들 수 있어 피해 주세요.',''),
     ('인스타그램 DM','교환','사이즈 교환 가능할까요?','어제 받았는데 M이 커요. S로 교환 가능할까요? 택은 그대로 있어요.','와이드 데님 팬츠 (M)','20261020-0001002','seen','pending','이도윤',150,
      '받으신 날부터 7일 안에 교환할 수 있어요. 택을 떼지 않은 상태로 보내 주시면 확인 후 S 사이즈로 바로 보내 드려요.','고객이 교환을 원해요. AI가 조건과 방법은 안내했어요. 처리할지 정해 주세요'),
     ('한큐','기타','선물 포장 되나요?','친구 생일 선물인데 포장해서 보내 주실 수 있나요?','','','answered','auto','정민재',110,
      '네, 주문 메모에 "선물 포장"이라고 남겨 주시면 무료로 포장해서 보내 드려요.',''),
     ('카페24','반품·환불','단순 변심으로 반품하고 싶어요','색이 화면과 달라서 반품하고 싶어요. 받은 지 3일 됐어요.','니트 가디건 (베이지)','20261020-0001003','seen','pending','박서준',70,
      '받은 날부터 7일 안이라 반품할 수 있어요. 단순 변심은 왕복 배송비 6,000원이 들고, 상품이 도착하면 확인 후 환불해 드려요.','고객이 반품·환불을 원해요. AI가 조건과 방법은 안내했어요. 환불할지 정해 주세요'),
     ('카페24','배송 조회','주문한 셔츠 언제 오나요?','월요일에 주문한 리넨 셔츠 언제 받을 수 있을까요? 주문번호 20261020-0001001이에요.','리넨 셔츠 (아이보리, M)','20261020-0001001','answered','auto','김하늘',12,
      '김하늘 고객님, 주문하신 리넨 셔츠(아이보리, M)는 어제 CJ대한통운으로 출고됐어요. 내일(목) 도착 예정이에요. 배송 조회 링크도 함께 남겨 드릴게요.',''),
    ]
    for ch,cat,title,body,prod,ono,status,dec,name,mins,ans,why in CASES:
        made=now-datetime.timedelta(minutes=mins);ai_at=made+datetime.timedelta(seconds=40)
        c=db.execute('''INSERT INTO cases(no,company_id,company_name,member,category,title,body,want,order_no,name,phone,email,lookup_hash,consent,status,decision,due,created,updated,product,received_on,channel,ai_why)
            VALUES(?,?,?,1,?,?,?,?,?,?,'','',?,1,?,?,?,?,?,?,?,?,?)''',
            (core.new_case_no(db),cid,co['name'],cat,title,body,'',ono,name,generate_password_hash(secrets.token_hex(8)),status,dec,
             core.iso(made+datetime.timedelta(days=core.REPLY_DAYS)),core.iso(made),core.iso(ai_at),prod,'',ch,why)).lastrowid
        db.execute("INSERT INTO events(case_id,kind,text,reply,created,actor) VALUES(?,'co','AI가 자동으로 답했어요',?,?,'')",(c,ans,core.iso(ai_at)))
    # 카페24 연결 (가짜 토큰, 밖으로 나가지 않는다)
    import cafe24, shops
    db.execute("INSERT INTO cafe24_links(company_id,mall_id,creds,shop_name,scopes,expires,refresh_expires,synced,n_ord,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (cid,'soborushop',shops.seal({'access_token':'x','refresh_token':'y'}),'소보루 견본몰',cafe24.SCOPES,'2099-01-01 00:00:00','2099-01-14 00:00:00',core.iso(),2,core.iso()))
    lc={r[1] for r in db.execute('PRAGMA table_info(cafe24_links)')}
    if 'boards' in lc:db.execute("UPDATE cafe24_links SET boards=?,n_inq=3 WHERE company_id=?",('[[6,"상품 Q&A"],[9,"1:1 맞춤상담"]]',cid))
# 카페24 등으로 실제로 보내지 않는다
core.deliver_reply=lambda db,c,text:('',"ok")
print('company',cid,flush=True)
from werkzeug.serving import run_simple
run_simple('127.0.0.1',int(os.getenv('VIDEO_PORT') or 8823),hanq.app,use_reloader=False,threaded=True)
