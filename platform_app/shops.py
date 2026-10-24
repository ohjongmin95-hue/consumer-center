"""판매처 연결: 사장님이 스마트스토어·쿠팡에서 직접 발급한 키를 넣으면, 문의와 주문을 SOBORU CS로 가져온다.
SOBORU CS가 판매처와 따로 계약하지 않는다. 키는 암호화해서 저장하고 화면에는 끝 4자리만 보인다.
  · 문의 -> SOBORU CS 요청 (채널 '스마트스토어'/'쿠팡'). 답변은 판매처에 올려야 고객에게 보인다.
  · 주문 -> 주문 장부 (주문번호가 같으면 상태·송장만 고친다)
서버 cron이 10분마다 sync_all()을 부른다. 판매처 문서: 네이버 커머스API센터, developers.coupang.com"""
import base64, datetime, traceback, hashlib, hmac, json, os, re, secrets, time, urllib.error, urllib.parse, urllib.request
import core, orders
from core import conn, clean, digits

SHOPS={'naver':dict(name='스마트스토어',full='네이버 스마트스토어',channel='스마트스토어',admin='https://sell.smartstore.naver.com',
                    fields=[('client_id','애플리케이션 ID'),('client_secret','애플리케이션 시크릿')]),
       'coupang':dict(name='쿠팡',full='쿠팡',channel='쿠팡',admin='https://wing.coupang.com',
                      fields=[('vendor_id','업체코드'),('access_key','Access Key'),('secret_key','Secret Key')],
                      optional=[('wing_id','Wing 로그인 아이디 (답변 올리기에 써요, 선택)')])}
FIRST_DAYS=3     # 처음 연결하면 며칠 전 것부터 가져올지
TIMEOUT=15

def init():
    with conn() as db:db.executescript('''
        CREATE TABLE IF NOT EXISTS shop_links(company_id INTEGER NOT NULL,shop TEXT NOT NULL,creds TEXT NOT NULL,hint TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'ok',note TEXT NOT NULL DEFAULT '',synced TEXT NOT NULL DEFAULT '',since TEXT NOT NULL DEFAULT '',
          n_inq INTEGER NOT NULL DEFAULT 0,n_ord INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL,
          PRIMARY KEY(company_id,shop),FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS shop_seen(company_id INTEGER NOT NULL,shop TEXT NOT NULL,ext_id TEXT NOT NULL,case_id INTEGER,
          PRIMARY KEY(company_id,shop,ext_id),FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE);''')
init()

# ---------- 키 암호화 (SECRET_KEY로 잠근다. HMAC-SHA256 카운터 모드 + 위조 검사) ----------
def _key(tag):return hmac.new(core.SECRET.encode(),b'soboru-shop-'+tag,hashlib.sha256).digest()
def _stream(nonce,n):
    out=b'';i=0
    while len(out)<n:out+=hmac.new(_key(b'enc'),nonce+i.to_bytes(4,'big'),hashlib.sha256).digest();i+=1
    return out[:n]
def seal(data):
    raw=json.dumps(data).encode();nonce=secrets.token_bytes(16)
    ct=bytes(a^b for a,b in zip(raw,_stream(nonce,len(raw))))
    return base64.b64encode(nonce+ct+hmac.new(_key(b'mac'),nonce+ct,hashlib.sha256).digest()).decode()
def unseal(text):
    """풀지 못하면(서버 SECRET_KEY가 바뀌었거나 값이 망가짐) None."""
    try:
        b=base64.b64decode(text);nonce,ct,tag=b[:16],b[16:-32],b[-32:]
        if not hmac.compare_digest(tag,hmac.new(_key(b'mac'),nonce+ct,hashlib.sha256).digest()):return None
        return json.loads(bytes(a^b for a,b in zip(ct,_stream(nonce,len(ct)))))
    except Exception:return None

# ---------- 저장 ----------
def link(db,cid,shop):return db.execute('SELECT * FROM shop_links WHERE company_id=? AND shop=?',(cid,shop)).fetchone()
def links(db,cid):return {r['shop']:r for r in db.execute('SELECT * FROM shop_links WHERE company_id=?',(cid,)).fetchall()}
def server_ip():return os.getenv('SERVER_IP','').strip()

class ShopError(Exception):
    """사장님께 그대로 보여 줄 우리말 안내를 담는다."""

# ---------- HTTP (테스트에서 바꿔 끼운다) ----------
def http(method,url,headers=None,body=None):
    """(상태 코드, JSON). 연결 자체가 안 되면 ShopError."""
    req=urllib.request.Request(url,data=body,method=method,headers=headers or {})
    try:
        with urllib.request.urlopen(req,timeout=TIMEOUT) as r:return r.status,json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        try:data=json.loads(e.read().decode() or '{}')
        except Exception:data={}
        return e.code,data
    except Exception as e:raise ShopError('판매처 서버에 연결하지 못했어요. 잠시 후 다시 해 주세요.') from e
def _check(code,data,shop):
    if code in (401,403):
        raise ShopError('키가 맞지 않거나, 판매처에 SOBORU CS 서버 IP가 등록되지 않았어요. 발급 안내를 다시 확인해 주세요.'+
                        (' 쿠팡 키는 발급 후 사용까지 하루 정도 걸릴 수 있어요.' if shop=='coupang' else ''))
    if code==429:raise ShopError('판매처가 잠시 요청을 막았어요. 몇 분 뒤 자동으로 다시 가져와요.')
    if code>=400:
        msg=str((data or {}).get('message') or '')[:120]
        raise ShopError(f'판매처가 요청을 거절했어요 ({code}{", "+msg if msg else ""}).')
    return data

def kst(dt):return dt.strftime('%Y-%m-%dT%H:%M:%S.000+09:00')

# ---------- 네이버 커머스API ----------
NAVER='https://api.commerce.naver.com/external'
_tokens={}
def naver_token(creds):
    """판매자 직접 사용 애플리케이션 토큰. client_secret_sign = base64(bcrypt(client_id_밀리초, client_secret))."""
    k=creds['client_id'];t=_tokens.get(k)
    if t and t[1]>time.time()+60:return t[0]
    import bcrypt
    ts=str(int(time.time()*1000))
    try:sign=base64.b64encode(bcrypt.hashpw(f'{k}_{ts}'.encode(),creds['client_secret'].encode())).decode()
    except ValueError:raise ShopError('애플리케이션 시크릿이 맞지 않아요. 커머스API센터에서 시크릿을 다시 복사해 주세요.')
    body=urllib.parse.urlencode(dict(client_id=k,timestamp=ts,client_secret_sign=sign,grant_type='client_credentials',type='SELF')).encode()
    data=_check(*http('POST',NAVER+'/v1/oauth2/token',{'Content-Type':'application/x-www-form-urlencoded'},body),'naver')
    if not data.get('access_token'):raise ShopError('스마트스토어 연결 확인에 실패했어요. 애플리케이션 ID와 시크릿을 확인해 주세요.')
    _tokens[k]=(data['access_token'],time.time()+int(data.get('expires_in') or 10800));return data['access_token']
def naver_get(creds,path,params=None,method='GET',payload=None):
    h={'Authorization':'Bearer '+naver_token(creds),'Content-Type':'application/json'}
    url=NAVER+path+('?'+urllib.parse.urlencode(params) if params else '')
    return _check(*http(method,url,h,json.dumps(payload).encode() if payload is not None else None),'naver')

N_STATUS={'PAYED':'paid','DELIVERING':'shipped','DELIVERED':'delivered','PURCHASE_DECIDED':'delivered','EXCHANGED':'exchanged',
          'CANCELED':'canceled','RETURNED':'returned','CANCELED_BY_NOPAYMENT':'canceled'}
N_COURIER={'CJGLS':'CJ대한통운','EPOST':'우체국택배','LOTTE':'롯데택배','HYUNDAI':'롯데택배','HANJIN':'한진택배','KGB':'로젠택배','LOGEN':'로젠택배',
           'CVSNET':'GS Postbox 편의점택배','CUPOST':'CU 편의점택배'}
def naver_orders(creds,frm,to):
    """바뀐 상품주문을 24시간 단위로 찾아 자세한 내용을 가져온다."""
    ids=[];cur=frm
    while cur<to:
        end=min(cur+datetime.timedelta(hours=24),to);params={'lastChangedFrom':kst(cur),'lastChangedTo':kst(end)}
        for _ in range(20):
            d=naver_get(creds,'/v1/pay-order/seller/product-orders/last-changed-statuses',params).get('data') or {}
            ids+=[str(x['productOrderId']) for x in d.get('lastChangeStatuses') or [] if x.get('productOrderId')]
            more=d.get('more') or {}
            if not more.get('moreFrom'):break
            params={**params,'lastChangedFrom':more['moreFrom'],'moreSequence':more.get('moreSequence','')}
        cur=end
    out=[];ids=list(dict.fromkeys(ids))
    for i in range(0,len(ids),300):
        for r in naver_get(creds,'/v1/pay-order/seller/product-orders/query',method='POST',payload={'productOrderIds':ids[i:i+300]}).get('data') or []:
            o,p,dl=r.get('order') or {},r.get('productOrder') or {},r.get('delivery') or {}
            st=N_STATUS.get(p.get('productOrderStatus'))
            if not st:continue  # 입금 대기 등
            if st=='paid' and p.get('placeOrderStatus')=='OK':st='ready'
            addr=p.get('shippingAddress') or {}
            out.append(dict(order_no=str(p.get('productOrderId','')),ordered_on=str(o.get('orderDate') or o.get('paymentDate') or '')[:10],
                            buyer=o.get('ordererName') or addr.get('name') or '',phone=digits(addr.get('tel1') or o.get('ordererTel') or ''),
                            address=' '.join(x for x in (addr.get('baseAddress'),addr.get('detailedAddress')) if x),
                            product=' / '.join(x for x in (p.get('productName'),p.get('productOption')) if x),qty=p.get('quantity') or 1,
                            amount=p.get('totalPaymentAmount') or 0,status=st,courier=N_COURIER.get(dl.get('deliveryCompany',''),'기타' if dl.get('deliveryCompany') else ''),
                            invoice=digits(dl.get('trackingNumber') or '')))
    return out
def naver_inquiries(creds,frm,to):
    """답변 안 한 고객 문의(1:1)."""
    out=[];page=1
    while page<=10:
        d=naver_get(creds,'/v1/pay-user/inquiries',{'startSearchDate':frm.strftime('%Y-%m-%d'),'endSearchDate':to.strftime('%Y-%m-%d'),'answered':'false','page':page,'size':100})
        d=d.get('data',d) if isinstance(d,dict) else {}
        for q in d.get('content') or []:
            if q.get('answered'):continue
            out.append(dict(ext_id='n'+str(q.get('inquiryNo')),title=q.get('title') or '',body=q.get('inquiryContent') or '',name=q.get('customerName') or '',
                            order_no=str((q.get('productOrderIdList') or [q.get('orderId') or ''])[0] or ''),product=q.get('productName') or '',
                            at=str(q.get('inquiryRegistrationDateTime') or '')[:19].replace('T',' ')))
        if page>=int(d.get('totalPages') or 1):break
        page+=1
    return out

# ---------- 쿠팡 OPEN API ----------
COUPANG='https://api-gateway.coupang.com'
def coupang_get(creds,path,query):
    """HMAC 서명: yyMMddTHHmmssZ + 메서드 + 경로 + 쿼리(물음표 없이), 16진수."""
    path=path.format(v=urllib.parse.quote(creds['vendor_id']));qs=urllib.parse.urlencode(query,safe=':')  # 문서대로 '+'는 %2B로
    dt=time.strftime('%y%m%dT%H%M%SZ',time.gmtime())
    sig=hmac.new(creds['secret_key'].encode(),(dt+'GET'+path+qs).encode(),hashlib.sha256).hexdigest()
    h={'Authorization':f"CEA algorithm=HmacSHA256, access-key={creds['access_key']}, signed-date={dt}, signature={sig}",'Content-Type':'application/json;charset=UTF-8'}
    return _check(*http('GET',COUPANG+path+'?'+qs,h),'coupang')
C_STATUS={'ACCEPT':'paid','INSTRUCT':'ready','DEPARTURE':'shipped','DELIVERING':'shipped','NONE_TRACKING':'shipped','FINAL_DELIVERY':'delivered'}
def courier_of(name):
    n=(name or '').replace(' ','')
    if not n:return ''
    for k in core.COURIERS:
        if k.replace(' ','')[:2] in n or n[:2] in k:return k
    return '기타'
def coupang_orders(creds,frm,to):
    out=[]
    for st in C_STATUS:
        q={'createdAtFrom':frm.strftime('%Y-%m-%d')+'+09:00','createdAtTo':to.strftime('%Y-%m-%d')+'+09:00','status':st,'maxPerPage':50}
        for _ in range(40):
            d=coupang_get(creds,'/v2/providers/openapi/apis/api/v5/vendors/{v}/ordersheets',q)
            for r in d.get('data') or []:
                items=r.get('orderItems') or [];rc=r.get('receiver') or {}
                names=[i.get('vendorItemName') or i.get('sellerProductName') or '' for i in items]
                out.append(dict(order_no=str(r.get('orderId','')),ordered_on=str(r.get('orderedAt') or '')[:10],buyer=(r.get('orderer') or {}).get('name') or rc.get('name') or '',
                                phone=digits(rc.get('safeNumber') or ''),address=' '.join(x for x in (rc.get('addr1'),rc.get('addr2')) if x),
                                product=(names[0] if names else '')+(f' 외 {len(names)-1}건' if len(names)>1 else ''),qty=sum(int(i.get('shippingCount') or 0) for i in items) or 1,
                                amount=sum(int(i.get('orderPrice') or 0) for i in items),status=C_STATUS[st],courier=courier_of(r.get('deliveryCompanyName')),
                                invoice=digits(r.get('invoiceNumber') or '')))
            if not d.get('nextToken'):break
            q={**q,'nextToken':d['nextToken']}
    return out
def coupang_inquiries(creds,frm,to):
    """답변 안 한 상품 문의와 쿠팡 고객센터가 넘긴 문의 (기간은 7일씩)."""
    out=[];cur=frm.date()
    while cur<=to.date():
        end=min(cur+datetime.timedelta(days=6),to.date());span={'inquiryStartAt':cur.isoformat(),'inquiryEndAt':end.isoformat()}
        for page in range(1,11):
            d=coupang_get(creds,'/v2/providers/openapi/apis/api/v5/vendors/{v}/onlineInquiries',{'vendorId':creds['vendor_id'],'answeredType':'NOANSWER',**span,'pageNum':page,'pageSize':50}).get('data') or {}
            for q in d.get('content') or []:
                out.append(dict(ext_id='q'+str(q.get('inquiryId')),title='',body=q.get('content') or '',name='',order_no=str((q.get('orderIds') or [''])[0] or ''),
                                product='',at=str(q.get('inquiryAt') or '')[:19].replace('T',' ')))
            if page>=int((d.get('pagination') or {}).get('totalPages') or 1):break
        for page in range(1,11):
            d=coupang_get(creds,'/v2/providers/openapi/apis/api/v5/vendors/{v}/callCenterInquiries',{'partnerCounselingStatus':'NO_ANSWER',**span,'pageNum':page,'pageSize':30}).get('data') or {}
            for q in d.get('content') or []:
                out.append(dict(ext_id='c'+str(q.get('inquiryId')),title='',body=q.get('content') or '',name='',order_no=str(q.get('orderId') or ''),
                                product=q.get('itemName') or '',at=str(q.get('inquiryAt') or '')[:19].replace('T',' ')))
            if page>=int((d.get('pagination') or {}).get('totalPages') or 1):break
        cur=end+datetime.timedelta(days=1)
    return out

# ---------- 답변 올리기 (시험 운영: 판매처 문서대로 만들었지만 실제 판매처 계정으로 아직 확인하지 못했다) ----------
def coupang_send(creds,method,path,payload):
    path=path.format(v=urllib.parse.quote(creds['vendor_id']))
    dt=time.strftime('%y%m%dT%H%M%SZ',time.gmtime())
    sig=hmac.new(creds['secret_key'].encode(),(dt+method+path).encode(),hashlib.sha256).hexdigest()
    h={'Authorization':f"CEA algorithm=HmacSHA256, access-key={creds['access_key']}, signed-date={dt}, signature={sig}",'Content-Type':'application/json;charset=UTF-8'}
    return _check(*http(method,COUPANG+path,h,json.dumps(payload).encode()),'coupang')
def post_reply(db,co,c,text):
    """판매처에서 가져온 문의에 답변을 올린다. 올리면 '', 못 올리면 이유."""
    seen=db.execute('SELECT * FROM shop_seen WHERE company_id=? AND case_id=? ORDER BY rowid LIMIT 1',(co['id'],c['id'])).fetchone()  # 처음 가져온 글 (이어진 댓글·답글이 아니라)
    if not seen:return '판매처에서 가져온 문의가 아니에요.'
    if seen['shop']=='email':
        import mailin
        return mailin.post_reply(db,co,c,text)
    if seen['shop']=='instagram':
        import instagram
        return instagram.post_reply(db,co,c,text)
    if seen['shop']=='kakao':
        import kakao
        return kakao.post_reply(db,co,c,text)
    text=(text or '').strip()[:1000]
    if seen['shop']=='cafe24':
        import cafe24
        return cafe24.post_reply(db,co,c,seen['ext_id'],text) if len(text)>=2 else '답변 내용이 너무 짧아요.'
    lk=link(db,co['id'],seen['shop'])
    creds=unseal(lk['creds']) if lk else None
    if not creds:return '판매처 연결이 끊겼어요. 서비스 연동에서 다시 연결해 주세요.'
    text=(text or '').strip()[:1000]
    if len(text)<2:return '답변 내용이 너무 짧아요.'
    kind,no=seen['ext_id'][0],seen['ext_id'][1:]
    try:
        if seen['shop']=='naver':naver_get(creds,f'/v1/pay-merchant/inquiries/{urllib.parse.quote(no)}/answer',method='POST',payload={'answerComment':text})
        else:
            if not creds.get('wing_id'):return '쿠팡에 답변을 올리려면 판매처 연결에서 쿠팡 Wing 아이디를 넣어 주세요.'
            if kind=='q':coupang_send(creds,'POST','/v2/providers/openapi/apis/api/v4/vendors/{v}/onlineInquiries/'+urllib.parse.quote(no)+'/replies',
                                      {'content':text,'vendorId':creds['vendor_id'],'replyBy':creds['wing_id']})
            else:coupang_send(creds,'POST','/v2/providers/openapi/apis/api/v4/vendors/{v}/callCenterInquiries/'+urllib.parse.quote(no)+'/replies',
                              {'vendorId':creds['vendor_id'],'inquiryId':no,'content':text,'replyBy':creds['wing_id']})
    except ShopError as e:return str(e)
    except Exception:
        traceback.print_exc();return '판매처 응답을 읽지 못했어요. 판매처 관리자 화면에서 답변이 올라갔는지 확인해 주세요.'
    return ''

FETCH={'naver':(naver_inquiries,naver_orders),'coupang':(coupang_inquiries,coupang_orders)}
def test(shop,creds):
    """키로 판매처에 실제로 한 번 물어본다. 안 되면 ShopError."""
    if shop=='naver':naver_token(creds)
    else:
        today=core.now().date().isoformat()
        coupang_get(creds,'/v2/providers/openapi/apis/api/v5/vendors/{v}/onlineInquiries',{'vendorId':creds['vendor_id'],'answeredType':'NOANSWER','inquiryStartAt':today,'inquiryEndAt':today,'pageNum':1,'pageSize':1})

def save(db,co,shop,form):
    """키를 확인하고 저장한다. (안내 문구, 'ok'|'error')"""
    spec=SHOPS[shop];creds={k:re.sub(r'\s','',form.get(k,''))[:200] for k,_ in spec['fields']+spec.get('optional',[])}
    miss=[label for k,label in spec['fields'] if not creds[k]]
    if miss:return f"{', '.join(miss)}을(를) 넣어 주세요",'error'
    if shop=='coupang' and not re.fullmatch(r'[A-Za-z0-9]{4,20}',creds['vendor_id']):return '업체코드를 확인해 주세요 (예: A00012345)','error'
    try:test(shop,creds)
    except ShopError as e:return str(e),'error'
    key=creds['client_id' if shop=='naver' else 'access_key']
    db.execute('''INSERT INTO shop_links(company_id,shop,creds,hint,status,note,created) VALUES(?,?,?,?,'ok','',?)
        ON CONFLICT(company_id,shop) DO UPDATE SET creds=excluded.creds,hint=excluded.hint,status='ok',note='',created=excluded.created''',
        (co['id'],shop,seal(creds),key[-4:],core.iso()))
    return f"{spec['full']}에 연결했어요. 문의와 주문을 가져올게요.",'ok'
def remove(db,co,shop):
    db.execute('DELETE FROM shop_links WHERE company_id=? AND shop=?',(co['id'],shop))
    db.execute('DELETE FROM shop_seen WHERE company_id=? AND shop=?',(co['id'],shop))

def _case(db,co,shop,q):
    """판매처 문의 하나 -> SOBORU CS 요청. 같은 문의는 한 번만."""
    if db.execute('SELECT 1 FROM shop_seen WHERE company_id=? AND shop=? AND ext_id=?',(co['id'],shop,q['ext_id'])).fetchone():return None
    from werkzeug.security import generate_password_hash
    body=clean(q['body'],core.BIG) or '(내용 없음)';ch=SHOPS[shop]['channel'] if shop in SHOPS else q['channel']
    title=clean(q['title'],60) or clean(re.sub(r'\s+',' ',body),40)
    cat=core.classify(title+' '+body) or '기타';t=core.iso()
    due=core.iso(core.now()+datetime.timedelta(days=core.REPLY_DAYS))
    import chatbot
    dec='ai' if q.get('ai',True) and chatbot.auto_on(core.company(db,co['id'])) else 'pending'  # AI 자동 답변이 켜져 있으면 AI가 먼저 본다 (승인 목록엔 AI가 넘긴 것만)
    cid=db.execute('''INSERT INTO cases(no,company_id,company_name,member,category,title,body,want,order_no,name,phone,email,lookup_hash,consent,status,decision,due,created,updated,product,received_on,channel)
        VALUES(?,?,?,1,?,?,?,?,?,?,'','',?,1,'forwarded',?,?,?,?,?,'',?)''',(core.new_case_no(db),co['id'],co['name'],cat,title,body,core.WANT_OF.get(cat,'기타'),
        clean(q['order_no'],40),clean(q['name'],20),generate_password_hash(secrets.token_hex(16)),dec,due,t,t,clean(q['product'],60),ch)).lastrowid
    core.add_event(db,cid,'sys',f"{ch} 문의를 가져왔어요"+(f" ({q['at']} 접수)" if q.get('at') else ''))
    db.execute('INSERT INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)',(co['id'],shop,q['ext_id'],cid))
    c=db.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
    import workflow;workflow.on_new(db,core.company(db,co['id']),c)  # 자동 배정 (판매처에는 영업시간 밖 안내를 올리지 않는다)
    return db.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
def _order(db,co,shop,o):
    """판매처 주문 하나 -> 주문 장부. SOBORU CS에서 처리한 취소·반품 결과는 덮지 않는다."""
    o={**o,'channel':SHOPS[shop]['channel'] if shop in SHOPS else o['channel'],'buyer':clean(o['buyer'],30),'phone':o['phone'][:11],'address':clean(o['address'],200),
       'product':clean(o['product'],200),'qty':max(1,min(int(o['qty'] or 1),9999)),'amount':max(0,int(o['amount'] or 0)),'order_no':clean(o['order_no'],60)}
    if not o['order_no']:return 0
    old=db.execute('SELECT * FROM orders WHERE company_id=? AND order_no=?',(co['id'],o['order_no'])).fetchone();t=core.iso()
    keys=('channel','ordered_on','buyer','phone','address','product','qty','amount','status','courier','invoice')
    if old:
        if old['status'] in ('canceled','returned','refunded','exchanged') and o['status'] in ('paid','ready','shipped','delivered'):o['status']=old['status']
        if not o['invoice']:o['invoice'],o['courier']=old['invoice'],old['courier']
        if all(old[k]==o[k] for k in keys):return 0
        db.execute('UPDATE orders SET '+','.join(f'{k}=?' for k in keys)+',updated=? WHERE id=?',[o[k] for k in keys]+[t,old['id']]);return 1
    if db.execute('SELECT COUNT(*) FROM orders WHERE company_id=?',(co['id'],)).fetchone()[0]>=orders.MAX_ORDERS:return 0
    db.execute('INSERT INTO orders(company_id,order_no,'+','.join(keys)+',created,updated) VALUES(?,?,'+','.join('?'*len(keys))+',?,?)',[co['id'],o['order_no']]+[o[k] for k in keys]+[t,t]);return 1

def sync(co,shop):
    """한 기업·판매처를 가져온다. (새 문의 수, 새로 넣거나 고친 주문 수). 실패하면 연결에 이유를 적고 ShopError."""
    with conn() as db:lk=link(db,co['id'],shop)
    if not lk:return 0,0
    creds=unseal(lk['creds'])
    def fail(msg):
        with conn() as db:db.execute("UPDATE shop_links SET status='error',note=? WHERE company_id=? AND shop=?",(msg,co['id'],shop))
        if lk['status']=='ok':core.notify_company_link_broken(co,SHOPS[shop]['full'],msg,'/connect/'+shop)  # 처음 끊겼을 때만
        raise ShopError(msg)
    if not creds:fail('저장한 키를 읽지 못했어요. 키를 다시 넣어 주세요.')
    now=core.now();frm=core.parse(lk['since']) if lk['since'] else None
    frm=(frm or now-datetime.timedelta(days=FIRST_DAYS))-datetime.timedelta(minutes=10)  # 판매처 반영이 늦는 것까지 겹쳐 가져온다
    get_inq,get_ord=FETCH[shop]
    try:inqs=get_inq(creds,frm,now);ords=get_ord(creds,frm,now)
    except ShopError as e:fail(str(e))
    except Exception:
        traceback.print_exc()  # 판매처 응답 모양이 바뀌었을 때 서버 기록으로 찾는다
        fail('판매처 응답을 읽지 못했어요. 잠시 후 다시 해 주세요.')
    new=[]
    with conn() as db:
        for q in sorted(inqs,key=lambda x:x.get('at') or ''):
            c=_case(db,co,shop,q)
            if c:new.append(c)
        n_ord=sum(_order(db,co,shop,o) for o in ords)
        db.execute("UPDATE shop_links SET status='ok',note='',synced=?,since=?,n_inq=n_inq+?,n_ord=n_ord+? WHERE company_id=? AND shop=?",
                   (core.iso(now),core.iso(now),len(new),n_ord,co['id'],shop))
    for c in new[:5]:core.notify_company_new(co,c)  # 한꺼번에 많이 들어와도 알림은 5건까지
    return len(new),n_ord
def sync_all():
    """cron: 연결된 모든 기업. 한 곳이 실패해도 나머지는 계속."""
    n=0
    with conn() as db:rows=db.execute("SELECT l.shop,c.* FROM shop_links l JOIN companies c ON c.id=l.company_id WHERE c.member=1 AND c.status='active'").fetchall()
    import billing;rows=[r for r in rows if billing.open_ok(r)]  # 결제가 없으면(체험 끝·결제 실패) 가져오지 않는다
    for r in rows:
        try:n+=sum(sync(r,r['shop']))
        except ShopError:pass
    return n

if __name__=='__main__':
    core.MAIL_ASYNC=False
    print(f'판매처 가져오기 {sync_all()}건')
    import cafe24, openapi, mailin, instagram, billing  # 같은 10분 cron에서 카페24 주문, 이메일 문의, 인스타그램 토큰 갱신, 외부 API 웹훅, 요금 자동결제, AI 자동 답변도 처리한다
    print(f'카페24 주문 {cafe24.sync_all()}건, 이메일 문의 {mailin.sync_all()}건, 인스타그램 토큰 갱신 {instagram.refresh_all()}건, 웹훅 {openapi.dispatch()}건, 요금 결제 {billing.renew_all()}건')
    import chatbot
    print(f'AI 자동 답변 {chatbot.auto_reply_all()}건')  # 위에서 가져온 문의까지 (켠 기업만)
