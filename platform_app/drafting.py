"""답변 초안 만들기.

ANTHROPIC_API_KEY가 있으면 Claude가 회사 말투(설정의 말투 + 자동 처리 답변 문구)로 초안을 쓴다.
없거나 실패하면 유형별 기본 문구로 초안을 만든다. 어느 쪽이든 초안일 뿐이고 담당자가 고쳐서 보낸다.
"""
import os, json, urllib.request
import core, law

MODEL=os.getenv('DRAFT_MODEL','claude-sonnet-5-5')
TONE_HINT={'polite':'정중하고 차분한 존댓말','friendly':'따뜻하고 친근한 존댓말 (해요체)','brief':'짧고 분명한 존댓말, 군더더기 없이'}

def facts(c):
    chk=law.check(c)
    out=[f"유형: {c['category']}",f"원하는 해결: {c['want']}",f"제목: {c['title']}",f"내용: {c['body']}"]
    if c['product']:out.append(f"상품: {c['product']}")
    if c['order_no']:out.append(f"주문번호: {c['order_no']}")
    if chk:out.append(f"상품 받은 지 {chk['days']}일째 ({'7일 이내' if chk['within'] else '7일 경과'})")
    return out

def fallback(c,co,rule_reply,history):
    name=(c['name'] or '고객')+'님'
    open_={'배송 조회':'배송이 늦어져 걱정하셨을 텐데 죄송합니다.','교환':'교환 요청 확인했습니다.','반품·환불':'반품·환불 요청 확인했습니다.',
           '제품 불량':'상품에 문제가 있어 불편을 드려 정말 죄송합니다.','고객 응대':'응대 과정에서 불쾌하셨던 점 진심으로 사과드립니다.','기타':'문의 주셔서 감사합니다.'}
    lines=[f"안녕하세요, {name}. {co['name']}입니다.",open_.get(c['category'],open_['기타'])]
    chk=law.check(c)
    if chk and c['category'] in ('교환','반품·환불'):
        lines.append('상품을 받으신 지 7일 이내라 반품(교환)이 가능합니다.' if chk['within'] else '상품을 받으신 지 7일이 지나 단순 변심 반품 기간은 지났지만, 상품에 문제가 있다면 사진과 함께 알려 주세요. 확인 후 도와드리겠습니다.')
    if rule_reply:lines.append(rule_reply)
    elif c['category']=='기타':lines.append('말씀하신 내용을 확인한 뒤 바로 다시 안내드리겠습니다.')
    lines.append('더 궁금하신 점은 언제든 말씀해 주세요. 감사합니다.')
    return '\n'.join(lines)

def ask_claude(c,co,rule_reply,history,samples):
    key=core.secret('ANTHROPIC_API_KEY')
    if not key:return None
    refs='\n\n'.join(law.plain(r) for r,_ in law.BY_CAT.get(c['category'],[]))
    tone=TONE_HINT.get(co['tone'],TONE_HINT['polite'])
    system=(f"너는 온라인 쇼핑몰 '{co['name']}'의 고객 상담 담당자다. 고객 요청에 보낼 답변 초안을 한국어로 쓴다.\n"
            f"말투: {tone}. 아래 '회사 답변 예시'의 말투와 표현을 따라 한다.\n"
            "규칙: 사실로 확인되지 않은 일정·금액·약속은 지어내지 말고 {날짜}처럼 중괄호 자리표시로 남긴다. "
            "법 내용은 아래 '관련 조문'에 있는 것만 쓰고, 조문 번호를 고객에게 길게 늘어놓지 않는다. 고객 탓을 하지 않는다. "
            "인사와 맺음말을 포함해 6문장 이내로, 답변 본문만 출력한다.")
    user=("[요청]\n"+'\n'.join(facts(c))+"\n\n[지금까지 주고받은 내용]\n"+(history or '없음')+
          "\n\n[회사 답변 예시]\n"+(samples or '없음')+"\n\n[이 유형의 기본 조치 문구]\n"+(rule_reply or '없음')+"\n\n[관련 조문]\n"+(refs or '없음'))
    return call(system,[{'role':'user','content':user}])

def call(system,messages,model=None,max_tokens=800,timeout=40):
    """Claude에 한 번 묻고 글만 돌려준다. 키가 없거나 실패하면 None."""
    key=core.secret('ANTHROPIC_API_KEY')
    if not key:return None
    body={'model':model or MODEL,'max_tokens':max_tokens,'system':system,'messages':messages}
    req=urllib.request.Request('https://api.anthropic.com/v1/messages',data=json.dumps(body).encode(),method='POST',
        headers={'content-type':'application/json','x-api-key':key,'anthropic-version':'2023-06-01'})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:res=json.loads(r.read().decode())
        text=''.join(b.get('text','') for b in res.get('content',[]) if b.get('type')=='text').strip()
        return text or None
    except Exception:return None

def draft(db,c,co):
    rule=core.rule_for(db,co['id'],c['category'])
    ev=core.events(db,c['id'])
    history='\n'.join(('고객: ' if e['kind']=='me' else '회사: ')+(e['reply'] or e['text']) for e in ev if e['kind'] in ('me','co'))[-2000:]
    samples='\n'.join('- '+r for r in (core.rule_for(db,co['id'],cat)['reply'] for cat in core.CATS) if r)
    text=ask_claude(c,co,rule['reply'],history,samples)
    if text:return {'text':text,'by':'ai'}
    return {'text':fallback(c,co,rule['reply'],history),'by':'template'}
