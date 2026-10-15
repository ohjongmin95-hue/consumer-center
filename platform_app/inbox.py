"""받은 요청함 도구 (Gorgias의 Tags·Priority·Macros·Snooze·Merge·Bulk actions·Export·Customer profile에 해당).

  · 태그: 회사마다 이름을 정해 요청에 붙인다. 고객에게는 보이지 않는다.
  · 우선순위: 급함·높음·보통·낮음. 목록을 우선순위 순으로 볼 수 있다.
  · 답변 템플릿: 자주 쓰는 답변. {고객명}·{주문번호}처럼 적으면 요청 내용으로 채운다. 고르면 정해 둔 태그도 붙는다.
  · 미루기: 정한 때까지 '답변 전' 목록에서 빼 둔다. 때가 되거나 고객이 새로 글을 남기면 다시 나온다.
  · 합치기: 같은 고객이 따로 남긴 요청을 하나로. 원래 요청과 기록은 지우지 않고 '합쳐짐'으로 닫는다.
  · 일괄 처리·CSV 내려받기: 목록에서 여러 건을 고르거나 지금 보는 목록을 표로 받는다. 연락처·계좌는 표에 넣지 않는다.
"""
import csv, io, datetime
import core
from core import conn, clean

PRIO={'urgent':'급함','high':'높음','normal':'보통','low':'낮음'}
PRIO_ORDER={'urgent':0,'high':1,'normal':2,'low':3}
COLORS=('blue','green','amber','red','purple','gray')
MAX_TAGS=40;MAX_MACROS=60
VARS=('{고객명}','{주문번호}','{상품}','{택배사}','{송장번호}','{접수번호}','{가게이름}')

def init():
    with conn() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,name TEXT NOT NULL,color TEXT NOT NULL DEFAULT 'blue',created TEXT NOT NULL,
          UNIQUE(company_id,name),FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS case_tags(case_id INTEGER NOT NULL,tag_id INTEGER NOT NULL,PRIMARY KEY(case_id,tag_id),
          FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE,FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS macros(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,name TEXT NOT NULL,body TEXT NOT NULL,tags TEXT NOT NULL DEFAULT '',
          used INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL,FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE CASCADE);''')
init()  # 요청의 우선순위·미루기·합친 곳 칸은 core.init이 붙인다

def note(db,co,c,text):
    """회사 안의 일(태그·우선순위·미루기)은 고객이 보는 진행 기록이 아니라 내부 메모에 남긴다 (담당자 배정과 같음)."""
    who=(getattr(core.g,'actor','') or '시스템') if core.has_request_context() else '시스템'
    db.execute('INSERT INTO notes(case_id,company_id,author,text,created) VALUES(?,?,?,?,?)',(c['id'],co['id'],who,text,core.iso()))

# ---------- 태그 ----------
def tags(db,cid):return db.execute('SELECT * FROM tags WHERE company_id=? ORDER BY name',(cid,)).fetchall()
def tags_by_case(db,cid,case_ids=None):
    """{case_id:[tag행,...]} (목록 화면 한 번에)."""
    rows=db.execute('SELECT ct.case_id,t.* FROM case_tags ct JOIN tags t ON t.id=ct.tag_id WHERE t.company_id=? ORDER BY t.name',(cid,)).fetchall()
    out={}
    for r in rows:
        if case_ids is None or r['case_id'] in case_ids:out.setdefault(r['case_id'],[]).append(r)
    return out
def tag_named(db,cid,name,create=True):
    name=clean(name,20).strip().lstrip('#').strip()
    if not name:return None
    t=db.execute('SELECT * FROM tags WHERE company_id=? AND name=?',(cid,name)).fetchone()
    if t or not create:return t
    n=db.execute('SELECT COUNT(*) FROM tags WHERE company_id=?',(cid,)).fetchone()[0]
    if n>=MAX_TAGS:return None
    color=COLORS[n%len(COLORS)]
    db.execute('INSERT INTO tags(company_id,name,color,created) VALUES(?,?,?,?)',(cid,name,color,core.iso()))
    return db.execute('SELECT * FROM tags WHERE company_id=? AND name=?',(cid,name)).fetchone()
def add_tag(db,co,c,name):
    t=tag_named(db,co['id'],name)
    if not t:return None
    if db.execute('INSERT OR IGNORE INTO case_tags(case_id,tag_id) VALUES(?,?)',(c['id'],t['id'])).rowcount:note(db,co,c,f"태그 '{t['name']}'을(를) 붙였어요")
    return t
def remove_tag(db,co,c,tag_id):
    t=db.execute('SELECT * FROM tags WHERE id=? AND company_id=?',(tag_id,co['id'])).fetchone()
    if t and db.execute('DELETE FROM case_tags WHERE case_id=? AND tag_id=?',(c['id'],t['id'])).rowcount:note(db,co,c,f"태그 '{t['name']}'을(를) 뗐어요")
def delete_tag(db,cid,tag_id):db.execute('DELETE FROM tags WHERE id=? AND company_id=?',(tag_id,cid))

# ---------- 우선순위·미루기 ----------
def set_priority(db,co,c,p):
    if p not in PRIO or p==(c['priority'] or 'normal'):return False
    db.execute('UPDATE cases SET priority=? WHERE id=?',(p,c['id']));note(db,co,c,f'우선순위를 {PRIO[p]}(으)로 바꿨어요');return True

def snooze_time(choice,day='',base=None):
    """'1h'|'tomorrow'(내일 오전 9시)|'3d'|'date'(그날 오전 9시) -> ISO 문자열 또는 None."""
    t=base or core.now()
    if choice=='1h':return core.iso(t+datetime.timedelta(hours=1))
    if choice=='tomorrow':return core.iso((t+datetime.timedelta(days=1)).replace(hour=9,minute=0,second=0))
    if choice=='3d':return core.iso((t+datetime.timedelta(days=3)).replace(hour=9,minute=0,second=0))
    if choice=='date':
        try:d=datetime.date.fromisoformat(day)
        except (TypeError,ValueError):return None
        at=datetime.datetime.combine(d,datetime.time(9))
        if at<=t or at>t+datetime.timedelta(days=90):return None
        return core.iso(at)
    return None
def snooze(db,co,c,choice,day=''):
    if choice=='off':
        if not c['snooze_until']:return ''
        db.execute("UPDATE cases SET snooze_until='' WHERE id=?",(c['id'],));note(db,co,c,'미루기를 풀었어요');return '미루기를 풀었어요'
    if c['status'] in core.FINAL:return None
    at=snooze_time(choice,day)
    if not at:return None
    db.execute('UPDATE cases SET snooze_until=? WHERE id=?',(at,c['id']))
    label=fmt_when(at);note(db,co,c,f'{label}까지 미뤘어요');return f'{label}까지 미뤘어요'
def snoozed(c,now=None):return bool(c['snooze_until']) and c['snooze_until']>core.iso(now)
def fmt_when(ts):
    t=core.parse(ts)
    return f"{t.month}월 {t.day}일 {t.hour}시" if t.minute==0 else f"{t.month}월 {t.day}일 {t.hour}:{t.minute:02d}"

# ---------- 답변 템플릿 ----------
def macros(db,cid):return db.execute('SELECT * FROM macros WHERE company_id=? ORDER BY used DESC,name',(cid,)).fetchall()
def save_macro(db,cid,f,mid=None):
    name=clean(f.get('name'),30);body=clean(f.get('body'),3000)
    tg=','.join(dict.fromkeys(t for t in (clean(x,20).strip().lstrip('#') for x in (f.get('tags') or '').split(',')) if t))[:200]
    if not name or not body:return '이름과 답변 내용을 적어 주세요','error'
    if mid:
        if not db.execute('UPDATE macros SET name=?,body=?,tags=? WHERE id=? AND company_id=?',(name,body,tg,mid,cid)).rowcount:return '템플릿을 찾지 못했어요','error'
        return '템플릿을 고쳤어요','ok'
    if db.execute('SELECT COUNT(*) FROM macros WHERE company_id=?',(cid,)).fetchone()[0]>=MAX_MACROS:return f'템플릿은 {MAX_MACROS}개까지 만들 수 있어요','error'
    db.execute('INSERT INTO macros(company_id,name,body,tags,created) VALUES(?,?,?,?,?)',(cid,name,body,tg,core.iso()));return '템플릿을 만들었어요','ok'
def delete_macro(db,cid,mid):db.execute('DELETE FROM macros WHERE id=? AND company_id=?',(mid,cid))
def fill(body,c,co,order=None):
    """템플릿의 {고객명} 같은 자리를 요청 내용으로 채운다. 모르는 값은 그대로 두어 사람이 확인하게 한다."""
    vals={'{고객명}':c['name'],'{주문번호}':c['order_no'] or (order['order_no'] if order else ''),'{상품}':c['product'] or (order['product'] if order else ''),
          '{택배사}':(order['courier'] if order else '') or c['out_courier'],'{송장번호}':(order['invoice'] if order else '') or c['out_tracking'],
          '{접수번호}':c['no'],'{가게이름}':co['name']}
    for k,v in vals.items():
        if v:body=body.replace(k,v)
    return body
def used_macro(db,co,c,mid):
    """답변을 보낼 때 고른 템플릿: 쓴 횟수를 세고 정해 둔 태그를 붙인다."""
    m=db.execute('SELECT * FROM macros WHERE id=? AND company_id=?',(mid,co['id'])).fetchone()
    if not m:return
    db.execute('UPDATE macros SET used=used+1 WHERE id=?',(m['id'],))
    for t in [x for x in m['tags'].split(',') if x]:add_tag(db,co,c,t)

# ---------- 합치기 ----------
def same_customer(a,b):
    return bool((a['phone'] and a['phone']==b['phone']) or (a['email'] and a['email'].lower()==b['email'].lower()))
def merge(db,co,src,target_no):
    """src 요청을 target(접수번호)에 합친다. 지우지 않고 '합쳐짐'으로 닫는다. -> (안내, ok|error)"""
    t=db.execute('SELECT * FROM cases WHERE no=? AND company_id=? AND member=1 AND consent=1',(clean(target_no,30).strip().upper(),co['id'])).fetchone()
    if not t:return '그 접수번호의 요청을 찾지 못했어요','error'
    if t['id']==src['id']:return '같은 요청에는 합칠 수 없어요','error'
    if src['merged_into'] or src['status'] in core.FINAL:return '이미 끝난 요청은 합칠 수 없어요','error'
    if t['merged_into'] or t['status'] in core.FINAL:return '합칠 요청이 이미 끝났어요. 진행 중인 요청을 골라 주세요','error'
    if not same_customer(src,t):return '같은 고객(같은 휴대폰 번호나 이메일)의 요청만 합칠 수 있어요','error'
    db.execute("UPDATE cases SET merged_into=?,status='closed',snooze_until='' WHERE id=?",(t['id'],src['id']))
    core.add_event(db,src['id'],'sys',f"같은 내용의 접수 {t['no']}와 합쳐서 그쪽에서 이어서 처리해요")
    core.add_event(db,t['id'],'sys',f"같은 고객의 접수 {src['no']}를 이 요청에 합쳤어요")
    body=src['body'][:1500]
    db.execute('INSERT INTO notes(case_id,company_id,author,text,created) VALUES(?,?,?,?,?)',(t['id'],co['id'],(getattr(core.g,'actor','') or '시스템'),f"합친 요청 {src['no']} 「{src['title']}」\n{body}",core.iso()))
    for r in db.execute('SELECT tag_id FROM case_tags WHERE case_id=?',(src['id'],)).fetchall():db.execute('INSERT OR IGNORE INTO case_tags(case_id,tag_id) VALUES(?,?)',(t['id'],r['tag_id']))
    return f"{t['no']}에 합쳤어요",'ok'

# ---------- 고객 프로필 ----------
def customer(db,co,c):
    """같은 고객(휴대폰 번호나 이메일이 같은)의 다른 요청과 주문."""
    if not c['phone'] and not c['email']:return {'cases':[],'orders':[]}
    cases=db.execute("SELECT id,no,title,category,status,created FROM cases WHERE company_id=? AND member=1 AND consent=1 AND id!=? AND ((phone!='' AND phone=?) OR (email!='' AND lower(email)=lower(?))) ORDER BY id DESC LIMIT 6",
                     (co['id'],c['id'],c['phone'],c['email'])).fetchall()
    orders=db.execute("SELECT id,order_no,product,status,ordered_on,amount FROM orders WHERE company_id=? AND phone!='' AND phone=? ORDER BY ordered_on DESC,id DESC LIMIT 5",(co['id'],c['phone'])).fetchall() if c['phone'] else []
    n=db.execute("SELECT COUNT(*) FROM cases WHERE company_id=? AND member=1 AND consent=1 AND ((phone!='' AND phone=?) OR (email!='' AND lower(email)=lower(?)))",(co['id'],c['phone'],c['email'])).fetchone()[0]
    return {'cases':cases,'orders':orders,'n':n}

# ---------- 일괄 처리 ----------
def bulk(db,co,rows,form,people):
    """목록에서 고른 요청들에 같은 일을 한다. rows: 이 회사 요청만. -> 바뀐 건수"""
    act=form.get('bulk');n=0
    for c in rows:
        if act=='tag':n+=bool(add_tag(db,co,c,form.get('tag','')))
        elif act=='prio':n+=set_priority(db,co,c,form.get('prio',''))
        elif act=='snooze':n+=bool(snooze(db,co,c,form.get('when','tomorrow')))
        elif act=='unsnooze':n+=bool(snooze(db,co,c,'off'))
        elif act=='assign':
            import team
            n+=team.assign(db,co,c,form.get('assignee',''))is not None
    return n

# ---------- CSV ----------
def _cell(v):
    v='' if v is None else str(v)
    return "'"+v if v[:1] in ('=','+','-','@','\t','\r') else v  # 엑셀 수식으로 읽히지 않게
def csv_bytes(rows,tagmap,names,status_label):
    """지금 보는 목록을 표로. 연락처·이메일·계좌 같은 개인정보는 넣지 않는다."""
    out=io.StringIO();w=csv.writer(out)
    w.writerow(['접수번호','접수일','채널','유형','제목','원하는 해결','주문번호','상태','우선순위','담당자','태그','마지막 변경'])
    for r in rows:
        w.writerow([_cell(x) for x in (r['no'],r['created'],r['channel'] or core.CNAME,r['category'],r['title'],r['want'],r['order_no'],status_label(r),
                   PRIO.get(r['priority'] or 'normal',''),names.get(r['assignee'],''),', '.join(t['name'] for t in tagmap.get(r['id'],[])),r['updated'])])
    return ('﻿'+out.getvalue()).encode('utf-8')  # 엑셀이 한글을 바로 읽게 BOM
