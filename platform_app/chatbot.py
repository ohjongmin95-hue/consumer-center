"""상담창 AI 답변.

ANTHROPIC_API_KEY가 있고 입점 기업 상담창이면, Claude가 그 회사의 안내 문구·자동 처리 규칙·반품 안내·상품정보만 보고 답한다.
키가 없거나 실패하면 None을 돌려주고, 상담창은 예전처럼 유형별 안내 문구로 답한다.
"""
import os, json, re
import core, drafting

MODEL=os.getenv('CHAT_MODEL','claude-haiku-5-5')
MAX_TURNS=10  # 앞에서 주고받은 말은 이만큼만 같이 보낸다

def company_facts(db,co):
    """AI에게 줄 회사 정보: 유형별 안내·자동 처리 여부, 반품 안내, 상품정보."""
    out=[]
    for cat in core.CATS:
        r=core.rule_for(db,co['id'],cat)
        how='접수하면 바로 처리' if r['auto'] and not r['cond'] else ('받은 지 7일 이내면 바로 처리' if r['auto'] else '담당자가 확인 후 처리')
        out.append(f"- {cat} ({how}): {r['faq']}")
    lines=['[유형별 안내]']+out
    guide=core.return_guide(co)
    if guide:lines+=['','[반품·교환 보내실 곳]',guide]
    ps=core.products(db,co['id'])
    if ps:
        lines+=['','[상품정보]']
        for p in ps:
            bits=[p['name']]
            if p['price']:bits.append('가격 '+p['price'])
            if p['stock']:bits.append(core.STOCKS.get(p['stock'],p['stock']))
            if p['info']:bits.append(p['info'].replace('\n',' '))
            lines.append('- '+' / '.join(bits))
    return '\n'.join(lines)

def clean_history(raw):
    """브라우저가 보낸 앞의 대화 [{who:'me'|'bot',text}]. 모양이 이상하면 버린다."""
    try:h=json.loads(raw) if isinstance(raw,str) else raw
    except Exception:return []
    out=[]
    for t in (h if isinstance(h,list) else [])[-MAX_TURNS:]:
        if isinstance(t,dict) and t.get('who') in ('me','bot') and isinstance(t.get('text'),str) and t['text'].strip():
            role='user' if t['who']=='me' else 'assistant';msg=t['text'].strip()[:800]
            if out and out[-1]['role']==role:out[-1]['content']+='\n'+msg  # 같은 쪽 말이 이어지면 하나로
            else:out.append({'role':role,'content':msg})
    while out and out[0]['role']!='user':out.pop(0)
    return out

def parse(text):
    """{"category":..,"answer":..} 꼴 답을 읽는다. JSON이 아니면 글 전체를 답으로 쓴다."""
    m=re.search(r'\{.*\}',text or '',re.S)
    if m:
        try:
            d=json.loads(m.group(0))
            ans=str(d.get('answer') or '').strip()
            if ans:return {'answer':ans[:1500],'category':d.get('category') if d.get('category') in core.CATS else None}
        except Exception:pass
    t=(text or '').strip()
    return {'answer':t[:1500],'category':core.classify(t)} if t else None

def ready():return bool(core.secret('ANTHROPIC_API_KEY'))
def answer(co,facts,text,history=None):
    """고객 한마디에 대한 AI 답. facts는 company_facts()로 미리 만든 회사 정보. {'answer','category'} 또는 None (키 없음·실패)."""
    if not ready():return None
    tone=drafting.TONE_HINT.get(co['tone'],drafting.TONE_HINT['polite'])
    system=(f"너는 온라인 쇼핑몰 '{co['name']}'의 고객센터 상담창이다. 고객 질문에 한국어로 답한다.\n"
            f"말투: {tone}.\n"
            "규칙:\n"
            "- 아래 '회사 정보'에 있는 내용만 사실로 말한다. 가격·재고·일정·금액을 지어내지 않는다. 모르면 모른다고 하고 접수를 권한다.\n"
            "- 환불·보상·교환을 확정해 약속하지 않는다. 회사 안내에 있는 절차만 알려 준다.\n"
            "- 카드번호·비밀번호 같은 민감한 정보를 묻지 않는다.\n"
            "- 3~4문장 이내로 짧게 답한다. 고객 탓을 하지 않는다.\n"
            f"- category는 고객 문의가 해당하는 유형 하나({', '.join(core.CATS)}) 또는 상품 문의처럼 해당 없으면 null.\n"
            "출력은 JSON 한 개만: {\"category\": \"유형 또는 null\", \"answer\": \"고객에게 보여 줄 답\"}\n\n"
            "[회사 정보]\n"+facts)
    msgs=clean_history(history)
    if msgs and msgs[-1]['role']=='user':msgs[-1]['content']+='\n'+text
    else:msgs.append({'role':'user','content':text})
    return parse(drafting.call(system,msgs,model=MODEL,max_tokens=600,timeout=25))
