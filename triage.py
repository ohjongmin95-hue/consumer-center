"""AI 제보 분류와 법률 안내 자동 응답 초안.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다.
- 접수 뒤 따로(접수는 기다리지 않음) AI가 '취재 검토'(센터가 직접 볼 제보)와 '자동 응답'(법률 안내로 답할 제보)으로 나눈다.
- 자동 응답 제보에는 법률 안내 답변 초안을 만든다. 근거 조문은 platform_app/law_texts.json(국가법령정보센터 원문)에 있는 것만 고를 수 있고,
  답변 아래에 붙이는 조문 이름도 그 파일에서 가져온다. AI가 목록에 없는 조문을 적으면 버린다.
- AI에는 이름·연락처 등을 지운 제보 내용만 보낸다(companydesk.case_input). 첨부 파일은 보내지 않는다.
- 제보자에게 보내는 건 운영자·기자가 초안을 확인하고 '제보자에게 보내기'를 눌렀을 때만이다. 자동 발송하지 않는다.
- 분류는 언제든 사람이 바꿀 수 있고, 바꾼 사람이 기록된다.
"""
import importlib.util, json, logging, os, re, threading
from pathlib import Path
from flask import abort, after_this_request, flash, request

LOG=logging.getLogger(__name__)
TRACKS={'story':'취재 검토','auto':'자동 응답'}
_spec=importlib.util.spec_from_file_location('jebo_law',Path(__file__).parent/'platform_app'/'law.py')
law=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(law)

# 제보 유형별로 AI에 보여 줄 조문 후보 (유형 이름은 관리자가 바꿀 수 있어 없는 유형은 전체 후보를 씀)
POOL_ALL=['ecom:제15조:①','ecom:제15조:②','ecom:제17조:①','ecom:제17조:②','ecom:제17조:③','ecom:제17조:⑤','ecom:제17조:⑥',
          'ecom:제18조:②','ecom:제18조:③','ecom:제18조:⑨','ecom:제18조:⑩','ecom_dec:제21조의3','ecom:제21조:①:1','ecom:제21조:①:3','basic:제16조:③']
# 헬스장·학원·필라테스처럼 1개월 이상 이용권(계속거래): 방문판매법. 오프라인 계약은 전자상거래법이 아니라 이쪽
DOOR=['door:제2조::10','door:제31조','door:제32조:①','door:제32조:③','door:제34조:①:4','door_dec:제41조:②']
POOL_ALL=POOL_ALL+DOOR
POOL={'배송·교환·환불':DOOR+['ecom:제15조:①','ecom:제15조:②','ecom:제17조:①','ecom:제17조:②','ecom:제17조:③','ecom:제17조:⑤','ecom:제18조:②','ecom:제18조:③','ecom:제18조:⑨','ecom:제18조:⑩','ecom_dec:제21조의3'],
      '품질·하자·AS':['ecom:제17조:③','ecom:제17조:⑤','ecom:제18조:⑩','basic:제16조:③'],
      '요금·결제':['ecom:제17조:①','ecom:제18조:②','ecom:제18조:③','ecom_dec:제21조의3','basic:제16조:③']+DOOR,
      '계약·해지':['ecom:제17조:①','ecom:제17조:②','ecom:제18조:②','ecom:제18조:⑨','basic:제16조:③']+DOOR,
      '허위·과장 광고':['ecom:제17조:③','ecom:제18조:⑩','ecom:제21조:①:1'],
      '고객 응대':['ecom:제21조:①:3','ecom:제21조:①:1','basic:제16조:③']+DOOR}
OPENING='안녕하세요. 소비자제보센터입니다.\n\n먼저 소중한 제보를 보내주셔서 감사합니다.'
HELP=('■ 도움받을 수 있는 곳\n'
      '- 1372 소비자상담센터: 국번 없이 1372 또는 www.ccn.go.kr 에서 상담을 받을 수 있어요.\n'
      '- 한국소비자원 피해구제: 업체와 해결되지 않으면 www.kca.go.kr 에서 피해구제를 신청할 수 있어요.\n'
      '- 품목별 소비자분쟁해결기준: '+law.KCA_STANDARD)
CLOSING=('이 안내는 보내 주신 내용을 바탕으로 한 일반적인 법률 정보이며, 개별 사안에 대한 법률 자문이나 판단은 아니에요. '
         '실제 결과는 계약 내용과 사실관계에 따라 달라질 수 있어요.\n'
         '추가로 알려 주실 내용이나 자료가 있으면 이 화면에서 답장해 주세요. 센터가 함께 확인할게요.\n\n소비자제보센터 드림')
SYSTEM=('너는 소비자제보센터의 제보 분류와 답변 초안을 돕는다. 제보 내용과 [조문 후보]만 근거로 JSON을 만든다.\n'
        '1) 분류 track: "story"(취재 검토) 또는 "auto"(자동 응답).\n'
        '   story: 여러 소비자에게 반복될 수 있는 피해, 큰 금액, 안전·건강 위해, 기업의 조직적·고의적 행위 의심, 사회적 관심이 클 사안 등 센터가 직접 취재·검토할 가치가 있는 제보.\n'
        '   auto: 개인 간 일회성 분쟁, 단순 변심·반품·환불 문의처럼 법률 안내만으로 소비자가 스스로 해결을 시도할 수 있는 제보.\n'
        '   애매하면 story로 한다.\n'
        '2) reason: 그렇게 나눈 이유 한두 문장(운영자용).\n'
        '3) guidance: 제보자에게 줄 법률 안내 2~4문단 배열. [조문 후보]의 내용만 근거로 쉬운 존댓말(해요체)로 쓴다. '
        '조문에 없는 기간·금액·권리를 지어내지 않는다. 기업이 법을 위반했다고 단정하지 않는다("~라면 ~할 수 있어요"처럼 조건으로 쓴다). '
        '개인정보(이름·연락처·주소·계좌·주문번호)는 쓰지 않는다. 조문 번호는 문단에 쓰지 않아도 된다.\n'
        '   [조문 후보]에는 온라인 거래(전자상거래법)와 계속거래(방문판매법: 헬스장·학원·필라테스처럼 1개월 이상 이용권 계약) 조문이 섞여 있다. '
        '제보 상황에 맞는 법만 고른다. 매장에서 직접 맺은 이용권 계약에는 전자상거래법을 쓰지 말고 방문판매법 계속거래 조문을 쓴다. '
        '맞는 조문이 없으면 끌어다 쓰지 말고, 계약서·약관 확인과 품목별 소비자분쟁해결기준·1372 상담을 중심으로 일반적인 안내만 한다.\n'
        '4) refs: guidance의 근거가 된 조문 후보 id 0~4개 배열(후보 목록의 id 그대로). 맞는 조문이 없으면 빈 배열.\n'
        '5) steps: 제보자가 할 일 2~4개 배열(예: 업체에 서면으로 요청하고 기록 남기기). 해요체 짧은 문장.\n'
        'guidance와 steps는 반드시 문자열의 배열(JSON array)로 쓴다.')

def ref_pool(category):return POOL.get(category,POOL_ALL)

def law_block(refs):
    return '\n\n'.join(f'[{r}] '+law.plain(r) for r in refs)

def ask(case):
    """{track, reason, guidance, refs, steps} 와 모델 이름. 실패하면 예외(키는 메시지에 넣지 않음)."""
    desk=_desk
    key=os.getenv('OPENAI_API_KEY','').strip()
    if not key:raise RuntimeError('OpenAI API 키가 없어요')
    pool=ref_pool(case['category'])
    user=json.dumps(desk.case_input(case),ensure_ascii=False)+'\n\n[조문 후보]\n'+law_block(pool)
    body={'model':desk.ai_model(),'temperature':0.2,'response_format':{'type':'json_object'},
          'messages':[{'role':'system','content':_branded(SYSTEM)},{'role':'user','content':user}]}
    st,res=desk.post_json('https://api.openai.com/v1/chat/completions',{'Authorization':'Bearer '+key,'Content-Type':'application/json'},body,45)
    if st!=200:raise RuntimeError(f'AI 응답 오류 ({st}) '+str((res.get('error') or {}).get('message',''))[:120].replace(key,'***'))
    try:out=json.loads(res['choices'][0]['message']['content'])
    except (KeyError,IndexError,TypeError,ValueError):raise RuntimeError('AI 응답을 읽지 못했어요')
    return clean(out,case,pool),res.get('model') or desk.ai_model()

def clean(out,case,pool):
    if not isinstance(out,dict):raise RuntimeError('AI 응답 형식이 달라요')
    names=[case['reporter_name']] if 'reporter_name' in case.keys() else []
    s=lambda v:_desk.scrub(str(v).strip(),names)
    track=out.get('track') if out.get('track') in TRACKS else 'story'
    def items(v,sep):
        # AI가 배열 대신 한 덩어리 글로 줄 때가 있어 문단(줄)으로 나눔 (글자 단위로 쪼개지지 않게)
        if isinstance(v,str):v=[x for x in re.split(sep,v)]
        if not isinstance(v,list):return []
        return [re.sub(r'^\s*(\d+[.)]|[-•·])\s*','',str(x)).strip() for x in v if str(x).strip()]
    guidance=[s(p) for p in items(out.get('guidance'),r'\n\s*\n|\n')][:4]
    steps=[s(p) for p in items(out.get('steps'),r'\n')][:4]
    refs=[r for r in dict.fromkeys(out.get('refs') or []) if r in pool][:4]  # 후보에 없는 조문은 버림
    if not guidance:raise RuntimeError('AI가 안내 내용을 채우지 못했어요')
    return {'track':track,'reason':s(out.get('reason') or '')[:300],'guidance':guidance,'steps':steps,'refs':refs}

def _branded(text):
    # 기본 문구 속 '소비자제보센터'를 지금 사이트 이름(관리자 설정)으로 바꿈
    import notify
    return notify.branded(text)

def compose(res):
    parts=[OPENING,'','보내 주신 내용을 살펴보고, 관련 법률을 바탕으로 도움이 될 만한 내용을 안내드려요.','','■ 관련 법률 안내','\n\n'.join(res['guidance'])]
    if res['refs']:parts+=['','■ 근거 조문']+[f"- {c['label']} ({c['title']})" for c in (law.cite(r) for r in res['refs'])]
    if res['steps']:parts+=['','■ 이렇게 해 보세요']+[f'{i}. {t}' for i,t in enumerate(res['steps'],1)]
    parts+=['',HELP,'',CLOSING]
    return _branded('\n'.join(parts))

_desk=None
def install(S):
    global _desk
    app=S.app;conn=S.conn;now=S.now;_desk=S.companydesk
    with conn() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS case_triage(case_id INTEGER PRIMARY KEY,track TEXT NOT NULL DEFAULT '',ai_track TEXT NOT NULL DEFAULT '',reason TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',refs TEXT NOT NULL DEFAULT '',model TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'draft',
            set_by TEXT NOT NULL DEFAULT '',sent_at TEXT NOT NULL DEFAULT '',sent_by TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,updated TEXT NOT NULL)''')
    app.jinja_env.globals.update(TRIAGE_TRACKS=TRACKS)

    def row(db,case_id):return db.execute('SELECT * FROM case_triage WHERE case_id=?',(case_id,)).fetchone()
    def save(db,case_id,**f):
        if row(db,case_id):db.execute(f"UPDATE case_triage SET {','.join(k+'=?' for k in f)},updated=? WHERE case_id=?",[*f.values(),now(),case_id])
        else:db.execute(f"INSERT INTO case_triage(case_id,{','.join(f)},created,updated) VALUES(?,{','.join('?'*len(f))},?,?)",[case_id,*f.values(),now(),now()])

    def run(case_id,actor='자동'):
        """AI로 분류하고 답변 초안을 만듦. 사람이 이미 분류를 정했으면 그 분류는 그대로 둠."""
        with conn() as db:case=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        if not case:return False
        try:res,model=ask(case)
        except Exception as e:
            msg=str(e)[:200];LOG.warning('제보 AI 분류 실패 (제보 %s): %s',case_id,msg)
            with conn() as db:save(db,case_id,error=msg);S.log_case(db,case_id,'AI 분류 실패: '+msg[:60])
            return False
        with conn() as db:
            old=row(db,case_id)
            keep=old and old['set_by'] and old['track']
            save(db,case_id,track=old['track'] if keep else res['track'],ai_track=res['track'],reason=res['reason'],body=compose(res),
                 refs=json.dumps(res['refs'],ensure_ascii=False),model=model,error='',status='draft')
            S.log_case(db,case_id,f"AI 분류: {TRACKS[res['track']]} · 답변 초안 생성")
        return True
    S.triage_run=run

    def run_later(case_id):
        if not _desk.ai_ready():return
        def go(resp):
            threading.Thread(target=run,args=(case_id,),daemon=True).start();return resp
        after_this_request(go)
    S.triage_after_submit=run_later

    def context(db,case):
        t=row(db,case['id'])
        refs=[law.cite(r) for r in json.loads(t['refs'] or '[]')] if t and t['refs'] else []
        return dict(t=t,refs=refs,ready=_desk.ai_ready())
    S.triage_context=context

    def handle(db,case,form):
        cid=case['id'];who=S.actor_name();t=row(db,cid)
        if form=='triage_run':
            if not _desk.ai_ready():flash('AI 키가 없어 분류할 수 없어요.');return
            flash('AI가 분류하고 답변 초안을 새로 만들었어요.' if run(cid,who) else 'AI가 답변 초안을 만들지 못했어요. 잠시 뒤 다시 눌러 주세요.')
        elif form=='triage_track':
            track=request.form.get('track')
            if track not in TRACKS:abort(400)
            save(db,cid,track=track,set_by=who);S.log_case(db,cid,f'분류 변경: {TRACKS[track]}')
            if track=='auto' and not (t and t['body']) and _desk.ai_ready():
                # 자동 응답으로 골랐는데 초안이 없으면 바로 만듦 (고른 분류는 그대로)
                db.commit()  # AI 작업이 따로 여는 연결이 기다리지 않도록 먼저 저장
                flash('자동 응답으로 바꾸고 답변 초안을 만들었어요. 아래에서 확인해 주세요.' if run(cid,who) else '자동 응답으로 바꿨어요. 답변 초안은 만들지 못했어요. "AI로 분류하기"를 다시 눌러 주세요.')
            else:flash(f'{TRACKS[track]}(으)로 바꿨어요.')
        elif form=='triage_send':
            body=request.form.get('body','').strip()
            if not body or len(body)>8000:flash('보낼 내용을 확인해 주세요.');return
            if t and t['status']=='sent' and not request.form.get('again'):flash('이미 보낸 답변이에요.');return
            db.execute('INSERT INTO messages(case_id,author,body,created,sender) VALUES(?,?,?,?,?)',(cid,'센터',body,now(),S.staff_sender()))
            save(db,cid,body=body,status='sent',sent_at=now(),sent_by=who,**({} if t and t['track'] else {'track':'auto','set_by':who}))
            S.log_case(db,cid,'법률 안내 답변을 제보자에게 보냄');S.notify_later(cid,'message');flash('제보자에게 보냈어요.')
        else:abort(400)
    S.triage_handle_form=handle;S.TRIAGE_FORMS=('triage_run','triage_track','triage_send')

    def counts(db):
        return {r['track']:r['n'] for r in db.execute("SELECT COALESCE(t.track,'') AS track,COUNT(*) AS n FROM cases c LEFT JOIN case_triage t ON t.case_id=c.id GROUP BY 1")}
    def tracks_for(db,ids):
        if not ids:return {}
        return {r['case_id']:r for r in db.execute(f"SELECT case_id,track,status FROM case_triage WHERE case_id IN ({','.join('?'*len(ids))})",ids)}
    S.triage_counts=counts;S.triage_rows=tracks_for
