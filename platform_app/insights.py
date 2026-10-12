"""기업 화면의 숫자들: 월간 리포트, 업종 비교, 불량 조기 경보.

cron이 부르는 함수(send_monthly_reports, send_alerts)는 같은 내용을 두 번 보내지 않게 sent_marks에 기록한다.
"""
import datetime, statistics
import core
from core import conn

DEFECT_CATS=('제품 불량','교환','반품·환불')
ALERT_DAYS=7
ALERT_PRODUCT=3   # 같은 상품 민원이 7일에 3건 이상
ALERT_CATEGORY=5  # 같은 유형 민원이 7일에 5건 이상
COMPARE_MIN=3     # 같은 업종 다른 기업이 이만큼 있어야 비교를 보여 준다 (한 회사가 드러나지 않게)

def company_cases(db,cid):return db.execute('SELECT * FROM cases WHERE company_id=? AND member=1 AND consent=1 ORDER BY id',(cid,)).fetchall()

def first_reply_hours(db,rows):
    """민원별 접수부터 기업의 첫 답변(자료 요청 포함)까지 걸린 시간(시간 단위)."""
    out={}
    if not rows:return out
    ids=[r['id'] for r in rows]
    for chunk in range(0,len(ids),500):
        part=ids[chunk:chunk+500]
        for e in db.execute(f"SELECT case_id,MIN(created) t FROM events WHERE kind='co' AND case_id IN ({','.join('?'*len(part))}) GROUP BY case_id",part):out[e['case_id']]=e['t']
    res={}
    for r in rows:
        a=core.parse(r['created']);b=core.parse(out.get(r['id']))
        if a and b:res[r['id']]=max(0,(b-a).total_seconds()/3600)
    return res

def summarize(db,rows):
    n=len(rows);hrs=list(first_reply_hours(db,rows).values())
    rated=[r for r in rows if r['status'] in ('resolved','unresolved')]
    return {'n':n,'auto':round(sum(r['decision']=='auto' for r in rows)/n*100) if n else 0,
            'res':round(sum(r['status']=='resolved' for r in rated)/len(rated)*100) if rated else None,
            'reply_h':round(statistics.median(hrs),1) if hrs else None,
            'late':sum(bool(r['late_sent']) for r in rows),
            'cats':[(c,sum(r['category']==c for r in rows)) for c in core.CATS],
            'channels':sorted({(r['channel'] or '한큐') for r in rows})}

def month_range(y,m):
    start=datetime.date(y,m,1);end=(start+datetime.timedelta(days=32)).replace(day=1)
    return start,end
def prev_month(today=None):
    d=(today or datetime.date.today()).replace(day=1)-datetime.timedelta(days=1);return d.year,d.month

def monthly(db,co,y,m):
    start,end=month_range(y,m)
    rows=[r for r in company_cases(db,co['id']) if start.isoformat()<=r['created'][:10]<end.isoformat()]
    ps,pe=month_range(*prev_month(start))
    prev=[r for r in company_cases(db,co['id']) if ps.isoformat()<=r['created'][:10]<pe.isoformat()]
    s=summarize(db,rows);p=summarize(db,prev)
    prods={}
    for r in rows:
        k=(r['product'] or '').strip()
        if k:prods[k]=prods.get(k,0)+1
    s.update(y=y,m=m,prev_n=p['n'],top_products=sorted(prods.items(),key=lambda x:-x[1])[:5],
             by_channel=[(ch,sum((r['channel'] or '한큐')==ch for r in rows)) for ch in ['한큐']+core.CHANNELS if any((r['channel'] or '한큐')==ch for r in rows)])
    return s

def report_text(co,s):
    ym=f"{s['y']}년 {s['m']}월"
    lines=[f"{co['name']}의 {ym} CS 리포트예요.",'',
           f"■ 받은 민원: {s['n']}건 (지난달 {s['prev_n']}건)",
           f"■ 자동 처리율: {s['auto']}%",
           f"■ 해결률: {'-' if s['res'] is None else str(s['res'])+'%'} (소비자가 결과를 알려 준 민원 기준)",
           f"■ 첫 답변까지: {'-' if s['reply_h'] is None else '중간값 '+str(s['reply_h'])+'시간'}",
           f"■ 답변 목표일을 넘긴 민원: {s['late']}건",'','유형별']+[f"  · {c} {n}건" for c,n in s['cats'] if n]
    if s['top_products']:lines+=['','민원이 많았던 상품']+[f"  · {p} {n}건" for p,n in s['top_products']]
    return '\n'.join(lines)

def send_monthly_reports(today=None):
    """매달 1일에 지난달 리포트를 알림 이메일로 보낸다 (리포트 메일을 끈 기업 제외). cron에서 날마다 부른다."""
    today=today or datetime.date.today()
    if today.day!=1:return 0
    y,m=prev_month(today);key=f'{y}-{m:02d}';n=0
    with conn() as db:
        for co in db.execute("SELECT * FROM companies WHERE status='active' AND member=1 AND report_mail=1").fetchall():
            if db.execute("SELECT 1 FROM sent_marks WHERE kind='report' AND company_id=? AND key=?",(co['id'],key)).fetchone():continue
            s=monthly(db,co,y,m)
            core.send_mail(co['notify_email'],f'[{core.BNAME}] {y}년 {m}월 CS 리포트',report_text(co,s)+'\n\n'+core.site_or_blank('biz',f'/report?ym={key}'))
            db.execute("INSERT INTO sent_marks(kind,company_id,key,created) VALUES('report',?,?,?)",(co['id'],key,core.iso()));n+=1
    return n

def compare(db,co):
    """같은 업종 기업들과 비교. 업종을 안 정했거나 비교할 기업이 COMPARE_MIN보다 적으면 None."""
    if not co['industry']:return None
    since=(datetime.date.today()-datetime.timedelta(days=90)).isoformat()
    others=db.execute("SELECT * FROM companies WHERE status='active' AND member=1 AND industry=? AND id!=?",(co['industry'],co['id'])).fetchall()
    peers=[]
    for o in others:
        rows=[r for r in company_cases(db,o['id']) if r['created'][:10]>=since]
        if rows:peers.append(summarize(db,rows))
    if len(peers)<COMPARE_MIN:return {'ready':False,'have':len(peers),'need':COMPARE_MIN}
    mine=summarize(db,[r for r in company_cases(db,co['id']) if r['created'][:10]>=since])
    def avg(key):
        v=[p[key] for p in peers if p[key] is not None];return round(sum(v)/len(v),1) if v else None
    def share(s,cat):return round(dict(s['cats'])[cat]/s['n']*100) if s['n'] else 0
    return {'ready':True,'peers':len(peers),'mine':mine,'avg':{'auto':avg('auto'),'res':avg('res'),'reply_h':avg('reply_h'),'n':avg('n')},
            'cats':[(c,share(mine,c),round(sum(share(p,c) for p in peers)/len(peers))) for c in core.CATS]}

def alerts(db,co,today=None):
    """최근 7일 같은 상품·같은 유형 민원이 몰리면 경보 목록."""
    today=today or datetime.date.today();since=(today-datetime.timedelta(days=ALERT_DAYS-1)).isoformat()
    rows=[r for r in company_cases(db,co['id']) if r['created'][:10]>=since]
    out=[];prods={}
    for r in rows:
        k=' '.join((r['product'] or '').split()).lower()
        if k and r['category'] in DEFECT_CATS:prods.setdefault(k,[]).append(r)
    for k,rs in prods.items():
        if len(rs)>=ALERT_PRODUCT:out.append({'key':'p:'+k,'kind':'product','label':rs[-1]['product'].strip(),'n':len(rs),'cats':sorted({r['category'] for r in rs})})
    for c in core.CATS:
        n=sum(r['category']==c for r in rows)
        if c!='기타' and n>=ALERT_CATEGORY:out.append({'key':'c:'+c,'kind':'category','label':c,'n':n,'cats':[c]})
    return out

def send_alerts(today=None):
    """경보를 하루에 한 번씩 알림 이메일로. cron(한 시간마다)에서 부른다."""
    today=today or datetime.date.today();n=0
    with conn() as db:
        for co in db.execute("SELECT * FROM companies WHERE status='active' AND member=1").fetchall():
            for a in alerts(db,co,today):
                key=f"{today.isoformat()}:{a['key']}"
                if db.execute("SELECT 1 FROM sent_marks WHERE kind='alert' AND company_id=? AND key=?",(co['id'],key)).fetchone():continue
                what=f"'{a['label']}' 관련 민원" if a['kind']=='product' else f"'{a['label']}' 민원"
                core.send_mail(co['notify_email'],f"[{core.BNAME}] 경보: 최근 7일 {what} {a['n']}건",
                    f"최근 7일 동안 {what}이 {a['n']}건 들어왔어요. 같은 문제가 반복되는지 확인해 보세요.\n\n{core.site_or_blank('biz','/')}")
                db.execute("INSERT INTO sent_marks(kind,company_id,key,created) VALUES('alert',?,?,?)",(co['id'],key,core.iso()));n+=1
    return n
