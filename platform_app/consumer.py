"""소비자용 '한큐': 어느 기업이든 한곳에서 민원 접수·조회."""
import os, datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import core
from core import conn, clean, digits

app=Flask(__name__,static_folder='static',template_folder='templates')
app.jinja_env.globals.update(core.TEMPLATE_GLOBALS,site='me')

@app.before_request
def guard():core.check_csrf()

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
@app.context_processor
def counts():return {'n_mine':len(my_ids()),'biz_url':core.site_url('biz','/')}

@app.route('/')
def home():
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
    return render_template('c_new.html',d=d)

@app.route('/guide')
def guide():return render_template('c_guide.html')

@app.route('/companies')
def companies():return jsonify(core.search_companies(request.args.get('q','')[:40]))

@app.route('/submit',methods=['POST'])
def submit():
    f=request.form;ups=request.files.getlist('files')
    d={k:clean(f.get(k),n) for k,n in (('company',60),('category',20),('title',80),('body',3000),('want',20),('order_no',40),('name',20),('phone',20),('email',80))}
    d['consent']=f.get('consent')=='1'
    pw=f.get('password','');err=''
    if not d['company']:err='기업 이름을 적어 주세요.'
    elif d['category'] not in core.CATS:err='어떤 일인지 골라 주세요.'
    elif not d['title']:err='한 줄 요약을 적어 주세요.'
    elif len(d['body'])<10:err='자세한 내용을 10자 이상 적어 주세요.'
    elif d['want'] not in core.WANTS:err='원하는 해결을 골라 주세요.'
    elif not 10<=len(digits(d['phone']))<=11:err='휴대폰 번호를 정확히 적어 주세요. 내 민원을 찾을 때 써요.'
    elif len(pw)<4:err='조회 비밀번호를 4자 이상 정해 주세요.'
    elif f.get('privacy')!='1':err='개인정보 수집·이용에 동의해야 접수할 수 있어요.'
    else:err=core.files_ok(ups)
    if not err and core.throttled('submit',limit=8,minutes=30):err='짧은 시간에 접수가 너무 많아요. 잠시 후 다시 시도해 주세요.'
    if err:
        flash(err,'error');session['draft']={k:v for k,v in d.items()};return redirect(url_for('new'))
    with conn() as db:
        co=None
        if f.get('company_id','').isdigit():
            co=core.company(db,int(f['company_id']))
            if co and co['name'].lower()!=d['company'].lower():co=None
        co=co or core.find_company(db,d['company'])
        if not co:
            cid=db.execute("INSERT INTO companies(name,member,status,created) VALUES(?,0,'listed',?)",(d['company'],core.iso())).lastrowid
            co=core.company(db,cid)
        member=core.active_member(co);t=core.iso()
        cur=db.execute('''INSERT INTO cases(no,company_id,company_name,member,category,title,body,want,order_no,name,phone,email,lookup_hash,consent,status,created,updated)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(core.new_case_no(db),co['id'],co['name'],int(member),d['category'],d['title'],d['body'],d['want'],d['order_no'],
            d['name'],digits(d['phone']),d['email'],generate_password_hash(pw),int(d['consent']),'received',t,t))
        case_id=cur.lastrowid
        core.save_files(db,case_id,ups)
        core.add_event(db,case_id,'me','민원을 접수했어요.')
        if member and d['consent']:
            due=core.iso(core.now()+datetime.timedelta(days=core.REPLY_DAYS))
            db.execute("UPDATE cases SET status='forwarded',due=?,decision='pending' WHERE id=?",(due,case_id))
            core.add_event(db,case_id,'sys',f"{co['name']} 담당 화면으로 전달했어요. 답변 목표일: {core.fmt_day(due)}")
            c=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
            if core.rule_for(db,co['id'],d['category'])['auto']:core.run_playbook(db,c,'auto')
            else:core.send_mail(co['notify_email'],f"[SOBORU Business] 새 민원: {d['title']}",
                f"{co['name']}에 새 민원이 들어왔어요.\n\n■ 유형: {d['category']}\n■ 요약: {d['title']}\n\n요약과 추천 조치를 보고 승인해 주세요.\n{core.site_url('biz','/')}")
        elif member:core.add_event(db,case_id,'sys','기업 전달에 동의하지 않아 접수만 했어요.')
        else:core.add_event(db,case_id,'sys','비입점 기업이에요. 센터가 공식 연락처로 전달을 시도할게요.' if d['consent'] else '비입점 기업이고 전달 동의가 없어 접수만 했어요.')
        no=db.execute('SELECT no FROM cases WHERE id=?',(case_id,)).fetchone()[0]
    remember(case_id)
    core.send_mail(d['email'],f'[{core.CNAME}] 접수됐어요 ({no})',f"{d['name'] or '고객'}님, 민원이 접수됐어요.\n\n■ 접수번호: {no}\n■ 기업: {co['name']}\n■ 요약: {d['title']}\n\n진행 상황은 휴대폰 번호와 조회 비밀번호로 확인할 수 있어요.\n{core.site_url('me','/mine')}")
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
    else:remember(*found);flash(f'민원 {len(found)}건을 찾았어요.','ok')
    return redirect(url_for('mine'))

@app.route('/forget',methods=['POST'])
def forget():session.pop('mine',None);flash('이 기기에서 내 민원 목록을 지웠어요.','ok');return redirect(url_for('mine'))

@app.route('/case/<int:case_id>',methods=['GET','POST'])
def case(case_id):
    c=my_case(case_id)
    if request.method=='POST':
        act=request.form.get('act');msg=clean(request.form.get('msg'),2000)
        with conn() as db:
            if act=='rate' and c['status']=='answered' and request.form.get('v') in ('resolved','unresolved'):
                v=request.form['v'];db.execute('UPDATE cases SET status=? WHERE id=?',(v,c['id']))
                core.add_event(db,c['id'],'me','해결됐다고 알려 주셨어요.' if v=='resolved' else '아직 해결되지 않았다고 알려 주셨어요.')
                if v=='unresolved' and c['member']:
                    co=core.company(db,c['company_id']);core.send_mail(co['notify_email'],f"[SOBORU Business] 소비자가 미해결로 응답했어요: {c['title']}",f"소비자가 아직 해결되지 않았다고 알려 왔어요.\n{core.site_url('biz','/case/%d'%c['id'])}")
            elif act=='again' and core.can_follow_up(db,c):
                text='다시 요청'+(': '+msg if msg else '했어요.')
                core.add_event(db,c['id'],'me',text)
                if c['member'] and c['consent']:
                    due=core.iso(core.now()+datetime.timedelta(days=core.REPLY_DAYS))
                    db.execute("UPDATE cases SET status='seen',decision='pending',due=? WHERE id=?",(due,c['id']))
                    core.add_event(db,c['id'],'sys',f"{c['company_name']}에 다시 전달했어요. 답변 목표일: {core.fmt_day(due)}")
                    co=core.company(db,c['company_id']);core.send_mail(co['notify_email'],f"[SOBORU Business] 소비자가 다시 요청했어요: {c['title']}",f"{msg or '아직 해결되지 않았다고 알려 왔어요.'}\n{core.site_url('biz','/case/%d'%c['id'])}")
                elif c['consent']:
                    db.execute("UPDATE cases SET status='received' WHERE id=?",(c['id'],))
                    core.add_event(db,c['id'],'sys','센터가 기업에 다시 전달할게요')
                    core.send_mail(os.getenv('OPS_EMAIL',''),f"[SOBORU] 비입점 민원 다시 요청: {c['title']}",core.site_url('biz','/ops/case/%d'%c['id']))
                flash('다시 요청했어요','ok')
            elif act in ('info','add') and msg and c['status'] not in ('resolved','unresolved'):
                err=core.files_ok(request.files.getlist('files'))
                if err:flash(err,'error');return redirect(url_for('case',case_id=case_id))
                eid=core.add_event(db,c['id'],'me',('추가 자료: ' if act=='info' else '')+msg)
                core.save_files(db,c['id'],request.files.getlist('files'),eid)
                if act=='info' and c['status']=='info':db.execute("UPDATE cases SET status='seen',decision='pending' WHERE id=?",(c['id'],))
                if c['member']:
                    co=core.company(db,c['company_id']);core.send_mail(co['notify_email'],f"[SOBORU Business] 소비자가 내용을 보냈어요: {c['title']}",f"{core.site_url('biz','/case/%d'%c['id'])}")
        return redirect(url_for('case',case_id=case_id))
    with conn() as db:
        ev=core.events(db,c['id']);fl=core.case_files(db,c['id']);co=core.company(db,c['company_id'])
        again=core.can_follow_up(db,c)
    return render_template('c_case.html',c=c,ev=ev,files=fl,co=co,again=again)

@app.route('/case/<int:case_id>/relief')
def relief(case_id):
    """피해구제 신청에 쓸 자료를 한 장으로 정리 (인쇄·복사용)"""
    c=my_case(case_id)
    with conn() as db:
        ev=core.events(db,c['id']);fl=core.case_files(db,c['id']);co=core.company(db,c['company_id'])
    return render_template('c_relief.html',c=c,ev=ev,files=fl,co=co)

@app.route('/to/<int:company_id>')
def company_page(company_id):
    """기업별 접수 페이지: 기업 홈페이지·쇼핑몰에서 이 주소로 연결한다"""
    with conn() as db:co=core.company(db,company_id)
    if not co or co['status'] not in ('active','listed'):abort(404)
    return render_template('c_company.html',co=co,member=core.active_member(co))

@app.route('/case/<int:case_id>/file/<int:file_id>')
def case_file(case_id,file_id):
    c=my_case(case_id)
    with conn() as db:f=db.execute('SELECT * FROM files WHERE id=? AND case_id=?',(file_id,c['id'])).fetchone()
    if not f:abort(404)
    return send_file(core.UPLOAD/f['stored'],download_name=f['original'])

@app.route('/privacy')
def privacy():return render_template('c_privacy.html')

@app.errorhandler(404)
def nf(e):return render_template('c_error.html',msg='페이지를 찾을 수 없어요.'),404
@app.errorhandler(413)
def big(e):flash('첨부 파일이 너무 커요. 합계 15MB까지 올릴 수 있어요.','error');return redirect(url_for('new'))
