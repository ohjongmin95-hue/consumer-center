"""소비자제보센터 플랫폼 기능: 기업별 공개 페이지, 기업 검색, 제보 공개 심사, 제보 진행 이력.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 주소를 붙인다.
공개 화면의 숫자는 모두 DB에서 바로 센다. 표본이 적으면 비율 대신 '–'를 보여 준다.
"""
import datetime, re, statistics
from flask import render_template, request, abort, jsonify, url_for, g

# 예전 제보 유형 → 새 유형 (예전 제보도 새 유형으로 걸러 볼 수 있게)
CATEGORY_MAP={'상품·품질':'품질·하자·AS','배송·환불':'배송·교환·환불','구독·결제':'요금·결제','금융·통신':'요금·결제',
              '여행·숙박':'계약·해지','서비스·계약':'계약·해지'}
MIN_N=5  # 비율을 보여 주는 최소 유효 제보 수
NOT_VALID=('rejected','duplicate')  # 운영자가 반려·중복 처리한 제보는 통계에서 뺀다
# 검토 결과는 진행 단계와 따로 관리한다. 예전 값(ok·duplicate·rejected)을 그대로 쓰고 이름만 바꿈.
REVIEWS={'':'미검토','ok':'정상','duplicate':'중복','rejected':'제외'}
REVIEW_HINTS={'':'접수 후 아직 확인하지 않은 제보','ok':'정상적으로 접수·검토된 제보','duplicate':'같은 내용이 반복 접수된 제보','rejected':'허위·광고·욕설 등 운영 기준에 맞지 않는 제보'}
REVIEW_KEYS={'new':'','ok':'ok','duplicate':'duplicate','rejected':'rejected'}  # 주소에 쓰는 이름 → DB 값
CASE_COLS=('public_subject','public_body','public_request','review','review_note','reviewed_at','occurred_on','forwarded_at','seen_at','confirmed_at','closed_at','outcome')
COMPANY_COLS=('brand','biz_name','official_email','statement','statement_at','statement_draft','statement_draft_at','email_token','email_verified_at','claim_id')
MESSAGE_COLS=(('edited',"TEXT NOT NULL DEFAULT ''"),('source',"TEXT NOT NULL DEFAULT ''"),('want_public','INTEGER NOT NULL DEFAULT 0'))
OUTCOMES={'resolved':'해결됐어요','unresolved':'아직 해결되지 않았어요'}
SOURCES={'biz':'기업 회원 화면','link':'답변 링크','email':'이메일 (원문 그대로 등록)'}
# 무료 메일 주소는 회사 공식 메일로 보기 어려워 운영자 화면에 따로 표시
FREE_MAIL={'gmail.com','naver.com','daum.net','hanmail.net','kakao.com','nate.com','hotmail.com','outlook.com','yahoo.com','icloud.com','me.com','live.com','msn.com','korea.com','empas.com','dreamwiz.com','paran.com','proton.me','protonmail.com'}
def official_domain(email):return (email or '').rsplit('@',1)[-1].lower() not in FREE_MAIL
PUBLIC_STEPS=['제보 접수','운영자 검토','기업 전달 시도','기업 전달 확인','기업 공식 답변','소비자 확인','종결']
# 진행 단계 표시: 제보자 본인 화면은 5단계, 외부 공개 화면은 3단계(화면 이름은 app.py my_names·pub_names). 색은 접수증 색(.st-1~6)에서 고름.
MY_STEPS=[('접수','소비자가 민원 제출'),('검토','플랫폼에서 내용 심사'),('기업 전달','해당 기업에 민원 전달'),('기업 답변·처리','기업과 소비자가 해결 진행'),('완료·평가','소비자가 결과를 확인하고 평가')]
PUB_STAGES=['접수','처리 중','종결']
MY_COLOR=[1,2,3,5,6];PUB_COLOR=[1,5,6]
STATUS_MY={'접수':1,'검토 중':2,'추가 확인':2,'기업 답변 대기':3,'기업 답변 도착':4,'종결':5}
# 소보루 등급 (BBB처럼 A+~F): 최근 3년, 기업에 전달된 확인된 제보로 매김. 기준은 /companies/grade에 공개
ANSWER_DAYS=14  # 기업에 전달하고 이 날수가 지나도록 답이 없으면 '답변 없음'
GRADE_YEARS=3
GRADE_PTS={'answer':50,'resolve':30,'speed':20}
GRADE_CUTS=[(97,'A+'),(94,'A'),(90,'A-'),(87,'B+'),(84,'B'),(80,'B-'),(77,'C+'),(74,'C'),(70,'C-'),(67,'D+'),(64,'D'),(60,'D-'),(0,'F')]
GRADE_SPEED=[(24,20),(72,16),(168,10),(336,5)]  # 첫 답변까지 걸린 시간(중앙값, 시간) → 점수
GRADE_WORDS={'A':'제보에 빠르게 답하고, 해결도 잘 하는 기업이에요','B':'대체로 답하지만 아쉬운 점이 조금 있어요','C':'답이 늦거나 해결되지 않은 제보가 자주 있어요',
             'D':'답 없이 남은 제보가 많아요','F':'제보에 거의 답하지 않아요'}

def migrate(db):
    cols={r['name'] for r in db.execute('PRAGMA table_info(cases)')}
    for c in CASE_COLS:
        if c not in cols:db.execute(f"ALTER TABLE cases ADD COLUMN {c} TEXT NOT NULL DEFAULT ''")
    if 'forwarded_at' not in cols:
        # 예전 기록에서 실제 전달 시각을 찾아 채움: 답변 링크 발급, 가입 기업 연결 (기업 담당자 화면에 이미 보이던 제보)
        db.execute("UPDATE cases SET forwarded_at=COALESCE((SELECT created FROM company_invites i WHERE i.case_id=cases.id),'')")
        db.execute("""UPDATE cases SET forwarded_at=COALESCE((SELECT MIN(created) FROM case_log l WHERE l.case_id=cases.id AND l.action LIKE '기업 연결:%'),created)
            WHERE forwarded_at='' AND company_id IS NOT NULL AND share_company=1""")
    cols={r['name'] for r in db.execute('PRAGMA table_info(companies)')}
    for c in COMPANY_COLS:
        if c not in cols:db.execute(f"ALTER TABLE companies ADD COLUMN {c} TEXT NOT NULL DEFAULT ''")
    cols={r['name'] for r in db.execute('PRAGMA table_info(messages)')}
    for c,t in MESSAGE_COLS:
        if c not in cols:db.execute(f'ALTER TABLE messages ADD COLUMN {c} {t}')
    # 기업 답변을 고칠 때 이전 글을 지우지 않고 남김 (원문 보존)
    db.execute('CREATE TABLE IF NOT EXISTS answer_revisions(id INTEGER PRIMARY KEY,message_id INTEGER NOT NULL,body TEXT NOT NULL,was_public INTEGER NOT NULL DEFAULT 0,edited_at TEXT NOT NULL,editor TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS cases_company ON cases(company_id)')

def now():return datetime.datetime.now().isoformat(timespec='seconds')
def mark(db,case_id,field):
    """처음 일어난 시각만 남긴다 (검토·전달·확인 등)."""
    db.execute(f"UPDATE cases SET {field}=? WHERE id=? AND {field}=''",(now(),case_id))

def cat_names(cat):
    """새 유형으로 거를 때 함께 볼 예전 유형까지."""
    return [cat]+[old for old,new in CATEGORY_MAP.items() if new==cat]
def cat_label(cat):return CATEGORY_MAP.get(cat,cat)

def pub(case,mask):
    """공개 화면에 쓰는 글: 운영자가 다듬은 공개용 글, 없으면 원문에서 연락처를 가린 글."""
    return {'subject':case['public_subject'] or mask(case['subject']),'body':case['public_body'] or mask(case['description']),
            'request':case['public_request'] or mask(case['request_text'])}

def reviewed(case):return bool(case['reviewed_at']) or case['status']!='접수'
def valid(case):return (reviewed(case) or case['review']=='ok') and case['review'] not in NOT_VALID

def first_answers(db,ids):
    if not ids:return {}
    q=','.join('?'*len(ids))
    return {r[0]:r[1] for r in db.execute(f"SELECT case_id,MIN(created) FROM messages WHERE author='기업 답변' AND case_id IN ({q}) GROUP BY case_id",list(ids))}

def hours(a,b):
    try:return (datetime.datetime.fromisoformat(b[:19])-datetime.datetime.fromisoformat(a[:19])).total_seconds()/3600
    except ValueError:return None
def fmt_hours(h):
    if h is None:return '–'
    return f'{h:.0f}시간' if h<48 else f'{h/24:.1f}일'

def company_stats(db,company_id,months=6):
    rows=db.execute('SELECT id,status,review,reviewed_at,created,forwarded_at,confirmed_at,outcome,rating FROM cases WHERE company_id=?',(company_id,)).fetchall()
    good=[r for r in rows if valid(r)]
    first=first_answers(db,[r['id'] for r in good])
    answered=[r for r in good if r['id'] in first]
    waits=[h for h in (hours(r['forwarded_at'],first[r['id']]) for r in answered if r['forwarded_at']) if h is not None and h>=0]
    n=len(good)
    rate=lambda k:f'{round(100*k/n)}%' if n>=MIN_N else '–'
    today=datetime.date.today().replace(day=1);monthly=[]
    for i in range(months-1,-1,-1):
        y,m=today.year,today.month-i
        while m<=0:y-=1;m+=12
        key=f'{y:04d}-{m:02d}'
        monthly.append({'label':f'{m}월','key':key,'n':sum(1 for r in good if r['created'][:7]==key),
                        'answered':sum(1 for r in answered if r['created'][:7]==key)})
    top=max([x['n'] for x in monthly]+[1])
    return {'valid':n,'answered':len(answered),'answer_rate':rate(len(answered)),'confirmed':sum(1 for r in good if r['confirmed_at']),
            'confirm_rate':rate(sum(1 for r in good if r['confirmed_at'])),'median':fmt_hours(statistics.median(waits)) if len(waits)>=MIN_N else '–','n_waits':len(waits),
            'resolved':sum(1 for r in good if r['outcome']=='resolved'),
            # 해결 비율: 결과를 알려 준 제보자 중 '해결됐어요'라고 한 비율 (알려 준 사람이 MIN_N명 이상일 때만)
            'resolve_rate':(lambda c:f"{round(100*sum(1 for r in c if r['outcome']=='resolved')/len(c))}%" if len(c)>=MIN_N else '–')([r for r in good if r['outcome'] in ('resolved','unresolved')]),
            'rating':(lambda v:f'{sum(v)/len(v):.1f}' if len(v)>=MIN_N else '–')([r['rating'] for r in good if r['rating']]),
            'monthly':monthly,'top':top,'enough':n>=MIN_N,'total':len(rows),'since':min((r['created'][:10] for r in rows),default='')}

def days_since(stamp,today=None):
    try:return ((today or datetime.date.today())-datetime.date.fromisoformat(stamp[:10])).days
    except (TypeError,ValueError):return None
def no_answer(case,has_answer,today=None):
    """기업에 전달하고 ANSWER_DAYS일이 지나도록 공식 답변이 없으면 True ('답변 없음')."""
    if has_answer or not case['forwarded_at']:return False
    d=days_since(case['forwarded_at'],today)
    return d is not None and d>=ANSWER_DAYS

def silent_companies(db,limit=None,today=None,days=365):
    """답변 없는 기업: 기업에 전달하고 ANSWER_DAYS일이 지나도록 공식 답변이 없는 확인된 제보가 1건이라도 있으면 들어감.
    제보 수(MIN_N)와 상관없음. 기업이 답하면 그 제보는 바로 빠짐. 최근 days일 동안 접수된 제보만 셈."""
    today=today or datetime.date.today()
    since=(today-datetime.timedelta(days=days)).isoformat()
    rows=[r for r in db.execute("""SELECT c.id,c.company_id,c.status,c.review,c.reviewed_at,c.created,c.forwarded_at,co.name FROM cases c JOIN companies co ON co.id=c.company_id
        WHERE co.status IN ('active','listed') AND c.forwarded_at IS NOT NULL AND c.forwarded_at!='' AND c.created>=?""",(since,)) if valid(r)]
    first=first_answers(db,[r['id'] for r in rows])
    per={}
    for r in rows:
        p=per.setdefault(r['company_id'],{'id':r['company_id'],'name':r['name'],'n':0,'silent':0,'oldest':0})
        p['n']+=1
        if no_answer(r,r['id'] in first,today):
            p['silent']+=1;p['oldest']=max(p['oldest'],days_since(r['forwarded_at'],today) or 0)
    out=sorted([p for p in per.values() if p['silent']],key=lambda p:(-p['silent'],-p['oldest'],p['name']))
    return out[:limit] if limit else out

def grade_of(score):
    return next(g for cut,g in GRADE_CUTS if score>=cut)

def company_grade(db,company_id,today=None):
    """소보루 등급과 기업 요약 숫자. 표본이 MIN_N건보다 적으면 grade=''.
    점수(100) = 답변 비율 50 + 해결 비율 30 + 답변 속도 20. 전달하고 아직 ANSWER_DAYS일이 안 된 제보는 '기다리는 중'이라 빼고 셈."""
    today=today or datetime.date.today()
    since=(today-datetime.timedelta(days=365*GRADE_YEARS)).isoformat();year=(today-datetime.timedelta(days=365)).isoformat()
    rows=[r for r in db.execute('SELECT id,status,review,reviewed_at,created,forwarded_at,confirmed_at,outcome FROM cases WHERE company_id=? AND created>=?',(company_id,since)) if valid(r)]
    first=first_answers(db,[r['id'] for r in rows])
    fw=[r for r in rows if r['forwarded_at']]
    silent={r['id'] for r in fw if no_answer(r,r['id'] in first,today)}
    scored=[r for r in fw if r['id'] in first or r['id'] in silent]
    answered=[r for r in scored if r['id'] in first]
    told=[r for r in answered if r['outcome'] in ('resolved','unresolved')]
    resolved=[r for r in told if r['outcome']=='resolved']
    waits=sorted(h for h in (hours(r['forwarded_at'],first[r['id']]) for r in answered) if h is not None and h>=0)
    out={'n':len(rows),'scored':len(scored),'silent':len(silent),'answered':len(answered),'told':len(told),'resolved':len(resolved),
         'resolved_year':sum(1 for r in rows if r['outcome']=='resolved' and r['created']>=year),'n_year':sum(1 for r in rows if r['created']>=year),
         'grade':'','score':None,'parts':[],'word':'','tone':'none','min_n':MIN_N,'days':ANSWER_DAYS,'years':GRADE_YEARS}
    if len(scored)<MIN_N:return out
    a=len(answered)/len(scored)
    # 해결 비율은 결과를 알려 준 제보자가 MIN_N명보다 적으면 알 수 없어 중간값(절반)으로 둠
    r=len(resolved)/len(told) if len(told)>=MIN_N else None
    med=statistics.median(waits) if waits else None
    sp=next((p for h,p in GRADE_SPEED if med is not None and med<=h),0)
    pa=round(GRADE_PTS['answer']*a);pr=round(GRADE_PTS['resolve']*(r if r is not None else .5));score=pa+pr+sp
    g=grade_of(score)
    out.update(grade=g,score=score,word=GRADE_WORDS[g[0]],tone=g[0].lower(),resolve_known=r is not None,
               parts=[('answer','답변',pa,GRADE_PTS['answer'],f'{round(100*a)}% 답변'),
                      ('resolve','해결',pr,GRADE_PTS['resolve'],f'{round(100*r)}% 해결' if r is not None else '확인 적음 · 절반으로 계산'),
                      ('speed','속도',sp,GRADE_PTS['speed'],f'보통 {fmt_hours(med)}' if med is not None else '답변 없음')])
    return out

def timeline(db,case,mask):
    """개별 제보의 진행 이력. 실제로 일어난 일만 시간순으로. (이력, 지금 단계 번호 1~7)"""
    ev=[('me','제보 접수',case['created'],'')]
    if reviewed(case):ev.append(('sys','운영자 검토',case['reviewed_at'],'운영자가 내용과 개인정보를 확인했어요.'))
    if case['forwarded_at']:ev.append(('sys','기업 전달 시도',case['forwarded_at'],'센터가 기업에 제보 내용을 전달했어요.'))
    if case['seen_at']:ev.append(('sys','기업 전달 확인',case['seen_at'],'기업 담당자가 제보를 열어 확인했어요.'))
    msgs=db.execute("SELECT author,body,created FROM messages WHERE case_id=? AND public=1 AND author IN ('기업 답변','제보자') ORDER BY id",(case['id'],)).fetchall()
    # 기업 답변 원문은 이력 아래 '공식 답변'에 그대로 싣고, 이력에는 등록 시각만 남김
    for m in msgs:ev.append(('co','기업 공식 답변',m['created'],'') if m['author']=='기업 답변' else ('me','제보자 추가 의견',m['created'],mask(m['body'])))
    if case['confirmed_at']:ev.append(('me','소비자 확인',case['confirmed_at'],{'resolved':'제보자가 해결됐다고 확인했어요.','unresolved':'제보자가 아직 해결되지 않았다고 알렸어요.'}.get(case['outcome'],'제보자가 처리 결과를 확인했어요.')))
    if case['status']=='종결':ev.append(('sys','종결',case['closed_at'],''))
    has_answer=db.execute("SELECT 1 FROM messages WHERE case_id=? AND author='기업 답변'",(case['id'],)).fetchone() is not None
    step=my_step(case,has_answer)
    ev.sort(key=lambda e:e[2] or '9')  # 시각을 모르는 예전 기록은 뒤로
    return ev,step,has_answer

def step_of(case,has_answer):
    """공개 7단계 중 지금 단계 (1~7). 실제로 기록된 일까지만."""
    step=1+reviewed(case)
    for i,ok in ((3,case['forwarded_at']),(4,case['seen_at']),(5,has_answer),(6,case['confirmed_at']),(7,case['status']=='종결')):
        if ok:step=i
    return step

def my_step(case,has_answer=False):
    """제보자 5단계 중 지금 단계 (1~5). 운영자가 정한 진행 상태와 실제 기록 중 앞선 쪽."""
    keys=case.keys()
    has=lambda k:k in keys and case[k]
    step=STATUS_MY.get(case['status'],1)
    if has('reviewed_at'):step=max(step,2)
    if has('forwarded_at') or has('seen_at'):step=max(step,3)
    if has_answer:step=max(step,4)
    if has('confirmed_at'):step=5
    return step

def pub_step(my):
    """제보자 5단계를 공개 3단계로: 접수 → 접수, 검토·기업 전달·기업 답변·처리 → 처리 중, 완료·평가 → 종결."""
    return 1 if my<=1 else 3 if my>=5 else 2

def visible_company(db,company_id):
    return db.execute("SELECT * FROM companies WHERE id=? AND status IN ('active','listed')",(company_id,)).fetchone()

def install(S):
    app=S.app;conn=S.conn;mask=S.mask_personal;norm=S.norm_company
    S.COMPANY_STATUSES['listed']='등록 (미가입)'
    with conn() as db:migrate(db)
    app.jinja_env.globals.update(jebo_no_answer=no_answer,JEBO_ANSWER_DAYS=ANSWER_DAYS,cat_label=cat_label,PUBLIC_STEPS=PUBLIC_STEPS,MY_COLOR=MY_COLOR,PUB_COLOR=PUB_COLOR,my_step=my_step,pub_step=pub_step,JEBO_MIN_N=MIN_N)

    def names(co):return [co['name'],co['brand'],co['biz_name']]+[a.strip() for a in (co['aliases'] or '').split(',') if a.strip()]
    def search(db,q,limit=30):
        t=norm(q)
        if not t:return []
        rows=db.execute("""SELECT co.*,(SELECT COUNT(*) FROM cases c WHERE c.company_id=co.id AND c.public_consent=1 AND c.published=1) AS n_public,
            (SELECT COUNT(*) FROM cases c WHERE c.company_id=co.id) AS n_all FROM companies co WHERE co.status IN ('active','listed')""").fetchall()
        hits=[]
        for co in rows:
            ns=[norm(n) for n in names(co) if n]
            if any(n==t for n in ns):hits.append((0,co))
            elif any(n.startswith(t) for n in ns):hits.append((1,co))
            elif any(t in n for n in ns):hits.append((2,co))
        hits.sort(key=lambda h:(h[0],-h[1]['n_all'],h[1]['name']))
        return [co for _,co in hits[:limit]]
    S.company_search=search

    @app.route('/companies')
    def companies():
        q=request.args.get('q','').strip()[:60]
        with conn() as db:
            found=search(db,q) if q else []
            busy=[] if q else db.execute("""SELECT co.*,COUNT(c.id) AS n_public FROM companies co JOIN cases c ON c.company_id=co.id AND c.public_consent=1 AND c.published=1
                WHERE co.status IN ('active','listed') GROUP BY co.id ORDER BY n_public DESC,co.name LIMIT 30""").fetchall()
            grades={c['id']:company_grade(db,c['id'])['grade'] for c in list(found)+list(busy)}
        return render_template('companies.html',q=q,found=found,busy=busy,grades=grades)

    @app.route('/companies/no-answer')
    def companies_silent():
        # 답변 없는 기업 (검은고양이처럼): 제보 1건이어도 전달 뒤 ANSWER_DAYS일 동안 답이 없으면 공개
        with conn() as db:rows=silent_companies(db)
        return render_template('companies_silent.html',rows=rows,days=ANSWER_DAYS)

    @app.route('/companies/grade')
    def company_grade_guide():
        # 소보루 등급 기준 공개 페이지 (BBB처럼 무엇으로 매기는지 그대로 보여 줌)
        return render_template('company_grade.html',cuts=GRADE_CUTS,pts=GRADE_PTS,speed=GRADE_SPEED,words=GRADE_WORDS,days=ANSWER_DAYS,years=GRADE_YEARS,min_n=MIN_N)

    @app.route('/companies/suggest')
    def companies_suggest():
        q=request.args.get('q','').strip()[:60]
        with conn() as db:rows=search(db,q,8) if len(norm(q))>=1 else []
        resp=jsonify([{'id':c['id'],'name':c['name'],'sub':' · '.join(x for x in (c['brand'],c['biz_name']) if x and x!=c['name']),'n':c['n_public'],'member':c['status']=='active'} for c in rows])
        resp.headers['Cache-Control']='no-store'
        return resp

    @app.route('/companies/<int:company_id>')
    def company_page(company_id):
        cat=request.args.get('category','')
        page=max(1,request.args.get('page',1,type=int));size=20
        with conn() as db:
            co=visible_company(db,company_id)
            if not co:abort(404)
            st=company_stats(db,company_id);gr=company_grade(db,company_id)
            where="company_id=? AND public_consent=1 AND published=1";args=[company_id]
            if cat in S.report_categories():
                where+=f" AND category IN ({','.join('?'*len(cat_names(cat)))})";args+=cat_names(cat)
            else:cat=''
            total=db.execute('SELECT COUNT(*) FROM cases WHERE '+where,args).fetchone()[0]
            rows=db.execute('SELECT * FROM cases WHERE '+where+' ORDER BY id DESC LIMIT ? OFFSET ?',args+[size,(page-1)*size]).fetchall()
            first=first_answers(db,[r['id'] for r in rows])
            cats=db.execute("SELECT category,COUNT(*) AS n FROM cases WHERE company_id=? AND public_consent=1 AND published=1 GROUP BY category",(company_id,)).fetchall()
        by_cat={}
        for r in cats:by_cat[cat_label(r['category'])]=by_cat.get(cat_label(r['category']),0)+r['n']
        cases=[dict(id=r['id'],category=cat_label(r['category']),created=r['created'][:10],status=r['status'],answered=r['id'] in first,confirmed=bool(r['confirmed_at']),step=pub_step(my_step(r,r['id'] in first)),
                    silent=no_answer(r,r['id'] in first),outcome=r['outcome'],**pub(r,mask)) for r in rows]
        indexable=bool(total or co['statement'])
        return render_template('company_page.html',co=co,st=st,gr=gr,cases=cases,total=total,page=page,pages=max(1,-(-total//size)),cat=cat,by_cat=by_cat,
                               categories=S.report_categories(),indexable=indexable,today=datetime.date.today().isoformat(),aka=[n for n in names(co)[1:] if n and n!=co['name']])

    # ---- 2차: 기업 공식 이메일 인증, 공식 입장, 답변 수정 이력, 소비자 해결 확인 ----
    import hashlib,secrets
    from flask import redirect,flash,session
    def token_hash(t):return hashlib.sha256(t.encode()).hexdigest()
    def send_verify(db,company):
        """담당자 이메일로 인증 링크를 보냄. 메일 설정이 없으면 False (운영자가 직접 확인)."""
        token=secrets.token_urlsafe(24)
        db.execute('UPDATE companies SET email_token=? WHERE id=?',(token_hash(token),company['id']))
        if not S.notify.email_ready():return False
        link=url_for('biz_verify',token=token,_external=True)
        body=(f"{company['contact_name']}님, {S.notify.site_name()} 기업 회원 가입을 신청해 주셔서 감사합니다.\n\n"
              f"아래 링크를 누르면 {company['contact_email']} 주소가 {company['name']}의 담당자 이메일로 확인돼요.\n{link}\n\n"
              "이메일 확인과 별개로 센터가 사업자 정보를 확인한 뒤 승인해요. 직접 신청하지 않았다면 이 메일을 무시해 주세요.")
        try:S.notify.send_email(company['contact_email'],f'[{S.notify.site_name()}] 기업 담당자 이메일 확인',body)
        except Exception:return False
        return True
    S.send_company_verify=send_verify

    @app.route('/biz/verify/<token>')
    def biz_verify(token):
        if len(token)>100:abort(404)
        with conn() as db:
            co=db.execute("SELECT * FROM companies WHERE email_token=? AND email_token!=''",(token_hash(token),)).fetchone()
            if not co:flash('링크가 맞지 않거나 이미 쓴 링크예요.');return redirect(url_for('biz_login'))
            db.execute("UPDATE companies SET email_verified_at=?,email_token='' WHERE id=?",(now(),co['id']))
        flash('담당자 이메일을 확인했어요. 센터가 사업자 정보를 확인한 뒤 승인해요.')
        return redirect(url_for('biz_home'))

    @app.route('/biz/verify/resend',methods=['POST'])
    @S.biz_only
    def biz_verify_resend():
        if g.biz_preview or not g.company or g.company['email_verified_at']:return redirect(url_for('biz_home'))
        with conn() as db:sent=send_verify(db,g.company)
        flash('인증 메일을 다시 보냈어요. 메일함을 확인해 주세요.' if sent else '지금은 메일을 보낼 수 없어요. 센터가 연락드려 직접 확인할게요.')
        return redirect(url_for('biz_home'))

    @app.route('/biz/statement',methods=['GET','POST'])
    @S.biz_active
    def biz_statement():
        # 기업 공식 입장: 기업이 쓰고, 센터가 확인한 뒤 기업 페이지에 그대로 공개 (센터는 글을 고치지 않음)
        if request.method=='POST':
            if g.biz_preview:flash('미리보기에서는 저장할 수 없어요.');return redirect(url_for('biz_statement'))
            text=request.form.get('statement','').strip()
            if len(text)>3000:flash('공식 입장은 3,000자 이내로 적어 주세요.');return redirect(url_for('biz_statement'))
            with conn() as db:db.execute('UPDATE companies SET statement_draft=?,statement_draft_at=? WHERE id=?',(text,now() if text else '',g.company['id']))
            flash('보냈어요. 센터가 확인한 뒤 기업 페이지에 공개돼요.' if text else '보낸 글을 지웠어요.')
            return redirect(url_for('biz_statement'))
        return render_template('biz_statement.html')

    @app.route('/biz/answer/<int:message_id>/edit',methods=['POST'])
    @S.biz_active
    def biz_answer_edit(message_id):
        # 답변을 고치면 이전 글은 수정 이력에 남고, 사이트 공개는 센터가 다시 확인할 때까지 내려감
        if g.biz_preview:flash('미리보기에서는 고칠 수 없어요.');return redirect(url_for('biz_home'))
        body=request.form.get('response','').strip()
        with conn() as db:
            m=db.execute("""SELECT m.* FROM messages m JOIN cases c ON c.id=m.case_id WHERE m.id=? AND m.author='기업 답변' AND m.source IN ('biz','')
                AND c.company_id=? AND c.share_company=1 AND c.forwarded_at!=''""",(message_id,g.company['id'])).fetchone()
            if not m:abort(404)
            if not body or len(body)>5000:flash('답변을 5,000자 이내로 적어 주세요.');return redirect(url_for('biz_case',case_id=m['case_id'])+'#answer')
            if body!=m['body']:
                who=g.company['name']+' '+g.biz_user['name']
                db.execute('INSERT INTO answer_revisions(message_id,body,was_public,edited_at,editor) VALUES(?,?,?,?,?)',(m['id'],m['body'],m['public'],now(),who))
                db.execute('UPDATE messages SET body=?,edited=?,public=0 WHERE id=?',(body,now(),m['id']))
                db.execute('INSERT INTO case_log(case_id,actor,action,created) VALUES(?,?,?,?)',(m['case_id'],who,'기업 답변 수정 (이전 글 보관)',now()))
                flash('답변을 고쳤어요. 이전 글은 수정 이력에 남고, 사이트 공개는 센터가 다시 확인해요.' if m['public'] else '답변을 고쳤어요. 이전 글은 수정 이력에 남아요.')
        return redirect(url_for('biz_case',case_id=m['case_id'])+'#answer')

    @app.route('/case/outcome',methods=['POST'])
    def case_outcome():
        # 제보자가 처리 결과를 확인: 해결됨 / 아직 해결 안 됨 (바꿀 수 있고, 처음 확인한 시각은 남김)
        case_id=session.get('case_id')
        if not case_id:return redirect(url_for('lookup'))
        outcome=request.form.get('outcome','')
        if outcome not in OUTCOMES:abort(400)
        rating=request.form.get('rating',type=int)
        if rating is not None and not 1<=rating<=5:rating=None
        with conn() as db:
            case=db.execute('SELECT id,outcome FROM cases WHERE id=?',(case_id,)).fetchone()
            if not case:abort(404)
            if not db.execute("SELECT 1 FROM messages WHERE case_id=? AND author='기업 답변'",(case_id,)).fetchone():abort(400)
            db.execute('UPDATE cases SET outcome=?,rating=COALESCE(?,rating) WHERE id=?',(outcome,rating,case_id));mark(db,case_id,'confirmed_at')
            if outcome!=case['outcome']:db.execute('INSERT INTO case_log(case_id,actor,action,created) VALUES(?,?,?,?)',(case_id,'제보자',f'처리 결과 확인: {OUTCOMES[outcome]}',now()))
        flash('알려 주셔서 고마워요. 센터와 기업에 전달돼요.')
        return redirect(url_for('case_detail')+'#outcome')
    app.jinja_env.globals.update(JEBO_OUTCOMES=OUTCOMES,JEBO_SOURCES=SOURCES,official_domain=official_domain)
