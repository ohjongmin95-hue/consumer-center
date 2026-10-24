"""외부 연동 API (Gorgias의 REST API·Webhooks에 해당). 보안 점검 전이라 공개하지 않는다.

  · SOBORU CS 운영자가 회사별로 켜야 쓸 수 있다(companies.api_enabled). 켜지 않은 회사에는 메뉴도 안 보인다.
  · 키는 회사마다 만든다. 원문은 만들 때 한 번만 보여 주고 SHA-256 해시만 저장한다.
    sk_test_ 키는 그 회사의 데모 작업 공간(견본 데이터)에만 닿는다. 실제 고객 데이터에 닿지 않고 시험해 볼 수 있다.
  · 웹훅: 새 문의·답변을 회사가 정한 https 주소로 보낸다. 본문에 HMAC-SHA256 서명을 붙이고, 보낸 기록을 남긴다.
    사설망·내부 주소로는 보내지 않는다(SSRF 방지). 판매처 가져오기 cron(10분마다, shops.py)이 dispatch()를 부른다.
"""
import datetime, functools, hashlib, hmac, ipaddress, json, re, secrets, socket, time, urllib.parse
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session, jsonify, g
from werkzeug.security import generate_password_hash
import core, shops
from core import conn, clean, digits, BIG

bp=Blueprint('api',__name__)
EVENTS={'case.created':'새 문의가 들어왔을 때','case.replied':'문의에 답변했을 때'}
MAX_KEYS=10;MAX_HOOKS=5;RATE=120  # 키마다 1분에 요청 수
FAIL_STOP=20  # 연달아 이만큼 실패하면 웹훅을 멈춘다

def init():
    with conn() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS api_keys(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,name TEXT NOT NULL,mode TEXT NOT NULL,prefix TEXT NOT NULL,
              hash TEXT UNIQUE NOT NULL,created TEXT NOT NULL,last_used TEXT NOT NULL DEFAULT '',revoked TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS api_hits(key_id INTEGER NOT NULL,minute TEXT NOT NULL,n INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(key_id,minute));
            CREATE TABLE IF NOT EXISTS webhooks(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,mode TEXT NOT NULL DEFAULT 'live',url TEXT NOT NULL,secret TEXT NOT NULL,events TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1,fails INTEGER NOT NULL DEFAULT 0,last_case INTEGER NOT NULL DEFAULT 0,last_event INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS webhook_log(id INTEGER PRIMARY KEY,webhook_id INTEGER NOT NULL,event TEXT NOT NULL,ref TEXT NOT NULL DEFAULT '',status INTEGER NOT NULL DEFAULT 0,
              ok INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',ms INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL);''')
        if 'api_enabled' not in {r[1] for r in db.execute('PRAGMA table_info(companies)')}:db.execute('ALTER TABLE companies ADD COLUMN api_enabled INTEGER NOT NULL DEFAULT 0')
init()

def h(raw):return hashlib.sha256(raw.encode()).hexdigest()
def target(db,co,mode):
    """키가 닿는 회사: live는 그 회사, test는 그 회사의 데모 작업 공간(없으면 만든다)."""
    if mode=='live':return co
    import demo
    d=demo.of(db,co)
    if not d:demo.create(db,co);d=demo.of(db,co)
    return d

# ---------- 인증 ----------
def err(code,msg,status):return jsonify(error={'code':code,'message':msg}),status
def api_auth(f):
    @functools.wraps(f)
    def w(*a,**k):
        m=re.match(r'^Bearer\s+(sk_(live|test)_[A-Za-z0-9_-]{20,80})$',request.headers.get('Authorization',''))
        if not m:return err('unauthorized','Authorization: Bearer <API 키> 머리글이 필요해요.',401)
        with conn() as db:
            key=db.execute("SELECT * FROM api_keys WHERE hash=? AND revoked=''",(h(m.group(1)),)).fetchone()
            if not key:return err('unauthorized','API 키가 맞지 않거나 폐기됐어요.',401)
            co=core.company(db,key['company_id'])
            if not co or co['status']!='active' or not co['api_enabled']:return err('forbidden','이 회사는 API를 쓸 수 없어요.',403)
            if key['mode']=='live' and not co['member']:return err('forbidden','회사 인증이 끝나야 실제 데이터 API를 쓸 수 있어요. 시험 키(sk_test_)는 지금 쓸 수 있어요.',403)
            minute=core.now().strftime('%Y-%m-%d %H:%M')
            db.execute('INSERT INTO api_hits(key_id,minute,n) VALUES(?,?,1) ON CONFLICT(key_id,minute) DO UPDATE SET n=n+1',(key['id'],minute))
            if db.execute('SELECT n FROM api_hits WHERE key_id=? AND minute=?',(key['id'],minute)).fetchone()[0]>RATE:return err('rate_limited',f'1분에 {RATE}번까지 부를 수 있어요.',429)
            db.execute("DELETE FROM api_hits WHERE minute<?",(core.now().strftime('%Y-%m-%d'),))
            db.execute('UPDATE api_keys SET last_used=? WHERE id=?',(core.iso(),key['id']))
            g.api_co=target(db,co,key['mode']);g.api_mode=key['mode'];g.actor=f"API ({key['name']})"
        return f(*a,**k)
    return w

def case_json(c,ev=None):
    out={'no':c['no'],'status':c['status'],'category':c['category'],'channel':c['channel'] or '한큐','title':c['title'],'body':c['body'],'want':c['want'],
         'order_no':c['order_no'],'product':c['product'],'customer_name':c['name'],'created':c['created'],'updated':c['updated'],'due':c['due'] or None}
    if ev is not None:out['events']=[{'kind':{'me':'customer','co':'company','sys':'system'}.get(e['kind'],e['kind']),'text':e['text'],'reply':e['reply'],'created':e['created']} for e in ev]
    return out
def get_case(db,no):
    c=db.execute('SELECT * FROM cases WHERE no=? AND company_id=?',(no,g.api_co['id'])).fetchone()
    if not c:abort(404)
    return c

@bp.route('/api/ext/v1/me')
@api_auth
def me():
    return jsonify(company={'name':g.api_co['name'],'mode':g.api_mode,'demo':g.api_co['status']=='demo'})

@bp.route('/api/ext/v1/cases')
@api_auth
def cases():
    st=request.args.get('status','');since=request.args.get('updated_since','')
    lim=min(max(int(request.args.get('limit','50')) if request.args.get('limit','').isdigit() else 50,1),100)
    sql='SELECT * FROM cases WHERE company_id=?';a=[g.api_co['id']]
    if st:
        if st not in core.STATUS:return err('bad_request','status 값을 확인해 주세요.',400)
        sql+=' AND status=?';a.append(st)
    if since:
        if not core.parse(since.replace('T',' ')[:19]):return err('bad_request','updated_since는 2026-10-01T00:00:00 꼴로 보내 주세요.',400)
        sql+=' AND updated>=?';a.append(since.replace('T',' ')[:19])
    with conn() as db:rows=db.execute(sql+' ORDER BY updated DESC LIMIT ?',a+[lim]).fetchall()
    return jsonify(data=[case_json(c) for c in rows])

@bp.route('/api/ext/v1/cases/<no>')
@api_auth
def case(no):
    with conn() as db:c=get_case(db,no);return jsonify(data=case_json(c,core.events(db,c['id'])))

@bp.route('/api/ext/v1/cases',methods=['POST'])
@api_auth
def create():
    import business
    j=request.get_json(silent=True) or {}
    f={k:str(j.get(k,'') or '') for k in ('channel','category','title','body','want','order_no','product','received_on','name','phone','email')}
    f['channel']=f['channel'] or '기타'
    d,e,cid=business.new_case_apply(g.api_co,f)
    if e:return err('bad_request',e,400)
    with conn() as db:c=db.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
    return jsonify(data=case_json(c)),201

@bp.route('/api/ext/v1/cases/<no>/replies',methods=['POST'])
@api_auth
def reply(no):
    import business
    j=request.get_json(silent=True) or {}
    with conn() as db:
        c=get_case(db,no)
        if c['status'] in core.FINAL:return err('conflict','이미 끝난 문의예요.',409)
        msg,level=business.case_act(db,c,{'act':'reply','msg':str(j.get('message','') or '')})
        if level!='ok':return err('bad_request',msg,400)
        c=get_case(db,no);return jsonify(data=case_json(c,core.events(db,c['id'])))

@bp.route('/api/ext/v1/orders')
@api_auth
def order_list():
    lim=min(max(int(request.args.get('limit','50')) if request.args.get('limit','').isdigit() else 50,1),100)
    no=clean(request.args.get('order_no'),60)
    with conn() as db:
        rows=db.execute('SELECT * FROM orders WHERE company_id=?'+(' AND order_no=?' if no else '')+' ORDER BY updated DESC LIMIT ?',[g.api_co['id']]+([no] if no else [])+[lim]).fetchall()
    return jsonify(data=[{'order_no':o['order_no'],'channel':o['channel'],'ordered_on':o['ordered_on'],'product':o['product'],'qty':o['qty'],'amount':o['amount'],
                          'status':o['status'],'courier':o['courier'],'invoice':o['invoice'],'updated':o['updated']} for o in rows])

@bp.errorhandler(404)
def nf(e):
    if request.path.startswith('/api/ext/'):return err('not_found','찾는 것이 없어요.',404)
    return e

# ---------- 웹훅 ----------
def safe_url(url):
    """https이고 공용 인터넷 주소일 때만 ''(통과). 아니면 이유."""
    p=urllib.parse.urlparse(url)
    if p.scheme!='https' or not p.hostname:return 'https:// 로 시작하는 주소만 쓸 수 있어요.'
    if p.username or p.password:return '주소에 아이디·비밀번호를 넣을 수 없어요.'
    try:infos=socket.getaddrinfo(p.hostname,p.port or 443,proto=socket.IPPROTO_TCP)
    except OSError:return '주소를 찾지 못했어요.'
    for i in infos:
        ip=ipaddress.ip_address(i[4][0])
        if not ip.is_global:return '사설망·내부 주소로는 보낼 수 없어요.'
    return ''
def sign(secret,ts,body):return hmac.new(secret.encode(),f'{ts}.'.encode()+body,hashlib.sha256).hexdigest()
def post(url,secret,event,data):
    """(상태 코드, 오류, 걸린 ms)"""
    e=safe_url(url)
    if e:return 0,e,0
    body=json.dumps({'id':'evt_'+secrets.token_hex(8),'type':event,'created':core.iso(),'data':data},ensure_ascii=False).encode()
    ts=str(int(time.time()));t0=time.time()
    try:code,_=shops.http('POST',url,{'Content-Type':'application/json','User-Agent':'SoboruCS-Webhook/1','X-Soboru-Event':event,
                                      'X-Soboru-Signature':f't={ts},v1={sign(secret,ts,body)}'},body)
    except shops.ShopError:return 0,'연결하지 못했어요',int((time.time()-t0)*1000)
    return code,'' if 200<=code<300 else f'응답 {code}',int((time.time()-t0)*1000)

def deliver(db,wh,event,ref,data):
    code,e,ms=post(wh['url'],shops.unseal(wh['secret']) or '',event,data)
    ok=1 if not e else 0
    db.execute('INSERT INTO webhook_log(webhook_id,event,ref,status,ok,error,ms,created) VALUES(?,?,?,?,?,?,?,?)',(wh['id'],event,ref,code,ok,e,ms,core.iso()))
    db.execute('UPDATE webhooks SET fails=CASE ? WHEN 1 THEN 0 ELSE fails+1 END,active=CASE WHEN ?=0 AND fails+1>=? THEN 0 ELSE active END WHERE id=?',(ok,ok,FAIL_STOP,wh['id']))
    if not ok and wh['active'] and wh['fails']+1>=FAIL_STOP:
        co=core.company(db,wh['company_id'])
        core.send_mail(co['notify_email'],f'[{core.BNAME}] 웹훅을 멈췄어요',f"{wh['url']} 로 보내는 알림이 {FAIL_STOP}번 연달아 실패해서 멈췄어요. 받는 쪽을 고친 뒤 외부 API 화면에서 다시 켜 주세요.\n{core.site_url('biz','/developers')}")
    return ok

def dispatch():
    """cron: 켜진 웹훅마다 새 문의·답변을 차례로 보낸다. 실패하면 거기서 멈추고 다음 번에 다시 보낸다."""
    n=0
    with conn() as db:
        hooks=db.execute("SELECT w.*,c.api_enabled FROM webhooks w JOIN companies c ON c.id=w.company_id WHERE w.active=1 AND c.api_enabled=1 AND c.status='active'").fetchall()
        for wh in hooks:
            co=target(db,core.company(db,wh['company_id']),wh['mode']);evs=set(wh['events'].split(','))
            for c in db.execute('SELECT * FROM cases WHERE company_id=? AND id>? AND import_batch=0 ORDER BY id LIMIT 50',(co['id'],wh['last_case'])).fetchall():
                if 'case.created' in evs and not deliver(db,wh,'case.created',c['no'],case_json(c)):break
                db.execute('UPDATE webhooks SET last_case=? WHERE id=?',(c['id'],wh['id']));n+=1
            else:
                for e in db.execute("""SELECT e.*,c.no FROM events e JOIN cases c ON c.id=e.case_id WHERE c.company_id=? AND e.kind='co' AND e.reply!='' AND e.id>? AND c.import_batch=0 ORDER BY e.id LIMIT 50""",(co['id'],wh['last_event'])).fetchall():
                    if 'case.replied' in evs and not deliver(db,wh,'case.replied',e['no'],{'no':e['no'],'reply':e['reply'],'created':e['created']}):break
                    db.execute('UPDATE webhooks SET last_event=? WHERE id=?',(e['id'],wh['id']));n+=1
    return n

# ---------- 회사 화면: 키·웹훅 관리 ----------
def company():
    import business
    if not session.get('co_id'):return None
    co=business.real()
    if not co or not co['api_enabled']:abort(404)  # 운영자가 켜기 전에는 없는 화면
    return co

@bp.route('/developers',methods=['GET','POST'])
def manage():
    co=company()
    if co is None:return redirect(url_for('login'))
    new_key=''
    with conn() as db:
        if request.method=='POST':
            act=request.form.get('act')
            if act=='key':
                mode='test' if request.form.get('mode')=='test' else 'live';name=clean(request.form.get('name'),40) or ('시험 키' if mode=='test' else '운영 키')
                if db.execute("SELECT COUNT(*) FROM api_keys WHERE company_id=? AND revoked=''",(co['id'],)).fetchone()[0]>=MAX_KEYS:flash(f'키는 {MAX_KEYS}개까지 만들 수 있어요','error')
                elif mode=='live' and not co['member']:flash('운영 키는 회사 인증이 끝난 뒤에 만들 수 있어요. 시험 키는 지금 만들 수 있어요.','error')
                else:
                    new_key=f'sk_{mode}_'+secrets.token_urlsafe(32)
                    db.execute('INSERT INTO api_keys(company_id,name,mode,prefix,hash,created) VALUES(?,?,?,?,?,?)',(co['id'],name,mode,new_key[:12],h(new_key),core.iso()))
                    if mode=='test':target(db,co,'test')
            elif act=='revoke' and request.form.get('id','').isdigit():
                db.execute("UPDATE api_keys SET revoked=? WHERE id=? AND company_id=? AND revoked=''",(core.iso(),int(request.form['id']),co['id']));flash('키를 폐기했어요. 이 키로는 더 부를 수 없어요.','ok')
            elif act=='hook':
                url=clean(request.form.get('url'),300);evs=[e for e in request.form.getlist('events') if e in EVENTS]
                mode='test' if request.form.get('mode')=='test' else 'live'
                bad=safe_url(url)
                if bad:flash(bad,'error')
                elif not evs:flash('받을 알림을 하나 이상 골라 주세요','error')
                elif db.execute('SELECT COUNT(*) FROM webhooks WHERE company_id=?',(co['id'],)).fetchone()[0]>=MAX_HOOKS:flash(f'웹훅은 {MAX_HOOKS}개까지예요','error')
                else:
                    sec='whsec_'+secrets.token_urlsafe(24);tg=target(db,co,mode)
                    last_c=db.execute('SELECT COALESCE(MAX(id),0) FROM cases WHERE company_id=?',(tg['id'],)).fetchone()[0]
                    last_e=db.execute('SELECT COALESCE(MAX(e.id),0) FROM events e JOIN cases c ON c.id=e.case_id WHERE c.company_id=?',(tg['id'],)).fetchone()[0]
                    db.execute('INSERT INTO webhooks(company_id,mode,url,secret,events,last_case,last_event,created) VALUES(?,?,?,?,?,?,?,?)',(co['id'],mode,url,shops.seal(sec),','.join(evs),last_c,last_e,core.iso()))
                    flash(f'웹훅을 만들었어요. 서명 비밀값은 지금 한 번만 보여요: {sec}','ok')
            elif act in ('hook_del','hook_on','hook_test') and request.form.get('id','').isdigit():
                wh=db.execute('SELECT * FROM webhooks WHERE id=? AND company_id=?',(int(request.form['id']),co['id'])).fetchone()
                if wh and act=='hook_del':db.execute('DELETE FROM webhooks WHERE id=?',(wh['id'],));db.execute('DELETE FROM webhook_log WHERE webhook_id=?',(wh['id'],));flash('웹훅을 지웠어요','ok')
                elif wh and act=='hook_on':db.execute('UPDATE webhooks SET active=1,fails=0 WHERE id=?',(wh['id'],));flash('웹훅을 다시 켰어요','ok')
                elif wh:
                    ok=deliver(db,wh,'ping','',{'message':'SOBORU CS 웹훅 시험이에요'})
                    flash('시험 알림을 보냈어요' if ok else '시험 알림을 보내지 못했어요. 아래 보낸 기록을 확인해 주세요','ok' if ok else 'error')
            if not new_key:return redirect(url_for('api.manage'))
        keys=db.execute('SELECT * FROM api_keys WHERE company_id=? ORDER BY revoked!=\'\',id DESC',(co['id'],)).fetchall()
        hooks=db.execute('SELECT * FROM webhooks WHERE company_id=? ORDER BY id',(co['id'],)).fetchall()
        logs=db.execute('SELECT l.*,w.url FROM webhook_log l JOIN webhooks w ON w.id=l.webhook_id WHERE w.company_id=? ORDER BY l.id DESC LIMIT 30',(co['id'],)).fetchall()
    return render_template('b_developers.html',keys=keys,hooks=hooks,logs=logs,new_key=new_key,EVENTS=EVENTS,base=core.site_url('biz','/api/ext/v1') or url_for('api.me',_external=True).rsplit('/me',1)[0],RATE=RATE,tab='connect')

# ---------- 운영: 회사별로 켜고 끄기 ----------
@bp.route('/ops/company/<int:cid>/api',methods=['POST'])
def ops_toggle(cid):
    if not session.get('ops'):return redirect(url_for('ops_login'))
    on=1 if request.form.get('on')=='1' else 0
    with conn() as db:
        db.execute("UPDATE companies SET api_enabled=? WHERE id=? AND status IN ('active','suspended')",(on,cid))
        if not on:db.execute('UPDATE webhooks SET active=0 WHERE company_id=?',(cid,))
    flash('외부 API를 켰어요 (이 회사만, 시범)' if on else '외부 API를 껐어요. 웹훅도 멈췄어요','ok')
    return redirect(url_for('ops_company',cid=cid))
