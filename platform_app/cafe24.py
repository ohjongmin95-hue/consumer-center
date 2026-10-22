"""카페24 연결 (OAuth 2.0). 소보루가 카페24 개발자센터에 앱을 등록하고 키(CAFE24_CLIENT_ID·SECRET)를 넣기 전까지는 '연동 대기'.

  · 사장님이 쇼핑몰 아이디(mall_id)를 넣으면 카페24 로그인·권한 동의 화면으로 보낸다 -> 돌아오면 토큰을 암호화해 저장.
  · 접근 토큰은 2시간, 갱신 토큰은 2주. 쓸 때마다 만료 5분 전이면 갱신하고, 갱신 토큰도 새로 바뀐다(카페24 방식).
  · 갱신이 안 되면(2주 넘게 안 썼거나 앱 삭제) '다시 연결 필요'로 바꾸고 사장님께 다시 연결을 안내한다.
  · 주문 가져오기, 문의 게시판(Q&A·1:1 상담) 글 가져오기 -> 소보루 요청, 소보루에서 쓴 답변을 게시판 답글로 올리기.
  · 상품 가져오기 -> 상품정보 (이름·가격·판매 상태·요약 설명). 상품 문의 글엔 상품 이름을 붙인다. 사장님이 고친 안내는 덮지 않는다.
  · 취소·반품: 사장님(대표·관리자)이 주문 화면에서 누를 때만 카페24에 보낸다. 같은 주문은 한 번만 (cafe24_actions 잠금).
문서: apidocs.cafe24.com > Admin API (Authentication, order/cancellation, return, community/boards)
시험 운영: 문서대로 만들었고, 실제 쇼핑몰로는 OH 시험 쇼핑몰에서 먼저 확인한다.
"""
import base64, datetime, hashlib, hmac as _hmac, html, json, logging, os, re, secrets, threading, time, urllib.parse
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session, current_app
import core, shops, orders
from core import conn, clean, digits

bp=Blueprint('c24',__name__);log=logging.getLogger('cafe24')
SCOPES='mall.read_store,mall.read_product,mall.read_order,mall.write_order,mall.read_community,mall.write_community'
PAY_SCOPES='mall.read_application,mall.write_application'  # 앱 결제(앱스토어 주문). 카페24 앱 권한에 넣은 뒤 운영 > 요금제에서 켠다
def scopes():
    """연결할 때 받을 권한. 카페24 앱 결제를 켰으면 결제 권한도 (카페24 앱 등록에 없는 권한을 달라면 연결이 거절돼서 켜야만 넣는다)."""
    import billing
    return SCOPES+(','+PAY_SCOPES if billing.c24_on() else '')
SCOPE_NAMES={'store':'상점','order':'주문','community':'게시판','customer':'회원','product':'상품','application':'앱 결제'}
def scope_text(scopes):
    """'mall.read_order,mall.write_order' -> '주문 읽기·쓰기'"""
    got={}
    for x in str(scopes or '').replace(' ','').split(','):
        m=re.fullmatch(r'mall\.(read|write)_(\w+)',x)
        if m:got.setdefault(m[2],set()).add(m[1])
    return ', '.join(f"{SCOPE_NAMES.get(k,k)} {'읽기·쓰기' if v=={'read','write'} else '쓰기' if v=={'write'} else '읽기'}" for k,v in got.items())
BOARD_RE=re.compile(r'q\s*&?\s*a|문의|상담',re.I)  # 처음 연결할 때 알아서 고르는 게시판 (사장님이 바꿀 수 있다)
MALL_RE=re.compile(r'^[a-z0-9][a-z0-9-]{2,29}$')

def init():
    with conn() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS cafe24_links(company_id INTEGER PRIMARY KEY,mall_id TEXT NOT NULL,creds TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ok',note TEXT NOT NULL DEFAULT '',shop_name TEXT NOT NULL DEFAULT '',scopes TEXT NOT NULL DEFAULT '',
        expires TEXT NOT NULL DEFAULT '',refresh_expires TEXT NOT NULL DEFAULT '',synced TEXT NOT NULL DEFAULT '',since TEXT NOT NULL DEFAULT '',n_ord INTEGER NOT NULL DEFAULT 0,
        created TEXT NOT NULL,FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS cafe24_actions(company_id INTEGER NOT NULL,order_no TEXT NOT NULL,kind TEXT NOT NULL,state TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',
          actor TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,PRIMARY KEY(company_id,order_no,kind),FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE)''')
        cols={r[1] for r in db.execute('PRAGMA table_info(cafe24_links)')}
        for col,kind in (('boards',"TEXT NOT NULL DEFAULT ''"),('since_b',"TEXT NOT NULL DEFAULT ''"),('n_inq','INTEGER NOT NULL DEFAULT 0'),
                         ('synced_p',"TEXT NOT NULL DEFAULT ''"),('n_prod','INTEGER NOT NULL DEFAULT 0'),('full_o',"TEXT NOT NULL DEFAULT ''")):
            if col not in cols:db.execute(f'ALTER TABLE cafe24_links ADD COLUMN {col} {kind}')
        pc={r[1] for r in db.execute('PRAGMA table_info(products)')}
        for col in ('src','ext_id','src_info','image','url'):  # src 'cafe24' + 카페24 상품번호. src_info: 마지막으로 카페24에서 받은 안내 (사장님이 고쳤는지 보려고). image·url: 목록 사진과 쇼핑몰 상품 주소
            if col not in pc:db.execute(f"ALTER TABLE products ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        if 'src' not in {r[1] for r in db.execute('PRAGMA table_info(orders)')}:db.execute("ALTER TABLE orders ADD COLUMN src TEXT NOT NULL DEFAULT ''")  # 'cafe24': 카페24에서 가져온 주문
init()

def ready():return bool(core.secret('CAFE24_CLIENT_ID') and core.secret('CAFE24_CLIENT_SECRET'))
def redirect_uri():return core.site_url('biz','/connect/cafe24/callback') or url_for('c24.callback',_external=True)
def base(mall):return f'https://{mall}.cafe24api.com/api/v2'
def link(db,cid):return db.execute('SELECT * FROM cafe24_links WHERE company_id=?',(cid,)).fetchone()

def authorize_url(mall,state):
    q={'response_type':'code','client_id':core.secret('CAFE24_CLIENT_ID'),'state':state,'redirect_uri':redirect_uri(),'scope':scopes()}
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
    old=link(db,cid)
    if old and old['mall_id']!=mall:  # 다른 쇼핑몰로 바꿔 연결: 글 번호가 겹치지 않게 본 글 기록과 가져온 때를 비운다 (이미 만든 요청은 그대로)
        db.execute("DELETE FROM shop_seen WHERE company_id=? AND shop='cafe24'",(cid,))
        db.execute("UPDATE cafe24_links SET since='',since_b='',full_o='',synced_p='',boards='',created=? WHERE company_id=?",(core.iso(),cid))
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
    fresh=lambda r:(core.parse(r['expires']) or core.now())>core.now()+datetime.timedelta(minutes=5)
    if fresh(lk):return lk['mall_id'],creds['access_token']
    # 갱신 토큰은 한 번 쓰면 바뀐다(카페24). 새 토큰을 잃으면 연결이 끊기므로: 다른 작업(cron·화면·AI 답변)과 겹치지 않게 잠그고,
    # 그사이 누가 갱신했으면 그 토큰을 쓰고, 받은 토큰은 그 자리에서 저장(커밋)한다. 뒤의 API 호출이 실패해도 되돌리지 않는다
    db.commit();db.execute('BEGIN IMMEDIATE')
    try:
        lk=link(db,cid);creds=shops.unseal(lk['creds']) or creds
        if fresh(lk):db.commit();return lk['mall_id'],creds['access_token']
        try:data=_token(lk['mall_id'],{'grant_type':'refresh_token','refresh_token':creds['refresh_token']})
        except shops.ShopError:
            db.execute("UPDATE cafe24_links SET status='reconnect',note=? WHERE company_id=?",('연결이 만료됐어요. 다시 연결해 주세요.',cid));db.commit()
            if lk['status']=='ok':core.notify_company_link_broken(core.company(db,cid),'카페24','연결이 만료됐어요','/connect/cafe24')
            raise shops.ShopError('카페24 연결이 만료됐어요. 다시 연결해 주세요.')
        store(db,cid,lk['mall_id'],data);db.commit()
    except BaseException:
        if db.in_transaction:db.commit()
        raise
    return lk['mall_id'],data['access_token']

def api(db,cid,path,params=None,method='GET',payload=None):
    mall,tok=access_token(db,cid)
    url=base(mall)+path+('?'+urllib.parse.urlencode(params) if params else '')
    code,data=shops.http(method,url,{'Authorization':'Bearer '+tok,'Content-Type':'application/json'},json.dumps(payload).encode() if payload is not None else None)
    if code==401:
        db.execute("UPDATE cafe24_links SET status='reconnect',note=? WHERE company_id=?",('카페24가 접근을 거절했어요. 앱 권한을 확인하고 다시 연결해 주세요.',cid))
        raise shops.ShopError('카페24가 접근을 거절했어요. 다시 연결해 주세요.')
    if code==403:raise shops.ShopError('이 기능에 필요한 카페24 권한이 없어요. 다시 연결하면서 권한에 동의해 주세요.')
    if code==429:raise shops.ShopError('카페24가 잠시 요청을 막았어요. 몇 분 뒤 다시 해 주세요.')
    if code>=400:
        msg=str(((data or {}).get('error') or {}).get('message') or '')[:160] if isinstance((data or {}).get('error'),dict) else ''
        raise shops.ShopError(f'카페24가 요청을 거절했어요 ({code}{": "+msg if msg else ""}).')
    return data

C_STATUS={'N00':'paid','N10':'paid','N20':'ready','N21':'ready','N22':'ready','N30':'shipped','N40':'delivered','N50':'delivered',  # N00 입금 전도 '결제 완료'로 둔다 (입금 대기 상태가 따로 없음)
          'C00':'paid','C11':'paid','R00':'delivered','R11':'delivered','R12':'delivered','E00':'delivered','E11':'delivered','E12':'delivered'}  # 신청·거부·보류는 아직 끝난 게 아니다
def status_of(code):
    """카페24 주문 상태 코드 -> 소보루 주문 상태. 취소(C)·반품(R)·교환(E)의 처리 중·완료는 앞글자로."""
    code=str(code or '')
    return C_STATUS.get(code) or {'C':'canceled','R':'returned','E':'exchanged'}.get(code[:1],'paid')
FULL_DAYS=14;FULL_EVERY=datetime.timedelta(hours=1)  # 주문일로만 찾아지므로, 한 시간마다 최근 14일 주문을 다시 읽어 배송·취소 변화를 반영한다
def put_order(db,co,o):
    """카페24 주문 하나(embed=items,receivers) -> 주문 장부. 넣거나 고쳤으면 1."""
    items=o.get('items') or [];rc=(o.get('receivers') or [{}])[0]
    st=status_of((items[0] if items else {}).get('order_status'))
    names=[i.get('product_name') or '' for i in items]
    n=shops._order(db,co,'cafe24',dict(channel='자사몰',order_no=str(o.get('order_id','')),ordered_on=str(o.get('order_date') or '')[:10],buyer=o.get('billing_name') or rc.get('name') or '',
        phone=digits(rc.get('cellphone') or rc.get('phone') or ''),address=' '.join(x for x in (rc.get('address1'),rc.get('address2')) if x),
        product=(names[0] if names else '')+(f' 외 {len(names)-1}건' if len(names)>1 else ''),qty=sum(int(i.get('quantity') or 0) for i in items) or 1,
        amount=int(float(o.get('actual_payment_amount') or o.get('payment_amount') or 0)),status=st,
        courier=shops.courier_of((items[0] if items else {}).get('shipping_company_name')),invoice=digits((items[0] if items else {}).get('tracking_no') or '')))
    db.execute("UPDATE orders SET src='cafe24' WHERE company_id=? AND order_no=? AND src=''",(co['id'],str(o.get('order_id',''))))
    return n
def fetch_order(db,co,order_no):
    """카페24 주문번호 하나를 카페24에서 찾아 주문 장부에 넣고 그 줄을 돌려준다. 없거나 못 읽으면 None."""
    if not re.fullmatch(r'[\w-]{6,30}',order_no or ''):return None
    try:d=api(db,co['id'],'/admin/orders/'+order_no,{'embed':'items,receivers'})
    except shops.ShopError:return None
    o=d.get('order') if isinstance(d.get('order'),dict) else None
    if not o or not o.get('order_id'):return None
    put_order(db,co,o)
    return db.execute('SELECT * FROM orders WHERE company_id=? AND order_no=?',(co['id'],str(o['order_id']))).fetchone()
MEMBER_DAYS=90
def member_order(db,co,member_id):
    """게시판 글쓴이가 쇼핑몰 회원이면 그 회원의 가장 최근 주문번호 (주문 장부에도 넣는다). 없거나 못 찾으면 ''.
    고객이 주문번호를 안 적어도 '배송이 안 와요' 같은 문의에 AI가 그 주문의 상태·송장으로 답할 수 있게."""
    if not member_id:return ''
    now=core.now();db.commit()
    try:d=api(db,co['id'],'/admin/orders',{'member_id':member_id,'start_date':(now-datetime.timedelta(days=MEMBER_DAYS)).strftime('%Y-%m-%d'),'end_date':now.strftime('%Y-%m-%d'),'embed':'items,receivers','limit':20})
    except shops.ShopError:return ''
    rows=[o for o in d.get('orders') or [] if o.get('order_id') and str(o.get('member_id') or member_id)==member_id]
    if not rows:return ''
    o=max(rows,key=lambda x:str(x.get('order_date') or ''));put_order(db,co,o)
    return str(o['order_id'])
def sync_orders(db,co):
    """카페24 주문 -> 주문 장부 (채널 '자사몰'). 넣거나 고친 수."""
    lk=link(db,co['id']);now=core.now()
    frm=(core.parse(lk['since']) if lk['since'] else now-datetime.timedelta(days=shops.FIRST_DAYS))-datetime.timedelta(minutes=10)
    full=bool(lk['since']) and (not lk['full_o'] or now-(core.parse(lk['full_o']) or now)>=FULL_EVERY)
    if full:frm=min(frm,now-datetime.timedelta(days=FULL_DAYS))
    n=0;offset=0
    while offset<5000:
        db.commit()  # 카페24를 기다리는 동안 DB를 잠가 두지 않는다 (그사이 사장님 화면의 저장이 'database is locked'로 실패했다)
        d=api(db,co['id'],'/admin/orders',{'start_date':frm.strftime('%Y-%m-%d'),'end_date':now.strftime('%Y-%m-%d'),'embed':'items,receivers','limit':100,'offset':offset})
        rows=d.get('orders') or []
        for o in rows:n+=put_order(db,co,o)
        if len(rows)<100:break
        offset+=100
    db.execute("UPDATE cafe24_links SET status='ok',note='',synced=?,since=?,n_ord=n_ord+? WHERE company_id=?",(core.iso(now),core.iso(now),n,co['id']))
    if full or not lk['full_o']:db.execute('UPDATE cafe24_links SET full_o=? WHERE company_id=?',(core.iso(now),co['id']))
    return n

# ---------- 상품 ----------
PRODUCT_EVERY=datetime.timedelta(hours=6)  # 자동으로는 6시간마다 ('지금 가져오기'는 바로)
def has_scope(lk,scope):return scope in str(lk['scopes'] or '').replace(' ','').split(',')
def won(v):
    try:n=int(float(str(v or '').replace(',','')))
    except ValueError:return ''
    return f'{n:,}원' if n>0 else ''
def _num(v):
    try:return int(float(str(v or '').replace(',','')))
    except ValueError:return 0
def options_text(p):
    """카페24 옵션(embed=options) -> '색상: 빨강, 파랑 / 사이즈: S, M'. 모양이 달라도 읽을 수 있는 만큼만."""
    o=p.get('options');o=o.get('options') if isinstance(o,dict) else o
    out=[]
    for x in o if isinstance(o,list) else []:
        if not isinstance(x,dict):continue
        vals=x.get('option_value') or x.get('option_values') or []
        vals=[clean(str(v.get('value_name') or v.get('option_text') or v.get('name') or '') if isinstance(v,dict) else str(v),30) for v in (vals if isinstance(vals,list) else [vals])]
        name=clean(str(x.get('option_name') or x.get('name') or ''),20);vals=[v for v in vals if v][:15]
        if name and vals:out.append(f"{name}: {', '.join(vals)}")
    return ' / '.join(out)
def product_info(p):
    """카페24 상품 -> 상담에 쓰는 안내 글: 요약·간단 설명, 정가(할인 중이면), 옵션, 모델명, 검색어, 상세 설명의 글자 부분(대부분 이미지라 있을 때만)."""
    bits=[]
    for k in ('summary_description','simple_description'):
        t=text_of(p.get(k))
        if t and t not in bits:bits.append(t)
    if _num(p.get('retail_price'))>_num(p.get('price'))>0:bits.append(f"정가 {won(p.get('retail_price'))} (지금 {won(p.get('price'))})")
    opt=options_text(p)
    if opt:bits.append('옵션 '+opt)
    if p.get('model_name'):bits.append('모델명 '+clean(str(p['model_name']),40))
    tags=p.get('product_tag');tags=', '.join(tags) if isinstance(tags,list) else str(tags or '')
    if tags.strip():bits.append('검색어 '+clean(tags,120))
    d=text_of(p.get('description'))
    if len(d)>=10:bits.append('상세 설명: '+d[:1200])
    return clean('\n'.join(bits),2000)
def product_url(mall,no):return f'https://{mall}.cafe24.com/product/detail.html?product_no={no}'
def product_image(p):
    u=str(p.get('list_image') or p.get('small_image') or p.get('tiny_image') or '')
    return u if u.startswith('https://') else ('https:'+u if u.startswith('//') else '')
def sync_products(db,co,force=False):
    """카페24 상품 -> 상품정보. 이름·가격·판매 상태는 카페24 기준, 안내는 사장님이 고치지 않았을 때만 바꾼다. 가져온 개수 (권한이 없거나 아직 때가 아니면 None)."""
    lk=link(db,co['id']);now=core.now()
    if not has_scope(lk,'mall.read_product'):return None  # 예전 연결: 다시 연결해야 상품 권한이 생긴다
    last=core.parse(lk['synced_p']) if lk['synced_p'] else None
    if not force and last and now-last<PRODUCT_EVERY:return None
    mine={r['ext_id']:r for r in db.execute("SELECT * FROM products WHERE company_id=? AND src='cafe24'",(co['id'],))}
    byname={r['name']:r for r in db.execute("SELECT * FROM products WHERE company_id=? AND src=''",(co['id'],))}
    count=db.execute('SELECT COUNT(*) FROM products WHERE company_id=?',(co['id'],)).fetchone()[0]
    n=0;offset=0;t=core.iso();embed={'embed':'options'}
    while offset<=5000:
        db.commit()
        try:rows=api(db,co['id'],'/admin/products',{'limit':100,'offset':offset,**embed}).get('products') or []
        except shops.ShopError:
            if not embed or link(db,co['id'])['status']!='ok':raise
            embed={};rows=api(db,co['id'],'/admin/products',{'limit':100,'offset':offset}).get('products') or []  # 옵션 함께 받기를 안 받아 주면 옵션 없이
        for p in rows:
            no=str(p.get('product_no') or '');name=clean(p.get('product_name'),60)
            if not no or not name:continue
            price=won(p.get('price'));info=product_info(p);img=product_image(p);url=product_url(lk['mall_id'],no)
            stock='품절' if p.get('sold_out')=='T' or p.get('selling')=='F' else '있음'
            cur=mine.get(no) or byname.pop(name,None)  # 사장님이 먼저 같은 이름으로 적어 둔 상품은 이어 쓴다
            if cur:
                keep=cur['info'] and cur['info']!=cur['src_info']  # 사장님이 직접 고친 안내는 그대로
                db.execute("UPDATE products SET name=?,price=?,stock=?,info=?,src='cafe24',ext_id=?,src_info=?,image=?,url=?,updated=? WHERE id=?",
                           (name,price or cur['price'],stock,cur['info'] if keep else info,no,info,img,url,t,cur['id']))
            elif count<core.MAX_PRODUCTS:
                db.execute("INSERT INTO products(company_id,name,price,stock,info,updated,src,ext_id,src_info,image,url) VALUES(?,?,?,?,?,?,'cafe24',?,?,?,?)",(co['id'],name,price,stock,info,t,no,info,img,url))
                count+=1
            else:continue
            n+=1
        if len(rows)<100:break
        offset+=100
    db.execute('UPDATE cafe24_links SET synced_p=?,n_prod=? WHERE company_id=?',(core.iso(now),n,co['id']))
    return n
def product_name(db,cid,no):
    """카페24 상품번호 -> 가져온 상품 이름 (모르면 '')."""
    if not no or str(no)=='0':return ''
    r=db.execute("SELECT name FROM products WHERE company_id=? AND src='cafe24' AND ext_id=?",(cid,str(no))).fetchone()
    return r['name'] if r else ''

# ---------- 문의 게시판 (Q&A·1:1 상담) ----------
def text_of(h):
    """게시판 본문(HTML) -> 글."""
    t=re.sub(r'(?i)<br\s*/?>|</p>|</div>','\n',str(h or ''));t=html.unescape(re.sub(r'<[^>]+>','',t))
    return re.sub(r'\n{3,}','\n\n',re.sub(r'[ \t\xa0]+',' ',t)).strip()
def boards_of(lk):
    """지켜보는 게시판 [(번호, 이름)]. 아직 안 골랐으면 None."""
    if not lk['boards']:return None
    try:return [(int(n),str(nm)) for n,nm in json.loads(lk['boards'])]
    except Exception:return []
def all_boards(db,cid):
    d=api(db,cid,'/admin/boards')
    return [(int(b['board_no']),clean(b.get('board_name'),40) or f"게시판 {b['board_no']}") for b in d.get('boards') or [] if b.get('use_board','T')!='F' and b.get('board_no')]
def pick_boards(db,cid,picked=None):
    """picked가 None이면 이름에 Q&A·문의·상담이 들어간 게시판을 고른다."""
    bs=all_boards(db,cid)
    if picked is not None:bs=[b for b in bs if b[0] in picked]
    else:bs=[b for b in bs if BOARD_RE.search(b[1])]
    db.execute('UPDATE cafe24_links SET boards=? WHERE company_id=?',(json.dumps(bs,ensure_ascii=False),cid))
    return bs
def sync_boards(db,co):
    """지켜보는 게시판의 새 글 -> 소보루 요청 (채널 '카페24'). 새로 만든 요청 목록."""
    lk=link(db,co['id']);now=core.now()
    bs=boards_of(lk)
    if bs is None:bs=pick_boards(db,co['id'])
    frm=(core.parse(lk['since_b']) if lk['since_b'] else now-datetime.timedelta(days=shops.FIRST_DAYS))-datetime.timedelta(minutes=10)
    new=[];seen_m={}
    for bno,bname in bs:
        offset=0
        while offset<2000:
            db.commit()  # 위와 같은 이유
            d=api(db,co['id'],f'/admin/boards/{bno}/articles',{'start_date':frm.strftime('%Y-%m-%d'),'end_date':now.strftime('%Y-%m-%d'),'limit':100,'offset':offset})
            rows=d.get('articles') or []
            answered={int(a.get('parent_article_no') or 0) for a in rows if int(a.get('parent_article_no') or 0)!=int(a.get('article_no') or 0) and mine(co,lk,a.get('writer') or a.get('nick_name'))}
            for a in sorted(rows,key=lambda x:str(x.get('created_date') or '')):
                no=int(a.get('article_no') or 0);parent=int(a.get('parent_article_no') or 0)
                if not no or a.get('notice')=='T' or (a.get('deleted') or 'F')!='F':continue  # 공지·지운 글은 빼고
                if (parent and parent!=no) or int(a.get('reply_depth') or 0)>1:  # 답글: 고객이 같은 문의에 이어 쓴 것만 그 요청에 붙인다
                    follow(db,co,lk,bno,parent,f"a{bno}:{no}",a.get('writer') or a.get('nick_name') or '',text_of(a.get('content')),a.get('secret')=='T');continue
                if no in answered or a.get('reply_status')=='C':continue  # 가게가 이미 답한 글 (처음 연결할 때 지난 글, 카페24 관리자에서 답한 글)
                at=str(a.get('created_date') or '')[:19].replace('T',' ')
                ext=f"b{bno}:{no}:{'s' if a.get('secret')=='T' else 'p'}"
                if db.execute("SELECT 1 FROM shop_seen WHERE company_id=? AND shop='cafe24' AND ext_id=?",(co['id'],ext)).fetchone():continue  # 이미 가져온 글 (회원 주문을 다시 찾지 않게)
                body=text_of(a.get('content'));import chatbot
                typed=chatbot.ORDER_RE.search((a.get('title') or '')+'\n'+body)
                ono=str(a.get('order_id') or '');by='shop' if ono else ''  # 카페24가 붙여 준 주문 (회원이 주문 내역에서 쓴 글)
                if typed and typed.group(1)!=ono:ono,by=typed.group(1),''  # 본문에 적은 주문번호가 먼저 (본인 주문인지는 AI가 답하기 전에 본다)
                if not ono and (a.get('member_id') or '').strip():  # 회원 글: 주문번호를 안 적었으면 그 회원의 최근 주문을 붙인다
                    mid=str(a['member_id']).strip()
                    if mid not in seen_m:seen_m[mid]=member_order(db,co,mid)
                    ono=seen_m[mid];by='shop' if ono else ''
                c=shops._case(db,co,'cafe24',dict(ext_id=ext,title=a.get('title') or '',body=body,
                    name=a.get('writer') or a.get('nick_name') or '',order_no=ono,product=product_name(db,co['id'],a.get('product_no')),at=at[:16],channel='카페24'))  # 아직 답이 없는 글이면 연결 전에 올라왔어도 AI가 먼저 본다 (승인 목록엔 AI가 넘긴 것만)
                if c:
                    if by:db.execute("UPDATE cases SET order_by=? WHERE id=?",(by,c['id']));c=db.execute('SELECT * FROM cases WHERE id=?',(c['id'],)).fetchone()
                    new.append(c)
            if len(rows)<100:break
            offset+=100
    new+=sync_urgent(db,co,lk,frm,now)
    sync_comments(db,co,lk)
    db.execute('UPDATE cafe24_links SET since_b=?,n_inq=n_inq+? WHERE company_id=?',(core.iso(now),len(new),co['id']))
    return new
def sync_urgent(db,co,lk,frm,now):
    """카페24 긴급문의 -> 소보루 요청 (답변은 그 긴급문의의 답변으로 올라간다). 이미 답한 긴급문의는 빼고. 새로 만든 요청 목록."""
    new=[];seen_m={};offset=0
    while offset<2000:
        db.commit()  # 카페24를 기다리는 동안 DB를 잠그지 않게
        try:d=api(db,co['id'],'/admin/urgentinquiry',{'start_date':frm.strftime('%Y-%m-%d'),'end_date':now.strftime('%Y-%m-%d'),'limit':100,'offset':offset})
        except shops.ShopError:return new  # 긴급문의를 못 읽어도 게시판 가져오기는 그대로
        rows=d.get('urgentinquiry') or []
        for a in sorted(rows,key=lambda x:str(x.get('start_date') or '')):
            no=int(a.get('article_no') or 0)
            if not no or a.get('reply_status')=='T':continue  # 가게가 카페24에서 이미 답한 것
            ext=f'u{no}'
            if db.execute("SELECT 1 FROM shop_seen WHERE company_id=? AND shop='cafe24' AND ext_id=?",(co['id'],ext)).fetchone():continue
            at=str(a.get('start_date') or '')[:19].replace('T',' ')
            ono='';mid=str(a.get('member_id') or '').strip()
            if mid:
                if mid not in seen_m:seen_m[mid]=member_order(db,co,mid)
                ono=seen_m[mid]
            body=text_of(a.get('content'));import chatbot
            typed=chatbot.ORDER_RE.search((a.get('title') or '')+'\n'+body)
            by='shop' if ono else ''
            if typed and typed.group(1)!=ono:ono,by=typed.group(1),''
            c=shops._case(db,co,'cafe24',dict(ext_id=ext,title='[긴급문의] '+(a.get('title') or ''),body=body,
                name=a.get('writer') or '',order_no=ono,product='',at=at[:16],channel='카페24'))
            if c:
                if by:db.execute("UPDATE cases SET order_by=? WHERE id=?",(by,c['id']))
                new.append(c)
        if len(rows)<100:break
        offset+=100
    return new
OPEN_COMMENTS=30  # 한 번에 댓글을 확인하는 진행 중 요청 수 (호출을 아끼려고)
def sync_comments(db,co,lk):
    """진행 중인 카페24 문의 글에 고객이 단 댓글을 그 요청에 붙인다."""
    fin=','.join('?'*len(core.FINAL))
    rows=db.execute(f'''SELECT s.ext_id,c.id FROM shop_seen s JOIN cases c ON c.id=s.case_id WHERE s.company_id=? AND s.shop='cafe24' AND s.ext_id LIKE 'b%'
        AND c.status NOT IN ({fin}) ORDER BY c.updated DESC LIMIT ?''',(co['id'],*core.FINAL,OPEN_COMMENTS)).fetchall()
    for r in rows:
        m=re.fullmatch(r'b(\d+):(\d+):([sp])(?::.*)?',r['ext_id'])  # 끝난 문의에 다시 쓴 글로 연 요청은 뒤에 그 글 표시가 붙는다
        if not m:continue
        bno,no=int(m[1]),int(m[2])
        db.commit()  # 카페24를 기다리는 동안 DB를 잠그지 않게
        try:d=api(db,co['id'],f'/admin/boards/{bno}/articles/{no}/comments',{'limit':100})
        except shops.ShopError:continue  # 댓글을 못 읽어도 새 글 가져오기는 계속한다
        for cm in sorted(d.get('comments') or [],key=lambda x:str(x.get('created_date') or '')):
            if not cm.get('comment_no'):continue
            follow(db,co,lk,bno,no,f"c{bno}:{no}:{cm['comment_no']}",cm.get('writer') or cm.get('nick_name') or '',text_of(cm.get('content')),m[3]=='s')
def mine(co,lk,writer):
    """우리(가게)가 쓴 글·댓글인지: 소보루가 올린 답글의 글쓴이와 같거나 관리자 이름."""
    w=(writer or '').strip()
    return bool(w) and w in {clean(lk['shop_name'] or co['name'],40),co['name'],lk['shop_name'] or '','관리자','운영자'}
def follow(db,co,lk,bno,parent,ext,writer,text,secret):
    """카페24 문의 글에 이어진 답글·댓글 하나. 진행 중이면 그 요청에 붙이고, 끝난 요청이면 새 요청으로 받는다."""
    if mine(co,lk,writer) or db.execute("SELECT 1 FROM shop_seen WHERE company_id=? AND shop='cafe24' AND ext_id=?",(co['id'],ext)).fetchone():return None
    root=db.execute("SELECT case_id FROM shop_seen WHERE company_id=? AND shop='cafe24' AND ext_id LIKE ? ORDER BY rowid DESC LIMIT 1",(co['id'],f'b{bno}:{parent}:%')).fetchone()
    if not root:return None  # 소보루가 가져온 적 없는 글에 달린 것
    c=db.execute('SELECT * FROM cases WHERE id=?',(root['case_id'],)).fetchone()  # 그 글로 만든 가장 최근 요청 (끝난 뒤 다시 연 요청이 있으면 그쪽)
    text=text or '(내용 없음)'
    if c and c['name'] and clean(writer,20)!=c['name']:  # 고객이 아닌 사람이 쓴 것. 답글(댓글 말고)이면 카페24 관리자 화면에서 가게가 직접 답한 것으로 본다
        if ext.startswith('a') and c['status'] in ('forwarded','seen') and c['decision'] in ('pending','ai','hold','info'):
            db.execute("UPDATE cases SET status='answered',decision='direct',updated=? WHERE id=?",(core.iso(),c['id']))
            core.add_event(db,c['id'],'co','카페24 관리자 화면에서 답했어요',text)
            db.execute("INSERT INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)",(co['id'],'cafe24',ext,c['id']))
        return None
    if c and c['status'] not in core.FINAL:
        core.add_event(db,c['id'],'me',text)
        if c['status'] in ('answered','info'):db.execute("UPDATE cases SET status='seen' WHERE id=?",(c['id'],))
        db.execute('UPDATE cases SET updated=? WHERE id=?',(core.iso(),c['id']))
        import chatbot;chatbot.again(db,c,text)  # AI가 답한 글에 고객이 다시 쓰면 AI가 이어서 답한다 (AI를 껐으면 사장님이 본다)
        db.execute("INSERT INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)",(co['id'],'cafe24',ext,c['id']));return c
    # 끝난 요청에 다시 쓰면 새 요청 (답변은 처음 글에 답글로 올라간다)
    n=shops._case(db,co,'cafe24',dict(ext_id=f"b{bno}:{parent}:{'s' if secret else 'p'}:{ext}",title='다시 문의: '+((c['title'] if c else '') or '카페24 문의'),body=text,
        name=writer,order_no=(c['order_no'] if c else ''),product='',at='',channel='카페24'))
    if n:core.notify_company_new(co,n,db)
    return n
def post_reply(db,co,c,ext_id,text):
    """소보루에서 쓴 답변을 카페24 게시판 답글(긴급문의는 긴급문의 답변)로 올린다. 올리면 '', 못 올리면 이유."""
    u=re.fullmatch(r'u(\d+)',ext_id or '')
    if u:
        lk=link(db,co['id'])
        if not lk:return '카페24 연결이 끊겼어요. 서비스 연동에서 다시 연결해 주세요.'
        try:api(db,co['id'],f'/admin/urgentinquiry/{int(u[1])}/reply',method='POST',payload={'shop_no':1,'request':{'content':text,'status':'T','user_id':lk['mall_id'][:20]}})  # 대표 운영자 아이디 = 쇼핑몰 아이디
        except shops.ShopError as e:return str(e)
        return ''
    m=re.fullmatch(r'b(\d+):(\d+):([sp])(?::.*)?',ext_id or '')  # 끝난 문의에 다시 단 글이면 뒤에 그 글 표시가 붙는다
    if not m:return '카페24 게시판에서 가져온 문의가 아니에요.'
    bno,no,sec=int(m[1]),int(m[2]),m[3]=='s'
    lk=link(db,co['id'])
    if not lk:return '카페24 연결이 끊겼어요. 서비스 연동에서 다시 연결해 주세요.'
    body='<br>'.join(html.escape(x) for x in text.splitlines())
    req={'writer':clean(lk['shop_name'] or co['name'],40),'title':clean('RE: '+(c['title'] or '문의 답변'),120),'content':body,
         'client_ip':shops.server_ip() or '127.0.0.1','reply_article_no':no,'secret':'T' if sec else 'F'}
    if sec:req['password']=secrets.token_hex(8)  # 비밀글 답글도 비밀글로. 글쓴이와 관리자만 본다
    try:api(db,co['id'],f'/admin/boards/{bno}/articles',method='POST',payload={'shop_no':1,'requests':[req]})
    except shops.ShopError as e:return str(e)
    return ''

# ---------- 취소·반품 (사장님이 누를 때만) ----------
REASONS={'A':'단순 변심','B':'배송 지연','E':'상품 불만족','F':'상품 정보와 다름','D':'포장 불량','H':'품절','I':'기타'}
BEFORE_SHIP=('N00','N10','N20','N21','N22')
def _items(db,cid,order_no):
    d=api(db,cid,f'/admin/orders/{urllib.parse.quote(order_no)}',{'embed':'items'})
    return (d.get('order') or {}).get('items') or []
def claim(db,co,o,kind,reason_type,reason,actor=''):
    """kind 'cancel'(발송 전 취소·환불) | 'return'(발송 후 반품 접수). (안내, 'ok'|'error')"""
    if o['src']!='cafe24':return '카페24에서 가져온 주문이 아니에요.','error'
    if reason_type not in REASONS:return '사유를 골라 주세요.','error'
    reason=clean(reason,500) or REASONS[reason_type]
    done=db.execute('SELECT * FROM cafe24_actions WHERE company_id=? AND order_no=? AND kind=?',(co['id'],o['order_no'],kind)).fetchone()
    if done and done['state'] in ('ok','sending'):return ('이미 카페24에 보냈어요.' if done['state']=='ok' else '카페24에 보내는 중이에요. 잠시 뒤 다시 확인해 주세요.'),'error'
    db.execute("INSERT OR REPLACE INTO cafe24_actions(company_id,order_no,kind,state,actor,created) VALUES(?,?,?,'sending',?,?)",(co['id'],o['order_no'],kind,actor,core.iso()))
    db.commit()  # 동시에 두 번 눌러도 한 번만 보내도록 먼저 잠근다
    def fail(msg):
        db.execute("UPDATE cafe24_actions SET state='fail',note=? WHERE company_id=? AND order_no=? AND kind=?",(msg[:200],co['id'],o['order_no'],kind));return msg,'error'
    try:
        items=_items(db,co['id'],o['order_no'])
        st=[str(i.get('order_status') or '') for i in items]
        if not items:return fail('카페24에서 이 주문의 상품을 찾지 못했어요.')
        live=[i for i in items if str(i.get('order_status') or '')[:1] in ('N',)]
        if not live:return fail('카페24에서 이미 취소·반품·교환 중인 주문이에요. 카페24 관리자에서 확인해 주세요.')
        lines=[{'order_item_code':i['order_item_code'],'quantity':int(i.get('quantity') or 1)} for i in live]
        if kind=='cancel':
            if any(x not in BEFORE_SHIP for x in st if x[:1]=='N'):return fail('이미 발송된 상품이 있어요. 반품 접수로 처리해 주세요.')
            api(db,co['id'],f"/admin/orders/{urllib.parse.quote(o['order_no'])}/cancellation",method='POST',payload={'shop_no':1,'request':{
                'status':'canceled','claim_reason_type':reason_type,'reason':reason,'recover_inventory':'T','payment_gateway_cancel':'T','add_memo_too':'T','items':lines}})
            db.execute("UPDATE orders SET status='canceled',updated=? WHERE id=?",(core.iso(),o['id']))
            msg='카페24에서 주문을 취소했어요. 카드·간편결제는 결제 취소까지 함께 요청했어요. 무통장 입금은 카페24 관리자에서 환불 계좌를 확인해 주세요.'
        else:
            if all(x in BEFORE_SHIP for x in st if x[:1]=='N'):return fail('아직 발송 전이에요. 취소로 처리해 주세요.')
            api(db,co['id'],'/admin/return',method='POST',payload={'shop_no':1,'requests':[{
                'order_id':o['order_no'],'status':'accepted','claim_reason_type':reason_type,'reason':reason,'recover_inventory':'T','add_memo_too':'T','request_pickup':'F','items':lines}]})
            msg='카페24에 반품을 접수했어요. 상품을 돌려받으면 카페24 관리자에서 반품 완료·환불을 해 주세요.'
    except shops.ShopError as e:return fail(str(e))
    except Exception:
        current_app.logger.exception('카페24 %s 실패',kind)
        db.execute("UPDATE cafe24_actions SET state='unknown',note=? WHERE company_id=? AND order_no=? AND kind=?",('응답을 읽지 못함',co['id'],o['order_no'],kind))
        return '카페24 응답을 읽지 못했어요. 처리됐는지 카페24 관리자에서 먼저 확인해 주세요.','error'
    db.execute("UPDATE cafe24_actions SET state='ok',note='' WHERE company_id=? AND order_no=? AND kind=?",(co['id'],o['order_no'],kind))
    memo=f"[{core.iso()[:16]}] 카페24 {'취소' if kind=='cancel' else '반품 접수'} ({REASONS[reason_type]}){' · '+actor if actor else ''}"
    db.execute("UPDATE orders SET memo=trim(memo||char(10)||?) WHERE id=?",(memo,o['id']))
    import orders as om
    for cs in om.cases_for(db,o):
        if cs['order_no']==o['order_no']:core.add_event(db,cs['id'],'sys',f"카페24에 주문 {o['order_no']} {'취소' if kind=='cancel' else '반품 접수'}를 보냈어요")
    return msg,'ok'
def action(db,cid,order_no,kind):return db.execute('SELECT * FROM cafe24_actions WHERE company_id=? AND order_no=? AND kind=?',(cid,order_no,kind)).fetchone()

def sync_all():
    """cron: 연결된 카페24 쇼핑몰의 주문과 문의 게시판. 키가 없으면 아무것도 안 한다."""
    if not ready():return 0
    n=0
    with conn() as db:rows=db.execute("SELECT c.* FROM cafe24_links l JOIN companies c ON c.id=l.company_id WHERE l.status='ok' AND c.member=1 AND c.status='active'").fetchall()
    import billing;rows=[r for r in rows if billing.open_ok(r)]  # 결제가 없으면(체험 끝·결제 실패) 가져오지 않는다
    for co in rows:  # 한 쇼핑몰·한 단계가 실패해도 나머지는 계속 (예상 못 한 오류도 기록만 하고 넘어간다)
        try:
            with conn() as db:n+=sync_orders(db,co)
        except shops.ShopError:pass
        except Exception:log.exception('카페24 주문 가져오기 실패 (회사 %s)',co['id'])
        try:
            with conn() as db:sync_products(db,co)  # 상품을 먼저 (상품 문의에 이름을 붙이려고)
        except shops.ShopError:pass
        except Exception:log.exception('카페24 상품 가져오기 실패 (회사 %s)',co['id'])
        try:
            with conn() as db:new=sync_boards(db,co);n+=len(new)
            for c in [c for c in new if c['decision']!='ai'][:5]:core.notify_company_new(co,c)  # AI가 먼저 보는 문의는 넘겨받을 때 알린다. 한꺼번에 많아도 5건까지
        except shops.ShopError:pass  # 게시판 권한이 없는 예전 연결은 주문만
        except Exception:log.exception('카페24 문의 가져오기 실패 (회사 %s)',co['id'])
    return n

# ---------- 앱 삭제 웹훅 ----------
# 사장님이 카페24 관리자 > 앱에서 소보루 CS를 지우면 카페24가 이벤트 90077을 보낸다. 연결을 '앱 삭제됨'으로 바꾸고 토큰을 지운다
# (가져온 주문·요청은 그대로 둔다). 인증정보(CAFE24_WEBHOOK_KEY)가 맞으면 그대로 믿고, 없거나 다르면 카페24에 직접 물어
# 토큰이 정말 막혔을 때만 끊는다: 남이 이 주소로 가짜 이벤트를 보내도 살아 있는 연결은 끊기지 않는다.
APP_DELETED=90077
def _still_works(db,cid):
    """이 연결의 토큰으로 카페24가 아직 응답하면 True. 갱신까지 거절되면 False. 네트워크 오류 등 모르면 None."""
    try:mall,tok=access_token(db,cid)
    except shops.ShopError:return False
    except Exception:return None
    try:code,_=shops.http('GET',base(mall)+'/admin/store',{'Authorization':'Bearer '+tok},None)
    except Exception:return None
    return True if code<400 else False if code in (401,403) else None
def app_deleted(db,mall,trusted):
    """mall을 연결한 회사들의 연결을 거둔다 -> 거둔 수."""
    n=0
    for lk in db.execute("SELECT * FROM cafe24_links WHERE mall_id=? AND status!='removed'",(mall,)).fetchall():
        if not trusted and _still_works(db,lk['company_id']) is not False:
            log.warning('카페24 앱 삭제 이벤트를 확인하지 못해 연결을 그대로 둠: %s',mall);continue
        db.execute("UPDATE cafe24_links SET status='removed',creds='',note=? WHERE company_id=?",('카페24에서 소보루 CS 앱을 지웠어요. 다시 쓰려면 다시 연결해 주세요.',lk['company_id']))
        core.notify_company_link_broken(core.company(db,lk['company_id']),'카페24','카페24 관리자에서 소보루 CS 앱을 지웠어요','/connect/cafe24',db);n+=1
    return n
# 게시물 등록·댓글 이벤트는 '지금 그 쇼핑몰 게시판을 가져오라'는 신호로만 쓴다 (내용은 믿지 않고 카페24 API로 다시 읽는다).
# 그래서 가짜 이벤트가 와도 할 수 있는 건 가져오기를 한 번 더 하는 것뿐이다. 같은 회사는 몇 초에 한 번만.
POST_EVENTS={'90033','90034','90039','90035'}  # 게시물 등록, 댓글 등록, 게시물 수정, 긴급문의 접수
SYNC_LOCK=os.getenv('PLATFORM_SYNC_LOCK','/run/soboru-platform-sync.lock')  # 1분 cron(quick_sync.py)과 같은 잠금: 겹쳐 돌지 않게
_kick={}
def boards_now(mall):
    """그 쇼핑몰을 연결한 회사들의 게시판을 바로 가져오고 AI가 답한다 (뒤에서). 1분 cron을 기다리지 않게."""
    def job():
        import fcntl, chatbot
        fh=None
        for mode in ('r','a+'):  # cron(root)이 만든 잠금 파일은 읽기로 열어도 잠글 수 있다
            try:fh=open(SYNC_LOCK,mode);break
            except OSError:pass
        try:
            if fh:
                try:fcntl.flock(fh,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except OSError:return  # cron이 가져오는 중: 그쪽이 곧 처리한다
            with conn() as db:rows=db.execute("SELECT c.* FROM cafe24_links l JOIN companies c ON c.id=l.company_id WHERE l.mall_id=? AND l.status='ok' AND c.member=1 AND c.status='active'",(mall,)).fetchall()
            for co in rows:
                try:
                    with conn() as db:new=sync_boards(db,co)
                    for c in [c for c in new if c['decision']!='ai'][:5]:core.notify_company_new(co,c)
                except shops.ShopError:pass
                except Exception:log.exception('카페24 웹훅 가져오기 실패 (회사 %s)',co['id'])
            chatbot.auto_reply_all()
        finally:
            if fh:fh.close()
    t=time.time()
    if t-_kick.get(mall,0)<5:return False
    _kick[mall]=t
    threading.Thread(target=job,daemon=True).start() if BACKGROUND else job()
    return True
BACKGROUND=True  # 시험에서는 False

# 고객이 카페24에서 문의 글을 지우면(이벤트 90036) 진행 중인 그 요청을 닫는다. 이벤트 내용은 믿지 않고, 카페24 게시판에서 그 글이 정말 없어졌을 때만.
POST_DELETED='90036'
PAY_EVENTS={'90157','90079','90078','90158','90159'}  # 앱 결제 완료, 구독 갱신, 앱 만료, 환불 요청, 환불 완료 (billing.c24_event)
def _gone(db,cid,bno,no,since):
    """게시판에 그 글이 없거나 지워졌으면 True. 못 읽었거나 너무 많아 끝까지 못 봤으면 False (닫지 않는다)."""
    end=core.now()+datetime.timedelta(days=1)
    for off in range(0,500,100):
        try:d=api(db,cid,f'/admin/boards/{bno}/articles',{'start_date':since.strftime('%Y-%m-%d'),'end_date':end.strftime('%Y-%m-%d'),'limit':100,'offset':off})
        except shops.ShopError:return False
        rows=d.get('articles') or []
        for a in rows:
            if int(a.get('article_no') or 0)==no:return (a.get('deleted') or 'F')!='F'
        if len(rows)<100:return True
    return False
def post_deleted(db,mall,bno,no):
    """mall을 연결한 회사들에서, 지워진 글로 만든 진행 중인 요청을 닫는다 -> 닫은 수."""
    n=0;fin=','.join('?'*len(core.FINAL))
    for lk in db.execute("SELECT * FROM cafe24_links WHERE mall_id=? AND status='ok'",(mall,)).fetchall():
        c=db.execute(f'''SELECT c.* FROM shop_seen s JOIN cases c ON c.id=s.case_id WHERE s.company_id=? AND s.shop='cafe24' AND s.ext_id IN (?,?)
            AND c.status NOT IN ({fin})''',(lk['company_id'],f'b{bno}:{no}:s',f'b{bno}:{no}:p',*core.FINAL)).fetchone()
        if not c:continue
        since=core.parse(c['created'])-datetime.timedelta(days=shops.FIRST_DAYS+1)  # 처음 연결할 때는 며칠 전 글도 가져온다
        db.commit()  # 카페24를 기다리는 동안 DB를 잠그지 않게
        if not _gone(db,lk['company_id'],bno,no,since):continue
        if db.execute(f"UPDATE cases SET status='closed',updated=? WHERE id=? AND status NOT IN ({fin})",(core.iso(),c['id'],*core.FINAL)).rowcount:
            core.add_event(db,c['id'],'sys','고객이 카페24에서 문의 글을 지워서 요청을 닫았어요.');n+=1
    return n
def deleted_now(mall,bno,no):
    def job():
        try:
            with conn() as db:post_deleted(db,mall,bno,no)
        except Exception:log.exception('카페24 글 삭제 처리 실패: %s',mall)
    threading.Thread(target=job,daemon=True).start() if BACKGROUND else job()
@bp.route('/hook/cafe24',methods=['POST'])
def hook():
    """카페24 웹훅: 앱 삭제(연결 거두기), 게시물·댓글·긴급문의 등록(바로 가져오기), 게시물 삭제(요청 닫기). 받으면 늘 200 (카페24가 다시 보내지 않게)."""
    if not ready():abort(404)
    key=core.secret('CAFE24_WEBHOOK_KEY');got=request.headers.get('X-Api-Key') or request.headers.get('X-Cafe24-Api-Key') or ''
    trusted=bool(key and got and _hmac.compare_digest(got,key))
    d=request.get_json(silent=True) or {};res=d.get('resource') if isinstance(d.get('resource'),dict) else {}
    if str(d.get('event_no'))==str(APP_DELETED):
        mall=clean(str(res.get('mall_id') or ''),40);cid=str(res.get('client_id') or '')
        if mall and (not cid or cid==core.secret('CAFE24_CLIENT_ID')):
            with conn() as db:n=app_deleted(db,mall,trusted)
            log.warning('카페24 앱 삭제: %s (거둔 연결 %s, 인증 %s)',mall,n,'맞음' if trusted else '확인함' if n else '안 됨')
    elif str(d.get('event_no')) in POST_EVENTS:
        mall=clean(str(res.get('mall_id') or ''),40)
        if re.fullmatch(r'[a-z0-9_-]{2,40}',mall or ''):boards_now(mall)
    elif str(d.get('event_no')) in PAY_EVENTS:
        mall=clean(str(res.get('mall_id') or ''),40);cid=str(res.get('client_id') or '')
        if re.fullmatch(r'[a-z0-9_-]{2,40}',mall or '') and (not cid or cid==core.secret('CAFE24_CLIENT_ID')):
            import billing
            try:billing.c24_event(mall,str(d.get('event_no')),res)
            except Exception:log.exception('카페24 앱 결제 웹훅 처리 실패: %s',mall)
    elif str(d.get('event_no'))==POST_DELETED:
        mall=clean(str(res.get('mall_id') or ''),40);bno,no=str(res.get('board_no') or ''),str(res.get('no') or res.get('article_no') or '')
        if re.fullmatch(r'[a-z0-9_-]{2,40}',mall or '') and bno.isdigit() and no.isdigit():deleted_now(mall,int(bno),int(no))
    return {'ok':True}

# ---------- 화면 ----------
def company():
    import business
    co=business.me()
    if not co:abort(403)
    return co

# ---------- 카페24 앱스토어·관리자에서 앱을 열 때 (App URL) ----------
LAUNCH_MAX_AGE=2*3600  # 카페24가 붙여 보낸 timestamp가 이보다 오래되면 받지 않는다
def launch_ok(raw_query):
    """카페24가 App URL에 붙여 보내는 값(mall_id, timestamp, hmac 등)이 진짜인지. 맞으면 mall_id, 아니면 None.
    hmac = base64(HMAC-SHA256(client secret, hmac을 뺀 쿼리 문자열)). 카페24가 보낸 순서 그대로와 이름 순 정렬 둘 다 확인한다."""
    secret=core.secret('CAFE24_CLIENT_SECRET')
    if not secret:return None
    pairs=urllib.parse.parse_qsl(raw_query,keep_blank_values=True)
    d=dict(pairs);sig=d.get('hmac','');mall=(d.get('mall_id') or '').lower()
    if not sig or not MALL_RE.match(mall):return None
    try:
        if abs(time.time()-int(d.get('timestamp','0')))>LAUNCH_MAX_AGE:return None
    except ValueError:return None
    rest=[(k,v) for k,v in pairs if k!='hmac']
    for q in {urllib.parse.urlencode(rest),urllib.parse.urlencode(sorted(rest)),'&'.join(x for x in raw_query.split('&') if not x.startswith('hmac='))}:
        mac=base64.b64encode(_hmac.new(secret.encode(),q.encode(),hashlib.sha256).digest()).decode()
        if _hmac.compare_digest(mac,sig):return mall
    return None

@bp.route('/cafe24/launch')
def launch():
    """카페24에서 '소보루 CS' 앱을 누르면 오는 곳. 로그인돼 있으면 바로 연결(권한 동의)로, 아니면 가입·로그인 뒤 이어서."""
    if not ready():abort(404)
    mall=launch_ok(request.query_string.decode())
    if not mall:
        current_app.logger.warning('카페24 앱 실행 값 확인 실패: %s',request.args.get('mall_id',''))
        flash('카페24에서 온 요청을 확인하지 못했어요. 카페24 관리자에서 앱을 다시 열어 주세요.','error')
        return redirect(url_for('login'))
    session['c24_launch']=mall
    if not session.get('co_id'):
        flash(f'카페24 쇼핑몰({mall})을 소보루 CS에 연결할게요. 먼저 가입하거나 로그인해 주세요.','ok')
        return redirect(url_for('signup'))
    co=company()
    with conn() as db:lk=link(db,co['id'])
    if lk and lk['mall_id']==mall and lk['status']=='ok':
        session.pop('c24_launch',None);return redirect(url_for('decide'))
    # 카페24가 서명해 보낸 실행(=그 쇼핑몰 관리자)이고, 이어서 카페24 로그인·권한 동의까지 하면 회사 인증으로 본다 (카페24 입점 심사를 거친 쇼핑몰)
    nonce=secrets.token_urlsafe(12);session['c24_nonce']=nonce
    return redirect(authorize_url(mall,core.signer('c24').dumps({'co':co['id'],'mall':mall,'n':nonce,'l':1})))

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
                try:
                    n=sync_orders(db,co)
                    try:p=sync_products(db,co,force=True)
                    except shops.ShopError:p=None
                    new=sync_boards(db,co)
                    flash(f'주문 {n}건, 새 문의 {len(new)}건'+(f', 상품 {p}개' if p is not None else '')+'를 가져왔어요','ok')
                    if new:db.commit();import chatbot;chatbot.auto_reply_later()
                except shops.ShopError as e:flash(str(e),'error')
            elif act=='boards':
                try:bs=all_boards(db,co['id'])
                except shops.ShopError as e:flash(str(e),'error');return redirect(url_for('c24.page'))
                lk=link(db,co['id']);on={n for n,_ in (boards_of(lk) or [])}
                return render_template('b_cafe24.html',scope_text=scope_text,lk=lk,ready=ready(),scopes=scopes(),tab='connect',watch=boards_of(lk),pick=[(n,nm,n in on) for n,nm in bs])
            elif act=='boards_save':
                try:
                    bs=pick_boards(db,co['id'],{int(x) for x in request.form.getlist('board') if x.isdigit()})
                    flash(f"문의 게시판 {len(bs)}개를 지켜볼게요" if bs else '지켜보는 게시판이 없어요. 게시판 문의는 가져오지 않아요.','ok')
                except shops.ShopError as e:flash(str(e),'error')
            elif act=='check':
                try:
                    d=api(db,co['id'],'/admin/store');name=clean((d.get('store') or {}).get('shop_name') or (d.get('store') or {}).get('mall_name'),60)
                    db.execute('UPDATE cafe24_links SET shop_name=? WHERE company_id=?',(name,co['id']));flash(f'연결이 잘 돼 있어요{": "+name if name else ""}','ok')
                except shops.ShopError as e:flash(str(e),'error')
            else:
                if not ready():flash('카페24 연결은 소보루가 카페24 앱 등록을 마치면 열려요.','error')
                else:
                    mall=clean(request.form.get('mall_id'),40).lower().removesuffix('.cafe24.com')
                    launched=bool(mall) and session.get('c24_launch')==mall  # 카페24 관리자에서 앱을 열고 온 쇼핑몰
                    if not co['member'] and not launched:flash('판매처 연결은 실제 고객 정보를 가져오는 일이라 회사 인증이 끝난 뒤에 할 수 있어요. 카페24 관리자에서 소보루 CS 앱을 열면 바로 연결할 수 있어요.','error')
                    elif not MALL_RE.match(mall):flash('카페24 쇼핑몰 아이디를 확인해 주세요 (관리자 로그인 아이디, 예: myshop)','error')
                    else:
                        nonce=secrets.token_urlsafe(12);session['c24_nonce']=nonce
                        state=core.signer('c24').dumps(dict({'co':co['id'],'mall':mall,'n':nonce},**({'l':1} if launched else {})))
                        return redirect(authorize_url(mall,state))
        return redirect(url_for('c24.page'))
    with conn() as db:lk=link(db,co['id'])
    return render_template('b_cafe24.html',scope_text=scope_text,lk=lk,ready=ready(),scopes=scopes(),tab='connect',watch=boards_of(lk) if lk else None,pick=None,launch=session.pop('c24_launch',None) if co['member'] else session.get('c24_launch'))

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
        store(db,co['id'],st['mall'],data);session.pop('c24_launch',None)
        import billing;billing.start_c24_trial(db,co['id'])  # 카페24로 처음 연결: 5일 무료 체험 (그 안에 카페24로 결제)
        if st.get('l') and not co['member']:  # 카페24에서 연 앱 + 그 쇼핑몰 관리자 동의 = 회사 인증 (국세청·이메일 확인을 기다리지 않는다)
            import onboard;onboard.make_member(db,co);co=core.company(db,co['id'])
            log.warning('카페24 관리자 동의로 회사 인증: 회사 %s, 쇼핑몰 %s',co['id'],st['mall'])
        try:sync_orders(db,co)
        except shops.ShopError:pass
        try:sync_products(db,co,force=True)
        except shops.ShopError:pass
        try:new=sync_boards(db,co)
        except shops.ShopError:new=[]
    if new:import chatbot;chatbot.auto_reply_later()
    flash(f"카페24({st['mall']})에 연결했어요. 주문, 상품, 문의 게시판을 가져올게요.",'ok')
    return redirect(url_for('c24.page'))
