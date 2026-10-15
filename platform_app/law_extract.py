"""law_texts.json 만들기: 국가법령정보센터 원문 미러(github.com/legalize-kr/legalize-kr, kr/<법령명>/법률.md·시행령.md)에서 필요한 조문만 글자 그대로 뽑는다.
받은 파일은 <법령명>_법률.md, <법령명>_시행령.md 이름으로 한 폴더에 둔다. 사용법: python law_extract.py <폴더> law_texts.json (손으로 조문을 옮겨 쓰지 않는다)"""
import re, json, sys
from pathlib import Path
src=Path(sys.argv[1]); out=Path(sys.argv[2])
WANT={
 '전자상거래등에서의소비자보호에관한법률_법률.md':('ecom',['제15조','제17조','제18조','제21조']),
 '전자상거래등에서의소비자보호에관한법률_시행령.md':('ecom_dec',['제21조','제21조의3']),
 '소비자기본법_법률.md':('basic',['제16조']),
 '소비자기본법_시행령.md':('basic_dec',['제8조']),
 # 헬스장·학원 이용권 같은 계속거래 (오프라인 계약은 전자상거래법이 아니라 이 법)
 '방문판매등에관한법률_법률.md':('door',['제2조','제31조','제32조','제34조']),
 '방문판매등에관한법률_시행령.md':('door_dec',['제41조']),
}
TAG=re.compile(r'\s*<(개정|신설|전문개정|본조신설|제목개정)[^>]*>')
def meta(txt):
    fm=txt.split('---')[1];m={}
    for line in fm.splitlines():
        if ':' in line and not line.startswith(' '):k,_,v=line.partition(':');m[k.strip()]=v.strip().strip("'")
    return m
res={}
for fn,(key,arts) in WANT.items():
    txt=(src/fn).read_text(encoding='utf-8');m=meta(txt)
    law={'name':m['제목'],'kind':m['법령구분'],'no':m['공포번호'],'promulgated':m['공포일자'],'effective':m['시행일자'],'source':m['출처'],'articles':{}}
    blocks=re.split(r'(?m)^##### ',txt)
    for b in blocks[1:]:
        head,_,body=b.partition('\n')
        mm=re.match(r'(제\d+조(?:의\d+)?)\s*(?:\((.*)\))?',head.strip())
        if not mm or mm.group(1) not in arts:continue
        paras=[];cur=None
        for line in body.splitlines():
            if line.startswith('#'):break
            s=TAG.sub('',line).rstrip()
            if not s.strip():continue
            pm=re.match(r'\*\*(.)\*\*\s*(.*)',s)
            im=re.match(r'\s+(\d+(?:의\d+)?)\\\.\s*(.*)',s)
            sm=re.match(r'\s+([가-하])\\\.\s*(.*)',s)
            if sm and cur is not None and cur['items']:cur['items'][-1].setdefault('subs',[]).append({'n':sm.group(1),'text':sm.group(2)});continue
            if pm:cur={'n':pm.group(1),'text':pm.group(2),'items':[]};paras.append(cur)
            elif im and cur is not None:cur['items'].append({'n':im.group(1),'text':im.group(2)})
            elif im:cur={'n':'','text':'','items':[{'n':im.group(1),'text':im.group(2)}]};paras.append(cur)
            else:cur={'n':'','text':s.strip(),'items':[]};paras.append(cur)
        law['articles'][mm.group(1)]={'title':mm.group(2) or '','paras':paras}
    missing=set(arts)-set(law['articles'])
    assert not missing,(fn,missing)
    res[key]=law
out.write_text(json.dumps(res,ensure_ascii=False,indent=1),encoding='utf-8')
print('ok',{k:list(v['articles']) for k,v in res.items()})
