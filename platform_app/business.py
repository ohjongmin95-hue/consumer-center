"""기업용 소보루 CS (+ 센터 운영 화면 /ops).

기업: 가입 → 운영자 승인 → 로그인 → 승인 카드(승인·보류·자료 요청), 전체 요청, 자동 처리 규칙, 설정.
운영자: 기업 가입 승인, 기업 목록, 비입점 기업 요청 처리(전달 시도·회신 기록·피해구제 안내).
"""
import os, re, hmac, json, functools, datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, send_file, g, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
import csv, io
import core, law, insights, drafting, chatbot
import tracking as tracking_mod
import orders as orders_mod
import shops, mailin
import product_pdf
import team, inbox, workflow, automations, livechat, onboard, demo, funnel, market, sales, cms, csimport, growth, security, cafe24, openapi, aistats, instagram
from core import conn, clean, digits, BIG

app=Flask(__name__,static_folder='static',template_folder='templates')
app.jinja_env.globals.update(core.TEMPLATE_GLOBALS,site='biz',now_iso=core.iso,law_check=law.check,is_direct=core.is_direct,BIZ_STATUS=onboard.BIZ_STATUS,PLANS=onboard.PLANS)
OPS_HASH=os.getenv('OPS_PASSWORD_HASH','')
# 소개 화면의 앱 받기 버튼: 스토어 주소를 서버 설정(.env)에 넣으면 '곧 출시' 대신 버튼이 나온다
APP_LINKS={'android':os.getenv('BIZ_APP_ANDROID_URL',''),'ios':os.getenv('BIZ_APP_IOS_URL','')}
EMAIL_RE=re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

app.register_blueprint(market.bp);app.register_blueprint(sales.bp);app.register_blueprint(cms.bp);app.register_blueprint(csimport.bp);app.register_blueprint(growth.bp);app.register_blueprint(security.bp);app.register_blueprint(cafe24.bp);app.register_blueprint(openapi.bp);app.register_blueprint(aistats.bp);app.register_blueprint(instagram.bp)
app.jinja_env.globals.update(has_ep=lambda name:name in app.view_functions)

@app.before_request
def guard():
    if not request.path.startswith(('/api/','/hook/')):core.check_csrf()  # 앱 API는 쿠키 대신 토큰을, 택배 알림은 주소의 서명 토큰을 쓴다
app.after_request(core.copy_after_request('biz'))  # 운영 화면에서 고친 문구 적용
core.track_template(app)

def me():
    if 'co' not in g:
        g.co=None;g.who=None
        if session.get('co_id'):
            with conn() as db:
                co=core.company(db,session['co_id']);sid=session.get('staff_id')
                s=team.member(db,co['id'],sid) if co and sid else None
                d=demo.of(db,co) if co and session.get('demo') else None
            # 가입하면 바로 쓴다(회사 인증 전이어도 로그인). 데모로 바꿔 두었으면 화면은 데모 회사를 보여 준다.
            if co and co['status']=='active' and (not sid or (s and s['status']=='active')):
                g.real=co;g.co=d or co;g.demo=bool(d);g.who=team.staff_actor(s) if s else team.owner_actor(co)
                if session.get('demo') and not d:session.pop('demo',None)
            else:session.pop('co_id',None);session.pop('staff_id',None);session.pop('demo',None)
    return g.co
def real():
    """로그인한 진짜 회사 (데모를 보는 중이어도). 인증·설정 도우미·데모 전환은 이것을 본다."""
    me();return getattr(g,'real',None)
def in_demo():me();return bool(getattr(g,'demo',False))
def who():
    """지금 로그인한 사람 (대표 또는 직원). 로그인 전이면 None."""
    me();return getattr(g,'who',None)
# 역할별로 못 들어가는 화면 (team.can 참고). 앱 API는 대표 로그인만 받는다.
MANAGE_EPS={'macros','automations_page','connect_widget','c24.page','c24.callback','api.manage','gr.co_partner','imp.page','imp.batch','imp.undo','rules','ai_profile','products','products_pdf','product_import','settings','connect','connect_shop','connect_email','ig.page','ig.callback','team_page'}
DECIDE_EPS={'approve_many'}
DECIDE_ACTS={'approve','comp','comp_skip','refund_done'}
# 데모에서 막는 화면: 진짜 키·직원·계정·외부 연결을 건드리는 곳
DEMO_BLOCKED={'c24.page','c24.callback','ig.page','ig.callback','connect_email','api.manage','gr.co_partner','imp.page','imp.batch','imp.undo','connect','connect_shop','team_page','settings','start','products_pdf','product_import','hook_trace'}
@app.before_request
def role_guard():
    a=who() if not request.path.startswith(('/api/','/hook/','/ops')) else None
    if not a:return
    g.actor=a['name']
    ep=request.endpoint or ''
    need='manage' if ep in MANAGE_EPS else 'decide' if ep in DECIDE_EPS else ('work' if request.method=='POST' and ep!='logout' else '')
    if need and not team.can(a,need):
        flash(f"{team.ROLES[a['role']]} 계정은 이 일을 할 수 없어요. 대표나 관리자에게 부탁해 주세요.",'error')
        return redirect(url_for('decide'))
    if in_demo() and ep in DEMO_BLOCKED:
        flash('데모에서는 판매처 연결·팀·설정·주문 올리기를 할 수 없어요. 데모를 끝내고 해 주세요.','error')
        return redirect(url_for('decide'))
def login_required(f):
    @functools.wraps(f)
    def w(*a,**k):
        if not me():return redirect(url_for('login'))
        return f(*a,**k)
    return w
def ops_required(f):
    @functools.wraps(f)
    def w(*a,**k):
        if not session.get('ops'):return redirect(url_for('ops_login'))
        return f(*a,**k)
    return w
@app.context_processor
def ctx():
    co=me();n=0
    if co:
        with conn() as db:n=db.execute("SELECT COUNT(*) FROM cases WHERE company_id=? AND member=1 AND consent=1 AND decision='pending' AND status IN ('forwarded','seen')",(co['id'],)).fetchone()[0]
    a=who() if co else None;rc=real() if co else None
    return {'PUB_NAV':pub_nav(),'n_leads':sales.n_new() if session.get('ops') and request.path.startswith('/ops') else 0,'co':co,'n_pending':n,'is_ops':bool(session.get('ops')),'actor':a,'can':lambda what:team.can(a,what),'ROLES':team.ROLES,
            'real_co':rc,'in_demo':in_demo() if co else False,'trust':onboard.trust(rc) if rc else None,'setup':onboard.progress(rc) if rc else None}

def pub_nav():
    """로그인 전 위쪽 메뉴: 각 공개 화면 모듈이 내놓는 메뉴를 차례로."""
    return market.nav()+cms.nav()+sales.nav()
def kpis(rows):
    n=len(rows);auto=sum(r['decision']=='auto' for r in rows);res=sum(r['status']=='resolved' for r in rows)
    rated=sum(r['status'] in ('resolved','unresolved') for r in rows);late=sum(core.overdue(r) for r in rows)
    return {'n':n,'auto':round(auto/n*100) if n else 0,'res':round(res/rated*100) if rated else None,'late':late}

# ---------- 기업 계정 ----------
@app.route('/robots.txt')
def robots():return app.response_class(core.robots_txt('biz',['/api','/ops','/case','/all','/rules','/stats','/settings','/new','/guide','/report','/news','/reset','/team','/join','/start','/verify','/demo','/auth','/import','/partner/','/r/','/developers']),mimetype='text/plain')

@app.route('/sitemap.xml')
def sitemap():
    ent=[(p,'') for p in ['/','/signup','/login','/terms']+market.sitemap_paths()+sales.sitemap_paths()+growth.sitemap_paths()+['/security']]+cms.sitemap_entries()
    body=''.join('<url><loc>%s</loc>%s</url>'%(core.site_url('biz',p),'<lastmod>%s</lastmod>'%m if m else '') for p,m in ent)
    return app.response_class('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+body+'</urlset>',mimetype='application/xml')

@app.route('/terms')
def terms():
    return render_template('b_terms.html',op=core.OPERATOR,since=core.TERMS_SINCE,privacy_url=core.site_url('me','/privacy'))

def signup_apply(f,via='email',google_sub=''):
    """가입 검사와 저장. 웹·앱·구글 가입이 같이 쓴다. (입력값, 오류 문구, 회사 id). 문구가 비면 작업 공간이 만들어진 것이다.
    운영자 승인 없이 바로 쓴다. 소비자 접수·판매처 연결은 회사 인증(이메일 확인 + 사업자 상태) 뒤에 열린다 (onboard.py)."""
    d={k:clean(f.get(k),n) for k,n in (('name',40),('biz_no',20),('owner_name',20),('phone',20),('login_id',80),('contact',60),('industry',20))}
    if d['industry'] not in core.INDUSTRIES:d['industry']=''
    pw=f.get('password','');err=''
    if not d['name']:err='회사 이름을 적어 주세요.'
    elif len(digits(d['biz_no']))!=10:err='사업자등록번호 10자리를 적어 주세요.'
    elif not onboard.bizno_ok(d['biz_no']):err='사업자등록번호가 맞지 않아요. 사업자등록증의 번호를 다시 확인해 주세요.'
    elif not d['owner_name']:err='대표자 이름을 적어 주세요.'
    elif not EMAIL_RE.match(d['login_id']):err='로그인에 쓸 이메일을 정확히 적어 주세요.'
    elif via!='google' and len(pw)<10:err='비밀번호는 10자 이상으로 정해 주세요.'
    elif str(f.get('terms'))not in ('1','True','true'):err='이용약관에 동의해 주세요.'
    elif core.throttled('signup',limit=5,minutes=60):err='잠시 후 다시 시도해 주세요.'
    cid=None
    if not err:
        with conn() as db:cid,err=onboard.signup(db,d,generate_password_hash(pw if via!='google' else secrets.token_hex(24)),via,google_sub)
    return d,err,cid
def start_session(co,staff_id=None):
    """로그인 상태로 만든다 (가입·로그인·구글·직원 초대 공용). 다른 탭의 화면과 운영 로그인은 그대로 둔다."""
    keep={k:session[k] for k in ('ops','csrf','utm','vid','ref','partner_uid','c24_launch') if k in session}  # 다른 탭 화면·운영 로그인·첫 유입 기록·카페24에서 연 앱은 그대로
    session.clear();session.update(keep);session['co_id']=co['id'];session.permanent=True
    if staff_id:session['staff_id']=staff_id
@app.route('/signup',methods=['GET','POST'])
def signup():
    g_=session.get('google_signup') or {}
    if request.method=='POST':
        via='google' if g_ and clean(request.form.get('login_id'),80).lower()==g_.get('email') else 'email'
        d,err,cid=signup_apply(request.form,via,g_.get('sub','') if via=='google' else '')
        if not err:
            with conn() as db:co=core.company(db,cid)
            start_session(co);funnel.track('signup',co['id'],via)
            flash(f"{co['name']} 작업 공간을 만들었어요. 차례대로 설정하면 바로 쓸 수 있어요.",'ok');return redirect(url_for('start'))
        flash(err,'error');return render_template('b_signup.html',d=d,google=onboard.google_ready(),g_=g_),400
    d={'login_id':g_.get('email',''),'owner_name':g_.get('name','')} if g_ else {}
    return render_template('b_signup.html',d=d,google=onboard.google_ready(),g_=g_)

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='GET' and me():return redirect(url_for('decide'))  # 이미 로그인했으면 홈으로
    if request.method=='POST':
        lid=clean(request.form.get('login_id'),80).lower();pw=request.form.get('password','')
        if core.throttled('login',limit=10,minutes=10):flash('로그인 시도가 너무 많습니다. 10분 뒤에 다시 해 주세요.','error');return render_template('b_login.html'),429
        with conn() as db:
            co=db.execute('SELECT * FROM companies WHERE login_id=?',(lid,)).fetchone();st=None
            if not co:
                st=team.find_login(db,lid);co=core.company(db,st['company_id']) if st else None
        if not co or not check_password_hash((st or co)['pw_hash'],pw):flash('이메일이나 비밀번호가 맞지 않습니다.','error')
        elif co['status']=='pending':flash('가입 승인을 기다리고 있습니다. 승인되면 이메일로 알려 드립니다.','error')
        elif co['status']!='active':flash('이용할 수 없는 계정입니다. 센터에 문의해 주세요.','error')
        else:
            start_session(co,st['id'] if st else None)
            if st:
                with conn() as db:db.execute('UPDATE staff SET last_login=? WHERE id=?',(core.iso(),st['id']))
            return redirect(url_for('decide'))
        return render_template('b_login.html'),400
    return render_template('b_login.html')

@app.route('/forgot',methods=['GET','POST'])
def forgot():
    """비밀번호 찾기: 로그인 이메일로 1시간짜리 재설정 링크. 비밀번호가 바뀌면 그 링크는 더 못 쓴다."""
    if request.method=='POST':
        msg,level=send_reset(request.form.get('login_id'));flash(msg,level)
        if level=='ok':return redirect(url_for('login'))
    # 메일이 꺼져 있으면 운영팀에 문의하라는 안내 화면 (운영 화면 기업 관리에서 재설정 링크를 만들어 보낸다)
    return render_template('b_forgot.html',mail=core.mail_ready())
def send_reset(login_id):
    lid=clean(login_id,80).lower()
    if core.throttled('forgot',limit=5,minutes=30):return '잠시 후 다시 시도해 주세요.','error'
    if not core.mail_ready():return f'지금은 메일로 보내 드릴 수 없어요. {core.BNAME} 운영팀에 연락하시면 재설정 링크를 바로 보내 드려요.','error'
    with conn() as db:co=db.execute("SELECT * FROM companies WHERE login_id=? AND status='active'",(lid,)).fetchone()
    if co:
        core.send_mail(co['login_id'],f'[{core.BNAME}] 비밀번호 재설정',f"아래 링크에서 새 비밀번호를 정해 주세요. 1시간 동안만 열립니다.\n{reset_link(co)}\n\n직접 요청하지 않으셨다면 이 메일은 무시해 주세요.")
    return '가입된 이메일이라면 재설정 링크를 보냈습니다.','ok'

def reset_link(co):return core.site_url('biz','/reset/'+core.signer('pw').dumps({'id':co['id'],'h':co['pw_hash'][-16:]}))

@app.route('/reset/<tok>',methods=['GET','POST'])
def reset(tok):
    try:d=core.signer('pw').loads(tok,max_age=3600)
    except Exception:d=None
    with conn() as db:co=core.company(db,d['id']) if d else None
    if not co or co['pw_hash'][-16:]!=d['h']:flash('링크가 만료되었습니다. 다시 요청해 주세요.','error');return redirect(url_for('forgot'))
    if request.method=='POST':
        pw=request.form.get('password','')
        if len(pw)<10:flash('비밀번호는 10자 이상으로 정해 주세요.','error')
        else:
            with conn() as db:db.execute('UPDATE companies SET pw_hash=? WHERE id=?',(generate_password_hash(pw),co['id']))
            flash('비밀번호를 바꿨습니다. 새 비밀번호로 로그인해 주세요.','ok');return redirect(url_for('login'))
    return render_template('b_forgot.html',reset=True)

@app.route('/logout',methods=['POST'])
def logout():session.pop('co_id',None);session.pop('staff_id',None);return redirect(url_for('login'))

# ---------- 회사 인증·구글 가입 (onboard.py) ----------
@app.route('/verify/<tok>')
def verify(tok):
    """가입 확인 메일의 링크. 이메일 확인이 끝나고, 국세청 상태까지 맞으면 회사 인증도 바로 끝난다."""
    with conn() as db:co=onboard.check_verify(db,tok)
    if not co:flash('확인 링크가 만료됐거나 맞지 않아요. 로그인한 뒤 확인 메일을 다시 받아 주세요.','error');return redirect(url_for('login'))
    flash('이메일을 확인했어요.'+(' 회사 인증도 끝나 소비자 접수가 바로 들어와요.' if co['member'] else ' 사업자 확인이 끝나면 소비자 접수와 판매처 연결이 열려요.'),'ok')
    return redirect(url_for('start') if me() else url_for('login'))
@app.route('/verify',methods=['POST'])
@login_required
def verify_again():
    """확인 메일 다시 보내기, 국세청 상태 다시 확인하기."""
    co=real()
    if core.throttled('verify',limit=5,minutes=30):flash('잠시 후 다시 해 주세요','error')
    elif request.form.get('act')=='biz':
        with conn() as db:co=onboard.recheck_biz(db,co)
        flash('회사 인증이 끝났어요.' if co['member'] else f"국세청 확인 결과: {onboard.BIZ_STATUS.get(co['biz_status'],co['biz_status'])}"+('' if onboard.nts_ready() else ' (자동 확인 준비 중이라 운영팀이 직접 확인해요)'),'ok' if co['member'] else 'error')
    elif not co['email_verified']:
        onboard.send_verify(co);flash('확인 메일을 보냈어요.' if core.mail_ready() else '지금은 메일을 보낼 수 없어요. 운영팀이 직접 확인해 드려요.','ok' if core.mail_ready() else 'error')
    nxt=request.form.get('next','')
    return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else url_for('start'))

@app.route('/auth/google')
def google_login():
    """구글로 가입·로그인 (연동 대기: 운영 화면에 구글 클라이언트 ID·시크릿을 넣으면 켜진다)."""
    if not onboard.google_ready():flash('구글 로그인은 연결 준비 중이에요. 이메일로 가입해 주세요.','error');return redirect(url_for('signup'))
    session['g_state']=secrets.token_urlsafe(16)
    return redirect(onboard.google_auth_url(session['g_state']))
@app.route('/auth/google/callback')
def google_callback():
    st=session.pop('g_state',None)
    if not st or not hmac.compare_digest(st,request.args.get('state','')) or not request.args.get('code'):flash('구글 로그인을 다시 해 주세요.','error');return redirect(url_for('login'))
    u=onboard.google_user(request.args['code'])
    if not u:flash('구글에서 이메일을 확인하지 못했어요. 이메일로 가입해 주세요.','error');return redirect(url_for('signup'))
    with conn() as db:
        co=db.execute("SELECT * FROM companies WHERE (google_sub=? AND google_sub!='') OR lower(login_id)=?",(u['sub'],u['email'])).fetchone()
        stf=None if co else team.find_login(db,u['email'])
        if co and co['status']=='active':
            if not co['google_sub']:db.execute('UPDATE companies SET google_sub=?,email_verified=1 WHERE id=?',(u['sub'],co['id']));onboard.maybe_verify(db,core.company(db,co['id']))
            start_session(co);return redirect(url_for('decide'))
        if stf:
            start_session(core.company(db,stf['company_id']),stf['id']);db.execute('UPDATE staff SET last_login=? WHERE id=?',(core.iso(),stf['id']));return redirect(url_for('decide'))
        if co:flash('이용할 수 없는 계정입니다. 센터에 문의해 주세요.','error');return redirect(url_for('login'))
    session['google_signup']=u;flash('구글 계정을 확인했어요. 회사 정보를 적으면 가입이 끝나요.','ok')
    return redirect(url_for('signup'))

# ---------- 처음 설정 도우미 (/start) ----------
TEST_CASE=dict(channel='기타',category='배송 조회',title='[시험 문의] 주문한 상품은 언제 오나요?',body='소보루 CS 시험 문의예요. 실제 고객이 아니에요. 답변을 보내 보세요.',want='배송 확인',name='시험 고객')
@app.route('/start',methods=['GET','POST'])
@login_required
def start():
    """가입 직후 8단계 설정. 단계마다 저장해서 나중에 이어서 할 수 있다. 저장은 원래 설정 표에 그대로 한다."""
    co=real();step=request.values.get('step') or onboard.progress(co)['next'] or 'company'
    if step not in onboard.STEP_KEYS:abort(404)
    if request.method=='POST':
        if not team.can(who(),'manage'):flash('처음 설정은 대표나 관리자가 할 수 있어요','error');return redirect(url_for('decide'))
        f=request.form;act=f.get('act','save')
        with conn() as db:
            if act=='skip':co=onboard.mark(db,co,step,'skip')
            elif act=='test_new':
                st=onboard.setup_state(co)
                old=db.execute('SELECT id FROM cases WHERE id=? AND company_id=?',(st.get('test_case',0),co['id'])).fetchone()
                if not old:
                    d,err,cid=new_case_apply(co,TEST_CASE);st['test_case']=cid
                    db.execute('UPDATE companies SET setup=? WHERE id=?',(json.dumps(st,ensure_ascii=False),co['id']))
                    old={'id':cid}
                flash('시험 문의를 만들었어요. 답변을 보내면 이 단계가 끝나요.','ok');return redirect(url_for('case',case_id=old['id']))
            else:
                err=save_step(db,co,step,f)
                if err:flash(err,'error');return redirect(url_for('start',step=step))
                co=onboard.mark(db,co,step,'done')
            p=onboard.progress(co)
            if p['finished']:funnel.track('setup_done',co['id'])
        if p['finished']:flash('처음 설정을 모두 마쳤어요. 이제 실제 문의를 받아 보세요.','ok');return redirect(url_for('decide'))
        return redirect(url_for('start',step=p['next']))
    with conn() as db:
        prof=chatbot.profile(db,co['id']);lk=shops.links(db,co['id']);st=onboard.setup_state(co)
        tc=db.execute('SELECT * FROM cases WHERE id=? AND company_id=?',(st.get('test_case',0),co['id'])).fetchone()
        tc_done=bool(tc and db.execute("SELECT 1 FROM events WHERE case_id=? AND kind='co'",(tc['id'],)).fetchone())
        if step=='test' and tc_done and st.get('test')!='done':co=onboard.mark(db,co,'test','done')
    return render_template('b_start.html',step=step,p=onboard.progress(co),STEPS=onboard.STEPS,SHOP_TYPES=onboard.SHOP_TYPES,prof=prof,links=lk,SHOPS=shops.SHOPS,
        rc=co,tc=tc,tc_done=tc_done,link=core.site_url('me','/to/%d'%co['id']),widget=core.site_url('me','/widget.js?c=%d'%co['id']),tab='start')
def save_step(db,co,step,f):
    """설정 도우미 한 단계 저장. 오류 문구(없으면 '')."""
    if step=='company':
        ind=f.get('industry','') if f.get('industry','') in core.INDUSTRIES else ''
        if not ind:return '업종을 골라 주세요'
        db.execute('UPDATE companies SET industry=?,owner_name=?,phone=? WHERE id=?',(ind,clean(f.get('owner_name'),20) or co['owner_name'],digits(f.get('phone','')),co['id']))
    elif step=='shop':
        pick=[x for x in f.getlist('shop_types') if x in onboard.SHOP_TYPES]
        if not pick:return '파는 곳을 하나 이상 골라 주세요'
        db.execute('UPDATE companies SET shop_types=? WHERE id=?',(','.join(pick),co['id']))
    elif step=='center':
        email=clean(f.get('notify_email'),80)
        if email and not EMAIL_RE.match(email):return '알림 이메일을 확인해 주세요'
        if not clean(f.get('contact'),60):return '고객센터 연락처를 적어 주세요'
        db.execute('UPDATE companies SET contact=?,notify_email=? WHERE id=?',(clean(f.get('contact'),60),email or co['login_id'],co['id']))
        chatbot.save_profile(db,co['id'],{'hours':f.get('hours','')})
    elif step=='policy':
        if not clean(f.get('returns'),3000):return '교환·반품 규정을 적어 주세요'
        courier=f.get('return_courier','') if f.get('return_courier','') in core.COURIERS else ''
        db.execute('UPDATE companies SET return_address=?,return_courier=? WHERE id=?',(clean(f.get('return_address'),200),courier,co['id']))
        chatbot.save_profile(db,co['id'],{k:f.get(k,'') for k in ('shipping','returns')})
    elif step=='ai':
        chatbot.save_profile(db,co['id'],{k:f.get(k,'') for k in ('brand','scope','handoff')})
    elif step=='connect':
        if not shops.links(db,co['id']):return '아직 연결한 판매처가 없어요. 연결하거나 나중에 하기를 눌러 주세요'
    elif step=='test':
        st=onboard.setup_state(co)
        if not db.execute("SELECT 1 FROM events e JOIN cases c ON c.id=e.case_id WHERE c.id=? AND c.company_id=? AND e.kind='co'",(st.get('test_case',0),co['id'])).fetchone():
            return '시험 문의에 아직 답하지 않았어요'
    return ''

# ---------- 데모 (demo.py) ----------
@app.route('/demo',methods=['POST'])
@login_required
def demo_page():
    """데모 켜기·처음부터 다시·끝내기. 데모 회사는 진짜 회사와 완전히 따로 있다."""
    act=request.form.get('act','on');co=real()
    with conn() as db:
        if act=='off':session.pop('demo',None);flash('데모를 끝냈어요. 실제 화면이에요.','ok');return redirect(url_for('decide'))
        if act=='reset':demo.reset(db,co);session['demo']=True;flash('데모를 처음 상태로 되돌렸어요','ok');return redirect(url_for('decide'))
        demo.create(db,co)
    session['demo']=True;funnel.track('demo',co['id'])
    flash('데모 화면이에요. 견본 요청으로 승인·답변·배정을 마음껏 해 보세요. 실제 고객·주문에는 아무 영향이 없어요.','ok')
    return redirect(url_for('decide'))

# ---------- 기업 화면 ----------
# 기업은 전달에 동의한 요청만 본다
def my_cases(db,co):return db.execute('SELECT * FROM cases WHERE company_id=? AND member=1 AND consent=1 ORDER BY id DESC',(co['id'],)).fetchall()
def my_case(db,case_id):
    c=db.execute('SELECT * FROM cases WHERE id=? AND company_id=? AND member=1 AND consent=1',(case_id,me()['id'])).fetchone()
    if not c:abort(404)
    return c

def is_pending(r):return r['decision']=='pending' and r['status'] in ('forwarded','seen')
def is_open(r):return r['status'] in ('forwarded','seen','info')
def by_cat(rows):
    n=len(rows) or 1
    return [(cat,cnt,round(cnt/n*100)) for cat in core.CATS for cnt in [sum(r['category']==cat for r in rows)]]

@app.route('/')
def decide():
    if request.args.get('mall_id') and request.args.get('hmac'):  # 카페24 App URL이 첫 화면이면 앱 실행으로
        return redirect(url_for('c24.launch')+'?'+request.query_string.decode())
    if not me():return render_template('b_intro.html',app_links=APP_LINKS)  # 로그인 전: 서비스 소개
    if session.get('c24_launch'):return redirect(url_for('c24.page'))  # 카페24에서 열고 가입·로그인한 뒤 이어서
    with conn() as db:
        rows=my_cases(db,me());n_auto=db.execute('SELECT COUNT(*) FROM rules WHERE company_id=? AND auto=1',(me()['id'],)).fetchone()[0]
        warn=insights.alerts(db,me());news=db.execute('SELECT * FROM news ORDER BY id DESC LIMIT 3').fetchall();comps=core.comp_rules(db,me()['id'])
    pend=[r for r in rows if is_pending(r)]
    counts={'comp':sum(core.comp_pending(r,comps) for r in rows),'all':len(rows),'open':sum(map(is_open,rows)),'late':sum(map(core.overdue,rows)),'auto':n_auto,'ret':sum(r['ret_status']=='sent' for r in rows)}
    today=core.now().date().isoformat();counts['today']=sum(r['created'][:10]==today for r in rows)
    with conn() as db:ocnt=orders_mod.counts(db,me()['id'])
    h=core.now().hour;hello='좋은 아침이에요' if h<11 else '좋은 오후예요' if h<18 else '오늘도 수고 많으셨어요'
    return render_template('b_decide.html',pend=pend,recent=rows[:6],k=kpis(rows),counts=counts,cats=by_cat(rows),warn=warn,news=news,link=core.site_url('me','/to/%d'%me()['id']),
        hello=hello,brief=briefing(rows,counts,ocnt),tab='home')

def briefing(rows,counts,ocnt):
    """홈의 '소보루 브리핑': 실제 요청·주문 숫자로 사장님이 먼저 볼 것을 몇 줄로 정리."""
    week=(core.now().date()-datetime.timedelta(days=6)).isoformat();r7=[r for r in rows if r['created'][:10]>=week]
    out=[]
    if r7:
        top,n=max(((cat,sum(r['category']==cat for r in r7)) for cat in core.CATS),key=lambda x:x[1])
        out.append(f"최근 7일 요청 {len(r7)}건 중 '{top}' 요청이 {n}건으로 가장 많았어요." if n>=2 else f'최근 7일 요청이 {len(r7)}건 들어왔어요.')
        a=sum(r['decision']=='auto' for r in r7)
        if a:out.append(f'정해 둔 자동 처리로 {a}건은 바로 답했어요.')
    p=sum(map(is_pending,rows))
    out.append(f'사장님 승인이 필요한 요청이 {p}건 있어요.' if p else '승인할 요청은 모두 처리했어요.')
    if counts['late']:out.append(f"답변 기한이 지난 요청이 {counts['late']}건 있어요. 먼저 봐 주세요.")
    if counts['ret']:out.append(f"고객이 보낸 반품 상품 {counts['ret']}건이 오는 중이에요.")
    if ocnt.get('todo'):out.append(f"아직 보내지 않은 주문이 {ocnt['todo']}건 있어요.")
    if not rows:out=['아직 들어온 요청이 없어요. 아래 고객센터 링크를 고객에게 알려 주세요.']
    return out

@app.route('/approvals')
@login_required
def approvals():
    """승인할 일: 사장님 판단이 필요한 요청만 모아서 바로 승인."""
    with conn() as db:rows=my_cases(db,me());comps=core.comp_rules(db,me()['id'])
    pend=[r for r in rows if is_pending(r)]
    return render_template('b_approvals.html',pend=pend,n_comp=sum(core.comp_pending(r,comps) for r in rows),tab='approve')

RET_CATS=('교환','반품·환불','제품 불량')
RET_STAGES=[('new','새로 접수'),('back','회수 중'),('next','다음 처리 대기'),('done','처리 완료')]
def ret_stage(c):
    """교환·반품 요청이 지금 어느 단계인지: 접수 → 회수 중 → (재출고·환불) 대기 → 완료."""
    if c['out_tracking'] or c['refund_status']=='done':return 'done'
    if c['ret_status']=='received':return 'done' if c['status'] in core.FINAL and c['refund_status']!='requested' else 'next'
    if c['ret_status'] in ('guided','sent'):return 'back'
    if c['refund_status']=='requested':return 'next'
    return 'done' if c['status'] in core.FINAL else 'new'

@app.route('/returns')
@login_required
def returns():
    with conn() as db:rows=[r for r in my_cases(db,me()) if r['category'] in RET_CATS or r['refund_status']=='requested']
    keys=dict(RET_STAGES);st=request.args.get('s','');st=st if st in keys else ''
    staged=[(r,ret_stage(r)) for r in rows];cnt={k:sum(x==k for _,x in staged) for k in keys}
    return render_template('b_returns.html',rows=[(r,x) for r,x in staged if not st or x==st],cnt=cnt,stages=RET_STAGES,st=st,tab='returns')

@app.route('/connect')
@login_required
def connect():
    """서비스 연동: 지금 실제로 이어진 것과 준비 중인 것을 그대로 보여 준다."""
    with conn() as db:
        n=db.execute('SELECT channel,COUNT(*) n FROM orders WHERE company_id=? GROUP BY channel',(me()['id'],)).fetchall();by={r['channel']:r['n'] for r in n}
        lk=shops.links(db,me()['id']);c24=cafe24.link(db,me()['id']);ml=mailin.link(db,me()['id']);ig=instagram.link(db,me()['id'])
    track_on=bool(core.secret('SWEETTRACKER_T_KEY'))
    rows=[]
    for key,spec in shops.SHOPS.items():
        l=lk.get(key)
        if l:desc,state=(f"문의 {l['n_inq']}건 · 주문 {l['n_ord']}건 가져옴"+(f" · {core.fmt(l['synced'])}" if l['synced'] else ' · 곧 가져와요'),'on') if l['status']=='ok' else (l['note'],'err')
        else:desc,state=(f"주문 {by[spec['channel']]}건 · 엑셀로 올리는 중. 내 키를 넣으면 자동으로 가져와요" if by.get(spec['channel']) else '내 키를 넣으면 문의와 주문을 자동으로 가져와요'),'link'
        rows.append(dict(group='판매처',name=spec['full'],desc=desc,state=state,href=url_for('connect_shop',shop=key)))
    if c24:rows.append(dict(group='판매처',name='카페24',desc=(f"문의 {c24['n_inq']}건 · 주문 {c24['n_ord']}건 가져옴"+(f" · {core.fmt(c24['synced'])}" if c24['synced'] else '')) if c24['status']=='ok' else c24['note'],state='on' if c24['status']=='ok' else 'err',href=url_for('c24.page')))
    else:rows.append(dict(group='판매처',name='카페24',desc='카페24 로그인으로 연결하면 주문과 게시판 문의를 자동으로 가져와요' if cafe24.ready() else '소보루가 카페24 앱 등록을 마치면 열려요. 그동안은 주문 엑셀로 써 주세요',state='link' if cafe24.ready() else 'wait',href=url_for('c24.page')))
    rows+=[dict(group='판매처',name=nm,desc=f'주문 {by[ch]}건 · 주문 엑셀(CSV)로 올리는 중' if by.get(ch) else '주문 엑셀(CSV)을 올리면 바로 쓸 수 있어요',
               state='csv' if by.get(ch) else 'ready',href=url_for('orders_page')) for nm,ch in (('자사몰','자사몰'),('오픈마켓','오픈마켓'))]
    if real()['api_enabled']:rows.append(dict(group='개발',name='외부 API·웹훅 (시범)',desc='우리 회사 프로그램에서 문의를 읽고 답하고, 새 문의를 웹훅으로 받아요',state='link',href=url_for('api.manage')))
    rows+=[dict(group='택배',name='택배 배송 조회',desc='송장번호로 고객·사장님 화면에서 위치를 바로 보여 줘요' if track_on else '소보루가 연결을 준비하고 있어요',state='on' if track_on else 'soon',href=''),
           dict(group='알림',name='이메일 알림',desc='새 요청과 답변을 이메일로 알려 드려요' if core.mail_ready() else '소보루가 연결을 준비하고 있어요',state='on' if core.mail_ready() else 'soon',href=url_for('settings')),
           dict(group='알림',name='카카오 알림톡',desc='고객에게 진행 상황을 카카오톡으로 보내요',state='soon',href=''),
           dict(group='상담',name='이메일 문의',desc=((f"{ml['address']} · 문의 {ml['n_inq']}건 가져옴"+(f" · {core.fmt(ml['synced'])}" if ml['synced'] else ' · 곧 가져와요')) if ml['status']=='ok' else ml['note']) if ml else '회사 메일함을 이으면 메일 문의가 요청으로 들어와요',
                state=('on' if ml['status']=='ok' else 'err') if ml else 'link',href=url_for('connect_email')),
           dict(group='상담',name='인스타그램 DM',desc=((f"@{ig['username']} · DM {ig['n_inq']}건 받음") if ig['status']=='ok' else ig['note']) if ig else ('인스타그램으로 로그인하면 DM이 요청으로 들어와요' if instagram.ready() else '소보루가 메타 앱 준비를 마치면 열려요'),
                state=('on' if ig['status']=='ok' else 'err') if ig else ('link' if instagram.ready() else 'wait'),href=url_for('ig.page')),
           dict(group='상담',name='쇼핑몰 문의 버튼',desc=(f"{real()['widget_host']}에 붙어 있어요 · {core.fmt(real()['widget_seen'])} 확인" if real()['widget_seen'] else '쇼핑몰에 한 줄만 붙이면 문의하기 버튼이 생겨요'),state='on' if real()['widget_seen'] else 'link',href=url_for('connect_widget')),
           dict(group='상담',name='AI 상담',desc='고객 채팅에 AI가 먼저 답해요' if chatbot.ready() else '소보루가 연결을 준비하고 있어요',state='on' if chatbot.ready() else 'soon',href=url_for('rules')+'#ai' if chatbot.ready() else '')]
    return render_template('b_connect.html',rows=rows,tab='connect')

@app.route('/connect/widget')
@login_required
def connect_widget():
    """쇼핑몰 문의 버튼(위젯) 설치 안내: 붙일 한 줄, 카페24 붙이는 곳, 붙었는지 확인."""
    co=real()
    return render_template('b_widget.html',rc=co,widget=core.site_url('me','/widget.js?c=%d'%co['id']),link=core.site_url('me','/to/%d'%co['id']),tab='connect')

@app.route('/connect/email',methods=['GET','POST'])
@login_required
def connect_email():
    """이메일 문의 받기: 회사 메일함 주소와 앱 비밀번호를 넣는다. 연결 확인 -> 저장, 지금 가져오기, 연결 끊기."""
    co=me()
    if request.method=='POST':
        act=request.form.get('act','save')
        if act!='delete' and not co['member']:flash('메일함 연결은 실제 고객 정보를 가져오는 일이라 회사 인증이 끝난 뒤에 할 수 있어요.','error')
        elif act=='delete':
            with conn() as db:mailin.remove(db,co)
            flash('연결을 끊었어요. 저장한 비밀번호도 지웠어요.','ok')
        elif act=='sync':
            try:flash(f'새 메일 문의 {mailin.sync(co)}건을 가져왔어요','ok')
            except mailin.MailError as e:flash(str(e),'error')
        elif core.throttled('mailin',limit=10,minutes=10):flash('잠시 후 다시 해 주세요','error')
        else:
            with conn() as db:msg,level=mailin.save(db,co,request.form)
            flash(msg,level)
            if level=='ok':
                try:mailin.sync(co)
                except mailin.MailError:pass  # 연결 상태에 이유가 남는다
        return redirect(url_for('connect_email'))
    with conn() as db:lk=mailin.link(db,co['id'])
    return render_template('b_mail.html',lk=lk,presets=mailin.PRESETS,tab='connect')

@app.route('/connect/<shop>',methods=['GET','POST'])
@login_required
def connect_shop(shop):
    """판매처 연결: 사장님이 판매처에서 발급한 키를 넣는다. 연결 확인 -> 저장, 지금 가져오기, 연결 끊기."""
    if shop not in shops.SHOPS:abort(404)
    co=me()
    if request.method=='POST' and not co['member'] and request.form.get('act','save')!='delete':
        flash('판매처 연결은 실제 고객 정보를 가져오는 일이라 회사 인증이 끝난 뒤에 할 수 있어요.','error');return redirect(url_for('connect_shop',shop=shop))
    if request.method=='POST':
        act=request.form.get('act','save')
        if act=='delete':
            with conn() as db:shops.remove(db,co,shop)
            flash('연결을 끊었어요. 저장한 키도 지웠어요.','ok')
        elif act=='sync':
            try:n_inq,n_ord=shops.sync(co,shop);flash(f'새 문의 {n_inq}건, 주문 {n_ord}건을 가져왔어요','ok')
            except shops.ShopError as e:flash(str(e),'error')
        else:
            if core.throttled('shop',limit=10,minutes=10):flash('잠시 후 다시 해 주세요','error')
            else:
                with conn() as db:msg,level=shops.save(db,co,shop,request.form)
                flash(msg,level)
                if level=='ok':
                    try:shops.sync(co,shop)
                    except shops.ShopError:pass  # 연결 상태에 이유가 남는다
        return redirect(url_for('connect_shop',shop=shop))
    with conn() as db:lk=shops.link(db,co['id'],shop)
    return render_template('b_shop.html',shop=shop,spec=shops.SHOPS[shop],lk=lk,ip=shops.server_ip(),tab='connect')

@app.route('/approve_many',methods=['POST'])
@login_required
def approve_many():
    """같은 유형의 승인 대기 요청을 한 번에 승인 (홈의 'n건 모두 승인')."""
    cat=request.form.get('category')
    if cat not in core.CATS:abort(400)
    n=0
    with conn() as db:
        for c in [r for r in my_cases(db,me()) if is_pending(r) and r['category']==cat]:
            done=core.run_playbook(db,c,'approved')
            if done is None:continue
            if done:notify_consumer(c,f'[{core.CNAME}] 기업 답변이 도착했어요',f"{c['company_name']}이(가) 답변했어요.")
            n+=1
    if n:flash(f'{cat} {n}건을 승인했습니다','ok')
    else:flash(f'{cat}은(는) 미리 정한 답변이 없어요. 요청을 열어 답변을 직접 적어 주세요.','error')
    return redirect(url_for('decide'))

@app.route('/pending')
def pending():return redirect(url_for('decide'))

@app.route('/all')
@login_required
def all_cases():
    fil,q,tg,sort,rows,tagmap,names=inbox_rows()
    with conn() as db:all_tags=inbox.tags(db,me()['id']);people=team.people(db,me())
    groups=g.inbox_groups
    return render_template('b_all.html',sla=g.sla,groups=groups,fil=fil,rows=rows,q=q,tg=tg,sort=sort,tab='all',names=names,tagmap=tagmap,all_tags=all_tags,people=people,PRIO=inbox.PRIO)
def inbox_rows():
    """요청 목록 (화면·CSV 같이 씀): 탭(f)·검색(q)·태그(t)·정렬(s=prio)."""
    fil=request.args.get('f','all');q=clean(request.args.get('q'),40);tg=request.args.get('t','');sort=request.args.get('s','')
    with conn() as db:
        rows=my_cases(db,me());comps=core.comp_rules(db,me()['id'])
        tagmap=inbox.tags_by_case(db,me()['id']);names=dict(team.people(db,me()))
    if q:rows=[r for r in rows if q.lower() in (r['title']+' '+r['no']+' '+(r['name'] or '')+' '+r['body']).lower()]
    if tg.isdigit():rows=[r for r in rows if any(t['id']==int(tg) for t in tagmap.get(r['id'],[]))]
    nowi=core.iso();live=lambda r:not (r['snooze_until'] and r['snooze_until']>nowi)  # 미뤄 둔 요청은 때가 될 때까지 할 일 목록에서 뺀다
    groups={'all':rows,'open':[r for r in rows if is_open(r) and live(r)],'done':[r for r in rows if r['status'] in ('answered','resolved','closed','withdrawn')],
            'bad':[r for r in rows if r['status']=='unresolved' or core.overdue(r)],
            'ret':[r for r in rows if r['ret_status'] in ('guided','sent') or r['refund_status']=='requested'],
            'comp':[r for r in rows if core.comp_pending(r,comps)],
            'mine':[r for r in rows if r['assignee']==who()['key'] and r['status'] not in core.FINAL and live(r)],
            'none':[r for r in rows if not r['assignee'] and r['status'] not in core.FINAL and live(r)],
            'snz':[r for r in rows if not live(r) and r['status'] not in core.FINAL]}
    if fil not in groups:fil='all'
    out=groups[fil]
    if sort=='prio':out=sorted(out,key=lambda r:(inbox.PRIO_ORDER.get(r['priority'] or 'normal',2),-r['id']))
    g.inbox_groups=groups
    with conn() as db:g.sla=workflow.states(db,me(),out);g.live_on=livechat.online_cases(db,[r['id'] for r in out if r['live']])
    return fil,q,tg,sort,out,tagmap,names

@app.route('/all.csv')
@login_required
def all_csv():
    """지금 보는 요청 목록을 엑셀에서 여는 표(CSV)로. 연락처·이메일·계좌는 넣지 않는다."""
    if not team.can(who(),'manage'):abort(403)
    fil,q,tg,sort,rows,tagmap,names=inbox_rows()
    data=inbox.csv_bytes(rows,tagmap,names,lambda r:core.status_label(r['status']))
    return send_file(io.BytesIO(data),mimetype='text/csv',as_attachment=True,download_name=f"requests-{core.now():%Y%m%d}.csv")

@app.route('/all/bulk',methods=['POST'])
@login_required
def all_bulk():
    """목록에서 고른 요청들에 태그·담당자·우선순위·미루기를 한 번에."""
    ids={int(x) for x in request.form.getlist('ids') if x.isdigit()}
    back=request.form.get('back') or url_for('all_cases')
    if not back.startswith('/'):back=url_for('all_cases')
    if not ids:flash('먼저 요청을 골라 주세요','error');return redirect(back)
    with conn() as db:
        rows=[r for r in my_cases(db,me()) if r['id'] in ids]
        n=inbox.bulk(db,me(),rows,request.form,team.people(db,me()))
    flash(f'{n}건을 바꿨어요' if n else '바뀐 요청이 없어요',  'ok' if n else 'error')
    return redirect(back)

@app.route('/macros',methods=['GET','POST'])
@login_required
def macros():
    """답변 템플릿과 태그 관리. 템플릿은 요청 화면의 답변 쓰기에서 골라 쓴다."""
    co=me()
    if request.method=='POST':
        act=request.form.get('act');mid=request.form.get('id','')
        with conn() as db:
            if act=='save':msg,level=inbox.save_macro(db,co['id'],request.form,int(mid) if mid.isdigit() else None);flash(msg,level)
            elif act=='delete' and mid.isdigit():inbox.delete_macro(db,co['id'],int(mid));flash('템플릿을 지웠어요','ok')
            elif act=='tag_add':
                flash('태그를 만들었어요' if inbox.tag_named(db,co['id'],request.form.get('name','')) else f'태그 이름을 적어 주세요 (최대 {inbox.MAX_TAGS}개)','ok' if request.form.get('name','').strip() else 'error')
            elif act=='tag_delete' and mid.isdigit():inbox.delete_tag(db,co['id'],int(mid));flash('태그를 지웠어요. 붙어 있던 요청에서도 떨어졌어요.','ok')
        return redirect(url_for('macros'))
    with conn() as db:ms=inbox.macros(db,co['id']);ts=inbox.tags(db,co['id']);counts=dict(db.execute('SELECT tag_id,COUNT(*) FROM case_tags ct JOIN tags t ON t.id=ct.tag_id WHERE t.company_id=? GROUP BY tag_id',(co['id'],)).fetchall())
    edit=request.args.get('edit','')
    return render_template('b_macros.html',ms=ms,ts=ts,counts=counts,edit=int(edit) if edit.isdigit() else (0 if request.args.get('new') else None),VARS=inbox.VARS,tab='macros')

@app.route('/automations',methods=['GET','POST'])
@login_required
def automations_page():
    """자동화 규칙: 새 요청이 들어오면 조건에 맞춰 태그·우선순위·담당자·메모를 정한다."""
    import automations as au
    co=me();rid=request.form.get('id','') or request.args.get('edit','')
    rid=int(rid) if str(rid).isdigit() else None
    with conn() as db:people=team.people(db,co)
    if request.method=='POST':
        act=request.form.get('act')
        with conn() as db:
            if act=='save':
                r,err=au.parse(request.form,dict(people))
                if err:
                    flash(err,'error');rs=au.rules(db,co['id'])
                    return render_template('b_auto.html',rs=rs,edit=rid or 0,cur=r,people=people,AU=au,PRIO=inbox.PRIO,CATS=core.CATS,counts={},tab='automations')
                new=au.save(db,co['id'],r,rid if rid and au.get(db,co['id'],rid) else None)
                flash('규칙을 저장했어요. 이제 들어오는 요청부터 적용돼요.' if new else f'규칙은 {au.MAX_RULES}개까지 만들 수 있어요','ok' if new else 'error')
            elif rid and act=='toggle':au.toggle(db,co['id'],rid)
            elif rid and act=='delete':au.delete(db,co['id'],rid);flash('규칙을 지웠어요','ok')
            elif rid and act in ('up','down'):au.move(db,co['id'],rid,act=='up')
        return redirect(url_for('automations_page'))
    with conn() as db:
        rs=au.rules(db,co['id']);counts={r['id']:au.preview(db,co,r) for r in rs}
    edit=rid if rid else (0 if request.args.get('new') else None)
    cur=next((r for r in rs if r['id']==edit),None) if edit else None
    if edit==0 and request.args.get('ex') in au.EXAMPLES:cur=au.EXAMPLES[request.args['ex']]
    return render_template('b_auto.html',rs=rs,edit=edit,cur=cur,people=people,AU=au,PRIO=inbox.PRIO,CATS=core.CATS,counts=counts,tab='automations')

@app.route('/stats')
@login_required
def stats():
    with conn() as db:s=stats_data(db,me())
    return render_template('b_stats.html',top=max([c for _,c in s['weeks']] or [0]) or 1,tab='stats',**s)
def stats_data(db,co):
    rows=my_cases(db,co);cmp=insights.compare(db,co);reply_h=insights.summarize(db,rows)['reply_h']
    n=len(rows) or 1
    how=[(DEC,cnt,round(cnt/n*100)) for key,DEC in (('auto','자동 처리'),('approved','원클릭 승인'),('direct','직접 답변'),('hold','보류'),('info','자료 요청'),('pending','승인 대기')) for cnt in [sum(r['decision']==key for r in rows)]]
    today=core.now().date();weeks=[]
    for w in range(7,-1,-1):
        end=today-datetime.timedelta(days=7*w);start=end-datetime.timedelta(days=6)
        weeks.append((f'{start.month}.{start.day}',sum(start.isoformat()<=r['created'][:10]<=end.isoformat() for r in rows)))
    return dict(k=kpis(rows),cats=by_cat(rows),how=how,weeks=weeks,cmp=cmp,reply_h=reply_h,sla=workflow.report(db,co,rows),conv=insights.conversion(db,co))

notify_consumer=core.notify_consumer
SEND_VIA={mailin.CHANNEL:'메일로',instagram.CHANNEL:'인스타그램 DM으로'}  # 사람이 눌러야 그 채널로 답이 나가는 곳

def can_ship_track(db,c):
    """배송 조회 요청에 송장을 넣어 답할 수 있는지: 아직 안 넣었고 끝나지 않은 배송 조회 요청."""
    return c['category']=='배송 조회' and c['status'] not in core.FINAL and not db.execute("SELECT 1 FROM tracks WHERE fid=?",(tracking_mod.fid(c['id'],'ship'),)).fetchone()
def case_act(db,c,form):
    """기업이 요청에 하는 일(승인·보류·자료 요청·답변·회수 확인·발송·환불 완료). 웹과 앱이 같이 쓴다. -> (안내 문구, ok|error|bad)"""
    act=form.get('act');open_=c['status'] not in core.FINAL
    if act=='ret_received' and c['ret_status'] in ('guided','sent'):
        db.execute("UPDATE cases SET ret_status='received' WHERE id=?",(c['id'],))
        core.add_event(db,c['id'],'co','반품 상품 회수를 확인했어요')
        if c['category']=='반품·환불':orders_mod.sync_case(db,c,'returned')
        notify_consumer(c,f'[{core.CNAME}] 보내신 상품이 도착했어요',f"{c['company_name']}이(가) 반품 상품 회수를 확인했어요.")
        return '회수 확인을 기록했습니다','ok'
    if act=='out_ship' and c['category'] in ('교환','제품 불량') and c['ret_status']=='received' and not c['out_tracking']:
        courier=form.get('courier','');tracking=digits(form.get('tracking',''))
        if (courier not in core.COURIERS and courier!='기타') or not 8<=len(tracking)<=20:return '택배사와 송장번호를 확인해 주세요','error'
        db.execute('UPDATE cases SET out_courier=?,out_tracking=? WHERE id=?',(courier,tracking,c['id']))
        tracking_on=tracking_mod.register(db,c['id'],'out',courier,tracking)
        core.add_event(db,c['id'],'co',f'새 상품을 보냈어요: {courier} {tracking}');orders_mod.sync_case(db,c,'exchanged')
        notify_consumer(c,f'[{core.CNAME}] 새 상품을 보냈어요',f"{c['company_name']}이(가) 교환 상품을 보냈어요.\n{courier} 송장번호 {tracking}"+('\n배송 상태가 바뀌면 알려 드릴게요.' if tracking_on else ''))
        return '고객에게 송장번호를 알렸습니다','ok'
    if act=='refund_done' and core.refund_case(c) and c['refund_status']!='done':
        # 환불이 끝나면 계좌 정보는 더 둘 이유가 없으니 바로 지운다
        db.execute("UPDATE cases SET refund_status='done',refund_bank='',refund_account='',refund_holder='' WHERE id=?",(c['id'],))
        core.add_event(db,c['id'],'co','환불을 완료했어요');orders_mod.sync_case(db,c,'refunded')
        notify_consumer(c,f'[{core.CNAME}] 환불이 완료됐어요',f"{c['company_name']}이(가) 환불을 완료했어요. 입금 내역을 확인해 주세요.")
        return '환불 완료를 기록했습니다','ok'
    if act=='comp' and core.comp_open(c):
        what=clean(form.get('comp'),100)
        if not what:return '보상 내용을 적어 주세요','error'
        db.execute("UPDATE cases SET comp=?,comp_status='given' WHERE id=?",(what,c['id']))
        core.add_event(db,c['id'],'co','보상: '+what,f'불편을 드려 죄송합니다. 사과의 뜻으로 {what}을(를) 드릴게요.')
        notify_consumer(c,f'[{core.CNAME}] 보상 안내가 도착했어요',f"{c['company_name']}: {what}")
        return '보상을 승인하고 고객에게 알렸습니다','ok'
    if act=='comp_skip' and core.comp_open(c):
        db.execute("UPDATE cases SET comp_status='skipped' WHERE id=?",(c['id'],))
        core.add_event(db,c['id'],'sys','보상 없이 처리하기로 했어요');return '보상 없이 처리합니다','ok'
    if not open_:return '이미 끝난 요청이에요','bad'
    if act=='ship_track' and can_ship_track(db,c):
        courier=form.get('courier','');tracking=digits(form.get('tracking',''))
        if (courier not in core.COURIERS and courier!='기타') or not 8<=len(tracking)<=20:return '택배사와 송장번호를 확인해 주세요','error'
        on=tracking_mod.register(db,c['id'],'ship',courier,tracking)
        link=core.COURIERS.get(courier,'')
        msg=f"주문하신 상품은 {courier} 송장번호 {tracking}(으)로 보냈어요."+(' 배송 상태가 바뀌면 이 화면과 알림으로 바로 알려 드릴게요.' if on else (f' 택배사 홈페이지({link})에서 지금 위치를 확인하실 수 있어요.' if link else ''))
        db.execute("UPDATE cases SET status='answered',decision=CASE decision WHEN 'pending' THEN 'direct' WHEN '' THEN 'direct' ELSE decision END WHERE id=?",(c['id'],))
        core.add_event(db,c['id'],'co','송장번호를 알렸어요',msg);orders_mod.sync_case(db,c,'shipped',courier,tracking)
        notify_consumer(c,f'[{core.CNAME}] 송장번호를 알려 드려요',f"{c['company_name']}: {courier} 송장번호 {tracking}")
        return '고객에게 송장번호를 알렸습니다','ok'
    if act=='approve' and c['decision'] not in ('approved','auto'):
        done=core.run_playbook(db,c,'approved')
        if done is None:return '이 유형은 미리 정한 답변이 없어요. 아래에서 답변을 직접 적어 보내 주세요.','error'
        if done:notify_consumer(c,f'[{core.CNAME}] 기업 답변이 도착했어요',f"{c['company_name']}이(가) 답변했어요.")
        return '승인했습니다','ok'
    if act=='hold':
        db.execute("UPDATE cases SET decision='hold',status=CASE status WHEN 'forwarded' THEN 'seen' ELSE status END WHERE id=?",(c['id'],))
        core.add_event(db,c['id'],'sys','보류했어요');return '보류했습니다','ok'
    if act=='ask':
        ask=clean(form.get('ask'),300) or ('불량 부분 사진과 주문번호를 보내 주세요.' if c['category']=='제품 불량' else '주문번호와 확인할 수 있는 사진이나 캡처를 보내 주세요.')
        db.execute("UPDATE cases SET decision='info',status='info',info_ask=? WHERE id=?",(ask,c['id']))
        core.add_event(db,c['id'],'co','자료 요청: '+ask);notify_consumer(c,f'[{core.CNAME}] 기업이 자료를 요청했어요',ask);return '자료를 요청했습니다','ok'
    if act=='reply':
        msg=clean(form.get('msg'),3000)
        if not msg:return '답변 내용을 적어 주세요','error'
        db.execute("UPDATE cases SET status='answered',decision=CASE decision WHEN 'pending' THEN 'direct' WHEN '' THEN 'direct' ELSE decision END WHERE id=?",(c['id'],))
        core.add_event(db,c['id'],'co','답변을 보냈어요',msg)
        if not (c['live'] and livechat.online(db,c['id'],'me')):notify_consumer(c,f'[{core.CNAME}] 기업 답변이 도착했어요',f"{c['company_name']}이(가) 답변했어요.")  # 채팅방을 보고 있으면 메일은 보내지 않는다
        return '보냈습니다','ok'
    return '','ok'

@app.route('/case/<int:case_id>',methods=['GET','POST'])
@login_required
def case(case_id):
    with conn() as db:
        c=my_case(db,case_id)
        if request.method=='POST':
            act=request.form.get('act')
            if act=='note':
                if team.add_note(db,me(),c,who(),request.form.get('note')):flash('메모를 남겼어요. 고객에게는 보이지 않아요.','ok')
                else:flash('메모 내용을 적어 주세요','error')
                return redirect(url_for('case',case_id=case_id)+'#notes')
            if act=='post_shop':
                last=next((e for e in reversed(core.events(db,c['id'])) if e['kind']=='co' and e['reply']),None)
                if not last:flash('먼저 답변을 보내 주세요','error')
                elif core.throttled('post_shop',limit=20,minutes=10):flash('잠시 후 다시 해 주세요','error')
                else:
                    e=shops.post_reply(db,me(),c,last['reply'])
                    via=SEND_VIA.get(c['channel'])
                    if e:core.add_event(db,c['id'],'sys',(f'{via} 보내지 못했어요: ' if via else f"{c['channel']}에 답변을 올리지 못했어요: ")+e);flash(e,'error')
                    else:
                        done=f'{via} 답변을 보냈어요' if via else f"{c['channel']}에 답변을 올렸어요"
                        core.add_event(db,c['id'],'sys',done);flash(done,'ok')
                return redirect(url_for('case',case_id=case_id))
            if act in ('tag_add','tag_del','prio','snooze','merge'):
                flash(*case_inbox(db,c,act,request.form));return redirect(url_for('case',case_id=case_id))
            if act=='assign':
                name=team.assign(db,me(),c,request.form.get('assignee',''))
                if name is not None:flash(f'담당자를 {name}(으)로 정했어요' if name else '담당자를 비웠어요','ok')
                return redirect(url_for('case',case_id=case_id))
            if act in DECIDE_ACTS and not team.can(who(),'decide'):
                flash('승인·보상·환불 완료는 대표나 관리자만 할 수 있어요. 메모로 부탁해 주세요.','error');return redirect(url_for('case',case_id=case_id))
            msg,level=case_act(db,c,request.form)
            if level=='bad':abort(400)
            if level=='ok' and act=='reply' and request.form.get('macro','').isdigit():inbox.used_macro(db,me(),c,int(request.form['macro']))
            if msg:flash(msg,level)
            if level=='ok' and act in ('reply','approve','ask','ship_track') and not in_demo() and not c['title'].startswith('[시험 문의]'):funnel.track('first_reply',me()['id'])
            st=onboard.setup_state(real())
            if level=='ok' and st.get('test_case')==c['id'] and st.get('test')!='done':
                onboard.mark(db,real(),'test','done');flash('시험 문의 처리 단계를 마쳤어요.','ok')
            return redirect(url_for('case',case_id=case_id))
        if c['status']=='forwarded':
            db.execute("UPDATE cases SET status='seen' WHERE id=?",(c['id'],));core.add_event(db,c['id'],'sys','기업이 확인했어요')
            c=my_case(db,case_id)
        ev=core.events(db,c['id']);fl=core.case_files(db,c['id']);rule=core.rule_for(db,me()['id'],c['category'])
        tracks=[tracking_mod.as_dict(t) for t in tracking_mod.tracks(db,c['id'])];ship_track=can_ship_track(db,c)
        notes=team.notes(db,c['id']);people=team.people(db,me());assignee=team.assignee_name(db,me(),c['assignee'])
        from_shop=db.execute('SELECT shop FROM shop_seen WHERE company_id=? AND case_id=?',(me()['id'],c['id'])).fetchone()
        posted=any(e['kind']=='sys' and e['text'].endswith(('에 답변을 올렸어요','로 답변을 보냈어요')) for e in ev)
        ctags=inbox.tags_by_case(db,me()['id'],{c['id']}).get(c['id'],[]);all_tags=inbox.tags(db,me()['id']);ms=inbox.macros(db,me()['id'])
        sla=workflow.state(me(),c,workflow.first_replies(db,me()['id']).get(c['id']));
        profile=inbox.customer(db,me(),c);merged=db.execute('SELECT id,no FROM cases WHERE id=?',(c['merged_into'],)).fetchone() if c['merged_into'] else None
    comp_show=core.comp_open(c) and (rule['comp'] or c['category'] in core.COMP_CATS)
    with conn() as db:order=orders_mod.for_case(db,c);blocked=orders_mod.cancel_blocked(db,c)
    ms=[dict(id=x['id'],name=x['name'],body=inbox.fill(x['body'],c,me(),order)) for x in ms]
    guides=[law.GUIDE_BY_ID[g] for g in law.CAT_GUIDE.get(c['category'],[])]
    return render_template('b_case.html',c=c,ev=ev,files=fl,rule=rule,laws=law.for_case(c),chk=law.check(c),guides=guides,tracks=tracks,ship_track=ship_track,comp_show=comp_show,order=order,notes=notes,people=people,assignee=assignee,blocked=blocked,OSTATUS=orders_mod.STATUS,COMP_EXAMPLES=core.COMP_EXAMPLES,
        last_reply=next((e for e in reversed(ev) if e['kind']=='co' and e['reply']),None),from_shop=from_shop,posted=posted,tab='all',
        ctags=ctags,all_tags=all_tags,sla=sla,macros=ms,profile=profile,merged=merged,PRIO=inbox.PRIO,snoozed=inbox.snoozed(c),fmt_when=inbox.fmt_when,today=core.now().date().isoformat())
@app.route('/case/<int:case_id>/live',methods=['GET','POST'])
@login_required
def case_live(case_id):
    """채팅방(사장님 쪽): GET은 after 다음의 새 말, POST는 답변 보내기."""
    with conn() as db:
        c=my_case(db,case_id)
        if request.method=='POST':
            msg,level=case_act(db,c,{'act':'reply','msg':request.form.get('text','')})
            if level!='ok':return jsonify(error=msg or '보내지 못했어요'),400
            if not in_demo() and not c['title'].startswith('[시험 문의]'):funnel.track('first_reply',me()['id'])
        livechat.ping(db,case_id,'co')
        after=request.values.get('after','0');after=int(after) if after.isdigit() else 0
        c=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        return jsonify(msgs=livechat.since(db,case_id,after),me_online=livechat.online(db,case_id,'me'),open=livechat.is_open(c))

def case_inbox(db,c,act,f):
    """요청 화면 오른쪽 '분류': 태그·우선순위·미루기·합치기. -> (안내, ok|error)"""
    co=me()
    if act=='tag_add':
        t=inbox.add_tag(db,co,c,f.get('tag',''))
        return (f"태그 '{t['name']}'을(를) 붙였어요",'ok') if t else (f'태그 이름을 적어 주세요 (회사당 최대 {inbox.MAX_TAGS}개)','error')
    if act=='tag_del':
        if f.get('tag_id','').isdigit():inbox.remove_tag(db,co,c,int(f['tag_id']))
        return '태그를 뗐어요','ok'
    if act=='prio':
        return (f"우선순위를 {inbox.PRIO[f.get('prio')]}(으)로 바꿨어요",'ok') if inbox.set_priority(db,co,c,f.get('prio','')) else ('바뀐 게 없어요','ok')
    if act=='snooze':
        msg=inbox.snooze(db,co,c,f.get('when',''),f.get('day',''))
        return (msg,'ok') if msg else ('미룰 때를 확인해 주세요 (오늘 이후 90일 안)','error') if msg is None else ('미뤄 둔 요청이 아니에요','ok')
    if act=='merge':return inbox.merge(db,co,c,f.get('target',''))
    return '','ok'

@app.route('/case/<int:case_id>/draft',methods=['POST'])
@login_required
def draft(case_id):
    """답변 초안 (화면의 '초안 만들기' 버튼). 보내지는 않고 글만 돌려준다."""
    if core.throttled('draft',limit=30,minutes=10):return jsonify(error='잠시 후 다시 시도해 주세요'),429
    with conn() as db:
        c=my_case(db,case_id);res=drafting.draft(db,c,me())
        if not in_demo():aistats.log_draft(db,me(),c,res.get('by','template'))
    return jsonify(res)

@app.route('/case/<int:case_id>/record')
@login_required
def record(case_id):
    """처리 기록 한 장: 인쇄하거나 'PDF로 저장'해서 보관·제출용으로 쓴다."""
    with conn() as db:
        c=my_case(db,case_id);ev=core.events(db,c['id']);fl=core.case_files(db,c['id'])
    return render_template('b_record.html',c=c,ev=ev,files=fl,laws=law.for_case(c),chk=law.check(c),printed=core.iso())

@app.route('/new',methods=['GET','POST'])
@login_required
def new_case():
    """전화·쇼핑몰 문의·DM 등 다른 곳으로 받은 요청을 직접 등록해 같은 화면에서 처리한다."""
    if request.method=='POST':
        d,err,cid=new_case_apply(me(),request.form)
        if err:flash(err,'error');return render_template('b_new.html',d=d,tab='all'),400
        flash('등록했습니다','ok');return redirect(url_for('case',case_id=cid))
    return render_template('b_new.html',d={'channel':request.args.get('channel','전화')},tab='all')
def new_case_apply(co,f):
    """직접 등록 검사와 저장(웹·앱 공용). (입력값, 오류 문구, 새 요청 id)."""
    d={k:clean(f.get(k),n) for k,n in (('channel',20),('category',20),('title',BIG),('body',BIG),('want',20),('order_no',40),('product',60),('received_on',10),('name',20),('phone',20),('email',80))}
    err=''
    if d['channel'] not in core.CHANNELS:err='어디로 받은 요청인지 골라 주세요.'
    elif d['category'] not in core.CATS:err='유형을 골라 주세요.'
    elif not d['title']:err='한 줄 요약을 적어 주세요.'
    elif not d['body']:err='내용을 적어 주세요.'
    elif d['want'] not in core.WANTS:err='원하는 해결을 골라 주세요.'
    elif d['received_on'] and law.days_since(d['received_on']) not in range(0,3651):err='상품 받은 날을 확인해 주세요.'
    if err:return d,err,None
    with conn() as db:
        t=core.iso();due=core.iso(core.now()+datetime.timedelta(days=core.REPLY_DAYS))
        cur=db.execute('''INSERT INTO cases(no,company_id,company_name,member,category,title,body,want,order_no,name,phone,email,lookup_hash,consent,status,decision,due,created,updated,product,received_on,channel)
            VALUES(?,?,?,1,?,?,?,?,?,?,?,?,?,1,'seen','pending',?,?,?,?,?,?)''',(core.new_case_no(db),co['id'],co['name'],d['category'],d['title'],d['body'],d['want'],d['order_no'],
            d['name'],digits(d['phone']),d['email'],generate_password_hash(secrets.token_hex(16)),due,t,t,d['product'],d['received_on'],d['channel']))
        core.add_event(db,cur.lastrowid,'sys',f"{d['channel']}(으)로 받은 요청을 직접 등록했어요")
        import automations;automations.run(db,co,db.execute('SELECT * FROM cases WHERE id=?',(cur.lastrowid,)).fetchone())  # 직접 등록한 요청에도 자동화 규칙
    return d,'',cur.lastrowid

@app.route('/guide')
@login_required
def guide():
    return render_template('b_guide.html',guide=law.GUIDE,cite=law.cite,sources=law.sources(),kca=law.KCA_STANDARD,table=law.BASIC_DEC_TABLE,tab='guide')

@app.route('/report')
@login_required
def report():
    ym=request.args.get('ym','');today=datetime.date.today()
    months=[]
    y,m=today.year,today.month
    for _ in range(12):months.append((y,m));y,m=(y,m-1) if m>1 else (y-1,12)
    try:y,m=map(int,ym.split('-'));assert (y,m) in months
    except Exception:y,m=insights.prev_month(today)
    with conn() as db:s=insights.monthly(db,me(),y,m)
    return render_template('b_report.html',s=s,months=months,sel=(y,m),tab='stats')

@app.route('/news')
@login_required
def news():
    with conn() as db:rows=db.execute('SELECT * FROM news ORDER BY id DESC LIMIT 100').fetchall()
    return render_template('b_news.html',rows=rows,tab='home')

@app.route('/case/<int:case_id>/file/<int:file_id>')
@login_required
def case_file(case_id,file_id):
    with conn() as db:
        c=my_case(db,case_id);f=db.execute('SELECT * FROM files WHERE id=? AND case_id=?',(file_id,c['id'])).fetchone()
    if not f:abort(404)
    return send_file(core.UPLOAD/f['stored'],download_name=f['original'])

@app.route('/rules',methods=['GET','POST'])
@login_required
def rules():
    co=me()
    with conn() as db:
        if request.method=='POST':
            if not save_rule(db,co,request.form):abort(400)
            flash('저장했습니다','ok');return redirect(url_for('rules')+('#'+request.form.get('anchor','') if request.form.get('anchor') else ''))
        rs={cat:core.rule_for(db,co['id'],cat) for cat in core.CATS}
        since=core.now().strftime('%Y-%m-01')
        chat={o:db.execute('SELECT COUNT(*) FROM chat_log WHERE company_id=? AND outcome=? AND created>=?',(co['id'],o,since)).fetchone()[0] for o in ('asked','solved','filed')}
        ps=core.products(db,co['id']);priv=product_pdf.private_for(db,co['id']);prof=chatbot.profile(db,co['id'])
    return render_template('b_rules.html',rs=rs,chat=chat,link=core.site_url('me','/to/%d'%co['id']),products=ps,priv=priv,prof=prof,PROFILE=chatbot.PROFILE,PROFILE_HINT=chatbot.HINT,STOCKS=core.STOCKS,ai=chatbot.ready(),tab='rules')

@app.route('/ai-profile',methods=['POST'])
@login_required
def ai_profile():
    """사업자별 AI 상담 설정 (회사 소개, 배송·반품 규정, 상담 범위, 담당자 연결 조건, 응대 지침)."""
    co=me()
    with conn() as db:chatbot.save_profile(db,co['id'],request.form)
    flash('AI 상담 설정을 저장했습니다','ok');return redirect(url_for('rules')+'#ai')

# ---------- 상품정보 (상담창 AI가 가격·재고·사용법 문의에 답할 때 본다) ----------
def save_product(db,co,f):
    """상품 하나 추가·수정·삭제(웹·앱 공용). (안내 문구, 'ok'|'error')."""
    pid=f.get('id');pid=int(pid) if str(pid or '').isdigit() else None
    if pid and not db.execute('SELECT 1 FROM products WHERE id=? AND company_id=?',(pid,co['id'])).fetchone():return '상품을 찾을 수 없습니다','error'
    if f.get('act')=='delete':
        if pid:db.execute('DELETE FROM product_private WHERE product_id=? AND company_id=?',(pid,co['id']));db.execute('DELETE FROM products WHERE id=? AND company_id=?',(pid,co['id']))
        return '삭제했습니다','ok'
    cur=db.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone() if pid else None
    keep=lambda k,n:clean(f.get(k),n) if k in f or not cur else cur[k]  # 고칠 때 보내지 않은 항목은 그대로 둔다
    name,price,info=keep('name',60),keep('price',30),keep('info',2000)
    stock=keep('stock',10);stock=stock if stock in core.STOCKS else ''
    if not name:return '상품 이름을 적어 주세요','error'
    if pid:db.execute('UPDATE products SET name=?,price=?,stock=?,info=?,updated=? WHERE id=?',(name,price,stock,info,core.iso(),pid))
    else:
        if db.execute('SELECT COUNT(*) FROM products WHERE company_id=?',(co['id'],)).fetchone()[0]>=core.MAX_PRODUCTS:return f'상품은 {core.MAX_PRODUCTS}개까지 등록할 수 있어요','error'
        pid=db.execute('INSERT INTO products(company_id,name,price,stock,info,updated) VALUES(?,?,?,?,?,?)',(co['id'],name,price,stock,info,core.iso())).lastrowid
    if 'private' in f:product_pdf.save_private(db,co['id'],pid,f.get('private'))  # 공급가 등 내부 정보는 따로 (상담에 안 쓰임)
    return '저장했습니다','ok'

PRODUCT_COLS={'name':('상품명','상품 이름','상품','이름'),'price':('가격','판매가'),'stock':('재고','판매 상태','상태'),'info':('안내','설명','사용법','상품 안내')}
def import_products(db,co,raw):
    """엑셀에서 'CSV'로 저장한 상품 목록을 읽어 넣는다. 이름이 같으면 고쳐 쓴다. (안내 문구, 'ok'|'error')."""
    for enc in ('utf-8-sig','cp949'):
        try:text=raw.decode(enc);break
        except UnicodeDecodeError:text=None
    if text is None:return '파일을 읽지 못했어요. 엑셀에서 CSV(쉼표로 분리)로 저장해 주세요','error'
    rows=list(csv.reader(io.StringIO(text)))
    if not rows:return '빈 파일이에요','error'
    head=[h.strip() for h in rows[0]]
    idx={k:next((i for i,h in enumerate(head) if h in names),None) for k,names in PRODUCT_COLS.items()}
    if idx['name'] is None:return '첫 줄에 "상품명" 칸이 있어야 해요','error'
    have={r['name']:r['id'] for r in core.products(db,co['id'])};n=0
    for r in rows[1:]:
        get=lambda k:(r[idx[k]].strip() if idx[k] is not None and idx[k]<len(r) else '')
        name=get('name')[:60]
        if not name:continue
        st=get('stock');stock='품절' if '품절' in st else ('있음' if st else '')
        vals=(get('price')[:30],stock,get('info')[:1000],core.iso())
        if name in have:db.execute('UPDATE products SET price=?,stock=?,info=?,updated=? WHERE id=?',vals+(have[name],))
        elif len(have)<core.MAX_PRODUCTS:
            cur=db.execute('INSERT INTO products(company_id,name,price,stock,info,updated) VALUES(?,?,?,?,?,?)',(co['id'],name)+vals);have[name]=cur.lastrowid
        else:break
        n+=1
    return (f'{n}개 상품을 저장했습니다','ok') if n else ('저장할 상품이 없어요','error')

# ---------- 주문 장부 ----------
@app.route('/orders',methods=['GET','POST'])
@login_required
def orders_page():
    co=me();g=request.args.get('g','all');q=clean(request.args.get('q'),40)
    with conn() as db:
        if request.method=='POST':
            if request.form.get('act')=='csv':
                up=request.files.get('file')
                msg,level=orders_mod.import_csv(db,co,up.read(5_000_000),request.form.get('channel','')) if up and up.filename else ('파일을 골라 주세요','error')
                flash(msg,level);return redirect(url_for('orders_page'))
            msg,level,oid=orders_mod.save(db,co,request.form)
            flash(msg,level)
            return redirect(url_for('order_page',oid=oid) if oid else url_for('orders_page',add=1))
        if g not in dict((k,1) for k,_,_ in orders_mod.GROUPS):g='all'
        rows=orders_mod.orders(db,co['id'],g,q);cnt=orders_mod.counts(db,co['id'])
    return render_template('b_orders.html',rows=rows,cnt=cnt,g=g,q=q,GROUPS=orders_mod.GROUPS,OSTATUS=orders_mod.STATUS,OCHANNELS=orders_mod.CHANNELS,tab='orders')

@app.route('/order/<int:oid>',methods=['GET','POST'])
@login_required
def order_page(oid):
    co=me()
    with conn() as db:
        o=orders_mod.order(db,co['id'],oid)
        if not o:abort(404)
        if request.method=='POST':
            if request.form.get('act')=='delete':orders_mod.delete(db,co,oid);flash('주문을 지웠어요','ok');return redirect(url_for('orders_page'))
            if request.form.get('act') in ('c24_cancel','c24_return'):
                if not team.can(who(),'decide'):flash('카페24 취소·반품은 대표나 관리자만 할 수 있어요. 메모로 부탁해 주세요.','error')
                elif in_demo():flash('데모에서는 카페24에 보낼 수 없어요.','error')
                elif core.throttled('c24_claim',limit=20,minutes=10):flash('잠시 후 다시 해 주세요','error')
                else:
                    msg,level=cafe24.claim(db,co,o,'cancel' if request.form['act']=='c24_cancel' else 'return',request.form.get('reason_type',''),request.form.get('reason',''),(who() or {}).get('name',''))
                    flash(msg,level)
                return redirect(url_for('order_page',oid=oid))
            msg,level,_=orders_mod.save(db,co,request.form,oid);flash(msg,level)
            return redirect(url_for('order_page',oid=oid))
        cs=orders_mod.cases_for(db,o)
        c24=None
        if o['src']=='cafe24':
            lk=cafe24.link(db,co['id'])
            c24=dict(ok=bool(lk and lk['status']=='ok'),acts={k:cafe24.action(db,co['id'],o['order_no'],k) for k in ('cancel','return')})
    return render_template('b_order.html',o=o,cs=cs,c24=c24,C24_REASONS=cafe24.REASONS,OSTATUS=orders_mod.STATUS,OCHANNELS=orders_mod.CHANNELS,tab='orders')

@app.route('/hook/trace/<tok>',methods=['POST'])
def hook_trace(tok):
    """스마트택배가 배송 상태가 바뀔 때마다 보내는 알림. 주소의 서명 토큰이 맞을 때만 받는다."""
    d=request.get_json(silent=True)
    if not isinstance(d,dict):d=request.form.to_dict()
    ok=tracking_mod.callback(tok,d)
    return jsonify(code=ok,message='success' if ok else 'fail')

@app.route('/products',methods=['POST'])
@login_required
def products():
    co=me()
    with conn() as db:
        if request.form.get('act')=='csv':
            up=request.files.get('file')
            msg,level=import_products(db,co,up.read(2_000_000)) if up and up.filename else ('파일을 골라 주세요','error')
        else:msg,level=save_product(db,co,request.form)
    flash(msg,level);return redirect(url_for('rules')+'#products')

@app.route('/products/pdf',methods=['POST'])
@login_required
def products_pdf():
    """상품소개서 PDF를 올리면 AI가 상품을 뽑는다. 결과는 검토 화면에서 사장님이 고르고 고친 뒤 등록한다."""
    co=me();up=request.files.get('file')
    if not up or not up.filename:flash('PDF 파일을 골라 주세요','error');return redirect(url_for('rules')+'#products')
    try:
        with conn() as db:token=product_pdf.start(db,co,up.filename,up.read(product_pdf.MAX_BYTES+1))
    except ValueError as e:flash(str(e),'error');return redirect(url_for('rules')+'#products')
    return redirect(url_for('product_import',token=token))

@app.route('/products/import/<token>',methods=['GET','POST'])
@login_required
def product_import(token):
    co=me()
    with conn() as db:
        if request.method=='POST':
            msg,level=product_pdf.confirm(db,co,token,request.form);flash(msg,level)
            return redirect(url_for('rules')+'#products')
        j=product_pdf.job(db,co['id'],token)
    if not j:abort(404)
    return render_template('b_product_import.html',j=j,token=token,compose=product_pdf.compose,PUBLIC=product_pdf.PUBLIC,INTERNAL=product_pdf.INTERNAL,tab='rules')

COND_CATS=('교환','반품·환불')  # 받은 지 7일 조건은 이 두 유형에만
def save_rule(db,co,f):
    """유형 하나의 자동 처리 규칙 저장. 보내지 않은 항목은 그대로 둔다."""
    cat=f.get('category')
    if cat not in core.CATS:return False
    cur=core.rule_for(db,co['id'],cat)
    auto=cur['auto'] if 'auto' not in f else str(f['auto']) in ('1','True','true')
    reply=clean(f.get('reply'),2000) if 'reply' in f else cur['reply']
    faq=clean(f.get('faq'),1000) if 'faq' in f else cur['faq']
    cond=f.get('cond','') if 'cond' in f else cur['cond']
    if cond not in core.COND or cat not in COND_CATS:cond=''
    comp=clean(f.get('comp'),100) if 'comp' in f else cur['comp']
    db.execute('INSERT INTO rules(company_id,category,auto,reply,faq,cond,comp) VALUES(?,?,?,?,?,?,?) ON CONFLICT(company_id,category) DO UPDATE SET auto=excluded.auto,reply=excluded.reply,faq=excluded.faq,cond=excluded.cond,comp=excluded.comp',(co['id'],cat,int(auto),reply,faq,cond,comp))
    return True

@app.route('/team',methods=['GET','POST'])
@login_required
def team_page():
    """직원 관리: 초대, 역할 바꾸기, 내보내기, 비밀번호 링크 다시 만들기. 직원 수로 요금을 받지 않는다."""
    co=me();link=''
    with conn() as db:
        if request.method=='POST':
            if request.form.get('act')=='invite':msg,level,link=team.invite(db,co,request.form)
            else:msg,level,link=team.update(db,co,who(),request.form)
            if msg:flash(msg,level)
            if not link:return redirect(url_for('team_page'))
        rows=team.staff(db,co['id'])
        load={k:db.execute("SELECT COUNT(*) FROM cases WHERE company_id=? AND assignee=? AND status NOT IN ('resolved','unresolved','closed','withdrawn')",(co['id'],k)).fetchone()[0] for k in ['owner']+[str(r['id']) for r in rows]}
    return render_template('b_team.html',rows=rows,link=link,load=load,owner=team.owner_actor(co),INVITE_ROLES=team.INVITE_ROLES,tab='team')

@app.route('/join/<tok>',methods=['GET','POST'])
def join(tok):
    """직원 초대 링크: 비밀번호를 정하면 바로 로그인. 한 번 쓰면 다시 못 쓴다."""
    with conn() as db:
        s=team.read_invite(db,tok)
        if not s:flash('초대 링크가 만료됐거나 이미 썼어요. 대표나 관리자에게 다시 요청해 주세요.','error');return redirect(url_for('login'))
        co=core.company(db,s['company_id'])
        if request.method=='POST':
            err=team.accept(db,s,request.form.get('password',''))
            if not err:
                csrf=session.get('csrf');session.clear();session['co_id']=co['id'];session['staff_id']=s['id'];session.permanent=True
                if csrf:session['csrf']=csrf
                flash(f"{co['name']}에 오신 걸 환영해요",'ok');return redirect(url_for('decide'))
            flash(err,'error')
    return render_template('b_join.html',s=s,company=co,role=team.ROLES[s['role']])

@app.route('/settings',methods=['GET','POST'])
@login_required
def settings():
    co=me()
    if request.method=='POST':
        with conn() as db:flash(*save_settings(db,co,request.form))
        return redirect(url_for('settings'))
    with conn() as db:use=onboard.usage(db,co['id']);refs=growth.company_page_data(db,real())
    return render_template('b_settings.html',tab='settings',DAYS=workflow.DAYS,SLA_CHOICES=workflow.SLA_CHOICES,AWAY_DEFAULT=workflow.AWAY_DEFAULT,hours_text=workflow.hours_text(co),link=core.site_url('me','/to/%d'%co['id']),kakao_ready=core.kakao_ready(),guide_preview=core.return_guide(co),use=use,refs=refs)

def save_settings(db,co,f):
    """설정 저장(웹·앱 공용). act: password·return·notify, 없으면 회사 정보. (문구, 'ok'|'error')를 돌려준다."""
    on=lambda k:str(f.get(k)) in ('1','True','true')
    if f.get('act')=='password':
        if not check_password_hash(co['pw_hash'],f.get('old','')):return '지금 비밀번호가 맞지 않습니다','error'
        if len(f.get('new',''))<10:return '새 비밀번호는 10자 이상입니다','error'
        db.execute('UPDATE companies SET pw_hash=? WHERE id=?',(generate_password_hash(f['new']),co['id']));return '비밀번호를 바꿨습니다','ok'
    if f.get('act')=='return':
        courier=f.get('return_courier','') if f.get('return_courier','') in core.COURIERS else ''
        db.execute('UPDATE companies SET return_address=?,return_courier=?,return_memo=? WHERE id=?',(clean(f.get('return_address'),200),courier,clean(f.get('return_memo'),300),co['id']));return '반품 안내를 저장했습니다','ok'
    if f.get('act')=='ops':return workflow.save(db,co,f)
    if f.get('act')=='notify':
        phone=digits(f.get('phone',''))
        if on('kakao') and not (phone.startswith('01') and 10<=len(phone)<=11):return '알림톡을 받을 휴대폰 번호를 확인해 주세요','error'
        db.execute('UPDATE companies SET phone=?,kakao=?,report_mail=? WHERE id=?',(phone,int(on('kakao')),int(on('report_mail')),co['id']));return '알림 설정을 저장했습니다','ok'
    email=clean(f.get('notify_email'),80)
    industry=f.get('industry','') if f.get('industry','') in core.INDUSTRIES else ''
    tone=f.get('tone','polite') if f.get('tone') in core.TONES else 'polite'
    if email and not EMAIL_RE.match(email):return '알림 이메일을 확인해 주세요','error'
    db.execute('UPDATE companies SET contact=?,notify_email=?,industry=?,tone=? WHERE id=?',(clean(f.get('contact'),60),email,industry,tone,co['id']));return '저장했습니다','ok'

# ---------- 센터 운영 ----------
@app.route('/ops/login',methods=['GET','POST'])
def ops_login():
    if request.method=='POST':
        if core.throttled('ops',limit=8,minutes=10):flash('잠시 후 다시 시도해 주세요','error')
        elif OPS_HASH and check_password_hash(OPS_HASH,request.form.get('password','')):
            co_id=session.get('co_id');csrf=session.get('csrf');session.clear();session['ops']=True
            if csrf:session['csrf']=csrf
            if co_id:session['co_id']=co_id;session.permanent=True  # 기업 로그인은 그대로 둔다
            return redirect(url_for('ops'))
        else:flash('비밀번호가 맞지 않습니다','error')
    return render_template('o_login.html')
@app.route('/ops/logout',methods=['POST'])
def ops_logout():session.pop('ops',None);return redirect(url_for('ops_login'))

@app.route('/ops')
@ops_required
def ops():
    with conn() as db:
        rows=db.execute('SELECT * FROM cases WHERE member=0 ORDER BY CASE WHEN status IN (\'received\',\'forwarded\') THEN 0 ELSE 1 END,id DESC LIMIT 300').fetchall()
        n_pending=db.execute("SELECT COUNT(*) FROM companies WHERE "+onboard.WAITING_SQL).fetchone()[0]
    q=clean(request.args.get('q'),40);fil=request.args.get('f','all')
    if q:rows=[r for r in rows if q.lower() in (r['title']+' '+r['no']+' '+r['company_name']).lower()]
    groups={'all':rows,'send':[r for r in rows if r['consent'] and not r['attempts'] and r['status'] not in core.FINAL],
            'open':[r for r in rows if r['status'] not in core.FINAL],'done':[r for r in rows if r['status'] in core.FINAL]}
    if fil not in groups:fil='all'
    return render_template('o_home.html',rows=groups[fil],groups=groups,fil=fil,q=q,n_signup=n_pending,otab='non')

@app.route('/ops/all')
@ops_required
def ops_all():
    with conn() as db:
        rows=db.execute("SELECT * FROM cases WHERE COALESCE(company_id,0) NOT IN (SELECT id FROM companies WHERE status='demo') ORDER BY id DESC LIMIT 500").fetchall();n_pending=db.execute("SELECT COUNT(*) FROM companies WHERE "+onboard.WAITING_SQL).fetchone()[0]
        n=lambda sql,*a:db.execute(sql,a).fetchone()[0]
        sums=dict(members=n("SELECT COUNT(*) FROM companies WHERE status='active' AND member=1"),cases=n("SELECT COUNT(*) FROM cases WHERE COALESCE(company_id,0) NOT IN (SELECT id FROM companies WHERE status='demo')"),
                  non=n('SELECT COUNT(*) FROM cases WHERE member=0'),open=n("SELECT COUNT(*) FROM cases WHERE status IN ('received','forwarded','seen','info') AND COALESCE(company_id,0) NOT IN (SELECT id FROM companies WHERE status='demo')"))
        todo=db.execute("SELECT * FROM cases WHERE member=0 AND status IN ('received','forwarded','seen','info') ORDER BY CASE WHEN attempts=0 AND consent=1 THEN 0 ELSE 1 END,id LIMIT 6").fetchall()
        signups=db.execute("SELECT * FROM companies WHERE "+onboard.WAITING_SQL+" ORDER BY id LIMIT 5").fetchall()
        no_contact=n("SELECT COUNT(*) FROM companies WHERE status='listed' AND contact=''")
    late=sum(map(core.overdue,rows))
    watch=[dict(text=f'회사 인증을 기다리는 가입 {n_pending}건이 있어요',href=url_for('ops_companies')) for _ in [0] if n_pending]
    watch+=[dict(text=f'답변 기한이 지난 요청이 {late}건 있어요',href=url_for('ops')) for _ in [0] if late]
    watch+=[dict(text=f'공식 연락처가 없는 비입점 기업이 {no_contact}곳 있어요',href=url_for('ops_companies')) for _ in [0] if no_contact]
    watch+=[dict(text=f'{core.SECRETS[k][0]}가 꺼져 있어요',href=url_for('ops_keys')) for k in core.SECRETS if not core.secret(k)]
    return render_template('o_all.html',rows=rows,k=kpis(rows),sums=sums,todo=todo,signups=signups,watch=watch,n_signup=n_pending,otab='all')

@app.route('/ops/case/<int:case_id>',methods=['GET','POST'])
@ops_required
def ops_case(case_id):
    with conn() as db:
        c=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        if not c:abort(404)
        if request.method=='POST':
            act=request.form.get('act')
            if c['member'] or c['status'] in core.FINAL:abort(400)
            if act=='attempt' and c['consent']:
                ch=request.form.get('channel') if request.form.get('channel') in ('이메일','전화','1:1 문의','우편') else '이메일'
                db.execute("UPDATE cases SET status='forwarded',attempts=attempts+1 WHERE id=?",(c['id'],))
                core.add_event(db,c['id'],'sys',f'센터가 {ch}(으)로 기업에 전달했어요');flash('기록했습니다','ok')
            elif act=='reply' and clean(request.form.get('msg'),3000):
                db.execute("UPDATE cases SET status='answered' WHERE id=?",(c['id'],))
                core.add_event(db,c['id'],'co','기업 회신 (센터 기록)',clean(request.form.get('msg'),3000))
                notify_consumer(c,f'[{core.CNAME}] 기업 회신이 도착했어요',f"{c['company_name']}의 회신을 센터가 기록했어요.");flash('기록했습니다','ok')
            elif act=='unresolved':
                db.execute("UPDATE cases SET status='unresolved' WHERE id=?",(c['id'],))
                core.add_event(db,c['id'],'sys','기업 회신이 없어 공식 피해구제 절차(1372 소비자상담센터, 한국소비자원)를 안내했어요')
                notify_consumer(c,f'[{core.CNAME}] 피해구제 절차를 안내해 드려요','기업 회신이 없어 공식 피해구제 절차를 안내해 드려요. 접수 화면에서 확인해 주세요.');flash('안내했습니다','ok')
            return redirect(url_for('ops_case',case_id=case_id))
        ev=core.events(db,c['id']);fl=core.case_files(db,c['id']);co=core.company(db,c['company_id'])
    return render_template('o_case.html',c=c,ev=ev,files=fl,cinfo=co,otab='non')

@app.route('/ops/case/<int:case_id>/file/<int:file_id>')
@ops_required
def ops_file(case_id,file_id):
    with conn() as db:f=db.execute('SELECT * FROM files WHERE id=? AND case_id=?',(file_id,case_id)).fetchone()
    if not f:abort(404)
    return send_file(core.UPLOAD/f['stored'],download_name=f['original'])

@app.route('/ops/companies',methods=['GET','POST'])
@ops_required
def ops_companies():
    with conn() as db:
        if request.method=='POST':
            act=request.form.get('act');cid=request.form.get('id','')
            co=core.company(db,int(cid)) if cid.isdigit() else None
            waiting=co and (co['status']=='pending' or (co['status']=='active' and not co['member'] and not co['demo_of']))
            if act=='approve' and waiting:
                # 회사 인증: 같은 이름의 비입점 기업 요청을 이 기업으로 옮기고(이후 요청부터 입점 처리) 소비자 접수·판매처 연결을 연다
                onboard.make_member(db,co);flash(f"{co['name']} 회사 인증을 마쳤습니다",'ok')
            elif act=='recheck' and waiting:
                co=onboard.recheck_biz(db,co);flash(f"국세청 확인: {onboard.BIZ_STATUS.get(co['biz_status'],co['biz_status'])}"+('' if onboard.nts_ready() else ' (국세청 키가 없어요. 서비스 키 화면에서 넣어 주세요)'),'ok')
            elif act=='reject' and waiting:db.execute("UPDATE companies SET status='rejected',member=0 WHERE id=?",(co['id'],));flash('반려했습니다. 이 계정은 더 로그인할 수 없어요','ok')
            elif act=='suspend' and co and co['status']=='active':db.execute("UPDATE companies SET status='suspended',susp_member=member,member=0 WHERE id=?",(co['id'],));flash('이용을 중지했습니다','ok')
            elif act=='resume' and co and co['status']=='suspended':db.execute("UPDATE companies SET status='active',member=susp_member WHERE id=?",(co['id'],));flash('다시 이용할 수 있게 했습니다','ok')
            elif act=='pwlink' and co and co['status']=='active' and co['pw_hash']:
                flash(f"{co['name']} 비밀번호 재설정 링크예요. 1시간 동안 열려요. 복사해서 사장님께 보내 주세요: {reset_link(co)}",'ok')
            elif act=='contact' and co:db.execute('UPDATE companies SET contact=? WHERE id=?',(clean(request.form.get('contact'),60),co['id']));flash('저장했습니다','ok')
            elif act=='add':
                name=clean(request.form.get('name'),40)
                if name and not core.find_company(db,name):db.execute("INSERT INTO companies(name,member,status,contact,created) VALUES(?,0,'listed',?,?)",(name,clean(request.form.get('contact'),60),core.iso()));flash('추가했습니다','ok')
                else:flash('이름이 비었거나 이미 있습니다','error')
            return redirect(url_for('ops_companies'))
        pending=db.execute("SELECT * FROM companies WHERE "+onboard.WAITING_SQL+" ORDER BY id").fetchall()
        rows=db.execute("SELECT c.*,(SELECT COUNT(*) FROM cases WHERE company_id=c.id) n,(SELECT MAX(created) FROM cases WHERE company_id=c.id) last FROM companies c WHERE status IN ('active','listed','suspended') ORDER BY member DESC,name").fetchall()
    return render_template('o_companies.html',pending=pending,rows=rows,n_signup=len(pending),otab='co')

@app.route('/ops/company/<int:cid>')
@ops_required
def ops_company(cid):
    """기업 상세 (보기 전용): 기본 정보, 이용 상태, 연동 현황, 요청 처리 현황, 최근 요청. 바꾸는 일은 기업 관리 목록에서 한다."""
    with conn() as db:
        co=core.company(db,cid)
        if not co or co['status'] not in ('active','listed','suspended'):abort(404)
        cases=db.execute('SELECT * FROM cases WHERE company_id=? ORDER BY id DESC',(cid,)).fetchall()
        chans=db.execute('SELECT channel,COUNT(*) n FROM orders WHERE company_id=? GROUP BY channel',(cid,)).fetchall()
        n_auto=db.execute('SELECT COUNT(*) FROM rules WHERE company_id=? AND auto=1',(cid,)).fetchone()[0]
        n_pending=db.execute("SELECT COUNT(*) FROM companies WHERE "+onboard.WAITING_SQL).fetchone()[0]
    return render_template('o_company.html',co=co,cases=cases[:20],k=kpis(cases),n_open=sum(r['status'] not in core.FINAL for r in cases),chans=chans,n_auto=n_auto,n_signup=n_pending,otab='co')

@app.route('/ops/marketing')
@ops_required
def ops_marketing():
    """마케팅 분석: 공개 화면 방문부터 가입·설정·첫 답변·상담 신청까지 실제 기록만 센다."""
    days=int(request.args.get('d','30')) if request.args.get('d') in ('7','30','90') else 30
    with conn() as db:r=funnel.report(db,days)
    top=max([n for _,_,n in r['steps']]+[1])
    return render_template('o_marketing.html',r=r,top=top,days=days,keep=funnel.KEEP_DAYS,site=core.site_url('biz','/'),n_signup=cms.n_waiting(),otab='mkt')

@app.route('/ops/news',methods=['GET','POST'])
@ops_required
def ops_news():
    """법·제도 소식: 운영자가 공식 출처를 확인하고 직접 올린다 (자동 수집하지 않음)."""
    with conn() as db:
        if request.method=='POST':
            if request.form.get('act')=='delete' and request.form.get('id','').isdigit():
                db.execute('DELETE FROM news WHERE id=?',(int(request.form['id']),));flash('지웠습니다','ok')
            else:
                title=clean(request.form.get('title'),120);body=clean(request.form.get('body'),3000);src=clean(request.form.get('source_url'),300)
                if not title or not body or not src.startswith(('https://','http://')):flash('제목, 내용, 출처 주소(https://…)를 모두 적어 주세요','error')
                else:
                    db.execute('INSERT INTO news(title,body,source_url,created) VALUES(?,?,?,?)',(title,body,src,core.iso()))
                    if request.form.get('mail')=='1':
                        for co in db.execute("SELECT notify_email FROM companies WHERE status='active' AND member=1").fetchall():
                            core.send_mail(co['notify_email'],f'[{core.BNAME}] 법·제도 소식: {title}',f"{body}\n\n출처: {src}\n{core.site_url('biz','/news')}")
                    flash('올렸습니다','ok')
            return redirect(url_for('ops_news'))
        rows=db.execute('SELECT * FROM news ORDER BY id DESC').fetchall();n_pending=db.execute("SELECT COUNT(*) FROM companies WHERE "+onboard.WAITING_SQL).fetchone()[0]
    return render_template('o_news.html',rows=rows,n_signup=n_pending,otab='news')

@app.route('/ops/keys',methods=['GET','POST'])
@ops_required
def ops_keys():
    """외부 서비스 키: 서버 창을 열지 않고 운영 화면에서 넣고 바꾼다. 화면에는 끝 4자리만 보인다."""
    if request.method=='POST':
        name=request.form.get('name')
        if name not in core.SECRETS:abort(400)
        val=re.sub(r'\s','',request.form.get('value',''))[:300]
        with conn() as db:
            if request.form.get('act')=='delete':db.execute('DELETE FROM settings WHERE key=?',(name,));flash('지웠습니다','ok')
            elif not val:flash('키를 붙여 넣어 주세요','error')
            else:
                db.execute('INSERT INTO settings(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated',(name,val,core.iso()))
                flash(f'{core.SECRETS[name][0]}를 저장했습니다. 바로 적용돼요','ok')
        return redirect(url_for('ops_keys'))
    keys=[dict(name=k,label=l,hint=h,source=core.secret_source(k),tail=core.secret(k)[-4:]) for k,(l,h) in core.SECRETS.items()]
    with conn() as db:n_pending=db.execute("SELECT COUNT(*) FROM companies WHERE "+onboard.WAITING_SQL).fetchone()[0]
    return render_template('o_keys.html',keys=keys,n_signup=n_pending,otab='keys')

COPY_PAGES=[('c_home.html','고객 첫 화면'),('c_new.html','요청 접수'),('c_done.html','접수 완료'),('c_mine.html','내 접수'),('c_case.html','접수 상세'),
 ('c_company.html','기업별 고객센터'),('c_guide.html','이용 안내'),('c_relief.html','피해구제 안내'),('c_privacy.html','개인정보 처리방침'),('c_error.html','오류 화면'),
 ('_c.html','고객 공통 메뉴'),('_chat.html','상담 챗봇'),('consumer.py','고객 안내 메시지'),
 ('b_intro.html','소보루 CS 소개'),('b_login.html','로그인'),('b_signup.html','가입'),('b_start.html','처음 설정'),('b_forgot.html','비밀번호 찾기'),
 ('b_decide.html','사장님 홈'),('b_all.html','요청 목록'),('b_case.html','요청 상세'),('b_new.html','직접 등록'),('b_rules.html','자동 처리'),('b_stats.html','통계'),
 ('b_report.html','리포트'),('insights.py','리포트 분석 문구'),('b_guide.html','응대 가이드'),('law.py','응대 가이드 상황별 문구'),('b_news.html','법·제도 소식'),
 ('b_settings.html','설정'),('b_record.html','처리 기록'),('b_terms.html','약관'),('_b.html','기업 공통 메뉴'),('business.py','기업 안내 메시지'),
 ('base.html','두 곳 공통'),('core.py','공통 안내 문구')]

@app.route('/ops/copy',methods=['GET','POST'])
@ops_required
def ops_copy():
    """문구 고치기: 고객센터·소보루 CS 화면의 문구를 바꾼다. 템플릿은 그대로 두고 화면에 내보낼 때만 바꾼다.
    저장하면 그대로 유지되고, 같은 자리에서 언제든 다시 고칠 수 있다."""
    q=clean(request.values.get('q'),100);pg=request.values.get('pg','')
    ajax=request.headers.get('X-Requested-With')=='fetch'
    with conn() as db:
        if request.method=='POST':
            site=request.form.get('site');src=(request.form.get('src') or '').strip();dst='\n'.join(l for l in (' '.join(x.split()) for x in (request.form.get('dst') or '').splitlines()) if l)  # 줄바꿈은 살리고 빈 줄은 뺀다
            tpl=request.form.get('tpl') or ''
            if site not in core.COPY_SITES or not src or (tpl and (site=='all' or not re.fullmatch(r'[a-z_]+\.html',tpl))):msg,ok='바꿀 문구를 확인해 주세요',False
            elif tpl:  # 화면 보며 고친 글자: 그 화면에서만 바뀐다
                if dst==src:db.execute('DELETE FROM copy_page_edits WHERE site=? AND tpl=? AND src=?',(site,tpl,src))
                else:db.execute('INSERT INTO copy_page_edits(site,tpl,src,dst,created) VALUES(?,?,?,?,?) ON CONFLICT(site,tpl,src) DO UPDATE SET dst=excluded.dst,created=excluded.created',(site,tpl,src[:2000],dst[:2000],core.iso()))
                msg,ok=('화면에서 지웠어요' if not dst else '저장했어요'),True
            else:
                if request.form.get('shown'):  # 화면에서 바로 고친 경우: 보이는 글자가 이미 바꾼 문구면 그 기록을 고친다
                    prev=db.execute("SELECT site,src FROM copy_edits WHERE dst=? AND site IN (?,'all') ORDER BY site=? DESC LIMIT 1",(src,site,site)).fetchone()
                    if prev:site,src=prev['site'],prev['src']
                if dst==src:db.execute('DELETE FROM copy_edits WHERE site=? AND src=?',(site,src))  # 원래 문구와 같으면 바꾼 기록이 필요 없음
                else:db.execute('INSERT INTO copy_edits(site,src,dst,created) VALUES(?,?,?,?) ON CONFLICT(site,src) DO UPDATE SET dst=excluded.dst,created=excluded.created',(site,src[:2000],dst[:2000],core.iso()))
                msg,ok=('화면에서 지웠어요' if not dst else '저장했어요'),True
            if ajax:return jsonify(ok=ok,msg=msg,edited=ok and dst!=src)
            flash(msg,'ok' if ok else 'error')
            return redirect(url_for('ops_copy',q=q or None,pg=pg or None))
        edits={(e['site'],e['src']):e for e in db.execute('SELECT * FROM copy_edits ORDER BY id DESC')}
        page_edits=db.execute('SELECT * FROM copy_page_edits ORDER BY id DESC').fetchall()
        n_pending=db.execute("SELECT COUNT(*) FROM companies WHERE "+onboard.WAITING_SQL).fetchone()[0]
    names=dict(COPY_PAGES);cat=core.copy_catalog();keys={(s,t) for s,t,_ in cat}
    items=[dict(site=s,src=t,files=fs,dst=edits[(s,t)]['dst'] if (s,t) in edits else t,edited=(s,t) in edits) for s,t,fs in cat]
    items=[dict(site=s,src=t,files=[],dst=e['dst'],edited=True) for (s,t),e in edits.items() if (s,t) not in keys]+items
    items=[dict(site=e['site'],src=e['src'],tpl=e['tpl'],files=[e['tpl']],dst=e['dst'],edited=True,only=True) for e in page_edits]+items  # 화면 보며 고친 글자 (그 화면에서만)
    counts={}
    for it in items:
        for f in it['files']:counts[f]=counts.get(f,0)+1
    pages=[(f,n,counts[f]) for f,n in COPY_PAGES if counts.get(f)]
    if pg=='edited':items=[it for it in items if it['edited']]
    elif pg:items=[it for it in items if pg in it['files']]
    if q:items=[it for it in items if q in it['src'] or q in it['dst']]
    order={f:i for i,(f,_) in enumerate(COPY_PAGES)}
    items.sort(key=lambda it:(not it['edited'],min((order.get(f,99) for f in it['files']),default=99)))  # 바꾼 문구 먼저, 그다음 화면 순서대로
    for it in items:it['where']=(', '.join(names.get(f,'') for f in it['files'][:3] if names.get(f)) or core.COPY_SITES[it['site']])+(' 화면에서만' if it.get('only') else '')
    return render_template('o_copy.html',items=items[:200],n_items=len(items),pages=pages,n_edited=len(edits)+len(page_edits),q=q,pg=pg,pg_name=names.get(pg,''),n_signup=n_pending,otab='copy')


VISUAL_PAGES=[('me','/','고객 첫 화면',0),('me','/new','요청 접수',0),('me','/guide','이용 안내',0),('me','/mine','내 접수',0),('me','/to/','기업별 고객센터',0),('me','/privacy','개인정보 처리방침',0),
 ('biz','/','소보루 CS 소개',0),('biz','/login','로그인',0),('biz','/signup','가입',0),('biz','/forgot','비밀번호 찾기',0),('biz','/terms','약관',0),
 ('biz','/','사장님 홈',1),('biz','/all','요청 목록',1),('biz','/rules','자동 처리',1),('biz','/stats','통계',1),('biz','/report','리포트',1),('biz','/guide','응대 가이드',1),('biz','/news','법·제도 소식',1),('biz','/new','직접 등록',1),('biz','/settings','설정',1)]

def visual_companies():
    with conn() as db:return db.execute("SELECT id,name FROM companies WHERE status='active' AND member=1 ORDER BY id").fetchall()

@app.route('/ops/visual')
@ops_required
def ops_visual():
    """화면 보며 고치기: 실제 화면을 띄워 놓고 문장을 끌어 옮기거나 두 번 눌러 글자를 고친다."""
    i=request.args.get('p','0');i=int(i) if i.isdigit() and int(i)<len(VISUAL_PAGES) else 0
    with conn() as db:n_pending=db.execute("SELECT COUNT(*) FROM companies WHERE "+onboard.WAITING_SQL).fetchone()[0]
    cos=visual_companies();dev='m' if request.args.get('dev')=='m' else 'pc'
    return render_template('o_visual.html',pages=VISUAL_PAGES,p=i,dev=dev,cos=cos,co_id=request.args.get('co',''),n_signup=n_pending,otab='visual')

@app.route('/ops/visual/frame')
@ops_required
def ops_visual_frame():
    """편집할 화면을 안에서 그려서, 옮기기·고치기 도구를 붙여 내보낸다. 실제 화면과 같은 글자·위치가 보인다."""
    import consumer
    i=request.args.get('p','0');i=int(i) if i.isdigit() and int(i)<len(VISUAL_PAGES) else 0
    site,path,_,need_login=VISUAL_PAGES[i];cos=visual_companies()
    co=next((c for c in cos if str(c['id'])==request.args.get('co','')),cos[0] if cos else None)
    if path=='/to/':path='/to/%d'%co['id'] if co else '/'
    client=(consumer.app if site=='me' else app).test_client()
    if need_login:
        if not co:return '<p style="font:16px sans-serif;padding:40px;text-align:center;color:#4e5968">입점한 기업이 있어야 사장님 화면을 볼 수 있어요.</p>'
        with client.session_transaction() as s:s['co_id']=co['id']
    r=client.get(path,headers={'X-Cp-Editor':'1'})
    if r.status_code!=200 or r.mimetype!='text/html':return '<p style="font:16px sans-serif;padding:40px;text-align:center;color:#4e5968">이 화면은 미리 볼 수 없어요.</p>'
    html=r.get_data(as_text=True);tpl=r.headers.get('X-Cp-Tpl','')
    cfg=json.dumps(dict(site=site,tpl=tpl,csrf=core.csrf_token(),copy=url_for('ops_copy'),move=url_for('ops_visual_move')),ensure_ascii=False).replace('<','\\u003c')
    tool=render_template('_visual_tool.html',cfg=cfg)
    html=html.replace('</body>',tool+'</body>',1) if '</body>' in html else html+tool
    resp=app.response_class(html,mimetype='text/html');resp.headers['X-Frame-Options']='SAMEORIGIN'
    return resp

@app.route('/ops/visual/move',methods=['POST'])
@ops_required
def ops_visual_move():
    f=request.form;tpl=(f.get('tpl') or '')[:80];sel=(f.get('sel') or '').strip();dev=f.get('dev')
    try:dx=max(-2000,min(2000,round(float(f.get('dx','0')))));dy=max(-4000,min(4000,round(float(f.get('dy','0')))))
    except ValueError:return jsonify(ok=False,msg='위치를 확인해 주세요')
    if not re.fullmatch(r'[a-z_]+\.html',tpl) or dev not in core.MOVE_MEDIA or not core.MOVE_SEL.match(sel):return jsonify(ok=False,msg='옮길 문장을 다시 골라 주세요')
    with conn() as db:
        reset=f.get('reset')=='1' or (dev=='pc' and dx==0 and dy==0)  # 모바일은 0,0도 '처음 자리에 둠'으로 저장 (PC 위치를 안 따라감)
        if reset:db.execute('DELETE FROM copy_moves WHERE tpl=? AND sel=? AND dev=?',(tpl,sel,dev))
        else:db.execute('INSERT INTO copy_moves(tpl,sel,dev,dx,dy,created) VALUES(?,?,?,?,?,?) ON CONFLICT(tpl,sel,dev) DO UPDATE SET dx=excluded.dx,dy=excluded.dy,created=excluded.created',(tpl,sel,dev,dx,dy,core.iso()))
    return jsonify(ok=True,msg=('모바일도 PC 위치를 따라가요' if dev=='m' else '원래 자리로 옮겼어요') if reset else '위치를 저장했어요')


# ---------- 사장님 앱 API (/api/v1) ----------
# 로그인하면 토큰을 준다. 토큰에 비밀번호 해시 끝부분을 넣어 두어서 비밀번호를 바꾸면 예전 토큰은 못 쓴다.
def co_token(co):return core.signer('app-biz').dumps({'id':co['id'],'h':co['pw_hash'][-16:]})
def api_co():
    tok=request.headers.get('Authorization','').removeprefix('Bearer ').strip() or request.args.get('t','')
    try:d=core.signer('app-biz').loads(tok)
    except Exception:d=None
    with conn() as db:co=core.company(db,d.get('id')) if isinstance(d,dict) else None
    if not co or co['status']!='active' or co['pw_hash'][-16:]!=d.get('h'):abort(401)  # 인증 전 회사도 앱을 쓴다 (판매처 연결·소비자 접수만 인증 뒤)
    g.co=co;g.who=team.owner_actor(co);g.actor=g.who['name'];return co
def api_form():j=request.get_json(silent=True);return j if isinstance(j,dict) and j else request.form
def co_info(co):
    return dict(id=co['id'],name=co['name'],login_id=co['login_id'],link=core.site_url('me','/to/%d'%co['id']),verified=bool(co['member']),plan=onboard.PLANS.get(co['plan'],{}).get('name',''))
def biz_summary(c):
    return dict(id=c['id'],no=c['no'],category=c['category'],title=c['title'],name=c['name'] or '',status=c['status'],status_label=core.status_label(c['status']),
        decision=c['decision'],decision_label=core.DECISION.get(c['decision'],''),pending=is_pending(c),overdue=core.overdue(c),due=c['due'],created=c['created'],updated=c['updated'])
def biz_detail(db,c,co):
    ev=core.events(db,c['id']);fl=core.case_files(db,c['id']);rule=core.rule_for(db,co['id'],c['category']);pb=core.PLAYBOOK.get(c['category'],core.PLAYBOOK['기타'])
    tok=co_token(co);url=lambda f:url_for('api_biz_file',case_id=c['id'],file_id=f['id'],t=tok,_external=True)
    d=biz_summary(c);open_=c['status'] not in core.FINAL
    d.update(body=c['body'],want=c['want'],order_no=c['order_no'],product=c['product'],received_on=c['received_on'],info_ask=c['info_ask'],
        phone=core.fmt_phone(c['phone']) if c['phone'] else '',email=c['email'] or '',
        plan=dict(title=pb['title'],steps=pb['steps'],reply=rule.get('reply') or pb['reply']),
        ret=dict(status=c['ret_status'],courier=c['ret_courier'],tracking=c['ret_tracking'],out_courier=c['out_courier'],out_tracking=c['out_tracking']),
        refund=dict(possible=core.refund_case(c),status=c['refund_status'],bank=c['refund_bank'],account=c['refund_account'],holder=c['refund_holder']),
        events=[dict(id=e['id'],kind=e['kind'],text=e['text'],reply=e['reply'],created=e['created'],files=[dict(id=f['id'],name=f['original'],url=url(f)) for f in fl if f['event_id']==e['id']]) for e in ev],
        files=[dict(id=f['id'],name=f['original'],url=url(f)) for f in fl],
        tracks=[tracking_mod.as_dict(t) for t in tracking_mod.tracks(db,c['id'])],
        order=(lambda o:orders_mod.as_dict(o) if o else None)(orders_mod.for_case(db,c)),
        cancel_blocked=bool(orders_mod.cancel_blocked(db,c)),
        comp=dict(reco=rule['comp'],status=c['comp_status'],given=c['comp'],examples=core.COMP_EXAMPLES),
        can=dict(comp=core.comp_open(c) and bool(rule['comp'] or c['category'] in core.COMP_CATS),ship_track=can_ship_track(db,c),approve=open_ and c['decision'] not in ('approved','auto'),hold=open_ and c['decision']!='hold',ask=open_,reply=open_,
            ret_received=c['ret_status'] in ('guided','sent'),out_ship=c['category'] in ('교환','제품 불량') and c['ret_status']=='received' and not c['out_tracking'],
            refund_done=core.refund_case(c) and c['refund_status']!='done'))
    return d
def api_my_case(db,co,case_id):
    c=db.execute('SELECT * FROM cases WHERE id=? AND company_id=? AND member=1 AND consent=1',(case_id,co['id'])).fetchone()
    if not c:abort(404)
    return c

@app.route('/api/v1/meta')
def api_biz_meta():
    return jsonify(cats=core.CATS,couriers=list(core.COURIERS),operator=core.OPERATOR,name=core.BNAME,industries=core.INDUSTRIES,
        signup=core.site_url('biz','/signup'),forgot=core.site_url('biz','/forgot'),privacy=core.site_url('me','/privacy'))
@app.route('/api/v1/login',methods=['POST'])
def api_biz_login():
    f=api_form();lid=clean(f.get('login_id'),80).lower();pw=f.get('password','')
    if core.throttled('login',limit=10,minutes=10):return jsonify(error='로그인 시도가 너무 많습니다. 10분 뒤에 다시 해 주세요.'),429
    with conn() as db:co=db.execute('SELECT * FROM companies WHERE login_id=?',(lid,)).fetchone()
    if not co or not check_password_hash(co['pw_hash'],pw):return jsonify(error='이메일이나 비밀번호가 맞지 않습니다.'),400
    if co['status']=='pending':return jsonify(error='가입 승인을 기다리고 있습니다. 승인되면 이메일로 알려 드립니다.'),400
    if co['status']!='active':return jsonify(error='이용할 수 없는 계정입니다. 센터에 문의해 주세요.'),400
    return jsonify(token=co_token(co),company=co_info(co))
@app.route('/api/v1/home')
def api_biz_home():
    co=api_co()
    with conn() as db:
        rows=my_cases(db,co);n_auto=db.execute('SELECT COUNT(*) FROM rules WHERE company_id=? AND auto=1',(co['id'],)).fetchone()[0]
        warn=insights.alerts(db,co);news=db.execute('SELECT id,title,created FROM news ORDER BY id DESC LIMIT 3').fetchall();comps=core.comp_rules(db,co['id'])
    pend=[r for r in rows if is_pending(r)]
    return jsonify(company=co_info(co),kpi=kpis(rows),counts={'comp':sum(core.comp_pending(r,comps) for r in rows),'all':len(rows),'pending':len(pend),'open':sum(map(is_open,rows)),'late':sum(map(core.overdue,rows)),'auto_rules':n_auto,'ret':sum(r['ret_status']=='sent' for r in rows)},
        pending=[biz_summary(r) for r in pend],recent=[biz_summary(r) for r in rows[:6]],
        alerts=[dict(kind=w['kind'],label=w['label'],n=w['n'],cats=w['cats']) for w in warn],news=[dict(r) for r in news])
@app.route('/api/v1/cases')
def api_biz_cases():
    co=api_co();fil=request.args.get('f','all');q=clean(request.args.get('q'),40)
    with conn() as db:rows=my_cases(db,co);comps=core.comp_rules(db,co['id'])
    if q:rows=[r for r in rows if q.lower() in (r['title']+' '+r['no']+' '+(r['name'] or '')+' '+r['body']).lower()]
    groups={'comp':[r for r in rows if core.comp_pending(r,comps)],'all':rows,'pending':[r for r in rows if is_pending(r)],'open':[r for r in rows if is_open(r)],
            'done':[r for r in rows if r['status'] in ('answered','resolved','closed','withdrawn')],'bad':[r for r in rows if r['status']=='unresolved' or core.overdue(r)]}
    return jsonify(cases=[biz_summary(r) for r in groups.get(fil,rows)],counts={k:len(v) for k,v in groups.items()})
@app.route('/api/v1/cases/<int:case_id>',methods=['GET','POST'])
def api_biz_case(case_id):
    co=api_co()
    with conn() as db:
        c=api_my_case(db,co,case_id);msg=''
        if request.method=='POST':
            msg,level=case_act(db,c,api_form())
            if level!='ok':return jsonify(error=msg or '처리할 수 없어요.'),400
        elif c['status']=='forwarded':
            db.execute("UPDATE cases SET status='seen' WHERE id=?",(c['id'],));core.add_event(db,c['id'],'sys','기업이 확인했어요')
        c=api_my_case(db,co,case_id);d=biz_detail(db,c,co)
    return jsonify(dict(d,message=msg))
@app.route('/api/v1/cases/<int:case_id>/draft',methods=['POST'])
def api_biz_draft(case_id):
    co=api_co()
    if core.throttled('draft',limit=30,minutes=10):return jsonify(error='잠시 후 다시 시도해 주세요'),429
    with conn() as db:c=api_my_case(db,co,case_id);res=drafting.draft(db,c,co)
    return jsonify(res)
@app.route('/api/v1/cases/<int:case_id>/files/<int:file_id>')
def api_biz_file(case_id,file_id):
    co=api_co()
    with conn() as db:c=api_my_case(db,co,case_id);f=db.execute('SELECT * FROM files WHERE id=? AND case_id=?',(file_id,c['id'])).fetchone()
    if not f:abort(404)
    return send_file(core.UPLOAD/f['stored'],download_name=f['original'])
@app.route('/api/v1/approve_many',methods=['POST'])
def api_biz_approve_many():
    co=api_co();cat=api_form().get('category')
    if cat not in core.CATS:return jsonify(error='유형을 확인해 주세요.'),400
    n=0
    with conn() as db:
        for c in [r for r in my_cases(db,co) if is_pending(r) and r['category']==cat]:
            done=core.run_playbook(db,c,'approved')
            if done is None:continue
            if done:notify_consumer(c,f'[{core.CNAME}] 기업 답변이 도착했어요',f"{c['company_name']}이(가) 답변했어요.")
            n+=1
    return jsonify(approved=n,message=f'{cat} {n}건을 승인했습니다' if n else f'{cat}은(는) 미리 정한 답변이 없어요. 요청을 열어 답변을 직접 적어 주세요.')
@app.route('/api/v1/push',methods=['POST'])
def api_biz_push():
    """사장님 앱 알림 토큰 등록. 같은 휴대폰은 마지막에 로그인한 회사로 옮겨진다."""
    co=api_co();t=clean(api_form().get('push_token'),200)
    if not t.startswith('ExponentPushToken['):return jsonify(error='알림 토큰을 확인해 주세요.'),400
    with conn() as db:db.execute('INSERT INTO biz_push(token,company_id,created) VALUES(?,?,?) ON CONFLICT(token) DO UPDATE SET company_id=excluded.company_id,created=excluded.created',(t,co['id'],core.iso()))
    return jsonify(ok=True)
@app.route('/api/v1/logout',methods=['POST'])
def api_biz_logout():
    """로그아웃하면 이 휴대폰으로 더는 알림을 보내지 않는다."""
    co=api_co();t=clean(api_form().get('push_token'),200)
    if t:
        with conn() as db:db.execute('DELETE FROM biz_push WHERE token=? AND company_id=?',(t,co['id']))
    return jsonify(ok=True)

# 앱 안에서 가입 신청·비밀번호 찾기·규칙·통계·설정·응대 가이드까지 (웹으로 나가지 않게)
@app.route('/api/v1/signup',methods=['POST'])
def api_biz_signup():
    d,err,cid=signup_apply(api_form())
    if err:return jsonify(error=err),400
    with conn() as db:co=core.company(db,cid)
    funnel.track('signup',cid,'app')
    return jsonify(ok=True,name=d['name'],token=co_token(co),company=co_info(co),verified=bool(co['member']),
        message='가입했어요. 바로 쓸 수 있어요. 로그인 이메일 확인과 사업자 확인이 끝나면 소비자 접수와 판매처 연결이 열려요.')
@app.route('/api/v1/forgot',methods=['POST'])
def api_biz_forgot():
    msg,level=send_reset(api_form().get('login_id'))
    if level!='ok':return jsonify(error=msg),400
    return jsonify(ok=True,message=msg)
def rules_json(db,co):
    since=core.now().strftime('%Y-%m-01')
    chat={o:db.execute('SELECT COUNT(*) FROM chat_log WHERE company_id=? AND outcome=? AND created>=?',(co['id'],o,since)).fetchone()[0] for o in ('asked','solved','filed')}
    return dict(rules=[dict(category=cat,cond_ok=cat in COND_CATS,**core.rule_for(db,co['id'],cat)) for cat in core.CATS],
        conds=[dict(value=k,label=v) for k,v in core.COND.items()],chat=chat,link=core.site_url('me','/to/%d'%co['id']))
@app.route('/api/v1/rules',methods=['GET','POST'])
def api_biz_rules():
    co=api_co()
    with conn() as db:
        if request.method=='POST' and not save_rule(db,co,api_form()):return jsonify(error='유형을 확인해 주세요.'),400
        d=rules_json(db,co)
    return jsonify(dict(d,message='저장했습니다' if request.method=='POST' else ''))
def products_json(db,co):
    return dict(products=[dict(id=p['id'],name=p['name'],price=p['price'],stock=p['stock'],info=p['info']) for p in core.products(db,co['id'])],
        stocks=[dict(value=k,label=v) for k,v in core.STOCKS.items()],ai=chatbot.ready())
@app.route('/api/v1/products',methods=['GET','POST'])
def api_biz_products():
    co=api_co();msg=''
    with conn() as db:
        if request.method=='POST':
            msg,level=save_product(db,co,api_form())
            if level!='ok':return jsonify(error=msg),400
        d=products_json(db,co)
    return jsonify(dict(d,message=msg))
def orders_meta():
    return dict(groups=[dict(key=k,label=l) for k,l,_ in orders_mod.GROUPS],statuses=[dict(value=k,label=v) for k,v in orders_mod.STATUS.items()],channels=orders_mod.CHANNELS)
@app.route('/api/v1/orders',methods=['GET','POST'])
def api_biz_orders():
    co=api_co();g=request.args.get('g','all');q=clean(request.args.get('q'),40);msg=''
    with conn() as db:
        if request.method=='POST':
            msg,level,oid=orders_mod.save(db,co,api_form())
            if level!='ok':return jsonify(error=msg),400
        rows=orders_mod.orders(db,co['id'],g,q);cnt=orders_mod.counts(db,co['id'])
    return jsonify(orders=[orders_mod.as_dict(o) for o in rows],counts=cnt,message=msg,**orders_meta())
@app.route('/api/v1/orders/<int:oid>',methods=['GET','POST'])
def api_biz_order(oid):
    co=api_co();msg=''
    with conn() as db:
        if not orders_mod.order(db,co['id'],oid):abort(404)
        if request.method=='POST':
            f=api_form()
            if f.get('act')=='delete':orders_mod.delete(db,co,oid);return jsonify(ok=True,message='주문을 지웠어요')
            msg,level,_=orders_mod.save(db,co,f,oid)
            if level!='ok':return jsonify(error=msg),400
        o=orders_mod.order(db,co['id'],oid);cs=orders_mod.cases_for(db,o)
    return jsonify(dict(orders_mod.as_dict(o),cases=[biz_summary(c) for c in cs],message=msg,**orders_meta()))
@app.route('/api/v1/stats')
def api_biz_stats():
    co=api_co()
    with conn() as db:s=stats_data(db,co)
    cmp=s['cmp']
    if cmp and cmp.get('ready'):cmp=dict(ready=True,peers=cmp['peers'],mine={k:cmp['mine'][k] for k in ('n','auto','res','reply_h')},avg=cmp['avg'])
    return jsonify(kpi=s['k'],reply_h=s['reply_h'],cats=[dict(label=c,n=n,pct=p) for c,n,p in s['cats']],how=[dict(label=c,n=n,pct=p) for c,n,p in s['how']],
        weeks=[dict(label=w,n=n) for w,n in s['weeks']],compare=cmp)
def settings_json(co):
    return dict(name=co['name'],login_id=co['login_id'],contact=co['contact'] or '',notify_email=co['notify_email'] or '',industry=co['industry'] or '',tone=co['tone'] or 'polite',
        return_address=co['return_address'] or '',return_courier=co['return_courier'] or '',return_memo=co['return_memo'] or '',
        phone=co['phone'] or '',kakao=bool(co['kakao']),report_mail=bool(co['report_mail']),kakao_ready=core.kakao_ready(),return_guide=core.return_guide(co),
        industries=core.INDUSTRIES,tones=[dict(value=k,label=v) for k,v in core.TONES.items()],couriers=list(core.COURIERS))
@app.route('/api/v1/settings',methods=['GET','POST'])
def api_biz_settings():
    co=api_co();out={}
    if request.method=='POST':
        f=api_form()
        with conn() as db:msg,level=save_settings(db,co,f);co=core.company(db,co['id'])
        if level!='ok':return jsonify(error=msg),400
        out['message']=msg
        if f.get('act')=='password':out['token']=co_token(co)  # 예전 토큰은 못 쓰게 되니 새 토큰을 준다
    return jsonify(dict(settings_json(co),**out))
@app.route('/api/v1/guide')
def api_biz_guide():
    api_co()
    def law_item(ref):
        c=law.cite(ref);return dict(label=c['label'],title=c['title'],source=c['source'],
            text='\n'.join(((p['n']+' ') if p['n'] else '')+p['text']+''.join('\n  '+i['n']+'. '+i['text'] for i in p['items']) for p in c['paras']))
    return jsonify(guide=[dict(id=x['id'],title=x['title'],points=[dict(text=t,label=law.cite(r)['label']) for t,r in x['points']],sample=x['sample'],laws=[law_item(r) for r in x['refs']]) for x in law.GUIDE],
        kca=law.KCA_STANDARD,sources=law.sources())
@app.route('/api/v1/new',methods=['GET','POST'])
def api_biz_new():
    co=api_co()
    if request.method=='GET':return jsonify(channels=core.CHANNELS,cats=core.CATS,wants=core.WANTS,hints=core.CAT_HINT)
    d,err,cid=new_case_apply(co,api_form())
    if err:return jsonify(error=err),400
    return jsonify(ok=True,id=cid,message='등록했습니다')
@app.route('/api/v1/cases/<int:case_id>/record')
def api_biz_record(case_id):
    """처리 기록 한 장(HTML). 앱이 PDF로 만들어 저장·공유한다."""
    co=api_co()
    with conn() as db:c=api_my_case(db,co,case_id);ev=core.events(db,c['id']);fl=core.case_files(db,c['id'])
    return jsonify(no=c['no'],html=render_template('b_record.html',c=c,ev=ev,files=fl,laws=law.for_case(c),chk=law.check(c),printed=core.iso(),app=True))
@app.route('/api/v1/report')
def api_biz_report():
    co=api_co();today=datetime.date.today();months=[];y,m=today.year,today.month
    for _ in range(12):months.append((y,m));y,m=(y,m-1) if m>1 else (y-1,12)
    try:y,m=map(int,request.args.get('ym','').split('-'));assert (y,m) in months
    except Exception:y,m=insights.prev_month(today)
    with conn() as db:s=insights.monthly(db,co,y,m)
    return jsonify(ym=f'{y}-{m:02d}',months=[f'{a}-{b:02d}' for a,b in months],n=s['n'],prev_n=s['prev_n'],auto=s['auto'],res=s['res'],reply_h=s['reply_h'],late=s['late'],
        cats=[dict(label=c,n=n) for c,n in s['cats']],top_products=[dict(label=p,n=n) for p,n in s['top_products']],by_channel=[dict(label=c,n=n) for c,n in s['by_channel']],
        text=insights.report_text(co,s))
@app.route('/api/v1/news')
def api_biz_news():
    api_co()
    with conn() as db:rows=db.execute('SELECT * FROM news ORDER BY id DESC LIMIT 100').fetchall()
    return jsonify(news=[dict(id=r['id'],title=r['title'],body=r['body'],source_url=r['source_url'],created=r['created']) for r in rows])
@app.route('/api/v1/leave',methods=['POST'])
def api_biz_leave():
    """회원 탈퇴 요청. 진행 중인 요청 기록이 있어 운영팀이 확인하고 처리한다."""
    co=api_co()
    if not check_password_hash(co['pw_hash'],api_form().get('password','')):return jsonify(error='비밀번호가 맞지 않습니다.'),400
    core.send_mail(os.getenv('OPS_EMAIL',''),f"[{core.CNAME} 운영] 기업 탈퇴 요청: {co['name']}",f"{co['name']} ({co['login_id']})이 앱에서 탈퇴를 요청했습니다.\n{core.site_url('biz','/ops/companies')}")
    return jsonify(ok=True,message='탈퇴 요청을 받았습니다. 처리되면 이메일로 알려 드립니다.')

@app.errorhandler(401)
def unauth(e):
    if request.path.startswith('/api/'):return jsonify(error='다시 로그인해 주세요.'),401
    return redirect(url_for('login'))
@app.errorhandler(400)
def bad(e):return core.bad_request()
@app.errorhandler(404)
def nf(e):
    if request.path.startswith('/api/'):return jsonify(error='찾을 수 없어요.'),404
    return render_template('c_error.html',msg='페이지를 찾을 수 없어요.'),404
