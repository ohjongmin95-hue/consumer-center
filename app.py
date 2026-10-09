import os, re, json, sqlite3, secrets, hashlib, hmac, datetime, functools, contextlib
from pathlib import Path
from flask import Flask, g, render_template, request, redirect, url_for, session, flash, abort, send_file
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from markupsafe import Markup, escape
import site_content

BASE=Path(__file__).parent
DB=Path(os.getenv('DATABASE_PATH',str(BASE/'cases.sqlite3')))
UPLOAD=Path(os.getenv('UPLOAD_DIR',str(BASE/'private_uploads')))
UPLOAD.mkdir(parents=True,exist_ok=True)
app=Flask(__name__)
if os.getenv('TRUST_PROXY')=='1':app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1,x_host=1)
app.secret_key=os.getenv('SECRET_KEY',secrets.token_hex(32))
if (os.getenv('ENABLE_INTAKE')=='1' or os.getenv('ENABLE_BOARD')=='1') and (not os.getenv('SECRET_KEY') or not os.getenv('ADMIN_PASSWORD_HASH')):
    raise RuntimeError('제보 접수나 게시판을 활성화하려면 SECRET_KEY와 ADMIN_PASSWORD_HASH가 필요합니다.')
app.config['MAX_CONTENT_LENGTH']=15*1024*1024
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('HTTPS_ONLY')=='1')
STATUSES=site_content.STATUSES
HOME_LATEST=8  # 메인 화면 최신 제보 수 기본값 (관리자 '메인 화면'에서 3~20으로 변경)
REPORTS_PAGE_SIZE=20
def status_step(status):return STATUSES.index(status)+1 if status in STATUSES else 1

@contextlib.contextmanager
def conn():
    # 커밋(오류 시 롤백) 후 연결을 닫음. sqlite3 기본 with 문은 연결을 닫지 않음.
    db=sqlite3.connect(DB,timeout=10); db.row_factory=sqlite3.Row
    try:
        with db:yield db
    finally:db.close()

def init():
    with conn() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS cases(id INTEGER PRIMARY KEY,receipt TEXT UNIQUE NOT NULL,lookup_hash TEXT NOT NULL,category TEXT NOT NULL,company TEXT NOT NULL,subject TEXT NOT NULL,description TEXT NOT NULL,request_text TEXT NOT NULL,contact TEXT,share_company INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT '접수',created TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS attachments(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL,stored TEXT NOT NULL,original TEXT NOT NULL,FOREIGN KEY(case_id) REFERENCES cases(id))''')
        db.execute('''CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL,author TEXT NOT NULL,body TEXT NOT NULL,created TEXT NOT NULL,FOREIGN KEY(case_id) REFERENCES cases(id))''')
init()
with conn() as db:
    db.execute('''CREATE TABLE IF NOT EXISTS company_invites(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL UNIQUE,token_hash TEXT NOT NULL,company_name TEXT NOT NULL,created TEXT NOT NULL,FOREIGN KEY(case_id) REFERENCES cases(id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS internal_notes(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL,note TEXT NOT NULL,created TEXT NOT NULL,FOREIGN KEY(case_id) REFERENCES cases(id))''')
    cols={row['name'] for row in db.execute('PRAGMA table_info(cases)')}
    if 'assignee' not in cols: db.execute("ALTER TABLE cases ADD COLUMN assignee TEXT DEFAULT ''")
    if 'public_consent' not in cols: db.execute('ALTER TABLE cases ADD COLUMN public_consent INTEGER NOT NULL DEFAULT 0')
    if 'published' not in cols: db.execute('ALTER TABLE cases ADD COLUMN published INTEGER NOT NULL DEFAULT 0')
    if 'use_consent' not in cols: db.execute('ALTER TABLE cases ADD COLUMN use_consent INTEGER NOT NULL DEFAULT 0')
    db.execute('CREATE TABLE IF NOT EXISTS site_content(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS site_lists(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated TEXT NOT NULL)')
    db.execute("CREATE TABLE IF NOT EXISTS takedown_requests(id INTEGER PRIMARY KEY,requester TEXT NOT NULL,contact TEXT NOT NULL,target TEXT NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT '접수',admin_note TEXT NOT NULL DEFAULT '',created TEXT NOT NULL)")
TAKEDOWN_STATUSES=['접수','검토 중','임시 비공개','비공개 처리','기각','처리 완료']

def load_content():
    with conn() as db:saved={r['key']:r['value'] for r in db.execute('SELECT key,value FROM site_content')}
    return {k:saved[k] if k in saved and (saved[k] or f.get('optional')) else f['default'] for k,f in site_content.FIELDS.items()}
def legacy_list(db,key):
    # 예전에 고정 칸(faq.q1~8, process.step1~4, nav.*)으로 수정해 둔 값이 있으면 그 내용을 첫 목록으로 씀.
    if key=='menu':
        saved={r['key']:r['value'] for r in db.execute("SELECT key,value FROM site_content WHERE key LIKE 'nav.%'")}
        return [{'label':saved.get(k) or label,'page':page,'url':''} for k,page,label in site_content.LEGACY_NAV] if saved else None
    prefix={'faq':'faq.','process_steps':'process.step'}.get(key)
    if not prefix:return None
    saved={r['key']:r['value'] for r in db.execute('SELECT key,value FROM site_content WHERE key LIKE ?',(prefix+'%',))}
    if not saved:return None
    if key=='faq':
        old=dict(zip(['faq.q%d'%i for i in range(1,9)],[q for q,_ in site_content.FAQ_DEFAULTS]+['']*8))|dict(zip(['faq.a%d'%i for i in range(1,9)],[a for _,a in site_content.FAQ_DEFAULTS]+['']*8))
        return [{'q':saved.get('faq.q%d'%i,old['faq.q%d'%i]),'a':saved.get('faq.a%d'%i,old['faq.a%d'%i])} for i in range(1,9) if saved.get('faq.q%d'%i,old['faq.q%d'%i])]
    old={}
    for i,(t,b) in enumerate(site_content.PROCESS_DEFAULTS,1):old['process.step%d_title'%i]=t;old['process.step%d_body'%i]=b
    return [{'title':saved.get('process.step%d_title'%i,old.get('process.step%d_title'%i,'')),'body':saved.get('process.step%d_body'%i,old.get('process.step%d_body'%i,''))} for i in range(1,5) if saved.get('process.step%d_title'%i,old.get('process.step%d_title'%i,''))]
def load_lists():
    with conn() as db:
        saved={r['key']:json.loads(r['value']) for r in db.execute('SELECT key,value FROM site_lists')}
        return {key:saved[key] if key in saved else (legacy_list(db,key) or site_content.LIST_DEFAULTS[key]) for key,*_ in site_content.LISTS}
@app.before_request
def content_for_request():
    if request.endpoint!='static':g.content=load_content();g.lists=load_lists()
def items(key):return g.lists.get(key,[])
def report_categories():return [i['name'] for i in items('report_categories')]
def board_categories():return [i['name'] for i in items('board_categories')]
app.jinja_env.globals['items']=items
SAFE_LINK=re.compile(r'^(https?://[^\s<>"]+|/[^\s<>"]*)$')
def menu_href(item):
    page=item.get('page','')
    if page=='custom':return item.get('url','') if SAFE_LINK.match(item.get('url','')) else '#'
    if page in ('guide','process','faq','types'):return url_for('info_page',page=page)
    if page in ('terms','privacy'):return url_for('policy_page',page=page)
    if page in ('reports','board','report','lookup','home','takedown'):return url_for(page)
    return '#'
def menu_active(href):
    # 현재 페이지가 이 메뉴 주소이거나 그 하위 주소(예: /reports/12, /board/3)면 강조.
    if not href.startswith('/') or href=='#':return False
    return request.path==href or (href!='/' and request.path.startswith(href.rstrip('/')+'/'))
def block_count(item,default,top=30):
    try:return min(top,max(1,int(item.get('count',''))))
    except ValueError:return default
app.jinja_env.globals.update(menu_href=menu_href,menu_active=menu_active,block_count=block_count)
EMPHASIS=re.compile(r'\*\*(.+?)\*\*')
@app.template_filter('emph')
def emph(text):
    # 관리자 글의 **강조**만 <strong>으로 바꾸고 나머지는 모두 이스케이프. 줄바꿈은 <br>.
    out=EMPHASIS.sub(lambda m:'\0'+m.group(1)+'\1',(text or '').replace('\0','').replace('\1',''))
    html=str(escape(out)).replace('\0','<strong class="em">').replace('\1','</strong>').replace('\n','<br>')
    return Markup(html)
STEP_ICON_ORDER=['write','search','chat','scale','check','bell','shield','call']
app.jinja_env.globals['step_icon']=lambda item,i:item.get('icon') or STEP_ICON_ORDER[i%len(STEP_ICON_ORDER)]
def txt(key):
    # 관리자가 입력한 문구는 HTML로 해석하지 않고 줄바꿈만 반영함.
    return Markup('<br>').join(escape(line) for line in g.content.get(key,'').split('\n'))
app.jinja_env.globals['txt']=txt
app.jinja_env.globals['STATUSES']=STATUSES
app.jinja_env.globals['status_step']=status_step
DOC_VARS={'운영자':'operator.name','대표자':'operator.ceo','이메일':'operator.email','전화':'operator.phone','주소':'operator.address','보호책임자':'operator.privacy_officer','보호책임자연락처':'operator.privacy_contact','청소년보호책임자':'operator.youth_officer','청소년보호책임자연락처':'operator.youth_contact','시행일':'policy.effective_date'}
DOC_FALLBACK={'operator.youth_officer':'operator.privacy_officer','operator.youth_contact':'operator.privacy_contact'}
def doc_value(src):
    return g.content.get(src) or g.content.get(DOC_FALLBACK.get(src,''),'') or '(운영자 정보 미입력)'
def doc_headings(key):
    # 목차용: "## " 소제목 목록 (본문 h2의 id와 같은 순서)
    return [line.strip()[3:] for line in g.content.get(key,'').split('\n') if line.strip().startswith('## ')]
app.jinja_env.globals['doc_headings']=doc_headings
FOOTER_ROWS=[[('operator.name','상호'),('operator.ceo','대표'),('operator.address','소재지')],
             [('operator.phone','전화'),('operator.fax','팩스'),('operator.email','이메일'),('operator.biz_no','사업자등록번호')],
             [('operator.privacy_officer','개인정보 보호책임자'),('operator.youth_officer','청소년보호책임자')]]
def footer_rows():
    # 푸터 사업자 정보: 입력된 항목만, 줄 단위로 묶어서 보여 줌
    rows=[[(label,g.content.get(key)) for key,label in row if g.content.get(key)] for row in FOOTER_ROWS]
    return [row for row in rows if row]
app.jinja_env.globals['footer_rows']=footer_rows
def doc(key):
    # 약관류 본문: "## "는 소제목, "- "는 목록, 빈 줄은 문단 구분. {운영자} 등은 운영자 정보로 치환.
    text=g.content.get(key,'')
    # 긴 이름부터 바꿔야 {청소년보호책임자연락처}가 {보호책임자}로 먼저 잘못 바뀌지 않음
    for name,src in sorted(DOC_VARS.items(),key=lambda kv:-len(kv[0])):text=text.replace('{'+name+'}',doc_value(src))
    out=[];items=[];heads=0
    def flush():
        if items:out.append(Markup('<ul>')+Markup('').join(Markup('<li>%s</li>')%i for i in items)+Markup('</ul>'));items.clear()
    for line in text.split('\n'):
        line=line.strip()
        if line.startswith('- '):items.append(line[2:]);continue
        flush()
        if line.startswith('## '):heads+=1;out.append(Markup('<h2 id="sec-%d">%s</h2>')%(heads,line[3:]))
        elif line:out.append(Markup('<p>%s</p>')%line)
    flush()
    return Markup('\n').join(out)
app.jinja_env.globals['doc']=doc

def csrf():
    if '_csrf' not in session: session['_csrf']=secrets.token_urlsafe(32)
    return session['_csrf']
app.jinja_env.globals['csrf_token']=csrf
@app.before_request
def protect():
    if request.method=='POST' and not hmac.compare_digest(str(request.form.get('_csrf','')),str(csrf())): abort(400)
@app.after_request
def headers(resp):
    resp.headers['X-Content-Type-Options']='nosniff';resp.headers['X-Frame-Options']='DENY';resp.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    if request.path.startswith(('/report','/lookup','/admin','/case','/takedown','/company')):resp.headers['Cache-Control']='no-store'
    return resp
def report_rows(where='1=1',args=(),limit=20,offset=0):
    # 모든 제보를 번호·분류·단계·접수일로 보여 주고, 제목은 공개 제보(제보자가 공개 선택, 운영자가 내리지 않음)만 노출.
    with conn() as db:
        rows=db.execute('SELECT id,category,company,subject,status,created,public_consent,published FROM cases WHERE '+where+' ORDER BY id DESC LIMIT ? OFFSET ?',list(args)+[limit,offset]).fetchall()
    today=datetime.date.today().isoformat()
    def when(created):
        # 오늘 들어온 제보는 시각(15:48), 그 전은 날짜(10.08)로 짧게 표시.
        return created[11:16] if created[:10]==today and len(created)>=16 else created[5:10].replace('-','.')
    return [dict(no=r['id'],cat=r['category'],title=mask_personal(r['subject']) if r['public_consent'] and r['published'] else None,
                 company=mask_personal(r['company']) if r['public_consent'] and r['published'] else None,
                 status=r['status'],created=r['created'][:10],when=when(r['created'])) for r in rows]
def report_summary():
    with conn() as db:stats={r['status']:r['n'] for r in db.execute('SELECT status,COUNT(*) AS n FROM cases GROUP BY status')}
    total=sum(stats.values());done=stats.get('종결',0)
    return dict(total=total,done=done,active=total-done)

def home_latest():
    try:return min(20,max(3,int(g.content.get('home.latest_count',''))))
    except ValueError:return HOME_LATEST

def recent_posts(limit):
    with conn() as db:return db.execute('SELECT id,category,title,likes,comments,created FROM posts WHERE hidden=0 ORDER BY id DESC LIMIT ?',(limit,)).fetchall()
def sample_fill(cases,n):
    # 실제 제보가 n건보다 적으면 남는 자리만 '예시' 카드로 채움 (실제 제보처럼 보이지 않게 템플릿에서 표시).
    return items('sample_reports')[:max(0,n-len(cases))]
app.jinja_env.globals.update(report_rows=report_rows,report_summary=report_summary,recent_posts=recent_posts,home_latest=home_latest,sample_fill=sample_fill)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/reports/latest')
def latest_reports():
    # 메인 화면이 주기적으로 불러가는 최신 목록 조각 (실시간 갱신용). n은 블록에 정한 개수.
    n=min(30,max(1,request.args.get('n',home_latest(),type=int)))
    template='report_cards.html' if request.args.get('view')=='cards' else 'report_rows.html'
    resp=app.make_response(render_template(template,cases=report_rows(limit=n),summary=report_summary(),live=True,n=n))
    resp.headers['Cache-Control']='no-store'
    return resp

@app.route('/reports')
def reports():
    search_query=request.args.get('q','').strip()[:160]
    selected_category=request.args.get('category','')
    if selected_category not in report_categories():selected_category=''
    page=max(1,request.args.get('page',1,type=int))
    where=['1=1'];args=[]
    if selected_category:where.append('category=?');args.append(selected_category)
    if search_query:
        where.append("public_consent=1 AND published=1 AND subject LIKE ? ESCAPE '\\'")
        args.append('%'+search_query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
    cond=' AND '.join(where)
    with conn() as db:total=db.execute('SELECT COUNT(*) FROM cases WHERE '+cond,args).fetchone()[0]
    return render_template('reports.html',categories=report_categories(),cases=report_rows(cond,args,REPORTS_PAGE_SIZE,(page-1)*REPORTS_PAGE_SIZE),total=total,page=page,pages=max(1,-(-total//REPORTS_PAGE_SIZE)),summary=report_summary(),search_query=search_query,selected_category=selected_category)

PHONE_RE=re.compile(r'(01[016789]|0\d{1,2})[-.\s]?\d{3,4}[-.\s]?\d{4}')
EMAIL_RE=re.compile(r'[\w.+-]+@[\w-]+(\.[\w-]+)+')
def mask_personal(text):
    # 공개 화면에서만 전화번호·이메일로 보이는 부분을 가림 (원문은 그대로 보관).
    return EMAIL_RE.sub('[이메일 비공개]',PHONE_RE.sub('[전화번호 비공개]',text or ''))

@app.route('/reports/<int:case_id>')
def public_case(case_id):
    with conn() as db:case=db.execute('SELECT id,category,company,subject,description,request_text,status,created FROM cases WHERE id=? AND public_consent=1 AND published=1',(case_id,)).fetchone()
    if not case:abort(404)
    return render_template('public_case.html',case=case,company=mask_personal(case['company']),subject=mask_personal(case['subject']),description=mask_personal(case['description']),request_text=mask_personal(case['request_text']))

@app.route('/guide',defaults={'page':'guide'})
@app.route('/process',defaults={'page':'process'})
@app.route('/types',defaults={'page':'types'})
@app.route('/faq',defaults={'page':'faq'})
def info_page(page):
    return render_template('info.html',page=page,categories=report_categories())

def verification_code(key):
    # 관리자 칸에 코드만 넣어도, 사이트가 준 <meta ...> 태그를 통째로 붙여 넣어도 content 값만 꺼내 씀.
    value=g.content.get(key,'').strip()
    found=re.search(r'content=["\']([^"\']+)',value)
    return (found.group(1) if found else value).strip()
app.jinja_env.globals['verification_code']=verification_code

@app.route('/robots.txt')
def robots_txt():
    lines=['User-agent: *','Allow: /','Disallow: /admin','Disallow: /case','Disallow: /company/','Disallow: /board/write','Disallow: /reports/latest','','Sitemap: '+url_for('sitemap_xml',_external=True)]
    daum=g.content.get('seo.daum_robots','').strip()
    if daum:lines.insert(0,daum if daum.startswith('#') else '#'+daum)
    return app.response_class('\n'.join(lines)+'\n',mimetype='text/plain')

@app.route('/sitemap.xml')
def sitemap_xml():
    pages=[(url_for(e,_external=True),None) for e in ('home','reports','board','report','takedown')]
    pages+=[(url_for('info_page',page=p,_external=True),None) for p in ('guide','process','faq','types')]
    pages+=[(url_for('policy_page',page=p,_external=True),None) for p in ('terms','privacy','youth')]
    with conn() as db:
        pages+=[(url_for('public_case',case_id=r['id'],_external=True),r['created'][:10]) for r in db.execute('SELECT id,created FROM cases WHERE public_consent=1 AND published=1 ORDER BY id DESC LIMIT 5000')]
        pages+=[(url_for('board_post',post_id=r['id'],_external=True),r['created'][:10]) for r in db.execute('SELECT id,created FROM posts WHERE hidden=0 ORDER BY id DESC LIMIT 5000')]
    body=''.join('<url><loc>%s</loc>%s</url>'%(escape(u),'<lastmod>%s</lastmod>'%d if d else '') for u,d in pages)
    return app.response_class('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+body+'</urlset>',mimetype='application/xml')

@app.route('/terms',defaults={'page':'terms'})
@app.route('/privacy',defaults={'page':'privacy'})
@app.route('/youth',defaults={'page':'youth'})
def policy_page(page):
    return render_template('policy.html',page=page)

@app.route('/takedown',methods=['GET','POST'])
def takedown():
    if request.method=='POST':
        data={k:request.form.get(k,'').strip() for k in ('requester','contact','target','reason')}
        if any(not v for v in data.values()) or not request.form.get('consent'):
            flash('모든 항목과 개인정보 수집 동의를 확인해 주세요.');return render_template('takedown.html'),400
        if any(len(data[k])>limit for k,limit in [('requester',120),('contact',150),('target',300),('reason',5000)]):abort(400)
        with conn() as db:db.execute('INSERT INTO takedown_requests(requester,contact,target,reason,created) VALUES(?,?,?,?,?)',(data['requester'],data['contact'],data['target'],data['reason'],datetime.datetime.now().isoformat(timespec='seconds')))
        return render_template('takedown.html',submitted=True)
    return render_template('takedown.html')

@app.route('/report',methods=['GET','POST'])
def report():
    if request.method=='GET':return render_template('report.html',categories=report_categories(), intake_enabled=os.getenv('ENABLE_INTAKE')=='1')
    if os.getenv('ENABLE_INTAKE')!='1': abort(503, description='제보 접수 준비 중입니다.')
    data={k:request.form.get(k,'').strip() for k in ('category','company','subject','description','request_text','contact')}
    if data['category'] not in report_categories() or any(not data[k] for k in ('company','subject','description','request_text')) or not request.form.get('consent') or not request.form.get('truth') or request.form.get('visibility') not in ('public','secret'):
        flash('필수 항목과 필수 동의를 확인해 주세요.');return render_template('report.html',categories=report_categories(),intake_enabled=os.getenv('ENABLE_INTAKE')=='1'),400
    if any(len(data[k])>limit for k,limit in [('company',120),('subject',160),('description',6000),('request_text',3000),('contact',150)]):abort(400)
    file=request.files.get('evidence')
    if file and file.filename:
        suffix=Path(secure_filename(file.filename)).suffix.lower()
        if suffix not in ('.pdf','.png','.jpg','.jpeg','.webp'):flash('첨부는 PDF 또는 이미지 파일만 가능합니다.');return render_template('report.html',categories=report_categories(),intake_enabled=os.getenv('ENABLE_INTAKE')=='1'),400
        head=file.stream.read(12);file.stream.seek(0)
        valid=(suffix=='.pdf' and head.startswith(b'%PDF-')) or (suffix=='.png' and head.startswith(b'\x89PNG')) or (suffix in ('.jpg','.jpeg') and head.startswith(b'\xff\xd8')) or (suffix=='.webp' and head[8:12]==b'WEBP')
        if not valid:flash('첨부파일 형식을 확인해 주세요.');return render_template('report.html',categories=report_categories(),intake_enabled=os.getenv('ENABLE_INTAKE')=='1'),400
    receipt='CJ-'+datetime.datetime.now().strftime('%y%m%d')+'-'+secrets.token_hex(3).upper()
    code=secrets.token_urlsafe(12)
    with conn() as db:
        cur=db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,contact,share_company,created) VALUES(?,?,?,?,?,?,?,?,?,?)',(receipt,hashlib.sha256(code.encode()).hexdigest(),data['category'],data['company'],data['subject'],data['description'],data['request_text'],data['contact'],int(bool(request.form.get('share_company'))),datetime.datetime.now().isoformat(timespec='seconds')))
        public=int(request.form.get('visibility')=='public')
        db.execute('UPDATE cases SET public_consent=?,published=?,use_consent=? WHERE id=?',(public,public,int(bool(request.form.get('use_consent'))),cur.lastrowid))
        if file and file.filename:
            stored=secrets.token_hex(20)+suffix;file.save(UPLOAD/stored)
            db.execute('INSERT INTO attachments(case_id,stored,original) VALUES(?,?,?)',(cur.lastrowid,stored,secure_filename(file.filename)[:180]))
    return render_template('success.html',receipt=receipt,code=code)
@app.route('/lookup',methods=['GET','POST'])
def lookup():
    if request.method=='GET':return render_template('lookup.html')
    receipt=request.form.get('receipt','').strip().upper();code=request.form.get('code','').strip()
    with conn() as db:case=db.execute('SELECT * FROM cases WHERE receipt=?',(receipt,)).fetchone()
    if not case or not hmac.compare_digest(case['lookup_hash'],hashlib.sha256(code.encode()).hexdigest()):
        flash('접수번호 또는 조회 코드가 일치하지 않습니다.');return render_template('lookup.html'),401
    session.clear();session['case_id']=case['id'];return redirect(url_for('case_detail'))
@app.route('/case',methods=['GET','POST'])
def case_detail():
    case_id=session.get('case_id')
    if not case_id:return redirect(url_for('lookup'))
    with conn() as db:
        case=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        if not case:abort(404)
        if request.method=='POST':
            msg=request.form.get('message','').strip()
            if not msg or len(msg)>3000:abort(400)
            db.execute('INSERT INTO messages(case_id,author,body,created) VALUES(?,?,?,?)',(case_id,'제보자',msg,datetime.datetime.now().isoformat(timespec='seconds')))
            return redirect(url_for('case_detail'))
        msgs=db.execute('SELECT * FROM messages WHERE case_id=? ORDER BY id',(case_id,)).fetchall()
    return render_template('case.html',case=case,msgs=msgs)
@app.route('/admin/login',methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        stored=os.getenv('ADMIN_PASSWORD_HASH','')
        if stored and check_password_hash(stored,request.form.get('password','')):
            session.clear();session['admin']=True;return redirect(url_for('admin'))
        flash('로그인에 실패했습니다.')
    return render_template('admin_login.html')
def admin_only(f):
    @functools.wraps(f)
    def wrapped(*a,**kw):
        if not session.get('admin'):return redirect(url_for('admin_login'))
        return f(*a,**kw)
    return wrapped
@app.route('/admin')
@admin_only
def admin():
    with conn() as db:cases=db.execute('SELECT id,receipt,category,company,subject,status,created FROM cases ORDER BY id DESC LIMIT 200').fetchall()
    return render_template('admin.html',cases=cases)
@app.route('/admin/case/<int:case_id>',methods=['GET','POST'])
@admin_only
def admin_case(case_id):
    with conn() as db:
        case=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        if not case:abort(404)
        if request.method=='POST':
            status=request.form.get('status','')
            if status not in STATUSES:abort(400)
            db.execute('UPDATE cases SET status=?,assignee=?,published=? WHERE id=?',(status,request.form.get('assignee','').strip()[:80],int(bool(request.form.get('published'))) if case['public_consent'] else 0,case_id))
            note=request.form.get('internal_note','').strip()
            if note:
                if len(note)>3000:abort(400)
                db.execute('INSERT INTO internal_notes(case_id,note,created) VALUES(?,?,?)',(case_id,note,datetime.datetime.now().isoformat(timespec='seconds')))
            msg=request.form.get('message','').strip()
            if msg:
                if len(msg)>3000:abort(400)
                db.execute('INSERT INTO messages(case_id,author,body,created) VALUES(?,?,?,?)',(case_id,'센터',msg,datetime.datetime.now().isoformat(timespec='seconds')))
            return redirect(url_for('admin_case',case_id=case_id))
        msgs=db.execute('SELECT * FROM messages WHERE case_id=? ORDER BY id',(case_id,)).fetchall()
        files=db.execute('SELECT * FROM attachments WHERE case_id=?',(case_id,)).fetchall()
        notes=db.execute('SELECT * FROM internal_notes WHERE case_id=? ORDER BY id DESC',(case_id,)).fetchall()
        invite=db.execute('SELECT * FROM company_invites WHERE case_id=?',(case_id,)).fetchone()
    return render_template('admin_case.html',case=case,msgs=msgs,files=files,statuses=STATUSES,notes=notes,invite=invite)
@app.route('/admin/content',methods=['GET','POST'])
@admin_only
def admin_content():
    if request.method=='POST':
        now=datetime.datetime.now().isoformat(timespec='seconds')
        reset=request.form.get('reset_section','')
        with conn() as db:
            for key,field in site_content.FIELDS.items():
                if reset:
                    if field['section']==reset:db.execute('DELETE FROM site_content WHERE key=?',(key,))
                    continue
                if key not in request.form:continue
                value=request.form[key].replace('\r\n','\n').strip()
                if len(value)>(site_content.DOC_MAX_LENGTH if field.get('doc') else site_content.MAX_LENGTH):abort(400)
                if not field.get('multiline'):value=' '.join(value.split())
                if value==field['default'] or (not value and not field.get('optional')):db.execute('DELETE FROM site_content WHERE key=?',(key,))
                else:db.execute('INSERT INTO site_content(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated',(key,value,now))
        flash('기본값으로 되돌렸습니다.' if reset else '문구를 저장했습니다.')
        return redirect(url_for('admin_content',_anchor='section-'+(reset or request.form.get('section',''))))
    with conn() as db:changed={r['key'] for r in db.execute('SELECT key FROM site_content')}
    return render_template('admin_content.html',sections=site_content.SECTIONS,content=load_content(),changed=changed,policy_hint=site_content.POLICY_HINT)
@app.route('/admin/lists',methods=['GET','POST'])
@admin_only
def admin_lists():
    lists={key:(title,desc,fields,minimum) for key,title,desc,fields,minimum in site_content.LISTS}
    if request.method=='POST':
        key=request.form.get('list','')
        if key not in lists:abort(400)
        title,_,fields,minimum=lists[key]
        now=datetime.datetime.now().isoformat(timespec='seconds')
        if request.form.get('reset'):
            with conn() as db:db.execute('DELETE FROM site_lists WHERE key=?',(key,))
            flash(title+' 항목을 기본값으로 되돌렸습니다.');return redirect(url_for('admin_lists',_anchor='list-'+key))
        # 같은 이름의 칸이 항목 순서대로 반복되므로 필드별 getlist를 묶으면 화면 순서 그대로 항목이 됨.
        columns=[request.form.getlist(name) for name,_,_ in fields]
        if len({len(c) for c in columns})!=1:abort(400)
        rows=[]
        for values in zip(*columns):
            item={}
            for (name,_,opts),value in zip(fields,values):
                value=value.replace('\r\n','\n').strip()
                if not opts.get('multiline'):value=' '.join(value.split())
                if len(value)>site_content.MAX_LENGTH:abort(400)
                if opts.get('choices') and value and value not in dict(opts['choices']):abort(400)
                item[name]=value
            if any(item.values()):rows.append(item)
        first=fields[0][0];error=None
        if len(rows)>site_content.LIST_MAX_ITEMS:error='항목은 %d개까지 만들 수 있어요.'%site_content.LIST_MAX_ITEMS
        elif any(not r[first] for r in rows):error='"%s" 칸이 비어 있는 항목이 있어요.'%fields[0][1]
        elif len(rows)<minimum:error='%s은(는) 최소 %d개가 있어야 해요.'%(title,minimum)
        elif key.endswith('categories') and len({r[first] for r in rows})!=len(rows):error='같은 이름이 두 번 들어갔어요.'
        elif key=='menu' and any(not r['label'] or not r['page'] for r in rows):error='메뉴 이름과 연결할 페이지를 모두 정해 주세요.'
        elif key=='menu' and any(r['page']=='custom' and not SAFE_LINK.match(r['url']) for r in rows):error='직접 입력한 주소는 https:// 또는 / 로 시작해야 해요.'
        elif key=='home_blocks' and any(r['button_link'] and not SAFE_LINK.match(r['button_link']) for r in rows):error='버튼 주소는 https:// 또는 / 로 시작해야 해요.'
        elif key=='home_blocks' and any(r['count'] and not r['count'].isdigit() for r in rows):error='보여줄 개수에는 숫자만 넣어 주세요.'
        if error:
            # 입력한 내용을 잃지 않도록 저장하지 않은 상태 그대로 다시 보여 줌.
            flash(title+': '+error);data=load_lists();data[key]=rows
            return render_admin_lists(data,focus=key),400
        with conn() as db:db.execute('INSERT INTO site_lists(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated',(key,json.dumps(rows,ensure_ascii=False),now))
        flash(title+' 항목을 저장했습니다.')
        return redirect(url_for('admin_lists',_anchor='list-'+key))
    return render_admin_lists(load_lists())
def render_admin_lists(data,focus=None):
    with conn() as db:changed={r['key'] for r in db.execute('SELECT key FROM site_lists')}
    return render_template('admin_lists.html',lists=site_content.LISTS,data=data,changed=changed,max_items=site_content.LIST_MAX_ITEMS,focus=focus)

@app.route('/admin/takedowns',methods=['GET','POST'])
@admin_only
def admin_takedowns():
    with conn() as db:
        if request.method=='POST':
            status=request.form.get('status','')
            if status not in TAKEDOWN_STATUSES:abort(400)
            db.execute('UPDATE takedown_requests SET status=?,admin_note=? WHERE id=?',(status,request.form.get('admin_note','').strip()[:3000],request.form.get('id',type=int)))
            flash('처리 상태를 저장했습니다.');return redirect(url_for('admin_takedowns'))
        rows=db.execute('SELECT * FROM takedown_requests ORDER BY id DESC LIMIT 200').fetchall()
    return render_template('admin_takedowns.html',rows=rows,statuses=TAKEDOWN_STATUSES)
@app.route('/admin/file/<int:file_id>')
@admin_only
def admin_file(file_id):
    with conn() as db:f=db.execute('SELECT * FROM attachments WHERE id=?',(file_id,)).fetchone()
    if not f:abort(404)
    return send_file(UPLOAD/f['stored'],as_attachment=True,download_name=f['original'])
@app.route('/admin/logout',methods=['POST'])
@admin_only
def logout():session.clear();return redirect(url_for('home'))

@app.route('/admin/invite/<int:case_id>',methods=['POST'])
@admin_only
def create_invite(case_id):
    with conn() as db:
        case=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        if not case:abort(404)
        if not case['share_company']:
            flash('기업 전달 동의가 없는 제보입니다.');return redirect(url_for('admin_case',case_id=case_id))
        token=secrets.token_urlsafe(32)
        db.execute('INSERT OR REPLACE INTO company_invites(case_id,token_hash,company_name,created) VALUES(?,?,?,?)',(case_id,hashlib.sha256(token.encode()).hexdigest(),case['company'],datetime.datetime.now().isoformat(timespec='seconds')))
    return render_template('invite_created.html',case=case,invite_url=url_for('company_access',case_id=case_id,token=token,_external=True))

@app.route('/company/<int:case_id>/<token>',methods=['GET','POST'])
def company_access(case_id,token):
    if len(token)>150:abort(404)
    with conn() as db:
        invite=db.execute('SELECT * FROM company_invites WHERE case_id=?',(case_id,)).fetchone()
        case=db.execute('SELECT * FROM cases WHERE id=? AND share_company=1',(case_id,)).fetchone()
        if not invite or not case or not hmac.compare_digest(invite['token_hash'],hashlib.sha256(token.encode()).hexdigest()):abort(404)
        if request.method=='POST':
            body=request.form.get('response','').strip()
            if not body or len(body)>5000:abort(400)
            db.execute('INSERT INTO messages(case_id,author,body,created) VALUES(?,?,?,?)',(case_id,'기업 답변',body,datetime.datetime.now().isoformat(timespec='seconds')))
            return redirect(url_for('company_access',case_id=case_id,token=token))
        responses=db.execute("SELECT author,body,created FROM messages WHERE case_id=? AND author='기업 답변' ORDER BY id",(case_id,)).fetchall()
    # 업체에는 제보자의 연락처, 첨부파일, 내부 메모를 공개하지 않음.
    return render_template('company.html',case=case,responses=responses)

@app.route('/case/logout',methods=['POST'])
def case_logout():
    session.pop('case_id',None)
    return redirect(url_for('home'))

# ---- 소비자게시판 -----------------------------------------------------------
# 회원가입 없이 닉네임과 삭제용 비밀번호로 글·댓글을 남김. 공감·알리기는 브라우저 세션당 1회.
BOARD_PAGE_SIZE=20
FLAG_HIDE_THRESHOLD=5  # 서로 다른 이용자 알림이 이만큼 쌓이면 자동 숨김 후 운영자 확인
with conn() as db:
    db.execute('''CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY,category TEXT NOT NULL,nickname TEXT NOT NULL,pw_hash TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,ip_hash TEXT NOT NULL,created TEXT NOT NULL,hidden INTEGER NOT NULL DEFAULT 0,likes INTEGER NOT NULL DEFAULT 0,comments INTEGER NOT NULL DEFAULT 0,flags INTEGER NOT NULL DEFAULT 0)''')
    db.execute('''CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY,post_id INTEGER NOT NULL,nickname TEXT NOT NULL,pw_hash TEXT NOT NULL,body TEXT NOT NULL,ip_hash TEXT NOT NULL,created TEXT NOT NULL,hidden INTEGER NOT NULL DEFAULT 0,flags INTEGER NOT NULL DEFAULT 0,FOREIGN KEY(post_id) REFERENCES posts(id))''')
    db.execute('CREATE TABLE IF NOT EXISTS board_votes(kind TEXT NOT NULL,target TEXT NOT NULL,voter TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(kind,target,voter))')
    db.execute('CREATE INDEX IF NOT EXISTS comments_post ON comments(post_id)')

def board_enabled():return os.getenv('ENABLE_BOARD')=='1'
def voter_id():
    if 'voter' not in session:session['voter']=secrets.token_urlsafe(16)
    return hashlib.sha256(session['voter'].encode()).hexdigest()
def ip_hash():
    # 접속 IP는 원문 대신 서버 비밀키로 만든 해시만 저장 (도배 방지용).
    return hmac.new(app.secret_key.encode(),(request.remote_addr or '').encode(),'sha256').hexdigest()
def recent_count(db,table,minutes):
    since=(datetime.datetime.now()-datetime.timedelta(minutes=minutes)).isoformat(timespec='seconds')
    return db.execute(f'SELECT COUNT(*) FROM {table} WHERE ip_hash=? AND created>=?',(ip_hash(),since)).fetchone()[0]
def board_back(post_id=None):
    nxt=request.form.get('next','')
    if nxt.startswith('/board') and '//' not in nxt:return redirect(nxt)
    return redirect(url_for('board_post',post_id=post_id) if post_id else url_for('board'))
def refresh_comment_count(db,post_id):
    db.execute('UPDATE posts SET comments=(SELECT COUNT(*) FROM comments WHERE post_id=? AND hidden=0) WHERE id=?',(post_id,post_id))

@app.template_filter('ago')
def ago(created):
    try:delta=datetime.datetime.now()-datetime.datetime.fromisoformat(created)
    except (TypeError,ValueError):return ''
    s=delta.total_seconds()
    if s<60:return '방금 전'
    if s<3600:return f'{int(s//60)}분 전'
    if s<86400:return f'{int(s//3600)}시간 전'
    if s<86400*7:return f'{int(s//86400)}일 전'
    return created[:10].replace('-','.')

@app.route('/board')
def board():
    q=request.args.get('q','').strip()[:60];cat=request.args.get('category','')
    sort='top' if request.args.get('sort')=='top' else 'new'
    page=max(1,request.args.get('page',1,type=int))
    where=['hidden=0'];args=[]
    if cat in board_categories():where.append('category=?');args.append(cat)
    else:cat=''
    if q:where.append("(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')");like='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%';args+=[like,like]
    order='likes DESC,id DESC' if sort=='top' else 'id DESC'
    with conn() as db:
        total=db.execute('SELECT COUNT(*) FROM posts WHERE '+' AND '.join(where),args).fetchone()[0]
        posts=db.execute('SELECT id,category,nickname,title,substr(body,1,160) AS excerpt,likes,comments,created FROM posts WHERE '+' AND '.join(where)+f' ORDER BY {order} LIMIT ? OFFSET ?',args+[BOARD_PAGE_SIZE,(page-1)*BOARD_PAGE_SIZE]).fetchall()
        week_ago=(datetime.datetime.now()-datetime.timedelta(days=7)).isoformat(timespec='seconds')
        hot=db.execute('SELECT id,category,title,likes,comments FROM posts WHERE hidden=0 AND likes>0 AND created>=? ORDER BY likes DESC,id DESC LIMIT 3',(week_ago,)).fetchall() if not (q or cat or page>1) else []
        liked={r['target'] for r in db.execute("SELECT target FROM board_votes WHERE kind='like' AND voter=?",(voter_id(),))}
    return render_template('board.html',posts=posts,hot=hot,liked=liked,categories=board_categories(),cat=cat,q=q,sort=sort,page=page,pages=max(1,-(-total//BOARD_PAGE_SIZE)),total=total,enabled=board_enabled())

@app.route('/board/write',methods=['GET','POST'])
def board_write():
    if request.method=='POST':
        if not board_enabled():abort(503,description='게시판 글쓰기 준비 중입니다.')
        f={k:request.form.get(k,'').strip() for k in ('category','nickname','password','title','body')}
        errors=[]
        if request.form.get('website'):abort(400)  # 사람에게는 보이지 않는 칸. 채워져 있으면 자동 등록 프로그램.
        if f['category'] not in board_categories():errors.append('분류를 골라 주세요.')
        if not 2<=len(f['nickname'])<=20:errors.append('닉네임은 2~20자로 적어 주세요.')
        if not 4<=len(f['password'])<=30:errors.append('비밀번호는 4~30자로 정해 주세요.')
        if not 2<=len(f['title'])<=100:errors.append('제목은 2~100자로 적어 주세요.')
        if not 10<=len(f['body'])<=5000:errors.append('내용은 10~5,000자로 적어 주세요.')
        if not request.form.get('agree'):errors.append('글쓰기 약속에 동의해 주세요.')
        with conn() as db:
            if not errors and recent_count(db,'posts',10)>=3:errors.append('잠시 후 다시 올려 주세요. 10분에 3개까지 쓸 수 있어요.')
            if errors:
                for e in errors:flash(e)
                return render_template('board_write.html',categories=board_categories(),enabled=True),400
            cur=db.execute('INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created) VALUES(?,?,?,?,?,?,?)',(f['category'],f['nickname'],generate_password_hash(f['password']),f['title'],f['body'],ip_hash(),datetime.datetime.now().isoformat(timespec='seconds')))
        return redirect(url_for('board_post',post_id=cur.lastrowid))
    return render_template('board_write.html',categories=board_categories(),enabled=board_enabled())

@app.route('/board/<int:post_id>')
def board_post(post_id):
    with conn() as db:
        post=db.execute('SELECT * FROM posts WHERE id=?',(post_id,)).fetchone()
        if not post or (post['hidden'] and not session.get('admin')):abort(404)
        comments=db.execute('SELECT id,nickname,body,created FROM comments WHERE post_id=? AND hidden=0 ORDER BY id',(post_id,)).fetchall()
        mine={r['kind']+r['target'] for r in db.execute('SELECT kind,target FROM board_votes WHERE voter=?',(voter_id(),))}
    return render_template('board_post.html',post=post,comments=comments,categories=board_categories(),liked=('likep:%d'%post_id) in mine,flagged=('flagp:%d'%post_id) in mine,enabled=board_enabled())

@app.route('/board/<int:post_id>/like',methods=['POST'])
def board_like(post_id):
    if not board_enabled():abort(503)
    with conn() as db:
        if not db.execute('SELECT 1 FROM posts WHERE id=? AND hidden=0',(post_id,)).fetchone():abort(404)
        key=('like','p:%d'%post_id,voter_id())
        if db.execute('DELETE FROM board_votes WHERE kind=? AND target=? AND voter=?',key).rowcount==0:
            db.execute('INSERT INTO board_votes(kind,target,voter,created) VALUES(?,?,?,?)',key+(datetime.datetime.now().isoformat(timespec='seconds'),))
        db.execute("UPDATE posts SET likes=(SELECT COUNT(*) FROM board_votes WHERE kind='like' AND target=?) WHERE id=?",(key[1],post_id))
    return board_back(post_id)

@app.route('/board/<int:post_id>/comment',methods=['POST'])
def board_comment(post_id):
    if not board_enabled():abort(503)
    if request.form.get('website'):abort(400)
    nickname=request.form.get('nickname','').strip();password=request.form.get('password','');body=request.form.get('body','').strip()
    with conn() as db:
        if not db.execute('SELECT 1 FROM posts WHERE id=? AND hidden=0',(post_id,)).fetchone():abort(404)
        if not (2<=len(nickname)<=20 and 4<=len(password)<=30 and 1<=len(body)<=1000):
            flash('닉네임(2~20자), 비밀번호(4~30자), 댓글(1,000자 이내)을 확인해 주세요.');return redirect(url_for('board_post',post_id=post_id)+'#comment-form')
        if recent_count(db,'comments',2)>=5:
            flash('잠시 후 다시 남겨 주세요.');return redirect(url_for('board_post',post_id=post_id)+'#comment-form')
        db.execute('INSERT INTO comments(post_id,nickname,pw_hash,body,ip_hash,created) VALUES(?,?,?,?,?,?)',(post_id,nickname,generate_password_hash(password),body,ip_hash(),datetime.datetime.now().isoformat(timespec='seconds')))
        refresh_comment_count(db,post_id)
    return redirect(url_for('board_post',post_id=post_id)+'#comments')

@app.route('/board/flag/<kind>/<int:item_id>',methods=['POST'])
def board_flag(kind,item_id):
    if kind not in ('p','c'):abort(404)
    table='posts' if kind=='p' else 'comments'
    with conn() as db:
        item=db.execute(f'SELECT * FROM {table} WHERE id=? AND hidden=0',(item_id,)).fetchone()
        if not item:abort(404)
        target='%s:%d'%(kind,item_id)
        db.execute('INSERT OR IGNORE INTO board_votes(kind,target,voter,created) VALUES(?,?,?,?)',('flag',target,voter_id(),datetime.datetime.now().isoformat(timespec='seconds')))
        flags=db.execute("SELECT COUNT(*) FROM board_votes WHERE kind='flag' AND target=?",(target,)).fetchone()[0]
        db.execute(f'UPDATE {table} SET flags=?,hidden=? WHERE id=?',(flags,int(flags>=FLAG_HIDE_THRESHOLD),item_id))
        post_id=item_id if kind=='p' else item['post_id']
        if kind=='c':refresh_comment_count(db,post_id)
    flash('알려 주셔서 고마워요. 운영자가 확인할게요.')
    if kind=='p' and flags>=FLAG_HIDE_THRESHOLD:return redirect(url_for('board'))
    return redirect(url_for('board_post',post_id=post_id))

@app.route('/board/delete/<kind>/<int:item_id>',methods=['POST'])
def board_delete(kind,item_id):
    if kind not in ('p','c'):abort(404)
    with conn() as db:
        item=db.execute('SELECT * FROM %s WHERE id=?'%('posts' if kind=='p' else 'comments'),(item_id,)).fetchone()
        if not item:abort(404)
        post_id=item_id if kind=='p' else item['post_id']
        if not check_password_hash(item['pw_hash'],request.form.get('password','')):
            flash('비밀번호가 맞지 않아요.');return redirect(url_for('board_post',post_id=post_id))
        delete_board_item(db,kind,item_id)
    flash('삭제했어요.')
    return redirect(url_for('board') if kind=='p' else url_for('board_post',post_id=post_id)+'#comments')

def delete_board_item(db,kind,item_id):
    # 작성자·운영자 삭제 모두 원문을 바로 지움 (개인정보 처리방침: 삭제 시 즉시 파기).
    if kind=='p':
        ids=[r['id'] for r in db.execute('SELECT id FROM comments WHERE post_id=?',(item_id,))]
        db.execute('DELETE FROM board_votes WHERE target=?'+' OR target=?'*len(ids),['p:%d'%item_id]+['c:%d'%i for i in ids])
        db.execute('DELETE FROM comments WHERE post_id=?',(item_id,))
        db.execute('DELETE FROM posts WHERE id=?',(item_id,))
    else:
        post_id=db.execute('SELECT post_id FROM comments WHERE id=?',(item_id,)).fetchone()['post_id']
        db.execute('DELETE FROM board_votes WHERE target=?',('c:%d'%item_id,))
        db.execute('DELETE FROM comments WHERE id=?',(item_id,))
        refresh_comment_count(db,post_id)

@app.route('/admin/board',methods=['GET','POST'])
@admin_only
def admin_board():
    with conn() as db:
        if request.method=='POST':
            kind=request.form.get('kind');item_id=request.form.get('id',type=int);action=request.form.get('action')
            if kind not in ('p','c') or not item_id or action not in ('hide','show','delete'):abort(400)
            table='posts' if kind=='p' else 'comments'
            if not db.execute(f'SELECT 1 FROM {table} WHERE id=?',(item_id,)).fetchone():abort(404)
            if action=='delete':delete_board_item(db,kind,item_id)
            else:
                db.execute(f'UPDATE {table} SET hidden=? WHERE id=?',(int(action=='hide'),item_id))
                if kind=='c':refresh_comment_count(db,db.execute('SELECT post_id FROM comments WHERE id=?',(item_id,)).fetchone()['post_id'])
            flash({'hide':'숨겼어요.','show':'다시 보이게 했어요.','delete':'삭제했어요.'}[action])
            return redirect(url_for('admin_board',view=request.args.get('view','')))
        flagged=request.args.get('view')!='all'
        cond='WHERE flags>0 OR hidden=1' if flagged else ''
        posts=db.execute(f'SELECT id,category,nickname,title,body,created,hidden,likes,comments,flags FROM posts {cond} ORDER BY flags DESC,id DESC LIMIT 200').fetchall()
        comments=db.execute(f'SELECT c.id,c.post_id,c.nickname,c.body,c.created,c.hidden,c.flags,p.title FROM comments c JOIN posts p ON p.id=c.post_id {cond.replace("flags","c.flags").replace("hidden","c.hidden")} ORDER BY c.flags DESC,c.id DESC LIMIT 200').fetchall()
    return render_template('admin_board.html',posts=posts,comments=comments,flagged=flagged,threshold=FLAG_HIDE_THRESHOLD)

if __name__=='__main__':app.run(debug=False)
