"""AI 호출 한곳. 상담창 답변, 답변 초안, PDF 상품 추출이 모두 여기를 거친다.

운영 화면(서비스 키)이나 서버 설정에 OPENAI_API_KEY가 있으면 OpenAI를, 없고 ANTHROPIC_API_KEY만 있으면 Anthropic을 쓴다.
키는 로그·화면에 남기지 않는다. 실패하면 None을 돌려주고, 부른 쪽이 기본 안내로 대신한다.
"""
import base64, html, json, logging, os, re, time, uuid, urllib.error, urllib.parse, urllib.request
import core

LOG=logging.getLogger(__name__)
# 모델: 기본은 GPT-6 Luna. 평소 문의는 낮은 추론(low), 어려운 문의(tier='high')는 같은 Luna의 높은 추론(high).
# Luna 높은 추론으로도 안 되면(실패·확신 없음) 운영 화면에서 켠 경우에만 GPT-6.1 Sol. 어느 것이든 실패하면 예전 모델(4.1-mini)로 한 번 더.
# 운영 > AI 모델에서 예전 모델로 되돌리거나 일부 회사만 Luna로 옮길 수 있다 (settings: ai_model, ai_rollout, ai_sol).
LUNA='gpt-6-luna';SOL='gpt-6.1-sol'
OLD_MODEL=os.getenv('OPENAI_MODEL') or os.getenv('SOBORU_AI_MODEL') or 'gpt-4.1-mini'
OPENAI_MODEL=OLD_MODEL  # 예전 이름 (다른 곳에서 읽을 수 있음)
PRICES={'gpt-6-luna':(0.10,0.01,0.50),'gpt-6.1-sol':(2.00,0.10,10.00),'gpt-6-sol':(2.00,0.10,10.00),'gpt-4.1-mini':(0.40,0.10,1.60),'gpt-4.1':(2.00,0.50,8.00)}  # 100만 토큰당 달러 (입력, 캐시 입력, 출력). OpenAI 가격표 2026-10
EFFORTS={'low':'low','high':'high','sol':'high'}
ANTHROPIC_MODEL=os.getenv('CHAT_MODEL','claude-haiku-5-5')
VENDORS={'openai':dict(name='OpenAI, L.L.C.',contact='OpenAI, L.L.C. (미국, privacy@openai.com)',train='OpenAI는 API로 받은 내용을 기본적으로 AI 학습에 쓰지 않아요.',keep='답변을 만든 뒤 OpenAI의 보관 정책(최대 30일)에 따라 삭제'),
         'anthropic':dict(name='Anthropic, PBC',contact='Anthropic, PBC (미국, privacy@anthropic.com)',train='Anthropic은 받은 내용을 AI 학습에 쓰지 않아요.',keep='답변을 만든 뒤 Anthropic의 보관 정책에 따라 삭제')}

def provider():
    if core.secret('OPENAI_API_KEY'):return 'openai'
    if core.secret('ANTHROPIC_API_KEY'):return 'anthropic'
    return ''
def ready():return bool(provider())
def vendor():return VENDORS.get(provider())

def setting(key):
    try:
        with core.conn() as db:r=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
    except Exception:r=None
    return (r['value'] if r else '').strip()
def save_setting(key,value):
    with core.conn() as db:db.execute('INSERT INTO settings(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated',(key,value,core.iso()))
def plan():
    """{'model': 상담 모델, 'rollout': Luna로 옮긴 회사 비율(%), 'sol': Sol 자동 호출}"""
    m=setting('ai_model') or os.getenv('CS_AI_MODEL') or LUNA
    try:r=max(0,min(100,int(setting('ai_rollout') or 100)))
    except ValueError:r=100
    return {'model':m,'rollout':r,'sol':setting('ai_sol')=='1'}
def model_for(company_id=None,pl=None):
    """이 회사가 쓸 모델. 단계적 전환: 회사 번호로 나눠 rollout%만 새 모델."""
    pl=pl or plan()
    if pl['model']==OLD_MODEL or company_id is None or int(company_id)%100<pl['rollout']:return pl['model']
    return OLD_MODEL
def thinks(model):
    """생각하는 모델(gpt-5 이후, o 시리즈): temperature를 받지 않고, 생각에 쓰는 토큰까지 출력 한도에 든다."""
    return bool(re.match(r'(gpt-([5-9]|\d\d)|o\d)',model or ''))
def oa_params(model,max_tokens,temperature,effort,responses=False):
    if not thinks(model):return {'max_output_tokens' if responses else 'max_tokens':max_tokens,'temperature':temperature}
    if effort=='none':return {'max_output_tokens' if responses else 'max_completion_tokens':max_tokens,'temperature':temperature,**({'reasoning':{'effort':'none'}} if responses else {'reasoning_effort':'none'})}
    room=max_tokens+(4000 if effort in ('high','xhigh','max') else 1500)  # 생각할 자리
    return {'max_output_tokens':room,'reasoning':{'effort':effort}} if responses else {'max_completion_tokens':room,'reasoning_effort':effort}

# ---------- 호출 기록 (모델·추론 수준·토큰·비용·응답시간·결과) ----------
def init():
    with core.conn() as db:db.executescript('''CREATE TABLE IF NOT EXISTS ai_calls(id INTEGER PRIMARY KEY,req TEXT NOT NULL,created TEXT NOT NULL,company_id INTEGER,case_id INTEGER,
        purpose TEXT NOT NULL DEFAULT '',tier TEXT NOT NULL DEFAULT '',model TEXT NOT NULL,effort TEXT NOT NULL DEFAULT '',in_tok INTEGER NOT NULL DEFAULT 0,cached_tok INTEGER NOT NULL DEFAULT 0,
        out_tok INTEGER NOT NULL DEFAULT 0,reason_tok INTEGER NOT NULL DEFAULT 0,cost REAL,ms INTEGER NOT NULL DEFAULT 0,ok INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',
        why TEXT NOT NULL DEFAULT '',outcome TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS ai_calls_created ON ai_calls(created);CREATE INDEX IF NOT EXISTS ai_calls_case ON ai_calls(case_id);''')
init()
def cost(model,i,c,o):
    p=PRICES.get(model)
    return round(((i-c)*p[0]+c*p[1]+o*p[2])/1e6,6) if p else None
def usage(res):
    """(입력, 캐시 입력, 출력, 생각) 토큰. Chat Completions·Responses·Anthropic 모양 모두."""
    u=res.get('usage') or {}
    i=u.get('prompt_tokens',u.get('input_tokens',0)) or 0;o=u.get('completion_tokens',u.get('output_tokens',0)) or 0
    c=((u.get('prompt_tokens_details') or u.get('input_tokens_details') or {}).get('cached_tokens') or 0)
    r=((u.get('completion_tokens_details') or u.get('output_tokens_details') or {}).get('reasoning_tokens') or 0)
    return int(i),int(c),int(o),int(r)
def log_call(meta,model,effort,res,ms,ok,error=''):
    if meta is None:return
    i,c,o,r=usage(res or {})
    try:
        with core.conn() as db:
            lid=db.execute('INSERT INTO ai_calls(req,created,company_id,case_id,purpose,tier,model,effort,in_tok,cached_tok,out_tok,reason_tok,cost,ms,ok,error,why) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (meta.setdefault('req',uuid.uuid4().hex[:16]),core.iso(),meta.get('company_id'),meta.get('case_id'),meta.get('purpose',''),meta.get('tier','low'),model,effort or '',i,c,o,r,
                 cost(model,i,c,o),int(ms),1 if ok else 0,str(error)[:120],meta.get('why','')[:120])).lastrowid
        if ok:meta.update(log_id=lid,model=model,effort=effort or '')
    except Exception as e:LOG.warning('AI 기록 실패: %s',type(e).__name__)
def outcome(meta,result):
    """이 요청(req)의 결과: answered(상담창 답함) / sent(자동 답변 보냄) / handoff(사장님께) / failed / followup(답한 뒤 고객이 다시 물음)."""
    if not meta or not meta.get('req'):return
    with core.conn() as db:db.execute('UPDATE ai_calls SET outcome=? WHERE req=?',(result,meta['req']))
def followed_up(db,case_id):
    """AI가 보낸 뒤 고객이 같은 문의에 다시 물었다: 앞 답은 해결 못 한 것으로 센다."""
    db.execute("UPDATE ai_calls SET outcome='followup' WHERE case_id=? AND outcome='sent'",(case_id,))

def post(url,headers,body,timeout):
    """(상태 코드, JSON). 테스트에서 바꿔 끼운다. 연결 실패는 예외."""
    req=urllib.request.Request(url,data=json.dumps(body,ensure_ascii=False).encode(),method='POST',headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:return r.status,json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        try:return e.code,json.loads(e.read().decode() or '{}')
        except Exception:return e.code,{}

def get(url,headers,timeout):
    """(상태 코드, JSON). 테스트에서 바꿔 끼운다."""
    req=urllib.request.Request(url,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:return r.status,json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:return e.code,{}

# ---------- 네이버 검색 (키가 있으면 AI가 필요할 때 부른다) ----------
def naver_ready():return bool(core.secret('NAVER_SEARCH_ID') and core.secret('NAVER_SEARCH_SECRET'))
def _plain(s):return html.unescape(re.sub(r'<[^>]+>','',s or '')).strip()
def naver_search(query):
    """네이버 웹문서·블로그 검색 결과 [{title,text,source}] (최대 8개). 실패하면 빈 목록."""
    out=[];h={'X-Naver-Client-Id':core.secret('NAVER_SEARCH_ID'),'X-Naver-Client-Secret':core.secret('NAVER_SEARCH_SECRET')}
    for kind,label in (('webkr','네이버 웹문서'),('blog','네이버 블로그')):
        try:code,res=get(f'https://openapi.naver.com/v1/search/{kind}.json?'+urllib.parse.urlencode({'query':query[:100],'display':4}),h,8)
        except Exception as e:LOG.warning('네이버 검색 실패: %s',type(e).__name__);continue
        if code!=200:LOG.warning('네이버 검색 응답 %s',code);continue
        out+=[{'title':_plain(i.get('title')),'text':_plain(i.get('description'))[:300],'source':label} for i in (res.get('items') or [])[:4]]
    return out
SEARCH_TOOL={'type':'function','function':{'name':'search','description':'네이버에서 일반 정보(원료·성분, 사용법, 보관법, 상식 등)를 검색한다. 이 가게의 가격·정책은 검색하지 않는다.',
    'parameters':{'type':'object','properties':{'query':{'type':'string','description':'한국어 검색어'}},'required':['query']}}}

OA_URL='https://api.openai.com/v1/'
def oa_headers():return {'Content-Type':'application/json','Authorization':'Bearer '+core.secret('OPENAI_API_KEY')}
def oa_call(path,body,timeout,meta,effort):
    """OpenAI 한 번 부르고 기록한다. (상태 코드, JSON)"""
    t=time.time()
    try:code,res=post(OA_URL+path,oa_headers(),body,timeout)
    except Exception as e:log_call(meta,body['model'],effort,{},(time.time()-t)*1000,False,type(e).__name__);raise
    err='' if code==200 else f"{code} {str((res.get('error') or {}).get('message',''))[:100]}"
    log_call(meta,body['model'],effort,res,(time.time()-t)*1000,code==200,err)
    if code!=200:LOG.warning('OpenAI(%s) 응답 %s: %s',body['model'],code,str((res.get('error') or {}).get('message',''))[:200])
    return code,res

def naver_answer(system,messages,max_tokens,timeout,temperature,json_mode,model,meta=None):
    """OpenAI가 필요할 때 네이버 검색 도구를 부르게 하고, 결과를 보고 답하게 한다. 실패하면 None.
    Luna는 Chat Completions에서 함수 호출을 추론 수준 none일 때만 받는다 (평소 문의만 이 길로 온다)."""
    msgs=[{'role':'system','content':system}]+[dict(m) for m in messages];end=time.time()+timeout
    effort='none' if thinks(model) else ''
    for rnd in range(3):
        body={'model':model,'messages':msgs,**oa_params(model,max_tokens,temperature,effort),'tools':[SEARCH_TOOL],'tool_choice':'none' if rnd==2 else 'auto'}
        if json_mode:body['response_format']={'type':'json_object'}
        code,res=oa_call('chat/completions',body,max(5,end-time.time()),meta,effort)
        if code!=200:return None
        m=(res.get('choices') or [{}])[0].get('message') or {}
        calls=m.get('tool_calls') or []
        if not calls:return (m.get('content') or '').strip() or None
        msgs.append({'role':'assistant','content':m.get('content'),'tool_calls':calls})
        for c in calls[:3]:
            try:q=json.loads((c.get('function') or {}).get('arguments') or '{}').get('query','')
            except ValueError:q=''
            found=naver_search(q) if q else []
            msgs.append({'role':'tool','tool_call_id':c.get('id'),'content':json.dumps(found,ensure_ascii=False)[:4000] if found else '검색 결과 없음'})
    return None

def web_answer(system,messages,max_tokens,timeout,temperature,model,effort='',meta=None):
    """OpenAI Responses API + 인터넷 검색 도구. AI가 필요할 때만 검색한다. 실패하면 None (부른 쪽이 검색 없이 다시 묻는다)."""
    body={'model':model,'instructions':system,'input':[dict(m) for m in messages],'tools':[{'type':'web_search'}],
          **oa_params(model,max_tokens,temperature,effort,responses=True)}
    code,res=oa_call('responses',body,timeout,meta,effort)
    if code!=200:return None
    text=''.join(c.get('text','') for o in res.get('output') or [] if o.get('type')=='message' for c in o.get('content') or [] if c.get('type')=='output_text')
    return text.strip() or None

def ladder(company_id,tier):
    """[(모델, 추론 수준)] 차례대로. 앞에서 실패하면 다음."""
    pl=plan();main=model_for(company_id,pl);out=[]
    if tier=='sol' and pl['sol']:out.append((SOL,'high'))
    if thinks(main):
        out.append((main,EFFORTS.get(tier,'low')))
        if tier=='high' and pl['sol']:out.append((SOL,'high'))  # Luna 높은 추론이 실패하면 (켠 경우에만) Sol
    else:out.append((main,''))
    if OLD_MODEL not in [m for m,_ in out]:out.append((OLD_MODEL,''))
    return out

def chat(system,messages,max_tokens=700,timeout=30,json_mode=False,temperature=0.3,files=None,anthropic_model=None,web=False,meta=None):
    """한 번 묻고 글을 돌려준다. messages: [{'role':'user'|'assistant','content':str}]. files: [(파일 이름, bytes)] PDF 첨부(OpenAI만).
    web=True면 (OpenAI일 때) 인터넷 검색을 쓸 수 있게 한다. 키가 없거나 실패하면 None.
    meta: {'company_id','case_id','purpose','tier': 'low'|'high'|'sol','why'} 를 주면 회사별 모델·추론 수준을 고르고 호출을 기록한다.
    끝나면 meta에 'req'(요청 묶음), 'model', 'effort', 'log_id'가 들어간다."""
    p=provider();m=meta if meta is not None else {}
    tier=m.get('tier','low');steps=ladder(m.get('company_id'),tier) if p=='openai' else []
    try:
        if p=='openai' and web and not files and tier=='low':  # 검색은 평소 문의에만 (어려운 문의는 생각에 집중)
            model,effort=steps[0]
            if naver_ready():  # 네이버 검색 키가 있으면 네이버로 검색
                try:
                    text=naver_answer(system,messages,max_tokens,timeout,temperature,json_mode,model,m)
                    if text:return text
                except Exception as e:LOG.warning('네이버 검색 상담 실패: %s',type(e).__name__)
            else:  # 없으면 OpenAI 자체 검색
                try:
                    text=web_answer(system+('\n출력은 JSON 한 개만.' if json_mode else ''),messages,max_tokens,timeout,temperature,model,effort,m)
                    if text:return text
                except Exception as e:LOG.warning('OpenAI 검색 실패: %s',type(e).__name__)
        if p=='openai':
            msgs=[{'role':'system','content':system}]+[dict(x) for x in messages]
            if files:  # 마지막 사용자 말에 PDF를 붙인다
                parts=[{'type':'file','file':{'filename':n,'file_data':'data:application/pdf;base64,'+base64.b64encode(b).decode()}} for n,b in files]
                msgs[-1]={'role':'user','content':parts+[{'type':'text','text':msgs[-1]['content']}]}
            end=time.time()+timeout
            for model,effort in steps:
                if end-time.time()<3:break
                body={'model':model,'messages':msgs,**oa_params(model,max_tokens,temperature,effort)}
                if json_mode:body['response_format']={'type':'json_object'}
                try:code,res=oa_call('chat/completions',body,max(5,end-time.time()),m,effort)
                except Exception as e:LOG.warning('OpenAI(%s) 연결 실패: %s',model,type(e).__name__);continue
                if code!=200:continue
                text=(((res.get('choices') or [{}])[0].get('message') or {}).get('content') or '').strip()
                if text:return text
            return None
        if p=='anthropic':
            if files:return None
            sys_=system+('\n출력은 JSON 한 개만.' if json_mode else '')
            model=anthropic_model or ANTHROPIC_MODEL;t=time.time()
            body={'model':model,'max_tokens':max_tokens,'system':sys_,'messages':messages}
            code,res=post('https://api.anthropic.com/v1/messages',{'content-type':'application/json','x-api-key':core.secret('ANTHROPIC_API_KEY'),'anthropic-version':'2023-06-01'},body,timeout)
            log_call(m,model,'',res,(time.time()-t)*1000,code==200,'' if code==200 else str(code))
            if code!=200:LOG.warning('Anthropic 응답 %s',code);return None
            return ''.join(b.get('text','') for b in res.get('content',[]) if b.get('type')=='text').strip() or None
    except Exception as e:LOG.warning('AI 연결 실패: %s',type(e).__name__)
    return None

def parse_json(text):
    """글에서 JSON 객체를 꺼낸다. 못 읽으면 None."""
    if not text:return None
    try:return json.loads(text,strict=False)
    except ValueError:
        import re
        m=re.search(r'\{.*\}',text,re.S)
        try:return json.loads(m.group(0),strict=False) if m else None
        except ValueError:return None

def chat_json(system,messages,**kw):
    """JSON 객체로 답을 받는다. 못 읽으면 None."""
    return parse_json(chat(system,messages,json_mode=True,**kw))

# ---------- 운영 > AI 모델: 비교 보고서와 연결 시험 ----------
GROUPS=[('low','일반 Luna (낮은 추론)'),('high','고추론 Luna'),('sol','GPT-6.1 Sol'),('old','예전 모델')]
SOLVED=('sent','answered');UNSOLVED=('handoff','followup','failed')
def group_of(r):
    if r['model']==SOL:return 'sol'
    if not thinks(r['model']):return 'old'
    return 'high' if r['effort'] in ('high','xhigh','max') else 'low'
def report(days=30):
    """요청(req)마다 마지막으로 답한 모델·추론 수준으로 묶어 요청 수·응답시간·토큰·비용·해결률을 센다. 비용·시간은 실패한 앞 시도까지 더한다."""
    import datetime
    since=core.iso(core.now()-datetime.timedelta(days=days))
    with core.conn() as db:rows=db.execute('SELECT * FROM ai_calls WHERE created>=? ORDER BY id',(since,)).fetchall()
    reqs={}
    for r in rows:reqs.setdefault(r['req'],[]).append(r)
    out={k:dict(key=k,label=l,n=0,ms=0,in_tok=0,out_tok=0,reason_tok=0,cost=0.0,solved=0,judged=0,up=0) for k,l in GROUPS}
    for rs in reqs.values():
        last=([r for r in rs if r['ok']] or rs)[-1];g=out[group_of(last)]
        g['n']+=1;g['ms']+=sum(r['ms'] for r in rs);g['in_tok']+=sum(r['in_tok'] for r in rs);g['out_tok']+=sum(r['out_tok'] for r in rs)
        g['reason_tok']+=sum(r['reason_tok'] for r in rs);g['cost']+=sum(r['cost'] or 0 for r in rs)
        if last['tier']!='low' and any(r['tier']=='low' for r in rs):g['up']+=1  # 낮은 추론에서 AI가 올려 보낸 요청
        if last['outcome'] in SOLVED:g['solved']+=1;g['judged']+=1
        elif last['outcome'] in UNSOLVED:g['judged']+=1
    for g in out.values():
        n=g['n'] or 1
        g.update(avg_ms=round(g['ms']/n),avg_in=round(g['in_tok']/n),avg_out=round(g['out_tok']/n),avg_cost=g['cost']/n,rate=round(g['solved']/g['judged']*100) if g['judged'] else None)
    return [out[k] for k,_ in GROUPS]
def recent(limit=40):
    with core.conn() as db:return db.execute('SELECT a.*,c.name co_name FROM ai_calls a LEFT JOIN companies c ON c.id=a.company_id ORDER BY a.id DESC LIMIT ?',(limit,)).fetchall()
def check():
    """실제 API가 각 모델·추론 수준을 받는지 짧게 물어본다. [{'label','model','effort','ok','code','ms','msg'}]"""
    out=[]
    if provider()!='openai':return out
    for label,model,effort in (('일반 Luna',LUNA,'low'),('고추론 Luna',LUNA,'high'),('검색용 Luna (함수 호출)',LUNA,'none'),('GPT-6.1 Sol',SOL,'high'),('예전 모델',OLD_MODEL,'')):
        body={'model':model,'messages':[{'role':'user','content':'"됐어요"라고만 답해 주세요.'}],**oa_params(model,20,0.3,effort)}
        if effort=='none':body.update(tools=[SEARCH_TOOL],tool_choice='auto')
        t=time.time()
        try:code,res=oa_call('chat/completions',body,40,{'purpose':'check','tier':''},effort)
        except Exception as e:code,res=0,{'error':{'message':type(e).__name__}}
        msg=(((res.get('choices') or [{}])[0].get('message') or {}).get('content') or '') if code==200 else str((res.get('error') or {}).get('message',''))
        out.append(dict(label=label,model=model,effort=effort or '-',ok=code==200,code=code,ms=round((time.time()-t)*1000),msg=msg[:120]))
    save_setting('ai_check',json.dumps(dict(at=core.iso(),rows=out),ensure_ascii=False))
    return out
def last_check():
    try:return json.loads(setting('ai_check') or 'null')
    except ValueError:return None
