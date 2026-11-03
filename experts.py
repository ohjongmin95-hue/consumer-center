"""전문가 등록 (운영자 요청 2026-11-03: 전문가를 한 명씩 가입시키기).
- 관리자 > 회원 > 전문가에서 이름·분야·소속을 넣고 '초대 링크'를 만든다. 링크를 받은 전문가가 로그인(카카오 등)하고
  자격 정보를 확인해 보내면 바로 '전문가'가 된다(운영자가 직접 모신 분이라).
- 초대 없이 /expert/apply 에서 신청할 수도 있다. 이건 관리자가 자격을 확인하고 승인해야 전문가가 된다.
- 승인된 전문가가 제보에 댓글을 달면 이름 옆에 '전문가 · 변호사' 같은 표시가 붙는다.
- 법무법인·사무소 같은 곳도 '전문 기관'으로 등록할 수 있다(사업자등록번호·로고).
- 수수료·수임료·광고비는 받지 않는다. 로톡처럼 사건을 연결해 돈을 받는 구조가 아니라 표시만 해 주는 플랫폼 (운영자 2026-11-03).
- 자격증 사진(증빙)은 관리자만 볼 수 있다. 관리자는 언제든 표시를 멈추거나 다시 켤 수 있다.
"""
import datetime, os, secrets, uuid

from flask import abort, flash, g, redirect, render_template, request, send_file, url_for

FIELDS = ('변호사', '손해사정사', '공인회계사', '세무사', '공인노무사', '법무사', '변리사', '감정평가사',
          '소비자전문상담사', '의사', '약사', '자동차 정비', '건축·인테리어', '기타 전문가')
FIRM_FIELDS = ('법무법인', '법률사무소', '손해사정법인', '세무법인', '회계법인', '노무법인', '특허법인', '법무사사무소', '기타 전문 기관')  # 운영자 2026-11-03: 사무소·법인도 등록
KINDS = {'person': '전문가', 'firm': '전문 기관'}
STATUS = {'invited': '초대함', 'pending': '확인 기다림', 'approved': '전문가', 'rejected': '반려', 'stopped': '멈춤'}
PROOF_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.pdf')


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS experts(id INTEGER PRIMARY KEY,user_id INTEGER UNIQUE,name TEXT NOT NULL,field TEXT NOT NULL,
        org TEXT NOT NULL DEFAULT '',license_no TEXT NOT NULL DEFAULT '',intro TEXT NOT NULL DEFAULT '',phone TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL DEFAULT '',proof TEXT NOT NULL DEFAULT '',photo TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'pending',token TEXT UNIQUE,
        note TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,approved TEXT NOT NULL DEFAULT '')''')
    cols = {r[1] for r in db.execute('PRAGMA table_info(experts)')}
    if 'photo' not in cols: db.execute("ALTER TABLE experts ADD COLUMN photo TEXT NOT NULL DEFAULT ''")
    if 'kind' not in cols: db.execute("ALTER TABLE experts ADD COLUMN kind TEXT NOT NULL DEFAULT 'person'")


def labels(db, user_ids):
    """{회원 번호: {'field': '변호사', 'photo': 사진 주소}} — 승인된 전문가만."""
    ids = [int(i) for i in set(user_ids) if i]
    if not ids: return {}
    try:
        rows = db.execute(f"SELECT id,user_id,field,photo,kind FROM experts WHERE status='approved' AND user_id IN ({','.join('?' * len(ids))})", ids).fetchall()
    except Exception:
        return {}
    return {r[1]: {'field': r[2], 'photo': photo_url(r[0], r[3]), 'label': KINDS.get(r[4], '전문가')} for r in rows}


def photo_url(eid, photo):
    return f'/expert/{eid}/photo.jpg?v={photo[:8]}' if photo else ''


def install(S):
    app, conn = S.app, S.conn
    folder = S.UPLOAD / 'experts'; folder.mkdir(parents=True, exist_ok=True)
    with conn() as db: migrate(db)

    def now(): return datetime.datetime.now().isoformat(timespec='seconds')
    def clean(name, n): return ' '.join((request.form.get(name) or '').split())[:n]

    def save_proof(old=''):
        up = request.files.get('proof')
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
        out = {k: r.get(k, '') for k in ('name', 'field', 'org', 'license_no', 'intro', 'phone', 'email')}
        out['kind'] = r.get('kind') or 'person'
        return out

    def submit(row, invited):
        f = {'name': clean('name', 30), 'field': clean('field', 20), 'org': clean('org', 60), 'license_no': clean('license_no', 40),
             'intro': clean('intro', 120), 'phone': clean('phone', 20), 'email': clean('email', 120)}
        kind = 'firm' if request.form.get('kind') == 'firm' else 'person'
        if not f['name'] or f['field'] not in (FIRM_FIELDS if kind == 'firm' else FIELDS): raise ValueError('이름과 분야를 넣어 주세요.')
        if not f['license_no'] and not request.files.get('proof', None) and not (row and row['proof']):
            raise ValueError('사업자등록번호를 쓰거나 사업자등록증을 올려 주세요.' if kind == 'firm' else '자격·등록번호를 쓰거나 자격증 사진을 올려 주세요.')
        if not request.form.get('agree'): raise ValueError('전문가 표시와 확인 정보 보관에 동의해 주세요.')
        proof = save_proof(row['proof'] if row else '')
        photo = save_photo(row['photo'] if row else '')
        status = 'approved' if invited else 'pending'
        with conn() as db:
            if row:
                db.execute('UPDATE experts SET user_id=?,name=?,field=?,org=?,license_no=?,intro=?,phone=?,email=?,proof=?,photo=?,kind=?,status=?,token=NULL,approved=? WHERE id=?',
                           (g.user['id'], *f.values(), proof, photo, kind, status, now() if invited else '', row['id']))
            else:
                db.execute('INSERT INTO experts(user_id,name,field,org,license_no,intro,phone,email,proof,photo,kind,status,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (g.user['id'], *f.values(), proof, photo, kind, status, now()))
        return status

    @app.route('/expert/apply', methods=['GET', 'POST'])
    @S.member_only
    def expert_apply():
        with conn() as db: mine = db.execute('SELECT * FROM experts WHERE user_id=?', (g.user['id'],)).fetchone()
        if mine and mine['status'] in ('approved', 'pending', 'stopped') and request.method == 'GET':
            return render_template('expert_apply.html', mine=mine, fields=FIELDS, firm_fields=FIRM_FIELDS, kinds=KINDS, f=form_values(mine), invite=None, status=STATUS, photo=photo_url(mine['id'], mine['photo']))
        if request.method == 'POST':
            if mine and mine['status'] in ('approved', 'stopped'): abort(400)
            try:
                submit(mine, False)
            except ValueError as e:
                flash(str(e)); return render_template('expert_apply.html', mine=None, fields=FIELDS, firm_fields=FIRM_FIELDS, kinds=KINDS, f=form_values(request.form), invite=None, status=STATUS)
            flash('전문가 신청을 받았어요. 자격을 확인한 뒤 알려 드릴게요.')
            return redirect(url_for('expert_apply'))
        return render_template('expert_apply.html', mine=None, fields=FIELDS, firm_fields=FIRM_FIELDS, kinds=KINDS, f=form_values(mine), invite=None, status=STATUS)

    @app.route('/expert/photo', methods=['POST'])
    @S.member_only
    def expert_photo_change():
        with conn() as db:
            mine = db.execute('SELECT * FROM experts WHERE user_id=?', (g.user['id'],)).fetchone()
            if not mine: abort(404)
            try: db.execute('UPDATE experts SET photo=? WHERE id=?', (save_photo(mine['photo']), mine['id'])); flash('사진을 바꿨어요.')
            except ValueError as e: flash(str(e))
        return redirect(url_for('expert_apply'))

    @app.route('/expert/<int:eid>/photo.jpg')
    def expert_photo(eid):
        """승인된 전문가 사진만 공개 (관리자는 언제나)."""
        with conn() as db: row = db.execute('SELECT photo,status FROM experts WHERE id=?', (eid,)).fetchone()
        if not row or not row['photo'] or not (folder / row['photo']).is_file(): abort(404)
        if row['status'] != 'approved' and not S.admin_active(): abort(404)
        return send_file(folder / row['photo'], mimetype='image/jpeg', max_age=86400)

    @app.route('/expert/join/<token>', methods=['GET', 'POST'])
    @S.member_only
    def expert_join(token):
        with conn() as db:
            inv = db.execute("SELECT * FROM experts WHERE token=? AND status='invited'", (token,)).fetchone()
            mine = db.execute('SELECT * FROM experts WHERE user_id=?', (g.user['id'],)).fetchone()
        if not inv: abort(404)
        if mine and mine['id'] != inv['id'] and mine['status'] == 'approved':
            flash('이미 전문가로 등록된 계정이에요.'); return redirect(url_for('expert_apply'))
        if request.method == 'POST':
            try:
                if mine and mine['id'] != inv['id']:
                    with conn() as db: db.execute('DELETE FROM experts WHERE id=?', (mine['id'],))  # 초대가 먼저
                submit(inv, True)
            except ValueError as e:
                flash(str(e)); return render_template('expert_apply.html', mine=None, fields=FIELDS, firm_fields=FIRM_FIELDS, kinds=KINDS, f=form_values(request.form), invite=inv, status=STATUS)
            flash('전문가로 등록됐어요. 이제 제보에 댓글을 달면 전문가 표시가 붙어요.')
            return redirect(url_for('expert_apply'))
        return render_template('expert_apply.html', mine=None, fields=FIELDS, firm_fields=FIRM_FIELDS, kinds=KINDS, f=form_values(inv), invite=inv, status=STATUS)

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
                        for f in (row['proof'], row['photo']):
                            if f: (folder / f).unlink(missing_ok=True)
                        db.execute('DELETE FROM experts WHERE id=?', (eid,))
            return redirect(url_for('admin_experts'))
        with conn() as db:
            rows = db.execute('''SELECT e.*,u.nickname FROM experts e LEFT JOIN users u ON u.id=e.user_id
                ORDER BY CASE e.status WHEN 'pending' THEN 0 WHEN 'invited' THEN 1 WHEN 'approved' THEN 2 ELSE 3 END,e.id DESC''').fetchall()
        return render_template('admin_experts.html', rows=rows, fields=FIELDS, firm_fields=FIRM_FIELDS, kinds=KINDS, status=STATUS, photo_url=photo_url,
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

    @app.route('/admin/experts/<int:eid>/proof')
    @S.admin_only
    def admin_expert_proof(eid):
        with conn() as db: row = db.execute('SELECT proof FROM experts WHERE id=?', (eid,)).fetchone()
        if not row or not row['proof'] or not (folder / row['proof']).is_file(): abort(404)
        r = send_file(folder / row['proof']); r.headers['Cache-Control'] = 'private, no-store'; return r
