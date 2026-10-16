"""인스타그램 DM 받기 (Instagram API with Instagram Login).
소보루가 메타 개발자 앱을 만들고 키(IG_APP_ID·IG_APP_SECRET·IG_VERIFY_TOKEN)를 서버에 넣기 전까지는 '연동 대기'.

  · 사장님이 '인스타그램으로 로그인'을 누르면 인스타그램 권한 동의 화면으로 간다 -> 돌아오면 장기 토큰(60일)을 암호화해 저장하고,
    그 계정의 DM 알림(웹훅)을 소보루로 받도록 신청한다. 토큰은 cron이 30일마다 새로 바꾼다.
  · 고객이 DM을 보내면 메타가 /hook/instagram 으로 알려 준다(서명 X-Hub-Signature-256을 앱 시크릿으로 확인).
    같은 고객의 DM은 끝나지 않은 요청에 이어 붙고, 없으면 새 요청('인스타그램 DM')이 된다.
  · 답변은 사람이 요청 화면에서 '인스타그램 DM으로 답변 보내기'를 눌러야 나간다. 인스타그램 규칙상 고객이 마지막으로 보낸 지 24시간 안에만 보낼 수 있다.
문서: developers.facebook.com/docs/instagram-platform (Business Login, Webhooks, Messaging API)
"""
import datetime, hashlib, hmac, json, secrets, traceback, urllib.parse
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, jsonify, current_app
import core, shops
from core import conn, clean

bp=Blueprint('ig',__name__)
SHOP='instagram'            # shop_seen 이름. ext_id 'u:<고객 IGSID>' = 대화 상대, 'm:<mid>' = 받은 메시지(중복 막기)
CHANNEL='인스타그램 DM'
GRAPH='https://graph.instagram.com/v21.0'
SCOPES='instagram_business_basic,instagram_business_manage_messages'
REFRESH_DAYS=30
NO_TEXT='(사진이나 첨부를 보냈어요. 인스타그램에서 확인해 주세요)'

def init():
    with conn() as db:db.execute('''CREATE TABLE IF NOT EXISTS ig_links(company_id INTEGER PRIMARY KEY,ig_id TEXT NOT NULL UNIQUE,username TEXT NOT NULL DEFAULT '',creds TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ok',note TEXT NOT NULL DEFAULT '',refreshed TEXT NOT NULL DEFAULT '',last_in TEXT NOT NULL DEFAULT '',n_inq INTEGER NOT NULL DEFAULT 0,
        n_sent INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL,FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE)''')
init()

def ready():return all(core.secret(k) for k in ('IG_APP_ID','IG_APP_SECRET','IG_VERIFY_TOKEN'))
def redirect_uri():return core.site_url('biz','/connect/instagram/callback') or url_for('ig.callback',_external=True)
def hook_url():return core.site_url('biz','/hook/instagram')
def link(db,cid):return db.execute('SELECT * FROM ig_links WHERE company_id=?',(cid,)).fetchone()

class IgError(Exception):
    """사장님께 그대로 보여 줄 우리말 안내."""
def _call(method,url,params=None,form=None,token=None):
    """(상태, JSON). 인스타그램 오류는 그대로 돌려준다 (부르는 쪽이 이유를 고른다)."""
    if params:url+='?'+urllib.parse.urlencode(params)
    h={'Authorization':'Bearer '+token} if token else {}
    body=None
    if form is not None:
        if isinstance(form,dict) and any(isinstance(v,dict) for v in form.values()):h['Content-Type']='application/json';body=json.dumps(form).encode()
        else:h['Content-Type']='application/x-www-form-urlencoded';body=urllib.parse.urlencode(form).encode()
    try:return shops.http(method,url,h,body)
    except shops.ShopError:raise IgError('인스타그램에 연결하지 못했어요. 잠시 후 다시 해 주세요.')
def _err(data):
    e=(data or {}).get('error') or {}
    return e if isinstance(e,dict) else {'message':str(e)}

# ---------- 연결 (인스타그램 로그인) ----------
def authorize_url(state):
    return 'https://www.instagram.com/oauth/authorize?'+urllib.parse.urlencode({'client_id':core.secret('IG_APP_ID'),'redirect_uri':redirect_uri(),
        'response_type':'code','scope':SCOPES,'state':state,'enable_fb_login':'0','force_authentication':'1'})
def connect(db,co,code):
    """인증 코드 -> 장기 토큰 -> 계정 확인 -> DM 알림 신청 -> 저장. 안 되면 IgError."""
    s,d=_call('POST','https://api.instagram.com/oauth/access_token',form={'client_id':core.secret('IG_APP_ID'),'client_secret':core.secret('IG_APP_SECRET'),
        'grant_type':'authorization_code','redirect_uri':redirect_uri(),'code':code})
    short=d.get('access_token') if s<400 else None
    if not short:raise IgError(f"인스타그램 인증에 실패했어요 ({clean(_err(d).get('message') or d.get('error_message') or s,100)}).")
    s,d=_call('GET','https://graph.instagram.com/access_token',{'grant_type':'ig_exchange_token','client_secret':core.secret('IG_APP_SECRET'),'access_token':short})
    tok=d.get('access_token') if s<400 else None
    if not tok:raise IgError('인스타그램 장기 토큰을 받지 못했어요. 다시 연결해 주세요.')
    s,me=_call('GET',GRAPH+'/me',{'fields':'user_id,username'},token=tok)
    ig_id=str(me.get('user_id') or '') if s<400 else ''
    if not ig_id:raise IgError('인스타그램 계정을 확인하지 못했어요. 프로페셔널(비즈니스·크리에이터) 계정인지 확인해 주세요.')
    other=db.execute('SELECT company_id FROM ig_links WHERE ig_id=? AND company_id!=?',(ig_id,co['id'])).fetchone()
    if other:raise IgError('이 인스타그램 계정은 다른 회사에 이미 연결돼 있어요.')
    s,d=_call('POST',GRAPH+'/me/subscribed_apps',{'subscribed_fields':'messages'},form={},token=tok)
    if s>=400 or not d.get('success',True):raise IgError('DM 알림을 신청하지 못했어요. 인스타그램 앱에서 메시지 접근 허용을 켜고 다시 연결해 주세요.')
    username=clean(me.get('username'),60)
    db.execute('''INSERT INTO ig_links(company_id,ig_id,username,creds,status,note,refreshed,created) VALUES(?,?,?,?,'ok','',?,?)
        ON CONFLICT(company_id) DO UPDATE SET ig_id=excluded.ig_id,username=excluded.username,creds=excluded.creds,status='ok',note='',refreshed=excluded.refreshed''',
        (co['id'],ig_id,username,shops.seal({'token':tok}),core.iso(),core.iso()))
    return username
def token(db,lk):
    c=shops.unseal(lk['creds']) if lk else None
    return (c or {}).get('token')
def refresh_all():
    """cron: 장기 토큰(60일)을 30일마다 새로 바꾼다. 안 되면 '확인 필요'로 두고 사장님께 한 번 알린다."""
    n=0;cut=core.iso(core.now()-datetime.timedelta(days=REFRESH_DAYS))
    with conn() as db:rows=db.execute("SELECT l.*,c.name co_name FROM ig_links l JOIN companies c ON c.id=l.company_id WHERE l.status='ok' AND l.refreshed<?",(cut,)).fetchall()
    for lk in rows:
        with conn() as db:tok=token(db,lk)
        try:
            s,d=_call('GET','https://graph.instagram.com/refresh_access_token',{'grant_type':'ig_refresh_token','access_token':tok or ''})
            new=d.get('access_token') if s<400 else None
        except IgError:continue  # 다음 cron에서 다시
        with conn() as db:
            if new:db.execute('UPDATE ig_links SET creds=?,refreshed=? WHERE company_id=?',(shops.seal({'token':new}),core.iso(),lk['company_id']));n+=1
            else:
                fail(db,lk['company_id'],'인스타그램 연결이 끊겼어요. 다시 연결해 주세요.')
    return n
def fail(db,cid,msg):
    lk=link(db,cid)
    db.execute("UPDATE ig_links SET status='error',note=? WHERE company_id=?",(msg,cid))
    if lk and lk['status']=='ok':core.notify_company_link_broken(core.company(db,cid),'인스타그램 DM',msg,'/connect/instagram')  # 처음 끊겼을 때만

# ---------- DM 받기 ----------
def signature_ok(raw,header):
    sec=core.secret('IG_APP_SECRET')
    if not sec or not header or not header.startswith('sha256='):return False
    return hmac.compare_digest(header[7:],hmac.new(sec.encode(),raw,hashlib.sha256).hexdigest())
def take(db,co,lk,ev):
    """메시지 하나 -> 새 요청 또는 이어 붙이기. -> 새 요청 row 또는 None"""
    msg=ev.get('message') or {}
    sender=str((ev.get('sender') or {}).get('id') or '');mid=str(msg.get('mid') or '')
    if not sender or not mid or msg.get('is_echo') or msg.get('is_deleted') or sender==lk['ig_id']:return None
    if db.execute('SELECT 1 FROM shop_seen WHERE company_id=? AND shop=? AND ext_id=?',(co['id'],SHOP,'m:'+mid)).fetchone():return None
    text=clean(msg.get('text'),core.BIG).strip() or NO_TEXT
    r=db.execute('SELECT case_id FROM shop_seen WHERE company_id=? AND shop=? AND ext_id=? ORDER BY rowid DESC LIMIT 1',(co['id'],SHOP,'u:'+sender)).fetchone()
    c=db.execute('SELECT * FROM cases WHERE id=?',(r['case_id'],)).fetchone() if r else None
    name=''
    if not (c and c['status'] not in core.FINAL):  # 새 요청이면 이름을 먼저 묻는다 (DB에 쓰기 전에: 기다리는 동안 DB를 잠그지 않게)
        try:
            s,d=_call('GET',GRAPH+'/'+urllib.parse.quote(sender),{'fields':'username,name'},token=token(db,lk))
            if s<400:name=clean(d.get('username') or d.get('name'),20)
        except IgError:pass
    db.execute('UPDATE ig_links SET last_in=? WHERE company_id=?',(core.iso(),co['id']))
    if c and c['status'] not in core.FINAL:  # 같은 고객의 진행 중인 요청에 이어 붙인다
        core.add_event(db,c['id'],'me',text);core.notify_company_msg(db,c['id'],text)
        if c['status'] in ('answered','info'):db.execute("UPDATE cases SET status='seen' WHERE id=?",(c['id'],))
        db.execute('UPDATE cases SET updated=? WHERE id=?',(core.iso(),c['id']))
        db.execute('INSERT INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)',(co['id'],SHOP,'m:'+mid,c['id']))
        return None
    from werkzeug.security import generate_password_hash
    import datetime as _d
    title=clean(' '.join(text.split()),40)
    cat=core.classify(text) or '기타';t=core.iso();due=core.iso(core.now()+_d.timedelta(days=core.REPLY_DAYS))
    cid=db.execute('''INSERT INTO cases(no,company_id,company_name,member,category,title,body,want,order_no,name,phone,email,lookup_hash,consent,status,decision,due,created,updated,product,received_on,channel)
        VALUES(?,?,?,1,?,?,?,?,'',?,'','',?,1,'forwarded','pending',?,?,?,'','',?)''',(core.new_case_no(db),co['id'],co['name'],cat,title,text,core.WANT_OF.get(cat,'기타'),
        name,generate_password_hash(secrets.token_hex(16)),due,t,t,CHANNEL)).lastrowid
    core.add_event(db,cid,'sys','인스타그램 DM을 가져왔어요'+(f' (@{name})' if name else ''))
    db.execute('INSERT INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)',(co['id'],SHOP,'u:'+sender,cid))
    db.execute('INSERT INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)',(co['id'],SHOP,'m:'+mid,cid))
    db.execute('UPDATE ig_links SET n_inq=n_inq+1 WHERE company_id=?',(co['id'],))
    c=db.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
    import workflow;workflow.on_new(db,core.company(db,co['id']),c)
    return db.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
def _why(fmt,*a):
    try:current_app.logger.warning('인스타그램 웹훅 '+fmt,*a)
    except RuntimeError:pass  # 요청 밖(테스트·스크립트)
def receive(payload):
    """웹훅 본문 -> 새 요청 수."""
    new=[]
    if payload.get('object')!='instagram':_why('object=%s',clean(str(payload.get('object')),30))
    for ent in (payload.get('entry') or []) if payload.get('object')=='instagram' else []:
        evs=ent.get('messaging') or []
        # 왜 요청이 안 생겼는지 서버 기록으로 알 수 있게, 메시지 내용 없이 id와 종류만 남긴다
        _why('entry=%s events=%d kinds=%s changes=%s',clean(str(ent.get('id')),40),len(evs),','.join(sorted({k for ev in evs for k in ev if k not in ('sender','recipient','timestamp')})) or '-',
             ','.join(sorted({str(ch.get('field')) for ch in ent.get('changes') or []})) or '-')
        with conn() as db:
            lk=db.execute("SELECT * FROM ig_links WHERE ig_id=? AND status='ok'",(str(ent.get('id') or ''),)).fetchone()
            co=core.company(db,lk['company_id']) if lk else None
            if not lk:_why('연결된 계정 없음: entry=%s',clean(str(ent.get('id')),40));continue
            if not co or not co['member'] or co['status']!='active':_why('입점 회사가 아님: company=%s',lk['company_id']);continue
            for ev in evs:
                try:c=take(db,co,lk,ev)
                except Exception:traceback.print_exc();c=None  # 이상한 메시지 하나 때문에 멈추지 않는다
                if c:new.append((co,c))
    for co,c in new[:5]:core.notify_company_new(co,c)
    return len(new)

# ---------- 답변 보내기 (사람이 눌렀을 때만) ----------
def post_reply(db,co,c,text):
    """인스타그램 DM으로 답한다. 보내면 '', 못 보내면 이유."""
    lk=link(db,co['id']);tok=token(db,lk) if lk else None
    if not tok:return '인스타그램 연결이 끊겼어요. 서비스 연동에서 다시 연결해 주세요.'
    text=(text or '').strip()
    if len(text)<2:return '답변 내용이 너무 짧아요.'
    r=db.execute("SELECT ext_id FROM shop_seen WHERE company_id=? AND shop=? AND case_id=? AND ext_id LIKE 'u:%' LIMIT 1",(co['id'],SHOP,c['id'])).fetchone()
    if not r:return '인스타그램에서 가져온 대화가 아니에요.'
    try:s,d=_call('POST',GRAPH+'/me/messages',form={'recipient':{'id':r['ext_id'][2:]},'message':{'text':text[:1000]}},token=tok)
    except IgError as e:return str(e)
    if s>=400 or not d.get('message_id'):
        e=_err(d)
        if e.get('error_subcode')==2534022 or e.get('code')==10:return '고객이 마지막으로 보낸 지 24시간이 지나서 보낼 수 없어요. 인스타그램 앱에서 답해 주세요.'
        if e.get('code')==190:fail(db,co['id'],'인스타그램 연결이 끊겼어요. 다시 연결해 주세요.');return '인스타그램 연결이 끊겼어요. 서비스 연동에서 다시 연결해 주세요.'
        return f"인스타그램이 보내지 않았어요 ({clean(e.get('message') or s,100)})."
    db.execute('UPDATE ig_links SET n_sent=n_sent+1 WHERE company_id=?',(co['id'],))
    return ''

# ---------- 화면 ----------
def company():
    import business
    co=business.me()
    if not co:abort(403)
    return co

@bp.route('/hook/instagram',methods=['GET','POST'])
def hook():
    if request.method=='GET':  # 메타가 콜백 주소를 확인할 때
        tok=core.secret('IG_VERIFY_TOKEN')
        if request.args.get('hub.mode')=='subscribe' and tok and hmac.compare_digest(request.args.get('hub.verify_token',''),tok):
            return request.args.get('hub.challenge',''),200,{'Content-Type':'text/plain'}
        abort(403)
    raw=request.get_data(cache=False)
    if not signature_ok(raw,request.headers.get('X-Hub-Signature-256','')):abort(403)
    try:payload=json.loads(raw.decode() or '{}')
    except ValueError:abort(400)
    receive(payload)
    return jsonify(ok=True)

@bp.route('/connect/instagram',methods=['GET','POST'])
def page():
    if not session.get('co_id'):return redirect(url_for('login'))
    co=company()
    if request.method=='POST':
        act=request.form.get('act','connect')
        if act=='delete':
            with conn() as db:db.execute('DELETE FROM ig_links WHERE company_id=?',(co['id'],))
            flash('인스타그램 연결을 끊었어요. 저장한 토큰도 지웠어요. 인스타그램 설정 > 앱 및 웹사이트에서 소보루를 지우면 권한도 완전히 거둬져요.','ok')
        elif not ready():flash('인스타그램 연결은 소보루가 메타 앱 준비를 마치면 열려요.','error')
        elif not co['member']:flash('인스타그램 연결은 실제 고객 정보를 가져오는 일이라 회사 인증이 끝난 뒤에 할 수 있어요.','error')
        else:
            nonce=secrets.token_urlsafe(12);session['ig_nonce']=nonce
            return redirect(authorize_url(core.signer('ig').dumps({'co':co['id'],'n':nonce})))
        return redirect(url_for('ig.page'))
    with conn() as db:lk=link(db,co['id'])
    return render_template('b_ig.html',lk=lk,ready=ready(),tab='connect')

@bp.route('/connect/instagram/callback')
def callback():
    if not session.get('co_id'):return redirect(url_for('login'))
    co=company()
    try:st=core.signer('ig').loads(request.args.get('state',''),max_age=900)
    except Exception:st=None
    nonce=session.pop('ig_nonce',None)
    if not st or st.get('co')!=co['id'] or not nonce or st.get('n')!=nonce:
        flash('연결 요청이 만료됐거나 다른 브라우저에서 왔어요. 다시 연결해 주세요.','error');return redirect(url_for('ig.page'))
    if request.args.get('error'):
        current_app.logger.warning('인스타그램 연결 거절: %s %s',clean(request.args.get('error'),60),clean(request.args.get('error_description'),200))
        flash('인스타그램에서 권한 동의를 취소했어요. 다시 연결하려면 권한에 동의해 주세요.','error');return redirect(url_for('ig.page'))
    code=request.args.get('code','').removesuffix('#_')
    if not code:flash('인스타그램이 인증 코드를 보내지 않았어요. 다시 해 주세요.','error');return redirect(url_for('ig.page'))
    try:
        with conn() as db:name=connect(db,co,code)
    except IgError as e:flash(str(e),'error');return redirect(url_for('ig.page'))
    flash(f'인스타그램(@{name})에 연결했어요. 이제 새 DM이 요청으로 들어와요.','ok')
    return redirect(url_for('ig.page'))
