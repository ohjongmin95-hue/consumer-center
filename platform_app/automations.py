"""자동화 규칙 (Gorgias의 Rules에 해당).

새 요청이 들어오면 사장님이 만든 규칙을 위에서부터 차례로 보고, 조건이 맞으면 정한 일을 한다.
  · 조건: 제목·내용에 들어간 말, 유형, 들어온 곳, 주문번호가 있는지, 영업시간 밖인지
  · 할 일: 태그 붙이기, 우선순위 바꾸기, 담당자 정하기, 내부 메모 남기기
고객에게 보이는 일(답변·알림 보내기)은 하지 않는다. 답은 사람이 확인하고 보낸다.
담당자는 먼저 맞은 규칙이 정한다. 규칙이 담당자를 정하지 않았으면 그다음에 자동 배정이 나눈다.
"""
import json, datetime
import core, inbox, team
from core import conn, clean

MAX_RULES=30;MAX_CONDS=5;MAX_ACTS=5
FIELDS={'text':'제목·내용에','category':'유형이','channel':'들어온 곳이','order':'주문번호가','hours':'들어온 때가'}
ACTS={'tag':'태그 붙이기','prio':'우선순위 바꾸기','assign':'담당자 정하기','note':'내부 메모 남기기'}
SOBORU='SOBORU CS'
def channels():return [SOBORU,'스마트스토어','쿠팡','카페24']+[c for c in core.CHANNELS if c not in ('기타',)]+['기타']

def init():
    with conn() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS automations(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,name TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,
          match TEXT NOT NULL DEFAULT 'all',conds TEXT NOT NULL DEFAULT '[]',acts TEXT NOT NULL DEFAULT '[]',pos INTEGER NOT NULL DEFAULT 0,
          runs INTEGER NOT NULL DEFAULT 0,last_run TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE)''')
init()

def _load(r):
    d=dict(r)
    try:d['conds']=json.loads(r['conds'] or '[]');d['acts']=json.loads(r['acts'] or '[]')
    except ValueError:d['conds']=[];d['acts']=[]
    return d
def rules(db,cid):return [_load(r) for r in db.execute('SELECT * FROM automations WHERE company_id=? ORDER BY pos,id',(cid,)).fetchall()]
def get(db,cid,rid):
    r=db.execute('SELECT * FROM automations WHERE id=? AND company_id=?',(rid,cid)).fetchone()
    return _load(r) if r else None

# ---------- 조건 ----------
def channel_of(c):
    ch=c['channel'] or ''
    return SOBORU if ch in ('','한큐') else ch
def words(v):return [w.strip().lower() for w in str(v).split(',') if w.strip()]
def cond_ok(co,c,cd):
    f,op,v=cd.get('f'),cd.get('op','is'),cd.get('v','')
    if f=='text':
        txt=((c['title'] or '')+' '+(c['body'] or '')).lower();hit=any(w in txt for w in words(v))
        return hit if op=='has' else not hit
    if f=='category':return (c['category']==v) if op=='is' else (c['category']!=v)
    if f=='channel':return (channel_of(c)==v) if op=='is' else (channel_of(c)!=v)
    if f=='order':return bool((c['order_no'] or '').strip()) if op=='has' else not (c['order_no'] or '').strip()
    if f=='hours':
        import workflow
        t=core.parse(c['created']) or core.now();inn=workflow.in_hours(co,t)
        return (not inn) if op=='out' else inn
    return False
def matches(co,c,r):
    if not r['conds']:return False
    oks=[cond_ok(co,c,cd) for cd in r['conds']]
    return any(oks) if r['match']=='any' else all(oks)

# ---------- 실행 ----------
def run(db,co,c):
    """새 요청에 켜 둔 규칙을 위에서부터 적용한다. -> 맞은 규칙 이름 목록"""
    hit=[];assigned=False;people=dict(team.people(db,co))
    for r in rules(db,co['id']):
        if not r['enabled'] or not matches(co,c,r):continue
        for a in r['acts']:
            k,v=a.get('a'),a.get('v','')
            if k=='tag':
                for w in [x.strip() for x in str(v).split(',') if x.strip()]:inbox.add_tag(db,co,c,w)
            elif k=='prio' and v in inbox.PRIO:inbox.set_priority(db,co,c,v)
            elif k=='assign' and not assigned and (v in people or v==''):
                team.assign(db,co,c,v);assigned=True
            elif k=='note' and v:inbox.note(db,co,c,clean(v,300))
            c=db.execute('SELECT * FROM cases WHERE id=?',(c['id'],)).fetchone()
        inbox.note(db,co,c,f"자동화 규칙 '{r['name']}'을(를) 적용했어요")
        db.execute('UPDATE automations SET runs=runs+1,last_run=? WHERE id=?',(core.iso(),r['id']))
        hit.append(r['name'])
    return hit

def preview(db,co,r,days=30):
    """최근 days일 요청 중 이 조건에 맞았을 건수 (실제로 바꾸지 않음)."""
    since=core.iso(core.now()-datetime.timedelta(days=days))
    rows=db.execute("SELECT * FROM cases WHERE company_id=? AND created>=? AND title NOT LIKE '[시험 문의]%'",(co['id'],since)).fetchall()
    return sum(1 for c in rows if matches(co,c,r)),len(rows)

# ---------- 저장 ----------
def parse(f,people):
    """폼 -> (규칙 dict, 오류 문구). 폼 칸: name, match, cf_N/cop_N/cv_N, af_N/av_N"""
    name=clean(f.get('name'),30).strip()
    conds=[];acts=[]
    for i in range(MAX_CONDS):
        fld=f.get(f'cf_{i}','');op=f.get(f'cop_{i}','');v=clean(f.get(f'cv_{i}'),200).strip()
        if fld not in FIELDS:continue
        if fld=='text':
            if op not in ('has','not'):op='has'
            if not words(v):continue
        elif fld=='category':
            if v not in core.CATS:continue
            op='not' if op=='not' else 'is'
        elif fld=='channel':
            if v not in channels():continue
            op='not' if op=='not' else 'is'
        elif fld=='order':op='none' if op=='none' else 'has';v=''
        elif fld=='hours':op='in' if op=='in' else 'out';v=''
        conds.append(dict(f=fld,op=op,v=v))
    for i in range(MAX_ACTS):
        k=f.get(f'af_{i}','');v=clean(f.get(f'av_{i}'),300).strip()
        if k=='tag' and v:acts.append(dict(a=k,v=','.join(w for w in (x.strip().lstrip('#')[:20] for x in v.split(',')) if w)))
        elif k=='prio' and v in inbox.PRIO:acts.append(dict(a=k,v=v))
        elif k=='assign' and v in people:acts.append(dict(a=k,v=v))
        elif k=='note' and v:acts.append(dict(a=k,v=v))
    r=dict(name=name,match='any' if f.get('match')=='any' else 'all',conds=conds,acts=acts)
    if not name:return r,'규칙 이름을 적어 주세요'
    if not conds:return r,'조건을 하나 이상 정해 주세요'
    if not acts:return r,'할 일을 하나 이상 정해 주세요'
    return r,''
def save(db,cid,r,rid=None):
    if rid:
        db.execute('UPDATE automations SET name=?,match=?,conds=?,acts=? WHERE id=? AND company_id=?',(r['name'],r['match'],json.dumps(r['conds'],ensure_ascii=False),json.dumps(r['acts'],ensure_ascii=False),rid,cid))
        return rid
    n=db.execute('SELECT COUNT(*),COALESCE(MAX(pos),0) FROM automations WHERE company_id=?',(cid,)).fetchone()
    if n[0]>=MAX_RULES:return None
    return db.execute('INSERT INTO automations(company_id,name,match,conds,acts,pos,created) VALUES(?,?,?,?,?,?,?)',
                      (cid,r['name'],r['match'],json.dumps(r['conds'],ensure_ascii=False),json.dumps(r['acts'],ensure_ascii=False),n[1]+1,core.iso())).lastrowid
def toggle(db,cid,rid):db.execute('UPDATE automations SET enabled=1-enabled WHERE id=? AND company_id=?',(rid,cid))
def delete(db,cid,rid):db.execute('DELETE FROM automations WHERE id=? AND company_id=?',(rid,cid))
def move(db,cid,rid,up):
    rs=rules(db,cid);ids=[r['id'] for r in rs]
    if rid not in ids:return
    i=ids.index(rid);j=i-1 if up else i+1
    if 0<=j<len(ids):ids[i],ids[j]=ids[j],ids[i]
    for p,x in enumerate(ids):db.execute('UPDATE automations SET pos=? WHERE id=?',(p,x))

# ---------- 화면용 문장 ----------
def say_cond(cd):
    f,op,v=cd['f'],cd['op'],cd['v']
    if f=='text':
        v=', '.join(x.strip() for x in v.split(',') if x.strip())
        return f"제목·내용에 '{v}'"+(' 중 하나가 있음' if ',' in v else '이(가) 있음') if op=='has' else f"제목·내용에 '{v}'이(가) 없음"
    if f=='category':return f"유형이 {v}"+('' if op=='is' else ' 아님')
    if f=='channel':return f"들어온 곳이 {v}"+('' if op=='is' else ' 아님')
    if f=='order':return '주문번호 있음' if op=='has' else '주문번호 없음'
    if f=='hours':return '영업시간 밖에 들어옴' if op=='out' else '영업시간 안에 들어옴'
    return ''
def say_act(a,names):
    k,v=a['a'],a['v']
    if k=='tag':return '태그 '+', '.join('#'+w for w in v.split(','))
    if k=='prio':return f"우선순위 {inbox.PRIO.get(v,v)}"
    if k=='assign':return f"담당자 {names.get(v,'없음') if v else '없음'}"
    if k=='note':return f"메모 '{v[:20]}{'…' if len(v)>20 else ''}'"
    return ''

# 처음 쓰는 사장님을 위한 예시 (누르면 새 규칙 칸에 채워진다. 저장 전에 고칠 수 있다)
EXAMPLES={
    'angry':dict(name='화난 고객 먼저',match='any',conds=[dict(f='text',op='has',v='환불해, 최악, 신고, 소비자원, 사기')],acts=[dict(a='prio',v='urgent'),dict(a='tag',v='불만')]),
    'defect':dict(name='불량은 사진 확인',match='all',conds=[dict(f='category',op='is',v='제품 불량')],acts=[dict(a='tag',v='불량'),dict(a='note',v='사진이 있는지 먼저 확인해 주세요')]),
    'night':dict(name='밤사이 문의 표시',match='all',conds=[dict(f='hours',op='out',v='')],acts=[dict(a='tag',v='영업시간외')]),
}
