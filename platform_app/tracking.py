"""택배 배송 추적 (스마트택배 Trace API).

송장을 등록(add_invoice)하면 스마트택배가 배송 상태가 바뀔 때마다 우리 주소(/hook/trace/<토큰>)로 알려 준다.
SWEETTRACKER_TIER, SWEETTRACKER_KEY가 없으면 등록하지 않고, 송장번호와 택배사 홈페이지 안내만 그대로 쓴다.
콜백에는 인증값이 없어서(secret_value는 더 이상 안 씀) 송장마다 서명한 토큰을 주소에 넣고, 토큰이 맞을 때만 받는다.
"""
import os, json, threading, urllib.request
import core
from core import conn

HOST=os.getenv('SWEETTRACKER_HOST','https://trace-api.sweettracker.net').rstrip('/')
# 우리 택배사 이름 -> 스마트택배 택배사 코드
CODES={'우체국택배':'01','CJ대한통운':'04','한진택배':'05','로젠택배':'06','롯데택배':'08'}
LEVELS={1:'배송 준비 중',2:'택배사가 상품을 받음',3:'배송 중',4:'배송지 근처 지점 도착',5:'배송 출발',6:'배송 완료'}
KINDS={'ship':'주문 상품','out':'교환 상품','ret':'반품 상품'}

def ready():return bool(os.getenv('SWEETTRACKER_TIER') and os.getenv('SWEETTRACKER_KEY'))
def fid(case_id,kind):return f'{case_id}-{kind}'
def level_label(n):return LEVELS.get(n,'조회할 수 없음' if n==-99 else '')

def post(path,body):
    req=urllib.request.Request(HOST+path,data=json.dumps(body).encode(),method='POST',headers={'content-type':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as r:return json.loads(r.read().decode() or '{}')

def register(db,case_id,kind,courier,invoice):
    """송장을 기록하고, 키가 있고 지원하는 택배사면 스마트택배에 추적을 맡긴다. 맡겼으면 True."""
    f=fid(case_id,kind)
    db.execute('INSERT INTO tracks(fid,case_id,kind,courier,invoice,level,place,at,note,updated) VALUES(?,?,?,?,?,0,\'\',\'\',\'\',?) '
               'ON CONFLICT(fid) DO UPDATE SET courier=excluded.courier,invoice=excluded.invoice,level=0,place=\'\',at=\'\',note=\'\',updated=excluded.updated',
               (f,case_id,kind,courier,invoice,core.iso()))
    code=CODES.get(courier)
    if not (ready() and code):return False
    body={'num':invoice,'code':code,'fid':f,'callback_url':core.site_url('biz','/hook/trace/'+core.signer('trace').dumps(f)),
          'callback_type':'json','tier':os.getenv('SWEETTRACKER_TIER'),'key':os.getenv('SWEETTRACKER_KEY'),'type':'json'}
    def job():
        try:res=post('/add_invoice',body)
        except Exception:res={}
        if not res.get('success'):
            try:
                with conn() as db2:db2.execute('UPDATE tracks SET note=? WHERE fid=?',('배송 조회 등록 실패: '+str(res.get('e_message') or '연결 오류')[:100],f))
            except Exception:pass
    # 화면이 느려지지 않게 뒤에서 보낸다 (테스트에서는 바로)
    if core.MAIL_ASYNC:threading.Thread(target=job,daemon=True).start()
    else:job()
    return True

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
    place=core.clean(str(d.get('where') or ''),100);when=core.clean(str(d.get('time_trans') or ''),30)
    with conn() as db:
        t=db.execute('SELECT * FROM tracks WHERE fid=?',(f,)).fetchone()
        if not t:return False
        if level<t['level'] and level!=-99:return True  # 늦게 온 예전 단계는 무시
        db.execute('UPDATE tracks SET level=?,place=?,at=?,updated=? WHERE fid=?',(level,place,when,core.iso(),f))
        if level==t['level']:return True
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
                                 f"택배사 기록상 배송 완료됐어요. 상품을 확인하고 회수 확인을 눌러 주세요.\n{core.site_url('biz','/case/%d'%c['id'])}")
    return True
