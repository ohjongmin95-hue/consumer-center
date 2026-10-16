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
    with m.conn() as db:
        db.execute("INSERT OR REPLACE INTO site_content(key,value,updated) VALUES('site.brand',?,'2026-10-16')", (os.environ['VRT_BRAND'],))
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
