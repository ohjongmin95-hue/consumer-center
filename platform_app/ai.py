"""AI 호출 한곳. 상담창 답변, 답변 초안, PDF 상품 추출이 모두 여기를 거친다.

운영 화면(서비스 키)이나 서버 설정에 OPENAI_API_KEY가 있으면 OpenAI를, 없고 ANTHROPIC_API_KEY만 있으면 Anthropic을 쓴다.
키는 로그·화면에 남기지 않는다. 실패하면 None을 돌려주고, 부른 쪽이 기본 안내로 대신한다.
"""
import base64, html, json, logging, os, re, time, urllib.error, urllib.parse, urllib.request
import core

LOG=logging.getLogger(__name__)
OPENAI_MODEL=os.getenv('OPENAI_MODEL') or os.getenv('SOBORU_AI_MODEL') or 'gpt-4.1-mini'
ANTHROPIC_MODEL=os.getenv('CHAT_MODEL','claude-haiku-5-5')
VENDORS={'openai':dict(name='OpenAI, L.L.C.',contact='OpenAI, L.L.C. (미국, privacy@openai.com)',train='OpenAI는 API로 받은 내용을 기본적으로 AI 학습에 쓰지 않아요.',keep='답변을 만든 뒤 OpenAI의 보관 정책(최대 30일)에 따라 삭제'),
         'anthropic':dict(name='Anthropic, PBC',contact='Anthropic, PBC (미국, privacy@anthropic.com)',train='Anthropic은 받은 내용을 AI 학습에 쓰지 않아요.',keep='답변을 만든 뒤 Anthropic의 보관 정책에 따라 삭제')}

def provider():
    if core.secret('OPENAI_API_KEY'):return 'openai'
    if core.secret('ANTHROPIC_API_KEY'):return 'anthropic'
    return ''
def ready():return bool(provider())
def vendor():return VENDORS.get(provider())

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

def naver_answer(system,messages,max_tokens,timeout,temperature,json_mode):
    """OpenAI가 필요할 때 네이버 검색 도구를 부르게 하고, 결과를 보고 답하게 한다. 실패하면 None."""
    msgs=[{'role':'system','content':system}]+[dict(m) for m in messages];end=time.time()+timeout
    for rnd in range(3):
        body={'model':OPENAI_MODEL,'messages':msgs,'max_tokens':max_tokens,'temperature':temperature,'tools':[SEARCH_TOOL],'tool_choice':'none' if rnd==2 else 'auto'}
        if json_mode:body['response_format']={'type':'json_object'}
        code,res=post('https://api.openai.com/v1/chat/completions',{'Content-Type':'application/json','Authorization':'Bearer '+core.secret('OPENAI_API_KEY')},body,max(5,end-time.time()))
        if code!=200:LOG.warning('OpenAI 응답 %s: %s',code,str((res.get('error') or {}).get('message',''))[:200]);return None
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

def web_answer(system,messages,max_tokens,timeout,temperature):
    """OpenAI Responses API + 인터넷 검색 도구. AI가 필요할 때만 검색한다. 실패하면 None (부른 쪽이 검색 없이 다시 묻는다)."""
    body={'model':OPENAI_MODEL,'instructions':system,'input':[dict(m) for m in messages],'tools':[{'type':'web_search'}],
          'max_output_tokens':max_tokens,'temperature':temperature}
    code,res=post('https://api.openai.com/v1/responses',{'Content-Type':'application/json','Authorization':'Bearer '+core.secret('OPENAI_API_KEY')},body,timeout)
    if code!=200:LOG.warning('OpenAI 검색 응답 %s: %s',code,str((res.get('error') or {}).get('message',''))[:200]);return None
    text=''.join(c.get('text','') for o in res.get('output') or [] if o.get('type')=='message' for c in o.get('content') or [] if c.get('type')=='output_text')
    return text.strip() or None

def chat(system,messages,max_tokens=700,timeout=30,json_mode=False,temperature=0.3,files=None,anthropic_model=None,web=False):
    """한 번 묻고 글을 돌려준다. messages: [{'role':'user'|'assistant','content':str}]. files: [(파일 이름, bytes)] PDF 첨부(OpenAI만).
    web=True면 (OpenAI일 때) 인터넷 검색을 쓸 수 있게 한다. 키가 없거나 실패하면 None."""
    p=provider()
    try:
        if p=='openai' and web and not files and naver_ready():  # 네이버 검색 키가 있으면 네이버로 검색
            try:
                text=naver_answer(system,messages,max_tokens,timeout,temperature,json_mode)
                if text:return text
            except Exception as e:LOG.warning('네이버 검색 상담 실패: %s',type(e).__name__)
        elif p=='openai' and web and not files:  # 없으면 OpenAI 자체 검색
            try:
                text=web_answer(system+('\n출력은 JSON 한 개만.' if json_mode else ''),messages,max_tokens,timeout,temperature)
                if text:return text
            except Exception as e:LOG.warning('OpenAI 검색 실패: %s',type(e).__name__)
        if p=='openai':
            msgs=[{'role':'system','content':system}]+[dict(m) for m in messages]
            if files:  # 마지막 사용자 말에 PDF를 붙인다
                parts=[{'type':'file','file':{'filename':n,'file_data':'data:application/pdf;base64,'+base64.b64encode(b).decode()}} for n,b in files]
                msgs[-1]={'role':'user','content':parts+[{'type':'text','text':msgs[-1]['content']}]}
            body={'model':OPENAI_MODEL,'messages':msgs,'max_tokens':max_tokens,'temperature':temperature}
            if json_mode:body['response_format']={'type':'json_object'}
            code,res=post('https://api.openai.com/v1/chat/completions',{'Content-Type':'application/json','Authorization':'Bearer '+core.secret('OPENAI_API_KEY')},body,timeout)
            if code!=200:LOG.warning('OpenAI 응답 %s: %s',code,str((res.get('error') or {}).get('message',''))[:200]);return None
            return ((res.get('choices') or [{}])[0].get('message') or {}).get('content','').strip() or None
        if p=='anthropic':
            if files:return None
            sys_=system+('\n출력은 JSON 한 개만.' if json_mode else '')
            body={'model':anthropic_model or ANTHROPIC_MODEL,'max_tokens':max_tokens,'system':sys_,'messages':messages}
            code,res=post('https://api.anthropic.com/v1/messages',{'content-type':'application/json','x-api-key':core.secret('ANTHROPIC_API_KEY'),'anthropic-version':'2023-06-01'},body,timeout)
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
