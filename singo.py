"""해결 도우미 (/doumi). 운영자 2026-11-13: 소보루고발에 '해결 도우미'를 엮음 (고발과 신고가 같은 말로 들려서 '해결'로).

- 피해 유형을 고르면 → 신고할 기관(순서대로), 준비할 것, 신고서 대신 써 주기(복사), 소보루고발에도 올리기.
- 기관 접수는 본인 인증이 필요해서 대신 넣지 않는다. 글을 대신 써 주고 기관 신청 페이지를 열어 주는 데까지.
- 신고서 문장은 화면에서 바로 만든다 (AI 비용 없음). 내가 쓴 고발(/doumi/<유형>?case=번호)이면 그 내용으로 채움.
- 기관 정보는 공식 사이트·대표 번호만. 번호가 확실하지 않은 곳은 번호를 적지 않는다.
"""
from flask import abort, g, redirect, render_template, request, url_for

# 기관: 이름, 한 줄 설명, 대표 번호(없으면 ''), 공식 주소
PLACES = {
    'ccn': ('1372 소비자상담센터', '모든 소비자 문제를 먼저 상담해요. 해결이 안 되면 한국소비자원 피해구제로 넘겨 줘요.', '1372', 'https://www.ccn.go.kr'),
    'kca': ('한국소비자원 피해구제', '1372 상담을 거친 뒤 신청해요. 사실을 조사하고 업체에 합의를 권고해요.', '', 'https://www.kca.go.kr'),
    'ecmc': ('전자거래분쟁조정위원회', '온라인으로 사고판 거래의 분쟁을 조정해요. 신청 비용은 없어요.', '', 'https://www.ecmc.or.kr'),
    'ftc': ('공정거래위원회 신고', '청약철회 방해, 거짓·과장 광고처럼 법을 어긴 업체를 신고해요.', '', 'https://www.ftc.go.kr'),
    'kcdrc': ('통신분쟁조정위원회', '휴대폰·인터넷·IPTV 요금과 계약 분쟁을 조정해요.', '', 'https://www.kcdrc.kr'),
    'fss': ('금융감독원 금융민원', '카드·보험·대출·은행 문제를 민원으로 접수해요.', '1332', 'https://www.fss.or.kr'),
    'mfds': ('식품의약품안전처 불량식품 신고', '이물질, 변질, 위생 문제를 신고해요.', '1399', 'https://www.mfds.go.kr'),
    'police': ('경찰청 사이버범죄 신고', '돈을 보냈는데 물건이 안 오는 사기, 중고거래 사기를 신고해요.', '112', 'https://ecrm.police.go.kr'),
    'kisa': ('개인정보침해 신고센터', '개인정보 유출, 동의 없는 수집·이용을 신고해요.', '118', 'https://privacy.kisa.or.kr'),
    'car': ('자동차리콜센터', '자동차 결함을 신고하고 리콜 여부를 확인해요.', '', 'https://www.car.go.kr'),
    'medi': ('한국의료분쟁조정중재원', '진료 결과나 의료 사고 분쟁을 조정해요.', '', 'https://www.k-medi.or.kr'),
    'epeople': ('국민신문고', '학원은 관할 교육청처럼, 담당 행정기관에 민원을 넣어요.', '110', 'https://www.epeople.go.kr'),
}

# 피해 유형: 키, 토스페이스 이모지, 이름, 예시, 신고할 곳(순서대로), 준비할 것, 소보루고발 제보 유형
TYPES = [
    ('shop', '🛒', '온라인 쇼핑·환불', '환불 거부, 반품 안 받아 줌, 불량 상품', ['ccn', 'kca', 'ecmc', 'ftc'],
     ['주문 내역과 결제 내역', '판매자와 주고받은 대화 캡처', '받은 상품 사진', '상품 설명 화면 캡처'], '배송·교환·환불'),
    ('delivery', '📦', '택배 분실·파손', '물건이 안 왔거나 깨져서 왔어요', ['ccn', 'kca'],
     ['운송장 번호', '물품 가격을 알 수 있는 영수증', '파손된 물건과 상자 사진', '택배사에 연락한 기록'], '배송·교환·환불'),
    ('contract', '🏋️', '헬스장·학원·구독 해지', '해지를 안 해 주거나 위약금이 너무 커요', ['ccn', 'kca', 'epeople'],
     ['계약서나 가입 화면 캡처', '결제 내역', '해지를 요청한 날짜와 기록', '업체가 말한 위약금 금액'], '계약·해지'),
    ('telecom', '📱', '휴대폰·인터넷', '약속과 다른 요금, 해지 방해', ['ccn', 'kcdrc'],
     ['가입 계약서', '요금 청구서', '상담 날짜와 상담원 이름, 녹취가 있으면 녹취'], '요금·결제'),
    ('finance', '💳', '카드·보험·금융', '보험금 거절, 모르는 결제, 불완전 판매', ['fss', 'ccn'],
     ['계약서나 약관', '거래·결제 내역', '회사와 상담한 기록'], '요금·결제'),
    ('food', '🍱', '음식 이물질·위생', '음식에서 이물질이 나왔어요', ['mfds', 'ccn'],
     ['이물질이 보이는 사진', '제품 포장 (유통기한·제조번호가 보이게)', '영수증이나 주문 내역', '남은 제품은 버리지 말고 보관'], '안전·위해'),
    ('scam', '🚨', '사기·중고거래', '돈을 보냈는데 연락이 끊겼어요', ['police'],
     ['입금한 내역', '상대방 연락처·계좌번호', '대화와 게시글 캡처'], '기타'),
    ('privacy', '🔒', '개인정보 유출', '유출 문자를 받았거나 동의 없이 쓰였어요', ['kisa'],
     ['유출 알림 문자·메일', '피해가 생겼다면 그 내역'], '개인정보'),
    ('ad', '📣', '거짓·과장 광고', '광고와 실제가 너무 달라요', ['ftc', 'ccn'],
     ['광고 화면 캡처 (날짜가 보이게)', '받은 상품이나 서비스 사진'], '허위·과장 광고'),
    ('travel', '✈️', '항공·여행·숙소', '취소 수수료, 결항 환불', ['ccn', 'kca'],
     ['예약 확인서', '취소·환불 규정 화면', '결제 내역'], '계약·해지'),
    ('car', '🚗', '자동차 결함', '같은 고장이 계속 나요', ['car', 'ccn'],
     ['정비·수리 기록', '결함 사진이나 영상', '자동차 등록증'], '품질·하자·AS'),
    ('medical', '🏥', '병원·의료', '진료비, 시술 결과 분쟁', ['medi', 'ccn'],
     ['진료 기록 사본', '진료비 영수증'], '기타'),
]
BY_KEY = {t[0]: t for t in TYPES}
# 고발 유형 → 해결 도우미 유형 (고발 글에서 '기관에도 신고하기'를 누르면)
FROM_CATEGORY = {'배송·교환·환불': 'shop', '계약·해지': 'contract', '요금·결제': 'shop', '품질·하자·AS': 'shop', '허위·과장 광고': 'ad',
                 '개인정보': 'privacy', '안전·위해': 'food', '고객 응대': 'shop'}
WANTS = ['환불', '교환', '수리', '해지', '배상', '사과']
# 유형별로 같이 보면 좋은 계산기 (soboru_tools.CALCS의 slug)
CALC_FOR = {'shop': ['cooling'], 'contract': ['fitness', 'academy', 'subscription'], 'finance': ['card'], 'travel': ['cooling']}
# 내 고발 '해결까지 할 일' (운영자 2026-11-13). 키, 이름, 한 줄 설명
STEPS = [('ask', '업체에 정식으로 요구하기', '날짜를 정해 글로 요구하고, 답을 기록해요'),
         ('letter', '내용증명 보내기', '답이 없으면 기한을 정해 내용증명을 보내요'),
         ('c1372', '1372 상담 받기', '국번 없이 1372, 상담 기록이 다음 단계의 근거가 돼요'),
         ('kca', '피해구제 신청하기', '한국소비자원이 조사하고 합의를 권고해요'),
         ('adr', '분쟁조정 신청하기', '합의가 안 되면 소비자분쟁조정위원회로 가요')]


def install(S):
    app = S.app
    with S.conn() as db:
        db.execute('CREATE TABLE IF NOT EXISTS case_steps(case_id INTEGER NOT NULL,step TEXT NOT NULL,done_at TEXT NOT NULL,PRIMARY KEY(case_id,step))')
    try:
        from soboru_tools import CALCS
    except Exception:
        CALCS = []
    calc_by = {c['slug']: c for c in CALCS}
    app.jinja_env.globals['consumer_calcs'] = lambda: [c for c in CALCS if c.get('group') == '소비자']

    def own_case(cid):
        """내가 쓴 고발이면 그 고발 (신고서 채우기용). 아니면 None"""
        if not cid.isdigit() or not g.get('user'): return None
        with S.conn() as db:
            c = db.execute('SELECT id,user_id,company,category,subject,description,request_text,occurred_on FROM cases WHERE id=?', (int(cid),)).fetchone()
        return c if c and c['user_id'] and c['user_id'] == g.user['id'] else None

    def singo_for(category):
        return url_for('singo_type', key=FROM_CATEGORY.get(category or '', 'shop'))
    app.jinja_env.globals['singo_for'] = singo_for

    @app.route('/doumi')
    def singo_home():
        c = own_case(request.args.get('case', ''))
        if c:
            return redirect(url_for('singo_type', key=FROM_CATEGORY.get(c['category'], 'shop'), case=c['id']))
        return render_template('singo.html', types=TYPES, t=None)

    @app.route('/doumi/<key>')
    def singo_type(key):
        t = BY_KEY.get(key)
        if not t: abort(404)
        c = own_case(request.args.get('case', ''))
        draft = dict(company=c['company'], when=c['occurred_on'] or '', what=c['description'], want=c['request_text']) if c else None
        calcs = [calc_by[x] for x in CALC_FOR.get(key, []) if x in calc_by]
        return render_template('singo.html', types=TYPES, t=t, places=[(k,) + PLACES[k] for k in t[4]], wants=WANTS, draft=draft, case=c, calcs=calcs)

    @app.route('/doumi/letter')
    def singo_letter():
        """내용증명 쓰기: 칸을 채우면 내용증명 문장이 화면에서 바로 만들어짐 (서버로 보내지 않음). 내 고발이면 그 내용으로"""
        c = own_case(request.args.get('case', ''))
        draft = dict(company=c['company'], when=c['occurred_on'] or '', what=c['description'], want=c['request_text']) if c else None
        return render_template('singo_letter.html', wants=WANTS, draft=draft, case=c, me=g.get('user'))

    # ── 내 고발 '해결까지 할 일' ──────────────────────────
    def case_steps(case):
        """내가 쓴 고발이면 [(키, 이름, 설명, 끝낸 날, 바로가기)] 아니면 None"""
        if not case or not g.get('user') or not case['user_id'] or case['user_id'] != g.user['id']: return None
        with S.conn() as db:
            done = {r['step']: r['done_at'] for r in db.execute('SELECT step,done_at FROM case_steps WHERE case_id=?', (case['id'],))}
        kind = FROM_CATEGORY.get(case['category'] or '', 'shop')
        go = {'letter': url_for('singo_letter', case=case['id']), 'c1372': 'tel:1372', 'kca': url_for('singo_type', key=kind, case=case['id']), 'adr': 'https://www.kca.go.kr'}
        return [(k, n, d, done.get(k, ''), go.get(k, '')) for k, n, d in STEPS]
    app.jinja_env.globals['case_steps'] = case_steps

    @app.route('/case/<int:case_id>/steps', methods=['POST'])
    def case_step_toggle(case_id):
        c = own_case(str(case_id))
        step = request.form.get('step', '')
        if not c or step not in dict((k, n) for k, n, d in STEPS): abort(404)
        with S.conn() as db:
            if db.execute('SELECT 1 FROM case_steps WHERE case_id=? AND step=?', (case_id, step)).fetchone():
                db.execute('DELETE FROM case_steps WHERE case_id=? AND step=?', (case_id, step))
            else:
                db.execute('INSERT INTO case_steps(case_id,step,done_at) VALUES(?,?,?)', (case_id, step, S.now()))
        return redirect(url_for('public_case', case_id=case_id) + '#steps')
