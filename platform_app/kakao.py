"""카카오톡 채널 문의 받기 (카카오 i 오픈빌더 챗봇 스킬).
소보루가 따로 키를 받지 않는다: 사장님이 카카오 챗봇 관리자센터에서 봇을 만들고, 소보루가 준 스킬 주소를 폴백 블록에 넣고, 콜백을 켜고, 배포해 채널에 잇는다.

  · 고객이 채널에 말을 걸면 카카오가 /hook/kakao/<토큰> 으로 보낸다. 서명이 없어서 회사마다 다른, 추측할 수 없는 토큰으로 확인한다 (DB에는 해시로 찾고, 주소를 다시 보여 주려고 암호화해 둔다).
    같은 고객(userRequest.user.id = 봇 사용자 키)의 말은 끝나지 않은 요청에 이어 붙고, 없으면 새 요청('카카오톡')이 된다. 인스타그램 DM과 같다.
  · 카카오는 5초 안에 답을 받아야 한다. AI 자동 답변을 켰으면 '잠시만요'(useCallback)로 먼저 답하고, AI 답이 나오면 콜백 주소(한 번만 쓰는 주소)로 보낸다.
  · 챗봇은 고객이 말을 걸 때만 답할 수 있다. 사장님 답·승인 결과처럼 나중에 나온 답은 kakao_out에 담아 두고, 그 고객이 다음에 말을 걸 때 앞에 붙여 전한다.
문서: kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide (스킬 응답 형식, AI 챗봇 콜백 가이드)
"""
import hashlib, json, secrets, threading, traceback, urllib.parse
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, jsonify, current_app
import core, shops
from core import conn, clean

bp=Blueprint('kk',__name__)
SHOP='kakao'               # shop_seen 이름. ext_id 'u:<봇 사용자 키>' = 그 고객의 가장 최근 요청, 'r:<요청 id>:<키>' = 그 요청의 답장 상대
CHANNEL='카카오톡'          # 직접 등록·엑셀 가져오기의 '카카오톡'과 같은 이름 (통계·요금 세기가 같다)
MAX_BODY=64*1024
TEXT_MAX=1000; OUT_MAX=3   # simpleText 한 개 1000자, 말풍선은 한 번에 3개까지
SYNC_WAIT=3.5              # 콜백이 없을 때 AI 답을 기다리는 시간 (카카오 5초 제한 안에서)
CB_HOSTS=('kakao.com','kakaoenterprise.com')  # 콜백 주소는 카카오 주소로만 보낸다 (토큰이 새어도 다른 곳으로 요청을 보내게 하지 않게)
WAIT='잠시만 기다려 주세요. 확인하고 바로 답해 드릴게요.'
HOLD='문의 잘 받았어요. 담당자가 확인하고 답해 드릴게요. 답이 준비되면 이 채팅방에 아무 말이나 보내 주세요. 바로 전해 드릴게요.'
OFF='지금은 이 채널에서 상담을 받지 못하고 있어요. 잠시 후 다시 보내 주세요.'
BUSY='메시지가 너무 많이 와서 잠시 쉬고 있어요. 조금 뒤에 다시 보내 주세요.'
NO_TEXT='(사진이나 첨부를 보냈어요. 카카오톡 채널 관리자센터에서 확인해 주세요)'
BACKGROUND=True  # 시험에서는 False (바로 돈다)

def init():
    with conn() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS kakao_links(company_id INTEGER PRIMARY KEY,tok_hash TEXT NOT NULL UNIQUE,creds TEXT NOT NULL,bot_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ok',note TEXT NOT NULL DEFAULT '',last_at TEXT NOT NULL DEFAULT '',n_inq INTEGER NOT NULL DEFAULT 0,n_sent INTEGER NOT NULL DEFAULT 0,
            created TEXT NOT NULL,FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE)''')
        # 고객에게 전할 말 (다음에 말을 걸 때·콜백으로 전한다). sent: ''=기다림, 'c:<표시>'=전하는 중, 'done'=전함
        db.execute('''CREATE TABLE IF NOT EXISTS kakao_out(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,user_key TEXT NOT NULL,case_id INTEGER NOT NULL DEFAULT 0,
            text TEXT NOT NULL,sent TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,delivered TEXT NOT NULL DEFAULT '',FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE)''')
        db.execute('CREATE INDEX IF NOT EXISTS kakao_out_user ON kakao_out(company_id,user_key,sent)')
init()

def link(db,cid):return db.execute('SELECT * FROM kakao_links WHERE company_id=?',(cid,)).fetchone()
def hashed(tok):return hashlib.sha256(('kakao:'+(tok or '')).encode()).hexdigest()
def token(lk):return ((shops.unseal(lk['creds']) if lk else None) or {}).get('token')
def hook_url(tok):return core.site_url('biz','/hook/kakao/'+tok)
def new_token(db,cid):
    """새 스킬 주소. 예전 주소는 바로 안 듣는다."""
    tok=secrets.token_urlsafe(24)
    db.execute('''INSERT INTO kakao_links(company_id,tok_hash,creds,status,note,created) VALUES(?,?,?,'ok','',?)
        ON CONFLICT(company_id) DO UPDATE SET tok_hash=excluded.tok_hash,creds=excluded.creds,status='ok',note=excluded.note''',(cid,hashed(tok),shops.seal({'token':tok}),core.iso()))
    return tok

# ---------- 고객에게 전할 말 ----------
def queue(db,co_id,key,case_id,text):
    db.execute('INSERT INTO kakao_out(company_id,user_key,case_id,text,created) VALUES(?,?,?,?,?)',(co_id,key,case_id,text,core.iso()))
def pieces(text):
    t=(text or '').strip();return [t[i:i+TEXT_MAX] for i in range(0,len(t),TEXT_MAX)] or []
def claim(db,co_id,key,room=OUT_MAX):
    """기다리던 말을 오래된 것부터 말풍선 room개 안에 들어가는 만큼 맡는다. -> (표시, [말풍선 글])"""
    mark='c:'+secrets.token_hex(6);texts=[]
    for r in db.execute("SELECT id,text FROM kakao_out WHERE company_id=? AND user_key=? AND sent='' ORDER BY id",(co_id,key)).fetchall():
        p=pieces(r['text'])
        if len(texts)+len(p)>room:break  # 남은 건 다음 차례에
        if db.execute("UPDATE kakao_out SET sent=? WHERE id=? AND sent=''",(mark,r['id'])).rowcount:texts+=p
    return mark,texts
def done(db,mark):
    """맡은 말을 전했다: 요청 진행 기록에 남긴다."""
    rows=db.execute('SELECT DISTINCT case_id,company_id FROM kakao_out WHERE sent=?',(mark,)).fetchall()
    db.execute("UPDATE kakao_out SET sent='done',delivered=? WHERE sent=?",(core.iso(),mark))
    for r in rows:
        if r['case_id']:core.add_event(db,r['case_id'],'sys','카카오톡으로 답변을 전했어요')
        db.execute('UPDATE kakao_links SET n_sent=n_sent+1 WHERE company_id=?',(r['company_id'],))
def release(db,mark):db.execute("UPDATE kakao_out SET sent='' WHERE sent=?",(mark,))  # 못 전했다: 다음 차례에 다시
def simple(texts):
    outs=[{'simpleText':{'text':t}} for t in texts[:OUT_MAX] if t] or [{'simpleText':{'text':HOLD}}]
    return {'version':'2.0','template':{'outputs':outs}}

# ---------- 말 받기 ----------
def take(db,co,lk,key,text):
    """고객 말 하나 -> (요청 row, 새 요청인지). 인스타그램 take()와 같은 길."""
    r=db.execute('SELECT case_id FROM shop_seen WHERE company_id=? AND shop=? AND ext_id=? ORDER BY rowid DESC LIMIT 1',(co['id'],SHOP,'u:'+key)).fetchone()
    c=db.execute('SELECT * FROM cases WHERE id=?',(r['case_id'],)).fetchone() if r else None
    db.execute('UPDATE kakao_links SET last_at=? WHERE company_id=?',(core.iso(),co['id']))
    if c and c['status'] not in core.FINAL:  # 같은 고객의 진행 중인 요청에 이어 붙인다
        core.add_event(db,c['id'],'me',text)
        if c['status'] in ('answered','info'):db.execute("UPDATE cases SET status='seen' WHERE id=?",(c['id'],))
        db.execute('UPDATE cases SET updated=? WHERE id=?',(core.iso(),c['id']))
        import chatbot;chatbot.again(db,c,text)  # AI가 맡던 대화면 AI가 이어서 답한다
        return db.execute('SELECT * FROM cases WHERE id=?',(c['id'],)).fetchone(),False
    from werkzeug.security import generate_password_hash
    import datetime as _d, chatbot
    title=clean(' '.join(text.split()),40)
    cat=core.classify(text) or '기타';t=core.iso();due=core.iso(core.now()+_d.timedelta(days=core.REPLY_DAYS))
    cid=db.execute('''INSERT INTO cases(no,company_id,company_name,member,category,title,body,want,order_no,name,phone,email,lookup_hash,consent,status,decision,due,created,updated,product,received_on,channel)
        VALUES(?,?,?,1,?,?,?,?,'','','','',?,1,'forwarded',?,?,?,?,'','',?)''',(core.new_case_no(db),co['id'],co['name'],cat,title,text,core.WANT_OF.get(cat,'기타'),
        generate_password_hash(secrets.token_hex(16)),'ai' if chatbot.auto_on(co) else 'pending',due,t,t,CHANNEL)).lastrowid  # AI 자동 답변을 켰으면 AI가 먼저 본다
    core.add_event(db,cid,'sys','카카오톡 채널 문의를 받았어요')
    if r:db.execute('INSERT OR IGNORE INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)',(co['id'],SHOP,f"r:{r['case_id']}:{key}",r['case_id']))
    db.execute('INSERT OR REPLACE INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)',(co['id'],SHOP,'u:'+key,cid))
    db.execute('INSERT INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)',(co['id'],SHOP,f'r:{cid}:{key}',cid))
    db.execute('UPDATE kakao_links SET n_inq=n_inq+1 WHERE company_id=?',(co['id'],))
    c=db.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
    import workflow;workflow.on_new(db,core.company(db,co['id']),c)
    return db.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone(),True

def ai_turn(case_id):
    """이 요청에 AI 자동 답변 한 차례 (chatbot.auto_reply 그대로). 답은 post_reply를 거쳐 kakao_out에 담긴다."""
    import chatbot
    try:return chatbot.auto_reply(case_id)
    except Exception:  # 실패하면 auto_reply_all처럼 승인 목록으로
        traceback.print_exc()
        with conn() as db:
            c=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
            if c:db.execute("UPDATE cases SET ai_tried=? WHERE id=? AND ai_tried=''",(core.iso(),case_id));chatbot._to_owner(db,c)
        return 'failed'
def cb_ok(url):
    try:u=urllib.parse.urlparse(url or '')
    except ValueError:return False
    h=(u.hostname or '').lower()
    return u.scheme=='https' and any(h==d or h.endswith('.'+d) for d in CB_HOSTS)
def _post(url,data):
    """콜백 주소로 최종 답을 보낸다. -> 받았으면 True"""
    try:s,d=shops.http('POST',url,{'Content-Type':'application/json'},json.dumps(data,ensure_ascii=False).encode())
    except shops.ShopError:return False
    return s<400 and str((d or {}).get('status') or 'SUCCESS').upper()=='SUCCESS'
def answer_later(co_id,key,case_id,cb):
    """AI 답을 만들고 콜백으로 보낸다. 못 보내면 담아 둔 채로 (다음 말에 전한다)."""
    res=ai_turn(case_id)
    with conn() as db:mark,texts=claim(db,co_id,key)
    if not texts:texts=['이어서 보내신 말까지 확인하고 답해 드릴게요.' if res is None else HOLD]
    ok=_post(cb,simple(texts))
    with conn() as db:(done if ok else release)(db,mark)
    if not ok:print(f'카카오 콜백 실패 (요청 {case_id}): 다음에 고객이 말을 걸 때 전해요')

def receive(lk,payload):
    """스킬 요청 하나 -> 카카오에 돌려줄 응답 JSON."""
    ur=payload.get('userRequest') or {};key=clean(str((ur.get('user') or {}).get('id') or ''),120)
    text=clean(str(ur.get('utterance') or ''),core.BIG).strip();cb=str(ur.get('callbackUrl') or '')
    bot=clean(str((payload.get('bot') or {}).get('id') or ''),80)
    with conn() as db:
        co=core.company(db,lk['company_id'])
        if not co or not co['member'] or co['status']!='active' or lk['status']!='ok':return simple([OFF])
        if bot and bot!=lk['bot_id']:db.execute('UPDATE kakao_links SET bot_id=? WHERE company_id=?',(bot,co['id']))
        if not key:return simple([OFF])
        if not text:  # 빈 말(웰컴 블록 등): 요청은 만들지 않고 기다리던 답만 전한다
            mark,texts=claim(db,co['id'],key);done(db,mark)
            return simple(texts or [f"안녕하세요, {core.short(co['name'],30)}이에요. 궁금한 점을 남겨 주시면 바로 답해 드릴게요."])
        c,new=take(db,co,lk,key,text)
    if new:core.notify_company_new(co,c)  # AI가 먼저 보는 문의는 넘겨받을 때 알린다
    import chatbot
    if c['decision']=='ai' and not c['ai_tried'] and chatbot.auto_on(co):
        if cb and cb_ok(cb):  # 콜백: '잠시만요'를 먼저, AI 답은 콜백으로
            run=lambda:answer_later(co['id'],key,c['id'],cb)
            if BACKGROUND:threading.Thread(target=run,daemon=True).start()
            else:run()
            return {'version':'2.0','useCallback':True,'data':{'text':WAIT}}
        th=threading.Thread(target=ai_turn,args=(c['id'],),daemon=True)  # 콜백을 못 쓰면 5초 안에 나온 만큼만
        if BACKGROUND:th.start();th.join(SYNC_WAIT)
        else:th.run()
        with conn() as db:
            mark,texts=claim(db,co['id'],key);done(db,mark)
        return simple(texts or [HOLD])
    with conn() as db:  # 사장님이 맡은 대화: 기다리던 답이 있으면 전하고, 받았다고 알린다
        mark,texts=claim(db,co['id'],key,room=OUT_MAX-1);done(db,mark)
    return simple(texts+['말씀 잘 받았어요. 담당자가 확인하고 답해 드릴게요.' if texts else HOLD])

# ---------- 답변 보내기 (상담 화면·AI) ----------
def post_reply(db,co,c,text):
    """카카오톡으로 보낼 답을 담는다 (고객이 다음에 말을 걸 때·콜백으로 전해진다). 담으면 '', 못 담으면 이유."""
    lk=link(db,co['id'])
    if not lk or lk['status']!='ok':return '카카오톡 채널 연결이 끊겼어요. 서비스 연동에서 다시 이어 주세요.'
    text=(text or '').strip()
    if len(text)<2:return '답변 내용이 너무 짧아요.'
    r=db.execute("SELECT ext_id FROM shop_seen WHERE company_id=? AND shop=? AND case_id=? AND (ext_id LIKE 'r:%' OR ext_id LIKE 'u:%') ORDER BY ext_id LIMIT 1",(co['id'],SHOP,c['id'])).fetchone()
    if not r:return '카카오톡에서 받은 대화가 아니에요.'
    queue(db,co['id'],r['ext_id'].rsplit(':',1)[-1],c['id'],text[:TEXT_MAX*2])
    return ''

# ---------- 화면 ----------
@bp.route('/hook/kakao/<tok>',methods=['POST'])
def hook(tok):
    if (request.content_length or 0)>MAX_BODY:abort(413)
    if len(tok)>80:abort(404)
    with conn() as db:lk=db.execute('SELECT * FROM kakao_links WHERE tok_hash=?',(hashed(tok),)).fetchone()
    if not lk:abort(404)
    if core.throttled('kakao:'+lk['tok_hash'][:16],limit=300,minutes=10):return jsonify(simple([BUSY]))
    raw=request.get_data(cache=False)
    if len(raw)>MAX_BODY:abort(413)
    try:payload=json.loads(raw.decode() or '{}')
    except ValueError:abort(400)
    if not isinstance(payload,dict):abort(400)
    return jsonify(receive(lk,payload))

@bp.route('/connect/kakao',methods=['GET','POST'])
def page():
    if not session.get('co_id'):return redirect(url_for('login'))
    import business
    co=business.me()
    if not co:abort(403)
    if request.method=='POST':
        act=request.form.get('act','new')
        if act=='delete':
            with conn() as db:db.execute('DELETE FROM kakao_links WHERE company_id=?',(co['id'],))
            flash('카카오톡 채널 연결을 끊었어요. 이제 그 스킬 주소로 온 말은 받지 않아요. 이미 받은 문의는 그대로 둬요.','ok')
        elif not co['member']:flash('카카오톡 채널 연결은 실제 고객 문의를 받는 일이라 회사 인증이 끝난 뒤에 할 수 있어요.','error')
        else:
            with conn() as db:had=link(db,co['id']);new_token(db,co['id'])
            flash('새 스킬 주소를 만들었어요. 예전 주소는 이제 안 들어요. 챗봇 관리자센터의 스킬 URL을 새 주소로 바꾸고 다시 배포해 주세요.' if had else '스킬 주소를 만들었어요. 아래 순서대로 챗봇 관리자센터에 넣어 주세요.','ok')
        return redirect(url_for('kk.page'))
    with conn() as db:
        lk=link(db,co['id']);wait=db.execute("SELECT COUNT(*) FROM kakao_out WHERE company_id=? AND sent=''",(co['id'],)).fetchone()[0]
    tok=token(lk)
    return render_template('b_kakao.html',lk=lk,url=hook_url(tok) if tok else '',wait=wait,tab='connect')
