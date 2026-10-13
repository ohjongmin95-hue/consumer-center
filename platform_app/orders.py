"""주문 장부: 기업이 엑셀(CSV)로 올리거나 직접 넣은 주문을 한곳에서 관리한다.
판매처 API(스마트스토어·쿠팡 등)가 연결되면 같은 표에 채워 넣는다. 고객 요청은 주문번호나 휴대폰 번호로 이 장부의 주문과 이어진다.
구매자 정보는 기업이 맡긴 것이라 그 기업 화면에서만 보이고, 기업이 탈퇴하면 함께 지워진다."""
import csv, io, re
import core
from core import clean, digits

STATUS={'paid':'결제 완료','ready':'발송 준비','shipped':'배송 중','delivered':'배송 완료','canceled':'취소','returned':'반품','refunded':'환불','exchanged':'교환'}
GROUPS=[('all','전체',None),('todo','발송 전',('paid','ready')),('moving','배송 중',('shipped',)),('done','배송 완료',('delivered',)),
        ('back','취소·반품',('canceled','returned','refunded','exchanged'))]
CHANNELS=['직접','스마트스토어','쿠팡','자사몰','오픈마켓','기타']
MAX_ROWS=5000      # 한 번에 올릴 수 있는 줄 수
MAX_ORDERS=50000   # 기업 하나가 둘 수 있는 주문 수

COLS={'order_no':('주문번호','상품주문번호','order_no','주문 번호'),'ordered_on':('주문일','주문일시','결제일','결제일시','주문일자'),
      'buyer':('구매자','구매자명','주문자','주문자명','수취인명','수취인','받는 분','수령인'),
      'phone':('연락처','휴대폰','휴대폰 번호','전화번호','구매자연락처','수취인연락처1','수취인 연락처','수령인 연락처'),
      'address':('주소','배송지','배송지 주소','수취인주소','받는 주소'),'product':('상품명','상품','상품 이름'),'option':('옵션','옵션정보','옵션명'),
      'qty':('수량','주문수량'),'amount':('결제금액','금액','주문금액','총 주문금액','최종 상품별 총 주문금액','상품별 총 주문금액'),
      'channel':('판매처','쇼핑몰','채널'),'courier':('택배사',),'invoice':('송장번호','운송장번호'),'status':('주문상태','상태')}

def status_from(text,invoice=''):
    """판매처 엑셀의 주문 상태 글을 우리 상태로. 모르면 송장 유무로 정한다."""
    t=(text or '').replace(' ','')
    for words,st in ((('환불',),'refunded'),(('반품',),'returned'),(('교환',),'exchanged'),(('취소',),'canceled'),
                     (('배송완료','구매확정'),'delivered'),(('배송중','발송완료','배송시작'),'shipped'),(('발송대기','발주확인','준비'),'ready')):
        if any(w in t for w in words):return st
    return 'shipped' if invoice else 'paid'
def num(text):
    d=re.sub(r'[^0-9]','',str(text or ''));return int(d) if d and len(d)<12 else 0

def orders(db,cid,group='all',q=''):
    sts=dict((k,s) for k,_,s in GROUPS).get(group)
    sql='SELECT * FROM orders WHERE company_id=?';args=[cid]
    if sts:sql+=' AND status IN (%s)'%','.join('?'*len(sts));args+=list(sts)
    if q:
        like='%'+q.replace('%','')+'%';sql+=' AND (order_no LIKE ? OR buyer LIKE ? OR product LIKE ? OR invoice LIKE ?'+(' OR phone LIKE ?' if digits(q) else '')+')'
        args+=[like]*4+(['%'+digits(q)+'%'] if digits(q) else [])
    return db.execute(sql+' ORDER BY ordered_on DESC,id DESC LIMIT 500',args).fetchall()
def counts(db,cid):
    rows=db.execute('SELECT status,COUNT(*) n FROM orders WHERE company_id=? GROUP BY status',(cid,)).fetchall();by={r['status']:r['n'] for r in rows}
    return {k:(sum(by.values()) if s is None else sum(by.get(x,0) for x in s)) for k,_,s in GROUPS}
def order(db,cid,oid):return db.execute('SELECT * FROM orders WHERE id=? AND company_id=?',(oid,cid)).fetchone()

def for_case(db,c):
    """요청과 이어진 주문: 주문번호가 같으면 그 주문, 없으면 같은 휴대폰 번호의 가장 최근 주문."""
    if not c['company_id']:return None
    if c['order_no']:
        o=db.execute('SELECT * FROM orders WHERE company_id=? AND order_no=?',(c['company_id'],c['order_no'].strip())).fetchone()
        if o:return o
    if c['phone']:return db.execute('SELECT * FROM orders WHERE company_id=? AND phone=? ORDER BY ordered_on DESC,id DESC LIMIT 1',(c['company_id'],digits(c['phone']))).fetchone()
    return None
def cases_for(db,o):
    """주문과 이어진 요청들 (주문번호가 같거나 같은 휴대폰 번호)."""
    return db.execute('SELECT * FROM cases WHERE company_id=? AND member=1 AND consent=1 AND (order_no=? OR (phone!=\'\' AND phone=?)) ORDER BY id DESC LIMIT 20',
                      (o['company_id'],o['order_no'],o['phone'] or '-')).fetchall()

def save(db,co,f,oid=None):
    """주문 하나 추가·수정 (웹·앱 공용). 보내지 않은 칸은 그대로 둔다. (안내 문구, 'ok'|'error', id)"""
    cur=order(db,co['id'],oid) if oid else None
    if oid and not cur:return '주문을 찾을 수 없어요','error',None
    keep=lambda k,n:clean(f.get(k),n) if k in f or not cur else cur[k]
    d=dict(order_no=keep('order_no',60),channel=keep('channel',20),ordered_on=keep('ordered_on',10),buyer=keep('buyer',30),
           address=keep('address',200),product=keep('product',200),memo=keep('memo',500),courier=keep('courier',20))
    d['phone']=digits(f['phone'])[:11] if 'phone' in f else (cur['phone'] if cur else '')
    d['invoice']=digits(f['invoice'])[:20] if 'invoice' in f else (cur['invoice'] if cur else '')
    d['qty']=max(1,min(num(f['qty']),9999)) if 'qty' in f else (cur['qty'] if cur else 1)
    d['amount']=num(f['amount']) if 'amount' in f else (cur['amount'] if cur else 0)
    d['status']=f.get('status') if f.get('status') in STATUS else (cur['status'] if cur else ('shipped' if d['invoice'] else 'paid'))
    if not d['order_no']:return '주문번호를 적어 주세요','error',None
    if d['channel'] not in CHANNELS:d['channel']='직접'
    if d['invoice'] and d['courier'] not in core.COURIERS and d['courier']!='기타':return '택배사를 골라 주세요','error',None
    if cur and cur['status'] in ('paid','ready') and d['invoice'] and not cur['invoice'] and 'status' not in f:d['status']='shipped'  # 송장을 넣으면 배송 중
    dup=db.execute('SELECT id FROM orders WHERE company_id=? AND order_no=?',(co['id'],d['order_no'])).fetchone()
    if dup and dup['id']!=oid:return '같은 주문번호가 이미 있어요','error',None
    t=core.iso()
    if cur:
        db.execute('UPDATE orders SET '+','.join(f'{k}=?' for k in d)+',updated=? WHERE id=?',list(d.values())+[t,oid]);return '저장했어요','ok',oid
    if db.execute('SELECT COUNT(*) FROM orders WHERE company_id=?',(co['id'],)).fetchone()[0]>=MAX_ORDERS:return f'주문은 {MAX_ORDERS:,}건까지 둘 수 있어요','error',None
    cur_id=db.execute('INSERT INTO orders(company_id,'+','.join(d)+',created,updated) VALUES(?,'+','.join('?'*len(d))+',?,?)',[co['id']]+list(d.values())+[t,t]).lastrowid
    return '주문을 넣었어요','ok',cur_id
def delete(db,co,oid):db.execute('DELETE FROM orders WHERE id=? AND company_id=?',(oid,co['id']))

def import_csv(db,co,raw,channel=''):
    """판매처에서 받은 주문 엑셀을 'CSV'로 저장해 올린다. 주문번호가 같으면 고쳐 쓴다(상태·송장 갱신). (안내 문구, 'ok'|'error')"""
    for enc in ('utf-8-sig','cp949'):
        try:text=raw.decode(enc);break
        except UnicodeDecodeError:text=None
    if text is None:return '파일을 읽지 못했어요. 엑셀에서 CSV(쉼표로 분리)로 저장해 주세요','error'
    rows=list(csv.reader(io.StringIO(text)))
    # 판매처 엑셀은 첫 줄에 안내 문구가 있을 때가 있어, 주문번호 칸이 있는 줄을 머리글로 쓴다
    hi=next((k for k,r in enumerate(rows[:5]) if any(h.strip() in COLS['order_no'] for h in r)),None)
    if hi is None:return '첫 줄에 "주문번호" 칸이 있어야 해요','error'
    head=[h.strip() for h in rows[hi]]
    idx={k:next((i for i,h in enumerate(head) if h in names),None) for k,names in COLS.items()}
    if idx['order_no'] is None and '상품주문번호' in head:idx['order_no']=head.index('상품주문번호')
    channel=channel if channel in CHANNELS else ''
    have={r['order_no']:r for r in db.execute('SELECT * FROM orders WHERE company_id=?',(co['id'],)).fetchall()}
    n_new=n_upd=0;t=core.iso()
    for r in rows[hi+1:hi+1+MAX_ROWS]:
        get=lambda k:(r[idx[k]].strip() if idx[k] is not None and idx[k]<len(r) else '')
        no=get('order_no')[:60]
        if not no:continue
        prod=get('product')[:150];opt=get('option')[:50]
        inv=digits(get('invoice'))[:20];cour=get('courier')
        cour=next((k for k in core.COURIERS if cour and (cour in k or k.startswith(cour[:2]))),'기타' if cour else '')
        d=dict(channel=channel or (get('channel') if get('channel') in CHANNELS else '기타' if get('channel') else '직접'),
               ordered_on=re.sub(r'[./]','-',get('ordered_on'))[:10],buyer=get('buyer')[:30],phone=digits(get('phone'))[:11],address=get('address')[:200],
               product=(prod+(' / '+opt if opt else ''))[:200],qty=max(1,min(num(get('qty')) or 1,9999)),amount=num(get('amount')),
               status=status_from(get('status'),inv),courier=cour,invoice=inv)
        if no in have:
            old=have[no]
            if old['status'] in ('canceled','returned','refunded','exchanged') and d['status'] in ('paid','ready','shipped'):d['status']=old['status']  # 소보루에서 처리한 결과를 덮지 않는다
            if not d['invoice']:d['invoice'],d['courier']=old['invoice'],old['courier']
            db.execute('UPDATE orders SET '+','.join(f'{k}=?' for k in d)+',updated=? WHERE id=?',list(d.values())+[t,old['id']]);n_upd+=1
        else:
            if len(have)+n_new>=MAX_ORDERS:break
            db.execute('INSERT INTO orders(company_id,order_no,'+','.join(d)+',created,updated) VALUES(?,?,'+','.join('?'*len(d))+',?,?)',[co['id'],no]+list(d.values())+[t,t])
            have[no]=None;n_new+=1
    if not (n_new or n_upd):return '올릴 주문이 없어요','error'
    return f'새 주문 {n_new}건, 고친 주문 {n_upd}건을 저장했어요','ok'

def as_dict(o):
    return dict(id=o['id'],order_no=o['order_no'],channel=o['channel'],ordered_on=o['ordered_on'],buyer=o['buyer'],phone=core.fmt_phone(o['phone']) if o['phone'] else '',
                address=o['address'],product=o['product'],qty=o['qty'],amount=o['amount'],status=o['status'],status_label=STATUS.get(o['status'],''),
                courier=o['courier'],invoice=o['invoice'],memo=o['memo'],link=core.COURIERS.get(o['courier'],''),updated=o['updated'])
