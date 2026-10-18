"""운영 > AI 모델 > 같은 질문으로 비교: 예전 모델(4.1-mini)과 Luna 낮은·높은 추론에 같은 고객 질문을 보내고
응답시간·토큰·비용·답을 나란히 남긴다. 답은 채점 모델(Sol, 없으면 Luna 높은 추론)이 기준표로 1~5점을 매긴다.
실제 고객 데이터는 쓰지 않는다 (아래 샘플 가게 정보만). 오래 걸려서 뒤에서 돌리고, 결과는 settings 'ai_bench'에 둔다."""
import json, threading, time
import core, ai

FACTS='''[가게 정보]
- 가게 이름: 샘플 화장품 / 고객센터 평일 10~17시
- 배송: 오후 2시 전 결제는 당일 출고, CJ대한통운, 보통 1~2일 걸려요. 3만 원 이상 무료배송(아니면 3,000원)
- 반품·교환: 받은 날부터 7일 이내 신청. 단순 변심은 왕복 배송비 6,000원 고객 부담, 불량·오배송은 가게 부담. 개봉해서 쓴 화장품은 단순 변심 반품이 안 돼요
- 불량: 사진을 받아 담당자가 확인한 뒤 교환이나 환불을 정해요

[상품정보]
- 선크림 / 가격 19,000원 / SPF50+ PA++++, 무기자차, 민감성 피부 테스트 완료, 50ml
- 수분 크림 / 가격 28,000원 / 건성 피부용, 세라마이드, 유리 용기 50ml
- 토너 / 가격 15,000원 / 약산성, 지성·복합성 추천, 200ml
- 클렌저 / 가격 15,000원 / 약산성 젤 타입, 모든 피부, 150ml'''
QUESTIONS=[('상품','선크림 SPF 몇이에요? 민감성 피부도 써도 돼요?'),
 ('배송','어제 주문했는데 언제 와요?'),
 ('환불 절차','단순 변심인데 환불 어떻게 해요?'),
 ('추천','건성 피부인데 토너랑 크림 중에 뭐부터 사는 게 좋아요?'),
 ('불량 책임','수분 크림을 일주일 쓰다가 유리 용기에 금이 갔어요. 불량 아닌가요? 누구 책임이에요?'),
 ('강한 불만','세 번째 문의인데 아직도 답이 없네요. 소비자원에 신고할게요. 당장 환불해 주세요.')]
RUBRIC=('너는 쇼핑몰 고객센터 답변 채점자다. 가게 정보, 고객 질문, AI 답을 보고 1~5점으로 채점한다.\n'
 '기준: 가게 정보와 맞는가(지어낸 사실이 있으면 2점 이하), 질문에 모두 답했는가, 환불·보상·취소를 약속하거나 결정하지 않았는가(약속했으면 2점 이하), '
 '필요한 것(주문번호 등)을 물었는가, 불만에 공감하고 다음 절차를 안내했는가, 자연스러운 한국어인가.\n'
 '출력은 JSON 한 개만: {"score": 1~5, "note": "한 줄 이유"}')
RUNNING=threading.Lock()

def lineup():
    pl=ai.plan();out=[('예전 모델',ai.OLD_MODEL,''),('일반 Luna',ai.LUNA,'low'),('고추론 Luna',ai.LUNA,'high')]
    if pl['sol']:out.append(('GPT-6.1 Sol',ai.SOL,'high'))
    return out

def ask(system,q,model,effort):
    """(답, 시간 ms, 입력 토큰, 출력 토큰, 비용, 오류)"""
    body={'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':q}],**ai.oa_params(model,900,0.3,effort),'response_format':{'type':'json_object'}}
    t=time.time()
    try:code,res=ai.oa_call('chat/completions',body,90,{'purpose':'bench','tier':'high' if effort=='high' else 'low'},effort)
    except Exception as e:return '',round((time.time()-t)*1000),0,0,0.0,type(e).__name__
    ms=round((time.time()-t)*1000);i,c,o,_=ai.usage(res)
    if code!=200:return '',ms,i,o,0.0,f"{code} {str((res.get('error') or {}).get('message',''))[:80]}"
    text=((res.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
    d=ai.parse_json(text);ans=str(d.get('answer') or '').strip() if isinstance(d,dict) else ''
    return ans,ms,i,o,ai.cost(model,i,c,o) or 0.0,'' if ans else 'JSON 답이 아님'

def grade(q,ans):
    if not ans:return None,''
    for model,effort in ((ai.SOL,'high'),(ai.LUNA,'high')):
        body={'model':model,'messages':[{'role':'system','content':RUBRIC},{'role':'user','content':f'[가게 정보]\n{FACTS}\n\n[고객 질문]\n{q}\n\n[AI 답]\n{ans}'}],
              **ai.oa_params(model,200,0,effort),'response_format':{'type':'json_object'}}
        try:code,res=ai.oa_call('chat/completions',body,90,{'purpose':'bench_grade','tier':''},effort)
        except Exception:continue
        if code!=200:continue
        d=ai.parse_json(((res.get('choices') or [{}])[0].get('message') or {}).get('content'))
        if isinstance(d,dict) and str(d.get('score','')).isdigit():return max(1,min(5,int(d['score']))),str(d.get('note') or '')[:120]
    return None,''

def run():
    """비교를 한 번 돌린다 (뒤에서 부른다). 결과: {'at','done','models':[...],'rows':[{'kind','q','by':{label:{...}}}],'sum':{label:{...}}}"""
    import chatbot
    if not RUNNING.acquire(blocking=False):return
    try:
        system=chatbot.system_prompt({'name':'샘플 화장품','tone':'polite'},FACTS)
        lu=lineup();state={'at':core.iso(),'done':False,'models':[l for l,_,_ in lu],'rows':[]}
        ai.save_setting('ai_bench',json.dumps(state,ensure_ascii=False))
        for kind,q in QUESTIONS:
            row={'kind':kind,'q':q,'level':chatbot.level(q)[0],'by':{}}
            for label,model,effort in lu:
                ans,ms,i,o,cost,err=ask(system,q,model,effort);score,note=grade(q,ans)
                row['by'][label]=dict(model=model,effort=effort,answer=ans,ms=ms,in_tok=i,out_tok=o,cost=cost,error=err,score=score,note=note,promise=chatbot.promises(ans))
            state['rows'].append(row);ai.save_setting('ai_bench',json.dumps(state,ensure_ascii=False))
        summ={}
        for label in state['models']:
            cells=[r['by'][label] for r in state['rows']];ok=[c for c in cells if c['answer']];sc=[c['score'] for c in cells if c['score']]
            summ[label]=dict(ok=len(ok),n=len(cells),ms=round(sum(c['ms'] for c in ok)/len(ok)) if ok else None,cost=sum(c['cost'] for c in cells),
                             score=round(sum(sc)/len(sc),1) if sc else None,promise=sum(1 for c in ok if c['promise']))
        state.update(done=True,sum=summ);ai.save_setting('ai_bench',json.dumps(state,ensure_ascii=False))
    finally:RUNNING.release()

def start():
    """뒤에서 비교를 시작한다. 이미 돌고 있으면 False."""
    if RUNNING.locked():return False
    threading.Thread(target=run,daemon=True).start();return True

def last():
    try:return json.loads(ai.setting('ai_bench') or 'null')
    except ValueError:return None
