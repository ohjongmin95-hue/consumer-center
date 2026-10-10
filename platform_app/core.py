"""SOBORU 플랫폼 공통: DB, 처리 규칙(플레이북), 사건 처리 동작, 보안 도우미.

소비자용(한큐 민원)과 기업용(SOBORU Business)이 같은 DB의 같은 사건을 다룬다.
홈페이지(소비자제보센터, 저장소 최상위 app.py)와는 DB도 서비스도 따로 쓴다.
"""
import os, re, sqlite3, secrets, hashlib, hmac, datetime, contextlib, smtplib, threading
from pathlib import Path
from email.message import EmailMessage
from flask import session, request, abort, g
from markupsafe import Markup, escape

BASE=Path(__file__).parent
DB=Path(os.getenv('PLATFORM_DATABASE_PATH',str(BASE/'platform.sqlite3')))
UPLOAD=Path(os.getenv('PLATFORM_UPLOAD_DIR',str(BASE/'private_uploads')))
UPLOAD.mkdir(parents=True,exist_ok=True)
SECRET=os.getenv('SECRET_KEY') or secrets.token_hex(32)
CONSUMER_HOST=os.getenv('CONSUMER_HOST','').strip().lower()
BUSINESS_HOST=os.getenv('BUSINESS_HOST','').strip().lower()
PILOT=os.getenv('PLATFORM_MODE','pilot')!='live'  # 시범 운영: 화면 위에 '실제 개인정보 넣지 마세요' 띠
MAIL_ASYNC=True  # 테스트에서는 False

CATS=['배송 조회','교환','반품·환불','제품 불량','고객 응대','기타']
WANTS=['교환','환불','배송 확인','사과·재발 방지','수리·A/S','기타']
# 유형별 추천 조치. 승인(또는 자동 처리)하면 steps를 차례로 기록하고 reply를 소비자에게 보낸다.
# 기업은 자동 처리 규칙 화면에서 reply 문구를 자기 회사 말로 바꿀 수 있다.
PLAYBOOK={
  '배송 조회':{'title':'송장 조회 후 배송 현황 안내','steps':['송장 조회','배송 현황 답변','도착 알림 예약'],'reply':'주문하신 상품의 배송 현황을 확인했습니다. 현재 배송 중이며 1~2일 안에 도착 예정입니다. 도착하면 다시 알려드릴게요.','auto_ok':True},
  '교환':{'title':'교환 접수 + 회수 요청','steps':['교환 접수','회수 요청','새 상품 발송'],'reply':'교환 접수가 완료되었습니다. 택배 기사님이 1~3일 안에 기존 상품을 회수하러 방문하고, 회수가 확인되면 새 상품을 바로 보내드립니다.','auto_ok':True},
  '반품·환불':{'title':'반품 회수 후 환불','steps':['반품 접수','회수 요청','결제 취소'],'reply':'반품 접수가 완료되었습니다. 상품 회수가 확인되면 결제하신 수단으로 환불해 드립니다. 카드 결제는 영업일 기준 3~5일 걸릴 수 있어요.','auto_ok':True},
  '제품 불량':{'title':'무상 교환 (배송비 업체 부담)','steps':['불량 확인','무상 교환 접수','새 상품 발송'],'reply':'불편을 드려 죄송합니다. 보내주신 내용으로 불량을 확인했고, 배송비 없이 새 상품으로 교환해 드리겠습니다. 회수 기사님이 1~3일 안에 방문합니다.','auto_ok':False},
  '고객 응대':{'title':'사과 답변 + 담당자 연락','steps':['사과 답변','담당자 배정','직접 연락'],'reply':'응대 과정에서 불쾌하셨던 점 진심으로 사과드립니다. 담당자가 직접 연락드려 자세히 듣고 바로잡겠습니다.','auto_ok':False},
  '기타':{'title':'담당자 직접 답변','steps':['담당자 배정','직접 답변'],'reply':'','auto_ok':False},
}
STEPS=['접수','기업 전달','기업 확인','답변·조치','결과 확인']
STATUS={'received':('접수됨','gray',0),'forwarded':('기업 전달','acc',1),'seen':('기업 확인 중','wait',2),'info':('추가 자료 요청','wait',2),
        'answered':('답변·조치 완료','done',3),'resolved':('해결','done',4),'unresolved':('미해결','bad',4)}
OPEN_STATUSES=('received','forwarded','seen','info')
DECISION={'pending':'승인 대기','approved':'승인됨','auto':'자동 처리','hold':'보류','info':'추가 확인','direct':'직접 답변'}
REPLY_DAYS=2  # 입점 기업 답변 목표일 (전달 후 n일)
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
    STEPS=STEPS,CATS=CATS,WANTS=WANTS,PLAYBOOK=PLAYBOOK,DECISION=DECISION,PILOT=PILOT,mask_phone=mask_phone,fmt_phone=fmt_phone)

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
    return {'auto':bool(r and r['auto']),'reply':(r['reply'] if r and r['reply'] is not None else pb['reply'])}

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
    if reply:add_event(db,c['id'],'co','답변을 보냈어요.',reply)
    db.execute('UPDATE cases SET status=?,decision=?,info_ask=? WHERE id=?',('answered' if reply else 'seen',how,'',c['id']))
    return bool(reply)

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
