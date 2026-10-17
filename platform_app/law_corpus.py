"""소비자 관련 법령 원문 모음에서 질문에 맞는 조문을 찾는다 (AI 답변의 근거로 넘길 때).

조문 글자는 law_corpus.json에서만 가져온다. 이 파일은 국가법령정보센터(law.go.kr) PDF 원문을 law_corpus_build.py로 조문 단위로 나눈 것이고,
손으로 고쳐 쓰지 않는다. 들어 있는 법령: 화장품법, 약관법, 표시광고법, 민법, 전자상거래법·시행령, 식품표시광고법, 식품위생법,
소비자기본법, 소비자분쟁해결기준(고시 본문 4개 조. 품목별 기준 별표는 없음), 찾기 쉬운 생활법령정보(인터넷 쇼핑 해설, 법적 효력 없음).

찾는 방법은 외부 라이브러리 없이 한글 두 글자 묶음(bigram)을 쓴다. 질문과 조문에 같이 나오는 묶음마다,
드물게 나오는 묶음일수록 점수를 더 주고(BM25), 조문 제목에 나오면 더 쳐 준다.
참조는 'ecom:제17조'처럼 '법 key:조문 번호'로 쓴다 (law.py의 'ecom:제17조:①'과 달리 조문 전체).
"""
import json, math, os, re
from collections import Counter
from pathlib import Path

PATH=Path(__file__).parent/'law_corpus.json'
# 관리자가 PDF로 더 올린 법령 파일 (같은 꼴의 JSON). 환경변수 LAW_CORPUS_EXTRA(여러 개는 ':'로) 또는 add_extra()로 붙인다.
# 같은 key의 법령이 있으면 올린 쪽이 기본 모음을 대신한다(법이 바뀌어 새 PDF를 올린 경우). 지우면 기본 모음으로 돌아간다.
EXTRA=[Path(x) for x in os.getenv('LAW_CORPUS_EXTRA','').split(os.pathsep) if x.strip()]
TITLE_W=3.0     # 제목에 나온 묶음 가중치
K1,B=1.2,0.6    # BM25
# 조문이 질문과 얼마나 맞는지 = 점수 × 맞은 몫(match). 앞의 세 조문 중 가장 큰 값으로 본다.
RELATED=6     # 이 이상이면 AI에게 관련 조문으로 같이 준다
LEGAL=12      # 이 이상이면 법률 질문으로 본다 (상담창은 인터넷 검색 없이 조문으로 답한다)
# 이런 말이 있으면 RELATED만 넘어도 법률 질문으로 본다
LEGAL_WORDS=('청약철회','환불','반품','교환','취소','위약금','배상','보상','약관','표시','기재','의무','법','불량','하자','파손','훼손','분실',
             '계약','해지','미성년','광고','사용기한','소비기한','유통기한','피해','분쟁')
MAX_GUIDE=2   # 근거 글에 넣는 생활법령정보 해설은 이만큼까지 (조문 원문을 먼저)
# 질문에 이런 말이 있으면 그 법의 조문을 조금 더 쳐 준다
HINTS=[(('화장품','크림','로션','세럼','앰플','선크림','샴푸','립스틱','기능성화장품'),('cosmetics',),1.6),
       (('식품','음식','먹','유통기한','소비기한','원재료','알레르기','건강기능','영양'),('food','foodlabel'),1.5),
       (('약관','이용약관','면책'),('terms',),1.5),
       (('광고','표시','과장','허위'),('adlabel','foodlabel','cosmetics'),1.2),
       (('온라인','인터넷','쇼핑몰','통신판매','택배','배송','반품','환불','청약철회','교환','주문','취소'),('ecom','ecom_dec','easylaw'),1.5),
       (('분쟁','피해구제','소비자원','보상','1372'),('basic','kca'),1.3)]

_DB=None;_SIG=None;_BASE=None
def add_extra(path):
    """더 올린 법령 파일을 찾기에 넣는다 (파일이 아직 없어도 됨. 생기거나 바뀌면 다음 찾기 때 다시 읽음)."""
    p=Path(path)
    if p not in EXTRA:EXTRA.append(p);reset()

def reset():
    global _DB
    _DB=None

def _sig():
    # 더 올린 파일이 바뀌었는지 (다른 서버 프로세스가 올려도 알아채게 파일 시각·크기로 봄)
    out=[]
    for p in EXTRA:
        try:st=p.stat();out.append((str(p),st.st_mtime_ns,st.st_size))
        except OSError:out.append((str(p),0,0))
    return tuple(out)

def extra_laws(path):
    """더 올린 법령 파일 하나 {key: 법령}. 없거나 깨졌으면 빈 dict."""
    try:data=json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}
    return {k:v for k,v in data.items() if isinstance(v,dict) and isinstance(v.get('articles'),dict) and ':' not in k} if isinstance(data,dict) else {}

def base_keys():
    """law_corpus.json(기본 모음)에 든 법령 key."""
    _load();return set(_BASE)

def _load():
    global _DB,_SIG,_BASE
    sig=_sig()
    if _DB is not None and sig==_SIG:return _DB
    if _BASE is None:_BASE=json.loads(PATH.read_text(encoding='utf-8'))
    laws=dict(_BASE)
    for p in EXTRA:
        for k,l in extra_laws(p).items():laws[k]=dict(l,extra=True,replaces=k in _BASE)
    _SIG=sig
    docs=[];df=Counter()
    for key,law in laws.items():
        for art,a in law['articles'].items():
            if a['title']=='삭제' or not a['text'].strip() or a['text'].strip().startswith('삭제'):continue
            tb=Counter(grams(a['title']));xb=Counter(grams(a['text']))
            docs.append({'ref':f'{key}:{art}','key':key,'art':art,'title':a['title'],'text':a['text'],'tb':tb,'xb':xb,'len':sum(xb.values())})
            for g in set(tb)|set(xb):df[g]+=1
    names={l['name']:k for k,l in laws.items()}
    for d in docs:d['cites']=cites(d['text'],names) if d['key']=='easylaw' else []
    n=len(docs);avg=sum(d['len'] for d in docs)/max(n,1)
    idf={g:math.log(1+(n-c+0.5)/(c+0.5)) for g,c in df.items()}
    _DB={'laws':laws,'docs':docs,'by_ref':{d['ref']:d for d in docs},'idf':idf,'avg':avg,'n':n}
    return _DB

# 말끝(해요체·물음)에서 나오는 묶음은 질문 뜻과 상관없어 뺀다
STOP={'어요','아요','해요','나요','세요','까요','에요','예요','되나','하나','는데','니다','습니','합니','있어','없어','주세','하세','인가','는지','은데',
      '나요','던데','네요','데요','건가','할까','될까','가요','와요','줘요','돼요','되요','이에','이요','거예','건데','어서','해서','했는','했어','었어','았어'}
def cites(text,names):
    """해설 글 속 '(「전자상거래 등에서의 소비자보호에 관한 법률」 제17조제3항 및 제18조제10항)' 같은 인용 -> ['ecom:제17조','ecom:제18조']"""
    out=[];cur=None
    for m in re.finditer(r'「([^」]+)」|제(\d+)조(?:의(\d+))?|\)',text):
        if m[1]:cur=names.get(m[1].strip())
        elif m[0]==')':cur=None
        elif cur:
            r=f"{cur}:제{m[2]}조"+(f"의{m[3]}" if m[3] else '')
            if r not in out:out.append(r)
    return out

def grams(s,stop=False):
    """한글·숫자 덩어리마다 두 글자 묶음. 한 글자짜리 덩어리는 그대로."""
    out=[]
    for w in re.findall(r'[가-힣]+|[0-9]+[가-힣]?|[A-Za-z]+',s or ''):
        out+= [w] if len(w)<2 else [w[i:i+2] for i in range(len(w)-1)]
    return [g for g in out if g not in STOP and len(g)>1] if stop else out

def laws():
    """[{key, name, short, kind, no, effective, source, count}]"""
    return [dict({k:v for k,v in l.items() if k!='articles'},count=len(l['articles'])) for l in _load()['laws'].values()]

def _short(key):return _load()['laws'][key]['short']

def label(ref):
    """'ecom:제17조' -> '전자상거래법 제17조 (청약철회등)'"""
    key,art=ref.split(':',1);a=_load()['laws'][key]['articles'][art]
    return f"{_short(key)} {art}"+(f" ({a['title']})" if a['title'] else '')

def text(ref):
    key,art=ref.split(':',1)
    return _load()['laws'][key]['articles'][art]['text']

def source(ref):
    """조문 원문 주소. 법률·시행령은 조문까지, 고시·생활법령정보는 문서 주소."""
    key,art=ref.split(':',1);law=_load()['laws'][key]
    return law['source']+('/'+art if law['kind'] in ('법률','대통령령','총리령') else '')

def exists(ref):
    try:key,art=ref.split(':',1);return art in _load()['laws'][key]['articles']
    except (ValueError,KeyError):return False

def cite(ref):
    """triage·화면에서 law.cite()와 같은 모양으로 쓰는 정보."""
    key,art=ref.split(':',1);law=_load()['laws'][key];a=law['articles'][art]
    return {'ref':ref,'label':f"{law['short']} {art}",'title':a['title'],'text':a['text'],'law':law['name'],'kind':law['kind'],'no':law['no'],
            'effective':law['effective'],'source':source(ref)}

def _boost(question):
    b={'easylaw':0.85,'civil':0.7}  # 해설보다 조문을, 일반법인 민법보다 소비자 법령을 먼저
    for words,keys,w in HINTS:
        if any(x in question for x in words):
            for k in keys:b[k]=b.get(k,1.0)*w
    return b

def _score(qg,d,db):
    s=0.0;norm=K1*(1-B+B*d['len']/db['avg'])
    for g,qn in qg.items():
        idf=db['idf'].get(g)
        if not idf:continue
        tf=d['xb'].get(g,0)
        s+=idf*(TITLE_W*(g in d['tb'])+(tf*(K1+1)/(tf+norm) if tf else 0))
    return s

def search(question,limit=6,laws=None,min_score=0.0):
    """질문에 맞는 조문 [{ref, label, title, text, score, match, law, source}], 점수 높은 순.
    laws: 찾을 법 key 목록 (없으면 전체). match: 질문 묶음 무게 중 이 조문에 나온 몫(0~1)."""
    db=_load();qg=Counter(grams(question,stop=True))
    if not qg:return []
    boost=_boost(question);top=math.log(1+db['n'])
    total=sum(db['idf'].get(g,top) for g in qg) or 1  # 법령에 없는 말도 질문 무게에 넣는다
    hits=[]
    for d in db['docs']:
        if laws and d['key'] not in laws:continue
        if not any(g in d['xb'] or g in d['tb'] for g in qg):continue
        s=_score(qg,d,db)*boost.get(d['key'],1.0)
        if s>min_score:hits.append((s,d))
    hits.sort(key=lambda x:-x[0])
    out=[]
    for s,d in hits[:limit]:
        m=sum(db['idf'].get(g,0) for g in qg if g in d['xb'] or g in d['tb'])/total
        out.append({'ref':d['ref'],'label':label(d['ref']),'title':d['title'],'text':d['text'],'score':round(s,2),'match':round(m,3),
                    'law':db['laws'][d['key']]['name'],'source':source(d['ref'])})
    return out

def strength(hits):
    return max((h['score']*h['match'] for h in hits[:3]),default=0)

def is_legal(hits,question=''):
    """찾은 조문이 질문과 충분히 맞는지 (상담창이 인터넷 검색을 끌지 정할 때)."""
    s=strength(hits)
    return s>=LEGAL or (s>=RELATED and any(w in question for w in LEGAL_WORDS))

def related(question,limit=4,laws=None):
    """근거로 줄 만한 조문만 (관련이 약하면 빈 목록). 첫 조문 점수의 40% 넘는 것만.
    생활법령정보 해설은 MAX_GUIDE개까지 넣고, 해설이 인용한 조문 원문(최대 2개)을 같이 넣는다. 순서: 조문, 해설이 인용한 조문, 해설."""
    db=_load();hits=search(question,limit*3,laws)
    if strength(hits)<RELATED:return []
    arts=[];guides=[];top=hits[0]['score']
    for h in hits:
        if h['score']<top*0.4 or len(arts)+len(guides)>=limit:break
        if h['ref'].startswith('easylaw:'):
            if len(guides)<MAX_GUIDE:guides.append(h)
        else:arts.append(h)
    have={h['ref'] for h in arts};extra=[]
    for g in guides:
        for r in db['by_ref'][g['ref']]['cites']:
            if len(extra)>=2:break
            if r in db['by_ref'] and r not in have and (not laws or r.split(':')[0] in laws):
                d=db['by_ref'][r];have.add(r)
                extra.append({'ref':r,'label':label(r),'title':d['title'],'text':d['text'],'score':g['score'],'match':g['match'],
                              'law':db['laws'][d['key']]['name'],'source':source(r),'via':g['ref']})
    return arts+extra+guides

def clip(s,n):return s if len(s)<=n else s[:n].rstrip()+' …(이하 생략)'

def grounding_block(question,limit=4,laws=None,hits=None,per=1500,total=6000,ids=False):
    """AI에게 줄 '[관련 법령 원문]' 글. 맞는 조문이 없으면 빈 글. ids=True면 각 조문 앞에 [corpus:참조]를 붙인다."""
    hits=related(question,limit,laws) if hits is None else hits
    out=[];used=0
    for h in hits:
        head=(f"[corpus:{h['ref']}] " if ids else '- ')+h['label']
        body=clip(h['text'],per)
        if used+len(body)>total and out:break
        out.append(head+'\n'+body);used+=len(body)
    return '\n\n'.join(out)
