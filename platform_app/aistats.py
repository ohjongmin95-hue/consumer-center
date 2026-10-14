"""AI 성과 분석: 실제로 남은 기록만 센다 (Gorgias의 AI Agent 성과 화면에 해당). 기록이 없으면 '–'로 두고 숫자를 만들지 않는다.

  · AI 상담: 고객이 상담창에서 물은 수, 그 자리에서 해결됐다고 누른 수, 결국 접수로 넘어간 수 (chat_log)
  · 자동 처리: 규칙으로 바로 처리된 문의 수와 비율, 그 문의의 해결·미해결 평가 (cases.decision='auto')
  · 답변 초안: 초안을 만든 문의 수, AI가 쓴 초안 수, 초안을 만든 뒤 실제로 답한 문의 수 (draft_log)
  · 첫 답변 시간: 자동 처리 문의와 사람이 답한 문의의 중간값
가져온 지난 문의(import_batch>0)와 시험 문의는 뺀다.
"""
import datetime, statistics
from flask import Blueprint, render_template, request, redirect, url_for, session
import core, insights
from core import conn

bp=Blueprint('ais',__name__)
MIN_N=5  # 이보다 적으면 비율을 보여 주지 않는다

def init():
    with conn() as db:db.executescript('''CREATE TABLE IF NOT EXISTS draft_log(id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL,case_id INTEGER NOT NULL,by TEXT NOT NULL,created TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS draft_log_co ON draft_log(company_id,created);''')
init()
def log_draft(db,co,c,by):db.execute('INSERT INTO draft_log(company_id,case_id,by,created) VALUES(?,?,?,?)',(co['id'],c['id'],by,core.iso()))

def pct(a,b):return round(a/b*100) if b>=MIN_N else None
def report(db,co,days=30):
    since=core.iso(core.now()-datetime.timedelta(days=days))
    q=lambda sql,*a:db.execute(sql,a).fetchone()[0]
    chat={o:q('SELECT COUNT(*) FROM chat_log WHERE company_id=? AND outcome=? AND created>=?',co['id'],o,since) for o in ('asked','solved','filed')}
    chat_cats=db.execute("SELECT category,SUM(outcome='asked') a,SUM(outcome='solved') s,SUM(outcome='filed') f FROM chat_log WHERE company_id=? AND created>=? GROUP BY category ORDER BY a DESC",(co['id'],since)).fetchall()
    rows=db.execute("SELECT * FROM cases WHERE company_id=? AND created>=? AND import_batch=0 AND title NOT LIKE '[시험 문의]%'",(co['id'],since)).fetchall()
    auto=[r for r in rows if r['decision']=='auto'];human=[r for r in rows if r['decision'] not in ('auto','')]
    rated=[r for r in auto if r['status'] in ('resolved','unresolved')]
    hrs=insights.first_reply_hours(db,rows)
    med=lambda xs:round(statistics.median(xs),1) if xs else None
    auto_cats=[(c,sum(r['category']==c for r in auto),sum(r['category']==c for r in rows)) for c in core.CATS]
    drafts=db.execute('SELECT case_id,by,MIN(created) t FROM draft_log WHERE company_id=? AND created>=? GROUP BY case_id',(co['id'],since)).fetchall()
    used=0
    for d in drafts:
        if db.execute("SELECT 1 FROM events WHERE case_id=? AND kind='co' AND reply!='' AND created>=?",(d['case_id'],d['t'])).fetchone():used+=1
    return dict(days=days,chat=chat,chat_solved=pct(chat['solved'],chat['asked']),chat_filed=pct(chat['filed'],chat['asked']),chat_cats=chat_cats,
                n=len(rows),n_auto=len(auto),auto_rate=pct(len(auto),len(rows)),auto_res=pct(sum(r['status']=='resolved' for r in rated),len(rated)),n_rated=len(rated),
                auto_cats=[x for x in auto_cats if x[2]],auto_h=med([hrs[r['id']] for r in auto if r['id'] in hrs]),human_h=med([hrs[r['id']] for r in human if r['id'] in hrs]),
                n_draft=len(drafts),n_draft_ai=sum(d['by']=='ai' for d in drafts),n_draft_used=used,MIN_N=MIN_N)

@bp.route('/stats/ai')
def page():
    if not session.get('co_id'):return redirect(url_for('login'))
    import business,chatbot
    days=int(request.args.get('d','30')) if request.args.get('d') in ('7','30','90') else 30
    with conn() as db:r=report(db,business.me(),days)
    return render_template('b_ai_stats.html',r=r,ai_on=chatbot.ready(),tab='stats')
