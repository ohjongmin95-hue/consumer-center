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
import base64, datetime, hashlib, hmac as _hmac, html, json, re, secrets, time, urllib.parse
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session, current_app
import core, shops, orders
from core import conn, clean, digits

bp=Blueprint('c24',__name__)
SCOPES='mall.read_store,mall.read_product,mall.read_order,mall.write_order,mall.read_community,mall.write_community'
SCOPE_NAMES={'store':'상점','order':'주문','community':'게시판','customer':'회원','product':'상품'}
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
                         ('synced_p',"TEXT NOT NULL DEFAULT ''"),('n_prod','INTEGER NOT NULL DEFAULT 0')):
            if col not in cols:db.execute(f'ALTER TABLE cafe24_links ADD COLUMN {col} {kind}')
        pc={r[1] for r in db.execute('PRAGMA table_info(products)')}
        for col in ('src','ext_id','src_info'):  # src 'cafe24' + 카페24 상품번호. src_info: 마지막으로 카페24에서 받은 안내 (사장님이 고쳤는지 보려고)
            if col not in pc:db.execute(f"ALTER TABLE products ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        if 'src' not in {r[1] for r in db.execute('PRAGMA table_info(orders)')}:db.execute("ALTER TABLE orders ADD COLUMN src TEXT NOT NULL DEFAULT ''")  # 'cafe24': 카페24에서 가져온 주문
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

C_STATUS={'N00':'paid','N10':'paid','N20':'ready','N21':'ready','N22':'ready','N30':'shipped','N40':'delivered',
          'C00':'canceled','C10':'canceled','C34':'canceled','C40':'canceled','R00':'returned','R10':'returned','R40':'returned','E00':'exchanged','E40':'exchanged'}
def sync_orders(db,co):
    """카페24 주문 -> 주문 장부 (채널 '자사몰'). 넣거나 고친 수."""
    lk=link(db,co['id']);now=core.now()
    frm=(core.parse(lk['since']) if lk['since'] else now-datetime.timedelta(days=shops.FIRST_DAYS))-datetime.timedelta(minutes=10)
    n=0;offset=0
    while offset<5000:
        db.commit()  # 카페24를 기다리는 동안 DB를 잠가 두지 않는다 (그사이 사장님 화면의 저장이 'database is locked'로 실패했다)
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
            db.execute("UPDATE orders SET src='cafe24' WHERE company_id=? AND order_no=? AND src=''",(co['id'],str(o.get('order_id',''))))
        if len(rows)<100:break
        offset+=100
    db.execute("UPDATE cafe24_links SET status='ok',note='',synced=?,since=?,n_ord=n_ord+? WHERE company_id=?",(core.iso(now),core.iso(now),n,co['id']))
    return n

# ---------- 상품 ----------
PRODUCT_EVERY=datetime.timedelta(hours=6)  # 자동으로는 6시간마다 ('지금 가져오기'는 바로)
def has_scope(lk,scope):return scope in str(lk['scopes'] or '').replace(' ','').split(',')
def won(v):
    try:n=int(float(str(v or '').replace(',','')))
    except ValueError:return ''
    return f'{n:,}원' if n>0 else ''
def product_info(p):
    """카페24 상품 -> 상담에 쓰는 안내 글 (요약·간단 설명만. 상세 설명은 대부분 이미지라 안 쓴다)."""
    bits=[]
    for k in ('summary_description','simple_description'):
        t=text_of(p.get(k))
        if t and t not in bits:bits.append(t)
    return clean('\n'.join(bits),2000)
def sync_products(db,co,force=False):
    """카페24 상품 -> 상품정보. 이름·가격·판매 상태는 카페24 기준, 안내는 사장님이 고치지 않았을 때만 바꾼다. 가져온 개수 (권한이 없거나 아직 때가 아니면 None)."""
    lk=link(db,co['id']);now=core.now()
    if not has_scope(lk,'mall.read_product'):return None  # 예전 연결: 다시 연결해야 상품 권한이 생긴다
    last=core.parse(lk['synced_p']) if lk['synced_p'] else None
    if not force and last and now-last<PRODUCT_EVERY:return None
    mine={r['ext_id']:r for r in db.execute("SELECT * FROM products WHERE company_id=? AND src='cafe24'",(co['id'],))}
    byname={r['name']:r for r in db.execute("SELECT * FROM products WHERE company_id=? AND src=''",(co['id'],))}
    count=db.execute('SELECT COUNT(*) FROM products WHERE company_id=?',(co['id'],)).fetchone()[0]
    n=0;offset=0;t=core.iso()
    while offset<=5000:
        db.commit()
        rows=api(db,co['id'],'/admin/products',{'limit':100,'offset':offset}).get('products') or []
        for p in rows:
            no=str(p.get('product_no') or '');name=clean(p.get('product_name'),60)
            if not no or not name:continue
            price=won(p.get('price'));info=product_info(p)
            stock='품절' if p.get('sold_out')=='T' or p.get('selling')=='F' else '있음'
            cur=mine.get(no) or byname.pop(name,None)  # 사장님이 먼저 같은 이름으로 적어 둔 상품은 이어 쓴다
            if cur:
                keep=cur['info'] and cur['info']!=cur['src_info']  # 사장님이 직접 고친 안내는 그대로
                db.execute("UPDATE products SET name=?,price=?,stock=?,info=?,src='cafe24',ext_id=?,src_info=?,updated=? WHERE id=?",
                           (name,price or cur['price'],stock,cur['info'] if keep else info,no,info,t,cur['id']))
            elif count<core.MAX_PRODUCTS:
                db.execute("INSERT INTO products(company_id,name,price,stock,info,updated,src,ext_id,src_info) VALUES(?,?,?,?,?,?,'cafe24',?,?)",(co['id'],name,price,stock,info,t,no,info))
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
    new=[]
    for bno,bname in bs:
        offset=0
        while offset<2000:
            db.commit()  # 위와 같은 이유
            d=api(db,co['id'],f'/admin/boards/{bno}/articles',{'start_date':frm.strftime('%Y-%m-%d'),'end_date':now.strftime('%Y-%m-%d'),'limit':100,'offset':offset})
            rows=d.get('articles') or []
            for a in sorted(rows,key=lambda x:str(x.get('created_date') or '')):
                no=int(a.get('article_no') or 0);parent=int(a.get('parent_article_no') or 0)
                if not no or a.get('notice')=='T' or (a.get('deleted') or 'F')!='F':continue  # 공지·지운 글은 빼고
                if (parent and parent!=no) or int(a.get('reply_depth') or 0)>1:  # 답글: 고객이 같은 문의에 이어 쓴 것만 그 요청에 붙인다
                    follow(db,co,lk,bno,parent,f"a{bno}:{no}",a.get('writer') or a.get('nick_name') or '',text_of(a.get('content')),a.get('secret')=='T');continue
                c=shops._case(db,co,'cafe24',dict(ext_id=f"b{bno}:{no}:{'s' if a.get('secret')=='T' else 'p'}",title=a.get('title') or '',body=text_of(a.get('content')),
                    name=a.get('writer') or a.get('nick_name') or '',order_no=str(a.get('order_id') or ''),product=product_name(db,co['id'],a.get('product_no')),at=str(a.get('created_date') or '')[:16].replace('T',' '),channel='카페24'))
                if c:new.append(c)
            if len(rows)<100:break
            offset+=100
    sync_comments(db,co,lk)
    db.execute('UPDATE cafe24_links SET since_b=?,n_inq=n_inq+? WHERE company_id=?',(core.iso(now),len(new),co['id']))
    return new
OPEN_COMMENTS=30  # 한 번에 댓글을 확인하는 진행 중 요청 수 (호출을 아끼려고)
def sync_comments(db,co,lk):
    """진행 중인 카페24 문의 글에 고객이 단 댓글을 그 요청에 붙인다."""
    fin=','.join('?'*len(core.FINAL))
    rows=db.execute(f'''SELECT s.ext_id,c.id FROM shop_seen s JOIN cases c ON c.id=s.case_id WHERE s.company_id=? AND s.shop='cafe24' AND s.ext_id LIKE 'b%'
        AND c.status NOT IN ({fin}) ORDER BY c.updated DESC LIMIT ?''',(co['id'],*core.FINAL,OPEN_COMMENTS)).fetchall()
    for r in rows:
        m=re.fullmatch(r'b(\d+):(\d+):([sp])',r['ext_id'])
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
    root=db.execute("SELECT case_id FROM shop_seen WHERE company_id=? AND shop='cafe24' AND ext_id IN (?,?) ORDER BY rowid LIMIT 1",(co['id'],f'b{bno}:{parent}:s',f'b{bno}:{parent}:p')).fetchone()
    if not root:return None  # 소보루가 가져온 적 없는 글에 달린 것
    c=db.execute('SELECT * FROM cases WHERE id=?',(root['case_id'],)).fetchone()
    if c and c['name'] and clean(writer,20)!=c['name']:return None  # 처음 글쓴 고객이 쓴 것만 (다른 사람·가게 답글은 빼고)
    text=text or '(내용 없음)'
    if c and c['status'] not in core.FINAL:
        core.add_event(db,c['id'],'me',text);core.notify_company_msg(db,c['id'],text)
        if c['status'] in ('answered','info'):db.execute("UPDATE cases SET status='seen' WHERE id=?",(c['id'],))
        db.execute('UPDATE cases SET updated=? WHERE id=?',(core.iso(),c['id']))
        db.execute("INSERT INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)",(co['id'],'cafe24',ext,c['id']));return c
    # 끝난 요청에 다시 쓰면 새 요청 (답변은 처음 글에 답글로 올라간다)
    n=shops._case(db,co,'cafe24',dict(ext_id=f"b{bno}:{parent}:{'s' if secret else 'p'}:{ext}",title='다시 문의: '+((c['title'] if c else '') or '카페24 문의'),body=text,
        name=writer,order_no=(c['order_no'] if c else ''),product='',at='',channel='카페24'))
    if n:core.notify_company_new(co,n)
    return n
def post_reply(db,co,c,ext_id,text):
    """소보루에서 쓴 답변을 카페24 게시판 답글로 올린다. 올리면 '', 못 올리면 이유."""
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
    for co in rows:
        try:
            with conn() as db:n+=sync_orders(db,co)
        except shops.ShopError:pass
        try:
            with conn() as db:sync_products(db,co)  # 상품을 먼저 (상품 문의에 이름을 붙이려고)
        except shops.ShopError:pass
        try:
            with conn() as db:new=sync_boards(db,co);n+=len(new)
            for c in new[:5]:core.notify_company_new(co,c)  # 한꺼번에 많이 들어와도 알림은 5건까지
        except shops.ShopError:pass  # 게시판 권한이 없는 예전 연결은 주문만
    return n

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
    if not co['member']:return redirect(url_for('c24.page'))  # 회사 인증 전: 연결 화면에서 안내
    nonce=secrets.token_urlsafe(12);session['c24_nonce']=nonce
    return redirect(authorize_url(mall,core.signer('c24').dumps({'co':co['id'],'mall':mall,'n':nonce})))

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
                return render_template('b_cafe24.html',scope_text=scope_text,lk=lk,ready=ready(),scopes=SCOPES,tab='connect',watch=boards_of(lk),pick=[(n,nm,n in on) for n,nm in bs])
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
    return render_template('b_cafe24.html',scope_text=scope_text,lk=lk,ready=ready(),scopes=SCOPES,tab='connect',watch=boards_of(lk) if lk else None,pick=None,launch=session.pop('c24_launch',None))

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
        try:sync_orders(db,co)
        except shops.ShopError:pass
        try:sync_products(db,co,force=True)
        except shops.ShopError:pass
        try:new=sync_boards(db,co)
        except shops.ShopError:new=[]
    if new:import chatbot;chatbot.auto_reply_later()
    flash(f"카페24({st['mall']})에 연결했어요. 주문, 상품, 문의 게시판을 가져올게요.",'ok')
    return redirect(url_for('c24.page'))
