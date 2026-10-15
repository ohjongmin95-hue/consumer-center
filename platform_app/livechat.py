"""실시간 채팅 (Gorgias의 Live chat에 해당).

사장님이 설정에서 켜 두면, 영업시간 안에는 고객센터 화면에 '상담원과 채팅' 버튼이 생긴다.
  · 고객이 채팅으로 접수하면 그 요청이 채팅방이 된다. 고객 화면과 사장님 화면이 몇 초마다 새 말을 가져온다(웹소켓 없이).
  · 고객은 채팅방에서 몇 번이고 말할 수 있다 (일반 요청의 '다시 요청'은 하루 한 번).
  · 서로 화면을 보고 있는지(최근 20초 안에 불러갔는지)를 보여 준다. 고객이 보고 있으면 답변 메일은 보내지 않는다.
영업시간 밖이거나 꺼 두면 버튼이 없고, 이미 열린 채팅방은 일반 요청처럼 이어진다.
"""
import datetime
import core
from core import conn, clean

ONLINE_SECS=20
MAX_LEN=1000

def init():
    with conn() as db:
        cols={r[1] for r in db.execute('PRAGMA table_info(companies)')}
        if 'live_chat' not in cols:db.execute("ALTER TABLE companies ADD COLUMN live_chat INTEGER NOT NULL DEFAULT 0")
        cols={r[1] for r in db.execute('PRAGMA table_info(cases)')}
        if 'live' not in cols:db.execute("ALTER TABLE cases ADD COLUMN live INTEGER NOT NULL DEFAULT 0")
        db.execute('CREATE TABLE IF NOT EXISTS live_seen(case_id INTEGER NOT NULL,side TEXT NOT NULL,at TEXT NOT NULL,PRIMARY KEY(case_id,side))')
init()

def available(co):
    """지금 고객에게 '상담원과 채팅'을 보여 줄지: 켜 두었고, 입점 기업이고, 영업시간 안."""
    import workflow
    return bool(co and co['live_chat'] and core.active_member(co) and workflow.in_hours(co))

def start(db,c):
    db.execute('UPDATE cases SET live=1 WHERE id=?',(c['id'],))
    core.add_event(db,c['id'],'sys','실시간 채팅으로 이어졌어요. 이 화면에서 바로 대화할 수 있어요.')

def is_open(c):return bool(c['live']) and c['status'] not in core.FINAL

def say(db,c,text):
    """고객이 채팅방에 쓴 말. 답을 받은 뒤라도 다시 '확인 중'으로 돌린다. -> 오류 문구 또는 ''"""
    text=clean(text,MAX_LEN).strip()
    if not text:return '내용을 적어 주세요.'
    if not is_open(c):return '끝난 대화예요. 새로 문의해 주세요.'
    core.add_event(db,c['id'],'me',text)
    if c['status']=='answered':db.execute("UPDATE cases SET status='seen' WHERE id=?",(c['id'],))
    db.execute('UPDATE cases SET updated=? WHERE id=?',(core.iso(),c['id']))
    return ''

def ping(db,case_id,side):
    db.execute('INSERT INTO live_seen(case_id,side,at) VALUES(?,?,?) ON CONFLICT(case_id,side) DO UPDATE SET at=excluded.at',(case_id,side,core.iso()))
def online(db,case_id,side):
    r=db.execute('SELECT at FROM live_seen WHERE case_id=? AND side=?',(case_id,side)).fetchone()
    t=core.parse(r['at']) if r else None
    return bool(t and t>=core.now()-datetime.timedelta(seconds=ONLINE_SECS))
def online_cases(db,ids,side='me'):
    """목록 화면: 고객이 지금 채팅방을 보고 있는 요청 id 집합."""
    if not ids:return set()
    since=core.iso(core.now()-datetime.timedelta(seconds=ONLINE_SECS))
    q=','.join('?'*len(ids))
    return {r[0] for r in db.execute(f'SELECT case_id FROM live_seen WHERE side=? AND at>=? AND case_id IN ({q})',(side,since,*ids))}

def since(db,case_id,after):
    """after 다음에 남은 대화 (고객 말과 회사 답변만). -> [{id,who,text,at}]"""
    out=[]
    for e in db.execute("SELECT * FROM events WHERE case_id=? AND id>? AND kind IN ('me','co') ORDER BY id",(case_id,after)).fetchall():
        text=e['reply'] if e['kind']=='co' else e['text']
        if e['kind']=='co' and not e['reply']:continue
        out.append(dict(id=e['id'],who=e['kind'],text=text,at=core.fmt(e['created'])))
    return out
def last_id(db,case_id):
    r=db.execute('SELECT MAX(id) FROM events WHERE case_id=?',(case_id,)).fetchone()
    return r[0] or 0
