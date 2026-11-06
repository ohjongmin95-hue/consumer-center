"""채널톡에 있는 상담 기본기 (소보루 CX 1차).

  · 상담원 상태: 대표·직원마다 '상담 중'/'자리 비움'. 자리 비움이면 자동 배정에서 빠진다. 팀 화면에 상태와 맡은 요청 수를 같이 보여 준다.
  · 만족도 조사: 요청이 끝나면(해결·미해결·종료) 고객 화면에 1~5점과 한 줄 의견을 받는다. 한 번만. 통계에 최근 30일 평균과 만족 비율.
  · 번역: 고객 말을 한국어로, 사장님 답변을 고객 언어로. AI 키가 없으면 하지 않는다.
  · 버튼 서포트봇: 사장님이 정한 질문 버튼(최대 8개). 답을 적어 두면 AI를 부르지 않고 바로 그 답을 보여 준다 (비용 0).
  · 상담 전 입력폼: 접수 화면에 사장님이 정한 추가 질문(최대 3개). 답은 요청 본문 끝에 붙는다.
"""
import json, re
import core, ai
from core import conn, clean

CSAT_LABELS={1:'별로예요',2:'아쉬워요',3:'보통이에요',4:'좋아요',5:'최고예요'}
CSAT_EMOJI={1:'😞',2:'🙁',3:'😐',4:'🙂',5:'😍'}
CSAT_STATUSES=('resolved','unresolved','closed')
MAX_BTNS=8
MAX_QS=3
LANGS={'ko':'한국어','en':'영어','ja':'일본어','zh':'중국어','vi':'베트남어','th':'태국어','ru':'러시아어','es':'스페인어'}

def init():
    with conn() as db:
        cols={r[1] for r in db.execute('PRAGMA table_info(companies)')}
        for col,kind in (('owner_away',"INTEGER NOT NULL DEFAULT 0"),('quick_btns',"TEXT NOT NULL DEFAULT ''"),('form_qs',"TEXT NOT NULL DEFAULT ''")):
            if col not in cols:db.execute(f'ALTER TABLE companies ADD COLUMN {col} {kind}')
        cols={r[1] for r in db.execute('PRAGMA table_info(staff)')}
        if 'away' not in cols:db.execute("ALTER TABLE staff ADD COLUMN away INTEGER NOT NULL DEFAULT 0")
        cols={r[1] for r in db.execute('PRAGMA table_info(cases)')}
        for col,kind in (('csat',"INTEGER NOT NULL DEFAULT 0"),('csat_note',"TEXT NOT NULL DEFAULT ''"),('csat_at',"TEXT NOT NULL DEFAULT ''")):
            if col not in cols:db.execute(f'ALTER TABLE cases ADD COLUMN {col} {kind}')
init()

# ---------- 상담원 상태 ----------
def away_keys(db,co):
    """자리 비움인 사람 key 집합 ('owner' 또는 직원 id 문자열)."""
    out={str(r[0]) for r in db.execute('SELECT id FROM staff WHERE company_id=? AND away=1',(co['id'],))}
    if co['owner_away']:out.add('owner')
    return out
def is_away(db,co,key):return key in away_keys(db,co)
def set_away(db,co,key,on):
    """key의 상태를 바꾼다. -> 안내 문구"""
    on=1 if on else 0
    if key=='owner':db.execute('UPDATE companies SET owner_away=? WHERE id=?',(on,co['id']))
    elif str(key).isdigit():db.execute('UPDATE staff SET away=? WHERE id=? AND company_id=?',(on,int(key),co['id']))
    else:return ''
    return '자리 비움으로 바꿨어요. 새 요청이 자동으로 배정되지 않아요.' if on else '상담 중으로 바꿨어요. 새 요청을 다시 받아요.'
def board(db,co):
    """상담원 현황: [{key,name,away,open}] 대표 먼저."""
    import team
    away=away_keys(db,co)
    load=dict(db.execute("SELECT assignee,COUNT(*) FROM cases WHERE company_id=? AND assignee!='' AND status IN ('forwarded','seen','info') GROUP BY assignee",(co['id'],)).fetchall())
    return [dict(key=k,name=n,away=k in away,open=load.get(k,0)) for k,n in team.people(db,co)]

# ---------- 만족도 조사 ----------
def can_rate(c):return c['status'] in CSAT_STATUSES and not c['csat'] and bool(c['member'])
def rate(db,c,score,note=''):
    """고객이 매긴 점수. -> (문구, 'ok'|'error')"""
    try:score=int(score)
    except (TypeError,ValueError):score=0
    if score not in CSAT_LABELS:return '점수를 골라 주세요','error'
    if not can_rate(c):return '이미 평가했어요','error'
    note=clean(note,300).strip()
    db.execute('UPDATE cases SET csat=?,csat_note=?,csat_at=? WHERE id=?',(score,note,core.iso(),c['id']))
    core.add_event(db,c['id'],'me',f"상담 만족도: {CSAT_EMOJI[score]} {CSAT_LABELS[score]}"+(f" · {note}" if note else ''))
    return '평가해 주셔서 고마워요','ok'
def stats(db,cid,days=30):
    """최근 days일 동안 평가: n, avg(소수 한 자리), good(4~5점 비율 %), dist{점수:수}, notes(최근 의견 5개)."""
    since=core.iso(core.now()-__import__('datetime').timedelta(days=days))
    rows=db.execute("SELECT csat,csat_note,csat_at,title,id FROM cases WHERE company_id=? AND csat>0 AND csat_at>=? ORDER BY csat_at DESC",(cid,since)).fetchall()
    n=len(rows)
    if not n:return dict(n=0,avg=None,good=None,dist={k:0 for k in CSAT_LABELS},notes=[],days=days)
    dist={k:sum(1 for r in rows if r['csat']==k) for k in CSAT_LABELS}
    return dict(n=n,avg=round(sum(r['csat'] for r in rows)/n,1),good=round(sum(1 for r in rows if r['csat']>=4)/n*100),dist=dist,
                notes=[dict(score=r['csat'],note=r['csat_note'],id=r['id'],title=r['title']) for r in rows if r['csat_note']][:5],days=days)

# ---------- 번역 ----------
def guess_lang(text):
    """글자로 대강 언어를 짐작한다 (AI를 부르지 않는다). 한글이 있으면 ko."""
    t=text or ''
    if re.search(r'[가-힣]',t):return 'ko'
    if re.search(r'[぀-ヿ]',t):return 'ja'
    if re.search(r'[一-鿿]',t):return 'zh'
    if re.search(r'[฀-๿]',t):return 'th'
    if re.search(r'[Ѐ-ӿ]',t):return 'ru'
    if re.search(r'[ăâđêôơư]',t.lower()):return 'vi'
    if re.search(r'[a-zA-Z]',t):return 'en'
    return 'ko'
def customer_lang(db,c):
    """고객이 쓴 말(본문 + 고객 말)로 언어를 짐작한다."""
    said=' '.join([c['body'] or '']+[r[0] for r in db.execute("SELECT text FROM events WHERE case_id=? AND kind='me' ORDER BY id DESC LIMIT 3",(c['id'],))])
    return guess_lang(said)
def translate(text,target,meta=None):
    """text를 target 언어로. 실패하면 None."""
    text=clean(text,3000).strip()
    if not text or target not in LANGS or not ai.ready():return None
    out=ai.chat(f"너는 쇼핑몰 고객 상담 번역가다. 받은 글을 {LANGS[target]}로 자연스럽게 번역해서 번역문만 돌려준다. 설명·따옴표·원문은 붙이지 않는다. 존댓말을 지킨다.",
                [{'role':'user','content':text}],max_tokens=900,timeout=25,temperature=0.1,meta=dict(meta or {},purpose='translate'))
    return (out or '').strip() or None

# ---------- 버튼 서포트봇 ----------
def buttons(co):
    try:v=json.loads(co['quick_btns'] or '[]')
    except ValueError:return []
    return [dict(q=clean(b.get('q'),40),a=clean(b.get('a'),1000)) for b in v if isinstance(b,dict) and b.get('q')][:MAX_BTNS]
def save_buttons(db,co,f):
    out=[]
    for i in range(MAX_BTNS):
        q=clean(f.get(f'bq{i}'),40).strip();a=clean(f.get(f'ba{i}'),1000).strip()
        if q:out.append(dict(q=q,a=a))
    db.execute('UPDATE companies SET quick_btns=? WHERE id=?',(json.dumps(out,ensure_ascii=False),co['id']))
    return f'질문 버튼 {len(out)}개를 저장했어요' if out else '질문 버튼을 모두 지웠어요','ok'

# ---------- 상담 전 입력폼 ----------
def questions(co):
    try:v=json.loads(co['form_qs'] or '[]')
    except ValueError:return []
    return [clean(q,60) for q in v if isinstance(q,str) and q.strip()][:MAX_QS]
def save_questions(db,co,f):
    qs=[clean(f.get(f'fq{i}'),60).strip() for i in range(MAX_QS)];qs=[q for q in qs if q]
    db.execute('UPDATE companies SET form_qs=? WHERE id=?',(json.dumps(qs,ensure_ascii=False),co['id']))
    return f'접수 화면 추가 질문 {len(qs)}개를 저장했어요' if qs else '접수 화면 추가 질문을 모두 지웠어요','ok'
def answers_text(co,f):
    """접수 화면에서 받은 추가 질문 답 -> 본문 끝에 붙일 글 ('' 이면 없음)."""
    lines=[]
    for i,q in enumerate(questions(co)):
        a=clean(f.get(f'fa{i}'),300).strip()
        if a:lines.append(f'- {q}: {a}')
    return ('\n\n[추가로 알려 주신 내용]\n'+'\n'.join(lines)) if lines else ''
