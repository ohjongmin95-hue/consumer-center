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
        if hasattr(m, 'clean_photo'):  # 예전 코드(기준 그림)로 띄우면 건너뜀
            # 이번 주 리뷰 주제(배달음식, 혜택 켬)와 그 주제 리뷰: 사진 리뷰 하나, 소보루 에디터 리뷰 하나 (미리보기 전용 예시)
            cpid = db.execute('INSERT INTO review_campaigns(slug,title,topic,intro,fields_hint,starts,ends,active,reward_on,reward_rules,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                              ('delivery-1017', '내가 시켜 먹은 배달음식, 솔직히 어땠나요?', '배달음식', '어제 시킨 치킨, 지난주 떡볶이. 맛·양·배달 시간까지 솔직하게 알려 주세요. 다른 분들이 메뉴 고를 때 큰 도움이 돼요.',
                               '주문한 메뉴와 가격\n맛·양·포장 상태\n주문부터 도착까지 걸린 시간', _dt.date.today().isoformat(), (_dt.date.today() + _dt.timedelta(days=6)).isoformat(), 1, 1,
                               '대상: 기간 안에 사진과 함께 리뷰를 남긴 분 중 추첨 20명\n혜택: 편의점 모바일 상품권 5천 원\n지급 방법: 끝나고 7일 안에 가입한 이메일로 보내 드려요\n유의사항: 별점이나 좋은 평가와 상관없이 추첨해요. 광고·도배 글은 빠져요.', ago(30))).lastrowid
            from PIL import Image as _Im, ImageDraw as _Dr
            _im = _Im.new('RGB', (900, 680), (246, 226, 196)); _d = _Dr.Draw(_im)
            _d.ellipse((120, 90, 780, 610), fill=(255, 255, 255)); _d.ellipse((170, 140, 730, 560), fill=(250, 244, 236))
            for x, y, r in [(330, 260, 95), (480, 230, 85), (560, 360, 100), (380, 410, 90), (470, 330, 70)]: _d.ellipse((x - r, y - r, x + r, y + r), fill=(206, 128, 46), outline=(168, 92, 26), width=6)
            _buf = __import__('io').BytesIO(); _im.save(_buf, 'JPEG', quality=90)
            photo = m.save_board_photo(*m.clean_photo(_buf.getvalue()))
            for nick, title, target, menu, rating, rec, pros, cons, h, ph, editor, reward in [
                    ('치킨러버', '바삭함은 최고, 배달이 50분 걸린 건 아쉬워요', '소보루치킨 역삼점', '후라이드 반 양념 반', 4, 1, '튀김옷이 집에 올 때까지 바삭했어요', '주문하고 50분 만에 왔어요', 3, photo, 0, 1),
                    ('떡볶이요정', '국물 떡볶이 양이 넉넉해서 둘이 먹기 딱', '오소보분식', '국물 떡볶이, 순대', 5, 1, '2인분인데 셋이 먹어도 될 만큼 넉넉해요', '', 9, '', 0, 1),
                    ('소보루 에디터', '에디터가 직접 시켜 본 보루피자, 도우가 쫄깃해요', '보루피자', '고구마 피자 라지', 4, 1, '도우가 쫄깃하고 토핑이 끝까지 있어요', '포장 상자가 조금 눌려서 왔어요', 20, '', 1, 0)]:
                pid = db.execute('INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created,kind,target,rating,pros,cons,recommend,likes,menu,photo,campaign_id,editor,reward,review_cat) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                 ('경험 공유', nick, generate_password_hash('1234'), title, '', 'seed', ago(h), 'review', target, rating, pros, cons, rec, 3, menu, ph, cpid, editor, reward, '배달음식')).lastrowid
            # 광고 효과 화면용 기록 (경로별 방문·가입·리뷰·재방문)
            for i in range(60):
                src = ['instagram', 'instagram', 'naver', '(direct)'][i % 4]; med = {'instagram': 'paid', 'naver': 'cpc'}.get(src, ''); cmp = 'delivery-1017' if src != '(direct)' else ''
                day = (_dt.date.today() - _dt.timedelta(days=i % 9)).isoformat(); vh = 'seed%03d' % i
                db.execute('INSERT INTO ad_events(day,utm_source,utm_medium,utm_campaign,event,visitor_hash) VALUES(?,?,?,?,?,?)', (day, src, med, cmp, 'visit', vh))
                for ev, every in (('signup', 5), ('review', 7), ('return', 3)):
                    if i % every == 0: db.execute('INSERT OR IGNORE INTO ad_events(day,utm_source,utm_medium,utm_campaign,event,visitor_hash) VALUES(?,?,?,?,?,?)', (_dt.date.today().isoformat(), src, med, cmp, ev, vh))
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
    if hasattr(m, 'lawrag'):
        # AI 소비자 상담 새 버전: 가짜 임베딩·가짜 답, 분쟁해결기준 별표 몇 줄, 현행 확인 기록, 품질 시험·상담 기록 (스위치는 꺼진 채, 관리자가 켬)
        import lawsync as _ls, hashlib as _h, datetime as _d
        rag = m.app.extensions['lawrag']; st = rag['store']
        W = lambda a, b, c='': f'{a:<34}{b:<44}{c}'
        pages = ['\n'.join(['[별표 Ⅱ] 품목별 해결기준(제3조 관련)', '[시행 2025. 12. 18.]', '12. 체육시설업(헬스장, 필라테스, 요가)', W('분쟁유형', '해결기준', '비고'),
                            W('1) 사업자의 귀책사유로 계약을', '- 계약해제 및 이용료 환급'), W('해제하는 경우', '- 남은 기간 이용료 전액 환급'),
                            W('2) 소비자의 사정으로 중도 해지', '- 이용일수에 해당하는 금액과 총 이용금액의', '개시일 이후'), W('하는 경우', '10% 공제 후 환급')]),
                 '\n'.join(['31. 외식업', W('분쟁유형', '해결기준', '비고'), W('1) 음식물에 이물 혼입', '- 제품 교환 또는 구입가 환급'), W('2) 부패·변질된 음식물', '- 제품 교환 또는 구입가 환급, 치료비 배상')]),
                 '\n'.join(['40. 인터넷콘텐츠업(구독 서비스)', W('분쟁유형', '해결기준', '비고'), W('1) 계약 중도 해지', '- 해지일까지 이용일수 요금과 잔여기간 이용금액의', '1개월 이상 계약'), W('', '10% 공제 후 환급')])]
        _x = _ls.parse_appendix(pages); _x.update(doc='소비자분쟁해결기준 [별표 Ⅱ]', file='소비자분쟁해결기준_별표2.pdf', added='2026-10-16T10:00:00')
        _ls.save_appendix(st, [_x])
        _now = _d.datetime.now().isoformat(timespec='seconds')
        st.write(st.status, {k: {'name': n, 'short': s, 'current': c, 'checked': _now, 'target': tg} for k, n, s, c, tg in [
            ('basic', '소비자기본법', '소비자기본법', '2026-09-11', 'law'), ('ecom', '전자상거래 등에서의 소비자보호에 관한 법률', '전자상거래법', '2026-07-21', 'law'),
            ('terms', '약관의 규제에 관한 법률', '약관법', '2024-08-07', 'law'), ('food', '식품위생법', '식품위생법', '2026-10-08', 'law'),
            ('installment', '할부거래에 관한 법률', '할부거래법', '2026-03-01', 'law'), ('kca', '소비자분쟁해결기준', '소비자분쟁해결기준', '2025-12-18', 'admrul')]})
        def _vec(text):
            v = [0.0] * 512
            for w in re.findall(r'[가-힣]+', text):
                for i in range(len(w) - 1): v[int(_h.md5(w[i:i + 2].encode()).hexdigest(), 16) % 512] += 1
            return v
        _prev = m.companydesk.post_json
        def fake_rag(url, headers, body, timeout):
            if url.endswith('/embeddings'):
                return 200, {'data': [{'index': i, 'embedding': _vec(x)} for i, x in enumerate(body['input'])], 'usage': {'total_tokens': 12 * len(body['input'])}}
            if 'AI 소비자 상담 도우미' not in body['messages'][0]['content']: return _prev(url, headers, body, timeout)
            user = body['messages'][-1]['content']; ids = re.findall(r'^\[(c\d+)\] \(([^)]+\)?)\) (.+)$', user, re.M)
            appx = [i for i, k, l in ids if '체육시설' in l or '인터넷콘텐츠' in l] or [i for i, k, l in ids if '분쟁해결기준' in k]
            law = [i for i, k, l in ids if k == '법률 조문'] or [i for i, _, _ in ids]
            a, b = (appx or law)[0], law[0]
            bm = f' [{b}]' if b != a else ''
            if '헬스' in user:
                parts = [{'name': '핵심 결론', 'text': f'헬스장 이용권을 중간에 해지해도 남은 기간 이용료는 돌려받을 수 있는 경우가 많아요. 소비자분쟁해결기준은 소비자 사정으로 중도 해지하면 이용일수에 해당하는 금액과 총 이용금액의 10%를 빼고 환급하도록 권고해요 [{a}].'},
                         {'name': '환불·보상 가능성', 'text': f'- 쓴 기간 이용료와 총 이용금액의 10%를 뺀 나머지를 돌려받을 수 있어요 [{a}].\n- 할인가로 계약했다면 할인가를 기준으로 계산하는지 업체에 확인해 보세요.\n- 분쟁해결기준은 권고라서 업체가 꼭 따라야 하는 것은 아니에요.'},
                         {'name': '증거', 'text': '- 계약서나 이용권 영수증, 결제 내역\n- 해지를 요청한 문자·앱 메시지 화면\n- 업체가 안내한 환불 금액'},
                         {'name': '대응 절차', 'text': f'- 문자나 앱처럼 기록이 남는 방법으로 해지와 환불을 요청해요.\n- 업체가 응하지 않으면 소비자기본법에 따른 피해구제를 신청할 수 있어요{bm}.'},
                         {'name': '신고·상담기관', 'text': '- 1372 소비자상담센터에서 상담받을 수 있어요.\n- 한국소비자원에 피해구제를 신청할 수 있어요.'}]
            else:
                parts = [{'name': '핵심 결론', 'text': f'찾은 근거 원문으로 보면 업체에 환불이나 교환을 요청할 수 있는 경우가 많아요 [{a}].'},
                         {'name': '대응 절차', 'text': f'- 기록이 남는 방법으로 먼저 요청해요{bm}.\n- 답이 없으면 1372 소비자상담센터에 상담해요.'}]
            out = {'need_more': False, 'questions': [], 'parts': parts, 'refs': [a, b], 'covered': True}
            return 200, {'model': m.companydesk.ai_model(), 'usage': {'prompt_tokens': 3100, 'completion_tokens': 620}, 'choices': [{'message': {'content': _json.dumps(out, ensure_ascii=False)}}]}
        m.companydesk.post_json = fake_rag
        rag['build_embeddings']()
        _batch = _now
        for _q in m.lawrag.TEST_QUESTIONS: rag['consult'](_q, (), 'test', batch=_batch)
        for _q in m.lawrag.TEST_QUESTIONS[:12] + ['사이즈 추천 부탁해요 감사합니다']: rag['consult'](_q, (), 'ask')
        # 법제처 본문 검색 (가짜 응답): 모아 둔 법에 없는 반려견 분양 질문이면 동물보호법을 찾아 모아 둠
        os.environ['LAW_OC'] = 'vrt-oc'
        def _law_get(url, timeout=25):
            if 'lawSearch.do' in url and 'search=2' in url:
                return 200, ('<LawSearch><law><법령일련번호>5001</법령일련번호><법령명한글>동물보호법</법령명한글><법령ID>0101</법령ID><시행일자>20260201</시행일자><법령구분명>법률</법령구분명></law></LawSearch>')
            if 'MST=5001' in url:
                return 200, ('<법령><기본정보><법령명_한글>동물보호법</법령명_한글><시행일자>20260201</시행일자><공포번호>1</공포번호><법종구분>법률</법종구분></기본정보><조문>'
                             '<조문단위><조문번호>69</조문번호><조문여부>조문</조문여부><조문제목>영업의 허가</조문제목><조문내용>제69조(영업의 허가) 반려동물과 관련된 동물생산업, 동물수입업, 동물판매업을 하려는 자는 특별자치시장ㆍ특별자치도지사ㆍ시장ㆍ군수ㆍ구청장의 허가를 받아야 한다.</조문내용></조문단위>'
                             '<조문단위><조문번호>78</조문번호><조문여부>조문</조문여부><조문제목>영업자 등의 준수사항</조문제목><조문내용>제78조(영업자 등의 준수사항) 동물판매업자는 반려견을 분양할 때 질병 발생 시 보상 내용 등을 적은 계약서를 소비자에게 주어야 한다.</조문내용></조문단위></조문></법령>')
            return 200, '<LawSearch><totalCnt>0</totalCnt></LawSearch>'
        _ls.http_get = _law_get
        rag['consult']('분양받은 반려견이 일주일 만에 파보장염으로 죽었어요. 분양업자에게 뭘 요구할 수 있나요?', (), 'ask')
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
# AI 분석 기사 화면 시험: 가짜 AI가 받은 자료의 숫자로 기사를 씀 (실제 OpenAI는 안 부름). 뉴스 해설은 일부러 자료에 없는 숫자 하나를 넣어 '검토 필요'를 보여 줌
if hasattr(m, 'soboru_writer'):
    import json as _json
    os.environ.setdefault('OPENAI_API_KEY', 'vrt-fake')
    _prev_ai = m.companydesk.post_json
    def _day(s): return '%d월 %d일' % (int(s[5:7]), int(s[8:10]))
    def _writer_article(facts):
        if '검색어별 추이(증감률 큰 순)' in facts:
            rows = facts['검색어별 추이(증감률 큰 순)']; a, b = rows[0], rows[1]
            up = lambda r: f"{abs(r['증감률(%)'])}% {'늘었' if r['증감률(%)'] >= 0 else '줄었'}"
            others = [f"'{r['검색어']}'은 {up(r)}어요" for r in rows[1:]]
            return {'title': f"요즘 '{a['검색어']}' 검색이 {up(a)}어요",
                    'summary': [f"최근 4주 네이버에서 '{a['검색어']}'를 찾아본 정도가 그 전 4주보다 {up(a)}어요.", f"'{b['검색어']}'도 {up(b)}어요.",
                                '같은 일을 겪고 있다면, 아래 순서대로 기록부터 챙겨 두세요.'],
                    'sections': [{'heading': '이 숫자, 뭘 뜻해요?', 'paragraphs': ['네이버 데이터랩 검색어트렌드는 검색 횟수를 그대로 보여 주지 않아요. 기간 안에서 가장 많이 찾은 때를 100으로 두고, 나머지를 그에 견준 상대 지수로 보여 줘요.',
                                                                         f"그래서 검색어끼리 누가 더 많이 찾아졌는지 견줄 수 있어요. 이번에는 {facts['기간']} 동안 '{rows[0]['검색어']}' 같은 소비자 검색어 다섯 개를 주 단위로 봤어요."]},
                                 {'heading': f"'{a['검색어']}', 얼마나 늘었어요?", 'paragraphs': [f"최근 4주 평균 지수는 {a['최근 4주 평균 지수']}로, 그 전 4주 평균 {a['그 전 4주 평균 지수']}보다 {up(a)}어요.",
                                                                                          f"가장 많이 찾은 때는 {_day(a['가장 많이 찾은 주'])}이 낀 주였고, 그 주 지수는 {a['그 주 지수']}였어요."]},
                                 {'heading': '다른 검색어는요?', 'paragraphs': [', '.join(others) + '.']},
                                 {'heading': '왜 늘었는지는요?', 'paragraphs': ['자료만으로는 이유까지 알 수 없어요. 검색 지수는 사람들이 얼마나 많이 찾아봤는지만 보여 주거든요. 다만 같은 고민을 하는 사람이 적지 않다는 건 분명해요.']}],
                    'tips': ['결제 내역, 계약서, 상담 기록 같은 증거를 먼저 모아 두세요.', '업체에는 전화보다 문자나 게시판처럼 기록이 남는 방법으로 요청하세요.',
                             '해결이 안 되면 1372 소비자상담센터에 상담하거나 소보루에 제보해 주세요.'], 'category': '생활'}
        if '뉴스' in facts:
            n = facts['뉴스']
            return {'title': '이번 주 소비자 뉴스, 이것만 알면 돼요', 'summary': [n[0]['제목'][:40] + ' 소식이 있었어요.', n[1]['제목'][:40] + ' 소식도 눈여겨볼 만해요.', '관련 법 조문으로 내 권리도 같이 짚어 봤어요.'],
                    'sections': [{'heading': i['제목'][:30], 'paragraphs': [i['요약']]} for i in n[:3]] + [{'heading': '피해 상담은 2배 늘었대요', 'paragraphs': ['자세한 숫자는 뉴스 원문에서 확인해 주세요.']}],
                    'tips': ['계약서와 영수증을 챙겨 두세요.', '1372 소비자상담센터에 물어보세요.'], 'category': '생활'}
        return {'title': '소비자 데이터로 본 이번 주', 'summary': ['자료를 정리했어요.', '숫자는 자료 그대로예요.', '할 일을 챙겨 보세요.'],
                'sections': [{'heading': '정리', 'paragraphs': ['자료를 바탕으로 정리했어요.']}], 'tips': ['1372 소비자상담센터에 물어보세요.'], 'category': '생활'}
    def _writer_ai(url, headers, body, timeout):
        if 'images' in url: return 503, {}
        if '의 에디터다' not in body['messages'][0]['content']: return _prev_ai(url, headers, body, timeout)
        facts = _json.loads(body['messages'][1]['content'].split('[자료]\n', 1)[1])
        return 200, {'choices': [{'message': {'content': _json.dumps(_writer_article(facts), ensure_ascii=False)}}]}
    m.companydesk.post_json = _writer_ai
# 앱 준비 화면 시험(appready.py): 회원 vrt_member / membershotpw1 의 알림함·차단 목록, 다른 회원 글의 더 보기 메뉴,
# 로그인 화면 Apple 버튼(가짜 키, 실제 애플은 안 부름), 알림함 푸시 버튼(가짜 키, 실제 발송 없음)
if os.environ.get('VRT_BRAND') and hasattr(m, 'appready'):
    import datetime as _dt2
    from cryptography.hazmat.primitives.asymmetric import ec as _ec
    from cryptography.hazmat.primitives import serialization as _ser
    _k = _ec.generate_private_key(_ec.SECP256R1())
    os.environ.update(APPLE_SERVICE_ID='kr.co.consumerjebo.soboru.web', APPLE_TEAM_ID='VRTTEAM123', APPLE_KEY_ID='VRTKEY1234',
                      APPLE_PRIVATE_KEY=_k.private_bytes(_ser.Encoding.PEM, _ser.PrivateFormat.PKCS8, _ser.NoEncryption()).decode().replace('\n', '\\n'),
                      KAKAO_REST_API_KEY='vrt', KAKAO_CLIENT_SECRET='vrt', NAVER_CLIENT_ID='vrt', NAVER_CLIENT_SECRET='vrt',
                      VAPID_PUBLIC_KEY='BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U', VAPID_PRIVATE_KEY='vrt' * 14, VAPID_SUBJECT='mailto:vrt@example.com')
    m.appready.webpush_send = lambda s, p, l: (False, False)
    def _ago(h): return (_dt2.datetime.now() - _dt2.timedelta(hours=h)).isoformat(timespec='seconds')
    with m.conn() as db:
        def _user(login, nick): return db.execute('INSERT INTO users(login_id,pw_hash,nickname,email,terms_version,agreed_at,ip_hash,created) VALUES(?,?,?,?,?,?,?,?)',
                                                  (login, generate_password_hash('membershotpw1'), nick, '', m.TERMS_VERSION, _ago(200), 'seed', _ago(200))).lastrowid
        me, writer, spam = _user('vrt_member', '알뜰소비'), _user('vrt_writer', '리뷰장인'), _user('vrt_spam', '광고왕')
        q = db.execute("INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created,user_id,kind,likes) VALUES('질문해요','알뜰소비','','중고폰 판매자가 환불을 안 해 줘요','택배로 받은 중고폰 화면에 줄이 있는데 판매자가 연락을 피해요. 어떻게 해야 할까요?','seed',?,?,'question',3)", (_ago(30), me)).lastrowid
        db.execute("INSERT INTO comments(post_id,nickname,pw_hash,body,ip_hash,created,user_id) VALUES(?,'리뷰장인','','거래 앱 고객센터에 신고부터 하세요. 대화 내용을 캡처해 두면 좋아요.','seed',?,?)", (q, _ago(2), writer))
        db.execute("UPDATE posts SET comments=1 WHERE id=?", (q,))
        wp = db.execute("INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created,user_id,kind,target,rating,pros,cons,recommend,likes) VALUES('경험 공유','리뷰장인','','무선 이어폰 한 달 써 보니 배터리가 아쉬워요','소리는 깔끔한데 배터리가 하루를 못 가요. 교환 문의는 빨리 받아 줬어요.','seed',?,?,'review','소보루사운드',3,'교환 문의 응답이 빨라요','배터리가 하루를 못 가요',0,5)", (_ago(5), writer)).lastrowid
        db.execute("INSERT INTO comments(post_id,nickname,pw_hash,body,ip_hash,created,user_id) VALUES(?,'광고왕','','최저가 링크 드려요!! 지금 바로 클릭','seed',?,?)", (wp, _ago(1), spam))
        db.execute("INSERT INTO comments(post_id,nickname,pw_hash,body,ip_hash,created,user_id) VALUES(?,'알뜰소비','','저도 같은 모델인데 배터리 공감해요.','seed',?,?)", (wp, _ago(0.5), me))
        db.execute("INSERT INTO comments(post_id,nickname,pw_hash,body,ip_hash,created,user_id) VALUES(?,'리뷰장인','','충전 케이스까지 쓰면 이틀은 가요. 참고하세요!','seed',?,?)", (wp, _ago(0.2), writer))
        db.execute("UPDATE posts SET comments=3 WHERE id=?", (wp,))
        db.execute('INSERT INTO user_blocks(blocker,blocked,created) VALUES(?,?,?)', (me, spam, _ago(20)))
        cid = ids[0]
        for kind, body, link, h, read in [('answer', '내 질문에 답변이 달렸어요: 중고폰 판매자가 환불을 안 해 줘요', '/board/%d' % q, 2, ''),
                                          ('case', '내 제보에 기업 답변이 도착했어요: 반품했는데 환불이 안 돼요', '/me/case/%d' % cid, 5, ''),
                                          ('solved', '답변한 질문이 해결됐어요: 헬스장 6개월권 중도 해지하면 위약금이 얼마나 되나요?', '/board', 26, _ago(20)),
                                          ('comment', '내 글에 댓글이 달렸어요: 동네 마트 사장님 칭찬해요', '/board', 50, _ago(40)),
                                          ('case', '내 제보 진행 단계가 바뀌었어요: 반품했는데 환불이 안 돼요', '/me/case/%d' % cid, 80, _ago(70))]:
            db.execute('INSERT INTO member_alerts(user_id,kind,body,link,created,read_at) VALUES(?,?,?,?,?,?)', (me, kind, body, link, _ago(h), read))
    print('appready seed: member vrt_member / membershotpw1, writer post', wp, 'question', q, flush=True)
# 소보루 레터 화면 시험: 가짜 AI가 가짜 뉴스(VRT_NAVER)로 레터를 씀 (실제 OpenAI·메일은 안 부름). 1·2호는 보낸 레터, 3호는 검토 필요 초안. 구독자 몇 명
if hasattr(m, 'soboru_letter') and os.environ.get('VRT_NAVER'):
    import json as _json, datetime as _dt
    os.environ.setdefault('OPENAI_API_KEY', 'vrt-fake')
    _prev_letter = m.companydesk.post_json
    _LT = [('헬스장', '헬스장이 문 닫았다면, 남은 회원권은?', '다니던 헬스장이 갑자기 폐업하면 남은 기간 이용료를 날린 것 같아 막막하죠. 카드 할부로 결제했다면 이야기가 달라져요. 할부 항변권을 쓰면 카드사에 남은 할부금을 내지 않겠다고 말할 수 있어요. 다만 결제 금액과 할부 기간 같은 조건이 맞아야 해요. 자세한 조건은 기사 원문에서 확인해 보세요.', '카드사에 할부 항변권을 서면으로 신청하고, 폐업 안내 사진을 남겨 두세요.'),
           ('택배', '택배가 사라졌을 때 받을 수 있는 돈', '택배가 분실되면 보상은 운송장에 적은 물건 값을 기준으로 해요. 운송장에 값을 적지 않았다면 최대 50만 원까지만 받을 수 있대요. 비싼 물건을 보낼 땐 운송장에 값을 꼭 적어 두는 게 좋아요.', '보내기 전에 운송장에 물건 값을 적고, 영수증은 버리지 마세요.'),
           ('구독', '해지했는데 또 결제됐다면', '구독을 해지했는데 다음 달 요금이 또 빠져나가는 일, 생각보다 흔해요. 해지 버튼을 꽁꽁 숨기거나 여러 번 붙잡는 화면을 다크패턴이라고 불러요. 공정위가 이런 화면을 단속하겠다고 밝혔어요. 해지할 때는 해지 완료 화면을 꼭 남겨 두세요.', '해지 완료 화면을 캡처해 두고, 또 결제되면 바로 환불을 요청하세요.'),
           ('항공권', '항공권 취소 수수료, 약관부터 봐요', '항공권을 취소했더니 생각보다 수수료가 많이 나왔다는 상담이 이어지고 있어요. 수수료는 항공사와 여행사 약관에 따라 달라서, 예약할 때 약관을 먼저 확인하는 게 제일 좋아요. 항공사 사정으로 결항됐다면 수수료 없이 돌려받을 수 있는지도 꼭 물어보세요.', '예약 화면의 취소 규정을 캡처해 두고, 결항이면 수수료 없는 환불을 요청하세요.'),
           ('중고거래', '중고거래 사기, 안전결제가 답이에요', '중고거래 사기 피해가 1년 새 30% 늘었대요. 판매자가 따로 보내 주는 결제 링크는 가짜일 수 있어요. 거래는 앱 안의 안전결제로만 하고, 너무 싼 물건은 한 번 더 의심해 보세요.', '앱 밖 결제 링크는 누르지 말고, 플랫폼 안전결제만 쓰세요.')]
    _LT_NO = {'n': 0}
    def _letter_ai(url, headers, body, timeout):
        if '소보루 레터' not in body['messages'][0]['content']: return _prev_letter(url, headers, body, timeout)
        news = _json.loads(body['messages'][1]['content'].split('[이번 호 뉴스]\n', 1)[1])
        no = int(re.search(r'소보루 레터 (\d+)호', body['messages'][1]['content']).group(1))
        items = []
        for x in news:
            key, title, text, tip = next((t for t in _LT if t[0] in x['제목']), _LT[0])
            if no == 3 and key == '항공권': text += ' 지난해보다 상담이 2배 늘었대요.'  # 자료에 없는 숫자: 관리자 화면 '검토 필요' 보기
            items.append({'no': x['번호'], 'title': title, 'body': text, 'tip': tip, 'law': x['법 조문 후보'][0]['id'] if x['법 조문 후보'] else ''})
        out = {'subject': ['', '택배 분실 보상, 얼마까지 받을까?', '해지했는데 또 결제됐다면', '헬스장이 문 닫았다면, 남은 회원권은?'][no] if no <= 3 else '이번 주 소비자 뉴스',
               'intro': '소보루 이웃님, 다니던 헬스장이 하루아침에 문을 닫으면 남은 회원권은 어떻게 될까요? 오늘은 카드 할부로 결제했을 때 돈을 돌려받는 방법부터 같이 읽어봐요. 그 밖에 택배 분실 보상, 해지 후 또 빠져나간 구독료, 항공권 취소 수수료와 중고거래 사기 소식도 정리해봤어요.',
               'outro': '오늘도 억울한 일 없이 지나가길 바라요. 혹시 겪었다면 소보루에 알려 주세요. 내일 아침에 또 만나요.', 'items': items}
        return 200, {'choices': [{'message': {'content': _json.dumps(out, ensure_ascii=False)}}]}
    m.companydesk.post_json = _letter_ai
    _prev_nv = m.naverhub.http
    def _today_news(method, url, headers, body, timeout):  # 레터는 지난 하루 뉴스만 쓰므로 가짜 뉴스 날짜를 오늘로
        st, res = _prev_nv(method, url, headers, body, timeout)
        if '/search/v1/news' in url:  # 분야마다 맞는 가짜 뉴스만 (분야 그림 보기)
            import urllib.parse as _up
            q = dict(_up.parse_qsl(url.split('?', 1)[1])).get('query', '')
            want = {'소비자': ('헬스장', '구독'), '물가': ('택배',), '국제': ('항공권',), '사회': ('중고거래',)}.get(q, ())
            res = dict(res, items=[dict(it, pubDate=_dt.datetime.now().strftime('%a, %d %b %Y 06:00:00 +0900')) for it in res['items'] if any(w in it['title'] for w in want)])
        return st, res
    m.naverhub.http = _today_news
    with m.conn() as db: db.execute('DELETE FROM naver_cache')
    _lx = app.extensions['soboru_letter']
    with app.app_context():
        for _i in range(3): print('letter', _lx['generate']('admin'), flush=True)
    with m.conn() as db:
        _now = _dt.datetime.now()
        db.execute("UPDATE letters SET status='sent',sent_at=?,sent_count=126 WHERE no=1", ((_now - _dt.timedelta(days=7)).isoformat(timespec='seconds'),))
        db.execute("UPDATE letters SET status='sent',sent_at=?,sent_count=131,created=? WHERE no=2", (_now.isoformat(timespec='seconds'), (_now - _dt.timedelta(minutes=40)).isoformat(timespec='seconds')))
        for _k, (_e, _st) in enumerate([('kim.sobi@example.com', 'active'), ('park.jy@example.com', 'active'), ('lee.mart@example.com', 'active'), ('choi.new@example.com', 'pending'), ('x:' + 'a' * 64, 'unsubscribed')]):
            db.execute('INSERT INTO letter_subscribers(email,token,status,created,confirmed,place) VALUES(?,?,?,?,?,?)',
                       (_e, 'vrt-%d' % _k, _st, (_now - _dt.timedelta(days=10 - _k)).isoformat(timespec='seconds'),
                        (_now - _dt.timedelta(days=9 - _k)).isoformat(timespec='seconds') if _st == 'active' else None, ['home', 'letter', 'life', 'home', 'issue'][_k]))
print('ready', ids, eid, flush=True)
# 소보루 등급·사기 주의 미리보기: 순위용 기업 제보를 20일 전에 전달한 것으로 바꾸고 해결 확인을 몇 개 넣음, 공개된 사기 신고 몇 개
if hasattr(m, 'scamwatch') and os.environ.get('VRT_NN'):
    import datetime as _dt
    def _ago_d(d): return (_dt.datetime.now() - _dt.timedelta(days=d)).isoformat(timespec='seconds')
    with m.conn() as db:
        for row in db.execute("SELECT c.id,c.company FROM cases c WHERE c.id<0").fetchall():
            db.execute('UPDATE cases SET created=?,forwarded_at=? WHERE id=?', (_ago_d(40), _ago_d(30), row[0]))
            db.execute("UPDATE messages SET created=? WHERE case_id=? AND author='기업 답변'", (_ago_d(29.5 if row[1] == '소보루마트' else 27), row[0]))
        for name, outs in [('소보루마트', ['resolved'] * 5), ('보루텔레콤', ['resolved', 'resolved', 'resolved', 'unresolved']), ('오소보쇼핑', ['resolved', 'unresolved', 'unresolved'])]:
            ids = [r[0] for r in db.execute("SELECT c.id FROM cases c WHERE c.company=? AND c.id<0 AND EXISTS(SELECT 1 FROM messages WHERE case_id=c.id AND author='기업 답변') ORDER BY c.id", (name,))]
            for cid_, o in zip(ids, outs): db.execute('UPDATE cases SET outcome=?,confirmed_at=? WHERE id=?', (o, _ago_d(20), cid_))
        uid = db.execute('SELECT id FROM users LIMIT 1').fetchone()
        for kind, region, title, story, tt, target, amount, d in [
                ('used', '서울', '중고 아이패드 입금했는데 연락이 끊겼어요', '중고거래 앱에서 아이패드를 보고 판매자가 보낸 안전결제 링크로 45만 원을 보냈어요. 결제 뒤 판매자 계정이 사라졌어요.', 'site', 'https://safe-pay-check.kr/order/123', 450000, 2),
                ('shop', '온라인·모름', '명품 운동화 70% 할인 쇼핑몰, 배송이 안 와요', '인스타 광고로 본 쇼핑몰에서 운동화를 샀는데 한 달째 배송이 없어요. 사업자 정보도 가짜였어요.', 'site', 'www.brand-outlet-kr.shop', 189000, 5),
                ('sms', '경기', '택배 주소 확인 문자 누르니 앱이 깔렸어요', '택배 주소가 잘못됐다는 문자에 링크가 있어서 눌렀더니 이상한 앱이 설치됐어요.', 'phone', '010-2389-4471', 0, 3),
                ('call', '부산', '검찰이라며 계좌가 범죄에 쓰였대요', '검찰 수사관이라는 사람이 전화해서 내 계좌가 범죄에 쓰였다며 안전 계좌로 옮기라고 했어요.', 'account', '국민 123456789012', 3000000, 8),
                ('invest', '대구', '리딩방에서 코인 투자하라고 해서 입금했어요', '원금 보장에 한 달 30% 수익이라며 리딩방에 초대받았어요. 처음엔 수익이 보이더니 출금이 안 돼요.', 'sns', '@coin_master_vip', 5200000, 12),
                ('used', '서울', '중고 카메라 판매자가 선입금만 요구해요', '직거래는 안 되고 선입금만 된다고 했어요. 같은 계좌로 다른 사람도 당했대요.', 'account', '신한 110987654321', 320000, 15),
                ('shop', '인천', '해외 직구 대행 사이트가 결제 후 사라졌어요', '대행 수수료가 싸서 맡겼는데 결제하고 나서 사이트가 닫혔어요.', 'site', 'buy-for-you.co', 640000, 20)]:
            db.execute("INSERT INTO scam_reports(kind,region,title,story,target_type,target,target_norm,amount,occurred_on,user_id,ip_hash,status,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,'public',?)",
                       (kind, region, title, story, tt, target, m.scamwatch.norm_target(tt, target), amount, _ago_d(d + 1)[:10], uid[0] if uid else None, 'seed', _ago_d(d)))
        db.execute("INSERT INTO scam_reports(kind,region,title,story,target_type,target,target_norm,status,created) VALUES('etc','서울','확인 전 신고 (보이면 안 됨)','운영자가 아직 확인하지 않은 신고예요. 공개 화면에 나오면 안 돼요.','none','','','pending',?)", (_ago_d(0),))
app.run(host='127.0.0.1', port=PORT)
