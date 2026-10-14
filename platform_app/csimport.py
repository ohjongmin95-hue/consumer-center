"""지난 CS 자료 가져오기: 다른 곳(엑셀·다른 상담 도구)에 쌓인 문의를 한 번에 옮긴다 (Gorgias의 Help desk import에 해당).

  · CSV(쉼표) 또는 엑셀(.xlsx) 파일을 올리면 머리글을 읽어 칸을 짐작해 맞춰 두고, 사장님이 고칠 수 있게 보여 준다.
  · 저장 전에 줄마다 오류(내용 없음, 날짜 이상 등)와 중복(이미 있는 문의, 파일 안 중복)을 보여 주고, 문제없는 줄만 옮긴다.
  · 옮긴 문의는 지난 기록이라 '종료'로 들어간다(기한 알림·소비자 알림 없음). 미처리 건만 처리 대기로 올리기를 고를 수 있다.
  · 한 번에 옮긴 묶음은 통째로 되돌릴 수 있다.
"""
import csv, datetime, hashlib, io, json, re, secrets, zipfile
import xml.etree.ElementTree as ET
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session, g
from werkzeug.security import generate_password_hash
import core
from core import conn, clean, digits, BIG

bp=Blueprint('imp',__name__)
MAX_ROWS=5000
MAX_BYTES=8_000_000
# (칸, 이름, 필수, 머리글로 쓰는 말들)
FIELDS=[('received','접수 일시',True,['접수일','접수일시','문의일','문의일시','작성일','작성일시','등록일','등록일시','날짜','일시','created','created_at','date']),
        ('title','제목',False,['제목','문의제목','요약','subject','title']),
        ('body','문의 내용',True,['내용','문의내용','본문','질문','문의','message','body','question','description']),
        ('answer','답변 내용',False,['답변','답변내용','처리내용','응대내용','reply','answer','response']),
        ('answered','답변 일시',False,['답변일','답변일시','처리일','처리일시','answered_at','replied_at']),
        ('status','처리 상태',False,['상태','처리상태','진행상태','status']),
        ('category','유형',False,['유형','문의유형','분류','카테고리','category','type']),
        ('channel','받은 곳',False,['채널','판매처','접수경로','경로','channel','source']),
        ('order_no','주문번호',False,['주문번호','상품주문번호','order','order_no','order_id']),
        ('product','상품',False,['상품','상품명','product']),
        ('name','고객 이름',False,['이름','고객명','구매자','구매자명','작성자','고객','name','customer']),
        ('phone','연락처',False,['연락처','전화','전화번호','휴대폰','phone']),
        ('email','이메일',False,['이메일','메일','email'])]
FIELD_NAME={k:n for k,n,_,_ in FIELDS}
DONE_WORDS=('완료','답변완료','처리완료','종료','해결','closed','resolved','done','answered','solved')
CHANNEL_OF={'스마트스토어':'스마트스토어','네이버':'스마트스토어','쿠팡':'쿠팡','전화':'전화','카카오':'카카오톡','카톡':'카카오톡','인스타':'인스타그램 DM','이메일':'이메일','메일':'이메일','자사몰':'쇼핑몰 문의','카페24':'쇼핑몰 문의','쇼핑몰':'쇼핑몰 문의','게시판':'쇼핑몰 문의'}

def init():
    with conn() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS import_batches(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,token TEXT UNIQUE NOT NULL,filename TEXT NOT NULL,
            head TEXT NOT NULL,data TEXT NOT NULL,mapping TEXT NOT NULL DEFAULT '{}',open_pending INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'ready',
            n_rows INTEGER NOT NULL DEFAULT 0,n_ok INTEGER NOT NULL DEFAULT 0,n_dup INTEGER NOT NULL DEFAULT 0,n_err INTEGER NOT NULL DEFAULT 0,actor TEXT NOT NULL DEFAULT '',
            created TEXT NOT NULL,done TEXT NOT NULL DEFAULT '')''')
        cols={r[1] for r in db.execute('PRAGMA table_info(cases)')}
        if 'import_batch' not in cols:db.execute('ALTER TABLE cases ADD COLUMN import_batch INTEGER NOT NULL DEFAULT 0')
        if 'import_key' not in cols:db.execute("ALTER TABLE cases ADD COLUMN import_key TEXT NOT NULL DEFAULT ''")
        db.execute('CREATE INDEX IF NOT EXISTS cases_import ON cases(company_id,import_key)')
init()

# ---------- 파일 읽기 ----------
def read_table(name,raw):
    """(머리글, 줄들, 오류). CSV는 utf-8/cp949, 엑셀은 첫 시트."""
    if len(raw)>MAX_BYTES:return None,None,'파일이 너무 커요. 8MB까지 올릴 수 있어요'
    if name.lower().endswith('.xlsx'):
        try:rows=read_xlsx(raw)
        except Exception:return None,None,'엑셀 파일을 읽지 못했어요. CSV(쉼표로 분리)로 저장해서 올려 주세요'
    elif name.lower().endswith(('.csv','.txt')):
        text=None
        for enc in ('utf-8-sig','cp949'):
            try:text=raw.decode(enc);break
            except UnicodeDecodeError:pass
        if text is None:return None,None,'파일을 읽지 못했어요. 엑셀에서 CSV(쉼표로 분리)로 저장해 주세요'
        rows=list(csv.reader(io.StringIO(text)))
    else:return None,None,'CSV 또는 엑셀(.xlsx) 파일만 올릴 수 있어요'
    rows=[[str(x).strip() for x in r] for r in rows if any(str(x).strip() for x in r)]
    if len(rows)<2:return None,None,'머리글 한 줄과 문의가 한 줄 이상 있어야 해요'
    head=[h or f'{i+1}번째 칸' for i,h in enumerate(rows[0])]
    body=rows[1:]
    if len(body)>MAX_ROWS:return None,None,f'한 번에 {MAX_ROWS:,}줄까지 올릴 수 있어요. 파일을 나눠 주세요'
    return head,[r+['']*(len(head)-len(r)) for r in body],''

NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
def read_xlsx(raw):
    """외부 라이브러리 없이 엑셀 첫 시트를 읽는다 (글자·숫자만, 서식은 무시)."""
    z=zipfile.ZipFile(io.BytesIO(raw))
    shared=[]
    if 'xl/sharedStrings.xml' in z.namelist():
        for si in ET.fromstring(z.read('xl/sharedStrings.xml')).iter(NS+'si'):shared.append(''.join(t.text or '' for t in si.iter(NS+'t')))
    sheets=sorted(n for n in z.namelist() if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',n))
    sheet=ET.fromstring(z.read(sheets[0]))
    out=[]
    for row in sheet.iter(NS+'row'):
        cells={}
        for c in row.iter(NS+'c'):
            ref=re.match(r'([A-Z]+)',c.get('r','A'));col=0
            for ch in ref.group(1):col=col*26+ord(ch)-64
            t=c.get('t');v=c.find(NS+'v')
            if t=='s' and v is not None:val=shared[int(v.text)]
            elif t=='inlineStr':val=''.join(x.text or '' for x in c.iter(NS+'t'))
            else:val=v.text if v is not None and v.text else ''
            cells[col-1]=val
        if cells:out.append([cells.get(i,'') for i in range(max(cells)+1)])
        if len(out)>MAX_ROWS+1:break
    return out

def guess(head):
    """머리글 -> {칸: 번호} 짐작."""
    norm=[re.sub(r'[\s_()\-·/]','',h).lower() for h in head];m={}
    for k,_,_,names in FIELDS:
        names=[re.sub(r'[\s_()\-·/]','',n).lower() for n in names]
        i=next((i for i,h in enumerate(norm) if h in names and i not in m.values()),None)
        if i is None:i=next((i for i,h in enumerate(norm) if any(n in h for n in names if len(n)>=2) and i not in m.values()),None)
        if i is not None:m[k]=i
    return m

def parse_when(v):
    v=(v or '').strip()
    if not v:return None
    if re.fullmatch(r'\d{4,5}(\.\d+)?',v):  # 엑셀 날짜 숫자
        n=float(v)
        if 20000<n<80000:return (datetime.datetime(1899,12,30)+datetime.timedelta(days=n)).replace(microsecond=0)
        return None
    s=re.sub(r'[./]','-',v).replace('T',' ')
    s=re.sub(r'\s*(오전|오후)\s*',lambda x:' '+x.group(1)+' ',s).strip()
    pm='오후' in s;s=s.replace('오전','').replace('오후','')
    m=re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})\.?(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?',re.sub(r'\s+',' ',s))
    if not m:return None
    try:
        h=int(m.group(4) or 0)
        if pm and h<12:h+=12
        return datetime.datetime(int(m.group(1)),int(m.group(2)),int(m.group(3)),h,int(m.group(5) or 0),int(m.group(6) or 0))
    except ValueError:return None

def key_of(co_id,when,order_no,body):
    return hashlib.sha256(f"{co_id}|{when:%Y-%m-%d %H:%M}|{order_no}|{re.sub(r'\s+',' ',body)[:200]}".encode()).hexdigest()[:32]

def check(db,co,head,rows,mapping):
    """줄마다 결과: dict(n, d(값), err, dup, key)."""
    have={r[0] for r in db.execute("SELECT import_key FROM cases WHERE company_id=? AND import_key!=''",(co['id'],))}
    seen=set();out=[]
    now=core.now()
    for n,r in enumerate(rows,start=2):
        get=lambda k:(r[mapping[k]] if k in mapping and mapping[k]<len(r) else '').strip()
        d={k:get(k) for k,_,_,_ in FIELDS};err=[]
        if not d['body'] and not d['title']:err.append('문의 내용이 비어 있어요')
        w=parse_when(d['received'])
        if not w:err.append('접수 일시를 읽지 못했어요' if d['received'] else '접수 일시가 비어 있어요')
        elif w>now+datetime.timedelta(days=1) or w.year<2000:err.append('접수 일시가 이상해요')
        aw=parse_when(d['answered']) if d['answered'] else None
        if d['answered'] and not aw:err.append('답변 일시를 읽지 못했어요')
        if d['email'] and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',d['email']):err.append('이메일 모양이 아니에요')
        if d['phone'] and not 9<=len(digits(d['phone']))<=12:err.append('연락처 자릿수가 이상해요')
        key=key_of(co['id'],w,d['order_no'],d['body'] or d['title']) if w else ''
        dup='' if err else ('이미 있는 문의' if key in have else '파일 안에서 겹침' if key in seen else '')
        if key and not err:seen.add(key)
        out.append(dict(n=n,d=d,when=w,answered=aw,err=err,dup=dup,key=key))
    return out

def channel_of(v):
    v=(v or '').replace(' ','')
    for k,ch in CHANNEL_OF.items():
        if k in v:return ch
    return '기타'

def commit(db,co,b,res):
    """문제없는 줄을 문의로 옮긴다. 옮긴 수."""
    n=0;t=core.iso();actor=getattr(g,'actor','') or ''
    for x in res:
        if x['err'] or x['dup']:continue
        d=x['d'];text=(d['title']+' '+d['body']).strip()
        cat=d['category'] if d['category'] in core.CATS else (core.classify(text) or '기타')
        done=bool(d['answer']) or any(w in d['status'].replace(' ','').lower() for w in DONE_WORDS)
        st='closed' if (done or not b['open_pending']) else 'seen'
        title=clean(d['title'],60) or clean(re.sub(r'\s+',' ',d['body']),40)
        when=core.iso(x['when'])
        due='' if st=='closed' else core.iso(core.now()+datetime.timedelta(days=core.REPLY_DAYS))
        cid=db.execute('''INSERT INTO cases(no,company_id,company_name,member,category,title,body,want,order_no,name,phone,email,lookup_hash,consent,status,decision,due,created,updated,product,received_on,channel,import_batch,import_key)
            VALUES(?,?,?,1,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,'',?,?,?)''',(core.new_case_no(db),co['id'],co['name'],cat,title,clean(d['body'],BIG) or title,core.WANT_OF.get(cat,'기타'),
            clean(d['order_no'],40),clean(d['name'],20),digits(d['phone'])[:11],clean(d['email'],80),generate_password_hash(secrets.token_hex(8),method='pbkdf2:sha256:1000'),
            st,'direct' if d['answer'] else ('pending' if st=='seen' else ''),due,when,t,clean(d['product'],60),channel_of(d['channel']),b['id'],x['key'])).lastrowid
        db.execute("INSERT INTO events(case_id,kind,text,reply,created,actor) VALUES(?,?,?,?,?,?)",(cid,'sys',f"'{b['filename']}'에서 가져온 지난 문의예요",'',when,actor))
        if d['answer']:
            db.execute("INSERT INTO events(case_id,kind,text,reply,created,actor) VALUES(?,?,?,?,?,?)",(cid,'co','지난 답변 (가져옴)',clean(d['answer'],BIG),core.iso(x['answered']) if x['answered'] else when,actor))
        n+=1
    return n

# ---------- 화면 ----------
def company():
    import business
    co=business.me()
    if not co:abort(403)
    return co

@bp.route('/import',methods=['GET','POST'])
def page():
    if not session.get('co_id'):return redirect(url_for('login'))
    co=company()
    if request.method=='POST':
        up=request.files.get('file')
        if not up or not up.filename:flash('파일을 골라 주세요','error');return redirect(url_for('imp.page'))
        head,rows,err=read_table(up.filename,up.read(MAX_BYTES+1))
        if err:flash(err,'error');return redirect(url_for('imp.page'))
        tok=secrets.token_urlsafe(12)
        with conn() as db:
            db.execute("DELETE FROM import_batches WHERE company_id=? AND status='ready'",(co['id'],))  # 저장하지 않고 둔 이전 파일은 버린다
            db.execute('INSERT INTO import_batches(company_id,token,filename,head,data,mapping,n_rows,created) VALUES(?,?,?,?,?,?,?,?)',
                       (co['id'],tok,clean(up.filename,120),json.dumps(head,ensure_ascii=False),json.dumps(rows,ensure_ascii=False),json.dumps(guess(head)),len(rows),core.iso()))
        return redirect(url_for('imp.batch',token=tok))
    with conn() as db:
        hist=db.execute("SELECT * FROM import_batches WHERE company_id=? AND status!='ready' ORDER BY id DESC LIMIT 20",(co['id'],)).fetchall()
    return render_template('b_import.html',hist=hist,FIELDS=FIELDS,MAX_ROWS=MAX_ROWS,tab='all')

@bp.route('/import/<token>',methods=['GET','POST'])
def batch(token):
    if not session.get('co_id'):return redirect(url_for('login'))
    co=company()
    with conn() as db:
        b=db.execute('SELECT * FROM import_batches WHERE token=? AND company_id=?',(token,co['id'])).fetchone()
        if not b:abort(404)
        if b['status']!='ready':return redirect(url_for('imp.page'))
        head=json.loads(b['head']);rows=json.loads(b['data']);mapping={k:int(v) for k,v in json.loads(b['mapping']).items()}
        if request.method=='POST':
            act=request.form.get('act')
            if act=='cancel':
                db.execute('DELETE FROM import_batches WHERE id=?',(b['id'],));flash('올린 파일을 버렸어요','ok');return redirect(url_for('imp.page'))
            mapping={}
            for k,_,_,_ in FIELDS:
                v=request.form.get('f_'+k,'')
                if v.isdigit() and int(v)<len(head):mapping[k]=int(v)
            op=1 if request.form.get('open_pending')=='1' else 0
            db.execute('UPDATE import_batches SET mapping=?,open_pending=? WHERE id=?',(json.dumps(mapping),op,b['id']))
            b=db.execute('SELECT * FROM import_batches WHERE id=?',(b['id'],)).fetchone()
            miss=[n for k,n,req,_ in FIELDS if req and k not in mapping and not (k=='body' and 'title' in mapping)]
            if miss:flash(', '.join(miss)+' 칸을 골라 주세요','error');return redirect(url_for('imp.batch',token=token))
            if act=='commit':
                res=check(db,co,head,rows,mapping)
                n=commit(db,co,b,res)
                db.execute("UPDATE import_batches SET status='done',data='[]',n_ok=?,n_dup=?,n_err=?,actor=?,done=? WHERE id=?",
                           (n,sum(1 for x in res if x['dup']),sum(1 for x in res if x['err']),getattr(g,'actor','') or '',core.iso(),b['id']))
                flash(f'지난 문의 {n:,}건을 옮겼어요','ok');return redirect(url_for('imp.page'))
            return redirect(url_for('imp.batch',token=token))
        res=check(db,co,head,rows,mapping)
    ok=[x for x in res if not x['err'] and not x['dup']]
    return render_template('b_import_map.html',bt=b,head=head,sample=rows[:3],mapping=mapping,res=res,n_ok=len(ok),
                           n_dup=sum(1 for x in res if x['dup']),n_err=sum(1 for x in res if x['err']),problems=[x for x in res if x['err'] or x['dup']][:200],
                           preview=ok[:5],FIELDS=FIELDS,FIELD_NAME=FIELD_NAME,channel_of=channel_of,tab='all')

@bp.route('/import/undo/<int:bid>',methods=['POST'])
def undo(bid):
    if not session.get('co_id'):return redirect(url_for('login'))
    co=company()
    with conn() as db:
        b=db.execute("SELECT * FROM import_batches WHERE id=? AND company_id=? AND status='done'",(bid,co['id'])).fetchone()
        if not b:abort(404)
        ids=[r[0] for r in db.execute('SELECT id FROM cases WHERE company_id=? AND import_batch=?',(co['id'],bid))]
        for i in range(0,len(ids),500):
            part=ids[i:i+500];q=','.join('?'*len(part))
            for tbl in ('events','files','notes','tracks','app_push'):
                try:db.execute(f'DELETE FROM {tbl} WHERE case_id IN ({q})',part)
                except Exception:pass
            db.execute(f'DELETE FROM cases WHERE id IN ({q})',part)
        db.execute("UPDATE import_batches SET status='undone',done=? WHERE id=?",(core.iso(),bid))
    flash(f'가져온 문의 {len(ids):,}건을 되돌렸어요','ok');return redirect(url_for('imp.page'))
