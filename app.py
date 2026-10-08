import os, sqlite3, secrets, hashlib, hmac, datetime, functools
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, send_file
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

BASE=Path(__file__).parent
DB=Path(os.getenv('DATABASE_PATH',str(BASE/'cases.sqlite3')))
UPLOAD=Path(os.getenv('UPLOAD_DIR',str(BASE/'private_uploads')))
UPLOAD.mkdir(parents=True,exist_ok=True)
app=Flask(__name__)
app.secret_key=os.getenv('SECRET_KEY',secrets.token_hex(32))
if os.getenv('ENABLE_INTAKE')=='1' and (not os.getenv('SECRET_KEY') or not os.getenv('ADMIN_PASSWORD_HASH')):
    raise RuntimeError('신고 접수를 활성화하려면 SECRET_KEY와 ADMIN_PASSWORD_HASH가 필요합니다.')
app.config['MAX_CONTENT_LENGTH']=15*1024*1024
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('HTTPS_ONLY')=='1')
CATEGORIES=['상품·품질','배송·환불','구독·결제','금융·통신','여행·숙박','서비스·계약','개인정보','기타']
STATUSES=['접수','검토 중','추가 확인','기업 답변 대기','조정 진행','종결']

def conn():
    db=sqlite3.connect(DB); db.row_factory=sqlite3.Row
    return db

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
    if request.path.startswith(('/report','/lookup','/admin','/case')):resp.headers['Cache-Control']='no-store'
    return resp
@app.route('/')
def home():
    with conn() as db:
        rows=db.execute('SELECT category,subject,status,created FROM cases WHERE public_consent=1 AND published=1 ORDER BY id DESC LIMIT 60').fetchall()
    public_cases=[dict(cat=r['category'],title=r['subject'],status=r['status'],created=r['created'][:10]) for r in rows]
    search_query=request.args.get('q','').strip()[:160]
    selected_category=request.args.get('category','')
    public_cases=[case for case in public_cases if (not search_query or search_query.casefold() in case['title'].casefold()) and (not selected_category or case['cat']==selected_category)]
    return render_template('index.html',categories=CATEGORIES,public_cases=public_cases,search_query=search_query,selected_category=selected_category)

@app.route('/guide',defaults={'page':'guide'})
@app.route('/process',defaults={'page':'process'})
@app.route('/types',defaults={'page':'types'})
@app.route('/faq',defaults={'page':'faq'})
def info_page(page):
    return render_template('info.html',page=page,categories=CATEGORIES)

@app.route('/report',methods=['GET','POST'])
def report():
    if request.method=='GET':return render_template('report.html',categories=CATEGORIES, intake_enabled=os.getenv('ENABLE_INTAKE')=='1')
    if os.getenv('ENABLE_INTAKE')!='1': abort(503, description='신고 접수 준비 중입니다.')
    data={k:request.form.get(k,'').strip() for k in ('category','company','subject','description','request_text','contact')}
    if data['category'] not in CATEGORIES or any(not data[k] for k in ('company','subject','description','request_text')) or not request.form.get('consent'):
        flash('필수 항목과 개인정보 안내 동의를 확인해 주세요.');return render_template('report.html',categories=CATEGORIES,intake_enabled=os.getenv('ENABLE_INTAKE')=='1'),400
    if any(len(data[k])>limit for k,limit in [('company',120),('subject',160),('description',6000),('request_text',3000),('contact',150)]):abort(400)
    file=request.files.get('evidence')
    if file and file.filename:
        suffix=Path(secure_filename(file.filename)).suffix.lower()
        if suffix not in ('.pdf','.png','.jpg','.jpeg','.webp'):flash('첨부는 PDF 또는 이미지 파일만 가능합니다.');return render_template('report.html',categories=CATEGORIES,intake_enabled=os.getenv('ENABLE_INTAKE')=='1'),400
        head=file.stream.read(12);file.stream.seek(0)
        valid=(suffix=='.pdf' and head.startswith(b'%PDF-')) or (suffix=='.png' and head.startswith(b'\x89PNG')) or (suffix in ('.jpg','.jpeg') and head.startswith(b'\xff\xd8')) or (suffix=='.webp' and head[8:12]==b'WEBP')
        if not valid:flash('첨부파일 형식을 확인해 주세요.');return render_template('report.html',categories=CATEGORIES,intake_enabled=os.getenv('ENABLE_INTAKE')=='1'),400
    receipt='CJ-'+datetime.datetime.now().strftime('%y%m%d')+'-'+secrets.token_hex(3).upper()
    code=secrets.token_urlsafe(12)
    with conn() as db:
        cur=db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,contact,share_company,created) VALUES(?,?,?,?,?,?,?,?,?,?)',(receipt,hashlib.sha256(code.encode()).hexdigest(),data['category'],data['company'],data['subject'],data['description'],data['request_text'],data['contact'],int(bool(request.form.get('share_company'))),datetime.datetime.now().isoformat(timespec='seconds')))
        db.execute('UPDATE cases SET public_consent=? WHERE id=?',(int(bool(request.form.get('public_consent'))),cur.lastrowid))
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
            db.execute('INSERT INTO messages(case_id,author,body,created) VALUES(?,?,?,?)',(case_id,'신고인',msg,datetime.datetime.now().isoformat(timespec='seconds')))
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
            flash('기업 전달 동의가 없는 신고입니다.');return redirect(url_for('admin_case',case_id=case_id))
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
    # 업체에는 신고인의 연락처, 첨부파일, 내부 메모를 공개하지 않음.
    return render_template('company.html',case=case,responses=responses)

@app.route('/case/logout',methods=['POST'])
def case_logout():
    session.pop('case_id',None)
    return redirect(url_for('home'))

if __name__=='__main__':app.run(debug=False)
