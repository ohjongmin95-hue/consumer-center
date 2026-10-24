"""소보루 이웃 (브런치처럼, 운영자 요청 2026-10-24): 회원 프로필(사진·소개) · 이웃 페이지 · 구독 · 새 글 알림.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다. 커뮤니티를 강조하려고, 글쓴이를 눌러 그 사람의 글을 모아 보고 구독할 수 있게 한다.
- 프로필(/me/people): 사진 한 장(EXIF 지운 JPG·PNG·WEBP)과 소개 한 줄(80자). 닉네임은 내 정보에서 바꾼다.
- 이웃 페이지(/u/<번호>): 사진·닉네임·소개, 글 수·구독자 수·받은 좋아요, 구독하기, 쓴 글 목록(숨긴 글 빼고).
- 구독(/u/<번호>/follow): 회원만, 나 자신은 안 됨. 한 번 더 누르면 구독 취소. 구독하면 그 이웃에게 알림.
- 구독한 이웃이 글을 올리면 구독자에게 알림(BOARD_HOOKS 'post'). 구독 피드(/me/following)에서 모아 본다.
- 좋아요는 게시판의 '좋아요'(board_votes)를 그대로 쓴다.
- 탈퇴하면 프로필·구독이 함께 지워진다(사진 파일 포함).
"""
import datetime, re, secrets
from flask import abort, flash, g, redirect, render_template, request, send_file, url_for

BIO_MAX = 80
FEED_N = 40
TOP_N = 6
PHOTO_RE = re.compile(r'[0-9a-f]{32}\.(jpg|png|webp)')
TYPES = {'jpg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp'}


def stamp(): return datetime.datetime.now().isoformat(timespec='seconds')


def migrate(db):
    db.execute("CREATE TABLE IF NOT EXISTS profiles(user_id INTEGER PRIMARY KEY,bio TEXT NOT NULL DEFAULT '',photo TEXT NOT NULL DEFAULT '',updated TEXT NOT NULL)")
    db.execute('CREATE TABLE IF NOT EXISTS follows(follower INTEGER NOT NULL,followee INTEGER NOT NULL,created TEXT NOT NULL,PRIMARY KEY(follower,followee))')
    db.execute('CREATE INDEX IF NOT EXISTS follows_followee ON follows(followee)')


def install(S):
    app = S.app; conn = S.conn
    folder = S.UPLOAD / 'avatars'; folder.mkdir(parents=True, exist_ok=True)
    with conn() as db: migrate(db)

    # ---- 프로필 읽기 (요청마다 한 번) -------------------------------------------------
    def photos():
        if 'people_photos' not in g:
            with conn() as db: g.people_photos = {r['user_id']: r['photo'] for r in db.execute("SELECT user_id,photo FROM profiles WHERE photo!=''")}
        return g.people_photos

    def avatar_url(user_id):
        name = photos().get(user_id) if user_id else None
        return url_for('people_photo', name=name) if name else ''

    def profile(db, user_id):
        u = db.execute("SELECT id,nickname,created FROM users WHERE id=? AND status='active'", (user_id,)).fetchone()
        if not u: return None
        p = db.execute('SELECT bio,photo FROM profiles WHERE user_id=?', (user_id,)).fetchone()
        st = db.execute('SELECT COUNT(*),COALESCE(SUM(likes),0) FROM posts WHERE user_id=? AND hidden=0', (user_id,)).fetchone()
        return {'id': u['id'], 'nickname': u['nickname'], 'since': u['created'][:7].replace('-', '.'), 'bio': p['bio'] if p else '', 'photo': p['photo'] if p else '',
                'posts': st[0], 'likes': st[1], 'followers': db.execute('SELECT COUNT(*) FROM follows WHERE followee=?', (user_id,)).fetchone()[0],
                'following': db.execute('SELECT COUNT(*) FROM follows WHERE follower=?', (user_id,)).fetchone()[0]}

    def is_following(user_id):
        if not g.user or not user_id: return False
        if 'people_follows' not in g:
            with conn() as db: g.people_follows = {r[0] for r in db.execute('SELECT followee FROM follows WHERE follower=?', (g.user['id'],))}
        return user_id in g.people_follows

    def top_writers(db, exclude=()):
        # 추천 이웃: 최근 30일 받은 좋아요가 많은 회원 (구독 피드가 비었을 때 보여 줌)
        since = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat(timespec='seconds')
        rows = db.execute("SELECT p.user_id,SUM(p.likes) AS l,COUNT(*) AS n FROM posts p JOIN users u ON u.id=p.user_id WHERE p.hidden=0 AND u.status='active' AND p.created>=? "
                          'GROUP BY p.user_id ORDER BY l DESC,n DESC LIMIT ?', (since, TOP_N + len(exclude))).fetchall()
        return [x for x in (profile(db, r['user_id']) for r in rows if r['user_id'] not in exclude) if x][:TOP_N]

    # ---- 이웃 페이지 --------------------------------------------------------------
    @app.route('/u/<int:user_id>')
    def person(user_id):
        with conn() as db:
            p = profile(db, user_id)
            if not p: abort(404)
            rows = db.execute('SELECT ' + S.FEED_COLS + ' FROM posts WHERE user_id=? AND hidden=0' + S.not_blocked() + ' ORDER BY id DESC LIMIT 60', (user_id,)).fetchall()
        return render_template('soboru_person.html', p=p, rows=rows, mine=bool(g.user and g.user['id'] == user_id))

    @app.route('/people/photo/<name>')
    def people_photo(name):
        if not PHOTO_RE.fullmatch(name): abort(404)
        with conn() as db:
            ok = db.execute("SELECT 1 FROM profiles p JOIN users u ON u.id=p.user_id WHERE p.photo=? AND u.status='active'", (name,)).fetchone()
        if not ok or not (folder / name).is_file(): abort(404)
        resp = send_file(folder / name, mimetype=TYPES[name.rsplit('.', 1)[1]], max_age=3600)
        resp.headers['Content-Security-Policy'] = "default-src 'none'"; resp.headers['Content-Disposition'] = 'inline'
        return resp

    @app.route('/u/<int:user_id>/follow', methods=['POST'])
    @S.member_only
    def follow(user_id):
        if user_id == g.user['id']: abort(400)
        with conn() as db:
            if not profile(db, user_id): abort(404)
            if db.execute('DELETE FROM follows WHERE follower=? AND followee=?', (g.user['id'], user_id)).rowcount:
                flash(S.ui_text('pp.unfollowed', '구독을 취소했어요.'))
            else:
                db.execute('INSERT INTO follows(follower,followee,created) VALUES(?,?,?)', (g.user['id'], user_id, stamp()))
                S.member_alert(db, user_id, 'follow', S.ui_text('pp.alert_follow', '{name}님이 나를 구독했어요').replace('{name}', g.user['nickname']), url_for('person', user_id=g.user['id']))
                flash(S.ui_text('pp.followed', '구독했어요. 새 글이 올라오면 알려 드릴게요.'))
        back = request.form.get('next', '')
        return redirect(back if back.startswith('/') and not back.startswith('//') else url_for('person', user_id=user_id))

    # ---- 구독 피드 -----------------------------------------------------------------
    @app.route('/me/following')
    @S.member_only
    def following():
        with conn() as db:
            ids = [r[0] for r in db.execute('SELECT followee FROM follows WHERE follower=? ORDER BY created DESC', (g.user['id'],))]
            people = [x for x in (profile(db, i) for i in ids) if x]
            rows = db.execute('SELECT ' + S.FEED_COLS + f" FROM posts WHERE hidden=0 AND user_id IN ({','.join('?' * len(ids))})" + S.not_blocked() + ' ORDER BY id DESC LIMIT ?',
                              ids + [FEED_N]).fetchall() if ids else []
            top = top_writers(db, set(ids) | {g.user['id']})
        return render_template('soboru_following.html', people=people, rows=rows, top=top)

    # ---- 내 프로필 고치기 ------------------------------------------------------------
    @app.route('/me/people', methods=['GET', 'POST'])
    @S.member_only
    def my_profile():
        uid = g.user['id']
        with conn() as db:
            old = db.execute('SELECT bio,photo FROM profiles WHERE user_id=?', (uid,)).fetchone()
            bio, photo = (old['bio'], old['photo']) if old else ('', '')
            if request.method == 'POST':
                bio = ' '.join(request.form.get('bio', '').split())[:BIO_MAX]
                up = request.files.get('photo')
                if request.form.get('drop_photo'): drop(photo); photo = ''
                elif up and up.filename:
                    data, kind = S.clean_photo(up.stream.read(S.BOARD_PHOTO_MAX + 1))
                    if not data: flash(S.ui_text('pp.bad_photo', '사진은 8MB 이하 JPG·PNG·WEBP로 올려 주세요.')); return redirect(url_for('my_profile'))
                    name = secrets.token_hex(16) + '.' + kind; (folder / name).write_bytes(data); drop(photo); photo = name
                db.execute('INSERT INTO profiles(user_id,bio,photo,updated) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET bio=excluded.bio,photo=excluded.photo,updated=excluded.updated',
                           (uid, bio, photo, stamp()))
                flash(S.ui_text('pp.saved', '프로필을 저장했어요.'))
                return redirect(url_for('person', user_id=uid))
            p = profile(db, uid)
        return render_template('soboru_profile_edit.html', p=p, bio_max=BIO_MAX)

    def drop(name):
        if name and PHOTO_RE.fullmatch(name): (folder / name).unlink(missing_ok=True)

    # ---- 새 글 알림: 구독한 이웃이 글을 올리면 ----------------------------------------------
    def on_board(event, db, **kw):
        if event != 'post' or not g.get('user'): return
        post = db.execute('SELECT id,title,hidden FROM posts WHERE id=?', (kw['post_id'],)).fetchone()
        if not post or post['hidden']: return
        text = S.ui_text('pp.alert_post', '{name}님이 새 글을 올렸어요').replace('{name}', g.user['nickname']) + ': ' + post['title'][:40]
        for r in db.execute('SELECT follower FROM follows WHERE followee=? LIMIT 2000', (g.user['id'],)).fetchall():
            S.member_alert(db, r['follower'], 'follow', text, url_for('board_post', post_id=post['id']), push=False)
    S.BOARD_HOOKS.append(on_board)

    # ---- 탈퇴: 프로필·구독도 지움 -------------------------------------------------------
    def forget(db, user_id):
        p = db.execute('SELECT photo FROM profiles WHERE user_id=?', (user_id,)).fetchone()
        if p: drop(p['photo'])
        db.execute('DELETE FROM profiles WHERE user_id=?', (user_id,))
        db.execute('DELETE FROM follows WHERE follower=? OR followee=?', (user_id, user_id))
        db.execute('DELETE FROM saves WHERE user_id=?', (user_id,))  # 담아 둔 글 (soboru_cm.py)
    S.MEMBER_DELETE_HOOKS.append(forget)

    def people_profile(user_id):
        if not user_id: return None
        with conn() as db: return profile(db, user_id)

    app.jinja_env.globals.update(avatar_url=avatar_url, is_following=is_following, people_profile=people_profile)
