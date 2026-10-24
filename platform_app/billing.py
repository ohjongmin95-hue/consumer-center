"""요금 결제 (포트원 V2 정기결제·빌링키, PG는 포트원 콘솔에서 정한 채널: KG이니시스 등).
운영자가 키(PORTONE_STORE_ID·PORTONE_CHANNEL_KEY·PORTONE_API_SECRET)와 요금제(이름·월 금액)를 넣기 전까지는 '준비 중'.

  · 사장님(대표·관리자)이 '카드 등록하고 시작'을 누르면 포트원 카드 등록 창이 뜬다 -> 빌링키를 받아 돌아오면
    포트원에 그 빌링키가 우리 고객 키로 발급된 것인지 확인한 뒤 암호화해 저장하고, 첫 달 요금을 바로 결제한다. 결제가 되면 다음 결제일은 한 달 뒤.
  · 다음 결제일이 되면 cron(10분마다, shops.py)이 하루 한 번만 결제를 시도한다. 실패하면 '결제 실패'로 두고 다음 날 다시,
    3번 연속 실패하면 멈추고 무료 시범으로 돌린다. 기능은 막지 않는다 (요금제가 정해지면 그때 정한다).
  · 해지하면 다음 결제일까지 쓰고 그날부터 결제하지 않는다. 다음 결제일 전에는 다시 이어 쓸 수 있다.
  · 포트원 시험 채널로는 실제 돈이 나가지 않는다 (채널을 실연동으로 바꾸면 실제 결제).
문서: developers.portone.io > 빌링키 결제 (POST /payments/{paymentId}/billing-key, GET·DELETE /billing-keys/{billingKey})
"""
import calendar, datetime, json, secrets, urllib.parse
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session, current_app
import core, shops
from core import conn, clean

bp=Blueprint('pay',__name__)
API='https://api.portone.io'
SDK='https://cdn.portone.io/v2/browser-sdk.js'
MAX_FAILS=3

def init():
    with conn() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS billing(company_id INTEGER PRIMARY KEY,customer_key TEXT NOT NULL UNIQUE,creds TEXT NOT NULL DEFAULT '',
          card TEXT NOT NULL DEFAULT '',plan_name TEXT NOT NULL DEFAULT '',price INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'none',
          next_charge TEXT NOT NULL DEFAULT '',last_try TEXT NOT NULL DEFAULT '',fails INTEGER NOT NULL DEFAULT 0,note TEXT NOT NULL DEFAULT '',
          started TEXT NOT NULL DEFAULT '',canceled TEXT NOT NULL DEFAULT '',FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS billing_payments(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,order_id TEXT NOT NULL UNIQUE,amount INTEGER NOT NULL,
          status TEXT NOT NULL,payment_key TEXT NOT NULL DEFAULT '',receipt TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,
          FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE)''')
init()
with conn() as _db:  # 카페24 앱 결제: source 'cafe24'면 카페24가 매달 결제하고 우리는 웹훅·조회로 상태만 맞춘다
    _cols={r[1] for r in _db.execute('PRAGMA table_info(billing)')}
    if 'source' not in _cols:_db.execute("ALTER TABLE billing ADD COLUMN source TEXT NOT NULL DEFAULT ''")
    for _c in ('tier','want_tier','warned'):  # 상담 건수 구간: 이번 기간 구간, 다음 결제부터 쓸 구간, 이번 기간에 보낸 사용량 알림
        if _c not in _cols:_db.execute(f"ALTER TABLE billing ADD COLUMN {_c} TEXT NOT NULL DEFAULT ''")
    if 'memo' not in {r[1] for r in _db.execute('PRAGMA table_info(billing_payments)')}:_db.execute("ALTER TABLE billing_payments ADD COLUMN memo TEXT NOT NULL DEFAULT ''")

def ready():return all(core.secret(k) for k in ('PORTONE_STORE_ID','PORTONE_CHANNEL_KEY','PORTONE_API_SECRET'))
# 운영자 결정 2026-10-21: 고르기아스처럼 '상담 건수' 구간으로 나누고 금액만 더 싸게 (부가세 포함). 기능은 모든 구간이 같다.
# 상담 1건 = 그 기간에 첫 답장(사장님·직원·AI)이 나간 문의 (고르기아스의 '청구 티켓'). 답장 없이 닫힌 문의, 영업시간 외 자동 안내만 나간 문의, 데모는 세지 않는다.
# 넘으면 막지 않고 다음 결제 때 추가 요금을 함께 결제한다 (over_n건마다 over_price원). 운영 화면에서 금액을 바꾸면 그 값을 쓴다.
TIERS=(dict(key='starter',name='스타터',price=14900,tickets=50,over_n=1,over_price=200),
       dict(key='basic',name='베이직',price=49000,tickets=300,over_n=100,over_price=19000),
       dict(key='pro',name='프로',price=290000,tickets=2000,over_n=100,over_price=15000),
       dict(key='advanced',name='어드밴스드',price=690000,tickets=5000,over_n=100,over_price=15000))
DEFAULT_TIER='basic'
def tiers():
    """구간 목록 (운영자가 바꾼 금액을 반영)."""
    with conn() as db:r=db.execute("SELECT value FROM settings WHERE key='billing_tiers'").fetchone()
    try:saved=json.loads(r['value']) if r else {}
    except ValueError:saved={}
    out=[]
    for t in TIERS:
        t=dict(t);v=saved.get(t['key']) if isinstance(saved,dict) else None
        for k in ('price','over_price'):
            try:
                if v and int(v.get(k) or 0)>=100:t[k]=int(v[k])
            except (TypeError,ValueError):pass
        out.append(t)
    return out
def tier(key=None):
    ts=tiers();return next((t for t in ts if t['key']==key),None) or next(t for t in ts if t['key']==DEFAULT_TIER)
def plan(key=None):
    """요금제 {key,name,price,tickets,over_n,over_price} (금액은 부가세 포함, 원). key가 없으면 기본 구간."""
    return tier(key)
def usage_of(co):
    with conn() as db:return usage(db,co)
def save_tiers(prices):
    """{key:{'price':원,'over_price':원}} 저장. 100원 미만은 버린다."""
    keep={k:{f:int(v[f]) for f in ('price','over_price') if int(v.get(f) or 0)>=100} for k,v in prices.items() if any(t['key']==k for t in TIERS)}
    with conn() as db:db.execute("INSERT INTO settings(key,value,updated) VALUES('billing_tiers',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated",
                                 (json.dumps(keep,ensure_ascii=False),core.iso()))
def over_fee(t,used):
    """구간을 넘은 상담에 붙는 추가 요금 -> (넘은 건수, 원)."""
    over=max(int(used)-t['tickets'],0)
    return over,(-(-over//t['over_n'])*t['over_price'] if over else 0)
def sub_month(d):
    y,m=(d.year-1,12) if d.month==1 else (d.year,d.month-1)
    return d.replace(year=y,month=m,day=min(d.day,calendar.monthrange(y,m)[1]))
def period(b):
    """지금 세는 기간 (시작, 끝) 날짜. 결제 중이면 지난 결제일~다음 결제일, 체험 중이면 체험 기간, 아니면 이번 달."""
    try:end=datetime.date.fromisoformat(b['next_charge']) if b and b['next_charge'] and b['status'] in ('trial','active','past_due','canceled','stopped') else None
    except ValueError:end=None
    if end and b['status']=='trial':
        try:return datetime.date.fromisoformat(b['started'][:10]),end
        except ValueError:return end-datetime.timedelta(days=TRIAL_DAYS),end
    if end:return sub_month(end),end
    t=today();start=t.replace(day=1);return start,add_month(start)
def tickets_used(db,cid,start,end):
    """기간 [start,end) 안에 첫 답장이 나간 문의 수."""
    import workflow
    return db.execute("""SELECT COUNT(*) FROM (SELECT e.case_id,MIN(e.created) t FROM events e JOIN cases c ON c.id=e.case_id
        WHERE c.company_id=? AND c.import_batch=0 AND c.channel!='데모' AND e.kind='co' AND e.reply!='' AND e.text!=? AND c.title NOT LIKE '[시험 문의]%' GROUP BY e.case_id) WHERE t>=? AND t<?""",
        (cid,workflow.AWAY_TEXT,start.isoformat(),end.isoformat())).fetchone()[0]
def usage(db,co,b=None):
    """이번 기간 쓴 상담 건수와 구간 {tier,used,start,end,pct,over,fee,next_tier}."""
    b=b if b is not None else row(db,co['id'])
    t=tier(b['tier'] if b and b['tier'] else None);start,end=period(b)
    used=tickets_used(db,co['id'],start,end);over,fee=over_fee(t,used)
    nxt=tier(b['want_tier']) if b and b['want_tier'] and b['want_tier']!=t['key'] else None
    return dict(tier=t,used=used,start=start,end=end,pct=min(100,used*100//max(t['tickets'],1)),over=over,fee=0 if b and b['status']=='trial' else fee,next_tier=nxt,
                free=bool(b and b['status']=='trial'),c24=bool(b and b['source']=='cafe24'))
TRIAL_DAYS=5  # 운영자 결정 2026-10-21: 카드를 먼저 등록하고 5일 무료, 5일째 첫 결제. 해지하지 않으면 매달 결제, 결제가 없으면 모든 기능을 멈춘다
def live():
    """요금을 받기 시작했는지: 결제할 길(포트원 키 또는 카페24 앱 결제)이 있을 때. 그 전에는 모두 무료 시범으로 쓴다."""
    return ready() or c24_on()
def open_ok(co):
    """이 회사가 소보루 CS를 쓸 수 있는지. 운영자가 요금을 정하기 전에는 모두 쓴다(무료 시범).
    정한 뒤에는 무료 체험 중('trial')이거나 결제 중('paid')인 회사만. 나머지는 요금·결제 화면만 열린다 (데이터는 지우지 않는다)."""
    if not co:return False
    return co['plan'] in ('paid','trial','free') or not live()  # 'free': 운영자가 무료로 열어 준 회사 (심사용·시범 계정)
def trial_days_left(co,b):
    if not co or co['plan']!='trial' or not b or not b['next_charge']:return None
    try:return max((datetime.date.fromisoformat(b['next_charge'])-today()).days,0)
    except ValueError:return None
def start_c24_trial(db,cid):
    """카페24 앱스토어로 설치한 쇼핑몰: 카페24 결제는 미리 카드를 받아 둘 수 없어서, 처음 연결한 날부터 5일 무료로 열고 그 안에 카페24로 결제하게 한다 (회사마다 한 번)."""
    if not plan() or not c24_on():return
    b=row(db,cid)
    if b and (b['started'] or b['status'] not in ('none','')):return
    if not b:db.execute('INSERT INTO billing(company_id,customer_key) VALUES(?,?)',(cid,'cs_'+secrets.token_urlsafe(24)))
    b=row(db,cid);p=plan(b['want_tier'] or b['tier'] or None);end=today()+datetime.timedelta(days=TRIAL_DAYS)
    db.execute("UPDATE billing SET status='trial',source='cafe24',tier=?,want_tier='',plan_name=?,price=?,started=?,next_charge=? WHERE company_id=?",(p['key'],p['name'],int(p['price']),core.iso(),end.isoformat(),cid))
    db.execute("UPDATE companies SET plan='trial',plan_since=? WHERE id=? AND plan NOT IN ('paid','free')",(core.iso(),cid))
def row(db,cid):return db.execute('SELECT * FROM billing WHERE company_id=?',(cid,)).fetchone()
def today():return core.now().date()
def mail_of(co):return co['notify_email'] or (co['login_id'] if '@' in (co['login_id'] or '') else '')
def add_month(d):
    """같은 날 다음 달 (31일 -> 다음 달 말일)."""
    y,m=(d.year+1,1) if d.month==12 else (d.year,d.month+1)
    return d.replace(year=y,month=m,day=min(d.day,calendar.monthrange(y,m)[1]))

class PayError(Exception):
    """사장님께 그대로 보여 줄 우리말 안내."""
def _call(method,path,body=None):
    """(상태, JSON). API 시크릿은 Authorization 헤더로만 보낸다."""
    h={'Authorization':'PortOne '+core.secret('PORTONE_API_SECRET'),'Content-Type':'application/json'}
    try:return shops.http(method,API+path,h,json.dumps(body).encode() if body is not None else None)
    except shops.ShopError:raise PayError('결제사에 연결하지 못했어요. 잠시 후 다시 해 주세요.')
def _msg(d,s):
    d=d or {};return clean(d.get('pgMessage') or d.get('message') or f'결제 오류 ({s})',200)
def _q(s):return urllib.parse.quote(s,safe='')
def store_q():return '?storeId='+_q(core.secret('PORTONE_STORE_ID'))
def drop_key(key):
    """더 안 쓰는 빌링키를 포트원에서 지운다 (실패해도 넘어간다: 우리 쪽에서는 이미 지웠다)."""
    try:_call('DELETE','/billing-keys/'+_q(key)+store_q())
    except PayError:pass

def charge(db,co,b,extra=(0,0)):
    """한 달 요금(+지난 기간에 구간을 넘은 상담 추가 요금 extra=(건수,원))을 결제한다. -> '' 또는 실패 이유. 결제 기록은 성공·실패 모두 남긴다."""
    c=shops.unseal(b['creds']) if b['creds'] else None
    if not c or not c.get('billing_key'):return '등록된 카드가 없어요.'
    order=f"SOBORU-{co['id']}-{core.now():%Y%m%d%H%M%S}-{secrets.token_hex(3)}"
    total=b['price']+extra[1];memo=f"{b['plan_name']} {b['price']:,}원"+(f" + 추가 상담 {extra[0]:,}건 {extra[1]:,}원" if extra[1] else '')
    db.execute("INSERT INTO billing_payments(company_id,order_id,amount,status,created,memo) VALUES(?,?,?,'try',?,?)",(co['id'],order,total,core.iso(),memo))
    cu={'id':b['customer_key'],'name':{'full':clean(co['name'],60)}}
    if mail_of(co):cu['email']=mail_of(co)
    body={'storeId':core.secret('PORTONE_STORE_ID'),'billingKey':c['billing_key'],'orderName':f"{core.BNAME} {b['plan_name']} (1개월)"+(' + 추가 상담' if extra[1] else ''),
          'customer':cu,'amount':{'total':total},'currency':'KRW'}
    try:s,d=_call('POST','/payments/'+_q(order)+'/billing-key',body)
    except PayError as e:s,d=0,{'message':str(e)}
    if s==200 and (d.get('payment') or {}).get('paidAt'):
        receipt=''
        try:  # 영수증 주소는 결제 조회에만 있다 (없어도 결제는 된 것)
            s2,p=_call('GET','/payments/'+_q(order)+store_q())
            if s2==200:receipt=clean(p.get('receiptUrl'),500)
        except PayError:pass
        db.execute("UPDATE billing_payments SET status='done',payment_key=?,receipt=? WHERE order_id=?",(clean(d['payment'].get('pgTxId'),200),receipt,order))
        return ''
    e=_msg(d,s);db.execute("UPDATE billing_payments SET status='fail',error=? WHERE order_id=?",(e,order))
    return e

def warn_usage():
    """cron: 이번 기간 상담이 구간의 80%·100%에 닿으면 한 번씩 알린다 (막지는 않는다. 넘은 만큼 다음 결제에 추가 요금)."""
    with conn() as db:
        for b in db.execute("SELECT * FROM billing WHERE status IN ('trial','active','past_due','canceled')").fetchall():
            co=core.company(db,b['company_id'])
            if not co or co['plan']=='free':continue
            u=usage(db,co,b);t=u['tier'];lv='100' if u['used']>=t['tickets'] else '80' if u['used']*10>=t['tickets']*8 else ''
            if not lv or b['warned'] in (lv,'100'):continue
            db.execute('UPDATE billing SET warned=? WHERE company_id=?',(lv,b['company_id']))
            if u['free']:body='체험 기간에는 추가 요금이 없어요.'
            elif u['c24']:body='카페24 결제는 구간 요금만 받아요. 더 많이 쓰시면 다음 달에 구간을 올려 주세요.'
            else:body=f"넘어도 그대로 쓰실 수 있고, {t['over_n']:,}건마다 {t['over_price']:,}원이 다음 결제에 더해져요. 많이 쓰시면 구간을 올리는 게 더 싸요."
            core.alert(co,'plan',f"이번 기간 상담 {u['used']:,}건, {t['name']} 구간 {t['tickets']:,}건 중 {'다 썼어요' if lv=='100' else '80%를 넘었어요'}",body,path='/billing',db=db)

def charge_due(db,co,b):
    """결제일 결제: 고른 구간의 한 달 요금 + 지난 기간에 구간을 넘은 상담 추가 요금 (체험 기간은 빼고).
    운영자가 바꾼 금액·사장님이 바꾼 구간은 여기서부터. 결제가 되어야 구간을 바꿔 적는다 (실패해 다시 시도해도 같은 금액)."""
    extra=(0,0) if b['status']=='trial' else over_fee(tier(b['tier'] or None),tickets_used(db,co['id'],*period(b)))
    p=plan(b['want_tier'] or b['tier'] or None)
    nb=dict(b);nb.update(plan_name=p['name'],price=int(p['price']))
    e=charge(db,co,nb,extra)
    if not e:db.execute("UPDATE billing SET tier=?,want_tier='',plan_name=?,price=? WHERE company_id=?",(p['key'],p['name'],int(p['price']),co['id']))
    return e

def paid(db,cid,start):
    db.execute("UPDATE billing SET status='active',fails=0,note='',warned='',next_charge=? WHERE company_id=?",(add_month(start).isoformat(),cid))
    db.execute("UPDATE companies SET plan='paid',plan_since=CASE plan WHEN 'paid' THEN plan_since ELSE ? END WHERE id=?",(core.iso(),cid))

def renew_all():
    """cron: 결제일이 된 회사를 하루 한 번만 결제. 해지한 회사는 결제일에 무료 시범으로 돌린다."""
    n=0;t=today().isoformat()
    c24_expire();warn_usage()
    with conn() as db:due=db.execute("SELECT * FROM billing WHERE status IN ('trial','active','past_due','canceled') AND source!='cafe24' AND next_charge!='' AND next_charge<=?",(t,)).fetchall()
    for b in due:
        with conn() as db:
            if b['status']=='canceled':
                c=shops.unseal(b['creds']) if b['creds'] else None
                if c and c.get('billing_key'):drop_key(c['billing_key'])
                db.execute("UPDATE billing SET status='ended',creds='' WHERE company_id=?",(b['company_id'],))
                db.execute("UPDATE companies SET plan='pilot',plan_since=? WHERE id=? AND plan!='free'",(core.iso(),b['company_id']));continue
            # 10분마다 도는 cron이 같은 날 두 번 결제하지 않게 먼저 '오늘 시도함'을 잡는다
            if not db.execute('UPDATE billing SET last_try=? WHERE company_id=? AND last_try<?',(t,b['company_id'],t)).rowcount:continue
            co=core.company(db,b['company_id'])
            if not co:continue
            e=charge_due(db,co,b)
            if not e:paid(db,b['company_id'],datetime.date.fromisoformat(b['next_charge']));n+=1;continue
            fails=b['fails']+1
            db.execute("UPDATE companies SET plan='pilot',plan_since=? WHERE id=? AND plan!='free'",(core.iso(),b['company_id']))  # 결제가 안 되면 모든 기능을 멈춘다 (다시 결제되면 paid()가 켠다)
            if fails>=MAX_FAILS:
                db.execute("UPDATE billing SET status='stopped',fails=?,note=? WHERE company_id=?",(fails,f'결제가 {fails}번 실패해 멈췄어요: {e}',b['company_id']))
                db.execute("UPDATE companies SET plan='pilot',plan_since=? WHERE id=? AND plan!='free'",(core.iso(),b['company_id']))
            else:db.execute("UPDATE billing SET status='past_due',fails=?,note=? WHERE company_id=?",(fails,f'결제하지 못했어요: {e} 결제될 때까지 소보루 CS를 쓸 수 없어요. 내일 다시 시도해요.',b['company_id']))
            if mail_of(co):core.send_mail(mail_of(co),f'[{core.BNAME}] 요금 결제를 하지 못했어요',f"{co['name']} 요금 결제가 되지 않았어요.\n이유: {e}\n결제될 때까지 소보루 CS 기능이 멈춰요. 설정 > 요금·결제에서 카드를 바꾸거나 다시 결제해 주세요.")
    return n

# ---------- 카페24 앱 결제 (카페24 앱스토어에서 설치한 쇼핑몰) ----------
# 카페24 앱스토어 앱은 카페24 결제로 받는다 (수수료 20%는 카페24가 떼고 정산). 운영자 결정 2026-10-18: 카페24로 연결한 사장님은 카페24 결제, 직접 가입은 포트원.
#  · '카페24로 결제하고 시작' -> POST /admin/appstore/orders (정기과금 automatic_payment=T, return_url=여기) -> 카페24 결제 화면(confirmation_url)
#  · 돌아오면 GET /admin/appstore/payments?order_id= 로 결제됐는지 카페24에 직접 확인한 뒤 유료로 켠다 (주소의 값은 믿지 않는다)
#  · 그다음 달부터는 카페24가 결제한다. 웹훅 90157(결제)·90079(갱신)은 카페24에 다시 확인해 기간을 늘리고, 90078(만료)·90159(환불 완료)는 끈다.
#    웹훅을 못 받아도: 이용 기간이 3일 넘게 지나면 카페24에 결제를 물어보고, 없으면 무료 시범으로 돌린다 (c24_expire).
#  · 해지는 카페24 관리자에서 한다 (카페24에 앱 결제 해지 API가 없음).
# 문서: apidocs.cafe24.com > Application > Appstore orders / Appstore payments. 조사: /mnt/project-files/plans/카페24_앱결제_조사.md
C24_GRACE=3
def c24_on():
    """운영자가 카페24 앱 결제를 켰는지 (카페24 앱 등록에 결제 권한·가격을 넣은 뒤 켠다)."""
    with conn() as db:r=db.execute("SELECT value FROM settings WHERE key='c24_billing'").fetchone()
    return bool(r and r['value']=='1')
def c24_link(db,cid):
    """카페24 앱 결제를 쓸 연결 (켰고, 연결이 살아 있으면). 결제 권한이 없는 예전 연결이면 ('reconnect', 연결)."""
    import cafe24
    if not c24_on() or not cafe24.ready():return None
    lk=cafe24.link(db,cid)
    if not lk or lk['status']!='ok':return None
    return lk if cafe24.has_scope(lk,'mall.write_application') else ('reconnect',lk)
def c24_paid(db,cid,order_id):
    """카페24에 이 주문의 결제를 직접 묻는다 -> 결제 dict(paid) 또는 None."""
    import cafe24
    d=today();q={'order_id':order_id,'start_date':(d-datetime.timedelta(days=400)).isoformat(),'end_date':(d+datetime.timedelta(days=1)).isoformat(),'limit':50}
    pays=(cafe24.api(db,cid,'/admin/appstore/payments',q) or {}).get('payments') or []
    paid=[p for p in pays if str(p.get('payment_status'))=='paid']
    return max(paid,key=lambda p:str(p.get('pay_date') or '')) if paid else None
def c24_until(p):
    """결제의 이용 기간 끝 (expiration_date), 없으면 결제일부터 한 달."""
    for k in ('expiration_date','pay_date'):
        try:
            v=datetime.date.fromisoformat(str(p.get(k) or '')[:10])
            return v if k=='expiration_date' else add_month(v)
        except ValueError:continue
    return add_month(today())
def c24_record(db,cid,order_id,p):
    """카페24 결제 하나를 기록하고 유료로 켠다 (같은 결제는 한 번만)."""
    pid='C24-'+str(p.get('payment_id') or order_id)
    if not db.execute('SELECT 1 FROM billing_payments WHERE order_id=?',(pid,)).fetchone():
        amt=int(float(str(p.get('payment_amount') or 0) or 0))
        db.execute("INSERT INTO billing_payments(company_id,order_id,amount,status,payment_key,created) VALUES(?,?,?,'done',?,?)",(cid,pid,amt,clean(str(p.get('approval_no') or ''),60),core.iso()))
    until=c24_until(p).isoformat()
    db.execute("UPDATE billing SET status='active',source='cafe24',fails=0,note='',warned=CASE next_charge WHEN ? THEN warned ELSE '' END,next_charge=?,creds=?,canceled='' WHERE company_id=?",(until,until,shops.seal({'c24_order':order_id}),cid))
    db.execute("UPDATE companies SET plan='paid',plan_since=CASE plan WHEN 'paid' THEN plan_since ELSE ? END WHERE id=?",(core.iso(),cid))
def c24_order_of(b):
    c=shops.unseal(b['creds']) if b and b['creds'] else None
    return (c or {}).get('c24_order','')
def c24_stop(db,cid,why):
    db.execute("UPDATE billing SET status='ended',note=? WHERE company_id=? AND source='cafe24'",(why,cid))
    db.execute("UPDATE companies SET plan='pilot',plan_since=? WHERE id=? AND plan='paid'",(core.iso(),cid))
def c24_event(mall,ev,res):
    """카페24 앱 결제 웹훅. 내용은 믿지 않고 카페24에 다시 물어서 맞춘다."""
    with conn() as db:
        rows=db.execute("SELECT b.* FROM billing b JOIN cafe24_links l ON l.company_id=b.company_id WHERE l.mall_id=? AND l.status='ok' AND b.source='cafe24'",(mall,)).fetchall()
        for b in rows:
            oid=c24_order_of(b)
            if not oid:continue
            p=c24_paid(db,b['company_id'],oid)
            if ev in ('90157','90079'):
                if p:c24_record(db,b['company_id'],oid,p)
            elif ev in ('90078','90159'):  # 만료·환불 완료: 카페24에 아직 기간이 남은 결제가 없으면 끈다
                if not p or c24_until(p)<today() or ev=='90159':c24_stop(db,b['company_id'],'카페24 앱 결제가 끝났어요 (만료 또는 환불).')
            elif ev=='90158':
                core.alert(core.company(db,b['company_id']),'link','카페24에 앱 환불 요청이 들어왔어요','카페24 관리자에서 처리돼요',db=db)
def c24_expire():
    """cron: 이용 기간이 사흘 넘게 지난 카페24 결제를 카페24에 다시 묻고, 새 결제가 없으면 멈춘다. 카페24 무료 체험은 끝나는 날 멈춘다."""
    with conn() as db:
        for b in db.execute("SELECT * FROM billing WHERE source='cafe24' AND status='trial' AND next_charge!='' AND next_charge<=?",(today().isoformat(),)).fetchall():
            db.execute("UPDATE billing SET status='ended',note='무료 체험이 끝났어요. 카페24로 결제하면 이어서 쓸 수 있어요.' WHERE company_id=?",(b['company_id'],))
            db.execute("UPDATE companies SET plan='pilot',plan_since=? WHERE id=? AND plan='trial'",(core.iso(),b['company_id']))
    t=(today()-datetime.timedelta(days=C24_GRACE)).isoformat()
    with conn() as db:due=db.execute("SELECT * FROM billing WHERE source='cafe24' AND status='active' AND next_charge!='' AND next_charge<?",(t,)).fetchall()
    for b in due:
        with conn() as db:
            try:p=c24_paid(db,b['company_id'],c24_order_of(b)) if c24_order_of(b) else None
            except shops.ShopError:continue  # 연결 문제면 다음에 (카페24 쪽 결제를 모르면 끄지 않는다)
            if p and c24_until(p)>=today():c24_record(db,b['company_id'],c24_order_of(b),p)
            else:c24_stop(db,b['company_id'],'카페24 앱 결제 기간이 끝났어요. 카페24에서 다시 결제하면 이어서 쓸 수 있어요.')

@bp.route('/billing/cafe24',methods=['POST'])
def c24_start():
    """카페24로 결제하고 시작: 앱스토어 주문을 만들고 카페24 결제 화면으로."""
    if not session.get('co_id'):return redirect(url_for('login'))
    co,can=company()
    if not can:abort(403)
    import cafe24
    with conn() as db:
        b=row(db,co['id']);p=plan((b['want_tier'] or b['tier']) if b else None)
        lk=c24_link(db,co['id'])
        if not p or not lk:flash('카페24 결제를 아직 쓸 수 없어요.','error');return redirect(url_for('pay.page'))
        if isinstance(lk,tuple):flash('카페24 앱 결제 권한이 필요해요. 서비스 연동 > 카페24에서 다시 연결해 주세요.','error');return redirect(url_for('c24.page'))
        body={'request':{'order_name':f"{core.BNAME} {p['name']} (월 정기결제)"[:100],'order_amount':str(int(p['price'])),
                         'return_url':url_for('pay.c24_done',_external=True),'automatic_payment':'T'}}
        try:d=cafe24.api(db,co['id'],'/admin/appstore/orders',method='POST',payload=body)
        except shops.ShopError as e:flash(str(e),'error');return redirect(url_for('pay.page'))
        o=(d or {}).get('order') or {};oid=clean(str(o.get('order_id') or ''),60);url=str(o.get('confirmation_url') or '')
        host=urllib.parse.urlparse(url).hostname or ''
        if not oid or not url.startswith('https://') or not (host=='cafe24.com' or host.endswith('.cafe24.com') or host.endswith('.cafe24api.com')):
            current_app.logger.warning('카페24 앱 주문 응답이 이상해요: %s',str(d)[:300]);flash('카페24 결제 화면을 열지 못했어요. 잠시 후 다시 해 주세요.','error');return redirect(url_for('pay.page'))
        if not row(db,co['id']):db.execute('INSERT INTO billing(company_id,customer_key) VALUES(?,?)',(co['id'],'cs_'+secrets.token_urlsafe(24)))
        db.execute("UPDATE billing SET tier=?,want_tier='',plan_name=?,price=? WHERE company_id=?",(p['key'],p['name'],int(p['price']),co['id']))
        session['c24_pay']=oid
    return redirect(url)

@bp.route('/billing/cafe24/done')
def c24_done():
    """카페24 결제 화면에서 돌아옴. 이 브라우저에서 만든 주문만, 카페24에 결제를 직접 확인한 뒤 켠다."""
    if not session.get('co_id'):return redirect(url_for('login'))
    co,can=company()
    oid=session.get('c24_pay') or ''
    if not oid:flash('결제 요청을 찾지 못했어요. 다시 해 주세요.','error');return redirect(url_for('pay.page'))
    with conn() as db:
        try:p=c24_paid(db,co['id'],oid)
        except shops.ShopError as e:flash(str(e),'error');return redirect(url_for('pay.page'))
        if not p:flash('카페24에서 결제가 아직 확인되지 않았어요. 결제를 마쳤다면 잠시 뒤 다시 열어 주세요.','error');return redirect(url_for('pay.page'))
        c24_record(db,co['id'],oid,p);db.execute("UPDATE billing SET started=CASE started WHEN '' THEN ? ELSE started END WHERE company_id=?",(core.iso(),co['id']))
    session.pop('c24_pay',None)
    flash('카페24로 결제했어요. 다음 달부터는 카페24가 매달 결제해요.','ok')
    return redirect(url_for('pay.page'))

# ---------- 화면 ----------
def company():
    import business, team
    co=business.me()
    if not co:abort(403)
    return co,team.can(business.who(),'manage')

@bp.route('/billing',methods=['GET','POST'])
def page():
    if not session.get('co_id'):return redirect(url_for('login'))
    co,can=company()
    with conn() as db:
        b=row(db,co['id'])
        if request.method=='POST':
            act=request.form.get('act')
            if not can:flash('요금·결제는 대표나 관리자만 바꿀 수 있어요.','error')
            elif act=='tier':
                t=next((x for x in tiers() if x['key']==request.form.get('tier')),None)
                if not t:flash('구간을 골라 주세요.','error')
                else:
                    if not b:db.execute('INSERT INTO billing(company_id,customer_key) VALUES(?,?)',(co['id'],'cs_'+secrets.token_urlsafe(24)));b=row(db,co['id'])
                    if b['status'] in ('none','ended','stopped','') or (b['status']=='trial' and b['source']!='cafe24'):  # 결제 전·체험 중에는 바로 바꾼다 (첫 결제가 그 구간)
                        db.execute("UPDATE billing SET tier=?,want_tier='',plan_name=?,price=? WHERE company_id=?",(t['key'],t['name'],t['price'],co['id']))
                        flash(f"{t['name']} 구간으로 정했어요. 월 {t['price']:,}원, 상담 {t['tickets']:,}건까지예요.",'ok')
                    elif b['source']=='cafe24':flash('카페24로 결제 중이에요. 구간을 바꾸려면 카페24 관리자의 앱 관리에서 해지한 뒤 새 구간으로 다시 결제해 주세요.','error')
                    else:
                        db.execute("UPDATE billing SET want_tier=? WHERE company_id=?",('' if t['key']==b['tier'] else t['key'],co['id']))
                        flash(f"다음 결제일({b['next_charge']})부터 {t['name']} 구간(월 {t['price']:,}원, 상담 {t['tickets']:,}건)으로 바뀌어요." if t['key']!=b['tier'] else '지금 구간을 그대로 써요.','ok')
            elif b and b['source']=='cafe24':flash('카페24로 결제 중이에요. 해지는 카페24 관리자의 앱 관리에서 해 주세요.','error')
            elif act=='cancel' and b and b['status'] in ('trial','active','past_due'):
                db.execute("UPDATE billing SET status='canceled',canceled=? WHERE company_id=?",(core.iso(),co['id']))
                flash(f"해지했어요. {b['next_charge']}까지 그대로 쓰고, 그날부터 결제하지 않아요."+(' 체험 기간이라 결제된 금액은 없어요.' if b['status']=='trial' else ''),'ok')
            elif act=='resume' and b and b['status']=='canceled':
                back='trial' if co['plan']=='trial' else 'active'  # 체험 중에 해지했다가 되돌리면 다시 체험 (끝나는 날 첫 결제)
                db.execute("UPDATE billing SET status=?,canceled='' WHERE company_id=?",(back,co['id']));flash('다시 이어서 쓰기로 했어요.','ok')
            elif act=='retry' and b and b['status'] in ('past_due','stopped'):
                e=charge_due(db,co,b)
                if e:flash('결제하지 못했어요: '+e,'error')
                else:paid(db,co['id'],today());flash('결제했어요.','ok')
            return redirect(url_for('pay.page'))
        pays=db.execute('SELECT * FROM billing_payments WHERE company_id=? ORDER BY id DESC LIMIT 24',(co['id'],)).fetchall()
        c24=c24_link(db,co['id'])
        if (ready() or c24) and can and not b:  # 포트원에 줄 고객 키: 추측할 수 없는 값으로 한 번 만들어 둔다
            db.execute('INSERT INTO billing(company_id,customer_key) VALUES(?,?)',(co['id'],'cs_'+secrets.token_urlsafe(24)));b=row(db,co['id'])
        use=usage(db,co,b)
    p=plan((b['want_tier'] or b['tier']) if b else None);once=None
    if ready() and can and b and b['status'] in ('none','ended') and not c24:  # 첫 달 바로 결제: 결제 번호는 여기서 정해 이 브라우저 세션에만 둔다
        once=dict(id=f"SOBORU1-{co['id']}-{core.now():%Y%m%d%H%M%S}-{secrets.token_hex(3)}",tier=p['key'],amount=int(p['price']))
        session['pay_once']=once
    return render_template('b_billing.html',co=co,bl=b,locked=not open_ok(co),pays=pays,p=p,tiers=tiers(),use=use,ready=ready(),may=can,c24=c24,c24_old=isinstance(c24,tuple),sdk=SDK,store_id=core.secret('PORTONE_STORE_ID'),
                           channel_key=core.secret('PORTONE_CHANNEL_KEY'),pay_channel_key=core.secret('PORTONE_PAY_CHANNEL_KEY') or core.secret('PORTONE_CHANNEL_KEY'),mail=mail_of(co),ok_url=url_for('pay.done',_external=True),
                           fail_url=url_for('pay.fail',_external=True),once=once,once_url=url_for('pay.once',_external=True),tab='settings')

@bp.route('/billing/once')
def once():
    """'첫 달 요금 바로 결제' 창에서 돌아옴 (?paymentId=). 운영자 결정 2026-10-24: 카드사 심사는 결제창 금액 = 화면 금액이어야 해서,
    체험 없이 첫 달을 일반 결제로 바로 받는 길을 둔다. 이 브라우저에서 만든 결제 번호만, 포트원에 상태·금액을 직접 확인한 뒤 켠다.
    빌링키가 없으니 다음 달 자동 결제는 카드를 등록해야 된다 (안 하면 결제일에 '등록된 카드가 없어요'로 멈춘다)."""
    if not session.get('co_id'):return redirect(url_for('login'))
    co,can=company()
    if not can:abort(403)
    if request.args.get('code'):
        flash('결제를 취소했거나 하지 못했어요. '+clean(request.args.get('message'),150),'error');return redirect(url_for('pay.page'))
    o=session.get('pay_once') or {};pid=clean(request.args.get('paymentId'),100)
    if not ready() or not pid or pid!=o.get('id'):flash('결제 요청이 맞지 않아요. 다시 해 주세요.','error');return redirect(url_for('pay.page'))
    try:s,d=_call('GET','/payments/'+_q(pid)+store_q())
    except PayError as e:flash(str(e),'error');return redirect(url_for('pay.page'))
    amt=int(o.get('amount') or 0)
    if s!=200 or d.get('status')!='PAID' or int((d.get('amount') or {}).get('total') or 0)!=amt or d.get('currency')!='KRW':  # 금액을 바꿔 결제한 것은 받지 않는다
        flash('결제가 확인되지 않았어요: '+(_msg(d,s) if s!=200 else '결제 상태나 금액이 맞지 않아요.'),'error');return redirect(url_for('pay.page'))
    t=tier(o.get('tier'))
    with conn() as db:
        if not db.execute('SELECT 1 FROM billing_payments WHERE order_id=?',(pid,)).fetchone():
            db.execute("INSERT INTO billing_payments(company_id,order_id,amount,status,payment_key,receipt,created,memo) VALUES(?,?,?,'done',?,?,?,?)",
                       (co['id'],pid,amt,clean(d.get('pgTxId'),200),clean(d.get('receiptUrl'),500),core.iso(),f"{t['name']} {amt:,}원 (첫 달 바로 결제)"))
            db.execute("UPDATE billing SET tier=?,want_tier='',plan_name=?,price=?,source='',started=CASE started WHEN '' THEN ? ELSE started END,canceled='',fails=0,note='',warned='' WHERE company_id=?",
                       (t['key'],t['name'],amt,core.iso(),co['id']))
            paid(db,co['id'],today())
    session.pop('pay_once',None)
    flash(f"{t['name']} 첫 달 요금 {amt:,}원을 결제했어요. 다음 달부터 자동으로 결제하려면 카드를 등록해 주세요.",'ok')
    return redirect(url_for('pay.page'))

@bp.route('/billing/done')
def done():
    """카드 등록 창에서 돌아옴 (?billingKey=). 포트원에 그 빌링키가 이 회사 고객 키로 발급됐는지 확인 -> 저장 -> (처음이면) 첫 달 결제."""
    if not session.get('co_id'):return redirect(url_for('login'))
    co,can=company()
    if not can:abort(403)
    if request.args.get('code'):return fail()
    key=clean(request.args.get('billingKey'),200)
    with conn() as db:b=row(db,co['id'])
    p=plan((b['want_tier'] or b['tier']) if b else None)
    if not b or not p or not ready() or not key:
        flash('카드 등록 요청이 맞지 않아요. 다시 해 주세요.','error');return redirect(url_for('pay.page'))
    try:s,d=_call('GET','/billing-keys/'+_q(key)+store_q())
    except PayError as e:flash(str(e),'error');return redirect(url_for('pay.page'))
    if s!=200 or d.get('status')!='ISSUED' or (d.get('customer') or {}).get('id')!=b['customer_key']:  # 남의 빌링키를 끼워 넣지 못하게
        flash('카드를 등록하지 못했어요: '+(_msg(d,s) if s!=200 else '등록 정보가 맞지 않아요.'),'error');return redirect(url_for('pay.page'))
    cd=next(((m.get('card') or {}) for m in d.get('methods') or [] if m.get('card')),{})
    card=' '.join(x for x in (clean(cd.get('name') or cd.get('issuer'),20),clean(cd.get('number'),30)) if x)
    with conn() as db:
        b=row(db,co['id']);first=b['status'] in ('none','ended','stopped')
        old=shops.unseal(b['creds']) if b['creds'] else None
        db.execute('UPDATE billing SET creds=?,card=? WHERE company_id=?',(shops.seal({'billing_key':key}),card,co['id']))
        if old and old.get('billing_key') and old['billing_key']!=key:drop_key(old['billing_key'])
        if not first:flash('카드를 바꿨어요. 다음 결제부터 이 카드로 결제해요.','ok');return redirect(url_for('pay.page'))
        trial=not b['started']  # 무료 체험은 회사마다 한 번 (해지했다가 다시 등록하면 바로 결제)
        db.execute("UPDATE billing SET tier=?,want_tier='',plan_name=?,price=?,started=CASE started WHEN '' THEN ? ELSE started END,canceled='',fails=0,note='',warned='' WHERE company_id=?",(p['key'],p['name'],int(p['price']),core.iso(),co['id']))
        if trial:
            end=today()+datetime.timedelta(days=TRIAL_DAYS)
            db.execute("UPDATE billing SET status='trial',source='',next_charge=? WHERE company_id=?",(end.isoformat(),co['id']))
            db.execute("UPDATE companies SET plan='trial',plan_since=? WHERE id=? AND plan!='free'",(core.iso(),co['id']))
            flash(f"카드를 등록했어요. {end.month}월 {end.day}일까지 무료로 쓰시고, 그날 {p['name']} 첫 달 요금 {int(p['price']):,}원이 결제돼요. 그 전에 해지하면 결제되지 않아요.",'ok')
            return redirect(url_for('decide'))
        e=charge(db,co,row(db,co['id']))
        if e:db.execute("UPDATE billing SET status='stopped',note=? WHERE company_id=?",('첫 결제를 하지 못했어요: '+e,co['id']));flash('카드는 등록했지만 결제하지 못했어요: '+e,'error')
        else:paid(db,co['id'],today());flash(f"{p['name']} 요금제를 시작했어요. 첫 달 요금을 결제했어요.",'ok')
    return redirect(url_for('pay.page'))

@bp.route('/billing/fail')
def fail():
    if not session.get('co_id'):return redirect(url_for('login'))
    current_app.logger.info('카드 등록 취소·실패: %s',clean(request.args.get('code'),60))
    flash('카드 등록을 취소했거나 하지 못했어요. '+clean(request.args.get('message'),150),'error')
    return redirect(url_for('pay.page'))
