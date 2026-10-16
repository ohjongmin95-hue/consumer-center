"""기업 대응 관리: AI 기업 입장 요청서, 기업 연락처, 요청서 전달 기록, 기업 답변 등록.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다.
- 요청서는 제보 접수 뒤 따로 만든다(AI가 늦거나 실패해도 접수는 그대로). 키가 없으면 운영자가 직접 쓴다.
- AI에는 이름·연락처·이메일·주소·계좌번호 등을 지운 제보 내용만 보낸다. 첨부 파일은 보내지 않는다.
- 저장할 때마다 새 판으로 쌓는다. 다시 만들어도 운영자가 고친 판은 이력에 그대로 남는다.
- 이메일·카카오톡 자동 발송은 하지 않는다. 운영자가 직접 보내고 '기업 전달 완료'로 기록한다.
- 기업 답변 원문은 고치지 않고 보관한다.
"""
import datetime, json, logging, os, re, secrets, threading, urllib.error, urllib.request
from pathlib import Path
from flask import abort, flash, g, redirect, render_template, request, url_for, send_file, after_this_request

LOG=logging.getLogger(__name__)
REQ_STATUSES={'draft':'초안','approved':'관리자 승인','sent':'기업 전달 완료'}
REQ_ORIGINS={'ai':'AI 생성','manual':'직접 작성','edit':'관리자 수정','restore':'이전 판 복원'}
CHANNELS={'email':'이메일','kakao':'카카오톡 채널','phone':'전화','post':'우편','biz':'기업 회원 화면','other':'기타'}
ANSWER_FILE_TYPES={'.pdf':'pdf','.png':'png','.jpg':'jpg','.jpeg':'jpg','.webp':'webp'}
ANSWER_FILES_MAX=3
NEED='확인 필요'
CLOSING=('본 센터는 접수된 제보를 토대로 사실관계를 확인하고 있으며, 사안에 따라 향후 추가 취재 및 보도가 진행될 수 있음을 알려드립니다.\n'
         '귀사의 공식 입장을 회신해 주시면 사실관계 확인 및 향후 취재·보도 과정에 반영하겠습니다.\n감사합니다.\n\n소비자제보센터 드림\nhttps://consumerjebo.co.kr')
SYSTEM=('너는 소비자제보센터의 기업 입장 요청서 초안을 돕는다. 아래 제보 내용만 근거로 JSON을 만든다.\n'
        '원칙: 확인되지 않은 사실을 단정하지 않는다. "제보자에 따르면", "제보자는 ~라고 주장했습니다"처럼 중립적으로 쓴다. '
        '제보에 없는 사실·날짜·금액·이름을 지어내지 않는다. 없는 항목은 "확인 필요"로 쓴다. 개인정보(이름·연락처·주소·계좌·주문번호 등)는 쓰지 않는다. '
        '기업을 비난하거나 압박·위협하는 표현, 법 위반으로 단정하는 표현을 쓰지 않는다. 존댓말(합니다체)로 쓴다.\n'
        'JSON 키: company(기업명), product(제품·서비스), purchase_date(구매일), damage_date(피해 발생일), '
        'paragraphs(주요 제보 내용 2~4문단 배열, 각 문단은 "제보자에 따르면"처럼 시작하거나 주장임을 드러냄), '
        'claims(피해 주장 요약), company_response(기업의 기존 대응, 제보자 주장 기준), demands(소비자 요구사항), '
        'questions(기업에 확인할 질문 3~5개 배열, 사실관계 확인용 중립 질문).')
NAME_SAFE=re.compile(r'[\w가-힣]')
PERSONAL=[re.compile(r'(01[016789]|0\d{1,2})[-.\s]?\d{3,4}[-.\s]?\d{4}'),re.compile(r'[\w.+-]+@[\w-]+(\.[\w-]+)+'),
          re.compile(r'\d{6}\s?-\s?[1-4]\d{6}'),re.compile(r'\d{2,6}-\d{2,6}-\d{2,8}'),re.compile(r'\d+\s?동\s?\d+\s?호')]

def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS company_requests(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL,version INTEGER NOT NULL,title TEXT NOT NULL DEFAULT '',body TEXT NOT NULL DEFAULT '',
        facts TEXT NOT NULL DEFAULT '',origin TEXT NOT NULL,model TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'draft',
        approved_at TEXT NOT NULL DEFAULT '',approved_by TEXT NOT NULL DEFAULT '',sent_at TEXT NOT NULL DEFAULT '',sent_by TEXT NOT NULL DEFAULT '',sent_channel TEXT NOT NULL DEFAULT '',sent_target TEXT NOT NULL DEFAULT '',
        actor TEXT NOT NULL DEFAULT '',created TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS company_requests_case ON company_requests(case_id,version)')
    db.execute('''CREATE TABLE IF NOT EXISTS company_contacts(id INTEGER PRIMARY KEY,name TEXT NOT NULL,aliases TEXT NOT NULL DEFAULT '',homepage TEXT NOT NULL DEFAULT '',main_email TEXT NOT NULL DEFAULT '',
        cs_email TEXT NOT NULL DEFAULT '',kakao_url TEXT NOT NULL DEFAULT '',manager TEXT NOT NULL DEFAULT '',checked_on TEXT NOT NULL DEFAULT '',source TEXT NOT NULL DEFAULT '',memo TEXT NOT NULL DEFAULT '',
        company_id INTEGER,created TEXT NOT NULL,updated TEXT NOT NULL)''')
    cols={r['name'] for r in db.execute('PRAGMA table_info(messages)')}
    for c,t in (('answer_company',"TEXT NOT NULL DEFAULT ''"),('answer_person',"TEXT NOT NULL DEFAULT ''"),('received_on',"TEXT NOT NULL DEFAULT ''"),
                ('channel',"TEXT NOT NULL DEFAULT ''"),('official','INTEGER NOT NULL DEFAULT 0')):
        if c not in cols:db.execute(f'ALTER TABLE messages ADD COLUMN {c} {t}')
    db.execute('CREATE TABLE IF NOT EXISTS answer_files(id INTEGER PRIMARY KEY,message_id INTEGER NOT NULL,case_id INTEGER NOT NULL,stored TEXT NOT NULL,original TEXT NOT NULL,created TEXT NOT NULL)')
    if 'close_reason' not in {r['name'] for r in db.execute('PRAGMA table_info(cases)')}:db.execute("ALTER TABLE cases ADD COLUMN close_reason TEXT NOT NULL DEFAULT ''")

# ---- AI 호출 ---------------------------------------------------------------------
def ai_ready():return bool(os.getenv('OPENAI_API_KEY','').strip())
def ai_model():return os.getenv('OPENAI_MODEL','').strip() or 'gpt-4.1-mini'
def post_json(url,headers,body,timeout):
    """(상태 코드, JSON). 테스트에서 바꿔 끼운다."""
    req=urllib.request.Request(url,data=json.dumps(body,ensure_ascii=False).encode(),method='POST',headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:return r.status,json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        try:return e.code,json.loads(e.read().decode() or '{}')
        except Exception:return e.code,{}

def scrub(text,extra=()):
    """AI에 보내기 전·받은 뒤 개인정보로 보이는 부분을 지움."""
    text=text or ''
    for p in PERSONAL:text=p.sub('[개인정보 삭제]',text)
    for word in extra:
        if word and len(word)>=2:text=text.replace(word,'[이름 삭제]')
    return text

def case_input(case):
    """AI에 보낼 제보 내용 (개인정보를 지운 것만)."""
    names=[case['reporter_name']] if 'reporter_name' in case.keys() else []
    keep=lambda k:scrub(case[k] if k in case.keys() else '',names)
    return {'제보 유형':keep('category'),'업체·서비스명':keep('company'),'제목':keep('subject'),'피해 발생일':case['occurred_on'] if 'occurred_on' in case.keys() else '',
            '피해 내용':keep('description'),'원하는 해결':keep('request_text')}

def ask_ai(case):
    """{facts, model}. 실패하면 예외(메시지에 키를 넣지 않음)."""
    key=os.getenv('OPENAI_API_KEY','').strip()
    if not key:raise RuntimeError('OpenAI API 키가 없어요')
    body={'model':ai_model(),'temperature':0.2,'response_format':{'type':'json_object'},
          'messages':[{'role':'system','content':_branded(SYSTEM)},{'role':'user','content':json.dumps(case_input(case),ensure_ascii=False)}]}
    st,res=post_json('https://api.openai.com/v1/chat/completions',{'Authorization':'Bearer '+key,'Content-Type':'application/json'},body,45)
    if st!=200:raise RuntimeError(f'AI 응답 오류 ({st}) '+str((res.get('error') or {}).get('message',''))[:120].replace(key,'***'))
    try:facts=json.loads(res['choices'][0]['message']['content'])
    except (KeyError,IndexError,TypeError,ValueError):raise RuntimeError('AI 응답을 읽지 못했어요')
    return clean_facts(facts,case),res.get('model') or ai_model()

def clean_facts(facts,case):
    """AI 결과 다듬기: 빈칸은 '확인 필요', 개인정보 다시 지움, 문단 2~4개·질문 3~5개."""
    if not isinstance(facts,dict):raise RuntimeError('AI 응답 형식이 달라요')
    names=[case['reporter_name']] if 'reporter_name' in case.keys() else []
    s=lambda v:scrub(str(v).strip(),names) if v not in (None,'') else NEED
    out={k:s(facts.get(k)) for k in ('company','product','purchase_date','damage_date','claims','company_response','demands')}
    paras=[scrub(str(p).strip(),names) for p in (facts.get('paragraphs') or []) if str(p).strip()][:4]
    qs=[scrub(str(q).strip(),names) for q in (facts.get('questions') or []) if str(q).strip()][:5]
    if len(paras)<1 or len(qs)<1:raise RuntimeError('AI가 요청서 내용을 채우지 못했어요')
    while len(qs)<3:qs.append('위 내용에 대한 귀사의 사실관계 확인과 공식 입장을 부탁드립니다.' if len(qs)==1 else '향후 재발 방지나 소비자 안내 계획이 있다면 알려 주시기 바랍니다.')
    out['paragraphs']=paras;out['questions']=qs[:5]
    return out

def _branded(text):
    # 기본 문구 속 '소비자제보센터'를 지금 사이트 이름(관리자 설정)으로 바꿈
    import notify
    return notify.branded(text)

def compose(facts,case_company,public_url):
    """요청서 양식(운영자가 정한 문구)에 내용을 채워 (제목, 본문)."""
    name=facts.get('company') if facts.get('company') and facts.get('company')!=NEED else case_company
    title=f'[소비자제보센터] {name} 관련 사실관계 확인 및 공식 입장 요청'
    parts=['안녕하세요. 소비자제보센터입니다.',
           '본 센터에 귀사와 관련한 소비자 피해 제보가 접수돼 사실관계 확인 및 공식 입장을 요청드립니다.','',
           '■ 주요 제보 내용','\n\n'.join(facts['paragraphs']),'',
           '■ 확인 요청 사항','\n'.join(f'{i}. {q}' for i,q in enumerate(facts['questions'],1))]
    if public_url:parts+=['','■ 제보 내용 확인',public_url]
    parts+=['',CLOSING]
    return _branded(title),_branded('\n'.join(parts))

def blank_facts(case):
    return {'company':case['company'],'paragraphs':['제보자에 따르면 (주요 제보 내용을 2~4문단으로 적어 주세요.)'],
            'questions':['(확인할 내용 1)','(확인할 내용 2)','(확인할 내용 3)']}

def install(S):
    app=S.app;conn=S.conn;now=S.now;jebo=S.jebo
    with conn() as db:migrate(db)
    S.jebo.SOURCES.setdefault('admin','운영자 등록 (원문 그대로)')
    S.ops.NOTICE_KINDS.setdefault('request','입장 요청서 전달')
    app.jinja_env.globals.update(REQ_STATUSES=REQ_STATUSES,REQ_ORIGINS=REQ_ORIGINS,DESK_CHANNELS=CHANNELS,desk_ai_ready=ai_ready)

    def public_url(case,link=None):
        # link: 접수 직후 뒤에서 만들 때 요청 안에서 미리 만들어 둔 주소 (요청 밖에서는 url_for를 쓸 수 없음)
        ok=case['public_consent'] and case['published'] and case['review'] not in jebo.NOT_VALID
        return (link or url_for('public_case',case_id=case['id'],_external=True)) if ok else ''
    def latest(db,case_id):
        return db.execute('SELECT * FROM company_requests WHERE case_id=? ORDER BY version DESC LIMIT 1',(case_id,)).fetchone()
    def add_version(db,case_id,title,body,origin,facts=None,model='',error='',actor=''):
        cur=latest(db,case_id)
        v=(cur['version'] if cur else 0)+1
        db.execute('INSERT INTO company_requests(case_id,version,title,body,facts,origin,model,error,actor,created) VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (case_id,v,title,body,json.dumps(facts,ensure_ascii=False) if facts else '',origin,model,error,actor,now()))
        return v

    def generate(case_id,actor='자동',link=None):
        """AI로 새 판을 만듦. 실패하면 오류만 남김(이미 판이 있으면 그대로 두고 기록만)."""
        with conn() as db:case=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        if not case or not case['share_company']:return False  # 기업 전달에 동의하지 않은 제보는 요청서를 만들지 않음
        try:
            facts,model=ask_ai(case)
        except Exception as e:  # 네트워크·응답 오류 모두 접수에 영향 없이 기록만
            msg=str(e)[:200]
            LOG.warning('기업 입장 요청서 AI 생성 실패 (제보 %s): %s',case_id,msg)
            with conn() as db:
                if not latest(db,case_id):add_version(db,case_id,'','','ai',error=msg,actor=actor)
                S.log_case(db,case_id,'AI 입장 요청서 생성 실패: '+msg[:60])
            return False
        with conn() as db:
            case=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
            title,body=compose(facts,case['company'],public_url(case,link))
            v=add_version(db,case_id,title,body,'ai',facts,model,actor=actor)
            S.log_case(db,case_id,f'AI 입장 요청서 {v}판 생성')
        return True
    S.desk_generate=generate

    def generate_later(case_id):
        # 접수 응답을 기다리게 하지 않도록 뒤에서 만듦
        if not ai_ready():return
        link=url_for('public_case',case_id=case_id,_external=True)
        def run(resp):
            threading.Thread(target=generate,args=(case_id,'자동',link),daemon=True).start();return resp
        after_this_request(run)
    S.desk_after_submit=generate_later

    # ---- 기업 연락처 --------------------------------------------------------------
    def find_contact(db,case):
        rows=db.execute('SELECT * FROM company_contacts ORDER BY updated DESC').fetchall()
        if case['company_id']:
            hit=next((r for r in rows if r['company_id']==case['company_id']),None)
            if hit:return hit
        t=S.norm_company(case['company'])
        if not t:return None
        for r in rows:
            names=[r['name']]+[a.strip() for a in (r['aliases'] or '').split(',') if a.strip()]
            if any(S.norm_company(n)==t for n in names):return r
        return None
    def contact_history(db,contact):
        names={S.norm_company(n) for n in [contact['name']]+[a.strip() for a in (contact['aliases'] or '').split(',') if a.strip()] if n}
        cases=[r for r in db.execute('SELECT id,receipt,subject,company,company_id,status,created FROM cases ORDER BY id DESC LIMIT 2000').fetchall()
               if S.norm_company(r['company']) in names or (contact['company_id'] and r['company_id']==contact['company_id'])]
        ids=[c['id'] for c in cases]
        if not ids:return [],0,0
        q=','.join('?'*len(ids))
        sent=db.execute(f"SELECT COUNT(DISTINCT case_id) FROM company_requests WHERE status='sent' AND case_id IN ({q})",ids).fetchone()[0]
        answered=db.execute(f"SELECT COUNT(DISTINCT case_id) FROM messages WHERE author='기업 답변' AND case_id IN ({q})",ids).fetchone()[0]
        return cases,sent,answered
    CONTACT_FIELDS=(('name',120),('aliases',300),('homepage',300),('main_email',150),('cs_email',150),('kakao_url',300),('manager',200),('checked_on',10),('source',200),('memo',1000))
    def save_contact(db,form,contact_id=None,company_id=None):
        f={k:form.get(k,'').strip()[:n] for k,n in CONTACT_FIELDS}
        if not f['name']:return None,'기업명을 넣어 주세요.'
        for k in ('main_email','cs_email'):
            if f[k] and not S.MEMBER_EMAIL_RE.match(f[k]):return None,'이메일 주소를 확인해 주세요.'
        for k in ('homepage','kakao_url'):
            if f[k] and not re.match(r'^https?://',f[k]):f[k]='https://'+f[k]
        if f['kakao_url'] and not re.match(r'^https://(pf\.kakao\.com|open\.kakao\.com|talk\.kakao\.com|accounts\.kakao\.com)/',f['kakao_url']):return None,'카카오톡 채널 주소는 https://pf.kakao.com/... 처럼 넣어 주세요.'
        if f['checked_on'] and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',f['checked_on']):f['checked_on']=''
        if contact_id:
            db.execute(f"UPDATE company_contacts SET {','.join(k+'=?' for k,_ in CONTACT_FIELDS)},updated=? WHERE id=?",[f[k] for k,_ in CONTACT_FIELDS]+[now(),contact_id])
            return contact_id,'연락처를 저장했어요.'
        cur=db.execute(f"INSERT INTO company_contacts({','.join(k for k,_ in CONTACT_FIELDS)},company_id,created,updated) VALUES({','.join('?'*(len(CONTACT_FIELDS)+3))})",
                       [f[k] for k,_ in CONTACT_FIELDS]+[company_id,now(),now()])
        return cur.lastrowid,'연락처를 등록했어요.'

    @app.route('/admin/contacts',methods=['GET','POST'])
    @S.admin_only
    def admin_contacts():
        with conn() as db:
            if request.method=='POST':
                cid=request.form.get('id',type=int)
                if request.form.get('action')=='delete' and cid:
                    db.execute('DELETE FROM company_contacts WHERE id=?',(cid,));flash('연락처를 지웠어요.')
                    return redirect(url_for('admin_contacts'))
                saved,msg=save_contact(db,request.form,cid)
                flash(msg);return redirect(url_for('admin_contacts',edit=saved or cid or '')+('#c%d'%saved if saved else ''))
            q=request.args.get('q','').strip()[:60]
            rows=db.execute('SELECT * FROM company_contacts ORDER BY name').fetchall()
            if q:rows=[r for r in rows if S.norm_company(q) in S.norm_company(r['name']+','+r['aliases'])]
            stats={r['id']:contact_history(db,r) for r in rows}
            edit=request.args.get('edit',type=int)
        return render_template('admin_contacts.html',rows=rows,stats=stats,q=q,edit=edit)

    # ---- 제보 상세 화면 -----------------------------------------------------------
    def context(db,case):
        versions=db.execute('SELECT * FROM company_requests WHERE case_id=? ORDER BY version DESC',(case['id'],)).fetchall()
        cur=next((v for v in versions if v['body']),None)
        files={}
        for f in db.execute('SELECT * FROM answer_files WHERE case_id=? ORDER BY id',(case['id'],)):files.setdefault(f['message_id'],[]).append(f)
        failed=versions[0] if versions and not versions[0]['body'] else None
        return dict(req=cur,versions=[v for v in versions if v['body']],failed=failed,contact=find_contact(db,case),public_url=public_url(case),
                    answer_files=files,today=datetime.date.today().isoformat())
    S.desk_context=context

    def handle_form(db,case,form):
        cid=case['id'];who=S.actor_name()
        cur=db.execute("SELECT * FROM company_requests WHERE case_id=? AND body!='' ORDER BY version DESC LIMIT 1",(cid,)).fetchone()
        if form=='req_generate':
            if not ai_ready():flash('AI 키가 없어 직접 작성으로 만들었어요.');form='req_manual'
            else:
                ok=generate(cid,who)
                flash('AI가 새 판을 만들었어요. 이전 판은 이력에 남아 있어요.' if ok else 'AI가 요청서를 만들지 못했어요. 잠시 뒤 다시 누르거나 직접 써 주세요.');return
        if form=='req_manual':
            title,body=compose(blank_facts(case),case['company'],public_url(case))
            v=add_version(db,cid,title,body,'manual',actor=who);S.log_case(db,cid,f'입장 요청서 {v}판 직접 작성 시작');flash('양식을 채워 두었어요. 내용을 고쳐 저장해 주세요.')
        elif form=='req_save':
            title=request.form.get('title','').strip()[:200];body=request.form.get('body','').strip()[:12000]
            if not title or not body:flash('제목과 본문을 모두 넣어 주세요.');return
            if cur and (title,body)==(cur['title'],cur['body']):flash('바뀐 내용이 없어요.');return
            v=add_version(db,cid,title,body,'edit',actor=who);S.log_case(db,cid,f'입장 요청서 {v}판 저장 (관리자 수정)');flash('저장했어요. 승인은 다시 해 주세요.')
        elif form=='req_restore':
            old=db.execute('SELECT * FROM company_requests WHERE case_id=? AND version=?',(cid,request.form.get('version',type=int))).fetchone()
            if not old or not old['body']:abort(400)
            v=add_version(db,cid,old['title'],old['body'],'restore',actor=who);S.log_case(db,cid,f"입장 요청서 {old['version']}판을 {v}판으로 복원");flash(f"{old['version']}판 내용으로 되돌렸어요.")
        elif form=='req_approve':
            if not cur:abort(400)
            db.execute("UPDATE company_requests SET status='approved',approved_at=?,approved_by=? WHERE id=?",(now(),who,cur['id']))
            S.log_case(db,cid,f"입장 요청서 {cur['version']}판 관리자 승인");flash('승인했어요. 기업에 보낸 뒤 \'기업 전달 완료\'를 눌러 주세요.')
        elif form=='req_sent':
            if not cur or cur['status']=='draft':flash('먼저 관리자 승인을 해 주세요.');return
            channel=request.form.get('channel','');target=request.form.get('target','').strip()[:200]
            if channel not in CHANNELS:flash('전달 경로를 골라 주세요.');return
            db.execute("UPDATE company_requests SET status='sent',sent_at=?,sent_by=?,sent_channel=?,sent_target=? WHERE id=?",(now(),who,channel,target,cur['id']))
            db.execute('INSERT INTO company_notices(case_id,company_id,kind,target,status,memo,actor,created) VALUES(?,?,?,?,?,?,?,?)',
                       (cid,case['company_id'],'request','','기록',f"입장 요청서 {cur['version']}판 · {CHANNELS[channel]}"+(f' · {target}' if target else ''),who,now()))
            jebo.mark(db,cid,'forwarded_at')
            S.log_case(db,cid,f"기업 입장 요청서 전달 완료 ({CHANNELS[channel]})")
            wait='기업 답변 대기'
            if S.STATUSES.index(case['status'])<S.STATUSES.index(wait):
                db.execute('UPDATE cases SET status=? WHERE id=?',(wait,cid))
                S.log_case(db,cid,f"진행 단계 변경: {case['status']} → {wait}");S.notify_later(cid,'status')
            flash('기업 전달 완료로 기록했어요. 진행 단계가 \'기업 답변 대기\'로 바뀌어요.')
        elif form=='close_no_answer':
            if case['status']=='종결':flash('이미 종결된 제보예요.');return
            db.execute("UPDATE cases SET status='종결',close_reason='no_answer' WHERE id=?",(cid,));jebo.mark(db,cid,'closed_at')
            S.log_case(db,cid,f"진행 단계 변경: {case['status']} → 종결 (정해진 기간 안에 기업 답변 없음)");S.notify_later(cid,'status')
            flash('종결했어요. 결과는 \'정해진 기간 안에 기업 답변이 오지 않음\'으로 남아요.')
        elif form=='desk_contact':
            contact=find_contact(db,case)
            saved,msg=save_contact(db,request.form,contact['id'] if contact else None,case['company_id'])
            flash(msg)
        elif form=='desk_answer':
            add_answer(db,case)
    S.desk_handle_form=handle_form
    S.DESK_FORMS=('req_generate','req_manual','req_save','req_restore','req_approve','req_sent','close_no_answer','desk_contact','desk_answer')

    def add_answer(db,case):
        """운영자가 받은 기업 답변을 원문 그대로 등록. 등록하면 제보자에게 기존 알림으로 안내."""
        f={k:request.form.get(k,'').strip() for k in ('answer_company','answer_person','received_on','channel','sender','body')}
        if not f['body'] or len(f['body'])>8000 or not f['answer_company'] or f['channel'] not in CHANNELS or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',f['received_on']) or f['received_on']>datetime.date.today().isoformat():
            flash('답변 기업명, 수신일, 수신 경로, 답변 원문을 모두 넣어 주세요.');return
        ups=[u for u in request.files.getlist('answer_files') if u and u.filename][:ANSWER_FILES_MAX+1]
        if len(ups)>ANSWER_FILES_MAX:flash(f'첨부는 {ANSWER_FILES_MAX}개까지 올릴 수 있어요.');return
        checked=[]
        for u in ups:
            suffix=Path(u.filename).suffix.lower();head=u.stream.read(12);u.stream.seek(0,2);size=u.stream.tell();u.stream.seek(0)
            if suffix not in ANSWER_FILE_TYPES or not S.file_ok(suffix,head) or size>10*1024*1024:flash('첨부는 10MB 이하 사진이나 PDF만 올릴 수 있어요.');return
            checked.append((u,suffix,re.sub(r'[\x00-\x1f/\\]','',Path(u.filename.replace('\\','/')).name)[:180] or 'file'+suffix))
        public=1 if request.form.get('public') and case['public_consent'] else 0
        got=f['received_on']
        source='email' if f['channel']=='email' else 'admin'
        cur=db.execute("INSERT INTO messages(case_id,author,body,created,source,answer_company,answer_person,received_on,channel,official,public) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (case['id'],'기업 답변',f['body'],got+'T00:00:00' if got<now()[:10] else now(),source,f['answer_company'][:120],f['answer_person'][:120],got,f['channel'],1 if request.form.get('official') else 0,public))
        for u,suffix,original in checked:
            stored='a_'+secrets.token_hex(20)+suffix;u.save(S.UPLOAD/stored)
            db.execute('INSERT INTO answer_files(message_id,case_id,stored,original,created) VALUES(?,?,?,?,?)',(cur.lastrowid,case['id'],stored,original,now()))
        S.log_case(db,case['id'],f"기업 답변 등록 ({f['answer_company'][:40]} · {CHANNELS[f['channel']]} · 받은 날 {got}"+(f" · 보낸 사람 {f['sender'][:60]}" if f['sender'] else '')+')'+(' · 사이트 공개' if public else ''))
        S.answer_arrived(db,case);S.notify_later(case['id'],'company')
        flash('기업 답변을 원문 그대로 등록했어요. 제보자에게 알림이 가요.')

    def answer_file(file_id):
        with conn() as db:f=db.execute('SELECT * FROM answer_files WHERE id=?',(file_id,)).fetchone()
        if not f:abort(404)
        resp=send_file(S.UPLOAD/f['stored'],as_attachment=True,download_name=f['original']);resp.headers['Cache-Control']='no-store'
        return resp
    app.add_url_rule('/admin/answer-file/<int:file_id>','desk_answer_file',S.admin_area(answer_file))
    app.add_url_rule('/reporter/answer-file/<int:file_id>','desk_answer_file_reporter',S.reporter_only(answer_file))
