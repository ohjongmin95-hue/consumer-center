"""홈페이지에서 SODA 써 보기 (OH 11/08 '우리도 써볼 수 있게').
사장님이 소개 화면에서 쇼핑몰 주소를 넣으면 SODA가 그 페이지를 읽고, 사장님이 고객인 척 물어보면 그 가게 상담원처럼 답한다. 가입 없이.

  · 읽기: soda.fetch_text로 공개 페이지 글만 읽고 TEACH_SYS로 정리 (검색은 안 씀, AI 값). 같은 주소는 7일 동안 다시 읽지 않고 저장해 둔 것을 쓴다.
  · 묻기: chatbot.answer와 같은 상담원 규칙(지어내지 않음, 환불 약속 안 함)으로 답한다. 대화는 세션에 최근 몇 마디만.
  · 값 지키기: 한 곳(IP)에서 주소 읽기 하루 5번, 질문 주소마다 6번. 전체 하루 읽기 300번.
"""
import hashlib, json, re, urllib.parse
from flask import Blueprint, request, session, jsonify
import core, ai, soda, chatbot
from core import conn, clean

bp=Blueprint('try',__name__)
CACHE_DAYS=7
READS_PER_IP=5      # 하루
READS_ALL=300       # 하루, 모든 곳
ASKS=6              # 주소 하나당 질문
NAME_SYS=soda.TEACH_SYS.replace('출력은 JSON 한 개만: {','출력은 JSON 한 개만 (name: 가게 이름, 모르면 빈 글): {"name":"",')

DEMO={'name':'소보루상회','brand':'린넨 셔츠와 생활 소품을 파는 작은 온라인 가게예요.','hours':'평일 10시~17시 상담, 주말·공휴일 휴무',
      'shipping':'평일 오후 2시까지 결제하면 당일 출고해요. CJ대한통운으로 보내고 보통 1~2일 걸려요. 3만 원 이상 무료배송, 그 아래는 3,000원이에요.',
      'returns':'받은 날부터 7일 안에 교환·반품을 신청할 수 있어요. 단순 변심은 왕복 배송비 6,000원을 내야 하고, 불량·오배송은 무료예요. 입었거나 세탁한 상품은 안 돼요.',
      'faq':[{'q':'린넨 셔츠 사이즈가 어떻게 돼요?','a':'S·M·L 세 가지예요. 평소 입는 사이즈로 고르시면 넉넉하게 맞아요.'},
             {'q':'선물 포장 되나요?','a':'네, 결제할 때 선물 포장을 고르면 3,000원에 해 드려요.'},
             {'q':'린넨 셔츠 세탁은 어떻게 해요?','a':'찬물 손세탁이나 세탁기 울 코스를 권해요. 건조기는 줄어들 수 있어 피해 주세요.'}]}

def init():
    with conn() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS try_shops(k TEXT PRIMARY KEY,url TEXT NOT NULL,name TEXT NOT NULL,facts TEXT NOT NULL,created TEXT NOT NULL)''')
init()

def key(url):
    u=urllib.parse.urlsplit(url);return hashlib.sha256((u.hostname or '').lower().removeprefix('www.').encode()+(u.path.rstrip('/') or '/').encode()).hexdigest()[:32]
def host_name(url):
    h=(urllib.parse.urlsplit(url).hostname or '').lower().removeprefix('www.').removeprefix('m.')
    return h.split('.')[0] if h else '우리 쇼핑몰'
def lines(d):
    out=[]
    for k,t in (('brand','가게 소개'),('hours','영업·상담 시간'),('shipping','배송'),('returns','교환·반품·환불')):
        v=str(d.get(k) or '').strip()
        if v:out.append(f'{t}: {v}')
    for x in (d.get('faq') or [])[:12]:
        if isinstance(x,dict) and x.get('q') and x.get('a'):out.append(f"Q. {x['q']}\nA. {x['a']}")
    return out
def suggest(d):
    """처음에 눌러 볼 질문 세 개. 읽은 자료에 있는 것부터."""
    qs=[str(x.get('q')) for x in (d.get('faq') or []) if isinstance(x,dict) and x.get('q')][:2]
    for q in ('배송은 얼마나 걸려요?','교환하려면 어떻게 해요?','받은 지 3일 됐는데 반품돼요?'):
        if len(qs)>=3:break
        if q not in qs:qs.append(q)
    return qs[:3]

def _today():return core.iso()[:10]
def _over():
    with conn() as db:
        n=db.execute("SELECT COUNT(*) FROM try_shops WHERE created>=? AND k!='demo'",(_today(),)).fetchone()[0]
    return n>=READS_ALL

@bp.post('/try/read')
def read():
    url=clean(request.form.get('url',''),300).strip()
    if not url:return jsonify(error='쇼핑몰 주소를 넣어 주세요'),400
    if url=='demo':  # 예시 쇼핑몰: 읽기 없이 바로
        with conn() as db:db.execute('INSERT OR REPLACE INTO try_shops(k,url,name,facts,created) VALUES(?,?,?,?,?)',('demo','demo',DEMO['name'],json.dumps(DEMO,ensure_ascii=False),core.iso()))
        session['try']={'k':'demo','n':0,'h':[]}
        return jsonify(name=DEMO['name'],hello=f"안녕하세요, {DEMO['name']} 상담원 SODA예요. 무엇이 궁금하세요?",qs=['어제 주문했는데 언제 와요?','받은 지 3일 됐는데 반품돼요?','환불해 주세요'],learned=len(lines(DEMO)))
    if not re.match(r'https?://',url):url='https://'+url
    if not urllib.parse.urlsplit(url).hostname or '.' not in urllib.parse.urlsplit(url).hostname:return jsonify(error='주소를 다시 확인해 주세요. 예: myshop.co.kr'),400
    k=key(url)
    with conn() as db:
        r=db.execute('SELECT * FROM try_shops WHERE k=? AND created>=?',(k,core.iso(core.now()-core.datetime.timedelta(days=CACHE_DAYS)))).fetchone()
    if r:d=json.loads(r['facts']);name=r['name']
    else:
        if not ai.ready():return jsonify(error='SODA가 잠시 쉬고 있어요. 조금 뒤에 다시 해 주세요'),503
        if core.throttled('try_read',READS_PER_IP,24*60) or _over():return jsonify(error='오늘 써 보기를 다 썼어요. 가입하면 내 쇼핑몰로 계속 써 볼 수 있어요'),429
        page=soda.fetch_text(url)
        if len(page)<200:return jsonify(error='이 주소는 글을 바로 읽을 수 없어요. 쇼핑몰 첫 화면이나 이용 안내 페이지 주소로 해 보세요'),422
        out=ai.chat(NAME_SYS,[{'role':'user','content':f'[쇼핑몰 페이지 {url}]\n{page[:12000]}'}],max_tokens=1200,timeout=60,json_mode=True,meta=dict(purpose='try_read'))
        d=ai.parse_json(out)
        if not isinstance(d,dict) or not lines(d):return jsonify(error='SODA가 이 페이지에서 상담 정보를 찾지 못했어요. 배송·교환 안내가 있는 페이지 주소로 해 보세요'),422
        name=clean(str(d.get('name') or ''),40).strip() or host_name(url)
        with conn() as db:
            db.execute('INSERT OR REPLACE INTO try_shops(k,url,name,facts,created) VALUES(?,?,?,?,?)',(k,url,name,json.dumps(d,ensure_ascii=False),core.iso()))
    session['try']={'k':k,'n':0,'h':[]}
    return jsonify(name=name,hello=f'안녕하세요, {name} 상담원 SODA예요. 무엇이 궁금하세요?',qs=suggest(d),learned=len(lines(d)))

@bp.post('/try/ask')
def ask():
    t=session.get('try') or {}
    q=clean(request.form.get('q',''),300).strip()
    if not t.get('k'):return jsonify(error='먼저 쇼핑몰 주소를 넣어 주세요'),400
    if not q:return jsonify(error='물어볼 말을 적어 주세요'),400
    if t.get('n',0)>=ASKS:return jsonify(error='써 보기는 여기까지예요. 가입하면 내 쇼핑몰에서 계속 써 볼 수 있어요',done=True),429
    with conn() as db:r=db.execute('SELECT * FROM try_shops WHERE k=?',(t['k'],)).fetchone()
    if not r:return jsonify(error='다시 쇼핑몰 주소를 넣어 주세요'),400
    co={'id':0,'name':r['name'],'tone':'polite'}
    law_text,_=chatbot.law_context(q)  # 청약철회 7일 같은 법 내용은 법령 원문으로
    system=chatbot.system_prompt(co,'\n'.join(lines(json.loads(r['facts']))),law_text)
    msgs=chatbot.clean_history(t.get('h') or [])
    msgs.append({'role':'user','content':chatbot.mask(q)})
    out=ai.chat(system,msgs,max_tokens=600,timeout=40,json_mode=True,meta=dict(purpose='try_ask',tier='low'))
    d=ai.parse_json(out)
    a=str((d or {}).get('answer') or '').strip() if isinstance(d,dict) else ''
    if not a:return jsonify(error='SODA가 답을 만들지 못했어요. 다시 물어봐 주세요'),502
    a=re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)',r'\1',a)[:800]
    need=bool(isinstance(d,dict) and (d.get('action') is True or d.get('handoff')))
    h=(t.get('h') or [])+[{'who':'me','text':q},{'who':'bot','text':a}]
    session['try']={'k':t['k'],'n':t.get('n',0)+1,'h':h[-6:]}
    return jsonify(answer=a,owner=need,left=ASKS-t.get('n',0)-1)
