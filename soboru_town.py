"""우리 동네 정보 (운영자 요청 2026-10-24, 육아크루 '동네 육아 정보'처럼): 동네 이웃이 직접 추천하는 맛집·병원·시장·놀 곳.

- /town: 시·도 + 시·군·구를 고르면 그 동네 추천 장소를 분류별로 봄. 옆 칸엔 같은 동네 내돈내산 장소 후기·사장님 소식·동네일자리.
- /town/new: 회원이 장소를 추천 (이름, 분류, 동, 한 줄 소개, 좋은 점 3개까지). 하루 5곳까지.
- /town/<id>: 추천 글 + '나도 추천해요' + 이웃 한마디(댓글). 신고 3번이면 가리고, 운영자·글쓴이가 내릴 수 있음.
- 가게 홍보는 사장님 소식으로 (여기는 이웃 추천만). 지역 목록은 동네일자리(soboru_jobs.REGIONS)와 같음.
"""
import datetime, re
from flask import abort, flash, g, redirect, render_template, request, url_for

from soboru_jobs import REGIONS

# 분류: 이름 → (이모지, 색 번호). 회색은 쓰지 않음 (운영자 2026-10-24: 칙칙함)
CATS = {'맛집': ('🍜', 0), '카페·빵집': ('☕', 1), '병원·약국': ('🏥', 2), '시장·마트': ('🛒', 3), '아이랑': ('🧸', 4), '운동': ('💪', 5),
        '공원·산책': ('🌳', 6), '생활·수리': ('🛠️', 7), '관공서·공공': ('🏛️', 8), '반려동물': ('🐶', 9), '기타': ('📍', 10)}
GOODS = ['가격이 착해요', '친절해요', '주차 돼요', '아이랑 가기 좋아요', '혼자 가기 좋아요', '늦게까지 해요', '주말에도 열어요', '예약하면 좋아요', '깨끗해요', '양이 많아요']
REPORT_REASONS = ['광고·홍보 글', '없는 곳·틀린 정보', '욕설·비방', '개인정보 노출']
REPORT_HIDE = 3
DAILY = 5
PAGE = 24


def now(): return datetime.datetime.now().isoformat(timespec='seconds')


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS town_places(id INTEGER PRIMARY KEY,user_id INTEGER,nickname TEXT NOT NULL,sido TEXT NOT NULL,sgg TEXT NOT NULL,
        dong TEXT NOT NULL DEFAULT '',cat TEXT NOT NULL,name TEXT NOT NULL,addr TEXT NOT NULL DEFAULT '',tip TEXT NOT NULL,goods TEXT NOT NULL DEFAULT '',
        likes INTEGER NOT NULL DEFAULT 0,talks INTEGER NOT NULL DEFAULT 0,views INTEGER NOT NULL DEFAULT 0,reports INTEGER NOT NULL DEFAULT 0,
        hidden INTEGER NOT NULL DEFAULT 0,ip_hash TEXT NOT NULL DEFAULT '',created TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS town_places_area ON town_places(sido,sgg)')
    db.execute('CREATE TABLE IF NOT EXISTS town_likes(place_id INTEGER NOT NULL,user_id INTEGER NOT NULL,created TEXT NOT NULL,PRIMARY KEY(place_id,user_id))')
    db.execute('''CREATE TABLE IF NOT EXISTS town_talks(id INTEGER PRIMARY KEY,place_id INTEGER NOT NULL,user_id INTEGER,nickname TEXT NOT NULL,body TEXT NOT NULL,
        hidden INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS town_talks_place ON town_talks(place_id)')
    db.execute('CREATE TABLE IF NOT EXISTS town_reports(place_id INTEGER NOT NULL,user_id INTEGER NOT NULL,reason TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(place_id,user_id))')


def region_of(a):
    sido = a.get('sido', ''); sido = sido if sido in REGIONS else ''
    sgg = a.get('sgg', ''); sgg = sgg if sido and sgg in REGIONS[sido] else ''
    return sido, sgg


def view(r):
    r = dict(r)
    cat = r['cat'] if r['cat'] in CATS else '기타'
    r['emoji'], r['z'] = CATS[cat]
    r['goods_list'] = [x for x in (r.get('goods') or '').split(',') if x]
    r['area'] = ' '.join(x for x in (r['sgg'], r['dong']) if x)
    return r


def install(S):
    app = S.app; conn = S.conn
    with conn() as db: migrate(db)

    def get_place(pid):
        with conn() as db: r = db.execute('SELECT * FROM town_places WHERE id=?', (pid,)).fetchone()
        if not r or (r['hidden'] and not S.admin_active() and not (g.user and g.user['id'] == r['user_id'])): abort(404)
        return r

    def area_where(sido, sgg, col_sgg='sgg'):
        if not sido: return '', []
        return (f' AND sido=? AND {col_sgg}=?', [sido, sgg]) if sgg else (' AND sido=?', [sido])

    def neighbors(sido, sgg):
        """같은 동네 다른 소식: 내돈내산 장소 후기 · 사장님 소식 · 동네일자리"""
        out = {'reviews': [], 'owners': [], 'jobs': [], 'n_jobs': 0}
        if not sido: return out
        with conn() as db:
            w, a = area_where(sido, sgg, 'gu')
            out['reviews'] = db.execute(f"SELECT id,title,rv_cat,likes FROM posts WHERE hidden=0 AND kind='review' AND rv_type='place'{w} ORDER BY id DESC LIMIT 3", a).fetchall()
            w, a = area_where(sido, sgg)
            out['owners'] = db.execute(f'SELECT id,shop,head,title FROM owner_news WHERE hidden=0{w} ORDER BY id DESC LIMIT 3', a).fetchall()
            w, a = area_where(sido, sgg, 'sigungu')
            out['jobs'] = db.execute(f"SELECT id,title,company FROM jobs WHERE status='open' AND hidden=0{w} ORDER BY src='own' DESC,created DESC LIMIT 3", a).fetchall()
            out['n_jobs'] = db.execute(f"SELECT COUNT(*) FROM jobs WHERE status='open' AND hidden=0{w}", a).fetchone()[0]
        return out

    @app.route('/town')
    def town():
        sido, sgg = region_of(request.args)
        cat = request.args.get('c', ''); cat = cat if cat in CATS else ''
        sort = 'like' if request.args.get('s') == 'like' else 'new'
        page = max(1, request.args.get('page', 1, type=int))
        where, args = 'hidden=0', []
        w, a = area_where(sido, sgg); where += w; args += a
        with conn() as db:
            counts = {r[0]: r[1] for r in db.execute(f'SELECT cat,COUNT(*) FROM town_places WHERE {where} GROUP BY cat', args)}
            if cat: where += ' AND cat=?'; args.append(cat)
            total = db.execute(f'SELECT COUNT(*) FROM town_places WHERE {where}', args).fetchone()[0]
            order = 'likes DESC,id DESC' if sort == 'like' else 'id DESC'
            rows = db.execute(f'SELECT * FROM town_places WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?', args + [PAGE, (page - 1) * PAGE]).fetchall()
            w, a = area_where(sido, sgg)
            best = db.execute(f'SELECT * FROM town_places WHERE hidden=0 AND likes>0{w} ORDER BY likes DESC,id DESC LIMIT 3', a).fetchall() if not cat and page == 1 else []
            areas = db.execute('SELECT sido,sgg,COUNT(*) n FROM town_places WHERE hidden=0 GROUP BY sido,sgg ORDER BY n DESC LIMIT 8').fetchall() if not sido else []
            liked = {r[0] for r in db.execute('SELECT place_id FROM town_likes WHERE user_id=?', (g.user['id'],))} if g.user else set()
        pages = max(1, -(-total // PAGE))
        if page > pages: abort(404)
        return render_template('soboru_town.html', rows=[view(r) for r in rows], best=[view(r) for r in best], areas=areas, counts=counts, total=total,
                               sido=sido, sgg=sgg, cat=cat, sort=sort, page=page, pages=pages, liked=liked, nb=neighbors(sido, sgg))

    @app.route('/town/new', methods=['GET', 'POST'])
    @S.member_only
    def town_new():
        f = request.form
        if request.method == 'POST':
            if f.get('website'): abort(400)
            sido, sgg = region_of(f)
            cat = f.get('cat', ''); name = ' '.join(f.get('name', '').split()); dong = re.sub(r'[^가-힣0-9]', '', f.get('dong', ''))[:10]
            addr = ' '.join(f.get('addr', '').split())[:60]; tip = f.get('tip', '').strip()
            goods = [x for x in f.getlist('goods') if x in GOODS][:3]
            err = None
            if not sgg: err = S.ui_text('town.e_area', '동네(시·도와 시·군·구)를 골라 주세요.')
            elif cat not in CATS: err = S.ui_text('town.e_cat', '어떤 곳인지 분류를 골라 주세요.')
            elif not 1 <= len(name) <= 30: err = S.ui_text('town.e_name', '장소 이름을 30자 안으로 적어 주세요.')
            elif not 10 <= len(tip) <= 500: err = S.ui_text('town.e_tip', '추천하는 이유를 10~500자로 적어 주세요.')
            elif len(f.getlist('goods')) > 3: err = S.ui_text('town.e_goods', '좋은 점은 3개까지 고를 수 있어요.')
            with conn() as db:
                if not err and db.execute('SELECT COUNT(*) FROM town_places WHERE user_id=? AND created>=?', (g.user['id'], datetime.date.today().isoformat())).fetchone()[0] >= DAILY:
                    err = S.ui_text('town.e_daily', '동네 정보는 하루에 5곳까지 올릴 수 있어요.')
                if not err and db.execute('SELECT 1 FROM town_places WHERE hidden=0 AND sido=? AND sgg=? AND name=?', (sido, sgg, name)).fetchone():
                    err = S.ui_text('town.e_dup', '이 동네에 같은 이름의 장소가 이미 있어요. 그 글에 ‘나도 추천해요’를 눌러 주세요.')
                if err: flash(err); return render_template('soboru_town_new.html', f=f, goods=goods), 400
                cur = db.execute('INSERT INTO town_places(user_id,nickname,sido,sgg,dong,cat,name,addr,tip,goods,ip_hash,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                                 (g.user['id'], g.user['nickname'], sido, sgg, dong, cat, name, addr, tip, ','.join(goods), S.ip_hash(), now()))
            flash(S.ui_text('town.sent', '동네 정보를 올렸어요. 이웃에게 큰 도움이 될 거예요.'))
            return redirect(url_for('town_place', place_id=cur.lastrowid))
        sido, sgg = region_of(request.args)
        return render_template('soboru_town_new.html', f={'sido': sido, 'sgg': sgg, 'cat': request.args.get('c', '')}, goods=[])

    @app.route('/town/<int:place_id>')
    def town_place(place_id):
        r = get_place(place_id)
        with conn() as db:
            db.execute('UPDATE town_places SET views=views+1 WHERE id=?', (place_id,))
            talks = db.execute('SELECT * FROM town_talks WHERE place_id=? AND hidden=0 ORDER BY id', (place_id,)).fetchall()
            liked = bool(g.user and db.execute('SELECT 1 FROM town_likes WHERE place_id=? AND user_id=?', (place_id, g.user['id'])).fetchone())
            reported = bool(g.user and db.execute('SELECT 1 FROM town_reports WHERE place_id=? AND user_id=?', (place_id, g.user['id'])).fetchone())
            near = db.execute('SELECT * FROM town_places WHERE hidden=0 AND id!=? AND sido=? AND sgg=? ORDER BY cat=? DESC,likes DESC,id DESC LIMIT 4',
                              (place_id, r['sido'], r['sgg'], r['cat'])).fetchall()
        return render_template('soboru_town_place.html', p=view(r), talks=talks, liked=liked, reported=reported, near=[view(x) for x in near],
                               mine=bool(g.user and g.user['id'] == r['user_id']), reasons=REPORT_REASONS)

    @app.route('/town/<int:place_id>/like', methods=['POST'])
    @S.member_only
    def town_like(place_id):
        r = get_place(place_id)
        with conn() as db:
            if db.execute('DELETE FROM town_likes WHERE place_id=? AND user_id=?', (place_id, g.user['id'])).rowcount:
                db.execute('UPDATE town_places SET likes=MAX(0,likes-1) WHERE id=?', (place_id,))
            elif r['user_id'] != g.user['id']:
                db.execute('INSERT INTO town_likes(place_id,user_id,created) VALUES(?,?,?)', (place_id, g.user['id'], now()))
                db.execute('UPDATE town_places SET likes=likes+1 WHERE id=?', (place_id,))
            else: flash(S.ui_text('town.own_like', '내가 올린 곳에는 추천을 누를 수 없어요.'))
        return redirect(S.safe_next('town') if request.form.get('next') else url_for('town_place', place_id=place_id))

    @app.route('/town/<int:place_id>/talk', methods=['POST'])
    @S.member_only
    def town_talk(place_id):
        r = get_place(place_id); body = ' '.join(request.form.get('body', '').split())
        if not 2 <= len(body) <= 300: flash(S.ui_text('town.e_talk', '한마디는 2~300자로 적어 주세요.'))
        else:
            with conn() as db:
                db.execute('INSERT INTO town_talks(place_id,user_id,nickname,body,created) VALUES(?,?,?,?,?)', (place_id, g.user['id'], g.user['nickname'], body, now()))
                db.execute('UPDATE town_places SET talks=talks+1 WHERE id=?', (place_id,))
                if r['user_id'] and r['user_id'] != g.user['id'] and hasattr(S, 'member_alert'):
                    S.member_alert(db, r['user_id'], 'town', S.ui_text('town.alert_talk', '내가 추천한 동네 정보에 이웃 한마디가 달렸어요') + f": {r['name'][:30]}", url_for('town_place', place_id=place_id))
        return redirect(url_for('town_place', place_id=place_id) + '#talks')

    @app.route('/town/talk/<int:talk_id>/hide', methods=['POST'])
    @S.member_only
    def town_talk_hide(talk_id):
        with conn() as db:
            t = db.execute('SELECT * FROM town_talks WHERE id=?', (talk_id,)).fetchone()
            if not t: abort(404)
            if not (S.admin_active() or g.user['id'] == t['user_id']): abort(403)
            if not t['hidden']:
                db.execute('UPDATE town_talks SET hidden=1 WHERE id=?', (talk_id,)); db.execute('UPDATE town_places SET talks=MAX(0,talks-1) WHERE id=?', (t['place_id'],))
        return redirect(url_for('town_place', place_id=t['place_id']) + '#talks')

    @app.route('/town/<int:place_id>/report', methods=['POST'])
    @S.member_only
    def town_report(place_id):
        get_place(place_id); reason = request.form.get('reason', '')
        if reason not in REPORT_REASONS: abort(400)
        with conn() as db:
            if not db.execute('SELECT 1 FROM town_reports WHERE place_id=? AND user_id=?', (place_id, g.user['id'])).fetchone():
                db.execute('INSERT INTO town_reports(place_id,user_id,reason,created) VALUES(?,?,?,?)', (place_id, g.user['id'], reason, now()))
                db.execute('UPDATE town_places SET reports=reports+1 WHERE id=?', (place_id,))
                if db.execute('SELECT reports FROM town_places WHERE id=?', (place_id,)).fetchone()[0] >= REPORT_HIDE:
                    db.execute('UPDATE town_places SET hidden=1 WHERE id=?', (place_id,))
        flash(S.ui_text('town.reported', '신고했어요. 운영자가 확인할게요.'))
        return redirect(url_for('town'))

    @app.route('/town/<int:place_id>/hide', methods=['POST'])
    @S.member_only
    def town_hide(place_id):
        r = get_place(place_id)
        if not (S.admin_active() or g.user['id'] == r['user_id']): abort(403)
        with conn() as db: db.execute('UPDATE town_places SET hidden=1 WHERE id=?', (place_id,))
        flash(S.ui_text('town.hidden', '동네 정보를 내렸어요.'))
        return redirect(url_for('town', sido=r['sido'], sgg=r['sgg']))

    @app.route('/admin/town', methods=['GET', 'POST'])
    @S.admin_only
    def admin_town():
        if request.method == 'POST':
            act = request.form.get('act'); pid = request.form.get('place', type=int)
            with conn() as db:
                if act in ('hide', 'show') and pid:
                    db.execute('UPDATE town_places SET hidden=? WHERE id=?', (1 if act == 'hide' else 0, pid))
                    if act == 'show': db.execute('UPDATE town_places SET reports=0 WHERE id=?', (pid,)); db.execute('DELETE FROM town_reports WHERE place_id=?', (pid,))
                    flash('가렸어요.' if act == 'hide' else '다시 보이게 했어요.')
                elif act == 'delete' and pid:
                    for t in ('town_places WHERE id', 'town_likes WHERE place_id', 'town_talks WHERE place_id', 'town_reports WHERE place_id'):
                        db.execute(f'DELETE FROM {t}=?', (pid,))
                    flash('지웠어요.')
            return redirect(url_for('admin_town'))
        with conn() as db:
            k = {'open': db.execute('SELECT COUNT(*) FROM town_places WHERE hidden=0').fetchone()[0], 'hidden': db.execute('SELECT COUNT(*) FROM town_places WHERE hidden=1').fetchone()[0],
                 'areas': db.execute('SELECT COUNT(DISTINCT sido||sgg) FROM town_places WHERE hidden=0').fetchone()[0], 'talks': db.execute('SELECT COUNT(*) FROM town_talks WHERE hidden=0').fetchone()[0]}
            reported = db.execute("SELECT p.*,(SELECT GROUP_CONCAT(reason,' · ') FROM town_reports r WHERE r.place_id=p.id) AS why FROM town_places p WHERE p.reports>0 OR p.hidden=1 ORDER BY p.hidden DESC,p.reports DESC LIMIT 50").fetchall()
            recent = db.execute('SELECT * FROM town_places ORDER BY id DESC LIMIT 30').fetchall()
        return render_template('admin_town.html', k=k, reported=reported, recent=recent)

    def search(q, per):
        like = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        with conn() as db:
            return [view(r) for r in db.execute("SELECT * FROM town_places WHERE hidden=0 AND (name LIKE ? ESCAPE '\\' OR tip LIKE ? ESCAPE '\\' OR dong LIKE ? ESCAPE '\\' OR sgg LIKE ? ESCAPE '\\') "
                                                 'ORDER BY likes DESC,id DESC LIMIT ?', (like, like, like, like, per))]

    def on_delete(db, uid):   # 탈퇴: 추천·신고 기록 지우고 올린 글은 가림
        db.execute('DELETE FROM town_likes WHERE user_id=?', (uid,)); db.execute('DELETE FROM town_reports WHERE user_id=?', (uid,))
        db.execute('UPDATE town_places SET hidden=1 WHERE user_id=?', (uid,)); db.execute('UPDATE town_talks SET hidden=1 WHERE user_id=?', (uid,))
    if hasattr(S, 'MEMBER_DELETE_HOOKS'): S.MEMBER_DELETE_HOOKS.append(on_delete)

    app.jinja_env.globals.update(TOWN_CATS=CATS, TOWN_GOODS=GOODS)
    app.extensions['soboru_town'] = {'search': search}
