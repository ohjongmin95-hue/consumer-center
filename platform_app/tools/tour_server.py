"""제품 둘러보기 그림을 찍기 위한 개발용 서버 (실제 서버에서 쓰지 않는다).

임시 DB에 견본 회사(인증 완료) 하나를 만들고 데모 데이터를 채워 127.0.0.1:8811에 띄운다.
  python tools/tour_server.py  &  node tools/tour_shots.js
"""
import os, sys, tempfile
from pathlib import Path
from werkzeug.security import generate_password_hash
d=tempfile.mkdtemp()
os.environ.update(PLATFORM_DATABASE_PATH=d+'/p.sqlite3',PLATFORM_UPLOAD_DIR=d+'/up',SECRET_KEY='tour-shots-only-'+os.urandom(8).hex(),
                  OPS_PASSWORD_HASH=generate_password_hash(os.getenv('TOUR_OPS_PW') or os.urandom(8).hex()),CONSUMER_HOST='',BUSINESS_HOST='',PLATFORM_MODE='pilot')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hanq, core, demo, chatbot
core.throttled=lambda *a,**k:False
with core.conn() as db:
    cid=db.execute("""INSERT INTO companies(name,member,status,contact,login_id,pw_hash,biz_no,owner_name,phone,notify_email,industry,created,email_verified,biz_status,plan,plan_since,setup)
      VALUES('소보루 견본상점',1,'active','02-000-0000','tour@example.com',?,'0000000000','김대표','','','패션·잡화',?,1,'01','pilot',?,'{"company":"done","shop":"done","center":"done","policy":"done","connect":"done","ai":"done","widget":"done","test":"done"}')""",
      (generate_password_hash('tourpassword1'),core.iso(),core.iso())).lastrowid
    co=core.company(db,cid);dm=demo.create(db,co)
    # 견본 데이터를 견본 회사로 옮겨 데모 표시 없이 찍는다 (이 임시 DB에서만)
    for t in ('orders','products','rules'):db.execute(f'UPDATE {t} SET company_id=? WHERE company_id=?',(cid,dm['id']))
    db.execute("UPDATE cases SET company_id=?,company_name=?,channel=CASE id%3 WHEN 0 THEN '스마트스토어' WHEN 1 THEN '쿠팡' ELSE '한큐' END WHERE company_id=?",(cid,co['name'],dm['id']))
    db.execute('DELETE FROM ai_profile WHERE company_id=?',(dm['id'],));db.execute('DELETE FROM companies WHERE id=?',(dm['id'],))
    chatbot.save_profile(db,cid,demo.PROFILE)
    # 상담창 주문 조회 화면 (견본 주문 하나에 견본 휴대폰 번호)
    db.execute("UPDATE orders SET phone='01012345678' WHERE id=(SELECT MIN(id) FROM orders WHERE company_id=? AND status='shipped')",(cid,))
    # 카페24 연결 화면·카페24 주문 화면 (가짜 토큰, 밖으로 나가지 않는다)
    import cafe24, shops
    db.execute("INSERT INTO cafe24_links(company_id,mall_id,creds,shop_name,scopes,expires,refresh_expires,synced,n_ord,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (cid,'soborushop',shops.seal({'access_token':'x','refresh_token':'y'}),'소보루 견본몰',cafe24.SCOPES,'2099-01-01 00:00:00','2099-01-14 00:00:00',core.iso(),2,core.iso()))
    oc={r[1] for r in db.execute('PRAGMA table_info(orders)')}
    if 'src' in oc:db.execute("UPDATE orders SET src='cafe24',channel='자사몰' WHERE id=(SELECT MIN(id) FROM orders WHERE company_id=? AND status IN ('paid','ready'))",(cid,))
    lc={r[1] for r in db.execute('PRAGMA table_info(cafe24_links)')}
    if 'boards' in lc:db.execute("UPDATE cafe24_links SET boards=?,n_inq=3 WHERE company_id=?",('[[6,"상품 Q&A"],[9,"1:1 맞춤상담"]]',cid))
print('company',cid,flush=True)
from werkzeug.serving import run_simple
run_simple('127.0.0.1',8811,hanq.app,use_reloader=False,threaded=True)
