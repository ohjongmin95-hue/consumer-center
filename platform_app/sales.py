"""상담·데모 신청과 영업 관리 (Gorgias의 'Book a demo' 신청과 영업팀 CRM에 해당).

  · 공개 /contact: 상담·데모 신청서. DB에 저장하고 운영자에게 메일로 알린다. 신청한 분께 접수 메일.
  · 운영 /ops/leads: 신청 목록·단계·담당자·시연 일정·다음 연락일·내부 메모·연락 기록. 운영 로그인만 볼 수 있다.
신청서의 개인정보는 영업 연락에만 쓰고, 종료(lost)·도입(won) 뒤 KEEP_DAYS가 지나면 지운다.
"""
import datetime, os, re
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session
import core, funnel, onboard
from core import conn, clean, digits

bp=Blueprint('sl',__name__)
EMAIL_RE=re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
KEEP_DAYS=365*3

STAGES=[('new','새 신청'),('contacted','연락함'),('scheduled','시연 예정'),('demo_done','시연 완료'),('reviewing','검토 중'),('pilot','시범 도입'),('won','도입'),('lost','보류·종료')]
STAGE=dict(STAGES)
OPEN_STAGES=('new','contacted','scheduled','demo_done','reviewing','pilot')
VOLUMES=['월 100건 미만','월 100~500건','월 500~2,000건','월 2,000~10,000건','월 10,000건 이상']
INTERESTS=['문의 한곳에 모으기','스마트스토어·쿠팡 연동','카페24 연동','AI 상담','자동 처리','교환·반품 관리','직원·권한 관리','통계·리포트','외부 API']
CHANNELS=['전화','이메일','화상','방문','문자·카카오톡','기타']

def init():
    with conn() as db:db.executescript('''
        CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY,company TEXT NOT NULL,name TEXT NOT NULL,email TEXT NOT NULL,phone TEXT NOT NULL DEFAULT '',
          shop_url TEXT NOT NULL DEFAULT '',channels TEXT NOT NULL DEFAULT '',volume TEXT NOT NULL DEFAULT '',interests TEXT NOT NULL DEFAULT '',message TEXT NOT NULL DEFAULT '',
          stage TEXT NOT NULL DEFAULT 'new',owner TEXT NOT NULL DEFAULT '',demo_at TEXT NOT NULL DEFAULT '',follow_up TEXT NOT NULL DEFAULT '',memo TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL DEFAULT '',medium TEXT NOT NULL DEFAULT '',campaign TEXT NOT NULL DEFAULT '',page TEXT NOT NULL DEFAULT '',
          created TEXT NOT NULL,updated TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS leads_stage ON leads(stage,created);
        CREATE TABLE IF NOT EXISTS lead_log(id INTEGER PRIMARY KEY,lead_id INTEGER NOT NULL,kind TEXT NOT NULL,channel TEXT NOT NULL DEFAULT '',text TEXT NOT NULL,
          created TEXT NOT NULL,FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE);''')
init()

def log(db,lead_id,kind,text,channel=''):
    db.execute('INSERT INTO lead_log(lead_id,kind,channel,text,created) VALUES(?,?,?,?,?)',(lead_id,kind,channel,clean(text,2000),core.iso()))

def apply(f):
    """신청서 검사·저장. (입력값, 오류 문구, 신청 id)"""
    d={k:clean(f.get(k),n) for k,n in (('company',60),('name',30),('email',80),('phone',20),('shop_url',200),('volume',30),('message',2000))}
    d['channels']=','.join(x for x in f.getlist('channels') if x in onboard.SHOP_TYPES) if hasattr(f,'getlist') else ''
    d['interests']=','.join(x for x in f.getlist('interests') if x in INTERESTS) if hasattr(f,'getlist') else ''
    if d['volume'] not in VOLUMES:d['volume']=''
    if d['shop_url'] and not re.match(r'^(https?://)?[\w.-]+\.[a-z]{2,}(/\S*)?$',d['shop_url'],re.I):return d,'쇼핑몰 주소를 확인해 주세요.',None
    if f.get('website'):return d,'',0  # 봇이 채우는 숨은 칸: 저장하지 않고 성공처럼 보인다
    if not d['company']:return d,'회사 이름을 적어 주세요.',None
    if not d['name']:return d,'담당자 이름을 적어 주세요.',None
    if not EMAIL_RE.match(d['email']):return d,'이메일을 정확히 적어 주세요.',None
    if d['phone'] and not 9<=len(digits(d['phone']))<=11:return d,'연락처를 확인해 주세요.',None
    if str(f.get('privacy')) not in ('1','True','true'):return d,'개인정보 수집·이용에 동의해 주세요.',None
    if core.throttled('lead',limit=5,minutes=60):return d,'잠시 후 다시 시도해 주세요.',None
    u=session.get('utm') or {};t=core.iso()
    with conn() as db:
        lid=db.execute('''INSERT INTO leads(company,name,email,phone,shop_url,channels,volume,interests,message,source,medium,campaign,page,created,updated)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(d['company'],d['name'],d['email'].lower(),digits(d['phone']),d['shop_url'],d['channels'],d['volume'],d['interests'],d['message'],
            u.get('utm_source',''),u.get('utm_medium',''),u.get('utm_campaign',''),clean(f.get('from'),120),t,t)).lastrowid
        log(db,lid,'sys','상담 신청이 들어왔어요')
    funnel.track('consult',detail=d['company'])
    core.send_mail(os.getenv('OPS_EMAIL',''),f"[{core.BNAME} 영업] 상담 신청: {d['company']}",
        f"{d['company']} {d['name']}님이 상담을 신청했어요.\n월 문의: {d['volume'] or '-'}\n관심: {d['interests'] or '-'}\n\n{core.site_url('biz','/ops/lead/%d'%lid)}")
    core.send_mail(d['email'],f"[{core.BNAME}] 상담 신청을 받았어요",
        f"{d['name']}님, {core.BNAME} 상담 신청을 받았어요.\n담당자가 영업일 기준 1~2일 안에 연락드릴게요.\n\n기다리는 동안 제품 둘러보기: {core.site_url('biz','/tour')}")
    return d,'',lid

@bp.route('/contact',methods=['GET','POST'])
def consult():
    if request.method=='POST':
        d,err,lid=apply(request.form)
        if not err:return render_template('s_contact.html',done=True,d=d,tab='sl.consult')
        flash(err,'error');return render_template('s_contact.html',d=d,f=request.form,tab='sl.consult'),400
    return render_template('s_contact.html',d={'company':request.args.get('company','')},tab='sl.consult')

def nav():return [('sl.consult','상담 신청')]
def sitemap_paths():return ['/contact']

# ---------- 운영: 영업 관리 ----------
def ops_guard():
    if not session.get('ops'):return redirect(url_for('ops_login'))
def counts(db):
    by={r['stage']:r['n'] for r in db.execute('SELECT stage,COUNT(*) n FROM leads GROUP BY stage')}
    return by
def n_waiting():
    with conn() as db:return db.execute('SELECT COUNT(*) FROM companies WHERE '+onboard.WAITING_SQL).fetchone()[0]
def n_new():
    with conn() as db:return db.execute("SELECT COUNT(*) FROM leads WHERE stage='new'").fetchone()[0]
def due_follow_ups(db):
    today=core.now().date().isoformat()
    return db.execute(f"SELECT * FROM leads WHERE follow_up!='' AND follow_up<=? AND stage IN ({','.join('?'*len(OPEN_STAGES))}) ORDER BY follow_up",(today,*OPEN_STAGES)).fetchall()

def signed_up(db,lead):
    """같은 이메일로 가입한 회사가 있으면 그 회사."""
    return db.execute("SELECT * FROM companies WHERE lower(login_id)=lower(?) AND status IN ('active','pending','suspended')",(lead['email'],)).fetchone()

@bp.route('/ops/leads')
def ops_leads():
    g=ops_guard()
    if g:return g
    st=request.args.get('s','open');q=clean(request.args.get('q'),40)
    with conn() as db:
        if st=='open':rows=db.execute(f"SELECT * FROM leads WHERE stage IN ({','.join('?'*len(OPEN_STAGES))}) ORDER BY CASE stage WHEN 'new' THEN 0 ELSE 1 END,COALESCE(NULLIF(follow_up,''),'9999'),id DESC",OPEN_STAGES).fetchall()
        elif st in STAGE:rows=db.execute('SELECT * FROM leads WHERE stage=? ORDER BY id DESC',(st,)).fetchall()
        else:st='all';rows=db.execute('SELECT * FROM leads ORDER BY id DESC').fetchall()
        if q:rows=[r for r in rows if q.lower() in (r['company']+' '+r['name']+' '+r['email']).lower()]
        by=counts(db);due=due_follow_ups(db)
    return render_template('o_leads.html',n_signup=n_waiting(),rows=rows,st=st,q=q,by=by,due=due,STAGES=STAGES,STAGE=STAGE,n_open=sum(by.get(k,0) for k in OPEN_STAGES),otab='leads')

@bp.route('/ops/lead/<int:lid>',methods=['GET','POST'])
def ops_lead(lid):
    g=ops_guard()
    if g:return g
    with conn() as db:
        lead=db.execute('SELECT * FROM leads WHERE id=?',(lid,)).fetchone()
        if not lead:abort(404)
        if request.method=='POST':
            f=request.form;act=f.get('act')
            if act=='update':
                stage=f.get('stage') if f.get('stage') in STAGE else lead['stage']
                demo_at=clean(f.get('demo_at'),16).replace('T',' ');follow=clean(f.get('follow_up'),10);owner=clean(f.get('owner'),30)
                if demo_at and not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}',demo_at):flash('시연 일시를 확인해 주세요','error');return redirect(url_for('sl.ops_lead',lid=lid))
                if follow and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',follow):flash('다음 연락일을 확인해 주세요','error');return redirect(url_for('sl.ops_lead',lid=lid))
                ch=[]
                if stage!=lead['stage']:ch.append(f"단계: {STAGE[lead['stage']]} → {STAGE[stage]}")
                if owner!=lead['owner']:ch.append(f"담당자: {owner or '없음'}")
                if demo_at!=lead['demo_at']:ch.append(f"시연: {demo_at or '없음'}")
                if follow!=lead['follow_up']:ch.append(f"다음 연락: {follow or '없음'}")
                db.execute('UPDATE leads SET stage=?,owner=?,demo_at=?,follow_up=?,updated=? WHERE id=?',(stage,owner,demo_at,follow,core.iso(),lid))
                if ch:log(db,lid,'sys',' · '.join(ch))
                flash('저장했어요','ok')
            elif act=='memo':
                db.execute('UPDATE leads SET memo=?,updated=? WHERE id=?',(clean(f.get('memo'),4000),core.iso(),lid));flash('메모를 저장했어요','ok')
            elif act=='contact':
                text=clean(f.get('text'),2000);ch=f.get('channel') if f.get('channel') in CHANNELS else '기타'
                if not text:flash('연락 내용을 적어 주세요','error')
                else:
                    log(db,lid,'contact',text,ch)
                    if lead['stage']=='new':db.execute("UPDATE leads SET stage='contacted' WHERE id=?",(lid,))
                    db.execute('UPDATE leads SET updated=? WHERE id=?',(core.iso(),lid));flash('연락 기록을 남겼어요','ok')
            elif act=='delete':
                db.execute('DELETE FROM leads WHERE id=?',(lid,));flash('신청을 지웠어요','ok');return redirect(url_for('sl.ops_leads'))
            return redirect(url_for('sl.ops_lead',lid=lid))
        hist=db.execute('SELECT * FROM lead_log WHERE lead_id=? ORDER BY id DESC',(lid,)).fetchall();co=signed_up(db,lead)
    return render_template('o_lead.html',n_signup=n_waiting(),lead=lead,hist=hist,co=co,STAGES=STAGES,STAGE=STAGE,CHANNELS=CHANNELS,otab='leads')

def cleanup():
    """종료·도입 뒤 오래된 신청의 개인정보를 지운다 (cron)."""
    cut=core.iso(core.now()-datetime.timedelta(days=KEEP_DAYS))
    with conn() as db:return db.execute("DELETE FROM leads WHERE stage IN ('won','lost') AND updated<?",(cut,)).rowcount

@bp.app_context_processor
def sales_ctx():return {'VOLUMES':VOLUMES,'INTERESTS':INTERESTS,'SHOP_TYPES':onboard.SHOP_TYPES,'today':core.now().date().isoformat()}
