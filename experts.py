"""전문가 등록 (운영자 요청 2026-11-03: 전문가를 한 명씩 가입시키기).
- 관리자 > 회원 > 전문가에서 이름·분야·소속을 넣고 '초대 링크'를 만든다. 링크를 받은 전문가가 로그인(카카오 등)하고
  자격 정보를 확인해 보내면 바로 '전문가'가 된다(운영자가 직접 모신 분이라).
- 초대 없이 /expert/apply 에서 신청할 수도 있다. 이건 관리자가 자격을 확인하고 승인해야 전문가가 된다.
- 승인된 전문가가 제보에 댓글을 달면 이름 옆에 '전문가 · 변호사' 같은 표시가 붙는다.
- 법무법인·사무소 같은 곳도 '전문 기관'으로 등록할 수 있다(사업자등록번호·로고).
- 수수료·수임료·광고비는 받지 않는다. 운영자 2026-11-03 나중: 변호사 소개(소개 페이지의 '상담 신청하기')는 하되 돈은 받지 않는다.
- 자격증 사진(증빙)은 관리자만 볼 수 있다. 관리자는 언제든 표시를 멈추거나 다시 켤 수 있다.
"""
import datetime
import random, os, secrets, threading, uuid

from flask import abort, flash, g, redirect, render_template, request, send_file, session, url_for

# 운영자 2026-11-03: 자문단은 일단 변호사와 교수만 받음 (사무소·법인은 법무법인·법률사무소). 예전에 등록된 다른 분야는 그대로 보임
FIELDS = ('변호사', '교수')
FIRM_FIELDS = ('법무법인', '법률사무소')
KINDS = {'person': '자문단', 'firm': '자문단'}  # 운영자 2026-11-03: 표시 이름 = 소보루 자문단 ('자문위원'·'전문가' 아님)
STATUS = {'invited': '초대함', 'pending': '확인 기다림', 'approved': '활동 중', 'rejected': '반려', 'stopped': '멈춤'}
PROOF_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.pdf')
# 관리자가 자격을 공식 조회로 맞춰 볼 곳 (운영자 2026-11-03: 다른 서비스처럼 '파일 받기 → 공식 조회 → 표시')
LOOKUP = {'변호사': ('대한변호사협회 변호사 검색', 'https://www.koreanbar.or.kr'), '법무법인': ('대한변호사협회 변호사 검색', 'https://www.koreanbar.or.kr'),
          '법률사무소': ('대한변호사협회 변호사 검색', 'https://www.koreanbar.or.kr')}


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS experts(id INTEGER PRIMARY KEY,user_id INTEGER UNIQUE,name TEXT NOT NULL,field TEXT NOT NULL,
        org TEXT NOT NULL DEFAULT '',license_no TEXT NOT NULL DEFAULT '',intro TEXT NOT NULL DEFAULT '',phone TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL DEFAULT '',proof TEXT NOT NULL DEFAULT '',photo TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'pending',token TEXT UNIQUE,
        note TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,approved TEXT NOT NULL DEFAULT '')''')
    cols = {r[1] for r in db.execute('PRAGMA table_info(experts)')}
    if 'photo' not in cols: db.execute("ALTER TABLE experts ADD COLUMN photo TEXT NOT NULL DEFAULT ''")
    if 'kind' not in cols: db.execute("ALTER TABLE experts ADD COLUMN kind TEXT NOT NULL DEFAULT 'person'")
    if 'proof2' not in cols: db.execute("ALTER TABLE experts ADD COLUMN proof2 TEXT NOT NULL DEFAULT ''")  # 재직증명서·사업자등록증 (선택)
    if 'claim' not in cols: db.execute('ALTER TABLE experts ADD COLUMN claim TEXT')  # 로그인 없이 등록한 분이 나중에 계정을 잇는 열쇠
    if 'career' not in cols: db.execute("ALTER TABLE experts ADD COLUMN career TEXT NOT NULL DEFAULT ''")  # 이력 (한 줄에 하나, 소개 페이지에 보임)
    # 운영자 2026-11-03: 자문단 소개 페이지의 '상담 신청하기'. 돈은 받지 않고, 남긴 글을 그 자문단에게 전해 줌
    db.execute('''CREATE TABLE IF NOT EXISTS expert_requests(id INTEGER PRIMARY KEY,expert_id INTEGER NOT NULL,user_id INTEGER NOT NULL,
        body TEXT NOT NULL,contact TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,seen INTEGER NOT NULL DEFAULT 0)''')
    # 운영자 2026-11-03: 새 제보가 올라오면 자문단이 알아야 의견을 남김. 하루 한 번 저녁에 메일로 묶어서 (끄고 켤 수 있음)
    if 'digest' not in cols: db.execute('ALTER TABLE experts ADD COLUMN digest INTEGER NOT NULL DEFAULT 1')
    # 운영자 2026-11-03: 흑묘 '도우미단 초대'처럼 — 제보자가 자기 제보에 자문단을 불러 의견을 청함. 의견이 달리면 answered에 시각
    db.execute('''CREATE TABLE IF NOT EXISTS expert_invites(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL,user_id INTEGER NOT NULL,expert_id INTEGER NOT NULL,
        reason TEXT NOT NULL,created TEXT NOT NULL,answered TEXT NOT NULL DEFAULT '',UNIQUE(case_id,expert_id))''')


def labels(db, user_ids):
    """{회원 번호: {'field': '변호사', 'photo': 사진 주소}} — 승인된 전문가만."""
    ids = [int(i) for i in set(user_ids) if i]
    if not ids: return {}
    try:
        rows = db.execute(f"SELECT id,user_id,field,photo,kind FROM experts WHERE status='approved' AND user_id IN ({','.join('?' * len(ids))})", ids).fetchall()
    except Exception:
        return {}
    return {r[1]: {'field': r[2], 'photo': photo_url(r[0], r[3]), 'label': KINDS.get(r[4], '자문단')} for r in rows}


def photo_url(eid, photo):
    return f'/expert/{eid}/photo.jpg?v={photo[:8]}' if photo else ''


def install(S):
    app, conn = S.app, S.conn
    folder = S.UPLOAD / 'experts'; folder.mkdir(parents=True, exist_ok=True)
    with conn() as db: migrate(db)

    def now(): return datetime.datetime.now().isoformat(timespec='seconds')
    def clean(name, n): return ' '.join((request.form.get(name) or '').split())[:n]

    def career_text():
        lines = [' '.join(l.split())[:80] for l in (request.form.get('career') or '').splitlines()]
        return '\n'.join([l for l in lines if l][:12])

    def save_proof(old='', key='proof'):
        up = request.files.get(key)
        if not up or not up.filename: return old
        ext = os.path.splitext(up.filename.lower())[1]
        if ext not in PROOF_EXT: raise ValueError('자격증은 사진(JPG·PNG·WEBP)이나 PDF로 올려 주세요.')
        data = up.read(10_000_001)
        if len(data) > 10_000_000: raise ValueError('파일은 10MB까지 올릴 수 있어요.')
        name = uuid.uuid4().hex + ext
        (folder / name).write_bytes(data)
        if old: (folder / old).unlink(missing_ok=True)
        return name

    def save_photo(old=''):
        """프로필 사진: 가운데를 정사각형으로 잘라 400px JPG로."""
        up = request.files.get('photo')
        if not up or not up.filename: return old
        from PIL import Image, ImageOps
        import io
        try:
            im = ImageOps.exif_transpose(Image.open(io.BytesIO(up.read(15_000_001)))).convert('RGB')
        except Exception:
            raise ValueError('사진을 열지 못했어요. JPG·PNG·WEBP 사진인지 확인해 주세요.')
        im = ImageOps.fit(im, (400, 400))
        name = uuid.uuid4().hex + '.jpg'
        im.save(folder / name, 'JPEG', quality=86)
        if old: (folder / old).unlink(missing_ok=True)
        return name

    def form_values(row=None):
        r = dict(row) if row else {}
        out = {k: r.get(k, '') or '' for k in ('name', 'field', 'org', 'intro', 'phone', 'email', 'career')}
        out['kind'] = r.get('kind') or 'person'
        return out

    def submit(row, invited):
        """운영자 2026-11-03: 로그인 없이 입력하고 등록. 자격은 번호 말고 파일로만. 로그인 안 했으면 나중에 계정을 잇는 열쇠(claim)를 줌."""
        f = {'name': clean('name', 30), 'field': clean('field', 20), 'org': clean('org', 60),
             'intro': clean('intro', 120), 'phone': clean('phone', 20), 'email': clean('email', 120), 'career': career_text()}
        kind = 'firm' if request.form.get('kind') == 'firm' else 'person'
        if not f['name'] or f['field'] not in (FIRM_FIELDS if kind == 'firm' else FIELDS): raise ValueError('이름과 분야를 넣어 주세요.')
        if not f['phone'] and not f['email']: raise ValueError('연락처나 이메일 중 하나는 적어 주세요.')
        up = request.files.get('proof')
        if not (up and up.filename) and not (row and row['proof']):
            raise ValueError('사업자등록증 파일을 올려 주세요.' if kind == 'firm' else '재직증명서 파일을 올려 주세요.' if f['field'] == '교수' else '변호사 등록증 파일을 올려 주세요.')
        # 운영자 2026-11-03: 자문단은 신뢰를 위해 프로필 사진이 꼭 필요 (사무소·법인은 로고라 선택)
        ph = request.files.get('photo')
        if kind == 'person' and not (ph and ph.filename) and not (row and row['photo']): raise ValueError('프로필 사진을 올려 주세요. 소비자가 믿고 볼 수 있게 얼굴이 보이는 사진이 필요해요.')
        if not request.form.get('agree'): raise ValueError('자문단 표시와 확인 정보 보관에 동의해 주세요.')
        proof = save_proof(row['proof'] if row else '')
        proof2 = save_proof(row['proof2'] if row else '', 'proof2')
        photo = save_photo(row['photo'] if row else '')
        status = 'approved' if invited else 'pending'
        uid = g.user['id'] if g.user else None
        claim = None if uid else secrets.token_urlsafe(16)
        with conn() as db:
            if row:
                db.execute('UPDATE experts SET user_id=?,name=?,field=?,org=?,intro=?,phone=?,email=?,career=?,proof=?,proof2=?,photo=?,kind=?,status=?,token=NULL,claim=?,approved=? WHERE id=?',
                           (uid, *f.values(), proof, proof2, photo, kind, status, claim, now() if invited else '', row['id']))
                eid = row['id']
            else:
                eid = db.execute('INSERT INTO experts(user_id,name,field,org,intro,phone,email,career,proof,proof2,photo,kind,status,claim,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                 (uid, *f.values(), proof, proof2, photo, kind, status, claim, now())).lastrowid
        alert_new_expert(eid, f, kind, status)
        return eid, status, claim

    def alert_new_expert(eid, f, kind, status):
        """운영자 2026-11-03 (밤): 자문단 가입이 들어오면 바로 하이웍스 메일(contact@)로 알림. EXPERT_ALERT_EMAIL로 바꿀 수 있음."""
        to = [e.strip() for e in (os.getenv('EXPERT_ALERT_EMAIL') or 'contact@consumerjebo.co.kr').split(',') if '@' in e]
        if not to or not S.notify.email_ready(): return
        state = '초대 링크로 가입해 바로 자문단이 됐어요' if status == 'approved' else '직접 신청했어요. 자격 파일을 보고 승인해 주세요'
        link = S.canonical_url(url_for('admin_experts'))
        subject = f"[{S.notify.site_name()}] 새 자문단 가입: {f['name']} {f['field']}"
        body = (f"새 자문단 가입이 들어왔어요.\n\n■ 이름: {f['name']} ({f['field']}{', 사무소·법인' if kind == 'firm' else ''})\n■ 소속: {f['org'] or '-'}\n"
                f"■ 연락처: {f['phone'] or '-'} / {f['email'] or '-'}\n■ 한 줄 소개: {f['intro'] or '-'}\n■ 상태: {state}\n\n관리자 화면에서 확인해 주세요.\n{link}")
        def run():
            for e in to:
                try: S.notify.send_email(e, subject, body)
                except Exception as ex: app.logger.warning('expert alert mail failed: %s', ex)
        threading.Thread(target=run, daemon=True).start()

    def form_page(invite=None, f=None):
        people = [r for r in helpers(12) if r['kind'] == 'person' and r['photo_url']]; random.shuffle(people)
        if not people:  # 운영자 2026-11-03: 사진 올린 자문단이 아직 없으면 왼쪽이 비어 보임 → 예시 카드 (예시 사진)
            people = [{'name': n, 'field': fd, 'org': o, 'photo_url': url_for('static', filename=f'img/advisors/{a}.jpg')}
                      for a, n, fd, o in (('a1', '김서연', '변호사', '소보루 법률사무소'), ('a2', '박성훈', '변호사', '법무법인 소보루'),
                                          ('a3', '이정민', '교수', '소보루대학교 법학전문대학원'), ('a4', '정민재', '변호사', '법률사무소 소보루'))]
        return render_template('expert_form.html', fields=FIELDS, firm_fields=FIRM_FIELDS, f=f or form_values(invite), invite=invite, people=people)

    def done(status, claim):
        session['expert_done'] = {'status': status, 'claim': claim or ''}
        return redirect(url_for('expert_done'))

    @app.route('/expert/apply', methods=['GET', 'POST'])
    def expert_apply():
        mine = None
        if g.user:
            with conn() as db: mine = db.execute('SELECT * FROM experts WHERE user_id=?', (g.user['id'],)).fetchone()
        if mine and mine['status'] in ('approved', 'pending', 'stopped') and request.method == 'GET':
            with conn() as db:
                reqs = db.execute('SELECT r.*,u.nickname FROM expert_requests r LEFT JOIN users u ON u.id=r.user_id WHERE r.expert_id=? ORDER BY r.id DESC LIMIT 30', (mine['id'],)).fetchall()
                db.execute('UPDATE expert_requests SET seen=1 WHERE expert_id=?', (mine['id'],))
                waiting = new_cases(db, 6)
            return render_template('expert_apply.html', mine=mine, kinds=KINDS, status=STATUS, photo=photo_url(mine['id'], mine['photo']), reqs=reqs, waiting=waiting)
        if request.method == 'POST':
            if request.form.get('website'): abort(400)  # 자동 등록 막기용 숨은 칸
            if mine and mine['status'] in ('approved', 'stopped'): abort(400)
            try:
                _, status, claim = submit(mine, False)
            except ValueError as e:
                flash(str(e)); return form_page(f=form_values(request.form))
            return done(status, claim)
        return form_page(f=form_values(mine))

    @app.route('/expert/done')
    def expert_done():
        d = session.get('expert_done')
        if not d: return redirect(url_for('experts_page'))
        nxt = url_for('expert_claim', key=d['claim']) if d.get('claim') else ''
        return render_template('expert_done.html', status=d['status'], login_url=url_for('login', next=nxt) if nxt else '')

    @app.route('/expert/claim/<key>')
    @S.member_only
    def expert_claim(key):
        """로그인 없이 등록한 분이 로그인하면 그 계정에 자문단 정보를 이어 줌."""
        with conn() as db:
            row = db.execute('SELECT id FROM experts WHERE claim=?', (key,)).fetchone()
            if not row: abort(404)
            other = db.execute('SELECT id FROM experts WHERE user_id=? AND id!=?', (g.user['id'], row['id'])).fetchone()
            if other: flash('이 계정에는 이미 자문단 정보가 있어요. 고객센터로 알려 주세요.'); return redirect(url_for('expert_apply'))
            db.execute('UPDATE experts SET user_id=?,claim=NULL WHERE id=?', (g.user['id'], row['id']))
        session.pop('expert_done', None)
        flash('계정을 이었어요. 제보에 댓글을 달면 이름 옆에 자문단 표시가 붙어요.')
        return redirect(url_for('expert_apply'))

    @app.route('/expert/photo', methods=['POST'])
    @S.member_only
    def expert_photo_change():
        with conn() as db:
            mine = db.execute('SELECT * FROM experts WHERE user_id=?', (g.user['id'],)).fetchone()
            if not mine: abort(404)
            try: db.execute('UPDATE experts SET photo=? WHERE id=?', (save_photo(mine['photo']), mine['id'])); flash('사진을 바꿨어요.')
            except ValueError as e: flash(str(e))
        return redirect(url_for('expert_apply'))

    @app.route('/expert/career', methods=['POST'])
    @S.member_only
    def expert_career_change():
        with conn() as db:
            mine = db.execute('SELECT id FROM experts WHERE user_id=?', (g.user['id'],)).fetchone()
            if not mine: abort(404)
            db.execute('UPDATE experts SET career=?,intro=? WHERE id=?', (career_text(), clean('intro', 120), mine['id']))
        flash('소개를 고쳤어요.')
        return redirect(url_for('expert_apply'))

    def public_expert(eid):
        with conn() as db: row = db.execute("SELECT * FROM experts WHERE id=? AND status='approved'", (eid,)).fetchone()
        if not row: abort(404)
        return row

    def new_cases(db, limit, since=''):
        """공개된 최근 제보 (자문단이 의견을 남길 수 있는 것). since가 있으면 그 뒤에 올라온 것만."""
        try:
            return [dict(r) for r in db.execute(f"""SELECT id,subject,public_subject,company,category,created FROM cases
                WHERE public_consent=1 AND published=1 AND review NOT IN ('rejected','duplicate') AND created>? ORDER BY id DESC LIMIT ?""", (since, limit))]
        except Exception:
            return []

    def digest(now_iso=None, dry=False):
        """운영자 2026-11-03: 지난번 뒤에 올라온 공개 제보를 자문단에게 하루 한 번 메일로 (cron이 저녁에 부름). 보낸 사람 수를 돌려줌."""
        now_iso = now_iso or now()
        with conn() as db:
            row = db.execute("SELECT value FROM admin_settings WHERE key='expert_digest_last'").fetchone()
            since = row[0] if row else (datetime.datetime.fromisoformat(now_iso) - datetime.timedelta(days=1)).isoformat(timespec='seconds')
            cases = new_cases(db, 15, since)
            people = db.execute("SELECT id,name,email FROM experts WHERE status='approved' AND digest=1 AND email!=''").fetchall()
            if not dry:
                db.execute("INSERT INTO admin_settings(key,value,updated) VALUES('expert_digest_last',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated", (now_iso, now_iso))
        if not cases or not people: return 0
        real = sorted(h for h in getattr(S, 'JEBO_HOSTS', set()) if not h.startswith('www.'))
        base = 'https://' + real[0] if real else 'https://consumerjebo.co.kr'
        lines = [f"· {c['public_subject'] or c['subject']}" + (f" ({c['company']})" if c['company'] else '') + f"\n  {base}/reports/{c['id']}" for c in cases]
        sent = 0
        for p in people:
            text = (f"{p['name']} 님, 소비자제보센터에 새 제보 {len(cases)}건이 올라왔어요.\n\n" + '\n'.join(lines) +
                    "\n\n제보에 의견을 남기면 이름 옆에 '자문단' 표시가 붙고, 제보가 기사로 나갈 때 함께 실릴 수 있어요."
                    f"\n\n이 메일을 그만 받으려면: {base}/expert/apply 에서 '새 제보 알림'을 꺼 주세요.")
            if dry: print(p['email'], text[:200]); sent += 1; continue
            try: S.notify.send_email(p['email'], f'[{S.notify.site_name()}] 새 제보 {len(cases)}건이 올라왔어요', text); sent += 1
            except Exception: pass
        return sent

    @app.route('/expert/digest', methods=['POST'])
    @S.member_only
    def expert_digest_toggle():
        with conn() as db:
            db.execute('UPDATE experts SET digest=? WHERE user_id=?', (1 if request.form.get('on') == '1' else 0, g.user['id']))
        flash('새 제보 알림을 켰어요.' if request.form.get('on') == '1' else '새 제보 알림을 껐어요.')
        return redirect(url_for('expert_apply'))

    app.extensions['experts_digest'] = digest

    # ---- 자문단 초대 (운영자 2026-11-03, 흑묘 '도우미단 초대'처럼) ----
    INVITE_MAX = 3  # 제보 하나에 부를 수 있는 자문단 수

    def site_base():
        real = sorted(h for h in getattr(S, 'JEBO_HOSTS', set()) if not h.startswith('www.'))
        return 'https://' + real[0] if real else 'https://consumerjebo.co.kr'

    def invite_box(case, has_answer):
        """제보 화면 아래 '자문단 초대' 상자에 쓸 값. 제보한 본인에게만, 기업이 답했거나 답 기한이 지난 제보에만 열림."""
        me = g.get('user')
        if not me or not case['user_id'] or case['user_id'] != me['id']: return None
        try:
            overdue = S.jebo.no_answer(case, has_answer)
        except Exception:
            overdue = False
        with conn() as db:
            sent = [dict(r) for r in db.execute("""SELECT i.expert_id,i.answered,i.created,e.name,e.field,e.photo FROM expert_invites i JOIN experts e ON e.id=i.expert_id
                WHERE i.case_id=? ORDER BY i.id""", (case['id'],))]
            people = [dict(r) for r in db.execute("SELECT id,name,field,org,photo FROM experts WHERE status='approved' AND kind='person' ORDER BY approved DESC,id DESC")]
        done = {x['expert_id'] for x in sent}
        for x in sent: x['photo_url'] = photo_url(x['expert_id'], x['photo'])
        for x in people: x['photo_url'] = photo_url(x['id'], x['photo'])
        return {'open': bool(has_answer or overdue), 'sent': sent, 'people': [x for x in people if x['id'] not in done],
                'left': max(0, INVITE_MAX - len(sent)), 'max': INVITE_MAX}
    app.jinja_env.globals['expert_invite_box'] = invite_box

    @app.route('/reports/<int:case_id>/invite-expert', methods=['POST'])
    @S.member_only
    def expert_invite(case_id):
        with conn() as db:
            case = db.execute('SELECT * FROM cases WHERE id=? AND public_consent=1 AND published=1', (case_id,)).fetchone()
            if not case or case['user_id'] != g.user['id']: abort(404)
            has_answer = db.execute("SELECT 1 FROM messages WHERE case_id=? AND author='기업 답변' AND public=1", (case_id,)).fetchone() is not None
        box = invite_box(case, has_answer)
        back = url_for('public_case', case_id=case_id) + '#invite'
        eid = request.form.get('expert', type=int)
        reason = (request.form.get('reason') or '').strip()[:500]
        if not box or not box['open']:
            flash('기업이 답하거나 답 기한이 지나면 자문단을 부를 수 있어요.'); return redirect(back)
        if box['left'] <= 0:
            flash(f"제보 하나에 자문단은 {box['max']}명까지 부를 수 있어요."); return redirect(back)
        e = next((x for x in box['people'] if x['id'] == eid), None)
        if not e:
            flash('부를 자문단을 골라 주세요.'); return redirect(back)
        if len(reason) < 10:
            flash('왜 의견이 필요한지 10자 넘게 적어 주세요.'); return redirect(back)
        with conn() as db:
            db.execute('INSERT OR IGNORE INTO expert_invites(case_id,user_id,expert_id,reason,created) VALUES(?,?,?,?,?)', (case_id, g.user['id'], eid, reason, now()))
            row = db.execute('SELECT email FROM experts WHERE id=?', (eid,)).fetchone()
        if row and row['email']:
            title = case['public_subject'] or case['subject']
            text = (f"{e['name']} 님, 제보자가 자문단 의견을 청했어요.\n\n제보: {title}" + (f" ({case['company']})" if case['company'] else '') +
                    f"\n부른 이유: {reason}\n\n제보 보기: {site_base()}/reports/{case_id}\n\n제보에 댓글로 의견을 남기면 제보자에게 바로 알려 드려요. 남긴 의견은 제보가 기사로 나갈 때 함께 실릴 수 있어요.")
            try: S.notify.send_email(row['email'], f'[{S.notify.site_name()}] 자문단 의견 요청이 왔어요', text)
            except Exception: pass
        flash(f"{e['name']} 님께 의견을 청했어요. 의견이 달리면 알려 드릴게요.")
        return redirect(back)

    def commented(db, case_id, user_id):
        """자문단이 댓글을 남기면 (casetalk.py에서 부름): 그 제보의 초대에 답 표시 + 제보자에게 메일."""
        ex = db.execute("SELECT id,name,field FROM experts WHERE user_id=? AND status='approved'", (user_id,)).fetchone()
        if not ex: return
        inv = db.execute("SELECT id,user_id FROM expert_invites WHERE case_id=? AND expert_id=? AND answered=''", (case_id, ex['id'])).fetchone()
        if not inv: return
        db.execute('UPDATE expert_invites SET answered=? WHERE id=?', (now(), inv['id']))
        u = db.execute("SELECT email FROM users WHERE id=? AND status='active'", (inv['user_id'],)).fetchone()
        c = db.execute('SELECT subject,public_subject FROM cases WHERE id=?', (case_id,)).fetchone()
        if u and u['email']:
            text = f"부르신 {ex['name']} 님({ex['field']})이 제보에 의견을 남겼어요.\n\n제보: {c['public_subject'] or c['subject']}\n의견 보기: {site_base()}/reports/{case_id}"
            try: S.notify.send_email(u['email'], f'[{S.notify.site_name()}] 자문단 의견이 달렸어요', text)
            except Exception: pass
    app.extensions['experts_commented'] = commented

    def invites_for_admin(db):
        """관리자: 자문단 의견이 달린 초대 = 기사화 후보 (의견 달린 것 먼저)."""
        try:
            return [dict(r) for r in db.execute("""SELECT i.*,e.name,e.field,c.subject,c.public_subject,c.company FROM expert_invites i JOIN experts e ON e.id=i.expert_id
                JOIN cases c ON c.id=i.case_id ORDER BY (i.answered=''),i.id DESC LIMIT 50""")]
        except Exception:
            return []

    @app.route('/experts/<int:eid>')
    def expert_profile(eid):
        """운영자 2026-11-03: 자문단을 누르면 나오는 깔끔한 소개 페이지. 사진·이름·소속·한 줄 소개 → 이력 → 남긴 의견 → 상담 신청하기."""
        e = dict(public_expert(eid)); e['photo_url'] = photo_url(e['id'], e['photo'])
        notes, count = [], 0
        if e['user_id']:
            with conn() as db:
                count = db.execute('SELECT COUNT(*) FROM case_comments WHERE hidden=0 AND user_id=?', (e['user_id'],)).fetchone()[0]
                try:
                    notes = [dict(r) for r in db.execute('''SELECT m.case_id,m.body,m.created,c.subject,c.company FROM case_comments m JOIN cases c ON c.id=m.case_id
                        WHERE m.hidden=0 AND m.user_id=? AND c.public_consent=1 AND c.published=1 AND c.review NOT IN ('rejected','duplicate') ORDER BY m.id DESC LIMIT 5''', (e['user_id'],))]
                except Exception:
                    notes = []
        career = [l for l in (e.get('career') or '').splitlines() if l.strip()]
        return render_template('expert_profile.html', e=e, career=career, notes=notes, count=count, sent=request.args.get('sent') == '1')

    @app.route('/experts/<int:eid>/ask', methods=['POST'])
    @S.member_only
    def expert_ask(eid):
        """상담 신청: 남긴 글을 저장하고 그 자문단에게 메일로도 알림. 돈은 받지 않음."""
        e = public_expert(eid)
        body = (request.form.get('body') or '').strip()[:1000]
        contact = clean('contact', 60)
        if len(body) < 10:
            flash('무슨 일인지 10자 넘게 적어 주세요.'); return redirect(url_for('expert_profile', eid=eid) + '#ask')
        with conn() as db:
            recent = db.execute("SELECT COUNT(*) FROM expert_requests WHERE user_id=? AND created>?", (g.user['id'], (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat(timespec='seconds'))).fetchone()[0]
            if recent >= 5: flash('상담 신청은 하루에 5번까지 할 수 있어요.'); return redirect(url_for('expert_profile', eid=eid))
            db.execute('INSERT INTO expert_requests(expert_id,user_id,body,contact,created) VALUES(?,?,?,?,?)', (eid, g.user['id'], body, contact, now()))
        if e['email']:
            text = f"{e['name']} 님, 소비자제보센터에서 상담 신청이 왔어요.\n\n신청한 분: {g.user['nickname']}\n연락처: {contact or '(적지 않음)'}\n\n{body}\n\n자문단 정보에서도 볼 수 있어요: {S.canonical_url(url_for('expert_apply'))}"
            try: S.notify.send_email(e['email'], f'[{S.notify.site_name()}] 상담 신청이 왔어요', text)
            except Exception: pass
        return redirect(url_for('expert_profile', eid=eid, sent=1))

    @app.route('/expert/<int:eid>/photo.jpg')
    def expert_photo(eid):
        """승인된 전문가 사진만 공개 (관리자는 언제나)."""
        with conn() as db: row = db.execute('SELECT photo,status FROM experts WHERE id=?', (eid,)).fetchone()
        if not row or not row['photo'] or not (folder / row['photo']).is_file(): abort(404)
        if row['status'] != 'approved' and not S.admin_active(): abort(404)
        return send_file(folder / row['photo'], mimetype='image/jpeg', max_age=86400)

    @app.route('/expert/join/<token>', methods=['GET', 'POST'])
    def expert_join(token):
        # 운영자 2026-11-03: 초대 링크 = 토스플레이스 상담 신청처럼 한 화면에서 바로 입력하고 등록 (로그인 없이도)
        with conn() as db: inv = db.execute("SELECT * FROM experts WHERE token=? AND status='invited'", (token,)).fetchone()
        if not inv: abort(404)
        if request.method == 'POST':
            if request.form.get('website'): abort(400)
            try:
                if g.user:
                    with conn() as db:
                        mine = db.execute('SELECT * FROM experts WHERE user_id=? AND id!=?', (g.user['id'], inv['id'])).fetchone()
                        if mine and mine['status'] == 'approved': flash('이미 자문단으로 등록된 계정이에요.'); return redirect(url_for('expert_apply'))
                        if mine: db.execute('DELETE FROM experts WHERE id=?', (mine['id'],))  # 초대가 먼저
                _, status, claim = submit(inv, True)
            except ValueError as e:
                flash(str(e)); return form_page(inv, form_values(request.form))
            return done(status, claim)
        return form_page(inv)

    @app.route('/admin/experts', methods=['GET', 'POST'])
    @S.admin_only
    def admin_experts():
        if request.method == 'POST':
            act, eid = request.form.get('act'), request.form.get('id', type=int)
            with conn() as db:
                if act == 'invite':
                    name, field = clean('name', 30), clean('field', 20)
                    kind = 'firm' if field in FIRM_FIELDS else 'person'
                    if not name or field not in FIELDS + FIRM_FIELDS:
                        flash('이름과 분야를 넣어 주세요.')
                    else:
                        db.execute("INSERT INTO experts(name,field,org,kind,status,token,note,created) VALUES(?,?,?,?,'invited',?,?,?)",
                                   (name, field, clean('org', 60), kind, secrets.token_urlsafe(16), clean('note', 200), now()))
                        flash(f'{name} 님 초대 링크를 만들었어요. 아래에서 복사해 보내 주세요.')
                elif eid and act == 'photo':
                    row = db.execute('SELECT * FROM experts WHERE id=?', (eid,)).fetchone()
                    if not row: abort(404)
                    try: db.execute('UPDATE experts SET photo=? WHERE id=?', (save_photo(row['photo']), eid))
                    except ValueError as e: flash(str(e))
                elif eid and act in ('approve', 'reject', 'stop', 'delete', 'note'):
                    row = db.execute('SELECT * FROM experts WHERE id=?', (eid,)).fetchone()
                    if not row: abort(404)
                    if act == 'approve': db.execute("UPDATE experts SET status='approved',approved=? WHERE id=?", (row['approved'] or now(), eid))
                    elif act == 'reject': db.execute("UPDATE experts SET status='rejected' WHERE id=?", (eid,))
                    elif act == 'stop': db.execute("UPDATE experts SET status='stopped' WHERE id=?", (eid,))
                    elif act == 'note': db.execute('UPDATE experts SET note=? WHERE id=?', (clean('note', 200), eid))
                    elif act == 'delete':
                        for f in (row['proof'], row['proof2'], row['photo']):
                            if f: (folder / f).unlink(missing_ok=True)
                        db.execute('DELETE FROM experts WHERE id=?', (eid,))
            return redirect(url_for('admin_experts'))
        with conn() as db:
            rows = db.execute('''SELECT e.*,u.nickname FROM experts e LEFT JOIN users u ON u.id=e.user_id
                ORDER BY CASE e.status WHEN 'pending' THEN 0 WHEN 'invited' THEN 1 WHEN 'approved' THEN 2 ELSE 3 END,e.id DESC''').fetchall()
            invites = invites_for_admin(db)
        return render_template('admin_experts.html', rows=rows, invites=invites, fields=FIELDS, firm_fields=FIRM_FIELDS, kinds=KINDS, status=STATUS, photo_url=photo_url, lookup=LOOKUP,
                               join_url=lambda t: S.canonical_url(url_for('expert_join', token=t)))

    @app.route('/experts')
    def experts_page():
        """전문가 (운영자 2026-11-03: 상단 메뉴 '소비자게시판' 자리에, 검은고양이처럼). 승인된 전문가·전문 기관과 최근 전문가 답변."""
        PUBLIC = "c.public_consent=1 AND c.published=1 AND c.review NOT IN ('rejected','duplicate')"
        with conn() as db:
            rows = [dict(r) for r in db.execute("SELECT id,user_id,name,field,org,intro,photo,kind FROM experts WHERE status='approved' ORDER BY approved DESC,id DESC")]
            ids = [r['user_id'] for r in rows if r['user_id']]
            counts, recent = {}, []
            if ids:
                q = ','.join('?' * len(ids))
                counts = {r[0]: r[1] for r in db.execute(f'SELECT user_id,COUNT(*) FROM case_comments WHERE hidden=0 AND user_id IN ({q}) GROUP BY user_id', ids)}
                try:
                    recent = [dict(r) for r in db.execute(f'SELECT m.case_id,m.body,m.created,m.user_id,c.subject,c.company FROM case_comments m JOIN cases c ON c.id=m.case_id WHERE m.hidden=0 AND m.user_id IN ({q}) AND {PUBLIC} ORDER BY m.id DESC LIMIT 6', ids)]
                except Exception:
                    recent = []
        by_user = {r['user_id']: r for r in rows}
        for r in rows: r['photo_url'] = photo_url(r['id'], r['photo']); r['answers'] = counts.get(r['user_id'], 0)
        for m in recent: m['expert'] = by_user.get(m['user_id'])
        return render_template('experts_page.html', people=[r for r in rows if r['kind'] != 'firm'], firms=[r for r in rows if r['kind'] == 'firm'], recent=recent)

    def helpers(limit=None):
        """승인된 자문단(개인 먼저)과 남긴 의견 수."""
        with conn() as db:
            rows = [dict(r) for r in db.execute("SELECT id,user_id,name,field,org,intro,photo,kind FROM experts WHERE status='approved' ORDER BY kind='firm',approved DESC,id DESC" + (' LIMIT %d' % limit if limit else ''))]
            ids = [r['user_id'] for r in rows if r['user_id']]
            counts = {r[0]: r[1] for r in db.execute('SELECT user_id,COUNT(*) FROM case_comments WHERE hidden=0 AND user_id IN (%s) GROUP BY user_id' % ','.join('?' * len(ids)), ids)} if ids else {}
        for r in rows: r['photo_url'] = photo_url(r['id'], r['photo']); r['answers'] = counts.get(r['user_id'], 0)
        return rows

    @app.route('/explore')
    def explore():
        """둘러보기 (운영자 2026-11-03: 헤이마오 '发现'처럼). 기업 응대 순위·사기 전에 확인 바로가기, 소보루 자문단 카드 줄, 최신 소식·공감 많은 제보."""
        hot = S.report_rows("public_consent=1 AND published=1 AND title_hidden=0 AND " + S.PUBLIC_VALID, (), 6, 0, S.HOT_ORDER)
        with conn() as db:
            try: news = db.execute("SELECT id,title,summary,category,COALESCE(published_at,created) AS at FROM articles WHERE status='published' ORDER BY COALESCE(published_at,created) DESC,id DESC LIMIT 3").fetchall()
            except Exception: news = []
        # 운영자 2026-11-03: 자문단은 순서대로 말고 랜덤으로 (네 명씩 보이고, 더 있으면 화면에서 돌아가며 바뀜)
        people = list(helpers(40)); random.shuffle(people)
        sample = False
        if len(people) < 4:  # 운영자 2026-11-03 (밤): 자문단이 적으면 횡해 보임 → '예시' 표시를 단 예시 카드로 채움 (실제 사람 아님)
            sample = True
            people += [{'id': None, 'name': n, 'field': fd, 'org': o, 'kind': 'person', 'intro': i, 'sample': True,
                        'photo_url': url_for('static', filename=f'img/advisors/{a}.jpg')}
                       for a, n, fd, o, i in (('a1', '김서연', '변호사', '소보루 법률사무소', '전자상거래 환불 분쟁을 주로 다뤄요'),
                                              ('a2', '박성훈', '변호사', '법무법인 소보루', '중고차·렌터카 계약 문제를 도와요'),
                                              ('a3', '이정민', '교수', '소보루대학교 법학전문대학원', '소비자법을 연구하고 가르쳐요'),
                                              ('a4', '정민재', '변호사', '법률사무소 소보루', '여행·항공 피해 상담을 해요'))][:4 - len(people)]
        return render_template('explore.html', helpers=people, helpers_sample=sample, hot=hot, news=news, ask_link='law_ask' in app.view_functions)

    @app.route('/explore/contact-tips')
    def contact_tips():
        """운영자 2026-11-03: 한국소비자원 '사업자와 접촉 시 소비자 행동요령' 7가지를 해요체로 풀어 둔 페이지 (출처 밝힘)."""
        return render_template('contact_tips.html')

    @app.route('/explore/tricks')
    def guide_tricks():
        """운영자 2026-11-03: 한국소비자원 '악덕상술 유형' 12가지 (출처 밝힘)."""
        return render_template('guide_tricks.html')

    @app.route('/admin/experts/<int:eid>/proof')
    @S.admin_only
    def admin_expert_proof(eid):
        col = 'proof2' if request.args.get('n') == '2' else 'proof'
        with conn() as db: row = db.execute(f'SELECT {col} AS f FROM experts WHERE id=?', (eid,)).fetchone()
        if not row or not row['f'] or not (folder / row['f']).is_file(): abort(404)
        r = send_file(folder / row['f']); r.headers['Cache-Control'] = 'private, no-store'; return r
