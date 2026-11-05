"""소보루 매거진 관리 > 광고 · 환경설정 · 접수글 (운영자 2026-11-05: ND CMS 관리 메뉴처럼. 게시판·플러그인은 매거진에 쓰임이 없어 뺌)

- 광고: 매거진 자리 세 곳(메인 HOT ISSUE 아래, 기사 본문 아래, 기사 목록 아래)에 배너 사진·주소·기간. 누른 횟수를 셈.
- 환경설정: 첫 화면·목록에 보일 분야와 순서, SNS 주소, 문의 메일, 독자 접수 받기.
- 접수글: 매거진 바닥글 '제보·문의'(soboru.co.kr/letter/contact)로 들어온 글. 90일 지나면 지움.
"""
import datetime
import json
import re

from flask import abort, flash, redirect, render_template, request, send_file, url_for
from markupsafe import Markup

AD_SLOTS = [('main', '메인 · HOT ISSUE 아래'), ('article', '기사 화면 · 본문 아래'), ('list', '기사 목록 · 목록 아래')]
SNS = [('instagram', '인스타그램'), ('youtube', '유튜브'), ('threads', '스레드'), ('x', 'X'), ('blog', '네이버 블로그')]
KINDS = ['기사 제보', '문의', '광고·제휴']
KEEP_DAYS = 90
SCHEMA = '''CREATE TABLE IF NOT EXISTS mag_inbox(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '', body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', created TEXT NOT NULL)'''


def install(S):
    from soboru import LIFE_CATEGORIES
    app, conn = S.app, S.conn
    with conn() as db: db.execute(SCHEMA)
    folder = S.UPLOAD / 'art'; folder.mkdir(parents=True, exist_ok=True)

    def setting(key, default):
        with conn() as db: row = db.execute('SELECT value FROM soboru_settings WHERE key=?', (key,)).fetchone()
        try: return json.loads(row[0]) if row else default
        except ValueError: return default

    def put(key, value):
        with conn() as db: db.execute('INSERT OR REPLACE INTO soboru_settings(key,value) VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))

    def now(): return datetime.datetime.now().isoformat(timespec='seconds')

    def web(u):
        u = (u or '').strip()
        return u if re.match(r'https://[^\s<>"]+$', u) or re.match(r'http://[^\s<>"]+$', u) else ''

    # ---- 환경설정 ----------------------------------------------------------------
    ALL = list(app.jinja_env.globals.get('mag_aisles') or LIFE_CATEGORIES)  # mag_seo가 정한 기본 순서

    def conf():
        c = setting('mag_conf', {})
        order = [x for x in c.get('aisles', ALL) if x in LIFE_CATEGORIES]
        return {'aisles': order, 'off': [x for x in c.get('off', []) if x in LIFE_CATEGORIES],
                'sns': {k: web(c.get('sns', {}).get(k)) for k, _ in SNS}, 'email': c.get('email', ''), 'inbox': c.get('inbox', True)}

    class Aisles:
        """템플릿의 mag_aisles: 환경설정 순서대로, 끈 분야는 빼고"""
        def __iter__(self):
            c = conf(); return iter([x for x in c['aisles'] + [x for x in ALL if x not in c['aisles']] if x not in c['off']])
        def __len__(self): return len(list(iter(self)))
    app.jinja_env.globals['mag_aisles'] = Aisles()
    app.jinja_env.globals['mag_conf'] = conf

    @app.route('/admin/magazine/settings', methods=['GET', 'POST'])
    @S.admin_only
    def mag_settings():
        if request.method == 'POST':
            f = request.form
            order = [x for x in f.getlist('aisle') if x in LIFE_CATEGORIES]
            email = f.get('email', '').strip()
            if email and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email): flash('문의 메일 주소를 다시 확인해 주세요.'); return redirect(url_for('mag_settings'))
            bad = [n for k, n in SNS if f.get('sns_' + k, '').strip() and not web(f.get('sns_' + k))]
            if bad: flash(', '.join(bad) + ' 주소는 https:// 로 시작하게 적어 주세요.'); return redirect(url_for('mag_settings'))
            put('mag_conf', {'aisles': order, 'off': [x for x in order if not f.get('on_' + x)], 'email': email, 'inbox': bool(f.get('inbox')),
                             'sns': {k: web(f.get('sns_' + k)) for k, _ in SNS}})
            flash('환경설정을 저장했어요.')
            return redirect(url_for('mag_settings'))
        c = conf()
        return render_template('mag_admin_settings.html', c=c, rows=c['aisles'] + [x for x in ALL if x not in c['aisles']], sns=SNS)

    # ---- 광고 --------------------------------------------------------------------
    def ads(): return setting('mag_ads', {})

    def live(ad):
        if not ad or not ad.get('on') or not ad.get('img') or not web(ad.get('url')): return False
        today = datetime.date.today().isoformat()
        return (not ad.get('start') or ad['start'] <= today) and (not ad.get('end') or today <= ad['end'])

    def mag_ad(slot):
        ad = ads().get(slot)
        if not live(ad): return ''
        return Markup('<aside class="mad mad-%s" aria-label="광고"><a href="%s" target="_blank" rel="sponsored noopener"><img src="%s" alt="%s" loading="lazy"></a><small>AD</small></aside>') % (
            slot, url_for('mag_ad_go', slot=slot), url_for('mag_ad_img', name=ad['img']), ad.get('alt') or '광고')
    app.jinja_env.globals['mag_ad'] = mag_ad

    @app.route('/art/ad/<name>')
    def mag_ad_img(name):
        if not re.fullmatch(r'ad-[a-z]+-\d{14}\.webp', name) or not (folder / name).is_file(): abort(404)
        return send_file(folder / name, mimetype='image/webp', max_age=86400 * 30)

    @app.route('/letter/ad/<slot>')
    def mag_ad_go(slot):
        a = ads(); ad = a.get(slot)
        if not live(ad): abort(404)
        ad['clicks'] = int(ad.get('clicks') or 0) + 1; put('mag_ads', a)
        return redirect(web(ad['url']), 302)

    @app.route('/admin/magazine/ads', methods=['GET', 'POST'])
    @S.admin_only
    def mag_ads_admin():
        if request.method == 'POST':
            f = request.form; slot = f.get('slot', '')
            if slot not in dict(AD_SLOTS): abort(400)
            a = ads(); ad = a.get(slot) or {}
            if f.get('act') == 'del':
                if ad.get('img'): (folder / ad['img']).unlink(missing_ok=True)
                a.pop(slot, None); put('mag_ads', a); flash('광고를 뺐어요.'); return redirect(url_for('mag_ads_admin'))
            url = f.get('url', '').strip()
            if url and not web(url): flash('광고 주소는 https:// 로 시작하게 적어 주세요.'); return redirect(url_for('mag_ads_admin'))
            pic = request.files.get('img')
            if pic and pic.filename:
                if pic.mimetype not in ('image/jpeg', 'image/png', 'image/webp'): flash('광고 사진은 JPG·PNG·WEBP로 골라 주세요.'); return redirect(url_for('mag_ads_admin'))
                from PIL import Image, ImageOps
                try: im = ImageOps.exif_transpose(Image.open(pic.stream)).convert('RGB'); im.thumbnail((2000, 2000))
                except Exception: flash('사진을 읽지 못했어요.'); return redirect(url_for('mag_ads_admin'))
                name = f'ad-{slot}-{datetime.datetime.now():%Y%m%d%H%M%S}.webp'; im.save(folder / name, 'WEBP', quality=88)
                if ad.get('img') and ad['img'] != name: (folder / ad['img']).unlink(missing_ok=True)
                ad['img'] = name
            day = lambda k: f.get(k, '') if re.fullmatch(r'\d{4}-\d{2}-\d{2}', f.get(k, '')) else ''
            ad.update(url=url, alt=f.get('alt', '').strip()[:80], start=day('start'), end=day('end'), on=bool(f.get('on')))
            if ad['on'] and not (ad.get('img') and ad['url']): ad['on'] = False; flash('사진과 주소를 모두 넣어야 광고가 켜져요.')
            else: flash('광고를 저장했어요.')
            a[slot] = ad; put('mag_ads', a)
            return redirect(url_for('mag_ads_admin'))
        a = ads()
        return render_template('mag_admin_ads.html', slots=[(k, n, a.get(k) or {}, live(a.get(k))) for k, n in AD_SLOTS])

    # ---- 접수글 --------------------------------------------------------------------
    def sweep():
        cut = (datetime.datetime.now() - datetime.timedelta(days=KEEP_DAYS)).isoformat(timespec='seconds')
        with conn() as db: db.execute('DELETE FROM mag_inbox WHERE created<?', (cut,))

    def inbox_new():
        with conn() as db: return db.execute("SELECT COUNT(*) FROM mag_inbox WHERE status='new'").fetchone()[0]
    app.jinja_env.globals['mag_inbox_new'] = inbox_new

    @app.route('/letter/contact', methods=['GET', 'POST'])
    def mag_contact():
        c = conf()
        if not c['inbox']: abort(404)
        done, err, form = False, '', {}
        if request.method == 'POST':
            f = request.form; form = {k: f.get(k, '').strip() for k in ('kind', 'name', 'email', 'body', 'agree')}
            if f.get('website'): abort(400)  # 자동 글쓰기 막기 (사람에게는 안 보이는 칸)
            if S.too_many_attempts('mag_contact'): err = '보낸 글이 너무 많아요. 10분쯤 뒤에 다시 보내 주세요.'
            elif form['kind'] not in KINDS: err = '무엇을 보내는지 골라 주세요.'
            elif len(form['body']) < 10: err = '내용을 10자 넘게 적어 주세요.'
            elif not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', form['email']): err = '답장 받을 이메일을 다시 확인해 주세요.'
            elif not form['agree']: err = '개인정보 수집·이용에 동의해야 보낼 수 있어요.'
            else:
                S.note_attempt('mag_contact'); sweep()
                with conn() as db:
                    db.execute('INSERT INTO mag_inbox(kind,name,email,body,created) VALUES(?,?,?,?,?)', (form['kind'], form['name'][:40], form['email'][:120], form['body'][:5000], now()))
                done = True
        return render_template('mag_contact.html', kinds=KINDS, done=done, err=err, form=form, keep=KEEP_DAYS)

    @app.route('/admin/magazine/inbox', methods=['GET', 'POST'])
    @S.admin_only
    def mag_inbox_admin():
        sweep()
        if request.method == 'POST':
            i, act = request.form.get('id', type=int), request.form.get('act')
            with conn() as db:
                if act == 'del': db.execute('DELETE FROM mag_inbox WHERE id=?', (i,)); flash('지웠어요.')
                elif act in ('done', 'new'): db.execute('UPDATE mag_inbox SET status=? WHERE id=?', (act, i))
            return redirect(url_for('mag_inbox_admin', view=request.args.get('view') or None))
        view = request.args.get('view', '')
        with conn() as db:
            rows = db.execute("SELECT * FROM mag_inbox" + (" WHERE status=?" if view in ('new', 'done') else '') + " ORDER BY id DESC LIMIT 300", (view,) if view in ('new', 'done') else ()).fetchall()
            n = {s: db.execute('SELECT COUNT(*) FROM mag_inbox WHERE status=?', (s,)).fetchone()[0] for s in ('new', 'done')}
        return render_template('mag_admin_inbox.html', rows=rows, n=n, view=view, keep=KEEP_DAYS)
