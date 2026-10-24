"""배포 전·후 실제 점검. 운영 DB를 복사한 임시 DB로만 돌리므로 운영 데이터는 바뀌지 않는다.

  sudo bash /opt/soboru/app/deploy/preview.sh [PDF 경로]   (새 버전을 따로 받아 점검, 배포 전)
  또는 지금 설치된 버전 점검:  cd /opt/soboru/app/platform_app && python selftest.py [PDF 경로]

  1. 기존 데이터: 복사본에서 새 버전이 열려도 기업·요청·상담 기록 수가 그대로인지
  2. 기존 화면: 고객 화면, 사장님 화면, 운영 화면이 열리는지
  3. AI 상담(실제 OpenAI): 여러 번 이어지는 대화, 불만·환불 요청 시 담당자 연결
  4. PDF 상품 추출(실제 OpenAI, PDF를 줬을 때): 상품 수, 공급가가 고객용 칸에 없는지
키와 개인정보는 출력하지 않는다.
"""
import os, re, sys, json, shutil, sqlite3, tempfile

SRC=os.getenv('PLATFORM_DATABASE_PATH','')
TMP=tempfile.mkdtemp(prefix='soboru-selftest-')
ok_all=True
def say(ok,msg):
    global ok_all
    ok_all&=bool(ok);print(('  통과  ' if ok else '  실패  ')+msg,flush=True)

def copy_db():
    dst=os.path.join(TMP,'platform.sqlite3')
    if SRC and os.path.exists(SRC):
        s=sqlite3.connect(f'file:{SRC}?mode=ro',uri=True);d=sqlite3.connect(dst);s.backup(d);s.close();d.close()
    return dst
COUNT_TABLES=('companies','cases','events','chat_log','products','rules')
def counts(path):
    db=sqlite3.connect(path);out={}
    for t in COUNT_TABLES:
        try:out[t]=db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        except sqlite3.Error:out[t]=None
    db.close();return out

def main(pdf_path=None,hook=None):
    """hook: 코드를 불러온 직후 부를 함수 (개발용, AI 호출을 가짜로 바꿀 때)."""
    if 'core' in sys.modules:raise SystemExit('점검은 앱 코드를 불러오기 전에 시작해야 해요 (운영 DB 보호)')
    print('SOBORU CSCS 점검 (운영 DB 복사본 사용, 운영 데이터는 바뀌지 않아요)')
    copy=copy_db();before=counts(copy)
    os.environ.update(PLATFORM_DATABASE_PATH=copy,PLATFORM_UPLOAD_DIR=os.path.join(TMP,'uploads'),HTTPS_ONLY='0')
    for k in [k for k in os.environ if k.startswith(('SMTP_','TELEGRAM_','ALERT_'))]:os.environ.pop(k)  # 점검 중 메일·알림을 보내지 않는다
    sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
    import core, hanq, consumer, business, chatbot, ai, product_pdf  # 새 버전 코드가 복사본에 표를 더한다 (hanq: 세션 설정)
    if hook:hook()

    print('\n1. 기존 데이터')
    say(os.path.abspath(str(core.DB))!=os.path.abspath(SRC or '-'),'운영 DB가 아닌 복사본으로 점검')
    after=counts(copy)
    for t in COUNT_TABLES:say(before[t]==after[t],f'{t}: {before[t]} → {after[t]}')

    print('\n2. 기존 화면')
    with core.conn() as db:
        co=db.execute("SELECT * FROM companies WHERE status='active' AND member=1 ORDER BY id LIMIT 1").fetchone()
    c=consumer.app.test_client();bz=business.app.test_client()
    for name,cl,path in (('고객 첫 화면',c,'/'),('사장님 로그인',bz,'/login'),('사장님 첫 화면',bz,'/'),('운영 로그인',bz,'/ops/login')):
        code=cl.get(path).status_code;say(code in (200,302),f'{name} ({path}) {code}')
    if not co:
        say(False,'운영 중인 입점 기업이 없어 상담 점검을 건너뛰어요');return finish()
    page=c.get(f"/to/{co['id']}");say(page.status_code==200,f"기업 상담 화면 (/to/{co['id']}) {page.status_code}")
    with bz.session_transaction() as s:s['co_id']=co['id']
    for path in ('/','/approvals','/all','/returns','/stats','/rules','/orders','/connect','/settings'):
        code=bz.get(path).status_code;say(code in (200,302),f'사장님 화면 {path} {code}')

    print('\n3. AI 상담 (실제 '+(ai.provider() or '키 없음')+')')
    if not ai.ready():
        say(False,'AI 키가 없어요. 운영 화면 > 서비스 키에서 OpenAI 키를 넣거나, update.sh가 AI 서버 설정에서 복사해요');return finish(pdf_path,co)
    tok=re.search(r'data-csrf="([^"]+)"',page.get_data(as_text=True)).group(1)
    hist=[]
    def talk(text):
        j=c.post(f"/chat/{co['id']}",data={'csrf':tok,'text':text,'history':json.dumps(hist,ensure_ascii=False)}).get_json() or {}
        hist.extend([{'who':'me','text':text},{'who':'bot','text':j.get('answer') or j.get('faq') or ''}])
        print(f"    고객: {text}\n    AI: {(j.get('answer') or '(AI 답 없음)')[:300]}\n    (유형 {j.get('category')}, 담당자 연결 {j.get('handoff')})")
        return j
    j1=talk('안녕하세요. 어떤 상품을 파는지 알려 주세요.');say(bool(j1.get('answer')),'첫 질문에 AI가 답함')
    j2=talk('방금 말한 것 중 첫 번째는 얼마예요? 그리고 배송은 보통 며칠 걸려요?');say(bool(j2.get('answer')),'앞 대화를 이어 두 가지 질문에 답함')
    j3=talk('받은 상품 상자가 찢어져 있고 내용물이 샜어요. 너무 화나네요. 환불해 주세요. 주문번호는 A-1234예요.')
    a3=j3.get('answer') or ''
    say(bool(j3.get('handoff')),'파손·환불 요청은 담당자 연결로 넘김')
    say(not re.search(r'환불(을|이)? ?(해 ?드렸|처리했|완료|처리되었)',a3),'환불을 직접 했다고 말하지 않음')
    say('A-1234' in (j3.get('summary') or ''),'담당자용 요약에 주문번호가 들어감')
    with core.conn() as db:facts=chatbot.company_facts(db,co)
    with core.conn() as db:priv=list(product_pdf.private_for(db,co['id']).values())
    say(all(not v or v not in facts for v in priv),'상담 AI가 보는 회사 정보에 내부 정보(공급가 등)가 없음')
    return finish(pdf_path,co)

def finish(pdf_path=None,co=None):
    if pdf_path:
        print('\n4. PDF 상품 추출 (실제 AI)')
        import ai, product_pdf
        try:
            raw=open(pdf_path,'rb').read();items=product_pdf.extract(raw)
            say(True,f'상품 {len(items)}개 찾음')
            for it in items:
                flag=(' · 확인 필요: '+', '.join(it['check'])) if it['check'] else ''
                print(f"    - {it['name']} / 소비자가 {it['price'] or '없음'} / 내부 정보 {len(it['internal'])}칸{flag}")
            leak=[it['name'] for it in items if product_pdf.SECRET_WORDS.search(product_pdf.compose(it)+' '+it['price'])]
            say(not leak,'고객용 내용에 공급가·마진 같은 말이 없음'+(f' (문제: {leak})' if leak else ''))
            nums=[it['name'] for it in items for k in ('supply','wholesale','cost') for n in product_pdf._nums(it['internal'].get(k,'')) if len(n)>=4 and n in product_pdf._nums(product_pdf.compose(it)+' '+it['price'])]
            say(not nums,'고객용 내용에 내부 가격 숫자가 없음'+(f' (문제: {nums})' if nums else ''))
        except ValueError as e:say(False,f'PDF 추출 실패: {e}')
    shutil.rmtree(TMP,ignore_errors=True)
    print('\n결과: '+('모두 통과했어요' if ok_all else '실패한 항목이 있어요. 위의 "실패" 줄을 알려 주세요'))
    return 0 if ok_all else 1

if __name__=='__main__':sys.exit(main(sys.argv[1] if len(sys.argv)>1 else None))
