# 소비자제보센터 화면 시험용 서버: 임시 DB에 예시 제보를 넣고 띄움 (실제 DB·운영 서버와 무관)
#   python tools/site_vrt_server.py [앱 폴더] [포트]   기본: 이 저장소, 8822
# 고치기 전 화면(기준 그림)은 git worktree로 받은 이전 코드 폴더를 앱 폴더로 넘겨서 띄워요.
# 관리자 비밀번호 adminshotpw1, 제보 조회 010-2222-3333 / 1234, 기업 회원 sobo_cs / bizshotpw1
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
post(u, '/report', dict(base, subject='비밀글 제보 예시', company='오소보쇼핑', phone='010-9999-0000', visibility='secret'))
print('ready', ids, eid, flush=True)
app.run(host='127.0.0.1', port=PORT)
