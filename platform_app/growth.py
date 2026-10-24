"""추천 코드와 파트너(대행사) 프로그램 (Gorgias의 Referral·Partner program에 해당).

  · 가입한 회사마다 추천 링크(/r/코드)가 생긴다. 그 링크로 들어와 가입한 회사 수·인증 수·실제 사용 수만 보여 준다.
  · 파트너(쇼핑몰 운영 대행사·컨설턴트)는 공개 화면에서 신청하고, SOBORU CS 운영자가 승인하면 파트너 화면에 로그인한다.
    파트너 화면에서는 자기 링크로 가입한 회사의 가입·인증·설정·사용량만 본다. 그 회사의 고객 정보와 문의 내용은 볼 수 없다.
  · 추천 보상·수수료·금전 지급은 만들지 않는다 (요금제가 생긴 뒤 별도로 정한다).
"""
import datetime, re, secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session, g
from werkzeug.security import generate_password_hash, check_password_hash
import core, funnel
from core import conn, clean, digits

bp=Blueprint('gr',__name__)
EMAIL_RE=re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
CODE_CHARS='abcdefghjkmnpqrstuvwxyz23456789'
KINDS=['쇼핑몰 운영 대행사','마케팅 대행사','컨설턴트·교육','솔루션·개발사','기타']
PSTATUS={'applied':'신청','approved':'승인','rejected':'거절','suspended':'중지'}
MAX_PSTAFF=10
INVITE_HOURS=72

def init():
    with conn() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS partners(id INTEGER PRIMARY KEY,name TEXT NOT NULL,biz_no TEXT NOT NULL DEFAULT '',kind TEXT NOT NULL DEFAULT '',
              contact TEXT NOT NULL,email TEXT NOT NULL,phone TEXT NOT NULL DEFAULT '',site TEXT NOT NULL DEFAULT '',intro TEXT NOT NULL DEFAULT '',clients TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'applied',code TEXT UNIQUE,memo TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,decided TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS partner_users(id INTEGER PRIMARY KEY,partner_id INTEGER NOT NULL,email TEXT NOT NULL,name TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'staff',
              pw_hash TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'invited',created TEXT NOT NULL,last_login TEXT NOT NULL DEFAULT '');
            CREATE UNIQUE INDEX IF NOT EXISTS partner_users_email ON partner_users(lower(email)) ;
            CREATE TABLE IF NOT EXISTS ref_clicks(id INTEGER PRIMARY KEY,code TEXT NOT NULL,visitor TEXT NOT NULL,day TEXT NOT NULL,UNIQUE(code,visitor,day));''')
        cols={r[1] for r in db.execute('PRAGMA table_info(companies)')}
        for col,ddl in (('ref_code','TEXT'),('referred_by','INTEGER NOT NULL DEFAULT 0'),('partner_id','INTEGER NOT NULL DEFAULT 0')):
            if col not in cols:db.execute(f'ALTER TABLE companies ADD COLUMN {col} {ddl}')
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS companies_ref_code ON companies(ref_code) WHERE ref_code IS NOT NULL')
init()

def new_code(db):
    while True:
        c=''.join(secrets.choice(CODE_CHARS) for _ in range(7))
        if not db.execute('SELECT 1 FROM companies WHERE ref_code=?',(c,)).fetchone() and not db.execute('SELECT 1 FROM partners WHERE code=?',('p'+c,)).fetchone():return c
def code_of(db,co):
    """회사 추천 코드 (처음 볼 때 만든다)."""
    if co['ref_code']:return co['ref_code']
    c=new_code(db);db.execute('UPDATE companies SET ref_code=? WHERE id=?',(c,co['id']));return c
def link(code):return core.site_url('biz','/r/'+code) or url_for('gr.ref',code=code,_external=True)

def owner_of(db,code):
    """코드 -> ('company'|'partner', 행). 쓸 수 없는 코드면 (None,None)."""
    if code.startswith('p'):
        p=db.execute("SELECT * FROM partners WHERE code=? AND status='approved'",(code,)).fetchone()
        if p:return 'partner',p
    co=db.execute("SELECT * FROM companies WHERE ref_code=? AND status='active'",(code,)).fetchone()
    return ('company',co) if co else (None,None)

@bp.route('/r/<code>')
def ref(code):
    code=code.lower()[:12]
    with conn() as db:
        kind,row=owner_of(db,code)
        if kind:
            session['ref']=code
            db.execute('INSERT OR IGNORE INTO ref_clicks(code,visitor,day) VALUES(?,?,?)',(code,funnel.visitor(),core.now().date().isoformat()))
    if kind:funnel.visit()
    return redirect(url_for('signup'))

def attach(db,cid):
    """가입한 회사에 추천한 곳을 이어 붙인다 (onboard.signup에서 부른다). 자기 자신은 안 된다."""
    code=session.get('ref') if core.has_request_context() else None
    if not code:return
    kind,row=owner_of(db,code)
    if kind=='partner':db.execute('UPDATE companies SET partner_id=? WHERE id=?',(row['id'],cid))
    elif kind=='company' and row['id']!=cid and row['biz_no']!=(core.company(db,cid) or {'biz_no':''})['biz_no']:
        db.execute('UPDATE companies SET referred_by=? WHERE id=?',(row['id'],cid))
    session.pop('ref',None)

def usage(db,ids,days=30):
    """회사별 사용량: 받은 문의·답한 문의 (지난 days일). 문의 내용·고객 정보는 꺼내지 않는다."""
    if not ids:return {}
    since=core.iso(core.now()-datetime.timedelta(days=days));q=','.join('?'*len(ids))
    got={r[0]:r[1] for r in db.execute(f"SELECT company_id,COUNT(*) FROM cases WHERE company_id IN ({q}) AND created>=? AND import_batch=0 AND title NOT LIKE '[시험 문의]%' GROUP BY company_id",ids+[since])}
    rep={r[0]:r[1] for r in db.execute(f"""SELECT c.company_id,COUNT(DISTINCT c.id) FROM cases c JOIN events e ON e.case_id=c.id AND e.kind='co' AND e.created>=?
        WHERE c.company_id IN ({q}) AND c.import_batch=0 GROUP BY c.company_id""",[since]+ids)}
    return {i:(got.get(i,0),rep.get(i,0)) for i in ids}

def stats(db,where,args,code):
    """추천 결과 요약 (실제 기록만)."""
    rows=db.execute(f"SELECT * FROM companies WHERE {where} AND status IN ('active','suspended') ORDER BY id DESC",args).fetchall()
    use=usage(db,[r['id'] for r in rows])
    clicks=db.execute('SELECT COUNT(*) FROM ref_clicks WHERE code=?',(code,)).fetchone()[0] if code else 0
    return {'rows':rows,'use':use,'clicks':clicks,'signups':len(rows),'verified':sum(1 for r in rows if r['member']),'using':sum(1 for r in rows if use.get(r['id'],(0,0))[1])}

def company_page_data(db,co):
    c=code_of(db,co)
    return dict(code=c,link=link(c),partner=partner_of(db,co),**stats(db,'referred_by=?',(co['id'],),c))

# ---------- 파트너 신청 (공개) ----------
@bp.route('/partners',methods=['GET','POST'])
def apply():
    d={};done=False;err=''
    if request.method=='POST':
        f=request.form
        d={k:clean(f.get(k),n) for k,n in (('name',60),('biz_no',12),('kind',30),('contact',30),('email',80),('phone',20),('site',200),('intro',2000),('clients',30))}
        d['email']=d['email'].lower()
        if f.get('website'):return render_template('g_partners.html',d={},done=True,KINDS=KINDS,tab='gr.apply')  # 봇
        if not d['name'] or not d['contact']:err='회사명과 담당자를 적어 주세요.'
        elif not EMAIL_RE.match(d['email']):err='이메일을 정확히 적어 주세요.'
        elif d['kind'] not in KINDS:err='어떤 일을 하는 곳인지 골라 주세요.'
        elif d['biz_no'] and len(digits(d['biz_no']))!=10:err='사업자등록번호 10자리를 확인해 주세요.'
        elif str(f.get('privacy'))!='1':err='개인정보 수집·이용에 동의해 주세요.'
        elif core.throttled('partner_apply',limit=5,minutes=60):err='잠시 후 다시 시도해 주세요.'
        if not err:
            with conn() as db:
                if db.execute("SELECT 1 FROM partners WHERE lower(email)=? AND status IN ('applied','approved')",(d['email'],)).fetchone():err='이미 신청했거나 승인된 이메일이에요. 확인 중이면 조금만 기다려 주세요.'
                else:
                    db.execute('INSERT INTO partners(name,biz_no,kind,contact,email,phone,site,intro,clients,created) VALUES(?,?,?,?,?,?,?,?,?,?)',
                               (d['name'],digits(d['biz_no']),d['kind'],d['contact'],d['email'],digits(d['phone']),d['site'],d['intro'],d['clients'],core.iso()))
            if not err:
                import os
                core.send_mail(os.getenv('OPS_EMAIL',''),f"[{core.BNAME} 운영] 파트너 신청: {d['name']}",f"{d['name']} ({d['kind']}, {d['contact']})\n{core.site_url('biz','/ops/partners')}")
                core.send_mail(d['email'],f'[{core.BNAME}] 파트너 신청을 받았어요',f"{d['contact']}님, {d['name']}의 파트너 신청을 받았어요.\n확인한 뒤 이메일로 결과를 알려 드릴게요.")
                done=True
        if err:flash(err,'error')
    return render_template('g_partners.html',d=d,done=done,KINDS=KINDS,tab='gr.apply'),(400 if err else 200)

# ---------- 파트너 로그인·화면 ----------
def puser():
    if 'puser' not in g:
        g.puser=None
        uid=session.get('partner_uid')
        if uid:
            with conn() as db:
                u=db.execute("SELECT u.*,p.name pname,p.code,p.status pstatus FROM partner_users u JOIN partners p ON p.id=u.partner_id WHERE u.id=? AND u.status='active'",(uid,)).fetchone()
            if u and u['pstatus']=='approved':g.puser=u
            else:session.pop('partner_uid',None)
    return g.puser
def partner_required(f):
    import functools
    @functools.wraps(f)
    def w(*a,**k):
        if not puser():return redirect(url_for('gr.plogin'))
        return f(*a,**k)
    return w

@bp.route('/partner/login',methods=['GET','POST'])
def plogin():
    if request.method=='POST':
        email=clean(request.form.get('email'),80).lower();pw=request.form.get('password','')
        if core.throttled('plogin:'+email,limit=10,minutes=15):flash('잠시 후 다시 시도해 주세요.','error')
        else:
            with conn() as db:
                u=db.execute("SELECT u.*,p.status pstatus FROM partner_users u JOIN partners p ON p.id=u.partner_id WHERE lower(u.email)=? AND u.status='active'",(email,)).fetchone()
                if u and u['pw_hash'] and check_password_hash(u['pw_hash'],pw) and u['pstatus']=='approved':
                    db.execute('UPDATE partner_users SET last_login=? WHERE id=?',(core.iso(),u['id']))
                    session['partner_uid']=u['id'];session.permanent=True;return redirect(url_for('gr.dashboard'))
            flash('이메일이나 비밀번호가 맞지 않아요.','error')
    return render_template('g_login.html',tab='gr.plogin')
@bp.route('/partner/logout',methods=['POST'])
def plogout():
    session.pop('partner_uid',None);return redirect(url_for('gr.plogin'))

def invite_link(u):return core.site_url('biz','/partner/join/'+core.signer('pjoin').dumps({'id':u['id'],'h':(u['pw_hash'] or 'new')[-12:]})) or url_for('gr.pjoin',tok=core.signer('pjoin').dumps({'id':u['id'],'h':(u['pw_hash'] or 'new')[-12:]}),_external=True)
def send_invite(u,pname):
    lk=invite_link(u)
    core.send_mail(u['email'],f'[{core.BNAME}] {pname} 파트너 화면 초대',f"{u['name']}님, {pname}의 {core.BNAME} 파트너 화면에 초대했어요.\n아래 링크에서 비밀번호를 정하면 바로 쓸 수 있어요. {INVITE_HOURS}시간 동안 열려요.\n{lk}")
    return lk
@bp.route('/partner/join/<tok>',methods=['GET','POST'])
def pjoin(tok):
    try:d=core.signer('pjoin').loads(tok,max_age=INVITE_HOURS*3600)
    except Exception:d=None
    with conn() as db:
        u=db.execute("SELECT u.*,p.name pname,p.status pstatus FROM partner_users u JOIN partners p ON p.id=u.partner_id WHERE u.id=? AND u.status!='removed'",((d or {}).get('id'),)).fetchone() if d else None
        if not u or (u['pw_hash'] or 'new')[-12:]!=d.get('h') or u['pstatus']!='approved':
            return render_template('g_login.html',bad_link=True,tab='gr.plogin'),400
        if request.method=='POST':
            pw=request.form.get('password','')
            if len(pw)<10:flash('비밀번호는 10자 이상으로 정해 주세요.','error')
            else:
                db.execute("UPDATE partner_users SET pw_hash=?,status='active' WHERE id=?",(generate_password_hash(pw),u['id']))
                session['partner_uid']=u['id'];session.permanent=True;flash('비밀번호를 정했어요','ok');return redirect(url_for('gr.dashboard'))
    return render_template('g_join.html',u=u,tab='gr.plogin')

@bp.route('/partner',methods=['GET','POST'])
@partner_required
def dashboard():
    u=puser()
    with conn() as db:
        if request.method=='POST':
            if u['role']!='owner':abort(403)
            act=request.form.get('act')
            if act=='invite':
                email=clean(request.form.get('email'),80).lower();name=clean(request.form.get('name'),30)
                n=db.execute("SELECT COUNT(*) FROM partner_users WHERE partner_id=? AND status!='removed'",(u['partner_id'],)).fetchone()[0]
                if not EMAIL_RE.match(email) or not name:flash('직원 이름과 이메일을 적어 주세요','error')
                elif n>=MAX_PSTAFF:flash(f'직원은 {MAX_PSTAFF}명까지예요','error')
                elif db.execute("SELECT 1 FROM partner_users WHERE lower(email)=? AND status!='removed'",(email,)).fetchone():flash('이미 쓰고 있는 이메일이에요','error')
                else:
                    db.execute("DELETE FROM partner_users WHERE lower(email)=? AND status='removed'",(email,))
                    uid=db.execute("INSERT INTO partner_users(partner_id,email,name,role,created) VALUES(?,?,?,'staff',?)",(u['partner_id'],email,name,core.iso())).lastrowid
                    lk=send_invite(db.execute('SELECT * FROM partner_users WHERE id=?',(uid,)).fetchone(),u['pname'])
                    flash(f"{name}님을 초대했어요."+('' if core.mail_ready() else f' 메일을 보낼 수 없어 이 링크를 직접 전해 주세요: {lk}'),'ok')
            elif act=='remove':
                uid=request.form.get('id','')
                if uid.isdigit() and int(uid)!=u['id']:db.execute("UPDATE partner_users SET status='removed',pw_hash='' WHERE id=? AND partner_id=? AND role!='owner'",(int(uid),u['partner_id']));flash('내보냈어요','ok')
            return redirect(url_for('gr.dashboard'))
        s=stats(db,'partner_id=?',(u['partner_id'],),u['code'])
        import onboard
        prog={r['id']:onboard.progress(r) for r in s['rows']}
        team=db.execute("SELECT * FROM partner_users WHERE partner_id=? AND status!='removed' ORDER BY id",(u['partner_id'],)).fetchall()
    return render_template('g_dashboard.html',u=u,s=s,prog=prog,team=team,link=link(u['code']),tab='gr.dashboard')

# ---------- 운영: 파트너 관리 ----------
def ops_guard():
    if not session.get('ops'):return redirect(url_for('ops_login'))
@bp.route('/ops/partners')
def ops_list():
    gd=ops_guard()
    if gd:return gd
    with conn() as db:
        rows=db.execute("SELECT p.*,(SELECT COUNT(*) FROM companies c WHERE c.partner_id=p.id AND c.status IN ('active','suspended')) n FROM partners p ORDER BY CASE status WHEN 'applied' THEN 0 ELSE 1 END,id DESC").fetchall()
        refs=db.execute("""SELECT r.id,r.name,COUNT(c.id) n,SUM(c.member) v FROM companies c JOIN companies r ON r.id=c.referred_by
            WHERE c.status IN ('active','suspended') GROUP BY r.id ORDER BY n DESC LIMIT 20""").fetchall()
    import cms
    return render_template('o_partners.html',rows=rows,refs=refs,PSTATUS=PSTATUS,n_signup=cms.n_waiting(),otab='partners')
@bp.route('/ops/partner/<int:pid>',methods=['GET','POST'])
def ops_partner(pid):
    gd=ops_guard()
    if gd:return gd
    with conn() as db:
        p=db.execute('SELECT * FROM partners WHERE id=?',(pid,)).fetchone()
        if not p:abort(404)
        if request.method=='POST':
            act=request.form.get('act')
            if act=='approve' and p['status'] in ('applied','rejected','suspended'):
                code=p['code'] or 'p'+new_code(db)
                db.execute("UPDATE partners SET status='approved',code=?,decided=? WHERE id=?",(code,core.iso(),pid))
                u=db.execute("SELECT * FROM partner_users WHERE partner_id=? AND role='owner'",(pid,)).fetchone()
                if not u:
                    if db.execute("SELECT 1 FROM partner_users WHERE lower(email)=? AND status!='removed'",(p['email'].lower(),)).fetchone():
                        flash('이 이메일로 이미 다른 파트너 계정이 있어요','error');return redirect(url_for('gr.ops_partner',pid=pid))
                    uid=db.execute("INSERT INTO partner_users(partner_id,email,name,role,created) VALUES(?,?,?,'owner',?)",(pid,p['email'].lower(),p['contact'],core.iso())).lastrowid
                    u=db.execute('SELECT * FROM partner_users WHERE id=?',(uid,)).fetchone()
                lk=send_invite(u,p['name']) if not u['pw_hash'] else ''
                flash('승인했어요.'+(f' 로그인 안내 메일을 보냈어요.' if core.mail_ready() else f' 메일을 보낼 수 없어 이 링크를 직접 전해 주세요: {lk}' if lk else ''),'ok')
            elif act=='reject' and p['status']=='applied':
                db.execute("UPDATE partners SET status='rejected',decided=? WHERE id=?",(core.iso(),pid))
                if request.form.get('mail')=='1':core.send_mail(p['email'],f'[{core.BNAME}] 파트너 신청 결과',f"{p['contact']}님, 이번에는 파트너로 함께하기 어려워요. 신청해 주셔서 고마워요.")
                flash('거절했어요','ok')
            elif act=='suspend' and p['status']=='approved':
                db.execute("UPDATE partners SET status='suspended',decided=? WHERE id=?",(core.iso(),pid));flash('중지했어요. 파트너 화면 로그인과 추천 링크가 멈춰요','ok')
            elif act=='memo':
                db.execute('UPDATE partners SET memo=? WHERE id=?',(clean(request.form.get('memo'),4000),pid));flash('메모를 저장했어요','ok')
            elif act=='resend':
                u=db.execute("SELECT * FROM partner_users WHERE partner_id=? AND role='owner'",(pid,)).fetchone()
                if u and p['status']=='approved':lk=send_invite(u,p['name']);flash('초대 링크를 다시 보냈어요.'+('' if core.mail_ready() else f' 링크: {lk}'),'ok')
            return redirect(url_for('gr.ops_partner',pid=pid))
        s=stats(db,'partner_id=?',(pid,),p['code']) if p['code'] else None
        users=db.execute("SELECT * FROM partner_users WHERE partner_id=? AND status!='removed' ORDER BY id",(pid,)).fetchall()
    import cms
    return render_template('o_partner.html',p=p,s=s,users=users,link=link(p['code']) if p['code'] else '',PSTATUS=PSTATUS,n_signup=cms.n_waiting(),otab='partners')

@bp.route('/settings/partner',methods=['POST'])
def co_partner():
    """이미 가입한 회사가 대행사(파트너)와 함께 쓰겠다고 직접 연결하거나 끊는다. 회사가 직접 해야 파트너가 사용 현황을 본다."""
    if not session.get('co_id'):return redirect(url_for('login'))
    import business
    co=business.real()
    with conn() as db:
        if request.form.get('act')=='unlink':
            db.execute('UPDATE companies SET partner_id=0 WHERE id=?',(co['id'],));flash('파트너 연결을 끊었어요','ok')
        else:
            code=clean(request.form.get('code'),12).lower()
            p=db.execute("SELECT * FROM partners WHERE code=? AND status='approved'",(code,)).fetchone()
            if not p:flash('파트너 코드를 확인해 주세요','error')
            else:db.execute('UPDATE companies SET partner_id=? WHERE id=?',(p['id'],co['id']));flash(f"{p['name']}와 연결했어요. 파트너는 가입·설정·사용 수만 보고 고객 정보는 보지 못해요",'ok')
    return redirect(url_for('settings')+'#partner')
def partner_of(db,co):
    return db.execute('SELECT * FROM partners WHERE id=?',(co['partner_id'],)).fetchone() if co['partner_id'] else None

def nav():return []
def sitemap_paths():return ['/partners']
