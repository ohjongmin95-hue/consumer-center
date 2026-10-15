"""회원 확장: 이메일 로그인 보조, 카카오·네이버 로그인, 예전 제보 연결, 기업 소속 인증 신청.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 주소를 붙인다.
- 카카오·네이버는 공식 OAuth(인가 코드) 방식. 키가 서버 설정(/etc/soboru.env)에 있을 때만 버튼이 보인다.
  받은 토큰은 저장하지 않고, 회원 고유번호·이메일·닉네임·실명·휴대전화번호만 쓴다.
  실명·휴대전화번호는 제보 양식 자동 입력용이며 공개 화면에는 나오지 않는다(관리자·본인만).
- 소셜 이메일이 기존 회원 이메일과 같아도 자동으로 합치지 않는다. 기존 계정으로 로그인한 뒤 내 정보에서 연결한다.
- 소셜로 로그인해도 기업 소속은 인증되지 않는다. 소속 인증 신청 → 관리자 승인 뒤에만 기업 회원.
  승인되면 그 회원에게 기업 담당자 자리(company_users.user_id)를 붙여, 카카오·네이버 로그인만으로 기업 화면(/biz)에 들어간다.
"""
import datetime, json, os, re, secrets, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from flask import abort, flash, g, redirect, render_template, request, send_file, session, url_for

PROVIDERS={
    'kakao':dict(name='카카오',key='KAKAO_REST_API_KEY',secret='KAKAO_CLIENT_SECRET',
                 authorize='https://kauth.kakao.com/oauth/authorize',token='https://kauth.kakao.com/oauth/token',me='https://kapi.kakao.com/v2/user/me'),
    'naver':dict(name='네이버',key='NAVER_CLIENT_ID',secret='NAVER_CLIENT_SECRET',
                 authorize='https://nid.naver.com/oauth2.0/authorize',token='https://nid.naver.com/oauth2.0/token',me='https://openapi.naver.com/v1/nid/me'),
}
MEMBERSHIP_STATUSES={'pending':'확인 중','approved':'승인','rejected':'반려'}
EVIDENCE_TYPES={'.pdf':'pdf','.png':'png','.jpg':'jpg','.jpeg':'jpg','.webp':'webp'}
EVIDENCE_MAX=5*1024*1024

def migrate(db):
    cols={r['name'] for r in db.execute('PRAGMA table_info(users)')}
    if 'kind' not in cols:db.execute("ALTER TABLE users ADD COLUMN kind TEXT NOT NULL DEFAULT 'consumer'")  # consumer / company
    if 'email_verified_at' not in cols:db.execute("ALTER TABLE users ADD COLUMN email_verified_at TEXT NOT NULL DEFAULT ''")
    # 제보자 실명·휴대전화 (카카오·네이버에서 받았거나 본인이 적은 값). 제보 양식 자동 입력용, 공개 안 함
    if 'real_name' not in cols:db.execute("ALTER TABLE users ADD COLUMN real_name TEXT NOT NULL DEFAULT ''")
    if 'phone' not in cols:db.execute("ALTER TABLE users ADD COLUMN phone TEXT NOT NULL DEFAULT ''")
    db.execute('''CREATE TABLE IF NOT EXISTS user_identities(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,provider TEXT NOT NULL,provider_uid TEXT NOT NULL,
        email TEXT NOT NULL DEFAULT '',linked_at TEXT NOT NULL,UNIQUE(provider,provider_uid),UNIQUE(user_id,provider))''')
    db.execute('''CREATE TABLE IF NOT EXISTS company_memberships(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,company_id INTEGER,company_name TEXT NOT NULL,biz_no TEXT NOT NULL,
        person_name TEXT NOT NULL,department TEXT NOT NULL DEFAULT '',phone TEXT NOT NULL,work_email TEXT NOT NULL,evidence_stored TEXT NOT NULL DEFAULT '',evidence_original TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',reason TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,decided_at TEXT NOT NULL DEFAULT '',decided_by TEXT NOT NULL DEFAULT '')''')
    db.execute('CREATE INDEX IF NOT EXISTS company_memberships_user ON company_memberships(user_id)')
    # 간편 로그인 기업 담당자: 비밀번호 없이 회원 계정(user_id)으로 기업 화면에 들어옴
    if 'user_id' not in {r['name'] for r in db.execute('PRAGMA table_info(company_users)')}:db.execute('ALTER TABLE company_users ADD COLUMN user_id INTEGER')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS company_users_member ON company_users(user_id) WHERE user_id IS NOT NULL')

def secret(name):return os.getenv(name,'').strip()
def provider_ready(p):return p in PROVIDERS and bool(secret(PROVIDERS[p]['key']) and secret(PROVIDERS[p]['secret']))
def ready_providers():return [p for p in PROVIDERS if provider_ready(p)]

def http(method,url,data=None,headers=None,timeout=10):
    """(상태 코드, JSON). 테스트에서 바꿔 끼운다."""
    body=urllib.parse.urlencode(data).encode() if data is not None else None
    req=urllib.request.Request(url,data=body,method=method,headers=dict(headers or {},**({'Content-Type':'application/x-www-form-urlencoded;charset=utf-8'} if body else {})))
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:return r.status,json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        try:return e.code,json.loads(e.read().decode() or '{}')
        except Exception:return e.code,{}

def kr_phone(v):
    """'+82 10-1234-5678' · '01012345678' → '010-1234-5678'. 알아볼 수 없으면 ''."""
    d=re.sub(r'\D','',v or '')
    if d.startswith('82'):d='0'+d[2:]
    if not re.match(r'^01\d{8,9}$',d):return ''
    return f'{d[:3]}-{d[3:-4]}-{d[-4:]}'

def fetch_profile(p,code,state,redirect_uri):
    """인가 코드 → {'uid','email','email_verified','nickname','name','phone'}. 실패하면 None."""
    cfg=PROVIDERS[p]
    form=dict(grant_type='authorization_code',client_id=secret(cfg['key']),client_secret=secret(cfg['secret']),code=code,redirect_uri=redirect_uri)
    if p=='naver':form['state']=state
    try:
        st,tok=http('POST',cfg['token'],form)
        access=tok.get('access_token') if st==200 else None
        if not access:return None
        st,me=http('GET',cfg['me'],headers={'Authorization':'Bearer '+access})
    except (OSError,ValueError):return None
    if st!=200:return None
    if p=='kakao':
        acc=me.get('kakao_account') or {}
        uid=str(me.get('id') or '')
        email=(acc.get('email') or '').strip()
        verified=bool(email and acc.get('is_email_valid') and acc.get('is_email_verified'))
        nick=((acc.get('profile') or {}).get('nickname') or (me.get('properties') or {}).get('nickname') or '').strip()
        real=(acc.get('name') or '').strip();phone=kr_phone(acc.get('phone_number'))
    else:
        if me.get('resultcode')!='00':return None
        r=me.get('response') or {}
        uid=str(r.get('id') or '');email=(r.get('email') or '').strip();verified=bool(email);nick=(r.get('nickname') or '').strip()
        real=(r.get('name') or '').strip();phone=kr_phone(r.get('mobile') or r.get('mobile_e164'))
    if not uid:return None
    return dict(uid=uid,email=email.lower()[:120],email_verified=verified,nickname=nick,name=real[:40],phone=phone)

def fill_identity(db,uid,prof):
    """카카오·네이버가 준 실명·휴대전화를 회원 정보의 빈칸에만 채움 (본인이 고친 값은 그대로 둠)."""
    if prof.get('name'):db.execute("UPDATE users SET real_name=? WHERE id=? AND real_name=''",(prof['name'],uid))
    if prof.get('phone'):db.execute("UPDATE users SET phone=? WHERE id=? AND phone=''",(prof['phone'],uid))

def auto_nickname(db):
    """게시판 닉네임 자동 지정 '소비자1234'. 카카오·네이버 닉네임은 실명인 경우가 많아 그대로 쓰지 않음. 내 정보에서 바꿀 수 있음."""
    for _ in range(50):
        nick='소비자'+str(secrets.randbelow(9000)+1000)
        if not db.execute('SELECT 1 FROM users WHERE nickname=?',(nick,)).fetchone():return nick
    return '소비자'+secrets.token_hex(4)

def install(S):
    app=S.app;conn=S.conn;now=S.now;ui_text=S.ui_text
    with conn() as db:migrate(db)
    def login_methods(user):
        """회원이 쓸 수 있는 로그인 방법 (해제할 때 하나는 꼭 남김)."""
        with conn() as db:linked=[r['provider'] for r in db.execute('SELECT provider FROM user_identities WHERE user_id=? ORDER BY id',(user['id'],))]
        return (['password'] if user['pw_hash'] else [])+linked
    def membership_of(db,uid):
        return db.execute('SELECT * FROM company_memberships WHERE user_id=? ORDER BY id DESC LIMIT 1',(uid,)).fetchone()
    app.jinja_env.globals.update(social_providers=ready_providers,SOCIAL_NAMES={k:v['name'] for k,v in PROVIDERS.items()},MEMBERSHIP_STATUSES=MEMBERSHIP_STATUSES)
    S.login_methods=login_methods;S.membership_of=membership_of

    def redirect_uri(p):
        base=secret('OAUTH_REDIRECT_BASE').rstrip('/')
        return base+url_for('social_callback',provider=p) if base else url_for('social_callback',provider=p,_external=True)

    @app.route('/auth/<provider>/start')
    def social_start(provider):
        if not provider_ready(provider) or not S.members_enabled():abort(404)
        mode='link' if g.user and request.args.get('link') else 'login'
        state=secrets.token_urlsafe(24)
        session['oauth']={'p':provider,'state':state,'mode':mode,'next':S.safe_next('mypage' if mode=='link' else 'home')}
        cfg=PROVIDERS[provider]
        q=dict(response_type='code',client_id=secret(cfg['key']),redirect_uri=redirect_uri(provider),state=state)
        return redirect(cfg['authorize']+'?'+urllib.parse.urlencode(q))

    @app.route('/auth/<provider>/callback')
    def social_callback(provider):
        if provider not in PROVIDERS:abort(404)
        info=session.pop('oauth',None)
        # 위조 방지: 이 브라우저에서 시작한 로그인인지 state 값으로 확인
        if not info or info.get('p')!=provider or not secrets.compare_digest(str(info.get('state','')),request.args.get('state','')):
            flash('로그인을 다시 시작해 주세요.');return redirect(url_for('login'))
        if request.args.get('error') or not request.args.get('code'):
            flash(PROVIDERS[provider]['name']+' 로그인을 취소했어요.');return redirect(url_for('mypage') if info['mode']=='link' and g.user else url_for('login'))
        if S.too_many_attempts('social'):flash(ui_text('msg.m28','로그인 시도가 너무 많아요. 10분 뒤 다시 시도해 주세요.'));return redirect(url_for('login'))
        prof=fetch_profile(provider,request.args['code'],request.args.get('state',''),redirect_uri(provider))
        if not prof:
            S.note_attempt('social');flash(PROVIDERS[provider]['name']+' 로그인에 실패했어요. 잠시 뒤 다시 시도해 주세요.');return redirect(url_for('login'))
        name=PROVIDERS[provider]['name']
        with conn() as db:
            ident=db.execute('SELECT * FROM user_identities WHERE provider=? AND provider_uid=?',(provider,prof['uid'])).fetchone()
            if info['mode']=='link':
                if not g.user:return redirect(url_for('login'))
                if ident and ident['user_id']!=g.user['id']:flash(f'이 {name} 계정은 이미 다른 회원과 연결돼 있어요.')
                elif ident:flash(f'이미 연결된 {name} 계정이에요.')
                elif db.execute('SELECT 1 FROM user_identities WHERE user_id=? AND provider=?',(g.user['id'],provider)).fetchone():flash(f'다른 {name} 계정이 이미 연결돼 있어요. 해제한 뒤 다시 연결해 주세요.')
                else:
                    db.execute('INSERT INTO user_identities(user_id,provider,provider_uid,email,linked_at) VALUES(?,?,?,?,?)',(g.user['id'],provider,prof['uid'],prof['email'],now()))
                    fill_identity(db,g.user['id'],prof)
                    flash(f'{name} 계정을 연결했어요. 이제 {name}로도 로그인할 수 있어요.')
                return redirect(url_for('mypage')+'#login-methods')
            if ident:
                user=db.execute('SELECT * FROM users WHERE id=?',(ident['user_id'],)).fetchone()
                if not user:db.execute('DELETE FROM user_identities WHERE id=?',(ident['id'],))
                elif user['status']!='active':flash(ui_text('msg.m29','이용이 제한된 계정이에요. 운영자에게 문의해 주세요.'));return redirect(url_for('login'))
                else:
                    db.execute("UPDATE users SET last_login=? WHERE id=?",(now(),user['id']))
                    fill_identity(db,user['id'],prof)
                    S.sign_in(user,True);return redirect(info.get('next') or url_for('home'))
            # 처음 보는 소셜 계정. 같은 이메일 회원이 있으면 합치지 않고 기존 계정 로그인을 안내 (남의 계정에 붙는 일 방지)
            if prof['email'] and db.execute("SELECT 1 FROM users WHERE email=? COLLATE NOCASE AND email!=''",(prof['email'],)).fetchone():
                flash(f'이미 이 이메일로 가입한 회원이 있어요. 기존 아이디로 로그인한 뒤 내 정보에서 {name} 계정을 연결해 주세요.')
                return redirect(url_for('login'))
        session['oauth_join']=dict(p=provider,**prof,at=now(),next=info.get('next') or '')
        return redirect(url_for('social_join'))

    @app.route('/auth/join',methods=['GET','POST'])
    def social_join():
        # 소셜 계정으로 처음 오면 약관 동의만 받고 가입. 닉네임은 자동으로 정하고(내 정보에서 변경), 실명·휴대전화는 제보 양식에 자동 입력
        pend=session.get('oauth_join')
        if g.user:return redirect(url_for('mypage'))
        if not pend or pend['at']<(datetime.datetime.now()-datetime.timedelta(minutes=30)).isoformat(timespec='seconds'):
            session.pop('oauth_join',None);flash('로그인을 다시 시작해 주세요.');return redirect(url_for('login'))
        name=PROVIDERS[pend['p']]['name']
        view=dict(provider=name,real_name=pend.get('name',''),phone=pend.get('phone',''),email=pend.get('email',''))
        if request.method=='GET':return render_template('social_join.html',**view)
        with conn() as db:
            if not all(request.form.get(k) for k in ('agree_terms','agree_privacy','agree_age')):
                flash(ui_text('msg.m17','필수 동의 항목을 모두 확인해 주세요.'));return render_template('social_join.html',**view),400
            if db.execute('SELECT 1 FROM user_identities WHERE provider=? AND provider_uid=?',(pend['p'],pend['uid'])).fetchone():
                session.pop('oauth_join',None);flash('이미 가입된 계정이에요. 다시 로그인해 주세요.');return redirect(url_for('login'))
            nick=auto_nickname(db)
            for _ in range(5):  # 소셜 회원은 아이디를 쓰지 않음. 겹치지 않는 내부 아이디만 만들어 둠
                login_id=pend['p'][0]+'_'+secrets.token_hex(5)
                if not db.execute('SELECT 1 FROM users WHERE login_id=?',(login_id,)).fetchone():break
            email=pend['email'] if pend['email'] and not db.execute("SELECT 1 FROM users WHERE email=? COLLATE NOCASE",(pend['email'],)).fetchone() else ''
            cur=db.execute("INSERT INTO users(login_id,pw_hash,nickname,email,terms_version,agreed_at,ip_hash,created,email_verified_at,real_name,phone) VALUES(?,'',?,?,?,?,?,?,?,?,?)",
                           (login_id,nick,email,S.TERMS_VERSION,now(),S.ip_hash(),now(),now() if email and pend['email_verified'] else '',pend.get('name',''),pend.get('phone','')))
            db.execute('INSERT INTO user_identities(user_id,provider,provider_uid,email,linked_at) VALUES(?,?,?,?,?)',(cur.lastrowid,pend['p'],pend['uid'],pend['email'],now()))
            user=db.execute('SELECT * FROM users WHERE id=?',(cur.lastrowid,)).fetchone()
        nxt=pend.get('next') or ''
        session.pop('oauth_join',None);S.sign_in(user,True)
        flash(user['nickname']+ui_text('msg.welcome','님, 가입을 환영해요!'))
        return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') and nxt!='/' else url_for('mypage'))

    @app.route('/me/social/<provider>/unlink',methods=['POST'])
    @S.member_only
    def social_unlink(provider):
        if provider not in PROVIDERS:abort(404)
        if len(login_methods(g.user))<=1:
            flash('로그인 방법이 하나만 남아 있어 해제할 수 없어요. 비밀번호를 먼저 만들어 주세요.');return redirect(url_for('mypage')+'#login-methods')
        with conn() as db:db.execute('DELETE FROM user_identities WHERE user_id=? AND provider=?',(g.user['id'],provider))
        flash(PROVIDERS[provider]['name']+' 연결을 해제했어요.')
        return redirect(url_for('mypage')+'#login-methods')

    # ---- 예전 제보 연결 -------------------------------------------------------
    @app.route('/me/link-case',methods=['POST'])
    @S.member_only
    def link_case():
        # 로그인 전에 접수한 제보: 접수번호 + 휴대폰 번호 + 조회 비밀번호가 모두 맞을 때만 내 계정에 연결
        back=redirect(url_for('mypage')+'#link-case')
        if S.too_many_attempts('case'):flash(ui_text('msg.lookup_rate','시도가 너무 많아요. 10분 뒤 다시 시도해 주세요.'));return back
        receipt=request.form.get('receipt','').strip().upper()[:30];digits=S.phone_digits(request.form.get('phone'));pw=request.form.get('password','')
        with conn() as db:
            case=db.execute('SELECT * FROM cases WHERE receipt=?',(receipt,)).fetchone() if receipt else None
            ok=case and case['user_id'] is None and len(digits)>=8 and S.phone_digits(case['phone'])==digits and S.case_pw_ok(case,pw)
            if not ok:
                S.note_attempt('case')
                if case and case['user_id']==g.user['id']:flash('이미 내 계정에 연결된 제보예요.')
                else:flash('접수번호, 휴대폰 번호, 조회 비밀번호를 다시 확인해 주세요. 조회 비밀번호 없이 접수한 제보는 운영자에게 문의해 주세요.')
                return back
            db.execute('UPDATE cases SET user_id=? WHERE id=?',(g.user['id'],case['id']))
            S.log_case(db,case['id'],'제보자 본인 확인 후 회원 계정에 연결')
        flash('제보를 내 계정에 연결했어요.')
        return redirect(url_for('mypage')+'#my-reports')

    # ---- 기업 소속 인증 -------------------------------------------------------
    def admin_ping(text):
        # 운영자 텔레그램으로 짧게 알림 (설정이 없으면 아무것도 안 함, 실패해도 신청은 그대로)
        notify=S.notify
        chats=[c for c in notify.env('TELEGRAM_CHAT_ID').replace(' ','').split(',') if c] if notify.env('TELEGRAM_BOT_TOKEN') else []
        def send(resp):
            for c in chats:
                try:notify.send_telegram(c,text)
                except Exception:app.logger.warning('기업 소속 신청 텔레그램 알림 실패')
            return resp
        if chats:S.after_this_request(send)
    @app.route('/me/company',methods=['GET','POST'])
    @S.member_only
    def me_company():
        with conn() as db:
            cur=membership_of(db,g.user['id'])
            if request.method=='GET':return render_template('me_company.html',m=cur)
            if cur and cur['status'] in ('pending','approved'):flash('이미 신청한 내용이 있어요.');return redirect(url_for('me_company'))
            f={k:request.form.get(k,'').strip() for k in ('company_name','biz_no','person_name','department','phone','work_email')}
            biz=re.sub(r'\D','',f['biz_no'])
            errors=[]
            if not 2<=len(f['company_name'])<=60:errors.append('기업명을 확인해 주세요.')
            if not S.biz_no_ok(biz):errors.append('사업자등록번호 10자리를 확인해 주세요.')
            if not 2<=len(f['person_name'])<=30:errors.append('담당자 이름을 확인해 주세요.')
            if len(f['department'])>60:errors.append('소속·직함은 60자까지 쓸 수 있어요.')
            if not re.fullmatch(r'[0-9\-\s]{8,20}',f['phone']):errors.append('연락처를 확인해 주세요.')
            if len(f['work_email'])>120 or not S.MEMBER_EMAIL_RE.match(f['work_email']):errors.append('회사 이메일을 확인해 주세요.')
            if not request.form.get('agree'):errors.append('개인정보 수집·이용에 동의해 주세요.')
            up=request.files.get('evidence');ev=None
            if up and up.filename:
                suffix=Path(up.filename).suffix.lower();head=up.stream.read(12);up.stream.seek(0,2);size=up.stream.tell();up.stream.seek(0)
                if suffix not in EVIDENCE_TYPES or not S.file_ok(suffix,head):errors.append('증빙은 사진이나 PDF만 올릴 수 있어요.')
                elif size>EVIDENCE_MAX:errors.append('증빙 파일은 5MB까지 올릴 수 있어요.')
                else:ev=(up,suffix,re.sub(r'[\x00-\x1f/\\]','',Path(up.filename.replace('\\','/')).name)[:180] or 'file'+suffix)
            if errors:
                for e in errors:flash(e)
                return render_template('me_company.html',m=cur),400
            stored=''
            if ev:stored='m_'+secrets.token_hex(20)+ev[1];ev[0].save(S.UPLOAD/stored)
            company=db.execute('SELECT id FROM companies WHERE biz_no=? ORDER BY id LIMIT 1',(biz,)).fetchone()
            db.execute('''INSERT INTO company_memberships(user_id,company_id,company_name,biz_no,person_name,department,phone,work_email,evidence_stored,evidence_original,created)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(g.user['id'],company['id'] if company else None,f['company_name'],biz,f['person_name'],f['department'],f['phone'],f['work_email'],stored,ev[2] if ev else '',now()))
        admin_ping(f"[소비자제보센터] 기업 소속 인증 신청: {f['company_name']}\n"+url_for('admin_members',_external=True)+'#memberships')
        flash('기업 소속 인증을 신청했어요. 운영자가 확인한 뒤 알려 드려요.')
        return redirect(url_for('me_company'))

    def biz_company_for(db,m):
        """소속 승인할 때 붙일 기업. 사업자번호가 같은 기업 → 센터가 미리 등록한 같은 이름 기업 → 없으면 새로 만듦.
        센터가 미리 등록만 해 둔 기업이면 운영자가 이 승인으로 확인한 것이므로 승인 상태로 바꿈.
        (다른 담당자가 아이디로 가입 신청해 승인 대기 중인 기업은 그 신청을 따로 승인해야 열림)"""
        company=db.execute('SELECT * FROM companies WHERE biz_no=? AND biz_no!=\'\' ORDER BY CASE status WHEN \'active\' THEN 0 ELSE 1 END,id LIMIT 1',(m['biz_no'],)).fetchone()
        if not company:
            hit=S.pick_company(db,None,m['company_name'])
            company=hit if hit and not hit['biz_no'] else None
        if not company:
            cid=db.execute("INSERT INTO companies(name,biz_no,status,contact_name,contact_phone,contact_email,created,approved,email_verified_at) VALUES(?,?,'active',?,?,?,?,?,?)",
                           (m['company_name'],m['biz_no'],m['person_name'],m['phone'],m['work_email'],now(),now(),now()+' 운영자 확인')).lastrowid
        elif company['status']=='listed':
            cid=company['id']
            db.execute("UPDATE companies SET status='active',approved=CASE approved WHEN '' THEN ? ELSE approved END,biz_no=?,"
                       "contact_name=CASE contact_name WHEN '' THEN ? ELSE contact_name END,contact_phone=CASE contact_phone WHEN '' THEN ? ELSE contact_phone END,"
                       "contact_email=CASE contact_email WHEN '' THEN ? ELSE contact_email END,email_verified_at=CASE email_verified_at WHEN '' THEN ? ELSE email_verified_at END WHERE id=?",
                       (now(),m['biz_no'],m['person_name'],m['phone'],m['work_email'],now()+' 운영자 확인',cid))
        else:cid=company['id']
        return db.execute('SELECT * FROM companies WHERE id=?',(cid,)).fetchone()

    def admin_memberships(db):
        return db.execute('''SELECT m.*,u.nickname,u.login_id FROM company_memberships m JOIN users u ON u.id=m.user_id
            ORDER BY CASE m.status WHEN 'pending' THEN 0 ELSE 1 END,m.id DESC LIMIT 100''').fetchall()
    def admin_membership_action(db,form):
        mid=form.get('membership_id',type=int);action=form.get('action')
        m=db.execute('SELECT * FROM company_memberships WHERE id=?',(mid,)).fetchone()
        if not m or action not in ('m_approve','m_reject'):abort(400)
        if action=='m_approve':
            company=biz_company_for(db,m)
            db.execute("UPDATE company_memberships SET status='approved',company_id=?,reason='',decided_at=?,decided_by='관리자' WHERE id=?",(company['id'],now(),mid))
            db.execute("UPDATE users SET kind='company' WHERE id=?",(m['user_id'],))
            if company['status'] in ('rejected','stopped'):
                return f"기업 소속을 승인했어요. 다만 {company['name']} 기업 계정이 {S.COMPANY_STATUSES[company['status']]} 상태라 기업 화면은 열리지 않아요."
            wait=f" {company['name']} 기업 가입 신청이 승인 대기라, 기업 관리에서 승인하면 제보가 보여요." if company['status']=='pending' else ''
            seat=db.execute('SELECT id FROM company_users WHERE user_id=?',(m['user_id'],)).fetchone()
            if seat:db.execute('UPDATE company_users SET company_id=?,name=?,session_ver=session_ver+1 WHERE id=?',(company['id'],m['person_name'],seat['id']))
            else:
                for _ in range(5):  # 간편 로그인 담당자는 아이디·비밀번호를 쓰지 않음. 겹치지 않는 내부 아이디만
                    login_id='sns_'+secrets.token_hex(5)
                    if not db.execute('SELECT 1 FROM company_users WHERE login_id=?',(login_id,)).fetchone():break
                db.execute("INSERT INTO company_users(company_id,login_id,pw_hash,name,created,user_id) VALUES(?,?,'',?,?,?)",(company['id'],login_id,m['person_name'],now(),m['user_id']))
            return f"기업 소속을 승인했어요. 이제 카카오·네이버 로그인으로 {company['name']} 기업 화면에 들어갈 수 있어요."+wait
        reason=form.get('reason','').strip()[:300]
        db.execute("UPDATE company_memberships SET status='rejected',reason=?,decided_at=?,decided_by='관리자' WHERE id=?",(reason,now(),mid))
        db.execute('DELETE FROM company_users WHERE user_id=? AND company_id IS ?',(m['user_id'],m['company_id']))
        if not db.execute("SELECT 1 FROM company_memberships WHERE user_id=? AND status='approved'",(m['user_id'],)).fetchone():
            db.execute("UPDATE users SET kind='consumer' WHERE id=?",(m['user_id'],))
        return '반려했어요.'
    S.admin_memberships=admin_memberships;S.admin_membership_action=admin_membership_action

    @app.route('/admin/memberships/<int:mid>/evidence')
    @S.admin_only
    def admin_membership_file(mid):
        with conn() as db:m=db.execute('SELECT * FROM company_memberships WHERE id=?',(mid,)).fetchone()
        if not m or not m['evidence_stored']:abort(404)
        resp=send_file(S.UPLOAD/m['evidence_stored'],as_attachment=True,download_name=m['evidence_original'])
        resp.headers['Cache-Control']='no-store';return resp

    def delete_member_extras(db,uid):
        # 탈퇴: 소셜 연결·기업 소속 신청(증빙 파일 포함)을 바로 지움
        db.execute('DELETE FROM user_identities WHERE user_id=?',(uid,))
        for r in db.execute("SELECT evidence_stored FROM company_memberships WHERE user_id=? AND evidence_stored!=''",(uid,)).fetchall():(S.UPLOAD/r['evidence_stored']).unlink(missing_ok=True)
        db.execute('DELETE FROM company_memberships WHERE user_id=?',(uid,))
        db.execute('DELETE FROM company_users WHERE user_id=?',(uid,))
    S.delete_member_extras=delete_member_extras
