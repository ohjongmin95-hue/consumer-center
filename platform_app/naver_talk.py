"""네이버 톡톡 문의 받기 (톡톡 파트너센터 '챗봇 API').
사장님이 톡톡 파트너센터 → 개발자도구 → 챗봇 API 설정에 소보루가 준 Webhook 주소를 넣고, '보내기 API' 인증키를 소보루에 넣는다.

  · 고객이 톡톡에 말을 걸면 네이버가 /hook/naver/<토큰> 으로 보낸다 (event='send'). 서명이 없어서 회사마다 다른, 추측할 수 없는 토큰으로 확인한다 (카카오와 같다).
    같은 고객(user = 톡톡 사용자 식별값)의 말은 끝나지 않은 요청에 이어 붙고, 없으면 새 요청('네이버 톡톡')이 된다.
  · 답(사장님·SODA)은 보내기 API(gw.talk.naver.com/chatbot/v1/event)로 바로 보낸다. 카카오처럼 고객이 다시 말을 걸 때까지 기다리지 않는다.
문서: github.com/navertalk/chatbot-api (Webhook 이벤트, 보내기 API)
"""
import hashlib, json, secrets, threading, traceback
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, jsonify
import core, shops
from core import conn, clean

bp=Blueprint('nt',__name__)
SHOP='naver_talk'
CHANNEL='네이버 톡톡'
SEND_URL='https://gw.talk.naver.com/chatbot/v1/event'
MAX_BODY=64*1024
TEXT_MAX=1000
NO_TEXT='(사진이나 첨부를 보냈어요. 톡톡 파트너센터에서 확인해 주세요)'
BACKGROUND=True  # 시험에서는 False

def init():
    with conn() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS naver_talk_links(company_id INTEGER PRIMARY KEY,tok_hash TEXT NOT NULL UNIQUE,creds TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ok',note TEXT NOT NULL DEFAULT '',last_at TEXT NOT NULL DEFAULT '',n_inq INTEGER NOT NULL DEFAULT 0,n_sent INTEGER NOT NULL DEFAULT 0,
            created TEXT NOT NULL,FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE)''')
init()

def link(db,cid):return db.execute('SELECT * FROM naver_talk_links WHERE company_id=?',(cid,)).fetchone()
def hashed(tok):return hashlib.sha256(('naver_talk:'+(tok or '')).encode()).hexdigest()
def creds(lk):return (shops.unseal(lk['creds']) if lk else None) or {}
def hook_url(tok):return core.site_url('biz','/hook/naver/'+tok)
def new_token(db,cid):
    """새 Webhook 주소. 예전 주소는 바로 안 듣는다. 넣어 둔 인증키는 그대로 둔다."""
    tok=secrets.token_urlsafe(24);old=creds(link(db,cid))
    db.execute('''INSERT INTO naver_talk_links(company_id,tok_hash,creds,status,note,created) VALUES(?,?,?,'ok','',?)
        ON CONFLICT(company_id) DO UPDATE SET tok_hash=excluded.tok_hash,creds=excluded.creds,status='ok',note=excluded.note''',(cid,hashed(tok),shops.seal({'token':tok,'auth':old.get('auth','')}),core.iso()))
    return tok
def set_auth(db,cid,auth):
    lk=link(db,cid);c=creds(lk);c['auth']=auth.strip()
    db.execute("UPDATE naver_talk_links SET creds=?,status='ok',note='' WHERE company_id=?",(shops.seal(c),cid))

# ---------- 보내기 ----------
def send(auth,user,text):
    """톡톡 보내기 API. -> 보냈으면 '', 못 보냈으면 이유."""
    body={'event':'send','user':user,'textContent':{'text':text[:TEXT_MAX]}}
    try:s,d=shops.http('POST',SEND_URL,{'Content-Type':'application/json;charset=UTF-8','Authorization':auth},json.dumps(body,ensure_ascii=False).encode())
    except shops.ShopError:return '네이버 톡톡에 연결하지 못했어요. 잠시 후 다시 해 주세요.'
    if s in (401,403) or str((d or {}).get('resultCode'))=='02':return '보내기 API 인증키가 맞지 않아요. 서비스 연동 → 네이버 톡톡에서 다시 넣어 주세요.'
    if s>=400 or (d and d.get('success') is False):return '네이버 톡톡이 답을 받지 않았어요 (%s). 잠시 후 다시 해 주세요.'%((d or {}).get('resultMessage') or s)
    return ''
def pieces(text):
    text=(text or '').strip()
    return [text[i:i+TEXT_MAX] for i in range(0,len(text),TEXT_MAX)][:3]

def post_reply(db,co,c,text):
    """상담 화면·SODA의 답을 그 고객의 톡톡으로 보낸다. 보냈으면 '', 못 보냈으면 이유."""
    lk=link(db,co['id']);cr=creds(lk)
    if not lk or lk['status']!='ok':return '네이버 톡톡 연결이 끊겼어요. 서비스 연동에서 다시 이어 주세요.'
    if not cr.get('auth'):return '보내기 API 인증키가 없어요. 서비스 연동 → 네이버 톡톡에서 넣어 주세요.'
    text=(text or '').strip()
    if len(text)<2:return '답변 내용이 너무 짧아요.'
    r=db.execute("SELECT ext_id FROM shop_seen WHERE company_id=? AND shop=? AND case_id=? AND ext_id LIKE 'r:%' LIMIT 1",(co['id'],SHOP,c['id'])).fetchone()
    if not r:return '네이버 톡톡에서 받은 대화가 아니에요.'
    user=r['ext_id'].split(':',2)[2]
    for t in pieces(text):
        e=send(cr['auth'],user,t)
        if e:return e
    db.execute('UPDATE naver_talk_links SET n_sent=n_sent+1 WHERE company_id=?',(co['id'],))
    return ''

# ---------- 받기 ----------
def take(db,co,user,text):
    """고객 말 하나 -> (요청 row, 새 요청인지). 카카오 take()와 같은 길."""
    r=db.execute('SELECT case_id FROM shop_seen WHERE company_id=? AND shop=? AND ext_id=? ORDER BY rowid DESC LIMIT 1',(co['id'],SHOP,'u:'+user)).fetchone()
    c=db.execute('SELECT * FROM cases WHERE id=?',(r['case_id'],)).fetchone() if r else None
    db.execute('UPDATE naver_talk_links SET last_at=? WHERE company_id=?',(core.iso(),co['id']))
    if c and c['status'] not in core.FINAL:
        core.add_event(db,c['id'],'me',text)
        if c['status'] in ('answered','info'):db.execute("UPDATE cases SET status='seen' WHERE id=?",(c['id'],))
        db.execute('UPDATE cases SET updated=? WHERE id=?',(core.iso(),c['id']))
        import chatbot;chatbot.again(db,c,text)
        return db.execute('SELECT * FROM cases WHERE id=?',(c['id'],)).fetchone(),False
    from werkzeug.security import generate_password_hash
    import datetime as _d, chatbot
    title=clean(' '.join(text.split()),40)
    cat=core.classify(text) or '기타';t=core.iso();due=core.iso(core.now()+_d.timedelta(days=core.REPLY_DAYS))
    cid=db.execute('''INSERT INTO cases(no,company_id,company_name,member,category,title,body,want,order_no,name,phone,email,lookup_hash,consent,status,decision,due,created,updated,product,received_on,channel)
        VALUES(?,?,?,1,?,?,?,?,'','','','',?,1,'forwarded',?,?,?,?,'','',?)''',(core.new_case_no(db),co['id'],co['name'],cat,title,text,core.WANT_OF.get(cat,'기타'),
        generate_password_hash(secrets.token_hex(16)),'ai' if chatbot.auto_on(co) else 'pending',due,t,t,CHANNEL)).lastrowid
    core.add_event(db,cid,'sys','네이버 톡톡 문의를 받았어요')
    db.execute('INSERT OR REPLACE INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)',(co['id'],SHOP,'u:'+user,cid))
    db.execute('INSERT INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)',(co['id'],SHOP,f'r:{cid}:{user}',cid))
    db.execute('UPDATE naver_talk_links SET n_inq=n_inq+1 WHERE company_id=?',(co['id'],))
    c=db.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
    import workflow;workflow.on_new(db,core.company(db,co['id']),c)
    return db.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone(),True

def ai_turn(case_id):
    import chatbot
    try:return chatbot.auto_reply(case_id)  # 답은 core.deliver_reply -> shops.post_reply -> post_reply 로 톡톡에 나간다
    except Exception:
        traceback.print_exc()
        with conn() as db:
            c=db.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
            if c:db.execute("UPDATE cases SET ai_tried=? WHERE id=? AND ai_tried=''",(core.iso(),case_id));chatbot._to_owner(db,c)

def receive(lk,payload):
    """Webhook 이벤트 하나. 고객 말(send)만 상담이 되고, 나머지(open·leave·friend·echo)는 받기만 한다."""
    if payload.get('event')!='send':return
    user=clean(str(payload.get('user') or ''),120)
    tc=payload.get('textContent') or {}
    text=clean(str(tc.get('text') or ''),core.BIG).strip() or (NO_TEXT if payload.get('imageContent') or payload.get('compositeContent') else '')
    if not user or not text:return
    with conn() as db:
        co=core.company(db,lk['company_id'])
        if not co or not co['member'] or co['status']!='active' or lk['status']!='ok':return
        c,new=take(db,co,user,text)
    if new:core.notify_company_new(co,c)
    import chatbot
    if c['decision']=='ai' and not c['ai_tried'] and chatbot.auto_on(co):
        if BACKGROUND:threading.Thread(target=ai_turn,args=(c['id'],),daemon=True).start()
        else:ai_turn(c['id'])

# ---------- 화면 ----------
@bp.route('/hook/naver/<tok>',methods=['POST'])
def hook(tok):
    if (request.content_length or 0)>MAX_BODY:abort(413)
    if len(tok)>80:abort(404)
    with conn() as db:lk=db.execute('SELECT * FROM naver_talk_links WHERE tok_hash=?',(hashed(tok),)).fetchone()
    if not lk:abort(404)
    if core.throttled('naver_talk:'+lk['tok_hash'][:16],limit=300,minutes=10):return jsonify(success=True)
    raw=request.get_data(cache=False)
    if len(raw)>MAX_BODY:abort(413)
    try:payload=json.loads(raw.decode() or '{}')
    except ValueError:abort(400)
    if isinstance(payload,dict):receive(lk,payload)
    return jsonify(success=True)  # 네이버에는 바로 200을 돌려준다 (답은 보내기 API로 따로)

@bp.route('/connect/naver-talk',methods=['GET','POST'])
def page():
    if not session.get('co_id'):return redirect(url_for('login'))
    import business
    co=business.me()
    if not co:abort(403)
    if request.method=='POST':
        act=request.form.get('act','new')
        if act=='delete':
            with conn() as db:db.execute('DELETE FROM naver_talk_links WHERE company_id=?',(co['id'],))
            flash('네이버 톡톡 연결을 끊었어요. 이미 받은 문의는 그대로 둬요.','ok')
        elif not co['member']:flash('네이버 톡톡 연결은 실제 고객 문의를 받는 일이라 회사 인증이 끝난 뒤에 할 수 있어요.','error')
        elif act=='auth':
            auth=clean(request.form.get('auth',''),200).strip()
            if len(auth)<10:flash('보내기 API 인증키를 확인해 주세요. 톡톡 파트너센터 → 개발자도구 → 챗봇 API 설정에 있어요.','error')
            else:
                with conn() as db:
                    if not link(db,co['id']):new_token(db,co['id'])
                    set_auth(db,co['id'],auth)
                flash('인증키를 넣었어요. 이제 상담 화면에서 쓴 답이 톡톡으로 바로 나가요.','ok')
        else:
            with conn() as db:had=link(db,co['id']);new_token(db,co['id'])
            flash('새 Webhook 주소를 만들었어요. 예전 주소는 이제 안 들어요. 톡톡 파트너센터에 새 주소를 넣어 주세요.' if had else 'Webhook 주소를 만들었어요. 아래 순서대로 톡톡 파트너센터에 넣어 주세요.','ok')
        return redirect(url_for('nt.page'))
    with conn() as db:lk=link(db,co['id'])
    cr=creds(lk)
    return render_template('b_naver_talk.html',lk=lk,url=hook_url(cr['token']) if cr.get('token') else '',has_auth=bool(cr.get('auth')),tab='connect')
