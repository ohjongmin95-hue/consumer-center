"""마케팅 분석: 방문 -> 가입 -> 설정 완료 -> 데모 -> 실제 사용 -> 상담 신청 흐름을 센다 (Gorgias의 가입 퍼널 분석에 해당).

개인정보를 모으지 않는다.
  · 방문자는 브라우저 세션에 넣은 임의 번호로만 구분한다 (IP·기기 정보·광고 식별자를 저장하지 않음).
  · 저장하는 것: 날짜, 페이지 주소, 들어온 사이트 이름(도메인만), UTM 값(utm_source·utm_medium·utm_campaign), 사건 종류.
  · 처음 들어올 때의 UTM을 세션에 기억해 두었다가 가입·상담 신청에 붙인다 (첫 유입 기준).
  · 오래된 방문 기록은 KEEP_DAYS가 지나면 지운다.
"""
import secrets, urllib.parse, datetime
from flask import request, session
import core
from core import conn, clean

KEEP_DAYS=400
KINDS={'visit':'방문','signup':'가입','setup_done':'처음 설정 완료','demo':'데모 사용','first_reply':'첫 실제 답변','consult':'상담 신청','tour':'제품 둘러보기','calc':'절감 계산'}
UTM=('utm_source','utm_medium','utm_campaign')

def init():
    with conn() as db:db.executescript('''
        CREATE TABLE IF NOT EXISTS funnel(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,company_id INTEGER NOT NULL DEFAULT 0,visitor TEXT NOT NULL DEFAULT '',
          path TEXT NOT NULL DEFAULT '',ref TEXT NOT NULL DEFAULT '',source TEXT NOT NULL DEFAULT '',medium TEXT NOT NULL DEFAULT '',campaign TEXT NOT NULL DEFAULT '',
          detail TEXT NOT NULL DEFAULT '',created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS funnel_kind ON funnel(kind,created);''')
init()

def visitor():
    if 'vid' not in session:session['vid']=secrets.token_hex(8)
    return session['vid']
def ref_host():
    r=request.referrer or ''
    h=urllib.parse.urlparse(r).hostname or ''
    return '' if not h or h==(request.host or '').split(':')[0] else h[:80]
def remember_utm():
    """주소에 UTM이 있으면 첫 유입으로 기억한다. 없으면 들어온 사이트 이름을 출처로."""
    a=request.args
    if any(a.get(k) for k in UTM):
        session['utm']={k:clean(a.get(k),60) for k in UTM}
    elif 'utm' not in session:
        h=ref_host();session['utm']={'utm_source':h,'utm_medium':'referral' if h else '','utm_campaign':''}
    return session.get('utm') or {}

def track(kind,company_id=0,detail='',path=None):
    """사건 하나 기록. 요청 안이 아니면(cron 등) 출처 없이 남긴다. 실패해도 서비스는 그대로."""
    try:
        u=(session.get('utm') or {}) if core.has_request_context() else {}
        vid=visitor() if core.has_request_context() else ''
        p=path if path is not None else (request.path if core.has_request_context() else '')
        rf=ref_host() if core.has_request_context() and kind=='visit' else ''
        with conn() as db:
            if kind!='visit' and company_id and kind in ('signup','setup_done','first_reply') and db.execute('SELECT 1 FROM funnel WHERE kind=? AND company_id=?',(kind,company_id)).fetchone():return
            db.execute('INSERT INTO funnel(kind,company_id,visitor,path,ref,source,medium,campaign,detail,created) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (kind,company_id or 0,vid,(p or '')[:120],rf,u.get('utm_source',''),u.get('utm_medium',''),u.get('utm_campaign',''),clean(detail,120),core.iso()))
    except Exception:pass

def visit():
    """공개 화면 방문 (같은 세션이 같은 페이지를 다시 열면 하루 한 번만)."""
    remember_utm()
    key=request.path+'|'+core.now().date().isoformat()
    seen=session.get('seen') or []
    if key in seen:return
    session['seen']=(seen+[key])[-30:]
    track('visit')

def cleanup():
    with conn() as db:db.execute('DELETE FROM funnel WHERE kind=? AND created<?',('visit',core.iso(core.now()-datetime.timedelta(days=KEEP_DAYS))))

def report(db,days=30):
    """운영 화면용 요약: 단계별 수, 출처별·캠페인별·페이지별 수. 실제 기록만 센다."""
    since=core.iso(core.now()-datetime.timedelta(days=days))
    q=lambda sql,*a:db.execute(sql,a).fetchall()
    steps=[]
    for k in ('visit','tour','calc','signup','setup_done','demo','first_reply','consult'):
        n=db.execute('SELECT COUNT(DISTINCT CASE WHEN company_id>0 THEN company_id ELSE visitor END) FROM funnel WHERE kind=? AND created>=?',(k,since)).fetchone()[0]
        steps.append((k,KINDS[k],n))
    by_source=q("""SELECT CASE WHEN source='' THEN '(직접 방문)' ELSE source END src,SUM(kind='visit') v,SUM(kind='signup') s,SUM(kind='consult') c
        FROM funnel WHERE created>=? GROUP BY src ORDER BY v DESC LIMIT 20""",since)
    by_campaign=q("""SELECT campaign,source,medium,SUM(kind='visit') v,SUM(kind='signup') s,SUM(kind='consult') c FROM funnel WHERE created>=? AND campaign!=''
        GROUP BY campaign,source,medium ORDER BY v DESC LIMIT 20""",since)
    by_page=q("SELECT path,COUNT(*) v FROM funnel WHERE kind='visit' AND created>=? GROUP BY path ORDER BY v DESC LIMIT 20",since)
    daily=q("SELECT substr(created,1,10) d,SUM(kind='visit') v,SUM(kind='signup') s FROM funnel WHERE created>=? GROUP BY d ORDER BY d",since)
    return {'days':days,'steps':steps,'by_source':by_source,'by_campaign':by_campaign,'by_page':by_page,'daily':daily}
