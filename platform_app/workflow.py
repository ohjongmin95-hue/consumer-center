"""응대 운영 (Gorgias의 Business hours·SLA·Auto-assign에 해당).

  · 영업시간: 요일과 시간을 정해 둔다. 정하지 않으면 늘 영업 중으로 본다.
  · 영업시간 밖 안내: 켜 두면 영업시간 밖에 소비자 화면으로 들어온 요청에 정해 둔 안내를 바로 남긴다.
    판매처(카페24 게시판 등)에는 올리지 않는다. 사람이 확인하고 올리게 둔다.
  · 첫 답변 목표(SLA): 들어온 때부터 영업시간만 세어 몇 시간 안에 첫 답변을 할지. 목록·요청 화면에 남은 시간을 보여 주고,
    통계에는 최근 30일 달성률을 산식과 함께 보여 준다.
  · 자동 배정: 새 요청을 지금 맡은 진행 중 요청이 가장 적은 사람에게 준다 (보기 전용 제외).
"""
import datetime
import core, team
from core import conn, clean

DAYS='월화수목금토일'
SLA_CHOICES=(0,1,2,4,8,24,48)
AWAY_TEXT='영업시간 외 자동 안내'  # 진행 기록에 남는 이름. 첫 답변으로 세지 않는다
AWAY_DEFAULT='문의 고맙습니다. 지금은 영업시간이 아니에요. {다음영업}에 확인해서 답변드릴게요.'

def init():
    with conn() as db:
        cols={r[1] for r in db.execute('PRAGMA table_info(companies)')}
        for col,kind in (('hours_days',"TEXT NOT NULL DEFAULT ''"),('hours_from',"TEXT NOT NULL DEFAULT '09:00'"),('hours_to',"TEXT NOT NULL DEFAULT '18:00'"),
                         ('away_on',"INTEGER NOT NULL DEFAULT 0"),('away_msg',"TEXT NOT NULL DEFAULT ''"),('sla_hours',"INTEGER NOT NULL DEFAULT 0"),('auto_assign',"INTEGER NOT NULL DEFAULT 0")):
            if col not in cols:db.execute(f'ALTER TABLE companies ADD COLUMN {col} {kind}')
init()

# ---------- 영업시간 ----------
def _hm(s,default):
    try:h,m=(int(x) for x in (s or default).split(':'));return datetime.time(h,m) if 0<=h<24 and 0<=m<60 else None
    except ValueError:return None
def hours(co):
    """(요일 집합 0=월, 시작, 끝) 또는 None(늘 영업)."""
    days={int(d)-1 for d in (co['hours_days'] or '') if d in '1234567'}
    a=_hm(co['hours_from'],'09:00');b=_hm(co['hours_to'],'18:00')
    if not days or not a or not b or a>=b:return None
    return days,a,b
def in_hours(co,t=None):
    h=hours(co);t=t or core.now()
    if not h:return True
    days,a,b=h;return t.weekday() in days and a<=t.time()<b
def next_open(co,t=None):
    """지금 이후 처음 영업을 시작하는 때 (영업 중이면 지금)."""
    h=hours(co);t=t or core.now()
    if not h or in_hours(co,t):return t
    days,a,b=h
    for i in range(8):
        d=(t+datetime.timedelta(days=i)).date()
        start=datetime.datetime.combine(d,a)
        if d.weekday() in days and start>=t.replace(second=0,microsecond=0):return start
    return t
def add_work_hours(co,start,hrs):
    """start부터 영업시간만 세어 hrs시간 뒤. 영업시간을 안 정했으면 그냥 hrs시간 뒤."""
    h=hours(co)
    if not h:return start+datetime.timedelta(hours=hrs)
    days,a,b=h;left=datetime.timedelta(hours=hrs);t=start
    for _ in range(400):
        if t.weekday() in days and t.time()<b:
            s=max(t,datetime.datetime.combine(t.date(),a));e=datetime.datetime.combine(t.date(),b)
            if s+left<=e:return s+left
            left-=e-s
        t=datetime.datetime.combine(t.date()+datetime.timedelta(days=1),datetime.time(0))
    return t
def fmt_open(t):
    now=core.now()
    day='오늘' if t.date()==now.date() else '내일' if t.date()==now.date()+datetime.timedelta(days=1) else f'{t.month}월 {t.day}일({DAYS[t.weekday()]})'
    return f"{day} {t.hour}시"+(f" {t.minute}분" if t.minute else '')
def hours_text(co):
    h=hours(co)
    if not h:return '정하지 않음 (늘 받음)'
    days,a,b=h;ds=''.join(DAYS[i] for i in sorted(days))
    ds={'월화수목금':'평일','월화수목금토일':'매일','토일':'주말'}.get(ds,'·'.join(ds))
    return f"{ds} {a.strftime('%H:%M')}~{b.strftime('%H:%M')}"

# ---------- 첫 답변 목표 ----------
def first_replies(db,cid):
    """{case_id: 첫 답변 시각} (영업시간 외 자동 안내는 빼고)."""
    return dict(db.execute("SELECT e.case_id,MIN(e.created) FROM events e JOIN cases c ON c.id=e.case_id WHERE c.company_id=? AND e.kind='co' AND e.reply!='' AND e.text!=? GROUP BY e.case_id",(cid,AWAY_TEXT)).fetchall())
def due(co,c):
    if not co['sla_hours']:return None
    t=core.parse(c['created']);return add_work_hours(co,t,co['sla_hours']) if t else None
def state(co,c,first):
    """첫 답변 목표: None(목표 없음·끝남) | (문구, 'ok'|'warn'|'bad')."""
    if not co['sla_hours'] or first or c['status'] not in ('forwarded','seen','info') or c['decision'] in ('auto',):return None
    d=due(co,c)
    if not d:return None
    left=(d-core.now()).total_seconds()/3600
    if left<0:return ('첫 답변 목표 지남','bad')
    return (f"첫 답변 {int(left*60)}분 남음" if left<1 else f"첫 답변 {int(left)}시간 남음",'warn' if left<=max(1,co['sla_hours']/4) else 'ok')
def states(db,co,rows):
    fr=first_replies(db,co['id']);out={}
    for r in rows:
        s=state(co,r,fr.get(r['id']))
        if s:out[r['id']]=s
    return out
def report(db,co,rows,days=30):
    """최근 days일에 들어와 목표 시간이 이미 지났거나 답한 요청 중 목표 안에 첫 답변한 비율. -> dict 또는 None"""
    if not co['sla_hours']:return None
    fr=first_replies(db,co['id']);since=core.iso(core.now()-datetime.timedelta(days=days));now=core.now();met=n=0
    for r in rows:
        if r['created']<since or r['decision']=='auto' or r['title'].startswith('[시험 문의]'):continue
        d=due(co,r);f=core.parse(fr[r['id']]) if r['id'] in fr else None
        if not d or (not f and d>now):continue  # 아직 목표 시간 전이고 답도 안 한 요청은 세지 않는다
        n+=1;met+=bool(f and f<=d)
    return dict(n=n,met=met,pct=round(met/n*100) if n else None,days=days,hours=co['sla_hours'])

# ---------- 새 요청이 들어왔을 때 ----------
def pick(db,co):
    """지금 맡은 진행 중 요청이 가장 적은 사람 (같으면 직원 먼저, 그다음 목록 순)."""
    ppl=team.people(db,co)
    if len(ppl)>1:ppl=[p for p in ppl if p[0]!='owner']  # 직원이 있으면 직원에게 나눈다
    load=dict(db.execute("SELECT assignee,COUNT(*) FROM cases WHERE company_id=? AND assignee!='' AND status IN ('forwarded','seen','info') GROUP BY assignee",(co['id'],)).fetchall())
    return min(ppl,key=lambda p:load.get(p[0],0))[0] if ppl else ''
def on_new(db,co,c,from_consumer=False):
    """요청이 들어온 직후: 자동화 규칙, 자동 배정, 영업시간 밖이면 안내. 자동 처리로 이미 답한 요청은 건드리지 않는다. -> 안내를 남겼으면 True"""
    c=db.execute('SELECT * FROM cases WHERE id=?',(c['id'],)).fetchone()
    if c['decision']=='auto' or c['status'] not in ('forwarded','seen'):return False
    import automations
    if automations.run(db,co,c):c=db.execute('SELECT * FROM cases WHERE id=?',(c['id'],)).fetchone()  # 사장님이 만든 규칙이 먼저. 담당자를 정했으면 자동 배정은 건너뛴다
    if co['auto_assign'] and not c['assignee']:
        key=pick(db,co)
        if key:team.assign(db,co,c,key)
    if from_consumer and co['away_on'] and not in_hours(co):
        msg=(co['away_msg'] or AWAY_DEFAULT).replace('{다음영업}',fmt_open(next_open(co)))
        core.add_event(db,c['id'],'co',AWAY_TEXT,msg);return True
    return False

def save(db,co,f):
    days=''.join(d for d in '1234567' if f.get('day'+d))
    a=f.get('hours_from','09:00');b=f.get('hours_to','18:00')
    if days and (not _hm(a,'') or not _hm(b,'') or _hm(a,'')>=_hm(b,'')):return '영업 시작 시간이 끝 시간보다 빨라야 해요','error'
    sla=int(f.get('sla_hours','0')) if str(f.get('sla_hours','0')).isdigit() and int(f.get('sla_hours','0')) in SLA_CHOICES else 0
    on=lambda k:str(f.get(k)) in ('1','True','true')
    db.execute('UPDATE companies SET hours_days=?,hours_from=?,hours_to=?,away_on=?,away_msg=?,sla_hours=?,auto_assign=? WHERE id=?',
               (days,a[:5],b[:5],int(on('away_on')),clean(f.get('away_msg'),300),sla,int(on('auto_assign')),co['id']))
    return '응대 운영 설정을 저장했어요','ok'
