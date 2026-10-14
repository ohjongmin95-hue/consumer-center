"""직원 계정·역할·담당자 배정·내부 메모 (Gorgias의 Users·Teams·Assignment·Internal notes에 해당).

  · 대표(owner): 가입할 때 만든 회사 로그인. 지울 수 없고 모든 권한.
  · 관리자(admin): 대표와 같은 권한 (자동 처리·설정·연동·직원 관리 포함).
  · 상담원(agent): 요청 답변·자료 요청·보류·메모·배정. 승인·보상·환불 완료처럼 돈이 드는 결정과 설정은 못 한다.
  · 보기 전용(viewer): 화면만 본다. 아무것도 바꾸지 못한다.
직원 수로 요금을 매기지 않는다 (Gorgias와 같음). 내부 메모는 별도 표에 두어 고객 화면·알림·앱 API로 절대 나가지 않게 한다.
"""
import re, secrets
from werkzeug.security import generate_password_hash
import core
from core import conn, clean

ROLES={'owner':'대표','admin':'관리자','agent':'상담원','viewer':'보기 전용'}
INVITE_ROLES=('admin','agent','viewer')  # 초대할 때 고를 수 있는 역할 (대표는 하나뿐)
INVITE_HOURS=72
EMAIL_RE=re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
MAX_STAFF=50  # 회사당 직원 수 안전선 (요금과 무관)

def init():
    with conn() as db:db.executescript('''
        CREATE TABLE IF NOT EXISTS staff(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,email TEXT NOT NULL,name TEXT NOT NULL,role TEXT NOT NULL,
          pw_hash TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'invited',created TEXT NOT NULL,last_login TEXT NOT NULL DEFAULT '',
          UNIQUE(email),FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL,company_id INTEGER NOT NULL,author TEXT NOT NULL,text TEXT NOT NULL,created TEXT NOT NULL,
          FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS notes_case ON notes(case_id);''')
init()

# ---------- 누가 로그인했나 ----------
def owner_actor(co):return {'key':'owner','id':0,'name':(co['owner_name'] or '대표')+' (대표)','short':co['owner_name'] or '대표','role':'owner','email':co['login_id']}
def staff_actor(s):return {'key':str(s['id']),'id':s['id'],'name':s['name'],'short':s['name'],'role':s['role'],'email':s['email']}
def can(actor,what):
    """what: 'manage'(설정·연동·직원) | 'decide'(승인·보상·환불 완료) | 'work'(답변·메모·배정·보류·자료 요청)"""
    r=(actor or {}).get('role')
    if r in ('owner','admin'):return True
    if r=='agent':return what=='work'
    return False

def staff(db,cid):return db.execute("SELECT * FROM staff WHERE company_id=? AND status!='removed' ORDER BY id",(cid,)).fetchall()
def member(db,cid,sid):return db.execute("SELECT * FROM staff WHERE id=? AND company_id=? AND status!='removed'",(sid,cid)).fetchone()
def find_login(db,email):
    """로그인 이메일 -> 직원 (초대를 받고 비밀번호를 정한 사람만)."""
    return db.execute("SELECT * FROM staff WHERE lower(email)=lower(?) AND status='active'",(email,)).fetchone()

def people(db,co):
    """배정할 수 있는 사람 [(key,이름)]: 대표 + 활성 직원 (보기 전용 제외)."""
    out=[('owner',owner_actor(co)['name'])]
    out+=[(str(s['id']),s['name']) for s in staff(db,co['id']) if s['status']=='active' and s['role']!='viewer']
    return out
def assignee_name(db,co,key):
    if not key:return ''
    if key=='owner':return owner_actor(co)['name']
    s=member(db,co['id'],int(key)) if key.isdigit() else None
    return s['name'] if s else ''

# ---------- 초대 ----------
def email_taken(db,email):
    return bool(db.execute('SELECT 1 FROM companies WHERE lower(login_id)=lower(?)',(email,)).fetchone() or
                db.execute("SELECT 1 FROM staff WHERE lower(email)=lower(?) AND status!='removed'",(email,)).fetchone())
def invite_link(s):
    return core.site_url('biz','/join/'+core.signer('join').dumps({'id':s['id'],'h':(s['pw_hash'] or 'new')[-12:]}))
def invite(db,co,f):
    """직원 초대. (안내 문구, 'ok'|'error', 초대 링크 또는 '')"""
    email=clean(f.get('email'),80).lower();name=clean(f.get('name'),30);role=f.get('role','agent')
    if not EMAIL_RE.match(email):return '직원 이메일을 정확히 적어 주세요','error',''
    if not name:return '직원 이름을 적어 주세요','error',''
    if role not in INVITE_ROLES:return '역할을 골라 주세요','error',''
    if email_taken(db,email):return '이미 쓰고 있는 이메일이에요','error',''
    if len(staff(db,co['id']))>=MAX_STAFF:return f'직원은 {MAX_STAFF}명까지 등록할 수 있어요','error',''
    db.execute("DELETE FROM staff WHERE lower(email)=lower(?) AND status='removed'",(email,))  # 예전에 지운 같은 이메일은 새로 초대
    sid=db.execute("INSERT INTO staff(company_id,email,name,role,status,created) VALUES(?,?,?,?,'invited',?)",(co['id'],email,name,role,core.iso())).lastrowid
    s=member(db,co['id'],sid);link=invite_link(s)
    core.send_mail(email,f"[{core.BNAME}] {co['name']}에서 초대했어요",
        f"{co['name']}에서 {name}님을 {ROLES[role]}(으)로 초대했어요.\n아래 링크에서 비밀번호를 정하면 바로 쓸 수 있어요. 링크는 {INVITE_HOURS}시간 동안 열려요.\n{link}")
    return f"{name}님을 초대했어요. 초대 메일{'을 보냈어요' if core.mail_ready() else '을 보낼 수 없어 아래 링크를 직접 전해 주세요'}.",'ok',link
def read_invite(db,tok):
    try:d=core.signer('join').loads(tok,max_age=INVITE_HOURS*3600)
    except Exception:return None
    s=db.execute("SELECT * FROM staff WHERE id=? AND status!='removed'",(d.get('id'),)).fetchone()
    if not s or (s['pw_hash'] or 'new')[-12:]!=d.get('h'):return None  # 비밀번호를 정하면 링크는 더 못 쓴다
    co=core.company(db,s['company_id'])
    return s if core.active_member(co) else None
def accept(db,s,pw):
    if len(pw or '')<10:return '비밀번호는 10자 이상으로 정해 주세요'
    db.execute("UPDATE staff SET pw_hash=?,status='active' WHERE id=?",(generate_password_hash(pw),s['id']));return ''

def update(db,co,actor,f):
    """역할 바꾸기·내보내기·초대 링크 다시 만들기. (문구, 'ok'|'error', 링크)"""
    sid=f.get('id','');s=member(db,co['id'],int(sid)) if str(sid).isdigit() else None
    if not s:return '직원을 찾을 수 없어요','error',''
    act=f.get('act')
    if act=='role':
        role=f.get('role')
        if role not in INVITE_ROLES:return '역할을 골라 주세요','error',''
        db.execute('UPDATE staff SET role=? WHERE id=?',(role,s['id']))
        if role=='viewer':db.execute("UPDATE cases SET assignee='' WHERE company_id=? AND assignee=?",(co['id'],str(s['id'])))
        return f"{s['name']}님 역할을 {ROLES[role]}(으)로 바꿨어요",'ok',''
    if act=='remove':
        if actor['key']==str(s['id']):return '자기 자신은 내보낼 수 없어요','error',''
        # 다시 초대할 수 있게 이메일은 남기되 로그인은 막는다. 맡던 요청은 담당자 없음으로.
        db.execute("UPDATE staff SET status='removed',pw_hash='' WHERE id=?",(s['id'],))
        db.execute("UPDATE cases SET assignee='' WHERE company_id=? AND assignee=?",(co['id'],str(s['id'])))
        return f"{s['name']}님을 내보냈어요. 맡던 요청은 담당자 없음으로 바꿨어요",'ok',''
    if act=='relink':
        if s['status']=='active':db.execute("UPDATE staff SET pw_hash=? WHERE id=?",(generate_password_hash(secrets.token_hex(16)),s['id']));s=member(db,co['id'],s['id'])
        return f"{s['name']}님이 새 비밀번호를 정할 링크예요. {INVITE_HOURS}시간 동안 열려요.",'ok',invite_link(s)
    return '','error',''

# ---------- 배정 ----------
def assign(db,co,c,key):
    """담당자 바꾸기. key: 'owner' | 직원 id | ''(담당자 없음). 바뀌었으면 새 담당자 이름(없음이면 ''), 아니면 None."""
    key=str(key or '')
    if key and key not in dict(people(db,co)):return None
    if key==(c['assignee'] or ''):return None
    db.execute('UPDATE cases SET assignee=? WHERE id=?',(key,c['id']))
    name=assignee_name(db,co,key)
    # 배정은 회사 안의 일이라 고객이 보는 진행 기록이 아니라 내부 메모에 남긴다
    who=(getattr(core.g,'actor','') or '시스템') if core.has_request_context() else '시스템'
    db.execute('INSERT INTO notes(case_id,company_id,author,text,created) VALUES(?,?,?,?,?)',(c['id'],co['id'],who,f'담당자를 {name}(으)로 정했어요' if name else '담당자를 비웠어요',core.iso()))
    if key and key!='owner':
        s=member(db,co['id'],int(key))
        core.send_mail(s['email'],f"[{core.BNAME}] 맡은 요청: {c['title'][:30]}",f"{name}님이 맡은 요청이 생겼어요.\n{core.site_url('biz','/case/%d'%c['id'])}")
    return name

# ---------- 내부 메모 ----------
def notes(db,case_id):return db.execute('SELECT * FROM notes WHERE case_id=? ORDER BY id',(case_id,)).fetchall()
def add_note(db,co,c,actor,text):
    text=clean(text,2000)
    if not text:return False
    db.execute('INSERT INTO notes(case_id,company_id,author,text,created) VALUES(?,?,?,?,?)',(c['id'],co['id'],actor['short'],text,core.iso()))
    # 메모에 @이름 이 있으면 그 직원에게 알림 메일
    for s in staff(db,co['id']):
        if s['status']=='active' and '@'+s['name'] in text and str(s['id'])!=actor['key']:
            core.send_mail(s['email'],f"[{core.BNAME}] {actor['short']}님이 메모에서 불렀어요",f"{text}\n\n{core.site_url('biz','/case/%d'%c['id'])}")
    return True
