"""카페24 연결 (OAuth 2.0). 소보루가 카페24 개발자센터에 앱을 등록하고 키(CAFE24_CLIENT_ID·SECRET)를 넣기 전까지는 '연동 대기'.

  · 사장님이 쇼핑몰 아이디(mall_id)를 넣으면 카페24 로그인·권한 동의 화면으로 보낸다 -> 돌아오면 토큰을 암호화해 저장.
  · 접근 토큰은 2시간, 갱신 토큰은 2주. 쓸 때마다 만료 5분 전이면 갱신하고, 갱신 토큰도 새로 바뀐다(카페24 방식).
  · 갱신이 안 되면(2주 넘게 안 썼거나 앱 삭제) '다시 연결 필요'로 바꾸고 사장님께 다시 연결을 안내한다.
  · 문의 게시판 가져오기·답변 올리기는 카페24 앱 심사에서 권한을 받은 뒤 켠다. 지금은 연결 확인(쇼핑몰 정보 읽기)과 주문 가져오기까지.
문서: developers.cafe24.com > Admin API > Authentication
"""
import base64, datetime, json, re, secrets, urllib.parse
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session, current_app
import core, shops, orders
from core import conn, clean, digits

bp=Blueprint('c24',__name__)
SCOPES='mall.read_store,mall.read_order'
MALL_RE=re.compile(r'^[a-z0-9][a-z0-9-]{2,29}$')

def init():
    with conn() as db:db.executescript('''CREATE TABLE IF NOT EXISTS cafe24_links(company_id INTEGER PRIMARY KEY,mall_id TEXT NOT NULL,creds TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ok',note TEXT NOT NULL DEFAULT '',shop_name TEXT NOT NULL DEFAULT '',scopes TEXT NOT NULL DEFAULT '',
        expires TEXT NOT NULL DEFAULT '',refresh_expires TEXT NOT NULL DEFAULT '',synced TEXT NOT NULL DEFAULT '',since TEXT NOT NULL DEFAULT '',n_ord INTEGER NOT NULL DEFAULT 0,
        created TEXT NOT NULL,FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE)''')
init()

def ready():return bool(core.secret('CAFE24_CLIENT_ID') and core.secret('CAFE24_CLIENT_SECRET'))
def redirect_uri():return core.site_url('biz','/connect/cafe24/callback') or url_for('c24.callback',_external=True)
def base(mall):return f'https://{mall}.cafe24api.com/api/v2'
def link(db,cid):return db.execute('SELECT * FROM cafe24_links WHERE company_id=?',(cid,)).fetchone()

def authorize_url(mall,state):
    q={'response_type':'code','client_id':core.secret('CAFE24_CLIENT_ID'),'state':state,'redirect_uri':redirect_uri(),'scope':SCOPES}
    return base(mall)+'/oauth/authorize?'+urllib.parse.urlencode(q)

def _token(mall,body):
    """토큰 요청 (발급·갱신 공용). 카페24 응답 dict 또는 ShopError."""
    auth=base64.b64encode(f"{core.secret('CAFE24_CLIENT_ID')}:{core.secret('CAFE24_CLIENT_SECRET')}".encode()).decode()
    code,data=shops.http('POST',base(mall)+'/oauth/token',{'Authorization':'Basic '+auth,'Content-Type':'application/x-www-form-urlencoded'},urllib.parse.urlencode(body).encode())
    if code>=400 or not data.get('access_token'):
        err=str(data.get('error_description') or data.get('error') or code)[:120]
        raise shops.ShopError(f'카페24 인증에 실패했어요 ({err}).')
    return data
def _parse_exp(v):
    p=core.parse(str(v or '')[:19].replace('T',' '))
    return core.iso(p) if p else ''
def store(db,cid,mall,data):
    creds={'mall_id':mall,'access_token':data['access_token'],'refresh_token':data.get('refresh_token','')}
    db.execute('''INSERT INTO cafe24_links(company_id,mall_id,creds,status,note,scopes,expires,refresh_expires,created) VALUES(?,?,?,'ok','',?,?,?,?)
        ON CONFLICT(company_id) DO UPDATE SET mall_id=excluded.mall_id,creds=excluded.creds,status='ok',note='',scopes=excluded.scopes,expires=excluded.expires,refresh_expires=excluded.refresh_expires''',
        (cid,mall,shops.seal(creds),','.join(data.get('scopes') or []) if isinstance(data.get('scopes'),list) else str(data.get('scopes') or ''),
         _parse_exp(data.get('expires_at')),_parse_exp(data.get('refresh_token_expires_at')),core.iso()))

def access_token(db,cid):
    """쓸 수 있는 접근 토큰. 만료가 가까우면 갱신한다. 안 되면 연결 상태를 '다시 연결'로 바꾸고 ShopError."""
    lk=link(db,cid)
    if not lk:raise shops.ShopError('카페24가 연결되어 있지 않아요.')
    creds=shops.unseal(lk['creds'])
    if not creds:
        db.execute("UPDATE cafe24_links SET status='reconnect',note=? WHERE company_id=?",('저장한 연결 정보를 읽지 못했어요.',cid));raise shops.ShopError('카페24를 다시 연결해 주세요.')
    exp=core.parse(lk['expires'])
    if exp and exp>core.now()+datetime.timedelta(minutes=5):return lk['mall_id'],creds['access_token']
    try:data=_token(lk['mall_id'],{'grant_type':'refresh_token','refresh_token':creds['refresh_token']})
    except shops.ShopError:
        db.execute("UPDATE cafe24_links SET status='reconnect',note=? WHERE company_id=?",('연결이 만료됐어요. 다시 연결해 주세요.',cid))
        if lk['status']=='ok':core.notify_company_link_broken(core.company(db,cid),'카페24','연결이 만료됐어요','/connect/cafe24')
        raise shops.ShopError('카페24 연결이 만료됐어요. 다시 연결해 주세요.')
    store(db,cid,lk['mall_id'],data)
    return lk['mall_id'],data['access_token']

def api(db,cid,path,params=None):
    mall,tok=access_token(db,cid)
    url=base(mall)+path+('?'+urllib.parse.urlencode(params) if params else '')
    code,data=shops.http('GET',url,{'Authorization':'Bearer '+tok,'Content-Type':'application/json'})
    if code==401:
        db.execute("UPDATE cafe24_links SET status='reconnect',note=? WHERE company_id=?",('카페24가 접근을 거절했어요. 앱 권한을 확인하고 다시 연결해 주세요.',cid))
        raise shops.ShopError('카페24가 접근을 거절했어요. 다시 연결해 주세요.')
    if code==403:raise shops.ShopError('이 기능에 필요한 카페24 권한이 없어요. 다시 연결하면서 권한에 동의해 주세요.')
    if code==429:raise shops.ShopError('카페24가 잠시 요청을 막았어요. 몇 분 뒤 다시 해 주세요.')
    if code>=400:raise shops.ShopError(f'카페24가 요청을 거절했어요 ({code}).')
    return data

C_STATUS={'N00':'paid','N10':'paid','N20':'ready','N21':'ready','N22':'ready','N30':'shipped','N40':'delivered',
          'C00':'canceled','C10':'canceled','C34':'canceled','C40':'canceled','R00':'returned','R10':'returned','R40':'returned','E00':'exchanged','E40':'exchanged'}
def sync_orders(db,co):
    """카페24 주문 -> 주문 장부 (채널 '자사몰'). 넣거나 고친 수."""
    lk=link(db,co['id']);now=core.now()
    frm=(core.parse(lk['since']) if lk['since'] else now-datetime.timedelta(days=shops.FIRST_DAYS))-datetime.timedelta(minutes=10)
    n=0;offset=0
    while offset<5000:
        d=api(db,co['id'],'/admin/orders',{'start_date':frm.strftime('%Y-%m-%d'),'end_date':now.strftime('%Y-%m-%d'),'embed':'items,receivers','limit':100,'offset':offset})
        rows=d.get('orders') or []
        for o in rows:
            items=o.get('items') or [];rc=(o.get('receivers') or [{}])[0]
            st=C_STATUS.get(str((items[0] if items else {}).get('order_status') or ''),'paid')
            names=[i.get('product_name') or '' for i in items]
            n+=shops._order(db,co,'cafe24',dict(channel='자사몰',order_no=str(o.get('order_id','')),ordered_on=str(o.get('order_date') or '')[:10],buyer=o.get('billing_name') or rc.get('name') or '',
                phone=digits(rc.get('cellphone') or rc.get('phone') or ''),address=' '.join(x for x in (rc.get('address1'),rc.get('address2')) if x),
                product=(names[0] if names else '')+(f' 외 {len(names)-1}건' if len(names)>1 else ''),qty=sum(int(i.get('quantity') or 0) for i in items) or 1,
                amount=int(float(o.get('actual_payment_amount') or o.get('payment_amount') or 0)),status=st,
                courier=shops.courier_of((items[0] if items else {}).get('shipping_company_name')),invoice=digits((items[0] if items else {}).get('tracking_no') or '')))
        if len(rows)<100:break
        offset+=100
    db.execute("UPDATE cafe24_links SET status='ok',note='',synced=?,since=?,n_ord=n_ord+? WHERE company_id=?",(core.iso(now),core.iso(now),n,co['id']))
    return n

def sync_all():
    """cron: 연결된 카페24 쇼핑몰의 주문. 키가 없으면 아무것도 안 한다."""
    if not ready():return 0
    n=0
    with conn() as db:rows=db.execute("SELECT c.* FROM cafe24_links l JOIN companies c ON c.id=l.company_id WHERE l.status='ok' AND c.member=1 AND c.status='active'").fetchall()
    for co in rows:
        try:
            with conn() as db:n+=sync_orders(db,co)
        except shops.ShopError:pass
    return n

# ---------- 화면 ----------
def company():
    import business
    co=business.me()
    if not co:abort(403)
    return co

@bp.route('/connect/cafe24',methods=['GET','POST'])
def page():
    if not session.get('co_id'):return redirect(url_for('login'))
    co=company()
    if request.method=='POST':
        act=request.form.get('act','connect')
        with conn() as db:
            if act=='delete':
                db.execute('DELETE FROM cafe24_links WHERE company_id=?',(co['id'],));flash('카페24 연결을 끊었어요. 저장한 연결 정보도 지웠어요. 카페24 관리자 > 앱에서 소보루 앱을 지우면 권한도 완전히 거둬져요.','ok')
            elif act=='sync':
                try:n=sync_orders(db,co);flash(f'주문 {n}건을 가져왔어요','ok')
                except shops.ShopError as e:flash(str(e),'error')
            elif act=='check':
                try:
                    d=api(db,co['id'],'/admin/store');name=clean((d.get('store') or {}).get('shop_name') or (d.get('store') or {}).get('mall_name'),60)
                    db.execute('UPDATE cafe24_links SET shop_name=? WHERE company_id=?',(name,co['id']));flash(f'연결이 잘 돼 있어요{": "+name if name else ""}','ok')
                except shops.ShopError as e:flash(str(e),'error')
            else:
                if not ready():flash('카페24 연결은 소보루가 카페24 앱 등록을 마치면 열려요.','error')
                elif not co['member']:flash('판매처 연결은 실제 고객 정보를 가져오는 일이라 회사 인증이 끝난 뒤에 할 수 있어요.','error')
                else:
                    mall=clean(request.form.get('mall_id'),40).lower().removesuffix('.cafe24.com')
                    if not MALL_RE.match(mall):flash('카페24 쇼핑몰 아이디를 확인해 주세요 (관리자 로그인 아이디, 예: myshop)','error')
                    else:
                        nonce=secrets.token_urlsafe(12);session['c24_nonce']=nonce
                        state=core.signer('c24').dumps({'co':co['id'],'mall':mall,'n':nonce})
                        return redirect(authorize_url(mall,state))
        return redirect(url_for('c24.page'))
    with conn() as db:lk=link(db,co['id'])
    return render_template('b_cafe24.html',lk=lk,ready=ready(),redirect_uri=redirect_uri(),scopes=SCOPES,tab='connect')

@bp.route('/connect/cafe24/callback')
def callback():
    if not session.get('co_id'):return redirect(url_for('login'))
    co=company()
    try:st=core.signer('c24').loads(request.args.get('state',''),max_age=900)
    except Exception:st=None
    nonce=session.pop('c24_nonce',None)
    if not st or st.get('co')!=co['id'] or not nonce or st.get('n')!=nonce:
        flash('연결 요청이 만료됐거나 다른 브라우저에서 왔어요. 다시 연결해 주세요.','error');return redirect(url_for('c24.page'))
    err=clean(request.args.get('error',''),60)
    if err:
        # 카페24가 돌려준 실제 이유를 보여 줌 (동의 취소만이 아니라 권한·앱 설정 문제도 같은 길로 옴)
        desc=clean(request.args.get('error_description',''),200)
        current_app.logger.warning('카페24 연결 거절: %s %s',err,desc)
        if err=='access_denied' and not desc:msg='카페24에서 권한 동의를 취소했어요. 다시 연결하려면 권한에 동의해 주세요.'
        else:msg=f'카페24가 연결을 거절했어요 ({err}{": "+desc if desc else ""}). 카페24 앱의 권한(Scope)과 설정을 확인해 주세요.'
        flash(msg,'error');return redirect(url_for('c24.page'))
    code=request.args.get('code','')
    if not code:flash('카페24가 인증 코드를 보내지 않았어요. 다시 해 주세요.','error');return redirect(url_for('c24.page'))
    try:data=_token(st['mall'],{'grant_type':'authorization_code','code':code,'redirect_uri':redirect_uri()})
    except shops.ShopError as e:flash(str(e),'error');return redirect(url_for('c24.page'))
    with conn() as db:
        store(db,co['id'],st['mall'],data)
        try:sync_orders(db,co)
        except shops.ShopError:pass
    flash(f"카페24({st['mall']})에 연결했어요. 주문을 가져올게요.",'ok')
    return redirect(url_for('c24.page'))
