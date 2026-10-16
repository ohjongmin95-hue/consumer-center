"""공개 제보 공감·댓글 (검은고양이의 '나도 겪었어요'처럼).

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다.
- 공감: '나도 겪었어요'·'응원해요' 두 가지. 게시판 공감과 같은 board_votes 표에 브라우저(회원은 계정)당 1번, 다시 누르면 취소.
- 댓글: 게시판 댓글처럼 닉네임+삭제용 비밀번호(회원은 닉네임 자동). 화면에 보일 때 전화번호·이메일은 가림.
  이 제보를 조회한 제보자 본인이 쓰면 '제보자' 표시가 붙는다.
- 알리기 5번이면 자동 숨김, 운영자는 관리자 > 게시판 신고에서 숨기기·보이기·삭제.
- 공개 동의하고 게시된 제보에만 열린다. 관리자 > 숨은 문구·설정 '제보 공감·댓글 끄기'에 '끔'이라고 적으면 모두 닫힌다.
"""
import datetime
from flask import abort, flash, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

KINDS = {'metoo': '나도 겪었어요', 'cheer': '응원해요'}


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS case_comments(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL,nickname TEXT NOT NULL,pw_hash TEXT NOT NULL,body TEXT NOT NULL,
        ip_hash TEXT NOT NULL,created TEXT NOT NULL,hidden INTEGER NOT NULL DEFAULT 0,flags INTEGER NOT NULL DEFAULT 0,user_id INTEGER,by_reporter INTEGER NOT NULL DEFAULT 0)''')
    db.execute('CREATE INDEX IF NOT EXISTS case_comments_case ON case_comments(case_id)')


def install(S):
    app = S.app; conn = S.conn
    with conn() as db: migrate(db)

    def stamp(): return datetime.datetime.now().isoformat(timespec='seconds')
    def talk_on(): return (g.content.get('case.talk_off') or '').strip() not in ('끔', '끄기', 'off')
    def open_case(db, case_id):
        return db.execute("SELECT id FROM cases WHERE id=? AND public_consent=1 AND published=1 AND review NOT IN ('rejected','duplicate')", (case_id,)).fetchone()
    def back(case_id, anchor='talk'):
        return redirect(url_for('public_case', case_id=case_id) + '#' + anchor)

    def case_talk(case_id):
        """제보 상세 화면에 보일 공감 수·내가 누른 공감·댓글."""
        if not talk_on(): return None
        voter = S.voter_id()
        with conn() as db:
            counts = {k: db.execute('SELECT COUNT(*) FROM board_votes WHERE kind=? AND target=?', (k, 'case:%d' % case_id)).fetchone()[0] for k in KINDS}
            mine = {r['kind'] for r in db.execute('SELECT kind FROM board_votes WHERE target=? AND voter=?', ('case:%d' % case_id, voter))}
            rows = db.execute('SELECT * FROM case_comments WHERE case_id=? AND hidden=0 ORDER BY id', (case_id,)).fetchall()
        comments = [dict(id=r['id'], nickname=r['nickname'], body=S.mask_personal(r['body']), created=r['created'], by_reporter=bool(r['by_reporter']),
                         own=bool(g.get('user') and r['user_id'] == g.user['id']), member=bool(r['user_id'])) for r in rows]
        return {'counts': counts, 'mine': mine, 'comments': comments, 'kinds': KINDS, 'reporter': session.get('case_id') == case_id}

    def talk_counts(ids):
        """목록·메인 카드에 붙일 '나도 겪었어요'·댓글 수 {제보 번호: (공감, 댓글)}."""
        if not ids or not talk_on(): return {}
        q = ','.join('?' * len(ids))
        with conn() as db:
            me = {int(r[0][5:]): r[1] for r in db.execute(f"SELECT target,COUNT(*) FROM board_votes WHERE kind='metoo' AND target IN ({q}) GROUP BY target", ['case:%d' % i for i in ids])}
            cm = {r[0]: r[1] for r in db.execute(f'SELECT case_id,COUNT(*) FROM case_comments WHERE hidden=0 AND case_id IN ({q}) GROUP BY case_id', list(ids))}
        return {i: (me.get(i, 0), cm.get(i, 0)) for i in ids}

    @app.route('/reports/<int:case_id>/react', methods=['POST'])
    def case_react(case_id):
        kind = request.form.get('kind')
        if kind not in KINDS or not talk_on(): abort(404)
        with conn() as db:
            if not open_case(db, case_id): abort(404)
            key = (kind, 'case:%d' % case_id, S.voter_id())
            if db.execute('DELETE FROM board_votes WHERE kind=? AND target=? AND voter=?', key).rowcount == 0:
                db.execute('INSERT INTO board_votes(kind,target,voter,created) VALUES(?,?,?,?)', key + (stamp(),))
        return back(case_id)

    @app.route('/reports/<int:case_id>/comment', methods=['POST'])
    def case_comment(case_id):
        if not talk_on(): abort(404)
        if request.form.get('website'): abort(400)  # 자동 등록 막기용 숨은 칸
        nickname = request.form.get('nickname', '').strip(); password = request.form.get('password', ''); body = request.form.get('body', '').strip()
        if g.get('user'): nickname = g.user['nickname']; password = 'member'
        with conn() as db:
            if not open_case(db, case_id): abort(404)
            if not (2 <= len(nickname) <= 20 and 4 <= len(password) <= 30 and 1 <= len(body) <= 1000):
                flash(S.ui_text('msg.case_c1', '닉네임(2~20자), 비밀번호(4~30자), 댓글(1,000자 이내)을 확인해 주세요.')); return back(case_id, 'talk-form')
            if S.recent_count(db, 'case_comments', 2) >= 5:
                flash(S.ui_text('msg.m13', '잠시 후 다시 남겨 주세요.')); return back(case_id, 'talk-form')
            db.execute('INSERT INTO case_comments(case_id,nickname,pw_hash,body,ip_hash,created,user_id,by_reporter) VALUES(?,?,?,?,?,?,?,?)',
                       (case_id, nickname, '' if g.get('user') else generate_password_hash(password), body, S.ip_hash(), stamp(),
                        g.user['id'] if g.get('user') else None, int(session.get('case_id') == case_id)))
        return back(case_id)

    @app.route('/reports/comment/<int:comment_id>/flag', methods=['POST'])
    def case_comment_flag(comment_id):
        with conn() as db:
            c = db.execute('SELECT * FROM case_comments WHERE id=? AND hidden=0', (comment_id,)).fetchone()
            if not c: abort(404)
            target = 'k:%d' % comment_id
            db.execute('INSERT OR IGNORE INTO board_votes(kind,target,voter,created) VALUES(?,?,?,?)', ('flag', target, S.voter_id(), stamp()))
            flags = db.execute("SELECT COUNT(*) FROM board_votes WHERE kind='flag' AND target=?", (target,)).fetchone()[0]
            db.execute('UPDATE case_comments SET flags=?,hidden=? WHERE id=?', (flags, int(flags >= S.FLAG_HIDE_THRESHOLD), comment_id))
        flash(S.ui_text('msg.m14', '알려 주셔서 고마워요. 운영자가 확인할게요.'))
        return back(c['case_id'])

    @app.route('/reports/comment/<int:comment_id>/delete', methods=['POST'])
    def case_comment_delete(comment_id):
        with conn() as db:
            c = db.execute('SELECT * FROM case_comments WHERE id=?', (comment_id,)).fetchone()
            if not c: abort(404)
            own = g.get('user') and c['user_id'] == g.user['id']
            if not own and not (c['pw_hash'] and check_password_hash(c['pw_hash'], request.form.get('password', ''))):
                flash(S.ui_text('msg.m15', '비밀번호가 맞지 않아요.')); return back(c['case_id'])
            delete_comment(db, comment_id)
        flash(S.ui_text('msg.m16', '삭제했어요.'))
        return back(c['case_id'])

    def delete_comment(db, comment_id):
        # 작성자·운영자 삭제 모두 원문을 바로 지움
        db.execute('DELETE FROM board_votes WHERE target=?', ('k:%d' % comment_id,))
        db.execute('DELETE FROM case_comments WHERE id=?', (comment_id,))

    app.jinja_env.globals.update(case_talk=case_talk, talk_counts=talk_counts)
    S.case_talk = case_talk; S.talk_counts = talk_counts; S.delete_case_comment = delete_comment
