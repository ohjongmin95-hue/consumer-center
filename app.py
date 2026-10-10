import os, re, json, time, sqlite3, secrets, hashlib, hmac, datetime, functools, contextlib
from pathlib import Path
from flask import Flask, g, has_request_context, render_template, request, redirect, url_for, session, flash, abort, send_file
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
app.config['MAX_CONTENT_LENGTH']=22*1024*1024  # 첨부 합계 20MB + 글 내용
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
    if 'user_id' not in cols: db.execute('ALTER TABLE cases ADD COLUMN user_id INTEGER')
    for col in ('reporter_name','phone','region_sido','region_sigungu','region_detail','gender','age_group','ip_hash','industry'):
        if col not in cols: db.execute(f"ALTER TABLE cases ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
    db.execute('CREATE TABLE IF NOT EXISTS site_content(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS site_lists(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated TEXT NOT NULL)')
    # 이용 안내 개편: 예전 기본 구성 그대로 저장돼 있으면 지워서 새 기본 구성(단계 카드·만화 3컷·업종 탭)을 쓰게 함
    row=db.execute("SELECT value FROM site_lists WHERE key='layout_guide'").fetchone()
    if row and [b.get('kind') for b in json.loads(row[0])]==['guide_basics','guide_writing','guide_evidence','guide_topics','guide_bottom'] and not any(b.get(k) for b in json.loads(row[0]) for k in ('title','body','button_label','button_link')):
        db.execute("DELETE FROM site_lists WHERE key='layout_guide'")
    db.execute("CREATE TABLE IF NOT EXISTS takedown_requests(id INTEGER PRIMARY KEY,requester TEXT NOT NULL,contact TEXT NOT NULL,target TEXT NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT '접수',admin_note TEXT NOT NULL DEFAULT '',created TEXT NOT NULL)")
TAKEDOWN_STATUSES=['접수','검토 중','임시 비공개','비공개 처리','기각','처리 완료']

def load_content():
    # 빈 값으로 저장된 문구는 '지운 문장' (편집 모드의 지우기). 관리자 문구 화면에서 비우면 행이 지워져 기본값으로 돌아감.
    with conn() as db:saved={r['key']:r['value'] for r in db.execute('SELECT key,value FROM site_content')}
    if has_request_context():g.deleted={k for k,v in saved.items() if v==''}
    return {k:saved[k] if k in saved else f['default'] for k,f in site_content.FIELDS.items()}
def legacy_list(db,key):
    # 예전에 고정 칸(faq.q1~8, process.step1~4, nav.*)으로 수정해 둔 값이 있으면 그 내용을 첫 목록으로 씀.
    if key=='menu':
        saved={r['key']:r['value'] for r in db.execute("SELECT key,value FROM site_content WHERE key LIKE 'nav.%'")}
        return [{'label':saved.get(k) or label,'page':page,'url':''} for k,page,label in site_content.LEGACY_NAV] if saved else None
    prefix={'faq':'faq.','process_steps':'process.step'}.get(key)
    if not prefix:return None
    # 예전 고정 칸 이름(faq.q1, process.step1_title 등)만 봄. faq.title 같은 다른 문구는 제외.
    pattern=re.compile(r'^faq\.[qa]\d+$' if key=='faq' else r'^process\.step\d+_(title|body)$')
    saved={r['key']:r['value'] for r in db.execute('SELECT key,value FROM site_content WHERE key LIKE ?',(prefix+'%',)) if pattern.match(r['key'])}
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
# 편집 모드에서 화면에 보이는 목록 칸 (클릭해서 바로 고칠 수 있는 칸)
LIST_DISPLAY_FIELDS={'menu':('label',),'home_blocks':('title','body','button_label'),'faq':('q','a'),'process_steps':('title','body'),
    'guide_basics':('title','body'),'guide_writing':('title','body'),'guide_topics':('name','heading','info','materials'),'guide_steps':('title',),'guide_industries':('name','examples','tip'),'sample_reports':('title','company'),
    'custom_pages':('title',),'report_consents':('title','body','agree'),**{'layout_'+p:('title','body','button_label') for p in site_content.PAGE_SECTIONS}}
def items(key):
    rows=g.lists.get(key,[])
    if not editing() or key not in LIST_DISPLAY_FIELDS:return rows
    return [{k:(ed_wrap('list:%s:%d:%s'%(key,i,k),v) if k in LIST_DISPLAY_FIELDS[key] and v else v) for k,v in row.items()} for i,row in enumerate(rows)]
def report_categories():return [i['name'] for i in items('report_categories')]
def report_industries():return [i['name'] for i in items('report_industries')]
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
GUIDE_ICONS={  # 이용 안내 단계 카드 아이콘 (주황 선이 포인트)
    'write':'<rect x="12" y="6" width="22" height="36" rx="4"/><path d="M17 15h12M17 21h12M17 27h7"/><path class="o" d="M30 34l9-9 3 3-9 9h-3z"/>',
    'attach':'<rect x="6" y="12" width="28" height="24" rx="3"/><circle cx="14" cy="20" r="3"/><path d="M6 32l9-8 6 5 5-4 8 7"/><path class="o" d="M38 14v14a5 5 0 0 1-10 0V12a3 3 0 0 1 6 0v14"/>',
    'ticket':'<path d="M6 14h36v6a4 4 0 0 0 0 8v6H6v-6a4 4 0 0 0 0-8z"/><path d="M18 14v20" stroke-dasharray="2 4"/><path class="o" d="M24 21h12M24 27h8"/>',
    'search':'<circle cx="21" cy="21" r="12"/><path d="M30 30l10 10"/><path class="o" d="M15 21l4 4 8-8"/>',
    'chat':'<path d="M7 9h34v22H20l-9 8v-8H7z"/><path class="o" d="M15 18h18M15 24h11"/>',
    'check':'<circle cx="24" cy="24" r="17"/><path class="o" d="M16 24l6 6 11-12"/>',
}
app.jinja_env.globals['industry_art']={k for k,_ in site_content.INDUSTRY_ART if k}  # static/img/guide-ind-<이름>.svg 가 있는 그림
app.jinja_env.globals['guide_icon']=lambda name:Markup('<svg viewBox="0 0 48 48" width="44" height="44" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">%s</svg>'%GUIDE_ICONS.get(name,GUIDE_ICONS['write']))
STEP_ICON_ORDER=['write','search','chat','scale','check','bell','shield','call']
app.jinja_env.globals['step_icon']=lambda item,i:item.get('icon') or STEP_ICON_ORDER[i%len(STEP_ICON_ORDER)]
# ---- 사이트에서 바로 고치기 (관리자 편집 모드) ----------------------------------
# 편집 모드에서는 문장마다 보이지 않는 표시를 붙여 두었다가, 응답을 내보내기 직전에
# 본문 글자는 <span data-k="키">로 바꾸고 태그 속성·제목 안의 표시는 지움 (edit_mode_markup).
ED_OPEN,ED_SEP,ED_CLOSE='\ue000','\ue001','\ue002'
def editing():
    if 'editing' not in g:
        g.editing=bool(session.get('edit_mode') and request.endpoint not in (None,'static')
                       and not request.path.startswith(('/admin','/reporter','/staff')) and admin_active())
    return g.editing
def ed_register(key,raw):
    marks=g.setdefault('ed_marks',{})
    marks.setdefault(key,raw)
    return list(marks).index(key)
def ed_wrap(key,value,raw=None):
    # value: 화면에 찍힐 값(문자열 또는 Markup), raw: 고칠 때 보여 줄 원문
    if not editing():return value
    if not str(value):
        # 지운 문장은 편집 모드에서만 흐리게 보여 줘서 다시 살릴 수 있게 함
        if key not in g.get('deleted',()):return value
        value=Markup('<span class="ed-ghost">(지운 문장 · 눌러서 되살리기)</span>');raw=''
    idx=ed_register(key,value if raw is None else raw)
    wrapped=ED_OPEN+str(idx)+ED_SEP
    return Markup(wrapped)+value+Markup(ED_CLOSE) if isinstance(value,Markup) else wrapped+value+ED_CLOSE
def ed_attr(key,raw=None):
    # 여러 줄로 나눠 그리는 문장(목록 등)은 감싸는 태그에 data-k를 붙여 통째로 고침
    if not editing():return ''
    ed_register(key,g.content.get(key,'') if raw is None else raw)
    return Markup(' data-k="%s"'%escape(key))
app.jinja_env.globals['ed_attr']=ed_attr
app.jinja_env.globals['editing']=editing
def ed_list(key):
    # 목록 아래에 "항목 추가·순서 바꾸기" 바로가기 (편집 모드에서만)
    if not editing():return ''
    label={'home_blocks':'＋ 메인 화면 섹션 추가·삭제·순서 바꾸기','custom_pages':'＋ 새 페이지 만들기·관리'}.get(key) or ('＋ 이 페이지 섹션 추가·삭제·순서 바꾸기' if key.startswith('layout_') else '＋ 항목 추가·삭제·순서 바꾸기')
    return Markup('<a class="ed-list" href="%s">%s</a>')%(url_for('admin_lists',_anchor='list-'+key),label)
app.jinja_env.globals['ed_list']=ed_list
def ed_remove(key,index):
    # 편집 모드에서 섹션·항목 옆에 붙는 "✕ 빼기" 버튼
    if not editing():return ''
    return Markup('<button type="button" class="ed-remove" data-list="%s" data-i="%d">✕ 빼기</button>')%(key,index)
app.jinja_env.globals['ed_remove']=ed_remove
def txt(key):
    # 관리자가 입력한 문구는 HTML로 해석하지 않고 줄바꿈만 반영함.
    raw=g.content.get(key,'')
    return ed_wrap(key,Markup('<br>').join(escape(line) for line in raw.split('\n')),raw)
app.jinja_env.globals['txt']=txt
def ui_text(key,default):
    # 화면 문구: 관리자가 바꾼 값이 있으면 그 값, 없으면 템플릿에 적힌 기본 문구 (site_content.UI_TEXTS 참고)
    content=g.get('content') or {}
    return content[key] if key in content else default
def ui(key,default):
    raw=ui_text(key,default)
    return ed_wrap(key,Markup('<br>').join(escape(line) for line in raw.split('\n')),raw)
app.jinja_env.globals['ui']=ui
app.jinja_env.globals['ui_text']=ui_text
def ui_rich(key,default):
    # **굵게** 표시를 쓸 수 있는 화면 문구
    text=ui_text(key,default).replace('\0','').replace('\1','')
    out=EMPHASIS.sub(lambda m:'\0'+m.group(1)+'\1',text)
    return ed_wrap(key,Markup(str(escape(out)).replace('\0','<strong>').replace('\1','</strong>').replace('\n','<br>')),ui_text(key,default))
app.jinja_env.globals['ui_rich']=ui_rich
def status_name(status):
    # 진행 단계 이름 (저장값은 그대로 두고 화면에 보이는 이름만 바꿈)
    names={STATUSES[0]:lambda:ui('status.n1','접수'),STATUSES[1]:lambda:ui('status.n2','검토 중'),STATUSES[2]:lambda:ui('status.n3','추가 확인'),
           STATUSES[3]:lambda:ui('status.n4','기업 답변 대기'),STATUSES[4]:lambda:ui('status.n5','조정 진행'),STATUSES[5]:lambda:ui('status.n6','종결')}
    return names[status]() if status in names else status
app.jinja_env.globals['status_name']=status_name
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
FOOTER_ROWS=[['operator.name','operator.ceo','operator.address'],
             ['operator.phone','operator.fax','operator.email','operator.biz_no'],
             ['operator.privacy_officer','operator.youth_officer']]
def footer_label(key):
    # 푸터 항목 이름도 관리자 '사이트 문구'에서 바꿀 수 있음
    return {'operator.name':ui_text('common.ft_name','상호'),'operator.ceo':ui_text('common.ft_ceo','대표'),'operator.address':ui_text('common.ft_address','소재지'),
            'operator.phone':ui_text('common.ft_phone','전화'),'operator.fax':ui_text('common.ft_fax','팩스'),'operator.email':ui_text('common.ft_email','이메일'),
            'operator.biz_no':ui_text('common.ft_biz_no','사업자등록번호'),'operator.privacy_officer':ui_text('common.ft_privacy_officer','개인정보 보호책임자'),
            'operator.youth_officer':ui_text('common.ft_youth_officer','청소년보호책임자')}[key]
def footer_rows():
    # 푸터 사업자 정보: 입력된 항목만, 줄 단위로 묶어서 보여 줌 (키, 항목 이름, 값)
    rows=[[(key,footer_label(key),g.content.get(key)) for key in row if g.content.get(key)] for row in FOOTER_ROWS]
    return [row for row in rows if row]
app.jinja_env.globals['footer_rows']=footer_rows
app.jinja_env.globals['css_v']='jebo-45'  # style.css 캐시 갱신용. 디자인을 고치면 숫자를 올림
def asset(filename):
    # 정적 파일이 바뀌면 주소도 바뀌게(수정 시각을 v로) 해서 브라우저가 예전 그림을 캐시에서 보여 주지 않게 함
    try:version=int((BASE/'static'/filename).stat().st_mtime)
    except OSError:version=0
    return url_for('static',filename=filename,v=version)
app.jinja_env.globals['asset']=asset
def doc(key):return doc_text(g.content.get(key,''))
def doc_text(text):
    # 약관류 본문: "## "는 소제목, "- "는 목록, 빈 줄은 문단 구분. {운영자} 등은 운영자 정보로 치환.
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
app.jinja_env.globals['doc_text']=doc_text

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
    if request.path.startswith(('/report','/lookup','/admin','/case','/takedown','/company','/login','/signup','/me','/staff','/reporter')):resp.headers['Cache-Control']='no-store'
    elif session.get('uid') and 'Cache-Control' not in resp.headers:resp.headers['Cache-Control']='private, no-cache'
    return resp
_ED_TAG=re.compile(r'<[^>]*>')
_ED_RAW=re.compile(r'(<(title|textarea|option|script|style)\b[^>]*>)(.*?)(</\2>)',re.S|re.I)
_ED_MARK=re.compile('\ue000(\\d+)\ue001')
def _ed_strip(text):return _ED_MARK.sub('',text).replace(ED_CLOSE,'')
@app.after_request
def edit_mode_markup(resp):
    if not g.get('editing') or resp.mimetype!='text/html' or resp.direct_passthrough:return resp
    html=resp.get_data(as_text=True)
    html=_ED_RAW.sub(lambda m:m.group(1)+_ed_strip(m.group(3))+m.group(4),html)
    html=_ED_TAG.sub(lambda m:_ed_strip(m.group(0)),html)
    keys=list(g.get('ed_marks',{}))
    html=_ED_MARK.sub(lambda m:'<span class="ed" data-k="%s">'%escape(keys[int(m.group(1))]),html).replace(ED_CLOSE,'</span>')
    data={k:{'v':str(v),'label':ed_label(k),'ml':ed_multiline(k),'del':ed_delete_mode(k)} for k,v in g.get('ed_marks',{}).items()}
    html=html.replace('</body>','<script id="ed-data" type="application/json">%s</script></body>'%json.dumps(data,ensure_ascii=False).replace('<','\\u003c'),1)
    resp.set_data(html);resp.headers['Cache-Control']='no-store'
    return resp
def _list_meta(key):
    for k,title,_,fields,minimum in site_content.LISTS:
        if k==key:return title,fields,minimum
    return None
def ed_label(key):
    if key.startswith('list:'):
        _,lk,i,field=key.split(':');meta=_list_meta(lk)
        return '%s · %s번째 · %s'%(meta[0],int(i)+1,dict((n,l) for n,l,_ in meta[1]).get(field,field)) if meta else key
    f=site_content.FIELDS.get(key);return f['label'] if f else key
def ed_delete_mode(key):
    # 지우기 버튼이 할 일: 'item' 항목째 빼기, 'text' 문장 지우기, '' 지울 수 없음
    if key.startswith('list:'):
        _,lk,_,field=key.split(':');meta=_list_meta(lk)
        return 'item' if meta and field==meta[1][0][0] else 'text'
    return '' if key in UNDELETABLE else 'text'
def ed_multiline(key):
    if key.startswith('list:'):
        _,lk,_,field=key.split(':');meta=_list_meta(lk)
        return bool(meta and dict((n,o) for n,_,o in meta[1]).get(field,{}).get('multiline'))
    f=site_content.FIELDS.get(key,{});return bool(f.get('multiline') or f.get('doc'))

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

CUSTOM_SLUG=re.compile(r'^[a-z0-9][a-z0-9-]{0,39}$')
def page_layout(page):
    # 페이지 섹션 구성 (관리자 '메뉴·항목' > ○○ 페이지 구성). 순서·삭제·글 상자 추가.
    return items('layout_'+page)
app.jinja_env.globals['page_layout']=page_layout
@app.route('/p/<slug>')
def custom_page(slug):
    for i,row in enumerate(g.lists.get('custom_pages',[])):
        if row.get('slug')==slug:
            return render_template('custom_page.html',page=items('custom_pages')[i],index=i,raw=row)
    abort(404)

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
    lines=['User-agent: *','Allow: /','Disallow: /admin','Disallow: /staff','Disallow: /reporter','Disallow: /case','Disallow: /company/','Disallow: /board/write','Disallow: /me','Disallow: /reports/latest','','Sitemap: '+url_for('sitemap_xml',_external=True)]
    daum=g.content.get('seo.daum_robots','').strip()
    if daum:lines.insert(0,daum if daum.startswith('#') else '#'+daum)
    return app.response_class('\n'.join(lines)+'\n',mimetype='text/plain')

@app.route('/sitemap.xml')
def sitemap_xml():
    pages=[(url_for(e,_external=True),None) for e in ('home','reports','board','report','takedown')]
    pages+=[(url_for('info_page',page=p,_external=True),None) for p in ('guide','process','faq','types')]
    pages+=[(url_for('policy_page',page=p,_external=True),None) for p in ('terms','privacy','youth')]
    pages+=[(url_for('custom_page',slug=r['slug'],_external=True),None) for r in g.lists.get('custom_pages',[]) if r.get('slug')]
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
            flash(ui_text('msg.m01','모든 항목과 개인정보 수집 동의를 확인해 주세요.'));return render_template('takedown.html'),400
        if any(len(data[k])>limit for k,limit in [('requester',120),('contact',150),('target',300),('reason',5000)]):abort(400)
        with conn() as db:db.execute('INSERT INTO takedown_requests(requester,contact,target,reason,created) VALUES(?,?,?,?,?)',(data['requester'],data['contact'],data['target'],data['reason'],datetime.datetime.now().isoformat(timespec='seconds')))
        return render_template('takedown.html',submitted=True)
    return render_template('takedown.html')

CONSENT_FIELDS={'privacy':'consent','share':'share_company','copyright':'use_consent','truth':'truth'}
def required_consents():
    # 제보하기 화면에 남아 있는 동의 항목만 필수 (관리자 '제보하기 동의 항목')
    return [CONSENT_FIELDS.get(r.get('kind'),'consent_custom_%d'%i) for i,r in enumerate(g.lists.get('report_consents',[]))]
SIDO=['서울','부산','대구','인천','광주','대전','울산','세종','경기','강원','충북','충남','전북','전남','경북','경남','제주']
GENDERS=['남성','여성']
AGE_GROUPS=['10대','20대','30대','40대','50대','60대','70대 이상']
UPLOAD_TYPES={'.pdf':'pdf','.png':'png','.jpg':'jpg','.jpeg':'jpg','.webp':'webp','.mp4':'mp4','.mov':'mov'}
MAX_FILES=5;MAX_UPLOAD_TOTAL=20*1024*1024
PHONE_INPUT=re.compile(r'^[0-9+()\- ]{8,20}$')
def file_ok(suffix,head):
    kind=UPLOAD_TYPES.get(suffix)
    return ((kind=='pdf' and head.startswith(b'%PDF-')) or (kind=='png' and head.startswith(b'\x89PNG')) or (kind=='jpg' and head.startswith(b'\xff\xd8'))
            or (kind=='webp' and head[8:12]==b'WEBP') or (kind in ('mp4','mov') and head[4:8]==b'ftyp'))
def report_form(status=200):
    return render_template('report.html',categories=report_categories(),industries=g.lists.get('report_industries',[]),intake_enabled=os.getenv('ENABLE_INTAKE')=='1',sido=SIDO,genders=GENDERS,ages=AGE_GROUPS,max_files=MAX_FILES),status
@app.route('/report',methods=['GET','POST'])
def report():
    if request.method=='GET':return report_form()
    if os.getenv('ENABLE_INTAKE')!='1': abort(503, description='제보 접수 준비 중입니다.')
    if request.form.get('website'):abort(400)  # 사람에게는 안 보이는 칸: 자동 등록 프로그램 차단
    keys=('industry','category','company','subject','description','request_text','contact','reporter_name','phone','region_sido','region_sigungu','region_detail','gender','age_group')
    data={k:request.form.get(k,'').strip() for k in keys}
    if data['category'] not in report_categories() or data['industry'] not in report_industries() or any(not data[k] for k in ('company','subject','description','request_text','reporter_name','phone')) or not all(request.form.get(k) for k in required_consents()) or request.form.get('visibility') not in ('public','secret'):
        flash(ui_text('msg.report_required','필수 항목과 필수 동의를 모두 확인해 주세요.'));return report_form(400)
    if any(len(data[k])>limit for k,limit in [('company',120),('subject',160),('description',6000),('request_text',3000),('contact',150),('reporter_name',40),('phone',20),('region_sigungu',40),('region_detail',120)]):abort(400)
    if not PHONE_INPUT.match(data['phone']):flash(ui_text('msg.report_phone','전화번호를 확인해 주세요.'));return report_form(400)
    if data['contact'] and not MEMBER_EMAIL_RE.match(data['contact']):flash(ui_text('msg.report_email','이메일 주소를 확인해 주세요.'));return report_form(400)
    if data['region_sido'] not in SIDO:data['region_sido']=''
    if data['gender'] not in GENDERS:data['gender']=''
    if data['age_group'] not in AGE_GROUPS:data['age_group']=''
    files=[f for f in request.files.getlist('evidence') if f and f.filename]
    if len(files)>MAX_FILES:flash(ui_text('msg.report_files','첨부파일은 5개까지 올릴 수 있어요.'));return report_form(400)
    total=0;checked=[]
    for f in files:
        suffix=Path(f.filename).suffix.lower()
        head=f.stream.read(12);f.stream.seek(0,2);size=f.stream.tell();f.stream.seek(0);total+=size
        if suffix not in UPLOAD_TYPES:flash(ui_text('msg.m02','첨부는 사진, PDF, 동영상(mp4·mov) 파일만 가능합니다.'));return report_form(400)
        if not file_ok(suffix,head):flash(ui_text('msg.m03','첨부파일 형식을 확인해 주세요.'));return report_form(400)
        # 원래 파일 이름은 한글을 살리되 경로·제어 문자는 지움
        original=re.sub(r'[\x00-\x1f/\\]','',Path(f.filename.replace('\\','/')).name)[:180] or 'file'+suffix
        checked.append((f,suffix,original))
    if total>MAX_UPLOAD_TOTAL:flash(ui_text('msg.report_size','첨부파일은 모두 합쳐 20MB까지 올릴 수 있어요.'));return report_form(400)
    receipt='CJ-'+datetime.datetime.now().strftime('%y%m%d')+'-'+secrets.token_hex(3).upper()
    code=secrets.token_urlsafe(12)
    with conn() as db:
        hour_ago=(datetime.datetime.now()-datetime.timedelta(hours=1)).isoformat(timespec='seconds')
        if db.execute('SELECT COUNT(*) FROM cases WHERE ip_hash=? AND created>=?',(ip_hash(),hour_ago)).fetchone()[0]>=5:
            flash(ui_text('msg.report_rate','잠시 후 다시 제보해 주세요. 한 시간에 5건까지 접수할 수 있어요.'));return report_form(429)
        cur=db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,contact,share_company,created) VALUES(?,?,?,?,?,?,?,?,?,?)',(receipt,hashlib.sha256(code.encode()).hexdigest(),data['category'],data['company'],data['subject'],data['description'],data['request_text'],data['contact'],int(bool(request.form.get('share_company'))),datetime.datetime.now().isoformat(timespec='seconds')))
        public=int(request.form.get('visibility')=='public')
        db.execute('UPDATE cases SET public_consent=?,published=?,use_consent=?,user_id=?,reporter_name=?,phone=?,region_sido=?,region_sigungu=?,region_detail=?,gender=?,age_group=?,ip_hash=?,industry=? WHERE id=?',
                   (public,public,int(bool(request.form.get('use_consent'))),g.user['id'] if g.user else None,data['reporter_name'],data['phone'],data['region_sido'],data['region_sigungu'],data['region_detail'],data['gender'],data['age_group'],ip_hash(),data['industry'],cur.lastrowid))
        for f,suffix,original in checked:
            stored=secrets.token_hex(20)+suffix;f.save(UPLOAD/stored)
            db.execute('INSERT INTO attachments(case_id,stored,original) VALUES(?,?,?)',(cur.lastrowid,stored,original))
    return render_template('success.html',receipt=receipt,code=code)
@app.route('/lookup',methods=['GET','POST'])
def lookup():
    if request.method=='GET':return render_template('lookup.html')
    receipt=request.form.get('receipt','').strip().upper();code=request.form.get('code','').strip()
    with conn() as db:case=db.execute('SELECT * FROM cases WHERE receipt=?',(receipt,)).fetchone()
    if not case or not hmac.compare_digest(case['lookup_hash'],hashlib.sha256(code.encode()).hexdigest()):
        flash(ui_text('msg.m04','접수번호 또는 조회 코드가 일치하지 않습니다.'));return render_template('lookup.html'),401
    session.pop('case_id',None);session['case_id']=case['id'];return redirect(url_for('case_detail'))
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
# 관리자 비밀번호: 관리자 화면에서 바꾸면 DB에 저장되고, 없으면 처음 설치 때 정한 /etc/soboru.env 값을 씀.
with conn() as db:db.execute('CREATE TABLE IF NOT EXISTS admin_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated TEXT NOT NULL)')
def admin_setting(key):
    with conn() as db:row=db.execute('SELECT value FROM admin_settings WHERE key=?',(key,)).fetchone()
    return row['value'] if row else ''
def admin_password_hash():return admin_setting('password_hash') or os.getenv('ADMIN_PASSWORD_HASH','')
def admin_session_ver():return admin_setting('session_ver') or '1'

@app.route('/admin/login',methods=['GET','POST'])
def admin_login():
    if request.method=='GET' and admin_active():return redirect(url_for('admin'))  # 이미 로그인돼 있으면 바로 관리자 홈으로
    if request.method=='POST':
        stored=admin_password_hash()
        if too_many_attempts('admin'):
            flash('로그인 시도가 너무 많습니다. 10분 뒤 다시 시도해 주세요.');return render_template('admin_login.html'),429
        if stored and check_password_hash(stored,request.form.get('password','')):
            session.clear();session['admin']=True;session['admin_v']=admin_session_ver();session['admin_at']=time.time();session.permanent=False;return redirect(url_for('admin'))
        note_attempt('admin')
        flash('로그인에 실패했습니다.')
    return render_template('admin_login.html')
ADMIN_IDLE_SECONDS=2*60*60  # 관리자 화면을 2시간 쓰지 않으면 자동 로그아웃
def end_admin():
    for k in ('admin','admin_v','admin_at','edit_mode'):session.pop(k,None)
def admin_active():
    # 관리자 로그인이 살아 있는지: 비밀번호를 바꿨거나 오래 쓰지 않았으면 끊음
    if not session.get('admin'):return False
    if session.get('admin_v')!=admin_session_ver() or time.time()-session.get('admin_at',0)>ADMIN_IDLE_SECONDS:
        end_admin();return False
    session['admin_at']=time.time()
    return True
app.jinja_env.globals['admin_active']=admin_active
def admin_only(f):
    @functools.wraps(f)
    def wrapped(*a,**kw):
        if not admin_active():
            flash('관리자 로그인이 끝났어요. 다시 로그인해 주세요.') if request.method=='GET' and request.path!='/admin' else None
            return redirect(url_for('admin_login'))
        return f(*a,**kw)
    return wrapped

@app.route('/admin/password',methods=['GET','POST'])
@admin_only
def admin_password():
    if request.method=='POST':
        cur=request.form.get('current','');pw=request.form.get('password','');pw2=request.form.get('password2','')
        if not check_password_hash(admin_password_hash(),cur):flash('지금 비밀번호가 맞지 않아요.')
        elif not (12<=len(pw)<=64 and re.search(r'[A-Za-z]',pw) and re.search(r'\d',pw)):flash('새 비밀번호는 영문과 숫자를 섞어 12자 이상으로 정해 주세요.')
        elif pw!=pw2:flash('새 비밀번호 확인이 일치하지 않아요.')
        elif check_password_hash(admin_password_hash(),pw):flash('지금 비밀번호와 다른 비밀번호로 정해 주세요.')
        else:
            ver=str(int(admin_session_ver())+1);stamp=datetime.datetime.now().isoformat(timespec='seconds')
            with conn() as db:
                for key,value in (('password_hash',generate_password_hash(pw)),('session_ver',ver)):
                    db.execute('INSERT INTO admin_settings(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated',(key,value,stamp))
            session['admin_v']=ver
            flash('관리자 비밀번호를 바꿨어요. 다음 로그인부터 새 비밀번호를 쓰세요.')
            return redirect(url_for('admin'))
    return render_template('admin_password.html')
# 지우면 사이트가 깨지는 문구 (이름·숫자 설정 등)
UNDELETABLE={'site.name','site.logo_rest','seo.home_title','home.latest_count','policy.effective_date','home.hero_button'}
@app.route('/admin/edit-mode',methods=['POST'])
@admin_only
def admin_edit_mode():
    session['edit_mode']=request.form.get('on')=='1'
    nxt=request.form.get('next','')
    if session['edit_mode']:return redirect(nxt if nxt.startswith('/') and not nxt.startswith(('//','/admin')) else url_for('home'))
    return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else url_for('admin'))

@app.route('/admin/list-remove',methods=['POST'])
@admin_only
def admin_list_remove():
    # 편집 모드의 "✕ 빼기": 목록(섹션·동의 항목 등)에서 한 줄을 지움
    key=request.form.get('list','');i=request.form.get('index',type=int)
    meta=_list_meta(key)
    if not meta or i is None:abort(400)
    rows=[dict(r) for r in load_lists()[key]]
    if not 0<=i<len(rows):abort(404)
    if len(rows)-1<meta[2]:return {'ok':False,'error':'%s은(는) 최소 %d개가 있어야 해요.'%(meta[0],meta[2])},400
    rows.pop(i)
    with conn() as db:db.execute('INSERT INTO site_lists(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated',(key,json.dumps(rows,ensure_ascii=False),datetime.datetime.now().isoformat(timespec='seconds')))
    return {'ok':True}

@app.route('/admin/inline',methods=['POST'])
@admin_only
def admin_inline():
    # 사이트 화면에서 문장 하나를 바로 고칠 때 쓰는 저장 주소. 비우거나 reset이면 기본값으로.
    key=request.form.get('key','');value=request.form.get('value','').replace('\r\n','\n').strip()
    reset=request.form.get('reset')=='1';delete=request.form.get('delete')=='1';stamp=datetime.datetime.now().isoformat(timespec='seconds')
    if delete:value=''
    if key.startswith('list:'):
        try:_,lk,i,field=key.split(':');i=int(i)
        except ValueError:abort(400)
        meta=_list_meta(lk)
        if not meta or field not in dict((n,o) for n,_,o in meta[1]):abort(400)
        title,fields,_=meta;opts=dict((n,o) for n,_,o in fields)[field]
        if opts.get('choices') or field in ('url','button_link','count'):abort(400)
        rows=[dict(r) for r in load_lists()[lk]]
        if not 0<=i<len(rows):abort(404)
        if not opts.get('multiline'):value=' '.join(value.split())
        if len(value)>site_content.MAX_LENGTH:abort(400)
        if not value and field==fields[0][0]:return {'ok':False,'error':'이 칸은 비울 수 없어요. 항목째 빼려면 지우기를 눌러 주세요.'},400
        rows[i][field]=value
        with conn() as db:db.execute('INSERT INTO site_lists(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated',(lk,json.dumps(rows,ensure_ascii=False),stamp))
        return {'ok':True}
    field=site_content.FIELDS.get(key)
    if not field:abort(400)
    if not (field.get('multiline') or field.get('doc')):value=' '.join(value.split())
    if len(value)>(site_content.DOC_MAX_LENGTH if field.get('doc') else site_content.MAX_LENGTH):abort(400)
    if delete and key in UNDELETABLE:return {'ok':False,'error':'이 문구는 지울 수 없어요. 내용만 바꿔 주세요.'},400
    with conn() as db:
        if delete:db.execute('INSERT INTO site_content(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated',(key,'',stamp))
        elif reset or value==field['default'] or (not value and not field.get('optional')):db.execute('DELETE FROM site_content WHERE key=?',(key,))
        else:db.execute('INSERT INTO site_content(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated',(key,value,stamp))
    return {'ok':True}

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
        elif key.endswith(('categories','industries')) and len({r[first] for r in rows})!=len(rows):error='같은 이름이 두 번 들어갔어요.'
        elif key=='menu' and any(not r['label'] or not r['page'] for r in rows):error='메뉴 이름과 연결할 페이지를 모두 정해 주세요.'
        elif key=='menu' and any(r['page']=='custom' and not SAFE_LINK.match(r['url']) for r in rows):error='직접 입력한 주소는 https:// 또는 / 로 시작해야 해요.'
        elif (key=='home_blocks' or key.startswith('layout_')) and any(r['button_link'] and not SAFE_LINK.match(r['button_link']) for r in rows):error='버튼 주소는 https:// 또는 / 로 시작해야 해요.'
        elif key=='custom_pages' and any(not CUSTOM_SLUG.match(r['slug']) for r in rows):error='영문 주소는 영어 소문자·숫자·하이픈(-)으로 40자 이내로 적어 주세요.'
        elif key=='custom_pages' and len({r['slug'] for r in rows})!=len(rows):error='같은 영문 주소가 두 번 들어갔어요.'
        elif key=='custom_pages' and any(not r['title'] for r in rows):error='페이지 제목을 적어 주세요.'
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
@app.route('/admin/logout',methods=['POST'])
@admin_only
def logout():end_admin();return redirect(url_for('admin_login'))

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
    for table in ('posts','comments'):
        if 'user_id' not in {r['name'] for r in db.execute(f'PRAGMA table_info({table})')}:db.execute(f'ALTER TABLE {table} ADD COLUMN user_id INTEGER')

def board_enabled():return os.getenv('ENABLE_BOARD')=='1'
def voter_id():
    if g.get('user'):return hashlib.sha256(('member:%d'%g.user['id']).encode()).hexdigest()  # 회원은 기기가 달라도 공감 1회
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
        posts=db.execute('SELECT id,category,nickname,user_id,title,substr(body,1,160) AS excerpt,likes,comments,created FROM posts WHERE '+' AND '.join(where)+f' ORDER BY {order} LIMIT ? OFFSET ?',args+[BOARD_PAGE_SIZE,(page-1)*BOARD_PAGE_SIZE]).fetchall()
        week_ago=(datetime.datetime.now()-datetime.timedelta(days=7)).isoformat(timespec='seconds')
        hot=db.execute('SELECT id,category,title,likes,comments FROM posts WHERE hidden=0 AND likes>0 AND created>=? ORDER BY likes DESC,id DESC LIMIT 3',(week_ago,)).fetchall() if not (q or cat or page>1) else []
        liked={r['target'] for r in db.execute("SELECT target FROM board_votes WHERE kind='like' AND voter=?",(voter_id(),))}
    return render_template('board.html',posts=posts,hot=hot,liked=liked,categories=board_categories(),cat=cat,q=q,sort=sort,page=page,pages=max(1,-(-total//BOARD_PAGE_SIZE)),total=total,enabled=board_enabled())

@app.route('/board/write',methods=['GET','POST'])
def board_write():
    if request.method=='POST':
        if not board_enabled():abort(503,description='게시판 글쓰기 준비 중입니다.')
        f={k:request.form.get(k,'').strip() for k in ('category','nickname','password','title','body')}
        if g.user:f['nickname']=g.user['nickname'];f['password']='member'  # 회원은 로그인 정보로 쓰고 지움
        errors=[]
        if request.form.get('website'):abort(400)  # 사람에게는 보이지 않는 칸. 채워져 있으면 자동 등록 프로그램.
        if f['category'] not in board_categories():errors.append(ui_text('msg.m05','분류를 골라 주세요.'))
        if not 2<=len(f['nickname'])<=20:errors.append(ui_text('msg.m06','닉네임은 2~20자로 적어 주세요.'))
        if not 4<=len(f['password'])<=30:errors.append(ui_text('msg.m07','비밀번호는 4~30자로 정해 주세요.'))
        if not 2<=len(f['title'])<=100:errors.append(ui_text('msg.m08','제목은 2~100자로 적어 주세요.'))
        if not 10<=len(f['body'])<=5000:errors.append(ui_text('msg.m09','내용은 10~5,000자로 적어 주세요.'))
        if not request.form.get('agree'):errors.append(ui_text('msg.m10','글쓰기 약속에 동의해 주세요.'))
        with conn() as db:
            if not errors and recent_count(db,'posts',10)>=3:errors.append(ui_text('msg.m11','잠시 후 다시 올려 주세요. 10분에 3개까지 쓸 수 있어요.'))
            if errors:
                for e in errors:flash(e)
                return render_template('board_write.html',categories=board_categories(),enabled=True),400
            cur=db.execute('INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created,user_id) VALUES(?,?,?,?,?,?,?,?)',(f['category'],f['nickname'],'' if g.user else generate_password_hash(f['password']),f['title'],f['body'],ip_hash(),datetime.datetime.now().isoformat(timespec='seconds'),g.user['id'] if g.user else None))
        return redirect(url_for('board_post',post_id=cur.lastrowid))
    return render_template('board_write.html',categories=board_categories(),enabled=board_enabled())

@app.route('/board/<int:post_id>')
def board_post(post_id):
    with conn() as db:
        post=db.execute('SELECT * FROM posts WHERE id=?',(post_id,)).fetchone()
        if not post or (post['hidden'] and not admin_active()):abort(404)
        comments=db.execute('SELECT id,nickname,body,created,user_id FROM comments WHERE post_id=? AND hidden=0 ORDER BY id',(post_id,)).fetchall()
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
    if g.user:nickname=g.user['nickname'];password='member'
    with conn() as db:
        if not db.execute('SELECT 1 FROM posts WHERE id=? AND hidden=0',(post_id,)).fetchone():abort(404)
        if not (2<=len(nickname)<=20 and 4<=len(password)<=30 and 1<=len(body)<=1000):
            flash(ui_text('msg.m12','닉네임(2~20자), 비밀번호(4~30자), 댓글(1,000자 이내)을 확인해 주세요.'));return redirect(url_for('board_post',post_id=post_id)+'#comment-form')
        if recent_count(db,'comments',2)>=5:
            flash(ui_text('msg.m13','잠시 후 다시 남겨 주세요.'));return redirect(url_for('board_post',post_id=post_id)+'#comment-form')
        db.execute('INSERT INTO comments(post_id,nickname,pw_hash,body,ip_hash,created,user_id) VALUES(?,?,?,?,?,?,?)',(post_id,nickname,'' if g.user else generate_password_hash(password),body,ip_hash(),datetime.datetime.now().isoformat(timespec='seconds'),g.user['id'] if g.user else None))
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
    flash(ui_text('msg.m14','알려 주셔서 고마워요. 운영자가 확인할게요.'))
    if kind=='p' and flags>=FLAG_HIDE_THRESHOLD:return redirect(url_for('board'))
    return redirect(url_for('board_post',post_id=post_id))

@app.route('/board/delete/<kind>/<int:item_id>',methods=['POST'])
def board_delete(kind,item_id):
    if kind not in ('p','c'):abort(404)
    with conn() as db:
        item=db.execute('SELECT * FROM %s WHERE id=?'%('posts' if kind=='p' else 'comments'),(item_id,)).fetchone()
        if not item:abort(404)
        post_id=item_id if kind=='p' else item['post_id']
        own=g.user and item['user_id']==g.user['id']
        if not own and not (item['pw_hash'] and check_password_hash(item['pw_hash'],request.form.get('password',''))):
            flash(ui_text('msg.m15','비밀번호가 맞지 않아요.'));return redirect(url_for('board_post',post_id=post_id))
        delete_board_item(db,kind,item_id)
    flash(ui_text('msg.m16','삭제했어요.'))
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

# ---- 회원 ------------------------------------------------------------------
# 아이디·비밀번호 회원가입. 제보와 게시판은 비회원도 그대로 쓸 수 있고, 회원은 내 정보에서 모아 봄.
# 수집은 최소한으로: 아이디, 비밀번호(암호화), 닉네임, 이메일(선택). 탈퇴하면 바로 지움.
TERMS_VERSION='2026-10-09'
LOGIN_LOCK_FAILS=5        # 같은 아이디로 이만큼 틀리면 잠시 잠금
LOGIN_LOCK_MINUTES=10
IP_ATTEMPT_LIMIT=20       # 같은 접속지에서 10분 동안 실패 허용 횟수 (회원·관리자 공통)
app.config['PERMANENT_SESSION_LIFETIME']=datetime.timedelta(days=14)
LOGIN_ID_RE=re.compile(r'^[a-z0-9_]{4,20}$')
MEMBER_EMAIL_RE=re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
with conn() as db:
    db.execute('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,login_id TEXT NOT NULL UNIQUE COLLATE NOCASE,pw_hash TEXT NOT NULL,nickname TEXT NOT NULL UNIQUE COLLATE NOCASE,email TEXT NOT NULL DEFAULT '',terms_version TEXT NOT NULL,agreed_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',session_ver INTEGER NOT NULL DEFAULT 1,failed INTEGER NOT NULL DEFAULT 0,locked_until TEXT NOT NULL DEFAULT '',last_login TEXT NOT NULL DEFAULT '',ip_hash TEXT NOT NULL DEFAULT '',created TEXT NOT NULL)''')
    db.execute('CREATE TABLE IF NOT EXISTS login_attempts(kind TEXT NOT NULL,ip_hash TEXT NOT NULL,created TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS login_attempts_ip ON login_attempts(ip_hash,created)')

def members_enabled():return bool(os.getenv('SECRET_KEY'))  # 서버 비밀키가 있어야 로그인 쿠키를 안전하게 씀
def now():return datetime.datetime.now().isoformat(timespec='seconds')
def too_many_attempts(kind):
    since=(datetime.datetime.now()-datetime.timedelta(minutes=10)).isoformat(timespec='seconds')
    with conn() as db:
        db.execute('DELETE FROM login_attempts WHERE created<?',(since,))
        return db.execute('SELECT COUNT(*) FROM login_attempts WHERE kind=? AND ip_hash=? AND created>=?',(kind,ip_hash(),since)).fetchone()[0]>=IP_ATTEMPT_LIMIT
def note_attempt(kind):
    with conn() as db:db.execute('INSERT INTO login_attempts(kind,ip_hash,created) VALUES(?,?,?)',(kind,ip_hash(),now()))

@app.before_request
def load_user():
    g.user=None
    uid=session.get('uid')
    if not uid:return
    with conn() as db:user=db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    # 탈퇴·정지·비밀번호 변경 뒤에는 예전 로그인 쿠키를 무효로 함.
    if not user or user['status']!='active' or user['session_ver']!=session.get('uv'):
        session.pop('uid',None);session.pop('uv',None);return
    g.user=user
def member_only(f):
    @functools.wraps(f)
    def wrapped(*a,**kw):
        if not g.user:return redirect(url_for('login',next=request.full_path.rstrip('?')))
        return f(*a,**kw)
    return wrapped
def safe_next(default='home'):
    nxt=request.values.get('next','')
    return nxt if nxt.startswith('/') and not nxt.startswith('//') and '\\' not in nxt else url_for(default)
def sign_in(user,remember):
    # 회원 로그인은 관리자 로그인을 이어받지 않음 (로그인 유지 쿠키에 관리자 권한이 남지 않도록)
    keep={k:session[k] for k in ('voter',) if k in session}
    session.clear();session.update(keep)
    session['uid']=user['id'];session['uv']=user['session_ver'];session.permanent=bool(remember)

@app.route('/signup',methods=['GET','POST'])
def signup():
    if g.user:return redirect(url_for('mypage'))
    if request.method=='GET':return render_template('signup.html',enabled=members_enabled())
    if not members_enabled():abort(503,description='회원가입 준비 중입니다.')
    if request.form.get('website'):abort(400)
    f={k:request.form.get(k,'').strip() for k in ('login_id','nickname','email')}
    f['login_id']=f['login_id'].lower();pw=request.form.get('password','');pw2=request.form.get('password2','')
    errors=[]
    if not all(request.form.get(k) for k in ('agree_terms','agree_privacy','agree_age')):errors.append(ui_text('msg.m17','필수 동의 항목을 모두 확인해 주세요.'))
    if not LOGIN_ID_RE.match(f['login_id']):errors.append(ui_text('msg.m18','아이디는 영문 소문자·숫자·밑줄(_)로 4~20자로 정해 주세요.'))
    if not (8<=len(pw)<=64 and re.search(r'[A-Za-z]',pw) and re.search(r'\d',pw)):errors.append(ui_text('msg.m19','비밀번호는 영문과 숫자를 섞어 8자 이상으로 정해 주세요.'))
    elif pw!=pw2:errors.append(ui_text('msg.m20','비밀번호 확인이 일치하지 않아요.'))
    elif f['login_id'] and f['login_id'] in pw.lower():errors.append(ui_text('msg.m21','비밀번호에 아이디를 넣지 말아 주세요.'))
    if not 2<=len(f['nickname'])<=12 or not re.match(r'^[0-9A-Za-z가-힣_]+$',f['nickname']):errors.append(ui_text('msg.m22','닉네임은 한글·영문·숫자로 2~12자로 정해 주세요.'))
    elif f['nickname'] in ('운영자','관리자','탈퇴한회원') or '운영' in f['nickname'] or '관리자' in f['nickname']:errors.append(ui_text('msg.m23','사용할 수 없는 닉네임이에요.'))
    if f['email'] and (len(f['email'])>120 or not MEMBER_EMAIL_RE.match(f['email'])):errors.append(ui_text('msg.m24','이메일 주소를 확인해 주세요.'))
    with conn() as db:
        if not errors:
            if db.execute('SELECT 1 FROM users WHERE login_id=?',(f['login_id'],)).fetchone():errors.append(ui_text('msg.m25','이미 쓰고 있는 아이디예요.'))
            if db.execute('SELECT 1 FROM users WHERE nickname=?',(f['nickname'],)).fetchone():errors.append(ui_text('msg.m26','이미 쓰고 있는 닉네임이에요.'))
        if not errors:
            hour_ago=(datetime.datetime.now()-datetime.timedelta(hours=1)).isoformat(timespec='seconds')
            if db.execute('SELECT COUNT(*) FROM users WHERE ip_hash=? AND created>=?',(ip_hash(),hour_ago)).fetchone()[0]>=3:errors.append(ui_text('msg.m27','잠시 후 다시 가입해 주세요.'))
        if errors:
            for e in errors:flash(e)
            return render_template('signup.html',enabled=True),400
        cur=db.execute('INSERT INTO users(login_id,pw_hash,nickname,email,terms_version,agreed_at,ip_hash,created) VALUES(?,?,?,?,?,?,?,?)',(f['login_id'],generate_password_hash(pw),f['nickname'],f['email'],TERMS_VERSION,now(),ip_hash(),now()))
        user=db.execute('SELECT * FROM users WHERE id=?',(cur.lastrowid,)).fetchone()
    sign_in(user,False)
    flash(user['nickname']+ui_text('msg.welcome','님, 가입을 환영해요!'))
    return redirect(url_for('mypage'))

@app.route('/login',methods=['GET','POST'])
def login():
    if g.user:return redirect(safe_next())
    if request.method=='GET':return render_template('login.html',enabled=members_enabled())
    if not members_enabled():abort(503)
    login_id=request.form.get('login_id','').strip().lower()[:40];pw=request.form.get('password','')
    fail=ui_text('msg.m30','아이디 또는 비밀번호가 맞지 않아요.')
    if too_many_attempts('member'):
        flash(ui_text('msg.m28','로그인 시도가 너무 많아요. 10분 뒤 다시 시도해 주세요.'));return render_template('login.html',enabled=True),429
    with conn() as db:
        user=db.execute('SELECT * FROM users WHERE login_id=?',(login_id,)).fetchone()
        if user and user['locked_until'] and user['locked_until']>now():
            flash(ui_text('msg.locked','비밀번호를 여러 번 틀려 잠시 잠겼어요. 10분 뒤 다시 시도해 주세요.'));return render_template('login.html',enabled=True),429
        if not user or not check_password_hash(user['pw_hash'],pw):
            if user:
                failed=user['failed']+1
                lock=(datetime.datetime.now()+datetime.timedelta(minutes=LOGIN_LOCK_MINUTES)).isoformat(timespec='seconds') if failed>=LOGIN_LOCK_FAILS else ''
                db.execute('UPDATE users SET failed=?,locked_until=? WHERE id=?',(0 if lock else failed,lock,user['id']))
            failed_login=True
        else:failed_login=False
        if not failed_login and user['status']!='active':
            flash(ui_text('msg.m29','이용이 제한된 계정이에요. 운영자에게 문의해 주세요.'));return render_template('login.html',enabled=True),403
        if not failed_login:db.execute("UPDATE users SET failed=0,locked_until='',last_login=? WHERE id=?",(now(),user['id']))
    if failed_login:
        note_attempt('member');flash(fail);return render_template('login.html',enabled=True),401
    sign_in(user,request.form.get('remember'))
    return redirect(safe_next())

@app.route('/account/help')
def account_help():return render_template('account_help.html')

@app.route('/logout',methods=['POST'])
def member_logout():
    session.pop('uid',None);session.pop('uv',None);session.pop('case_id',None)
    flash(ui_text('msg.m31','로그아웃했어요.'))
    return redirect(url_for('home'))

@app.route('/me')
@member_only
def mypage():
    with conn() as db:
        cases=db.execute('SELECT id,receipt,category,company,subject,status,created,public_consent,published FROM cases WHERE user_id=? ORDER BY id DESC LIMIT 100',(g.user['id'],)).fetchall()
        posts=db.execute('SELECT id,category,title,likes,comments,created,hidden FROM posts WHERE user_id=? ORDER BY id DESC LIMIT 50',(g.user['id'],)).fetchall()
        comment_count=db.execute('SELECT COUNT(*) FROM comments WHERE user_id=?',(g.user['id'],)).fetchone()[0]
    return render_template('mypage.html',cases=cases,posts=posts,comment_count=comment_count)

@app.route('/me/case/<int:case_id>')
@member_only
def my_case(case_id):
    with conn() as db:
        if not db.execute('SELECT 1 FROM cases WHERE id=? AND user_id=?',(case_id,g.user['id'])).fetchone():abort(404)
    session['case_id']=case_id
    return redirect(url_for('case_detail'))

@app.route('/me/edit',methods=['POST'])
@member_only
def mypage_edit():
    action=request.form.get('action')
    with conn() as db:
        if action=='email':
            email=request.form.get('email','').strip()
            if email and (len(email)>120 or not MEMBER_EMAIL_RE.match(email)):flash(ui_text('msg.m32','이메일 주소를 확인해 주세요.'))
            else:db.execute('UPDATE users SET email=? WHERE id=?',(email,g.user['id']));flash(ui_text('msg.m37','이메일을 저장했어요.') if email else ui_text('msg.m38','이메일을 지웠어요.'))
        elif action=='password':
            cur_pw=request.form.get('current','');pw=request.form.get('password','');pw2=request.form.get('password2','')
            if not check_password_hash(g.user['pw_hash'],cur_pw):flash(ui_text('msg.m33','지금 비밀번호가 맞지 않아요.'))
            elif not (8<=len(pw)<=64 and re.search(r'[A-Za-z]',pw) and re.search(r'\d',pw)):flash(ui_text('msg.m34','새 비밀번호는 영문과 숫자를 섞어 8자 이상으로 정해 주세요.'))
            elif pw!=pw2:flash(ui_text('msg.m35','새 비밀번호 확인이 일치하지 않아요.'))
            else:
                # 다른 기기에 남은 로그인은 끊고, 지금 화면은 그대로 로그인 유지.
                db.execute('UPDATE users SET pw_hash=?,session_ver=session_ver+1 WHERE id=?',(generate_password_hash(pw),g.user['id']))
                session['uv']=g.user['session_ver']+1;flash(ui_text('msg.m36','비밀번호를 바꿨어요. 다른 기기에서는 다시 로그인해야 해요.'))
        else:abort(400)
    return redirect(url_for('mypage')+'#settings')

@app.route('/me/withdraw',methods=['POST'])
@member_only
def withdraw():
    if not check_password_hash(g.user['pw_hash'],request.form.get('password','')) or not request.form.get('confirm'):
        flash(ui_text('msg.m39','비밀번호와 탈퇴 확인을 다시 확인해 주세요.'));return redirect(url_for('mypage')+'#withdraw')
    with conn() as db:delete_member(db,g.user['id'],bool(request.form.get('delete_posts')))
    session.pop('uid',None);session.pop('uv',None);session.pop('case_id',None)
    flash(ui_text('msg.m40','탈퇴를 마쳤어요. 그동안 함께해 주셔서 고마워요.'))
    return redirect(url_for('home'))

def delete_member(db,uid,delete_posts):
    # 회원 정보는 바로 지움. 제보는 접수번호·조회 코드로 계속 확인할 수 있도록 회원 연결만 끊음.
    if delete_posts:
        for r in db.execute('SELECT id FROM comments WHERE user_id=?',(uid,)).fetchall():delete_board_item(db,'c',r['id'])
        for r in db.execute('SELECT id FROM posts WHERE user_id=?',(uid,)).fetchall():delete_board_item(db,'p',r['id'])
    else:
        for table in ('posts','comments'):db.execute(f"UPDATE {table} SET user_id=NULL,nickname='탈퇴한 회원' WHERE user_id=?",(uid,))
    db.execute('DELETE FROM board_votes WHERE voter=?',(hashlib.sha256(('member:%d'%uid).encode()).hexdigest(),))
    db.execute('UPDATE cases SET user_id=NULL WHERE user_id=?',(uid,))
    db.execute('DELETE FROM users WHERE id=?',(uid,))

@app.route('/admin/members',methods=['GET','POST'])
@admin_only
def admin_members():
    with conn() as db:
        if request.method=='POST':
            uid=request.form.get('id',type=int);action=request.form.get('action')
            if not uid or action not in ('suspend','restore','delete'):abort(400)
            if not db.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():abort(404)
            if action=='delete':delete_member(db,uid,bool(request.form.get('delete_posts')))
            else:db.execute('UPDATE users SET status=?,session_ver=session_ver+1 WHERE id=?',('suspended' if action=='suspend' else 'active',uid))
            flash({'suspend':'이용을 정지했어요.','restore':'정지를 풀었어요.','delete':'회원을 삭제했어요.'}[action])
            return redirect(url_for('admin_members',q=request.args.get('q','')))
        q=request.args.get('q','').strip()[:40]
        like='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        members=db.execute("""SELECT u.id,u.login_id,u.nickname,u.email,u.status,u.created,u.last_login,
            (SELECT COUNT(*) FROM cases WHERE user_id=u.id) AS n_cases,(SELECT COUNT(*) FROM posts WHERE user_id=u.id) AS n_posts
            FROM users u WHERE u.login_id LIKE ? ESCAPE '\\' OR u.nickname LIKE ? ESCAPE '\\' ORDER BY u.id DESC LIMIT 300""",(like,like)).fetchall()
        total=db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    return render_template('admin_members.html',members=members,q=q,total=total)

# ---- 직원 제보 관리 / 관리자 홈 --------------------------------------------
# 관리자(대표): 사이트 문구·항목·회원·게시판·직원 계정을 관리하고, 제보 관리 화면도 볼 수 있음.
# 직원: 관리자가 만든 개인 계정으로 /staff 에 로그인해 제보만 확인·처리. 사이트 설정은 볼 수 없음.
STAFF_PAGE_SIZE=30
with conn() as db:
    db.execute('''CREATE TABLE IF NOT EXISTS staff(id INTEGER PRIMARY KEY,login_id TEXT NOT NULL UNIQUE COLLATE NOCASE,name TEXT NOT NULL,pw_hash TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,session_ver INTEGER NOT NULL DEFAULT 1,failed INTEGER NOT NULL DEFAULT 0,locked_until TEXT NOT NULL DEFAULT '',last_login TEXT NOT NULL DEFAULT '',created TEXT NOT NULL)''')
    db.execute('CREATE TABLE IF NOT EXISTS case_log(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,created TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS case_log_case ON case_log(case_id)')
    if 'author' not in {r['name'] for r in db.execute('PRAGMA table_info(internal_notes)')}:db.execute("ALTER TABLE internal_notes ADD COLUMN author TEXT NOT NULL DEFAULT ''")

@app.before_request
def load_staff():
    g.staff=None
    sid=session.get('staff_id')
    if not sid:return
    with conn() as db:member=db.execute('SELECT * FROM staff WHERE id=?',(sid,)).fetchone()
    if not member or not member['active'] or member['session_ver']!=session.get('staff_v'):
        session.pop('staff_id',None);session.pop('staff_v',None);return
    g.staff=member

# 제보 처리 화면은 두 곳에 따로 있음. 같은 기능이지만 주소·화면 틀·로그인이 완전히 분리됨.
#  - 기자실 /reporter : 소보루 기자 계정 전용. 관리자 로그인으로는 못 들어오고, 관리자 메뉴도 없음.
#  - 관리자 /admin/reports : 대표 전용. 관리자 화면 안의 한 메뉴.
AREAS={
    'reporter':{'layout':'reporter_base.html','list':'reporter_home','case':'reporter_case','file':'reporter_file','invite':'reporter_invite'},
    'admin':{'layout':'console.html','list':'admin_reports','case':'admin_report','file':'admin_file','invite':'admin_invite'},
}
def actor_name():return g.staff['name'] if g.get('area')=='reporter' and g.get('staff') else '대표'
def reporter_only(f):
    @functools.wraps(f)
    def wrapped(*a,**kw):
        if not g.get('staff'):return redirect(url_for('reporter_login',next=request.full_path.rstrip('?')))
        g.area='reporter'
        return f(*a,**kw)
    return wrapped
def admin_area(f):
    @functools.wraps(f)
    def wrapped(*a,**kw):
        g.area='admin'
        return f(*a,**kw)
    return admin_only(wrapped)
def log_case(db,case_id,action):
    db.execute('INSERT INTO case_log(case_id,actor,action,created) VALUES(?,?,?,?)',(case_id,actor_name(),action,now()))
def strong_password(pw):return 8<=len(pw)<=64 and re.search(r'[A-Za-z]',pw) and re.search(r'\d',pw)

def reports_list():
    ep=AREAS[g.area]
    status=request.args.get('status','');q=request.args.get('q','').strip()[:60];mine=request.args.get('mine')=='1' and g.area=='reporter'
    page=max(1,request.args.get('page',1,type=int))
    where=['1=1'];args=[]
    if status in STATUSES:where.append('status=?');args.append(status)
    else:status=''
    if q:
        like='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        where.append("(receipt LIKE ? ESCAPE '\\' OR subject LIKE ? ESCAPE '\\' OR company LIKE ? ESCAPE '\\')");args+=[like,like,like]
    if mine:where.append('assignee=?');args.append(g.staff['name'])
    cond=' AND '.join(where)
    with conn() as db:
        counts={r['status']:r['n'] for r in db.execute('SELECT status,COUNT(*) AS n FROM cases GROUP BY status')}
        total=db.execute('SELECT COUNT(*) FROM cases WHERE '+cond,args).fetchone()[0]
        cases=db.execute('SELECT id,receipt,industry,category,company,subject,status,created,assignee,public_consent,published,share_company FROM cases WHERE '+cond+' ORDER BY id DESC LIMIT ? OFFSET ?',args+[STAFF_PAGE_SIZE,(page-1)*STAFF_PAGE_SIZE]).fetchall()
    return render_template('reports_list.html',layout=ep['layout'],ep=ep,cases=cases,counts=counts,all_count=sum(counts.values()),status=status,q=q,mine=bool(mine),page=page,pages=max(1,-(-total//STAFF_PAGE_SIZE)),total=total)

def report_detail(case_id):
    ep=AREAS[g.area]
    with conn() as db:
        case=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        if not case:abort(404)
        if request.method=='POST':
            form=request.form.get('form','settings')
            if form=='settings':
                status=request.form.get('status','')
                if status not in STATUSES:abort(400)
                assignee=request.form.get('assignee',case['assignee'] or '').strip()[:80]
                published=int(bool(request.form.get('published'))) if case['public_consent'] else 0
                db.execute('UPDATE cases SET status=?,assignee=?,published=? WHERE id=?',(status,assignee,published,case_id))
                if status!=case['status']:log_case(db,case_id,f"진행 단계 변경: {case['status']} → {status}")
                if assignee!=(case['assignee'] or ''):log_case(db,case_id,f"담당 기자: {assignee or '미배정'}")
                if case['public_consent'] and published!=case['published']:log_case(db,case_id,'공개로 전환' if published else '비공개로 전환')
                flash('저장했어요.')
            elif form=='note':
                note=request.form.get('internal_note','').strip()
                if not note or len(note)>3000:abort(400)
                db.execute('INSERT INTO internal_notes(case_id,note,created,author) VALUES(?,?,?,?)',(case_id,note,now(),actor_name()))
            elif form=='message':
                msg=request.form.get('message','').strip()
                if not msg or len(msg)>3000:abort(400)
                db.execute('INSERT INTO messages(case_id,author,body,created) VALUES(?,?,?,?)',(case_id,'센터',msg,now()))
                log_case(db,case_id,'제보자에게 메시지 보냄')
            else:abort(400)
            return redirect(url_for(ep['case'],case_id=case_id)+('#'+form if form!='settings' else ''))
        msgs=db.execute('SELECT * FROM messages WHERE case_id=? ORDER BY id',(case_id,)).fetchall()
        files=db.execute('SELECT * FROM attachments WHERE case_id=?',(case_id,)).fetchall()
        notes=db.execute('SELECT * FROM internal_notes WHERE case_id=? ORDER BY id DESC',(case_id,)).fetchall()
        logs=db.execute('SELECT * FROM case_log WHERE case_id=? ORDER BY id DESC LIMIT 50',(case_id,)).fetchall()
        invite=db.execute('SELECT * FROM company_invites WHERE case_id=?',(case_id,)).fetchone()
        staff_names=[r['name'] for r in db.execute('SELECT name FROM staff WHERE active=1 ORDER BY name')]
        neighbors=(db.execute('SELECT id FROM cases WHERE id<? ORDER BY id DESC LIMIT 1',(case_id,)).fetchone(),db.execute('SELECT id FROM cases WHERE id>? ORDER BY id LIMIT 1',(case_id,)).fetchone())
    return render_template('report_detail.html',layout=ep['layout'],ep=ep,case=case,msgs=msgs,files=files,statuses=STATUSES,notes=notes,logs=logs,invite=invite,staff_names=staff_names,older=neighbors[0],newer=neighbors[1])

def download_file(file_id):
    with conn() as db:f=db.execute('SELECT * FROM attachments WHERE id=?',(file_id,)).fetchone()
    if not f:abort(404)
    return send_file(UPLOAD/f['stored'],as_attachment=True,download_name=f['original'])

def make_invite(case_id):
    ep=AREAS[g.area]
    with conn() as db:
        case=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        if not case:abort(404)
        if not case['share_company']:
            flash('기업 전달 동의가 없는 제보입니다.');return redirect(url_for(ep['case'],case_id=case_id))
        token=secrets.token_urlsafe(32)
        db.execute('INSERT OR REPLACE INTO company_invites(case_id,token_hash,company_name,created) VALUES(?,?,?,?)',(case_id,hashlib.sha256(token.encode()).hexdigest(),case['company'],now()))
        log_case(db,case_id,'기업 답변 링크 발급')
    return render_template('invite_created.html',layout=ep['layout'],ep=ep,case=case,invite_url=url_for('company_access',case_id=case_id,token=token,_external=True))

# ---- 소보루 기자실 (/reporter) ----
@app.route('/reporter/login',methods=['GET','POST'])
def reporter_login():
    if g.staff:return redirect(url_for('reporter_home'))
    if request.method=='GET':return render_template('reporter_login.html')
    login_id=request.form.get('login_id','').strip().lower()[:40];pw=request.form.get('password','')
    if too_many_attempts('staff'):
        flash('로그인 시도가 너무 많아요. 10분 뒤 다시 시도해 주세요.');return render_template('reporter_login.html'),429
    with conn() as db:
        member=db.execute('SELECT * FROM staff WHERE login_id=?',(login_id,)).fetchone()
        if member and member['locked_until'] and member['locked_until']>now():
            flash(f'비밀번호를 여러 번 틀려 잠시 잠겼어요. {LOGIN_LOCK_MINUTES}분 뒤 다시 시도해 주세요.');return render_template('reporter_login.html'),429
        ok=bool(member) and check_password_hash(member['pw_hash'],pw)
        if member and not ok:
            failed=member['failed']+1
            lock=(datetime.datetime.now()+datetime.timedelta(minutes=LOGIN_LOCK_MINUTES)).isoformat(timespec='seconds') if failed>=LOGIN_LOCK_FAILS else ''
            db.execute('UPDATE staff SET failed=?,locked_until=? WHERE id=?',(0 if lock else failed,lock,member['id']))
        if ok and not member['active']:
            flash('사용이 중지된 계정이에요. 대표에게 문의해 주세요.');return render_template('reporter_login.html'),403
        if ok:db.execute("UPDATE staff SET failed=0,locked_until='',last_login=? WHERE id=?",(now(),member['id']))
    if not ok:
        note_attempt('staff');flash('아이디 또는 비밀번호가 맞지 않아요.');return render_template('reporter_login.html'),401
    session['staff_id']=member['id'];session['staff_v']=member['session_ver']
    nxt=request.values.get('next','')
    return redirect(nxt if nxt.startswith('/reporter') and '//' not in nxt else url_for('reporter_home'))

@app.route('/reporter/logout',methods=['POST'])
def reporter_logout():
    session.pop('staff_id',None);session.pop('staff_v',None)
    return redirect(url_for('reporter_login'))

@app.route('/reporter/password',methods=['GET','POST'])
@reporter_only
def reporter_password():
    if request.method=='POST':
        cur=request.form.get('current','');pw=request.form.get('password','');pw2=request.form.get('password2','')
        if not check_password_hash(g.staff['pw_hash'],cur):flash('지금 비밀번호가 맞지 않아요.')
        elif not strong_password(pw):flash('새 비밀번호는 영문과 숫자를 섞어 8자 이상으로 정해 주세요.')
        elif pw!=pw2:flash('새 비밀번호 확인이 일치하지 않아요.')
        else:
            with conn() as db:db.execute('UPDATE staff SET pw_hash=?,session_ver=session_ver+1 WHERE id=?',(generate_password_hash(pw),g.staff['id']))
            session['staff_v']=g.staff['session_ver']+1;flash('비밀번호를 바꿨어요.');return redirect(url_for('reporter_home'))
    return render_template('reporter_password.html')

@app.route('/reporter')
@reporter_only
def reporter_home():return reports_list()
@app.route('/reporter/case/<int:case_id>',methods=['GET','POST'])
@reporter_only
def reporter_case(case_id):return report_detail(case_id)
@app.route('/reporter/file/<int:file_id>')
@reporter_only
def reporter_file(file_id):return download_file(file_id)
@app.route('/reporter/invite/<int:case_id>',methods=['POST'])
@reporter_only
def reporter_invite(case_id):return make_invite(case_id)

# ---- 관리자 화면 안의 제보 처리 (/admin/reports) ----
@app.route('/admin/reports')
@admin_area
def admin_reports():return reports_list()
@app.route('/admin/reports/<int:case_id>',methods=['GET','POST'])
@admin_area
def admin_report(case_id):return report_detail(case_id)
@app.route('/admin/file/<int:file_id>')
@admin_area
def admin_file(file_id):return download_file(file_id)
@app.route('/admin/invite/<int:case_id>',methods=['POST'])
@admin_area
def admin_invite(case_id):return make_invite(case_id)

# 예전 주소로 들어와도 새 화면으로 보냄
@app.route('/staff')
@app.route('/staff/<path:rest>')
def staff_moved(rest=''):
    target={'login':'reporter_login','password':'reporter_password'}.get(rest)
    if target:return redirect(url_for(target))
    m=re.fullmatch(r'case/(\d+)',rest)
    return redirect(url_for('reporter_case',case_id=int(m[1])) if m else url_for('reporter_home'))
@app.route('/admin/case/<int:case_id>')
def admin_case_redirect(case_id):return redirect(url_for('admin_report',case_id=case_id))

@app.route('/admin')
@admin_only
def admin():
    with conn() as db:
        counts={r['status']:r['n'] for r in db.execute('SELECT status,COUNT(*) AS n FROM cases GROUP BY status')}
        week_ago=(datetime.datetime.now()-datetime.timedelta(days=7)).isoformat(timespec='seconds')
        stats={
            'new_cases':db.execute('SELECT COUNT(*) FROM cases WHERE created>=?',(week_ago,)).fetchone()[0],
            'open_cases':db.execute('SELECT COUNT(*) FROM cases WHERE status!=?',(STATUSES[-1],)).fetchone()[0],
            'members':db.execute('SELECT COUNT(*) FROM users').fetchone()[0],
            'new_members':db.execute('SELECT COUNT(*) FROM users WHERE created>=?',(week_ago,)).fetchone()[0],
            'flagged':db.execute('SELECT (SELECT COUNT(*) FROM posts WHERE flags>0 OR hidden=1)+(SELECT COUNT(*) FROM comments WHERE flags>0 OR hidden=1)').fetchone()[0],
            'takedowns':db.execute("SELECT COUNT(*) FROM takedown_requests WHERE status IN ('접수','검토 중')").fetchone()[0],
            'staff':db.execute('SELECT COUNT(*) FROM staff WHERE active=1').fetchone()[0],
        }
    return render_template('admin_home.html',counts=counts,stats=stats)

@app.route('/admin/site')
@admin_only
def admin_site():
    # 사이트 편집 안내: 화면에서 바로 고치기, 구성 바꾸기, 숨은 문구·설정으로 가는 첫 화면
    with conn() as db:changed=db.execute('SELECT COUNT(*) FROM site_content').fetchone()[0]+db.execute('SELECT COUNT(*) FROM site_lists').fetchone()[0]
    return render_template('admin_site.html',changed=changed,custom_pages=g.lists.get('custom_pages',[]))

@app.route('/admin/staff',methods=['GET','POST'])
@admin_only
def admin_staff():
    with conn() as db:
        if request.method=='POST':
            action=request.form.get('action')
            if action=='add':
                login_id=request.form.get('login_id','').strip().lower();name=request.form.get('name','').strip();pw=request.form.get('password','')
                if not LOGIN_ID_RE.match(login_id):flash('아이디는 영문 소문자·숫자·밑줄로 4~20자로 정해 주세요.')
                elif not 1<=len(name)<=20:flash('이름을 20자 이내로 적어 주세요.')
                elif not strong_password(pw):flash('비밀번호는 영문과 숫자를 섞어 8자 이상으로 정해 주세요.')
                elif db.execute('SELECT 1 FROM staff WHERE login_id=?',(login_id,)).fetchone():flash('이미 있는 아이디예요.')
                else:
                    db.execute('INSERT INTO staff(login_id,name,pw_hash,created) VALUES(?,?,?,?)',(login_id,name,generate_password_hash(pw),now()))
                    flash(f'{name} 기자 계정을 만들었어요. 아이디와 비밀번호를 직접 전달해 주세요.')
                return redirect(url_for('admin_staff'))
            sid=request.form.get('id',type=int)
            member=db.execute('SELECT * FROM staff WHERE id=?',(sid,)).fetchone() if sid else None
            if not member:abort(404)
            if action=='reset':
                pw=request.form.get('password','')
                if not strong_password(pw):flash('새 비밀번호는 영문과 숫자를 섞어 8자 이상으로 정해 주세요.')
                else:
                    db.execute("UPDATE staff SET pw_hash=?,session_ver=session_ver+1,failed=0,locked_until='' WHERE id=?",(generate_password_hash(pw),sid))
                    flash(f"{member['name']} 비밀번호를 바꿨어요.")
            elif action in ('stop','start'):
                db.execute('UPDATE staff SET active=?,session_ver=session_ver+1 WHERE id=?',(int(action=='start'),sid))
                flash(f"{member['name']} 계정을 {'다시 사용하게 했어요' if action=='start' else '사용 중지했어요. 바로 로그아웃돼요'}.")
            elif action=='delete':
                db.execute('DELETE FROM staff WHERE id=?',(sid,));flash(f"{member['name']} 계정을 삭제했어요.")
            else:abort(400)
            return redirect(url_for('admin_staff'))
        members=db.execute('SELECT * FROM staff ORDER BY active DESC,id').fetchall()
    return render_template('admin_staff.html',members=members)

if __name__=='__main__':app.run(debug=False)
