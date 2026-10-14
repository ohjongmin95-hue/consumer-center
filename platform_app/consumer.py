"""소비자용 '소보루 CS' 고객센터: 어느 기업이든 한곳에서 요청 접수·조회."""
import os, re, datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import core, law, chatbot
import tracking as tracking_mod
import ai as ai_mod
from core import conn, clean, digits, BIG
from markupsafe import escape

app=Flask(__name__,static_folder='static',template_folder='templates')
app.jinja_env.globals.update(core.TEMPLATE_GLOBALS,site='me')

@app.before_request
def guard():
    if not request.path.startswith('/api/'):core.check_csrf()  # 앱 API는 쿠키 없이 요청별 토큰으로만 연다
app.after_request(core.copy_after_request('me'))  # 운영 화면에서 고친 문구 적용
core.track_template(app)

def my_ids():return set(session.get('mine',[]))
def remember(*ids):session['mine']=sorted(my_ids()|set(ids))[-50:]
def my_case(case_id):
    if case_id not in my_ids():abort(404)
    with conn() as db:
        c=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
    if not c:abort(404)
    return c

def mine_rows(limit=None):
    ids=my_ids()
    if not ids:return []
    with conn() as db:return db.execute(f"SELECT * FROM cases WHERE id IN ({','.join('?'*len(ids))}) ORDER BY id DESC"+(f' LIMIT {int(limit)}' if limit else ''),tuple(ids)).fetchall()
def cs_company():
    # 기업 고객센터(/to/<id>)로 들어온 소비자는 로고·접수하기가 그 기업으로 이어지게 한다
    cid=session.get('cs')
    if not cid:return None
    with conn() as db:co=core.company(db,cid)
    return co if co and co['status'] in ('active','listed') else None
@app.context_processor
def counts():
    cs=cs_company()
    return {'n_mine':len(my_ids()),'biz_url':core.site_url('biz','/'),'CS':cs,'BRAND':core.CNAME}

@app.route('/')
def home():
    session.pop('cs',None)
    with conn() as db:
        members=db.execute("SELECT id,name FROM companies WHERE status='active' AND member=1 ORDER BY id DESC LIMIT 8").fetchall()
        n_members=db.execute("SELECT COUNT(*) FROM companies WHERE status='active' AND member=1").fetchone()[0]
        n_cases=db.execute('SELECT COUNT(*) FROM cases').fetchone()[0]
        n_done=db.execute("SELECT COUNT(*) FROM cases WHERE status IN ('answered','resolved')").fetchone()[0]
    return render_template('c_home.html',rows=mine_rows(3),members=members,n_members=n_members,n_cases=n_cases,n_done=n_done)

@app.route('/new')
def new():
    d=session.pop('draft',None) or {'consent':True}
    if request.args.get('category') in core.CATS:d.setdefault('category',request.args['category'])
    if request.args.get('company_id','').isdigit():
        with conn() as db:co=core.company(db,int(request.args['company_id']))
        if co and co['status'] in ('active','listed'):d.setdefault('company',co['name']);d.setdefault('company_id',co['id']);d['member']=core.active_member(co)
    elif request.args.get('company'):d.setdefault('company',clean(request.args['company'],60))
    if request.args.get('body'):  # 상담창에서 쓴 문장을 그대로 이어 쓴다
        body=clean(request.args['body'],BIG);d.setdefault('body',body);d.setdefault('title',core.short(next((l for l in body.split('\n') if l.strip() and not l.startswith('[')),body),80))
        want={'주문 취소':'환불','반품·환불':'환불','교환':'교환','배송 조회':'배송 확인','고객 응대':'사과·재발 방지'}.get(d.get('category'))
        if want:d.setdefault('want',want)
    return render_template('c_new.html',d=d,today=datetime.date.today().isoformat())

@app.route('/guide')
def guide():return render_template('c_guide.html')

@app.route('/companies')
def companies():return jsonify(core.search_companies(request.args.get('q','')[:40]))

SUBMIT_FIELDS=(('company',60),('category',20),('title',BIG),('body',BIG),('want',20),('order_no',40),('name',20),('phone',20),('email',80),('product',60),('received_on',10))
def shape_request(d,reason):
    """버튼으로 고른 사유와 유형으로 요약·내용·원하는 처리를 채운다. 고객이 긴 글을 안 써도 접수되게."""
    cat=d['category'];reason=reason if reason in core.REASONS.get(cat,()) else ''
    if cat in core.WANT_OF and d['want'] not in core.WANTS:d['want']=core.WANT_OF[cat]
    d['reason']=reason
    if cat in core.TEXT_CATS and not d['body']:return
    if reason:d['body']=(reason+('\n'+d['body'] if d['body'] else ''))[:BIG]
    if not d['title']:d['title']=core.short(f"{cat} · {reason}" if reason else (d['body'].split('\n')[0] if d['body'] else cat),80)
def submit_check(d,pw,privacy,ups):
    """접수 내용 확인. 문제가 있으면 소비자에게 보일 문장, 없으면 ''."""
    if not d['company']:return '기업 이름을 적어 주세요.'
    if d['category'] not in core.CATS:return '어떤 일인지 골라 주세요.'
    if d['category'] in core.TEXT_CATS and not d['body']:return '바꿀 내용을 적어 주세요.' if d['category']=='주문 변경' else '요청할 내용을 적어 주세요.'
    if d['category'] in core.REASONS and not d.get('reason') and len(d['body'])<10:return '사유를 골라 주시거나 내용을 10자 이상 적어 주세요.'
    if d['category'] not in core.REASONS and len(d['body'])<10:return '자세한 내용을 10자 이상 적어 주세요.'
    if not d['title']:return '한 줄 요약을 적어 주세요.'
    if d['category'] in core.ORDER_CATS and not d['order_no']:return '주문번호를 적어 주세요. 주문을 찾아 처리할 때 꼭 필요해요.'
    if d['want'] not in core.WANTS:return '원하는 해결을 골라 주세요.'
    if d['received_on'] and law.days_since(d['received_on']) not in range(0,3651):return '상품 받은 날을 확인해 주세요.'
    if d['category'] in ('교환','반품·환불') and not d['received_on']:return '상품 받은 날을 알려 주세요. 교환·반품 기간(7일) 확인에 써요.'
    if not 10<=len(digits(d['phone']))<=11:return '휴대폰 번호를 정확히 적어 주세요. 내 요청을 찾을 때 써요.'
    if len(pw)<4:return '조회 비밀번호를 4자 이상 정해 주세요.'
    if not privacy:return '개인정보 수집·이용에 동의해야 접수할 수 있어요.'
    err=core.files_ok(ups)
    if not err and core.throttled('submit',limit=8,minutes=30):err='짧은 시간에 접수가 너무 많아요. 잠시 후 다시 시도해 주세요.'
    return err
def create_case(d,pw,ups,company_id=''):
    """요청을 저장하고 입점 기업이면 바로 전달한다. 웹 접수와 앱 접수가 같이 쓴다. (case_id, 접수번호, 기업)"""
    with conn() as db:
        co=None
        if str(company_id).isdigit():
            co=core.company(db,int(company_id))
            if co and co['name'].lower()!=d['company'].lower():co=None
        co=co or core.find_company(db,d['company'])
        if not co:
            cid=db.execute("INSERT INTO companies(name,member,status,created) VALUES(?,0,'listed',?)",(d['company'],core.iso())).lastrowid
            co=core.company(db,cid)
        member=core.active_member(co);t=core.iso()
        cur=db.execute('''INSERT INTO cases(no,company_id,company_name,member,category,title,body,want,order_no,name,phone,email,lookup_hash,consent,status,created,updated,product,received_on,channel)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'한큐')''',(core.new_case_no(db),co['id'],co['name'],int(member),d['category'],d['title'],d['body'],d['want'],d['order_no'],
            d['name'],digits(d['phone']),d['email'],generate_password_hash(pw),int(d['consent']),'received',t,t,d['product'],d['received_on']))
        case_id=cur.lastrowid
        core.save_files(db,case_id,ups)
        core.add_event(db,case_id,'me','요청을 접수했어요.')
        if member and d['consent']:
            due=core.iso(core.now()+datetime.timedelta(days=core.REPLY_DAYS))
            db.execute("UPDATE cases SET status='forwarded',due=?,decision='pending' WHERE id=?",(due,case_id))
            core.add_event(db,case_id,'sys',f"{co['name']} 담당 화면으로 전달했어요")
            c=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
            if core.auto_ok(db,c):
                if core.run_playbook(db,c,'auto'):core.notify_consumer(c,f'[{core.CNAME}] 기업 답변이 도착했어요',f"{co['name']}이(가) 답변했어요.")
            else:core.notify_company_new(co,c)
        elif member:core.add_event(db,case_id,'sys','기업 전달에 동의하지 않아 접수만 했어요.')
        else:core.add_event(db,case_id,'sys','비입점 기업이에요. 센터가 공식 연락처로 전달을 시도할게요.' if d['consent'] else '비입점 기업이고 전달 동의가 없어 접수만 했어요.')
        no=db.execute('SELECT no FROM cases WHERE id=?',(case_id,)).fetchone()[0]
    core.send_mail(d['email'],f'[{core.CNAME}] 접수됐어요 ({no})',f"{d['name'] or '고객'}님, 요청이 접수됐어요.\n\n■ 접수번호: {no}\n■ 기업: {co['name']}\n■ 요약: {d['title']}\n\n진행 상황은 휴대폰 번호와 조회 비밀번호로 확인할 수 있어요.\n{core.site_url('me','/mine')}")
    return case_id,no,co

@app.route('/submit',methods=['POST'])
def submit():
    f=request.form;ups=request.files.getlist('files')
    d={k:clean(f.get(k),n) for k,n in SUBMIT_FIELDS}
    d['consent']=f.get('consent')=='1';shape_request(d,clean(f.get('reason'),40))
    err=submit_check(d,f.get('password',''),f.get('privacy')=='1',ups)
    if err:
        flash(err,'error');session['draft']={k:v for k,v in d.items()};return redirect(url_for('new'))
    case_id,no,co=create_case(d,f.get('password',''),ups,f.get('company_id',''))
    remember(case_id)
    return redirect(url_for('done',case_id=case_id))

@app.route('/done/<int:case_id>')
def done(case_id):
    c=my_case(case_id)
    with conn() as db:co=core.company(db,c['company_id'])
    return render_template('c_done.html',c=c,co=co)

@app.route('/mine')
def mine():
    rows=mine_rows();files=[]
    if rows:
        with conn() as db:
            files=db.execute(f"SELECT f.*,c.title,c.no FROM files f JOIN cases c ON c.id=f.case_id WHERE f.case_id IN ({','.join('?'*len(rows))}) ORDER BY f.id DESC",tuple(r['id'] for r in rows)).fetchall()
    return render_template('c_mine.html',rows=rows,files=files)

@app.route('/lookup',methods=['POST'])
def lookup():
    phone=digits(request.form.get('phone',''));pw=request.form.get('password','')
    if core.throttled('lookup',limit=10,minutes=10):
        flash('조회 시도가 너무 많아요. 10분 뒤에 다시 해 주세요.','error');return redirect(url_for('mine'))
    with conn() as db:
        found=[r['id'] for r in db.execute('SELECT id,lookup_hash FROM cases WHERE phone=? ORDER BY id DESC LIMIT 100',(phone,)) if phone and check_password_hash(r['lookup_hash'],pw)]
    if not found:flash('휴대폰 번호나 조회 비밀번호가 맞지 않아요.','error')
    else:remember(*found);flash(f'요청 {len(found)}건을 찾았어요.','ok')
    return redirect(url_for('mine'))

@app.route('/lookup/mail',methods=['POST'])
def lookup_mail():
    """조회 비밀번호를 잊었을 때: 휴대폰 번호와 접수 때 적은 이메일이 맞으면 그 이메일로 바로 여는 링크를 보낸다."""
    phone=digits(request.form.get('phone',''));email=clean(request.form.get('email'),80).lower()
    if core.throttled('lookup_mail',limit=5,minutes=30):flash('잠시 후 다시 시도해 주세요.','error');return redirect(url_for('mine'))
    if not core.mail_ready():flash('지금은 메일을 보낼 수 없어요. 접수한 기업에 문의해 주세요.','error');return redirect(url_for('mine'))
    with conn() as db:n=db.execute("SELECT COUNT(*) FROM cases WHERE phone=? AND lower(email)=? AND channel IN ('','한큐')",(phone,email)).fetchone()[0] if phone and email else 0
    if n:
        tok=core.signer('lookup').dumps({'p':phone,'e':email})
        core.send_mail(email,f'[{core.CNAME}] 내 접수 바로 열기',f"아래 링크를 누르면 이 휴대폰 번호로 접수한 요청 {n}건을 볼 수 있어요. 30분 동안만 열려요.\n{core.site_url('me','/lookup/t/'+tok)}\n\n직접 요청하지 않으셨다면 이 메일은 무시해 주세요.")
    flash('접수 때 적은 이메일이 맞다면 바로 여는 링크를 보냈어요.','ok');return redirect(url_for('mine'))

@app.route('/lookup/t/<tok>')
def lookup_token(tok):
    try:d=core.signer('lookup').loads(tok,max_age=1800)
    except Exception:flash('링크가 만료됐어요. 다시 요청해 주세요.','error');return redirect(url_for('mine'))
    with conn() as db:ids=[r['id'] for r in db.execute("SELECT id FROM cases WHERE phone=? AND lower(email)=? AND channel IN ('','한큐') ORDER BY id DESC LIMIT 100",(d['p'],d['e']))]
    remember(*ids);flash(f'요청 {len(ids)}건을 찾았어요.','ok');return redirect(url_for('mine'))

@app.route('/forget',methods=['POST'])
def forget():session.pop('mine',None);flash('이 기기에서 내 요청 목록을 지웠어요.','ok');return redirect(url_for('mine'))

def case_act(c,form,ups):
    """소비자가 요청 화면에서 누른 동작(평가·다시 요청·반품 발송·취소·환불 계좌·추가 내용). 웹과 앱이 같이 쓴다. (안내 문장, 'ok'/'error')"""
    act=form.get('act');msg=clean(form.get('msg'),2000)
    with conn() as db:
        if act=='rate' and c['status']=='answered' and form.get('v') in ('resolved','unresolved'):
            v=form['v'];db.execute('UPDATE cases SET status=? WHERE id=?',(v,c['id']))
            core.add_event(db,c['id'],'me','해결됐다고 알려 주셨어요.' if v=='resolved' else '아직 해결되지 않았다고 알려 주셨어요.')
            if v=='unresolved' and c['member'] and c['consent']:
                co=core.company(db,c['company_id']);core.send_mail(co['notify_email'],f"[{core.BNAME}] 소비자가 미해결로 응답했어요: {c['title']}",f"소비자가 아직 해결되지 않았다고 알려 왔어요.\n{core.site_url('biz','/case/%d'%c['id'])}")
            return ('알려 주셔서 고마워요' if v=='resolved' else '아직 해결되지 않았다고 기록했어요. 아래에서 다시 요청할 수 있어요'),'ok'
        elif act=='again' and core.can_follow_up(db,c):
            text='다시 요청'+(': '+msg if msg else '했어요.')
            core.add_event(db,c['id'],'me',text)
            if c['member'] and c['consent']:
                due=core.iso(core.now()+datetime.timedelta(days=core.REPLY_DAYS))
                db.execute("UPDATE cases SET status='seen',decision='pending',due=? WHERE id=?",(due,c['id']))
                core.add_event(db,c['id'],'sys',f"{c['company_name']}에 다시 전달했어요")
                co=core.company(db,c['company_id']);core.send_mail(co['notify_email'],f"[{core.BNAME}] 소비자가 다시 요청했어요: {c['title']}",f"{msg or '아직 해결되지 않았다고 알려 왔어요.'}\n{core.site_url('biz','/case/%d'%c['id'])}")
            elif c['consent']:
                db.execute("UPDATE cases SET status='received' WHERE id=?",(c['id'],))
                core.add_event(db,c['id'],'sys','센터가 기업에 다시 전달할게요')
                core.send_mail(os.getenv('OPS_EMAIL',''),f"[{core.CNAME} 운영] 비입점 요청 재요청: {c['title']}",core.site_url('biz','/ops/case/%d'%c['id']))
            return ('다시 요청했어요' if c['consent'] else '다시 요청을 남겼어요. 정보 제공에 동의하지 않은 요청이라 기업에는 전달되지 않아요'),'ok'
        elif act=='ship' and c['ret_status'] in ('guided','sent'):
            courier=form.get('courier','');tracking=clean(form.get('tracking'),30)
            if courier not in core.COURIERS and courier!='기타':courier=''
            if not courier or not 8<=len(digits(tracking))<=20:return '택배사와 송장번호를 확인해 주세요','error'
            else:
                db.execute("UPDATE cases SET ret_status='sent',ret_courier=?,ret_tracking=? WHERE id=?",(courier,digits(tracking),c['id']))
                core.add_event(db,c['id'],'me',f'반품 상품을 보냈어요: {courier} {digits(tracking)}')
                tracking_mod.register(db,c['id'],'ret',courier,digits(tracking))
                co=core.company(db,c['company_id'])
                if co:core.send_mail(co['notify_email'],f"[{core.BNAME}] 소비자가 반품 상품을 보냈어요: {c['title']}",f"{courier} 송장번호 {digits(tracking)}\n{core.site_url('biz','/case/%d'%c['id'])}")
                return '송장번호를 알렸어요','ok'
        elif act=='cancel' and c['status'] in core.OPEN_STATUSES:
            db.execute("UPDATE cases SET status='withdrawn' WHERE id=?",(c['id'],))
            core.add_event(db,c['id'],'me','접수를 취소했어요.')
            if c['member'] and c['consent']:
                co=core.company(db,c['company_id']);core.send_mail(co['notify_email'],f"[{core.BNAME}] 고객이 접수를 취소했어요: {c['title']}",core.site_url('biz','/case/%d'%c['id']))
            return '접수를 취소했어요','ok'
        elif act=='refund' and core.refund_case(c) and c['refund_status']!='done':
            bank=form.get('bank','');acct=digits(form.get('account',''));holder=clean(form.get('holder'),20)
            if bank not in core.BANKS or not 8<=len(acct)<=16 or not holder:return '은행, 계좌번호, 예금주를 확인해 주세요','error'
            else:
                db.execute("UPDATE cases SET refund_bank=?,refund_account=?,refund_holder=?,refund_status='requested' WHERE id=?",(bank,acct,holder,c['id']))
                core.add_event(db,c['id'],'me',f'환불 받을 계좌를 등록했어요: {bank} {core.mask_account(acct)}')
                co=core.company(db,c['company_id'])
                if co:core.send_mail(co['notify_email'],f"[{core.BNAME}] 고객이 환불 계좌를 등록했어요: {c['title']}",f"{core.site_url('biz','/case/%d'%c['id'])}")
                return '환불 계좌를 등록했어요','ok'
        elif act in ('info','add') and msg and c['status'] not in core.FINAL:
            err=core.files_ok(ups)
            if err:return err,'error'
            eid=core.add_event(db,c['id'],'me',('추가 자료: ' if act=='info' else '')+msg)
            core.save_files(db,c['id'],ups,eid)
            if act=='info' and c['status']=='info':db.execute("UPDATE cases SET status='seen',decision='pending' WHERE id=?",(c['id'],))
            if c['member'] and c['consent']:
                co=core.company(db,c['company_id']);core.send_mail(co['notify_email'],f"[{core.BNAME}] 소비자가 내용을 보냈어요: {c['title']}",f"{core.site_url('biz','/case/%d'%c['id'])}")
            return ('자료를 보냈어요' if act=='info' else '내용을 더했어요'),'ok'
    return '',''

@app.route('/case/<int:case_id>',methods=['GET','POST'])
def case(case_id):
    c=my_case(case_id)
    if request.method=='POST':
        msg,level=case_act(c,request.form,request.files.getlist('files'))
        if msg:flash(msg,level)
        return redirect(url_for('case',case_id=case_id))
    with conn() as db:
        ev=core.events(db,c['id']);fl=core.case_files(db,c['id']);co=core.company(db,c['company_id'])
        again=core.can_follow_up(db,c);tracks=[tracking_mod.as_dict(t) for t in tracking_mod.tracks(db,c['id'])]
    return render_template('c_case.html',c=c,ev=ev,files=fl,co=co,again=again,tracks=tracks)

@app.route('/case/<int:case_id>/relief')
def relief(case_id):
    """피해구제 신청에 쓸 자료를 한 장으로 정리 (인쇄·복사용)"""
    c=my_case(case_id)
    with conn() as db:
        ev=core.events(db,c['id']);fl=core.case_files(db,c['id']);co=core.company(db,c['company_id'])
    return render_template('c_relief.html',c=c,ev=ev,files=fl,co=co)

@app.route('/robots.txt')
def robots():return app.response_class(core.robots_txt('me',['/case','/mine','/done','/submit','/lookup','/forget','/companies','/api']),mimetype='text/plain')
@app.route('/sitemap.xml')
def sitemap():
    urls=[core.site_url('me',p) for p in ('/','/guide','/new','/privacy')]
    with conn() as db:urls+=[core.site_url('me','/to/%d'%r['id']) for r in db.execute("SELECT id FROM companies WHERE status IN ('active','listed') ORDER BY id")]
    body=''.join('<url><loc>%s</loc></url>'%escape(u) for u in urls)
    return app.response_class('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+body+'</urlset>',mimetype='application/xml')

@app.route('/to/<int:company_id>')
def company_page(company_id):
    """기업별 접수 페이지: 기업 홈페이지·쇼핑몰에서 이 주소로 연결한다"""
    with conn() as db:co=core.company(db,company_id)
    if not co or co['status'] not in ('active','listed'):abort(404)
    session['cs']=co['id']
    return render_template('c_company.html',co=co,member=core.active_member(co),ret=core.return_guide(co),REPLY_DAYS=core.REPLY_DAYS)

@app.route('/track')
def track():
    """고객이 택배사와 송장번호로 배송 상태를 바로 조회한다. 요청을 만들지 않고, 조회 내용도 저장하지 않는다."""
    co=None
    if request.args.get('company_id','').isdigit():
        with conn() as db:co=core.company(db,int(request.args['company_id']))
        if co and co['status'] not in ('active','listed'):co=None
    courier=request.args.get('courier','');invoice=digits(request.args.get('invoice',''))
    if courier not in core.COURIERS:courier=co['return_courier'] if co and co['return_courier'] in core.COURIERS and not request.args.get('courier') else ''
    res=None
    if request.args.get('invoice') is not None:
        if not courier:res={'ok':False,'error':'택배사를 골라 주세요.'}
        elif not 8<=len(invoice)<=20:res={'ok':False,'error':'송장번호를 확인해 주세요. 숫자 8~20자리예요.'}
        elif core.throttled('track',limit=30,minutes=10):res={'ok':False,'error':'조회가 너무 많아요. 10분 뒤에 다시 해 주세요.'}
        else:res=tracking_mod.lookup(courier,invoice)
    return render_template('c_track.html',co=co,courier=courier,invoice=invoice,res=res)

def chat_answer(company_id,f):
    """상담창(자동응답): 고객 문장이나 고른 버튼 -> 유형과 그 기업의 안내 문구. 사람 손을 거치지 않는다.
    기업 없이(첫 화면) 부르면 기본 안내 문구로 답하고 기록은 남기지 않는다. (응답 dict, 상태 코드)"""
    co=None
    if company_id is not None:
        with conn() as db:co=core.company(db,company_id)
        if not co or co['status'] not in ('active','listed'):abort(404)
    if core.throttled('chat',limit=60,minutes=10):return dict(error='잠시 후 다시 시도해 주세요'),429
    if f.get('outcome') in ('solved','filed') and f.get('category') in core.CATS:
        if co:
            with conn() as db:db.execute('INSERT INTO chat_log(company_id,category,outcome,created) VALUES(?,?,?,?)',(co['id'],f['category'],f['outcome'],core.iso()))
        return dict(ok=True),200
    text=clean(f.get('text'),500)
    if co and text and f.get('category') not in core.CATS and core.active_member(co) and chatbot.ready():
        # 입점 기업 상담창에 고객이 직접 쓴 문장: AI가 회사 정보를 보고 답한다 (실패하면 아래 기본 안내로)
        with conn() as db:facts=chatbot.company_facts(db,co)
        ai=chatbot.answer(co,facts,text,f.get('history'))
        if ai:
            cat=ai['category']
            with conn() as db:
                rule=core.rule_for(db,co['id'],cat or '기타')
                db.execute('INSERT INTO chat_log(company_id,category,outcome,created) VALUES(?,?,?,?)',(co['id'],cat or '기타','asked',core.iso()))
            return dict(category=cat,answer=ai['answer'],handoff=ai['handoff'],summary=ai['summary'],faq=rule['faq'],auto=rule['auto'],cond=rule['cond'],member=True,ask_days=False),200
    cat=f.get('category') if f.get('category') in core.CATS else core.classify(text)
    if not cat:return dict(category=None),200
    if not co:return dict(category=cat,faq=core.CHAT_FAQ[cat],auto=False,cond='',member=False,ask_days=cat in ('교환','반품·환불')),200
    member=core.active_member(co)
    with conn() as db:
        rule=core.rule_for(db,co['id'],cat) if member else {'auto':False,'cond':'','faq':core.CHAT_FAQ[cat]}
        db.execute('INSERT INTO chat_log(company_id,category,outcome,created) VALUES(?,?,?,?)',(co['id'],cat,'asked',core.iso()))
    return dict(category=cat,faq=rule['faq'],auto=rule['auto'],cond=rule['cond'],member=member,ask_days=cat in ('교환','반품·환불')),200

@app.route('/chat',methods=['POST'])
@app.route('/chat/<int:company_id>',methods=['POST'])
def chat(company_id=None):
    body,code=chat_answer(company_id,request.form);return jsonify(body),code

@app.route('/case/<int:case_id>/file/<int:file_id>')
def case_file(case_id,file_id):
    c=my_case(case_id)
    with conn() as db:f=db.execute('SELECT * FROM files WHERE id=? AND case_id=?',(file_id,c['id'])).fetchone()
    if not f:abort(404)
    return send_file(core.UPLOAD/f['stored'],download_name=f['original'])

@app.route('/privacy')
def privacy():
    return render_template('c_privacy.html',op=core.OPERATOR,since=core.PRIVACY_SINCE,years=core.RETENTION_YEARS,contact=os.getenv('PRIVACY_EMAIL') or os.getenv('OPS_EMAIL',''),phone=os.getenv('PRIVACY_PHONE',''),
        mail_vendor=os.getenv('MAIL_VENDOR',''),ai=ai_mod.vendor(),kakao=core.kakao_ready() or core.kakao_ready('CS_KAKAO_TPL_REPLY'),kakao_vendor=os.getenv('KAKAO_VENDOR',''))

# ---------- 소보루 CS 앱 API (/api/v1) ----------
# 앱은 쿠키를 쓰지 않는다. 접수하거나 조회하면 요청마다 토큰을 받아 휴대폰에 두고, 그 토큰으로만 요청을 연다.
def case_token(case_id):return core.signer('app-case').dumps(case_id)
def token_case(tok):
    try:cid=core.signer('app-case').loads(tok or '')
    except Exception:return None
    with conn() as db:return db.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone() if isinstance(cid,int) else None
def api_case(case_id):
    tok=request.headers.get('Authorization','').removeprefix('Bearer ').strip() or request.args.get('t','')
    c=token_case(tok)
    if not c or c['id']!=case_id or core.is_direct(c):abort(404)
    return c
def api_json():j=request.get_json(silent=True);return j if isinstance(j,dict) else {}  # 배열 같은 엉뚱한 값이 와도 서버 오류 없이
def api_form():return api_json() or request.form
def case_summary(c):
    return dict(id=c['id'],no=c['no'],company_id=c['company_id'],company_name=c['company_name'],member=bool(c['member']),category=c['category'],title=c['title'],
        status=c['status'],status_label=core.status_label(c['status']),step=core.step_index(c['status']),created=c['created'],updated=c['updated'])
def case_detail(c):
    with conn() as db:
        ev=core.events(db,c['id']);fl=core.case_files(db,c['id']);co=core.company(db,c['company_id']);again=core.can_follow_up(db,c)
        tracks=[tracking_mod.as_dict(t) for t in tracking_mod.tracks(db,c['id'])]
    tok=case_token(c['id'])
    file_url=lambda f:url_for('api_file',case_id=c['id'],file_id=f['id'],t=tok,_external=True)
    d=case_summary(c)
    d.update(body=c['body'],want=c['want'],order_no=c['order_no'],product=c['product'],received_on=c['received_on'],due=c['due'],info_ask=c['info_ask'],
        overdue=core.overdue(c),contact=co['contact'] if co else '',ret_guide=core.return_guide(co) if co else '',
        ret=dict(status=c['ret_status'],courier=c['ret_courier'],tracking=c['ret_tracking'],out_courier=c['out_courier'],out_tracking=c['out_tracking']),
        refund=dict(possible=core.refund_case(c),status=c['refund_status'],bank=c['refund_bank'],account=core.mask_account(c['refund_account']),holder=c['refund_holder']),tracks=tracks,
        events=[dict(id=e['id'],kind=e['kind'],text=e['text'],reply=e['reply'],created=e['created'],files=[dict(id=f['id'],name=f['original'],url=file_url(f)) for f in fl if f['event_id']==e['id']]) for e in ev],
        files=[dict(id=f['id'],name=f['original'],url=file_url(f)) for f in fl],
        can=dict(rate=c['status']=='answered',again=bool(again),ship=c['ret_status'] in ('guided','sent'),cancel=c['status'] in core.OPEN_STATUSES,
            refund=core.refund_case(c) and c['refund_status']!='done',info=c['status']=='info',add=c['status'] in ('received','forwarded','seen','answered')))
    return d

@app.route('/api/v1/meta')
def api_meta():
    return jsonify(name=core.CNAME,cats=[dict(name=k,hint=core.CAT_HINT[k]) for k in core.CATS],wants=core.WANTS,couriers=list(core.COURIERS),banks=core.BANKS,
        reply_days=core.REPLY_DAYS,max_files=core.MAX_FILES,steps=core.STEPS,privacy_url=core.site_url('me','/privacy'),guide_url=core.site_url('me','/guide'))
@app.route('/api/v1/companies')
def api_companies():return jsonify(core.search_companies(request.args.get('q','')[:40]))
@app.route('/api/v1/companies/<int:company_id>')
def api_company(company_id):
    with conn() as db:co=core.company(db,company_id)
    if not co or co['status'] not in ('active','listed'):abort(404)
    return jsonify(id=co['id'],name=co['name'],member=core.active_member(co),contact=co['contact'],ret_guide=core.return_guide(co),reply_days=core.REPLY_DAYS)
@app.route('/api/v1/chat',methods=['POST'])
@app.route('/api/v1/chat/<int:company_id>',methods=['POST'])
def api_chat(company_id=None):
    body,code=chat_answer(company_id,api_form());return jsonify(body),code
@app.route('/api/v1/cases',methods=['POST'])
def api_submit():
    f=api_form();ups=request.files.getlist('files')
    d={k:clean(str(f.get(k) or ''),n) for k,n in SUBMIT_FIELDS}
    d['consent']=str(f.get('consent'))in('1','true','True');shape_request(d,clean(str(f.get('reason') or ''),40))
    pw=str(f.get('password',''))
    err=submit_check(d,pw,str(f.get('privacy'))in('1','true','True'),ups)
    if err:return jsonify(error=err),400
    case_id,no,co=create_case(d,pw,ups,f.get('company_id',''))
    return jsonify(id=case_id,no=no,token=case_token(case_id)),201
@app.route('/api/v1/lookup',methods=['POST'])
def api_lookup():
    f=api_form();phone=digits(str(f.get('phone','')));pw=str(f.get('password',''))
    if core.throttled('lookup',limit=10,minutes=10):return jsonify(error='조회 시도가 너무 많아요. 10분 뒤에 다시 해 주세요.'),429
    with conn() as db:
        rows=[r for r in db.execute("SELECT * FROM cases WHERE phone=? AND channel IN ('','한큐') ORDER BY id DESC LIMIT 100",(phone,)) if phone and check_password_hash(r['lookup_hash'],pw)]
    if not rows:return jsonify(error='휴대폰 번호나 조회 비밀번호가 맞지 않아요.'),404
    return jsonify(cases=[dict(case_summary(r),token=case_token(r['id'])) for r in rows])
@app.route('/api/v1/mine',methods=['POST'])
def api_mine():
    """휴대폰에 둔 토큰들로 내 요청 목록을 한 번에 받는다. 지워진 요청은 빠진다."""
    toks=api_json().get('tokens') or []
    if not isinstance(toks,list):toks=[]
    out=[]
    for t in toks[:100]:
        c=token_case(t if isinstance(t,str) else '')
        if c and not core.is_direct(c):out.append(dict(case_summary(c),token=t))
    return jsonify(cases=sorted(out,key=lambda x:-x['id']))
@app.route('/api/v1/cases/<int:case_id>',methods=['GET','POST'])
def api_case_view(case_id):
    c=api_case(case_id)
    if request.method=='POST':
        msg,level=case_act(c,api_form(),request.files.getlist('files'))
        if level=='error':return jsonify(error=msg),400
        with conn() as db:c=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        return jsonify(dict(case_detail(c),message=msg))
    return jsonify(case_detail(c))
@app.route('/api/v1/cases/<int:case_id>/files/<int:file_id>')
def api_file(case_id,file_id):
    c=api_case(case_id)
    with conn() as db:f=db.execute('SELECT * FROM files WHERE id=? AND case_id=?',(file_id,c['id'])).fetchone()
    if not f:abort(404)
    return send_file(core.UPLOAD/f['stored'],download_name=f['original'])
@app.route('/api/v1/push',methods=['POST'])
def api_push():
    """앱 알림 받기: Expo 푸시 토큰을 휴대폰에 둔 요청들에 묶는다."""
    j=api_json();push=str(j.get('push_token',''))[:200]
    if not re.fullmatch(r'(Exponent|Expo)PushToken\[[\w-]+\]',push):return jsonify(error='알림 토큰이 올바르지 않아요.'),400
    n=0
    with conn() as db:
        for t in (j.get('tokens') or [])[:100]:
            c=token_case(t if isinstance(t,str) else '')
            if c:db.execute('INSERT OR IGNORE INTO app_push(case_id,token,created) VALUES(?,?,?)',(c['id'],push,core.iso()));n+=1
    return jsonify(ok=True,cases=n)

@app.errorhandler(400)
def bad(e):return core.bad_request()
@app.errorhandler(404)
def nf(e):
    if request.path.startswith('/api/'):return jsonify(error='찾을 수 없어요.'),404
    return render_template('c_error.html',msg='페이지를 찾을 수 없어요.'),404
@app.errorhandler(413)
def big(e):
    if request.path.startswith('/api/'):return jsonify(error='첨부 파일이 너무 커요. 합계 15MB까지 올릴 수 있어요.'),413
    flash('첨부 파일이 너무 커요. 합계 15MB까지 올릴 수 있어요.','error');return redirect(url_for('new'))
