"""요금 결제 (토스페이먼츠 자동결제·빌링). 운영자가 키(TOSS_CLIENT_KEY·TOSS_SECRET_KEY)와 요금제(이름·월 금액)를 넣기 전까지는 '준비 중'.

  · 사장님(대표·관리자)이 '카드 등록하고 시작'을 누르면 토스페이먼츠 카드 등록 창이 뜬다 -> 돌아오면 authKey로 빌링키를 받아
    암호화해 저장하고, 첫 달 요금을 바로 결제한다. 결제가 되면 다음 결제일은 한 달 뒤.
  · 다음 결제일이 되면 cron(10분마다, shops.py)이 하루 한 번만 결제를 시도한다. 실패하면 '결제 실패'로 두고 다음 날 다시,
    3번 연속 실패하면 멈추고 무료 시범으로 돌린다. 기능은 막지 않는다 (요금제가 정해지면 그때 정한다).
  · 해지하면 다음 결제일까지 쓰고 그날부터 결제하지 않는다. 다음 결제일 전에는 다시 이어 쓸 수 있다.
  · 시험 키(test_)로는 실제 돈이 나가지 않는다. 화면에 '시험 모드'를 띄운다.
문서: docs.tosspayments.com > 자동결제(빌링) API (POST /v1/billing/authorizations/issue, POST /v1/billing/{billingKey})
"""
import base64, calendar, datetime, json, secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session, current_app
import core, shops
from core import conn, clean

bp=Blueprint('pay',__name__)
API='https://api.tosspayments.com'
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

def ready():return bool(core.secret('TOSS_CLIENT_KEY') and core.secret('TOSS_SECRET_KEY'))
def test_mode():return core.secret('TOSS_SECRET_KEY').startswith('test_')
def plan():
    """운영자가 정한 요금제 {name, price} 또는 None (금액은 부가세 포함, 원)."""
    with conn() as db:r=db.execute("SELECT value FROM settings WHERE key='billing_plan'").fetchone()
    try:p=json.loads(r['value']) if r else None
    except ValueError:p=None
    return p if p and p.get('name') and int(p.get('price') or 0)>0 else None
def save_plan(name,price):
    with conn() as db:db.execute("INSERT INTO settings(key,value,updated) VALUES('billing_plan',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated",
                                 (json.dumps({'name':name,'price':price},ensure_ascii=False),core.iso()))
def row(db,cid):return db.execute('SELECT * FROM billing WHERE company_id=?',(cid,)).fetchone()
def today():return core.now().date()
def mail_of(co):return co['notify_email'] or (co['login_id'] if '@' in (co['login_id'] or '') else '')
def add_month(d):
    """같은 날 다음 달 (31일 -> 다음 달 말일)."""
    y,m=(d.year+1,1) if d.month==12 else (d.year,d.month+1)
    return d.replace(year=y,month=m,day=min(d.day,calendar.monthrange(y,m)[1]))

class PayError(Exception):
    """사장님께 그대로 보여 줄 우리말 안내."""
def _call(path,body):
    """(상태, JSON). 시크릿 키는 Basic 인증으로만 보낸다."""
    auth=base64.b64encode((core.secret('TOSS_SECRET_KEY')+':').encode()).decode()
    try:return shops.http('POST',API+path,{'Authorization':'Basic '+auth,'Content-Type':'application/json'},json.dumps(body).encode())
    except shops.ShopError:raise PayError('토스페이먼츠에 연결하지 못했어요. 잠시 후 다시 해 주세요.')
def _msg(d,s):return clean((d or {}).get('message') or f'결제 오류 ({s})',200)

def charge(db,co,b):
    """한 달 요금을 결제한다. -> '' 또는 실패 이유. 결제 기록은 성공·실패 모두 남긴다."""
    c=shops.unseal(b['creds']) if b['creds'] else None
    if not c or not c.get('billing_key'):return '등록된 카드가 없어요.'
    order=f"SOBORU-{co['id']}-{core.now():%Y%m%d%H%M%S}-{secrets.token_hex(3)}"
    db.execute("INSERT INTO billing_payments(company_id,order_id,amount,status,created) VALUES(?,?,?,'try',?)",(co['id'],order,b['price'],core.iso()))
    body={'customerKey':b['customer_key'],'amount':b['price'],'orderId':order,'orderName':f"{core.BNAME} {b['plan_name']} (1개월)",'customerName':clean(co['name'],60)}
    if mail_of(co):body['customerEmail']=mail_of(co)
    try:s,d=_call('/v1/billing/'+c['billing_key'],body)
    except PayError as e:s,d=0,{'message':str(e)}
    if s==200 and d.get('status')=='DONE':
        db.execute("UPDATE billing_payments SET status='done',payment_key=?,receipt=? WHERE order_id=?",(clean(d.get('paymentKey'),200),clean((d.get('receipt') or {}).get('url'),500),order))
        return ''
    e=_msg(d,s);db.execute("UPDATE billing_payments SET status='fail',error=? WHERE order_id=?",(e,order))
    return e

def paid(db,cid,start):
    db.execute("UPDATE billing SET status='active',fails=0,note='',next_charge=? WHERE company_id=?",(add_month(start).isoformat(),cid))
    db.execute("UPDATE companies SET plan='paid',plan_since=CASE plan WHEN 'paid' THEN plan_since ELSE ? END WHERE id=?",(core.iso(),cid))

def renew_all():
    """cron: 결제일이 된 회사를 하루 한 번만 결제. 해지한 회사는 결제일에 무료 시범으로 돌린다."""
    n=0;t=today().isoformat()
    with conn() as db:due=db.execute("SELECT * FROM billing WHERE status IN ('active','past_due','canceled') AND next_charge!='' AND next_charge<=?",(t,)).fetchall()
    for b in due:
        with conn() as db:
            if b['status']=='canceled':
                db.execute("UPDATE billing SET status='ended',creds='' WHERE company_id=?",(b['company_id'],))
                db.execute("UPDATE companies SET plan='pilot',plan_since=? WHERE id=?",(core.iso(),b['company_id']));continue
            # 10분마다 도는 cron이 같은 날 두 번 결제하지 않게 먼저 '오늘 시도함'을 잡는다
            if not db.execute('UPDATE billing SET last_try=? WHERE company_id=? AND last_try<?',(t,b['company_id'],t)).rowcount:continue
            co=core.company(db,b['company_id'])
            if not co:continue
            p=plan()
            if p and (p['name'],int(p['price']))!=(b['plan_name'],b['price']):  # 운영자가 요금을 바꾸면 다음 결제부터 (화면에 미리 안내)
                db.execute('UPDATE billing SET plan_name=?,price=? WHERE company_id=?',(p['name'],int(p['price']),b['company_id']));b=row(db,b['company_id'])
            e=charge(db,co,b)
            if not e:paid(db,b['company_id'],datetime.date.fromisoformat(b['next_charge']));n+=1;continue
            fails=b['fails']+1
            if fails>=MAX_FAILS:
                db.execute("UPDATE billing SET status='stopped',fails=?,note=? WHERE company_id=?",(fails,f'결제가 {fails}번 실패해 멈췄어요: {e}',b['company_id']))
                db.execute("UPDATE companies SET plan='pilot',plan_since=? WHERE id=?",(core.iso(),b['company_id']))
            else:db.execute("UPDATE billing SET status='past_due',fails=?,note=? WHERE company_id=?",(fails,f'결제하지 못했어요: {e} 내일 다시 시도해요.',b['company_id']))
            if mail_of(co):core.send_mail(mail_of(co),f'[{core.BNAME}] 요금 결제를 하지 못했어요',f"{co['name']} 요금 결제가 되지 않았어요.\n이유: {e}\n설정 > 요금·결제에서 카드를 바꾸거나 다시 결제해 주세요.")
    return n

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
            elif act=='cancel' and b and b['status'] in ('active','past_due'):
                db.execute("UPDATE billing SET status='canceled',canceled=? WHERE company_id=?",(core.iso(),co['id']))
                flash(f"해지했어요. {b['next_charge']}까지 그대로 쓰고, 그날부터 결제하지 않아요.",'ok')
            elif act=='resume' and b and b['status']=='canceled':
                db.execute("UPDATE billing SET status='active',canceled='' WHERE company_id=?",(co['id'],));flash('다시 이어서 쓰기로 했어요.','ok')
            elif act=='retry' and b and b['status'] in ('past_due','stopped'):
                e=charge(db,co,b)
                if e:flash('결제하지 못했어요: '+e,'error')
                else:paid(db,co['id'],today());flash('결제했어요.','ok')
            return redirect(url_for('pay.page'))
        pays=db.execute('SELECT * FROM billing_payments WHERE company_id=? ORDER BY id DESC LIMIT 24',(co['id'],)).fetchall()
        if ready() and can and not b:  # 토스페이먼츠에 줄 고객 키: 추측할 수 없는 값으로 한 번 만들어 둔다
            db.execute('INSERT INTO billing(company_id,customer_key) VALUES(?,?)',(co['id'],'cs_'+secrets.token_urlsafe(24)));b=row(db,co['id'])
    return render_template('b_billing.html',co=co,bl=b,pays=pays,p=plan(),ready=ready(),test=test_mode(),may=can,client_key=core.secret('TOSS_CLIENT_KEY'),
                           ok_url=url_for('pay.done',_external=True),fail_url=url_for('pay.fail',_external=True),tab='settings')

@bp.route('/billing/done')
def done():
    """카드 등록 창에서 돌아옴: authKey -> 빌링키 -> (처음이면) 첫 달 결제."""
    if not session.get('co_id'):return redirect(url_for('login'))
    co,can=company()
    if not can:abort(403)
    p=plan()
    with conn() as db:
        b=row(db,co['id'])
        if not b or not p or not ready() or request.args.get('customerKey')!=b['customer_key'] or not request.args.get('authKey'):
            flash('카드 등록 요청이 맞지 않아요. 다시 해 주세요.','error');return redirect(url_for('pay.page'))
    try:s,d=_call('/v1/billing/authorizations/issue',{'authKey':clean(request.args.get('authKey'),300),'customerKey':b['customer_key']})
    except PayError as e:flash(str(e),'error');return redirect(url_for('pay.page'))
    if s!=200 or not d.get('billingKey'):flash('카드를 등록하지 못했어요: '+_msg(d,s),'error');return redirect(url_for('pay.page'))
    card=' '.join(x for x in (clean(d.get('cardCompany'),20),clean(d.get('cardNumber') or (d.get('card') or {}).get('number'),30)) if x)
    with conn() as db:
        first=b['status'] in ('none','ended','stopped')
        db.execute('UPDATE billing SET creds=?,card=? WHERE company_id=?',(shops.seal({'billing_key':d['billingKey']}),card,co['id']))
        if not first:flash('카드를 바꿨어요. 다음 결제부터 이 카드로 결제해요.','ok');return redirect(url_for('pay.page'))
        db.execute("UPDATE billing SET plan_name=?,price=?,started=?,canceled='',fails=0 WHERE company_id=?",(p['name'],int(p['price']),core.iso(),co['id']))
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
