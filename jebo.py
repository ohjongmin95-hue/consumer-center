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
REVIEWS={'':'검토 전','ok':'정상 제보','duplicate':'중복 제보','rejected':'반려 (허위·부적절·대상 아님)'}
CASE_COLS=('public_subject','public_body','public_request','review','review_note','reviewed_at','occurred_on','forwarded_at','seen_at','confirmed_at','closed_at')
COMPANY_COLS=('brand','biz_name','official_email','statement','statement_at')
PUBLIC_STEPS=['제보 접수','운영자 검토','기업 전달 시도','기업 전달 확인','기업 공식 답변','소비자 확인','종결']

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
def valid(case):return reviewed(case) and case['review'] not in NOT_VALID

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
    rows=db.execute('SELECT id,status,review,reviewed_at,created,forwarded_at,confirmed_at FROM cases WHERE company_id=?',(company_id,)).fetchall()
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
            'monthly':monthly,'top':top,'enough':n>=MIN_N,'total':len(rows),'since':min((r['created'][:10] for r in rows),default='')}

def timeline(db,case,mask):
    """개별 제보의 진행 이력. 실제로 일어난 일만 시간순으로. (이력, 지금 단계 번호 1~7)"""
    ev=[('me','제보 접수',case['created'],'')]
    if reviewed(case):ev.append(('sys','운영자 검토',case['reviewed_at'],'운영자가 내용과 개인정보를 확인했어요.'))
    if case['forwarded_at']:ev.append(('sys','기업 전달 시도',case['forwarded_at'],'센터가 기업에 제보 내용을 전달했어요.'))
    if case['seen_at']:ev.append(('sys','기업 전달 확인',case['seen_at'],'기업 담당자가 제보를 열어 확인했어요.'))
    msgs=db.execute("SELECT author,body,created FROM messages WHERE case_id=? AND public=1 AND author IN ('기업 답변','제보자') ORDER BY id",(case['id'],)).fetchall()
    # 기업 답변 원문은 이력 아래 '공식 답변'에 그대로 싣고, 이력에는 등록 시각만 남김
    for m in msgs:ev.append(('co','기업 공식 답변',m['created'],'') if m['author']=='기업 답변' else ('me','제보자 추가 의견',m['created'],mask(m['body'])))
    if case['confirmed_at']:ev.append(('me','소비자 확인',case['confirmed_at'],'제보자가 처리 결과를 확인했어요.'))
    if case['status']=='종결':ev.append(('sys','종결',case['closed_at'],''))
    has_answer=db.execute("SELECT 1 FROM messages WHERE case_id=? AND author='기업 답변'",(case['id'],)).fetchone() is not None
    step=step_of(case,has_answer)
    ev.sort(key=lambda e:e[2] or '9')  # 시각을 모르는 예전 기록은 뒤로
    return ev,step,has_answer

def step_of(case,has_answer):
    """공개 7단계 중 지금 단계 (1~7). 실제로 기록된 일까지만."""
    step=1+reviewed(case)
    for i,ok in ((3,case['forwarded_at']),(4,case['seen_at']),(5,has_answer),(6,case['confirmed_at']),(7,case['status']=='종결')):
        if ok:step=i
    return step

def visible_company(db,company_id):
    return db.execute("SELECT * FROM companies WHERE id=? AND status IN ('active','listed')",(company_id,)).fetchone()

def install(S):
    app=S.app;conn=S.conn;mask=S.mask_personal;norm=S.norm_company
    S.COMPANY_STATUSES['listed']='등록 (미가입)'
    with conn() as db:migrate(db)
    app.jinja_env.globals.update(cat_label=cat_label,PUBLIC_STEPS=PUBLIC_STEPS,JEBO_MIN_N=MIN_N)

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
        return render_template('companies.html',q=q,found=found,busy=busy)

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
            st=company_stats(db,company_id)
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
        cases=[dict(id=r['id'],category=cat_label(r['category']),created=r['created'][:10],status=r['status'],answered=r['id'] in first,confirmed=bool(r['confirmed_at']),step=step_of(r,r['id'] in first),**pub(r,mask)) for r in rows]
        indexable=bool(total or co['statement'])
        return render_template('company_page.html',co=co,st=st,cases=cases,total=total,page=page,pages=max(1,-(-total//size)),cat=cat,by_cat=by_cat,
                               categories=S.report_categories(),indexable=indexable,today=datetime.date.today().isoformat(),aka=[n for n in names(co)[1:] if n and n!=co['name']])
