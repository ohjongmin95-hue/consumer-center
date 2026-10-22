"""사기 주의 (BBB Scam Tracker처럼): 사기 사이트·문자·전화·계좌 신고, 검색, 지역 지도.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 주소를 붙인다.
- 신고는 회원만. 운영자가 확인해 '공개'로 바꾸기 전에는 어디에도 보이지 않는다 (관리자 > 사기 주의 신고).
- 공개 화면에서 전화번호·계좌번호는 앞뒤 몇 자리만 보이고, 검색은 전체 번호로 맞춰 본다. 본문 속 연락처는 가린다.
- 검색 결과는 공개된 신고 수만 센다 (확인 전 신고로 남을 사기꾼으로 몰지 않으려고).
"""
import datetime, re
from flask import abort, flash, g, redirect, render_template, request, url_for

KINDS = [('shop', '쇼핑몰 사기', '🛒'), ('used', '중고거래 사기', '📦'), ('sms', '문자·메신저 사기', '💬'),
         ('call', '사칭 전화', '📞'), ('invest', '투자·코인 사기', '📈'), ('etc', '그 밖의 사기', '⚠️')]
KIND = {k: (n, e) for k, n, e in KINDS}
TARGETS = {'site': '사이트 주소', 'phone': '전화번호', 'account': '계좌번호', 'sns': 'SNS·메신저 아이디', 'none': '없음'}
# 시도 타일 지도: (이름, 열, 행). 대략 실제 위치대로 4열 5행에 놓음
REGIONS = [('인천', 0, 0), ('서울', 1, 0), ('경기', 2, 0), ('강원', 3, 0),
           ('충남', 0, 1), ('세종', 1, 1), ('충북', 2, 1), ('경북', 3, 1),
           ('전북', 0, 2), ('대전', 1, 2), ('대구', 2, 2), ('울산', 3, 2),
           ('광주', 0, 3), ('전남', 1, 3), ('경남', 2, 3), ('부산', 3, 3),
           ('제주', 0, 4)]
REGION_NAMES = [r[0] for r in REGIONS] + ['온라인·모름']
STATUSES = {'pending': '확인 전', 'public': '공개', 'rejected': '공개 안 함'}


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS scam_reports(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,region TEXT NOT NULL,title TEXT NOT NULL,story TEXT NOT NULL,
        target_type TEXT NOT NULL DEFAULT 'none',target TEXT NOT NULL DEFAULT '',target_norm TEXT NOT NULL DEFAULT '',amount INTEGER NOT NULL DEFAULT 0,
        occurred_on TEXT NOT NULL DEFAULT '',user_id INTEGER,ip_hash TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'pending',
        admin_note TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,reviewed_at TEXT NOT NULL DEFAULT '')''')
    db.execute('CREATE INDEX IF NOT EXISTS scam_norm ON scam_reports(target_norm)')


def norm_target(kind, value):
    """검색용으로 맞춘 값: 번호는 숫자만, 사이트는 도메인만, 아이디는 소문자."""
    v = (value or '').strip().lower()
    if kind in ('phone', 'account'): return re.sub(r'\D', '', v)
    if kind == 'site':
        v = re.sub(r'^[a-z]+://', '', v).split('/')[0].split('?')[0]
        return v[4:] if v.startswith('www.') else v
    return v.lstrip('@')


def guess_norm(q):
    """검색창에 넣은 값: 숫자가 8자리 이상이면 번호로, 점이 있으면 사이트로, 아니면 아이디로 봄."""
    digits = re.sub(r'\D', '', q)
    if len(digits) >= 8 and len(digits) >= len(re.sub(r'[\s\-()]', '', q)) - 2: return [digits]
    if '.' in q: return [norm_target('site', q)]
    return [norm_target('sns', q)]


def mask_target(kind, value):
    """공개 화면용: 전화번호는 010-12**-**78, 계좌는 앞 3자리·뒤 2자리만."""
    if kind == 'phone':
        d = re.sub(r'\D', '', value)
        return (d[:3] + '-' + d[3:5] + '**-**' + d[-2:]) if len(d) >= 9 else '***'
    if kind == 'account':
        bank = re.sub(r'[\d\-\s]', '', value).strip()
        d = re.sub(r'\D', '', value)
        return ((bank + ' ') if bank else '') + (d[:3] + '*' * max(3, len(d) - 5) + d[-2:] if len(d) >= 6 else '***')
    if kind == 'site': return norm_target('site', value)
    return value


def install(S):
    app = S.app; conn = S.conn
    with conn() as db: migrate(db)
    def stamp(): return datetime.datetime.now().isoformat(timespec='seconds')

    def card(r):
        name, emoji = KIND.get(r['kind'], KIND['etc'])
        return dict(id=r['id'], kind=r['kind'], kind_name=name, emoji=emoji, region=r['region'], title=S.mask_personal(r['title']),
                    story=S.mask_personal(r['story']), target_type=r['target_type'], target_label=TARGETS.get(r['target_type'], ''),
                    target=mask_target(r['target_type'], r['target']) if r['target_type'] != 'none' else '',
                    amount=r['amount'], occurred_on=r['occurred_on'], created=r['created'][:10])

    @app.route('/scam')
    def scam_home():
        q = request.args.get('q', '').strip()[:100]
        kind = request.args.get('kind', '')
        region = request.args.get('region', '')
        if kind not in KIND: kind = ''
        if region not in REGION_NAMES: region = ''
        with conn() as db:
            where = "status='public'"; args = []
            if kind: where += ' AND kind=?'; args.append(kind)
            if region: where += ' AND region=?'; args.append(region)
            rows = db.execute(f'SELECT * FROM scam_reports WHERE {where} ORDER BY id DESC LIMIT 30', args).fetchall()
            by_region = {r[0]: r[1] for r in db.execute("SELECT region,COUNT(*) FROM scam_reports WHERE status='public' GROUP BY region")}
            by_kind = {r[0]: r[1] for r in db.execute("SELECT kind,COUNT(*) FROM scam_reports WHERE status='public' GROUP BY kind")}
            month = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
            recent = db.execute("SELECT COUNT(*) FROM scam_reports WHERE status='public' AND created>=?", (month,)).fetchone()[0]
            total = sum(by_kind.values())
            found = None
            if q:
                keys = [k for k in guess_norm(q) if len(k) >= 3]
                hits = db.execute(f"SELECT * FROM scam_reports WHERE status='public' AND target_norm IN ({','.join('?' * len(keys))}) ORDER BY id DESC", keys).fetchall() if keys else []
                found = {'n': len(hits), 'rows': [card(r) for r in hits[:10]], 'last': hits[0]['created'][:10] if hits else ''}
        top = max(list(by_region.values()) + [1])
        tiles = [dict(name=n, col=c, row=r, n=by_region.get(n, 0), level=0 if not by_region.get(n) else min(4, 1 + 3 * by_region[n] // top)) for n, c, r in REGIONS]
        return render_template('scam.html', q=q, found=found, rows=[card(r) for r in rows], kinds=KINDS, kind=kind, region=region,
                               tiles=tiles, by_kind=by_kind, total=total, recent=recent, online=by_region.get('온라인·모름', 0))

    @app.route('/scam/new', methods=['GET', 'POST'])
    @S.member_only
    def scam_new():
        f = request.form
        if request.method == 'POST':
            if f.get('website'): abort(400)  # 자동 등록 막기용 숨은 칸
            kind = f.get('kind', ''); region = f.get('region', ''); ttype = f.get('target_type', 'none')
            title = f.get('title', '').strip(); story = f.get('story', '').strip(); target = f.get('target', '').strip()
            amount = re.sub(r'\D', '', f.get('amount', ''))[:12]; occurred = f.get('occurred_on', '')[:10]
            err = None
            if kind not in KIND or region not in REGION_NAMES or ttype not in TARGETS: err = S.ui_text('scam.e_pick', '사기 종류와 지역을 골라 주세요.')
            elif not (5 <= len(title) <= 60): err = S.ui_text('scam.e_title', '제목을 5~60자로 적어 주세요.')
            elif not (20 <= len(story) <= 2000): err = S.ui_text('scam.e_story', '어떻게 당했는지 20자 이상 적어 주세요.')
            elif ttype != 'none' and not (3 <= len(norm_target(ttype, target)) <= 100): err = S.ui_text('scam.e_target', '사이트 주소나 번호를 확인해 주세요.')
            elif not f.get('truth'): err = S.ui_text('scam.e_truth', '사실대로 적었는지 확인해 주세요.')
            if occurred:
                try: datetime.date.fromisoformat(occurred)
                except ValueError: occurred = ''
            with conn() as db:
                if not err and S.recent_count(db, 'scam_reports', 60) >= 5: err = S.ui_text('msg.m13', '잠시 후 다시 남겨 주세요.')
                if err:
                    flash(err); return render_template('scam_new.html', kinds=KINDS, regions=REGION_NAMES, targets=TARGETS, f=f), 400
                db.execute('''INSERT INTO scam_reports(kind,region,title,story,target_type,target,target_norm,amount,occurred_on,user_id,ip_hash,created)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (kind, region, title, story, ttype, target if ttype != 'none' else '', norm_target(ttype, target) if ttype != 'none' else '',
                                                        int(amount or 0), occurred, g.user['id'], S.ip_hash(), stamp()))
            flash(S.ui_text('scam.sent', '신고해 주셔서 고마워요. 운영자가 확인한 뒤 공개돼요.'))
            return redirect(url_for('scam_home'))
        return render_template('scam_new.html', kinds=KINDS, regions=REGION_NAMES, targets=TARGETS, f={})

    @app.route('/admin/scam', methods=['GET', 'POST'])
    @S.admin_only
    def admin_scam():
        with conn() as db:
            if request.method == 'POST':
                status = request.form.get('status', '')
                if status not in STATUSES: abort(400)
                db.execute('UPDATE scam_reports SET status=?,admin_note=?,reviewed_at=? WHERE id=?',
                           (status, request.form.get('admin_note', '').strip()[:2000], stamp(), request.form.get('id', type=int)))
                flash('저장했어요.'); return redirect(url_for('admin_scam', show=request.args.get('show', 'pending')))
            show = request.args.get('show', 'pending')
            if show not in STATUSES: show = 'pending'
            rows = db.execute('SELECT s.*,u.nickname FROM scam_reports s LEFT JOIN users u ON u.id=s.user_id WHERE s.status=? ORDER BY s.id DESC LIMIT 200', (show,)).fetchall()
            counts = {r[0]: r[1] for r in db.execute('SELECT status,COUNT(*) FROM scam_reports GROUP BY status')}
        return render_template('admin_scam.html', rows=rows, show=show, statuses=STATUSES, counts=counts, kinds=KIND, targets=TARGETS, masked=mask_target)

    def pending_scams():
        with conn() as db: return db.execute("SELECT COUNT(*) FROM scam_reports WHERE status='pending'").fetchone()[0]
    app.jinja_env.globals.update(scam_pending=pending_scams)
