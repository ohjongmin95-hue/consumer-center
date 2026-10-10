"""기업용 SOBORU Business (+ 센터 운영 화면 /ops).

기업: 가입 → 운영자 승인 → 로그인 → 승인 카드(승인·보류·자료 요청), 전체 민원, 자동 처리 규칙, 설정.
운영자: 기업 가입 승인, 기업 목록, 비입점 기업 민원 처리(전달 시도·회신 기록·피해구제 안내).
"""
import os, re, hmac, functools
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, send_file, g
from werkzeug.security import generate_password_hash, check_password_hash
import core
from core import conn, clean, digits

app=Flask(__name__,static_folder='static',template_folder='templates')
app.jinja_env.globals.update(core.TEMPLATE_GLOBALS,site='biz')
OPS_HASH=os.getenv('OPS_PASSWORD_HASH','')
EMAIL_RE=re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

@app.before_request
def guard():core.check_csrf()

def me():
    if 'co' not in g:
        g.co=None
        if session.get('co_id'):
            with conn() as db:co=core.company(db,session['co_id'])
            if co and co['status']=='active' and co['member']:g.co=co
            else:session.pop('co_id',None)
    return g.co
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
        with conn() as db:n=db.execute("SELECT COUNT(*) FROM cases WHERE company_id=? AND member=1 AND decision='pending' AND status IN ('forwarded','seen')",(co['id'],)).fetchone()[0]
    return {'co':co,'n_pending':n,'is_ops':bool(session.get('ops'))}

def kpis(rows):
    n=len(rows);auto=sum(r['decision']=='auto' for r in rows);res=sum(r['status']=='resolved' for r in rows)
    rated=sum(r['status'] in ('resolved','unresolved') for r in rows);late=sum(core.overdue(r) for r in rows)
    return {'n':n,'auto':round(auto/n*100) if n else 0,'res':round(res/rated*100) if rated else None,'late':late}

# ---------- 기업 계정 ----------
@app.route('/signup',methods=['GET','POST'])
def signup():
    if request.method=='POST':
        f=request.form;d={k:clean(f.get(k),n) for k,n in (('name',40),('biz_no',20),('owner_name',20),('phone',20),('login_id',80),('contact',60))}
        pw=f.get('password','');err=''
        if not d['name']:err='회사 이름을 적어 주세요.'
        elif len(digits(d['biz_no']))!=10:err='사업자등록번호 10자리를 적어 주세요.'
        elif not d['owner_name']:err='대표자 이름을 적어 주세요.'
        elif not EMAIL_RE.match(d['login_id']):err='로그인에 쓸 이메일을 정확히 적어 주세요.'
        elif len(pw)<10:err='비밀번호는 10자 이상으로 정해 주세요.'
        elif f.get('terms')!='1':err='이용약관에 동의해 주세요.'
        elif core.throttled('signup',limit=5,minutes=60):err='잠시 후 다시 시도해 주세요.'
        if not err:
            with conn() as db:
                if db.execute('SELECT 1 FROM companies WHERE lower(login_id)=lower(?)',(d['login_id'],)).fetchone():err='이미 가입된 이메일이에요.'
                else:
                    db.execute("INSERT INTO companies(name,member,status,contact,login_id,pw_hash,biz_no,owner_name,phone,notify_email,created) VALUES(?,0,'pending',?,?,?,?,?,?,?,?)",
                        (d['name'],d['contact'],d['login_id'].lower(),generate_password_hash(pw),digits(d['biz_no']),d['owner_name'],digits(d['phone']),d['login_id'].lower(),core.iso()))
            if not err:
                core.send_mail(os.getenv('OPS_EMAIL',''),f"[SOBORU] 기업 가입 신청: {d['name']}",f"{d['name']} ({d['owner_name']})이 가입을 신청했어요.\n{core.site_url('biz','/ops/companies')}")
                return render_template('b_signup_done.html',name=d['name'])
        flash(err,'error');return render_template('b_signup.html',d=d),400
    return render_template('b_signup.html',d={})

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        lid=clean(request.form.get('login_id'),80).lower();pw=request.form.get('password','')
        if core.throttled('login',limit=10,minutes=10):flash('로그인 시도가 너무 많아요. 10분 뒤에 다시 해 주세요.','error');return render_template('b_login.html'),429
        with conn() as db:co=db.execute('SELECT * FROM companies WHERE login_id=?',(lid,)).fetchone()
        if not co or not check_password_hash(co['pw_hash'],pw):flash('이메일이나 비밀번호가 맞지 않아요.','error')
        elif co['status']=='pending':flash('가입 승인을 기다리고 있어요. 승인되면 이메일로 알려 드려요.','error')
        elif co['status']!='active':flash('이용할 수 없는 계정이에요. 센터에 문의해 주세요.','error')
        else:
            session.clear();session['co_id']=co['id'];session.permanent=True
            return redirect(url_for('decide'))
        return render_template('b_login.html'),400
    return render_template('b_login.html')

@app.route('/logout',methods=['POST'])
def logout():session.pop('co_id',None);return redirect(url_for('login'))

# ---------- 기업 화면 ----------
def my_cases(db,co):return db.execute('SELECT * FROM cases WHERE company_id=? AND member=1 ORDER BY id DESC',(co['id'],)).fetchall()
def my_case(db,case_id):
    c=db.execute('SELECT * FROM cases WHERE id=? AND company_id=? AND member=1',(case_id,me()['id'])).fetchone()
    if not c:abort(404)
    return c

@app.route('/')
@login_required
def decide():
    with conn() as db:
        rows=my_cases(db,me())
    pend=[r for r in rows if r['decision']=='pending' and r['status'] in ('forwarded','seen')]
    return render_template('b_decide.html',pend=pend,k=kpis(rows),tab='decide')

@app.route('/all')
@login_required
def all_cases():
    fil=request.args.get('f','all')
    with conn() as db:rows=my_cases(db,me())
    groups={'all':rows,'open':[r for r in rows if r['status'] in ('forwarded','seen','info')],'done':[r for r in rows if r['status'] in ('answered','resolved')],
            'bad':[r for r in rows if r['status']=='unresolved' or core.overdue(r)]}
    if fil not in groups:fil='all'
    return render_template('b_all.html',groups=groups,fil=fil,rows=groups[fil],tab='all')

def notify_consumer(c,subject,text):
    core.send_mail(c['email'],subject,f"{text}\n\n■ 접수번호: {c['no']}\n■ 요약: {c['title']}\n\n{core.site_url('me','/mine')}")

@app.route('/case/<int:case_id>',methods=['GET','POST'])
@login_required
def case(case_id):
    with conn() as db:
        c=my_case(db,case_id)
        if request.method=='POST':
            act=request.form.get('act');open_=c['status'] not in ('resolved','unresolved')
            if not open_:abort(400)
            if act=='approve' and c['decision'] not in ('approved','auto'):
                if core.run_playbook(db,c,'approved'):notify_consumer(c,'[한큐 민원] 기업 답변이 도착했어요',f"{c['company_name']}이(가) 답변했어요.")
                flash('승인했어요','ok')
            elif act=='hold':
                db.execute("UPDATE cases SET decision='hold',status=CASE status WHEN 'forwarded' THEN 'seen' ELSE status END WHERE id=?",(c['id'],))
                core.add_event(db,c['id'],'sys','보류했어요');flash('보류했어요','ok')
            elif act=='ask':
                ask=clean(request.form.get('ask'),300) or ('불량 부분 사진과 주문번호를 보내 주세요.' if c['category']=='제품 불량' else '주문번호와 확인할 수 있는 사진이나 캡처를 보내 주세요.')
                db.execute("UPDATE cases SET decision='info',status='info',info_ask=? WHERE id=?",(ask,c['id']))
                core.add_event(db,c['id'],'co','자료 요청: '+ask);notify_consumer(c,'[한큐 민원] 기업이 자료를 요청했어요',ask);flash('자료를 요청했어요','ok')
            elif act=='reply':
                msg=clean(request.form.get('msg'),3000)
                if not msg:flash('답변 내용을 적어 주세요','error')
                else:
                    db.execute("UPDATE cases SET status='answered',decision=CASE decision WHEN 'pending' THEN 'direct' WHEN '' THEN 'direct' ELSE decision END WHERE id=?",(c['id'],))
                    core.add_event(db,c['id'],'co','답변을 보냈어요',msg);notify_consumer(c,'[한큐 민원] 기업 답변이 도착했어요',f"{c['company_name']}이(가) 답변했어요.");flash('보냈어요','ok')
            return redirect(url_for('case',case_id=case_id))
        if c['status']=='forwarded':
            db.execute("UPDATE cases SET status='seen' WHERE id=?",(c['id'],));core.add_event(db,c['id'],'sys','기업이 확인했어요')
            c=my_case(db,case_id)
        ev=core.events(db,c['id']);fl=core.case_files(db,c['id']);rule=core.rule_for(db,me()['id'],c['category'])
    return render_template('b_case.html',c=c,ev=ev,files=fl,rule=rule,tab='all')

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
            cat=request.form.get('category')
            if cat not in core.CATS:abort(400)
            cur=core.rule_for(db,co['id'],cat)
            auto=cur['auto'] if 'auto' not in request.form else request.form['auto']=='1'
            reply=clean(request.form.get('reply'),2000) if 'reply' in request.form else cur['reply']
            db.execute('INSERT INTO rules(company_id,category,auto,reply) VALUES(?,?,?,?) ON CONFLICT(company_id,category) DO UPDATE SET auto=excluded.auto,reply=excluded.reply',(co['id'],cat,int(auto),reply))
            flash('저장했어요','ok');return redirect(url_for('rules')+('#'+request.form.get('anchor','') if request.form.get('anchor') else ''))
        rs={cat:core.rule_for(db,co['id'],cat) for cat in core.CATS}
    return render_template('b_rules.html',rs=rs,tab='rules')

@app.route('/settings',methods=['GET','POST'])
@login_required
def settings():
    co=me()
    if request.method=='POST':
        f=request.form
        with conn() as db:
            if f.get('act')=='password':
                if not check_password_hash(co['pw_hash'],f.get('old','')):flash('지금 비밀번호가 맞지 않아요','error')
                elif len(f.get('new',''))<10:flash('새 비밀번호는 10자 이상이에요','error')
                else:db.execute('UPDATE companies SET pw_hash=? WHERE id=?',(generate_password_hash(f['new']),co['id']));flash('비밀번호를 바꿨어요','ok')
            else:
                email=clean(f.get('notify_email'),80)
                if email and not EMAIL_RE.match(email):flash('알림 이메일을 확인해 주세요','error')
                else:db.execute('UPDATE companies SET contact=?,notify_email=? WHERE id=?',(clean(f.get('contact'),60),email,co['id']));flash('저장했어요','ok')
        return redirect(url_for('settings'))
    return render_template('b_settings.html',tab='settings')

# ---------- 센터 운영 ----------
@app.route('/ops/login',methods=['GET','POST'])
def ops_login():
    if request.method=='POST':
        if core.throttled('ops',limit=8,minutes=10):flash('잠시 후 다시 시도해 주세요','error')
        elif OPS_HASH and check_password_hash(OPS_HASH,request.form.get('password','')):
            session.clear();session['ops']=True;return redirect(url_for('ops'))
        else:flash('비밀번호가 맞지 않아요','error')
    return render_template('o_login.html')
@app.route('/ops/logout',methods=['POST'])
def ops_logout():session.pop('ops',None);return redirect(url_for('ops_login'))

@app.route('/ops')
@ops_required
def ops():
    with conn() as db:
        rows=db.execute('SELECT * FROM cases WHERE member=0 ORDER BY CASE WHEN status IN (\'received\',\'forwarded\') THEN 0 ELSE 1 END,id DESC LIMIT 300').fetchall()
        n_pending=db.execute("SELECT COUNT(*) FROM companies WHERE status='pending'").fetchone()[0]
    return render_template('o_home.html',rows=rows,n_signup=n_pending,otab='non')

@app.route('/ops/all')
@ops_required
def ops_all():
    with conn() as db:rows=db.execute('SELECT * FROM cases ORDER BY id DESC LIMIT 500').fetchall();n_pending=db.execute("SELECT COUNT(*) FROM companies WHERE status='pending'").fetchone()[0]
    return render_template('o_all.html',rows=rows,k=kpis(rows),n_signup=n_pending,otab='all')

@app.route('/ops/case/<int:case_id>',methods=['GET','POST'])
@ops_required
def ops_case(case_id):
    with conn() as db:
        c=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        if not c:abort(404)
        if request.method=='POST':
            act=request.form.get('act')
            if c['member'] or c['status'] in ('resolved','unresolved'):abort(400)
            if act=='attempt' and c['consent']:
                ch=request.form.get('channel') if request.form.get('channel') in ('이메일','전화','1:1 문의','우편') else '이메일'
                db.execute("UPDATE cases SET status='forwarded',attempts=attempts+1 WHERE id=?",(c['id'],))
                core.add_event(db,c['id'],'sys',f'센터가 {ch}(으)로 기업에 전달했어요');flash('기록했어요','ok')
            elif act=='reply' and clean(request.form.get('msg'),3000):
                db.execute("UPDATE cases SET status='answered' WHERE id=?",(c['id'],))
                core.add_event(db,c['id'],'co','기업 회신 (센터 기록)',clean(request.form.get('msg'),3000))
                notify_consumer(c,'[한큐 민원] 기업 회신이 도착했어요',f"{c['company_name']}의 회신을 센터가 기록했어요.");flash('기록했어요','ok')
            elif act=='unresolved':
                db.execute("UPDATE cases SET status='unresolved' WHERE id=?",(c['id'],))
                core.add_event(db,c['id'],'sys','기업 회신이 없어 공식 피해구제 절차(1372 소비자상담센터, 한국소비자원)를 안내했어요')
                notify_consumer(c,'[한큐 민원] 피해구제 절차를 안내해 드려요','기업 회신이 없어 공식 피해구제 절차를 안내해 드려요. 민원 화면에서 확인해 주세요.');flash('안내했어요','ok')
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
            if act=='approve' and co and co['status']=='pending':
                # 같은 이름의 비입점 기업이 있으면 그 민원을 이 기업으로 옮김 (이후 민원부터 입점 처리)
                old=db.execute("SELECT id FROM companies WHERE status='listed' AND lower(name)=lower(?)",(co['name'],)).fetchall()
                for o in old:db.execute('UPDATE cases SET company_id=? WHERE company_id=?',(co['id'],o['id']));db.execute('DELETE FROM companies WHERE id=?',(o['id'],))
                db.execute("UPDATE companies SET status='active',member=1 WHERE id=?",(co['id'],))
                core.send_mail(co['notify_email'],'[SOBORU Business] 가입이 승인됐어요',f"{co['name']}의 SOBORU Business 가입이 승인됐어요.\n{core.site_url('biz','/login')}")
                flash(f"{co['name']} 승인했어요",'ok')
            elif act=='reject' and co and co['status']=='pending':db.execute("UPDATE companies SET status='rejected' WHERE id=?",(co['id'],));flash('반려했어요','ok')
            elif act=='suspend' and co and co['status']=='active':db.execute("UPDATE companies SET status='suspended',member=0 WHERE id=?",(co['id'],));flash('이용을 중지했어요','ok')
            elif act=='resume' and co and co['status']=='suspended':db.execute("UPDATE companies SET status='active',member=1 WHERE id=?",(co['id'],));flash('다시 이용할 수 있게 했어요','ok')
            elif act=='contact' and co:db.execute('UPDATE companies SET contact=? WHERE id=?',(clean(request.form.get('contact'),60),co['id']));flash('저장했어요','ok')
            elif act=='add':
                name=clean(request.form.get('name'),40)
                if name and not core.find_company(db,name):db.execute("INSERT INTO companies(name,member,status,contact,created) VALUES(?,0,'listed',?,?)",(name,clean(request.form.get('contact'),60),core.iso()));flash('추가했어요','ok')
                else:flash('이름이 비었거나 이미 있어요','error')
            return redirect(url_for('ops_companies'))
        pending=db.execute("SELECT * FROM companies WHERE status='pending' ORDER BY id").fetchall()
        rows=db.execute("SELECT c.*,(SELECT COUNT(*) FROM cases WHERE company_id=c.id) n FROM companies c WHERE status IN ('active','listed','suspended') ORDER BY member DESC,name").fetchall()
    return render_template('o_companies.html',pending=pending,rows=rows,n_signup=len(pending),otab='co')

@app.errorhandler(404)
def nf(e):return render_template('c_error.html',msg='페이지를 찾을 수 없어요.'),404
