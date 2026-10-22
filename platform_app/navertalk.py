"""네이버 톡톡 문의 받기 (톡톡 챗봇 API V1, github.com/navertalk/chatbot-api).
소보루가 따로 키를 받지 않는다: 사장님이 톡톡 파트너센터 > 개발자도구 > 챗봇API 설정에서 신청하고, 파트너 ID와 보내기 API 인증키(Authorization)를 소보루에 넣는다.
소보루가 보여 주는 주소를 '이벤트 받을 URL'에 넣고, 받을 이벤트로 send·open·leave·echo를 고른다.

  · 고객이 톡톡에 말을 걸면 네이버가 /hook/navertalk/<토큰> 으로 보낸다. 서명이 없어서 회사마다 다른, 추측할 수 없는 토큰으로 확인한다 (카카오와 같다: DB에는 해시로 찾고, 주소와 인증키는 암호화해 둔다).
    같은 고객(user = 사용자 식별값)의 말은 끝나지 않은 요청에 이어 붙고, 없으면 새 요청('네이버 톡톡')이 된다. 인스타그램 DM과 같다.
  · 네이버는 3초(연결)·5초(읽기) 안에 응답을 받아야 해서, 받으면 바로 200을 주고 AI 답은 뒤에서 만든다 (chatbot.auto_reply_later, 인스타그램과 같은 길).
  · 답(AI·사장님·승인 답)은 보내기 API(gw.talk.naver.com/chatbot/v1/event)로 바로 보낸다. 우리가 보낸 말은 echo 이벤트로 돌아오므로 무시한다.
"""
import hashlib, json, re, secrets, traceback
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
import core, shops
from core import conn, clean

bp=Blueprint('nt',__name__)
SHOP='navertalk'           # shop_seen 이름. ext_id 'u:<사용자 식별값>' = 그 고객의 가장 최근 요청, 'r:<요청 id>:<식별값>' = 그 요청의 답장 상대
CHANNEL='네이버 톡톡'
SEND_URL='https://gw.talk.naver.com/chatbot/v1/event'  # 밖으로 나가는 요청은 여기로만
MAX_BODY=64*1024
TEXT_MAX=10000             # textContent 최대 1만 자
PARTNER_RE=re.compile(r'^[A-Za-z0-9_-]{2,40}$')
NO_TEXT='(사진이나 첨부를 보냈어요. 톡톡 파트너센터에서 확인해 주세요)'

def init():
    with conn() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS navertalk_links(company_id INTEGER PRIMARY KEY,tok_hash TEXT NOT NULL UNIQUE,creds TEXT NOT NULL,partner_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ok',note TEXT NOT NULL DEFAULT '',last_at TEXT NOT NULL DEFAULT '',n_inq INTEGER NOT NULL DEFAULT 0,n_sent INTEGER NOT NULL DEFAULT 0,
            created TEXT NOT NULL,FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE)''')
init()

def link(db,cid):return db.execute('SELECT * FROM navertalk_links WHERE company_id=?',(cid,)).fetchone()
def hashed(tok):return hashlib.sha256(('navertalk:'+(tok or '')).encode()).hexdigest()
def creds(lk):return (shops.unseal(lk['creds']) if lk else None) or {}
def hook_url(tok):return core.site_url('biz','/hook/navertalk/'+tok)
def save(db,cid,partner,key,renew=False):
    """파트너 ID·인증키 저장. 주소(토큰)는 처음이거나 renew일 때만 새로 만든다 (키만 바꿔도 '이벤트 받을 URL'은 그대로)."""
    lk=link(db,cid);old=creds(lk)
    tok=old.get('token') if (lk and not renew and old.get('token')) else secrets.token_urlsafe(24)
    key=key or old.get('key') or ''
    db.execute('''INSERT INTO navertalk_links(company_id,tok_hash,creds,partner_id,status,note,created) VALUES(?,?,?,?,'ok','',?)
        ON CONFLICT(company_id) DO UPDATE SET tok_hash=excluded.tok_hash,creds=excluded.creds,partner_id=excluded.partner_id,status='ok',note=''
        ''',(cid,hashed(tok),shops.seal({'token':tok,'key':key}),partner,core.iso()))
    return tok
def fail(db,cid,msg):
    lk=link(db,cid)
    db.execute("UPDATE navertalk_links SET status='error',note=? WHERE company_id=?",(msg,cid))
    if lk and lk['status']=='ok':core.notify_company_link_broken(core.company(db,cid),'네이버 톡톡',msg,'/connect/navertalk',db)  # 처음 끊겼을 때만

# ---------- 말 받기 ----------
def take(db,co,user,text):
    """고객 말 하나 -> 새 요청 row 또는 None(이어 붙임). 인스타그램 take()와 같은 길."""
    r=db.execute('SELECT case_id FROM shop_seen WHERE company_id=? AND shop=? AND ext_id=? ORDER BY rowid DESC LIMIT 1',(co['id'],SHOP,'u:'+user)).fetchone()
    c=db.execute('SELECT * FROM cases WHERE id=?',(r['case_id'],)).fetchone() if r else None
    if c and c['status'] not in core.FINAL:  # 같은 고객의 진행 중인 요청에 이어 붙인다
        core.add_event(db,c['id'],'me',text)
        if c['status'] in ('answered','info'):db.execute("UPDATE cases SET status='seen' WHERE id=?",(c['id'],))
        db.execute('UPDATE cases SET updated=? WHERE id=?',(core.iso(),c['id']))
        import chatbot;chatbot.again(db,c,text)  # AI가 맡던 대화면 AI가 이어서 답한다
        return None
    from werkzeug.security import generate_password_hash
    import datetime as _d, chatbot
    title=clean(' '.join(text.split()),40)
    cat=core.classify(text) or '기타';t=core.iso();due=core.iso(core.now()+_d.timedelta(days=core.REPLY_DAYS))
    cid=db.execute('''INSERT INTO cases(no,company_id,company_name,member,category,title,body,want,order_no,name,phone,email,lookup_hash,consent,status,decision,due,created,updated,product,received_on,channel)
        VALUES(?,?,?,1,?,?,?,?,'','','','',?,1,'forwarded',?,?,?,?,'','',?)''',(core.new_case_no(db),co['id'],co['name'],cat,title,text,core.WANT_OF.get(cat,'기타'),
        generate_password_hash(secrets.token_hex(16)),'ai' if chatbot.auto_on(co) else 'pending',due,t,t,CHANNEL)).lastrowid  # AI 자동 답변을 켰으면 AI가 먼저 본다
    core.add_event(db,cid,'sys','네이버 톡톡 문의를 받았어요')
    if r:db.execute('INSERT OR IGNORE INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)',(co['id'],SHOP,f"r:{r['case_id']}:{user}",r['case_id']))
    db.execute('INSERT OR REPLACE INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)',(co['id'],SHOP,'u:'+user,cid))
    db.execute('INSERT INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)',(co['id'],SHOP,f'r:{cid}:{user}',cid))
    db.execute('UPDATE navertalk_links SET n_inq=n_inq+1 WHERE company_id=?',(co['id'],))
    c=db.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
    import workflow;workflow.on_new(db,core.company(db,co['id']),c)
    return db.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()

def message_text(payload):
    """send 이벤트의 글. 글이 없으면(사진 등) 안내 문구."""
    tc=payload.get('textContent') if isinstance(payload.get('textContent'),dict) else {}
    return clean(str(tc.get('text') or ''),core.BIG).strip() or NO_TEXT
def receive(lk,payload):
    """이벤트 하나 -> 새 요청 수. send만 요청이 되고, echo(우리가 보낸 말)·open·leave·friend 등은 받기만 한다."""
    ev=str(payload.get('event') or '');user=clean(str(payload.get('user') or ''),120)
    new=None
    with conn() as db:
        co=core.company(db,lk['company_id'])
        if not co or not co['member'] or co['status']!='active' or lk['status']!='ok':return 0
        db.execute('UPDATE navertalk_links SET last_at=? WHERE company_id=?',(core.iso(),co['id']))  # 설정이 끝났는지 화면에서 알 수 있게
        if ev!='send' or not user:return 0
        db.execute('SAVEPOINT nt_take')
        try:new=take(db,co,user,message_text(payload));db.execute('RELEASE nt_take')
        except Exception:  # 이상한 메시지 하나가 반쯤 쓴 것은 되돌린다
            traceback.print_exc();db.execute('ROLLBACK TO nt_take');db.execute('RELEASE nt_take');return 0
    if new:core.notify_company_new(co,new)  # AI가 먼저 보는 문의는 넘겨받을 때 알린다
    import chatbot;chatbot.auto_reply_later()  # 새 문의·이어진 대화에 AI가 바로 답한다 (켠 회사만, 뒤에서)
    return 1 if new else 0

# ---------- 답변 보내기 (상담 화면·AI) ----------
def post_reply(db,co,c,text):
    """보내기 API로 고객에게 답한다. 보내면 '', 못 보내면 이유."""
    lk=link(db,co['id']);key=creds(lk).get('key') if lk else None
    if not key:return '네이버 톡톡 연결이 끊겼어요. 서비스 연동에서 다시 이어 주세요.'
    text=(text or '').strip()
    if len(text)<2:return '답변 내용이 너무 짧아요.'
    r=db.execute("SELECT ext_id FROM shop_seen WHERE company_id=? AND shop=? AND case_id=? AND (ext_id LIKE 'r:%' OR ext_id LIKE 'u:%') ORDER BY ext_id LIMIT 1",(co['id'],SHOP,c['id'])).fetchone()
    if not r:return '네이버 톡톡에서 받은 대화가 아니에요.'
    body={'event':'send','user':r['ext_id'].rsplit(':',1)[-1],'textContent':{'text':text[:TEXT_MAX]}}
    try:s,d=shops.http('POST',SEND_URL,{'Authorization':key,'Content-Type':'application/json;charset=UTF-8'},json.dumps(body,ensure_ascii=False).encode())
    except shops.ShopError:return '네이버 톡톡에 연결하지 못했어요. 잠시 후 다시 해 주세요.'
    d=d if isinstance(d,dict) else {}
    if s in (401,403):
        fail(db,co['id'],'보내기 API 인증키가 맞지 않아요. 톡톡 파트너센터에서 인증키를 확인하고 다시 넣어 주세요.')
        return '네이버 톡톡 인증키가 맞지 않아요. 서비스 연동에서 인증키를 다시 넣어 주세요.'
    if s>=400 or d.get('success') is not True:
        why=clean(str(d.get('resultMessage') or d.get('resultCode') or s),100)
        return f'네이버 톡톡이 보내지 않았어요 ({why}).'
    db.execute('UPDATE navertalk_links SET n_sent=n_sent+1 WHERE company_id=?',(co['id'],))
    return ''

# ---------- 화면 ----------
@bp.route('/hook/navertalk/<tok>',methods=['POST'])
def hook(tok):
    if (request.content_length or 0)>MAX_BODY:abort(413)
    if len(tok)>80:abort(404)
    with conn() as db:lk=db.execute('SELECT * FROM navertalk_links WHERE tok_hash=?',(hashed(tok),)).fetchone()
    if not lk:abort(404)
    if core.throttled('navertalk:'+lk['tok_hash'][:16],limit=300,minutes=10):return '',200  # 받기만 하고 넘긴다 (네이버가 다시 보내며 쌓이지 않게)
    raw=request.get_data(cache=False)
    if len(raw)>MAX_BODY:abort(413)
    try:payload=json.loads(raw.decode() or '{}')
    except ValueError:abort(400)
    if not isinstance(payload,dict):abort(400)
    receive(lk,payload)
    return '',200  # 답은 보내기 API로 따로 보낸다

@bp.route('/connect/navertalk',methods=['GET','POST'])
def page():
    if not session.get('co_id'):return redirect(url_for('login'))
    import business
    co=business.me()
    if not co:abort(403)
    if request.method=='POST':
        act=request.form.get('act','save')
        with conn() as db:lk=link(db,co['id'])
        if act=='delete':
            with conn() as db:db.execute('DELETE FROM navertalk_links WHERE company_id=?',(co['id'],))
            flash('네이버 톡톡 연결을 끊었어요. 저장한 인증키도 지웠어요. 이미 받은 문의는 그대로 둬요.','ok')
        elif not co['member']:flash('네이버 톡톡 연결은 실제 고객 문의를 받는 일이라 회사 인증이 끝난 뒤에 할 수 있어요.','error')
        elif act=='renew' and lk:
            with conn() as db:save(db,co['id'],lk['partner_id'],'',renew=True)
            flash('새 주소를 만들었어요. 예전 주소는 이제 안 들어요. 톡톡 파트너센터의 이벤트 받을 URL을 새 주소로 바꿔 주세요.','ok')
        else:
            partner=request.form.get('partner_id','').strip();key=request.form.get('auth_key','').strip()
            if not PARTNER_RE.match(partner):flash('파트너 ID를 확인해 주세요. 톡톡 주소(talk.naver.com/파트너 ID)의 끝부분이에요. 예: wc1234','error')
            elif not lk and not key:flash('보내기 API 인증키(Authorization)를 넣어 주세요.','error')
            elif key and (len(key)>200 or re.search(r'\s',key)):flash('인증키에 빈칸이 들어 있어요. 파트너센터에서 다시 복사해 주세요.','error')
            else:
                with conn() as db:save(db,co['id'],partner,key)
                flash('저장했어요. 이제 아래 주소를 톡톡 파트너센터의 이벤트 받을 URL에 넣어 주세요.' if not lk else '저장했어요. 이벤트 받을 URL은 그대로예요.','ok')
        return redirect(url_for('nt.page'))
    with conn() as db:lk=link(db,co['id'])
    cr=creds(lk);tok=cr.get('token')
    return render_template('b_navertalk.html',lk=lk,url=hook_url(tok) if tok else '',hint=(cr.get('key') or '')[-4:],tab='connect')
