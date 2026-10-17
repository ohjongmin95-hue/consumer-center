"""law_corpus.json 만들기: 국가법령정보센터(law.go.kr)에서 받은 법령 PDF를 pdftotext로 글자만 뽑아 이어 붙인 파일을 조문 단위로 나눈다.

사용법: python platform_app/law_corpus_build.py <소비자법령_원문_모음.txt> platform_app/law_corpus.json
  (관리자 > 법령 학습에서 올린 PDF도 parse_text()로 같은 방식으로 나눈다. LAWS에 없는 법령은 key·짧은 이름을 이름으로 만든다)
  · 법령마다 첫 줄은 '법제처 1 국가법령정보센터', 다음 줄은 법령 이름, 그 뒤 '[시행 YYYY. M. D.] [법률 제NNNNN호, ...]'
  · 쪽마다 되풀이되는 머리글('법제처 N 국가법령정보센터' + 법령 이름)은 지운다
  · PDF 줄바꿈으로 끊긴 문장은 다시 잇는다. 띄어 쓸지 붙일지는 같은 파일 안에서 그 낱말이 붙어 나온 적이 있는지로 정한다
  · 조문 끝의 <개정 …>·[본조신설 …] 같은 연혁 표시는 뺀다 (law_texts.json과 같은 방식). 부칙은 넣지 않는다
  · 화장품법 PDF 뒤에 붙어 있던 '찾기 쉬운 생활법령정보'(easylaw.go.kr, 인터넷 쇼핑) 해설은 법령이 아니므로
    key 'easylaw', kind '생활법령정보'로 따로 담는다 (법적 효력 없는 해설임을 이름에 밝힌다)
조문 글자는 손으로 고쳐 쓰지 않는다. 법이 바뀌면 PDF를 새로 받아 이 스크립트를 다시 돌린다.
"""
import bisect, json, re, sys
from collections import Counter

# 법령 이름 -> (key, 짧은 이름)
LAWS={'화장품법':('cosmetics','화장품법'),
      '약관의 규제에 관한 법률':('terms','약관법'),
      '표시ㆍ광고의 공정화에 관한 법률':('adlabel','표시광고법'),
      '민법':('civil','민법'),
      '전자상거래 등에서의 소비자보호에 관한 법률 시행령':('ecom_dec','전자상거래법 시행령'),
      '식품 등의 표시ㆍ광고에 관한 법률':('foodlabel','식품표시광고법'),
      '식품위생법':('food','식품위생법'),
      '소비자기본법':('basic','소비자기본법'),
      '소비자분쟁해결기준':('kca','소비자분쟁해결기준'),
      '전자상거래 등에서의 소비자보호에 관한 법률':('ecom','전자상거래법')}
CIRCLED='①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'
HANGUL_ORDER='가나다라마바사아자차카타파하'
PAGE=re.compile(r'^법제처 \d+ 국가법령정보센터$')
ART=re.compile(r'^제(\d+)조(?:의(\d+))?(?=\(| 삭제|삭제)')
TAG=re.compile(r'\s*<(?:개정|신설|전문개정|본조신설|제목개정|타법개정)[^>]*>')
NOTE=re.compile(r'^\[(?:본조신설|전문개정|제목개정|종전|본조제목개정|제\d+조(?:의\d+)?에서 이동|.*이동 <)')
CHAPTER=re.compile(r'^\s*제\d+(?:장|절|관)(?:의\d+)?\s')
PUNCT_END=tuple('.,;:)]>」』”’·ㆍ')

# ---------- 줄 잇기 ----------
class Joiner:
    """PDF에서 끊긴 두 줄을 이을 때 띄어 쓸지 정한다.
    파일 전체에서 낱말(띄어쓰기 사이 글자 덩어리)과 띄어 쓴 두 낱말을 세어, 붙인 꼴과 띄운 꼴 중 더 자주 나온 쪽을 고른다."""
    WORD=re.compile(r'[0-9A-Za-z가-힣]+')
    def __init__(self,lines):
        self.n=Counter();self.pair=Counter()
        prev_end=True
        for l in lines:
            raw=l.split()
            if not raw:prev_end=True;continue
            # 줄 끝 낱말은 문장 부호로 끝날 때만, 줄 첫 낱말은 앞 줄이 문장 부호로 끝났을 때만 센다 (끊긴 조각을 세지 않게)
            lo=0 if prev_end else 1;hi=len(raw) if raw[-1].endswith(PUNCT_END) else len(raw)-1
            for t in raw[lo:hi]:
                if re.fullmatch(r'(\d+(의\d+)?|[가-하])\.|[①-⑳]',t):continue  # 항·호·목 번호
                for w in self.WORD.findall(t):self.n[w]+=1
            for x,y in zip(raw,raw[1:]):
                if self.WORD.search(x+'.') and re.search(r'[0-9A-Za-z가-힣]$',x) and re.match(r'[0-9A-Za-z가-힣]',y):
                    self.pair[self.WORD.findall(x)[-1],self.WORD.findall(y)[0]]+=1
            prev_end=raw[-1].endswith(PUNCT_END)
        keys=sorted(self.n);self.keys=keys;acc=[0]
        for k in keys:acc.append(acc[-1]+self.n[k])
        self.acc=acc
    def prefix(self,p):
        """p로 시작하는 낱말 수"""
        i=bisect.bisect_left(self.keys,p);j=bisect.bisect_left(self.keys,p+'\U0010ffff')
        return self.acc[j]-self.acc[i]
    def join(self,a,b):
        a=a.rstrip();b=b.strip()
        if not a:return b
        if not b:return a
        if b[0] in ',.;:)]>」』”’ㆍ·%' or a[-1] in '(「『“‘[<ㆍ·':return a+b
        if a[-1] in PUNCT_END:return a+' '+b
        if not (re.search(r'[0-9A-Za-z가-힣]$',a) and re.match(r'[0-9A-Za-z가-힣]',b)):return a+' '+b
        cx=self.WORD.findall(a.split()[-1])[-1];cy=self.WORD.findall(b.split()[0])[0]
        if cx.endswith('제') and cy[0].isdigit():return a+b  # 「…법」 제\n17조
        if cx[-1].isdigit() and re.match(r'(조|항|호|목|일|월|년|개|명|원|퍼센트|분의|시간|세|회|배|층)',cy):return a+b
        both=self.prefix(cx+cy);apart=self.pair[cx,cy]
        if both or apart:return a+b if both>=apart else a+' '+b
        if (re.match(r'(한|할|함|하[는여고며면지기거였]|된|될|됨|되[는어고며면지기었])',cy) and re.search(r'[가-힣]$',cx)
                and not re.search(r'[야게지고서록며면는은을를이가에와과도로의]$',cx)):
            return a+b  # '포함\n한다', '약정\n한' (단, '하여야\n한다'는 띄움)
        if (not self.n[cy] and not self.n[cx] and re.match(r'[가-힣]',cy)
                and not re.search(r'[이가은는을를의에로와과도만며고서]$',cx)):return a+b  # 두 조각 다 낱말로 나온 적이 없으면 낱말 가운데서 끊긴 것
        return a+' '+b

# ---------- 법령 본문 ----------
def split_laws(lines):
    """[(이름, 시작 줄 번호, 줄들)]. '법제처 1 국가법령정보센터' 다음 줄 이름이 바뀌면 새 법령."""
    starts=[i for i,l in enumerate(lines) if l.strip()=='법제처 1 국가법령정보센터']
    out=[]
    for j,s in enumerate(starts):
        e=starts[j+1] if j+1<len(starts) else len(lines)
        out.append((lines[s+1].strip(),s,lines[s:e]))
    return out

def meta(name,block):
    for l in block[:8]:
        m=re.match(r'^\[시행 (\d{4})\. ?(\d{1,2})\. ?(\d{1,2})\.\] \[(.+?) 제([\d-]+)호, (\d{4})\. ?(\d{1,2})\. ?(\d{1,2})\.',l.strip())
        if m:
            eff=f'{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}';prom=f'{m[6]}-{int(m[7]):02d}-{int(m[8]):02d}'
            kind=m[4];return kind,m[5],eff,prom
    raise ValueError('시행일 줄을 못 찾음: '+name)

def body_lines(name,block):
    """머리글·장 제목·빈 줄을 지운 본문 줄 (부칙 앞까지)."""
    out=[];i=0
    while i<len(block):
        l=block[i].rstrip();s=l.strip()
        if PAGE.match(s):
            i+=1
            if i<len(block) and block[i].strip()==name:i+=1
            continue
        if re.match(r'^부칙(\s*<|$)',s):break
        if s and not CHAPTER.match(l):out.append(s)
        i+=1
    # 첫 조문 앞(법령 이름·시행일·담당 부서)은 버린다
    for k,l in enumerate(out):
        if ART.match(l):return out[k:]
    return []

def art_num(m):return (int(m[1]),int(m[2] or 0))

def logical(lines,J):
    """물리 줄 -> 조문 머리·항·호·목 단위로 시작하는 논리 줄. 번호 차례가 맞을 때만 새 줄로 본다(줄바꿈된 날짜 등과 구분)."""
    out=[];last_art=(0,0);para=-1;item=0;sub=-1
    for l in lines:
        m=ART.match(l)
        if m and art_num(m)>last_art:
            last_art=art_num(m);item=0;sub=-1;out.append(['art',l])
            para=0 if re.match(r'^제\d+조(?:의\d+)?\([^①]*?\)\s*①',l) else -1  # 머리 줄 안에 ①이 있으면 다음은 ②
            continue
        c=l[0]
        if out and out[-1][1].count('<')>out[-1][1].count('>'):  # '<개정 2019.\n1. 15.>'처럼 연혁 표시 안에서 끊긴 줄
            out[-1][1]=J.join(out[-1][1],l);continue
        if c in CIRCLED and (CIRCLED.index(c)==para+1 or (para<0 and c=='①')):
            para=CIRCLED.index(c);item=0;sub=-1;out.append(['para',l]);continue
        im=re.match(r'^(\d+)(?:의(\d+))?\.\s',l)
        if im and ((int(im[1])==item+1 and not im[2]) or (int(im[1])==item and im[2]) or (int(im[1])==1 and not im[2])) and out:
            item=int(im[1]);sub=-1;out.append(['item',l]);continue
        sm=re.match(r'^([가-하])\.\s',l)
        if sm and sm[1] in HANGUL_ORDER and HANGUL_ORDER.index(sm[1])==sub+1:
            sub+=1;out.append(['sub',l]);continue
        if re.match(r'^\d+\)\s',l) or (l.startswith('[') and NOTE.match(l)):
            out.append(['etc',l]);continue
        if out and not (out[-1][0]=='etc' and out[-1][1].startswith('[') and out[-1][1].endswith(']')):out[-1][1]=J.join(out[-1][1],l)
        elif out:out.append(['etc',l])
    return out

def paren_end(s,i):
    d=0
    for k in range(i,len(s)):
        if s[k]=='(':d+=1
        elif s[k]==')':
            d-=1
            if d==0:return k
    return -1

def parse_law(name,block,J):
    arts={};cur=None
    for kind,text in logical(body_lines(name,block),J):
        if kind=='etc' and NOTE.match(text):continue  # [본조신설 …] 같은 연혁
        text=TAG.sub('',text).strip()
        if kind=='art':
            m=ART.match(text);no='제'+m[1]+'조'+('의'+m[2] if m[2] else '');rest=text[m.end():]
            title=''
            if rest.startswith('('):
                e=paren_end(rest,0);title=rest[1:e];rest=rest[e+1:]
            rest=rest.strip()
            if rest.startswith('삭제'):title=title or '삭제'
            cur=arts[no]={'title':title,'lines':[rest] if rest else []}
        elif cur is not None and text:
            cur['lines'].append(('  ' if kind=='item' else '    ' if kind=='sub' else '')+text)
    return {k:{'title':v['title'],'text':'\n'.join(v['lines'])} for k,v in arts.items()}

# ---------- 찾기 쉬운 생활법령정보 ----------
def easylaw(lines,J):
    """화장품법 부칙 뒤에 붙어 온 생활법령정보 쪽들. 쪽(목차 번호)마다, 다시 소제목마다 나눈다. 같은 쪽이 두 번 들어 있으면 한 번만."""
    pages={};i=0;n=len(lines)
    while i<n:
        if not lines[i].startswith('이 정보는 ') or '기준으로 작성된 것입니다' not in lines[i]:i+=1;continue
        k=i+1
        while k<n and not re.match(r'^\d+\.\d+\.\d+\.\s',lines[k].strip()):k+=1
        if k>=n:break
        path,_,title=lines[k].strip().partition('. ');path=path.rstrip('.')
        body=[];k+=1
        while k<n:
            s=lines[k].strip()
            if s.startswith('이 정보는 ') and '기준으로 작성된 것입니다' in s:break
            if s=='찾기쉬운 생활법령' and k+1<n and re.match(r'^\d+ / (\d+)$',lines[k+1].strip()):
                p=re.match(r'^(\d+) / (\d+)$',lines[k+1].strip());k+=2
                if p[1]==p[2]:break  # 마지막 쪽
                continue
            if s:body.append(s)
            k+=1
        i=k
        if path not in pages:pages[path]=(title.strip(),body)
    out={}
    for path,(title,body) in pages.items():
        for j,(head,text) in enumerate(chunks(body,J),1):
            out[f'{path}-{j}']={'title':title+(' · '+head if head and head!=title else ''),'text':text}
    return out

def is_head(l,prev):
    if len(l)>28 or l.endswith(PUNCT_END) or l.endswith(('다','요','함','음')):return False
    if re.match(r'^(\d+\.|[가-하]\.|※|→|√|Q\.|A\.|<|\(|-|·|①)',l):return False
    return prev is None or prev.endswith(('.',')','>','다'))

def chunks(body,J,size=350):
    """소제목(짧고 문장으로 끝나지 않는 줄)에서 나누고, 너무 짧은 조각은 다음 조각과 합친다."""
    parts=[];head=None;buf=[];prev=None
    for l in body:
        if is_head(l,prev):
            if buf:parts.append([head,buf])
            head=l;buf=[];prev=l+'.';continue
        if buf and not re.match(r'^(\d+\.|[가-하]\.|※|→|√|Q\.|A\.|<)',l) and not (prev or '').endswith(('.','>')):buf[-1]=J.join(buf[-1],l)
        else:buf.append(l)
        prev=l
    if buf:parts.append([head,buf])
    out=[]
    for h,b in parts:
        t='\n'.join(b)
        if out and len(out[-1][1])<size:out[-1][1]+='\n'+((h+'\n') if h else '')+t
        else:out.append([h or '',t])
    return [(h,t) for h,t in out]

def source(name,kind):
    return ('https://www.law.go.kr/행정규칙/' if '고시' in kind else 'https://www.law.go.kr/법령/')+name.replace(' ','')

def auto_key(name):
    """LAWS에 없는 법령(관리자가 PDF로 더 올린 법령)의 key: 이름으로 만든 'u' + 8글자. 같은 이름이면 늘 같은 key."""
    import hashlib
    return 'u'+hashlib.sha1(name.encode()).hexdigest()[:8]

def short_name(name):
    """LAWS에 없는 법령의 짧은 이름. '할부거래에 관한 법률' -> '할부거래법', '… 법률 시행령' -> '…법 시행령'."""
    tail=''
    for t in (' 시행규칙',' 시행령'):
        if name.endswith(t):name,tail=name[:-len(t)],t;break
    m=re.match(r'^(.+?)(?: 등)?(?:에서의 .+?)?에 관한 (?:법률|특례법)$',name)
    if m:name=m[1].replace(' ','')+'법'
    elif len(name)>16:name=name[:16].rstrip()+'…'
    return name+tail

def law_entry(name,block,J,short=None):
    """법령 하나 {key, name, short, kind, no, effective, promulgated, source, articles}. LAWS에 없는 이름은 key·짧은 이름을 만들어 씀."""
    key,short0=LAWS.get(name) or (auto_key(name),short_name(name))
    kind,no,eff,prom=meta(name,block)
    return {'key':key,'name':name,'short':short or short0,'kind':'고시' if '고시' in kind else kind,'no':no,'effective':eff,'promulgated':prom,
            'source':source(name,kind),'articles':parse_law(name,block,J)}

def normalize(text):
    """pdftotext·pypdf로 뽑은 글을 이 스크립트가 읽는 꼴로: 쪽 나눔(\f) 지우기, 맨 앞에 '법제처 1 국가법령정보센터'가 없으면 붙이기."""
    lines=[l.replace('\f','').rstrip() for l in text.replace('\r\n','\n').split('\n')]
    lines=[re.sub(r'^\s*법제처\s+(\d+)\s+국가법령정보센터\s*$',r'법제처 \1 국가법령정보센터',l) for l in lines]
    first=next((i for i,l in enumerate(lines) if l.strip()=='법제처 1 국가법령정보센터'),len(lines))
    eff=next((i for i,l in enumerate(lines[:40]) if l.strip().startswith('[시행 ')),None)
    if eff is not None and eff<first:
        # 머리글이 없거나 쪽 아래에 붙은 PDF: '[시행 …]' 줄 바로 앞의 글자 있는 줄을 법령 이름으로 본다
        name=next((x.strip() for x in reversed(lines[:eff]) if x.strip()),'')
        if name:lines=['법제처 1 국가법령정보센터',name]+lines
    return lines

def parse_text(text):
    """PDF에서 뽑은 글 -> [법령 dict]. 법령을 못 찾으면 빈 목록. 시행일 줄이 없는 법령은 ValueError."""
    raw=normalize(text);J=Joiner(raw);parts=[]
    for name,start,block in split_laws(raw):
        if parts and parts[-1][0]==name:parts[-1][1].extend(block)  # 같은 법령의 다음 쪽(쪽 번호 1이 다시 나온 경우)
        else:parts.append((name,list(block)))
    return [law_entry(name,block,J) for name,block in parts]

def build(path):
    raw=open(path,encoding='utf-8').read().splitlines()
    J=Joiner(raw);res={}
    for name,start,block in split_laws(raw):
        law=law_entry(name,block,J);key=law['key']
        res[key]=law
        if key=='cosmetics':
            # 화장품법 부칙 뒤에 붙어 온 생활법령정보 해설
            tail=block[next(i for i,l in enumerate(block) if re.match(r'^부칙\s*<',l.strip())):]
            ez=easylaw([l.rstrip() for l in tail],J)
            if ez:res['easylaw']={'key':'easylaw','name':'찾기 쉬운 생활법령정보 – 인터넷 쇼핑 (법령 해설, 법적 효력 없음)','short':'생활법령정보',
                                 'kind':'생활법령정보','no':'','effective':'2026-09-15','promulgated':'','source':'https://www.easylaw.go.kr','articles':ez}
    return res

if __name__=='__main__':
    data=build(sys.argv[1])
    with open(sys.argv[2],'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,separators=(',',':'))
    for k,v in data.items():print(f"{k:10} {v['short']:12} {len(v['articles']):5}조  시행 {v['effective']}")
