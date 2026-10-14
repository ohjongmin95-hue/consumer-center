"""AI 호출 한곳. 상담창 답변, 답변 초안, PDF 상품 추출이 모두 여기를 거친다.

운영 화면(서비스 키)이나 서버 설정에 OPENAI_API_KEY가 있으면 OpenAI를, 없고 ANTHROPIC_API_KEY만 있으면 Anthropic을 쓴다.
키는 로그·화면에 남기지 않는다. 실패하면 None을 돌려주고, 부른 쪽이 기본 안내로 대신한다.
"""
import base64, json, logging, os, urllib.error, urllib.request
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

def chat(system,messages,max_tokens=700,timeout=30,json_mode=False,temperature=0.3,files=None,anthropic_model=None):
    """한 번 묻고 글을 돌려준다. messages: [{'role':'user'|'assistant','content':str}]. files: [(파일 이름, bytes)] PDF 첨부(OpenAI만).
    키가 없거나 실패하면 None."""
    p=provider()
    try:
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

def chat_json(system,messages,**kw):
    """JSON 객체로 답을 받는다. 못 읽으면 None."""
    text=chat(system,messages,json_mode=True,**kw)
    if not text:return None
    try:return json.loads(text,strict=False)
    except ValueError:
        import re
        m=re.search(r'\{.*\}',text,re.S)
        try:return json.loads(m.group(0),strict=False) if m else None
        except ValueError:return None
