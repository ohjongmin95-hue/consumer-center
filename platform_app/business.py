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
from core import conn, clean, digits, BIG

app=Flask(__name__,static_folder='static',template_folder='templates')
app.jinja_env.globals.update(core.TEMPLATE_GLOBALS,site='biz',law_check=law.check,is_direct=core.is_direct)
OPS_HASH=os.getenv('OPS_PASSWORD_HASH','')
# 소개 화면의 앱 받기 버튼: 스토어 주소를 서버 설정(.env)에 넣으면 '곧 출시' 대신 버튼이 나온다
APP_LINKS={'android':os.getenv('BIZ_APP_ANDROID_URL',''),'ios':os.getenv('BIZ_APP_IOS_URL','')}
EMAIL_RE=re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

@app.before_request
def guard():
    if not request.path.startswith(('/api/','/hook/')):core.check_csrf()  # 앱 API는 쿠키 대신 토큰을, 택배 알림은 주소의 서명 토큰을 쓴다
app.after_request(core.copy_after_request('biz'))  # 운영 화면에서 고친 문구 적용
core.track_template(app)

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
        with conn() as db:n=db.execute("SELECT COUNT(*) FROM cases WHERE company_id=? AND member=1 AND consent=1 AND decision='pending' AND status IN ('forwarded','seen')",(co['id'],)).fetchone()[0]
    return {'co':co,'n_pending':n,'is_ops':bool(session.get('ops'))}

def kpis(rows):
    n=len(rows);auto=sum(r['decision']=='auto' for r in rows);res=sum(r['status']=='resolved' for r in rows)
    rated=sum(r['status'] in ('resolved','unresolved') for r in rows);late=sum(core.overdue(r) for r in rows)
    return {'n':n,'auto':round(auto/n*100) if n else 0,'res':round(res/rated*100) if rated else None,'late':late}

# ---------- 기업 계정 ----------
@app.route('/robots.txt')
def robots():return app.response_class(core.robots_txt('biz',['/api','/ops','/case','/all','/rules','/stats','/settings','/new','/guide','/report','/news','/reset']),mimetype='text/plain')

@app.route('/sitemap.xml')
def sitemap():
    body=''.join('<url><loc>%s</loc></url>'%core.site_url('biz',p) for p in ('/','/signup','/login','/terms'))
    return app.response_class('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+body+'</urlset>',mimetype='application/xml')

@app.route('/terms')
def terms():
    return render_template('b_terms.html',op=core.OPERATOR,since=core.TERMS_SINCE,privacy_url=core.site_url('me','/privacy'))

def signup_apply(f):
    """가입 신청 검사와 저장. 웹과 앱이 같이 쓴다. (입력값, 오류 문구)를 돌려주고 문구가 비면 신청이 들어간 것이다."""
    d={k:clean(f.get(k),n) for k,n in (('name',40),('biz_no',20),('owner_name',20),('phone',20),('login_id',80),('contact',60),('industry',20))}
    if d['industry'] not in core.INDUSTRIES:d['industry']=''
    pw=f.get('password','');err=''
    if not d['name']:err='회사 이름을 적어 주세요.'
    elif len(digits(d['biz_no']))!=10:err='사업자등록번호 10자리를 적어 주세요.'
    elif not d['owner_name']:err='대표자 이름을 적어 주세요.'
    elif not EMAIL_RE.match(d['login_id']):err='로그인에 쓸 이메일을 정확히 적어 주세요.'
    elif len(pw)<10:err='비밀번호는 10자 이상으로 정해 주세요.'
    elif str(f.get('terms'))not in ('1','True','true'):err='이용약관에 동의해 주세요.'
    elif core.throttled('signup',limit=5,minutes=60):err='잠시 후 다시 시도해 주세요.'
    if not err:
        with conn() as db:
            if db.execute('SELECT 1 FROM companies WHERE lower(login_id)=lower(?)',(d['login_id'],)).fetchone():err='이미 가입된 이메일이에요.'
            else:
                db.execute("INSERT INTO companies(name,member,status,contact,login_id,pw_hash,biz_no,owner_name,phone,notify_email,industry,created) VALUES(?,0,'pending',?,?,?,?,?,?,?,?,?)",
                    (d['name'],d['contact'],d['login_id'].lower(),generate_password_hash(pw),digits(d['biz_no']),d['owner_name'],digits(d['phone']),d['login_id'].lower(),d['industry'],core.iso()))
        if not err:core.send_mail(os.getenv('OPS_EMAIL',''),f"[{core.CNAME} 운영] 기업 가입 신청: {d['name']}",f"{d['name']} ({d['owner_name']})이 가입을 신청했습니다.\n{core.site_url('biz','/ops/companies')}")
    return d,err
@app.route('/signup',methods=['GET','POST'])
def signup():
    if request.method=='POST':
        d,err=signup_apply(request.form)
        if not err:return render_template('b_signup_done.html',name=d['name'])
        flash(err,'error');return render_template('b_signup.html',d=d),400
    return render_template('b_signup.html',d={})

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='GET' and me():return redirect(url_for('decide'))  # 이미 로그인했으면 홈으로
    if request.method=='POST':
        lid=clean(request.form.get('login_id'),80).lower();pw=request.form.get('password','')
        if core.throttled('login',limit=10,minutes=10):flash('로그인 시도가 너무 많습니다. 10분 뒤에 다시 해 주세요.','error');return render_template('b_login.html'),429
        with conn() as db:co=db.execute('SELECT * FROM companies WHERE login_id=?',(lid,)).fetchone()
        if not co or not check_password_hash(co['pw_hash'],pw):flash('이메일이나 비밀번호가 맞지 않습니다.','error')
        elif co['status']=='pending':flash('가입 승인을 기다리고 있습니다. 승인되면 이메일로 알려 드립니다.','error')
        elif co['status']!='active':flash('이용할 수 없는 계정입니다. 센터에 문의해 주세요.','error')
        else:
            ops=session.get('ops');csrf=session.get('csrf');session.clear();session['co_id']=co['id'];session.permanent=True
            if csrf:session['csrf']=csrf  # 다른 탭에 열어 둔 화면도 그대로 쓸 수 있게
            if ops:session['ops']=True  # 운영 화면 로그인은 그대로 둔다
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
def logout():session.pop('co_id',None);return redirect(url_for('login'))

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
    if not me():return render_template('b_intro.html',app_links=APP_LINKS)  # 로그인 전: 서비스 소개
    with conn() as db:
        rows=my_cases(db,me());n_auto=db.execute('SELECT COUNT(*) FROM rules WHERE company_id=? AND auto=1',(me()['id'],)).fetchone()[0]
        warn=insights.alerts(db,me());news=db.execute('SELECT * FROM news ORDER BY id DESC LIMIT 3').fetchall();comps=core.comp_rules(db,me()['id'])
    pend=[r for r in rows if is_pending(r)]
    counts={'comp':sum(core.comp_pending(r,comps) for r in rows),'all':len(rows),'open':sum(map(is_open,rows)),'late':sum(map(core.overdue,rows)),'auto':n_auto,'ret':sum(r['ret_status']=='sent' for r in rows)}
    return render_template('b_decide.html',pend=pend,recent=rows[:6],k=kpis(rows),counts=counts,cats=by_cat(rows),warn=warn,news=news,link=core.site_url('me','/to/%d'%me()['id']),tab='home')

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
    fil=request.args.get('f','all');q=clean(request.args.get('q'),40)
    with conn() as db:rows=my_cases(db,me());comps=core.comp_rules(db,me()['id'])
    if q:rows=[r for r in rows if q.lower() in (r['title']+' '+r['no']+' '+(r['name'] or '')+' '+r['body']).lower()]
    groups={'all':rows,'open':[r for r in rows if is_open(r)],'done':[r for r in rows if r['status'] in ('answered','resolved','closed','withdrawn')],
            'bad':[r for r in rows if r['status']=='unresolved' or core.overdue(r)],
            'ret':[r for r in rows if r['ret_status'] in ('guided','sent') or r['refund_status']=='requested'],
            'comp':[r for r in rows if core.comp_pending(r,comps)]}
    if fil not in groups:fil='all'
    return render_template('b_all.html',groups=groups,fil=fil,rows=groups[fil],q=q,tab='all')

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
    return dict(k=kpis(rows),cats=by_cat(rows),how=how,weeks=weeks,cmp=cmp,reply_h=reply_h)

notify_consumer=core.notify_consumer

def can_ship_track(db,c):
    """배송 조회 요청에 송장을 넣어 답할 수 있는지: 아직 안 넣었고 끝나지 않은 배송 조회 요청."""
    return c['category']=='배송 조회' and c['status'] not in core.FINAL and not db.execute("SELECT 1 FROM tracks WHERE fid=?",(tracking_mod.fid(c['id'],'ship'),)).fetchone()
def case_act(db,c,form):
    """기업이 요청에 하는 일(승인·보류·자료 요청·답변·회수 확인·발송·환불 완료). 웹과 앱이 같이 쓴다. -> (안내 문구, ok|error|bad)"""
    act=form.get('act');open_=c['status'] not in core.FINAL
    if act=='ret_received' and c['ret_status'] in ('guided','sent'):
        db.execute("UPDATE cases SET ret_status='received' WHERE id=?",(c['id'],))
        core.add_event(db,c['id'],'co','반품 상품 회수를 확인했어요');notify_consumer(c,f'[{core.CNAME}] 보내신 상품이 도착했어요',f"{c['company_name']}이(가) 반품 상품 회수를 확인했어요.")
        return '회수 확인을 기록했습니다','ok'
    if act=='out_ship' and c['category'] in ('교환','제품 불량') and c['ret_status']=='received' and not c['out_tracking']:
        courier=form.get('courier','');tracking=digits(form.get('tracking',''))
        if (courier not in core.COURIERS and courier!='기타') or not 8<=len(tracking)<=20:return '택배사와 송장번호를 확인해 주세요','error'
        db.execute('UPDATE cases SET out_courier=?,out_tracking=? WHERE id=?',(courier,tracking,c['id']))
        tracking_on=tracking_mod.register(db,c['id'],'out',courier,tracking)
        core.add_event(db,c['id'],'co',f'새 상품을 보냈어요: {courier} {tracking}')
        notify_consumer(c,f'[{core.CNAME}] 새 상품을 보냈어요',f"{c['company_name']}이(가) 교환 상품을 보냈어요.\n{courier} 송장번호 {tracking}"+('\n배송 상태가 바뀌면 알려 드릴게요.' if tracking_on else ''))
        return '고객에게 송장번호를 알렸습니다','ok'
    if act=='refund_done' and core.refund_case(c) and c['refund_status']!='done':
        # 환불이 끝나면 계좌 정보는 더 둘 이유가 없으니 바로 지운다
        db.execute("UPDATE cases SET refund_status='done',refund_bank='',refund_account='',refund_holder='' WHERE id=?",(c['id'],))
        core.add_event(db,c['id'],'co','환불을 완료했어요');notify_consumer(c,f'[{core.CNAME}] 환불이 완료됐어요',f"{c['company_name']}이(가) 환불을 완료했어요. 입금 내역을 확인해 주세요.")
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
        core.add_event(db,c['id'],'co','송장번호를 알렸어요',msg);notify_consumer(c,f'[{core.CNAME}] 송장번호를 알려 드려요',f"{c['company_name']}: {courier} 송장번호 {tracking}")
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
        core.add_event(db,c['id'],'co','답변을 보냈어요',msg);notify_consumer(c,f'[{core.CNAME}] 기업 답변이 도착했어요',f"{c['company_name']}이(가) 답변했어요.");return '보냈습니다','ok'
    return '','ok'

@app.route('/case/<int:case_id>',methods=['GET','POST'])
@login_required
def case(case_id):
    with conn() as db:
        c=my_case(db,case_id)
        if request.method=='POST':
            msg,level=case_act(db,c,request.form)
            if level=='bad':abort(400)
            if msg:flash(msg,level)
            return redirect(url_for('case',case_id=case_id))
        if c['status']=='forwarded':
            db.execute("UPDATE cases SET status='seen' WHERE id=?",(c['id'],));core.add_event(db,c['id'],'sys','기업이 확인했어요')
            c=my_case(db,case_id)
        ev=core.events(db,c['id']);fl=core.case_files(db,c['id']);rule=core.rule_for(db,me()['id'],c['category'])
        tracks=[tracking_mod.as_dict(t) for t in tracking_mod.tracks(db,c['id'])];ship_track=can_ship_track(db,c)
    comp_show=core.comp_open(c) and (rule['comp'] or c['category'] in core.COMP_CATS)
    guides=[law.GUIDE_BY_ID[g] for g in law.CAT_GUIDE.get(c['category'],[])]
    return render_template('b_case.html',c=c,ev=ev,files=fl,rule=rule,laws=law.for_case(c),chk=law.check(c),guides=guides,tracks=tracks,ship_track=ship_track,comp_show=comp_show,COMP_EXAMPLES=core.COMP_EXAMPLES,
        last_reply=next((e for e in reversed(ev) if e['kind']=='co' and e['reply']),None),tab='all')

@app.route('/case/<int:case_id>/draft',methods=['POST'])
@login_required
def draft(case_id):
    """답변 초안 (화면의 '초안 만들기' 버튼). 보내지는 않고 글만 돌려준다."""
    if core.throttled('draft',limit=30,minutes=10):return jsonify(error='잠시 후 다시 시도해 주세요'),429
    with conn() as db:
        c=my_case(db,case_id);res=drafting.draft(db,c,me())
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
        ps=core.products(db,co['id'])
    return render_template('b_rules.html',rs=rs,chat=chat,link=core.site_url('me','/to/%d'%co['id']),products=ps,STOCKS=core.STOCKS,ai=chatbot.ready(),tab='rules')

# ---------- 상품정보 (상담창 AI가 가격·재고·사용법 문의에 답할 때 본다) ----------
def save_product(db,co,f):
    """상품 하나 추가·수정·삭제(웹·앱 공용). (안내 문구, 'ok'|'error')."""
    pid=f.get('id');pid=int(pid) if str(pid or '').isdigit() else None
    if pid and not db.execute('SELECT 1 FROM products WHERE id=? AND company_id=?',(pid,co['id'])).fetchone():return '상품을 찾을 수 없습니다','error'
    if f.get('act')=='delete':
        if pid:db.execute('DELETE FROM products WHERE id=? AND company_id=?',(pid,co['id']))
        return '삭제했습니다','ok'
    cur=db.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone() if pid else None
    keep=lambda k,n:clean(f.get(k),n) if k in f or not cur else cur[k]  # 고칠 때 보내지 않은 항목은 그대로 둔다
    name,price,info=keep('name',60),keep('price',30),keep('info',1000)
    stock=keep('stock',10);stock=stock if stock in core.STOCKS else ''
    if not name:return '상품 이름을 적어 주세요','error'
    if pid:db.execute('UPDATE products SET name=?,price=?,stock=?,info=?,updated=? WHERE id=?',(name,price,stock,info,core.iso(),pid))
    else:
        if db.execute('SELECT COUNT(*) FROM products WHERE company_id=?',(co['id'],)).fetchone()[0]>=core.MAX_PRODUCTS:return f'상품은 {core.MAX_PRODUCTS}개까지 등록할 수 있어요','error'
        db.execute('INSERT INTO products(company_id,name,price,stock,info,updated) VALUES(?,?,?,?,?,?)',(co['id'],name,price,stock,info,core.iso()))
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

@app.route('/settings',methods=['GET','POST'])
@login_required
def settings():
    co=me()
    if request.method=='POST':
        with conn() as db:flash(*save_settings(db,co,request.form))
        return redirect(url_for('settings'))
    return render_template('b_settings.html',tab='settings',link=core.site_url('me','/to/%d'%co['id']),kakao_ready=core.kakao_ready(),guide_preview=core.return_guide(co))

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
            if act=='approve' and co and co['status']=='pending':
                # 같은 이름의 비입점 기업이 있으면 그 요청을 이 기업으로 옮김 (이후 요청부터 입점 처리)
                old=db.execute("SELECT id FROM companies WHERE status='listed' AND lower(name)=lower(?)",(co['name'],)).fetchall()
                for o in old:db.execute('UPDATE cases SET company_id=? WHERE company_id=?',(co['id'],o['id']));db.execute('DELETE FROM companies WHERE id=?',(o['id'],))
                db.execute("UPDATE companies SET status='active',member=1 WHERE id=?",(co['id'],))
                core.send_mail(co['notify_email'],f'[{core.BNAME}] 가입이 승인되었습니다',f"{co['name']}의 {core.BNAME} 가입이 승인되었습니다.\n{core.site_url('biz','/login')}")
                flash(f"{co['name']} 승인했습니다",'ok')
            elif act=='reject' and co and co['status']=='pending':db.execute("UPDATE companies SET status='rejected' WHERE id=?",(co['id'],));flash('반려했습니다','ok')
            elif act=='suspend' and co and co['status']=='active':db.execute("UPDATE companies SET status='suspended',member=0 WHERE id=?",(co['id'],));flash('이용을 중지했습니다','ok')
            elif act=='resume' and co and co['status']=='suspended':db.execute("UPDATE companies SET status='active',member=1 WHERE id=?",(co['id'],));flash('다시 이용할 수 있게 했습니다','ok')
            elif act=='pwlink' and co and co['status']=='active' and co['pw_hash']:
                flash(f"{co['name']} 비밀번호 재설정 링크예요. 1시간 동안 열려요. 복사해서 사장님께 보내 주세요: {reset_link(co)}",'ok')
            elif act=='contact' and co:db.execute('UPDATE companies SET contact=? WHERE id=?',(clean(request.form.get('contact'),60),co['id']));flash('저장했습니다','ok')
            elif act=='add':
                name=clean(request.form.get('name'),40)
                if name and not core.find_company(db,name):db.execute("INSERT INTO companies(name,member,status,contact,created) VALUES(?,0,'listed',?,?)",(name,clean(request.form.get('contact'),60),core.iso()));flash('추가했습니다','ok')
                else:flash('이름이 비었거나 이미 있습니다','error')
            return redirect(url_for('ops_companies'))
        pending=db.execute("SELECT * FROM companies WHERE status='pending' ORDER BY id").fetchall()
        rows=db.execute("SELECT c.*,(SELECT COUNT(*) FROM cases WHERE company_id=c.id) n FROM companies c WHERE status IN ('active','listed','suspended') ORDER BY member DESC,name").fetchall()
    return render_template('o_companies.html',pending=pending,rows=rows,n_signup=len(pending),otab='co')

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
        rows=db.execute('SELECT * FROM news ORDER BY id DESC').fetchall();n_pending=db.execute("SELECT COUNT(*) FROM companies WHERE status='pending'").fetchone()[0]
    return render_template('o_news.html',rows=rows,n_signup=n_pending,otab='news')

COPY_PAGES=[('c_home.html','고객 첫 화면'),('c_new.html','요청 접수'),('c_done.html','접수 완료'),('c_mine.html','내 접수'),('c_case.html','접수 상세'),
 ('c_company.html','기업별 고객센터'),('c_guide.html','이용 안내'),('c_relief.html','피해구제 안내'),('c_privacy.html','개인정보 처리방침'),('c_error.html','오류 화면'),
 ('_c.html','고객 공통 메뉴'),('_chat.html','상담 챗봇'),('consumer.py','고객 안내 메시지'),
 ('b_intro.html','소보루 CS 소개'),('b_login.html','로그인'),('b_signup.html','가입'),('b_signup_done.html','가입 완료'),('b_forgot.html','비밀번호 찾기'),
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
        n_pending=db.execute("SELECT COUNT(*) FROM companies WHERE status='pending'").fetchone()[0]
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
    with conn() as db:n_pending=db.execute("SELECT COUNT(*) FROM companies WHERE status='pending'").fetchone()[0]
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
    if not co or co['status']!='active' or not co['member'] or co['pw_hash'][-16:]!=d.get('h'):abort(401)
    g.co=co;return co
def api_form():j=request.get_json(silent=True);return j if isinstance(j,dict) and j else request.form
def co_info(co):
    return dict(id=co['id'],name=co['name'],login_id=co['login_id'],link=core.site_url('me','/to/%d'%co['id']))
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
    if co['status']!='active' or not co['member']:return jsonify(error='이용할 수 없는 계정입니다. 센터에 문의해 주세요.'),400
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
    d,err=signup_apply(api_form())
    if err:return jsonify(error=err),400
    return jsonify(ok=True,name=d['name'],message='가입 신청을 받았습니다. 승인되면 이메일로 알려 드립니다.')
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
