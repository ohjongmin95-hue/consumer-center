"""택배 배송 추적 (스마트택배).

두 가지 방식을 쓸 수 있다. 서버 설정에 있는 키에 따라 정해진다.
  · 무료 조회 API (SWEETTRACKER_T_KEY): 송장번호로 지금 상태를 물어본다. 등록할 때 한 번, 그 뒤로는 cron(notify_late.py)이 한 시간마다 다시 물어본다.
  · Trace API (SWEETTRACKER_TIER + SWEETTRACKER_KEY): 송장을 등록하면 상태가 바뀔 때마다 우리 주소(/hook/trace/<토큰>)로 알려 준다.
    콜백에는 인증값이 없어서(secret_value는 더 이상 안 씀) 송장마다 서명한 토큰을 주소에 넣고, 토큰이 맞을 때만 받는다.
키가 없으면 등록하지 않고, 송장번호와 택배사 홈페이지 안내만 그대로 쓴다.
"""
import os, json, threading, datetime, urllib.request, urllib.parse
from flask import has_request_context, after_this_request
import core
from core import conn

HOST=os.getenv('SWEETTRACKER_HOST','https://trace-api.sweettracker.net').rstrip('/')
INFO_HOST=os.getenv('SWEETTRACKER_INFO_HOST','https://info.sweettracker.co.kr').rstrip('/')
# 우리 택배사 이름 -> 스마트택배 택배사 코드
CODES={'우체국택배':'01','CJ대한통운':'04','한진택배':'05','로젠택배':'06','롯데택배':'08'}
LEVELS={1:'배송 준비 중',2:'택배사가 상품을 받음',3:'배송 중',4:'배송지 근처 지점 도착',5:'배송 출발',6:'배송 완료'}
KINDS={'ship':'주문 상품','out':'교환 상품','ret':'반품 상품'}
POLL_DAYS=14  # 등록하고 이 기간이 지나도 배송 완료가 안 되면 더 묻지 않는다

def t_key():return os.getenv('SWEETTRACKER_T_KEY','').strip()
def trace_ready():return bool(os.getenv('SWEETTRACKER_TIER') and os.getenv('SWEETTRACKER_KEY'))
def ready():return bool(t_key() or trace_ready())
def fid(case_id,kind):return f'{case_id}-{kind}'
def level_label(n):return LEVELS.get(n,'조회할 수 없음' if n==-99 else '')

def post(path,body):
    req=urllib.request.Request(HOST+path,data=json.dumps(body).encode(),method='POST',headers={'content-type':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as r:return json.loads(r.read().decode() or '{}')
def get_info(code,invoice):
    """무료 조회 API: 송장 하나의 지금 상태 (JSON 그대로)."""
    q=urllib.parse.urlencode({'t_key':t_key(),'t_code':code,'t_invoice':invoice})
    with urllib.request.urlopen(INFO_HOST+'/api/v1/trackingInfo?'+q,timeout=10) as r:return json.loads(r.read().decode() or '{}')

def register(db,case_id,kind,courier,invoice):
    """송장을 기록하고, 키가 있고 지원하는 택배사면 스마트택배에 추적을 맡긴다. 맡겼으면 True."""
    f=fid(case_id,kind)
    db.execute('INSERT INTO tracks(fid,case_id,kind,courier,invoice,level,place,at,note,updated) VALUES(?,?,?,?,?,0,\'\',\'\',\'\',?) '
               'ON CONFLICT(fid) DO UPDATE SET courier=excluded.courier,invoice=excluded.invoice,level=0,place=\'\',at=\'\',note=\'\',updated=excluded.updated',
               (f,case_id,kind,courier,invoice,core.iso()))
    code=CODES.get(courier)
    if not (ready() and code):return False
    if t_key():
        job=lambda:refresh(f)  # 무료 조회: 바로 한 번 물어보고, 그 뒤는 cron이 묻는다
    else:
        body={'num':invoice,'code':code,'fid':f,'callback_url':core.site_url('biz','/hook/trace/'+core.signer('trace').dumps(f)),
              'callback_type':'json','tier':os.getenv('SWEETTRACKER_TIER'),'key':os.getenv('SWEETTRACKER_KEY'),'type':'json'}
        def job():
            try:res=post('/add_invoice',body)
            except Exception:res={}
            if not res.get('success'):note(f,'배송 조회 등록 실패: '+str(res.get('e_message') or '연결 오류')[:100])
    # 송장 기록이 저장(commit)된 뒤에, 화면이 느려지지 않게 뒤에서 보낸다 (테스트에서는 바로)
    run=lambda:threading.Thread(target=job,daemon=True).start() if core.MAIL_ASYNC else job()
    if has_request_context():
        @after_this_request
        def _after(resp):run();return resp
    else:run()
    return True

def note(f,text):
    try:
        with conn() as db:db.execute('UPDATE tracks SET note=? WHERE fid=?',(text,f))
    except Exception:pass

def refresh(f):
    """무료 조회 API로 송장 하나의 상태를 물어 저장한다. 바뀌었으면 True."""
    with conn() as db:t=db.execute('SELECT * FROM tracks WHERE fid=?',(f,)).fetchone()
    if not t or not CODES.get(t['courier']) or not t_key():return False
    try:d=get_info(CODES[t['courier']],t['invoice'])
    except Exception:return False
    if d.get('status') is False or d.get('code') and not d.get('level'):
        # 잘못된 송장·키 등: 스마트택배가 준 안내를 남긴다 (예: 운송장 미등록)
        if not t['level']:note(f,'배송 조회: '+str(d.get('msg') or '조회할 수 없어요')[:100])
        return False
    try:level=int(d.get('level'))
    except (TypeError,ValueError):return False
    last=d.get('lastDetail') or ((d.get('trackingDetails') or [{}])[-1])
    if level and t['note']:note(f,'')
    return update(f,level,str(last.get('where') or ''),str(last.get('timeString') or ''))

def lookup(courier,invoice):
    """고객이 송장번호로 직접 조회 (저장하지 않음). 받는 사람 주소·이름 같은 개인정보는 돌려주지 않는다.
    -> {'ok':True,'level','status','done','place','time','steps':[{time,where,kind}]} 또는 {'ok':False,'error'}"""
    code=CODES.get(courier)
    if not code:return {'ok':False,'error':'이 택배사는 여기서 바로 조회할 수 없어요. 택배사 홈페이지에서 확인해 주세요.'}
    if not t_key():return {'ok':False,'error':'지금은 바로 조회를 쓸 수 없어요. 택배사 홈페이지에서 확인해 주세요.'}
    try:d=get_info(code,invoice)
    except Exception:return {'ok':False,'error':'택배사 조회가 잠시 안 돼요. 조금 뒤에 다시 해 주세요.'}
    try:level=int(d.get('level'))
    except (TypeError,ValueError):level=0
    if d.get('status') is False or not level:
        return {'ok':False,'error':str(d.get('msg') or '조회 결과가 없어요. 택배사와 송장번호를 확인해 주세요.')[:100]}
    steps=[{'time':str(t.get('timeString') or '')[:30],'where':str(t.get('where') or '')[:60],'kind':str(t.get('kind') or '')[:60]}
           for t in (d.get('trackingDetails') or []) if isinstance(t,dict)]
    last=steps[-1] if steps else {'time':'','where':''}
    return {'ok':True,'level':level,'status':level_label(level),'done':level==6 or bool(d.get('complete')),
            'place':last['where'],'time':last['time'],'steps':list(reversed(steps))[:30]}

def poll(today=None):
    """cron: 아직 배송 완료가 안 된 송장을 다시 물어본다 (무료 조회 방식일 때만)."""
    if not t_key():return 0
    cut=core.iso((today or core.now())-datetime.timedelta(days=POLL_DAYS))
    with conn() as db:fs=[r['fid'] for r in db.execute("SELECT fid,updated FROM tracks WHERE level BETWEEN 0 AND 5 AND note='' AND updated>=?",(cut,)).fetchall()]
    n=0
    for f in fs:
        try:n+=bool(refresh(f))
        except Exception:pass
    return n

def tracks(db,case_id):return db.execute('SELECT * FROM tracks WHERE case_id=? ORDER BY kind',(case_id,)).fetchall()
def as_dict(t):
    return dict(kind=t['kind'],label=KINDS.get(t['kind'],''),courier=t['courier'],invoice=t['invoice'],level=t['level'],
                status=level_label(t['level']),place=t['place'],time=t['at'],done=t['level']==6,note=t['note'],live=bool(ready() and CODES.get(t['courier']) and not t['note']),link=core.COURIERS.get(t['courier'],''))

def callback(tok,d):
    """스마트택배가 보낸 배송 상태. 토큰이 맞으면 저장하고, 단계가 바뀌면 기록·알림. -> 처리했으면 True."""
    try:f=core.signer('trace').loads(tok)
    except Exception:return False
    if not isinstance(f,str) or str(d.get('fid',''))!=f:return False
    try:level=int(d.get('level'))
    except (TypeError,ValueError):return False
    return update(f,level,str(d.get('where') or ''),str(d.get('time_trans') or ''),known_only=True)

def update(f,level,place,when,known_only=False):
    """새 배송 상태 저장. 단계가 바뀌면 요청 기록에 남기고, 배송 출발·완료는 고객에게, 반품 도착은 기업에 알린다. 바뀌었으면 True (콜백은 처리했으면 True)."""
    place=core.clean(place,100);when=core.clean(when,30)
    with conn() as db:
        t=db.execute('SELECT * FROM tracks WHERE fid=?',(f,)).fetchone()
        if not t:return False
        if level<t['level'] and level!=-99:return known_only  # 늦게 온 예전 단계는 무시
        db.execute('UPDATE tracks SET level=?,place=?,at=? WHERE fid=?',(level,place,when,f))
        if level==t['level']:return known_only
        db.execute('UPDATE tracks SET updated=? WHERE fid=?',(core.iso(),f))
        c=db.execute('SELECT * FROM cases WHERE id=?',(t['case_id'],)).fetchone()
        if not c:return True
        label=level_label(level);what=KINDS.get(t['kind'],'상품')
        core.add_event(db,c['id'],'sys',f"{what} {label}{' · '+place if place else ''} ({t['courier']} {t['invoice']})")
        if t['kind'] in ('ship','out') and level in (5,6):
            core.notify_consumer(c,f"[{core.CNAME}] {what}이 {'오늘 배송을 출발했어요' if level==5 else '배송 완료됐어요'}",
                                 f"{c['company_name']}에서 보낸 {what}: {label}\n{t['courier']} 송장번호 {t['invoice']}")
        if t['kind']=='ret' and level==6:
            co=core.company(db,c['company_id'])
            if co:core.send_mail(co['notify_email'],f"[{core.BNAME}] 반품 상품이 도착했어요: {c['title']}",
                                 f"택배사 기록상 배송 완료됐어요. 상품을 확인하고 회수 확인을 눌러 주세요.\n{core.site_or_blank('biz','/case/%d'%c['id'])}")
    return True
