"""분쟁·대응 (/howto). 운영자 2026-11-04: 둘러보기와 따로, 분쟁·대응 관련 글 메뉴 ('TIP'이라는 말은 쓰지 않음, 다른 사이트를 그대로 따라 하지 않음).

- 상황별 글: '환불을 안 해 줄 때'처럼 소비자가 겪는 상황마다 먼저 확인할 것 → 대처 순서 → 알아 두면 좋은 기준.
- 운영자 2026-11-04: 글은 미리 만들지 않음. 관리자 > 제보 > 분쟁·대응에서 쓰고 '공개'로 바꾼 글만 보인다.
- 글 쓰는 법은 '사기 전에 확인'과 같음: '## 소제목', '- 항목', 빈 줄 문단. 소제목에 '대처·이렇게'가 있으면 번호 줄, '확인'이면 체크 줄.
"""
import datetime

from flask import abort, flash, redirect, render_template, request, url_for

from buycheck import excerpt

STATUSES = {'draft': '초안', 'published': '공개'}
TOPICS = ['환불·반품', '배송', '불량·파손', '구독·결제', '계약·해지', '사기', '기본']
FLOW = [('📸', '기록 남기기', '캡처·영수증·대화'), ('✉️', '업체에 정식 요구', '날짜를 정해 글로'), ('☎️', '1372 상담', '피해구제 신청'), ('⚖️', '분쟁조정·소송', '마지막 방법')]



def install(S):
    app, conn = S.app, S.conn
    with conn() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS howto_guides(id INTEGER PRIMARY KEY,topic TEXT NOT NULL DEFAULT '',emoji TEXT NOT NULL DEFAULT '',title TEXT NOT NULL,body TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',sort INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL,updated TEXT NOT NULL)""")

    @app.route('/howto')
    def howto_list():
        topic = request.args.get('t', '')
        with conn() as db:
            have = [r[0] for r in db.execute("SELECT DISTINCT topic FROM howto_guides WHERE status='published'")]
            if topic not in have: topic = ''
            rows = db.execute("SELECT * FROM howto_guides WHERE status='published'" + (' AND topic=?' if topic else '') + ' ORDER BY sort,id', (topic,) if topic else ()).fetchall()
        guides = [dict(r, excerpt=excerpt(r['body'], 70)) for r in rows]
        return render_template('howto_list.html', guides=guides, topic=topic, topics=[t for t in TOPICS if t in have] + [t for t in have if t not in TOPICS], flow=FLOW)

    @app.route('/howto/<int:gid>')
    def howto_page(gid):
        with conn() as db:
            r = db.execute('SELECT * FROM howto_guides WHERE id=?', (gid,)).fetchone()
            if not r or (r['status'] != 'published' and not S.admin_active()): abort(404)
            more = db.execute("SELECT id,title,emoji,topic FROM howto_guides WHERE status='published' AND id!=? ORDER BY (topic=?) DESC,sort,id LIMIT 4", (gid, r['topic'])).fetchall()
        return render_template('howto_page.html', g_=r, more=more)

    @app.route('/admin/howto', methods=['GET', 'POST'])
    @S.admin_only
    def admin_howto():
        if request.method == 'POST':
            with conn() as db:
                top = db.execute('SELECT COALESCE(MAX(sort),0)+1 FROM howto_guides').fetchone()[0]
                gid = db.execute("INSERT INTO howto_guides(topic,emoji,title,body,sort,created,updated) VALUES('기본','📌','새 글','',?,?,?)", (top, S.now(), S.now())).lastrowid
            return redirect(url_for('admin_howto_edit', gid=gid))
        with conn() as db: rows = db.execute('SELECT * FROM howto_guides ORDER BY sort,id').fetchall()
        return render_template('admin_howto.html', rows=rows, statuses=STATUSES)

    @app.route('/admin/howto/<int:gid>', methods=['GET', 'POST'])
    @S.admin_only
    def admin_howto_edit(gid):
        with conn() as db:
            r = db.execute('SELECT * FROM howto_guides WHERE id=?', (gid,)).fetchone()
            if not r: abort(404)
            if request.method == 'POST':
                act = request.form.get('act')
                if act == 'delete':
                    db.execute('DELETE FROM howto_guides WHERE id=?', (gid,)); flash('지웠어요.'); return redirect(url_for('admin_howto'))
                f = request.form
                status = f.get('status') if f.get('status') in STATUSES else r['status']
                try: sort = int(f.get('sort') or r['sort'])
                except ValueError: sort = r['sort']
                db.execute('UPDATE howto_guides SET topic=?,emoji=?,title=?,body=?,status=?,sort=?,updated=? WHERE id=?',
                           (' '.join((f.get('topic') or r['topic']).split())[:20], (f.get('emoji') or '').strip()[:4] or r['emoji'], ' '.join((f.get('title') or r['title']).split())[:80],
                            (f.get('body') or '')[:8000], status, sort, S.now(), gid))
                flash('저장했어요.'); return redirect(url_for('admin_howto_edit', gid=gid))
        return render_template('admin_howto_edit.html', r=r, statuses=STATUSES, topics=TOPICS)
