"""바로 가입·무료 시범 이용·처음 설정 도우미 (Gorgias의 셀프 가입·무료 체험·온보딩에 해당).

가입하면 운영자 승인 없이 곧바로 회사 작업 공간이 생기고 로그인된다.
다만 "사업자번호가 진짜인가"와 "이 사람이 그 회사 사람인가"는 따로 본다.
  · 바로 할 수 있는 것: 설정, 데모 체험, 직접 등록, AI 상담 설정, 직원 초대
  · 회사 인증(member=1)이 끝나야 하는 것: 소비자 접수가 우리 회사로 들어오기, 판매처 연결(실제 고객 데이터)
  회사 인증 = 로그인 이메일 확인 + 국세청 사업자 상태가 '계속사업자'. 국세청 키가 없거나 확인이 안 되면 운영자가 확인해 인증한다.
요금·결제는 아직 없다. 모든 회사는 '무료 시범' 요금제로 시작하고, 나중에 PLANS에 요금제를 더하면 된다.
"""
import json, logging, os, urllib.parse, urllib.request, urllib.error
import core
from core import conn, clean, digits

LOG=logging.getLogger(__name__)
PLANS={'pilot':{'name':'무료 시범','limit':None},'trial':{'name':'무료 체험','limit':None},'paid':{'name':'유료','limit':None},'free':{'name':'무료 제공','limit':None}}  # 'paid': 포트원 정기결제 중 (billing.py, 요금제 이름·금액은 운영 화면에서)
VERIFY_HOURS=48

def init():
    with conn() as db:
        cols={r[1] for r in db.execute('PRAGMA table_info(companies)')}
        for col,kind in (('email_verified',"INTEGER NOT NULL DEFAULT 0"),('biz_status',"TEXT NOT NULL DEFAULT ''"),('biz_checked',"TEXT NOT NULL DEFAULT ''"),
                         ('plan',"TEXT NOT NULL DEFAULT 'pilot'"),('plan_since',"TEXT NOT NULL DEFAULT ''"),('setup',"TEXT NOT NULL DEFAULT '{}'"),
                         ('shop_types',"TEXT NOT NULL DEFAULT ''"),('signup_via',"TEXT NOT NULL DEFAULT ''"),('google_sub',"TEXT NOT NULL DEFAULT ''"),
                         ('demo_of',"INTEGER NOT NULL DEFAULT 0"),('susp_member',"INTEGER NOT NULL DEFAULT 1")):  # susp_member: 중지 전 인증 여부 (예전 중지 회사는 인증 회사였다)
            if col not in cols:db.execute(f'ALTER TABLE companies ADD COLUMN {col} {kind}')
        # 예전 방식으로 가입해 운영자가 승인한 회사는 이미 확인된 회사로 본다
        if 'email_verified' not in cols:db.execute("UPDATE companies SET email_verified=1 WHERE status='active' AND member=1")
        # 예전 '가입 신청 후 승인 대기' 회사도 바로 쓸 수 있게 한다 (인증 전 상태로: 소비자 접수·판매처 연결은 운영자 인증 뒤)
        db.execute("UPDATE companies SET status='active',member=0 WHERE status='pending' AND login_id IS NOT NULL")
init()

# 운영 화면 '기업 관리'에서 확인을 기다리는 회사: 예전 가입 신청 + 바로 가입했지만 아직 인증 전인 회사
WAITING_SQL="(status='pending' OR (status='active' AND member=0 AND login_id IS NOT NULL AND demo_of=0))"

# ---------- 사업자등록번호 ----------
def bizno_ok(n):
    """사업자등록번호 10자리 검증번호 계산 (국세청 공개 규칙). 형식만 보고, 실제 등록 여부는 nts_status로 본다."""
    d=[int(x) for x in digits(n)]
    if len(d)!=10:return False
    w=[1,3,7,1,3,7,1,3,5];s=sum(a*b for a,b in zip(d,w))+(d[8]*5)//10
    return (10-s%10)%10==d[9]
BIZ_STATUS={'01':'계속사업자','02':'휴업자','03':'폐업자','none':'국세청에 없는 번호','':'확인 전'}
def nts_ready():return bool(core.secret('NTS_API_KEY'))
def nts_post(url,body):
    """(상태 코드, JSON). 테스트에서 바꿔 끼운다."""
    req=urllib.request.Request(url,data=json.dumps(body).encode(),method='POST',headers={'Content-Type':'application/json','Accept':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=8) as r:return r.status,json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:return e.code,{}
def nts_status(n):
    """국세청 사업자등록 상태조회 (공공데이터포털 '국세청_사업자등록정보 진위확인 및 상태조회 서비스').
    -> '01'|'02'|'03'|'none'(등록 안 됨) 또는 ''(키 없음·연결 실패: 운영자 확인으로 넘김)"""
    if not nts_ready():return ''
    url='https://api.odcloud.kr/api/nts-businessman/v1/status?'+urllib.parse.urlencode({'serviceKey':core.secret('NTS_API_KEY')})
    try:code,res=nts_post(url,{'b_no':[digits(n)]})
    except Exception as e:LOG.warning('국세청 조회 실패: %s',type(e).__name__);return ''
    if code!=200:LOG.warning('국세청 조회 응답 %s',code);return ''
    row=(res.get('data') or [{}])[0]
    cd=(row.get('b_stt_cd') or '').strip()
    if cd in ('01','02','03'):return cd
    return 'none' if '등록되지 않은' in (row.get('tax_type') or '') else ''

# ---------- 가입 ----------
def signup(db,d,pw_hash,via='email',google_sub=''):
    """회사 작업 공간을 만든다. d: 검사를 마친 가입 정보. (회사 id, 오류 문구)"""
    import team
    if team.email_taken(db,d['login_id']):return None,'이미 가입된 이메일이에요. 로그인해 주세요.'
    b=digits(d['biz_no'])
    if db.execute("SELECT 1 FROM companies WHERE biz_no=? AND status IN ('active','pending','suspended') AND demo_of=0",(b,)).fetchone():
        return None,'이미 가입된 사업자번호예요. 그 회사 대표에게 팀 화면에서 직원으로 초대해 달라고 해 주세요.'
    st=nts_status(b)
    if st=='03':return None,'국세청에 폐업으로 나오는 사업자번호예요. 번호를 확인해 주세요.'
    if st=='none':return None,'국세청에 등록되지 않은 사업자번호예요. 번호를 확인해 주세요.'
    t=core.iso()
    cid=db.execute("""INSERT INTO companies(name,member,status,contact,login_id,pw_hash,biz_no,owner_name,phone,notify_email,industry,created,
        email_verified,biz_status,biz_checked,plan,plan_since,signup_via,google_sub,ai_reply) VALUES(?,0,'active',?,?,?,?,?,?,?,?,?,?,?,?,'pilot',?,?,?,?)""",
        (d['name'],d.get('contact',''),d['login_id'].lower(),pw_hash,b,d['owner_name'],digits(d.get('phone','')),d['login_id'].lower(),d.get('industry',''),t,
         1 if via=='google' else 0,st,t if st else '',t,via,google_sub,t)).lastrowid  # ai_reply: AI 자동 답변은 처음부터 켬 (운영자 결정 2026-10-18)
    import growth;growth.attach(db,cid)  # 추천 링크로 들어왔으면 이어 붙인다
    co=core.company(db,cid)
    if via!='google':send_verify(co)
    core.send_mail(os.getenv('OPS_EMAIL',''),f"[{core.BNAME} 운영] 새 가입: {d['name']}",
        f"{d['name']} ({d['owner_name']})이 가입했어요. 사업자 상태: {BIZ_STATUS.get(st,st)}\n{core.site_url('biz','/ops/companies')}")
    maybe_verify(db,core.company(db,cid))
    return cid,''

def verify_link(co):return core.site_url('biz','/verify/'+core.signer('verify').dumps({'id':co['id'],'e':co['login_id']}))
def send_verify(co):
    core.send_mail(co['login_id'],f'[{core.BNAME}] 이메일을 확인해 주세요',
        f"{co['name']} 가입을 환영해요.\n아래 링크를 누르면 이메일 확인이 끝나요. {VERIFY_HOURS}시간 동안 열려요.\n{verify_link(co)}")
def check_verify(db,tok):
    try:d=core.signer('verify').loads(tok,max_age=VERIFY_HOURS*3600)
    except Exception:return None
    co=core.company(db,d.get('id'))
    if not co or co['login_id']!=d.get('e') or co['status']!='active':return None
    db.execute('UPDATE companies SET email_verified=1 WHERE id=?',(co['id'],))
    return maybe_verify(db,core.company(db,co['id']))

def make_member(db,co):
    """회사 인증 끝: 소비자 접수가 이 회사로 들어온다. 같은 이름의 비입점 기업에 쌓인 요청은 이 회사로 옮긴다 (예전 운영자 승인과 같음)."""
    old=db.execute("SELECT id FROM companies WHERE status='listed' AND lower(name)=lower(?)",(co['name'],)).fetchall()
    for o in old:db.execute('UPDATE cases SET company_id=? WHERE company_id=?',(co['id'],o['id']));db.execute('DELETE FROM companies WHERE id=?',(o['id'],))
    db.execute("UPDATE companies SET status='active',member=1,email_verified=1 WHERE id=?",(co['id'],))
    core.send_mail(co['notify_email'],f'[{core.BNAME}] 회사 인증이 끝났어요',f"{co['name']} 인증이 끝났어요. 이제 소비자 접수가 바로 들어오고 판매처를 연결할 수 있어요.\n{core.site_url('biz','/')}")
def maybe_verify(db,co):
    """이메일 확인 + 국세청 계속사업자면 자동 인증. 회사를 돌려준다."""
    if co and not co['member'] and co['status']=='active' and co['email_verified'] and co['biz_status']=='01':make_member(db,co)
    return core.company(db,co['id']) if co else None
def recheck_biz(db,co):
    st=nts_status(co['biz_no'])
    if st:db.execute('UPDATE companies SET biz_status=?,biz_checked=? WHERE id=?',(st,core.iso(),co['id']))
    return maybe_verify(db,core.company(db,co['id']))
def trust(co):
    """회사 인증 상태를 사장님께 보여 줄 말. -> {'ok':bool,'email':bool,'biz':str,'todo':[...]}"""
    todo=[]
    if not co['email_verified']:todo.append('로그인 이메일 확인')
    if co['biz_status']!='01':todo.append('사업자 상태 확인' if not nts_ready() or not co['biz_status'] else f"사업자 상태 확인 (국세청: {BIZ_STATUS.get(co['biz_status'],co['biz_status'])})")
    return {'ok':bool(co['member']),'email':bool(co['email_verified']),'biz':BIZ_STATUS.get(co['biz_status'],co['biz_status']),'todo':todo}

# ---------- 구글로 가입·로그인 ----------
def google_ready():return bool(core.secret('GOOGLE_CLIENT_ID') and core.secret('GOOGLE_CLIENT_SECRET'))
def google_redirect():return core.site_url('biz','/auth/google/callback')
def google_auth_url(state):
    return 'https://accounts.google.com/o/oauth2/v2/auth?'+urllib.parse.urlencode({'client_id':core.secret('GOOGLE_CLIENT_ID'),'redirect_uri':google_redirect(),
        'response_type':'code','scope':'openid email profile','state':state,'prompt':'select_account'})
def http_json(method,url,data=None,headers=None):
    """(상태 코드, JSON). 테스트에서 바꿔 끼운다."""
    body=urllib.parse.urlencode(data).encode() if data is not None else None
    req=urllib.request.Request(url,data=body,method=method,headers=headers or {})
    try:
        with urllib.request.urlopen(req,timeout=10) as r:return r.status,json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:return e.code,{}
def google_user(code):
    """인가 코드 -> {'sub','email','name'} (구글이 확인한 이메일만). 실패하면 None."""
    try:
        c,tok=http_json('POST','https://oauth2.googleapis.com/token',{'code':code,'client_id':core.secret('GOOGLE_CLIENT_ID'),'client_secret':core.secret('GOOGLE_CLIENT_SECRET'),
            'redirect_uri':google_redirect(),'grant_type':'authorization_code'},{'Content-Type':'application/x-www-form-urlencoded'})
        if c!=200 or not tok.get('access_token'):return None
        c,u=http_json('GET','https://openidconnect.googleapis.com/v1/userinfo',None,{'Authorization':'Bearer '+tok['access_token']})
    except Exception as e:LOG.warning('구글 로그인 실패: %s',type(e).__name__);return None
    if c!=200 or not u.get('email') or not u.get('email_verified'):return None
    return {'sub':str(u.get('sub','')),'email':u['email'].lower(),'name':clean(u.get('name'),20)}

# ---------- 처음 설정 도우미 ----------
SHOP_TYPES=['네이버 스마트스토어','쿠팡','카페24','자사몰','오픈마켓(11번가·G마켓 등)','오프라인·기타']
STEPS=[('company','기업 정보','회사 이름·업종·대표 연락처'),('shop','쇼핑몰 종류','어디서 팔고 계신가요'),('center','고객센터 정보','연락처·상담 시간·알림 받을 곳'),
       ('policy','교환·반품·환불 정책','배송·반품 규정과 반품 주소'),('connect','판매처 연결','카페24 주문·상품·문의 가져오기'),('ai','AI 상담 설정','회사 소개·AI가 답할 범위·넘길 때'),
       ('widget','고객센터 위젯 설치','쇼핑몰에 문의하기 버튼 붙이기'),('test','시험 문의 처리','시험 문의를 받아 직접 답해 보기')]
STEP_KEYS=[k for k,_,_ in STEPS]
def setup_state(co):
    try:s=json.loads(co['setup'] or '{}')
    except ValueError:s={}
    return s if isinstance(s,dict) else {}
def progress(co):
    s=setup_state(co);done=[k for k in STEP_KEYS if s.get(k) in ('done','skip')]
    nxt=next((k for k in STEP_KEYS if k not in done),None)
    return {'done':done,'n':len(done),'total':len(STEP_KEYS),'pct':round(len(done)/len(STEP_KEYS)*100),'next':nxt,'state':s,'finished':nxt is None}
def mark(db,co,step,how='done'):
    s=setup_state(co);s[step]=how
    db.execute('UPDATE companies SET setup=? WHERE id=?',(json.dumps(s,ensure_ascii=False),co['id']))
    return core.company(db,co['id'])

# ---------- 무료 시범 이용 현황 (나중에 요금을 매길 기준을 미리 센다: Gorgias 방식) ----------
def usage(db,cid,month=None):
    """이번 달(YYYY-MM) 이용: 받은 요청, 답장이 나간 요청(Gorgias의 과금 상담 기준), 자동 처리, AI 상담 질문 수."""
    m=month or core.now().strftime('%Y-%m');like=m+'%'
    q=lambda sql,*a:db.execute(sql,a).fetchone()[0]
    return {'month':m,
        'cases':q("SELECT COUNT(*) FROM cases WHERE company_id=? AND created LIKE ?",cid,like),
        'replied':q("SELECT COUNT(DISTINCT e.case_id) FROM events e JOIN cases c ON c.id=e.case_id WHERE c.company_id=? AND e.kind='co' AND e.created LIKE ?",cid,like),
        'auto':q("SELECT COUNT(*) FROM cases WHERE company_id=? AND decision='auto' AND created LIKE ?",cid,like),
        'ai_chats':q("SELECT COUNT(*) FROM chat_log WHERE company_id=? AND outcome='asked' AND created LIKE ?",cid,like)}
