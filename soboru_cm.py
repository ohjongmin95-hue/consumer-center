"""소보루 커뮤니티 (품앗히식, 운영자 요청 2026-10-24): 내돈내산 후기 피드 · 골라주세요 · 수다방 · 포인트 · 후기 에디터 모집.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 주소를 붙인다. 글·댓글은 게시판(posts·comments)을 그대로 쓰고,
app.py의 BOARD_HOOKS로 글이 올라갈 때 후기 정보·말머리·영수증·포인트를 더한다.
- 후기 피드(/feed): 리뷰 글에 상품/장소, 분류, 가격, 구매·방문일, 재구매·재방문 의사, 영수증.
  영수증은 운영자만 보고(관리자 > 영수증 확인), 확인하면 '영수증 인증' 표시와 포인트.
- 골라주세요(/vs): A vs B 투표. 누구나 한 번 고를 수 있고, 써 본 사람 표는 따로 셈. 마감 뒤 글쓴이가 결말을 남김.
- 수다방(/suda): 이야기·꿀팁·질문 글을 말머리로 모아 봄. 질문 말머리는 질문 글, 정보 말머리는 꿀팁 글이 됨.
- 포인트(/me/points): 회원만. 쓰는 곳은 아직 없고 쌓이기만 함.
- 에디터 모집(/editor): 신청서(호칭·휴대폰·제품·영수증 유무). 선정하지 않은 신청은 30일이 지나면 지움.
"""
import datetime, json, re, secrets
from flask import abort, flash, g, redirect, render_template, request, send_file, url_for

RV_TYPES = [('product', '상품'), ('place', '장소')]
RV_CATS = {'product': [('식품', '🥗'), ('뷰티', '🧴'), ('패션', '👕'), ('디지털·가전', '💻'), ('집·생활', '🏠'), ('육아', '🧸'), ('반려동물', '🐶'), ('스포츠·레저', '👟'), ('기타', '📦')],
           'place': [('맛집·카페', '☕'), ('숙소·여행', '✈️'), ('체험·클래스', '🎯'), ('미용·네일', '✨'), ('병원·의원', '🩺'), ('운동', '💪'), ('학원·교육', '📚'), ('기타', '📍')]}
# 예전 리뷰 분류(이번 주 리뷰 주제가 쓰는 것) → 후기 피드 분류
OLD_CAT = {'배달음식': ('place', '맛집·카페'), '편의점': ('product', '식품'), '생활용품': ('product', '집·생활'), '화장품': ('product', '뷰티'), '온라인 쇼핑': ('product', '기타')}
VS_CATS = [('먹거리', '🍜'), ('패션', '👕'), ('뷰티', '🧴'), ('영화·책', '📚'), ('여행', '✈️'), ('선물', '🎁'), ('살까말까', '🤔'), ('가전·디지털', '💻'),
           ('집·생활', '🏠'), ('동네', '📍'), ('기타', '💬')]
VS_DAYS = (1, 3, 7)
SUDA_HEADS = ['지름', '질문', '잡담', '정보', '연애', '직장', '인증', '운동']
HEAD_KIND = {'질문': 'question', '정보': 'tip'}  # 나머지 말머리는 이야기 글
KIND_HEAD = {'question': '질문', 'tip': '정보', 'post': '잡담'}  # 말머리 없이 쓴 예전 글
# 포인트: (이름, 점수, 하루에 받는 횟수. 0은 제한 없음)
POINTS = {'review_ok': ('영수증 인증 후기', 200, 0), 'vote': ('골라주세요 투표', 5, 3), 'vs_end': ('골라주세요 결말', 50, 0),
          'suda': ('수다 글', 10, 3), 'suda_first': ('첫 수다', 100, 0), 'comment': ('댓글', 10, 5)}
EDITOR_STATUS = {'new': '새 신청', 'pick': '선정', 'paid': '입금 완료', 'no': '선정 안 함'}
EDITOR_KEEP_DAYS = 30
PAGE = 20


def migrate(db):
    have = {r['name'] for r in db.execute('PRAGMA table_info(posts)')}
    for col, ddl in (('rv_type', "TEXT NOT NULL DEFAULT ''"), ('rv_cat', "TEXT NOT NULL DEFAULT ''"), ('price', 'INTEGER NOT NULL DEFAULT 0'),
                     ('bought', "TEXT NOT NULL DEFAULT ''"), ('again', 'INTEGER'), ('receipt', "TEXT NOT NULL DEFAULT ''"),
                     ('receipt_state', "TEXT NOT NULL DEFAULT ''"), ('views', 'INTEGER NOT NULL DEFAULT 0'), ('head', "TEXT NOT NULL DEFAULT ''")):
        if col not in have: db.execute(f'ALTER TABLE posts ADD COLUMN {col} {ddl}')
    for old, (t, c) in OLD_CAT.items():
        db.execute("UPDATE posts SET rv_type=?,rv_cat=? WHERE kind='review' AND rv_type='' AND review_cat=?", (t, c, old))
    db.execute('''CREATE TABLE IF NOT EXISTS vs_polls(id INTEGER PRIMARY KEY,cat TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL DEFAULT '',a TEXT NOT NULL,b TEXT NOT NULL,
        user_id INTEGER,nickname TEXT NOT NULL,ends TEXT NOT NULL,ending TEXT NOT NULL DEFAULT '',ending_note TEXT NOT NULL DEFAULT '',views INTEGER NOT NULL DEFAULT 0,
        hidden INTEGER NOT NULL DEFAULT 0,ip_hash TEXT NOT NULL DEFAULT '',created TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS vs_votes(poll_id INTEGER NOT NULL,voter TEXT NOT NULL,pick TEXT NOT NULL,used INTEGER NOT NULL DEFAULT 0,user_id INTEGER,created TEXT NOT NULL,
        PRIMARY KEY(poll_id,voter))''')
    db.execute('''CREATE TABLE IF NOT EXISTS vs_comments(id INTEGER PRIMARY KEY,poll_id INTEGER NOT NULL,user_id INTEGER,nickname TEXT NOT NULL,body TEXT NOT NULL,
        pick TEXT NOT NULL DEFAULT '',hidden INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS vs_comments_poll ON vs_comments(poll_id)')
    db.execute('''CREATE TABLE IF NOT EXISTS points(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,amount INTEGER NOT NULL,reason TEXT NOT NULL,ref TEXT NOT NULL DEFAULT '',created TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS points_user ON points(user_id)')
    db.execute('''CREATE TABLE IF NOT EXISTS editor_apps(id INTEGER PRIMARY KEY,name TEXT NOT NULL,phone TEXT NOT NULL,products TEXT NOT NULL,receipt INTEGER NOT NULL DEFAULT 0,
        user_id INTEGER,status TEXT NOT NULL DEFAULT 'new',note TEXT NOT NULL DEFAULT '',ip_hash TEXT NOT NULL DEFAULT '',created TEXT NOT NULL)''')


def stamp(): return datetime.datetime.now().isoformat(timespec='seconds')


def days_between(a, b):
    """구매·방문일(a)부터 글 쓴 날(b)까지 며칠. 날짜가 이상하면 None."""
    try: return (datetime.date.fromisoformat((b or '')[:10]) - datetime.date.fromisoformat((a or '')[:10])).days
    except ValueError: return None


def won(n):
    return '{:,}원'.format(n) if n else ''


def install(S):
    app = S.app; conn = S.conn
    with conn() as db: migrate(db)
    RECEIPT_DIR = S.UPLOAD / 'receipts'; RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    cat_emoji = {t: dict(rows) for t, rows in RV_CATS.items()}
    vs_emoji = dict(VS_CATS)

    # ---- 포인트 -----------------------------------------------------------
    def award(db, user_id, reason, ref=''):
        """포인트 주기. 같은 일(ref)로는 한 번만, 하루 횟수가 정해진 일은 그만큼만. 준 점수(못 주면 0)."""
        if not user_id or reason not in POINTS: return 0
        _, amount, cap = POINTS[reason]
        if ref and db.execute('SELECT 1 FROM points WHERE user_id=? AND reason=? AND ref=?', (user_id, reason, ref)).fetchone(): return 0
        if cap and db.execute('SELECT COUNT(*) FROM points WHERE user_id=? AND reason=? AND created>=?', (user_id, reason, datetime.date.today().isoformat())).fetchone()[0] >= cap: return 0
        db.execute('INSERT INTO points(user_id,amount,reason,ref,created) VALUES(?,?,?,?,?)', (user_id, amount, reason, ref, stamp()))
        return amount

    def point_total(user_id):
        with conn() as db: return db.execute('SELECT COALESCE(SUM(amount),0) FROM points WHERE user_id=?', (user_id,)).fetchone()[0]

    # ---- 게시판에 붙는 일: 글 올리기 전 말머리→종류, 올린 뒤 후기 정보·영수증·포인트, 열 때 조회수 ----
    def on_board(event, db, **kw):
        f = request.form
        if event == 'prepare':
            post = kw['form']; head = f.get('head', '')
            if post['kind'] in ('', 'post') and head in HEAD_KIND: post['kind'] = HEAD_KIND[head]
            if post['kind'] in ('', 'post') and head in SUDA_HEADS and post['category'] not in S.board_categories(): post['category'] = S.story_categories()[0]
        elif event == 'post':
            pid, kind = kw['post_id'], kw['kind']
            if kind == 'review':
                t = f.get('rv_type', ''); c = f.get('rv_cat', '')
                old = OLD_CAT.get(kw.get('review_cat', ''), ('', ''))
                if t not in RV_CATS: t, c = old
                elif c not in cat_emoji[t]: c = old[1] if old[0] == t else '기타'
                price = int(re.sub(r'\D', '', f.get('price', ''))[:9] or 0)
                bought = f.get('bought', '')[:10]
                if days_between(bought, stamp()) is None or days_between(bought, stamp()) < 0: bought = ''
                again = {'1': 1, '0': 0}.get(f.get('again', ''))
                receipt, state = '', ''
                up = request.files.get('receipt')
                if up and up.filename:
                    data, ext = S.clean_photo(up.stream.read(S.BOARD_PHOTO_MAX + 1))
                    if data:
                        receipt = secrets.token_hex(16) + '.' + ext; (RECEIPT_DIR / receipt).write_bytes(data); state = 'wait'
                        flash(S.ui_text('feed.receipt_sent', '영수증을 받았어요. 운영자가 확인하면 영수증 인증 표시와 200P가 붙어요.'))
                    else: flash(S.ui_text('feed.receipt_bad', '영수증 사진은 8MB 이하 JPG·PNG·WEBP로 다시 올려 주세요. 후기는 올라갔어요.'))
                db.execute('UPDATE posts SET rv_type=?,rv_cat=?,price=?,bought=?,again=?,receipt=?,receipt_state=? WHERE id=?', (t, c, price, bought, again, receipt, state, pid))
            else:
                head = f.get('head', '')
                db.execute('UPDATE posts SET head=? WHERE id=?', (head if head in SUDA_HEADS else KIND_HEAD.get(kind, ''), pid))
                if g.user:
                    got = award(db, g.user['id'], 'suda', 'p%d' % pid) + award(db, g.user['id'], 'suda_first', 'first')
                    if got: flash(S.ui_text('suda.got', '수다 포인트 {n}P를 받았어요.').replace('{n}', str(got)))
        elif event == 'comment':
            if g.user: award(db, g.user['id'], 'comment', 'c%d' % kw['comment_id'])
        elif event == 'view':
            db.execute('UPDATE posts SET views=views+1 WHERE id=?', (kw['post_id'],))
    S.BOARD_HOOKS.append(on_board)

    # ---- 후기 한 줄에 쓰는 값 ------------------------------------------------
    def review_view(p):
        p = dict(p)
        t = p.get('rv_type') or ''
        p['cat_emoji'] = cat_emoji.get(t, {}).get(p.get('rv_cat'), '📝')
        p['since'] = days_between(p.get('bought'), p.get('created')) if t == 'product' else None
        p['visit'] = p['bought'][5:].replace('-', '.') if t == 'place' and p.get('bought') else ''
        p['again_word'] = '' if p.get('again') is None else (('재방문' if t == 'place' else '재구매') + (' 의사 있어요' if p['again'] else ' 안 해요'))
        p['won'] = won(p.get('price') or 0)
        return p

    def suda_view(p):
        p = dict(p); p['head'] = p.get('head') or KIND_HEAD.get(p.get('kind'), '잡담'); return p

    app.jinja_env.globals.update(RV_TYPES=RV_TYPES, RV_CATS=RV_CATS, VS_CATS=VS_CATS, SUDA_HEADS=SUDA_HEADS, POINTS=POINTS, point_total=point_total,
                                 review_view=review_view, suda_view=suda_view)

    def search_like(q):
        return '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'

    # ---- 내돈내산 후기 피드 ---------------------------------------------------
    @app.route('/feed')
    def feed():
        a = request.args
        t = a.get('t', ''); t = t if t in RV_CATS else ''
        c = a.get('c', ''); c = c if t and c in cat_emoji[t] else ''
        sort = a.get('sort', 'new'); sort = sort if sort in ('new', 'views', 'likes') else 'new'
        ok = a.get('ok') == '1'
        q = a.get('q', '').strip()[:60]; field = a.get('f', 'all'); field = field if field in ('all', 'target', 'who') else 'all'
        page = max(1, a.get('page', 1, type=int))
        where = ["kind='review'", 'hidden=0' + S.not_blocked()]; args = []
        if t: where.append('rv_type=?'); args.append(t)
        if c: where.append('rv_cat=?'); args.append(c)
        if ok: where.append("receipt_state='ok'")
        if q:
            like = search_like(q)
            if field == 'target': where.append("target LIKE ? ESCAPE '\\'"); args.append(like)
            elif field == 'who': where.append("nickname LIKE ? ESCAPE '\\'"); args.append(like)
            else: where.append("(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\' OR target LIKE ? ESCAPE '\\')"); args += [like] * 3
        order = {'new': 'id DESC', 'views': 'views DESC,id DESC', 'likes': 'likes DESC,id DESC'}[sort]
        sql = ' AND '.join(where)
        with conn() as db:
            total = db.execute('SELECT COUNT(*) FROM posts WHERE ' + sql, args).fetchone()[0]
            rows = db.execute(f'SELECT * FROM posts WHERE {sql} ORDER BY {order} LIMIT ? OFFSET ?', args + [PAGE, (page - 1) * PAGE]).fetchall()
            n_ok = db.execute("SELECT COUNT(*) FROM posts WHERE kind='review' AND hidden=0 AND receipt_state='ok'").fetchone()[0]
            week = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat(timespec='seconds')
            hot = db.execute("SELECT id,title,target,views FROM posts WHERE kind='review' AND hidden=0" + S.not_blocked() + ' AND created>=? ORDER BY views DESC,likes DESC,id DESC LIMIT 5', (week,)).fetchall()
        pages = max(1, -(-total // PAGE))
        if page > pages: abort(404)
        return render_template('soboru_feed.html', rows=[review_view(r) for r in rows], t=t, c=c, sort=sort, ok=ok, q=q, field=field, page=page, pages=pages,
                               total=total, n_ok=n_ok, hot=hot, cat_emoji=cat_emoji)

    @app.route('/feed/receipt/<name>')
    @S.admin_only
    def feed_receipt(name):
        # 영수증 사진은 운영자만 (공개 화면 어디에도 안 나감)
        if not re.fullmatch(r'[0-9a-f]{32}\.(jpg|png|webp)', name) or not (RECEIPT_DIR / name).is_file(): abort(404)
        resp = send_file(RECEIPT_DIR / name, mimetype=S.PHOTO_TYPES[name.rsplit('.', 1)[1]], max_age=0)
        resp.headers['Content-Security-Policy'] = "default-src 'none'"; resp.headers['Cache-Control'] = 'private, no-store'
        return resp

    @app.route('/admin/receipts', methods=['GET', 'POST'])
    @S.admin_only
    def admin_receipts():
        with conn() as db:
            if request.method == 'POST':
                pid = request.form.get('id', type=int); act = request.form.get('act')
                post = db.execute("SELECT * FROM posts WHERE id=? AND kind='review'", (pid,)).fetchone()
                if not post or act not in ('ok', 'no'): abort(400)
                db.execute('UPDATE posts SET receipt_state=? WHERE id=?', (act, pid))
                if act == 'ok' and post['user_id'] and award(db, post['user_id'], 'review_ok', 'p%d' % pid):
                    S.member_alert(db, post['user_id'], 'points', S.ui_text('feed.alert_ok', '후기 영수증이 인증됐어요. 200P를 드렸어요') + f": {post['title'][:40]}", url_for('board_post', post_id=pid))
                flash('영수증 인증을 저장했어요.' if act == 'ok' else '인증하지 않음으로 저장했어요.')
                return redirect(url_for('admin_receipts', show=request.args.get('show', 'wait')))
            show = request.args.get('show', 'wait'); show = show if show in ('wait', 'ok', 'no') else 'wait'
            rows = db.execute('SELECT * FROM posts WHERE receipt!=? AND receipt_state=? ORDER BY id DESC LIMIT 100', ('', show)).fetchall()
            counts = dict(db.execute("SELECT receipt_state,COUNT(*) FROM posts WHERE receipt!='' GROUP BY receipt_state").fetchall())
        return render_template('admin_receipts.html', rows=[review_view(r) for r in rows], show=show, counts=counts)

    def receipts_waiting():
        with conn() as db: return db.execute("SELECT COUNT(*) FROM posts WHERE receipt_state='wait'").fetchone()[0]

    # ---- 골라주세요 -------------------------------------------------------
    def poll_state(p):
        if p['ending']: return 'done'
        return 'open' if p['ends'] > stamp() else 'wait'

    def poll_view(p, mine=None):
        p = dict(p)
        with conn() as db:
            n = dict(db.execute('SELECT pick,COUNT(*) FROM vs_votes WHERE poll_id=? GROUP BY pick', (p['id'],)).fetchall())
            used = dict(db.execute('SELECT pick,COUNT(*) FROM vs_votes WHERE poll_id=? AND used=1 GROUP BY pick', (p['id'],)).fetchall())
            p['talks'] = db.execute('SELECT COUNT(*) FROM vs_comments WHERE poll_id=? AND hidden=0', (p['id'],)).fetchone()[0]
        p['n_a'], p['n_b'] = n.get('a', 0), n.get('b', 0); p['n'] = p['n_a'] + p['n_b']
        p['pct_a'] = round(100 * p['n_a'] / p['n']) if p['n'] else 50; p['pct_b'] = 100 - p['pct_a'] if p['n'] else 50
        p['used_a'], p['used_b'] = used.get('a', 0), used.get('b', 0)
        p['state'] = poll_state(p); p['emoji'] = vs_emoji.get(p['cat'], '💬')
        p['mine'] = mine
        return p

    def my_votes(ids):
        if not ids: return {}
        with conn() as db:
            return dict(db.execute('SELECT poll_id,pick FROM vs_votes WHERE voter=? AND poll_id IN (%s)' % ','.join('?' * len(ids)), [S.voter_id()] + list(ids)).fetchall())

    def vs_rows(limit=10, cat='', state='', offset=0):
        where, args = ['hidden=0' + S.not_blocked()], []
        if cat: where.append('cat=?'); args.append(cat)
        if state == 'open': where.append("ending='' AND ends>?"); args.append(stamp())
        if state == 'done': where.append("ending!=''")
        with conn() as db:
            rows = db.execute('SELECT * FROM vs_polls WHERE ' + ' AND '.join(where) + ' ORDER BY id DESC LIMIT ? OFFSET ?', args + [limit, offset]).fetchall()
            total = db.execute('SELECT COUNT(*) FROM vs_polls WHERE ' + ' AND '.join(where), args).fetchone()[0]
        mine = my_votes([r['id'] for r in rows])
        return [poll_view(r, mine.get(r['id'])) for r in rows], total

    @app.route('/vs')
    def vs_home():
        cat = request.args.get('cat', ''); cat = cat if cat in vs_emoji else ''
        state = request.args.get('state', ''); state = state if state in ('open', 'done') else ''
        page = max(1, request.args.get('page', 1, type=int))
        rows, total = vs_rows(PAGE, cat, state, (page - 1) * PAGE)
        pages = max(1, -(-total // PAGE))
        if page > pages: abort(404)
        return render_template('soboru_vs.html', rows=rows, cat=cat, state=state, page=page, pages=pages, total=total)

    @app.route('/vs/new', methods=['GET', 'POST'])
    @S.member_only
    def vs_new():
        f = request.form
        if request.method == 'POST':
            if f.get('website'): abort(400)
            cat = f.get('cat', ''); a = ' '.join(f.get('a', '').split()); b = ' '.join(f.get('b', '').split())
            title = ' '.join(f.get('title', '').split()) or (f'{a} vs {b}' if a and b else '')
            body = f.get('body', '').strip(); days = f.get('days', 3, type=int)
            err = None
            if cat not in vs_emoji: err = S.ui_text('vs.e_cat', '분야를 골라 주세요.')
            elif not (1 <= len(a) <= 30 and 1 <= len(b) <= 30) or a == b: err = S.ui_text('vs.e_opt', '고를 것 두 가지를 30자 안으로 다르게 적어 주세요.')
            elif not 2 <= len(title) <= 80: err = S.ui_text('vs.e_title', '제목은 2~80자로 적어 주세요.')
            elif len(body) > 1000: err = S.ui_text('vs.e_body', '고민 내용은 1,000자 안으로 적어 주세요.')
            elif days not in VS_DAYS: err = S.ui_text('vs.e_days', '마감 기간을 골라 주세요.')
            with conn() as db:
                if not err and S.recent_count(db, 'vs_polls', 10) >= 3: err = S.ui_text('msg.m11', '잠시 후 다시 올려 주세요. 10분에 3개까지 쓸 수 있어요.')
                if err: flash(err); return render_template('soboru_vs_new.html', f=f), 400
                ends = (datetime.datetime.now() + datetime.timedelta(days=days)).isoformat(timespec='seconds')
                pid = db.execute('INSERT INTO vs_polls(cat,title,body,a,b,user_id,nickname,ends,ip_hash,created) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                 (cat, title, body, a, b, g.user['id'], g.user['nickname'], ends, S.ip_hash(), stamp())).lastrowid
            return redirect(url_for('vs_post', poll_id=pid))
        return render_template('soboru_vs_new.html', f={})

    def poll_or_404(db, poll_id):
        p = db.execute('SELECT * FROM vs_polls WHERE id=?', (poll_id,)).fetchone()
        if not p or (p['hidden'] and not S.admin_active()): abort(404)
        return p

    @app.route('/vs/<int:poll_id>')
    def vs_post(poll_id):
        with conn() as db:
            p = poll_or_404(db, poll_id)
            db.execute('UPDATE vs_polls SET views=views+1 WHERE id=?', (poll_id,))
            talks = db.execute('SELECT * FROM vs_comments WHERE poll_id=? AND hidden=0' + S.not_blocked() + ' ORDER BY id', (poll_id,)).fetchall()
        p = poll_view(p, my_votes([poll_id]).get(poll_id))
        own = bool(g.user and p['user_id'] == g.user['id'])
        more, _ = vs_rows(4, p['cat'])
        return render_template('soboru_vs_post.html', p=p, talks=talks, own=own, more=[m for m in more if m['id'] != poll_id][:3])

    @app.route('/vs/<int:poll_id>/vote', methods=['POST'])
    def vs_vote(poll_id):
        pick = request.form.get('pick')
        if pick not in ('a', 'b'): abort(400)
        with conn() as db:
            p = poll_or_404(db, poll_id)
            if poll_state(p) != 'open': flash(S.ui_text('vs.closed', '마감된 고민이에요.'))
            elif db.execute('INSERT OR IGNORE INTO vs_votes(poll_id,voter,pick,used,user_id,created) VALUES(?,?,?,?,?,?)',
                            (poll_id, S.voter_id(), pick, 1 if request.form.get('used') else 0, g.user['id'] if g.user else None, stamp())).rowcount:
                got = award(db, g.user['id'], 'vote', 'v%d' % poll_id) if g.user and p['user_id'] != g.user['id'] else 0
                flash(S.ui_text('vs.voted_p', '골라 줘서 고마워요! {n}P를 받았어요.').replace('{n}', str(got)) if got else S.ui_text('vs.voted', '골라 줘서 고마워요!'))
            else: flash(S.ui_text('vs.already', '이미 골라 준 고민이에요.'))
        back = request.form.get('next', '')
        return redirect(back if back.startswith('/vs') and '//' not in back else url_for('vs_post', poll_id=poll_id))

    @app.route('/vs/<int:poll_id>/talk', methods=['POST'])
    @S.member_only
    def vs_talk(poll_id):
        body = request.form.get('body', '').strip()
        with conn() as db:
            poll_or_404(db, poll_id)
            if not 1 <= len(body) <= 300: flash(S.ui_text('vs.e_talk', '한마디는 300자 안으로 적어 주세요.'))
            elif db.execute('SELECT COUNT(*) FROM vs_comments WHERE user_id=? AND created>=?', (g.user['id'], (datetime.datetime.now() - datetime.timedelta(minutes=2)).isoformat(timespec='seconds'))).fetchone()[0] >= 5: flash(S.ui_text('msg.m13', '잠시 후 다시 남겨 주세요.'))
            else:
                mine = db.execute('SELECT pick FROM vs_votes WHERE poll_id=? AND voter=?', (poll_id, S.voter_id())).fetchone()
                cid = db.execute('INSERT INTO vs_comments(poll_id,user_id,nickname,body,pick,created) VALUES(?,?,?,?,?,?)',
                                 (poll_id, g.user['id'], g.user['nickname'], body, mine['pick'] if mine else '', stamp())).lastrowid
                award(db, g.user['id'], 'comment', 'vc%d' % cid)
        return redirect(url_for('vs_post', poll_id=poll_id) + '#talk')

    @app.route('/vs/<int:poll_id>/end', methods=['POST'])
    @S.member_only
    def vs_end(poll_id):
        # 글쓴이가 결말(결국 무엇을 골랐는지)을 남김. 남기면 투표는 끝남
        pick = request.form.get('ending'); note = request.form.get('note', '').strip()[:300]
        with conn() as db:
            p = poll_or_404(db, poll_id)
            if p['user_id'] != g.user['id']: abort(403)
            if pick not in ('a', 'b') or p['ending']: abort(400)
            db.execute('UPDATE vs_polls SET ending=?,ending_note=?,ends=MIN(ends,?) WHERE id=?', (pick, note, stamp(), poll_id))
            got = award(db, g.user['id'], 'vs_end', 'e%d' % poll_id)
        flash(S.ui_text('vs.ended', '결말을 남겼어요. {n}P를 받았어요.').replace('{n}', str(got)))
        return redirect(url_for('vs_post', poll_id=poll_id))

    @app.route('/vs/<int:poll_id>/delete', methods=['POST'])
    def vs_delete(poll_id):
        with conn() as db:
            p = poll_or_404(db, poll_id)
            if not (S.admin_active() or (g.user and p['user_id'] == g.user['id'])): abort(403)
            for t in ('vs_votes', 'vs_comments'): db.execute(f'DELETE FROM {t} WHERE poll_id=?', (poll_id,))
            db.execute('DELETE FROM vs_polls WHERE id=?', (poll_id,))
        flash(S.ui_text('msg.m16', '삭제했어요.'))
        return redirect(url_for('vs_home'))

    # ---- 수다방 -----------------------------------------------------------
    def today_topic():
        topics = [t.strip() for t in S.ui_text('suda.topics', '요즘 제일 잘 산 물건 하나만 자랑해 주세요\n이번 달 카드값, 어디서 제일 많이 나갔나요?\n'
                                               '환불 받느라 고생했던 이야기 풀어 주세요\n월급날 나를 위한 작은 선물, 뭐 사세요?\n'
                                               '사지 말걸 후회한 물건 있나요?\n구독 서비스 몇 개나 쓰고 계세요?\n동네 단골집 자랑해 주세요').split('\n') if t.strip()]
        return topics[datetime.date.today().toordinal() % len(topics)] if topics else ''

    def suda_rows(limit=20, head='', hot=False, offset=0):
        where, args = ["kind IN ('post','tip','question')", 'hidden=0' + S.not_blocked()], []
        if head:
            kind = HEAD_KIND.get(head)
            where.append('(head=? OR (head=\'\' AND kind=?))' if kind or head == '잡담' else 'head=?')
            args += [head, kind or 'post'] if kind or head == '잡담' else [head]
        if hot: where.append('likes>0')
        sql = ' AND '.join(where)
        with conn() as db:
            total = db.execute('SELECT COUNT(*) FROM posts WHERE ' + sql, args).fetchone()[0]
            rows = db.execute(f"SELECT * FROM posts WHERE {sql} ORDER BY {'likes DESC,comments DESC,' if hot else ''}id DESC LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
        return [suda_view(r) for r in rows], total

    @app.route('/suda')
    def suda():
        head = request.args.get('head', ''); head = head if head in SUDA_HEADS else ''
        hot = request.args.get('sort') == 'hot'
        page = max(1, request.args.get('page', 1, type=int))
        rows, total = suda_rows(PAGE, head, hot, (page - 1) * PAGE)
        pages = max(1, -(-total // PAGE))
        if page > pages: abort(404)
        return render_template('soboru_suda.html', rows=rows, head=head, hot=hot, page=page, pages=pages, total=total, topic=today_topic())

    # ---- 포인트 통장 -------------------------------------------------------
    @app.route('/me/points')
    @S.member_only
    def my_points():
        with conn() as db:
            rows = db.execute('SELECT * FROM points WHERE user_id=? ORDER BY id DESC LIMIT 100', (g.user['id'],)).fetchall()
        return render_template('soboru_points.html', rows=rows, total=point_total(g.user['id']))

    # ---- 후기 에디터 모집 ----------------------------------------------------
    def editor_products():
        out = []
        for line in S.ui_text('editor.products', '무선 이어폰|25\n에어프라이어|25\n선크림|25\n물걸레 로봇청소기|25').split('\n'):
            name, _, cap = line.partition('|')
            if name.strip(): out.append((name.strip()[:40], int(cap) if cap.strip().isdigit() else 25))
        return out

    def drop_old_apps(db):
        # 선정하지 않은(새 신청·선정 안 함) 신청서는 30일이 지나면 지움 (신청 화면에 알린 그대로)
        since = (datetime.datetime.now() - datetime.timedelta(days=EDITOR_KEEP_DAYS)).isoformat(timespec='seconds')
        db.execute("DELETE FROM editor_apps WHERE status IN ('new','no') AND created<?", (since,))

    def seats(db):
        taken = {}
        for r in db.execute("SELECT products FROM editor_apps WHERE status IN ('pick','paid')"):
            for name in json.loads(r['products'] or '[]'): taken[name] = taken.get(name, 0) + 1
        return [(name, cap, max(0, cap - taken.get(name, 0))) for name, cap in editor_products()]

    @app.route('/editor', methods=['GET', 'POST'])
    def editor():
        f = request.form
        with conn() as db:
            drop_old_apps(db)
            rows = seats(db)
            if request.method == 'POST':
                if f.get('website'): abort(400)
                name = ' '.join(f.get('name', '').split()); phone = re.sub(r'[^\d]', '', f.get('phone', ''))
                open_names = [n for n, _, left in rows if left]
                picked = [p for p in f.getlist('product') if p in open_names][:2]
                other = ' '.join(f.get('other', '').split())[:40]
                if other: picked.append('그 밖에: ' + other)
                err = None
                if not 1 <= len(name) <= 20: err = S.ui_text('editor.e_name', '호칭을 20자 안으로 적어 주세요.')
                elif not re.fullmatch(r'01\d{8,9}', phone): err = S.ui_text('editor.e_phone', '휴대폰 번호를 확인해 주세요.')
                elif not picked: err = S.ui_text('editor.e_product', '쓰고 있는 제품을 골라 주세요.')
                elif f.get('receipt') not in ('1', '0'): err = S.ui_text('editor.e_receipt', '영수증이나 주문 내역이 있는지 골라 주세요.')
                elif not f.get('agree'): err = S.ui_text('editor.e_agree', '개인정보 수집에 동의해 주세요.')
                elif db.execute('SELECT COUNT(*) FROM editor_apps WHERE ip_hash=? AND created>=?', (S.ip_hash(), datetime.date.today().isoformat())).fetchone()[0] >= 3:
                    err = S.ui_text('msg.m13', '잠시 후 다시 남겨 주세요.')
                if err:
                    flash(err); return render_template('soboru_editor.html', rows=rows, f=f), 400
                db.execute('INSERT INTO editor_apps(name,phone,products,receipt,user_id,ip_hash,created) VALUES(?,?,?,?,?,?,?)',
                           (name, phone, json.dumps(picked, ensure_ascii=False), int(f['receipt']), g.user['id'] if g.user else None, S.ip_hash(), stamp()))
                flash(S.ui_text('editor.sent', '신청을 받았어요. 선정되면 적어 주신 번호로 연락드릴게요.'))
                return redirect(url_for('editor') + '#apply')
        return render_template('soboru_editor.html', rows=rows, f={})

    @app.route('/admin/editors', methods=['GET', 'POST'])
    @S.admin_only
    def admin_editors():
        with conn() as db:
            drop_old_apps(db)
            if request.method == 'POST':
                status = request.form.get('status', '')
                if status not in EDITOR_STATUS: abort(400)
                db.execute('UPDATE editor_apps SET status=?,note=? WHERE id=?', (status, request.form.get('note', '').strip()[:1000], request.form.get('id', type=int)))
                flash('저장했어요.'); return redirect(url_for('admin_editors', show=request.args.get('show', 'new')))
            show = request.args.get('show', 'new'); show = show if show in EDITOR_STATUS else 'new'
            rows = [dict(r, products=json.loads(r['products'] or '[]')) for r in db.execute('SELECT * FROM editor_apps WHERE status=? ORDER BY id DESC LIMIT 300', (show,))]
            counts = dict(db.execute('SELECT status,COUNT(*) FROM editor_apps GROUP BY status').fetchall())
            left = seats(db)
        return render_template('admin_editors.html', rows=rows, show=show, statuses=EDITOR_STATUS, counts=counts, left=left, keep=EDITOR_KEEP_DAYS)

    app.jinja_env.globals.update(receipts_waiting=receipts_waiting, vs_rows=vs_rows, suda_rows=suda_rows, today_topic=today_topic)
    S.award = award
    app.extensions['soboru_cm'] = {'award': award, 'point_total': point_total, 'vs_rows': vs_rows, 'suda_rows': suda_rows, 'today_topic': today_topic}
