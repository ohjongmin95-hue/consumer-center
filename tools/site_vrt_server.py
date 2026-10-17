# 소비자제보센터 화면 시험용 서버: 임시 DB에 예시 제보를 넣고 띄움 (실제 DB·운영 서버와 무관)
#   python tools/site_vrt_server.py [앱 폴더] [포트]   기본: 이 저장소, 8822
# 고치기 전 화면(기준 그림)은 git worktree로 받은 이전 코드 폴더를 앱 폴더로 넘겨서 띄워요.
# 관리자 비밀번호 adminshotpw1, 제보 조회 010-2222-3333 / 1234, 기업 회원 sobo_cs / bizshotpw1, 기자 vrt_staff / staffshotpw1
import os, sys, re, tempfile, importlib.util
from werkzeug.security import generate_password_hash
APP_DIR = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..'))
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8822
d = tempfile.mkdtemp()
os.environ.update(DATABASE_PATH=d + '/c.db', UPLOAD_DIR=d + '/up', SECRET_KEY='x' * 64, ADMIN_PASSWORD_HASH=generate_password_hash('adminshotpw1'),
                  ENABLE_INTAKE='1', ENABLE_BOARD='1', ENABLE_BIZ_MEMBERS='1', HTTPS_ONLY='0')
for k in ('SMTP_HOST', 'SOLAPI_API_KEY'): os.environ.pop(k, None)  # 알림은 보내지 않음
sys.path.insert(0, APP_DIR); os.chdir(APP_DIR)
spec = importlib.util.spec_from_file_location('site_under_test', os.path.join(APP_DIR, 'app.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
app = m.app
def csrf(c, p): return re.search(r'name="_csrf" value="([^"]+)"', c.get(p).get_data(as_text=True))[1]
def post(c, p, data, page=None): return c.post(p, data={'_csrf': csrf(c, page or p), **data})
a = app.test_client(); post(a, '/admin/login', {'password': 'adminshotpw1'})
post(a, '/admin/companies', {'action': 'create', 'name': '오소보쇼핑', 'brand': '소보몰', 'biz_name': '주식회사 오소보'})
u = app.test_client()
base = {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '오소보쇼핑', 'description': '반품을 보냈는데 2주째 환불이 안 돼요. 고객센터는 연결이 안 되고 게시판 답변도 없어요.',
        'reporter_name': '김소비', 'phone': '010-2222-3333', 'request_text': '카드 결제 취소를 원해요.', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234',
        'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'public', 'occurred_on': '2026-09-28'}
for s, cat in [('반품 후 2주째 환불이 안 돼요', '배송·교환·환불'), ('불량 제품 교환을 거부해요', '품질·하자·AS'), ('해지 후에도 요금이 나가요', '요금·결제')]:
    post(u, '/report', dict(base, subject=s, category=cat, phone='010-9999-0000'))
with m.conn() as db: ids = [r[0] for r in db.execute('SELECT id FROM cases ORDER BY id')]
for i in ids: post(a, '/admin/reports/%d' % i, {'form': 'publish_review', 'decision': 'approve'})
r = a.post('/admin/invite/%d' % ids[0], data={'_csrf': csrf(a, '/admin/reports/%d' % ids[0])})
inv = re.search(r'<strong>http://localhost(/company/[^<]+)</strong>', r.get_data(as_text=True))[1]
co = app.test_client(); post(co, inv, {'response': '불편을 드려 죄송합니다. 반품 확인이 늦어졌고, 오늘 카드 취소를 요청했어요.'})
with m.conn() as db: mid = db.execute("SELECT id FROM messages WHERE author='기업 답변'").fetchone()[0]
post(a, '/admin/reports/%d' % ids[0], {'form': 'answer_public', 'message_id': mid, 'public': '1'})
# 기업 회원: 가입 → 운영자 직접 확인 승인 → 제보 전달 → 답변
b = app.test_client()
post(b, '/biz/signup', {'company_name': '소보루전자', 'biz_no': '123-45-67891', 'contact_name': '박담당', 'contact_phone': '02-555-0101', 'contact_email': 'cs@soboru-elec.co.kr',
                        'login_id': 'sobo_cs', 'password': 'bizshotpw1', 'password2': 'bizshotpw1', 'agree': 'on'})
with m.conn() as db: cid = db.execute("SELECT id FROM companies WHERE name='소보루전자'").fetchone()[0]
post(a, '/admin/companies', {'id': cid, 'action': 'approve', 'manual': '1'})
post(u, '/report', dict(base, company='소보루전자', subject='무상 수리 기간인데 비용을 요구해요', category='품질·하자·AS'))
with m.conn() as db: eid = db.execute("SELECT id FROM cases WHERE company='소보루전자'").fetchone()[0]
post(a, '/admin/reports/%d' % eid, {'form': 'publish_review', 'decision': 'approve'})
post(a, '/admin/reports/%d' % eid, {'form': 'forward'})
post(b, '/biz/case/%d' % eid, {'response': '확인해 보니 무상 수리 대상이 맞아요. 접수하신 서비스센터에 비용 없이 처리하도록 안내했어요.'})
post(u, '/report', dict(base, subject='승인 대기 제보', company='소보몰', phone='010-9999-0000'))
# 기자실: 기자 계정 → 담당 배정 → 제보자에게 메시지 (기자 이지우 / staffshotpw1)
post(a, '/admin/staff', {'action': 'add', 'name': '이지우', 'login_id': 'vrt_staff', 'password': 'staffshotpw1'})
st = app.test_client(); post(st, '/reporter/login', {'login_id': 'vrt_staff', 'password': 'staffshotpw1'})
with m.conn() as db: est = db.execute('SELECT status FROM cases WHERE id=?', (eid,)).fetchone()[0]
post(st, '/reporter/case/%d' % eid, {'form': 'settings', 'status': est, 'assignee': '이지우', 'published': '1'})
post(st, '/reporter/case/%d' % eid, {'form': 'message', 'message': '기업 답변을 확인했어요. 처리 결과를 알려 주세요.'})
# 3차 화면: 보완 요청, 정정 요청, 기업 이의 신청 (메일은 설정이 없어 보내지 않음)
if hasattr(m, 'ops'):  # 3차 이전 코드(기준 그림)에는 없는 기능
    post(a, '/admin/reports/%d' % ids[1], {'form': 'supplement', 'body': '주문 내역 화면을 올려 주세요.'})
    lk = app.test_client(); post(lk, '/lookup', {'mode': 'phone', 'phone': '010-2222-3333', 'password': '1234'})
    post(lk, '/case/request', {'kind': 'correct', 'body': '발생일을 9월 27일로 고쳐 주세요.'}, page='/case')
    post(b, '/biz/case/%d/objection' % eid, {'body': '무상 수리 대상이라 이미 안내했습니다. 접수 기록이 있습니다.'}, page='/biz/case/%d' % eid)
# 소보루 화면: VRT_BRAND=소보루 로 띄우면 생활정보 글·게시판 글을 넣고 브랜드를 소보루로 바꿈
if os.environ.get('VRT_BRAND') and hasattr(m, 'soboru'):
    SUMS = {'📦': '운송장에 적은 금액이 기준이에요. 안 적었다면 최대 50만 원까지예요.', '🏋️': '남은 기간 이용료에서 10% 위약금만 빼고 돌려받을 수 있어요.', '✈️': '항공사 사정으로 결항되면 수수료 없이 전액 환불이 원칙이에요.', '🧾': '안전결제 링크를 따로 보내 주면 일단 의심하세요.', '🛒': '물건을 받은 날부터 7일 안이면 단순 변심도 반품할 수 있어요.', '📱': '남은 약정 개월 수와 할인받은 금액을 먼저 확인하세요.', '🏨': '숙박일 기준으로 며칠 전에 취소했는지에 따라 수수료가 달라져요.', '🍱': '먹던 음식과 이물질은 버리지 말고 사진부터 찍어 두세요.', '💳': '문자 속 번호 말고, 카드 뒷면 번호로 직접 전화하세요.', '🛴': '해당 모델은 무상 수리나 환불을 받을 수 있어요.'}
    for t, e, tone, cat, feat in [('택배가 사라졌다면? 보상은 얼마까지 받을 수 있을까', '📦', 't1', '쇼핑', '1'), ('헬스장 중도 해지, 위약금은 10%만 내면 돼요', '🏋️', 't3', '생활', ''),
                                  ('결항 환불, 이렇게 요청하면 빨라요', '✈️', 't2', '여행', ''), ('중고거래 택배 사기, 이렇게 피했어요', '🧾', 't4', '쇼핑', ''),
                                  ('온라인 쇼핑 청약철회, 7일 안에 이것만 기억해요', '🛒', 't6', '쇼핑', ''), ('휴대폰 약정 중도 해지, 위약금 미리 계산하는 법', '📱', 't5', '통신', ''),
                                  ('숙소 예약 취소 수수료, 어디까지 내야 할까', '🏨', 't2', '여행', ''), ('배달 음식에서 이물질이 나왔다면 사진부터', '🍱', 't3', '음식', ''),
                                  ('모르는 결제 문자, 카드사에 먼저 전화해야 하는 이유', '💳', 't4', '금융', ''), ('어린이 킥보드 일부 모델, 브레이크 결함으로 회수', '🛴', 't1', '리콜', '')]:
        post(a, '/admin/life', {'title': t, 'summary': SUMS.get(e, '꼭 알아야 할 것만 정리했어요.'), 'body': '먼저 판매자에게 알리세요.\n\n## 얼마까지 받을 수 있나요\n- 운송장에 적은 물품 가격 기준\n- 적지 않았다면 최대 50만 원',
                                'category': cat, 'emoji': e, 'tone': tone, 'source_name': '공정거래위원회 소비자24', 'source_url': 'https://www.consumer.go.kr', 'featured': feat, 'publish': '1'})
    # 커뮤니티 글: 리뷰·꿀팁·질문·이야기 (종류마다 화면이 달라 골고루)
    import datetime as _dt
    def ago(h): return (_dt.datetime.now() - _dt.timedelta(hours=h)).isoformat(timespec='seconds')
    POSTS = [  # kind, category, nickname, title, body, target, rating, pros, cons, recommend, summary, likes, hours ago, solved
        ('review', '경험 공유', '알뜰한다람쥐', '환불은 빨랐는데 상담 연결이 너무 오래 걸려요', '반품 접수하고 3일 만에 카드 취소가 됐어요. 다만 고객센터 전화는 30분 넘게 기다렸어요.', '오소보쇼핑', 4, '반품 접수 3일 만에 카드 취소까지 끝났어요', '고객센터 전화 연결이 30분 넘게 걸렸어요', 1, '', 12, 5, 0),
        ('tip', '꿀팁', '생활의고수', '택배 분실됐을 때 보상 제대로 받는 순서', '1. 택배사 고객센터에 분실 접수부터 해요.\n\n2. 운송장 번호와 물품 가격을 증명할 영수증을 준비해요.\n\n3. 접수 후 14일 안에 연락이 없으면 소비자24에 상담을 신청해요.', '', 0, '', '', None, '운송장에 적은 금액 기준, 안 적었다면 최대 50만 원까지예요', 9, 20, 0),
        ('question', '질문해요', '헬린이', '헬스장 6개월권 중도 해지하면 위약금이 얼마나 되나요?', '두 달 다니고 이사를 가게 됐어요. 헬스장에서는 할인가로 끊었으니 정가로 계산해서 빼겠다고 하는데 맞는 건가요?', '', 0, '', '', None, '', 6, 30, 1),
        ('review', '경험 공유', '꼼꼼소비', 'AS 기사님 친절, 수리비도 처음 안내 그대로', '무상 수리 기간이라 비용 없이 고쳤어요. 예약부터 방문까지 이틀 걸렸어요.', '소보루전자', 5, '예약 이틀 만에 방문, 비용 없이 수리', '', 1, '', 7, 40, 0),
        ('post', '칭찬해요', '따뜻한소비자', '동네 마트 사장님이 유통기한 지난 우유를 먼저 바꿔 주셨어요', '계산할 때 몰랐는데 집에 와서 보니 하루 지난 우유였어요. 다시 가니까 사과하시면서 새 걸로 바꿔 주시고 요구르트까지 챙겨 주셨어요.', '', 0, '', '', None, '', 4, 50, 0),
        ('question', '질문해요', '여행가자', '항공권 결항됐는데 수수료를 떼고 환불해 준대요', '항공사 사정으로 결항됐는데 여행사에서 취소 수수료 3만 원을 빼고 준대요. 이게 맞나요?', '', 0, '', '', None, '', 3, 8, 0),
        ('review', '경험 공유', '깐깐한고양이', '배송은 빠른데 포장이 너무 부실했어요', '유리병이 깨진 채로 왔어요. 교환은 해 줬지만 다시 받는 데 일주일 걸렸어요.', '오소보쇼핑', 2, '교환 요청은 바로 받아 줬어요', '유리병이 깨져서 왔고, 다시 받는 데 일주일', 0, '', 2, 70, 0),
        ('tip', '꿀팁', '절약왕', '통신사 약정 끝나기 전에 꼭 확인할 3가지', '약정 만료일, 남은 할부금, 선택약정 할인 재가입 여부를 먼저 확인하세요.\n\n특히 선택약정은 자동으로 이어지지 않아서 직접 다시 신청해야 해요.', '', 0, '', '', None, '선택약정 할인은 자동으로 안 이어져요. 직접 다시 신청하세요', 5, 90, 0),
    ]
    with m.conn() as db:
        oso = db.execute("SELECT id FROM companies WHERE name='오소보쇼핑'").fetchone()[0]
        for kind, cat, nick, title, body, target, rating, pros, cons, rec, summ, likes, h, solved in POSTS:
            pid = db.execute('INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created,kind,target,company_id,rating,pros,cons,recommend,summary,likes,solved) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                             (cat, nick, generate_password_hash('1234'), title, body, 'seed', ago(h), kind, target, oso if target == '오소보쇼핑' else (cid if target == '소보루전자' else None), rating, pros, cons, rec, summ, likes, solved)).lastrowid
            for i, cb in enumerate({'question': ['계약할 때 받은 할인 금액만큼은 빼도 돼요. 정가 전체를 다 빼는 건 과해요.', '저도 비슷했는데 소비자24 기준표 보여 주니 다시 계산해 줬어요.'], 'review': ['저도 같은 일 있었어요. 도움 됐어요!']}.get(kind, [])[: (2 if solved or kind == 'review' else 0)]):
                db.execute('INSERT INTO comments(post_id,nickname,pw_hash,body,ip_hash,created) VALUES(?,?,?,?,?,?)', (pid, ['이웃소비자', '경험자'][i], generate_password_hash('1234'), cb, 'seed', ago(max(0.2, h - 1 - i))))
            db.execute('UPDATE posts SET comments=(SELECT COUNT(*) FROM comments WHERE post_id=?) WHERE id=?', (pid, pid))
        db.execute("INSERT OR REPLACE INTO site_content(key,value,updated) VALUES('site.brand',?,'2026-10-16')", (os.environ['VRT_BRAND'],))
        if os.environ.get('VRT_NN'):
            # 뉴닉식 홈 미리보기용: 리뷰 대상 여러 개, 기업 답변 순위가 나올 만큼의 전달·답변 기록
            for nick, title, target, rating, rec, likes, h in [('살림9단', '소보루마트 신선식품, 이 가격에 이 품질이면 추천', '소보루마트', 5, 1, 31, 30), ('매일커피', '오소보카페 구독권, 한 달 써 보니 돈값 해요', '오소보카페', 5, 1, 18, 50),
                                                              ('통신박사', '보루텔레콤 알뜰요금제 6개월 사용기', '보루텔레콤', 4, 1, 22, 26), ('출장러', '루트호텔 체크인 대기만 빼면 만족', '루트호텔', 4, 1, 9, 80),
                                                              ('수리왕', '소보루전자 출장 수리, 두 번째도 친절했어요', '소보루전자', 5, 1, 15, 60)]:
                db.execute('INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created,kind,target,rating,recommend,likes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                           ('경험 공유', nick, generate_password_hash('1234'), title, '직접 써 보고 남기는 후기예요.', 'seed', ago(h), 'review', target, rating, rec, likes))
            for name, ans, wait_h in [('소보루마트', 5, 20), ('보루텔레콤', 4, 50), ('오소보쇼핑', 3, 90), ('루트호텔', 1, 0), ('가나다몰', 0, 0)]:
                co = db.execute("INSERT INTO companies(name,biz_no,status,contact_name,contact_phone,contact_email,created) VALUES(?,?,?,?,?,?,?)", (name, '000', 'active', '-', '-', '-', ago(500))).lastrowid
                for k in range(5):
                    c = -(co * 10 + k)  # 음수 번호: 실시간 제보 목록(최신순) 맨 뒤로
                    db.execute("INSERT INTO cases(id,receipt,lookup_hash,category,company,subject,description,request_text,created,company_id,forwarded_at,review,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                   (c, 'nn%d-%d' % (co, k), 'x', '배송·교환·환불', name, '순위용 제보', '본문', '환불', ago(300), co, ago(290), 'ok', '기업 답변 대기'))
                    if k < ans: db.execute("INSERT INTO messages(case_id,author,body,created) VALUES(?,?,?,?)", (c, '기업 답변', '확인했습니다.', ago(290 - wait_h / 10 - k * 3)))
    if hasattr(m, 'lawask'):
        # 법률 질문창: 가짜 AI 답(실제 OpenAI는 부르지 않음)과 관리자가 올린 법령 하나
        import json as _json
        law, = m.lawask.parse_text('법제처 1 국가법령정보센터\n할부거래에 관한 법률\n[시행 2026. 1. 2.] [법률 제12345호, 2025. 7. 1., 일부개정]\n'
                                   '제1조(목적) 이 법은 할부계약에 의한 거래를 공정하게 함을 목적으로 한다.\n'
                                   '제2조(할부계약의 청약철회) ① 소비자는 할부계약서를 받은 날부터 7일 이내에 할부계약에 관한 청약을 철회할 수 있다.\n')
        ext = m.app.extensions['lawask']['extra_path']; ext.write_text(_json.dumps({law['key']: dict(law, added='2026-10-16T10:00:00', file='할부거래법.pdf')}, ensure_ascii=False), encoding='utf-8')
        def fake_ai(url, headers, body, timeout):
            if '법률 안내 도우미' not in body['messages'][0]['content']: return 503, {}
            refs = re.findall(r'^\[corpus:([^\]]+)\]', body['messages'][1]['content'], re.M)
            out = {'headline': '단순 변심이라면 받은 날부터 7일이 지나면 환불이 어려울 수 있어요',
                   'paragraphs': ['전자상거래법 제17조에 따르면 온라인으로 산 물건은 받은 날부터 7일 안에 청약철회(주문 취소·반품)를 할 수 있어요. 7일이 지났다면 단순 변심으로는 반품을 요구하기 어려울 수 있어요.',
                                  '다만 받은 옷이 광고나 상품 설명과 다르다면 이야기가 달라요. 같은 조 제3항에 따라 받은 날부터 3개월 안, 그 사실을 안 날부터 30일 안에 청약철회를 할 수 있어요.',
                                  '판매자에게는 문자나 게시판처럼 기록이 남는 방법으로 요청하고, 상품 사진과 주문 내역을 보관해 두세요.'],
                   'refs': [r for r in refs if r.startswith('ecom:제17') or r.startswith('ecom:제18')][:2] or refs[:2], 'covered': True, 'suggest_report': True}
            return 200, {'choices': [{'message': {'content': _json.dumps(out, ensure_ascii=False)}}]}
        os.environ['OPENAI_API_KEY'] = 'vrt-fake'; m.companydesk.post_json = fake_ai
# 네이버 API HUB 화면 시험: VRT_NAVER=1이면 가짜 키와 가짜 응답으로 통합 검색·검색 추이·쇼핑 관심도를 띄움 (실제 네이버는 안 부름)
if os.environ.get('VRT_NAVER') and hasattr(m, 'naverhub'):
    import random as _r
    os.environ.update(NAVER_HUB_CLIENT_ID='vrt', NAVER_HUB_CLIENT_SECRET='vrt')
    def _series(seed, n=13):
        g = _r.Random(seed); v = 40 + g.random() * 30
        return [{'period': '2026-%02d-%02d' % (7 + i // 4, 1 + (i % 4) * 7), 'ratio': round(min(100, max(5, v := v + g.uniform(-9, 11))), 1)} for i in range(n)]
    _news = [('헬스장 폐업했는데 남은 회원권 환불은? 할부 항변권으로 돌려받는 법', '한국소비자원', 'kca.go.kr'), ('택배 분실 보상, 운송장 가격 기준으로 최대 50만원까지', '소비자경제', 'dailycnc.com'),
             ('구독 해지했는데 요금이 또 나갔다면… 공정위 "다크패턴 단속"', '연합뉴스', 'yna.co.kr'), ('항공권 취소 수수료 과다 청구, 소비자원 "약관 확인하세요"', '뉴시스', 'newsis.com'),
             ('중고거래 사기 피해 1년 새 30% 늘어… 안전결제 꼭 쓰세요', '머니투데이', 'mt.co.kr')]
    def _fake(method, url, headers, body, timeout):
        path = url.split('ntruss.com', 1)[1].split('?')[0]
        if path.startswith('/search/v1/'):
            kind = path.rsplit('/', 1)[1]
            items = [{'title': t, 'description': '소비자가 알아 두면 좋은 내용을 정리했어요. 계약서와 영수증을 꼭 챙기고, 업체와 나눈 대화는 캡처해 두세요.',
                      'originallink': 'https://www.%s/news/%d' % (h, i), 'link': 'https://www.%s/news/%d' % (h, i), 'pubDate': 'Thu, %02d Oct 2026 09:00:00 +0900' % (15 - i),
                      'bloggername': '알뜰소비 일기', 'postdate': '202610%02d' % (15 - i), 'cafename': '소비자 권리 찾기'} for i, (t, src, h) in enumerate(_news)]
            return 200, {'total': 1284, 'items': items}
        if path == '/search-trend/v1/search':
            return 200, {'results': [{'title': g['groupName'], 'keywords': g['keywords'], 'data': _series(g['groupName'])} for g in body['keywordGroups']]}
        if path == '/shopping/v1/categories':
            return 200, {'results': [{'title': c['name'], 'category': c['param'], 'data': _series(c['param'][0])} for c in body['category']]}
        if path.startswith('/shopping/v1/category/') and path.rsplit('/', 1)[1] in ('gender', 'age', 'device'):
            grp = {'gender': [('f', 62), ('m', 38)], 'age': [('10', 8), ('20', 31), ('30', 27), ('40', 19), ('50', 10), ('60', 5)], 'device': [('mo', 81), ('pc', 19)]}[path.rsplit('/', 1)[1]]
            return 200, {'results': [{'title': 'x', 'data': [{'period': '2026-09-01', 'group': k, 'ratio': v} for k, v in grp]}]}
        if path == '/shopping/v1/category/keywords':
            return 200, {'results': [{'title': k['name'], 'keyword': k['param'], 'data': _series(k['name'])} for k in body['keyword']]}
        return 404, {}
    m.naverhub.http = _fake
print('ready', ids, eid, flush=True)
app.run(host='127.0.0.1', port=PORT)
