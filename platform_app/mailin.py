"""이메일 문의 받기: 사장님 회사 메일함(네이버·지메일·다음·네이버웍스 등)을 이어 두면, 들어온 메일을 요청으로 가져온다.
  · 메일함 주소와 '앱 비밀번호'(메일 서비스에서 따로 만드는 비밀번호)를 넣는다. 비밀번호는 암호화해서 보관한다.
  · 1분마다(quick_sync.py cron, 10분 cron에서도) 새 메일만 읽는다. 메일함은 읽기 전용으로 열어서 '읽음' 표시도 바꾸지 않는다.
  · 같은 메일 대화(답장)는 원래 요청에 이어 붙인다. 이미 끝난 요청이면 새 요청으로 만든다.
  · 광고·자동 발송 메일(수신 거부 목록, 메일러 데몬 등)은 가져오지 않는다.
  · 답변은 사람이 요청 화면에서 '메일로 답변 보내기'를 눌러야 회사 메일함에서 고객에게 나간다. 자동으로 보내지 않는다.
"""
import datetime, email, email.utils, imaplib, re, secrets, smtplib, traceback, html as htmlmod
from email.message import EmailMessage
from email.policy import default as POLICY
import core
from core import conn, clean

SHOP='email'          # shop_seen에 남기는 이름 (가져온 메일과 보낸 답장의 Message-ID)
CHANNEL='이메일'
FIRST_DAYS=3          # 처음 이으면 며칠 전 메일부터 가져올지
MAX_PER_SYNC=50
TIMEOUT=20
PRESETS={
    'naver':dict(name='네이버 메일',imap='imap.naver.com',smtp='smtp.naver.com',help='네이버 메일 → 환경설정 → POP3/IMAP 설정에서 IMAP을 사용함으로 바꾸고, 네이버 보안설정에서 애플리케이션 비밀번호를 만들어요.'),
    'gmail':dict(name='Gmail',imap='imap.gmail.com',smtp='smtp.gmail.com',help='구글 계정 → 보안 → 2단계 인증을 켠 뒤, 앱 비밀번호를 만들어요.'),
    'daum':dict(name='다음·카카오 메일',imap='imap.daum.net',smtp='smtp.daum.net',help='다음 메일 → 환경설정 → IMAP/SMTP에서 사용함으로 바꾸고, 카카오 계정 보안에서 앱 비밀번호를 만들어요.'),
    'works':dict(name='네이버웍스',imap='imap.worksmobile.com',smtp='smtp.worksmobile.com',help='네이버웍스 메일 → 환경설정 → IMAP/SMTP에서 사용함으로 바꾸고, 외부 앱 비밀번호를 만들어요.'),
    'other':dict(name='다른 메일',imap='',smtp='',help='메일 서비스의 IMAP·SMTP 주소를 넣어요. 보통 메일 환경설정에 적혀 있어요.'),
}
SKIP_FROM=re.compile(r'(^|[._-])(no-?reply|do-?not-?reply|mailer-daemon|postmaster|bounce)',re.I)

def init():
    with conn() as db:db.execute('''CREATE TABLE IF NOT EXISTS mail_links(company_id INTEGER PRIMARY KEY,creds TEXT NOT NULL,address TEXT NOT NULL,preset TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'ok',note TEXT NOT NULL DEFAULT '',synced TEXT NOT NULL DEFAULT '',uidvalidity TEXT NOT NULL DEFAULT '',last_uid INTEGER NOT NULL DEFAULT 0,
        n_inq INTEGER NOT NULL DEFAULT 0,n_sent INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL,FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE)''')
init()

class MailError(Exception):
    """사장님께 그대로 보여 줄 우리말 안내."""

def link(db,cid):return db.execute('SELECT * FROM mail_links WHERE company_id=?',(cid,)).fetchone()

# ---------- 메일 서버 (테스트에서 바꿔 끼운다) ----------
def imap_open(creds):
    try:
        m=imaplib.IMAP4_SSL(creds['imap'],int(creds.get('imap_port') or 993),timeout=TIMEOUT)
    except Exception:raise MailError('메일 서버에 연결하지 못했어요. IMAP 주소를 확인해 주세요.')
    try:m.login(creds['user'],creds['password'])
    except imaplib.IMAP4.error:
        try:m.logout()
        except Exception:pass
        raise MailError('로그인하지 못했어요. 메일 주소와 앱 비밀번호, IMAP 사용 설정을 확인해 주세요.')
    return m
def smtp_send(creds,msg):
    port=int(creds.get('smtp_port') or 465)
    try:
        with (smtplib.SMTP_SSL if port==465 else smtplib.SMTP)(creds['smtp'],port,timeout=TIMEOUT) as s:
            if port!=465:s.starttls()
            s.login(creds['user'],creds['password']);s.send_message(msg)
    except smtplib.SMTPAuthenticationError:raise MailError('메일을 보내지 못했어요. 앱 비밀번호와 SMTP 사용 설정을 확인해 주세요.')
    except Exception:raise MailError('메일을 보내지 못했어요. 잠시 후 다시 해 주세요.')

def fetch(creds,uidvalidity,last_uid,since):
    """새 메일 -> (uidvalidity, [(uid, 원문 bytes)]). 메일함은 읽기 전용으로 연다."""
    m=imap_open(creds)
    try:
        typ,_=m.select('INBOX',readonly=True)
        if typ!='OK':raise MailError('받은메일함을 열지 못했어요.')
        uv=(m.untagged_responses.get('UIDVALIDITY') or [b''])[0]
        uv=uv.decode() if isinstance(uv,bytes) else str(uv or '')
        if uv!=uidvalidity or not last_uid:  # 처음이거나 메일함이 새로 만들어졌으면 최근 며칠 것만
            typ,data=m.uid('SEARCH',None,'SINCE',since.strftime('%d-%b-%Y'))
        else:typ,data=m.uid('SEARCH',None,'UID',f'{last_uid+1}:*')
        uids=sorted(int(x) for x in (data[0] or b'').split() if int(x)>(last_uid if uv==uidvalidity else 0))[:MAX_PER_SYNC]
        out=[]
        for u in uids:
            typ,d=m.uid('FETCH',str(u),'(BODY.PEEK[])')
            raw=next((x[1] for x in d or [] if isinstance(x,tuple)),None)
            if raw:out.append((u,raw))
        return uv,out
    finally:
        try:m.logout()
        except Exception:pass

# ---------- 메일 읽기 ----------
QUOTE=re.compile(r'(^-+ ?(original message|원본 메일|원래 메시지) ?-+$|^on .+wrote:$|^.{4,80}(님이 작성|작성했습니다|wrote):?$|^보낸 ?사람 ?:|^from: )',re.I|re.M)
def text_of(msg):
    part=msg.get_body(preferencelist=('plain','html'))
    if part is None:return ''
    try:body=part.get_content()
    except Exception:body=(part.get_payload(decode=True) or b'').decode('utf-8','replace')
    if part.get_content_type()=='text/html':
        body=re.sub(r'(?is)<(script|style).*?</\1>','',body);body=re.sub(r'(?i)<br\s*/?>|</p>|</div>|</tr>','\n',body)
        body=htmlmod.unescape(re.sub(r'<[^>]+>','',body))
    m=QUOTE.search(body)
    if m:body=body[:m.start()]  # 답장 아래에 딸려 온 지난 메일은 뺀다
    body='\n'.join(l for l in body.splitlines() if not l.startswith('>'))
    return re.sub(r'\n{3,}','\n\n',body).strip()
def parse(raw):
    msg=email.message_from_bytes(raw,policy=POLICY)
    name,addr=email.utils.parseaddr(str(msg.get('Reply-To') or msg.get('From') or ''))
    if not name:name=email.utils.parseaddr(str(msg.get('From') or ''))[0]
    refs=' '.join(str(msg.get(h) or '') for h in ('In-Reply-To','References'))
    try:at=email.utils.parsedate_to_datetime(str(msg.get('Date')))
    except Exception:at=None
    return dict(msgid=str(msg.get('Message-ID') or '').strip()[:300],name=name,addr=addr.lower(),subject=re.sub(r'^\s*((re|fw|fwd|답장|전달)\s*:\s*)+','',str(msg.get('Subject') or ''),flags=re.I).strip(),
                body=text_of(msg),refs=re.findall(r'<[^<>\s]+>',refs),at=at,
                bulk=bool(msg.get('List-Unsubscribe') or msg.get('List-Id') or str(msg.get('Precedence') or '').lower() in ('bulk','list','junk')
                          or str(msg.get('Auto-Submitted') or 'no').lower()!='no'))

# ---------- 가져오기 ----------
def _take(db,co,own,m,since=''):
    """메일 하나 -> 새 요청 또는 이어 붙이기. -> 새 요청 row 또는 None. since: 메일함을 이은 때 (그 전에 받은 메일엔 AI가 초안만 쓰고 보내지 않는다)"""
    if not m['msgid'] or not m['addr'] or '@' not in m['addr']:return None
    if m['bulk'] or SKIP_FROM.search(m['addr'].partition('@')[0]) or m['addr']==own:return None
    if db.execute('SELECT 1 FROM shop_seen WHERE company_id=? AND shop=? AND ext_id=?',(co['id'],SHOP,m['msgid'])).fetchone():return None
    body=clean(m['body'],core.BIG) or '(내용 없음)'
    # 이어지는 답장: 우리가 가져왔거나 보낸 메일을 가리키면 그 요청에 붙인다
    if m['refs']:
        q=','.join('?'*len(m['refs']))
        r=db.execute(f'SELECT case_id FROM shop_seen WHERE company_id=? AND shop=? AND ext_id IN ({q}) ORDER BY rowid DESC LIMIT 1',(co['id'],SHOP,*m['refs'])).fetchone()
        c=db.execute('SELECT * FROM cases WHERE id=?',(r['case_id'],)).fetchone() if r else None
        if c and c['status'] not in core.FINAL:
            core.add_event(db,c['id'],'me',body)
            if c['status'] in ('answered','info'):db.execute("UPDATE cases SET status='seen' WHERE id=?",(c['id'],))
            db.execute('UPDATE cases SET updated=? WHERE id=?',(core.iso(),c['id']))
            import chatbot;chatbot.again(db,c,body)  # AI가 맡던 대화면 AI가 이어서 답한다
            db.execute('INSERT INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)',(co['id'],SHOP,m['msgid'],c['id']))
            return None
    from werkzeug.security import generate_password_hash
    import chatbot
    title=clean(m['subject'],60) or clean(re.sub(r'\s+',' ',body),40)
    cat=core.classify(title+' '+body) or '기타';t=core.iso()
    due=core.iso(core.now()+datetime.timedelta(days=core.REPLY_DAYS))
    cid=db.execute('''INSERT INTO cases(no,company_id,company_name,member,category,title,body,want,order_no,name,phone,email,lookup_hash,consent,status,decision,due,created,updated,product,received_on,channel)
        VALUES(?,?,?,1,?,?,?,?,'',?,'',?,?,1,'forwarded',?,?,?,?,'','',?)''',(core.new_case_no(db),co['id'],co['name'],cat,title,body,core.WANT_OF.get(cat,'기타'),
        clean(m['name'],20),clean(m['addr'],120),generate_password_hash(secrets.token_hex(16)),'ai' if chatbot.auto_on(co) else 'pending',due,t,t,CHANNEL)).lastrowid  # AI 자동 답변을 켰으면 AI가 먼저 본다
    if since and m['at'] and core.iso(m['at'].astimezone().replace(tzinfo=None,microsecond=0))<since:  # 잇기 전에 받은 메일: 이미 답했을 수도 있어 AI가 바로 보내지 않는다
        db.execute("UPDATE cases SET ai_hold='1' WHERE id=?",(cid,))
    core.add_event(db,cid,'sys','이메일 문의를 가져왔어요'+(f" ({m['at'].strftime('%m.%d %H:%M')} 받음)" if m['at'] else ''))
    db.execute('INSERT INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)',(co['id'],SHOP,m['msgid'],cid))
    c=db.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
    import workflow;workflow.on_new(db,core.company(db,co['id']),c)  # 자동화 규칙과 자동 배정
    return db.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()

def sync(co):
    """한 기업 메일함에서 새 메일을 가져온다. -> 새 요청 수. 실패하면 연결에 이유를 적고 MailError."""
    import shops
    with conn() as db:lk=link(db,co['id'])
    if not lk:return 0
    creds=shops.unseal(lk['creds'])
    def fail(msg):
        with conn() as db:db.execute("UPDATE mail_links SET status='error',note=? WHERE company_id=?",(msg,co['id']))
        if lk['status']=='ok':core.notify_company_link_broken(co,'이메일 문의',msg,'/connect/email')  # 처음 끊겼을 때만
        raise MailError(msg)
    if not creds:fail('저장한 비밀번호를 읽지 못했어요. 다시 넣어 주세요.')
    now=core.now()
    try:uv,raws=fetch(creds,lk['uidvalidity'],lk['last_uid'],now-datetime.timedelta(days=FIRST_DAYS))
    except MailError as e:fail(str(e))
    except Exception:
        traceback.print_exc();fail('메일함을 읽지 못했어요. 잠시 후 다시 해 주세요.')
    new=[];last=lk['last_uid'] if uv==lk['uidvalidity'] else 0
    with conn() as db:
        for uid,raw in raws:
            try:c=_take(db,co,lk['address'],parse(raw),lk['created'])
            except Exception:traceback.print_exc();c=None  # 이상한 메일 하나 때문에 멈추지 않는다
            if c:new.append(c)
            last=max(last,uid)
        db.execute("UPDATE mail_links SET status='ok',note='',synced=?,uidvalidity=?,last_uid=?,n_inq=n_inq+? WHERE company_id=?",(core.iso(now),uv,last,len(new),co['id']))
    for c in new[:5]:core.notify_company_new(co,c)
    return len(new)
def sync_all():
    n=0
    with conn() as db:rows=db.execute("SELECT c.* FROM mail_links l JOIN companies c ON c.id=l.company_id WHERE c.member=1 AND c.status='active'").fetchall()
    for r in rows:
        try:n+=sync(r)
        except MailError:pass
    return n

# ---------- 저장 ----------
def save(db,co,form):
    """메일함에 실제로 로그인해 보고 맞을 때만 저장한다. -> (안내 문구, 'ok'|'error')"""
    import shops
    preset=form.get('preset') if form.get('preset') in PRESETS else 'other'
    user=re.sub(r'\s','',form.get('user',''))[:120].lower();pw=(form.get('password') or '').strip()[:200]
    p=PRESETS[preset]
    imap=p['imap'] or re.sub(r'[^A-Za-z0-9.-]','',form.get('imap',''))[:100];smtp=p['smtp'] or re.sub(r'[^A-Za-z0-9.-]','',form.get('smtp',''))[:100]
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',user):return '메일 주소를 확인해 주세요','error'
    if not pw:return '앱 비밀번호를 넣어 주세요','error'
    if not imap or not smtp or '.' not in imap or '.' not in smtp:return 'IMAP·SMTP 주소를 넣어 주세요','error'
    creds=dict(user=user,password=pw,imap=imap,smtp=smtp,imap_port=993,smtp_port=465)
    try:
        m=imap_open(creds)
        try:m.logout()
        except Exception:pass
    except MailError as e:return str(e),'error'
    db.execute('''INSERT INTO mail_links(company_id,creds,address,preset,status,note,created) VALUES(?,?,?,?,'ok','',?)
        ON CONFLICT(company_id) DO UPDATE SET creds=excluded.creds,address=excluded.address,preset=excluded.preset,status='ok',note='',
        uidvalidity=CASE WHEN mail_links.address=excluded.address THEN mail_links.uidvalidity ELSE '' END,
        last_uid=CASE WHEN mail_links.address=excluded.address THEN mail_links.last_uid ELSE 0 END''',(co['id'],shops.seal(creds),user,preset,core.iso()))
    return f'{user} 메일함을 이었어요. 새 메일을 가져올게요.','ok'
def remove(db,co):db.execute('DELETE FROM mail_links WHERE company_id=?',(co['id'],))

# ---------- 답변 보내기 (사람이 눌렀을 때만) ----------
def post_reply(db,co,c,text):
    """회사 메일함에서 고객에게 답장을 보낸다. 보내면 '', 못 보내면 이유."""
    import shops
    lk=link(db,co['id']);creds=shops.unseal(lk['creds']) if lk else None
    if not creds:return '메일함 연결이 끊겼어요. 서비스 연동에서 다시 이어 주세요.'
    text=(text or '').strip()
    if len(text)<2:return '답변 내용이 너무 짧아요.'
    if not c['email'] or '@' not in c['email']:return '고객 메일 주소가 없어요.'
    ids=[r['ext_id'] for r in db.execute('SELECT ext_id FROM shop_seen WHERE company_id=? AND shop=? AND case_id=? ORDER BY rowid',(co['id'],SHOP,c['id']))]
    msg=EmailMessage();msg['Subject']='Re: '+(c['title'] or '문의하신 내용');msg['From']=email.utils.formataddr((co['name'],creds['user']));msg['To']=c['email']
    mid=email.utils.make_msgid(domain=creds['user'].partition('@')[2] or None);msg['Message-ID']=mid
    if ids:msg['In-Reply-To']=ids[-1];msg['References']=' '.join(ids[-10:])
    msg.set_content(text)
    try:smtp_send(creds,msg)
    except MailError as e:return str(e)
    db.execute('INSERT OR IGNORE INTO shop_seen(company_id,shop,ext_id,case_id) VALUES(?,?,?,?)',(co['id'],SHOP,mid,c['id']))
    db.execute('UPDATE mail_links SET n_sent=n_sent+1 WHERE company_id=?',(co['id'],))
    return ''
