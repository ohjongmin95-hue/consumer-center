"""소비자제보센터 3차: 운영 자동화.
- 운영자 제보 검토: 중복 제보 후보, 개인정보 노출 의심, 보완 요청
- 기업 통지와 이력: 기업 공식 이메일로 안내(답변 링크), 발송·직접 연락 기록, 빈도 제한, 수신 거부
  운영자 결정 2026-10-21: 검토 '정상'으로 승인하면 기업에 자동 전달, 답이 없으면 제보자가 '답변 독촉'을 누를 수 있음
- 이메일 알림: 소비자(보완 요청·전달 확인), 가입 기업(새 제보·추가 의견·추가 자료), 운영자(기업 답변·정정·삭제·이의, 개인정보 위험)
- 정정·삭제 요청(제보자)과 이의 신청(기업): 접수 → 운영자 처리 → 결과 안내
- 운영 통계: 실제 DB로 계산하고 집계 기간과 산식을 함께 보여 줌
app.py 끝에서 install(S)로 붙임 (jebo.py와 같은 방식).
"""
import datetime, hashlib, re, secrets
from pathlib import Path
from flask import request, redirect, url_for, flash, abort, render_template, session, g, has_request_context, after_this_request

REQUEST_KINDS = {'correct': '정정 요청', 'delete': '삭제 요청', 'objection': '기업 이의 신청'}
REQUEST_STATUSES = ('접수', '처리 완료', '반려')
NOTICE_KINDS = {'first': '첫 안내 메일', 'remind': '재안내 메일', 'manual': '직접 연락 기록'}
NOTICE_GAP_HOURS = 72          # 같은 제보로 기업에 다시 메일을 보내려면 이만큼 지나야 함
NOTICE_MAX_PER_CASE = 3        # 제보 하나로 기업에 보내는 안내 메일 최대 횟수
NOTICE_MAX_PER_COMPANY_DAY = 20  # 기업 한 곳에 하루에 보내는 안내 메일 최대 횟수
ALERT_GAP_MINUTES = 30         # 가입 기업 알림(추가 의견·자료)은 같은 제보로 이 간격 안에 한 번만
DELAY_DAYS = 7                 # 이만큼 아무 처리 기록이 없으면 '처리 지연'
MAX_CASE_FILES = 10            # 제보 하나에 붙일 수 있는 첨부 파일 (처음 + 추가 자료)
NUDGE_AFTER_DAYS = 3           # 기업에 전달된 뒤 이만큼 답이 없으면 제보자가 독촉할 수 있음
NUDGE_MAX = 2                  # 제보 하나에 독촉 횟수
STAT_PERIODS = {'30': '최근 30일', '90': '최근 90일', '365': '최근 1년', 'all': '전체 기간'}

RISK = [('전화번호', re.compile(r'01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}')),
        ('이메일', re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')),
        ('주민등록번호', re.compile(r'\d{6}\s?-\s?[1-4]\d{6}')),
        ('계좌번호', re.compile(r'\d{2,6}-\d{2,6}-\d{2,8}')),
        ('상세 주소', re.compile(r'\d+\s?동\s?\d+\s?호'))]


def risks(*texts):
    """개인정보로 보이는 내용 종류. 공개 전 운영자가 꼭 가리도록 표시만 하고, 자동으로 고치지는 않음."""
    return [name for name, rx in RISK if any(rx.search(t or '') for t in texts)]


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS company_notices(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL,company_id INTEGER,kind TEXT NOT NULL,
        target TEXT NOT NULL DEFAULT '',status TEXT NOT NULL,memo TEXT NOT NULL DEFAULT '',actor TEXT NOT NULL DEFAULT '',created TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS case_requests(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL,who TEXT NOT NULL,kind TEXT NOT NULL,body TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT '접수',result TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,handled_at TEXT NOT NULL DEFAULT '',actor TEXT NOT NULL DEFAULT '')''')
    db.execute('CREATE INDEX IF NOT EXISTS company_notices_case ON company_notices(case_id)')
    db.execute('CREATE INDEX IF NOT EXISTS case_requests_case ON case_requests(case_id)')
    cols = {r['name'] for r in db.execute('PRAGMA table_info(companies)')}
    for c in ('notice_optout', 'optout_token'):
        if c not in cols: db.execute(f"ALTER TABLE companies ADD COLUMN {c} TEXT NOT NULL DEFAULT ''")
    cols = {r['name'] for r in db.execute('PRAGMA table_info(cases)')}
    if 'supplement_at' not in cols: db.execute("ALTER TABLE cases ADD COLUMN supplement_at TEXT NOT NULL DEFAULT ''")
    # 센터 메시지를 보낸 담당자 이름 (제보자 화면에 보여 줌). 대표 계정이 보내면 빈칸 → '센터'로만 표시
    if 'sender' not in {r['name'] for r in db.execute('PRAGMA table_info(messages)')}: db.execute("ALTER TABLE messages ADD COLUMN sender TEXT NOT NULL DEFAULT ''")


def later(fn):
    """요청이 끝나 DB 저장(커밋)이 된 뒤에 보냄. 보내기 기록을 쓰다가 DB가 잠기지 않게."""
    if not has_request_context(): return fn()
    @after_this_request
    def run(resp):
        fn(); return resp


def ago(**kw):
    return (datetime.datetime.now() - datetime.timedelta(**kw)).isoformat(timespec='seconds')


def hours_between(a, b):
    try:
        return (datetime.datetime.fromisoformat(b[:19]) - datetime.datetime.fromisoformat(a[:19])).total_seconds() / 3600
    except ValueError:
        return None


def install(S):
    app = S.app; conn = S.conn; notify = S.notify; now = S.now; jebo = S.jebo
    STATUSES = S.STATUSES
    with conn() as db: migrate(db)
    app.jinja_env.globals.update(OPS_REQUEST_KINDS=REQUEST_KINDS, OPS_NOTICE_KINDS=NOTICE_KINDS, NOTIFY_EVENTS=notify.EVENTS)

    def case_link(case_id):
        return url_for('admin_report', case_id=case_id, _external=True)

    # ---- 알림 -----------------------------------------------------------------
    def admin_alert(case, event, title, lines):
        body = '\n'.join(lines + ['', '관리자 화면에서 확인해 주세요.', case_link(case['id'])])
        subject = f"[{notify.site_name()}] {title}: {case['receipt']}"
        later(lambda: notify.admin_alert(conn, case, event, subject, body))

    def optout_url(db, company):
        token = company['optout_token']
        if not token:
            token = secrets.token_urlsafe(18)
            db.execute('UPDATE companies SET optout_token=? WHERE id=?', (token, company['id']))
        return url_for('company_optout', token=token, _external=True)

    def member_alert(db, case, event):
        """가입한 기업 담당자에게 알림 메일. 수신 거부했거나 같은 알림을 방금 보냈으면 건너뜀."""
        if not case['company_id'] or not case['share_company'] or not case['forwarded_at']: return
        co = db.execute("SELECT * FROM companies WHERE id=? AND status='active'", (case['company_id'],)).fetchone()
        if not co or co['notice_optout'] or not co['contact_email'] or not notify.email_ready(): return
        if db.execute("SELECT 1 FROM notifications WHERE case_id=? AND event=? AND channel='company_email' AND created>=?", (case['id'], event, ago(minutes=ALERT_GAP_MINUTES))).fetchone(): return
        what = {'company_new': '새 제보가 전달됐습니다', 'company_opinion': '제보자가 추가 의견을 남겼습니다', 'company_files': '제보자가 추가 자료를 냈습니다',
                'company_nudge': '제보자가 답변을 기다리고 있습니다'}[event]
        body = (f"{co['name']} 담당자님, {notify.site_name()}에서 알려 드립니다.\n\n{what}.\n■ 접수번호: {case['receipt']}\n■ 분야: {case['category']}\n\n"
                f"기업 회원 화면에서 확인해 주세요.\n{url_for('biz_case', case_id=case['id'], _external=True)}\n\n"
                f"{notify.site_name()}는 공공기관이 아닌 민간 플랫폼이며, 답변 등록은 무료입니다.\n이런 메일을 그만 받으려면: {optout_url(db, co)}")
        to = co['contact_email']
        later(lambda: notify.company_email(conn, case, event, to, f"[{notify.site_name()}] {what}", body))
    S.ops_member_alert = member_alert

    def answer_alert(case):
        admin_alert(case, 'admin_answer', '기업 답변 등록', [f"■ 업체: {case['company']}", f"■ 제목: {notify.short(case['subject'], 60)}",
                                                         '', '공개 제보라면 답변을 확인한 뒤 사이트 공개 여부를 정해 주세요.' if case['public_consent'] else ''])
    S.ops_answer_alert = answer_alert

    def risk_alert(case):
        found = risks(case['subject'], case['description'])
        if found:
            admin_alert(case, 'admin_risk', '개인정보 노출 의심 제보', [f"■ 의심 항목: {', '.join(found)}", '', '공개를 고른 제보라면 공개용 글에서 꼭 가려 주세요.' if case['public_consent'] else '비밀글이라 공개되지는 않아요.'])
    S.ops_risk_alert = risk_alert

    # ---- 운영자 제보 화면에 보일 정보 ----------------------------------------------
    def context(db, case):
        digits = re.sub(r'\D', '', case['phone'] or '')
        since = ago(days=90)
        rows = db.execute('SELECT id,receipt,subject,company,status,created,phone,company_id FROM cases WHERE id!=? AND created>=? ORDER BY id DESC LIMIT 500', (case['id'], since)).fetchall()
        norm = S.norm_company(case['company'])
        dups = []
        for r in rows:
            why = []
            if digits and re.sub(r'\D', '', r['phone'] or '') == digits: why.append('같은 휴대폰 번호')
            if (case['company_id'] and r['company_id'] == case['company_id']) or (norm and S.norm_company(r['company']) == norm):
                if S.norm_company(r['subject']) == S.norm_company(case['subject']): why.append('같은 업체·같은 제목')
                elif why: why.append('같은 업체')
            if why: dups.append((r, why))
        company = db.execute('SELECT * FROM companies WHERE id=?', (case['company_id'],)).fetchone() if case['company_id'] else None
        notices = db.execute('SELECT * FROM company_notices WHERE case_id=? ORDER BY id DESC', (case['id'],)).fetchall()
        reqs = db.execute('SELECT * FROM case_requests WHERE case_id=? ORDER BY id DESC', (case['id'],)).fetchall()
        return dict(risks=risks(case['subject'], case['description'], case['request_text']),
                    public_risks=risks(case['public_subject'], case['public_body'], case['public_request']) if case['public_consent'] else [],
                    dups=dups[:8], company=company, notices=notices, requests=reqs, notice_block=notice_block(db, case, company),
                    notice_to=notice_target(company), files=db.execute('SELECT COUNT(*) FROM attachments WHERE case_id=?', (case['id'],)).fetchone()[0])
    S.ops_context = context

    def notice_target(company):
        if not company: return ''
        return company['official_email'] or (company['contact_email'] if company['status'] == 'active' else '')

    def notice_block(db, case, company):
        """기업 안내 메일을 지금 보낼 수 없는 이유. 보낼 수 있으면 ''."""
        if not case['share_company']: return '제보자가 기업 전달에 동의하지 않았어요.'
        if case['review'] in jebo.NOT_VALID: return '반려·중복 처리된 제보예요.'
        if not company: return '먼저 이 제보를 기업에 연결해 주세요.'
        if company['notice_optout']: return f"{company['name']}이(가) 안내 메일 수신을 거부했어요 ({company['notice_optout'][:10]})."
        if not notice_target(company): return '기업 공식 이메일이 없어요. 기업 화면에서 공식 이메일을 넣어 주세요.'
        sent = db.execute("SELECT created FROM company_notices WHERE case_id=? AND kind IN ('first','remind') AND status='보냄' ORDER BY id DESC", (case['id'],)).fetchall()
        if len(sent) >= NOTICE_MAX_PER_CASE: return f'이 제보로는 안내 메일을 {NOTICE_MAX_PER_CASE}번까지 보낼 수 있어요.'
        if sent and sent[0]['created'] > ago(hours=NOTICE_GAP_HOURS): return f'마지막 안내 메일 뒤 {NOTICE_GAP_HOURS}시간이 지나야 다시 보낼 수 있어요.'
        if db.execute("SELECT COUNT(*) FROM company_notices WHERE company_id=? AND kind IN ('first','remind') AND status='보냄' AND created>=?", (company['id'], ago(days=1))).fetchone()[0] >= NOTICE_MAX_PER_COMPANY_DAY:
            return f'이 기업에는 하루에 {NOTICE_MAX_PER_COMPANY_DAY}통까지만 보내요.'
        if not notify.email_ready(): return '메일 발송 설정(SMTP)이 없어 보낼 수 없어요. 직접 연락했다면 아래에 기록해 주세요.'
        return ''

    # ---- 운영자 제보 화면의 양식 (report_detail에서 부름) ------------------------------
    def handle_form(db, case, form):
        cid = case['id']
        if form == 'supplement':
            body = request.form.get('body', '').strip()
            if not body or len(body) > 3000: flash('보완 요청 내용을 적어 주세요.'); return
            db.execute('INSERT INTO messages(case_id,author,body,created,sender) VALUES(?,?,?,?,?)', (cid, '센터', '[보완 요청] ' + body, now(), S.staff_sender()))
            db.execute('UPDATE cases SET supplement_at=? WHERE id=?', (now(), cid))
            if STATUSES.index(case['status']) < 2:
                db.execute('UPDATE cases SET status=? WHERE id=?', (STATUSES[2], cid)); S.log_case(db, cid, f"진행 단계 변경: {case['status']} → {STATUSES[2]}")
            S.log_case(db, cid, '제보자에게 보완 요청'); S.notify_later(cid, 'supplement')
            flash('보완 요청을 보냈어요. 제보자 조회 화면에 보이고, 연락처가 있으면 알림이 가요.')
        elif form == 'notice':
            company = db.execute('SELECT * FROM companies WHERE id=?', (case['company_id'],)).fetchone() if case['company_id'] else None
            block = notice_block(db, case, company)
            if block: flash(block); return
            send_notice(db, case, company)
        elif form == 'notice_manual':
            memo = request.form.get('memo', '').strip()[:300]
            if not memo: flash('어떻게 연락했는지 적어 주세요.'); return
            db.execute('INSERT INTO company_notices(case_id,company_id,kind,status,memo,actor,created) VALUES(?,?,?,?,?,?,?)', (cid, case['company_id'], 'manual', '기록', memo, S.actor_name(), now()))
            S.log_case(db, cid, '기업 연락 기록: ' + memo[:60]); flash('연락 기록을 남겼어요.')
        elif form == 'request_done':
            handle_request(db, request.form.get('request_id', type=int), cid)
    S.ops_handle_form = handle_form
    S.OPS_FORMS = ('supplement', 'notice', 'notice_manual', 'request_done')

    def send_notice(db, case, company, quiet=False, actor=None, nudge=False):
        """기업 공식 이메일로 답변 링크를 보냄 (운영자 버튼, 승인 시 자동 전달, 제보자 독촉). 보냈으면 True.
        메일을 보냈다고 '기업이 확인했다'고 표시하지 않음(열어 봐야 확인)."""
        cid = case['id']; to = notice_target(company)
        token = secrets.token_urlsafe(32)
        db.execute('INSERT OR REPLACE INTO company_invites(case_id,token_hash,company_name,created) VALUES(?,?,?,?)', (cid, hashlib.sha256(token.encode()).hexdigest(), company['name'], now()))
        link = url_for('company_access', case_id=cid, token=token, _external=True); optout = optout_url(db, company)
        kind = 'remind' if db.execute("SELECT 1 FROM company_notices WHERE case_id=? AND kind IN ('first','remind') AND status='보냄'", (cid,)).fetchone() else 'first'
        subject = f"[{notify.site_name()}] {company['name']} 관련 소비자 제보 안내 ({case['receipt']})" + (' - 재안내' if kind == 'remind' else '')
        body = (f"{company['name']} 고객 담당자님께,\n\n{notify.site_name()}에 {company['name']}와(과) 관련된 소비자 제보가 접수돼 안내드립니다.\n\n"
                f"■ 접수번호: {case['receipt']}\n■ 분야: {case['category']}\n■ 접수일: {case['created'][:10]}\n\n"
                + ("제보자가 아직 답변을 받지 못해 답변을 기다리고 있다고 알려 왔습니다.\n\n" if nudge else '') +
                f"아래 링크에서 제보 내용을 확인하고 공식 답변을 남길 수 있습니다. 답변 등록은 무료이며, 링크는 이 제보 하나만 볼 수 있습니다.\n{link}\n\n"
                "이 메일에 바로 답장하셔도 담당자가 받아 봅니다.\n\n"
                "제보는 소비자 개인의 경험과 주장이며, 센터가 사실관계를 확인한 내용이 아닙니다. 답변 여부와 내용은 귀사가 정합니다.\n"
                f"{notify.site_name()}는 공공기관이 아닌 민간 플랫폼입니다.\n\n"
                f"이런 안내 메일을 그만 받으려면: {optout}")
        html = render_template('company_notice_email.html', subject=subject, company=company['name'], site=notify.site_name(), receipt=case['receipt'],
                               category=case['category'], created=case['created'][:10], link=link, optout=optout, nudge=nudge, remind=kind == 'remind')
        try:
            notify.send_email(to, subject, body, html=html); status, memo = '보냄', ''
        except Exception as e:
            status, memo = '실패', str(e)[:200]
        db.execute('INSERT INTO company_notices(case_id,company_id,kind,target,status,memo,actor,created) VALUES(?,?,?,?,?,?,?,?)',
                   (cid, company['id'], kind, notify.mask(to), status, memo, actor or S.actor_name(), now()))
        if status == '보냄':
            jebo.mark(db, cid, 'forwarded_at')
            S.log_case(db, cid, f"기업 {NOTICE_KINDS[kind]} 보냄 ({notify.mask(to)})")
            if not quiet: flash(f"{company['name']}에 {NOTICE_KINDS[kind]}을 보냈어요. 기업이 링크를 열어야 '기업 전달 확인'으로 바뀌어요.")
            to_wait(db, cid)
            return True
        S.log_case(db, cid, f'기업 안내 메일 실패: {memo[:60]}')
        if not quiet: flash('메일을 보내지 못했어요: ' + memo)
        return False

    def to_wait(db, cid):
        """기업에 전달되면 진행 단계를 '기업 답변 대기'로 올리고 제보자에게 알림 (이미 그 뒤 단계면 그대로)"""
        case = db.execute('SELECT status FROM cases WHERE id=?', (cid,)).fetchone()
        if jebo.STATUS_MY.get(case['status'], 0) >= jebo.STATUS_MY['기업 답변 대기']: return
        db.execute("UPDATE cases SET status='기업 답변 대기' WHERE id=?", (cid,)); jebo.mark(db, cid, 'reviewed_at')
        S.log_case(db, cid, f"진행 단계 변경: {case['status']} → 기업 답변 대기"); S.notify_later(cid, 'status')

    def auto_forward(db, cid):
        """검토 '정상'으로 승인된 제보를 기업에 자동 전달 (운영자 결정 2026-10-21). 관리자에게 보일 문구('' 이면 할 일 없음).
        가입 기업은 담당자 화면으로, 아니면 공식 이메일로 답변 링크. 제보자 동의·수신 거부·횟수 제한은 버튼으로 보낼 때와 같음."""
        case = db.execute('SELECT * FROM cases WHERE id=?', (cid,)).fetchone()
        if case['review'] != 'ok' or case['forwarded_at'] or not case['share_company'] or not case['company_id']: return ''
        company = db.execute('SELECT * FROM companies WHERE id=?', (case['company_id'],)).fetchone()
        if company['status'] == 'active':
            jebo.mark(db, cid, 'forwarded_at'); S.log_case(db, cid, f"기업 담당자 화면에 자동 전달: {company['name']}")
            member_alert(db, db.execute('SELECT * FROM cases WHERE id=?', (cid,)).fetchone(), 'company_new'); to_wait(db, cid)
            return f"{company['name']} 담당자 화면에 자동으로 보냈어요."
        block = notice_block(db, case, company)
        if block:
            S.log_case(db, cid, '기업 자동 전달 못 함: ' + block); return '기업 자동 전달은 못 했어요. ' + block
        if send_notice(db, case, company, quiet=True, actor='자동 전달'): return f"{company['name']}에 안내 메일을 자동으로 보냈어요."
        return '기업 안내 메일을 보내지 못했어요. 처리 기록을 확인해 주세요.'
    S.ops_auto_forward = auto_forward

    # ---- 제보자: 기업 답변 독촉 -------------------------------------------------------
    def nudges(db, cid):
        return db.execute("SELECT created FROM case_log WHERE case_id=? AND action LIKE '제보자 답변 독촉%' ORDER BY id DESC", (cid,)).fetchall()

    def nudge_state(db, case):
        """제보자 화면의 '답변 독촉' 칸. 보일 때가 아니면 None, 아니면 {'why': 지금 못 누르는 이유('' 이면 누를 수 있음), 'count': 누른 횟수}"""
        if not case['forwarded_at'] or jebo.STATUS_MY.get(case['status'], 0) != jebo.STATUS_MY['기업 답변 대기']: return None
        done = nudges(db, case['id']); why = ''
        if len(done) >= NUDGE_MAX: why = f'독촉은 {NUDGE_MAX}번까지 보낼 수 있어요. 센터가 계속 확인할게요.'
        elif case['forwarded_at'] > ago(days=NUDGE_AFTER_DAYS): why = f'기업에 전달된 지 {NUDGE_AFTER_DAYS}일이 지나면 누를 수 있어요.'
        elif done and done[0]['created'] > ago(hours=NOTICE_GAP_HOURS): why = f'마지막 독촉 뒤 {NOTICE_GAP_HOURS // 24}일이 지나면 다시 누를 수 있어요.'
        return dict(why=why, count=len(done))

    @app.route('/case/nudge', methods=['POST'])
    def case_nudge():
        with conn() as db:
            case = reporter_case(db)
            if not case: return redirect(url_for('lookup'))
            st = nudge_state(db, case)
            if not st: flash('지금은 독촉할 수 없는 단계예요.'); return redirect(url_for('case_detail'))
            if st['why']: flash(st['why']); return redirect(url_for('case_detail') + '#nudge')
            company = db.execute('SELECT * FROM companies WHERE id=?', (case['company_id'],)).fetchone() if case['company_id'] else None
            how = '센터에 알림'
            if company and company['status'] == 'active' and company['contact_email']:
                member_alert(db, case, 'company_nudge'); how = '기업 담당자에게 알림 메일'
            elif company and not notice_block(db, case, company) and send_notice(db, case, company, quiet=True, actor='제보자', nudge=True):
                how = '기업 공식 이메일로 재안내'
            db.execute('INSERT INTO case_log(case_id,actor,action,created) VALUES(?,?,?,?)', (case['id'], '제보자', f'제보자 답변 독촉 ({how})', now()))
            if how == '센터에 알림':  # 메일로 못 보내면 운영자가 직접 연락하도록
                admin_alert(case, 'admin_request', '제보자 답변 독촉', [f"■ 업체: {case['company']}", '기업에 메일로 보낼 수 없어 운영자 연락이 필요해요.'])
        flash('기업에 답변을 독촉했어요. 답변이 오면 바로 알려 드릴게요.')
        return redirect(url_for('case_detail') + '#nudge')

    # ---- 기업 수신 거부 ----------------------------------------------------------
    @app.route('/company/optout/<token>', methods=['GET', 'POST'])
    def company_optout(token):
        if len(token) > 60: abort(404)
        with conn() as db:
            co = db.execute("SELECT * FROM companies WHERE optout_token=? AND optout_token!=''", (token,)).fetchone()
            if not co: abort(404)
            if request.method == 'POST':
                if not co['notice_optout']: db.execute('UPDATE companies SET notice_optout=? WHERE id=?', (now(), co['id']))
                co = db.execute('SELECT * FROM companies WHERE id=?', (co['id'],)).fetchone()
        return render_template('company_optout.html', company=co)

    # ---- 제보자: 추가 자료, 정정·삭제 요청 ------------------------------------------
    def reporter_case(db):
        case_id = session.get('case_id')
        if not case_id: return None
        return db.execute('SELECT * FROM cases WHERE id=?', (case_id,)).fetchone()

    @app.route('/case/files', methods=['POST'])
    def case_files():
        with conn() as db:
            case = reporter_case(db)
            if not case: return redirect(url_for('lookup'))
            have = db.execute('SELECT COUNT(*) FROM attachments WHERE case_id=?', (case['id'],)).fetchone()[0]
            files = [f for f in request.files.getlist('evidence') if f and f.filename]
            if not files: flash('올릴 파일을 골라 주세요.'); return redirect(url_for('case_detail') + '#more-files')
            if len(files) > S.MAX_FILES or have + len(files) > MAX_CASE_FILES:
                flash(f'첨부파일은 한 번에 {S.MAX_FILES}개, 제보 하나에 모두 {MAX_CASE_FILES}개까지 올릴 수 있어요.'); return redirect(url_for('case_detail') + '#more-files')
            total = 0; checked = []
            for f in files:
                suffix = Path(f.filename).suffix.lower()
                head = f.stream.read(12); f.stream.seek(0, 2); size = f.stream.tell(); f.stream.seek(0); total += size
                if suffix not in S.UPLOAD_TYPES or not S.file_ok(suffix, head):
                    flash('첨부는 사진, PDF, 동영상(mp4·mov) 파일만 가능해요.'); return redirect(url_for('case_detail') + '#more-files')
                checked.append((f, suffix, re.sub(r'[\x00-\x1f/\\]', '', Path(f.filename.replace('\\', '/')).name)[:180] or 'file' + suffix))
            if total > S.MAX_UPLOAD_TOTAL: flash('첨부파일은 한 번에 모두 합쳐 20MB까지 올릴 수 있어요.'); return redirect(url_for('case_detail') + '#more-files')
            for f, suffix, original in checked:
                stored = secrets.token_hex(20) + suffix; f.save(S.UPLOAD / stored)
                db.execute('INSERT INTO attachments(case_id,stored,original) VALUES(?,?,?)', (case['id'], stored, original))
            db.execute('INSERT INTO case_log(case_id,actor,action,created) VALUES(?,?,?,?)', (case['id'], '제보자', f'추가 자료 {len(checked)}개 제출', now()))
            member_alert(db, case, 'company_files')
        flash('추가 자료를 올렸어요. 센터가 확인해요. 자료는 공개되지 않아요.')
        return redirect(url_for('case_detail') + '#more-files')

    @app.route('/case/request', methods=['POST'])
    def case_request():
        kind = request.form.get('kind', ''); body = request.form.get('body', '').strip()
        if kind not in ('correct', 'delete'): abort(400)
        with conn() as db:
            case = reporter_case(db)
            if not case: return redirect(url_for('lookup'))
            if not body or len(body) > 2000: flash('요청 내용을 2,000자 이내로 적어 주세요.'); return redirect(url_for('case_detail') + '#requests')
            if db.execute("SELECT 1 FROM case_requests WHERE case_id=? AND who='reporter' AND status='접수'", (case['id'],)).fetchone():
                flash('처리 중인 요청이 있어요. 센터가 처리한 뒤 다시 요청해 주세요.'); return redirect(url_for('case_detail') + '#requests')
            add_request(db, case, 'reporter', kind, body, '제보자')
        flash(f'{REQUEST_KINDS[kind]}을 받았어요. 센터가 확인한 뒤 이 화면의 메시지로 결과를 알려 드려요.')
        return redirect(url_for('case_detail') + '#requests')

    def add_request(db, case, who, kind, body, actor):
        db.execute('INSERT INTO case_requests(case_id,who,kind,body,created) VALUES(?,?,?,?,?)', (case['id'], who, kind, body, now()))
        db.execute('INSERT INTO case_log(case_id,actor,action,created) VALUES(?,?,?,?)', (case['id'], actor, f'{REQUEST_KINDS[kind]} 접수', now()))
        admin_alert(case, 'admin_request', REQUEST_KINDS[kind], [f"■ 업체: {case['company']}", f"■ 요청: {notify.short(body, 200)}"])

    def reporter_extras(db, case):
        return dict(requests=db.execute("SELECT * FROM case_requests WHERE case_id=? AND who='reporter' ORDER BY id DESC", (case['id'],)).fetchall(),
                    alerts=db.execute("SELECT event,channel,status,created FROM notifications WHERE case_id=? AND channel IN ('kakao','email') ORDER BY id DESC LIMIT 20", (case['id'],)).fetchall(),
                    files=db.execute('SELECT COUNT(*) FROM attachments WHERE case_id=?', (case['id'],)).fetchone()[0], max_files=MAX_CASE_FILES,
                    supplement=case['supplement_at'] and case['status'] == STATUSES[2], nudge=nudge_state(db, case))
    S.ops_reporter_extras = reporter_extras

    # ---- 기업: 이의 신청 (가입 기업 화면, 답변 링크 화면) -----------------------------
    def company_objection(db, case, actor):
        body = request.form.get('body', '').strip()
        if not body or len(body) > 3000: flash('이의 신청 내용을 3,000자 이내로 적어 주세요.'); return
        if db.execute("SELECT 1 FROM case_requests WHERE case_id=? AND who='company' AND status='접수'", (case['id'],)).fetchone():
            flash('처리 중인 이의 신청이 있어요. 센터가 처리한 뒤 다시 신청해 주세요.'); return
        add_request(db, case, 'company', 'objection', body, actor)
        flash('이의 신청을 받았어요. 센터가 제보 내용과 함께 검토한 뒤 이 화면에 결과를 남겨요.')
    S.ops_company_objection = company_objection

    def company_requests(db, case_id):
        return db.execute("SELECT * FROM case_requests WHERE case_id=? AND who='company' ORDER BY id DESC", (case_id,)).fetchall()
    S.ops_company_requests = company_requests

    @app.route('/biz/case/<int:case_id>/objection', methods=['POST'])
    def biz_objection(case_id):
        if g.get('biz_preview'): flash('미리보기에서는 보낼 수 없어요.'); return redirect(url_for('biz_case', case_id=case_id))
        with conn() as db:
            case = db.execute("SELECT * FROM cases WHERE id=? AND company_id=? AND share_company=1 AND forwarded_at!=''", (case_id, g.company['id'])).fetchone()
            if not case: abort(404)
            company_objection(db, case, g.company['name'] + ' (기업 회원)')
        return redirect(url_for('biz_case', case_id=case_id) + '#objection')

    # ---- 운영자: 정정·삭제·이의 처리 ---------------------------------------------
    def handle_request(db, req_id, case_id=None):
        req = db.execute('SELECT * FROM case_requests WHERE id=?', (req_id,)).fetchone()
        if not req or (case_id and req['case_id'] != case_id) or req['status'] != '접수': abort(400)
        status = '처리 완료' if request.form.get('decision') == 'done' else '반려'
        result = request.form.get('result', '').strip()[:1000]
        if not result: flash('처리 결과를 적어 주세요. 요청한 쪽에 그대로 보여요.'); return
        db.execute('UPDATE case_requests SET status=?,result=?,handled_at=?,actor=? WHERE id=?', (status, result, now(), S.actor_name(), req['id']))
        S.log_case(db, req['case_id'], f"{REQUEST_KINDS[req['kind']]} {status}")
        if req['who'] == 'reporter':
            db.execute('INSERT INTO messages(case_id,author,body,created,sender) VALUES(?,?,?,?,?)', (req['case_id'], '센터', f"[{REQUEST_KINDS[req['kind']]} {status}] {result}", now(), S.staff_sender()))
            S.notify_later(req['case_id'], 'message')
        flash(f"{REQUEST_KINDS[req['kind']]}을 {status}로 처리했어요.")

    @app.route('/admin/requests', methods=['GET', 'POST'])
    @S.admin_only
    def admin_requests():
        g.area = 'admin'
        show = request.args.get('status', '접수')
        if show not in REQUEST_STATUSES + ('all',): show = '접수'
        with conn() as db:
            if request.method == 'POST':
                handle_request(db, request.form.get('request_id', type=int))
                return redirect(url_for('admin_requests', status=show))
            counts = {r['status']: r['n'] for r in db.execute('SELECT status,COUNT(*) AS n FROM case_requests GROUP BY status')}
            rows = db.execute('SELECT r.*,c.receipt,c.subject,c.company FROM case_requests r JOIN cases c ON c.id=r.case_id' + ('' if show == 'all' else ' WHERE r.status=?') + ' ORDER BY r.id DESC LIMIT 300',
                              () if show == 'all' else (show,)).fetchall()
        return render_template('admin_requests.html', rows=rows, counts=counts, show=show, statuses=REQUEST_STATUSES)

    # ---- 운영자 홈: 처리 지연 -------------------------------------------------------
    def delayed(db, limit=8):
        """종결 전인데 DELAY_DAYS일 넘게 아무 처리 기록(로그·메시지)이 없는 제보."""
        cut = ago(days=DELAY_DAYS)
        rows = db.execute(f"""SELECT c.id,c.receipt,c.subject,c.company,c.status,c.created,
            MAX(c.created,COALESCE((SELECT MAX(created) FROM case_log WHERE case_id=c.id),''),COALESCE((SELECT MAX(created) FROM messages WHERE case_id=c.id),'')) AS last
            FROM cases c WHERE c.status!=? AND c.review NOT IN ('rejected','duplicate')""", (STATUSES[-1],)).fetchall()
        late = sorted([r for r in rows if r['last'] < cut], key=lambda r: r['last'])
        return len(late), late[:limit]

    def home_extras(db):
        n_late, late = delayed(db)
        return dict(late=late, n_late=n_late, delay_days=DELAY_DAYS,
                    n_requests=db.execute("SELECT COUNT(*) FROM case_requests WHERE status='접수'").fetchone()[0],
                    n_unreviewed=db.execute("SELECT COUNT(*) FROM cases WHERE review=''").fetchone()[0])
    S.ops_home_extras = home_extras

    # ---- 운영 통계 ----------------------------------------------------------------
    @app.route('/admin/stats')
    @S.admin_only
    def admin_stats():
        period = request.args.get('period', '90')
        if period not in STAT_PERIODS: period = '90'
        since = '' if period == 'all' else ago(days=int(period))
        with conn() as db:
            stats = compute_stats(db, since)
            first = db.execute('SELECT MIN(created) FROM cases').fetchone()[0] or ''
        return render_template('admin_stats.html', s=stats, period=period, periods=STAT_PERIODS, since=since or first, until=now(), statuses=STATUSES)

    def compute_stats(db, since):
        rows = db.execute("SELECT * FROM cases WHERE created>=? AND review NOT IN ('rejected','duplicate')", (since,)).fetchall()
        all_n = db.execute('SELECT COUNT(*) FROM cases WHERE created>=?', (since,)).fetchone()[0]
        ids = [r['id'] for r in rows]
        first_answer = {}
        if ids:
            q = ','.join('?' * len(ids))
            for m in db.execute(f"SELECT case_id,MIN(created) AS t FROM messages WHERE author='기업 답변' AND case_id IN ({q}) GROUP BY case_id", ids): first_answer[m['case_id']] = m['t']
        names = {c['id']: c['name'] for c in db.execute('SELECT id,name FROM companies')}
        def count(f): return sum(1 for r in rows if f(r))
        def pct(a, b): return round(100 * a / b, 1) if b else None
        def avg(vals):
            vals = [v for v in vals if v is not None and v >= 0]
            return (round(sum(vals) / len(vals) / 24, 1), len(vals)) if vals else (None, 0)
        by_cat, by_co, by_status = {}, {}, {}
        for r in rows:
            by_cat[jebo.cat_label(r['category'])] = by_cat.get(jebo.cat_label(r['category']), 0) + 1
            key = names.get(r['company_id']) or (r['company'] or '').strip() or '(업체명 없음)'
            by_co[key] = by_co.get(key, 0) + 1
            by_status[r['status']] = by_status.get(r['status'], 0) + 1
        shared = [r for r in rows if r['share_company']]
        forwarded = [r for r in shared if r['forwarded_at']]
        answered = [r for r in forwarded if r['id'] in first_answer]
        valid = len(rows)
        return dict(
            valid=valid, excluded=all_n - valid,
            by_cat=sorted(by_cat.items(), key=lambda x: -x[1]), by_co=sorted(by_co.items(), key=lambda x: -x[1])[:10], by_status=by_status,
            shared=len(shared), forwarded=len(forwarded), forwarded_pct=pct(len(forwarded), len(shared)),
            seen=count(lambda r: r['share_company'] and r['forwarded_at'] and r['seen_at']), seen_pct=pct(count(lambda r: r['share_company'] and r['forwarded_at'] and r['seen_at']), len(forwarded)),
            answered=len(answered), answered_pct=pct(len(answered), len(forwarded)),
            confirmed=count(lambda r: r['confirmed_at']), resolved=count(lambda r: r['outcome'] == 'resolved'), unresolved=count(lambda r: r['outcome'] == 'unresolved'),
            confirmed_pct=pct(count(lambda r: r['confirmed_at']), len(answered)),
            closed=count(lambda r: r['status'] == STATUSES[-1]),
            avg_close=avg([hours_between(r['created'], r['closed_at']) for r in rows if r['status'] == STATUSES[-1] and r['closed_at']]),
            avg_answer=avg([hours_between(r['forwarded_at'], first_answer[r['id']]) for r in answered]),
            public=count(lambda r: r['public_consent']), public_pct=pct(count(lambda r: r['public_consent']), valid),
            published=count(lambda r: r['public_consent'] and r['published']), published_pct=pct(count(lambda r: r['public_consent'] and r['published']), count(lambda r: r['public_consent'])),
            requests={r['kind']: r['n'] for r in db.execute('SELECT kind,COUNT(*) AS n FROM case_requests WHERE created>=? GROUP BY kind', (since,))},
            notices=db.execute("SELECT COUNT(*) FROM company_notices WHERE kind IN ('first','remind') AND status='보냄' AND created>=?", (since,)).fetchone()[0])
