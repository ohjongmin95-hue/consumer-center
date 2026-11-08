"""Exercise the live templates and existing report flow using an isolated database."""
import datetime, json, hashlib, io
import importlib.util
import io, os
from pathlib import Path
import re
import secrets
import tempfile
import threading
_REAL_THREAD = threading.Thread
import unittest
import urllib.parse
from unittest.mock import patch

from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]


class SiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.password = secrets.token_urlsafe(24)
        cls.env = patch.dict(os.environ, {
            'DATABASE_PATH': str(Path(cls.temp.name) / 'cases.sqlite3'),
            'UPLOAD_DIR': str(Path(cls.temp.name) / 'uploads'),
            'SECRET_KEY': secrets.token_hex(32),
            'ADMIN_PASSWORD_HASH': generate_password_hash(cls.password),
            'ENABLE_INTAKE': '1',
            'ENABLE_BOARD': '1',
            'HTTPS_ONLY': '0',
            'SOBORU_GUEST_WRITE': '1', 'SOBORU_EXAMPLES': '0', 'SOBORU_COMPANY_SEED': '0', 'SOBORU_LOGO_FETCH': '0',  # 예전 테스트는 비회원 글쓰기로 돎. 소보루 로그인 글쓰기는 test_soboru_login_to_write에서
        })
        cls.env.start()
        spec = importlib.util.spec_from_file_location('site_under_test', ROOT / 'app.py')
        cls.site = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.site)
        cls.site.app.config['TESTING'] = True

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.temp.cleanup()

    def test_www_redirects_to_bare_domain(self):
        r = self.client.get('/reports?page=2', base_url='https://www.consumerjebo.co.kr')
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r.headers['Location'], 'https://consumerjebo.co.kr/reports?page=2')
        self.assertEqual(self.client.get('/', base_url='https://consumerjebo.co.kr').status_code, 200)

    def test_process_disclaimer(self):
        # 운영 안내는 하단이 아니라 처리 절차 페이지 맨 아래에만. 운영자 2026-11-03: 변호사 소개는 하되 돈은 안 받음
        page = self.client.get('/process').get_data(as_text=True)
        self.assertIn('돈은 받지 않아요', page); self.assertNotIn('변호사 소개는 하지 않아요', page)
        self.assertNotIn('돈은 받지 않아요', self.client.get('/').get_data(as_text=True))

    def test_search_meta_tags(self):
        import json, re
        def ld(html):
            return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('<title>소보루(SOBORU) - 소비자 제보·내돈내산 후기·소비 생활 매거진</title>', home)
        self.assertIn('<meta name="title" content="소보루(SOBORU) - 소비자 제보·내돈내산 후기·소비 생활 매거진">', home)
        self.assertIn('소비자 피해 제보부터 제품·업체 리뷰와 추천', home)
        self.assertIn('og:locale" content="ko_KR"', home)
        self.assertIn('WebSite', [d.get('@type') for d in ld(home)])
        with self.site.conn() as db:
            cid = db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES('CJ-SEO','x','배송·환불','가게','환불이 안 돼요','한 달째 환불을 안 해 줍니다','환불','2026-10-09T10:00:00',1,1)").lastrowid
            pid = db.execute("INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created) VALUES(?,?,?,?,?,?,?)", ('꿀팁', '소비자', '', '환불 받은 후기', '이렇게 해서 환불을 받았어요', 'x', '2026-10-09T10:00:00')).lastrowid
        page = self.client.get(f'/reports/{cid}').get_data(as_text=True)
        self.assertIn('og:type" content="article"', page)
        self.assertEqual(ld(page)[0][0]['@type'], 'Article')
        post = self.client.get(f'/board/{pid}').get_data(as_text=True)
        self.assertEqual(ld(post)[0][0]['@type'], 'DiscussionForumPosting')
        faq = self.client.get('/faq').get_data(as_text=True)
        self.assertIn('<title>자주 묻는 질문 | 소보루</title>', faq)
        self.assertIn('FAQPage', faq)
        self.assertNotIn('noindex', self.client.get('/reports').get_data(as_text=True))
        self.assertIn('noindex,follow', self.client.get('/reports?q=환불').get_data(as_text=True))

    def test_company_grade_and_summary(self):
        # 소보루 등급: 답변 50 + 해결 30 + 속도 20, 전달하고 14일이 안 된 제보는 빼고, 14일 넘게 답이 없으면 '답변 없음'
        import datetime, jebo
        self.assertEqual([jebo.grade_of(s) for s in (100, 97, 96, 90, 80, 60, 59, 0)], ['A+', 'A+', 'A', 'A-', 'B-', 'D-', 'F', 'F'])
        today = datetime.date.today()
        ago = lambda d, h=0: (datetime.datetime.combine(today, datetime.time(9)) - datetime.timedelta(days=d, hours=-h)).isoformat(timespec='seconds')
        self.assertTrue(jebo.no_answer({'forwarded_at': ago(15)}, False))
        self.assertFalse(jebo.no_answer({'forwarded_at': ago(15)}, True))
        self.assertFalse(jebo.no_answer({'forwarded_at': ago(3)}, False))
        self.assertFalse(jebo.no_answer({'forwarded_at': ''}, False))
        with self.site.conn() as db:
            co = db.execute("INSERT INTO companies(name,biz_no,status,contact_name,contact_phone,contact_email,created) VALUES('등급몰','1','active','','','','x')").lastrowid
            def case(n, answer_h=None, outcome='', fw=30):
                cid = db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,company_id,subject,description,request_text,created,forwarded_at,reviewed_at,status,outcome,public_consent,published) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,1)",
                                 (f'GR-{n}', 'x', '배송·환불', '등급몰', co, f'제보 {n}', '환불이 안 돼요', '환불', ago(fw + 1), ago(fw), ago(fw), '기업 전달', outcome)).lastrowid
                if answer_h is not None:
                    db.execute("INSERT INTO messages(case_id,author,body,created) VALUES(?,?,?,?)", (cid, '기업 답변', '확인할게요', ago(fw, answer_h)))
            for i in range(4): case(i, 10, 'resolved')
            gr = jebo.company_grade(db, co)
            self.assertEqual(gr['grade'], '')  # 4건이면 아직 등급 없음
            case(4, 30)
            case(5, None, fw=3)  # 전달 3일째: 기다리는 중, 점수에 안 들어감
            gr = jebo.company_grade(db, co)
            self.assertEqual((gr['scored'], gr['answered'], gr['silent'], gr['told'], gr['resolved']), (5, 5, 0, 4, 4))
            self.assertEqual((gr['score'], gr['grade']), (50 + 15 + 20, 'B'))  # 해결을 알려 준 사람이 5명 미만이면 해결 점수는 절반
            case(6, None, fw=20)  # 20일째 답 없음
            gr = jebo.company_grade(db, co)
            self.assertEqual(gr['silent'], 1)
            self.assertEqual(gr['score'], round(50 * 5 / 6) + 15 + 20)
        page = self.client.get(f'/companies/{co}').get_data(as_text=True)
        self.assertIn('co-grade g-', page)
        self.assertIn('1건은 전달하고 14일이 넘도록 답이 없어요', page)
        self.assertIn('해결됐어요', page)
        self.assertIn('>답변 없음<', page)
        guide = self.client.get('/companies/grade').get_data(as_text=True)
        self.assertIn('60점 미만', guide)
        self.assertNotIn('060점', guide)
        self.assertIn('/companies/grade', self.client.get('/companies').get_data(as_text=True))

    def test_home_pieces_hidden_and_toggle(self):
        # 꾸밈 조각(빨간 점 꼬리표·고민될 땐·오늘의 수다 상자)은 처음부터 숨김, 관리자가 다시 보이게 할 수 있음
        home = self.client.get('/').get_data(as_text=True)
        self.assertNotIn('nn-voice-tag', home)
        self.assertNotIn('고민될 땐', home)
        self.assertNotIn('nn-talk-box', home)
        admin = self.login_admin()
        token = self.csrf(admin, '/admin/screens')
        self.assertTrue(admin.post('/admin/screens', data={'_csrf': token, 'page': '_piece', 'block': 'home.vs_box', 'act': 'show', 'ajax': '1'}).get_json()['ok'])
        self.assertIn('고민될 땐', self.client.get('/').get_data(as_text=True))
        self.assertEqual(admin.post('/admin/screens', data={'_csrf': token, 'page': '_piece', 'block': 'nope', 'act': 'show'}).status_code, 400)
        admin.post('/admin/screens', data={'_csrf': token, 'page': '_piece', 'block': 'home.vs_box', 'act': 'hide', 'ajax': '1'})
        screens = admin.get('/admin/screens').get_data(as_text=True)
        self.assertIn('작은 꾸밈 넣기 · 지우기', screens)
        self.assertIn('＋ 넣기', screens)
        self.assertNotIn('고민될 땐', self.client.get('/').get_data(as_text=True))

    def test_openai_credit_alert(self):
        # OpenAI 충전금이 바닥나면(429 insufficient_quota) 관리자 화면 맨 위에 알림, 충전 뒤 호출이 성공하면 저절로 사라짐
        desk = self.site.companydesk
        admin = self.login_admin()
        self.assertNotIn('class="ad-ai-alert"', admin.get('/admin').get_data(as_text=True))
        quota = (429, {'error': {'message': 'You exceeded your current quota', 'type': 'insufficient_quota', 'code': 'insufficient_quota'}})
        with patch.object(desk, '_post_json', return_value=quota):
            self.assertEqual(desk.post_json('https://api.openai.com/v1/chat/completions', {}, {}, 5)[0], 429)
        page = admin.get('/admin').get_data(as_text=True)
        self.assertIn('OpenAI 충전금이 바닥났어요', page)
        self.assertIn('AI 글쓰기·답변', page)
        self.assertNotIn('ad-ai-alert', self.client.get('/').get_data(as_text=True))  # 방문자에게는 안 보임
        with patch.object(desk, '_post_json', return_value=(429, {'error': {'code': 'rate_limit_exceeded'}})):
            desk.post_json('https://api.openai.com/v1/chat/completions', {}, {}, 5)  # 잠깐 몰린 것(속도 제한)은 충전 알림이 아님
        self.assertIn('충전금이 바닥났어요', admin.get('/admin').get_data(as_text=True))
        with patch.object(desk, '_post_json', return_value=(200, {'choices': []})):
            desk.post_json('https://api.openai.com/v1/chat/completions', {}, {}, 5)
        self.assertNotIn('class="ad-ai-alert"', admin.get('/admin').get_data(as_text=True))
        with patch.object(desk, '_post_json', return_value=(401, {'error': {'code': 'invalid_api_key'}})):
            desk.post_json('https://api.openai.com/v1/chat/completions', {}, {}, 5)
        self.assertIn('OpenAI 키가 막혔어요', admin.get('/admin').get_data(as_text=True))
        with patch.object(desk, '_post_json', return_value=(200, {})): desk.post_json('https://api.openai.com/v1/chat/completions', {}, {}, 5)

    def test_scam_watch(self):
        # 사기 주의: 회원만 신고, 운영자가 '공개'로 바꾸기 전에는 어디에도 안 보임, 번호는 일부만 보이고 검색은 전체 번호로
        import scamwatch
        self.assertEqual(scamwatch.mask_target('phone', '010-2389-4471'), '010-23**-**71')
        self.assertEqual(scamwatch.mask_target('account', '신한 110-123-456789'), '신한 110*******89')
        self.assertEqual(scamwatch.norm_target('site', 'https://www.Abc-Shop.kr/item?id=1'), 'abc-shop.kr')
        self.assertEqual(scamwatch.guess_norm('010 2389 4471'), ['01023894471'])
        with self.site.conn() as db: db.execute('DELETE FROM scam_reports')
        self.assertEqual(self.client.get('/scam').status_code, 200)
        self.assertIn('/login', self.client.get('/scam/new').headers['Location'])
        member = self.site.app.test_client()
        self.signup(member)
        data = {'kind': 'used', 'title': '중고 카메라 선입금 사기', 'story': '직거래는 안 되고 선입금만 된다고 했어요. 입금하니 연락이 끊겼어요.',
                'target_type': 'phone', 'target': '010-2389-4471', 'region': '서울', 'amount': '320,000', 'truth': '1'}
        self.assertEqual(self.post_form(member, '/scam/new', {**data, 'truth': ''}).status_code, 400)
        self.assertEqual(self.post_form(member, '/scam/new', data).status_code, 302)
        hidden = self.client.get('/scam?q=010-2389-4471').get_data(as_text=True)
        self.assertNotIn('중고 카메라 선입금 사기', hidden)
        self.assertIn('아직 공개된 신고는 없어요', hidden)
        admin = self.login_admin()
        self.assertIn('중고 카메라 선입금 사기', admin.get('/admin/scam').get_data(as_text=True))
        with self.site.conn() as db: sid = db.execute('SELECT id FROM scam_reports').fetchone()[0]
        token = self.csrf(admin, '/admin/scam')
        admin.post('/admin/scam', data={'_csrf': token, 'id': sid, 'status': 'public', 'admin_note': ''})
        found = self.client.get('/scam?q=01023894471').get_data(as_text=True)
        self.assertIn('사기 신고가 1건 있어요', found)
        self.assertIn('010-23**-**71', found)
        self.assertNotIn('010-2389-4471', found)
        self.assertIn('32만 원', found)
        self.assertIn('사기 주의', self.client.get('/').get_data(as_text=True))

    def setUp(self):
        self.client = self.site.app.test_client()
        self.site.app.config['ADMIN_FACE'] = 'soboru'  # 옛 소보루 사이트 편집 시험 (실제 관리자는 소비자제보센터가 기본)
        with self.site.conn() as db:
            for table in ('group_members', 'damage_groups', 'company_users', 'companies', 'notifications', 'internal_notes', 'company_invites', 'attachments', 'messages', 'cases', 'site_content', 'site_lists', 'takedown_requests', 'board_votes', 'comments', 'posts', 'users', 'login_attempts', 'staff', 'case_log', 'admin_settings', 'user_identities', 'company_memberships', 'company_requests', 'company_contacts', 'answer_files', 'company_notices', 'user_blocks', 'member_alerts', 'push_subscriptions', 'apple_tokens'):
                db.execute('DELETE FROM ' + table)

    def old_guide(self):
        # 예전 이용 안내 구성(구매 정보·작성 방법·자료·분야별)으로 되돌려 편집 기능을 시험
        kinds = ['guide_basics', 'guide_writing', 'guide_evidence', 'guide_topics', 'guide_bottom']
        rows = [{'kind': k, 'title': '', 'body': '', 'button_label': '', 'button_link': ''} for k in kinds]
        with self.site.conn() as db:
            db.execute("INSERT OR REPLACE INTO site_lists(key,value,updated) VALUES('layout_guide',?,'x')", (json.dumps(rows),))

    def csrf(self, client, path):
        response = client.get(path)
        self.assertEqual(response.status_code, 200)
        return re.search(r'name="_csrf" value="([^"]+)"', response.get_data(as_text=True))[1]

    def test_navigation_and_real_form(self):
        for path in ('/', '/reports', '/guide', '/process', '/types', '/faq', '/report', '/lookup', '/terms', '/privacy', '/takedown', '/board', '/board/write'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn('class="sb-header', response.get_data(as_text=True))  # 소보루 머리글 하나뿐 (예전 소비자제보센터 머리글은 뺌)
            self.assertNotIn('class="section-nav"', response.get_data(as_text=True))
        for path in ('/admin/login', '/reporter/login'):
            self.assertIn('noindex', self.client.get(path).get_data(as_text=True))
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('nn-intro', home)
        self.assertIn('<title>소보루(SOBORU) - 소비자 제보·내돈내산 후기·소비 생활 매거진</title>', home)
        self.assertIn('<meta property="og:title" content="소보루(SOBORU) - 소비자 제보·내돈내산 후기·소비 생활 매거진">', home)
        self.assertNotIn('brand-by', home)
        self.assertIn('href="/report"', home)
        self.assertNotIn('localStorage', home)
        self.assertEqual(self.client.get('/?look=old').get_data(as_text=True).count('nn-intro'), home.count('nn-intro'))  # 예전 홈 비교 주소도 소보루 홈
        report = self.client.get('/report?category=배송·교환·환불').get_data(as_text=True)
        self.assertIn('<option selected>배송·교환·환불</option>', report)

    def test_public_list_filters_only_approved_consented_cases(self):
        with self.site.conn() as db:
            for receipt, subject, category, consent, published in (
                ('one', '공개 환불 요청', '배송·환불', 1, 1),
                ('two', '공개 계약 문의', '서비스·계약', 1, 1),
                ('three', '비공개 접수', '배송·환불', 1, 0),
                ('four', '미동의 접수', '배송·환불', 0, 1),
            ):
                db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (receipt, hashlib.sha256(b'test').hexdigest(), category, '테스트 업체', subject, '공개 본문' if consent and published else '비공개 상세 내용', '요청', '2026-10-09', consent, published))
            db.execute("UPDATE cases SET reviewed_at='2026-10-10T10:00:00' WHERE receipt='three'")  # 운영자가 보고 공개하지 않기로 둔 제보
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('공개 환불 요청', home)
        self.assertIn('공개 계약 문의', home)
        # 비밀글·공개 전 제보도 제목·업체명은 보이고(눌러도 비밀번호 창), 본문은 안 보임
        self.assertIn('미동의 접수', home)
        self.assertIn('비공개 접수', home)
        live = home.split('class="nn-sec nn-live')[1].split('</section>')[0]  # 방금 들어온 제보: 공개 제보만 본문 앞부분, 비밀글·공개 전은 제목·업체만
        self.assertNotIn('비공개 상세 내용', live); self.assertEqual(live.count('공개 본문'), 2)
        self.assertEqual(live.count('<span class="nn-vc-co">테스트 업체</span>'), 4)
        self.assertNotIn('nn-stats', home)  # 메인에는 건수 현황 없음
        self.assertNotIn('비공개 처리된 제보예요', home)
        self.assertNotIn('비밀글로 접수된 제보예요', home)
        self.assertNotIn('누적 제보', self.client.get('/reports').get_data(as_text=True))
        self.assertIn('>접수</span>', live)
        filtered_cat = self.client.get('/reports', query_string={'category': '배송·교환·환불'}).get_data(as_text=True)
        self.assertIn('미동의 접수</h3>', filtered_cat)  # 소보루 제보 목록은 카드 (2026-11-03)
        self.assertIn('비공개 접수</h3>', filtered_cat)
        self.assertNotIn('공개 계약 문의', filtered_cat)
        self.assertIn('비공개 접수', self.client.get('/reports?q=비공개').get_data(as_text=True))
        self.assertIn('미동의 접수', self.client.get('/reports?q=미동의').get_data(as_text=True))
        # 예전에 '제목 숨김'으로 둔 제보도 제목은 보이고, 반려·중복 처리한 제보만 제목을 내림
        with self.site.conn() as db:
            db.execute("UPDATE cases SET title_hidden=1 WHERE subject='미동의 접수'")
            db.execute("UPDATE cases SET review='rejected' WHERE subject='비공개 접수'")
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('미동의 접수', home)
        self.assertNotIn('비공개 접수', home)
        self.assertNotIn('비공개 접수', self.client.get('/reports?q=비공개').get_data(as_text=True))
        filtered = self.client.get('/reports', query_string={'q': '환불', 'category': '배송·교환·환불'}).get_data(as_text=True)
        self.assertIn('공개 환불 요청', filtered)
        self.assertNotIn('공개 계약 문의', filtered)
        empty = self.client.get('/reports?q=missing').get_data(as_text=True)
        self.assertIn('찾는 제보가 없어요.', empty)

    def test_hero_banner_default_video(self):
        # 운영자 2026-11-03: 첫 화면 기본 = 둥근 배너 + '대화로 제보하기' 영상, '실제 제보 영상' 글씨 없음
        self.site.JEBO_HOSTS.add('consumerjebo.co.kr'); self.addCleanup(self.site.JEBO_HOSTS.discard, 'consumerjebo.co.kr')
        home = self.client.get('/', base_url='https://consumerjebo.co.kr').get_data(as_text=True)
        self.assertIn('hero-photo', home); self.assertIn('img/hero-city.jpg', home); self.assertNotIn('실제 제보 영상', home)

    def test_guide_toss_jebo(self):
        # 운영자 2026-11-03: 제보센터 이용 안내 = 토스식 + '대화로 제보하기' 화면 영상 + 업종 칩
        self.site.JEBO_HOSTS.add('consumerjebo.co.kr'); self.addCleanup(self.site.JEBO_HOSTS.discard, 'consumerjebo.co.kr')
        page = self.client.get('/guide', base_url='https://consumerjebo.co.kr').get_data(as_text=True)
        for text in ('tg-page', 'video/guide-howto.mp4', 'data-tg-i="0"', '이 세 가지만'):
            self.assertIn(text, page)
        self.assertNotIn('tg-page', self.client.get('/guide').get_data(as_text=True))  # 소보루 화면은 그대로

    def test_hero_photos_wall(self):
        # 첫 화면 사진 (운영자 2026-11-03): 관리자가 고른 제보 사진의 가린 사본만 공개, 3장부터 제보센터 첫 화면 뒤에 깔림
        with self.site.conn() as db: db.execute("INSERT OR REPLACE INTO site_content(key,value,updated) VALUES('home.hero_media','off','x')")  # 첫 화면 사진은 영상을 껐을 때만 (운영자 2026-11-03: 기본은 '대화로 제보하기' 영상 배너)
        def _off():
            with self.site.conn() as db: db.execute("DELETE FROM site_content WHERE key='home.hero_media'")
        self.addCleanup(_off)
        from PIL import Image
        jebo = 'https://consumerjebo.co.kr'
        self.site.JEBO_HOSTS.add('consumerjebo.co.kr'); self.addCleanup(self.site.JEBO_HOSTS.discard, 'consumerjebo.co.kr')
        self.assertNotIn('hero-split', self.client.get('/', base_url=jebo).get_data(as_text=True))
        self.assertEqual(self.client.get('/admin/hero-photos').status_code, 302)
        admin = self.login_admin()
        token = self.csrf(admin, '/admin/hero-photos')
        def pic(color):
            b = io.BytesIO(); Image.new('RGB', (900, 1200), color).save(b, 'JPEG'); b.seek(0); return b
        for i, color in enumerate(('red', 'green', 'blue')):
            r = admin.post('/admin/hero-photos/add', data={'_csrf': token, 'mode': 'boxes' if i else 'all', 'boxes': '[[0.1,0.1,0.5,0.5]]', 'caption': '택배 · 파손', 'photo': (pic(color), 'a.jpg')}, content_type='multipart/form-data')
            self.assertEqual(r.status_code, 302)
        home = self.client.get('/', base_url=jebo).get_data(as_text=True)
        self.assertIn('hero-split', home); self.assertNotIn('실제 제보 사진', home)  # 직접 올린 사진엔 '실제 제보 사진' 표시 X (운영자 2026-11-03)
        name = re.search(r'/hero/([0-9a-f]{24}\.jpg)', home).group(1)
        img = self.client.get('/hero/' + name)
        self.assertEqual((img.status_code, Image.open(io.BytesIO(img.data)).size), (200, (600, 800)))
        self.assertEqual(self.client.get('/hero/' + 'a' * 24 + '.jpg').status_code, 404)
        with self.site.conn() as db: pid = db.execute('SELECT id FROM hero_photos WHERE stored=?', (name,)).fetchone()[0]
        admin.post('/admin/hero-photos/%d' % pid, data={'_csrf': token, 'act': 'delete'})
        self.assertEqual(self.client.get('/hero/' + name).status_code, 404)
        self.assertIn('hero-split', self.client.get('/', base_url=jebo).get_data(as_text=True))  # 직접 올린 사진은 한두 장이어도 나옴 (운영자 2026-11-03)

    def test_report_needs_login(self):
        # 운영자 2026-11-03: 로그인해야 제보 (대화 제보·양식 모두). 이름·전화번호 칸은 그대로
        import os
        os.environ['REPORT_LOGIN'] = '1'; self.addCleanup(os.environ.pop, 'REPORT_LOGIN', None)
        for path in ('/report', '/report/talk'):
            r = self.client.get(path); self.assertEqual(r.status_code, 302); self.assertIn('/login', r.headers['Location'])
        os.environ['REPORT_LOGIN'] = '0'
        self.assertIn('제보 전 꼭 읽어 주세요', self.client.get('/report/talk').get_data(as_text=True))

    def test_hero_photos_auto(self):
        # 운영자 2026-11-03: 공개 게시된 제보의 사진은 관리자가 안 골라도 모자이크해서 첫 화면에. 비공개로 바뀌면 바로 빠짐
        with self.site.conn() as db: db.execute("INSERT OR REPLACE INTO site_content(key,value,updated) VALUES('home.hero_media','off','x')")  # 첫 화면 사진은 영상을 껐을 때만 (운영자 2026-11-03: 기본은 '대화로 제보하기' 영상 배너)
        def _off():
            with self.site.conn() as db: db.execute("DELETE FROM site_content WHERE key='home.hero_media'")
        self.addCleanup(_off)
        from PIL import Image
        jebo = 'https://consumerjebo.co.kr'
        self.site.JEBO_HOSTS.add('consumerjebo.co.kr'); self.addCleanup(self.site.JEBO_HOSTS.discard, 'consumerjebo.co.kr')
        with self.site.conn() as db:
            cids = []
            from PIL import ImageDraw
            boxes = [(0, 0, 400, 800), (0, 0, 800, 400), (200, 200, 600, 600), (0, 0, 400, 800)]  # 마지막은 첫 사진과 같은 사진 → 한 번만
            for i in range(4):
                cid = db.execute("INSERT INTO cases(receipt,lookup_hash,category,industry,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                 ('CJ-HERO%d' % i, 'x', '배송·환불', '쇼핑·유통', '가게%d' % i, '환불이 안 돼요', '내용', '환불', '2026-10-09T10:00:00', 1, 1)).lastrowid
                im = Image.new('RGB', (800, 800), 'white'); ImageDraw.Draw(im).rectangle(boxes[i], fill='red')
                name = 'hero-src-%d.jpg' % i; b = io.BytesIO(); im.save(b, 'JPEG'); (self.site.UPLOAD / name).write_bytes(b.getvalue())
                db.execute('INSERT INTO attachments(case_id,stored,original) VALUES(?,?,?)', (cid, name, 'a.jpg')); cids.append(cid)
            secret = db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES('CJ-HEROX','x','배송·환불','가게','비밀','내용','환불','2026-10-09T10:00:00',0,0)").lastrowid
            db.execute("INSERT INTO attachments(case_id,stored,original) VALUES(?,'hero-src-0.jpg','a.jpg')", (secret,))
        self.login_admin().get('/admin/hero-photos')  # 관리자 화면을 열면 바로 채움
        home = self.client.get('/', base_url=jebo).get_data(as_text=True)
        self.assertNotIn('hero-split', home)  # 운영자 2026-11-03: 제보 사진은 작고 흐려서 첫 화면 큰 카드엔 안 씀 (직접 올린 연출 사진만)
        with self.site.conn() as db: names = [r[0] for r in db.execute("SELECT stored FROM hero_photos WHERE auto=1 AND hidden=0")]
        self.assertEqual(len(names), 3)  # 비공개 제보 사진·같은 사진은 안 들어감
        self.assertEqual(self.client.get('/hero/' + names[0]).status_code, 200)
        with self.site.conn() as db: db.execute('UPDATE cases SET published=0 WHERE id=?', (cids[1],))
        self.assertEqual(sum(self.client.get('/hero/' + n).status_code == 404 for n in names), 1)

    def test_case_shots(self):
        # 운영자 2026-11-04: 첫 화면 아래 제보 사진 — 전체 모자이크 없이, AI가 찾은 이름·번호 자리만 가림. AI 못 쓰면 안 냄, 신분증 같은 건 빼기
        import json, case_shots
        from unittest import mock
        from PIL import Image, ImageDraw
        jebo = 'https://consumerjebo.co.kr'
        self.site.JEBO_HOSTS.add('consumerjebo.co.kr'); self.addCleanup(self.site.JEBO_HOSTS.discard, 'consumerjebo.co.kr')
        with self.site.conn() as db:
            cids = []
            for i in range(5):
                cid = db.execute("INSERT INTO cases(receipt,lookup_hash,category,industry,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                 ('CJ-SHOT%d' % i, 'x', '배송·환불', '쇼핑·유통', '사진가게%d' % i, '사진 제보 %d' % i, '내용', '환불', '2026-10-09T10:00:00', 1, 1)).lastrowid
                im = Image.new('RGB', (800, 600), 'white'); d = ImageDraw.Draw(im)
                for x in range(0, 400, 4): d.line([(x, 0), (x, 300)], fill='black' if x % 8 else 'red')  # 왼쪽 위 = '전화번호' 자리 (줄무늬)
                k = 2 if i == 3 else i; d.rectangle(([(420, 320, 800, 600), (400, 0, 800, 300), (0, 320, 380, 600), (0, 0, 0, 0), (600, 100, 700, 500)][k]), fill='blue')  # 3번은 2번과 같은 사진
                name = 'shot-src-%d.jpg' % i; b = io.BytesIO(); im.save(b, 'JPEG', quality=95); (self.site.UPLOAD / name).write_bytes(b.getvalue())
                db.execute('INSERT INTO attachments(case_id,stored,original) VALUES(?,?,?)', (cid, name, 'a.jpg')); cids.append(cid)
        def answer(i):
            body = {'private': True} if i == 4 else {'boxes': [{'x': 0, 'y': 0, 'w': 0.5, 'h': 0.5, 'what': '전화번호'}], 'private': False}
            return 200, {'choices': [{'message': {'content': json.dumps(body)}}]}
        with mock.patch.object(case_shots.companydesk, 'ai_key_for', return_value=''):
            self.assertEqual(self.site.case_shots_fill(10), 0)  # AI 키가 없으면 아무것도 안 냄
        calls = iter(range(4, -1, -1))  # 최근 제보부터 봄 → 마지막(4번)이 '개인정보 대부분'
        with mock.patch.object(case_shots.companydesk, 'ai_key_for', return_value='k'), mock.patch.object(case_shots.companydesk, 'post_json', side_effect=lambda *a: answer(next(calls))):
            self.assertEqual(self.site.case_shots_fill(5), 3)  # 같은 사진(3·2번)은 한 번만
        with self.site.conn() as db:
            rows = db.execute("SELECT id,stored,case_id FROM case_shots WHERE stored!='' ORDER BY case_id").fetchall()
            self.assertEqual(db.execute("SELECT note FROM case_shots WHERE case_id=?", (cids[4],)).fetchone()[0], 'private')
            self.assertEqual(db.execute("SELECT COUNT(*) FROM case_shots WHERE note='dup'").fetchone()[0], 1)
        self.assertEqual(len(rows), 3)
        shot = Image.open(self.site.UPLOAD / 'shots' / rows[0]['stored']).convert('RGB')
        left = [shot.getpixel((x, 60)) for x in range(20, 200, 2)]; right = shot.getpixel((330, 262))
        self.assertLess(max(map(sum, left)) - min(map(sum, left)), 90)  # 가린 곳은 줄무늬가 뭉개짐 (검정·빨강이 섞여 한 색)
        self.assertGreater(sum(right), 700)  # 나머지는 그대로 (흰 바탕)
        home = self.client.get('/', base_url=jebo).get_data(as_text=True)
        self.assertIn('home-shots', home); self.assertIn('/shot/' + rows[0]['stored'], home); self.assertNotIn('<strong>사진 제보 4</strong>', home)
        self.assertEqual(self.client.get('/shot/' + rows[0]['stored']).status_code, 200)
        with self.site.conn() as db: db.execute('UPDATE cases SET published=0 WHERE id=?', (rows[1]['case_id'],))
        self.assertEqual(self.client.get('/shot/' + rows[1]['stored']).status_code, 404)  # 비공개로 바뀌면 바로 막힘
        admin = self.login_admin()
        self.assertIn('사진으로 보는 제보', admin.get('/admin/hero-photos').get_data(as_text=True))
        admin.post('/admin/case-shots/%d' % rows[2]['id'], data={'_csrf': self.csrf(admin, '/admin/hero-photos')})
        self.assertEqual(self.client.get('/shot/' + rows[2]['stored']).status_code, 404)
        # 운영자 2026-11-05: 얼굴은 무조건 모자이크 — 얼굴 자리는 굵게, 얼굴이 있다는데 자리를 못 대면 안 씀
        def ai(body):
            with mock.patch.object(case_shots.companydesk, 'ai_key_for', return_value='k'), mock.patch.object(case_shots.companydesk, 'post_json', return_value=(200, {'choices': [{'message': {'content': json.dumps(body)}}]})):
                return case_shots.find_boxes(b'x')
        self.assertEqual(ai({'boxes': [], 'faces': [], 'face_count': 1}), 'face')
        found = ai({'boxes': [], 'faces': [{'x': 0.1, 'y': 0.1, 'w': 0.3, 'h': 0.4}], 'face_count': 1})
        self.assertEqual(len(found['faces']), 1)
        face = Image.new('RGB', (800, 600), 'white'); d = ImageDraw.Draw(face)
        for x in range(0, 800, 4): d.line([(x, 0), (x, 600)], fill='black' if x % 8 else 'red')
        face = Image.open(io.BytesIO(case_shots.make_shot(face, found))).convert('RGB')
        row = [face.getpixel((x, 150)) for x in range(80, 240, 2)]; far = [face.getpixel((x, 420)) for x in range(400, 560, 2)]
        self.assertLess(max(map(sum, row)) - min(map(sum, row)), 90)  # 얼굴 자리는 뭉개짐
        self.assertGreater(max(map(sum, far)) - min(map(sum, far)), 200)  # 나머지 줄무늬는 그대로
        with self.site.conn() as db:
            self.assertEqual(db.execute('SELECT hidden FROM case_shots WHERE id=?', (rows[2]['id'],)).fetchone()[0], 1)
            db.execute('DELETE FROM case_shots')
            for c in cids: db.execute('DELETE FROM attachments WHERE case_id=?', (c,)); db.execute('DELETE FROM hero_photos WHERE case_id=?', (c,)); db.execute('DELETE FROM cases WHERE id=?', (c,))

    def test_howto(self):
        # 운영자 2026-11-04: 분쟁·대응 메뉴 — 글은 미리 만들지 않음. 관리자가 공개한 글이 생기면 메뉴에 보임
        jebo = 'https://consumerjebo.co.kr'
        self.site.JEBO_HOSTS.add('consumerjebo.co.kr'); self.addCleanup(self.site.JEBO_HOSTS.discard, 'consumerjebo.co.kr')
        self.assertNotIn('href="/howto"', self.client.get('/', base_url=jebo).get_data(as_text=True))
        self.assertIn('준비하고 있어요', self.client.get('/howto', base_url=jebo).get_data(as_text=True))
        admin = self.login_admin(); token = self.csrf(admin, '/admin/howto')
        r = admin.post('/admin/howto', data={'_csrf': token}); gid = int(r.headers['Location'].rstrip('/').rsplit('/', 1)[1])
        self.assertEqual(self.client.get('/howto/%d' % gid).status_code, 404)  # 초안은 안 보임
        admin.post('/admin/howto/%d' % gid, data={'_csrf': token, 'act': 'save', 'title': '환불을 안 해 줄 때', 'topic': '환불·반품', 'emoji': '💸', 'status': 'published', 'sort': '1',
                                               'body': '도입이에요.\n\n## 먼저 확인할 것\n- 받은 날짜\n\n## 이렇게 대처해요\n- 캡처 <b>해요</b>'})
        page = self.client.get('/howto/%d' % gid, base_url=jebo).get_data(as_text=True)
        self.assertIn('ck-check', page); self.assertIn('ck-steps', page); self.assertIn('&lt;b&gt;', page)
        home = self.client.get('/', base_url=jebo).get_data(as_text=True)
        self.assertIn('href="/howto"', home); self.assertIn('분쟁·대응', home)
        self.assertIn('환불을 안 해 줄 때', self.client.get('/howto', base_url=jebo).get_data(as_text=True))
        with self.site.conn() as db: db.execute('DELETE FROM howto_guides')

    def test_admin_company_logo_upload(self):
        # 운영자 2026-11-04: 자동으로 못 받은 로고는 관리자 기업 화면에서 직접 올림
        from PIL import Image
        with self.site.conn() as db: cid = db.execute("INSERT INTO companies(name,biz_no,status,contact_name,contact_phone,contact_email,created) VALUES('로고시험','','listed','','','','x')").lastrowid
        admin = self.login_admin(); token = self.csrf(admin, '/admin/companies')
        buf = io.BytesIO(); Image.new('RGBA', (120, 120), (255, 0, 0, 255)).save(buf, 'PNG'); buf.seek(0)
        admin.post('/admin/companies/%d/logo' % cid, data={'_csrf': token, 'logo': (buf, 'l.png')}, content_type='multipart/form-data')
        with self.site.conn() as db: self.assertEqual(db.execute('SELECT logo FROM companies WHERE id=?', (cid,)).fetchone()[0], '%d.png' % cid)
        self.assertEqual(self.client.get('/co/%d/logo.png' % cid).status_code, 200)
        self.assertIn('로고 올리기', admin.get('/admin/companies').get_data(as_text=True))
        with self.site.conn() as db: db.execute('DELETE FROM companies WHERE id=?', (cid,))

    def test_company_typo_fix(self):
        # 운영자 2026-11-03: 큰 기업 이름 오타는 자동으로 (큐팡 → 쿠팡). 헷갈리거나 모르는 이름은 그대로
        import company_fix
        self.assertEqual([company_fix.fix(t) for t in ('큐팡', '쿠팽', '배달의민죡', '쿠팡', '쿠팡이츠', '지마켓', 'MISUKO연발새총 해궁', '카카오페', 'KT')],
                         ['쿠팡', '쿠팡', '배달의민족', '쿠팡', '쿠팡이츠', '지마켓', 'MISUKO연발새총 해궁', '카카오페', 'KT'])
        with self.site.conn() as db:
            cid = db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES('CJ-TYPO','x','배송·환불','큐팡','제목','내용','환불','2026-10-09T10:00:00',1,1)").lastrowid
        company_fix.fix_old_cases(self.site.conn, self.site.link_company)
        with self.site.conn() as db:
            row = db.execute('SELECT c.company,co.name FROM cases c LEFT JOIN companies co ON co.id=c.company_id WHERE c.id=?', (cid,)).fetchone()
        self.assertEqual(tuple(row), ('쿠팡', '쿠팡'))

    def test_company_web_email(self):
        # 운영자 2026-11-03: 기업 공식 홈페이지에서 고객센터·홍보팀 메일을 찾아 연결. 채용·광고·개인정보·noreply·다른 회사 메일은 안 씀
        import company_web_email as w
        page = ('<footer>고객센터 1577-0000 | 이메일 : help@coupang.com <a href="mailto:press@coupangcorp.com">보도자료 문의</a> '
                'recruit@coupang.com privacy@coupang.com noreply@coupang.com ads@coupang.com contact@agency.co.kr logo@2x.png abc@naver.com</footer>')
        self.assertEqual(w.emails_on(page, 'coupang.com'), [('help@coupang.com', 'cs'), ('press@coupangcorp.com', 'pr')])
        with self.site.conn() as db:
            a = db.execute("INSERT INTO companies(name,biz_no,status,contact_name,contact_phone,contact_email,created,domain,official_email,email_source) VALUES('웹몰A','','listed','','','','2026-11-03','weba.com','ftc@weba.com','공정위 통신판매 신고 정보')").lastrowid
            b = db.execute("INSERT INTO companies(name,biz_no,status,contact_name,contact_phone,contact_email,created,domain,official_email,email_source) VALUES('웹몰B','','listed','','','','2026-11-03','webb.com','boss@webb.com','')").lastrowid
        fake = lambda d: ('cs@' + d, 'cs', 'https://' + d + '/help', [('cs@' + d, 'cs', 'https://' + d + '/help'), ('pr@' + d, 'pr', 'https://' + d + '/')])
        w.run(finder=fake, say=lambda *_: None, force=True)
        with self.site.conn() as db:
            ra = db.execute('SELECT official_email,email_source FROM companies WHERE id=?', (a,)).fetchone()
            rb = db.execute('SELECT official_email FROM companies WHERE id=?', (b,)).fetchone()
        self.assertEqual(tuple(ra), ('cs@weba.com', '공식 홈페이지(고객센터)'))
        self.assertEqual(rb['official_email'], 'boss@webb.com')  # 관리자가 넣은 메일은 그대로
        self.assertIn('pr@webb.com(홍보팀)', self.login_admin().get('/admin/companies').get_data(as_text=True))

    def test_explore_hub(self):
        # 운영자 2026-11-03: 메뉴 '전문가' 대신 '둘러보기' 허브 (기업 순위·사기 전에 확인·소보루 자문단·공감 많은 제보)
        self.site.JEBO_HOSTS.add('consumerjebo.co.kr'); self.addCleanup(self.site.JEBO_HOSTS.discard, 'consumerjebo.co.kr')
        page = self.client.get('/explore', base_url='https://consumerjebo.co.kr').get_data(as_text=True)
        for text in ('xh-title', '기업 응대 순위', '사기 전에 확인', '소보루 자문단'):
            self.assertIn(text, page)
        self.assertIn('/explore/tricks', page); self.assertIn('/explore/contact-tips', page)  # 소비자 안내서 주제 카드
        for path, text in (('/explore/tricks', '네거티브 옵션'), ('/explore/contact-tips', '담당자 찾기')):
            body = self.client.get(path).get_data(as_text=True); self.assertIn(text, body); self.assertIn('한국소비자원', body)
        home = self.client.get('/', base_url='https://consumerjebo.co.kr').get_data(as_text=True)
        self.assertIn('href="/explore"', home); self.assertNotIn('>전문가<', home)

    def test_expert_mail_builder(self):
        # 운영자 2026-11-03 (밤): 관리자에서 자문단 섭외 메일을 화면에서 바로 고쳐 저장, 법인 이름은 화면에서 넣음
        adm = self.login_admin()
        page = adm.get('/admin/experts/mail').get_data(as_text=True)
        self.assertIn('○○ 법무법인 귀중', page)
        self.assertIn('https://consumerjebo.co.kr/expert/apply', page)
        self.assertEqual(self.post_form(adm, '/admin/experts/mail', {'act': 'save', 'subject': '새 제목', 'html': '<p onclick="x()">고친 ○○ 법무법인 메일</p><script>bad()</script>'}).status_code, 302)
        page = adm.get('/admin/experts/mail').get_data(as_text=True)
        self.assertIn('고친 ○○ 법무법인 메일', page)
        self.assertIn('새 제목', page)
        self.assertNotIn('bad()', page)
        self.assertNotIn('&lt;p onclick', page)
        self.post_form(adm, '/admin/experts/mail', {'act': 'reset'})
        self.assertIn('창립 자문위원 모집', adm.get('/admin/experts/mail').get_data(as_text=True))
        self.assertIn(self.client.get('/admin/experts/mail').status_code, (302, 401, 403, 404))

    def test_about_and_llms_for_jebo(self):
        # 운영자 2026-11-03 (밤): 네이버 AI 브리핑·AI 검색용 서비스 소개와 llms.txt (제보센터 주소)
        c = self.site.app.test_client()
        hosts = patch.object(self.site, 'JEBO_HOSTS', {'consumerjebo.co.kr'}); hosts.start(); self.addCleanup(hosts.stop)
        page = c.get('/about', base_url='https://consumerjebo.co.kr').get_data(as_text=True)
        self.assertIn('소비자 제보 플랫폼', page); self.assertIn('제보는 이렇게 흘러가요', page); self.assertNotIn('권익', page); self.assertIn('FAQPage', page); self.assertIn('AboutPage', page)
        txt = c.get('/llms.txt', base_url='https://consumerjebo.co.kr').get_data(as_text=True)
        self.assertIn('# 소비자제보센터', txt)
        self.assertIn('/about', c.get('/sitemap.xml', base_url='https://consumerjebo.co.kr').get_data(as_text=True))
        adm = self.login_admin()
        self.assertIn('오늘 방문', adm.get('/admin').get_data(as_text=True))

    def test_expert_signup_alert_mail(self):
        # 운영자 2026-11-03 (밤): 자문단이 가입하면 하이웍스 메일(contact@)로 바로 알림
        import experts as X
        from PIL import Image
        adm = self.login_admin()
        self.post_form(adm, '/admin/experts', {'act': 'invite', 'name': '최변호', 'field': '변호사'})
        with self.site.conn() as db: token = db.execute("SELECT token FROM experts WHERE name='최변호'").fetchone()[0]
        class Now:
            def __init__(self, target, daemon=None): self.t = target
            def start(self): self.t()
        sent = []
        pic = io.BytesIO(); Image.new('RGB', (300, 300), 'blue').save(pic, 'JPEG'); pic.seek(0)
        with patch.object(self.site.notify, 'email_ready', lambda: True), patch.object(self.site.notify, 'send_email', lambda to, subj, body, **k: sent.append((to, subj, body))), patch.object(X.threading, 'Thread', Now):
            pro = self.site.app.test_client()
            self.post_form(pro, '/expert/join/' + token, {'name': '최변호', 'field': '변호사', 'email': 'choi@x.kr', 'agree': '1',
                                                          'proof': (io.BytesIO(b'%PDF-1.4 t'), 'l.pdf'), 'photo': (pic, 'me.jpg')})
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], 'contact@consumerjebo.co.kr')
        self.assertIn('최변호', sent[0][1]); self.assertIn('choi@x.kr', sent[0][2])

    def test_expert_invite(self):
        # 운영자 2026-11-03: 흑묘 도우미단처럼 제보자가 자문단을 불러요 (기업 답변이 있거나 기한이 지난 제보, 3명까지)
        from PIL import Image
        adm = self.login_admin()
        self.post_form(adm, '/admin/experts', {'act': 'invite', 'name': '박변호', 'field': '변호사'})
        with self.site.conn() as db: token = db.execute("SELECT token FROM experts WHERE name='박변호'").fetchone()[0]
        pro, pid = self.member_client('pro_park', '박변')
        pic = io.BytesIO(); Image.new('RGB', (300, 300), 'blue').save(pic, 'JPEG'); pic.seek(0)
        self.assertEqual(self.post_form(pro, '/expert/join/' + token, {'name': '박변호', 'field': '변호사', 'email': 'park@x.kr', 'agree': '1',
                                                                       'proof': (io.BytesIO(b'%PDF-1.4 t'), 'l.pdf'), 'photo': (pic, 'me.jpg')}).status_code, 302)
        owner, oid = self.member_client('inv_owner', '제보자')
        with self.site.conn() as db:
            eid = db.execute("SELECT id FROM experts WHERE name='박변호'").fetchone()[0]
            db.execute('UPDATE experts SET user_id=? WHERE id=?', (pid, eid))
            cid = db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published,user_id) VALUES('CJ-INV','x','배송·환불','가게','제목','내용','환불',?,1,1,?)", (datetime.datetime.now().isoformat(timespec='seconds'), oid)).lastrowid
        self.site.JEBO_HOSTS.add('localhost'); self.addCleanup(self.site.JEBO_HOSTS.discard, 'localhost')
        page = owner.get('/reports/%d' % cid).get_data(as_text=True)
        self.assertIn('id="invite"', page); self.assertNotIn('pc-inv-form', page)  # 기업 답 전에는 안내만
        self.assertNotIn('id="invite"', self.client.get('/reports/%d' % cid).get_data(as_text=True))  # 남에게는 안 보임
        with self.site.conn() as db: db.execute("INSERT INTO messages(case_id,author,body,created,public) VALUES(?,'기업 답변','확인해 볼게요.',?,1)", (cid, datetime.datetime.now().isoformat(timespec='seconds')))
        page = owner.get('/reports/%d' % cid).get_data(as_text=True)
        self.assertIn('pc-inv-form', page); self.assertIn('박변호', page)
        sent = []
        with patch.object(self.site.notify, 'send_email', lambda to, subj, body, **k: sent.append((to, subj, body))):
            t = self.csrf(owner, '/reports/%d' % cid)
            self.assertEqual(owner.post('/reports/%d/invite-expert' % cid, data={'_csrf': t, 'expert': eid, 'reason': '짧음'}).status_code, 302)
            with self.site.conn() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM expert_invites').fetchone()[0], 0)
            owner.post('/reports/%d/invite-expert' % cid, data={'_csrf': t, 'expert': eid, 'reason': '기업 답변이 맞는지 궁금해요.'})
            with self.site.conn() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM expert_invites WHERE case_id=?', (cid,)).fetchone()[0], 1)
            self.assertTrue(any(x[0] == 'park@x.kr' for x in sent))
            self.assertIn('요청함', owner.get('/reports/%d' % cid).get_data(as_text=True))
            t2 = self.csrf(pro, '/reports/%d' % cid)
            pro.post('/reports/%d/comment' % cid, data={'_csrf': t2, 'body': '청약철회 기간을 먼저 확인해 보세요.'})
        with self.site.conn() as db: self.assertTrue(db.execute('SELECT answered FROM expert_invites WHERE case_id=?', (cid,)).fetchone()[0])
        self.assertIn('의견 도착', owner.get('/reports/%d' % cid).get_data(as_text=True))

    def test_soboru_host_retired(self):
        # 운영자 2026-11-04: soboru.co.kr은 막고 전부 consumerjebo.co.kr로
        r = self.client.get('/reports?tab=new', base_url='https://www.soboru.co.kr')
        self.assertEqual(r.status_code, 301); self.assertEqual(r.headers['Location'], 'https://consumerjebo.co.kr/reports?tab=new')
        # 운영자 2026-11-05: 매거진 검색 노출 — soboru.co.kr/ 이 매거진 첫 화면 그대로, /letter는 / 로
        self.assertIn('class="lt-top nm-top"', self.client.get('/', base_url='https://soboru.co.kr').get_data(as_text=True))
        self.assertEqual(self.client.get('/letter', base_url='https://soboru.co.kr').headers['Location'], '/')
        # 운영자 2026-11-05: 제보센터 주소의 레터는 매거진으로 (같은 글이 두 주소에 뜨지 않게), 제보센터 사이트맵·RSS에도 매거진 글 없음
        self.assertEqual(self.client.get('/letter?v=1', base_url='https://consumerjebo.co.kr').headers['Location'], 'https://soboru.co.kr/letter?v=1')
        jmap = self.client.get('/sitemap.xml', base_url='https://consumerjebo.co.kr').get_data(as_text=True)
        self.assertNotIn('/life', jmap); self.assertNotIn('/letter', jmap); self.assertIn('https://consumerjebo.co.kr/reports', jmap)
        self.assertNotIn('/life/', self.client.get('/rss.xml', base_url='https://consumerjebo.co.kr').get_data(as_text=True))
        for base in ('https://soboru.co.kr', 'https://letter.soboru.co.kr'):
            page = self.client.get('/letter?v=1', base_url=base).get_data(as_text=True)
            self.assertIn('class="lt-top nm-top"', page, base)  # 매거진 머리 (귤색 띠 + 영문 메뉴, 운영자 2026-11-04)
            self.assertNotIn('site-footer', page, base)  # 바닥글 없음
            self.assertNotIn('sb-tabbar', page, base); self.assertNotIn('jebo_header', page, base); self.assertNotIn('class="sb-nav"', page, base)
        self.assertEqual(self.client.get('/', base_url='https://letter.soboru.co.kr').status_code, 200)
        self.assertEqual(self.client.get('/letter', base_url='https://letter.soboru.co.kr').headers['Location'], '/')
        self.assertEqual(self.client.get('/reports', base_url='https://letter.soboru.co.kr').headers['Location'], 'https://consumerjebo.co.kr/reports')
        self.assertNotEqual(self.site.CANONICAL_HOST, 'soboru.co.kr')

    def test_experts(self):
        # 운영자 2026-11-03: 전문가를 한 명씩 가입시키기. 초대 링크로 들어오면 바로 전문가, 직접 신청은 관리자 승인 뒤. 댓글에 전문가 표시
        adm = self.login_admin()
        self.assertEqual(self.post_form(adm, '/admin/experts', {'act': 'invite', 'name': '김변호', 'field': '변호사', 'org': '소보루 법률사무소'}).status_code, 302)
        with self.site.conn() as db: token = db.execute("SELECT token FROM experts WHERE name='김변호'").fetchone()[0]
        self.assertIn('/expert/join/' + token, adm.get('/admin/experts').get_data(as_text=True))
        # 운영자 2026-11-03: 초대 링크 = 토스플레이스 풍 한 화면, 로그인 없이 입력하고 바로 등록. 자격은 파일로만
        page = self.client.get('/expert/join/' + token).get_data(as_text=True)
        self.assertIn('xf-form', page); self.assertIn('김변호 님', page); self.assertIn('value="소보루 법률사무소"', page); self.assertNotIn('license_no', page); self.assertNotIn('name="proof"', page)
        pdf = lambda: (io.BytesIO(b'%PDF-1.4 test'), 'license.pdf')
        self.assertEqual(self.post_form(self.client, '/expert/join/' + token, {'name': '김변호', 'field': '변호사', 'email': 'kim@x.kr', 'agree': '1'}).status_code, 200)  # 프로필 사진 없으면 다시 (초대는 자격 파일 없이 됨)
        from PIL import Image
        pic = io.BytesIO(); Image.new('RGB', (600, 300), 'blue').save(pic, 'JPEG'); pic.seek(0)
        guest = self.site.app.test_client()
        r = self.post_form(guest, '/expert/join/' + token, {'name': '김변호', 'field': '변호사', 'email': 'kim@x.kr', 'agree': '1', 'photo': (pic, 'me.jpg')})
        self.assertEqual(r.status_code, 302)
        done = guest.get(r.headers['Location']).get_data(as_text=True)
        # 운영자 2026-11-04: 등록하면 자문단 회원 계정이 바로 생기고 로그인됨 (따로 로그인·잇기 없음)
        self.assertIn('자문단 계정이 만들어졌어요', done); self.assertNotIn('/expert/claim/', done)
        self.assertEqual(guest.get('/expert/join/' + token).status_code, 404)  # 링크는 한 번만
        pro = guest
        self.assertIn('자문단 · 변호사', pro.get('/expert/apply').get_data(as_text=True))
        with self.site.conn() as db: self.assertEqual(db.execute("SELECT u.nickname FROM experts e JOIN users u ON u.id=e.user_id WHERE e.name='김변호'").fetchone()[0], '김변호')
        # 운영자 2026-11-04: 등록증은 받지 않음. 섭외 메일 링크(?k=)로 온 사람은 사진만 넣으면 바로 자문단
        import experts as ex
        key = ex.mail_key(self.site.app.secret_key)
        mailer = self.site.app.test_client()
        mp = mailer.get('/expert/apply?k=' + key).get_data(as_text=True)
        self.assertNotIn('name="proof"', mp); self.assertNotIn('name="proof"', mailer.get('/expert/apply').get_data(as_text=True))
        pic3 = io.BytesIO(); Image.new('RGB', (300, 300), 'green').save(pic3, 'JPEG'); pic3.seek(0)
        self.assertEqual(self.post_form(mailer, '/expert/apply?k=' + key, {'name': '홍메일', 'field': '변호사', 'agree': '1', 'phone': '010-2222-3333', 'email': 'hong@x.kr', 'photo': (pic3, 'me.jpg')}).status_code, 302)
        with self.site.conn() as db:
            self.assertEqual(db.execute("SELECT status FROM experts WHERE name='홍메일'").fetchone()[0], 'approved')
            db.execute("UPDATE users SET ip_hash='' WHERE id=(SELECT user_id FROM experts WHERE name='홍메일')")  # 테스트 안 가입 횟수 제한(시간당 3명)에 걸리지 않게
        self.assertIn('/expert/apply?k=' + key, adm.get('/admin/experts/mail').get_data(as_text=True))
        # 운영자 2026-11-04: 자동으로 만든 자문단 계정은 같은 이메일의 카카오로 처음 들어오면 그 계정으로 이어짐 (휴대폰 로그인 대신)
        with patch.dict(os.environ, {'KAKAO_REST_API_KEY': 'rest-key', 'KAKAO_CLIENT_SECRET': 'shh'}):
            again = self.site.app.test_client()
            _, fake = self.kakao_fake(uid='7777', email='hong@x.kr', nickname='홍카카오')
            self.assertEqual(self.social_round(again, fake).status_code, 302)
            with self.site.conn() as db:
                uid = db.execute("SELECT user_id FROM experts WHERE name='홍메일'").fetchone()[0]
                self.assertEqual(db.execute("SELECT user_id FROM user_identities WHERE provider_uid='7777'").fetchone()[0], uid)
        # 직접 신청은 승인 전까지 표시 없음
        other, oid = self.member_client('pro_lee', '이사정')
        self.assertEqual(self.post_form(other, '/expert/apply', {'name': '이사정', 'field': '교수', 'agree': '1', 'phone': '010-1234-5678',
                                                                 'proof': (io.BytesIO(b'%PDF-1.4 test'), 'license.pdf')}).status_code, 200)  # 운영자 2026-11-03: 신뢰를 위해 프로필 사진 필수
        pic2 = io.BytesIO(); Image.new('RGB', (300, 300), 'red').save(pic2, 'JPEG'); pic2.seek(0)
        self.assertEqual(self.post_form(other, '/expert/apply', {'name': '이사정', 'field': '교수', 'agree': '1', 'phone': '010-1234-5678',
                                                                 'proof': (io.BytesIO(b'%PDF-1.4 test'), 'license.pdf'), 'photo': (pic2, 'me.jpg')}).status_code, 302)
        with self.site.conn() as db:
            row = db.execute('SELECT id,status,proof FROM experts WHERE user_id=?', (oid,)).fetchone()
            cid = db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES('CJ-PRO','x','배송·환불','가게','제목','내용','환불','2026-10-09T10:00:00',1,1)").lastrowid
        self.assertEqual(row['status'], 'pending'); self.assertTrue(row['proof'].endswith('.pdf'))
        self.assertEqual(self.client.get('/admin/experts/%d/proof' % row['id']).status_code, 302)  # 자격증은 관리자만
        self.assertEqual(adm.get('/admin/experts/%d/proof' % row['id']).status_code, 200)
        for c, body in ((pro, '청약철회 기간을 확인해 보세요.'), (other, '보험 처리가 될 수 있어요.')):
            token2 = self.csrf(c, '/reports/%d' % cid)
            self.assertEqual(c.post('/reports/%d/comment' % cid, data={'_csrf': token2, 'body': body}).status_code, 302)
        page = self.client.get('/reports/%d' % cid).get_data(as_text=True)
        self.assertIn('자문단 · 변호사', page); self.assertNotIn('자문단 · 교수', page)
        photo = re.search(r'src="(/expert/\d+/photo\.jpg[^"]*)"', page)[1]
        self.assertEqual(Image.open(io.BytesIO(self.client.get(photo).data)).size, (400, 400))  # 정사각형으로 잘라서
        self.assertEqual(self.post_form(adm, '/admin/experts', {'act': 'approve', 'id': row['id']}).status_code, 302)
        self.assertIn('자문단 · 교수', self.client.get('/reports/%d' % cid).get_data(as_text=True))
        # 운영자 2026-11-03: 자문단을 누르면 소개 페이지(이력·상담 신청). 승인 전·멈춘 자문단은 안 보임. 상담 신청은 회원만, 돈은 안 받음
        self.assertEqual(self.client.get('/experts/%d' % row['id']).status_code, 200)
        self.assertIn('/experts/%d' % row['id'], self.client.get('/explore').get_data(as_text=True))
        self.assertEqual(self.client.post('/experts/%d/ask' % row['id'], data={'_csrf': 'x', 'body': '환불 문제로 상담하고 싶어요.'}).status_code in (302, 400), True)
        asker = pro
        t = self.csrf(asker, '/experts/%d' % row['id'])
        self.assertEqual(asker.post('/experts/%d/ask' % row['id'], data={'_csrf': t, 'body': '환불을 3주째 못 받고 있어요. 상담하고 싶어요.', 'contact': '010-0000-1111'}).status_code, 302)
        with self.site.conn() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM expert_requests WHERE expert_id=?', (row['id'],)).fetchone()[0], 1)
        self.assertIn('환불을 3주째', other.get('/expert/apply').get_data(as_text=True))
        # 운영자 2026-11-03: 새 제보를 자문단에게 하루 한 번 메일로 (공개 제보만, 알림 끄면 안 감)
        page = other.get('/expert/apply').get_data(as_text=True)
        self.assertIn('의견을 기다리는 제보', page)
        sent = []
        with patch.object(self.site.notify, 'send_email', lambda to, subj, body, **k: sent.append((to, subj, body))):
            with self.site.app.app_context():
                with self.site.conn() as db: db.execute("UPDATE experts SET email='lee@x.kr' WHERE id=?", (row['id'],)); db.execute("DELETE FROM admin_settings WHERE key='expert_digest_last'")
                self.site.app.extensions['experts_digest'](now_iso='2026-10-09T20:00:00')
        self.assertTrue(any(t == 'lee@x.kr' and '/reports/%d' % cid in b for t, _, b in sent))
        t = self.csrf(other, '/expert/apply'); other.post('/expert/digest', data={'_csrf': t, 'on': '0'})
        with self.site.conn() as db: self.assertEqual(db.execute('SELECT digest FROM experts WHERE id=?', (row['id'],)).fetchone()[0], 0)
        # 법무법인 같은 사무소·법인도 등록 (전문 기관 표시)
        firm, fid = self.member_client('firm_sb', '법무법인소보루')
        self.assertEqual(self.post_form(adm, '/admin/experts', {'act': 'invite', 'name': '법무법인 소보루', 'field': '법무법인'}).status_code, 302)
        with self.site.conn() as db: ft = db.execute("SELECT token,kind FROM experts WHERE name='법무법인 소보루'").fetchone()
        self.assertEqual(ft['kind'], 'firm')
        self.assertEqual(self.post_form(firm, '/expert/join/' + ft['token'], {'kind': 'firm', 'name': '법무법인 소보루', 'field': '법무법인', 'email': 'law@x.kr', 'agree': '1', 'proof': pdf()}).status_code, 302)
        token3 = self.csrf(firm, '/reports/%d' % cid)
        firm.post('/reports/%d/comment' % cid, data={'_csrf': token3, 'body': '소비자 분쟁 상담을 돕고 있어요.'})
        self.assertIn('자문단 · 법무법인', self.client.get('/reports/%d' % cid).get_data(as_text=True))
        with self.site.conn() as db: kim = db.execute("SELECT id FROM experts WHERE name='김변호'").fetchone()[0]
        self.post_form(adm, '/admin/experts', {'act': 'stop', 'id': kim})
        self.assertNotIn('자문단 · 변호사', self.client.get('/reports/%d' % cid).get_data(as_text=True))
        self.assertEqual(self.client.get(photo).status_code, 404)  # 멈추면 사진도 안 보임

    def test_report_talk_ai_draft(self):
        # 대화로 제보하기 (운영자 2026-11-03): AI가 되물을 것과 초안을 주고, 업종·유형은 목록 안에서만, 개인정보는 지움. 접수는 기존 /report로
        page = self.client.get('/report/talk').get_data(as_text=True)
        self.assertIn('id="tk-log"', page); self.assertIn('action="/report"', page); self.assertIn('name="truth"', page)
        token = self.csrf(self.client, '/report/talk')
        seen = []
        def fake(url, headers, body, timeout):
            seen.append(body)
            out = {'summary': '환불 거절 건이시죠?', 'industry': '쇼핑', 'category': '배송·교환·환불', 'company': '하루몰', 'occurred_on': '2999-01-01',
                   'subject': '환불이 안 돼요', 'description': '연락처 010-1234-5678로 문자했어요.', 'request_text': '환불', 'request_options': ['전액 환불'],
                   'questions': [{'q': '업체에 연락해 보셨나요?', 'options': ['네', '아니요']}, {'q': 'a'}, {'q': 'b'}]}
            return 200, {'choices': [{'message': {'content': json.dumps(out, ensure_ascii=False)}}]}
        photo = io.BytesIO(b'\xff\xd8\xff' + b'0' * 100)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test'}), patch.object(self.site.companydesk, 'post_json', fake):
            r = self.client.post('/report/talk/ai', data={'_csrf': token, 'story': '운동화 반품했는데 환불이 안 돼요', 'qa': '[]', 'photo': (photo, 'a.jpg')}, content_type='multipart/form-data')
        d = r.get_json()['draft']
        self.assertEqual((d['industry'], d['category'], d['occurred_on']), ('쇼핑·유통', '배송·교환·환불', ''))
        self.assertNotIn('010-1234-5678', d['description']); self.assertEqual(len(d['questions']), 2)
        self.assertEqual(seen[0]['model'], 'gpt-6-luna'); self.assertEqual(seen[0]['messages'][1]['content'][1]['type'], 'image_url')
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            self.assertEqual(self.client.post('/report/talk/ai', data={'_csrf': token, 'story': '환불이 안 돼요'}).get_json(), {'ok': False, 'error': 'ai'})
        self.assertEqual(self.client.post('/report/talk/ai', data={'_csrf': token, 'story': ''}).status_code, 400)
        # 운영자 2026-11-03 (밤): 두 번째부터는 사진 없이 정리된 정보 + 최근 대화 4개만
        qa = json.dumps([{'q': 'q%d' % i, 'a': 'a%d' % i} for i in range(8)])
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test'}), patch.object(self.site.companydesk, 'post_json', fake):
            self.client.post('/report/talk/ai', data={'_csrf': token, 'story': '환불이 안 돼요', 'qa': qa, 'known': json.dumps({'company': '하루몰', 'description': '사진 속 운동화가 찢어져 있었어요.'}, ensure_ascii=False),
                                                      'photo': (io.BytesIO(b'\xff\xd8\xff' + b'0' * 100), 'a.jpg')}, content_type='multipart/form-data')
        content = seen[-1]['messages'][1]['content']
        self.assertEqual(len(content), 1); text = content[0]['text']
        self.assertIn('[지금까지 정리된 정보]', text); self.assertIn('업체: 하루몰', text); self.assertIn('q7', text); self.assertNotIn('q3', text)

    def test_ai_usage_by_feature(self):
        # 운영자 2026-11-03: 기능별 호출 횟수·토큰 기록, 기능 전용 키
        desk = self.site.companydesk; heads = []
        with self.site.conn() as db: db.execute('DELETE FROM ai_usage')
        def raw(url, headers, body, timeout):
            heads.append(headers['Authorization'])
            return 200, {'choices': [{'message': {'content': '{"summary": "x", "questions": []}'}}], 'usage': {'prompt_tokens': 120, 'completion_tokens': 30, 'prompt_tokens_details': {'cached_tokens': 100}}}
        token = self.csrf(self.client, '/report/talk')
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-main', 'OPENAI_API_KEY_REPORT_TALK': 'sk-talk'}), patch.object(desk, '_post_json', raw):
            self.client.post('/report/talk/ai', data={'_csrf': token, 'story': '환불이 안 돼요'})
        self.assertEqual(heads, ['Bearer sk-talk'])
        with self.site.conn() as db: row = db.execute("SELECT * FROM ai_usage WHERE feature='report_talk'").fetchone()
        self.assertEqual((row['calls'], row['prompt'], row['cached'], row['completion']), (1, 120, 100, 30))
        page = self.login_admin().get('/admin/ai-usage').get_data(as_text=True)
        self.assertIn('AI 대화 제보', page); self.assertIn('OPENAI_API_KEY_REPORT_TALK', page)

    def test_phone_start_signup_and_login(self):
        # 운영자 2026-11-03 (밤): 카카오 아니면 휴대폰 번호(문자 인증). 닉네임 비우면 자동, 같은 번호로 다시 오면 로그인
        sent = []
        with patch.dict(os.environ, {'PHONE_AUTH_TEST': '1'}), patch.object(self.site.phoneauth.bizmsg, 'keys_ready', lambda: True), \
             patch.object(self.site.phoneauth.bizmsg, 'sms', lambda ph, text: sent.append((ph, text))):
            self.assertIn('휴대폰 번호로 시작하기', self.client.get('/login').get_data(as_text=True))
            token = self.csrf(self.client, '/start/phone')
            self.client.post('/start/phone', data={'_csrf': token, 'step': 'phone', 'phone': '010-2222-3333'})
            code = re.search(r'인증번호 (\d{6})', sent[-1][1]).group(1)
            bad = self.client.post('/start/phone', data={'_csrf': token, 'step': 'code', 'code': '000000' if code != '000000' else '111111'})
            self.assertEqual(bad.status_code, 400)
            self.client.post('/start/phone', data={'_csrf': token, 'step': 'code', 'code': code})
            r = self.client.post('/start/phone', data={'_csrf': token, 'step': 'join', 'nickname': '', 'agree_terms': '1', 'agree_privacy': '1', 'agree_age': '1'})
            self.assertEqual(r.status_code, 302)
            with self.site.conn() as db: u = db.execute("SELECT * FROM users WHERE phone_verified='010-2222-3333'").fetchone()
            self.assertIn('소보루', u['nickname']); self.assertEqual(u['pw_hash'], '')
            other = self.site.app.test_client(); token = self.csrf(other, '/start/phone')
            other.post('/start/phone', data={'_csrf': token, 'step': 'phone', 'phone': '01022223333'})
            code = re.search(r'인증번호 (\d{6})', sent[-1][1]).group(1)
            other.post('/start/phone', data={'_csrf': token, 'step': 'code', 'code': code})
            self.assertIn(u['nickname'], other.get('/me').get_data(as_text=True))

    def test_reports_tabs_and_tools_page(self):
        # 운영자 2026-11-03: 목록 탭에 공감·댓글 많은 순, 계산기는 제보센터에서도 토스 스타일 CSS
        html = self.client.get('/reports?sort=talk', base_url='https://consumerjebo.co.kr').get_data(as_text=True)
        self.assertIn('댓글 많은 순', html); self.assertIn('공감 많은 순', html)
        tools = self.client.get('/tools', base_url='https://consumerjebo.co.kr').get_data(as_text=True)
        self.assertIn('class="tl-card"', tools)
        self.assertNotIn('제보하기 →', self.client.get('/', base_url='https://consumerjebo.co.kr').get_data(as_text=True))

    def test_explore_sample_advisors(self):
        # 운영자 2026-11-03 (밤): 자문단이 적으면 '예시' 표시를 단 예시 카드로 채움
        self.site.JEBO_HOSTS.add('localhost')
        try:
            with self.site.conn() as db: db.execute("DELETE FROM experts")
            page = self.client.get('/explore').get_data(as_text=True)
        finally: self.site.JEBO_HOSTS.discard('localhost')
        self.assertEqual(page.count('class="xs-sample"'), 4); self.assertIn('김서연', page)

    def test_report_talk_speech_to_text(self):
        # 말로 입력 (운영자 2026-11-03): 네이버 앱 등은 브라우저 받아쓰기가 안 돼서 녹음 파일을 서버에서 글로 바꿈
        page = self.client.get('/report/talk').get_data(as_text=True)
        self.assertIn('/report/talk/stt', page); self.assertIn('tk-guide', page)
        token = self.csrf(self.client, '/report/talk')
        sent = []
        class Res:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s): return json.dumps({'text': ' 소보루몰에서  운동화를 샀어요 '}).encode()
        def fake(req, timeout):
            sent.append(req); return Res()
        audio = lambda: (io.BytesIO(b'0' * 2000), 'voice.webm')
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test'}), patch('urllib.request.urlopen', fake):
            r = self.client.post('/report/talk/stt', data={'_csrf': token, 'audio': audio()}, content_type='multipart/form-data')
        self.assertEqual(r.get_json(), {'ok': True, 'text': '소보루몰에서 운동화를 샀어요'})
        self.assertIn(b'name="language"', sent[0].data); self.assertIn(b'filename="voice.webm"', sent[0].data)
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            self.assertEqual(self.client.post('/report/talk/stt', data={'_csrf': token, 'audio': audio()}, content_type='multipart/form-data').get_json(), {'ok': False, 'error': 'ai'})
        self.assertEqual(self.client.post('/report/talk/stt', data={'_csrf': token, 'audio': (io.BytesIO(b'0'), 'v.webm')}, content_type='multipart/form-data').status_code, 400)

    def test_submission_lookup_admin_and_company_response(self):
        token = self.csrf(self.client, '/report')
        self.assertEqual(self.client.post('/report', data={'_csrf': token}).status_code, 400)
        # Validation errors must still offer an enabled submit button.
        invalid = self.client.post('/report', data={'_csrf': token}).get_data(as_text=True)
        self.assertNotIn('disabled title="현재 접수 준비 중"', invalid)
        response = self.client.post('/report', data={
            '_csrf': token, 'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '테스트 업체',
            'subject': '테스트 환불 요청', 'description': '테스트 내용',
            'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': '환불 요청', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'use_consent': 'on', 'visibility': 'public',
            'share_company': 'on',
        })
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('제보를 접수했어요.', html)
        receipt = re.search(r'CJ-\d{6}-[A-F0-9]+', html)[0]
        self.assertNotIn('조회 코드는 다시 표시되지 않습니다', html)
        token = self.csrf(self.client, '/lookup')
        wrong = self.client.post('/lookup', data={'_csrf': token, 'mode': 'phone', 'phone': '01012345678', 'password': '9999'})
        self.assertEqual(wrong.status_code, 401)
        # 하이픈 없이 넣어도 같은 번호로 찾음
        response = self.client.post('/lookup', data={'_csrf': token, 'mode': 'phone', 'phone': '01012345678', 'password': '1234'}, follow_redirects=True)
        self.assertIn('테스트 환불 요청', response.get_data(as_text=True))
        self.assertIn('aria-current="step"', response.get_data(as_text=True))
        self.assertIn('<p class="vcs-co-top">테스트 업체</p>', self.client.get('/reports').get_data(as_text=True))  # 운영자 2026-11-04: 목록 카드는 업체 이름만 (업종·유형 뺌)
        self.assertIn('현재 단계: 접수', response.get_data(as_text=True))
        admin = self.site.app.test_client()
        token = self.csrf(admin, '/admin/login')
        response = admin.post('/admin/login', data={'_csrf': token, 'password': self.password}, follow_redirects=True)
        self.assertIn('ch-mag', response.get_data(as_text=True))  # 먼저 어디를 관리할지 고름
        self.assertIn('관리자 홈', admin.get('/admin').get_data(as_text=True))
        with self.site.conn() as db:
            case_id = db.execute('SELECT id FROM cases WHERE receipt=?', (receipt,)).fetchone()['id']
        path = '/admin/reports/' + str(case_id)
        token = self.csrf(admin, path)
        response = admin.post(path, data={'_csrf': token, 'status': '검토 중', 'published': 'on'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('테스트 환불 요청', self.client.get('/').get_data(as_text=True))
        response = admin.post('/admin/invite/' + str(case_id), data={'_csrf': token})
        invite = re.search(r'<strong>(http://localhost/company/[^<]+)</strong>', response.get_data(as_text=True))[1]
        company = self.site.app.test_client()
        path = invite.removeprefix('http://localhost')
        token = self.csrf(company, path)
        response = company.post(path, data={'_csrf': token, 'response': '테스트 기업 답변'}, follow_redirects=True)
        self.assertIn('테스트 기업 답변', response.get_data(as_text=True))
        self.assertIn('답변을 보냈어요', response.get_data(as_text=True))  # 1회용: 한 번 보내면 링크가 닫힘 (OH 2026-11-06)
        self.assertNotIn('name="response"', response.get_data(as_text=True))
        company.post(path, data={'_csrf': token, 'response': '두 번째 답변'})
        with self.site.conn() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages WHERE case_id=? AND author='기업 답변'", (case_id,)).fetchone()[0], 1)
        self.assertIn('답변 받음, 링크 닫힘', admin.get('/admin/reports/' + str(case_id)).get_data(as_text=True))
        again = admin.post('/admin/invite/' + str(case_id), data={'_csrf': self.csrf(admin, '/admin/reports/' + str(case_id))})
        fresh = re.search(r'<strong>http://localhost(/company/[^<]+)</strong>', again.get_data(as_text=True))[1]
        self.assertIn('name="response"', company.get(fresh).get_data(as_text=True))  # 다시 만들면 새 링크로 또 답변 가능
        with self.site.conn() as db:  # AI 입장 요청서 정리가 있으면 기업 답변 페이지 위에 보여 주고 원문은 접어 둠
            db.execute("INSERT INTO company_requests(case_id,version,facts,origin,created) VALUES(?,99,?,'ai','x')", (case_id, json.dumps({'paragraphs': ['제보자에 따르면 환불이 늦어지고 있다고 합니다.'], 'demands': '환불', 'questions': ['환불 처리 일정을 알려 주시기 바랍니다.'], 'product': '확인 필요'}, ensure_ascii=False)))
        page = company.get(fresh).get_data(as_text=True)
        for text in ('AI가 제보 내용을 정리했어요', '제보자에 따르면 환불이 늦어지고', '환불 처리 일정을', '제보자가 쓴 원문 보기'):
            self.assertIn(text, page)
        self.assertNotIn('확인 필요', page)
        self.assertEqual(company.get(path).status_code, 404)  # 예전 링크는 안 열림

    def login_admin(self):
        admin = self.site.app.test_client()
        token = self.csrf(admin, '/admin/login')
        admin.post('/admin/login', data={'_csrf': token, 'password': self.password})
        return admin

    def test_soboru_brand_switch_and_life(self):
        self.enterContext(patch.object(self.site, 'RETIRED_HOSTS', set()))  # 예전 두 사이트 운영 때의 동작 확인 (지금 soboru.co.kr은 막혀 있음)
        # 소보루 하나만: 설정 없이도 방문자·관리자 모두 소보루 화면 (예전 ?brand= 미리보기는 뺌)
        self.assertIn('sb-header', self.client.get('/').get_data(as_text=True))
        admin = self.login_admin()
        page = admin.get('/?brand=off').get_data(as_text=True)
        self.assertIn('sb-header', page)
        self.assertNotIn('미리보기 중', page)
        self.assertIn('<title>소보루(SOBORU) - 소비자 제보·내돈내산 후기·소비 생활 매거진</title>', page)
        self.assertIn('<meta name="description" content="소비자 피해 제보부터 제품·업체 리뷰와 추천, 소비자 권리 안내까지. 소비자의 경험을 나누는 소비자 정보 플랫폼, 소보루.">', page)
        # 네이버 기준: 화면마다 다른 제목·설명, 화면 종류별 공유 그림, 개인 화면은 검색 제외
        board = admin.get('/board').get_data(as_text=True)
        self.assertIn('<title>제품·업체 리뷰와 추천 | 소보루</title>', board)
        self.assertIn('static/soboru-og-pick.png', board)
        self.assertIn('<meta name="twitter:image" content="http://localhost/static/soboru-og-pick.png', board)
        self.assertIn('<title>소비자 피해 제보하기 | 소보루</title>', admin.get('/report').get_data(as_text=True))
        self.assertIn('<title>자주 묻는 질문 | 소보루</title>', admin.get('/faq').get_data(as_text=True))
        self.assertIn('<meta name="robots" content="noindex,nofollow">', admin.get('/lookup').get_data(as_text=True))
        self.assertIn('User-agent: Yeti', self.client.get('/robots.txt').get_data(as_text=True))
        self.assertEqual(self.client.get('/reports?page=999').status_code, 404)  # 없는 쪽은 소프트 404 대신 404
        self.assertIn('<meta name="robots" content="noindex,follow">', admin.get('/board?type=review').get_data(as_text=True))
        self.assertIn('<meta property="og:image" content="http://localhost/static/soboru-og.png', page)
        self.assertIn('"alternateName": ["SOBORU", ', page)  # 구조화 데이터 (한글은 \u 꼴로 들어감)
        # 운영 도메인으로 들어오면(http여도) canonical·og:url·사이트맵이 https://consumerjebo.co.kr 로 통일
        prod = self.client.get('/', base_url='http://consumerjebo.co.kr').get_data(as_text=True)
        self.assertIn('<link rel="canonical" href="https://consumerjebo.co.kr/">', prod)
        self.assertIn('<meta property="og:url" content="https://consumerjebo.co.kr/">', prod)
        self.assertIn('<loc>https://consumerjebo.co.kr/</loc>', self.client.get('/sitemap.xml', base_url='http://consumerjebo.co.kr').get_data(as_text=True))
        self.assertIn('Sitemap: https://consumerjebo.co.kr/sitemap.xml', self.client.get('/robots.txt', base_url='http://consumerjebo.co.kr').get_data(as_text=True))
        # soboru.co.kr로 들어와도 같은 사이트, 대표 주소는 CANONICAL_HOST(기본 consumerjebo.co.kr)
        self.assertIn('<link rel="canonical" href="https://consumerjebo.co.kr/">', self.client.get('/', base_url='https://soboru.co.kr').get_data(as_text=True))
        self.assertEqual(self.client.get('/letter', base_url='http://www.soboru.co.kr').headers['Location'], 'https://soboru.co.kr/letter')
        # 생활정보: 초안은 관리자만, 게시하면 누구나
        r = admin.post('/admin/life', data={'_csrf': self.csrf(admin, '/admin/life'), 'title': '택배 분실 보상 정리', 'summary': '요약', 'body': '첫 문단\n\n## 소제목\n- 목록', 'category': '쇼핑', 'emoji': '📦', 'tone': 't1'})
        aid = int(r.headers['Location'].rstrip('/').split('/')[-1])
        visitor = self.site.app.test_client()
        self.assertEqual(visitor.get(f'/life/{aid}').status_code, 404)
        self.assertNotIn('택배 분실 보상 정리', visitor.get('/life').get_data(as_text=True))
        admin.post(f'/admin/life/{aid}', data={'_csrf': self.csrf(admin, f'/admin/life/{aid}'), 'act': 'publish', 'title': '택배 분실 보상 정리', 'summary': '요약', 'body': '첫 문단\n\n## 소제목\n- 목록', 'category': '쇼핑'})
        art = visitor.get(f'/life/{aid}').get_data(as_text=True)
        self.assertIn('<span class="sb-h-emo" aria-hidden="true">📌</span><span class="sb-h-t"><small>01</small>소제목</span></h2>', art)  # 이모지 없는 예전 글도 이모지 칸, 소제목 번호
        self.assertIn('"@type": "Article"', art)
        self.assertIn(f'<link>http://localhost/life/{aid}</link>', visitor.get('/rss.xml').get_data(as_text=True))  # RSS에 생활정보 기사도
        self.assertEqual(visitor.get('/', base_url='http://www.consumerjebo.co.kr').headers['Location'], 'https://consumerjebo.co.kr/')  # www는 https 대표 주소로 한 번에
        self.assertIn('<li>목록</li>', art)
        self.assertIn('택배 분실 보상 정리', visitor.get('/life?category=쇼핑').get_data(as_text=True))
        # 방문자 화면·메일 이름이 모두 소보루. 예전 '브랜드' 설정값이 남아 있어도(비워도) 그대로 소보루
        for brand in ('', '소비자제보센터'):
            with self.site.conn() as db:
                db.execute("INSERT OR REPLACE INTO site_content(key,value,updated) VALUES('site.brand',?,'2026-10-16')", (brand,))
            home = visitor.get('/').get_data(as_text=True)
            self.assertIn('nn-home', home)
            self.assertIn('택배 분실 보상 정리', home)
            self.assertIn('소보루는 공공기관이 아닌', visitor.get('/companies').get_data(as_text=True))
            self.assertEqual(self.site.notify.site_name(), '소보루')
            self.assertEqual(self.site.notify.branded('소비자제보센터 드림'), '소보루 드림')
        with self.site.conn() as db: db.execute("DELETE FROM site_content WHERE key='site.brand'")

    def test_soboru_home_blocks_order_and_hide(self):
        # 메인 화면 묶음: 관리자 > 화면 편집에서 순서를 바꾸고 숨기면 홈에 그대로. 공개 제보만 본문이 나감
        with self.site.conn() as db:
            for receipt, subject, consent in (('p1', '공개 제보 카드 제목', 1), ('s1', '비밀 제보 카드 제목', 0)):
                db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (receipt, hashlib.sha256(b'test').hexdigest(), '배송·교환·환불', '테스트 업체', subject, '본문 미리보기 010-1234-5678', '요청', '2026-10-09T10:00:00', consent, 1))
        admin = self.login_admin()
        admin.post('/admin/life', data={'_csrf': self.csrf(admin, '/admin/life'), 'title': '생활정보 카드 제목', 'summary': '요약', 'body': '본문', 'category': '쇼핑', 'publish': '1'})
        try:
            home = self.client.get('/').get_data(as_text=True)
            order = lambda html: [k for k in ('nn-intro', 'nn-about', 'nn-live', 'nn-pick', 'nn-answer', 'lt-card') if k in html]
            self.assertEqual(order(home), ['nn-intro', 'nn-live', 'nn-pick', 'nn-answer', 'lt-card'])  # '이런 곳' 소개는 처음엔 숨김
            self.assertLess(home.index('nn-intro'), home.index('nn-live'))
            self.assertIn('생활정보 카드 제목', home)
            self.assertIn('공개 제보 카드 제목', home)
            self.assertIn('소비자의 소리', home); self.assertLess(home.index('nn-live'), home.index('id="letter-sub"'))  # 제보 목록 바로 밑에 레터 구독
            self.assertNotIn('nn-stats', home)  # 맨 위 건수 현황은 뺌
            self.assertIn('</svg>비밀 제보 카드 제목</h3>', home)  # 비밀글도 제목·업체는 보이고 본문만 잠금
            self.assertIn('커뮤니티', home)  # 메뉴 이름 (소보루 픽 → 커뮤니티, 2026-10-24)
            self.assertIn('AI 학습 이용을 금지', home)  # 하단 무단 이용 금지 문구
            self.assertIn('User-agent: GPTBot', self.client.get('/robots.txt').get_data(as_text=True))
            self.assertIn('자주 묻는 질문', home); self.assertNotIn('피해 유형별 안내', home)  # 피해 유형별 안내는 메뉴에서 뺌(운영자 요청)
            self.assertNotIn('010-1234-5678', home)
            self.assertNotIn('ed-blockbar', home)  # 손님 화면에는 편집 막대 없음
            # 화면 편집: 예전 '메인 화면 순서' 주소는 화면 편집으로
            self.assertIn('/admin/screens#page-home', admin.get('/admin/home-plan').headers['Location'])
            page = admin.get('/admin/screens').get_data(as_text=True)
            for name in ('화면 편집', '홈', '매거진', '커뮤니티', '제보', '기업', '법률 질문', '소보루 레터', '공통 머리글·바닥글', '소비자의 소리', '이 페이지 문구 모두 보기'):
                self.assertIn(name, page)
            token = self.csrf(admin, '/admin/screens')
            # 순서표 통째로: 레터를 맨 위로, 기업 답변 기록은 숨김
            r = admin.post('/admin/screens', data={'_csrf': token, 'page': 'home', 'act': 'order', 'block': ['letter', 'intro', 'quick', 'live', 'life', 'pick', 'answer'],
                                                   'show_letter': '1', 'show_intro': '1', 'show_quick': '1', 'show_live': '1', 'show_life': '1', 'show_pick': '1'})
            self.assertEqual(r.status_code, 302)
            home = self.client.get('/').get_data(as_text=True)
            self.assertEqual(order(home), ['nn-intro', 'nn-about', 'nn-live', 'nn-pick', 'lt-card'])
            self.assertLess(home.index('lt-card'), home.index('nn-intro'))
            self.assertNotIn('nn-answer', home)
            # 한 칸씩: 레터 아래로, 기업 답변 다시 보이기, 소개 숨기기 (편집 모드 막대가 쓰는 주소)
            self.assertEqual(admin.post('/admin/screens', data={'_csrf': token, 'page': 'home', 'block': 'letter', 'act': 'down', 'ajax': '1'}).get_json(), {'ok': True})
            admin.post('/admin/screens', data={'_csrf': token, 'page': 'home', 'block': 'answer', 'act': 'show', 'ajax': '1'})
            admin.post('/admin/screens', data={'_csrf': token, 'page': 'home', 'block': 'intro', 'act': 'hide', 'ajax': '1'})
            home = self.client.get('/').get_data(as_text=True)
            self.assertNotIn('nn-intro', home)
            self.assertIn('nn-answer', home)
            self.assertLess(home.index('lt-card'), home.index('nn-about'))
            with self.site.app.test_request_context('/'):
                self.assertEqual(self.site.app.extensions['soboru']['page_blocks']('home')[:3], [['intro', 0], ['letter', 1], ['quick', 1]])
            # 이상한 값은 무시하고, 모르는 묶음은 빠지고 빠진 묶음은 뒤에 붙음
            self.assertEqual(admin.post('/admin/screens', data={'_csrf': token, 'page': 'nope', 'block': 'x', 'act': 'up'}).status_code, 400)
            self.assertEqual(self.site.soboru.clean_blocks('letter', [['archive', 1], ['zzz', 1]]), [['archive', 1], ['hero', 1], ['feats', 1], ['reels', 1], ['subscribe', 1]])
            # 편집 모드: 묶음마다 옮기기 막대, 숨긴 묶음은 맨 아래에서 다시 보이기
            admin.post('/admin/edit-mode', data={'_csrf': token, 'on': '1', 'next': '/'})
            edit = admin.get('/').get_data(as_text=True)
            self.assertIn('class="ed-blockbar" data-page="home" data-block="quick"', edit)
            self.assertIn('class="ed-hiddenblocks"', edit)
            self.assertIn('data-act="show"', edit)
            # 예전 '메인 화면 순서'에서 끈 묶음은 새 화면에서도 꺼져 있음
            with self.site.conn() as db:
                db.execute("DELETE FROM soboru_settings WHERE key='blocks:home'")
                db.execute("INSERT OR REPLACE INTO soboru_settings(key,value) VALUES('home',?)", (json.dumps({'sections': [['top', 1], ['life', 1], ['rank', 0]]}),))
            home = self.client.get('/').get_data(as_text=True)
            self.assertIn('nn-intro', home); self.assertNotIn('nn-pick', home); self.assertNotIn('nn-answer', home)
            # 2026-10-24 전에 저장한 순서는 한 번만 새 순서(소개 → 제보 → 픽 → 골라주세요·수다방 → 이런 곳)로, 숨긴 건 그대로
            with self.site.conn() as db:
                db.execute("DELETE FROM soboru_settings WHERE key='home'")
                db.execute("INSERT OR REPLACE INTO soboru_settings(key,value) VALUES('blocks:home',?)", (json.dumps([['intro', 1], ['quick', 1], ['live', 1], ['pick', 1], ['answer', 0]]),))
            home = self.client.get('/').get_data(as_text=True)
            self.assertLess(home.index('nn-live'), home.index('nn-pick')); self.assertNotIn('nn-about', home)
            self.assertNotIn('nn-answer', home)
            with self.site.conn() as db:
                self.assertIn('_v2', db.execute("SELECT value FROM soboru_settings WHERE key='blocks:home'").fetchone()[0])
        finally:
            with self.site.conn() as db:
                db.execute("DELETE FROM soboru_settings WHERE key IN ('home','blocks:home')")

    def test_soboru_ai_art(self):
        # AI 일러스트: 분야·공개 제목만 보내고(연락처·이름 빠짐), 그린 그림은 게시 전엔 관리자만, 게시하면 카드에 그림('AI 일러스트' 표시는 없음)
        import base64
        with self.site.conn() as db:
            cid = db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published,reporter_name) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                             ('art1', 'x', '배송·교환·환불', '비밀상사', '홍길동 환불 거부 010-1234-5678', '본문 비밀 내용', '환불', '2026-10-09T10:00:00', 1, 1, '홍길동')).lastrowid
        sent = []
        def fake(url, headers, body, timeout):
            sent.append(body)
            return 200, {'data': [{'b64_json': base64.b64encode(b'RIFFxxxxWEBPfake').decode()}]}
        admin = self.login_admin()
        try:
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test', 'ART_AUTO': '1'}), patch.object(self.site.companydesk, 'post_json', fake):  # 자동 그리기는 운영자 2026-11-04부터 기본 꺼짐
                page = admin.get('/admin/art?kind=report').get_data(as_text=True)
                self.assertIn('AI 일러스트', page)
                self.assertNotIn('소비자 제보', admin.get('/admin/art').get_data(as_text=True))  # 매거진 '기사 사진'엔 제보 없음
                admin.post(f'/admin/art/report/{cid}', data={'_csrf': self.csrf(admin, '/admin/art'), 'act': 'draw'})
            prompt = sent[0]['prompt']
            self.assertIn('환불 거부', prompt)
            for secret in ('010-1234-5678', '홍길동', '비밀상사', '본문 비밀 내용'):
                self.assertNotIn(secret, prompt)
            visitor = self.site.app.test_client()
            self.assertEqual(visitor.get(f'/art/report/{cid}.webp').status_code, 404)
            self.assertEqual(admin.get(f'/art/report/{cid}.webp').status_code, 200)
            self.assertNotIn('sb-art', visitor.get('/').get_data(as_text=True))
            admin.post(f'/admin/art/report/{cid}', data={'_csrf': self.csrf(admin, '/admin/art'), 'act': 'publish'})
            self.assertEqual(visitor.get(f'/art/report/{cid}.webp').status_code, 200)
            detail = visitor.get(f'/reports/{cid}').get_data(as_text=True)
            self.assertIn(f'/art/report/{cid}.webp', detail)
            self.assertNotIn('sb-art-l', detail); self.assertIn('sb-art-ai', detail)
            self.assertNotIn('sb-art', visitor.get('/').get_data(as_text=True))  # 홈은 그림 없이 이모지 (예전 /?look=old 홈은 뺌)
            admin.post(f'/admin/art/report/{cid}', data={'_csrf': self.csrf(admin, '/admin/art'), 'act': 'hide'})
            self.assertEqual(visitor.get(f'/art/report/{cid}.webp').status_code, 404)
            # 생활정보 글은 만들면 자동으로 그려서 바로 붙음
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test', 'ART_AUTO': '1'}), patch.object(self.site.companydesk, 'post_json', fake):
                r = admin.post('/admin/life', data={'_csrf': self.csrf(admin, '/admin/life'), 'title': '헬스장 환불 받는 법', 'summary': '요약', 'body': '본문', 'category': '쇼핑', 'publish': '1'})
            aid = int(r.headers['Location'].rstrip('/').split('/')[-1])
            self.assertIn('헬스장 환불 받는 법', sent[-1]['prompt'])
            self.assertEqual(visitor.get(f'/art/life/{aid}.webp').status_code, 200)
            self.assertIn(f'/art/life/{aid}.webp', visitor.get(f'/life/{aid}').get_data(as_text=True))
            # 공개 제보는 게시되면 자동으로 그림 (내린 그림은 그대로 둠), 그림 없는 글은 한 번에 채우기
            with self.site.conn() as db:
                cid2 = db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                  ('art2', 'x', '배송·교환·환불', '가게', '택배가 안 와요', '본문', '배송', '2026-10-09T10:00:00', 1, 0)).lastrowid
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test', 'ART_AUTO': '1'}), patch.object(self.site.companydesk, 'post_json', fake):
                admin.post('/admin/art/fill', data={'_csrf': self.csrf(admin, '/admin/art'), 'kind': 'report'})
                self.assertEqual(visitor.get(f'/art/report/{cid2}.webp').status_code, 404)  # 게시 전이라 안 그림
                self.assertEqual(visitor.get(f'/art/report/{cid}.webp').status_code, 404)  # 내린 그림은 그대로
                with self.site.app.test_request_context('/'):
                    self.site.app.extensions['soboru_art']['auto']('report', cid2)  # 게시 전 제보는 그릴 글이 없어 조용히 넘어감
                with self.site.conn() as db: db.execute('UPDATE cases SET published=1 WHERE id=?', (cid2,))
                admin.post('/admin/art/fill', data={'_csrf': self.csrf(admin, '/admin/art'), 'kind': 'report'})
            self.assertEqual(visitor.get(f'/art/report/{cid2}.webp').status_code, 200)
            self.assertEqual(sent[-1]['quality'], 'low')
            # 옛 그림체 그림은 한 번에 새 그림체로 (게시 중이면 게시 상태 그대로)
            with self.site.conn() as db: db.execute("UPDATE soboru_art SET style=1 WHERE kind='report' AND target_id=?", (cid2,))
            n = len(sent)
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test', 'ART_AUTO': '1'}), patch.object(self.site.companydesk, 'post_json', fake):
                self.assertIn('옛 그림체 1개', admin.get('/admin/art?kind=report').get_data(as_text=True))
                admin.post('/admin/art/fill', data={'_csrf': self.csrf(admin, '/admin/art'), 'kind': 'report', 'mode': 'old'})
            self.assertEqual(len(sent), n + 1)
            with self.site.conn() as db:
                r = db.execute("SELECT * FROM soboru_art WHERE kind='report' AND target_id=?", (cid2,)).fetchone()
            self.assertEqual((r['style'], r['status']), (self.site.soboru_art.STYLE_V, 'live'))
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test', 'ART_AUTO': '1'}):
                self.assertNotIn('새 그림체로 다시 그리기', admin.get('/admin/art?kind=report').get_data(as_text=True))
            # 대표 사진: 관리자가 고른 첨부 사진만 공개, 고르면 AI 그림 대신 사진
            (Path(self.site.UPLOAD) / 'cover-test.png').write_bytes(b'\x89PNG fake')
            with self.site.conn() as db:
                fid = db.execute("INSERT INTO attachments(case_id,stored,original) VALUES(?,'cover-test.png','영수증.png')", (cid2,)).lastrowid
            self.assertEqual(visitor.get(f'/reports/{cid2}/cover').status_code, 404)
            page = admin.get(f'/admin/reports/{cid2}').get_data(as_text=True)
            self.assertIn('대표 사진 공개', page)
            admin.post(f'/admin/reports/{cid2}/cover', data={'_csrf': self.csrf(admin, f'/admin/reports/{cid2}'), 'file_id': fid})
            self.assertEqual(visitor.get(f'/reports/{cid2}/cover').status_code, 200)
            detail = visitor.get(f'/reports/{cid2}').get_data(as_text=True)
            self.assertIn(f'/reports/{cid2}/cover', detail)
            self.assertIn('제보자 사진', detail)
            self.assertIn(f'<meta property="og:image" content="http://localhost/reports/{cid2}/cover?v={fid}">', detail)  # 공유 미리보기도 그 사진
            admin.post(f'/admin/reports/{cid2}/cover', data={'_csrf': self.csrf(admin, f'/admin/reports/{cid2}'), 'file_id': 0})
            self.assertEqual(visitor.get(f'/reports/{cid2}/cover').status_code, 404)
        finally:
            with self.site.conn() as db:
                db.execute('DELETE FROM soboru_art'); db.execute('DELETE FROM articles')

    def test_soboru_naver_hub(self):
        # 네이버 API HUB: 서버에서만 키를 붙여 부르고, 같은 요청은 저장해 둔 결과를 다시 씀. 키는 화면에 안 나옴
        calls = []
        def fake(method, url, headers, body, timeout):
            calls.append((method, url, headers, body))
            path = url.split('ntruss.com', 1)[1].split('?')[0]
            if path.startswith('/search/v1/'):
                return 200, {'total': 3, 'items': [{'title': '<b>헬스장</b> 환불 &amp; 위약금', 'description': '요약 <b>환불</b>', 'link': 'https://n.news.naver.com/a/1',
                                                    'originallink': 'https://www.example-news.co.kr/a/1', 'pubDate': 'Thu, 15 Oct 2026 09:00:00 +0900', 'bloggername': '블로거', 'postdate': '20261015', 'cafename': '맘카페'},
                                                   {'title': '나쁜 링크', 'description': '', 'link': 'javascript:alert(1)'}]}
            if path == '/search-trend/v1/search':
                return 200, {'results': [{'title': g['groupName'], 'keywords': g['keywords'], 'data': [{'period': '2026-09-01', 'ratio': 40}, {'period': '2026-09-08', 'ratio': 50}, {'period': '2026-09-15', 'ratio': 80}, {'period': '2026-09-22', 'ratio': 100}]} for g in body['keywordGroups']]}
            if path == '/shopping/v1/categories':
                return 200, {'results': [{'title': c['name'], 'category': c['param'], 'data': [{'period': '2026-09-01', 'ratio': 50}, {'period': '2026-09-08', 'ratio': 60}]} for c in body['category']]}
            if path in ('/shopping/v1/category/gender', '/shopping/v1/category/age', '/shopping/v1/category/device'):
                grp = {'gender': ['f', 'm'], 'age': ['20', '30'], 'device': ['pc', 'mo']}[path.rsplit('/', 1)[1]]
                return 200, {'results': [{'title': '분야', 'data': [{'period': '2026-09-01', 'group': grp[0], 'ratio': 75}, {'period': '2026-09-01', 'group': grp[1], 'ratio': 25}]}]}
            if path == '/shopping/v1/category/keywords':
                return 200, {'results': [{'title': k['name'], 'keyword': k['param'], 'data': [{'period': '2026-09-01', 'ratio': 30}, {'period': '2026-09-08', 'ratio': 90}]} for k in body['keyword']]}
            return 404, {}
        with self.site.conn() as db:
            db.execute('DELETE FROM naver_cache'); db.execute('DELETE FROM naver_usage')
        hub = self.site.naverhub
        try:
            # 키가 없으면 '곧 열려요'만, 네이버는 부르지 않음
            with patch.object(hub, 'http', fake):
                self.assertIn('곧 열려요', self.client.get('/life/search?q=환불').get_data(as_text=True))
            self.assertEqual(calls, [])
            env = {'NAVER_HUB_CLIENT_ID': 'cid-test', 'NAVER_HUB_CLIENT_SECRET': 'secret-test-value'}
            with patch.dict(os.environ, env), patch.object(hub, 'http', fake):
                page = self.client.get('/life/search?q=헬스장 환불').get_data(as_text=True)
                self.assertIn('헬스장 환불 &amp; 위약금', page)
                self.assertIn('https://www.example-news.co.kr/a/1', page)  # 뉴스는 원문 링크
                self.assertIn('example-news.co.kr', page)
                self.assertIn('맘카페', page)
                self.assertIn('검색 결과 제공: NAVER', page)
                self.assertNotIn('javascript:', page)
                self.assertNotIn('<b>헬스장', page)
                self.assertNotIn('secret-test-value', page)
                self.assertNotIn('cid-test', page)
                self.assertEqual(len(calls), 4)
                method, url, headers, _ = calls[0]
                self.assertTrue(url.startswith('https://naverapihub.apigw.ntruss.com/search/v1/'))
                self.assertEqual((headers['X-NCP-APIGW-API-KEY-ID'], headers['X-NCP-APIGW-API-KEY']), ('cid-test', 'secret-test-value'))
                self.client.get('/life/search?q=헬스장 환불')
                self.assertEqual(len(calls), 4)  # 같은 검색은 저장해 둔 결과
                page = self.client.get('/life/search?q=헬스장 환불&tab=news&sort=date').get_data(as_text=True)
                self.assertIn('sort=date', calls[-1][1])
                self.assertIn('3건', page)
                # 검색어 추이·쇼핑 관심도
                page = self.client.get('/life/trend?k=환불&k=택배&months=3').get_data(as_text=True)
                self.assertIn('nv-chart', page)
                self.assertEqual([g['groupName'] for g in calls[-1][3]['keywordGroups']], ['환불', '택배'])
                self.assertEqual(calls[-1][2]['Content-Type'], 'application/json')
                page = self.client.get('/life/shopping').get_data(as_text=True)
                self.assertIn('디지털/가전', page)
                self.assertIn('20%', page)
                page = self.client.get('/life/shopping?cat=50000003&k=노트북').get_data(as_text=True)
                self.assertIn('여성 75%', page)
                self.assertIn('모바일 25%', page)
                self.assertEqual(calls[-1][3]['category'], '50000003')
                self.assertEqual(self.client.get('/life/shopping?cat=999').status_code, 404)
                # 생활정보 첫 화면: 탭과 요즘 소비자 뉴스
                life = self.client.get('/life').get_data(as_text=True)
                self.assertIn('요즘 소비자 뉴스', life)
                self.assertIn('통합 검색', life)
            # 인증 실패·한도 초과는 키 없이 쉬운 말로
            with patch.dict(os.environ, dict(env, NAVER_HUB_DAILY_SEARCH='1000000')), patch.object(hub, 'http', lambda *a: (401, {'errorCode': '401'})):
                page = self.client.get('/life/search?q=새로운 말').get_data(as_text=True)
                self.assertIn('네이버 검색 연결을 확인하고 있어요', page)
                self.assertNotIn('secret-test-value', page)
            with self.site.conn() as db: db.execute("UPDATE naver_usage SET n=99999 WHERE api='search'")
            with patch.dict(os.environ, env), patch.object(hub, 'http', fake):
                self.assertIn('오늘 쓸 수 있는 검색을 모두 썼어요', self.client.get('/life/search?q=또 다른 말').get_data(as_text=True))
        finally:
            with self.site.conn() as db:
                db.execute('DELETE FROM naver_cache'); db.execute('DELETE FROM naver_usage')

    def test_case_metoo_and_comments(self):
        # 공개 제보: '나도 겪었어요' 공감(누르면 +1, 다시 누르면 취소), 댓글(연락처 가림), 알리기 5번이면 숨김, 비공개 제보는 막힘
        with self.site.conn() as db:
            for receipt, consent in (('t1', 1), ('t2', 0)):
                db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (receipt, 'x', '배송·교환·환불', '테스트 업체', '공감 시험 제보', '본문', '환불', '2026-10-09T10:00:00', consent, 1))
            pub, sec = [r['id'] for r in db.execute("SELECT id FROM cases WHERE receipt IN ('t1','t2') ORDER BY id")]
        c = self.site.app.test_client()
        tok = self.csrf(c, f'/reports/{pub}')
        c.post(f'/reports/{pub}/react', data={'_csrf': tok, 'kind': 'metoo'})
        page = c.get(f'/reports/{pub}').get_data(as_text=True)
        self.assertIn('talk-btn t-metoo on', page)
        with self.site.conn() as db:
            db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('t3', 'x', '배송·교환·환불', '테스트 업체', '공감 없는 새 제보', '본문', '환불', '2026-10-10T10:00:00', 1, 1))
        hot = c.get('/reports?sort=hot').get_data(as_text=True)
        self.assertLess(hot.index('공감 시험 제보'), hot.index('공감 없는 새 제보'))  # 공감 많은 순
        new = c.get('/reports').get_data(as_text=True)
        self.assertLess(new.index('공감 없는 새 제보'), new.index('공감 시험 제보'))  # 최신순
        c.post(f'/reports/{pub}/react', data={'_csrf': tok, 'kind': 'metoo'})
        self.assertNotIn('talk-btn t-metoo on', c.get(f'/reports/{pub}').get_data(as_text=True))
        self.assertEqual(c.post(f'/reports/{sec}/react', data={'_csrf': tok, 'kind': 'metoo'}).status_code, 404)
        c.post(f'/reports/{pub}/comment', data={'_csrf': tok, 'nickname': '겪은사람', 'password': '1234', 'body': '저도 똑같아요 010-1234-5678'})
        page = c.get(f'/reports/{pub}').get_data(as_text=True)
        self.assertIn('저도 똑같아요', page)
        self.assertNotIn('010-1234-5678', page)
        self.assertEqual(c.post(f'/reports/{sec}/comment', data={'_csrf': tok, 'nickname': '겪은사람', 'password': '1234', 'body': '비공개'}).status_code, 404)
        with self.site.conn() as db:
            cid = db.execute('SELECT id FROM case_comments WHERE case_id=?', (pub,)).fetchone()[0]
        for _ in range(self.site.FLAG_HIDE_THRESHOLD):
            v = self.site.app.test_client()
            v.post(f'/reports/comment/{cid}/flag', data={'_csrf': self.csrf(v, f'/reports/{pub}')})
        self.assertNotIn('저도 똑같아요', c.get(f'/reports/{pub}').get_data(as_text=True))
        admin = self.login_admin()
        self.assertIn('제보 댓글', admin.get('/admin/board').get_data(as_text=True))
        admin.post('/admin/board', data={'_csrf': self.csrf(admin, '/admin/board'), 'kind': 'k', 'id': cid, 'action': 'show'})
        self.assertIn('저도 똑같아요', c.get(f'/reports/{pub}').get_data(as_text=True))
        # 관리자 설정으로 끄면 사라짐
        with self.site.conn() as db:
            db.execute("INSERT OR REPLACE INTO site_content(key,value,updated) VALUES('case.talk_off','끔','2026-10-16')")
        try:
            self.assertNotIn('talk-react', c.get(f'/reports/{pub}').get_data(as_text=True))
        finally:
            with self.site.conn() as db:
                db.execute("DELETE FROM site_content WHERE key='case.talk_off'")

    def test_admin_edits_site_copy(self):
        # 소보루 홈 문구(맨 위 큰 문구부터 작은 안내까지)를 관리자가 바꾸면 그대로 보이고, HTML은 글자로만 나감
        self.assertEqual(self.client.get('/admin/content').status_code, 302)
        admin = self.login_admin()
        token = self.csrf(admin, '/admin/content')
        response = admin.post('/admin/content', data={
            '_csrf': token, 'section': 'home',
            'home.intro_sub': '첫 줄\r\n<b>둘째 줄</b>', 'home.intro_title': '<script>x</script>소보루!', 'home.intro_btn': '',
            'home.live_title': '지금 막 온 제보', 'home.intro_kicker': '**굵게** <i>기울임</i>',
        }, follow_redirects=True)
        self.assertIn('문구를 저장했어요.', response.get_data(as_text=True))
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('첫 줄<br>&lt;b&gt;둘째 줄&lt;/b&gt;', home)
        self.assertIn('&lt;script&gt;x&lt;/script&gt;소보루!', home)
        self.assertNotIn('<script>x</script>', home)
        self.assertIn('<strong>굵게</strong> &lt;i&gt;기울임&lt;/i&gt;', home)
        self.assertIn('지금 막 온 제보', home)
        self.assertNotIn('써 본 건 추천하고', home)
        self.assertIn('>제보하기</a><a class="nn-intro-write"', home)  # required field left blank falls back to default
        admin.post('/admin/content', data={'_csrf': token, 'reset_section': 'home'})
        self.assertIn('억울한 일은 제보하고', self.client.get('/').get_data(as_text=True))

    def test_branding_policies_and_takedown(self):
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('img/soboru-logo.png', home)
        self.assertNotIn('<span>소비자</span>제보센터', home)  # 예전 로고는 뺌
        self.assertIn('<strong>소</strong>비자 권익 <strong>보</strong>호를 위한 <strong>루</strong>트', home)  # 바닥글 한 줄도 고칠 수 있는 문구
        self.assertIn('href="/privacy"', home)
        self.assertNotIn('신고센터', home)
        for link in ('href="/terms"', 'href="/privacy"', 'href="/youth"', '권리침해 신고 및 임시조치 안내'):
            self.assertIn(link, home)
        privacy = self.client.get('/privacy').get_data(as_text=True)
        self.assertIn('<h2 id="sec-1">1. 개인정보의 처리 목적</h2>', privacy)
        self.assertIn('<a href="#sec-13">13. 개인정보 처리방침의 변경</a>', privacy)
        self.assertIn('소보루(이하', privacy)  # {운영자} placeholder filled from operator info
        token = self.csrf(self.client, '/report')
        missing_truth = self.client.post('/report', data={'_csrf': token, 'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': 'A', 'subject': 'B', 'description': 'C', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': 'D', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234'})
        self.assertEqual(missing_truth.status_code, 400)
        full = {'_csrf': token, 'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': 'A', 'subject': 'B', 'description': 'C', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': 'D', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'secret'}
        for required in ('consent', 'share_company', 'use_consent', 'truth'):
            self.assertEqual(self.client.post('/report', data={k: v for k, v in full.items() if k != required}).status_code, 400, required)
        form = self.client.get('/report').get_data(as_text=True)
        for text in ('개인정보 제3자 제공', '저작권 동의', '게시글 작성 시로부터 3년', '제보 대상이 된 해당 사업자'):
            self.assertIn(text, form)
        self.assertNotIn('badge-opt', form)
        token = self.csrf(self.client, '/takedown')
        self.assertEqual(self.client.post('/takedown', data={'_csrf': token, 'requester': '업체'}).status_code, 400)
        done = self.client.post('/takedown', data={'_csrf': token, 'requester': '테스트 업체', 'contact': 'a@example.com', 'target': '제목', 'reason': '<b>사실과 다름</b>', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234'})
        self.assertIn('요청을 접수했어요.', done.get_data(as_text=True))
        admin = self.login_admin()
        listing = admin.get('/admin/takedowns').get_data(as_text=True)
        self.assertIn('&lt;b&gt;사실과 다름&lt;/b&gt;', listing)
        token = self.csrf(admin, '/admin/takedowns')
        with self.site.conn() as db:
            request_id = db.execute('SELECT id FROM takedown_requests').fetchone()['id']
        admin.post('/admin/takedowns', data={'_csrf': token, 'id': request_id, 'status': '임시 비공개', 'admin_note': '확인 중'})
        with self.site.conn() as db:
            self.assertEqual(db.execute('SELECT status FROM takedown_requests').fetchone()['status'], '임시 비공개')
        token = self.csrf(admin, '/admin/content')
        admin.post('/admin/content', data={'_csrf': token, 'section': 'operator', 'operator.name': '새 운영사', 'operator.manager': '홍민주', 'operator.email': 'help@example.com'})
        privacy = self.client.get('/privacy').get_data(as_text=True)
        self.assertIn('새 운영사(이하', privacy)
        footer = self.client.get('/').get_data(as_text=True)
        self.assertIn('<li>이메일. help@example.com</li>', footer)  # 관리자 옆에 대표 이메일 (전화는 비어 있어 안 보임)
        self.assertNotIn('<li>전화.', footer)
        self.assertIn('<li>상호. 새 운영사</li>', footer)
        self.assertIn('<li>관리자. <a class="ft-quiet" href="/admin/login" rel="nofollow">홍</a>민주</li>', footer)
        self.assertNotIn('<li>팩스.', footer)  # 비어 있는 항목은 표시하지 않음
        youth = self.client.get('/youth').get_data(as_text=True)
        self.assertIn('<h1>청소년보호정책</h1>', youth)
        self.assertIn('class="policy-toc"', youth)
        self.assertIn('<h2 id="sec-1">', youth)
        self.assertIn('청소년보호책임자: 오규섭 (대표)', youth)  # 비우면 기본값(대표자)인 개인정보 보호책임자로 표시
        self.assertIn('연락처: (운영자 정보 미입력)', youth)
        admin.post('/admin/content', data={'_csrf': self.csrf(admin, '/admin/content'), 'section': 'operator', 'operator.name': '새 운영사', 'operator.privacy_officer': '홍길동'})
        self.assertIn('청소년보호책임자: 홍길동', self.client.get('/youth').get_data(as_text=True))  # 비우면 개인정보 보호책임자로 대신 표시

    def post_form(self, client, path, data):
        token = self.csrf(client, path)
        return client.post(path, data={'_csrf': token, **data})

    def test_soboru_login_to_write(self):
        # 소보루는 로그인해야 제보·글·댓글을 씀 (운영자 2026-10-24)
        with patch.dict(os.environ, {'SOBORU_GUEST_WRITE': ''}):
            for path in ('/report', '/board/write?type=review'):
                r = self.client.get(path); self.assertEqual(r.status_code, 302); self.assertIn('/login?next=', r.headers['Location'])
            me, _ = self.member_client('login_writer', '로그인작가')
            self.assertEqual(me.get('/report').status_code, 200)
            self.assertEqual(me.get('/board/write?type=review').status_code, 200)

    def test_soboru_examples(self):
        # 커뮤니티 예시 글: 글쓴이 '소보루 예시' + 본문에 예시 표시, 두 번 넣어도 한 번만, remove로 모두 지움
        import soboru_examples as ex
        ex.add(self.site); ex.add(self.site)
        with self.site.conn() as db:
            rows = db.execute("SELECT nickname,body FROM posts WHERE ip_hash='example'").fetchall()
            self.assertEqual(len(rows), len(ex.REVIEWS) + len(ex.SUDA))
            self.assertTrue(all(r['nickname'] == '소보루 예시' and '예시 글' in r['body'] for r in rows))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM vs_polls WHERE ip_hash='example'").fetchone()[0], len(ex.POLLS))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM owner_news WHERE ip_hash='example'").fetchone()[0], len(ex.OWNERS))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cases WHERE subject LIKE '%예시%'").fetchone()[0], 0)  # 제보에는 안 넣음
        ex.remove(self.site)
        with self.site.conn() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM posts WHERE ip_hash='example'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM vs_polls WHERE ip_hash='example'").fetchone()[0], 0)
        # 배포하면 저절로 한 번만: 지운 뒤에는 다시 넣지 않음
        with patch.dict(os.environ, {'SOBORU_EXAMPLES': ''}):
            ex.auto(self.site); ex.auto(self.site)
            with self.site.conn() as db: self.assertEqual(db.execute("SELECT COUNT(*) FROM posts WHERE ip_hash='example'").fetchone()[0], len(ex.REVIEWS) + len(ex.SUDA))
            ex.remove(self.site); ex.auto(self.site)
            with self.site.conn() as db: self.assertEqual(db.execute("SELECT COUNT(*) FROM posts WHERE ip_hash='example'").fetchone()[0], 0)

    def test_consumer_board(self):
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('>커뮤니티</a>', home)
        self.assertIn('>이용 안내</a>', home)
        self.assertNotIn('제보 유형</a>', home)
        writer = self.site.app.test_client()
        bad = self.post_form(writer, '/board/write', {'category': '꿀팁', 'nickname': 'a', 'password': '1', 'title': 'x', 'body': 'short', 'agree': 'on'})
        self.assertEqual(bad.status_code, 400)
        self.assertIn('닉네임은 2~20자', bad.get_data(as_text=True))
        bot = self.post_form(writer, '/board/write', {'category': '꿀팁', 'nickname': '소보루', 'password': '1234', 'title': '환불 팁', 'body': '영수증을 꼭 챙기세요. 정말 중요해요.', 'agree': 'on', 'website': 'spam'})
        self.assertEqual(bot.status_code, 400)
        made = self.post_form(writer, '/board/write', {'category': '꿀팁', 'nickname': '소보루', 'password': '1234', 'title': '<환불> 팁', 'body': '영수증을 꼭 챙기세요.\n정말 중요해요.', 'agree': 'on'})
        self.assertEqual(made.status_code, 302)
        path = made.headers['Location']
        post_id = int(path.rstrip('/').split('/')[-1])
        page = writer.get(path).get_data(as_text=True)
        self.assertIn('&lt;환불&gt; 팁', page)
        listing = self.client.get('/board?category=꿀팁').get_data(as_text=True)
        self.assertIn('&lt;환불&gt; 팁', listing)
        self.assertNotIn('&lt;환불&gt; 팁', self.client.get('/board?category=자유').get_data(as_text=True))
        self.assertIn('&lt;환불&gt; 팁', self.client.get('/board?q=영수증').get_data(as_text=True))
        # 공감은 같은 브라우저에서 누르면 켜지고 다시 누르면 꺼짐
        token = self.csrf(self.client, path)
        self.client.post(f'/board/{post_id}/like', data={'_csrf': token})
        other = self.site.app.test_client()
        token2 = self.csrf(other, path)
        other.post(f'/board/{post_id}/like', data={'_csrf': token2})
        with self.site.conn() as db:
            self.assertEqual(db.execute('SELECT likes FROM posts WHERE id=?', (post_id,)).fetchone()['likes'], 2)
        self.client.post(f'/board/{post_id}/like', data={'_csrf': token})
        with self.site.conn() as db:
            self.assertEqual(db.execute('SELECT likes FROM posts WHERE id=?', (post_id,)).fetchone()['likes'], 1)
        # 댓글과 비밀번호 삭제
        self.client.post(f'/board/{post_id}/comment', data={'_csrf': token, 'nickname': '이웃', 'password': 'abcd', 'body': '저도 그랬어요'})
        self.assertIn('저도 그랬어요', self.client.get(path).get_data(as_text=True))
        with self.site.conn() as db:
            comment_id = db.execute('SELECT id FROM comments').fetchone()['id']
            self.assertEqual(db.execute('SELECT comments FROM posts').fetchone()['comments'], 1)
        self.client.post(f'/board/delete/c/{comment_id}', data={'_csrf': token, 'password': 'wrong'})
        self.assertIn('저도 그랬어요', self.client.get(path).get_data(as_text=True))
        self.client.post(f'/board/delete/c/{comment_id}', data={'_csrf': token, 'password': 'abcd'})
        self.assertNotIn('저도 그랬어요', self.client.get(path).get_data(as_text=True))
        # 서로 다른 이용자 알림이 기준을 넘으면 자동 숨김, 관리자가 다시 공개
        for _ in range(self.site.FLAG_HIDE_THRESHOLD):
            c = self.site.app.test_client()
            c.post(f'/board/flag/p/{post_id}', data={'_csrf': self.csrf(c, path)})
        self.assertEqual(self.client.get(path).status_code, 404)
        admin = self.login_admin()
        self.assertIn('&lt;환불&gt; 팁', admin.get('/admin/board').get_data(as_text=True))
        admin.post('/admin/board', data={'_csrf': self.csrf(admin, '/admin/board'), 'kind': 'p', 'id': post_id, 'action': 'show'})
        self.assertEqual(self.client.get(path).status_code, 200)
        # 작성자 비밀번호로 글 삭제
        writer.post(f'/board/delete/p/{post_id}', data={'_csrf': self.csrf(writer, path), 'password': '1234'})
        with self.site.conn() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM board_votes').fetchone()[0], 0)
        with patch.dict(os.environ, {'ENABLE_BOARD': '0'}):
            self.assertEqual(self.post_form(writer, '/board/write', {}).status_code, 503)

    def test_community_review_tip_question(self):
        # 커뮤니티 글 종류: 리뷰(별점·좋았던 점·기업 연결), 꿀팁(요약), 질문(글쓴이가 해결됨 표시). 소보루 화면에서 종류별로 보임
        with self.site.conn() as db:
            co = db.execute("INSERT INTO companies(name,biz_no,contact_name,contact_phone,contact_email,created,status) VALUES('리뷰상사','1234567890','담당','02','a@b.c','2026-10-01','listed')").lastrowid
        writer = self.site.app.test_client()
        base = {'nickname': '후기왕', 'password': '1234', 'agree': 'on'}
        r = self.post_form(writer, '/board/write', {**base, 'kind': 'review', 'target': '리뷰 상사', 'rating': '4', 'recommend': '1', 'title': '환불이 빨랐어요', 'pros': '사흘 만에 환불 010-1234-5678', 'cons': '전화 연결이 느려요', 'body': ''})
        self.assertEqual(r.status_code, 302)
        rid = int(r.headers['Location'].rstrip('/').split('/')[-1])
        bad = self.post_form(writer, '/board/write', {**base, 'kind': 'review', 'target': '어딘가', 'title': '별점 없는 리뷰', 'body': '별점을 안 골랐어요. 열 글자 넘게.'})
        self.assertEqual(bad.status_code, 400)
        self.assertIn('별점을 골라 주세요', bad.get_data(as_text=True))
        q = self.post_form(writer, '/board/write', {**base, 'kind': 'question', 'title': '위약금 얼마인가요?', 'body': '헬스장 중도 해지 위약금이 궁금해요.', 'category': '자유'})
        qid = int(q.headers['Location'].rstrip('/').split('/')[-1])
        with self.site.conn() as db:
            row = db.execute('SELECT * FROM posts WHERE id=?', (rid,)).fetchone()
            self.assertEqual((row['kind'], row['rating'], row['recommend'], row['company_id'], row['category']), ('review', 4, 1, co, '경험 공유'))
            self.assertEqual(db.execute('SELECT kind,category FROM posts WHERE id=?', (qid,)).fetchone()[:], ('question', '질문해요'))
            tid = db.execute("INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created,kind,summary) VALUES('꿀팁','팁','','택배 분실 보상 순서','먼저 택배사에 접수해요. 그다음 영수증.','x',?,'tip','운송장 금액 기준이에요')", (datetime.datetime.now().isoformat(timespec='seconds'),)).lastrowid
        page = writer.get(f'/board/{rid}').get_data(as_text=True)
        self.assertIn('aria-label="별점 5점 중 4점"', page)
        self.assertIn(f'/companies/{co}', page)
        self.assertNotIn('010-1234-5678', page)
        # 질문: 비밀번호가 틀리면 그대로, 맞으면 해결됨
        token = self.csrf(writer, f'/board/{qid}')
        writer.post(f'/board/{qid}/solve', data={'_csrf': token, 'password': 'nope'})
        with self.site.conn() as db:self.assertEqual(db.execute('SELECT solved FROM posts WHERE id=?', (qid,)).fetchone()[0], 0)
        writer.post(f'/board/{qid}/solve', data={'_csrf': token, 'password': '1234'})
        with self.site.conn() as db:self.assertEqual(db.execute('SELECT solved FROM posts WHERE id=?', (qid,)).fetchone()[0], 1)
        self.assertIn('해결됨', self.client.get(f'/board/{qid}').get_data(as_text=True))
        self.assertIn('리뷰 상사', self.client.get('/board').get_data(as_text=True))  # 목록에도 리뷰 대상이 보임
        self.assertIn('커뮤니티 리뷰', self.client.get(f'/companies/{co}').get_data(as_text=True))
        board = self.client.get('/board').get_data(as_text=True)
        for text in ('무엇을 올릴까요?', '리뷰 모아 보기', '환불이 빨랐어요', '운송장 금액 기준이에요', 'cm-solved', '별점 5점 중 4점'):
            self.assertIn(text, board)
        only = self.client.get('/board?type=question').get_data(as_text=True)
        self.assertIn('위약금 얼마인가요?', only)
        self.assertNotIn('환불이 빨랐어요', only)
        self.assertIn('value="정보" checked', self.client.get('/board/write?type=tip').get_data(as_text=True))  # 꿀팁은 수다의 '정보' 말머리로
        post = self.client.get(f'/board/{rid}').get_data(as_text=True)
        self.assertIn('cm-review', post)
        self.assertIn('좋았던 점', post)
        self.assertNotIn('010-1234-5678', post)
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('sb-cm-card k-review', home)
        self.assertIn('택배 분실 보상 순서', home)
        self.assertIn('별점 5점 중 4점', self.client.get(f'/companies/{co}').get_data(as_text=True))

    def jpeg_with_gps(self):
        # 위치(GPS)가 든 EXIF를 붙인 작은 JPEG
        from PIL import Image
        im = Image.new('RGB', (40, 30), (255, 120, 0))
        exif = Image.Exif()
        exif[0x010F] = 'SecretCam'
        exif[0x8825] = {1: 'N', 2: (37.0, 30.0, 0.0), 3: 'E', 4: (127.0, 2.0, 0.0)}
        buf = io.BytesIO()
        im.save(buf, 'JPEG', exif=exif.tobytes())
        return buf.getvalue()

    def test_review_campaign_photo_editor(self):
        # 이번 주 리뷰 주제: 관리자가 열면 소보루 픽·메인·안내 화면에 보이고, 그 주제로 쓴 리뷰는 '이벤트 참여 리뷰' 표시
        with self.site.conn() as db:
            db.execute('DELETE FROM review_campaigns')
        try:
            self.assertEqual(self.client.get('/admin/campaigns').status_code, 302)
            admin = self.login_admin()
            r = self.post_form(admin, '/admin/campaigns', {'slug': 'delivery-1017', 'title': '내가 시켜 먹은 배달음식, 솔직히 어땠나요?', 'topic': '배달음식', 'intro': '맛·양·배달까지 솔직하게',
                                                          'fields_hint': '주문한 메뉴와 가격', 'starts': '', 'ends': '', 'active': '1', 'reward_on': '1', 'reward_rules': '대상: 사진 리뷰 중 추첨 20명\n지급 방법: 가입한 이메일로 보내 드려요\n유의사항: 별점과 상관없이 추첨해요'})
            self.assertEqual(r.status_code, 302)
            bad = self.post_form(admin, '/admin/campaigns', {'slug': 'Bad Slug', 'title': '두 번째'})
            self.assertEqual(bad.status_code, 302)
            with self.site.conn() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM review_campaigns').fetchone()[0], 1)
                camp = db.execute('SELECT * FROM review_campaigns').fetchone()
            self.assertIn('리뷰 주제', admin.get('/admin/campaigns').get_data(as_text=True))
            board = self.client.get('/board').get_data(as_text=True)
            self.assertIn('내가 시켜 먹은 배달음식, 솔직히 어땠나요?', board)
            self.assertIn('/board/write?type=review&amp;campaign=delivery-1017', board)
            self.assertNotIn('cp-card', self.client.get('/').get_data(as_text=True))  # 홈에선 기본으로 지움 (OH 2026-10-29)
            page = self.client.get('/pick/delivery-1017').get_data(as_text=True)
            for text in ('#배달음식', '#내돈내산', '#사진 리뷰', '첫 리뷰를 남기면 소보루 픽 순위가 생겨요', '참여 혜택 안내', '사진 리뷰 중 추첨 20명', 'soboru-character-hero.png'):
                self.assertIn(text, page)
            self.assertEqual(self.client.get('/pick/nope').status_code, 404)
            self.assertIn('/pick/delivery-1017</loc>', self.client.get('/sitemap.xml').get_data(as_text=True))  # 연 주제는 사이트맵에
            write = self.client.get('/board/write?type=review&campaign=delivery-1017').get_data(as_text=True)
            for text in ('name="campaign" value="delivery-1017"', '주문 메뉴', 'enctype="multipart/form-data"', 'name="photo"', '첫 리뷰를 남기면'):
                self.assertIn(text, write)
            self.assertNotIn('name="editor"', write)  # 에디터 칸은 관리자에게만
            # 손님이 사진(위치 정보 포함)과 함께 주제 리뷰를 씀
            guest = self.site.app.test_client()
            token = self.csrf(guest, '/board/write?type=review&campaign=delivery-1017')
            base = {'_csrf': token, 'nickname': '배달러', 'password': '1234', 'agree': 'on', 'kind': 'review', 'campaign': 'delivery-1017', 'target': '소보루치킨 역삼점', 'menu': '후라이드 반 양념 반',
                    'rating': '4', 'recommend': '1', 'title': '바삭함은 최고, 배달은 50분', 'pros': '튀김옷이 끝까지 바삭했어요', 'cons': '배달이 50분 걸렸어요', 'body': ''}
            no = guest.post('/board/write', data={**base, 'photo': (io.BytesIO(b'<script>alert(1)</script>'), 'x.jpg')}, content_type='multipart/form-data')
            self.assertEqual(no.status_code, 400)
            self.assertIn('사진은 8MB 이하 JPG·PNG·WEBP 한 장만', no.get_data(as_text=True))
            ok = guest.post('/board/write', data={**base, 'photo': (io.BytesIO(self.jpeg_with_gps()), 'me.jpg')}, content_type='multipart/form-data')
            self.assertEqual(ok.status_code, 302)
            rid = int(ok.headers['Location'].rstrip('/').split('/')[-1])
            with self.site.conn() as db:
                row = db.execute('SELECT * FROM posts WHERE id=?', (rid,)).fetchone()
            self.assertEqual((row['campaign_id'], row['reward'], row['editor'], row['review_cat'], row['menu']), (camp['id'], 1, 0, '배달음식', '후라이드 반 양념 반'))
            self.assertRegex(row['photo'], r'^[0-9a-f]{32}\.jpg$')
            stored = (Path(os.environ['UPLOAD_DIR']) / 'board' / row['photo']).read_bytes()
            self.assertTrue(stored.startswith(b'\xff\xd8\xff'))
            self.assertNotIn(b'Exif', stored)
            self.assertNotIn(b'SecretCam', stored)
            photo = self.client.get('/board/photo/' + row['photo'])
            self.assertEqual((photo.status_code, photo.mimetype, photo.headers['X-Content-Type-Options']), (200, 'image/jpeg', 'nosniff'))
            photo.close()
            self.assertEqual(self.client.get('/board/photo/../app.py').status_code, 404)
            post = self.client.get(f'/board/{rid}').get_data(as_text=True)
            for text in ('소보루 이벤트 참여 리뷰 · 혜택을 받을 수 있어요', '/board/photo/' + row['photo'], '후라이드 반 양념 반', '/pick/delivery-1017'):
                self.assertIn(text, post)
            listing = self.client.get('/board?type=review&rc=배달음식').get_data(as_text=True)
            self.assertIn('바삭함은 최고, 배달은 50분', listing)
            self.assertIn('cm-thumb', listing)
            self.assertIn('소보루 이벤트 참여 리뷰', listing)
            self.assertNotIn('바삭함은 최고, 배달은 50분', self.client.get('/board?type=review&rc=편의점').get_data(as_text=True))
            self.assertIn('벌써', self.client.get('/pick/delivery-1017').get_data(as_text=True))
            # 소보루 에디터 리뷰: 관리자만, 표시가 붙고, 혜택·소비자 순위에는 안 들어감
            self.assertIn('name="editor"', admin.get('/board/write?type=review').get_data(as_text=True))
            ed = self.post_form(admin, '/board/write', {'kind': 'review', 'editor': '1', 'campaign': 'delivery-1017', 'target': '에디터픽치킨', 'rating': '5', 'recommend': '1', 'title': '에디터가 먹어 본 치킨', 'pros': '양이 많아요 정말 많아요', 'agree': 'on'})
            self.assertEqual(ed.status_code, 302)
            sneaky = self.post_form(guest, '/board/write', {'kind': 'review', 'editor': '1', 'nickname': '흉내', 'password': '1234', 'target': '가짜에디터', 'rating': '5', 'title': '에디터인 척', 'pros': '열 글자가 넘는 후기예요', 'agree': 'on'})
            self.assertEqual(sneaky.status_code, 302)
            with self.site.conn() as db:
                eds = dict(db.execute('SELECT target,editor FROM posts WHERE target IN (?,?)', ('에디터픽치킨', '가짜에디터')).fetchall())
                erow = db.execute("SELECT * FROM posts WHERE target='에디터픽치킨'").fetchone()
            self.assertEqual(eds, {'에디터픽치킨': 1, '가짜에디터': 0})
            self.assertEqual((erow['reward'], erow['nickname']), (0, '소보루 에디터'))
            board = self.client.get('/board').get_data(as_text=True)
            self.assertIn('cm-editor', board)
            rated = board.split('cm-rated-h', 1)[1]
            self.assertNotIn('에디터픽치킨', rated)
            self.assertIn('소보루치킨 역삼점', rated)
            home = self.client.get('/').get_data(as_text=True)
            self.assertNotIn('에디터픽치킨</', home.split('소비자 추천 TOP 5', 1)[1].split('nn-pick-feed', 1)[0])
            self.assertNotIn('에디터픽치킨', self.client.get('/pick/delivery-1017').get_data(as_text=True).split('cp-rank-h', 1)[1])
            # 숨긴 글의 사진은 운영자만, 글을 지우면 사진 파일도 지움
            with self.site.conn() as db:db.execute('UPDATE posts SET hidden=1 WHERE id=?', (rid,))
            self.assertEqual(self.client.get('/board/photo/' + row['photo']).status_code, 404)
            admin.get('/board/photo/' + row['photo']).close()
            with self.site.conn() as db:self.site.delete_board_item(db, 'p', rid)
            self.assertFalse((Path(os.environ['UPLOAD_DIR']) / 'board' / row['photo']).exists())
            # 주제를 끝내면 카드가 내려가고, 끝난 주제로는 참여하지 않음
            admin.post('/admin/campaigns', data={'_csrf': self.csrf(admin, '/admin/campaigns'), 'id': camp['id'], 'act': 'end'})
            self.assertNotIn('cp-card', self.client.get('/board').get_data(as_text=True))
            self.assertNotIn('name="campaign"', self.client.get('/board/write?type=review&campaign=delivery-1017').get_data(as_text=True))
            self.assertIn('이 주제는 끝났어요', self.client.get('/pick/delivery-1017').get_data(as_text=True))
        finally:
            with self.site.conn() as db:
                db.execute('DELETE FROM review_campaigns')

    def test_photo_cleaning_without_pillow(self):
        # Pillow가 없으면 JPEG의 EXIF(APP1) 조각만 떼어 내고, PNG는 글 조각을 떼고, WEBP는 받지 않음
        from PIL import Image
        jpg = self.jpeg_with_gps()
        self.assertIn(b'Exif', jpg)
        png = io.BytesIO(); Image.new('RGB', (4, 4)).save(png, 'PNG'); raw = png.getvalue()
        text = b'GPS\x0037.5'
        raw = raw[:33] + len(text).to_bytes(4, 'big') + b'tEXt' + text + b'\0\0\0\0' + raw[33:]  # 머리(IHDR) 바로 뒤에 글 조각
        webp = io.BytesIO(); Image.new('RGB', (4, 4)).save(webp, 'WEBP')
        with patch.dict('sys.modules', {'PIL': None}):
            out, kind = self.site.clean_photo(jpg)
            self.assertEqual(kind, 'jpg')
            self.assertNotIn(b'Exif', out)
            self.assertTrue(out.startswith(b'\xff\xd8') and out.endswith(b'\xff\xd9'))
            out, kind = self.site.clean_photo(raw)
            self.assertEqual(kind, 'png')
            self.assertNotIn(b'GPS', out)
            self.assertEqual(self.site.clean_photo(webp.getvalue()), (None, None))
        self.assertEqual(self.site.clean_photo(b'GIF89a' + b'\0' * 20), (None, None))
        self.assertEqual(self.site.clean_photo(b'\xff\xd8\xff' + b'\0' * (8 * 1024 * 1024)), (None, None))

    def test_jebo_signup_has_no_id_form(self):
        # 운영자 2026-11-03: 제보센터는 아이디 가입 없음. 문자 키가 없어도 아이디 칸으로 돌아가지 않음
        hosts = patch.object(self.site, 'JEBO_HOSTS', {'consumerjebo.co.kr'}); hosts.start(); self.addCleanup(hosts.stop)
        page = self.site.app.test_client().get('/signup', base_url='https://consumerjebo.co.kr').get_data(as_text=True)
        self.assertNotIn('name="login_id"', page)

    def test_site_visits_by_site_and_source(self):
        # 방문 통계: 소보루·소비자제보센터를 나눠 방문자(하루 한 번)·들어온 곳·많이 본 화면. 관리자·봇·토큰은 남지 않음
        with self.site.conn() as db: db.execute('DELETE FROM site_visits'); db.execute('DELETE FROM page_views')
        hosts = {'consumerjebo.co.kr', 'www.consumerjebo.co.kr'}
        self.site.JEBO_HOSTS.update(hosts)
        try:
            a = self.site.app.test_client()
            a.get('/', headers={'Referer': 'https://m.search.naver.com/search.naver?query=소보루'})
            a.get('/feed'); a.get('/reports')  # 같은 날 같은 사이트는 한 사람
            b = self.site.app.test_client()
            b.get('/reports', base_url='https://consumerjebo.co.kr', headers={'Referer': 'https://www.google.co.kr/'})
            b.get('/company/1/abcdefghijklmnopqrstu', base_url='https://consumerjebo.co.kr')
            self.client.get('/', headers={'User-Agent': 'Mozilla/5.0 (compatible; Yeti/1.1; +https://naver.me/spd)'})  # 봇
            admin = self.login_admin(); admin.get('/')  # 관리자
            with self.site.conn() as db:
                self.assertEqual(sorted(tuple(r) for r in db.execute('SELECT site,source FROM site_visits')), [('jebo', '구글'), ('soboru', '네이버 검색')])
                views = {(r['site'], r['page']): r['n'] for r in db.execute('SELECT * FROM page_views')}
            self.assertEqual(views[('soboru', '/')], 1); self.assertEqual(views[('soboru', '/feed')], 1); self.assertEqual(views[('jebo', '/reports')], 1)
            self.assertFalse(any('abcdefghijklmnop' in k[1] for k in views))
            page = admin.get('/admin/visits').get_data(as_text=True)
            # 운영자 2026-11-03: 소보루는 이제 없음 → 통계는 소비자제보센터만
            self.assertIn('방문 통계', page); self.assertIn('구글', page); self.assertNotIn('네이버 검색', page); self.assertNotIn('두 사이트 합계', page)
            self.assertEqual(self.client.get('/admin/visits').status_code, 302)
            # 운영자 2026-11-04: 관리자 기기는 로그아웃해도 안 셈, 등록한 IP도 안 셈
            def count():
                with self.site.conn() as db: return db.execute("SELECT COALESCE(SUM(n),0) FROM page_views WHERE page='/faq'").fetchone()[0]
            with admin.session_transaction() as s: s.pop('admin', None)
            admin.get('/faq'); self.assertEqual(count(), 0)
            self.assertIn('세지 않는 곳', page); self.assertIn('127.0.0.1', page)
            c = self.login_admin(); self.post_form(c, '/admin/visits', {'ips': '127.0.0.1\nnot-an-ip'})
            self.site.app.test_client().get('/faq'); self.assertEqual(count(), 0)
            self.post_form(c, '/admin/visits', {'ips': ''})
            self.site.app.test_client().get('/faq'); self.assertEqual(count(), 1)
        finally:
            self.site.JEBO_HOSTS.difference_update(hosts)

    def test_ad_effect_first_touch(self):
        # 광고 효과: 처음 들어온 경로(utm)별 방문·가입·리뷰·재방문. 쿠키 번호는 해시로만 저장
        with self.site.conn() as db:db.execute('DELETE FROM ad_events')
        visitor = self.site.app.test_client()
        r = visitor.get('/board?utm_source=instagram&utm_medium=paid&utm_campaign=delivery-1017')
        self.assertIn('sb_vid=', r.headers.get('Set-Cookie', '') + ''.join(r.headers.getlist('Set-Cookie')))
        visitor.get('/reports?utm_source=naver')  # 두 번째 경로는 무시(첫 경로만)
        self.signup(visitor, login_id='ad_user', nickname='광고손님')
        self.post_form(visitor, '/board/write', {'kind': 'review', 'target': '광고치킨', 'rating': '5', 'title': '광고 보고 와서 쓴 리뷰', 'pros': '열 글자가 넘는 후기예요', 'agree': 'on'})
        self.client.get('/', headers={'User-Agent': 'Mozilla/5.0 (compatible; Yeti/1.1; +https://naver.me/spd)'})  # 검색 로봇은 세지 않음
        with self.site.conn() as db:
            rows = db.execute('SELECT * FROM ad_events ORDER BY event').fetchall()
            self.assertEqual(sorted(r['event'] for r in rows), ['review', 'signup', 'visit'])
            self.assertEqual({(r['utm_source'], r['utm_medium'], r['utm_campaign']) for r in rows}, {('instagram', 'paid', 'delivery-1017')})
            vid = visitor.get_cookie('sb_vid').value
            self.assertNotIn(vid, rows[0]['visitor_hash'])
            self.assertEqual(len(rows[0]['visitor_hash']), 64)
            # 다음 날 다시 오면 재방문. 90일 지난 기록은 지움
            yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
            db.execute('UPDATE ad_events SET day=?', (yesterday,))
            db.execute("INSERT INTO ad_events(day,utm_source,event,visitor_hash) VALUES('2020-01-01','old','visit','x')")
        with visitor.session_transaction() as s:s.pop('ad_day', None)
        visitor.get('/')
        with self.site.conn() as db:
            self.assertEqual(db.execute("SELECT utm_source FROM ad_events WHERE event='return'").fetchone()[0], 'instagram')
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ad_events WHERE utm_source='old'").fetchone()[0], 0)
        self.assertEqual(self.client.get('/admin/ads').status_code, 302)
        page = self.login_admin().get('/admin/ads').get_data(as_text=True)
        self.assertIn('instagram', page)
        self.assertIn('100.0%', page)
        self.assertIn('익명 방문자 쿠키', self.client.get('/privacy').get_data(as_text=True))

    def test_public_and_secret_report_pages(self):
        ids = {}
        for visibility in ('public', 'secret'):
            token = self.csrf(self.client, '/report')
            self.client.post('/report', data={
                '_csrf': token, 'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '공개 업체', 'subject': visibility + ' 제목',
                'description': '연락은 010-1234-5678 또는 me@example.com 으로', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': '환불',
                'contact': 'secret@example.com', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': visibility,
            })
            with self.site.conn() as db:
                ids[visibility] = db.execute('SELECT id FROM cases WHERE subject=?', (visibility + ' 제목',)).fetchone()['id']
        # 공개를 고른 제보는 접수 즉시 게시 (연락처는 가려서)
        self.assertEqual(self.client.get('/reports/%d' % ids['public']).status_code, 200)
        admin = self.login_admin()
        self.assertIn('pub-chip is-on">공개 중', admin.get('/admin/reports/%d' % ids['public']).get_data(as_text=True))
        listing = admin.get('/admin/reports').get_data(as_text=True)
        # 목록은 공개가 기본이라 따로 안 적고, 비밀글만 표시
        self.assertIn('jl-lock" title="제보자가 비밀글로 접수">비밀', listing)
        self.assertIn('rv-chip rv-new">미검토', listing)
        # 운영자가 사후에 게시를 내리면 목록에는 '비공개'로 제목만, 누르면 조회 비밀번호 창
        self.post_form(admin, '/admin/reports/%d' % ids['public'], {'form': 'publish_review', 'decision': 'hold'})
        self.assertEqual(self.client.get('/reports/%d' % ids['public']).status_code, 404)
        listing = self.client.get('/reports').get_data(as_text=True)
        card = listing.split('href="/reports/%d/mine"' % ids['public'])[1].split('</a>')[0]  # 카드: 제목만, 누르면 조회 비밀번호 창
        self.assertIn('public 제목</h3>', card); self.assertNotIn('vcs-lock', card)  # 운영자 2026-11-04: 자물쇠 표시는 뺌
        self.assertNotIn('연락은 010', listing)
        self.assertEqual(self.post_form(admin, '/admin/reports/%d' % ids['secret'], {'form': 'publish_review', 'decision': 'approve'}).status_code, 400)
        self.post_form(admin, '/admin/reports/%d' % ids['public'], {'form': 'publish_review', 'decision': 'approve'})
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('href="/reports/%d">' % ids['public'], home)
        self.assertIn('public 제목', home)
        self.assertIn('href="/reports/%d/mine"' % ids['secret'], home)  # 비밀글은 제목이 보여도 비밀번호 창으로
        self.assertIn('secret 제목', home)
        listing = self.client.get('/reports').get_data(as_text=True)
        self.assertIn('secret 제목</h3>', listing)
        self.assertNotIn('연락은 010', listing)  # 비밀글 본문은 목록에 없음
        # 비밀글 제목·업체명은 늘 목록에 보임 (운영자 설정을 저장해도 그대로)
        self.post_form(admin, '/admin/reports/%d' % ids['secret'], {'form': 'settings', 'status': '접수', 'assignee': ''})
        self.assertIn('secret 제목', self.client.get('/reports').get_data(as_text=True))
        page = self.client.get('/reports/%d' % ids['public']).get_data(as_text=True)
        self.assertIn('[전화번호 비공개]', page)
        self.assertIn('[이메일 비공개]', page)
        self.assertNotIn('010-1234-5678', page)
        self.assertNotIn('secret@example.com', page)
        self.assertIn('공개 업체', page)
        self.assertEqual(self.client.get('/reports/%d' % ids['secret']).status_code, 404)
        token = self.csrf(self.client, '/report')
        no_choice = self.client.post('/report', data={'_csrf': token, 'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': 'A', 'subject': 'B', 'description': 'C', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': 'D', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on'})
        self.assertEqual(no_choice.status_code, 400)

    def test_reporter_notifications(self):
        notify = self.site.notify
        notify.ASYNC = False
        kakao, mails = [], []
        base = {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': 'A', 'subject': '알림 테스트 제보', 'description': 'C', 'reporter_name': '김소비',
                'phone': '010-2222-3333', 'contact': 'me@example.com', 'request_text': 'D', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234',
                'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'secret'}
        # 설정이 없으면 아무것도 안 보냄
        with patch.object(notify.bizmsg, 'http_post', side_effect=lambda *a, **k: kakao.append(a) or {}), patch.object(notify, 'send_email', side_effect=lambda *a, **k: mails.append(a + (k.get("html"),))):
            self.post_form(self.client, '/report', base)
        self.assertEqual((kakao, mails), ([], []))
        keys = {'SOLAPI_API_KEY': 'k', 'SOLAPI_API_SECRET': 's', 'SOLAPI_PFID': 'pf', 'KAKAO_TPL_RECEIVED': 'T1', 'KAKAO_TPL_STATUS': 'T2', 'KAKAO_TPL_MESSAGE': 'T3',
                'SMTP_HOST': 'smtp.example.com', 'SMTP_USER': 'bot@example.com', 'SMTP_PASSWORD': 'pw'}
        with patch.dict(os.environ, keys), patch.object(notify.bizmsg, 'http_post', side_effect=lambda *a, **k: kakao.append(a) or {'statusCode': '2000'}), \
             patch.object(notify, 'send_email', side_effect=lambda *a, **k: mails.append(a + (k.get("html"),))):
            self.post_form(self.client, '/report', dict(base, subject='알림 두번째'))
            self.assertEqual(len(kakao), 1)
            message = kakao[0][1]['message']
            self.assertEqual(message['to'], '01022223333')
            self.assertEqual(message['kakaoOptions']['templateId'], 'T1')
            self.assertEqual(message['kakaoOptions']['variables']['#{이름}'], '김소비')
            self.assertTrue(kakao[0][2]['Authorization'].startswith('HMAC-SHA256 apiKey=k, date='))
            self.assertEqual(mails[0][0], 'me@example.com')
            self.assertIn('제보가 접수됐습니다', mails[0][2])
            self.assertIn('http://localhost/lookup', mails[0][2])
            with self.site.conn() as db:
                case_id = db.execute("SELECT id FROM cases WHERE subject='알림 두번째'").fetchone()['id']
            admin = self.login_admin()
            self.post_form(admin, '/admin/reports/%d' % case_id, {'form': 'settings', 'status': '검토 중', 'assignee': ''})
            self.assertEqual(kakao[-1][1]['message']['kakaoOptions']['templateId'], 'T2')
            self.assertIn('현재 단계: 검토 중', mails[-1][2])
            self.post_form(admin, '/admin/reports/%d' % case_id, {'form': 'message', 'message': '확인 중입니다'})
            self.assertEqual(kakao[-1][1]['message']['kakaoOptions']['templateId'], 'T3')
            self.assertNotIn('확인 중입니다', mails[-1][2])
            # 실패도 기록되고, 관리자 화면에 보임
            with patch.object(notify.bizmsg, 'http_post', side_effect=OSError('down')):
                self.post_form(admin, '/admin/reports/%d' % case_id, {'form': 'message', 'message': '두 번째'})
            page = admin.get('/admin/reports/%d' % case_id).get_data(as_text=True)
        self.assertIn('카톡 켜짐', page)
        self.assertIn('010****3333', page)
        self.assertIn('me***@example.com', page)
        self.assertIn('down', page)
        with self.site.conn() as db:
            rows = db.execute('SELECT channel,event,status FROM notifications WHERE case_id=? ORDER BY id', (case_id,)).fetchall()
        self.assertEqual([tuple(r) for r in rows], [('kakao', 'received', 'sent'), ('email', 'received', 'sent'), ('kakao', 'status', 'sent'), ('email', 'status', 'sent'),
                                                   ('kakao', 'message', 'sent'), ('email', 'message', 'sent'), ('kakao', 'message', 'failed'), ('email', 'message', 'sent')])
        notify.ASYNC = True

    def test_aligo_vendor(self):
        # MSG_VENDOR=aligo: 알리고에서 승인된 템플릿 문구를 받아 변수를 채워 보냄. 솔라피 값은 그대로 둬도 안 씀
        notify, bizmsg = self.site.notify, self.site.notify.bizmsg
        notify.ASYNC = False
        bizmsg._aligo_templates.clear()
        calls = []
        tpl = {'templtCode': 'AT1', 'templtName': '제보 접수', 'templtTitle': '제보가 접수됐어요',
               'templtContent': '#{이름}님, 제보가 접수됐습니다.\n\n■ 접수번호: #{접수번호}\n■ 제목: #{제목}',
               'buttons': [{'ordering': '1', 'name': '진행 상황 보기', 'linkType': 'WL', 'linkTypeName': '웹링크', 'linkMo': 'https://soboru.co.kr/lookup', 'linkPc': 'https://soboru.co.kr/lookup'}]}

        def fake(url, payload, headers=None, form=False):
            calls.append((url, payload, form))
            if 'template/list' in url:
                return {'code': 0, 'message': '성공', 'list': [tpl]}
            return {'code': 0, 'message': '성공'} if 'kakaoapi' in url else {'result_code': '1', 'message': 'success'}
        keys = {'MSG_VENDOR': 'aligo', 'ALIGO_API_KEY': 'ak', 'ALIGO_USER_ID': 'soboru', 'ALIGO_SENDER_KEY': 'sk', 'ALIGO_SENDER': '02-749-7515',
                'ALIGO_KAKAO_TPL_RECEIVED': 'AT1', 'KAKAO_TPL_RECEIVED': 'SOLAPI-ID', 'SOLAPI_API_KEY': 'k', 'SOLAPI_API_SECRET': 's', 'SOLAPI_PFID': 'pf'}
        with patch.dict(os.environ, keys):
            self.assertTrue(notify.kakao_ready('received'))
            self.assertFalse(notify.kakao_ready('status'))  # 알리고 템플릿이 없으면 솔라피 ID가 있어도 꺼짐
            with patch.object(bizmsg, 'http_post', side_effect=fake):
                notify.send_kakao('010-2222-3333', 'received', {'name': '김소비', 'receipt': 'R-1', 'subject': '알리고 제보', 'status': '접수'})
                notify.send_kakao('010-2222-3333', 'received', {'name': '이소비', 'receipt': 'R-2', 'subject': '두번째', 'status': '접수'})
                notify.send_sms('010-9999-8888', '새 제보')
        self.assertEqual([c[0] for c in calls], ['https://kakaoapi.aligo.in/akv10/template/list/', 'https://kakaoapi.aligo.in/akv10/alimtalk/send/',
                                                 'https://kakaoapi.aligo.in/akv10/alimtalk/send/', 'https://apis.aligo.in/send/'])  # 템플릿은 한 번만 받아 옴
        self.assertTrue(all(c[2] for c in calls))
        sent = calls[1][1]
        self.assertEqual((sent['tpl_code'], sent['senderkey'], sent['sender'], sent['receiver_1']), ('AT1', 'sk', '027497515', '01022223333'))
        self.assertEqual(sent['message_1'], '김소비님, 제보가 접수됐습니다.\n\n■ 접수번호: R-1\n■ 제목: 알리고 제보')
        self.assertEqual(sent['emtitle_1'], '제보가 접수됐어요')
        self.assertEqual(json.loads(sent['button_1'])['button'][0]['linkMo'], 'https://soboru.co.kr/lookup')
        self.assertNotIn('failover', sent)
        self.assertEqual((calls[3][1]['sender'], calls[3][1]['receiver'], calls[3][1]['msg']), ('027497515', '01099998888', '새 제보'))
        # 실패 응답은 오류로
        with patch.dict(os.environ, keys), patch.object(bizmsg, 'http_post', return_value={'code': -99, 'message': '발신프로필 오류'}):
            with self.assertRaisesRegex(RuntimeError, '발신프로필 오류'):
                notify.send_kakao('010-2222-3333', 'received', {'name': '김', 'receipt': 'R', 'subject': 'S', 'status': ''})
        bizmsg._aligo_templates.clear()
        notify.ASYNC = True

    def test_admin_new_case_alert(self):
        notify = self.site.notify
        notify.ASYNC = False
        sms, mails = [], []
        base = {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '알림상점', 'subject': '운영자 알림 제보', 'description': 'C', 'reporter_name': '김소비',
                'phone': '010-2222-3333', 'request_text': 'D', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234',
                'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'secret'}
        keys = {'SMTP_HOST': 'smtp.example.com', 'SMTP_USER': 'bot@example.com', 'SMTP_PASSWORD': 'pw', 'ADMIN_ALERT_EMAIL': 'boss@example.com, ops@example.com',
                'TELEGRAM_BOT_TOKEN': '123:abc', 'TELEGRAM_CHAT_ID': '-1001',
                'SOLAPI_API_KEY': 'k', 'SOLAPI_API_SECRET': 's', 'SOLAPI_SENDER': '02-123-4567', 'ADMIN_ALERT_PHONE': '010-9999-8888'}
        admin = self.login_admin()
        before = admin.get('/admin/new-cases').get_json()
        with patch.dict(os.environ, keys), patch.object(notify, 'http_post', side_effect=lambda *a: sms.append(a) or {'ok': True}), \
             patch.object(notify.bizmsg, 'http_post', side_effect=lambda *a, **k: sms.append(a) or {'statusCode': '2000'}), \
             patch.object(notify, 'send_email', side_effect=lambda *a, **k: mails.append(a + (k.get("html"),))):
            self.post_form(self.client, '/report', base)
        self.assertEqual([m[0] for m in mails], ['boss@example.com', 'ops@example.com'])
        self.assertIn('새 제보: 운영자 알림 제보', mails[0][1])
        self.assertIn('/admin/reports/', mails[0][2])
        self.assertIn('김소비 (010-2222-3333)', mails[0][2])
        # 알림톡 템플릿이 없으면 제보자에게도 접수 문자를 대신 보냄 (2026-11-08)
        self.assertEqual(sms[0][1]['message']['to'], '01022223333')
        self.assertIn('제보가 접수됐어요', sms[0][1]['message']['text'])
        del sms[0]
        self.assertEqual(sms[0][0], 'https://api.telegram.org/bot123:abc/sendMessage')
        self.assertEqual(sms[0][1]['chat_id'], '-1001')
        self.assertIn('김소비 (010-2222-3333)', sms[0][1]['text'])
        del sms[0]
        self.assertEqual(sms[0][1]['message']['to'], '01099998888')
        self.assertEqual(sms[0][1]['message']['from'], '021234567')
        self.assertIn('알림상점', sms[0][1]['message']['text'])
        self.assertIn('김소비 010-2222-3333', sms[0][1]['message']['text'])
        # 알림톡 템플릿이 있으면 카카오톡으로 (실패하면 문자로 대신)
        with patch.dict(os.environ, dict(keys, SOLAPI_PFID='pf', KAKAO_TPL_ADMIN='TA')), patch.object(notify, 'http_post', side_effect=lambda *a: sms.append(a) or {'ok': True}), \
             patch.object(notify.bizmsg, 'http_post', side_effect=lambda *a, **k: sms.append(a) or {'statusCode': '2000'}), \
             patch.object(notify, 'send_email', side_effect=lambda *a, **k: mails.append(a + (k.get("html"),))):
            self.post_form(self.client, '/report', dict(base, subject='카톡 알림 제보'))
        message = sms[-1][1]['message']
        self.assertEqual(message['kakaoOptions']['templateId'], 'TA')
        self.assertEqual(message['kakaoOptions']['variables']['#{제목}'], '카톡 알림 제보')
        self.assertEqual(message['kakaoOptions']['variables']['#{연락처}'], '010-2222-3333')
        self.assertFalse(message['kakaoOptions']['disableSms'])
        self.assertEqual(message['from'], '021234567')
        del sms[1:], mails[2:]
        # 상태 변경 같은 다른 알림은 운영자에게 가지 않음
        with self.site.conn() as db:
            case_id = db.execute("SELECT id FROM cases WHERE subject='운영자 알림 제보'").fetchone()['id']
            last_id = db.execute("SELECT id FROM cases WHERE subject='카톡 알림 제보'").fetchone()['id']
        # 관리자 화면: 새 제보 확인 주소와 메뉴 숫자
        after = admin.get('/admin/new-cases').get_json()
        self.assertEqual(after['latest'], last_id)
        self.assertEqual(after['count'], before['count'] + 2)
        self.assertEqual(after['subject'], '카톡 알림 제보')
        page = admin.get('/admin').get_data(as_text=True)
        self.assertIn('id="ad-new-badge"', page)
        self.assertIn('브라우저 알림 켜기', page)
        self.assertIn('운영자 메일', admin.get('/admin/reports/%d' % case_id).get_data(as_text=True))
        # 운영자 2026-11-08: 진행 단계가 바뀔 때도 운영자(메일·텔레그램·문자)와 제보자에게 알림
        texts = []
        with patch.dict(os.environ, keys), patch.object(notify, 'http_post', side_effect=lambda *a: sms.append(a) or {'ok': True}), \
             patch.object(notify.bizmsg, 'http_post', side_effect=lambda *a, **k: texts.append(a) or {'statusCode': '2000'}), \
             patch.object(notify, 'send_email', side_effect=lambda *a, **k: mails.append(a + (k.get("html"),))):
            mails.clear(); sms.clear()
            self.post_form(admin, '/admin/reports/%d' % case_id, {'form': 'settings', 'status': '검토 중', 'assignee': ''})
        self.assertEqual([m[0] for m in mails], ['boss@example.com', 'ops@example.com'])
        self.assertIn('단계 변경', mails[0][1])
        self.assertEqual(len(sms), 1)
        self.assertEqual(sorted(t[1]['message']['to'] for t in texts), ['01022223333', '01099998888'])
        # 로그인 안 했으면 확인 주소는 막힘
        self.assertEqual(self.site.app.test_client().get('/admin/new-cases').status_code, 401)
        notify.ASYNC = True

    def test_company_members(self):
        # 기업 회원은 기본으로 꺼져 있음: 화면은 404, 하단 링크 없음
        self.assertEqual(self.client.get('/biz/login').status_code, 404)
        self.assertNotIn('/biz/login', self.client.get('/').get_data(as_text=True))
        self.site.BIZ_ON = True
        self.addCleanup(setattr, self.site, 'BIZ_ON', False)
        notify = self.site.notify
        notify.ASYNC = False
        # 1) 기업 가입: 사업자번호 검증번호가 틀리면 거절
        biz = self.site.app.test_client()
        form = {'company_name': '주식회사 테스트몰', 'biz_no': '123-45-67890', 'contact_name': '김담당', 'contact_phone': '02-123-4567',
                'contact_email': 'cs@testmall.co.kr', 'login_id': 'testmall', 'password': 'abcd1234', 'password2': 'abcd1234', 'agree': 'on'}
        self.assertEqual(self.post_form(biz, '/biz/signup', form).status_code, 400)
        self.assertEqual(self.post_form(biz, '/biz/signup', dict(form, biz_no='123-45-67891')).status_code, 302)
        self.assertIn('가입 신청을 확인하고 있어요', biz.get('/biz').get_data(as_text=True))
        self.assertEqual(self.post_form(self.site.app.test_client(), '/biz/signup', dict(form, biz_no='1234567891', login_id='other')).status_code, 400)
        with self.site.conn() as db:
            company_id = db.execute("SELECT id FROM companies WHERE biz_no='1234567891'").fetchone()['id']
        # 2) 제보 둘: 기업 전달 동의 / 미동의
        base = {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '테스트몰', 'description': '환불이 안 돼요', 'reporter_name': '홍길동',
                'phone': '010-7777-8888', 'contact': 'reporter@example.com', 'request_text': '환불', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234',
                'use_consent': 'on', 'truth': 'on', 'visibility': 'public'}
        self.post_form(self.client, '/report', dict(base, subject='기업 전달 동의 제보', share_company='on'))
        self.post_form(self.client, '/report', dict(base, subject='기업 전달 미동의 제보', share_company='on'))
        with self.site.conn() as db:
            db.execute("UPDATE cases SET share_company=0 WHERE subject='기업 전달 미동의 제보'")  # 예전 제보처럼 미동의
            shared = db.execute("SELECT id FROM cases WHERE subject='기업 전달 동의 제보'").fetchone()['id']
            private = db.execute("SELECT id FROM cases WHERE subject='기업 전달 미동의 제보'").fetchone()['id']
        # 승인 전에는 제보 화면에 못 들어감
        self.assertEqual(biz.get('/biz/case/%d' % shared).status_code, 302)
        # 3) 관리자 승인 → 제보에 연결 (★ 추천), 미동의 제보는 연결 불가
        admin = self.login_admin()
        self.assertIn('주식회사 테스트몰', admin.get('/admin/companies').get_data(as_text=True))
        self.post_form(admin, '/admin/companies', {'id': company_id, 'action': 'approve', 'manual': '1'})
        self.post_form(admin, '/admin/companies', {'id': company_id, 'action': 'aliases', 'aliases': 'TestMall, 테스트 쇼핑'})
        self.assertIn('★ 주식회사 테스트몰', admin.get('/admin/reports/%d' % shared).get_data(as_text=True))
        self.post_form(admin, '/admin/reports/%d' % shared, {'form': 'company', 'company_id': company_id})
        # 미동의 제보도 기업 페이지에는 모을 수 있지만 기업 담당자 화면에는 안 감
        self.post_form(admin, '/admin/reports/%d' % private, {'form': 'company', 'company_id': company_id})
        self.assertEqual(self.post_form(admin, '/admin/reports/%d' % private, {'form': 'forward'}).status_code, 400)
        self.post_form(admin, '/admin/reports/%d' % shared, {'form': 'publish_review', 'decision': 'approve'})
        # 4) 기업 화면: 연결된 동의 제보만, 제보자 정보 없음
        home = biz.get('/biz').get_data(as_text=True)
        self.assertIn('기업 전달 동의 제보', home)
        self.assertNotIn('미동의', home)
        page = biz.get('/biz/case/%d' % shared).get_data(as_text=True)
        self.assertIn('환불이 안 돼요', page)
        for secret in ('홍길동', '010-7777-8888', 'reporter@example.com'):
            self.assertNotIn(secret, page)
        self.assertEqual(biz.get('/biz/case/%d' % private).status_code, 404)
        # 5) 답변 → 단계 '기업 답변 도착', 제보자에게 알림, 공개는 운영자 확인 뒤
        mails = []
        with patch.dict(os.environ, {'SMTP_HOST': 'smtp.example.com', 'SMTP_USER': 'bot@example.com', 'SMTP_PASSWORD': 'pw'}), \
             patch.object(notify, 'send_email', side_effect=lambda *a, **k: mails.append(a + (k.get("html"),))):
            self.post_form(biz, '/biz/case/%d' % shared, {'response': '내일까지 환불 처리하겠습니다.'})
        self.assertIn('업체가 답변했습니다', mails[-1][2])
        with self.site.conn() as db:
            case = db.execute('SELECT status FROM cases WHERE id=?', (shared,)).fetchone()
            msg = db.execute("SELECT id,public FROM messages WHERE case_id=? AND author='기업 답변'", (shared,)).fetchone()
        self.assertEqual(case['status'], '기업 답변 도착')
        self.assertEqual(msg['public'], 0)
        self.assertIn('답변 완료 <b>1</b>', biz.get('/biz?tab=done').get_data(as_text=True))
        self.assertNotIn('내일까지 환불', self.client.get('/reports/%d' % shared).get_data(as_text=True))
        self.post_form(admin, '/admin/reports/%d' % shared, {'form': 'answer_public', 'message_id': msg['id'], 'public': '1'})
        public = self.client.get('/reports/%d' % shared).get_data(as_text=True)
        self.assertIn('내일까지 환불 처리하겠습니다.', public)
        self.assertIn('주식회사 테스트몰', public)
        # 인증 기업 계정이 직접 쓴 답변에는 인증 표시, 기업 페이지에도 인증 기업 배지와 설명
        self.assertIn('인증 기업 계정이 직접 등록', public)
        co_page = self.client.get('/companies/%d' % company_id).get_data(as_text=True)
        self.assertIn('co-badge verified', co_page)
        self.assertIn('서비스 품질을 보증하는 표시는 아니에요', co_page)
        # 대표 미리보기: 관리자 로그인으로 그 기업 화면을 보되 답변은 못 함
        admin.post('/admin/companies/%d/preview' % company_id, data={'_csrf': self.csrf(admin, '/admin')})
        preview = admin.get('/biz').get_data(as_text=True)
        self.assertIn('대표 미리보기', preview)
        self.assertIn('답변 완료 <b>1</b>', preview)
        admin.post('/biz/case/%d' % shared, data={'_csrf': self.csrf(admin, '/biz/case/%d' % shared), 'response': '미리보기 답변'})
        with self.site.conn() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM messages WHERE body='미리보기 답변'").fetchone())
        admin.post('/biz/preview/end', data={'_csrf': self.csrf(admin, '/admin')})
        self.assertEqual(admin.get('/biz').status_code, 302)
        # 관리자가 아니면 미리보기 주소를 눌러도 안 됨
        self.assertEqual(self.client.post('/admin/companies/%d/preview' % company_id, data={'_csrf': self.csrf(self.client, '/report')}).status_code, 302)
        self.assertEqual(self.client.get('/biz').status_code, 302)
        # 대표 마스터 계정: 관리자에서 만들고, 기업 로그인 화면으로 들어가 모든 기업을 골라 봄 (보기 전용)
        self.post_form(admin, '/admin/companies', {'action': 'master', 'master_id': 'testmall', 'password': 'master123', 'password2': 'master123'})
        with self.site.conn() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM admin_settings WHERE key='biz_master_id'").fetchone())  # 기업 아이디와 겹치면 안 됨
        self.post_form(admin, '/admin/companies', {'action': 'master', 'master_id': 'boss', 'password': 'master123', 'password2': 'master123'})
        master = self.site.app.test_client()
        self.assertEqual(self.post_form(master, '/biz/login', {'login_id': 'boss', 'password': 'wrong1234'}).status_code, 401)
        self.post_form(master, '/biz/login', {'login_id': 'boss', 'password': 'master123'})
        self.assertIn('주식회사 테스트몰', master.get('/biz').get_data(as_text=True))
        master.post('/biz/master/company', data={'_csrf': self.csrf(master, '/biz'), 'company_id': company_id})
        self.assertIn('기업 전달 동의 제보', master.get('/biz?tab=done').get_data(as_text=True))
        master.post('/biz/case/%d' % shared, data={'_csrf': self.csrf(master, '/biz/case/%d' % shared), 'response': '마스터 답변'})
        with self.site.conn() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM messages WHERE body='마스터 답변'").fetchone())
        self.assertEqual(self.post_form(self.site.app.test_client(), '/biz/signup', dict(form, biz_no='2208123455', login_id='boss')).status_code, 400)
        # 비밀번호를 다시 저장하면 이전 마스터 로그인은 끊김
        self.post_form(admin, '/admin/companies', {'action': 'master', 'master_id': 'boss', 'password': 'master456', 'password2': 'master456'})
        self.assertEqual(master.get('/biz').status_code, 302)
        # 6) 중지하면 바로 로그아웃
        self.post_form(admin, '/admin/companies', {'id': company_id, 'action': 'stop'})
        self.assertEqual(biz.get('/biz').status_code, 302)
        notify.ASYNC = True
        self.assertIn('기업 회원 이용약관', self.client.get('/biz/terms').get_data(as_text=True))

    def test_damage_groups(self):
        # 공동 대응은 기본으로 꺼져 있음: 주소는 404, 메인·제보 화면에 안내 없음
        self.assertEqual(self.client.get('/groups').status_code, 404)
        self.assertNotIn('공동 대응', self.client.get('/').get_data(as_text=True))
        self.site.GROUPS_ON = True
        self.addCleanup(setattr, self.site, 'GROUPS_ON', False)
        with self.site.conn() as db:
            for i, (subject, public) in enumerate((('OO쇼핑 환불 지연', 1), ('OO쇼핑 환불 안 돼요', 0))):
                db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           ('G%d' % i, 'x', '배송·환불', 'OO쇼핑', subject, '본문 비공개 내용', '환불', '2026-10-09', public, public))
            first, second = [r['id'] for r in db.execute('SELECT id FROM cases ORDER BY id')]
        # 공개 제보에는 '나도 겪었어요' 공감과 함께, 공개 제보·비밀글 비밀번호 화면 모두 '공동 대응 제안하기'로 안내
        self.assertIn('나도 겪었어요', self.client.get('/reports/%d' % first).get_data(as_text=True))
        self.assertNotIn('나도 겪었어요', self.client.get('/reports/%d/mine' % second).get_data(as_text=True))
        self.assertIn('/groups/new?company=OO', self.client.get('/reports/%d' % first).get_data(as_text=True))
        self.assertIn('/groups/new?company=OO', self.client.get('/reports/%d/mine' % second).get_data(as_text=True))
        # 1) 소비자 제안 → 검토 중(제안자·관리자만 보임), 제안자는 첫 참여자
        proposer = self.site.app.test_client()
        join = {'name': '박소비', 'phone': '010-3333-4444', 'detail': '9월에 반품했는데 아직 환불이 없어요', 'amount': '약 5만 원', 'consent': 'on'}
        self.assertEqual(self.post_form(proposer, '/groups/new', dict(join, company='OO쇼핑', title='짧')).status_code, 400)
        made = self.post_form(proposer, '/groups/new', dict(join, company='OO쇼핑', title='OO쇼핑 반품 후 환불 지연', share_consent='on'))
        gid = int(made.headers['Location'].rsplit('/', 1)[1])
        self.assertIn('센터가 제안 내용을 확인하고 있어요', proposer.get('/groups/%d' % gid).get_data(as_text=True))
        self.assertEqual(self.client.get('/groups/%d' % gid).status_code, 404)
        self.assertNotIn('OO쇼핑 반품 후 환불 지연', self.client.get('/groups').get_data(as_text=True))
        # 2) 관리자 확인 → 공개, 제보 연결
        admin = self.login_admin()
        self.assertIn('소비자 제안', admin.get('/admin/groups').get_data(as_text=True))
        self.post_form(admin, '/admin/groups/%d' % gid, {'action': 'approve'})
        self.post_form(admin, '/admin/groups/%d' % gid, {'action': 'link', 'case_ids': '%d, %d' % (first, second)})
        # 3) 공개: 목록·배너·진행 막대(1/50), 같은 업체 제보에서 '같이 참여하기'
        self.assertIn('OO쇼핑 반품 후 환불 지연', self.client.get('/groups').get_data(as_text=True))
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('href="/groups">공동 대응</a>', home)  # 소보루 머리글 제보 메뉴 (예전 홈의 공동 대응 묶음은 뺌)
        self.assertIn('공동 대응 참여 모집', self.client.get('/reports').get_data(as_text=True))
        group = self.client.get('/groups/%d' % gid).get_data(as_text=True)
        self.assertIn('<b>1</b>명 참여', group)
        self.assertIn('목표 50명', group)
        self.assertIn('9월에 반품했는데 아직 환불이 없어요', group)  # 제안 내용이 피해 설명으로
        self.assertNotIn('박소비', group)
        self.assertNotIn('본문 비공개 내용', group)
        self.assertIn('같이 참여하기', self.client.get('/reports/%d/mine' % second).get_data(as_text=True))
        # 4) 다른 소비자 참여: 필수 동의 없으면 거절
        visitor = self.site.app.test_client()
        other = dict(join, name='이소비')
        other.pop('consent')
        self.assertEqual(self.post_form(visitor, '/groups/%d' % gid, other).status_code, 400)
        self.post_form(visitor, '/groups/%d' % gid, dict(other, consent='on'))
        self.assertIn('<b>2</b>명 참여', self.client.get('/groups/%d' % gid).get_data(as_text=True))
        detail = admin.get('/admin/groups/%d' % gid).get_data(as_text=True)
        self.assertIn('박소비', detail)
        self.assertIn('변호사·기관 제공 동의', detail)
        self.assertIn('변호사·기관 제공 미동의', detail)
        self.assertIn('010-3333-4444', admin.get('/admin/groups/%d/members.csv' % gid).get_data(as_text=True))
        self.assertEqual(self.client.get('/admin/groups/%d/members.csv' % gid).status_code, 302)
        # 5) 목표 인원을 2명으로 바꾸면 '목표 달성', 종료하면 신청 불가
        self.post_form(admin, '/admin/groups/%d' % gid, {'action': 'save', 'title': 'OO쇼핑 반품 후 환불 지연', 'company': 'OO쇼핑', 'summary': 'x', 'guide': '', 'status': 'open', 'target': '2'})
        self.assertIn('목표 인원이 모였어요', self.client.get('/groups/%d' % gid).get_data(as_text=True))
        self.post_form(admin, '/admin/groups/%d' % gid, {'action': 'save', 'title': 'OO쇼핑 반품 후 환불 지연', 'company': 'OO쇼핑', 'summary': 'x', 'guide': '', 'status': 'closed', 'target': '2'})
        late = self.site.app.test_client()
        self.assertIn('지금은 참여 신청을 받지 않아요', late.get('/groups/%d' % gid).get_data(as_text=True))
        self.assertEqual(late.post('/groups/%d' % gid, data=dict(join, _csrf=self.csrf(late, '/report'))).status_code, 400)
        # 6) 반려된 제안은 안 보임
        made = self.post_form(self.site.app.test_client(), '/groups/new', dict(join, company='XX몰', title='XX몰 나쁜 회사 망해라'))
        bad = int(made.headers['Location'].rsplit('/', 1)[1])
        self.post_form(admin, '/admin/groups/%d' % bad, {'action': 'reject'})
        self.assertEqual(self.client.get('/groups/%d' % bad).status_code, 404)

    def test_admin_deletes_report(self):
        admin = self.login_admin()
        stored = 'deltest' + '0' * 33 + '.png'
        (self.site.UPLOAD / stored).write_bytes(b'x')
        with self.site.conn() as db:
            db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created) VALUES('CJ-DEL','x','배송·환불','가게','지울 제보','내용','환불','2026-10-09T10:00:00')")
            case_id = db.execute("SELECT id FROM cases WHERE receipt='CJ-DEL'").fetchone()['id']
            db.execute('INSERT INTO attachments(case_id,stored,original) VALUES(?,?,?)', (case_id, stored, 'a.png'))
            db.execute("INSERT INTO messages(case_id,author,body,created) VALUES(?,'센터','안녕하세요','2026-10-09T10:00:00')", (case_id,))
        path = '/admin/reports/%d' % case_id
        self.assertIn('제보 삭제', admin.get(path).get_data(as_text=True))
        self.assertEqual(self.post_form(admin, path, {'form': 'delete'}).status_code, 400)  # 확인 체크 없이는 안 지움
        done = self.post_form(admin, path, {'form': 'delete', 'confirm': '1'})
        self.assertEqual(done.headers['Location'], '/admin/reports')
        self.assertEqual(admin.get(path).status_code, 404)
        with self.site.conn() as db:
            for table in ('attachments', 'messages'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table} WHERE case_id=?', (case_id,)).fetchone()[0], 0)
        self.assertFalse((self.site.UPLOAD / stored).exists())

    def test_lookup_with_password(self):
        # 예전 '조회 코드' 안내는 어디에도 안 남음
        for path in ('/lookup', '/guide', '/process', '/report', '/terms', '/privacy', '/faq'):
            self.assertNotIn('조회 코드', self.client.get(path).get_data(as_text=True), path)
        base = {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': 'A', 'description': 'C', 'reporter_name': '홍길동', 'phone': '010-5555-1234',
                'request_text': 'D', 'consent': 'on', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'secret'}
        # 비밀번호가 없거나 확인이 다르면 접수 안 됨
        self.assertEqual(self.post_form(self.client, '/report', dict(base, subject='x', lookup_pw='12', lookup_pw2='12')).status_code, 400)
        self.assertEqual(self.post_form(self.client, '/report', dict(base, subject='x', lookup_pw='1234', lookup_pw2='4321')).status_code, 400)
        done = self.post_form(self.client, '/report', dict(base, subject='비밀 제보 하나', lookup_pw='2580', lookup_pw2='2580')).get_data(as_text=True)
        self.assertIn('조회 비밀번호로', done)
        self.post_form(self.client, '/report', dict(base, subject='비밀 제보 둘', lookup_pw='2580', lookup_pw2='2580'))
        self.post_form(self.client, '/report', dict(base, subject='다른 비번 제보', lookup_pw='0000', lookup_pw2='0000'))
        with self.site.conn() as db:
            first = db.execute("SELECT id,pw_hash FROM cases WHERE subject='비밀 제보 하나'").fetchone()
        self.assertNotIn('2580', first['pw_hash'])
        # 목록에서 비밀글을 누르면 비밀번호 창 → 맞으면 내 제보
        reports = self.client.get('/reports').get_data(as_text=True)
        self.assertIn('href="/reports/%d/mine"' % first['id'], reports)
        visitor = self.site.app.test_client()
        page = visitor.get('/reports/%d/mine' % first['id']).get_data(as_text=True)
        self.assertNotIn('환불이', page)  # 비밀번호 창에는 제목만, 본문은 없음
        self.assertEqual(self.post_form(visitor, '/reports/%d/mine' % first['id'], {'password': '0000'}).status_code, 401)
        self.assertEqual(visitor.get('/case').status_code, 302)
        opened = self.post_form(visitor, '/reports/%d/mine' % first['id'], {'password': '2580'})
        self.assertIn('/case', opened.headers['Location'])
        self.assertIn('비밀 제보 하나', visitor.get('/case').get_data(as_text=True))
        # 휴대폰 번호 + 비밀번호: 같은 비번 제보가 여럿이면 고르는 목록, 다른 비번 제보는 안 보임
        other = self.site.app.test_client()
        found = self.post_form(other, '/lookup', {'mode': 'phone', 'phone': '010 5555 1234', 'password': '2580'}).get_data(as_text=True)
        self.assertIn('비밀 제보 하나', found)
        self.assertIn('비밀 제보 둘', found)
        self.assertNotIn('다른 비번 제보', found)
        other.post('/lookup/%d' % first['id'], data={'_csrf': self.csrf(other, '/lookup')})
        self.assertIn('비밀 제보 하나', other.get('/case').get_data(as_text=True))
        stranger = self.site.app.test_client()
        stranger.post('/lookup/%d' % first['id'], data={'_csrf': self.csrf(stranger, '/lookup')})
        self.assertEqual(stranger.get('/case').status_code, 302)
        # 관리자가 새 비밀번호를 정해 주면 그걸로 열림
        admin = self.login_admin()
        self.post_form(admin, '/admin/reports/%d' % first['id'], {'form': 'lookup_pw', 'lookup_pw': '7777'})
        again = self.site.app.test_client()
        self.assertEqual(self.post_form(again, '/reports/%d/mine' % first['id'], {'password': '2580'}).status_code, 401)
        self.assertEqual(self.post_form(again, '/reports/%d/mine' % first['id'], {'password': '7777'}).status_code, 302)

    def test_home_shows_latest_and_reports_page_lists_all(self):
        with self.site.conn() as db:
            for i in range(25):
                db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,1,1)',
                           ('R%d' % i, 'x', '기타', '업체', '공개 제보 %02d' % i, '내용', '요청', '2026-10-09'))
        home = self.client.get('/').get_data(as_text=True)
        live = home.split('class="nn-sec nn-live')[1].split('</section>')[0]
        self.assertEqual(live.count('class="nn-vc-card" href="/reports/'), 6)  # 방금 들어온 제보 6건 (콘텐츠 카드)
        self.assertIn('공개 제보 24', home); self.assertIn('class="nn-vc-ex">내용<', live)  # 공개 제보는 본문 앞부분도
        with self.site.conn() as db:
            top = db.execute('SELECT MAX(id) FROM cases').fetchone()[0]
            for k in range(3): db.execute("INSERT INTO board_votes(kind,target,voter,created) VALUES('metoo',?,?,'x')", ('case:%d' % top, 'v%d' % k))
        self.assertIn('나도 겪었어요 3</span>', self.client.get('/').get_data(as_text=True))  # '나도 겪었어요' 수
        self.assertNotIn('공개 제보 04<', home)
        self.assertIn('href="/reports">', home)  # 메뉴와 전체 보기 링크
        live = self.client.get('/reports/latest')
        self.assertEqual(live.headers['Cache-Control'], 'no-store')
        self.assertEqual(live.get_data(as_text=True).count('class="case-link"'), self.site.HOME_LATEST)
        page1 = self.client.get('/reports').get_data(as_text=True)
        self.assertEqual(page1.count('class="nn-vc-card'), 20)
        self.assertIn('aria-current="page">제보 목록</a>', page1)
        page2 = self.client.get('/reports?page=2').get_data(as_text=True)
        self.assertEqual(page2.count('class="nn-vc-card'), 5)
        self.assertIn('공개 제보 00', page2)

    def test_search_engine_support(self):
        robots = self.client.get('/robots.txt').get_data(as_text=True)
        self.assertIn('Disallow: /admin', robots)
        self.assertIn('Sitemap: http://localhost/sitemap.xml', robots)
        with self.site.conn() as db:
            db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,1,1)', ('S1', 'x', '기타', '업체', '공개 제목', '공개 본문 내용입니다', '요청', '2026-10-09T10:00:00'))
            db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,0,0)', ('S2', 'x', '기타', '업체', '비밀 제목', '비밀', '요청', '2026-10-09T10:00:00'))
            public_id = db.execute("SELECT id FROM cases WHERE receipt='S1'").fetchone()['id']
            secret_id = db.execute("SELECT id FROM cases WHERE receipt='S2'").fetchone()['id']
        sitemap = self.client.get('/sitemap.xml')
        self.assertEqual(sitemap.mimetype, 'application/xml')
        xml = sitemap.get_data(as_text=True)
        self.assertIn('<loc>http://localhost/reports/%d</loc><lastmod>2026-10-09</lastmod>' % public_id, xml)
        self.assertNotIn('/reports/%d<' % secret_id, xml)
        self.assertNotIn('/admin', xml)
        for path in ('/companies</loc>', '/ask</loc>', '/life</loc>', '/faq</loc>'): self.assertIn(path, xml)
        self.assertNotIn('/types</loc>', xml)  # 메뉴에서 뺀 안내는 사이트맵에서도 뺌
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('<meta name="description" content="소비자 피해 제보부터 제품·업체 리뷰와 추천', home)
        self.assertNotIn('naver-site-verification', home)
        detail = self.client.get('/reports/%d' % public_id).get_data(as_text=True)
        self.assertIn('<meta name="description" content="공개 본문 내용입니다">', detail)
        self.assertIn('<meta property="og:title" content="공개 제목 | 소보루">', detail)
        admin = self.login_admin()
        admin.post('/admin/content', data={'_csrf': self.csrf(admin, '/admin/content'), 'section': 'seo',
            'seo.naver_verification': '<meta name="naver-site-verification" content="abc123naver" />',
            'seo.google_verification': 'goog-XYZ_789', 'seo.daum_robots': 'DaumWebMasterTool:pin:id',
            'seo.facebook_verification': '<meta name="facebook-domain-verification" content="fbdv123abc" />'})
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('<meta name="naver-site-verification" content="abc123naver">', home)
        self.assertIn('<meta name="google-site-verification" content="goog-XYZ_789">', home)
        self.assertIn('<meta name="facebook-domain-verification" content="fbdv123abc">', home)
        self.assertTrue(self.client.get('/robots.txt').get_data(as_text=True).startswith('#DaumWebMasterTool:pin:id'))
        self.assertIn('noindex', admin.get('/admin').get_data(as_text=True))
        # 네이버 RSS 제출용 피드와 채널 정보 마크업
        rss = self.client.get('/rss.xml')
        self.assertEqual(rss.mimetype, 'application/rss+xml')
        feed = rss.get_data(as_text=True)
        self.assertIn('<link>http://localhost/reports/%d</link>' % public_id, feed)
        self.assertIn('공개 본문 내용입니다', feed)
        self.assertNotIn('비밀 제목', feed)
        self.assertIn('application/rss+xml', home)
        admin.post('/admin/content', data={'_csrf': self.csrf(admin, '/admin/content'), 'section': 'seo',
            'seo.channels': 'https://blog.naver.com/soboru\nhttps://www.instagram.com/soboru'})
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('"sameAs": ["https://blog.naver.com/soboru", "https://www.instagram.com/soboru"]', home)

    def test_admin_list_editor(self):
        self.old_guide()
        self.assertEqual(self.client.get('/admin/lists').status_code, 302)
        guide = self.client.get('/guide').get_data(as_text=True)
        self.assertEqual(guide.count('class="evidence-topic"'), 10)
        self.assertIn('<summary><span>가전·IT</span>', guide)
        self.assertIn('<dt>결제한 금액</dt>', guide)
        self.assertEqual(self.client.get('/faq').get_data(as_text=True).count('class="faq-item"'), 4)
        admin = self.login_admin()
        page = admin.get('/admin/lists').get_data(as_text=True)
        self.assertIn('id="list-guide_topics"', page)
        token = self.csrf(admin, '/admin/lists')
        # 항목 순서를 바꾸고, 하나를 지우고, 새로 추가 (빈 항목은 무시)
        admin.post('/admin/lists', data={'_csrf': token, 'list': 'faq', 'q': ['새 질문', '제보하면 바로 해결되나요?', ''], 'a': ['새 답변\n둘째 줄', '아니요', '']})
        faq = self.client.get('/faq').get_data(as_text=True)
        self.assertEqual(faq.count('class="faq-item"'), 2)
        self.assertLess(faq.index('새 질문'), faq.index('제보하면 바로 해결되나요?'))
        self.assertNotIn('어떤 자료를 첨부하면 좋나요?', faq)
        # 제보 유형: 추가한 유형으로 제보 가능, 지운 유형은 거부
        admin.post('/admin/lists', data={'_csrf': token, 'list': 'report_categories', 'name': ['배송·환불', '중고거래']})
        report = self.client.get('/report').get_data(as_text=True)
        self.assertIn('<option >중고거래</option>', report.replace('<option  >', '<option >'))
        self.assertNotIn('상품·품질', report)
        token2 = self.csrf(self.client, '/report')
        base = {'_csrf': token2, 'industry': '기타', 'company': 'A', 'subject': 'B', 'description': 'C', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': 'D', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'secret'}
        self.assertEqual(self.client.post('/report', data={**base, 'category': '상품·품질'}).status_code, 400)
        self.assertEqual(self.client.post('/report', data={**base, 'category': '중고거래'}).status_code, 200)
        # 잘못된 입력은 저장하지 않고, 입력한 내용을 그대로 다시 보여 줌
        bad = admin.post('/admin/lists', data={'_csrf': token, 'list': 'board_categories', 'name': ['자유', '자유']})
        self.assertEqual(bad.status_code, 400)
        self.assertIn('같은 이름이 두 번', bad.get_data(as_text=True))
        self.assertEqual(admin.post('/admin/lists', data={'_csrf': token, 'list': 'board_categories', 'name': ['']}).status_code, 400)
        self.assertIn('꿀팁', self.client.get('/board').get_data(as_text=True))
        # 기본값으로 되돌리기
        admin.post('/admin/lists', data={'_csrf': token, 'list': 'faq', 'reset': '1'})
        self.assertEqual(self.client.get('/faq').get_data(as_text=True).count('class="faq-item"'), 4)

    def test_legacy_fixed_slots_carry_over(self):
        with self.site.conn() as db:
            db.execute("INSERT INTO site_content(key,value,updated) VALUES('faq.q2','바뀐 두번째 질문','x'),('faq.q5','추가했던 다섯번째','x'),('faq.a5','답','x'),('process.step3_title','','x')")
        faq = self.client.get('/faq').get_data(as_text=True)
        self.assertIn('바뀐 두번째 질문', faq)
        self.assertIn('추가했던 다섯번째', faq)
        self.assertEqual(faq.count('class="faq-item"'), 5)
        process = self.client.get('/process').get_data(as_text=True)
        self.assertEqual(process.count('class="process-card"'), 2)

    def test_screen_editor_edits_every_soboru_text(self):
        # 화면 편집: 소보루 화면 글자(홈 큰 문구·머리글 메뉴·아래 탭·레터·생활정보·소보루 픽)를 편집 모드에서 눌러 고치고, 페이지별 문구 목록에서도 고침
        admin = self.login_admin()
        token = self.csrf(admin, '/admin/screens')
        admin.post('/admin/edit-mode', data={'_csrf': token, 'on': '1', 'next': '/'})
        pages = {'/': ('home.intro_title', 'home.live_title', 'home.pick_title', 'home.answer_eyebrow', 'sb.nav_home', 'sb.tab_home', 'common.ft_why', 'letter.card_title'),
                 '/life': ('life.title', 'life.cat_all', 'letter.subscribe'), '/board': ('cm.title', 'cm.pick_title'), '/letter': ('letter.sub_t', 'letter.sub_btn', 'letter.archive_title'),
                 '/companies': ('sb.nav_companies',), '/ask': ('ask.h1',)}
        for path, keys in pages.items():
            page = admin.get(path).get_data(as_text=True)
            self.assertNotRegex(page, '[\ue000-\ue002]', path)
            for key in keys:
                self.assertIn('data-k="%s"' % key, page, (path, key))
        self.assertIn('href="/admin/screens">화면 편집</a>', admin.get('/').get_data(as_text=True))  # 편집 막대에서 바로 화면 편집으로
        # 편집 모드에서 눌러 저장: HTML은 글자로, {자리}는 화면 값으로
        self.assertTrue(admin.post('/admin/inline', data={'_csrf': token, 'key': 'home.intro_title', 'value': '소보루 <b>새 얼굴</b>'}).get_json()['ok'])
        self.assertTrue(admin.post('/admin/inline', data={'_csrf': token, 'key': 'home.answer_eyebrow', 'value': '지난 {days}일 기록'}).get_json()['ok'])
        self.assertTrue(admin.post('/admin/inline', data={'_csrf': token, 'key': 'sb.tab_home', 'value': '처음'}).get_json()['ok'])
        self.assertEqual(admin.post('/admin/inline', data={'_csrf': token, 'key': 'home.live_title', 'value': 'x' * 2001}).status_code, 400)  # 길이 제한 그대로
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('소보루 &lt;b&gt;새 얼굴&lt;/b&gt;', home)
        self.assertIn('지난 30일 기록', home)
        self.assertIn('</svg>처음</a>', home)
        self.assertNotIn('data-k=', home)
        # 화면 편집 > 페이지별 문구 목록: 그 페이지 문구만 한 번에 저장, 비우면 기본 문구로
        page = admin.get('/admin/screens').get_data(as_text=True)
        self.assertIn('name="home.intro_sub"', page)
        self.assertIn('name="letter.sub_t"', page)
        self.assertIn('name="sb.nav_life"', page)
        r = admin.post('/admin/screens', data={'_csrf': token, 'page': 'home', 'act': 'texts', 'home.intro_title': '', 'home.pick_title': '오늘의 픽', 'report.submit': '무시돼요'})
        self.assertEqual(r.status_code, 302)
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('오늘의 픽', home)
        self.assertNotIn('새 얼굴', home)
        self.assertIn('제보 접수하기', self.client.get('/report').get_data(as_text=True))  # 다른 페이지 문구는 그대로
        self.assertEqual(admin.post('/admin/screens', data={'_csrf': token, 'page': 'home', 'act': 'texts', 'home.pick_title': 'x' * 2001}).status_code, 400)
        r = admin.post('/admin/screens', data={'_csrf': token, 'page': 'letter', 'act': 'order', 'block': ['archive', 'hero'], 'show_archive': '1', 'show_hero': '1'})
        letter = self.client.get('/letter').get_data(as_text=True)
        self.assertLess(letter.index('lt-archive'), letter.index('lt-hero'))
        self.assertLess(letter.index('lt-hero'), letter.index('lt-feats'))  # 순서표에 없던 묶음은 켠 채로 맨 뒤에 붙음 (화면이 비지 않게)
        for key in ('life', 'board'):
            admin.post('/admin/screens', data={'_csrf': token, 'page': key, 'block': 'head', 'act': 'hide'})
        self.assertNotIn('sb-page-head', self.client.get('/life').get_data(as_text=True))
        self.assertNotIn('cm-head', self.client.get('/board').get_data(as_text=True))
        with self.site.conn() as db: db.execute("DELETE FROM soboru_settings WHERE key LIKE 'blocks:%'")

    def test_jebo_face_shares_reports(self):
        self.enterContext(patch.object(self.site, 'RETIRED_HOSTS', set()))  # 예전 두 사이트 운영 때의 동작 확인 (지금 soboru.co.kr은 막혀 있음)
        # JEBO_HOST(consumerjebo.co.kr)로 들어오면 소비자제보센터 화면, 그 밖은 소보루. 제보는 한 곳에 저장돼 양쪽에 같이 보임
        hosts = {'consumerjebo.co.kr', 'www.consumerjebo.co.kr'}
        self.site.JEBO_HOSTS.update(hosts)
        try:
            with self.site.conn() as db:
                db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           ('jebo-face', hashlib.sha256(b'test').hexdigest(), '배송·환불', '양쪽 업체', '두 사이트에 같이 뜨는 제보', '원문 비공개 내용', '요청', '2026-10-17', 1, 1))
            jebo = self.client.get('/', base_url='https://consumerjebo.co.kr').get_data(as_text=True)
            with patch.object(self.site, 'CANONICAL_HOST', 'soboru.co.kr'):  # 관리자는 소보루 주소 하나
                r = self.client.get('/admin/content?face=jebo', base_url='https://consumerjebo.co.kr')
                self.assertEqual((r.status_code, r.headers['Location']), (302, 'https://soboru.co.kr/admin/content?face=jebo'))
            self.assertIn('jebo-favicon.png', jebo); self.assertIn('<meta property="og:site_name" content="소비자제보센터">', jebo)  # 검색·광고에 뜨는 이름·아이콘
            self.assertNotEqual(self.client.get('/favicon.ico', base_url='https://consumerjebo.co.kr').data, self.client.get('/favicon.ico').data)
            self.assertIn('class="site-header"', jebo)
            self.assertNotIn('class="sb"', jebo)
            self.assertIn('<title>소비자제보센터 - 소비자 피해 제보·고발</title>', jebo)
            self.assertIn('<link rel="canonical" href="https://consumerjebo.co.kr/">', jebo)
            self.assertIn('여러분의 제보가', jebo)
            sob = self.client.get('/', base_url='https://soboru.co.kr').get_data(as_text=True)
            self.assertIn('class="sb"', sob)
            self.assertNotIn('class="site-header"', sob)
            for base in ('https://consumerjebo.co.kr', 'https://soboru.co.kr'):
                rows = self.client.get('/reports', base_url=base).get_data(as_text=True)
                self.assertIn('두 사이트에 같이 뜨는 제보', rows)
                self.assertNotIn('원문 비공개 내용', rows)  # 운영자 2026-11-04: 목록 카드는 제목·상태만 (본문 앞부분 안 보임)
            self.assertIn('소비자게시판', self.client.get('/board', base_url='https://consumerjebo.co.kr').get_data(as_text=True))
            self.assertEqual(self.client.get('/reports', base_url='http://www.consumerjebo.co.kr').headers['Location'], 'https://consumerjebo.co.kr/reports')
            with patch.object(self.site, 'CANONICAL_HOST', 'soboru.co.kr'):
                r = self.client.get('/life?category=쇼핑', base_url='https://consumerjebo.co.kr')
                self.assertEqual((r.status_code, r.headers['Location']), (301, 'https://soboru.co.kr/life?category=%EC%87%BC%ED%95%91'))
                self.assertEqual(self.client.get('/reports', base_url='https://consumerjebo.co.kr').status_code, 200)
                # 검색엔진 대표 주소: 제보 화면은 소비자제보센터, 소보루 화면은 소보루, 홈은 각자
                self.assertIn('<link rel="canonical" href="https://consumerjebo.co.kr/reports">', self.client.get('/reports', base_url='https://soboru.co.kr').get_data(as_text=True))
                self.assertIn('<link rel="canonical" href="https://soboru.co.kr/board">', self.client.get('/board', base_url='https://consumerjebo.co.kr').get_data(as_text=True))
                self.assertIn('<link rel="canonical" href="https://soboru.co.kr/">', self.client.get('/', base_url='https://soboru.co.kr').get_data(as_text=True))
                jmap = self.client.get('/sitemap.xml', base_url='https://consumerjebo.co.kr').get_data(as_text=True)
                smap = self.client.get('/sitemap.xml', base_url='https://soboru.co.kr').get_data(as_text=True)
                self.assertIn('<loc>https://consumerjebo.co.kr/reports</loc>', jmap); self.assertNotIn('soboru.co.kr', jmap); self.assertNotIn('/life', jmap)
                self.assertIn('<loc>https://soboru.co.kr/life</loc>', smap); self.assertNotIn('consumerjebo', smap); self.assertNotIn('/reports<', smap)
                self.assertIn('Sitemap: https://consumerjebo.co.kr/sitemap.xml', self.client.get('/robots.txt', base_url='https://consumerjebo.co.kr').get_data(as_text=True))
                self.assertNotIn('soboru.co.kr', self.client.get('/rss.xml', base_url='https://consumerjebo.co.kr').get_data(as_text=True).split('<item>', 1)[-1])
        finally:
            self.site.JEBO_HOSTS.difference_update(hosts)
        # 관리자는 소보루 주소에서도 /?face=jebo 로 미리 봄
        admin = self.login_admin()
        self.assertIn('class="site-header"', admin.get('/?face=jebo').get_data(as_text=True))
        self.assertIn('class="sb"', admin.get('/?face=off').get_data(as_text=True))
        self.assertIn('class="sb"', self.client.get('/?face=jebo').get_data(as_text=True))  # 손님은 못 바꿈
        content = admin.get('/admin/content').get_data(as_text=True)
        self.assertNotIn('name="jebo.site_name"', content)  # 제보센터 이름·검색 설정은 소비자제보센터 칸에서
        self.assertNotIn('name="site.brand"', content)
        jcontent = admin.get('/admin/content?face=jebo').get_data(as_text=True)
        self.assertIn('name="jebo.site_name"', jcontent); self.assertNotIn('name="seo.naver_verification"', jcontent)
        lists = admin.get('/admin/lists').get_data(as_text=True)
        for key in ('menu', 'home_blocks', 'sample_reports'):
            self.assertIn('id="list-%s"' % key, lists)

    def test_jebo_copy_is_separate(self):
        # 관리자는 하나지만 소비자제보센터에서 고친 문구·구성은 제보센터에만, 소보루 문구는 소보루에만
        admin = self.login_admin(); tok = self.csrf(admin, '/admin/content')
        default = self.site.site_content.FIELDS['home.hero_button']['default']
        admin.post('/admin/content?face=jebo', data={'_csrf': tok, 'section': 'home', 'home.hero_button': '제보센터 전용 제목'})
        admin.post('/admin/content', data={'_csrf': tok, 'section': 'home', 'home.hero_button': '소보루 전용 제목'})
        self.assertIn('제보센터 전용 제목', admin.get('/admin/content?face=jebo').get_data(as_text=True))
        self.assertNotIn('제보센터 전용 제목', admin.get('/admin/content').get_data(as_text=True))
        self.assertIn('제보센터 전용 제목', admin.get('/?face=jebo').get_data(as_text=True))
        # 다른 탭에서 미리보기를 소비자제보센터로 바꿔도 face 없는 관리자 저장은 소보루로
        admin.post('/admin/inline', data={'_csrf': tok, 'key': 'home.hero_button', 'value': '인라인 소보루'})
        admin.post('/admin/inline', data={'_csrf': tok, 'key': 'home.hero_button', 'value': '인라인 제보센터', 'face': 'jebo'})
        with self.site.conn() as db:
            saved = dict(db.execute("SELECT key,value FROM site_content WHERE key LIKE '%home.hero_button'").fetchall())
        self.assertEqual(saved, {'home.hero_button': '인라인 소보루', 'jebo:home.hero_button': '인라인 제보센터'})
        # 사업자 정보는 두 사이트 공통
        admin.post('/admin/content?face=jebo', data={'_csrf': tok, 'section': 'operator', 'operator.name': '공통상호'})
        self.assertIn('공통상호', admin.get('/admin/content').get_data(as_text=True))
        # 제보센터 FAQ 목록도 따로
        admin.post('/admin/lists?face=jebo', data={'_csrf': tok, 'list': 'faq', 'q': ['제보센터 질문'] * 3, 'a': ['답'] * 3})
        self.assertIn('제보센터 질문', admin.get('/admin/lists?face=jebo').get_data(as_text=True))
        self.assertNotIn('제보센터 질문', admin.get('/admin/lists').get_data(as_text=True))
        self.assertTrue(default)

    def test_admin_can_delete_anything(self):
        # 관리자는 올라간 글·댓글·생활정보 글을 그 화면에서 바로 지울 수 있음
        now = datetime.datetime.now().isoformat(timespec='seconds')
        with self.site.conn() as db:
            aid = db.execute("INSERT INTO articles(title,summary,body,status,created,updated,published_at) VALUES('지울 글','요약','본문','published',?,?,?)", (now, now, now)).lastrowid
            pid = db.execute("INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created) VALUES('꿀팁','남','','남의 글','내용','x',?)", (now,)).lastrowid
        self.assertNotIn('admin-del', self.client.get(f'/life/{aid}').get_data(as_text=True))  # 손님에게는 안 보임
        admin = self.login_admin()
        self.assertIn('admin-del', admin.get(f'/life/{aid}').get_data(as_text=True))
        self.assertIn('admin-del', admin.get(f'/board/{pid}').get_data(as_text=True))
        tok = self.csrf(admin, '/admin/life')
        r = admin.post(f'/admin/life/{aid}/delete', data={'_csrf': tok, 'next': f'/life/{aid}'})
        self.assertEqual(r.headers['Location'], '/life')
        r = admin.post('/admin/board', data={'_csrf': tok, 'kind': 'p', 'id': pid, 'action': 'delete', 'next': f'/board/{pid}'})
        self.assertEqual(r.headers['Location'], '/board')
        with self.site.conn() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM articles WHERE id=?', (aid,)).fetchone())
            self.assertIsNone(db.execute('SELECT 1 FROM posts WHERE id=?', (pid,)).fetchone())

    def test_cross_site_login(self):
        self.enterContext(patch.object(self.site, 'RETIRED_HOSTS', set()))  # 예전 두 사이트 운영 때의 동작 확인 (지금 soboru.co.kr은 막혀 있음)
        # 소비자제보센터에서 가입·로그인하면 소보루에도 로그인, 로그아웃도 같이. 표는 한 번만 쓰고 다른 브라우저 상태값으론 안 됨
        J, M = 'https://consumerjebo.co.kr', 'https://soboru.co.kr'
        hosts = {'consumerjebo.co.kr', 'www.consumerjebo.co.kr'}
        self.site.JEBO_HOSTS.update(hosts)
        def hop(client, r):
            loc = r.headers['Location']; base = loc.split('/', 3)[:3]
            return client.get('/' + loc.split('/', 3)[3], base_url='/'.join(base))
        try:
            with patch.object(self.site, 'CANONICAL_HOST', 'soboru.co.kr'):
                c = self.site.app.test_client()
                page = c.get('/signup?id=1', base_url=J).get_data(as_text=True)  # 제보센터 기본 가입엔 아이디 칸이 없음 → 예전 아이디 가입 주소로
                self.assertIn('class="auth-top"', page)  # 가입 화면은 소비자제보센터 얼굴, 메뉴 없는 별도 화면 (운영자 2026-11-03)
                token = re.search(r'name="_csrf" value="([^"]+)"', page)[1]
                r = c.post('/signup', base_url=J, data={'_csrf': token, 'login_id': 'jebo_user', 'password': 'butter123', 'password2': 'butter123', 'nickname': '제보회원', 'phone': '010-5555-6666',
                                                        'agree_terms': 'on', 'agree_privacy': 'on', 'agree_age': 'on'})
                self.assertTrue(r.headers['Location'].startswith(M + '/sso/begin?'))
                r = hop(c, r); self.assertTrue(r.headers['Location'].startswith(J + '/sso/issue?'))
                r = hop(c, r); self.assertTrue(r.headers['Location'].startswith(M + '/sso/in?'))
                ticket = r.headers['Location']
                r = hop(c, r); self.assertEqual(r.headers['Location'], J + '/me')
                self.assertEqual(c.get('/me', base_url=M).status_code, 200)
                self.assertEqual(c.get('/me', base_url=J).status_code, 200)
                # 같은 표를 다른 브라우저에서 쓰면 로그인 안 됨
                other = self.site.app.test_client()
                other.get('/' + ticket.split('/', 3)[3], base_url=M)
                self.assertEqual(other.get('/me', base_url=M).status_code, 302)
                # 다른 주소로는 돌려보내지 않음
                self.assertEqual(c.get('/sso/begin?back=https://evil.example/', base_url=M).status_code, 404)
                # 소보루에서 로그아웃하면 소비자제보센터도 로그아웃
                token = re.search(r'name="_csrf" value="([^"]+)"', c.get('/me', base_url=M).get_data(as_text=True))[1]
                r = c.post('/logout', base_url=M, data={'_csrf': token})
                self.assertTrue(r.headers['Location'].startswith(J + '/sso/out?'))
                hop(c, r)
                self.assertEqual(c.get('/me', base_url=J).status_code, 302)
                self.assertEqual(c.get('/me', base_url=M).status_code, 302)
        finally:
            self.site.JEBO_HOSTS.difference_update(hosts)

    def test_process_page_cards(self):
        page = self.client.get('/process').get_data(as_text=True)
        self.assertEqual(page.count('class="process-card"'), 6)  # 운영자 2026-11-03: 기사화 단계 따로
        self.assertIn('<span class="pc-step">1단계</span>제보 접수', page)
        self.assertIn('<strong class="em">온라인으로 제보</strong>', page)
        self.assertEqual(page.count('class="step-icon"'), 6)
        admin = self.login_admin()
        token = self.csrf(admin, '/admin/lists')
        admin.post('/admin/lists', data={'_csrf': token, 'list': 'process_steps', 'title': ['상담', '끝'], 'icon': ['call', ''], 'body': ['**<i>빠르게</i>** 연락드려요', '']})
        page = self.client.get('/process').get_data(as_text=True)
        self.assertEqual(page.count('class="process-card"'), 2)
        self.assertIn('<strong class="em">&lt;i&gt;빠르게&lt;/i&gt;</strong> 연락드려요', page)
        self.assertEqual(admin.post('/admin/lists', data={'_csrf': token, 'list': 'process_steps', 'title': ['x'], 'icon': ['rocket'], 'body': ['']}).status_code, 400)

    def signup(self, client, login_id='sobo_ru', nickname='소보루', password='butter123', **extra):
        data = {'login_id': login_id, 'password': password, 'nickname': nickname, 'phone': '010-1234-5678',
                'agree_terms': 'on', 'agree_privacy': 'on', 'agree_age': 'on', **extra}
        return self.post_form(client, '/signup', data)

    def join_form(self, client):
        # 소셜 가입 화면에 미리 채워진 닉네임을 그대로 써서 가입 (휴대폰 번호가 없으면 시험용 번호)
        page = client.get('/auth/join').get_data(as_text=True)
        form = {'agree_terms': 'on', 'agree_privacy': 'on', 'agree_age': 'on', 'nickname': re.search(r'name="nickname"[^>]*value="([^"]*)"', page)[1]}
        if 'name="phone"' in page: form['phone'] = '010-2222-0000'
        return form

    def test_signup_requires_consents_and_valid_fields(self):
        page = self.client.get('/signup').get_data(as_text=True)
        for text in ('이용약관', '개인정보 수집·이용', '만 14세 이상', '회원 탈퇴 시 즉시 파기', 'data-check-all'):
            self.assertIn(text, page)
        self.assertIn('>회원가입</a>', self.client.get('/').get_data(as_text=True))
        missing = self.signup(self.client, agree_age='')
        self.assertEqual(missing.status_code, 400)
        self.assertIn('필수 동의 항목', missing.get_data(as_text=True))
        weak = self.signup(self.client, password='12345678')
        self.assertIn('영문과 숫자를 섞어', weak.get_data(as_text=True))
        self.assertIn('사용할 수 없는 닉네임', self.signup(self.client, nickname='운영자').get_data(as_text=True))
        self.assertIn('휴대폰 번호를 확인해 주세요', self.signup(self.client, phone='1234').get_data(as_text=True))
        made = self.signup(self.client, phone='01012345678')
        self.assertEqual(made.status_code, 302)
        with self.site.conn() as db:
            user = db.execute('SELECT * FROM users').fetchone()
        self.assertNotEqual(user['pw_hash'], 'butter123')
        self.assertEqual(user['terms_version'], self.site.TERMS_VERSION)
        self.assertEqual(user['phone'], '010-1234-5678')  # 휴대폰 번호는 하이픈 넣어 저장
        me = self.client.get('/me').get_data(as_text=True)
        self.assertIn('소보루님', me)
        other = self.site.app.test_client()
        dup = self.signup(other, login_id='SOBO_RU', nickname='다른이름')
        self.assertIn('이미 쓰고 있는 아이디', dup.get_data(as_text=True))
        self.assertIn('이미 쓰고 있는 닉네임', self.signup(other, login_id='another', nickname='소보루').get_data(as_text=True))

    def test_email_login_and_link_old_case(self):
        self.signup(self.site.app.test_client(), email='Sobo@Example.com')
        # 같은 이메일로는 또 가입할 수 없음
        dup = self.signup(self.site.app.test_client(), login_id='another', nickname='다른이름', email='sobo@example.com')
        self.assertIn('이미 가입한 이메일', dup.get_data(as_text=True))
        self.assertIn('아이디 또는 이메일', self.client.get('/login').get_data(as_text=True))
        bad = self.post_form(self.client, '/login', {'login_id': 'sobo@example.com', 'password': 'wrong-pass1'})
        self.assertEqual(bad.status_code, 401)
        ok = self.post_form(self.client, '/login', {'login_id': 'SOBO@example.com', 'password': 'butter123'})
        self.assertEqual(ok.status_code, 302)
        self.assertIn('소보루님', self.client.get('/me').get_data(as_text=True))
        # 로그인 전에 접수한 제보: 접수번호 + 휴대폰 + 조회 비밀번호가 모두 맞아야 연결
        guest = self.site.app.test_client()
        self.post_form(guest, '/report', {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '테스트몰', 'subject': '비회원 제보', 'description': '배송이 오지 않았어요.', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': '환불', 'consent': 'on', 'lookup_pw': '5678', 'lookup_pw2': '5678', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'secret'})
        with self.site.conn() as db:
            case = db.execute("SELECT id,receipt,user_id FROM cases WHERE subject='비회원 제보'").fetchone()
        self.assertIsNone(case['user_id'])
        me = self.client.get('/me').get_data(as_text=True)
        self.assertIn('로그인 전에 접수한 제보 연결하기', me)
        wrong = self.post_me(self.client, '/me/link-case', {'receipt': case['receipt'], 'phone': '010-1234-5678', 'password': '0000'})
        self.assertEqual(wrong.status_code, 302)
        with self.site.conn() as db:
            self.assertIsNone(db.execute('SELECT user_id FROM cases WHERE id=?', (case['id'],)).fetchone()['user_id'])
        self.post_me(self.client, '/me/link-case', {'receipt': case['receipt'].lower(), 'phone': '01012345678', 'password': '5678'})
        with self.site.conn() as db:
            self.assertIsNotNone(db.execute('SELECT user_id FROM cases WHERE id=?', (case['id'],)).fetchone()['user_id'])
            self.assertTrue(db.execute("SELECT 1 FROM case_log WHERE case_id=? AND action LIKE '%회원 계정에 연결'", (case['id'],)).fetchone())
        self.assertIn('비회원 제보', self.client.get('/me').get_data(as_text=True))
        # 다른 회원은 이미 연결된 제보를 가져갈 수 없음
        other = self.site.app.test_client()
        self.signup(other, login_id='other_one', nickname='다른사람')
        self.post_me(other, '/me/link-case', {'receipt': case['receipt'], 'phone': '010-1234-5678', 'password': '5678'})
        with self.site.conn() as db:
            owner = db.execute('SELECT u.login_id FROM cases c JOIN users u ON u.id=c.user_id WHERE c.id=?', (case['id'],)).fetchone()['login_id']
        self.assertEqual(owner, 'sobo_ru')

    def post_me(self, client, path, data):
        return client.post(path, data={'_csrf': self.csrf(client, '/me'), **data})

    def kakao_fake(self, uid='4242', email='kim@kakao.test', nickname='김카카오', name='김실명', phone='+82 10-1234-5678'):
        calls = []
        def fake(method, url, data=None, headers=None, timeout=10):
            calls.append((method, url, data, headers))
            if 'oauth/token' in url:
                return 200, {'access_token': 'tok-' + uid}
            return 200, {'id': int(uid), 'kakao_account': {'email': email, 'is_email_valid': True, 'is_email_verified': True, 'profile': {'nickname': nickname}, 'name': name, 'phone_number': phone}}
        return calls, fake

    def social_round(self, client, fake, start='/auth/kakao/start'):
        r = client.get(start)
        self.assertEqual(r.status_code, 302)
        loc = r.headers['Location']
        self.assertTrue(loc.startswith('https://kauth.kakao.com/oauth/authorize?'))
        state = re.search(r'state=([^&]+)', loc)[1]
        with patch.object(self.site.members, 'http', fake):
            return client.get(f'/auth/kakao/callback?code=abc&state={state}')

    def test_kakao_login_signup_link_and_withdraw(self):
        self.assertNotIn('카카오로', self.client.get('/login').get_data(as_text=True))  # 키가 없으면 버튼도 없음
        self.assertEqual(self.client.get('/auth/kakao/start').status_code, 404)
        with patch.dict(os.environ, {'KAKAO_REST_API_KEY': 'rest-key', 'KAKAO_CLIENT_SECRET': 'shh'}):
            self.assertIn('카카오로 로그인', self.client.get('/login').get_data(as_text=True))
            calls, fake = self.kakao_fake()
            # 다른 브라우저에서 시작한 state는 거절
            self.client.get('/auth/kakao/start')
            with patch.object(self.site.members, 'http', fake):
                forged = self.client.get('/auth/kakao/callback?code=abc&state=forged')
            self.assertEqual(forged.headers['Location'], '/login')
            self.assertEqual(calls, [])
            # 처음이면 동의 화면을 거쳐 가입
            r = self.social_round(self.client, fake)
            self.assertEqual(r.headers['Location'], '/auth/join')
            token_call = calls[0]
            self.assertEqual(token_call[2]['client_secret'], 'shh')
            self.assertEqual(token_call[2]['redirect_uri'], 'http://localhost/auth/kakao/callback')
            page = self.client.get('/auth/join').get_data(as_text=True)
            self.assertIn('카카오로 가입하기', page)
            self.assertIn('김실명', page)
            self.assertIn('010-1234-5678', page)
            self.assertIn('name="nickname"', page)  # 닉네임은 직접 정함 (자동 닉네임을 미리 채워 둠)
            self.assertNotIn('name="phone"', page)  # 카카오에서 받은 휴대폰 번호가 있으면 묻지 않음
            self.assertEqual(self.post_form(self.client, '/auth/join', {}).status_code, 400)
            joined = self.post_form(self.client, '/auth/join', self.join_form(self.client))
            self.assertEqual(joined.status_code, 302)
            with self.site.conn() as db:
                user = db.execute("SELECT * FROM users WHERE real_name='김실명'").fetchone()
                ident = db.execute('SELECT * FROM user_identities WHERE user_id=?', (user['id'],)).fetchone()
            self.assertRegex(user['nickname'], r'^[가-힣]+소보루\d+$')  # 카카오 닉네임(실명일 수 있음)은 게시판에 쓰지 않음
            self.assertEqual((user['pw_hash'], user['email'], ident['provider'], ident['provider_uid']), ('', 'kim@kakao.test', 'kakao', '4242'))
            self.assertEqual((user['real_name'], user['phone']), ('김실명', '010-1234-5678'))
            # 제보 양식에 실명·연락처가 자동으로 채워짐
            form = self.client.get('/report').get_data(as_text=True)
            self.assertIn('value="김실명"', form)
            self.assertIn('value="010-1234-5678"', form)
            self.assertIn('value="kim@kakao.test"', form)
            self.assertIn('내 정보로 자동으로 채웠어요', form)
            # 실명은 공개 화면(내 정보 제목·게시판)에 쓰이지 않음
            self.assertNotIn('김실명님', self.client.get('/me').get_data(as_text=True))
            self.assertTrue(user['email_verified_at'])
            self.assertNotIn('tok-4242', json.dumps([dict(r) for r in [user, ident]]))  # 토큰은 저장하지 않음
            me = self.client.get('/me').get_data(as_text=True)
            self.assertIn('카카오로 가입', me)
            self.assertIn('비밀번호 만들기', me)
            # 소셜 회원은 비밀번호가 없어 아이디 로그인 불가
            self.assertEqual(self.post_form(self.site.app.test_client(), '/login', {'login_id': user['login_id'], 'password': ''}).status_code, 401)
            # 로그인 방법이 하나뿐이면 해제 불가
            self.post_me(self.client, '/me/social/kakao/unlink', {})
            with self.site.conn() as db:
                self.assertTrue(db.execute('SELECT 1 FROM user_identities WHERE user_id=?', (user['id'],)).fetchone())
            # 다시 오면 바로 로그인
            again = self.site.app.test_client()
            self.assertEqual(self.social_round(again, fake).headers['Location'], '/')
            self.assertIn(user['nickname'] + '님', again.get('/me').get_data(as_text=True))
            # 같은 이메일의 기존 회원이 있으면 합치지 않음
            self.signup(self.site.app.test_client(), login_id='lee_id', nickname='이아이디', email='lee@kakao.test')
            _, fake2 = self.kakao_fake(uid='777', email='lee@kakao.test', nickname='이카카오')
            blocked = self.social_round(self.site.app.test_client(), fake2)
            self.assertEqual(blocked.headers['Location'], '/login')
            with self.site.conn() as db:
                self.assertIsNone(db.execute("SELECT 1 FROM user_identities WHERE provider_uid='777'").fetchone())
            # 기존 회원은 로그인한 뒤 내 정보에서 연결
            lee = self.site.app.test_client()
            self.post_form(lee, '/login', {'login_id': 'lee_id', 'password': 'butter123'})
            linked = self.social_round(lee, fake2, '/auth/kakao/start?link=1')
            self.assertEqual(linked.headers['Location'], '/me#login-methods')
            self.assertIn('연결됨', lee.get('/me').get_data(as_text=True))
            # 이미 다른 회원에게 연결된 카카오 계정은 연결 안 됨
            self.social_round(lee, fake, '/auth/kakao/start?link=1')
            with self.site.conn() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM user_identities WHERE provider_uid='4242'").fetchone()[0], 1)
            # 비밀번호가 있으면 해제 가능
            self.post_me(lee, '/me/social/kakao/unlink', {})
            with self.site.conn() as db:
                self.assertIsNone(db.execute("SELECT 1 FROM user_identities WHERE provider_uid='777'").fetchone())
            # 소셜 회원 탈퇴: 비밀번호 없이 확인만, 연결 정보도 삭제
            out = self.post_me(self.client, '/me/withdraw', {'confirm': 'on'})
            self.assertEqual(out.status_code, 302)
            with self.site.conn() as db:
                self.assertIsNone(db.execute('SELECT 1 FROM users WHERE id=?', (user['id'],)).fetchone())
                self.assertIsNone(db.execute('SELECT 1 FROM user_identities WHERE user_id=?', (user['id'],)).fetchone())

    def test_naver_profile_and_state(self):
        with patch.dict(os.environ, {'NAVER_CLIENT_ID': 'nid', 'NAVER_CLIENT_SECRET': 'nsec', 'ENABLE_NAVER_LOGIN': '1'}):
            r = self.client.get('/auth/naver/start')
            self.assertTrue(r.headers['Location'].startswith('https://nid.naver.com/oauth2.0/authorize?'))
            state = re.search(r'state=([^&]+)', r.headers['Location'])[1]
            seen = []
            def fake(method, url, data=None, headers=None, timeout=10):
                seen.append(data)
                if 'oauth2.0/token' in url:
                    return 200, {'access_token': 'nt'}
                return 200, {'resultcode': '00', 'response': {'id': 'naver-uid-1', 'email': 'park@naver.test', 'nickname': '박네이버!', 'name': '박실명', 'mobile': '010-9876-5432'}}
            with patch.object(self.site.members, 'http', fake):
                self.assertEqual(self.client.get(f'/auth/naver/callback?code=c&state={state}').headers['Location'], '/auth/join')
            self.assertEqual(seen[0]['state'], state)
            self.assertIn('박실명', self.client.get('/auth/join').get_data(as_text=True))
            # 같은 state로 다시 들어오면 거절 (한 번만 씀)
            with patch.object(self.site.members, 'http', fake):
                self.assertEqual(self.client.get(f'/auth/naver/callback?code=c&state={state}').headers['Location'], '/login')
            r = self.client.get('/auth/naver/start')
            state = re.search(r'state=([^&]+)', r.headers['Location'])[1]
            with patch.object(self.site.members, 'http', fake):
                self.client.get(f'/auth/naver/callback?code=c&state={state}')
            self.assertEqual(self.post_form(self.client, '/auth/join', self.join_form(self.client)).status_code, 302)
            with self.site.conn() as db:
                u = db.execute("SELECT * FROM users WHERE real_name='박실명'").fetchone()
            self.assertRegex(u['nickname'], r'^[가-힣]+소보루\d+$')
            self.assertEqual(u['phone'], '010-9876-5432')

    def test_report_quick_fill_and_profile(self):
        self.assertEqual((self.site.members.kr_phone('+82 10-1234-5678'), self.site.members.kr_phone('01012345678'), self.site.members.kr_phone('02-123')), ('010-1234-5678', '010-1234-5678', ''))
        with patch.dict(os.environ, {'KAKAO_REST_API_KEY': 'rest-key', 'KAKAO_CLIENT_SECRET': 'shh'}):
            page = self.client.get('/report').get_data(as_text=True)
            self.assertIn('간편하게 입력하기', page)
            self.assertIn('/auth/kakao/start?next=/report', page)
            r = self.client.get('/auth/kakao/start?next=/report')
            with self.client.session_transaction() as sess:
                self.assertEqual(sess['oauth']['next'], '/report')
        # 아이디 회원: 내 정보에서 실명·전화번호와 닉네임을 바꾸면 제보 양식에 채워짐
        self.signup(self.client)
        self.assertNotIn('간편하게 입력하기', self.client.get('/report').get_data(as_text=True))
        self.post_me(self.client, '/me/edit', {'action': 'profile', 'real_name': '홍길동', 'phone': '010-2222-3333'})
        self.post_me(self.client, '/me/edit', {'action': 'nickname', 'nickname': '새닉네임'})
        self.post_me(self.client, '/me/edit', {'action': 'nickname', 'nickname': '운영팀'})
        with self.site.conn() as db:
            u = db.execute("SELECT * FROM users WHERE real_name='홍길동'").fetchone()
        self.assertEqual((u['phone'], u['nickname']), ('010-2222-3333', '새닉네임'))
        form = self.client.get('/report').get_data(as_text=True)
        self.assertIn('value="홍길동"', form)
        self.assertIn('value="010-2222-3333"', form)

    def test_company_membership_request_and_approval(self):
        self.signup(self.client)
        self.assertIn('소속 인증 신청', self.client.get('/me').get_data(as_text=True))
        form = {'company_name': '고양이상회', 'biz_no': '123-45-67891', 'person_name': '김담당', 'department': 'CS팀', 'phone': '02-123-4567', 'work_email': 'cs@cat.example', 'agree': 'on'}
        bad = self.post_form(self.client, '/me/company', dict(form, biz_no='111-11-11111'))
        self.assertEqual(bad.status_code, 400)
        token = self.csrf(self.client, '/me/company')
        made = self.client.post('/me/company', data={'_csrf': token, **form, 'evidence': (io.BytesIO(b'%PDF-1.4 test'), 'card.pdf')}, content_type='multipart/form-data')
        self.assertEqual(made.status_code, 302)
        page = self.client.get('/me/company').get_data(as_text=True)
        self.assertIn('확인 중', page)
        with self.site.conn() as db:
            m = db.execute('SELECT * FROM company_memberships').fetchone()
            self.assertEqual(db.execute("SELECT kind FROM users WHERE login_id='sobo_ru'").fetchone()['kind'], 'consumer')
        self.assertTrue((Path(self.temp.name) / 'uploads' / m['evidence_stored']).exists())
        # 기업 소속 신청만으로는 기업 화면·제보에 접근할 수 없음
        self.assertEqual(self.client.get(f"/admin/memberships/{m['id']}/evidence").status_code, 302)
        admin = self.login_admin()
        listing = admin.get('/admin/members').get_data(as_text=True)
        self.assertIn('고양이상회', listing)
        self.assertIn('확인 대기 1', listing)
        self.assertEqual(admin.get(f"/admin/memberships/{m['id']}/evidence").status_code, 200)
        self.post_form(admin, '/admin/members', {'membership_id': m['id'], 'action': 'm_approve'})
        with self.site.conn() as db:
            self.assertEqual(db.execute("SELECT kind FROM users WHERE login_id='sobo_ru'").fetchone()['kind'], 'company')
            self.assertEqual(db.execute('SELECT status FROM company_memberships').fetchone()['status'], 'approved')
        self.assertIn('기업 회원', self.client.get('/me').get_data(as_text=True))
        # 탈퇴하면 신청과 증빙 파일도 지움
        self.post_me(self.client, '/me/withdraw', {'password': 'butter123', 'confirm': 'on'})
        with self.site.conn() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM company_memberships').fetchone())
        self.assertFalse((Path(self.temp.name) / 'uploads' / m['evidence_stored']).exists())

    def test_company_member_signs_in_to_biz_with_social_login(self):
        self.site.BIZ_ON = True
        self.addCleanup(setattr, self.site, 'BIZ_ON', False)
        with patch.dict(os.environ, {'KAKAO_REST_API_KEY': 'rest-key', 'KAKAO_CLIENT_SECRET': 'shh'}):
            login_page = self.client.get('/biz/login').get_data(as_text=True)
            self.assertIn('카카오로 기업 로그인', login_page)
            self.assertIn('/auth/kakao/start?next=/biz', login_page)
            self.assertIn('/auth/kakao/start?next=/me/company', self.client.get('/biz/signup').get_data(as_text=True))
        admin = self.login_admin()
        self.post_form(admin, '/admin/companies', {'action': 'create', 'name': '고양이상회'})
        # 회원 로그인만으로는 기업 화면이 열리지 않고, 소속 인증 안내가 보임
        self.signup(self.client)
        self.assertEqual(self.client.get('/biz').headers['Location'], '/biz/login?next=/biz')
        self.assertIn('기업 소속 인증이 필요해요', self.client.get('/biz/login').get_data(as_text=True))
        form = {'company_name': '고양이상회', 'biz_no': '123-45-67891', 'person_name': '김담당', 'department': 'CS팀', 'phone': '02-123-4567', 'work_email': 'cs@cat.example', 'agree': 'on'}
        self.post_form(self.client, '/me/company', form)
        self.assertIn('소속 인증을 확인하고 있어요', self.client.get('/biz/login').get_data(as_text=True))
        self.assertEqual(self.client.get('/biz').status_code, 302)
        with self.site.conn() as db:
            m = db.execute('SELECT * FROM company_memberships').fetchone()
        self.post_form(admin, '/admin/members', {'membership_id': m['id'], 'action': 'm_approve'})
        with self.site.conn() as db:
            company = db.execute("SELECT * FROM companies WHERE name='고양이상회'").fetchone()
            seat = db.execute('SELECT * FROM company_users WHERE user_id IS NOT NULL').fetchone()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM companies').fetchone()[0], 1)  # 미리 등록된 기업에 붙음
        self.assertEqual((company['status'], company['biz_no'], seat['company_id'], seat['name'], seat['pw_hash']), ('active', '1234567891', company['id'], '김담당', ''))
        # 승인 뒤에는 같은 회원 로그인으로 기업 화면에 들어감 (비밀번호 변경 화면은 없음)
        home = self.client.get('/biz')
        self.assertEqual(home.status_code, 200)
        self.assertIn('고양이상회 · 김담당', home.get_data(as_text=True))
        self.assertNotIn('비밀번호 변경', home.get_data(as_text=True))
        self.assertEqual(self.client.get('/biz/password').headers['Location'], '/biz')
        self.assertIn('기업 화면으로 가기', self.client.get('/me/company').get_data(as_text=True))
        # 내부 아이디로 비밀번호 로그인은 안 되고, 관리자 비밀번호 재설정도 간편 로그인 담당자에겐 적용 안 됨
        other = self.site.app.test_client()
        self.assertEqual(self.post_form(other, '/biz/login', {'login_id': seat['login_id'], 'password': ''}).status_code, 401)
        self.assertIn('간편 로그인 김담당', admin.get('/admin/companies').get_data(as_text=True))
        self.post_form(admin, '/admin/companies', {'action': 'reset', 'id': company['id'], 'password': 'newpass123'})
        with self.site.conn() as db:
            self.assertEqual(db.execute('SELECT pw_hash FROM company_users WHERE id=?', (seat['id'],)).fetchone()['pw_hash'], '')
        # 기업 화면에서 로그아웃하면 회원 로그인도 끝남
        self.client.post('/biz/logout', data={'_csrf': self.csrf(self.client, '/biz')})
        self.assertEqual(self.client.get('/me').status_code, 302)
        # 소속 반려하면 기업 화면 자리도 없어짐
        self.post_form(self.client, '/login', {'login_id': 'sobo_ru', 'password': 'butter123'})
        self.assertEqual(self.client.get('/biz').status_code, 200)
        self.post_form(admin, '/admin/members', {'membership_id': m['id'], 'action': 'm_reject', 'reason': '확인 불가'})
        self.assertEqual(self.client.get('/biz').status_code, 302)
        with self.site.conn() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM company_users WHERE user_id IS NOT NULL').fetchone())

    DESK_REPORT = {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '고양이몰', 'subject': '환불이 안 돼요',
                   'description': '홍길동입니다. 9월 1일 산 운동화를 반품했는데 환불이 안 돼요. 연락은 010-1234-5678로 주세요.', 'reporter_name': '홍길동',
                   'phone': '010-1234-5678', 'request_text': '환불해 주세요.', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234',
                   'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'public'}

    def ai_reply(self, sent, status=200):
        facts = {'company': '고양이몰', 'product': '운동화', 'purchase_date': '', 'damage_date': '확인 필요',
                 'paragraphs': ['제보자에 따르면 운동화를 반품했지만 환불을 받지 못했다고 합니다. 연락처 010-9999-8888', '제보자는 환불을 요구하고 있습니다.'],
                 'claims': '환불 지연', 'company_response': '확인 필요', 'demands': '환불', 'questions': ['반품 접수 여부를 확인해 주시기 바랍니다.', '환불 처리 일정을 알려 주시기 바랍니다.']}
        def fake(url, headers, body, timeout):
            if '제보 분류' in body['messages'][0]['content']:
                return 503, {}  # AI 분류는 이 테스트에서 보지 않음
            sent.append((url, headers, body))
            if status != 200:
                return status, {'error': {'message': 'server busy'}}
            return 200, {'model': 'gpt-test', 'choices': [{'message': {'content': json.dumps(facts, ensure_ascii=False)}}]}
        return fake

    class NowThread:
        def __init__(self, target, args=(), daemon=None):
            self.target, self.args = target, args
        def start(self):
            # 실제처럼 요청 밖(다른 스레드)에서 돌리고 끝날 때까지 기다림
            t = _REAL_THREAD(target=self.target, args=self.args); t.start(); t.join()

    def test_ai_company_request_generate_edit_approve_send(self):
        desk = self.site.companydesk
        sent = []
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(desk, 'post_json', self.ai_reply(sent)), patch.object(desk.threading, 'Thread', self.NowThread):
            r = self.post_form(self.client, '/report', self.DESK_REPORT)
            self.assertEqual(r.status_code, 200)
            self.post_form(self.client, '/report', dict(self.DESK_REPORT, subject='비밀 제보', visibility='secret'))
            # 기업 전달에 동의하지 않은 제보(예전 제보 등)는 AI에 보내지 않음
            with self.site.conn() as db:
                db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,share_company) VALUES('N1','x','기타','고양이몰','전달 미동의','내용','요청','2026-10-15',0)")
                nid = db.execute("SELECT id FROM cases WHERE receipt='N1'").fetchone()['id']
            self.assertFalse(self.site.desk_generate(nid))
        self.assertEqual(len(sent), 2)
        payload = json.dumps(sent[0][2], ensure_ascii=False)
        for secret in ('홍길동', '010-1234-5678', 'sk-test-key'):
            self.assertNotIn(secret, payload)
        self.assertEqual(sent[0][1]['Authorization'], 'Bearer sk-test-key')
        with self.site.conn() as db:
            ids = {r['subject']: r['id'] for r in db.execute('SELECT id,subject FROM cases')}
            req = db.execute('SELECT * FROM company_requests WHERE case_id=?', (ids['환불이 안 돼요'],)).fetchone()
            secret_req = db.execute('SELECT * FROM company_requests WHERE case_id=?', (ids['비밀 제보'],)).fetchone()
            self.assertIsNone(db.execute('SELECT 1 FROM company_requests WHERE case_id=?', (ids['전달 미동의'],)).fetchone())
        self.assertEqual((req['version'], req['origin'], req['status'], req['model']), (1, 'ai', 'draft', 'gpt-test'))
        self.assertEqual(req['title'], '[소보루] 고양이몰 관련 사실관계 확인 및 공식 입장 요청')
        for text in ('안녕하세요. 소보루입니다.', '■ 주요 제보 내용', '■ 확인 요청 사항', '1. 반품 접수 여부', '3. ', '■ 제보 내용 확인',
                     f"/reports/{ids['환불이 안 돼요']}", '소보루 드림\nhttps://consumerjebo.co.kr', '향후 추가 취재 및 보도가 진행될 수 있음'):
            self.assertIn(text, req['body'])
        self.assertNotIn('010-9999-8888', req['body'])  # AI가 돌려준 개인정보도 지움
        self.assertNotIn('■ 제보 내용 확인', secret_req['body'])  # 비밀글은 링크 없이
        cid = ids['환불이 안 돼요']
        admin = self.login_admin()
        page = admin.get(f'/admin/reports/{cid}').get_data(as_text=True)
        for text in ('AI 기업 입장 요청서', '제목 복사', '본문 복사', '전체 복사', '관리자 승인', '공개 제보 보기'):
            self.assertIn(text, page)
        token = self.csrf(admin, f'/admin/reports/{cid}')
        post = lambda **d: admin.post(f'/admin/reports/{cid}', data={'_csrf': token, **d})
        post(form='req_save', title=req['title'], body=req['body'] + '\n(관리자 추가)')
        # 승인 전에는 전달 완료 불가
        post(form='req_sent', channel='email', target='cs@cat.example')
        with self.site.conn() as db:
            self.assertFalse(db.execute("SELECT 1 FROM company_requests WHERE status='sent'").fetchone())
        # 다시 만들어도 관리자가 고친 판은 이력에 그대로
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(desk, 'post_json', self.ai_reply(sent)):
            post(form='req_generate')
        with self.site.conn() as db:
            vs = db.execute('SELECT version,origin,body FROM company_requests WHERE case_id=? ORDER BY version', (cid,)).fetchall()
        self.assertEqual([(v['version'], v['origin']) for v in vs], [(1, 'ai'), (2, 'edit'), (3, 'ai')])
        self.assertIn('(관리자 추가)', vs[1]['body'])
        post(form='req_restore', version='2')
        post(form='req_approve')
        post(form='req_sent', channel='email', target='cs@cat.example')
        with self.site.conn() as db:
            last = db.execute('SELECT * FROM company_requests WHERE case_id=? ORDER BY version DESC LIMIT 1', (cid,)).fetchone()
            case = db.execute('SELECT status,forwarded_at,seen_at FROM cases WHERE id=?', (cid,)).fetchone()
            notice = db.execute("SELECT * FROM company_notices WHERE case_id=? AND kind='request'", (cid,)).fetchone()
        self.assertEqual((last['version'], last['origin'], last['status'], last['sent_channel']), (4, 'restore', 'sent', 'email'))
        self.assertIn('(관리자 추가)', last['body'])
        self.assertEqual(case['status'], '기업 답변 대기')
        self.assertTrue(case['forwarded_at'])
        self.assertFalse(case['seen_at'])  # 보냈다고 '기업 확인'으로 표시하지 않음
        self.assertIn('이메일', notice['memo'])
        page = admin.get(f'/admin/reports/{cid}').get_data(as_text=True)
        self.assertIn('기업 전달 완료', page)
        self.assertIn('입장 요청서 전달', page)
        self.assertIn('이력 4판', page)
        # 답변 없이 종결 (중립 표현)
        post(form='close_no_answer')
        with self.site.conn() as db:
            c = db.execute('SELECT status,close_reason FROM cases WHERE id=?', (cid,)).fetchone()
        self.assertEqual((c['status'], c['close_reason']), ('종결', 'no_answer'))

    def test_ai_request_failure_does_not_block_and_manual_fallback(self):
        desk = self.site.companydesk
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(desk, 'post_json', self.ai_reply([], status=500)), \
             patch.object(desk.threading, 'Thread', self.NowThread), self.assertLogs('companydesk', level='WARNING'):
            r = self.post_form(self.client, '/report', self.DESK_REPORT)
        self.assertEqual(r.status_code, 200)
        with self.site.conn() as db:
            cid = db.execute('SELECT id FROM cases').fetchone()['id']
            row = db.execute('SELECT * FROM company_requests WHERE case_id=?', (cid,)).fetchone()
        self.assertEqual(row['body'], '')
        self.assertIn('500', row['error'])
        self.assertNotIn('sk-test-key', row['error'])
        admin = self.login_admin()
        page = admin.get(f'/admin/reports/{cid}').get_data(as_text=True)
        self.assertIn('<span class="cs-pill off">생성 실패</span>', page)
        self.assertIn('직접 쓰기', page)
        token = self.csrf(admin, f'/admin/reports/{cid}')
        admin.post(f'/admin/reports/{cid}', data={'_csrf': token, 'form': 'req_manual'})
        with self.site.conn() as db:
            manual = db.execute("SELECT * FROM company_requests WHERE case_id=? AND body!=''", (cid,)).fetchone()
        self.assertEqual(manual['origin'], 'manual')
        self.assertIn('■ 확인 요청 사항', manual['body'])
        self.assertNotIn('<span class="cs-pill off">생성 실패</span>', admin.get(f'/admin/reports/{cid}').get_data(as_text=True))

    def triage_ai(self, sent, track='auto', refs=('ecom:제17조:①', 'ecom:제99조', 'ecom:제18조:②')):
        guidance = {'track': track, 'reason': '단순 반품·환불 문의라 법률 안내로 충분해요.',
                    'guidance': ['상품을 받은 날부터 7일 안이면 반품(청약철회)을 요청할 수 있어요. 홍길동 010-1234-5678', '상품이 돌아간 날부터 3영업일 안에 환불돼야 해요.'],
                    'refs': list(refs), 'steps': ['업체에 반품·환불을 문자나 게시판처럼 기록이 남는 방법으로 요청하세요.', '반품 송장 번호를 보관하세요.']}
        facts = {'company': '고양이몰', 'paragraphs': ['제보자에 따르면 환불이 안 됐습니다.'], 'questions': ['환불 지연 사유는 무엇인가요?']}
        def fake(url, headers, body, timeout):
            sent.append(body)
            out = guidance if '제보 분류' in body['messages'][0]['content'] else facts
            return 200, {'model': 'gpt-test', 'choices': [{'message': {'content': json.dumps(out, ensure_ascii=False)}}]}
        return fake

    def test_ai_triage_draft_send_and_filters(self):
        desk = self.site.companydesk
        sent = []
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(desk, 'post_json', self.triage_ai(sent)), patch.object(desk.threading, 'Thread', self.NowThread):
            self.assertEqual(self.post_form(self.client, '/report', self.DESK_REPORT).status_code, 200)
        tri_calls = [b for b in sent if 'messages' in b and '제보 분류' in b['messages'][0]['content']]
        self.assertEqual(len(tri_calls), 1)
        user = tri_calls[0]['messages'][1]['content']
        self.assertNotIn('010-1234-5678', user)  # 개인정보는 AI에 보내지 않음
        self.assertNotIn('홍길동', user)
        self.assertIn('[ecom:제17조:①]', user)  # 조문 후보(원문)를 함께 보냄
        self.assertIn('[corpus:', user)  # 제보 글로 찾은 법령 원문 후보도 함께
        self.assertIn('일반 지식이나 인터넷 검색', tri_calls[0]['messages'][0]['content'])
        with self.site.conn() as db:
            cid = db.execute("SELECT id FROM cases WHERE subject='환불이 안 돼요'").fetchone()['id']
            t = db.execute('SELECT * FROM case_triage WHERE case_id=?', (cid,)).fetchone()
            log = [r['actor'] + ':' + r['action'] for r in db.execute('SELECT * FROM case_log WHERE case_id=?', (cid,))]
            self.assertEqual(db.execute("SELECT COUNT(*) FROM messages WHERE case_id=? AND author='센터'", (cid,)).fetchone()[0], 0)  # 자동 발송 안 함
        self.assertEqual((t['track'], t['ai_track'], t['status']), ('auto', 'auto', 'draft'))
        self.assertEqual(json.loads(t['refs']), ['ecom:제17조:①', 'ecom:제18조:②'])  # 후보에 없는 조문은 버림
        self.assertIn('전자상거래 등에서의 소비자보호에 관한 법률', self.site.triage.law.cite('ecom:제17조:①')['law'])
        self.assertIn('- 전자상거래법 제17조 제1항 (청약철회등)', t['body'])
        self.assertIn('1372', t['body'])
        self.assertNotIn('010-1234-5678', t['body'])
        self.assertIn('자동:AI 분류: 자동 응답 · 답변 초안 생성', log)
        admin = self.login_admin()
        page = admin.get('/admin/reports/%d' % cid).get_data(as_text=True)
        self.assertIn('AI 분류 · 법률 안내 답변', page)
        self.assertIn('단순 반품·환불 문의라', page)
        listing = admin.get('/admin/reports').get_data(as_text=True)
        self.assertIn('자동 응답 <b>1</b>', listing)
        self.assertIn('<span class="tri-auto">자동 응답</span>', listing)
        self.assertNotIn('환불이 안 돼요', admin.get('/admin/reports?track=story').get_data(as_text=True))
        # 확인하고 보내기: 제보자 메시지로 들어가고 다시 누르면 막음
        body = t['body'].replace('안내드려요.', '안내드려요. (담당자 확인)')
        self.post_form(admin, '/admin/reports/%d' % cid, {'form': 'triage_send', 'body': body})
        self.post_form(admin, '/admin/reports/%d' % cid, {'form': 'triage_send', 'body': body})
        with self.site.conn() as db:
            msgs = db.execute("SELECT body FROM messages WHERE case_id=? AND author='센터'", (cid,)).fetchall()
            t = db.execute('SELECT * FROM case_triage WHERE case_id=?', (cid,)).fetchone()
        self.assertEqual(len(msgs), 1)
        self.assertIn('(담당자 확인)', msgs[0]['body'])
        self.assertEqual((t['status'], t['sent_by']), ('sent', '대표'))
        # 사람이 분류를 바꾸면 다시 만들어도 사람이 정한 분류 유지
        self.post_form(admin, '/admin/reports/%d' % cid, {'form': 'triage_track', 'track': 'story'})
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(desk, 'post_json', self.triage_ai([])):
            self.post_form(admin, '/admin/reports/%d' % cid, {'form': 'triage_run'})
        with self.site.conn() as db:
            t = db.execute('SELECT * FROM case_triage WHERE case_id=?', (cid,)).fetchone()
        self.assertEqual((t['track'], t['ai_track'], t['set_by']), ('story', 'auto', '대표'))
        self.assertIn('취재 검토 <b>1</b>', admin.get('/admin/reports').get_data(as_text=True))
        # 초안 없는 제보에서 '자동 응답'을 고르면 초안도 바로 만듦
        with self.site.conn() as db:
            db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,share_company) VALUES('T2','x','배송·교환·환불','고양이몰','예전 제보','반품했는데 환불이 안 돼요','환불','2026-10-01',0)")
            old = db.execute("SELECT id FROM cases WHERE receipt='T2'").fetchone()['id']
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(desk, 'post_json', self.triage_ai([], track='story')):
            self.post_form(admin, '/admin/reports/%d' % old, {'form': 'triage_track', 'track': 'auto'})
        with self.site.conn() as db:
            t2 = db.execute('SELECT * FROM case_triage WHERE case_id=?', (old,)).fetchone()
        self.assertEqual((t2['track'], t2['ai_track']), ('auto', 'story'))
        self.assertIn('■ 관련 법률 안내', t2['body'])
        # AI가 배열 대신 글 한 덩어리로 줘도 글자 단위로 쪼개지지 않음
        res = self.site.triage.clean({'track': 'auto', 'guidance': '헬스장 이용권은 계약서를 먼저 확인해요.\n\n남은 기간 환불은 분쟁해결기준을 따라요.', 'steps': '1. 계약서를 확인해요.\n2. 서면으로 요청해요.', 'refs': []},
                                     {'reporter_name': '홍길동'}, self.site.triage.POOL_ALL)
        self.assertEqual(res['guidance'], ['헬스장 이용권은 계약서를 먼저 확인해요.', '남은 기간 환불은 분쟁해결기준을 따라요.'])
        self.assertEqual(res['steps'], ['계약서를 확인해요.', '서면으로 요청해요.'])
        # 헬스장 같은 계속거래는 방문판매법 조문(원문)을 후보로 줌
        tri = self.site.triage
        self.assertIn('door:제31조', tri.ref_pool('계약·해지'))
        self.assertEqual(tri.law.cite('door:제31조')['label'], '방문판매법 제31조')
        self.assertIn('언제든지 계약을 해지할 수 있다', tri.law.plain('door:제31조'))
        self.assertIn('"계속거래"란 1개월 이상', tri.law.plain('door:제2조::10'))
        # 담당자별 몰아 보기
        self.post_form(admin, '/admin/reports/%d' % cid, {'form': 'settings', 'status': '검토 중', 'assignee': '이지우'})
        self.assertIn('환불이 안 돼요', admin.get('/admin/reports?assignee=이지우').get_data(as_text=True))
        self.assertNotIn('환불이 안 돼요', admin.get('/admin/reports?assignee=-').get_data(as_text=True))
        self.assertIn('이지우 <b>1</b>', admin.get('/admin/reports').get_data(as_text=True))

    def test_triage_corpus_candidates(self):
        """제보 글로 법령 원문 모음에서 찾은 조문이 'corpus:' 후보로 더해지고, 후보 밖 조문은 버리며, 근거 조문 목록에 이름이 붙는다."""
        tri = self.site.triage
        info = {'제보 유형': '품질·하자·AS', '업체·서비스명': '뷰티몰', '제목': '화장품에 사용기한 표시가 없어요',
                '피해 내용': '온라인에서 산 크림 포장에 사용기한이나 개봉 후 사용기간 표시가 없어요', '원하는 해결': '환불'}
        fixed = tri.ref_pool('품질·하자·AS')
        pool = tri.candidates({'category': '품질·하자·AS'}, info)
        self.assertEqual(pool[:len(fixed)], fixed)
        extra = pool[len(fixed):]
        self.assertIn('corpus:cosmetics:제10조', extra)
        self.assertTrue(all(r.startswith('corpus:') for r in extra))
        self.assertLessEqual(len(extra), tri.CORPUS_MAX)
        block = tri.law_block(pool)
        self.assertIn('[corpus:cosmetics:제10조] 화장품법 제10조 (화장품의 기재사항)', block)
        self.assertIn('사용기한 또는 개봉 후 사용기간', block)
        # 고정 후보에 이미 있는 조문(ecom:제17조:…)은 corpus 후보로 다시 넣지 않음
        refund = tri.candidates({'category': '배송·교환·환불'}, dict(info, 제목='환불이 안 돼요', **{'피해 내용': '운동화를 반품했는데 환불이 안 돼요'}))
        self.assertNotIn('corpus:ecom:제17조', refund)
        self.assertIn('corpus:ecom:제17조', tri.corpus_refs('운동화를 반품했는데 환불이 안 돼요'))
        res = tri.clean({'track': 'auto', 'guidance': ['화장품 포장에는 사용기한을 적어야 해요.'], 'steps': ['사진을 남겨 두세요.'],
                         'refs': ['corpus:cosmetics:제10조', 'ecom:제17조:③', 'corpus:civil:제750조', 'corpus:cosmetics:제999조']},
                        {'reporter_name': '홍길동'}, pool)
        self.assertEqual(res['refs'], ['corpus:cosmetics:제10조', 'ecom:제17조:③'])  # 후보에 없는 조문은 버림
        body = tri.compose(res)
        self.assertIn('- 화장품법 제10조 (화장품의 기재사항)', body)
        self.assertIn('- 전자상거래법 제17조 제3항 (청약철회등)', body)
        c = tri.cite('corpus:cosmetics:제10조')
        self.assertEqual((c['ref'], c['law']), ('corpus:cosmetics:제10조', '화장품법'))
        self.assertTrue(c['source'].startswith('https://www.law.go.kr/'))
        self.assertIn('[조문 후보]에 주어진 법령 원문에서만', tri.SYSTEM)

    def test_company_contacts_and_answer_registration(self):
        for subject in ('첫 제보', '둘째 제보'):
            self.post_form(self.client, '/report', dict(self.DESK_REPORT, subject=subject))
        with self.site.conn() as db:
            ids = [r['id'] for r in db.execute('SELECT id FROM cases ORDER BY id')]
        admin = self.login_admin()
        token = self.csrf(admin, f'/admin/reports/{ids[0]}')
        post = lambda cid, files=None, **d: admin.post(f'/admin/reports/{cid}', data={'_csrf': token, **d, **(files or {})}, content_type='multipart/form-data' if files else None)
        post(ids[0], form='desk_contact', name='고양이몰', aliases='냥몰', cs_email='cs@cat.example', kakao_url='http://evil.example/x')
        with self.site.conn() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM company_contacts').fetchone())  # 카카오 채널이 아닌 주소는 거절
        post(ids[0], form='desk_contact', name='고양이몰', aliases='냥몰', cs_email='cs@cat.example', kakao_url='pf.kakao.com/_abc', checked_on='2026-10-15', source='공식 홈페이지')
        # 같은 기업의 다른 제보에 자동으로 보임
        page = admin.get(f'/admin/reports/{ids[1]}').get_data(as_text=True)
        self.assertIn('data-copy-text="cs@cat.example"', page)
        self.assertIn('href="https://pf.kakao.com/_abc"', page)
        self.assertIn('카카오톡 채널 열기', page)
        # 기업 답변 등록 (원문 그대로, 첨부, 공식 여부)
        bad = post(ids[1], form='desk_answer', answer_company='고양이몰', received_on='2026-10-14', channel='nope', body='답변')
        with self.site.conn() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM messages WHERE author='기업 답변'").fetchone())
        body = '안녕하세요. 고양이몰 고객지원팀입니다.\n  반품 확인 후 환불하겠습니다.  '
        post(ids[1], files={'answer_files': (io.BytesIO(b'%PDF-1.4 a'), 'reply.pdf')}, form='desk_answer', answer_company='고양이몰', answer_person='CS팀 김OO',
             received_on='2026-10-14', channel='kakao', sender='카카오 채널', body=body, official='on', public='on')
        with self.site.conn() as db:
            m = db.execute("SELECT * FROM messages WHERE author='기업 답변'").fetchone()
            case = db.execute('SELECT status FROM cases WHERE id=?', (ids[1],)).fetchone()
            f = db.execute('SELECT * FROM answer_files').fetchone()
        self.assertEqual((m['answer_company'], m['answer_person'], m['channel'], m['official'], m['public'], m['received_on'], m['source']),
                         ('고양이몰', 'CS팀 김OO', 'kakao', 1, 1, '2026-10-14', 'admin'))
        self.assertEqual(m['body'], body.strip())
        self.assertEqual(case['status'], '기업 답변 도착')
        page = admin.get(f'/admin/reports/{ids[1]}').get_data(as_text=True)
        self.assertIn('공식 답변 확인', page)
        self.assertIn('reply.pdf', page)
        self.assertEqual(admin.get(f"/admin/answer-file/{f['id']}").status_code, 200)
        self.assertEqual(self.client.get(f"/admin/answer-file/{f['id']}").status_code, 302)
        self.assertNotIn('reply.pdf', self.client.get(f'/reports/{ids[1]}').get_data(as_text=True))  # 첨부는 공개 안 함
        # 연락처 목록: 요청·답변 이력
        listing = admin.get('/admin/contacts').get_data(as_text=True)
        self.assertIn('고양이몰', listing)
        self.assertIn('제보 2 · 요청 0 · 답변 1', listing)
        # 제보를 지우면 답변 첨부도 지움
        admin.post(f'/admin/reports/{ids[1]}', data={'_csrf': token, 'form': 'delete', 'confirm': '1'})
        self.assertFalse((Path(self.temp.name) / 'uploads' / f['stored']).exists())

    def test_login_lock_mypage_and_withdraw(self):
        self.signup(self.site.app.test_client())
        self.assertEqual(self.client.get('/me').status_code, 302)
        for _ in range(self.site.LOGIN_LOCK_FAILS):
            bad = self.post_form(self.client, '/login', {'login_id': 'sobo_ru', 'password': 'wrong-pass1'})
            self.assertEqual(bad.status_code, 401)
        locked = self.post_form(self.client, '/login', {'login_id': 'sobo_ru', 'password': 'butter123'})
        self.assertEqual(locked.status_code, 429)
        with self.site.conn() as db:
            db.execute("UPDATE users SET locked_until=''")
            db.execute('DELETE FROM login_attempts')
        ok = self.post_form(self.client, '/login?next=/report', {'login_id': 'sobo_ru', 'password': 'butter123', 'next': '/report'})
        self.assertEqual(ok.headers['Location'], '/report')
        evil = self.site.app.test_client()
        self.signup(evil, login_id='evil_one', nickname='다른사람')
        # 회원으로 제보하면 내 정보에 모이고, 다른 회원은 열 수 없음
        report = self.post_form(self.client, '/report', {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '테스트몰', 'subject': '회원 제보', 'description': '배송이 오지 않았어요.', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': '환불', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'secret'})
        self.assertEqual(report.status_code, 200)
        with self.site.conn() as db:
            case_id = db.execute("SELECT id FROM cases WHERE subject='회원 제보'").fetchone()['id']
        me = self.client.get('/me').get_data(as_text=True)
        self.assertIn('회원 제보', me)
        self.assertEqual(evil.get(f'/me/case/{case_id}').status_code, 404)
        self.assertEqual(self.client.get(f'/me/case/{case_id}').headers['Location'], '/case')
        self.assertIn('회원 제보', self.client.get('/case').get_data(as_text=True))
        # 회원 글은 비밀번호 없이 쓰고, 본인만 지울 수 있음
        made = self.post_form(self.client, '/board/write', {'category': '꿀팁', 'title': '회원 글이에요', 'body': '회원으로 쓰는 글입니다. 반가워요.', 'agree': 'on'})
        post_id = int(made.headers['Location'].rstrip('/').split('/')[-1])
        page = self.client.get(f'/board/{post_id}').get_data(as_text=True)
        self.assertIn('소보루</a><span class="cm-member">회원</span>', page)
        token = self.csrf(evil, f'/board/{post_id}')
        evil.post(f'/board/delete/p/{post_id}', data={'_csrf': token, 'password': ''})
        with self.site.conn() as db:
            self.assertIsNotNone(db.execute('SELECT 1 FROM posts WHERE id=?', (post_id,)).fetchone())
        # 비밀번호를 바꾸면 다른 기기 로그인은 끊김
        second = self.site.app.test_client()
        self.post_form(second, '/login', {'login_id': 'sobo_ru', 'password': 'butter123'})
        self.assertEqual(second.get('/me').status_code, 200)
        token = self.csrf(self.client, '/me')
        self.client.post('/me/edit', data={'_csrf': token, 'action': 'password', 'current': 'butter123', 'password': 'newbutter45', 'password2': 'newbutter45'})
        self.assertEqual(self.client.get('/me').status_code, 200)
        self.assertEqual(second.get('/me').status_code, 302)
        # 탈퇴: 회원 정보 삭제, 남긴 글은 "탈퇴한 회원", 제보는 연결만 끊김
        token = self.csrf(self.client, '/me')
        out = self.client.post('/me/withdraw', data={'_csrf': token, 'password': 'newbutter45', 'confirm': 'on'})
        self.assertEqual(out.status_code, 302)
        with self.site.conn() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM users WHERE login_id='sobo_ru'").fetchone())
            self.assertEqual(db.execute('SELECT nickname FROM posts WHERE id=?', (post_id,)).fetchone()['nickname'], '탈퇴한 회원')
            self.assertIsNone(db.execute('SELECT user_id FROM cases WHERE id=?', (case_id,)).fetchone()['user_id'])
        self.assertIn('>로그인</a>', self.client.get('/').get_data(as_text=True))

    def test_admin_can_suspend_members(self):
        member = self.site.app.test_client()
        self.signup(member)
        self.assertEqual(member.get('/me').status_code, 200)
        self.post_form(self.client, '/admin/login', {'password': self.password})
        listing = self.client.get('/admin/members').get_data(as_text=True)
        self.assertIn('sobo_ru', listing)
        with self.site.conn() as db:
            uid = db.execute('SELECT id FROM users').fetchone()['id']
        token = self.csrf(self.client, '/admin/members')
        self.client.post('/admin/members', data={'_csrf': token, 'id': uid, 'action': 'suspend'})
        self.assertEqual(member.get('/me').status_code, 302)
        blocked = self.post_form(member, '/login', {'login_id': 'sobo_ru', 'password': 'butter123'})
        self.assertEqual(blocked.status_code, 403)

    def test_staff_console_is_separate_from_admin(self):
        admin = self.login_admin()
        home = admin.get('/admin').get_data(as_text=True)
        self.assertIn('관리자 홈', home)
        self.assertIn('기자 계정', home)
        for label in ('사이트 화면 편집', '화면에서 바로 고치기', '첫 화면 사진', '메뉴·구성', '문구·사업자 정보·검색', '제보 처리'):
            self.assertIn(label, home)
        site = admin.get('/admin/site').get_data(as_text=True)
        self.assertIn('화면에서 바로 고치기', site)
        self.assertIn('편집 시작하기', site)
        token = self.csrf(admin, '/admin/staff')
        weak = admin.post('/admin/staff', data={'_csrf': token, 'action': 'add', 'name': '김민지', 'login_id': 'minji', 'password': 'short'}, follow_redirects=True)
        self.assertIn('8자 이상', weak.get_data(as_text=True))
        admin.post('/admin/staff', data={'_csrf': token, 'action': 'add', 'name': '김민지', 'login_id': 'minji', 'password': 'staffpass1'})
        with self.site.conn() as db:
            db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,share_company) VALUES('CJ-1','x','배송·환불','가게','배송이 안 와요','내용','환불','2026-10-09T10:00:00',1)")
            case_id = db.execute("SELECT id FROM cases WHERE receipt='CJ-1'").fetchone()['id']
        # 관리자로 로그인한 브라우저라도 기자실은 기자 로그인 없이는 못 들어가고, 들어가도 관리자 메뉴는 없음
        both = self.login_admin()
        self.assertIn('/reporter/login', both.get('/reporter').headers['Location'])
        self.post_form(both, '/reporter/login', {'login_id': 'minji', 'password': 'staffpass1'})
        page = both.get('/reporter').get_data(as_text=True)
        self.assertIn('기자실', page)
        for admin_text in ('사이트 문구', '기자 계정', '메뉴·항목', '회원</a>', '게시판</a>'):
            self.assertNotIn(admin_text, page)
        staff = self.site.app.test_client()
        self.assertEqual(staff.get('/reporter').status_code, 302)
        bad = self.post_form(staff, '/reporter/login', {'login_id': 'minji', 'password': 'wrong1234'})
        self.assertEqual(bad.status_code, 401)
        ok = self.post_form(staff, '/reporter/login', {'login_id': 'minji', 'password': 'staffpass1'})
        self.assertEqual(ok.headers['Location'], '/reporter')
        listing = staff.get('/reporter').get_data(as_text=True)
        self.assertIn('배송이 안 와요', listing)
        self.assertIn('김민지 기자', listing)
        self.assertNotIn('사이트 문구', listing)
        # 직원은 관리자 메뉴에 들어갈 수 없음
        for path in ('/admin', '/admin/content', '/admin/lists', '/admin/members', '/admin/staff', '/admin/board'):
            self.assertEqual(staff.get(path).status_code, 302, path)
            self.assertIn('/admin/login', staff.get(path).headers['Location'])
        path = '/reporter/case/%d' % case_id
        token = self.csrf(staff, path)
        staff.post(path, data={'_csrf': token, 'form': 'settings', 'status': '검토 중', 'assignee': '김민지'})
        staff.post(path, data={'_csrf': token, 'form': 'message', 'message': '확인 중입니다'})
        page = staff.get(path).get_data(as_text=True)
        self.assertIn('진행 단계 변경: 접수 → 검토', page)
        self.assertIn('<option value="검토 중" selected>2. 검토</option>', page)  # 관리 화면도 5단계
        listing5 = staff.get('/reporter').get_data(as_text=True)
        for name in ('기업 전달', '기업 답변·처리', '완료·평가'):self.assertIn(name, listing5)
        self.assertNotIn('기업 답변 대기', listing5)
        self.assertIn('<b>김민지</b>', page)
        self.assertNotIn('내부 메모', page)
        self.assertIn('확인 중입니다', page)
        self.assertIn('내 담당 제보', staff.get('/reporter').get_data(as_text=True))
        self.assertIn('class="ad-side"', staff.get('/reporter').get_data(as_text=True))  # 관리자와 같은 공통 레이아웃
        # 제보자는 조회 화면에서 센터 담당자와 메시지를 보낸 담당자를 볼 수 있음
        me = self.site.app.test_client()
        with me.session_transaction() as sess:sess['case_id'] = case_id
        mine = me.get('/case').get_data(as_text=True)
        self.assertIn('<span>센터 담당자</span><b>김민지</b>', mine)
        self.assertIn('센터 · 김민지 담당자', mine)
        self.assertIn('배송이 안 와요', staff.get('/reporter?mine=1').get_data(as_text=True))
        self.assertNotIn('배송이 안 와요', staff.get('/reporter?status=종결').get_data(as_text=True))
        self.assertEqual(staff.get('/staff/case/%d' % case_id).headers['Location'], path)
        self.assertEqual(staff.get('/staff/login').headers['Location'], '/reporter/login')
        self.assertEqual(staff.get('/admin/reports/%d' % case_id).status_code, 302)
        # 기자는 제보를 삭제할 수 없음
        self.assertNotIn('제보 삭제', page)
        self.assertEqual(self.post_form(staff, path, {'form': 'delete', 'confirm': '1'}).status_code, 400)
        # 관리자가 계정을 중지하면 바로 로그아웃
        with self.site.conn() as db:
            sid = db.execute("SELECT id FROM staff WHERE login_id='minji'").fetchone()['id']
        admin.post('/admin/staff', data={'_csrf': self.csrf(admin, '/admin/staff'), 'action': 'stop', 'id': sid})
        self.assertEqual(staff.get('/reporter').status_code, 302)
        stopped = self.post_form(staff, '/reporter/login', {'login_id': 'minji', 'password': 'staffpass1'})
        self.assertEqual(stopped.status_code, 403)
        # 대표(관리자)도 제보 관리 화면을 볼 수 있음
        self.assertIn('배송이 안 와요', admin.get('/admin/reports').get_data(as_text=True))
        self.assertIn('관리자', admin.get('/admin/reports').get_data(as_text=True))

    def test_admin_changes_password_in_admin(self):
        admin = self.login_admin()
        other = self.login_admin()
        token = self.csrf(admin, '/admin/password')
        wrong = admin.post('/admin/password', data={'_csrf': token, 'current': 'nope', 'password': 'NewAdminPass99', 'password2': 'NewAdminPass99'}, follow_redirects=True)
        self.assertIn('지금 비밀번호가 맞지 않아요', wrong.get_data(as_text=True))
        short = admin.post('/admin/password', data={'_csrf': token, 'current': self.password, 'password': '123', 'password2': '123'}, follow_redirects=True)
        self.assertIn('4자 이상', short.get_data(as_text=True))
        done = admin.post('/admin/password', data={'_csrf': token, 'current': self.password, 'password': 'NewAdminPass99', 'password2': 'NewAdminPass99'})
        self.assertEqual(done.headers['Location'], '/admin')
        self.assertEqual(admin.get('/admin').status_code, 200)  # 바꾼 화면은 그대로 로그인
        self.assertEqual(other.get('/admin').status_code, 302)  # 다른 기기는 로그아웃
        fresh = self.site.app.test_client()
        old = self.post_form(fresh, '/admin/login', {'password': self.password})
        self.assertNotEqual(old.headers.get('Location'), '/admin/choose')
        new = self.post_form(fresh, '/admin/login', {'password': 'NewAdminPass99'})
        self.assertEqual(new.headers['Location'], '/admin/choose')  # 운영자 2026-11-05: 들어오면 먼저 제보센터·매거진 고르기

    def test_every_screen_text_is_editable(self):
        self.old_guide()
        admin = self.login_admin()
        page = admin.get('/admin/content').get_data(as_text=True)
        for key in ('report.submit', 'common.login', 'home.intro_title', 'home.write1', 'sb.nav_home', 'member.signup_btn', 'msg.welcome', 'guide.u1'):
            self.assertIn('name="%s"' % key, page)
        token = self.csrf(admin, '/admin/content')
        admin.post('/admin/content', data={'_csrf': token, 'section': 'report', 'report.submit': '지금 제보하기', 'report.c3_title': '콘텐츠 이용 동의'})
        form = self.client.get('/report').get_data(as_text=True)
        self.assertIn('지금 제보하기', form)
        self.assertIn('콘텐츠 이용 동의', form)
        self.assertNotIn('제보 접수하기 ↗', form)
        admin.post('/admin/content', data={'_csrf': token, 'section': 'common', 'common.login': '로그인하기'})
        self.assertNotIn('name="site.brand"', page)  # 예전 브랜드 바꾸기 칸은 뺌
        self.assertIn('>로그인하기</a>', self.client.get('/').get_data(as_text=True))
        admin.post('/admin/content', data={'_csrf': token, 'section': 'guide', 'guide.u1': '파일은 **하나만** 올려 주세요'})
        self.assertIn('파일은 <strong>하나만</strong> 올려 주세요', self.client.get('/guide').get_data(as_text=True))
        admin.post('/admin/content', data={'_csrf': token, 'section': 'report', 'reset_section': 'report'})
        self.assertIn('제보 접수하기 ↗', self.client.get('/report').get_data(as_text=True))

    def test_edit_mode_on_the_site(self):
        self.old_guide()
        admin = self.login_admin()
        self.assertNotIn('data-k=', admin.get('/guide').get_data(as_text=True))
        token = self.csrf(admin, '/admin')
        admin.post('/admin/edit-mode', data={'_csrf': token, 'on': '1'})
        for path in ('/', '/guide', '/process', '/faq', '/report', '/board', '/signup', '/reports', '/lookup', '/privacy'):
            page = admin.get(path).get_data(as_text=True)
            self.assertNotRegex(page, '[\ue000-\ue002]', path)  # 숨은 표시가 남지 않음
            self.assertIn('data-k=', page, path)
            self.assertIn('id="ed-data"', page, path)
            title = re.search(r'<title>(.*?)</title>', page, re.S)[1]
            self.assertNotIn('<span', title, path)
            self.assertNotRegex(page, r'(placeholder|aria-label|content)="[^"]*<span', path)
        guide = admin.get('/guide').get_data(as_text=True)
        self.assertIn('data-k="list:guide_basics:0:title"', guide)
        self.assertIn('data-k="list:guide_topics:0:steps"', guide)
        self.assertIn('href="/admin/lists#list-guide_topics"', guide)
        # 사이트 화면에서 문장 고치기: 화면 문구, 목록 항목, 진행 단계 이름
        token = self.csrf(admin, '/guide')
        self.assertTrue(admin.post('/admin/inline', data={'_csrf': token, 'key': 'guide.u_title', 'value': '첨부 전 체크'}).get_json()['ok'])
        self.assertTrue(admin.post('/admin/inline', data={'_csrf': token, 'key': 'list:guide_basics:0:title', 'value': '구매한 날'}).get_json()['ok'])
        self.assertTrue(admin.post('/admin/inline', data={'_csrf': token, 'key': 'status.p1', 'value': '접수 완료'}).get_json()['ok'])
        self.assertEqual(admin.post('/admin/inline', data={'_csrf': token, 'key': 'list:guide_basics:0:title', 'value': ''}).status_code, 400)
        self.assertEqual(admin.post('/admin/inline', data={'_csrf': token, 'key': 'list:menu:0:page', 'value': 'x'}).status_code, 400)
        self.assertEqual(admin.post('/admin/inline', data={'_csrf': token, 'key': 'nope', 'value': 'x'}).status_code, 400)
        public = self.client.get('/guide').get_data(as_text=True)
        self.assertIn('첨부 전 체크', public)
        self.assertIn('구매한 날', public)
        self.assertNotIn('data-k=', public)
        with self.site.conn() as db:
            db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('edit-mode', hashlib.sha256(b'edit').hexdigest(), '배송·환불', '단계 업체', '단계 이름 제보', '내용', '요청', '2026-10-17', 1, 1))
        self.assertIn('class="vcs-st vcs-1">접수 완료<', self.client.get('/reports').get_data(as_text=True))  # 제보 카드의 공개 단계 이름
        admin.post('/admin/inline', data={'_csrf': token, 'key': 'guide.u_title', 'value': '', 'reset': '1'})
        self.assertIn('첨부하기 전에 확인해 주세요', self.client.get('/guide').get_data(as_text=True))
        self.assertEqual(self.client.post('/admin/inline', data={'_csrf': self.csrf(self.client, '/report'), 'key': 'guide.u_title', 'value': 'x'}).status_code, 302)
        # 처리 절차·FAQ 문구를 고쳐도 단계 카드와 질문 목록은 그대로 유지
        steps_before = self.client.get('/process').get_data(as_text=True).count('class="process-card"')
        admin.post('/admin/inline', data={'_csrf': token, 'key': 'process.card_step', 'value': '스텝'})
        admin.post('/admin/inline', data={'_csrf': token, 'key': 'faq.title', 'value': '궁금해요'})
        process = self.client.get('/process').get_data(as_text=True)
        self.assertEqual(process.count('class="process-card"'), steps_before)
        self.assertIn('1스텝', process)
        self.assertIn('궁금해요', self.client.get('/faq').get_data(as_text=True))
        admin.post('/admin/edit-mode', data={'_csrf': token, 'on': '0'})
        self.assertNotIn('data-k=', admin.get('/guide').get_data(as_text=True))

    def test_page_sections_and_custom_pages(self):
        self.old_guide()
        guide = self.client.get('/guide').get_data(as_text=True)
        self.assertLess(guide.index('id="purchase-info"'), guide.index('id="photo-guide"'))
        admin = self.login_admin()
        token = self.csrf(admin, '/admin/lists')
        # 이용 안내: 03을 맨 앞으로, 02는 빼고, 글 상자 추가
        admin.post('/admin/lists', data={'_csrf': token, 'list': 'layout_guide',
            'kind': ['guide_evidence', 'text', 'guide_basics', 'guide_topics', 'guide_bottom'],
            'title': ['', '먼저 읽어 주세요', '', '', ''], 'body': ['', '**사진**이 가장 중요해요', '', '', ''],
            'button_label': ['', '', '', '', ''], 'button_link': ['', '', '', '', '']})
        guide = self.client.get('/guide').get_data(as_text=True)
        self.assertNotIn('id="writing-guide"', guide)
        self.assertLess(guide.index('id="photo-guide"'), guide.index('먼저 읽어 주세요'))
        self.assertLess(guide.index('먼저 읽어 주세요'), guide.index('id="purchase-info"'))
        self.assertIn('<strong class="em">사진</strong>', guide)
        self.assertRegex(guide, r'guide-number" aria-hidden="true">01</span><h2 id="photo-heading">')
        self.assertNotIn('href="#writing-guide"', guide)
        # 처리 절차에 안내 박스 추가
        admin.post('/admin/lists', data={'_csrf': token, 'list': 'layout_process', 'kind': ['notice', 'process_cards'],
            'title': ['상담 전화', ''], 'body': ['평일 10시~5시', ''], 'button_label': ['제보하기', ''], 'button_link': ['/report', '']})
        process = self.client.get('/process').get_data(as_text=True)
        self.assertLess(process.index('상담 전화'), process.index('class="process-cards"'))
        bad = admin.post('/admin/lists', data={'_csrf': token, 'list': 'layout_faq', 'kind': ['notice'], 'title': ['x'], 'body': [''], 'button_label': ['go'], 'button_link': ['javascript:alert(1)']})
        self.assertEqual(bad.status_code, 400)
        # 새 페이지
        admin.post('/admin/lists', data={'_csrf': token, 'list': 'custom_pages', 'slug': ['about'], 'title': ['소보루 소개'], 'body': ['## 우리는\n- 소비자 편에 섭니다']})
        page = self.client.get('/p/about').get_data(as_text=True)
        self.assertIn('<h1>소보루 소개</h1>', page)
        self.assertIn('<h2 id="sec-1">우리는</h2>', page)
        self.assertIn('<li>소비자 편에 섭니다</li>', page)
        self.assertEqual(self.client.get('/p/none').status_code, 404)
        self.assertIn('/p/about', self.client.get('/sitemap.xml').get_data(as_text=True))
        self.assertEqual(admin.post('/admin/lists', data={'_csrf': token, 'list': 'custom_pages', 'slug': ['About Us'], 'title': ['x'], 'body': ['y']}).status_code, 400)
        # 편집 모드: 페이지 이동 목록과 섹션 바로가기
        admin.post('/admin/edit-mode', data={'_csrf': self.csrf(admin, '/admin'), 'on': '1'})
        edit = admin.get('/p/about').get_data(as_text=True)
        self.assertIn('고칠 페이지 고르기', edit)
        self.assertIn('새 페이지: 소보루 소개', edit)
        self.assertIn('data-k="list:custom_pages:0:body"', edit)
        self.assertIn('이 페이지 섹션 추가', admin.get('/process').get_data(as_text=True))
        self.assertIn('data-k="list:layout_process:0:title"', admin.get('/process').get_data(as_text=True))

    def test_remove_consent_and_sections(self):
        admin = self.login_admin()
        admin.post('/admin/edit-mode', data={'_csrf': self.csrf(admin, '/admin'), 'on': '1'})
        form = admin.get('/report').get_data(as_text=True)
        self.assertIn('data-list="report_consents" data-i="3"', form)
        token = self.csrf(admin, '/report')
        # 사실 작성 확인(4번째) 빼기 → 화면에서 사라지고 체크 없이도 접수
        self.assertTrue(admin.post('/admin/list-remove', data={'_csrf': token, 'list': 'report_consents', 'index': 3}).get_json()['ok'])
        public = self.client.get('/report').get_data(as_text=True)
        self.assertNotIn('사실 작성 확인', public)
        self.assertNotIn('name="truth"', public)
        t = self.csrf(self.client, '/report')
        ok = self.client.post('/report', data={'_csrf': t, 'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': 'A', 'subject': '사실확인 없이', 'description': 'C', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': 'D', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'visibility': 'secret'})
        self.assertEqual(ok.status_code, 200)
        # 직접 만든 동의 항목은 필수
        rows = self.site.load_lists()['report_consents'] + [{'kind': 'custom', 'title': '연락 동의', 'body': '확인 연락을 드릴 수 있어요.', 'agree': '연락에 동의해요.'}]
        admin.post('/admin/lists', data={'_csrf': token, 'list': 'report_consents', 'kind': [r['kind'] for r in rows], 'title': [r['title'] for r in rows], 'body': [r['body'] for r in rows], 'agree': [r['agree'] for r in rows]})
        public = self.client.get('/report').get_data(as_text=True)
        self.assertIn('연락 동의', public)
        self.assertIn('name="consent_custom_3"', public)
        base = {'_csrf': t, 'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': 'A', 'subject': 'B', 'description': 'C', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': 'D', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'visibility': 'secret'}
        self.assertEqual(self.client.post('/report', data=base).status_code, 400)
        self.assertEqual(self.client.post('/report', data={**base, 'consent_custom_3': 'on'}).status_code, 200)
        # 페이지 섹션도 빼기
        guide = admin.get('/guide').get_data(as_text=True)
        self.assertIn('data-list="layout_guide" data-i="1"', guide)
        admin.post('/admin/list-remove', data={'_csrf': token, 'list': 'layout_guide', 'index': 1})
        self.assertNotIn('id="writing-guide"', self.client.get('/guide').get_data(as_text=True))
        self.assertEqual(admin.post('/admin/list-remove', data={'_csrf': token, 'list': 'layout_guide', 'index': 99}).status_code, 404)
        self.assertEqual(self.client.post('/admin/list-remove', data={'_csrf': t, 'list': 'layout_guide', 'index': 0}).status_code, 302)

    def test_delete_text_while_editing(self):
        self.old_guide()
        admin = self.login_admin()
        admin.post('/admin/edit-mode', data={'_csrf': self.csrf(admin, '/admin'), 'on': '1'})
        token = self.csrf(admin, '/report')
        self.assertIn('"del": "text"', admin.get('/guide').get_data(as_text=True))
        # 문장 지우기 → 방문자 화면에서 사라지고, 편집 모드에서는 흐린 자리로 남음
        self.assertTrue(admin.post('/admin/inline', data={'_csrf': token, 'key': 'guide.s1_desc', 'delete': '1'}).get_json()['ok'])
        self.assertNotIn('구매일 대신 계약일', self.client.get('/guide').get_data(as_text=True))
        self.assertIn('지운 문장 · 눌러서 되살리기', admin.get('/guide').get_data(as_text=True))
        admin.post('/admin/inline', data={'_csrf': token, 'key': 'guide.s1_desc', 'reset': '1'})
        self.assertIn('구매일 대신 계약일', self.client.get('/guide').get_data(as_text=True))
        # 화면 문구(ui)도 지울 수 있음
        admin.post('/admin/inline', data={'_csrf': token, 'key': 'report.consent_all', 'delete': '1'})
        self.assertNotIn('아래 내용에 모두 동의해요', self.client.get('/report').get_data(as_text=True))
        # 지우면 안 되는 문구는 거절
        self.assertEqual(admin.post('/admin/inline', data={'_csrf': token, 'key': 'site.name', 'delete': '1'}).status_code, 400)
        # 목록의 둘째 칸은 지우기, 첫째 칸은 항목째 빼기로 안내
        self.assertTrue(admin.post('/admin/inline', data={'_csrf': token, 'key': 'list:guide_basics:0:body', 'delete': '1'}).get_json()['ok'])
        self.assertEqual(admin.post('/admin/inline', data={'_csrf': token, 'key': 'list:guide_basics:0:title', 'delete': '1'}).status_code, 400)
        self.assertIn('"del": "item"', admin.get('/guide').get_data(as_text=True))

    def test_new_guide_page(self):
        guide = self.client.get('/guide').get_data(as_text=True)
        self.assertIn('한눈에 보는 제보 방법', guide)
        self.assertEqual(guide.count('class="gd-steps"'), 1)
        self.assertEqual(guide.count('img/guide-cut'), 3)
        self.assertEqual(guide.count('class="gd-ind"'), 10)
        self.assertEqual(guide.count('img/guide-ind-'), 10)
        self.assertIn('<h3>의약·의료</h3>', guide)
        self.assertIn('<h3>게임·앱</h3>', guide)
        self.assertEqual(self.client.get('/static/img/guide-ind-game.svg').status_code, 200)
        self.assertIn('<li>계정 아이디와 서버</li>', guide)
        self.assertEqual(self.client.get('/static/img/guide-cut1.svg').status_code, 200)
        self.assertIn('rel="apple-touch-icon"', guide)
        self.assertIn('<meta property="og:image" content="http://localhost/static/soboru-og.png', guide)
        for path in ('/favicon.ico', '/static/favicon.svg', '/static/apple-touch-icon.png', '/static/og-image.png'):
            resp = self.client.get(path); self.assertEqual(resp.status_code, 200); resp.close()
        admin = self.login_admin()
        admin.post('/admin/edit-mode', data={'_csrf': self.csrf(admin, '/admin'), 'on': '1'})
        page = admin.get('/guide').get_data(as_text=True)
        self.assertIn('data-k="list:guide_industries:0:must"', page)
        self.assertIn('data-k="list:guide_steps:0:title"', page)
        token = self.csrf(admin, '/report')
        self.assertTrue(admin.post('/admin/inline', data={'_csrf': token, 'key': 'guide.c2_k4', 'delete': '1'}).get_json()['ok'])
        self.assertTrue(admin.post('/admin/inline', data={'_csrf': token, 'key': 'list:guide_industries:0:tip', 'value': '이물은 냉동 보관'}).get_json()['ok'])
        public = self.client.get('/guide').get_data(as_text=True)
        self.assertNotIn('원하는 해결</li>', public)
        self.assertIn('이물은 냉동 보관', public)
        # 제보하기 업종 칸도 같은 분류를 씀
        report = self.client.get('/report').get_data(as_text=True)
        self.assertIn('<option value="의약·의료">', report)

    def test_admin_session_ends_properly(self):
        admin = self.login_admin()
        admin.post('/admin/edit-mode', data={'_csrf': self.csrf(admin, '/admin'), 'on': '1'})
        self.assertIn('ed-bar', admin.get('/guide').get_data(as_text=True))
        # 로그아웃하면 관리자 화면·편집 모드 모두 닫힘
        admin.post('/admin/logout', data={'_csrf': self.csrf(admin, '/admin')})
        self.assertEqual(admin.get('/admin').status_code, 302)
        self.assertNotIn('ed-bar', admin.get('/guide').get_data(as_text=True))
        self.assertEqual(admin.post('/admin/inline', data={'_csrf': self.csrf(admin, '/report'), 'key': 'guide.u_title', 'value': 'x'}).status_code, 302)
        # 2시간 넘게 쓰지 않으면 자동 로그아웃
        admin = self.login_admin()
        with admin.session_transaction() as sess:
            sess['admin_at'] -= self.site.ADMIN_IDLE_SECONDS + 1
        self.assertEqual(admin.get('/admin').status_code, 302)
        # 회원 '로그인 상태 유지'가 관리자 권한을 이어받지 않음
        admin = self.login_admin()
        self.signup(self.site.app.test_client(), login_id='keeper1', nickname='유지회원')
        self.post_form(admin, '/login', {'login_id': 'keeper1', 'password': 'butter123', 'remember': 'on'})
        self.assertEqual(admin.get('/admin').status_code, 302)
        self.assertEqual(admin.get('/me').status_code, 200)

    def test_detailed_report_form(self):
        form = self.client.get('/report').get_data(as_text=True)
        for name in ('reporter_name', 'phone', 'region_sido', 'region_sigungu', 'region_detail', 'gender', 'age_group'):
            self.assertIn('name="%s"' % name, form)
        self.assertIn('multiple accept=', form)
        token = self.csrf(self.client, '/report')
        base = {'_csrf': token, 'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '상세몰', 'subject': '상세 제보', 'description': '내용', 'request_text': '환불',
                'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'public'}
        self.assertEqual(self.client.post('/report', data=base).status_code, 400)  # 이름·전화 필수
        self.assertEqual(self.client.post('/report', data={**base, 'reporter_name': '홍길동', 'phone': 'abc'}).status_code, 400)
        self.assertEqual(self.client.post('/report', data={**base, 'reporter_name': '홍길동', 'phone': '010-1111-2222', 'website': 'bot'}).status_code, 400)
        import io
        png = b'\x89PNG\r\n\x1a\n' + b'0' * 50
        mp4 = b'\x00\x00\x00\x18ftypmp42' + b'0' * 50
        files = {'evidence': [(io.BytesIO(png), '영수증.png'), (io.BytesIO(mp4), '영상.mp4')]}
        ok = self.client.post('/report', data={**base, 'reporter_name': '홍길동', 'phone': '010-1111-2222', 'region_sido': '서울', 'region_sigungu': '강남구',
                                                'gender': '여성', 'age_group': '30대', **files}, content_type='multipart/form-data')
        self.assertEqual(ok.status_code, 200)
        with self.site.conn() as db:
            case = db.execute("SELECT * FROM cases WHERE subject='상세 제보'").fetchone()
            names = [r['original'] for r in db.execute('SELECT original FROM attachments WHERE case_id=?', (case['id'],))]
        self.assertEqual((case['reporter_name'], case['phone'], case['region_sido'], case['gender'], case['age_group']), ('홍길동', '010-1111-2222', '서울', '여성', '30대'))
        self.assertEqual(sorted(names), ['영상.mp4', '영수증.png'])
        # 공개 화면에는 제보자 정보가 나오지 않음
        public = self.client.get('/reports/%d' % case['id']).get_data(as_text=True)
        self.assertNotIn('홍길동', public)
        self.assertNotIn('010-1111-2222', public)
        # 관리자 화면에는 보임
        admin = self.login_admin()
        detail = admin.get('/admin/reports/%d' % case['id']).get_data(as_text=True)
        for text in ('홍길동', '010-1111-2222', '서울 강남구', '여성', '30대', '영상.mp4'):
            self.assertIn(text, detail)
        bad = self.client.post('/report', data={**base, 'subject': '가짜파일', 'reporter_name': '홍길동', 'phone': '010-1111-2222', 'evidence': [(io.BytesIO(b'hello'), 'x.png')]}, content_type='multipart/form-data')
        self.assertEqual(bad.status_code, 400)

    def test_disabled_intake_and_csrf(self):
        self.assertEqual(self.client.post('/report', data={}).status_code, 400)
        token = self.csrf(self.client, '/report')
        with patch.dict(os.environ, {'ENABLE_INTAKE': '0'}):
            self.assertEqual(self.client.post('/report', data={'_csrf': token}).status_code, 503)
            self.assertIn('disabled title="현재 접수 준비 중"', self.client.get('/report').get_data(as_text=True))


    def test_company_page_flow(self):
        # 기업별 공개 페이지, 기업 검색, 공개 심사, 7단계 진행 이력 (jebo.py)
        admin = self.login_admin()
        self.post_form(admin, '/admin/companies', {'action': 'create', 'name': '검은고양이몰', 'brand': 'BC몰', 'biz_name': '주식회사 검은고양이', 'official_email': 'cs@bc.example'})
        self.assertIn('같은 이름의 기업이 이미 있어요', self.post_form(admin, '/admin/companies', {'action': 'create', 'name': '(주)검은고양이몰'}).headers.get('Location', '') and admin.get('/admin/companies').get_data(as_text=True))
        with self.site.conn() as db:
            co = db.execute("SELECT * FROM companies WHERE name='검은고양이몰'").fetchone()
            self.assertEqual(co['status'], 'listed')
            self.assertEqual(db.execute("SELECT COUNT(*) FROM companies WHERE name LIKE '%검은고양이몰%'").fetchone()[0], 1)
        rows = self.client.get('/companies/suggest?q=bc').get_json()
        self.assertEqual([r['name'] for r in rows], ['검은고양이몰'])
        # 이름만 있는 기업 페이지는 검색엔진에 싣지 않음
        page = self.client.get('/companies/%d' % co['id']).get_data(as_text=True)
        self.assertIn('noindex', page)
        self.assertIn('아직 들어온 제보가 없어요', page)
        self.assertNotIn('/companies/%d<' % co['id'], self.client.get('/sitemap.xml').get_data(as_text=True))
        # 브랜드 이름으로 제보해도 그 기업에 자동으로 모임. 발생일도 저장
        base = {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': 'BC몰', 'subject': '원래 제목 홍길동', 'description': '주문번호 A-123 환불이 안 돼요',
                'reporter_name': '홍길동', 'phone': '010-4444-5555', 'request_text': '환불', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234',
                'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'public', 'occurred_on': '2026-10-01'}
        self.post_form(self.client, '/report', base)
        with self.site.conn() as db:
            case = db.execute("SELECT * FROM cases WHERE subject='원래 제목 홍길동'").fetchone()
        self.assertEqual(case['company_id'], co['id'])
        self.assertEqual(case['occurred_on'], '2026-10-01')
        # 공개 제보는 접수 즉시 게시되고 검토 결과는 '미검토'
        self.assertEqual((case['published'], case['review'], case['reviewed_at']), (1, '', ''))
        self.assertIn('원래 제목', self.client.get('/companies/%d' % co['id']).get_data(as_text=True))
        # 운영자가 사후에 공개용 글을 다듬음 → 원문은 그대로, 공개 화면은 다듬은 글. 검토 결과는 따로 '정상'으로
        path = '/admin/reports/%d' % case['id']
        self.post_form(admin, path, {'form': 'publish_review', 'decision': 'save', 'public_subject': '환불이 한 달째 안 돼요', 'public_body': '환불이 안 돼요', 'public_request': ''})
        self.post_form(admin, path, {'form': 'review', 'review': 'ok', 'review_note': '무시됨'})
        with self.site.conn() as db:
            case = db.execute('SELECT * FROM cases WHERE id=?', (case['id'],)).fetchone()
        self.assertEqual((case['published'], case['review'], case['review_note'], case['subject']), (1, 'ok', '', '원래 제목 홍길동'))
        self.assertEqual((case['reviewed_at'], case['status']), ('', '접수'))  # 검토 결과는 진행 단계를 바꾸지 않음
        page = self.client.get('/companies/%d' % co['id']).get_data(as_text=True)
        self.assertIn('환불이 한 달째 안 돼요', page)
        self.assertNotIn('홍길동', page)
        self.assertNotIn('noindex', page)
        self.assertIn('공식 답변 미등록', page)
        self.assertIn('/companies/%d<' % co['id'], self.client.get('/sitemap.xml').get_data(as_text=True))
        self.assertIn('검은고양이몰', self.client.get('/companies?q=검은고양이').get_data(as_text=True))
        self.assertIn('환불이 한 달째', self.client.get('/reports?q=한 달째').get_data(as_text=True))
        self.assertNotIn('원래 제목', self.client.get('/reports?q=원래').get_data(as_text=True))
        public = self.client.get('/reports/%d' % case['id']).get_data(as_text=True)
        self.assertNotIn('public-case-notice', public)  # 아래 안내 문구·내 제보 버튼은 뺌
        self.assertNotIn('public-case-mine', public)
        for text in ('환불이 한 달째 안 돼요', '공식 답변 미등록', 'href="/companies/%d"' % co['id'], 'aria-current="step"><span class="stepper-dot">1</span><span class="stepper-label">접수'):
            self.assertIn(text, public)
        self.assertNotIn('A-123', public)
        # 답변 링크 발급 = 전달 시도, 기업이 열어 봐야 '전달 확인'
        token = self.csrf(admin, path)
        response = admin.post('/admin/invite/%d' % case['id'], data={'_csrf': token})
        invite = re.search(r'<strong>(http://localhost/company/[^<]+)</strong>', response.get_data(as_text=True))[1].removeprefix('http://localhost')
        with self.site.conn() as db:
            row = db.execute('SELECT forwarded_at,seen_at FROM cases WHERE id=?', (case['id'],)).fetchone()
        self.assertTrue(row['forwarded_at'])
        self.assertEqual(row['seen_at'], '')
        self.assertIn('기업 전달 시도', self.client.get('/reports/%d' % case['id']).get_data(as_text=True))
        company = self.site.app.test_client()
        self.post_form(company, invite, {'response': '확인 후 환불해 드리겠습니다.'})
        with self.site.conn() as db:
            self.assertTrue(db.execute('SELECT seen_at FROM cases WHERE id=?', (case['id'],)).fetchone()['seen_at'])
            mid = db.execute("SELECT id FROM messages WHERE case_id=? AND author='기업 답변'", (case['id'],)).fetchone()['id']
        self.assertNotIn('환불해 드리겠습니다', self.client.get('/reports/%d' % case['id']).get_data(as_text=True))
        self.post_form(admin, path, {'form': 'answer_public', 'message_id': mid, 'public': '1'})
        public = self.client.get('/reports/%d' % case['id']).get_data(as_text=True)
        self.assertIn('확인 후 환불해 드리겠습니다.', public)
        self.assertIn('기업 전달 확인', public)
        self.assertNotIn('공식 답변 미등록', public)
        # 표본이 적으면 비율은 '–'
        page = self.client.get('/companies/%d' % co['id']).get_data(as_text=True)
        self.assertIn('<dt>공식 답변 비율</dt><dd>–</dd>', page)
        self.assertIn('<dt>확인된 제보</dt><dd>1</dd>', page)
        # 반려하면 공개가 내려가고 통계에서 빠짐
        self.post_form(admin, path, {'form': 'review', 'review': 'rejected', 'review_note': '허위 확인'})
        self.assertEqual(self.client.get('/reports/%d' % case['id']).status_code, 404)
        self.assertIn('<dt>확인된 제보</dt><dd>0</dd>', self.client.get('/companies/%d' % co['id']).get_data(as_text=True))
        with self.site.conn() as db:
            self.assertEqual(db.execute('SELECT review_note FROM cases WHERE id=?', (case['id'],)).fetchone()[0], '허위 확인')
        listing = self.client.get('/reports').get_data(as_text=True)
        self.assertNotIn('/reports/%d"' % case['id'], listing)  # 제외한 제보는 공개 목록에서 빠짐
        self.assertNotIn('/reports/%d/mine"' % case['id'], listing)
        listing = admin.get('/admin/reports?review=rejected').get_data(as_text=True)
        self.assertIn('rv-chip rv-rejected">제외', listing)
        self.assertNotIn('rv-chip rv-new', listing)
        # 이름만으로 새 기업 등록 후 연결
        self.post_form(self.client, '/report', dict(base, company='새로운상점', subject='다른 제보'))
        with self.site.conn() as db:
            other = db.execute("SELECT id,company_id FROM cases WHERE subject='다른 제보'").fetchone()
        self.assertTrue(other['company_id'])  # 이름만 적어도 접수 때 바로 새 기업으로 등록·연결 (2026-10-29)
        self.post_form(admin, '/admin/reports/%d' % other['id'], {'form': 'company_new', 'name': '새로운상점'})
        with self.site.conn() as db:
            new = db.execute("SELECT c.company_id,co.status FROM cases c JOIN companies co ON co.id=c.company_id WHERE c.id=?", (other['id'],)).fetchone()
        self.assertEqual(new['status'], 'listed')
        # 중지한 기업 페이지는 안 보임
        self.post_form(admin, '/admin/companies', {'id': co['id'], 'action': 'stop'})
        self.assertEqual(self.client.get('/companies/%d' % co['id']).status_code, 404)
        self.post_form(admin, '/admin/companies', {'id': co['id'], 'action': 'start'})
        with self.site.conn() as db:
            self.assertEqual(db.execute('SELECT status FROM companies WHERE id=?', (co['id'],)).fetchone()['status'], 'listed')


    def test_company_verify_answers_and_outcome(self):
        # 2차: 기업 담당자 이메일 인증 + 운영자 승인, 미리 등록된 기업 페이지 합치기, 공식 입장, 답변 수정 이력, 이메일 답변, 소비자 확인
        self.site.BIZ_ON = True
        self.addCleanup(setattr, self.site, 'BIZ_ON', False)
        notify = self.site.notify
        notify.ASYNC = False
        self.addCleanup(setattr, notify, 'ASYNC', True)
        admin = self.login_admin()
        self.post_form(admin, '/admin/companies', {'action': 'create', 'name': '고양이상회'})
        base = {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '고양이상회', 'subject': '고양이상회 환불 제보', 'description': '환불이 안 돼요',
                'reporter_name': '이소비', 'phone': '010-3131-2020', 'request_text': '환불', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234',
                'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'public'}
        self.post_form(self.client, '/report', base)
        with self.site.conn() as db:
            listed = db.execute("SELECT * FROM companies WHERE name='고양이상회'").fetchone()
            case = db.execute("SELECT * FROM cases WHERE subject='고양이상회 환불 제보'").fetchone()
        self.assertEqual(case['company_id'], listed['id'])
        path = '/admin/reports/%d' % case['id']
        self.post_form(admin, path, {'form': 'publish_review', 'decision': 'approve'})
        # 1) 가입 신청: 담당자 이메일로 인증 링크가 감 (메일 설정이 있을 때)
        mails = []
        biz = self.site.app.test_client()
        form = {'company_name': '고양이상회', 'biz_no': '123-45-67891', 'contact_name': '김담당', 'contact_phone': '02-123-4567',
                'contact_email': 'cs@cat.co.kr', 'login_id': 'catshop', 'password': 'abcd1234', 'password2': 'abcd1234', 'agree': 'on'}
        with patch.dict(os.environ, {'SMTP_HOST': 'smtp.example.com', 'SMTP_USER': 'bot@example.com', 'SMTP_PASSWORD': 'pw'}), \
             patch.object(notify, 'send_email', side_effect=lambda *a, **k: mails.append(a + (k.get("html"),))):
            self.post_form(biz, '/biz/signup', form)
        verify = [m for m in mails if m[0] == 'cs@cat.co.kr']
        self.assertEqual(len(verify), 1)
        link = re.search(r'http://localhost(/biz/verify/\S+)', verify[0][2])[1]
        with self.site.conn() as db:
            pending = db.execute("SELECT * FROM companies WHERE status='pending'").fetchone()
        self.assertEqual(int(pending['claim_id']), listed['id'])
        home = biz.get('/biz').get_data(as_text=True)
        self.assertIn('담당자 이메일 확인', home)
        self.assertIn('인증 메일 다시 받기', home)
        # 사업자번호가 맞아도, 이메일 확인 전에는 일반 승인이 안 됨
        companies = admin.get('/admin/companies').get_data(as_text=True)
        self.assertIn('기업 페이지에 합쳐서 승인해요', companies)
        self.assertIn('직접 확인 후 승인', companies)
        self.post_form(admin, '/admin/companies', {'id': pending['id'], 'action': 'approve'})
        with self.site.conn() as db:
            self.assertEqual(db.execute('SELECT status FROM companies WHERE id=?', (pending['id'],)).fetchone()['status'], 'pending')
        self.assertEqual(biz.get(link).status_code, 302)
        self.assertEqual(biz.get(link).status_code, 302)  # 두 번째는 '이미 쓴 링크'
        with self.site.conn() as db:
            self.assertTrue(db.execute('SELECT email_verified_at FROM companies WHERE id=?', (pending['id'],)).fetchone()['email_verified_at'])
        # 2) 승인하면 미리 등록된 기업 페이지에 합쳐짐 (제보는 그대로, 신청서 줄은 사라짐)
        self.post_form(admin, '/admin/companies', {'id': pending['id'], 'action': 'approve'})
        with self.site.conn() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM companies WHERE id=?', (pending['id'],)).fetchone())
            merged = db.execute('SELECT * FROM companies WHERE id=?', (listed['id'],)).fetchone()
            self.assertEqual((merged['status'], merged['biz_no']), ('active', '1234567891'))
            self.assertEqual(db.execute('SELECT company_id FROM company_users WHERE login_id=?', ('catshop',)).fetchone()['company_id'], listed['id'])
        self.post_form(biz, '/biz/login', {'login_id': 'catshop', 'password': 'abcd1234'})
        self.assertNotIn('고양이상회 환불 제보', biz.get('/biz').get_data(as_text=True))  # 운영자가 보내기 전에는 안 보임
        alerts = []
        with patch.dict(os.environ, {'SMTP_HOST': 'smtp.example.com', 'SMTP_USER': 'bot@example.com', 'SMTP_PASSWORD': 'pw'}), \
             patch.object(notify, 'send_email', side_effect=lambda *a: alerts.append(a)):
            self.post_form(admin, path, {'form': 'forward'})
        self.assertEqual([(m[0], m[1]) for m in alerts], [('cs@cat.co.kr', '[소보루] 새 제보가 전달됐습니다')])
        self.assertIn('/company/optout/', alerts[0][2])
        self.assertIn('고양이상회 환불 제보', biz.get('/biz').get_data(as_text=True))
        # 3) 공식 입장: 센터 확인 전에는 공개되지 않고, 확인하면 원문 그대로 공개
        self.post_form(biz, '/biz/statement', {'statement': '고객센터 1588-0000에서 환불을 도와드려요.'})
        self.assertNotIn('1588-0000', self.client.get('/companies/%d' % listed['id']).get_data(as_text=True))
        self.post_form(admin, '/admin/companies', {'id': listed['id'], 'action': 'statement_ok'})
        self.assertIn('고객센터 1588-0000에서 환불을 도와드려요.', self.client.get('/companies/%d' % listed['id']).get_data(as_text=True))
        # 4) 답변 → 센터 공개 → 기업이 고치면 이전 글은 이력에 남고 공개는 내려감
        self.post_form(biz, '/biz/case/%d' % case['id'], {'response': '첫 답변입니다.'})
        with self.site.conn() as db:
            mid = db.execute("SELECT id FROM messages WHERE case_id=? AND author='기업 답변'", (case['id'],)).fetchone()['id']
        self.post_form(admin, path, {'form': 'answer_public', 'message_id': mid, 'public': '1'})
        self.assertIn('첫 답변입니다.', self.client.get('/reports/%d' % case['id']).get_data(as_text=True))
        biz.post('/biz/answer/%d/edit' % mid, data={'_csrf': self.csrf(biz, '/biz/case/%d' % case['id']), 'response': '고친 답변입니다.'})
        with self.site.conn() as db:
            msg = db.execute('SELECT * FROM messages WHERE id=?', (mid,)).fetchone()
            rev = db.execute('SELECT * FROM answer_revisions WHERE message_id=?', (mid,)).fetchall()
        self.assertEqual((msg['body'], msg['public'], bool(msg['edited'])), ('고친 답변입니다.', 0, True))
        self.assertEqual([(r['body'], r['was_public']) for r in rev], [('첫 답변입니다.', 1)])
        public = self.client.get('/reports/%d' % case['id']).get_data(as_text=True)
        self.assertNotIn('답변입니다.', public)
        self.assertIn('센터가 공개 여부를 확인하고 있어요', public)
        self.assertIn('수정 이력 1건', admin.get(path).get_data(as_text=True))
        self.assertIn('수정 이력 1건', biz.get('/biz/case/%d' % case['id']).get_data(as_text=True))
        self.post_form(admin, path, {'form': 'answer_public', 'message_id': mid, 'public': '1'})
        public = self.client.get('/reports/%d' % case['id']).get_data(as_text=True)
        self.assertIn('고친 답변입니다.', public)
        self.assertIn('수정됨', public)
        # 5) 제보자: 처리 결과 확인과 공개 희망 추가 의견
        reporter = self.site.app.test_client()
        self.post_form(reporter, '/lookup', {'mode': 'phone', 'phone': '010-3131-2020', 'password': '1234'})
        page = reporter.get('/case').get_data(as_text=True)
        self.assertIn('기업 답변을 받고 해결됐나요?', page)
        self.assertIn('공개 제보 아래에 함께 보여 주세요', page)
        reporter.post('/case/outcome', data={'_csrf': self.csrf(reporter, '/case'), 'outcome': 'resolved', 'rating': '4'})
        self.post_form(reporter, '/case', {'message': '환불 받았어요. 010-3131-2020', 'want_public': '1'})
        with self.site.conn() as db:
            row = db.execute('SELECT outcome,confirmed_at,rating FROM cases WHERE id=?', (case['id'],)).fetchone()
            opinion = db.execute("SELECT * FROM messages WHERE case_id=? AND author='제보자'", (case['id'],)).fetchone()
        self.assertEqual(row['outcome'], 'resolved')
        self.assertEqual(row['rating'], 4)
        self.assertTrue(row['confirmed_at'])
        self.assertEqual((opinion['want_public'], opinion['public']), (1, 0))
        self.assertIn('제보자가 해결됐다고 확인했어요', self.client.get('/reports/%d' % case['id']).get_data(as_text=True))
        self.assertIn('해결됐어요', biz.get('/biz/case/%d' % case['id']).get_data(as_text=True))
        self.assertIn('공개 희망', admin.get(path).get_data(as_text=True))
        self.post_form(admin, path, {'form': 'answer_public', 'message_id': opinion['id'], 'public': '1'})
        public = self.client.get('/reports/%d' % case['id']).get_data(as_text=True)
        self.assertIn('환불 받았어요.', public)
        self.assertNotIn('010-3131-2020', public)
        # 6) 가입하지 않은 기업의 이메일 답변: 원문 그대로 등록, 형식이 틀리면 거절
        self.post_form(self.client, '/report', dict(base, company='미가입상점', subject='미가입 상점 제보', phone='010-4141-2020'))
        with self.site.conn() as db:
            other = db.execute("SELECT id FROM cases WHERE subject='미가입 상점 제보'").fetchone()['id']
        opath = '/admin/reports/%d' % other
        self.post_form(admin, opath, {'form': 'email_answer', 'sender': 'nope', 'received': '2026-10-01', 'body': '답변'})
        self.post_form(admin, opath, {'form': 'email_answer', 'sender': 'cs@shop.example', 'received': '2026-10-01', 'body': '메일로 드리는 답변입니다.'})
        with self.site.conn() as db:
            answers = db.execute("SELECT body,source,public FROM messages WHERE case_id=? AND author='기업 답변'", (other,)).fetchall()
            status = db.execute('SELECT status FROM cases WHERE id=?', (other,)).fetchone()['status']
            log = db.execute("SELECT action FROM case_log WHERE case_id=? AND action LIKE '이메일로 받은%'", (other,)).fetchone()['action']
        self.assertEqual([tuple(a) for a in answers], [('메일로 드리는 답변입니다.', 'email', 0)])
        self.assertEqual(status, '기업 답변 도착')
        self.assertIn('cs@shop.example', log)
        reporter2 = self.site.app.test_client()
        self.post_form(reporter2, '/lookup', {'mode': 'phone', 'phone': '010-4141-2020', 'password': '1234'})
        self.assertIn('원문 그대로 옮겼어요', reporter2.get('/case').get_data(as_text=True))

    def test_public_report_without_password(self):
        # 공개 제보는 조회 비밀번호 없이 접수, 비밀글은 꼭 필요. 비밀번호를 넣어도 공개 설정은 그대로
        form = {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '비번없는몰', 'description': '환불이 안 돼요', 'reporter_name': '최소비',
                'phone': '010-8181-2020', 'request_text': '환불', 'consent': 'on', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'lookup_pw': '', 'lookup_pw2': ''}
        page = self.post_form(self.client, '/report', dict(form, subject='비번 없는 공개 제보', visibility='public'))
        self.assertEqual(page.status_code, 200)
        self.assertIn('비밀번호 없이 공개 제보로 접수했어요', page.get_data(as_text=True))
        self.assertEqual(self.post_form(self.client, '/report', dict(form, subject='비번 없는 비밀글', visibility='secret')).status_code, 400)
        self.post_form(self.client, '/report', dict(form, subject='비번 있는 공개 제보', visibility='public', lookup_pw='4321', lookup_pw2='4321'))
        with self.site.conn() as db:
            rows = {r['subject']: r for r in db.execute('SELECT subject,public_consent,pw_hash FROM cases')}
        self.assertNotIn('비번 없는 비밀글', rows)
        self.assertEqual((rows['비번 없는 공개 제보']['public_consent'], rows['비번 없는 공개 제보']['pw_hash']), (1, ''))
        self.assertEqual(rows['비번 있는 공개 제보']['public_consent'], 1)
        self.assertTrue(rows['비번 있는 공개 제보']['pw_hash'])
        # 비밀번호 없는 제보는 빈 비밀번호로도 열리지 않음
        self.assertNotIn('/case', self.post_form(self.client, '/lookup', {'mode': 'phone', 'phone': '010-8181-2020', 'password': ''}).headers.get('Location', ''))
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('비번 없는 공개 제보', home)
        self.assertNotIn('공개 검토 중', home)  # 공개 제보는 접수 즉시 게시
        self.assertIn('href="/reports/1"', home)
        self.assertIn('class="vcs-st vcs-1">접수</span>', self.client.get('/reports').get_data(as_text=True))

    def test_publish_legacy_pending_reports(self):
        # 자동 게시 전에 들어와 승인을 기다리던 공개 제보는 관리자가 한 번에 게시. 게시를 내린 기록이 있으면 그대로
        form = {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '예전몰', 'description': '환불이 안 돼요', 'reporter_name': '최소비',
                'phone': '010-8181-2020', 'request_text': '환불', 'consent': 'on', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'public'}
        for subject in ('예전 대기 제보', '내린 제보'):
            self.post_form(self.client, '/report', dict(form, subject=subject))
        admin = self.login_admin()
        with self.site.conn() as db:
            ids = {r['subject']: r['id'] for r in db.execute('SELECT id,subject FROM cases')}
        self.post_form(admin, '/admin/reports/%d' % ids['내린 제보'], {'form': 'publish_review', 'decision': 'hold'})
        with self.site.conn() as db:
            db.execute('UPDATE cases SET published=0 WHERE id=?', (ids['예전 대기 제보'],))  # 예전 규칙으로 승인 대기
        self.assertIn('승인을 기다리던 공개 제보 1건', admin.get('/admin/reports').get_data(as_text=True))
        admin.post('/admin/reports/publish-pending', data={'_csrf': self.csrf(admin, '/admin/reports')})
        with self.site.conn() as db:
            pub = {r['subject']: r['published'] for r in db.execute('SELECT subject,published FROM cases')}
        self.assertEqual(pub, {'예전 대기 제보': 1, '내린 제보': 0})
        self.assertNotIn('pend-bar', admin.get('/admin/reports').get_data(as_text=True))

    def test_public_three_and_reporter_five_stages(self):
        # 공개 화면은 접수·처리 중·종결 3단계, 제보자 본인 화면은 5단계. 5단계 → 3단계 연결
        jebo = self.site.jebo
        mine = [jebo.my_step({'status': s}) for s in self.site.STATUSES]
        self.assertEqual(mine, [1, 2, 2, 3, 4, 5])
        self.assertEqual([jebo.pub_step(n) for n in range(1, 6)], [1, 2, 2, 2, 3])
        self.assertEqual(jebo.my_step({'status': '접수', 'reviewed_at': 'x', 'forwarded_at': 'x'}), 3)
        self.assertEqual(jebo.my_step({'status': '검토 중'}, has_answer=True), 4)
        self.assertEqual(jebo.my_step({'status': '기업 답변 도착', 'confirmed_at': 'x'}), 5)
        form = {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '단계몰', 'description': '환불이 안 돼요', 'reporter_name': '최소비', 'subject': '단계 확인 제보',
                'phone': '010-8181-3030', 'request_text': '환불', 'consent': 'on', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'secret', 'lookup_pw': '4321', 'lookup_pw2': '4321'}
        done = self.post_form(self.client, '/report', form).get_data(as_text=True)
        self.assertEqual(done.count('class="stepper-label"'), 5)
        self.assertIn('기업 답변·처리', done)
        with self.site.conn() as db:db.execute("UPDATE cases SET status='기업 답변 대기' WHERE subject='단계 확인 제보'")
        reports = self.client.get('/reports').get_data(as_text=True)
        self.assertIn('<span class="vcs-st vcs-2">처리 중</span>', reports)
        self.assertNotIn('기업 답변 대기', reports)
        self.post_form(self.client, '/lookup', {'mode': 'phone', 'phone': '010-8181-3030', 'password': '4321'})
        case = self.client.get('/case').get_data(as_text=True)
        self.assertIn('aria-current="step"><span class="stepper-dot">3</span><span class="stepper-label">기업 전달', case)
        self.assertIn('현재 단계: 기업 전달</b> 기업에 제보를 전했어요', case)
        # 관리자·기자실은 6단계: '3. 추가자료 요청'을 따로 고를 수 있고, 제보자 화면에서는 검토로 보임
        admin = self.login_admin()
        with self.site.conn() as db:cid = db.execute("SELECT id FROM cases WHERE subject='단계 확인 제보'").fetchone()['id']
        page = admin.get('/admin/reports/%d' % cid).get_data(as_text=True)
        self.assertIn('>3. 추가자료 요청</option>', page)
        self.assertIn('>4. 기업 전달</option>', page)
        self.post_form(admin, '/admin/reports/%d' % cid, {'form': 'settings', 'status': '추가 확인', 'assignee': ''})
        with self.site.conn() as db:
            self.assertEqual(db.execute('SELECT status FROM cases WHERE id=?', (cid,)).fetchone()['status'], '추가 확인')
            self.assertTrue(db.execute("SELECT 1 FROM case_log WHERE case_id=? AND action LIKE '%기업 전달 → 추가자료 요청%'", (cid,)).fetchone())
        listing = admin.get('/admin/reports?status=추가 확인').get_data(as_text=True)
        self.assertIn('단계 확인 제보', listing)
        self.assertIn('추가자료 요청 <b>1</b>', listing)
        self.assertNotIn('단계 확인 제보', admin.get('/admin/reports?status=검토 중').get_data(as_text=True))

    def test_ops_auto_forward_on_approval_and_reporter_nudge(self):
        """검토 '정상'으로 승인하면 기업에 자동 전달 + 단계 '기업 답변 대기' 알림, 답이 없으면 제보자가 독촉 (운영자 결정 2026-10-21)"""
        notify = self.site.notify
        notify.ASYNC = False
        self.addCleanup(setattr, notify, 'ASYNC', True)
        mails = []
        env = {'SMTP_HOST': 'smtp.example.com', 'SMTP_USER': 'bot@example.com', 'SMTP_PASSWORD': 'pw', 'ADMIN_ALERT_EMAIL': 'ops@example.com'}
        patcher = patch.dict(os.environ, env); patcher.start(); self.addCleanup(patcher.stop)
        mailer = patch.object(notify, 'send_email', side_effect=lambda *a, **k: mails.append(a)); mailer.start(); self.addCleanup(mailer.stop)
        admin = self.login_admin()
        self.post_form(admin, '/admin/companies', {'action': 'create', 'name': '독촉상점', 'official_email': 'cs@nudge-shop.example'})
        base = {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '독촉상점', 'description': '환불이 2주째 안 돼요',
                'reporter_name': '김소비', 'phone': '010-7777-1212', 'contact': 'nudge@example.com', 'request_text': '환불', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234',
                'use_consent': 'on', 'truth': 'on', 'visibility': 'public'}
        self.post_form(self.client, '/report', dict(base, subject='독촉상점 환불 지연', share_company='on'))
        self.post_form(self.client, '/report', dict(base, subject='독촉상점 전달 안 함', phone='010-7777-3434', share_company='on'))
        with self.site.conn() as db:
            first, second = [r['id'] for r in db.execute("SELECT id FROM cases WHERE company='독촉상점' ORDER BY id")]
            db.execute('UPDATE cases SET share_company=0 WHERE id=?', (second,))  # 기업 전달 동의 없음
        mails.clear()
        self.post_form(admin, '/admin/reports/%d' % first, {'form': 'review', 'review': 'ok'})
        sent = [m for m in mails if m[0] == 'cs@nudge-shop.example']
        self.assertEqual(len(sent), 1); self.assertIn('/company/%d/' % first, sent[0][2])
        self.assertTrue(any(m[0] == 'nudge@example.com' and '진행' in m[1] for m in mails))  # 제보자에게 단계 알림
        with self.site.conn() as db:
            row = db.execute('SELECT status,forwarded_at FROM cases WHERE id=?', (first,)).fetchone()
            self.assertEqual(row['status'], '기업 답변 대기'); self.assertTrue(row['forwarded_at'])
        mails.clear()
        self.post_form(admin, '/admin/reports/%d' % second, {'form': 'review', 'review': 'ok'})
        self.assertFalse([m for m in mails if m[0] == 'cs@nudge-shop.example'])  # 동의 없으면 보내지 않음
        # 제보자: 전달 뒤 3일 전에는 못 누름
        reporter = self.site.app.test_client()
        self.post_form(reporter, '/lookup', {'mode': 'phone', 'phone': '010-7777-1212', 'password': '1234'})
        reporter.post('/lookup/%d' % first, data={'_csrf': self.csrf(reporter, '/lookup')})
        page = reporter.get('/case').get_data(as_text=True)
        self.assertIn('기업 답변이 늦어지고 있나요?', page); self.assertIn('3일이 지나면', page); self.assertNotIn('기업에 답변 독촉하기', page)
        old = (datetime.datetime.now() - datetime.timedelta(days=4)).isoformat(timespec='seconds')
        with self.site.conn() as db:
            db.execute('UPDATE cases SET forwarded_at=? WHERE id=?', (old, first)); db.execute('UPDATE company_notices SET created=? WHERE case_id=?', (old, first))
        self.assertIn('기업에 답변 독촉하기', reporter.get('/case').get_data(as_text=True))
        mails.clear()
        reporter.post('/case/nudge', data={'_csrf': self.csrf(reporter, '/case')})
        sent = [m for m in mails if m[0] == 'cs@nudge-shop.example']
        self.assertEqual(len(sent), 1); self.assertIn('답변을 기다리고', sent[0][2])
        page = reporter.get('/case').get_data(as_text=True)
        self.assertIn('1번 독촉했어요', page); self.assertNotIn('기업에 답변 독촉하기', page)  # 바로 다시는 못 누름
        mails.clear()
        reporter.post('/case/nudge', data={'_csrf': self.csrf(reporter, '/case')})
        self.assertFalse([m for m in mails if m[0] == 'cs@nudge-shop.example'])

    def test_auto_forward_finds_company_email(self):
        """등록 안 된 기업도 승인하면 이름으로 연결하고, 공정위 통신판매 신고 정보에서 메일을 찾아 자동으로 보냄 (운영자 요청 2026-10-29)"""
        import company_mail, tempfile
        notify = self.site.notify
        notify.ASYNC = False
        self.addCleanup(setattr, notify, 'ASYNC', True)
        tmp = tempfile.mkdtemp(); mails = []
        env = {'SMTP_HOST': 'smtp.example.com', 'SMTP_USER': 'bot@example.com', 'SMTP_PASSWORD': 'pw', 'SELLER_DIR_PATH': os.path.join(tmp, 'dir.sqlite3'),
               'FTC_API_KEY': '', 'DATA_GO_KR_KEY': '', 'NTS_API_KEY': ''}
        patcher = patch.dict(os.environ, env); patcher.start(); self.addCleanup(patcher.stop)
        mailer = patch.object(notify, 'send_email', side_effect=lambda *a, **k: mails.append(a)); mailer.start(); self.addCleanup(mailer.stop)
        csv_path = os.path.join(tmp, 'seoul.csv')
        with open(csv_path, 'w', encoding='cp949') as f:
            f.write('통신판매번호,상호,사업자등록번호,법인여부,전자우편,업소상태\n'
                    '1,(주)유명마켓,1234567890,법인,help@famous-market.example,통신판매업 신고\n'
                    '2,유명마켓,9999999999,개인,old@famous-market.example,폐업\n'
                    '3,동명상회,1111111111,개인,a@same.example,통신판매업 신고\n4,동명상회,2222222222,개인,b@same.example,통신판매업 신고\n')
        self.assertEqual(company_mail.import_csv([csv_path]), 3)  # 폐업은 뺌
        self.assertEqual(company_mail.find(['유명마켓'])[0], 'help@famous-market.example')
        self.assertEqual(company_mail.find(['동명상회'])[0], '')  # 같은 이름이 여럿이면 고르지 않음
        admin = self.login_admin()
        base = {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '유명마켓', 'subject': '유명마켓 환불 지연', 'description': '환불이 안 돼요',
                'reporter_name': '오소비', 'phone': '010-8888-1212', 'contact': 'famous@example.com', 'request_text': '환불', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234',
                'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'public'}
        self.post_form(self.client, '/report', base)
        with self.site.conn() as db: cid = db.execute("SELECT id FROM cases WHERE company='유명마켓'").fetchone()['id']
        mails.clear()
        self.post_form(admin, '/admin/reports/%d' % cid, {'form': 'review', 'review': 'ok'})
        self.assertTrue([m for m in mails if m[0] == 'help@famous-market.example'])
        with self.site.conn() as db:
            co = db.execute('SELECT co.* FROM companies co JOIN cases c ON c.company_id=co.id WHERE c.id=?', (cid,)).fetchone()
            self.assertEqual(co['official_email'], 'help@famous-market.example'); self.assertTrue(co['email_source'])
        self.assertIn('자동으로 찾았어요', admin.get('/admin/companies').get_data(as_text=True))
        # 큰 기업 미리 등록: 다른 이름으로도 연결되고, 두 번 넣어도 겹치지 않음
        added, _ = company_mail.seed(lookup=False)
        self.assertGreater(added, 40); self.assertEqual(company_mail.seed(lookup=False)[0], 0)
        with self.site.conn() as db:
            self.assertEqual(self.site.pick_company(db, None, '배민')['name'], '배달의민족')
            self.assertEqual(db.execute("SELECT COUNT(*) FROM companies WHERE name='쿠팡'").fetchone()[0], 1)
        # 등록현황 전체 받기(sync) 뒤 사이트 기업 전부 채우기(fill) (운영자 요청 2026-10-30)
        import io, json as _json
        pages = {1: [{'bzmnNm': '주식회사 무신사', 'brno': '2118800000', 'emlAddr': 'cs@musinsa.example', 'operSttusCdNm': '통신판매업 신고'},
                     {'bzmnNm': '닫은가게', 'brno': '3333333333', 'emlAddr': 'x@closed.example', 'operSttusCdNm': '폐업'}],
                 2: [{'bzmnNm': '메일없는곳', 'brno': '4444444444'}]}
        def fake_open(url, timeout=0):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)); n = int(q['pageNo'])
            body = {'response': {'body': {'totalCount': 3, 'items': {'item': pages.get(n, [])}}}}
            return io.BytesIO(_json.dumps(body).encode())
        with patch.dict(os.environ, {'FTC_API_KEY': 'k'}), patch.object(company_mail.urllib.request, 'urlopen', side_effect=fake_open):
            added, done = company_mail.sync(rows=2, say=lambda *a: None)
        self.assertEqual((added, done), (1, True))
        with patch.dict(os.environ, {'FTC_API_KEY': ''}):
            seen, filled = company_mail.fill()
        self.assertGreater(seen, 1); self.assertGreaterEqual(filled, 1)
        with self.site.conn() as db:
            self.assertEqual(db.execute("SELECT official_email FROM companies WHERE name='무신사'").fetchone()[0], 'cs@musinsa.example')

    def test_cases_link_companies_and_logos(self):
        """제보는 들어오면 기업에 자동으로 묶이고(없으면 등록), 예전 제보도 정리되며, 홈 '제보가 많은 기업'에 바로 셈 (운영자 요청 2026-10-29)"""
        import company_logo, io
        from PIL import Image
        base = {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '처음보는상점', 'subject': '처음보는상점 환불', 'description': '환불이 안 돼요',
                'reporter_name': '오소비', 'phone': '010-8181-1212', 'request_text': '환불', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234',
                'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'public'}
        self.post_form(self.client, '/report', base)
        with self.site.conn() as db:
            row = db.execute("SELECT c.company_id, co.name, co.status FROM cases c JOIN companies co ON co.id=c.company_id WHERE c.company='처음보는상점'").fetchone()
            self.assertEqual((row['name'], row['status']), ('처음보는상점', 'listed'))
            db.execute("UPDATE cases SET company_id=NULL WHERE company='처음보는상점'")
            db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created) VALUES('OLD-1','x','배송','(주)처음보는상점','옛 제보','내용','요청',?)", (datetime.datetime.now().isoformat(timespec='seconds'),))
        self.site.link_all_cases()
        with self.site.conn() as db:
            ids = {r[0] for r in db.execute("SELECT company_id FROM cases WHERE company LIKE '%처음보는상점'")}
            self.assertEqual(len(ids), 1); self.assertNotIn(None, ids)  # (주)를 붙여 써도 같은 기업
        with self.site.app.test_request_context('/'):
            most = self.site.app.jinja_env.globals['company_rank']()['most']
        self.assertEqual(next(p for p in most if p['name'] == '처음보는상점')['n'], 2)
        self.assertIn('제보가 많은 기업', self.site.app.test_client().get('/').get_data(as_text=True))
        # 로고: 도메인 정리, 작은 아이콘은 안 쓰고 큰 것은 128px PNG로
        self.assertEqual(company_logo.clean_domain('https://www.Coupang.com/np/x'), 'coupang.com')
        self.assertEqual(company_logo.clean_domain('localhost'), '')
        def png(n):
            b = io.BytesIO(); Image.new('RGB', (n, n), 'orange').save(b, 'PNG'); return b.getvalue()
        self.assertEqual(company_logo.to_png(png(16)), b'')
        self.assertEqual(Image.open(io.BytesIO(company_logo.to_png(png(512)))).size, (128, 128))

    def test_ops_review_notice_requests_stats(self):
        # 3차: 심사 확인(개인정보 의심·중복 후보), 보완 요청, 추가 자료, 기업 안내 메일(빈도 제한·수신 거부), 정정·삭제·이의 신청, 운영 통계
        notify = self.site.notify
        notify.ASYNC = False
        self.addCleanup(setattr, notify, 'ASYNC', True)
        mails = []
        env = {'SMTP_HOST': 'smtp.example.com', 'SMTP_USER': 'bot@example.com', 'SMTP_PASSWORD': 'pw', 'ADMIN_ALERT_EMAIL': 'ops@example.com'}
        patcher = patch.dict(os.environ, env); patcher.start(); self.addCleanup(patcher.stop)
        mailer = patch.object(notify, 'send_email', side_effect=lambda *a, **k: mails.append(a + (k.get("html"),))); mailer.start(); self.addCleanup(mailer.stop)
        admin = self.login_admin()
        self.post_form(admin, '/admin/companies', {'action': 'create', 'name': '안내상점', 'official_email': 'cs@notice-shop.example'})
        base = {'industry': '쇼핑·유통', 'category': '배송·교환·환불', 'company': '안내상점', 'description': '환불이 안 돼요. 제 번호는 010-5555-6666이에요',
                'reporter_name': '정소비', 'phone': '010-5555-6666', 'contact': 'me@example.com', 'request_text': '환불', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234',
                'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'public'}
        self.post_form(self.client, '/report', dict(base, subject='안내상점 환불 지연'))
        self.post_form(self.client, '/report', dict(base, subject='안내상점 환불 지연', description='두 번째 제보'))
        with self.site.conn() as db:
            first, second = [r['id'] for r in db.execute("SELECT id FROM cases WHERE company='안내상점' ORDER BY id")]
        self.assertTrue(any(m[0] == 'ops@example.com' and '개인정보 노출 의심' in m[1] for m in mails))
        path = '/admin/reports/%d' % first
        page = admin.get(path).get_data(as_text=True)
        self.assertIn('개인정보 의심', page)
        self.assertIn('같은 휴대폰 번호', page)
        # 보완 요청 → 단계 '추가 확인', 제보자 화면 맨 위에 보이고 메일 알림
        mails.clear()
        self.post_form(admin, path, {'form': 'supplement', 'body': '주문 내역 화면을 올려 주세요.'})
        with self.site.conn() as db:
            self.assertEqual(db.execute('SELECT status FROM cases WHERE id=?', (first,)).fetchone()['status'], '추가 확인')
        self.assertTrue(any(m[0] == 'me@example.com' and '보완' in m[1] for m in mails))
        reporter = self.site.app.test_client()
        self.post_form(reporter, '/lookup', {'mode': 'phone', 'phone': '010-5555-6666', 'password': '1234'})
        reporter.post('/lookup/%d' % first, data={'_csrf': self.csrf(reporter, '/lookup')})
        page = reporter.get('/case').get_data(as_text=True)
        self.assertIn('센터가 보완을 요청했어요', page)
        self.assertIn('주문 내역 화면을 올려 주세요.', page)
        self.assertIn('보완 요청', page)  # 받은 알림 목록
        # 추가 자료: 사진만, 공개 안 됨
        png = b'\x89PNG\r\n\x1a\n' + b'0' * 64
        token = self.csrf(reporter, '/case')
        reporter.post('/case/files', data={'_csrf': token, 'evidence': (io.BytesIO(png), 'order.png')}, content_type='multipart/form-data')
        reporter.post('/case/files', data={'_csrf': token, 'evidence': (io.BytesIO(b'MZ' + b'0' * 20), 'bad.exe')}, content_type='multipart/form-data')
        with self.site.conn() as db:
            self.assertEqual([r['original'] for r in db.execute('SELECT original FROM attachments WHERE case_id=?', (first,))], ['order.png'])
        # 정정 요청 → 운영자 처리 → 제보자에게 메시지
        mails.clear()
        reporter.post('/case/request', data={'_csrf': token, 'kind': 'correct', 'body': '날짜를 10월 1일로 고쳐 주세요.'})
        reporter.post('/case/request', data={'_csrf': token, 'kind': 'delete', 'body': '두 번째 요청'})  # 처리 중이면 거절
        self.assertTrue(any(m[0] == 'ops@example.com' and '정정 요청' in m[1] for m in mails))
        self.assertIn('날짜를 10월 1일로', admin.get('/admin/requests').get_data(as_text=True))
        with self.site.conn() as db:
            reqs = db.execute('SELECT * FROM case_requests WHERE case_id=?', (first,)).fetchall()
        self.assertEqual(len(reqs), 1)
        self.post_form(admin, '/admin/requests', {'request_id': reqs[0]['id'], 'decision': 'done', 'result': '공개 글의 날짜를 고쳤어요.'})
        self.assertIn('[정정 요청 처리 완료] 공개 글의 날짜를 고쳤어요.', reporter.get('/case').get_data(as_text=True))
        # 기업 안내 메일: 운영자가 누를 때만, 보내도 '전달 확인'은 아님, 72시간 안 재발송 막힘
        mails.clear()
        self.post_form(admin, path, {'form': 'notice'})
        sent = [m for m in mails if m[0] == 'cs@notice-shop.example']
        self.assertEqual(len(sent), 1)
        self.assertIn('민간 플랫폼', sent[0][2])
        self.assertIn('제보 확인하고 답변하기', sent[0][3]); self.assertIn('/company/optout/', sent[0][3])  # 꾸민 HTML 메일도 함께
        link = re.search(r'http://localhost(/company/\d+/\S+)', sent[0][2])[1]
        optout = re.search(r'http://localhost(/company/optout/\S+)', sent[0][2])[1]
        with self.site.conn() as db:
            row = db.execute('SELECT forwarded_at,seen_at FROM cases WHERE id=?', (first,)).fetchone()
            self.assertTrue(row['forwarded_at']); self.assertEqual(row['seen_at'], '')
        self.post_form(admin, path, {'form': 'notice'})
        self.assertEqual(len([m for m in mails if m[0] == 'cs@notice-shop.example']), 1)
        self.assertIn('72시간', admin.get(path).get_data(as_text=True))
        # 기업이 링크를 열면 '전달 확인' + 제보자 알림, 이의 신청
        mails.clear()
        company = self.site.app.test_client()
        self.assertEqual(company.get(link).status_code, 200)
        self.assertTrue(any(m[0] == 'me@example.com' and '확인했습니다' in m[1] for m in mails))
        company.post(link, data={'_csrf': self.csrf(company, link), 'form': 'objection', 'body': '이미 환불을 끝냈습니다. 영수증 있습니다.'})
        page = company.get(link).get_data(as_text=True)
        self.assertNotIn('name="form" value="objection"', page)  # 답변 화면에는 이의 신청 칸 없음 (OH 2026-10-29). 예전 요청은 그대로 받음
        self.assertIn('sb-header-min', page)
        with self.site.conn() as db:
            self.assertEqual(db.execute("SELECT kind FROM case_requests WHERE who='company' AND case_id=?", (first,)).fetchone()['kind'], 'objection')
        # 수신 거부하면 다른 제보로도 안내 메일을 못 보냄
        self.post_form(company, optout, {})
        self.assertIn('보내지 않아요', company.get(optout).get_data(as_text=True))
        mails.clear()
        self.post_form(admin, '/admin/reports/%d' % second, {'form': 'notice'})
        self.assertEqual(mails, [])
        self.assertIn('수신을 거부', admin.get('/admin/reports/%d' % second).get_data(as_text=True))
        # 운영 통계와 홈
        stats = admin.get('/admin/stats?period=30').get_data(as_text=True)
        self.assertIn('<b>2</b><small>기간 안 접수', stats)
        self.assertIn('기업 확인률', stats)
        home = admin.get('/admin').get_data(as_text=True)
        self.assertIn('정정·삭제·이의 신청', home)
        with self.site.conn() as db:
            db.execute("UPDATE cases SET created='2026-01-01T00:00:00' WHERE id=?", (second,))
            db.execute("UPDATE case_log SET created='2026-01-01T00:00:00' WHERE case_id=?", (second,))
            db.execute("UPDATE messages SET created='2026-01-01T00:00:00' WHERE case_id=?", (second,))
        self.assertIn('처리 지연 제보', admin.get('/admin').get_data(as_text=True))
        # 제보를 지우면 안내·요청 기록도 함께 지워짐
        self.post_form(admin, path, {'form': 'delete', 'confirm': '1'})
        with self.site.conn() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM case_requests WHERE case_id=?', (first,)).fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM company_notices WHERE case_id=?', (first,)).fetchone()[0], 0)

    # ---- 소비자 법률 질문창(/ask)과 법령 학습(/admin/laws) ----
    LAW_PDF_LINES = [['법제처 1 국가법령정보센터', '할부거래에 관한 법률', '[시행 2026. 1. 2.] [법률 제12345호, 2025. 7. 1., 일부개정]',
                      '제1조(목적) 이 법은 할부계약에 의한 거래를 공정하게 함을 목적으로 한다.',
                      '제2조(할부계약의 청약철회) ① 소비자는 할부계약서를 받은 날부터 7일 이내에 할부계약에 관한 청약을 철회할 수 있다.'],
                     ['법제처 2 국가법령정보센터', '할부거래에 관한 법률', '② 할부거래업자는 청약철회를 이유로 소비자에게 위약금을 청구할 수 없다.',
                      '부칙 <제12345호,2025. 7. 1.>', '제1조(시행일) 이 법은 공포한 날부터 시행한다.']]

    @staticmethod
    def make_pdf(pages):
        """글꼴 파일 없이 pdftotext가 읽을 수 있는 작은 PDF (유니코드 번호를 그대로 글자 번호로 쓰고 ToUnicode로 되돌림)."""
        objs = []
        def add(b): objs.append(b); return len(objs)
        rs = [f'<{h:02X}00> <{h:02X}FF> <{h:02X}00>' for h in range(256)]
        blocks = '\n'.join(f'{len(rs[i:i + 100])} beginbfrange\n' + '\n'.join(rs[i:i + 100]) + '\nendbfrange' for i in range(0, 256, 100))
        cmap = ('/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def '
                '/CMapName /Adobe-Identity-UCS def /CMapType 2 def 1 begincodespacerange <0000> <FFFF> endcodespacerange\n' + blocks +
                '\nendcmap CMapName currentdict /CMap defineresource pop end end').encode()
        tu = add(b'<< /Length %d >>\nstream\n' % len(cmap) + cmap + b'\nendstream')
        desc = add(b'<< /Type /FontDescriptor /FontName /T /Flags 4 /FontBBox [0 0 1000 1000] /ItalicAngle 0 /Ascent 880 /Descent -120 /CapHeight 700 /StemV 80 >>')
        cid = add(b'<< /Type /Font /Subtype /CIDFontType2 /BaseFont /T /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /FontDescriptor %d 0 R /DW 1000 /W [32 [250] 33 126 500] >>' % desc)
        font = add(b'<< /Type /Font /Subtype /Type0 /BaseFont /T /Encoding /Identity-H /DescendantFonts [%d 0 R] /ToUnicode %d 0 R >>' % (cid, tu))
        pages_id = len(objs) + 1 + 2 * len(pages); kids = []
        for lines in pages:
            # 한 줄은 글 하나(왼쪽 30) 또는 [(x, 글), …] (표처럼 칸을 나눠 놓을 때)
            s = '\n'.join('BT /F1 9 Tf %d %d Td <%s> Tj ET' % (x, 800 - i * 14, ''.join(f'{ord(ch):04X}' for ch in w))
                          for i, l in enumerate(lines) for x, w in ([(30, l)] if isinstance(l, str) else l)).encode()
            c = add(b'<< /Length %d >>\nstream\n' % len(s) + s + b'\nendstream')
            kids.append(add(b'<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>' % (pages_id, font, c)))
        add(b'<< /Type /Pages /Kids [%s] /Count %d >>' % (b' '.join(b'%d 0 R' % k for k in kids), len(kids)))
        cat = add(b'<< /Type /Catalog /Pages %d 0 R >>' % pages_id)
        out = bytearray(b'%PDF-1.4\n'); offs = []
        for i, o in enumerate(objs, 1): offs.append(len(out)); out += b'%d 0 obj\n' % i + o + b'\nendobj\n'
        x = len(out)
        out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1) + b''.join(b'%010d 00000 n \n' % o for o in offs)
        out += b'trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, cat, x)
        return bytes(out)

    def ask_setup(self):
        with self.site.conn() as db:
            db.execute('DELETE FROM law_questions')
        self.addCleanup(self.ask_cleanup)

    def ask_cleanup(self):
        with self.site.conn() as db:
            db.execute('DELETE FROM law_questions'); db.execute("DELETE FROM site_content WHERE key='ask.off'")
        extra = self.site.app.extensions['lawask']['extra_path']
        if extra.exists(): extra.unlink()
        self.site.triage.corpus.reset()

    def ask(self, client, q, **extra):
        return client.post('/ask', data={'_csrf': self.csrf(client, '/ask'), 'q': q, **extra})

    def test_law_ask_answer_cites_only_candidates(self):
        self.ask_setup()
        page = self.client.get('/ask').get_data(as_text=True)
        self.assertIn('소비자 법률, 편하게 물어보세요', page)
        self.assertIn('href="/ask"', page)  # 머리글 메뉴 '법률 질문'
        self.assertIn('온라인에서 산 옷, 7일 지나서도 환불되나요?', page)  # 예시 질문
        sent = []
        def fake(url, headers, body, timeout):
            sent.append((url, headers, body))
            out = {'headline': '받은 날부터 7일이 지났다면 단순 변심 환불은 어려울 수 있어요',
                   'paragraphs': ['전자상거래법 제17조에 따르면 상품을 받은 날부터 7일 안에 청약철회를 할 수 있어요. 문의 010-1234-5678', '광고와 다르면 더 길게 돼요.'],
                   'refs': ['corpus:ecom:제17조', 'ecom:제99조', 'civil:제1조'], 'covered': True, 'suggest_report': True}
            return 200, {'model': 'gpt-test', 'choices': [{'message': {'content': json.dumps(out, ensure_ascii=False)}}]}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(self.site.companydesk, 'post_json', fake):
            r = self.ask(self.client, '온라인에서 산 옷 7일 지나서 환불 되나요? 제 번호는 010-9876-5432예요')
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        (url, headers, body), = sent
        self.assertTrue(url.endswith('/chat/completions')); self.assertNotIn('tools', body)  # 검색 없이
        user = body['messages'][1]['content']
        self.assertNotIn('010-9876-5432', user); self.assertIn('[조문 후보]', user); self.assertIn('[corpus:ecom:제17조]', user)
        self.assertIn('조문 후보', body['messages'][0]['content']); self.assertNotIn('sk-test-key', json.dumps(body, ensure_ascii=False))
        self.assertIn('받은 날부터 7일이 지났다면', html)
        self.assertNotIn('010-1234-5678', html)  # 답에 섞인 개인정보도 지움
        cards = re.findall(r'<span class="sba-law">([^<]+)</span><span class="sba-art"><b>([^<]+)</b>', html)
        self.assertEqual(cards, [('전자상거래법', '제17조')])  # 후보에 없던 제99조·민법 제1조는 버림
        self.assertIn('https://www.law.go.kr/법령/', html); self.assertIn('법률 자문이 아니고', html)
        self.assertIn('href="/report"', html); self.assertIn('1372 소비자상담센터', html)
        # AI가 실패하면 찾은 조문 카드만 (키는 화면에 안 나옴)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(self.site.companydesk, 'post_json', lambda *a: (500, {'error': {'message': 'bad sk-test-key'}})):
            html = self.ask(self.client, '받은 지 5일 됐는데 단순 변심으로 환불 되나요?').get_data(as_text=True)
        self.assertIn('질문과 가장 가까운 조문을 찾았어요', html); self.assertNotIn('sk-test-key', html)
        with self.site.conn() as db:  # 질문 글은 저장하지 않음
            row = db.execute('SELECT * FROM law_questions').fetchone()
            self.assertEqual(set(row.keys()), {'id', 'ip_hash', 'created'})

    def test_law_ask_fallback_limit_and_off(self):
        self.ask_setup()
        env = {k: v for k, v in os.environ.items() if k != 'OPENAI_API_KEY'}
        with patch.dict(os.environ, env, clear=True):
            html = self.ask(self.client, '받은 지 5일 됐는데 단순 변심으로 환불 되나요?').get_data(as_text=True)
            self.assertIn('질문과 가장 가까운 조문을 찾았어요', html)
            self.assertIn('<b>제17조</b>', html)
            self.assertIn('배운 법령에서 딱 맞는 조문을 찾지 못했어요', self.ask(self.client, '사이즈 추천해 주세요 감사합니다').get_data(as_text=True))
            self.assertIn('조금 더 자세히', self.ask(self.client, '환불').get_data(as_text=True))  # 너무 짧음 (기록 안 함)
            self.assertIn('줄여 주세요', self.ask(self.client, '환불 ' * 200).get_data(as_text=True))
            self.assertEqual(self.ask(self.client, '환불 되나요 문의해요', website='http://spam').status_code, 400)
            for _ in range(8): self.ask(self.client, '받은 지 5일 됐는데 단순 변심으로 환불 되나요?')
            html = self.ask(self.client, '받은 지 5일 됐는데 단순 변심으로 환불 되나요?').get_data(as_text=True)
        self.assertIn('1시간 뒤에 다시', html); self.assertNotIn('가장 가까운 조문', html)
        with self.site.conn() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM law_questions').fetchone()[0], 10)
            db.execute("INSERT OR REPLACE INTO site_content(key,value,updated) VALUES('ask.off','끔','x')")
        self.assertEqual(self.client.get('/ask').status_code, 404)
        self.assertNotIn('href="/ask"', self.client.get('/').get_data(as_text=True))

    def test_law_text_parse_unknown_law(self):
        lawask = self.site.lawask
        text = '\n'.join(sum(self.LAW_PDF_LINES, []))
        (law,) = lawask.parse_text(text)
        self.assertEqual((law['name'], law['short'], law['kind'], law['effective']), ('할부거래에 관한 법률', '할부거래법', '법률', '2026-01-02'))
        self.assertRegex(law['key'], r'^u[0-9a-f]{8}$')
        self.assertEqual(list(law['articles']), ['제1조', '제2조'])  # 부칙 제1조는 빼고
        self.assertEqual(law['articles']['제2조']['text'], '① 소비자는 할부계약서를 받은 날부터 7일 이내에 할부계약에 관한 청약을 철회할 수 있다.\n② 할부거래업자는 청약철회를 이유로 소비자에게 위약금을 청구할 수 없다.')
        # 머리글 없이 이름 줄부터 시작해도 읽음, 아는 법령은 원래 key
        (law,) = lawask.parse_text('전자상거래 등에서의 소비자보호에 관한 법률\n[시행 2026. 7. 21.] [법률 제21312호, 2026. 1. 20., 일부개정]\n제1조(목적) 이 법은 소비자를 보호한다.\n')
        self.assertEqual((law['key'], law['short']), ('ecom', '전자상거래법'))
        with self.assertRaises(ValueError): lawask.parse_text('그냥 글입니다\n아무 법령도 아님')

    @unittest.skipUnless(__import__('shutil').which('pdftotext'), 'pdftotext 없음')
    def test_admin_law_pdf_upload_becomes_searchable(self):
        self.ask_setup()
        corpus = self.site.triage.corpus
        admin = self.login_admin()
        page = admin.get('/admin/laws').get_data(as_text=True)
        self.assertIn('법령 학습', page); self.assertIn('기본 모음', page); self.assertIn('전자상거래법', page)
        tok = self.csrf(admin, '/admin/laws')
        # PDF가 아니면 거절
        r = admin.post('/admin/laws', data={'_csrf': tok, 'act': 'preview', 'pdf': (io.BytesIO(b'hello'), 'law.txt')}, content_type='multipart/form-data')
        self.assertIn('PDF 파일만', r.get_data(as_text=True))
        r = admin.post('/admin/laws', data={'_csrf': tok, 'act': 'preview', 'pdf': (io.BytesIO(self.make_pdf(self.LAW_PDF_LINES)), '할부거래법.pdf')}, content_type='multipart/form-data')
        html = r.get_data(as_text=True)
        self.assertIn('미리 보기', html); self.assertIn('조문 2개', html); self.assertIn('할부계약의 청약철회', html)
        self.assertNotIn('할부거래법', [l['short'] for l in corpus.laws()])  # 저장 전엔 안 씀
        key = re.search(r'name="short_(u[0-9a-f]{8})" value="할부거래법"', html)[1]
        token = re.search(r'name="token" value="([^"]+)"', html)[1]
        r = admin.post('/admin/laws', data={'_csrf': tok, 'act': 'save', 'token': token, 'short_' + key: '할부거래법'}, follow_redirects=True)
        self.assertIn('법령을 배웠어요', r.get_data(as_text=True))
        self.assertIn('직접 올림', r.get_data(as_text=True))
        self.assertTrue(self.site.app.extensions['lawask']['extra_path'].exists())
        hits = corpus.search('할부계약 청약철회 위약금')
        self.assertEqual(hits[0]['ref'], key + ':제2조'); self.assertEqual(hits[0]['label'], '할부거래법 제2조 (할부계약의 청약철회)')
        self.assertEqual(self.site.triage.cite('corpus:' + key + ':제2조')['label'], '할부거래법 제2조')  # AI 제보 분류도 같은 모음
        env = {k: v for k, v in os.environ.items() if k != 'OPENAI_API_KEY'}
        with patch.dict(os.environ, env, clear=True):
            html = self.ask(self.client, '할부계약 청약철회하면 위약금을 내야 하나요?').get_data(as_text=True)
        self.assertIn('<span class="sba-law">할부거래법</span>', html)
        # 지우면 다시 안 찾음, 기본 모음은 못 지움
        admin.post('/admin/laws', data={'_csrf': tok, 'act': 'delete', 'key': key})
        self.assertNotIn(key, [l['key'] for l in corpus.laws()])
        r = admin.post('/admin/laws', data={'_csrf': tok, 'act': 'delete', 'key': 'ecom'}, follow_redirects=True)
        self.assertIn('올린 법령만 지울 수 있어요', r.get_data(as_text=True)); self.assertIn('ecom', [l['key'] for l in corpus.laws()])
        self.assertIn('법령 학습', admin.get('/admin').get_data(as_text=True))  # 관리자 메뉴

    # ---- AI 분석 기사 (soboru_writer.py) ------------------------------------------
    def writer_cleanup(self):
        with self.site.conn() as db:
            db.execute("DELETE FROM articles WHERE origin='ai'"); db.execute('DELETE FROM ai_articles')
            db.execute("DELETE FROM soboru_settings WHERE key LIKE 'writer%'"); db.execute('DELETE FROM soboru_art')
            db.execute("DELETE FROM messages WHERE case_id IN (SELECT id FROM cases WHERE receipt LIKE 'AIW-%')")
            db.execute("DELETE FROM cases WHERE receipt LIKE 'AIW-%'"); db.execute("DELETE FROM companies WHERE biz_no='AIW'")
            db.execute('DELETE FROM naver_cache'); db.execute('DELETE FROM naver_usage')

    def writer_ai(self, sent, extra='', pair=None, fix=None):
        """가짜 OpenAI: 받은 자료([자료] JSON)의 숫자만 써서 기사를 돌려줌. extra는 자료에 없는 말을 섞을 때.
        숫자 짝 검사(교열) 부름에는 pair(문제 목록, 없으면 문제 없음)를 돌려줌."""
        def fake(url, headers, body, timeout):
            if 'images' in url: return 500, {'error': {'message': 'no images in test'}}
            if body['messages'][0]['content'].startswith('너는 잡지 편집장'):  # 비슷한 주제 판단: 같은 소재 표시('외식')가 든 글끼리만 같다고 봄
                user = body['messages'][1]['content']; new, recent = user.split('[최근 30일 기사]')
                hit = '외식' in new.split('\n')[1] and '외식' in recent
                return 200, {'model': 'test-model', 'choices': [{'message': {'content': json.dumps({'same': hit, 'title': '외식비 부담' if hit else ''}, ensure_ascii=False)}}]}
            if body['messages'][0]['content'].startswith('너는 잡지 교열'):
                if '[문제]' in body['messages'][0]['content']:  # 재교열: 걸린 문장 고치기
                    self.fix_calls = getattr(self, 'fix_calls', []) + [body]
                    return 200, {'model': 'test-model', 'choices': [{'message': {'content': json.dumps({'fixes': fix or []}, ensure_ascii=False)}}]}
                self.pair_calls = getattr(self, 'pair_calls', []) + [body]
                got = pair(body) if callable(pair) else pair
                return 200, {'model': 'test-model', 'choices': [{'message': {'content': json.dumps({'problems': got or []}, ensure_ascii=False)}}]}
            sent.append(body)
            facts = json.loads(body['messages'][1]['content'].split('[자료]\n', 1)[1])
            nums = [v for v in facts.values() if isinstance(v, int)][:1] or [1372]
            out = {'title': f'요즘 소비자 이야기, 숫자로 보면 {nums[0]} {facts.get("주제", "")} {"가나다라마바사아자차"[len(sent) % 10]}편', 'summary': ['첫 줄 요약이에요.', '둘째 줄이에요.', f'셋째 줄, {facts["소비자상담센터 전화번호"]}도 기억해요.'],
                   'sections': [{'heading': '무슨 일이에요?', 'paragraphs': [f'자료를 보면 {nums[0]}이라는 숫자가 나와요.' + extra, '원인은 더 지켜볼 일이에요.']}],
                   'tips': ['영수증을 챙겨 두세요.', '1372 소비자상담센터에 물어보세요.'], 'category': '생활'}
            return 200, {'model': 'test-model', 'choices': [{'message': {'content': json.dumps(out, ensure_ascii=False)}}]}
        return fake

    def writer_cases(self, n_public=6, n_private=3):
        now = datetime.datetime.now()
        with self.site.conn() as db:
            co = db.execute("INSERT INTO companies(name,biz_no,status,contact_name,contact_phone,contact_email,created) VALUES('공개몰','AIW','active','담당','02','a@b.c',?)", (now.isoformat(),)).lastrowid
            secret = db.execute("INSERT INTO companies(name,biz_no,status,contact_name,contact_phone,contact_email,created) VALUES('비밀상회','AIW','active','담당','02','a@b.c',?)", (now.isoformat(),)).lastrowid
            for i in range(n_public):
                t = (now - datetime.timedelta(days=2, hours=i)).isoformat(timespec='seconds')
                cid = db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,company_id,subject,description,request_text,created,public_consent,published,review,reviewed_at,forwarded_at,status) VALUES(?,?,?,?,?,?,?,?,?,1,1,'ok',?,?,'기업 답변 대기')",
                                 (f'AIW-P{i}', 'x', '배송·교환·환불', '공개몰', co, '환불이 안 돼요', '공개 제보 내용', '환불', t, t, t)).lastrowid
                if i < 4: db.execute("INSERT INTO messages(case_id,author,body,created,public) VALUES(?,?,?,?,1)", (cid, '기업 답변', '처리했어요', (now - datetime.timedelta(days=1)).isoformat(timespec='seconds')))
            for i in range(n_private):  # 비밀글·게시 전 제보: 내용도 숫자도 기사에 들어가면 안 됨
                t = (now - datetime.timedelta(days=1, hours=i)).isoformat(timespec='seconds')
                db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,company_id,subject,description,request_text,created,public_consent,published,review,reviewed_at,forwarded_at,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,'ok',?,?,'기업 답변 대기')",
                           (f'AIW-S{i}', 'x', '개인정보', '비밀상회', secret, '비밀 제보 제목 김철수', '비밀 내용 010-1234-5678', '삭제', t, 0 if i % 2 == 0 else 1, 0, t, t))
        return co, secret

    def test_writer_number_check(self):
        check = self.site.soboru_writer.check_text
        facts = {'증감률(%)': -12, '지수': 53.27, '기간': '2026-09-01 ~ 2026-10-16', '건수': 1234, '금액': 30000, '시행일': '20261101'}
        ok = '검색이 12% 줄었어요. 지수는 53.3, 반올림하면 53이에요.\n2026년 9월 1일부터 10월 16일까지 1,234건이에요. 3만 원이에요. 11월 1일 시행돼요.'
        self.assertEqual(check(ok, facts), [])
        bad = check('검색이 2배로 늘었어요.\n지수는 53이에요.\n작년보다 47% 늘어난 1,500건이에요.\n이 회사는 최악이에요.', facts)
        self.assertEqual([p.get('numbers') for p in bad if 'numbers' in p], [['2배'], ['47%', '1,500건']])
        self.assertIn('2배로', bad[0]['line'])
        # 단위가 붙은 숫자는 자료에도 같은 단위로 있어야 함: 자료에 4(주)·12(%)가 있어도 '4배'·'12건'은 잡음
        self.assertEqual([p['numbers'] for p in check('검색이 4배, 12건이에요.', dict(facts, 기간='최근 4주'))], [['4배', '12건']])
        self.assertEqual([p['words'] for p in bad if 'words' in p], [['최악']])  # 기업 평가로 읽힐 말도
        clean = self.site.soboru_writer.clean_personal
        self.assertEqual(clean(self.site.companydesk.scrub, '2026-07-18 ~ 2026-10-16, 문의 010-1234-5678'), '2026-07-18 ~ 2026-10-16, 문의 [개인정보 삭제]')

    def test_writer_reports_paused(self):
        admin = self.login_admin()
        page = admin.get('/admin/life/ai').get_data(as_text=True)
        self.assertNotIn('소보루 제보 동향', page)
        r = admin.post('/admin/life/ai', data={'_csrf': self.csrf(admin, '/admin/life/ai'), 'kind': 'reports'}, follow_redirects=True)
        self.assertIn('멈춰 두었어요', r.get_data(as_text=True))

    def test_writer_reports_draft_check_dedupe_and_admin_only(self):
        self.writer_cleanup(); self.addCleanup(self.writer_cleanup)
        p = patch.object(self.site.soboru_writer, 'PAUSED', set()); p.start(); self.addCleanup(p.stop)  # 다시 켤 때를 위해 글 쓰기 자체는 계속 시험
        w = self.site.app.extensions['soboru_writer']
        co, secret = self.writer_cases(n_private=0)
        with self.site.app.app_context(): base = w['collect']('reports')['facts']
        with self.site.conn() as db: db.execute("DELETE FROM companies WHERE name='비밀상회'")
        self.writer_cases(n_public=0, n_private=4)  # 비밀글·게시 전 제보를 더해도 자료는 그대로
        with self.site.app.app_context(): got = w['collect']('reports')
        self.assertEqual(got['facts'], base)
        text = json.dumps(got, ensure_ascii=False)
        for word in ('비밀상회', '비밀 제보', '김철수', '010-1234-5678', '개인정보', '환불이 안 돼요'):
            self.assertNotIn(word, text)  # 비공개 제보는 기업 이름·제목·유형도 안 들어가고, 공개 제보도 제목·내용은 안 씀
        with self.site.conn() as db:
            n = db.execute("SELECT COUNT(*) FROM cases WHERE public_consent=1 AND published=1 AND review NOT IN ('rejected','duplicate') AND created>=?",
                           ((datetime.datetime.now() - datetime.timedelta(days=30)).isoformat(timespec='seconds'),)).fetchone()[0]
        self.assertEqual(got['facts']['최근 공개 제보(건)'], n)
        cos = got['facts']['기업별 답변 (공개 제보 5건 이상인 기업만, 많은 순)']
        self.assertEqual([(c['기업'], c['기업에 전달된 공개 제보(건)'], c['답변한 제보(건)'], c['답변률(%)']) for c in cos if c['기업'] == '공개몰'], [('공개몰', 6, 4, 67)])
        # 관리자만: 로그인 안 하면 화면·만들기 모두 막힘 (글도 안 생김)
        sent = []
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent)):
            r = self.client.get('/admin/life/ai'); self.assertEqual(r.status_code, 302); self.assertIn('/admin/login', r.headers['Location'])
            r = self.client.post('/admin/life/ai', data={'_csrf': self.csrf(self.client, '/report'), 'kind': 'reports'})
            self.assertEqual(r.status_code, 302); self.assertIn('/admin/login', r.headers['Location'])
            self.assertEqual(sent, [])
            admin = self.login_admin()
            page = admin.get('/admin/life/ai').get_data(as_text=True)
            self.assertIn('소보루 제보 동향', page); self.assertIn('네이버 API HUB 키가 없어요', page)  # 키 없는 종류는 이유를 보여 줌
            r = admin.post('/admin/life/ai', data={'_csrf': self.csrf(admin, '/admin/life/ai'), 'kind': 'reports'})
            self.assertEqual(r.status_code, 302)
            aid = int(re.search(r'/admin/life/(\d+)', r.headers['Location'])[1])
            (body,), = [sent]
            self.assertEqual(body['response_format'], {'type': 'json_object'}); self.assertNotIn('tools', body)  # 인터넷 검색 없이
            self.assertNotIn('비밀상회', json.dumps(body, ensure_ascii=False)); self.assertNotIn('sk-test-key', json.dumps(body, ensure_ascii=False))
            with self.site.conn() as db:
                a = db.execute('SELECT * FROM articles WHERE id=?', (aid,)).fetchone()
                x = db.execute('SELECT * FROM ai_articles WHERE article_id=?', (aid,)).fetchone()
            self.assertEqual((a['status'], a['origin'], a['ext_key']), ('draft', 'ai', 'ai:reports:' + datetime.date.today().isoformat()))
            self.assertIsNone(a['published_at']); self.assertEqual(a['source_name'], '소보루 공개 제보 통계')
            self.assertEqual(len(a['summary'].split('\n')), 3); self.assertIn('## 이렇게 대비하자', a['body'])
            self.assertEqual(x['check_ok'], 1)
            edit = admin.get(f'/admin/life/{aid}').get_data(as_text=True)
            self.assertIn('숫자 확인됨', edit); self.assertIn('AI에 넘긴 자료 보기', edit)
            self.assertEqual(self.client.get(f'/life/{aid}').status_code, 404)  # 초안은 방문자에게 안 보임
            # 같은 날 같은 종류는 한 번만 (다시 누르면 그 초안을 엶)
            r = admin.post('/admin/life/ai', data={'_csrf': self.csrf(admin, '/admin/life/ai'), 'kind': 'reports'})
            self.assertTrue(r.headers['Location'].endswith(f'/admin/life/{aid}')); self.assertEqual(len(sent), 1)
            self.assertEqual(w['generate']('reports', 'daily')['status'], 'exists')
            # 자료에 없는 숫자를 쓰면 '검토 필요' + 그 줄, 확인 체크 없이는 게시 안 됨
            r = admin.post('/admin/life/ai', data={'_csrf': self.csrf(admin, '/admin/life/ai'), 'kind': 'reports', 'force': '1'})
            self.assertEqual(len(sent), 2)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent, extra=' 작년보다 98765명 늘었어요.')):
            r = admin.post('/admin/life/ai', data={'_csrf': self.csrf(admin, '/admin/life/ai'), 'kind': 'reports', 'force': '1'})
        self.assertTrue(r.headers['Location'].endswith(f'/admin/life/{aid}'))  # 같은 초안을 새로 씀
        with self.site.conn() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM articles WHERE origin='ai'").fetchone()[0], 1)
            a = db.execute('SELECT * FROM articles WHERE id=?', (aid,)).fetchone()
        edit = admin.get(f'/admin/life/{aid}').get_data(as_text=True)
        self.assertIn('검토 필요 1곳', edit); self.assertIn('자료에 없는 숫자 98765', edit); self.assertIn('숫자를 직접 확인했어요', edit)
        self.assertIn('검토 필요 1곳', admin.get('/admin/life/ai').get_data(as_text=True))
        form = {'_csrf': self.csrf(admin, f'/admin/life/{aid}'), 'title': a['title'], 'summary': a['summary'], 'body': a['body'], 'category': a['category'],
                'emoji': a['emoji'], 'tone': a['tone'], 'source_name': a['source_name'], 'source_url': a['source_url']}
        r = admin.post(f'/admin/life/{aid}', data=dict(form, act='publish'), follow_redirects=True)
        self.assertIn('게시하지 않았어요', r.get_data(as_text=True))
        with self.site.conn() as db: self.assertEqual(db.execute('SELECT status FROM articles WHERE id=?', (aid,)).fetchone()[0], 'draft')
        # 운영자가 고쳐 저장하면 같은 자료로 다시 검사 → 통과하면 게시 가능
        fixed = a['body'].replace(' 작년보다 98765명 늘었어요.', '')
        admin.post(f'/admin/life/{aid}', data=dict(form, body=fixed, act='save'))
        with self.site.conn() as db: self.assertEqual(db.execute('SELECT check_ok FROM ai_articles WHERE article_id=?', (aid,)).fetchone()[0], 1)
        admin.post(f'/admin/life/{aid}', data=dict(form, body=fixed, act='publish'))
        with self.site.conn() as db: self.assertEqual(db.execute('SELECT status FROM articles WHERE id=?', (aid,)).fetchone()[0], 'published')
        page = self.client.get(f'/life/{aid}').get_data(as_text=True)
        self.assertIn('class="sb-sum3"', page); self.assertIn('바쁜 이웃님을 위한 3줄 요약', page); self.assertIn('sb-letter-cta', page); self.assertIn('소보루 공개 제보 통계 ↗', page); self.assertIn('AI가 위 자료의 숫자만으로', page)
        # 지우면 AI 기록도 같이 지움
        admin.post(f'/admin/life/{aid}', data=dict(form, act='delete'))
        with self.site.conn() as db: self.assertIsNone(db.execute('SELECT 1 FROM ai_articles WHERE article_id=?', (aid,)).fetchone())

    def writer_naver(self, calls):
        import urllib.parse
        weeks = [(datetime.date.today() - datetime.timedelta(days=7 * (12 - i))).isoformat() for i in range(12)]
        news_day = datetime.date.today() - datetime.timedelta(days=1)
        pub = news_day.strftime('%a, %d %b %Y 09:00:00 +0900')
        def fake(method, url, headers, body, timeout):
            calls.append(url)
            path = url.split('ntruss.com', 1)[1].split('?')[0]
            if path == '/search-trend/v1/search':
                return 200, {'results': [{'title': g['groupName'], 'data': [{'period': p, 'ratio': 20 + i * (k + 1)} for i, p in enumerate(weeks)]} for k, g in enumerate(body['keywordGroups'])]}
            if path == '/search/v1/news':
                q = dict(urllib.parse.parse_qsl(url.split('?', 1)[1]))['query']
                return 200, {'total': 2, 'items': [{'title': f'{q} 늘어 소비자 주의 {j}', 'description': f'{q} 관련 상담이 30% 늘었다 010-5555-6666', 'link': f'https://n.news.naver.com/{q}/{j}',
                                                    'originallink': f'https://news.example.co.kr/{abs(hash(q)) % 1000}/{j}', 'pubDate': pub} for j in range(2)]}
            if path == '/shopping/v1/categories':
                return 200, {'results': [{'title': c['name'], 'data': [{'period': p, 'ratio': 30 + i * (len(c['name']) % 4)} for i, p in enumerate(weeks)]} for c in body['category']]}
            if path.startswith('/shopping/v1/category/'):
                grp = {'gender': ['f', 'm'], 'age': ['20', '30'], 'device': ['pc', 'mo']}[path.rsplit('/', 1)[1]]
                return 200, {'results': [{'title': '분야', 'data': [{'period': weeks[0], 'group': grp[0], 'ratio': 60}, {'period': weeks[0], 'group': grp[1], 'ratio': 40}]}]}
            return 404, {}
        return fake

    def test_writer_daily_publishes_checked_and_rotates(self):
        self.writer_cleanup(); self.addCleanup(self.writer_cleanup)
        w = self.site.app.extensions['soboru_writer']; hub = self.site.naverhub
        sent, calls = [], []
        env = {'OPENAI_API_KEY': 'sk-test-key', 'NAVER_HUB_CLIENT_ID': 'cid-test', 'NAVER_HUB_CLIENT_SECRET': 'secret-test-value'}
        # AI 키가 없으면 아무것도 안 함
        with patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != 'OPENAI_API_KEY'}, clear=True):
            self.assertEqual(w['daily']()[0]['status'], 'skip')
        # 다른 시험이 넣은 공개 제보 수와 상관없이 '제보 동향'은 건너뛰게 (최소 건수를 아주 크게)
        with patch.dict(os.environ, env), patch.object(hub, 'http', self.writer_naver(calls)), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent)), \
                patch.object(self.site.jebo, 'MIN_N', 10 ** 6):
            self.assertEqual((w['settings']()['per_run'], w['settings']()['per_day']), (5, 15))  # 기본은 아침·오후·저녁 5개씩
            admin = self.login_admin()
            admin.post('/admin/life/ai/settings', data={'_csrf': self.csrf(admin, '/admin/life/ai'), 'auto': '1', 'publish': '1', 'per_run': '2'})
            morning = datetime.datetime(2026, 10, 20, 7, 30)
            out = w['daily'](now=morning)
            made = [r for r in out if r['status'] == 'made']
            self.assertEqual(len(made), 2)  # 한 번에 2개로 고른 대로
            self.assertEqual(out[0]['kind'], 'trend')  # 첫날은 순서표 맨 앞부터, 제보 동향은 공개 제보가 적어 건너뜀
            self.assertNotIn('reports', [r['kind'] for r in out])  # 제보로 쓰는 글은 멈춰 둠 (운영자 요청)
            self.assertEqual(w['daily'](now=morning), [])  # 같은 때 다시 돌려도 더 만들지 않음
            with self.site.conn() as db:
                rows = db.execute("SELECT a.*,x.kind,x.facts,x.sources FROM articles a JOIN ai_articles x ON x.article_id=a.id WHERE a.origin='ai'").fetchall()
            with self.site.conn() as db: checks = {r[0]: r[1] for r in db.execute('SELECT article_id,check_ok FROM ai_articles')}
            self.assertTrue(any(checks.values()))
            for r in rows:  # 숫자 검사를 통과한 글만 승인 없이 바로 게시, 아니면 초안
                self.assertEqual((r['status'], r['published_at'] is not None), ('published', True) if checks[r['id']] else ('draft', False))
            kinds = {r['kind']: r for r in rows}
            self.assertEqual(set(kinds), {'trend', 'news'})
            trend = json.loads(kinds['trend']['facts'])
            self.assertEqual([r['검색어'] for r in trend['검색어별 추이(증감률 큰 순)']][0], '구독 해지')
            news = kinds['news']
            self.assertNotIn('010-5555-6666', news['facts'])  # 뉴스 요약 속 연락처도 지움
            self.assertIn('관련 법 조문', news['facts']); self.assertIn('https://news.example.co.kr/', news['sources'])
            self.assertNotIn('secret-test-value', json.dumps([dict(r) for r in rows], ensure_ascii=False))
            life = self.client.get('/life').get_data(as_text=True)
            for r in rows: (self.assertIn if checks[r['id']] else self.assertNotIn)(r['title'], life)
            # 다음 날은 다음 종류부터, 자동 쓰기를 끄면 아무것도 안 함
            tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
            admin.post('/admin/life/ai/settings', data={'_csrf': self.csrf(admin, '/admin/life/ai'), 'per_run': '1'})
            self.assertEqual(w['settings'](), {'auto': 0, 'per_run': 1, 'per_day': 3, 'publish': 0, 'cats': 0})
            self.assertEqual(w['daily'](tomorrow)[0]['status'], 'off')
            admin.post('/admin/life/ai/settings', data={'_csrf': self.csrf(admin, '/admin/life/ai'), 'auto': '1', 'per_run': '1'})
            with self.site.conn() as db: db.execute("UPDATE ai_articles SET created='2000-01-01T07:00:00'")  # 오늘 만든 개수에서 빼서 다음 날처럼
            out = w['daily'](tomorrow, now=morning)
            self.assertNotIn('reports', [r['kind'] for r in out])
            self.assertEqual([r['kind'] for r in out if r['status'] == 'made'], ['news'])
            with self.site.conn() as db:
                self.assertEqual(db.execute("SELECT status FROM articles WHERE origin='ai' ORDER BY id DESC LIMIT 1").fetchone()[0], 'draft')  # 바로 게시를 끄면 초안
            # 맨 위 '자동 게시 멈추기'는 게시만 끄고 글은 계속 씀, '다시 켜기'는 게시를 켬
            admin.post('/admin/life/ai/settings', data={'_csrf': self.csrf(admin, '/admin/life/ai'), 'act': 'start'})
            self.assertEqual(w['settings'](), {'auto': 1, 'per_run': 1, 'per_day': 3, 'publish': 1, 'cats': 0})
            self.assertIn('자동 게시 중이에요', admin.get('/admin/life/ai').get_data(as_text=True))
            admin.post('/admin/life/ai/settings', data={'_csrf': self.csrf(admin, '/admin/life/ai'), 'act': 'stop'})
            self.assertEqual(w['settings'](), {'auto': 1, 'per_run': 1, 'per_day': 3, 'publish': 0, 'cats': 0})
            self.assertIn('자동 게시를 멈췄어요', admin.get('/admin/life/ai').get_data(as_text=True))
            # 쇼핑 관심도: 가장 많이 오른 분야와 그 분야 클릭 비중
            with self.site.app.app_context(): shop = w['collect']('shopping')
            top = shop['facts']['가장 많이 오른 분야']
            self.assertEqual(shop['facts'][f'{top} 클릭 비중']['성별 클릭 비중(%)'], {'여성': 60, '남성': 40})
            self.assertEqual(shop['category'], '쇼핑')

    def test_writer_pair_check_holds_wrong_subject_numbers(self):
        """숫자가 자료에 있어도 다른 대상에 붙었으면(하나은행 89명 → 119명) 바로 게시하지 않고, 게시된 글도 다시 검사해 초안으로."""
        self.writer_cleanup(); self.addCleanup(self.writer_cleanup)
        w = self.site.app.extensions['soboru_writer']; hub = self.site.naverhub
        sent, calls = [], []
        env = {'OPENAI_API_KEY': 'sk-test-key', 'NAVER_HUB_CLIENT_ID': 'cid-test', 'NAVER_HUB_CLIENT_SECRET': 'secret-test-value'}
        bad = [{'line': '국민은행과 하나은행도 각각 119명과 119명', 'why': '자료에서는 하나은행 89명'}]
        with patch.dict(os.environ, env), patch.object(hub, 'http', self.writer_naver(calls)), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent, pair=bad)), \
                patch.object(self.site.jebo, 'MIN_N', 10 ** 6):
            self.pair_calls = []
            r = w['generate']('trend', 'daily')
            self.assertEqual(r['status'], 'made'); self.assertFalse(r['published'])
            self.assertTrue(self.pair_calls)
            self.assertIn('[자료]', self.pair_calls[0]['messages'][1]['content']); self.assertIn('[글]', self.pair_calls[0]['messages'][1]['content'])
            with self.site.conn() as db:
                row = db.execute('SELECT a.status,x.check_ok,x.problems FROM articles a JOIN ai_articles x ON x.article_id=a.id WHERE a.id=?', (r['id'],)).fetchone()
            self.assertEqual((row['status'], row['check_ok']), ('draft', 0))
            self.assertEqual(json.loads(row['problems'])[0]['pair'], '자료에서는 하나은행 89명')
            admin = self.login_admin()
            self.assertIn('숫자 짝이 달라요: 자료에서는 하나은행 89명', admin.get(f'/admin/life/{r["id"]}').get_data(as_text=True))
        # 문제 없는 글은 게시되고, 나중에 다시 검사해서 걸리면 초안으로
        with patch.dict(os.environ, env), patch.object(hub, 'http', self.writer_naver(calls)), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent)), \
                patch.object(self.site.jebo, 'MIN_N', 10 ** 6):
            ok = w['generate']('news', 'daily')
            self.assertTrue(ok['published'])
            self.assertEqual(w['recheck'](7), [])  # 문제 없으면 그대로
        with patch.dict(os.environ, env), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent, pair=bad)):
            got = w['recheck'](7)
            self.assertEqual([g['id'] for g in got], [ok['id']])
            with self.site.conn() as db: self.assertEqual(db.execute('SELECT status FROM articles WHERE id=?', (ok['id'],)).fetchone()[0], 'draft')
        with patch.dict(os.environ, env), patch.object(self.site.companydesk, 'post_json', lambda *a, **k: (500, {'error': {'message': 'down'}})):
            with self.site.conn() as db: db.execute("UPDATE articles SET status='published' WHERE id=?", (ok['id'],))
            self.assertEqual(w['recheck'](7), [])  # 교열을 못 하면 게시된 글은 건드리지 않음

    def test_writer_proofread_fixes_published_article(self):
        """관리자 '재교열하기': 걸린 문장을 자료대로 고치고, 고친 뒤 깨끗하면 게시 그대로. 남으면 초안으로."""
        self.writer_cleanup(); self.addCleanup(self.writer_cleanup)
        w = self.site.app.extensions['soboru_writer']; hub = self.site.naverhub
        sent, calls = [], []
        env = {'OPENAI_API_KEY': 'sk-test-key', 'NAVER_HUB_CLIENT_ID': 'cid-test', 'NAVER_HUB_CLIENT_SECRET': 'secret-test-value'}
        with patch.dict(os.environ, env), patch.object(hub, 'http', self.writer_naver(calls)), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent)), \
                patch.object(self.site.jebo, 'MIN_N', 10 ** 6):
            r = w['generate']('news', 'daily'); self.assertTrue(r['published'])
        with self.site.conn() as db:
            db.execute("UPDATE articles SET body=body || ?, updated=updated WHERE id=?", ('\n\n국민은행과 하나은행도 각각 119명과 119명의 정보가 유출됐어요.', r['id']))
            f = json.loads(db.execute('SELECT facts FROM ai_articles WHERE article_id=?', (r['id'],)).fetchone()[0])
            f['은행 해킹 뉴스'] = '신한 2만5천명·국민 119명·하나 89명 정보 유출'
            db.execute('UPDATE ai_articles SET facts=? WHERE article_id=?', (json.dumps(f, ensure_ascii=False), r['id']))
        wrong = '국민은행과 하나은행도 각각 119명과 119명의 정보가 유출됐어요.'
        pair = lambda body: [{'line': wrong, 'why': '자료에서는 하나은행 89명'}] if wrong in body['messages'][1]['content'] else []
        fix = [{'before': wrong, 'after': '국민은행은 119명, 하나은행은 89명의 정보가 유출됐어요.'}]
        admin = self.login_admin()
        with patch.dict(os.environ, env), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent, pair=pair, fix=fix)):
            res = admin.post(f'/admin/life/{r["id"]}/proofread', data={'_csrf': self.csrf(admin, f'/admin/life/{r["id"]}')})
        self.assertEqual(res.status_code, 302)
        with self.site.conn() as db: a = db.execute('SELECT status,body FROM articles WHERE id=?', (r['id'],)).fetchone()
        self.assertIn('하나은행은 89명', a['body']); self.assertNotIn(wrong, a['body'])
        self.assertEqual(a['status'], 'published')  # 고친 뒤 문제가 없으면 게시 그대로
        page = admin.get(f'/admin/life/{r["id"]}').get_data(as_text=True)
        self.assertIn('1곳을 자료대로 고쳤어요', page); self.assertIn('하나은행은 89명', page); self.assertIn('재교열하기', page)
        self.assertNotIn('1곳을 자료대로 고쳤어요', admin.get(f'/admin/life/{r["id"]}').get_data(as_text=True))  # 결과는 한 번만
        # 고쳐도 문제가 남으면 게시를 내림
        always = [{'line': '첫 줄 요약이에요.', 'why': '자료와 다른 대상'}]
        with patch.dict(os.environ, env), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent, pair=always, fix=[])):
            out = w['proofread'](r['id'])
        self.assertEqual((out['status'], out['unpublished']), ('left', True))
        with self.site.conn() as db: self.assertEqual(db.execute('SELECT status FROM articles WHERE id=?', (r['id'],)).fetchone()[0], 'draft')

    def test_writer_reads_news_originals_for_numbers(self):
        """뉴스 요약이 잘려도 원문에서 숫자 문장을 가져와 자료에 넣음 (하나은행 89명이 요약에서 잘렸던 일)"""
        mod = self.site.soboru_writer
        page = ('<html><head><meta charset="utf-8"><script>var a=1234;</script></head><body><nav>메뉴 2026</nav><div class="art">'
                '<p>신한은행은 약 2만5000명의 개인정보가 유출됐다. 국민은행과 하나은행은 각각 119명, 89명이다.</p>'
                '<p>홍길동 기자 hong@news.kr 010-1234-5678</p><p>무단 전재 및 재배포 금지 2026</p></div></body></html>')
        sents = mod.number_sentences(page)
        self.assertIn('국민은행과 하나은행은 각각 119명, 89명이다.', sents)
        self.assertFalse([x for x in sents if '1234' in x or '@' in x or '재배포' in x or '메뉴' in x])
        self.assertFalse(mod._public_host('http://127.0.0.1/a')); self.assertFalse(mod._public_host('file:///etc/passwd')); self.assertFalse(mod._public_host('http://10.0.0.5/'))
        self.writer_cleanup(); self.addCleanup(self.writer_cleanup)
        w = self.site.app.extensions['soboru_writer']; hub = self.site.naverhub
        sent, calls, opened = [], [], []
        env = {'OPENAI_API_KEY': 'sk-test-key', 'NAVER_HUB_CLIENT_ID': 'cid-test', 'NAVER_HUB_CLIENT_SECRET': 'secret-test-value'}
        with patch.dict(os.environ, env), patch.object(hub, 'http', self.writer_naver(calls)), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent)), \
                patch.object(mod, 'fetch_page', lambda u: (opened.append(u), page)[1]):
            with self.site.app.app_context(): got = w['collect']('news')
        self.assertTrue(opened)
        self.assertIn('국민은행과 하나은행은 각각 119명, 89명이다.', got['facts']['뉴스'][0]['원문 속 숫자 문장(원문 확인)'])
        self.assertEqual(self.site.soboru_writer.check_text('하나은행은 89명이에요.', got['facts']), [])  # 원문 숫자는 숫자 검사도 통과

    def test_writer_daily_replaces_held_articles(self):
        """검사에 걸려 초안으로 남은 글은 몫에 세지 않고 다른 글을 더 써서 채움 (한 번에 몫의 두 배까지만)"""
        self.writer_cleanup(); self.addCleanup(self.writer_cleanup)
        w = self.site.app.extensions['soboru_writer']; hub = self.site.naverhub
        sent, calls, n = [], [], [0]
        env = {'OPENAI_API_KEY': 'sk-test-key', 'NAVER_HUB_CLIENT_ID': 'cid-test', 'NAVER_HUB_CLIENT_SECRET': 'secret-test-value'}
        def pair(body):
            n[0] += 1
            return [{'line': '첫 줄 요약이에요.', 'why': '다른 대상'}] if n[0] <= 2 else []
        with patch.dict(os.environ, env), patch.object(hub, 'http', self.writer_naver(calls)), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent, pair=pair)), \
                patch.object(self.site.jebo, 'MIN_N', 10 ** 6):
            w['save_settings'](1, 5, 1, 0)  # 연재는 끄고 '한 번에 몇 개' 몫으로
            out = w['daily'](now=datetime.datetime(2026, 10, 20, 7, 30))
            made = [r for r in out if r['status'] == 'made']
            self.assertEqual(sum(1 for r in made if r['published']), 5)  # 걸린 2개 대신 더 써서 게시 5개
            self.assertEqual(len(made), 7)
            self.assertEqual(w['daily'](now=datetime.datetime(2026, 10, 20, 8, 0)), [])
        always = lambda body: [{'line': '첫 줄 요약이에요.', 'why': '다른 대상'}]
        with patch.dict(os.environ, env), patch.object(hub, 'http', self.writer_naver(calls)), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent, pair=always)), \
                patch.object(self.site.jebo, 'MIN_N', 10 ** 6):
            out = w['daily'](now=datetime.datetime(2026, 10, 20, 13, 30))
            self.assertLessEqual(len([r for r in out if r['status'] == 'made']), 12)  # 다 걸려도 몫(5)의 두 배 + 2까지만

    def test_writer_every_kind_is_a_long_combined_article(self):
        """모든 글을 종합 기사로: 검색 추이 글에도 뉴스·법 조문을 곁들이고, 길게 쓰라고 함 (운영자 요청 2026-10-21)"""
        self.writer_cleanup(); self.addCleanup(self.writer_cleanup)
        w = self.site.app.extensions['soboru_writer']; hub = self.site.naverhub
        sent, calls = [], []
        env = {'OPENAI_API_KEY': 'sk-test-key', 'NAVER_HUB_CLIENT_ID': 'cid-test', 'NAVER_HUB_CLIENT_SECRET': 'secret-test-value'}
        with patch.dict(os.environ, env), patch.object(hub, 'http', self.writer_naver(calls)), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent)):
            with self.site.app.app_context(): got = w['collect']('trend')
            self.assertIn('최근 관련 뉴스(제목·요약만)', got['facts'])
            self.assertTrue(any('뉴스' in s['name'] or '·' in s['name'] for s in got['sources']))
            r = w['generate']('trend', 'daily'); self.assertEqual(r['status'], 'made')
        prompt = [b for b in sent if b['messages'][0]['content'].startswith('너는 소보루')][-1]['messages'][1]['content']
        self.assertIn('[분량·구성]', prompt); self.assertIn('1300~1700자', prompt); self.assertNotIn('3500~4500자', prompt); self.assertIn('최근 관련 뉴스', prompt)

    def test_writer_long_read_format(self):
        # 뉴닉 롱리드처럼: 소제목 없는 도입 → 핵심 상자 → 소제목 + 번호 요점 + 용어 풀이 → 이렇게 하세요 → 마무리 (운영자 2026-10-21)
        import soboru_writer as sw
        out = {'title': '첫 신용카드, 이것부터 알아 두세요', 'summary': ['하나', '둘', '셋'], 'highlight': '결제일을 놓치면 신용점수가 떨어질 수 있어요.',
               'intro': ['처음이라는 말은 늘 설레요.', '이 글은 첫 카드를 앞둔 분께 전하고 싶은 이야기예요.'],
               'sections': [{'emoji': '💳', 'heading': '쓰면서 꼭 기억해야 할 것들', 'paragraphs': ['처음부터 습관이 중요해요.'],
                             'points': [{'title': '1. 일시불을 써 보세요', 'text': '할부는 미래의 돈을 당겨 쓰는 거예요.'}, {'title': '결제일을 기억하세요', 'text': '알림을 꼭 켜 두세요.'}],
                             'terms': [{'word': '리볼빙', 'meaning': '카드값 일부만 내고 나머지를 미루는 서비스예요.'}]}],
               'tips': ['결제일 알림을 켜세요'], 'closing': {'heading': '소보루와 함께 시작해요', 'paragraphs': ['수상한 결제 문자를 받았다면 사기 주의에서 번호를 찾아보세요.']}}
        title, summary, body, cat = sw.assemble(out, 'feature')
        self.assertTrue(body.startswith('처음이라는 말은 늘 설레요.'))
        self.assertNotIn('> 💡', body); self.assertIn('## 쓰면서 꼭 기억해야 할 것들', body); self.assertNotIn('💳', body)  # 운영자 2026-11-05: 매거진 기사체 — 핵심 상자·이모지 없음
        self.assertIn('### 일시불을 써 보세요', body)  # 번호는 본문에 넣지 않음 (숫자 검사)
        self.assertIn('※ 리볼빙: 카드값 일부만', body)
        self.assertLess(body.index('## 이렇게 대비하자'), body.index('## 소보루와 함께 시작해요'))
        with self.site.app.test_request_context('/'): html = str(self.site.app.jinja_env.globals['life_body'](body))
        self.assertIn('<span class="sb-point-n" aria-hidden="true">2</span>결제일을 기억하세요', html)
        self.assertIn("<dl class=\"sb-terms\">", html); self.assertIn("<dt>리볼빙</dt>", html)  # 용어 풀이는 상자 하나로
        self.assertNotIn('###', html)
        with self.site.app.test_request_context('/'): one = str(self.site.app.jinja_env.globals['life_body']('## 가\n\n### 혼자인 요점\n\n설명\n\n## 나\n\n### 또 혼자\n\n설명'))
        self.assertNotIn('sb-point-n', one); self.assertIn('<h3 class="sb-point">혼자인 요점</h3>', one)  # 요점이 하나뿐이면 번호 없음 (모두 1로 보이던 문제)
        with self.site.app.test_request_context('/'): hl = str(self.site.app.jinja_env.globals['life_body']('앞 **꼭 기억할 말** 뒤 <b>x</b> **'))
        self.assertIn('<strong class="sb-hl">꼭 기억할 말</strong>', hl); self.assertIn('&lt;b&gt;', hl); self.assertNotIn('**', hl)  # 형광펜 강조, 태그는 글자로

    def test_writer_skips_similar_topic_within_30_days(self):
        """제목이 달라도 소재가 같은 글(외식비·외식 물가)은 30일 안에 다시 쓰지 않음"""
        self.writer_cleanup(); self.addCleanup(self.writer_cleanup)
        w = self.site.app.extensions['soboru_writer']; hub = self.site.naverhub
        sent, calls = [], []
        env = {'OPENAI_API_KEY': 'sk-test-key', 'NAVER_HUB_CLIENT_ID': 'cid-test', 'NAVER_HUB_CLIENT_SECRET': 'secret-test-value'}
        now = datetime.datetime.now().isoformat(timespec='seconds')
        with self.site.conn() as db:
            db.execute("INSERT INTO articles(title,summary,body,category,emoji,tone,source_name,source_url,status,origin,ext_key,created,updated) VALUES('외식비 부담 얼마나 늘었나','s','b','음식','📌','t1','','','published','ai','ai:feature:외식비:x',?,?)", (now, now))
        fake = self.writer_ai(sent)
        def ai(url, headers, body, timeout):  # 새 기사 제목에 '외식'을 넣어 비슷한 주제로 만듦
            st, res = fake(url, headers, body, timeout)
            if body['messages'][0]['content'].startswith('너는 소보루'):
                out = json.loads(res['choices'][0]['message']['content']); out['title'] = '외식 물가, 요즘 얼마나 올랐을까 ' + out['title']
                res = {'model': 'test-model', 'choices': [{'message': {'content': json.dumps(out, ensure_ascii=False)}}]}
            return st, res
        with patch.dict(os.environ, env), patch.object(hub, 'http', self.writer_naver(calls)), patch.object(self.site.companydesk, 'post_json', ai):
            r = w['generate']('trend', 'daily')
        self.assertEqual(r['status'], 'skip'); self.assertIn('비슷한 주제', r['reason'])
        with patch.dict(os.environ, env), patch.object(hub, 'http', self.writer_naver(calls)), patch.object(self.site.companydesk, 'post_json', fake):
            self.assertEqual(w['generate']('trend', 'daily')['status'], 'made')  # 다른 소재면 씀

    def test_writer_uses_kosis_stats(self):
        """KOSIS 키가 있으면 품목별 소비자물가와 주제로 찾은 통계표를 자료에 넣음 (값·증감률은 미리 계산해 넣고 AI는 옮기기만)"""
        mod = self.site.soboru_writer; mod._KOSIS_MEMO.clear()
        self.writer_cleanup(); self.addCleanup(self.writer_cleanup)
        w = self.site.app.extensions['soboru_writer']; hub = self.site.naverhub
        months = [f'2025{m:02d}' for m in range(9, 13)] + [f'2026{m:02d}' for m in range(1, 10)]  # 13달
        cpi = [{'C1_NM': n, 'PRD_DE': p, 'DT': str(base + i)} for n, base in (('총지수', 110), ('외식', 120), ('휘발유', 130)) for i, p in enumerate(months)]
        urls = []
        def get(url, timeout=15):
            urls.append(url); q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            self.assertEqual(q['apiKey'], 'kosis-test-key')
            if 'statisticsSearch' in url: return 200, json.dumps([{'ORG_ID': '117', 'TBL_ID': 'DT_X', 'TBL_NM': '외식업 경영 실태'}])
            if q.get('tblId') == 'DT_1J22003': return 200, json.dumps(cpi)
            if q.get('tblId') == 'DT_X' and q['prdSe'] == 'Y' and 'objL2' not in q:
                return 200, json.dumps([{'C1_NM': '전체', 'ITM_NM': '월평균 매출액', 'UNIT_NM': '만원', 'PRD_DE': p, 'DT': d} for p, d in (('2023', '1000'), ('2024', '1100'))])
            return 200, json.dumps({'err': '20', 'errMsg': '필수요청변수값이 누락되었습니다.'})
        env = {'OPENAI_API_KEY': 'sk-test-key', 'NAVER_HUB_CLIENT_ID': 'cid-test', 'NAVER_HUB_CLIENT_SECRET': 'secret-test-value', 'KOSIS_API_KEY': 'kosis-test-key'}
        sent, calls = [], []
        with patch.dict(os.environ, env), patch.object(mod, 'http_get', get), patch.object(hub, 'http', self.writer_naver(calls)), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent)):
            with self.site.app.app_context():
                st = w['kosis_facts']('외식비', '음식')
                got = w['collect']('trend')
        cpi_rows = st['소비자물가지수(통계청 KOSIS, 품목별)']
        self.assertEqual([r['품목'] for r in cpi_rows], ['총지수', '외식'])  # 음식 분야: 외식, 휘발유는 빼고
        self.assertEqual(cpi_rows[1]['1년 전 같은 달보다(%)'], round(12 / 120 * 100, 1)); self.assertEqual(cpi_rows[1]['기준 달'], '2026년 9월')
        table = st['관련 통계: 외식업 경영 실태 (통계청 KOSIS)'][0]
        self.assertEqual((table['값'], table['앞 기간 대비 증감률(%)'], table['단위']), (1100.0, 10.0, '만원'))
        self.assertTrue(any('통계청 KOSIS' in k for k in got['facts']))  # 검색 추이 글에도 주제로 찾은 통계표
        self.assertIn('통계청 국가통계포털(KOSIS)', [s['name'] for s in got['sources']])
        self.assertEqual(self.site.soboru_writer.check_text('외식 물가는 1년 전보다 10% 올랐어요.', st), [])  # 미리 계산한 증감률은 숫자 검사도 통과
        # 키가 없으면 KOSIS는 부르지 않음
        urls.clear(); mod._KOSIS_MEMO.clear()
        with patch.dict(os.environ, {k: v for k, v in env.items() if k != 'KOSIS_API_KEY'}), patch.object(mod, 'http_get', get), patch.object(hub, 'http', self.writer_naver(calls)):
            with self.site.app.app_context(): w['collect']('trend')
        self.assertFalse([u for u in urls if 'kosis' in u])

    def test_writer_stat_kind_from_cpi_by_item(self):
        """'숫자로 보는 생활비': 전국 코드를 찾아 품목 전부를 받고, 1년 새 많이 움직인 품목을 주제로 긴 기사 (운영자 요청 2026-10-21)"""
        mod = self.site.soboru_writer; mod._KOSIS_MEMO.clear()
        self.writer_cleanup(); self.addCleanup(self.writer_cleanup)
        w = self.site.app.extensions['soboru_writer']; hub = self.site.naverhub
        months = [f'2025{m:02d}' for m in range(9, 13)] + [f'2026{m:02d}' for m in range(1, 10)]
        region = [{'C1': c, 'C1_NM': n, 'ITM_NM': '소비자물가지수(총지수)', 'PRD_DE': p, 'DT': '115'} for c, n in (('T10', '전국'), ('T11', '서울')) for p in months]
        items = [{'C1': 'T10', 'C1_NM': '전국', 'C2_NM': n, 'ITM_NM': '소비자물가지수', 'PRD_DE': p, 'DT': str(base + step * i)}
                 for n, base, step in (('총지수', 110, 0.25), ('외식', 120, 0.5), ('쌀', 100, 2), ('휘발유', 130, -1)) for i, p in enumerate(months)]
        def get(url, timeout=15):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            if q.get('tblId') == 'DT_1J22003': return 200, json.dumps(items if q.get('objL1') == 'T10' and q.get('objL2') == 'ALL' else region)
            return 200, json.dumps({'err': '30', 'errMsg': '데이터가 존재하지 않습니다.'})
        env = {'OPENAI_API_KEY': 'sk-test-key', 'NAVER_HUB_CLIENT_ID': 'cid-test', 'NAVER_HUB_CLIENT_SECRET': 'secret-test-value', 'KOSIS_API_KEY': 'kosis-test-key'}
        sent, calls = [], []
        with patch.dict(os.environ, env), patch.object(mod, 'http_get', get), patch.object(hub, 'http', self.writer_naver(calls)), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent)):
            self.assertEqual([n for n, _ in mod.cpi_movers()], ['쌀', '휘발유', '외식'])  # 1년 상승률 큰 순, 총지수 빼고
            with self.site.app.app_context():
                got = w['collect']('stat')
            self.assertEqual(got['facts']['1년 전 같은 달보다(%)'], 24.0); self.assertEqual(got['facts']['기준 달'], '2026년 9월')
            self.assertEqual(got['facts']['전체 물가(총지수) 1년 상승률(%)'], round(3 / 110 * 100, 1))
            self.assertEqual(len(got['facts']['달별 지수']), 13)
            r = w['generate']('stat', 'daily'); self.assertIn(r['status'], ('made', 'skip'))
        prompts = [b['messages'][1]['content'] for b in sent if b['messages'][0]['content'].startswith('너는 소보루')]
        self.assertTrue(prompts); self.assertIn('[분량·구성]', prompts[-1]); self.assertIn('쌀', prompts[-1])

    def test_writer_uses_luna_only(self):
        """매거진 글은 GPT-6 Luna(낮은 추론, temperature 없음)로만. 오류면 다른 모델로 다시 쓰지 않음 (운영자 요청 2026-10-30)"""
        w = self.site.app.extensions['soboru_writer']; bodies = []
        def fake(url, headers, body, timeout):
            bodies.append(body); return 400, {'error': {'message': 'bad'}}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(self.site.companydesk, 'post_json', fake):
            with self.assertRaises(RuntimeError): w['chat']('s', 'u', 100)
        self.assertEqual([b['model'] for b in bodies], ['gpt-6-luna'])
        self.assertEqual((bodies[0]['reasoning_effort'], bodies[0]['max_completion_tokens']), ('low', 1600)); self.assertNotIn('temperature', bodies[0])

    def test_magazine_fix_topic_and_calc_links(self):
        """피해 해결 글: 검색어 그대로인 주제 + 법령 모음에서 찾을 말, 글 아래엔 맞는 계산기 (운영자 요청 2026-10-30: 검색 노출)"""
        mod = self.site.soboru_writer; tools = self.site.soboru_tools
        self.assertIn('헬스장 환불 거부', mod.FIX_TOPICS); self.assertIn('fix', mod.EXTRA)
        self.assertEqual([c['slug'] for c in tools.calcs_for('헬스장 환불 거부당했다면', '청약철회와 할부')], ['fitness', 'cooling'])
        self.assertEqual(tools.calcs_for('날씨 이야기', ''), [])

    def test_writer_drops_source_talk(self):
        """운영자 2026-11-05: '제공된 뉴스 요약만으로 ~는 확인할 수 없다' 같은 자료 이야기 문장은 매거진 기사에서 지움"""
        W = self.site.soboru_writer
        body = ('## 설명서에서 확인한다\n\n기능이 있다고 조건까지 알 수 있는 건 아니다. 제한 상황이 58개라고 전했지만, 제공된 뉴스 요약만으로 세부 내용은 확인할 수 없다. 설명서를 읽자.\n\n'
                '자료에는 금액이 나와 있지 않다.\n\n- 원인은 알 수 없다는 말이 많다.')
        self.assertEqual(W.drop_meta(body), '## 설명서에서 확인한다\n\n기능이 있다고 조건까지 알 수 있는 건 아니다. 설명서를 읽자.\n\n- 원인은 알 수 없다는 말이 많다.')
        self.assertIn('[출처·숫자는 구체적으로]', W.SYSTEM); self.assertIn('[우리 기사로 다시 쓰기]', W.SYSTEM); self.assertIn('[사례는 구체적으로]', W.SYSTEM); self.assertTrue(W.VAGUE.search('알려진 한 사례에서는 운영자가')); self.assertIn('[실명으로]', W.SYSTEM); self.assertIn('[되풀이 금지]', W.SYSTEM); self.assertEqual([p['words'] for p in W.check_text('식약처에 따르면 많다.\n소비자원에 따르면 적다.', {})], [['따르면 중복']]); self.assertTrue(W.VAGUE.search('A사는 환불을')); self.assertFalse(W.VAGUE.search('KT사는'))

    def test_writer_one_per_category(self):
        """분야마다 하루 한 편 기획 기사: 아침 3분야, 저녁까지 9분야 모두 (운영자 요청 2026-11-05)"""
        self.writer_cleanup(); self.addCleanup(self.writer_cleanup)
        w = self.site.app.extensions['soboru_writer']; hub = self.site.naverhub; mod = self.site.soboru_writer
        sent, calls = [], []
        env = {'OPENAI_API_KEY': 'sk-test-key', 'NAVER_HUB_CLIENT_ID': 'cid-test', 'NAVER_HUB_CLIENT_SECRET': 'secret-test-value'}
        with patch.dict(os.environ, env), patch.object(hub, 'http', self.writer_naver(calls)), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent)), \
                patch.object(self.site.jebo, 'MIN_N', 10 ** 6):
            self.assertEqual(w['settings']()['cats'], 1)  # 기본으로 켜 둠
            w['save_settings'](1, 1, 1)
            self.assertEqual(w['settings']()['cats'], 1)  # 다른 설정을 바꿔도 그대로
            out = w['daily'](now=datetime.datetime(2026, 10, 20, 7, 30))
            self.assertEqual([r['category'] for r in out if r.get('kind') == 'feature' and r.get('published')], list(mod.CATS[:3]))
            self.assertEqual(len([r for r in out if r['status'] == 'made' and r.get('published')]), 6)  # 아침: 3분야 + 종류 3개
            ev = w['daily'](now=datetime.datetime(2026, 10, 20, 19, 30))
            with self.site.conn() as db:
                kinds = [r[0] for r in db.execute("SELECT x.kind FROM ai_articles x JOIN articles a ON a.id=x.article_id WHERE x.kind!='feature' AND a.status='published'")]
            # 종류마다 한 편씩 연재 (법·통계는 시험에 키가 없어 건너뜀, 검색어 글은 가짜 AI 제목이 겹쳐 건너뜀)
            self.assertEqual(sorted(kinds), sorted(set(mod.SERIES) - {'law', 'stat', 'word'}))
            self.assertIn(('law', 'skip'), [(r.get('kind'), r['status']) for r in ev])
            self.assertEqual(len(kinds), len(set(kinds)))
            with self.site.conn() as db:
                cats = [r[0] for r in db.execute("SELECT a.category FROM articles a JOIN ai_articles x ON x.article_id=a.id WHERE x.kind='feature' AND a.status='published'")]
            self.assertEqual(sorted(set(cats)), sorted(mod.CATS))
            self.assertEqual(len(cats), len(mod.CATS))  # 분야마다 한 편씩만
            again = [r['kind'] for r in w['daily'](now=datetime.datetime(2026, 10, 20, 19, 40)) if r['status'] == 'made']
            self.assertFalse(set(again) & (set(kinds) | {'feature'}))  # 다시 돌려도 이미 쓴 분야·종류는 안 씀 (못 쓴 종류만 다시 해 봄)

    def test_writer_many_deep_articles_by_topic(self):
        self.writer_cleanup(); self.addCleanup(self.writer_cleanup)
        w = self.site.app.extensions['soboru_writer']; hub = self.site.naverhub
        sent, calls = [], []
        env = {'OPENAI_API_KEY': 'sk-test-key', 'NAVER_HUB_CLIENT_ID': 'cid-test', 'NAVER_HUB_CLIENT_SECRET': 'secret-test-value'}
        with patch.dict(os.environ, env), patch.object(hub, 'http', self.writer_naver(calls)), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent)), \
                patch.object(self.site.jebo, 'MIN_N', 10 ** 6):
            w['save_settings'](1, 5, 1, 0)  # 분야마다 한 편은 끄고 돌림표만 (분야별은 test_writer_one_per_category)
            out = w['daily'](now=datetime.datetime(2026, 10, 20, 7, 30))  # 아침 5개: 순서표(검색 추이·뉴스·쇼핑) 다음 기획 기사·주제별 글로 채움
            made = [r for r in out if r['status'] == 'made']
            self.assertEqual([r['kind'] for r in made][3:], ['feature', 'fix'])
            out = w['daily'](now=datetime.datetime(2026, 10, 20, 19, 30))  # 저녁에 돌면 오후 몫까지 채워 하루 15개
            made += [r for r in out if r['status'] == 'made']
            self.assertEqual(len(made), 15)
            self.assertEqual([r['kind'] for r in made][5:8], ['rights', 'word', 'feature'])
            with self.site.conn() as db:
                feats = db.execute("SELECT a.title,a.category,a.ext_key,x.facts FROM articles a JOIN ai_articles x ON x.article_id=a.id WHERE x.kind='feature'").fetchall()
                titles = [r[0] for r in db.execute("SELECT title FROM articles WHERE origin='ai'")]
            self.assertGreaterEqual(len(feats), 4)
            self.assertEqual(len({r['category'] for r in feats}), len(feats))  # 기획 기사는 글이 적은 분야부터: 분야가 겹치지 않게
            self.assertEqual(len(set(titles)), len(titles))  # 같은 제목은 다시 안 씀
            f = json.loads(feats[0]['facts'])
            self.assertIn('최근 관련 뉴스(제목·요약만)', f); self.assertIn('검색 추이(네이버 데이터랩)', f)
            self.assertIn('[분량·구성]', json.dumps(sent, ensure_ascii=False))
            with self.site.conn() as db:
                rows = {}
                for r in db.execute("SELECT a.ext_key,x.kind,x.facts FROM articles a JOIN ai_articles x ON x.article_id=a.id ORDER BY a.id"): rows.setdefault(r['kind'], r)  # 종류별 첫 글
            self.assertTrue(rows['rights']['ext_key'].startswith('ai:rights:온라인 쇼핑 청약철회:'))
            self.assertTrue(rows['fix']['ext_key'].startswith('ai:fix:온라인 쇼핑몰 환불 거부:'))  # 피해 해결 글: 검색어 그대로인 주제
            self.assertIn('전자상거래법 제17조', rows['rights']['facts'])
            word = json.loads(rows['word']['facts'])
            self.assertEqual(word['검색어별 추이'][0]['검색어'], word['주제 검색어'])
            self.assertIn('[주제] ' + word['주제 검색어'], json.dumps(sent, ensure_ascii=False))
            self.assertIn('성별 클릭 비중(%)', rows['shopcat']['facts'])
            # 다음 날 같은 종류는 다른 주제로
            with self.site.conn() as db: db.execute("UPDATE ai_articles SET created='2000-01-01T07:00:00'")
            tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
            again = w['generate']('rights', 'daily', day=tomorrow)
            with self.site.conn() as db: key = db.execute('SELECT ext_key FROM articles WHERE id=?', (again['id'],)).fetchone()[0]
            self.assertNotIn('온라인 쇼핑 청약철회', key)

    def test_writer_law_source_hides_key(self):
        self.writer_cleanup(); self.addCleanup(self.writer_cleanup)
        w = self.site.app.extensions['soboru_writer']; mod = self.site.soboru_writer
        soon = (datetime.date.today() + datetime.timedelta(days=5)).strftime('%Y%m%d')
        lst = ('<?xml version="1.0" encoding="UTF-8"?><LawSearch><totalCnt>2</totalCnt>'
               f'<law id="1"><법령명한글>전자상거래 등에서의 소비자보호에 관한 법률</법령명한글><법령구분명>법률</법령구분명><제개정구분명>일부개정</제개정구분명><공포일자>20260901</공포일자><시행일자>{soon}</시행일자><소관부처명>공정거래위원회</소관부처명><법령일련번호>999</법령일련번호><법령상세링크>/DRF/lawService.do?OC=oc-secret&amp;MST=999</법령상세링크></law>'
               f'<law id="2"><법령명한글>국방과학연구소법</법령명한글><시행일자>{soon}</시행일자></law></LawSearch>')
        detail = '<?xml version="1.0" encoding="UTF-8"?><법령><제개정이유><제개정이유내용>온라인 플랫폼에서 산 물건의 청약철회 기간을 7일로 정한다.</제개정이유내용></제개정이유></법령>'
        urls = []
        def fake(url, timeout=15):
            urls.append(url); return 200, (detail if 'lawService' in url else lst)
        with self.site.app.app_context():
            self.assertIn('LAW_OC', w['kind_ready']('law')[1])
            with patch.dict(os.environ, {'LAW_OC': 'oc-secret'}), patch.object(mod, 'http_get', fake):
                got = w['collect']('law')
        self.assertTrue(urls[0].startswith('http://www.law.go.kr/DRF/lawSearch.do?') and 'OC=oc-secret' in urls[0] and 'efYd=' in urls[0])
        laws = got['facts']['법령']
        self.assertEqual([l['법령'] for l in laws], ['전자상거래 등에서의 소비자보호에 관한 법률'])  # 소비자와 상관없는 법은 뺌
        self.assertEqual(laws[0]['시행일'], f'{soon[:4]}-{soon[4:6]}-{soon[6:]}'); self.assertIn('7일', laws[0]['개정 이유(원문 일부)'])
        self.assertNotIn('oc-secret', json.dumps(got, ensure_ascii=False))  # 인증키는 자료·출처에 안 남음
        self.assertEqual(got['sources'][0]['url'], 'https://www.law.go.kr/법령/전자상거래 등에서의 소비자보호에 관한 법률')
    # ---- AI 소비자 상담 새 버전 (lawrag.py · lawsync.py) ----
    APPX_PDF = [['법제처 1 국가법령정보센터', '[별표 Ⅱ] 품목별 해결기준(제3조 관련)', '[시행 2025. 12. 18.]', '1. 체육시설업(헬스장, 필라테스)',
                 [(30, '분쟁유형'), (260, '해결기준'), (470, '비고')],
                 [(30, '1) 사업자의 귀책사유로'), (260, '- 계약해제 및 이용료 환급')],
                 [(30, '계약을 해제하는 경우'), (260, '- 남은 기간 이용료 전액 환급')],
                 [(30, '2) 소비자의 사정으로 중도'), (260, '- 이용일수에 해당하는 금액과'), (470, '개시일 기준')],
                 [(30, '해지하는 경우'), (260, '총 이용금액의 10% 공제 후 환급')]],
                ['법제처 2 국가법령정보센터', '2. 외식업', [(30, '분쟁유형'), (260, '해결기준'), (470, '비고')], [(30, '1) 음식물에 이물 혼입'), (260, '- 제품 교환 또는 구입가 환급')]]]

    @staticmethod
    def fake_vec(text):
        """가짜 임베딩: 두 글자 묶음을 512칸에 흩뿌림 (같은 낱말이 많으면 가까움)"""
        import hashlib as _h
        v = [0.0] * 512
        for w in re.findall(r'[가-힣]+', text):
            for i in range(len(w) - 1): v[int(_h.md5(w[i:i + 2].encode()).hexdigest(), 16) % 512] += 1
        return v

    def rag_fake(self, sent, answer=None, status=200):
        """OpenAI 대신: 임베딩은 fake_vec, 상담 답은 answer(후보 id 목록) -> dict. 보낸 몸통은 sent에 쌓음."""
        def fake(url, headers, body, timeout):
            sent.append((url, body))
            if url.endswith('/embeddings'):
                return 200, {'data': [{'index': i, 'embedding': self.fake_vec(x)} for i, x in enumerate(body['input'])], 'usage': {'total_tokens': 10 * len(body['input'])}}
            if '법률 안내 도우미' in body['messages'][0]['content']:  # 예전 버전(lawask)
                return 200, {'choices': [{'message': {'content': json.dumps({'headline': '예전 답', 'paragraphs': ['예전 버전 설명이에요.'], 'refs': [], 'covered': True}, ensure_ascii=False)}}]}
            if status != 200: return status, {'error': {'message': 'busy sk-test-key'}}
            ids = re.findall(r'^\[(c\d+)\] ', body['messages'][-1]['content'], re.M)
            out = answer(ids) if answer else {'need_more': False, 'questions': [], 'refs': ids[:2], 'covered': True,
                                              'parts': [{'name': '핵심 결론', 'text': f'남은 기간 이용료를 돌려받을 수 있는 경우가 많아요 [{ids[0]}].'}]}
            return 200, {'model': 'answer-model-test', 'usage': {'prompt_tokens': 1200, 'completion_tokens': 300},
                         'choices': [{'message': {'content': json.dumps(out, ensure_ascii=False)}}]}
        return fake

    def rag_setup(self, on=True):
        self.ask_setup()
        rag = self.site.app.extensions['lawrag']
        rag['set_v2'](on)
        def clean():
            rag['set_v2'](False)
            st = rag['store']
            for p in (st.synced, st.status, st.appendix, st.emb_index, st.emb_vec, st.learned, st.api_use):
                if p.exists(): p.unlink()
            rag['corpus'].reset()
            with self.site.conn() as db: db.execute('DELETE FROM ask_logs')
        self.addCleanup(clean)
        return rag

    def rag_appendix(self, rag):
        import lawsync
        x = lawsync.parse_appendix(lawsync.pdf_layout_text(self.make_pdf(self.APPX_PDF)))
        x.update(doc='소비자분쟁해결기준 [별표 Ⅱ]', file='별표2.pdf', added='2026-10-16T10:00:00')
        lawsync.save_appendix(rag['store'], [x])

    def ask2(self, client, q, **extra):
        return client.post('/ask', data={'_csrf': self.csrf(client, '/ask'), 'q': q, **extra})

    def test_ask_v2_switch_off_keeps_old_screen(self):
        self.rag_setup(on=False)
        page = self.client.get('/ask').get_data(as_text=True)
        self.assertIn('소비자 법률, 편하게 물어보세요', page); self.assertNotIn('상담사가 아닌 AI가', page)
        self.assertIn('>법률 질문</a>', page); self.assertNotIn('>AI 소비자 상담</a>', page)
        self.assertNotIn('상담사가 아닌 AI가', self.client.get('/ask?v=2').get_data(as_text=True))  # 손님은 ?v=2로도 못 봄
        sent = []
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(self.site.companydesk, 'post_json', self.rag_fake(sent)):
            html = self.ask(self.client, '온라인에서 산 옷 7일 지나서 환불 되나요?').get_data(as_text=True)
        self.assertIn('예전 답', html)  # 예전 질문창이 그대로 답함
        self.assertEqual([u for u, _ in sent], ['https://api.openai.com/v1/chat/completions'])  # 임베딩도 안 부름
        with self.site.conn() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM ask_logs').fetchone()[0], 0)  # 새 기록도 안 남김
        # 관리자가 켜면 새 화면, 끄면 다시 예전 화면
        admin = self.login_admin()
        self.assertIn('상담사가 아닌 AI가', admin.get('/ask?v=2').get_data(as_text=True))  # 관리자 미리 보기
        tok = self.csrf(admin, '/admin/ask')
        admin.post('/admin/ask', data={'_csrf': tok, 'act': 'switch', 'on': '1'})
        page = self.client.get('/ask').get_data(as_text=True)
        self.assertIn('상담사가 아닌 AI가 제공하는 일반 정보예요', page); self.assertIn('>AI 소비자 상담</a>', page)
        admin.post('/admin/ask', data={'_csrf': tok, 'act': 'switch', 'on': '0'})
        self.assertEqual(self.client.get('/ask').get_data(as_text=True).count('소비자 법률, 편하게 물어보세요'), 1)
        with self.site.conn() as db: db.execute("INSERT OR REPLACE INTO site_content(key,value,updated) VALUES('ask.off','끔','x')")
        self.site.app.extensions['lawrag']['set_v2'](True)
        self.assertEqual(self.client.get('/ask').status_code, 404)  # 질문창 끄기는 새 버전에도

    def test_ask_v2_answer_masks_personal_info_and_checks_sources(self):
        rag = self.rag_setup(); self.rag_appendix(rag)
        sent = []
        def answer(ids):
            return {'need_more': False, 'questions': [], 'covered': True, 'refs': [ids[0], 'c99', 'ecom:제17조'],
                    'parts': [{'name': '핵심 결론', 'text': f'남은 기간 이용료를 돌려받을 수 있는 경우가 많아요 [{ids[0]}]. 대법원 2021다98765 판결도 같은 취지예요. 위약금은 77만 원까지만 내면 돼요.'},
                              {'name': '관련 법령', 'text': f'분쟁해결기준은 총 이용금액의 10% 공제 후 환급을 권고해요 [{ids[0]}]. 민법 제999조에 따라 해지할 수 있어요. [c77] 참고'},
                              {'name': '대응 절차', 'text': '- 문자로 해지를 요청해요. 담당 010-5555-6666\n- 답이 없으면 1372에 상담해요.'},
                              {'name': '이상한 부분', 'text': '빼야 해요'}]}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(self.site.companydesk, 'post_json', self.rag_fake(sent, answer)):
            rag['build_embeddings']()
            sent.clear()
            q = '헬스장 6개월권을 두 달 쓰고 중도 해지하면 환불되나요? 제 이름은 홍길동이고 010-9876-5432, hong@example.com 이에요. 김철수 매니저가 안 된대요'
            r = self.ask2(self.client, q)
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        dump = json.dumps([b for _, b in sent], ensure_ascii=False)
        for secret in ('010-9876-5432', 'hong@example.com', '홍길동', '김철수', 'sk-test-key'): self.assertNotIn(secret, dump)  # AI에는 개인정보 없이
        chat = [b for u, b in sent if u.endswith('/chat/completions')][-1]
        self.assertNotIn('tools', chat); self.assertEqual(chat['model'], self.site.companydesk.ai_model())  # 검색 없이, 답 모델은 그대로
        self.assertIn('[근거 후보]', chat['messages'][-1]['content']); self.assertIn('(분쟁해결기준(권고))', chat['messages'][-1]['content'])
        self.assertIn('체육시설업', chat['messages'][-1]['content'])  # 유형에 맞는 별표 줄을 후보로
        # 코드 확인: 지어낸 사건번호·금액·조항 문장, 후보에 없는 출처는 빠짐
        for bad in ('2021다98765', '77만', '제999조', '[c77]', '이상한 부분', '빼야 해요', '010-5555-6666'): self.assertNotIn(bad, html)
        self.assertIn('남은 기간 이용료를 돌려받을 수 있는 경우가 많아요', html); self.assertIn('10% 공제 후 환급', html)
        self.assertIn('근거 원문에서 확인되지 않은 내용은 빼고', html)
        docs = re.findall(r'class="sbv-doc">([^<]+)', html)
        self.assertEqual(docs, ['소비자분쟁해결기준 [별표 Ⅱ]'])  # 출처 카드는 넘겨준 후보 중 쓴 것만
        self.assertIn('분쟁해결기준(권고)', html); self.assertIn('PDF 1쪽', html); self.assertIn('현행 여부 미확인', html); self.assertIn('시행 2025.12.18', html)
        self.assertEqual(html.count('상담사가 아닌 AI가 제공하는 일반 정보예요'), 3)  # 맨 위 + 답마다 + 복사 글
        self.assertIn('data-copy', html); self.assertIn('업체와의 협의가 어려우신가요?', html)
        # 제보로 자동으로 넘기지 않음: 링크만, 채워 넣는 값 없음
        self.assertIn('href="/report"', html); self.assertNotRegex(html, r'href="/report\?')
        with self.client.session_transaction() as sess:
            self.assertNotIn('헬스장', json.dumps(dict(sess), ensure_ascii=False))
        self.assertNotIn('6개월권을 두 달', self.client.get('/report').get_data(as_text=True))
        with self.site.conn() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cases WHERE description LIKE '%헬스장%'").fetchone()[0], 0)
            row = db.execute("SELECT * FROM ask_logs WHERE kind='ask'").fetchone()
        self.assertNotIn('010-9876-5432', row['question']); self.assertNotIn('홍길동', row['question']); self.assertIn('헬스장', row['question'])
        self.assertEqual(row['status'], 'ok'); self.assertEqual(row['dtype'], '구독·서비스 계약'); self.assertEqual((row['tokens_in'], row['tokens_out']), (1200, 300))
        kinds = {f['type'] for f in json.loads(row['flags'])}; self.assertTrue({'case', 'amount', 'law', 'source'} <= kinds)
        # 이어 묻기: 앞 대화(지운 것)를 최근 6턴까지 같이 보냄
        hist = re.search(r'name="history" value="([^"]*)"', html)[1]
        import html as _html
        hist = json.loads(_html.unescape(hist)); self.assertEqual(len(hist), 1); self.assertNotIn('010-9876-5432', hist[0]['q'])
        long_hist = json.dumps(hist * 5 + [{'q': '전화 010-1111-2222로 주세요', 'a': '네'}], ensure_ascii=False)
        sent.clear()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(self.site.companydesk, 'post_json', self.rag_fake(sent)):
            html2 = self.ask2(self.client, '계약은 6개월에 60만 원이었어요', history=long_hist, conv='conv12345').get_data(as_text=True)
        chat = [b for u, b in sent if u.endswith('/chat/completions')][-1]
        self.assertEqual(len(chat['messages']), 1 + 6 + 1)  # 시스템 + 최근 6턴 + 이번 질문
        self.assertNotIn('010-1111-2222', json.dumps(chat, ensure_ascii=False))
        self.assertEqual(html2.count('class="sbv-a sbv-old"'), 3)

    def test_ask_v2_sale_channel_scope(self):
        # 유튜브 구독(온라인)에 방문판매법 방문판매·전화권유·다단계 조항(제5~29조)을 쓰지 않음. 계속거래(제30~34조)는 남김
        import lawrag
        self.assertEqual(lawrag.channel_of('유튜브 프리미엄 구독 해지 위약금'), 'online')
        self.assertEqual(lawrag.channel_of('집으로 찾아온 판매원에게 산 학습지'), 'door')
        self.assertEqual(lawrag.channel_of('헬스장 6개월권 해지'), '')
        self.assertTrue(lawrag.out_of_scope('online', 'door', '제7조')); self.assertTrue(lawrag.out_of_scope('online', 'door', '제8조'))
        self.assertFalse(lawrag.out_of_scope('online', 'door', '제32조')); self.assertFalse(lawrag.out_of_scope('door', 'door', '제8조'))
        self.assertFalse(lawrag.out_of_scope('', 'door', '제7조'))
        q = '유튜브 프리미엄 구독을 중도 해지하려는데 위약금이 있나요?'
        self.assertEqual(lawrag.grade(q, ['door:제7조', 'ecom:제17조'])[0], False)
        self.assertEqual(lawrag.grade(q, ['ecom:제17조']), (True, '맞음'))
        self.assertIn('[적용 범위]', lawrag.SYSTEM)

    def test_ask_v2_verify_drops_invented_content(self):
        import lawrag
        cards = [{'id': 'c1', 'ref': 'ecom:제17조', 'art': '제17조', 'short': '전자상거래법', 'law': '전자상거래 등에서의 소비자보호에 관한 법률', 'title': '청약철회등',
                  'text': '소비자는 재화등을 공급받은 날부터 7일 이내에 청약철회등을 할 수 있다. 위약금 10만원'}]
        out = {'parts': [{'name': '핵심 결론', 'text': '전자상거래법 제17조에 따라 7일 안에 반품할 수 있어요 [c1]. 전자상거래법 제18조에 따라 3일 안에 돌려줘야 해요.'},
                         {'name': '환불·보상 가능성', 'text': '위약금은 10만원이에요. 배상은 300만 원까지예요. 2019다1234 사건이 있어요.'},
                         {'name': '출처', 'text': '[c2] 참고 [c1]'}], 'refs': ['c1', 'c2', 'easylaw:1'], 'need_more': False}
        v = lawrag.verify(out, cards, '반품되나요')
        text = ' '.join(t for _, t in v['parts'])
        self.assertIn('제17조', text); self.assertIn('10만원', text)
        for bad in ('제18조', '300만', '2019다1234', '[c2]'): self.assertNotIn(bad, text)
        self.assertEqual(v['refs'], ['c1'])
        self.assertEqual({f['type'] for f in v['flags']}, {'law', 'amount', 'case', 'source'})
        with self.assertRaises(ValueError): lawrag.verify({'parts': [{'name': '핵심 결론', 'text': '민법 제1조에 따라 됩니다.'}]}, cards, 'q')
        ask = lawrag.verify({'need_more': True, 'questions': ['언제 받으셨나요?'], 'parts': []}, cards, 'q')
        self.assertTrue(ask['need_more']); self.assertEqual(ask['questions'], ['언제 받으셨나요?'])

    def test_ask_v2_no_law_and_follow_up_question(self):
        import lawsync
        rag = self.rag_setup()
        # 저장소 별표에는 '치수(사이즈)' 줄이 있어서, 법령이 없는 길만 보려고 잠깐 뺌
        rc = rag['corpus']; keep = list(rc.EXTRA); rc.EXTRA[:] = [p for p in keep if p not in lawsync.BUNDLED]; rc.reset()
        self.addCleanup(lambda: (rc.EXTRA.__setitem__(slice(None), keep), rc.reset()))
        sent = []
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(self.site.companydesk, 'post_json', self.rag_fake(sent)):
            html = self.ask2(self.client, '사이즈 추천해 주세요 감사합니다').get_data(as_text=True)
        self.assertIn('관련 법령을 찾지 못했어요', html); self.assertIn('1372 소비자상담센터', html); self.assertIn('일반적인 대응 순서', html)
        self.assertFalse([u for u, _ in sent if u.endswith('/chat/completions')])  # 법적 결론을 만들지 않게 AI도 안 부름
        ask = lambda ids: {'need_more': True, 'questions': ['물건을 받은 날이 언제인가요?', '판매자가 뭐라고 답했나요?'], 'parts': [], 'refs': []}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(self.site.companydesk, 'post_json', self.rag_fake(sent, ask)):
            html = self.ask2(self.client, '온라인에서 산 옷 환불 되나요?').get_data(as_text=True)
        self.assertIn('정확히 답하려면 몇 가지가 더 필요해요', html); self.assertIn('물건을 받은 날이 언제인가요?', html)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(self.site.companydesk, 'post_json', self.rag_fake(sent, status=500)):
            html = self.ask2(self.client, '온라인에서 산 옷 환불 되나요?').get_data(as_text=True)
        self.assertIn('질문과 가까운 근거 원문을 찾았어요', html); self.assertNotIn('sk-test-key', html)
        with self.site.conn() as db:
            self.assertEqual([r[0] for r in db.execute("SELECT status FROM ask_logs WHERE kind='ask' ORDER BY id")], ['no_law', 'ask_more', 'error'])
            self.assertNotIn('sk-test-key', ' '.join(r[0] for r in db.execute('SELECT error FROM ask_logs')))

    def test_ask_logs_only_top_admin_and_kept_30_days(self):
        rag = self.rag_setup()
        sent = []
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(self.site.companydesk, 'post_json', self.rag_fake(sent)):
            self.ask2(self.client, '온라인에서 산 옷 7일 지나서 환불 되나요? 010-3333-4444')
        with self.site.conn() as db:
            log_id = db.execute("SELECT id FROM ask_logs WHERE kind='ask'").fetchone()[0]
            old = (datetime.datetime.now() - datetime.timedelta(days=31)).isoformat(timespec='seconds')
            db.execute("INSERT INTO ask_logs(kind,created,question,status) VALUES('ask',?,'오래된 상담','ok')", (old,))
        # 손님·기자 계정은 못 봄
        self.assertIn('/admin/login', self.client.get('/admin/ask').headers['Location'])
        self.assertIn('/admin/login', self.client.get(f'/admin/ask/logs/{log_id}').headers['Location'])
        admin = self.login_admin()
        admin.post('/admin/staff', data={'_csrf': self.csrf(admin, '/admin/staff'), 'action': 'add', 'name': '박기자', 'login_id': 'askreporter', 'password': 'staffpass9'})
        staff = self.site.app.test_client()
        self.post_form(staff, '/reporter/login', {'login_id': 'askreporter', 'password': 'staffpass9'})
        self.assertIn('기자실', staff.get('/reporter').get_data(as_text=True))
        for path in ('/admin/ask', f'/admin/ask/logs/{log_id}', '/admin/ask/lab'):
            r = staff.get(path); self.assertEqual(r.status_code, 302); self.assertIn('/admin/login', r.headers['Location'])
        dash = admin.get('/admin/ask').get_data(as_text=True)
        self.assertIn('AI 상담 새 버전', dash); self.assertIn('상담 수', dash); self.assertIn('예상 비용', dash); self.assertIn('온라인 쇼핑', dash)
        self.assertNotIn('7일 지나서 환불', dash)  # 질문 글은 기록을 열 때만
        with self.site.conn() as db: self.assertEqual(db.execute("SELECT COUNT(*) FROM ask_logs WHERE question='오래된 상담'").fetchone()[0], 0)  # 30일 지난 기록은 지움
        page = admin.get(f'/admin/ask/logs/{log_id}').get_data(as_text=True)
        self.assertIn('7일 지나서 환불', page); self.assertNotIn('010-3333-4444', page); self.assertIn('열람 기록', page)
        admin.get(f'/admin/ask/logs/{log_id}')
        with self.site.conn() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ask_logs WHERE kind='view' AND target=?", (log_id,)).fetchone()[0], 2)  # 볼 때마다 남김
        self.assertIn('AI 상담', admin.get('/admin').get_data(as_text=True))  # 관리자 메뉴

    def test_ask_v2_quality_test_lab_and_embedding_cache(self):
        import lawrag
        rag = self.rag_setup(on=False)
        admin = self.login_admin(); tok = self.csrf(admin, '/admin/ask')
        sent = []
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(self.site.companydesk, 'post_json', self.rag_fake(sent)), patch.object(lawrag.threading, 'Thread', self.NowThread):
            admin.post('/admin/ask', data={'_csrf': tok, 'act': 'embed'})
            n_emb = len([u for u, _ in sent if u.endswith('/embeddings')]); self.assertGreater(n_emb, 0)
            total = len(rag['docs']()); self.assertEqual(len(rag['emb'].load().index), total)
            sent.clear(); admin.post('/admin/ask', data={'_csrf': tok, 'act': 'embed'})
            self.assertEqual([u for u, _ in sent if u.endswith('/embeddings')], [])  # 한 번 만든 건 다시 안 만듦
            self.rag_appendix(rag); admin.post('/admin/ask', data={'_csrf': tok, 'act': 'embed'})
            emb_calls = [b for u, b in sent if u.endswith('/embeddings')]
            self.assertEqual(sum(len(b['input']) for b in emb_calls), 3)  # 바뀐(새) 별표 3줄만
            sent.clear()
            admin.post('/admin/ask', data={'_csrf': tok, 'act': 'test'})
            dash = admin.get('/admin/ask').get_data(as_text=True)
            lab = admin.post('/admin/ask/lab', data={'_csrf': self.csrf(admin, '/admin/ask/lab'), 'q': '온라인에서 산 옷 7일 지나서 환불 되나요?'}).get_data(as_text=True)
        with self.site.conn() as db:
            rows = db.execute("SELECT * FROM ask_logs WHERE kind='test'").fetchall()
        self.assertEqual(len(rows), len(lawrag.TEST_QUESTIONS)); self.assertEqual(len(rows), 22)
        self.assertIn('배달 음식에서 바퀴벌레', dash); self.assertIn('품질 시험', dash); self.assertIn('ak-yes', dash)
        self.assertTrue(any(json.loads(r['parts']) == ['핵심 결론'] for r in rows))
        self.assertIn('예전 답', lab); self.assertIn('AI 소비자 상담', lab); self.assertIn('남은 기간 이용료', lab)
        self.assertIn('상담사가 아닌 AI가', admin.get('/ask?v=2').get_data(as_text=True))
        self.assertNotIn('상담사가 아닌 AI가', self.client.get('/ask').get_data(as_text=True))  # 실험해도 손님 화면은 예전 그대로

    def test_appendix_upload_and_law_sync(self):
        import lawsync
        rag = self.rag_setup()
        admin = self.login_admin(); tok = self.csrf(admin, '/admin/laws')
        page = admin.get('/admin/laws').get_data(as_text=True)
        self.assertIn('소비자분쟁해결기준 별표 PDF 올리기', page); self.assertIn('현행 여부', page); self.assertIn('현행 여부 미확인', page)
        r = admin.post('/admin/laws', data={'_csrf': tok, 'act': 'appendix_preview', 'pdf': (io.BytesIO(self.make_pdf(self.LAW_PDF_LINES)), '법.pdf')}, content_type='multipart/form-data', follow_redirects=True)
        self.assertIn('분쟁유형', r.get_data(as_text=True))  # 별표가 아니면 거절
        if __import__('shutil').which('pdftotext'):
            r = admin.post('/admin/laws', data={'_csrf': tok, 'act': 'appendix_preview', 'pdf': (io.BytesIO(self.make_pdf(self.APPX_PDF)), '별표2.pdf')}, content_type='multipart/form-data', follow_redirects=True)
            html = r.get_data(as_text=True)
            self.assertIn('별표 미리 보기', html); self.assertIn('3줄', html); self.assertIn('체육시설업', html); self.assertIn('2025-12-18', html)
            token = re.search(r'name="act" value="appendix_save"><input type="hidden" name="token" value="([^"]+)"', html)[1]
            r = admin.post('/admin/laws', data={'_csrf': tok, 'act': 'appendix_save', 'token': token, 'doc_0': '소비자분쟁해결기준 [별표 Ⅱ]', 'eff_0': '2025-12-18'}, follow_redirects=True)
            self.assertIn('별표를 배웠어요', r.get_data(as_text=True)); self.assertIn('배운 별표', r.get_data(as_text=True))
            laws = rag['corpus'].laws(); appx = next(l for l in laws if l['key'] == 'kca_appx')
            self.assertEqual(appx['count'], 3)
            art = rag['corpus']._load()['laws']['kca_appx']['articles']['별표Ⅱ-2']
            self.assertEqual((art['item'], art['page'], art['appendix']), ('체육시설업(헬스장, 필라테스)', 1, '별표 Ⅱ'))
            self.assertIn('총 이용금액의 10% 공제 후 환급', art['text'])
            self.assertNotIn('kca_appx', [l['key'] for l in self.site.triage.corpus.laws()])  # AI 제보 분류의 모음·검색은 그대로
        # 국가법령정보 Open API (가짜 응답)
        search = ('<LawSearch><totalCnt>1</totalCnt><law id="1"><법령일련번호>270001</법령일련번호><법령명한글>할부거래에 관한 법률</법령명한글>'
                  '<법령ID>001234</법령ID><시행일자>20260301</시행일자><법령구분명>법률</법령구분명></law></LawSearch>')
        adm = ('<AdmRulSearch><totalCnt>1</totalCnt><admrul id="1"><행정규칙일련번호>99</행정규칙일련번호><행정규칙명>소비자분쟁해결기준</행정규칙명>'
               '<시행일자>20260101</시행일자></admrul></AdmRulSearch>')
        service = ('<법령><기본정보><법령명_한글>할부거래에 관한 법률</법령명_한글><시행일자>20260301</시행일자><공포일자>20250901</공포일자><공포번호>21000</공포번호>'
                   '<법종구분>법률</법종구분></기본정보><조문><조문단위><조문번호>1</조문번호><조문여부>전문</조문여부><조문내용>제1장 총칙</조문내용></조문단위>'
                   '<조문단위><조문번호>1</조문번호><조문여부>조문</조문여부><조문제목>목적</조문제목><조문내용>제1조(목적) 이 법은 할부거래를 공정하게 한다.</조문내용></조문단위>'
                   '<조문단위><조문번호>8</조문번호><조문여부>조문</조문여부><조문제목>청약의 철회</조문제목><조문내용>제8조(청약의 철회)</조문내용>'
                   '<항><항번호>①</항번호><항내용>① 소비자는 계약서를 받은 날부터 7일 이내에 할부계약에 관한 청약을 철회할 수 있다. &lt;개정 2016. 3. 29.&gt;</항내용>'
                   '<호><호내용>1. 계약서를 받은 날</호내용></호></항></조문단위></조문></법령>')
        urls = []
        def get(url, timeout=25):
            urls.append(url)
            if 'lawSearch.do' in url and 'target=admrul' in url: return 200, adm
            if 'lawSearch.do' in url: return 200, search if '%ED%95%A0%EB%B6%80' in url else '<LawSearch><totalCnt>0</totalCnt></LawSearch>'
            if 'lawService.do' in url and 'MST=270001' in url: return 200, service
            return 200, 'error OC=test-oc-123 not allowed'
        st = rag['store']
        st.write(st.extra, {'u1234abcd': {'key': 'u1234abcd', 'name': '할부거래에 관한 법률', 'short': '할부거래법', 'kind': '법률', 'no': '1', 'effective': '2026-01-02', 'promulgated': '',
                                          'source': 'https://www.law.go.kr/법령/할부거래에관한법률', 'articles': {'제2조': {'title': '청약철회', 'text': '옛 조문'}}}})
        env = {k: v for k, v in os.environ.items() if k != 'LAW_OC'}
        with patch.dict(os.environ, env, clear=True):
            self.assertIn('LAW_OC', admin.post('/admin/ask', data={'_csrf': self.csrf(admin, '/admin/ask'), 'act': 'sync'}, follow_redirects=True).get_data(as_text=True))
        logs = []
        with patch.dict(os.environ, {'LAW_OC': 'test-oc-123'}), patch.object(lawsync, 'http_get', get):
            rows = lawsync.sync(st, laws=[('installment', '할부거래에 관한 법률', '할부거래법', 'law'), ('kca', '소비자분쟁해결기준', '소비자분쟁해결기준', 'admrul'),
                                          ('pl', '제조물 책임법', '제조물책임법', 'law')], log=logs.append)
            again = lawsync.sync(st, laws=[('installment', '할부거래에 관한 법률', '할부거래법', 'law')], log=logs.append)
        self.assertEqual([r['ok'] for r in rows], [True, True, False]); self.assertTrue(rows[0]['changed']); self.assertFalse(again[0]['changed'])
        self.assertTrue(all('OC=test-oc-123' in u and u.startswith('http://www.law.go.kr/DRF/') for u in urls))
        self.assertNotIn('test-oc-123', json.dumps(rows, ensure_ascii=False) + ' '.join(logs) + st.status.read_text(encoding='utf-8'))  # 키는 기록에 안 남김
        synced = json.loads(st.synced.read_text(encoding='utf-8'))['installment']
        self.assertEqual(list(synced['articles']), ['제1조', '제8조']); self.assertEqual(synced['effective'], '2026-03-01')
        self.assertEqual(synced['articles']['제8조']['text'], '① 소비자는 계약서를 받은 날부터 7일 이내에 할부계약에 관한 청약을 철회할 수 있다.\n1. 계약서를 받은 날')
        self.assertEqual([f['name'] for f in lawsync.pdf_flags(st)], ['할부거래에 관한 법률'])  # 올린 PDF는 옛 판
        rag['corpus'].reset()
        page = admin.get('/admin/laws').get_data(as_text=True)
        self.assertIn('개정됨, 확인 필요', page); self.assertIn('2026.03.01', page); self.assertNotIn('test-oc-123', page)
        hits = rag['corpus'].search('할부계약 청약 철회 7일')
        self.assertEqual(hits[0]['ref'], 'installment:제8조')  # 새 버전 모음은 받은 현행 원문
        self.assertNotIn('installment', [l['key'] for l in self.site.triage.corpus.laws()])
        dtype, cards, _ = rag['retrieve']('할부계약 청약 철회는 며칠 안에 하나요?')
        c = next(c for c in cards if c['ref'] == 'installment:제8조')
        self.assertEqual((c['status'], c['label'], c['effective']), ('현행', '법률 조문', '2026-03-01'))
        if __import__('shutil').which('pdftotext'):
            self.assertIn('개정됨, 확인 필요', page)  # 별표(2025-12-18)도 현행 고시(2026-01-01)보다 옛 판

    def test_ask_v2_finds_other_laws_from_law_api(self):
        import lawsync
        rag = self.rag_setup(); st = rag['store']
        # 저장소 별표에는 반려동물 기준이 있어서, API로 다른 법을 찾는 길만 따로 보려고 잠깐 뺌
        rc = rag['corpus']; keep = list(rc.EXTRA); rc.EXTRA[:] = [p for p in keep if p not in lawsync.BUNDLED]; rc.reset()
        self.addCleanup(lambda: (rc.EXTRA.__setitem__(slice(None), keep), rc.reset()))
        q = '분양받은 반려견이 일주일 만에 파보장염으로 죽었어요. 분양업자에게 뭘 요구할 수 있나요?'
        self.assertTrue(rag['retrieve'](q, api=False)[2]['weak'])  # 모아 둔 법으로는 약하게만 맞음
        found = ('<LawSearch><totalCnt>2</totalCnt>'
                 '<law id="1"><법령일련번호>5001</법령일련번호><법령명한글>동물보호법</법령명한글><법령ID>0101</법령ID><시행일자>20260201</시행일자><법령구분명>법률</법령구분명></law>'
                 '<law id="2"><법령일련번호>5002</법령일련번호><법령명한글>수의사법</법령명한글><법령ID>0102</법령ID><시행일자>20260101</시행일자><법령구분명>법률</법령구분명></law>'
                 '<law id="3"><법령일련번호>5003</법령일련번호><법령명한글>서울특별시 동물 조례</법령명한글><법령구분명>조례</법령구분명></law></LawSearch>')
        def law(mst, name, title, text):
            return (f'<법령><기본정보><법령명_한글>{name}</법령명_한글><시행일자>20260201</시행일자><공포번호>1</공포번호><법종구분>법률</법종구분></기본정보><조문>'
                    f'<조문단위><조문번호>7</조문번호><조문여부>조문</조문여부><조문제목>{title}</조문제목><조문내용>제7조({title}) {text}</조문내용></조문단위></조문></법령>')
        urls = []
        def get(url, timeout=25):
            urls.append((url, timeout))
            if 'lawSearch.do' in url: return 200, found
            if 'MST=5001' in url: return 200, law(5001, '동물보호법', '반려견 분양', '분양업자는 분양받은 반려견이 파보장염 등 질병으로 죽은 경우 같은 종으로 교환하거나 분양가를 돌려주어야 한다.')
            if 'MST=5002' in url: return 200, law(5002, '수의사법', '면허', '수의사가 되려면 농림축산식품부장관의 면허를 받아야 한다.')
            return 404, ''
        sent = []
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key', 'LAW_OC': 'oc-key-777'}), patch.object(lawsync, 'http_get', get), \
             patch.object(self.site.companydesk, 'post_json', self.rag_fake(sent)):
            html = self.ask2(self.client, q).get_data(as_text=True)
        self.assertIn('동물보호법', html)  # 법제처에서 찾은 조문으로 답함
        self.assertTrue(all(t <= lawsync.API_TIMEOUT for _, t in urls)); self.assertIn('search=2', urls[0][0])
        self.assertNotIn('%EB%B0%98%EB%A0%A4%EA%B2%AC%EC%9D%B4', urls[0][0].split('query=')[0])
        self.assertEqual(len([u for u, _ in urls if 'lawService.do' in u]), 2)  # 조례는 받지 않음
        learned = json.loads(st.learned.read_text(encoding='utf-8'))
        self.assertEqual([x['name'] for x in learned.values()], ['동물보호법'])  # 답에 쓴 법만 모아 둠
        self.assertNotIn('수의사법', st.synced.read_text(encoding='utf-8'))
        self.assertIn(('동물보호법', '동물보호법', 'law'), [x[1:] for x in lawsync.all_laws(st)])  # 다음부터 매일 받음
        with self.site.conn() as db:
            row = db.execute("SELECT answer, error FROM ask_logs WHERE kind='ask'").fetchone()
        self.assertEqual(json.loads(row[0])['api'], ['동물보호법']); self.assertNotIn('oc-key-777', ' '.join(map(str, row)) + st.api_use.read_text(encoding='utf-8'))
        # 두 번째는 모아 둔 법에서 바로 찾아 법제처를 다시 부르지 않음
        urls.clear()
        with patch.dict(os.environ, {'LAW_OC': 'oc-key-777'}), patch.object(lawsync, 'http_get', get):
            _, cards, info = rag['retrieve'](q)
        self.assertFalse(urls); self.assertIn('동물보호법', [c['law'] for c in cards])
        # 찾아도 쓸 만한 법이 없으면 하루 동안 같은 낱말로 다시 찾지 않고, 하루 한도를 넘지 않음
        urls.clear(); q2 = '우주정거장 관광 상품을 샀는데 발사가 미뤄졌어요'
        with patch.dict(os.environ, {'LAW_OC': 'oc-key-777'}), patch.object(lawsync, 'http_get', lambda u, t=25: (urls.append((u, t)), (200, '<LawSearch><totalCnt>0</totalCnt></LawSearch>'))[1]):
            rag['retrieve'](q2); n = len(urls); rag['retrieve'](q2)
            self.assertEqual(len(urls), n)
            with patch.object(lawsync, 'API_PER_DAY', 0):
                urls.clear(); rag['retrieve']('전혀 다른 질문인 열기구 체험 예약 취소')
            self.assertFalse(urls)
        # 관리자 화면에 '질문으로 찾음'으로 보이고, 뺄 수 있음
        admin = self.login_admin()
        if True:
            page = admin.get('/admin/laws').get_data(as_text=True)
            self.assertIn('질문으로 찾음', page); self.assertIn('동물보호법', page); self.assertNotIn('oc-key-777', page)
            key = next(iter(learned))
            admin.post('/admin/laws', data={'_csrf': self.csrf(admin, '/admin/laws'), 'act': 'appendix_forget', 'key': key})
            self.assertEqual(json.loads(st.learned.read_text(encoding='utf-8')), {}); self.assertNotIn('동물보호법', st.synced.read_text(encoding='utf-8'))

    # ---- 앱 포장 준비 (appready.py): 서비스 워커·앱 링크·차단·알림·푸시·Apple 로그인 ----
    def member_client(self, login_id, nickname):
        c = self.site.app.test_client()
        self.assertEqual(self.signup(c, login_id=login_id, nickname=nickname).status_code, 302)
        with self.site.conn() as db:
            return c, db.execute('SELECT id FROM users WHERE login_id=?', (login_id,)).fetchone()[0]

    def test_soboru_jobs(self):
        # 동네일자리: 사업자 인증 → 공고(최저임금·차별 문구 검사) → 찾기 필터 → 간편 지원(동의) → 지원자 관리, 신고 3번이면 가림, 외부 공고 수집·중복·마감
        J = self.site.soboru_jobs
        self.assertTrue(J.biz_no_ok('129-14-81596')); self.assertFalse(J.biz_no_ok('1234567890'))
        self.assertEqual(J.split_region('서울특별시 강남구 역삼동 1'), ('서울', '강남구', '역삼동')); self.assertEqual(J.parse_date('채용시까지 26-11-30'), '2026-11-30')
        self.assertTrue(J.bad_words('여자만 뽑아요')); self.assertTrue(J.bad_words('25세 이하')); self.assertFalse(J.bad_words('천여만 원 매출 가게'))
        self.assertEqual(self.client.get('/jobs').status_code, 200)
        boss, bid = self.member_client('job_boss', '빵집사장')
        self.assertIn('/jobs/biz', boss.get('/jobs/new').headers['Location'])
        self.assertEqual(self.post_form(boss, '/jobs/biz', {'biz_no': '1234567890', 'name': '소보루빵집', 'owner': '오사장', 'open_date': '2020-01-02', 'agree': '1'}).status_code, 400)
        with patch.dict(os.environ, {'NTS_API_KEY': ''}):
            self.assertEqual(self.post_form(boss, '/jobs/biz', {'biz_no': '129-14-81596', 'name': '소보루빵집', 'owner': '오사장', 'open_date': '2020-01-02', 'agree': '1'}).status_code, 302)
        with self.site.conn() as db: self.assertEqual(db.execute('SELECT state FROM jobs_biz WHERE user_id=?', (bid,)).fetchone()[0], 'pending')
        self.assertIn('/jobs/biz', boss.get('/jobs/new').headers['Location'])   # 승인 전에는 못 올림
        adm = self.login_admin()
        self.assertEqual(self.post_form(adm, '/admin/jobs', {'act': 'biz_ok', 'user': bid}).status_code, 302)
        form = {'title': '주말 오전 빵집 알바', 'industry': 'food', 'sido': '서울', 'sgg': '강남구', 'dong': '역삼동', 'term': 'long', 'days': ['토', '일'], 'start_t': '08:00', 'end_t': '13:00',
                'pay_type': '시급', 'pay': '9000', 'headcount': '1', 'body': '빵 포장과 계산을 해 주실 분을 찾아요. 처음이어도 괜찮아요.'}
        r = self.post_form(boss, '/jobs/new', form); self.assertEqual(r.status_code, 400); self.assertIn('최저임금', r.get_data(as_text=True))
        r = self.post_form(boss, '/jobs/new', dict(form, pay='12000', body='여자만 지원 가능해요. 빵 포장과 계산을 해 주실 분을 찾아요.')); self.assertEqual(r.status_code, 400)
        self.assertEqual(self.post_form(boss, '/jobs/new', dict(form, pay='12000')).status_code, 302)
        with self.site.conn() as db: jid = db.execute("SELECT id FROM jobs WHERE title='주말 오전 빵집 알바'").fetchone()[0]
        page = self.client.get(f'/jobs/{jid}').get_data(as_text=True)  # 구글 채용 검색용 구조화 데이터
        self.assertIn('"@type": "JobPosting"', page); self.assertIn('"unitText": "HOUR"', page)
        self.assertIn('주말 오전 빵집 알바', self.client.get('/jobs?sido=서울&sgg=강남구&days=weekend&time=morning&wage=11000').get_data(as_text=True))
        self.assertNotIn('주말 오전 빵집 알바', self.client.get('/jobs?sido=서울&sgg=강남구&time=evening').get_data(as_text=True).split('<main')[1])
        self.assertNotIn('주말 오전 빵집 알바', self.client.get('/jobs?sido=부산').get_data(as_text=True).split('<main')[1])
        # 지원: 동의 없으면 안 됨, 사장님만 연락처를 봄
        seek, sid = self.member_client('job_seek', '알바구함')
        self.assertEqual(self.post_form(seek, f'/jobs/{jid}/apply', {'name': '김구직', 'phone': '010-1234-5678', 'msg': '주말 가능해요'}).status_code, 400)
        self.assertEqual(self.post_form(seek, f'/jobs/{jid}/apply', {'name': '김구직', 'phone': '010-1234-5678', 'msg': '주말 가능해요', 'agree': '1'}).status_code, 302)
        self.assertIn('010-1234-5678', boss.get(f'/jobs/{jid}/applicants').get_data(as_text=True))
        self.assertEqual(seek.get(f'/jobs/{jid}/applicants').status_code, 403)
        self.assertNotIn('01012345678', self.client.get(f'/jobs/{jid}').get_data(as_text=True))
        with self.site.conn() as db: aid = db.execute('SELECT id FROM jobs_apps WHERE job_id=?', (jid,)).fetchone()[0]
        boss.post(f'/jobs/{jid}/applicants', data={'_csrf': self.csrf(boss, f'/jobs/{jid}/applicants'), 'app': aid, 'state': 'contact'})
        self.assertIn('연락함', seek.get('/jobs/my').get_data(as_text=True))
        seek.post(f'/jobs/{jid}/save', data={'_csrf': self.csrf(seek, f'/jobs/{jid}')}); self.assertIn('주말 오전 빵집 알바', seek.get('/jobs/my?t=saved').get_data(as_text=True))
        # 신고 3번이면 가림
        with self.site.conn() as db:   # 다른 회원 두 명이 이미 신고
            db.executemany("INSERT INTO jobs_reports(job_id,user_id,reason,created) VALUES(?,?,'허위·과장 공고','2026-01-01')", [(jid, 990001), (jid, 990002)])
            db.execute('UPDATE jobs SET reports=2 WHERE id=?', (jid,))
        seek.post(f'/jobs/{jid}/report', data={'_csrf': self.csrf(seek, f'/jobs/{jid}'), 'reason': '허위·과장 공고'})
        seek.post(f'/jobs/{jid}/report', data={'_csrf': self.csrf(boss, f'/jobs/{jid}'), 'reason': '허위·과장 공고'})
        self.assertEqual(adm.get(f'/jobs/{jid}').status_code, 200)   # 관리자는 봄
        self.assertEqual(seek.get(f'/jobs/{jid}').status_code, 404)
        # 외부 공고: 가짜 응답, 허용된 칸만, 중복·마감
        xml = ('<?xml version="1.0" encoding="UTF-8"?><wantedRoot><wanted><wantedAuthNo>K1</wantedAuthNo><company>소보루물류</company><title>상품 포장원</title><salTpNm>시급</salTpNm>'
               '<minSal>11000</minSal><region>서울 강남구</region><closeDt>채용시까지 99-12-31</closeDt><wantedInfoUrl>https://www.work24.go.kr/x?K1</wantedInfoUrl><contactTelNo>02-000-0000</contactTelNo></wanted>'
               '<wanted><wantedAuthNo>K2</wantedAuthNo><company>지난회사</company><title>마감된 공고</title><region>경기 수원시 장안구</region><closeDt>20-01-01</closeDt></wanted></wantedRoot>').encode()
        p = J.PROVIDER['work24']
        out = self.site.app.extensions['soboru_jobs']['sync'](fetcher=lambda prov, page: J.parse_items(prov, xml) if page == 1 else [])
        self.assertEqual(out['work24'][0], 2)
        self.site.app.extensions['soboru_jobs']['sync'](fetcher=lambda prov, page: J.parse_items(prov, xml) if page == 1 else [])
        with self.site.conn() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs WHERE src='work24'").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT status FROM jobs WHERE ext_id='K2'").fetchone()[0], 'closed')
            self.assertNotIn('02-000-0000', ' '.join(str(v) for v in db.execute("SELECT * FROM jobs WHERE ext_id='K1'").fetchone()))
        page = self.client.get('/jobs?src=ext').get_data(as_text=True)
        self.assertIn('상품 포장원', page); self.assertIn('고용24', page); self.assertNotIn('마감된 공고', page)
        self.assertIn('work24.go.kr', self.client.get('/jobs?q=상품 포장원').get_data(as_text=True) and self.client.get('/jobs/%d' % self._ext_id('K1')).get_data(as_text=True))
        self.assertIn('WORK24_API_KEY', adm.get('/admin/jobs').get_data(as_text=True))

    def test_soboru_town(self):
        # 우리 동네 정보: 회원만 올림, 동네·분류로 보기, 나도 추천해요(내 글은 안 됨), 이웃 한마디, 같은 이름 막기, 신고 3번이면 가림, 검색·관리자
        self.assertEqual(self.client.get('/town').status_code, 200)
        self.assertIn('/login', self.client.get('/town/new').headers['Location'])
        me, mid = self.member_client('town_me', '동네주민')
        form = {'sido': '서울', 'sgg': '강남구', 'dong': '논현동', 'cat': '병원·약국', 'name': '논현 바른소아과', 'tip': '선생님이 친절하고 토요일 오전에도 진료해요.', 'goods': ['친절해요', '주말에도 열어요']}
        self.assertEqual(self.post_form(me, '/town/new', dict(form, sgg='')).status_code, 400)
        self.assertEqual(self.post_form(me, '/town/new', dict(form, goods=['친절해요', '깨끗해요', '주차 돼요', '양이 많아요'])).status_code, 400)
        self.assertEqual(self.post_form(me, '/town/new', form).status_code, 302)
        self.assertEqual(self.post_form(me, '/town/new', form).status_code, 400)   # 같은 동네 같은 이름
        with self.site.conn() as db: pid = db.execute("SELECT id FROM town_places WHERE name='논현 바른소아과'").fetchone()[0]
        self.assertIn('논현 바른소아과', self.client.get('/town?sido=서울&sgg=강남구&c=병원·약국').get_data(as_text=True))
        self.assertNotIn('논현 바른소아과', self.client.get('/town?sido=부산').get_data(as_text=True).split('<main')[1])
        self.assertIn(f'href="/town/{pid}"', self.client.get('/search?q=소아과').get_data(as_text=True))
        xml = self.client.get('/sitemap.xml').get_data(as_text=True)  # 사이트맵에 동네 정보·새 화면
        for u in (f'/town/{pid}<', '/town<', '/feed<', '/tools/dict<', '/tools/calc/fitness<'): self.assertIn(u, xml)
        llms = self.client.get('/llms.txt')  # AI 검색용 사이트 안내
        self.assertEqual(llms.status_code, 200); self.assertIn('## 주요 화면', llms.get_data(as_text=True)); self.assertIn('/town)', llms.get_data(as_text=True))
        self.assertIn('"@type": "DefinedTermSet"', self.client.get('/tools/dict').get_data(as_text=True))
        me.post(f'/town/{pid}/like', data={'_csrf': self.csrf(me, f'/town/{pid}')})
        nb, nid = self.member_client('town_nb', '옆집')
        nb.post(f'/town/{pid}/like', data={'_csrf': self.csrf(nb, f'/town/{pid}')})
        nb.post(f'/town/{pid}/talk', data={'_csrf': self.csrf(nb, f'/town/{pid}'), 'body': '저도 다녀요. 주사도 안 아프게 놔 주세요.'})
        with self.site.conn() as db: self.assertEqual(tuple(db.execute('SELECT likes,talks FROM town_places WHERE id=?', (pid,)).fetchone()), (1, 1))
        self.assertIn('주사도 안 아프게', self.client.get(f'/town/{pid}').get_data(as_text=True))
        with self.site.conn() as db:
            db.executemany("INSERT INTO town_reports(place_id,user_id,reason,created) VALUES(?,?,'광고·홍보 글','2026-01-01')", [(pid, 990001), (pid, 990002)])
            db.execute('UPDATE town_places SET reports=2 WHERE id=?', (pid,))
        nb.post(f'/town/{pid}/report', data={'_csrf': self.csrf(nb, f'/town/{pid}'), 'reason': '광고·홍보 글'})
        self.assertEqual(self.client.get(f'/town/{pid}').status_code, 404)
        adm = self.login_admin()
        self.assertIn('논현 바른소아과', adm.get('/admin/town').get_data(as_text=True))
        self.post_form(adm, '/admin/town', {'act': 'show', 'place': pid})
        self.assertEqual(self.client.get(f'/town/{pid}').status_code, 200)

    def _ext_id(self, ext):
        with self.site.conn() as db: return db.execute('SELECT id FROM jobs WHERE ext_id=?', (ext,)).fetchone()[0]

    def test_soboru_site_search(self):
        # 통합 검색: 머리글 검색창, 한 화면에서 사전·매거진·커뮤니티 등을 같이 찾고 찾은 말에 형광펜
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('id="sb-sch"', home); self.assertIn('data-sch-open', home)
        page = self.client.get('/search?q=청약철회').get_data(as_text=True)
        self.assertIn('소비자·경제 사전', page); self.assertIn('<mark>청약철회</mark>', page)
        self.assertIn('무엇이든 찾아보세요', self.client.get('/search').get_data(as_text=True))
        self.assertEqual(self.client.get('/search?q=<script>&t=dict').status_code, 200)
        self.assertNotIn('<script>alert', self.client.get('/search?q=<script>alert(1)</script>').get_data(as_text=True))

    def test_soboru_tools_calc_dict_law(self):
        # AI 소비자 상담 옆 칸: 계산기 모음·계산기 칸, 사전 찾기·분야·첫 글자, 법령 찾기(AI 없이 모음에서)
        home = self.client.get('/tools').get_data(as_text=True)
        self.assertIn('<h1>계산기</h1>', home); self.assertIn('/tools/calc/fitness', home); self.assertIn('/tools/calc/loan', home)
        for c in self.site.soboru_tools.CALCS:
            page = self.client.get('/tools/calc/' + c['slug']).get_data(as_text=True)
            self.assertIn(c['name'], page); self.assertIn('data-calc="%s"' % c['slug'], page); self.assertIn('soboru-calc.js', page)
        self.assertEqual(self.client.get('/tools/calc/nope').status_code, 404)
        d = self.client.get('/tools/dict?q=청약').get_data(as_text=True).split('<main')[1]
        self.assertIn('청약철회', d); self.assertNotIn('기준금리', d)
        self.assertIn('기준금리', self.client.get('/tools/dict?c=경제 흐름').get_data(as_text=True).split('<main')[1])
        self.assertNotIn('위약금', self.client.get('/tools/dict?k=ㄱ').get_data(as_text=True).split('tl-words')[-1])
        self.assertEqual(self.site.soboru_tools.initial('쌍용'), 'ㅅ'); self.assertEqual(self.site.soboru_tools.initial('DSR'), 'A')
        law = self.client.get('/tools/law?q=청약철회').get_data(as_text=True)
        self.assertIn('법령 찾기', law); self.assertIn('law.go.kr', law)
        self.assertEqual(self.client.get('/tools/law?q=' + 'ㅋ' * 300).status_code, 200)

    def test_soboru_people_profile_and_follow(self):
        # 브런치식 이웃: 프로필 사진·소개, 이웃 페이지, 구독(토글·알림), 새 글 알림, 탈퇴하면 정리
        from PIL import Image
        a, aid = self.member_client('pp_writer', '빵순이')
        b, bid = self.member_client('pp_reader', '빵돌이')
        buf = io.BytesIO(); Image.new('RGB', (60, 60), (240, 146, 14)).save(buf, 'PNG')
        token = self.csrf(a, '/me/people')
        r = a.post('/me/people', data={'_csrf': token, 'bio': '  자취 5년 차   살림꾼 ' + 'x' * 100, 'photo': (io.BytesIO(buf.getvalue()), 'me.png')}, content_type='multipart/form-data')
        self.assertEqual(r.headers['Location'], f'/u/{aid}')
        with self.site.conn() as db:
            p = db.execute('SELECT * FROM profiles WHERE user_id=?', (aid,)).fetchone()
        self.assertTrue(p['bio'].startswith('자취 5년 차 살림꾼')); self.assertEqual(len(p['bio']), 80)
        self.assertEqual(self.client.get(f'/people/photo/{p["photo"]}').status_code, 200)
        self.assertEqual(self.client.get('/people/photo/../app.py').status_code, 404)
        page = self.client.get(f'/u/{aid}').get_data(as_text=True)
        self.assertIn('빵순이', page); self.assertIn('자취 5년 차', page); self.assertIn(p['photo'], page)
        self.assertEqual(self.client.get('/u/99999').status_code, 404)
        # 구독: 회원만, 나 자신은 안 됨, 한 번 더 누르면 취소
        follow = lambda c: c.post(f'/u/{aid}/follow', data={'_csrf': self.csrf(c, f'/u/{aid}' if c is self.client else '/me')})
        self.assertEqual(follow(self.client).status_code, 302)
        with self.site.conn() as db: self.assertIsNone(db.execute('SELECT 1 FROM follows').fetchone())
        self.assertEqual(follow(a).status_code, 400)
        follow(b)
        with self.site.conn() as db:
            self.assertTrue(db.execute('SELECT 1 FROM follows WHERE follower=? AND followee=?', (bid, aid)).fetchone())
            self.assertIn('빵돌이님이 나와 이웃을 맺었어요', db.execute("SELECT body FROM member_alerts WHERE user_id=? AND kind='follow'", (aid,)).fetchone()[0])
        self.assertIn('이웃이에요', b.get(f'/u/{aid}').get_data(as_text=True))
        # 구독한 이웃이 글을 쓰면 알림 + 구독 피드
        self.post_form(a, '/board/write?type=post', {'kind': 'post', 'head': '잡담', 'title': '오늘 장 본 이야기', 'body': '마트 세일 소식 나눠요.', 'agree': '1'})
        with self.site.conn() as db:
            self.assertIn('오늘 장 본 이야기', db.execute("SELECT body FROM member_alerts WHERE user_id=? AND kind='follow'", (bid,)).fetchone()[0])
        feed = b.get('/me/following').get_data(as_text=True)
        self.assertIn('오늘 장 본 이야기', feed); self.assertIn('빵순이', feed)
        with self.site.conn() as db: pid = db.execute("SELECT id FROM posts WHERE title='오늘 장 본 이야기'").fetchone()[0]
        self.assertIn('pp-card', b.get(f'/board/{pid}').get_data(as_text=True))
        follow(b)
        with self.site.conn() as db: self.assertIsNone(db.execute('SELECT 1 FROM follows').fetchone())
        follow(b)
        # 탈퇴: 프로필·사진·구독도 지움
        with self.site.conn() as db: self.site.delete_member(db, aid, True)
        with self.site.conn() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM profiles WHERE user_id=?', (aid,)).fetchone())
            self.assertIsNone(db.execute('SELECT 1 FROM follows').fetchone())
        self.assertFalse((self.site.UPLOAD / 'avatars' / p['photo']).exists())

    def test_soboru_community_feed_vs_suda(self):
        # 품앗히식 커뮤니티: 수다 말머리→종류, 후기 정보·영수증 인증, 골라주세요 투표·결말 (포인트는 뺌 2026-10-24)
        from PIL import Image
        with self.site.conn() as db:
            for t in ('vs_votes', 'vs_comments', 'vs_polls'): db.execute('DELETE FROM ' + t)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='points'").fetchone())  # 포인트 기록 표도 지움
        home = self.client.get('/').get_data(as_text=True)
        self.assertNotIn('nn-about', home); self.assertIn('nn-talk', home)
        me, uid = self.member_client('cm_writer', '수다쟁이')
        r = self.post_form(me, '/board/write?type=post', {'kind': 'post', 'head': '질문', 'title': '헬스장 환불 되나요?', 'body': '두 달 다니고 이사 가요. 환불 되나요?', 'agree': '1'})
        self.assertEqual(r.status_code, 302)
        with self.site.conn() as db:
            q = db.execute("SELECT * FROM posts WHERE title='헬스장 환불 되나요?'").fetchone()
            self.assertEqual((q['kind'], q['head']), ('question', '질문'))
        self.assertIn('헬스장 환불 되나요?', self.client.get('/suda?head=질문').get_data(as_text=True))
        self.assertNotIn('헬스장 환불 되나요?', self.client.get('/suda?head=지름').get_data(as_text=True))
        # 후기: 장소·분류·가격·방문일·재방문 의사·영수증
        buf = io.BytesIO(); Image.new('RGB', (40, 30), (255, 255, 255)).save(buf, 'JPEG')
        token = self.csrf(me, '/board/write?type=review')
        day = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        r = me.post('/board/write', data={'_csrf': token, 'kind': 'review', 'rv_type': 'place', 'rv_cat': '맛집·카페', 'target': '소보루식당', 'rating': '5', 'price': '21,000', 'bought': day,
                                          'again': '1', 'title': '국물이 진해요', 'body': '점심에 다녀왔는데 국물이 진했어요.', 'agree': '1', 'receipt': (io.BytesIO(buf.getvalue()), 'r.jpg'),
                                          'sido': '서울', 'gu': '강남구<b>', 'shop': '쿠팡'},
                    content_type='multipart/form-data')
        self.assertEqual(r.status_code, 302)
        with self.site.conn() as db:
            rv = db.execute("SELECT * FROM posts WHERE title='국물이 진해요'").fetchone()
        self.assertEqual((rv['rv_type'], rv['rv_cat'], rv['price'], rv['bought'], rv['again'], rv['receipt_state']), ('place', '맛집·카페', 21000, day, 1, 'wait'))
        feed = self.client.get('/feed?t=place').get_data(as_text=True)
        self.assertIn('국물이 진해요', feed); self.assertIn('21,000원', feed); self.assertIn('재방문 의사 있어요', feed)
        self.assertNotIn(rv['receipt'], feed)  # 영수증은 공개 화면에 안 나감
        # 우리 동네 후기: 장소 후기는 시·도·구 (산 곳은 상품 후기에만), 동네별로 모아 보기
        self.assertEqual((rv['sido'], rv['gu'], rv['shop']), ('서울', '강남구', ''))
        self.assertIn('서울 강남구', feed)
        self.assertIn('국물이 진해요', self.client.get('/feed?t=place&a=서울').get_data(as_text=True))
        self.assertIn('<b>0</b>개의 후기', self.client.get('/feed?t=place&a=부산').get_data(as_text=True))  # 제목은 옆 인기 후기엔 나올 수 있음
        # 어디서 샀어요?: 상품 후기의 산 곳
        r = self.post_form(me, '/board/write?type=review', {'kind': 'review', 'rv_type': 'product', 'rv_cat': '뷰티', 'target': '소보루 선크림', 'rating': '4', 'shop': '올리브영',
                                                            'title': '백탁 없는 선크림', 'body': '여름 내내 썼는데 백탁이 없었어요.', 'agree': '1'})
        self.assertEqual(r.status_code, 302)
        self.assertIn('백탁 없는 선크림', self.client.get('/feed?t=product&s=올리브영').get_data(as_text=True))
        self.assertIn('<b>0</b>개의 후기', self.client.get('/feed?t=product&s=쿠팡').get_data(as_text=True))
        self.assertIn('올리브영에서 샀어요', self.client.get('/feed?t=product').get_data(as_text=True))
        self.assertIn('<b>0</b>개의 후기', self.client.get('/feed?ok=1').get_data(as_text=True))
        self.assertNotEqual(self.client.get('/feed/receipt/' + rv['receipt']).status_code, 200)
        admin = self.login_admin()
        self.assertEqual(admin.get('/feed/receipt/' + rv['receipt']).status_code, 200)
        self.assertEqual(self.post_form(admin, '/admin/receipts', {'id': rv['id'], 'act': 'ok'}).status_code, 302)
        self.assertIn('<b>1</b>개의 후기', self.client.get('/feed?ok=1').get_data(as_text=True))
        self.client.get('/board/%d' % rv['id'])
        with self.site.conn() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM member_alerts WHERE user_id=? AND kind='review'", (uid,)).fetchone()[0], 1)  # 인증 알림
            self.assertEqual(db.execute('SELECT views FROM posts WHERE id=?', (rv['id'],)).fetchone()[0], 1)
        self.post_form(admin, '/admin/receipts', {'id': rv['id'], 'act': 'ok'})  # 두 번 눌러도 알림은 한 번
        with self.site.conn() as db: self.assertEqual(db.execute("SELECT COUNT(*) FROM member_alerts WHERE user_id=? AND kind='review'", (uid,)).fetchone()[0], 1)
        self.assertIn('/me', me.get('/me/points').headers['Location'])  # 예전 포인트 주소는 내 정보로
        self.assertNotIn('포인트', me.get('/me').get_data(as_text=True)); self.assertNotIn('200P', self.client.get('/feed').get_data(as_text=True))
        # 골라주세요: 회원만 올림, 누구나 한 번 고름, 글쓴이가 결말
        self.assertEqual(self.client.get('/vs/new').status_code, 302)
        r = self.post_form(me, '/vs/new', {'cat': '먹거리', 'a': '치킨', 'b': '피자', 'body': '둘이 먹어요', 'days': '3'})
        self.assertEqual(r.status_code, 302)
        with self.site.conn() as db: poll = db.execute('SELECT * FROM vs_polls').fetchone()
        self.assertEqual(poll['title'], '치킨 vs 피자')
        guest_token = self.csrf(self.client, '/vs/%d' % poll['id'])
        self.client.post('/vs/%d/vote' % poll['id'], data={'_csrf': guest_token, 'pick': 'a', 'used': '1'})
        self.client.post('/vs/%d/vote' % poll['id'], data={'_csrf': guest_token, 'pick': 'b'})  # 두 번째는 무시
        other, oid = self.member_client('cm_voter', '골라줌')
        other.post('/vs/%d/vote' % poll['id'], data={'_csrf': self.csrf(other, '/vs/%d' % poll['id']), 'pick': 'b'})
        page = self.client.get('/vs/%d' % poll['id']).get_data(as_text=True)
        self.assertIn('50%', page); self.assertIn('2명 골라줌', page); self.assertIn('써 본 사람 1명', page)
        self.assertEqual(other.post('/vs/%d/end' % poll['id'], data={'_csrf': self.csrf(other, '/vs/%d' % poll['id']), 'ending': 'a'}).status_code, 403)
        me.post('/vs/%d/end' % poll['id'], data={'_csrf': self.csrf(me, '/vs/%d' % poll['id']), 'ending': 'a', 'note': '치킨 먹었어요'})
        self.assertIn('결말 나옴', self.client.get('/vs').get_data(as_text=True))
        # 담아 두기: 회원만, 한 번 더 누르면 빠짐
        self.assertIn('/login', self.client.post('/me/saved/%d' % rv['id']).headers.get('Location', '') or '/login')
        sv = lambda: me.post('/me/saved/%d' % rv['id'], data={'_csrf': self.csrf(me, '/board/%d' % rv['id'])})
        self.assertEqual(sv().status_code, 302)
        self.assertIn('국물이 진해요', me.get('/me/saved').get_data(as_text=True))
        self.assertIn('담아 뒀어요', me.get('/board/%d' % rv['id']).get_data(as_text=True))
        sv()
        self.assertNotIn('국물이 진해요', me.get('/me/saved').get_data(as_text=True))
        # 사장님 소식: 회원이 하루 한 번, '홍보' 표시, https 링크만, 글쓴이·운영자가 내림
        with self.site.conn() as db: db.execute('DELETE FROM owner_news')
        bad = self.post_form(me, '/owners/new', {'head': '할인', 'biz': '빵·디저트', 'shop': '소보루빵집', 'title': '주말 1+1', 'body': '토요일 오후 3시부터 소보루빵 1+1이에요.', 'link': 'javascript:alert(1)'})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.post_form(me, '/owners/new', {'head': '할인', 'biz': '빵·디저트', 'shop': '소보루빵집', 'title': '주말 1+1', 'body': '토요일 오후 3시부터 소보루빵 1+1이에요.', 'link': 'https://soboru.example/sale', 'sido': '서울', 'sgg': '강남구'}).status_code, 302)
        self.assertEqual(self.post_form(me, '/owners/new', {'head': '오픈', 'biz': '빵·디저트', 'shop': '소보루빵집', 'title': '또 올림', 'body': '하루에 두 번째 소식이에요. 막혀야 해요.'}).status_code, 400)
        with self.site.conn() as db: self.assertEqual(db.execute('SELECT biz FROM owner_news').fetchone()[0], '빵·디저트')
        self.assertEqual(self.site.soboru_cm.guess_biz('오소보카페'), '카페'); self.assertEqual(self.site.soboru_cm.guess_biz('무명상회'), '기타')
        self.assertIn('주말 1+1', self.client.get('/owners?b=빵·디저트').get_data(as_text=True)); self.assertNotIn('주말 1+1', self.client.get('/owners?b=카페').get_data(as_text=True))
        # 지역: 고른 동네(서울 강남구) 소식은 보이고 다른 동네(부산)에선 안 보임
        self.assertIn('주말 1+1', self.client.get('/owners?sido=서울&sgg=강남구').get_data(as_text=True)); self.assertNotIn('주말 1+1', self.client.get('/owners?sido=부산').get_data(as_text=True))
        page = self.client.get('/owners').get_data(as_text=True)
        self.assertIn('주말 1+1', page); self.assertIn('홍보', page); self.assertIn('rel="nofollow sponsored noopener"', page)
        with self.site.conn() as db: nid = db.execute('SELECT id FROM owner_news').fetchone()[0]
        self.assertEqual(other.post('/owners/%d/hide' % nid, data={'_csrf': self.csrf(other, '/owners/new')}).status_code, 403)
        me.post('/owners/%d/hide' % nid, data={'_csrf': self.csrf(me, '/owners')})
        self.assertNotIn('주말 1+1', self.client.get('/owners').get_data(as_text=True))
        # 에디터 모집은 뺌: 예전 주소는 후기 피드로, 메뉴에도 없음
        self.assertEqual(self.client.get('/editor').headers['Location'], '/feed')
        self.assertNotIn('에디터 모집', self.client.get('/feed').get_data(as_text=True))

    def test_service_worker_and_offline_page(self):
        r = self.client.get('/sw.js')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, 'application/javascript')
        self.assertEqual(r.headers['Service-Worker-Allowed'], '/')
        self.assertEqual(r.headers['Cache-Control'], 'no-cache')
        sw = r.get_data(as_text=True)
        self.assertNotIn('__VERSION__', sw)
        self.assertIn("var VERSION = '%s'" % self.site.app.jinja_env.globals['css_v'], sw)  # 디자인 버전이 바뀌면 캐시도 새로
        self.assertIn("var OFFLINE_URL = '/offline'", sw)
        self.assertIn("req.method !== 'GET'", sw)  # POST는 손대지 않음
        self.assertEqual(sw.count('cache.put('), 1)  # 저장은 버전 붙은 /static 파일 한 곳뿐 (화면·내 정보·관리자는 저장 안 함)
        self.assertIn("url.pathname.indexOf('/static/') === 0 && url.searchParams.has('v')", sw)
        page = self.client.get('/offline')
        html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn('인터넷 연결이 끊겼어요', html)
        self.assertIn('다시 시도하기', html)
        self.assertIn('img/soboru-character-hero.png?v=', html)
        self.assertNotIn('sb-header', html)  # 회원 정보가 없는 단독 화면
        self.assertIn("navigator.serviceWorker.register('/sw.js'", self.client.get('/').get_data(as_text=True))

    def test_app_link_files_follow_settings(self):
        for path in ('/.well-known/assetlinks.json', '/.well-known/apple-app-site-association'):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        fp = ':'.join(['ab'] * 32)
        with patch.dict(os.environ, {'ANDROID_SHA256': fp + ', nope'}):
            r = self.client.get('/.well-known/assetlinks.json')
            self.assertEqual(r.mimetype, 'application/json')
            data = json.loads(r.get_data(as_text=True))
            self.assertEqual(data[0]['relation'], ['delegate_permission/common.handle_all_urls'])
            self.assertEqual(data[0]['target'], {'namespace': 'android_app', 'package_name': 'kr.co.consumerjebo.soboru', 'sha256_cert_fingerprints': [fp.upper()]})
        with patch.dict(os.environ, {'ANDROID_SHA256': 'nope'}):
            self.assertEqual(self.client.get('/.well-known/assetlinks.json').status_code, 404)  # 지문 모양이 아니면 없는 것과 같음
        with patch.dict(os.environ, {'ANDROID_SHA256': fp, 'ANDROID_PACKAGE': 'kr.example.app'}):
            self.assertEqual(json.loads(self.client.get('/.well-known/assetlinks.json').get_data(as_text=True))[0]['target']['package_name'], 'kr.example.app')
        with patch.dict(os.environ, {'APPLE_TEAM_ID': 'ABCDE12345'}):
            r = self.client.get('/.well-known/apple-app-site-association')
            self.assertEqual(r.mimetype, 'application/json')
            data = json.loads(r.get_data(as_text=True))
            self.assertEqual(data['applinks']['details'][0]['appIDs'], ['ABCDE12345.kr.co.consumerjebo.soboru'])
            self.assertIn({'/': '/admin*', 'exclude': True}, data['applinks']['details'][0]['components'])
            self.assertEqual(data['webcredentials']['apps'], ['ABCDE12345.kr.co.consumerjebo.soboru'])
        with patch.dict(os.environ, {'APPLE_TEAM_ID': 'ABCDE12345', 'IOS_BUNDLE_ID': 'kr.example.ios'}):
            self.assertIn('ABCDE12345.kr.example.ios', self.client.get('/.well-known/apple-app-site-association').get_data(as_text=True))

    def test_members_can_block_and_unblock(self):
        alice, a_id = self.member_client('alice_b', '앨리스')
        bob, b_id = self.member_client('bob_b', '밥밥')
        now = datetime.datetime.now().isoformat(timespec='seconds')
        with self.site.conn() as db:
            camp = db.execute("INSERT INTO review_campaigns(slug,title,topic,starts,ends,active,created) VALUES('block-test','차단 시험 주제','배달음식','','',1,?)", (now,)).lastrowid
            bad = db.execute("INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created,user_id,kind,target,rating,campaign_id) VALUES('경험 공유','밥밥','','밥이 쓴 리뷰 제목','밥이 쓴 본문 내용입니다','x',?,?,'review','밥가게',4,?)", (now, b_id, camp)).lastrowid
            other = db.execute("INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created,kind) VALUES('꿀팁','손님','x','손님이 쓴 꿀팁','손님 본문입니다 열 글자 넘게','x',?,'tip')", (now,)).lastrowid
            db.execute("INSERT INTO comments(post_id,nickname,pw_hash,body,ip_hash,created,user_id) VALUES(?,'밥밥','','밥이 단 댓글이에요','x',?,?)", (other, now, b_id))
            db.execute("INSERT INTO comments(post_id,nickname,pw_hash,body,ip_hash,created) VALUES(?,'손님2','x','손님 댓글이에요','x',?)", (other, now))
            guest_c = db.execute('SELECT id FROM comments WHERE user_id IS NULL').fetchone()[0]
        def seen(client):
            return {'board': '밥이 쓴 리뷰 제목' in client.get('/board').get_data(as_text=True),
                    'post': '밥이 쓴 본문 내용입니다' in client.get(f'/board/{bad}').get_data(as_text=True),
                    'comment': '밥이 단 댓글이에요' in client.get(f'/board/{other}').get_data(as_text=True),
                    'feed': '밥이 쓴 리뷰 제목' in client.get('/').get_data(as_text=True),
                    'campaign': '밥이 쓴 리뷰 제목' in client.get('/pick/block-test').get_data(as_text=True)}
        everywhere = {'board': True, 'post': True, 'comment': True, 'feed': True, 'campaign': True}
        self.assertEqual(seen(alice), everywhere)
        # 글·댓글의 더 보기 메뉴: 신고와 차단. 손님에게는 로그인하면 차단할 수 있다고 안내
        page = alice.get(f'/board/{bad}').get_data(as_text=True)
        self.assertIn('이 사용자 차단', page); self.assertIn('부적절한 글 알리기', page)
        self.assertIn(f'action="/board/block/p/{bad}"', page)
        guest = self.client.get(f'/board/{bad}').get_data(as_text=True)
        self.assertIn(f'href="/login?next=/board/{bad}"', guest); self.assertIn('로그인하면 차단할 수 있어요', guest)
        self.assertNotIn('/board/block/', guest)
        self.assertEqual(self.client.post(f'/board/block/p/{bad}', data={'_csrf': self.csrf(self.client, '/report')}).status_code, 302)  # 손님은 로그인 화면으로
        with self.site.conn() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM user_blocks').fetchone()[0], 0)
        self.assertNotIn(f'/board/block/p/{bad}', bob.get(f'/board/{bad}').get_data(as_text=True))  # 내 글에는 차단 메뉴 없음
        token = self.csrf(alice, f'/board/{other}')
        self.assertEqual(alice.post(f'/board/block/c/{guest_c}', data={'_csrf': token}).status_code, 404)  # 손님 댓글은 회원이 아니라 차단 못 함
        self.assertEqual(alice.post(f'/board/block/p/{bad}', data={}).status_code, 400)  # 위조 방지 값 없으면 거절
        r = alice.post(f'/board/block/p/{bad}', data={'_csrf': token})
        self.assertEqual(r.headers['Location'], '/board')
        self.assertIn('차단했어요', alice.get('/board').get_data(as_text=True))
        self.assertEqual(seen(alice), {k: False for k in everywhere})
        blocked_page = alice.get(f'/board/{bad}').get_data(as_text=True)
        self.assertIn('차단한 사용자의 글이에요', blocked_page); self.assertIn('차단 풀고 보기', blocked_page)
        self.assertIn('손님 댓글이에요', alice.get(f'/board/{other}').get_data(as_text=True))  # 다른 사람 댓글은 그대로
        self.assertEqual(seen(self.client), everywhere)  # 다른 사람에게는 그대로 보임
        self.assertEqual(seen(bob), everywhere)
        self.assertIn('내 글은 차단할 수 없어요', bob.get(bob.post(f'/board/block/p/{bad}', data={'_csrf': self.csrf(bob, '/report')}).headers['Location']).get_data(as_text=True))
        # 내 정보 > 차단한 사용자에서 풀기
        me = alice.get('/me').get_data(as_text=True)
        self.assertIn('차단한 사용자', me); self.assertIn('밥밥', me)
        r = alice.post(f'/me/blocks/{b_id}/remove', data={'_csrf': self.csrf(alice, '/me')})
        self.assertEqual(r.headers['Location'], '/me#blocked')
        self.assertEqual(seen(alice), everywhere)
        # 글 화면에서 '차단 풀고 보기'는 그 글로 돌아옴
        alice.post(f'/board/block/p/{bad}', data={'_csrf': self.csrf(alice, '/report')})
        r = alice.post(f'/me/blocks/{b_id}/remove', data={'_csrf': self.csrf(alice, '/me'), 'next': f'/board/{bad}'})
        self.assertEqual(r.headers['Location'], f'/board/{bad}')
        # 탈퇴하면 차단 기록도 지움
        alice.post(f'/board/block/p/{bad}', data={'_csrf': self.csrf(alice, '/report')})
        bob.post('/me/withdraw', data={'_csrf': self.csrf(bob, '/me'), 'password': 'butter123', 'confirm': 'on', 'delete_posts': 'on'})
        with self.site.conn() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM user_blocks').fetchone()[0], 0)

    def test_terms_have_zero_tolerance_and_reporting(self):
        terms = self.client.get('/terms').get_data(as_text=True)
        self.assertIn('무관용', terms); self.assertIn('차단', terms)
        privacy = self.client.get('/privacy').get_data(as_text=True)
        self.assertIn('푸시 알림', privacy); self.assertIn('Apple로 가입·로그인', privacy)

    def test_alerts_for_comments_answers_solved_and_reports(self):
        alice, a_id = self.member_client('alice_a', '앨리스')
        bob, b_id = self.member_client('bob_a', '밥밥')
        now = datetime.datetime.now().isoformat(timespec='seconds')
        with self.site.conn() as db:
            q = db.execute("INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created,user_id,kind) VALUES('질문해요','앨리스','','헬스장 환불 되나요?','중도 해지하면 환불이 되나요 궁금해요','x',?,?,'question')", (now, a_id)).lastrowid
        def comment(client, body, **extra):
            return client.post(f'/board/{q}/comment', data={'_csrf': self.csrf(client, f'/board/{q}'), 'body': body, **extra})
        self.assertNotIn('<b>', re.search(r'<a class="sb-bell[^"]*".*?</a>', alice.get('/').get_data(as_text=True), re.S)[0])  # 아직 알림 없음
        comment(bob, '네 10%만 빼고 돌려받아요')
        comment(self.client, '저도 궁금해요', nickname='손님', password='1234')
        comment(alice, '고마워요!')  # 내 글에 내가 단 댓글은 알리지 않음
        bell = re.search(r'<a class="sb-bell[^"]*".*?</a>', alice.get('/').get_data(as_text=True), re.S)[0]
        self.assertIn('href="/me/alerts"', bell); self.assertIn('<b>2</b>', bell); self.assertIn('알림 2개 안 읽음', bell)
        page = alice.get('/me/alerts').get_data(as_text=True)
        self.assertEqual(page.count('내 질문에 답변이 달렸어요: 헬스장 환불 되나요?'), 2)
        self.assertEqual(page.count('alert-row new'), 2)
        self.assertNotIn('푸시 알림 받기', page)  # 키가 없으면 푸시 버튼도 없음
        self.assertNotIn('<b>', re.search(r'<a class="sb-bell[^"]*".*?</a>', alice.get('/').get_data(as_text=True), re.S)[0])  # 열어 보면 모두 읽음
        with self.site.conn() as db:
            alert_id, link = db.execute('SELECT id,link FROM member_alerts WHERE user_id=? ORDER BY id LIMIT 1', (a_id,)).fetchone()
        self.assertRegex(link, rf'^/board/{q}#c\d+$')
        self.assertEqual(alice.get(f'/me/alerts/go/{alert_id}').headers['Location'], link)
        self.assertEqual(bob.get(f'/me/alerts/go/{alert_id}').headers['Location'], '/me/alerts')  # 남의 알림은 못 엶
        self.assertEqual(self.client.get('/me/alerts').status_code, 302)
        # 질문을 해결됨으로 바꾸면 답변한 회원에게
        alice.post(f'/board/{q}/solve', data={'_csrf': self.csrf(alice, f'/board/{q}')})
        self.assertIn('답변한 질문이 해결됐어요: 헬스장 환불 되나요?', bob.get('/me/alerts').get_data(as_text=True))
        # 내 글을 차단한 회원의 댓글은 알리지 않음
        with self.site.conn() as db:
            db.execute('INSERT INTO user_blocks(blocker,blocked,created) VALUES(?,?,?)', (a_id, b_id, now))
            before = db.execute('SELECT COUNT(*) FROM member_alerts WHERE user_id=?', (a_id,)).fetchone()[0]
        comment(bob, '한 번 더 남겨요')
        with self.site.conn() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM member_alerts WHERE user_id=?', (a_id,)).fetchone()[0], before)
        # 회원 계정에 연결된 제보의 진행 소식 (제보 알림이 커밋 뒤에 부름)
        with self.site.conn() as db:
            cid = db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,user_id) VALUES('CJ-AL1','x','배송','가게','택배가 안 와요','내용','환불',?,?)", (now, a_id)).lastrowid
            case = db.execute('SELECT * FROM cases WHERE id=?', (cid,)).fetchone()
        with self.site.app.test_request_context():
            self.site.case_alert(case, 'status'); self.site.case_alert(case, 'seen')  # 'seen'은 알림함에 넣지 않음
        with self.site.conn() as db:
            rows = db.execute("SELECT body,link FROM member_alerts WHERE user_id=? AND kind='case'", (a_id,)).fetchall()
        self.assertEqual([tuple(r) for r in rows], [('내 제보 진행 단계가 바뀌었어요: 택배가 안 와요', f'/me/case/{cid}')])
        # 탈퇴하면 알림도 지움
        alice.post('/me/withdraw', data={'_csrf': self.csrf(alice, '/me'), 'password': 'butter123', 'confirm': 'on'})
        with self.site.conn() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM member_alerts WHERE user_id=?', (a_id,)).fetchone()[0], 0)

    def test_push_subscribe_and_send(self):
        alice, a_id = self.member_client('alice_p', '앨리스')
        bob, b_id = self.member_client('bob_p', '밥밥')
        sub = {'endpoint': 'https://fcm.googleapis.com/fcm/send/abc123', 'p256dh': 'B' * 87, 'auth': 'a' * 22}
        token = self.csrf(alice, '/me')
        self.assertEqual(alice.post('/me/push/subscribe', data={'_csrf': token, **sub}).status_code, 503)  # 키가 없으면 꺼짐
        keys = {'VAPID_PUBLIC_KEY': 'BPub' + 'x' * 83, 'VAPID_PRIVATE_KEY': 'p' * 43, 'VAPID_SUBJECT': 'mailto:help@example.com'}
        with patch.dict(os.environ, keys):
            page = alice.get('/me/alerts').get_data(as_text=True)
            self.assertIn('푸시 알림 받기', page); self.assertIn('data-key="BPub', page)
            self.assertEqual(alice.post('/me/push/subscribe', data=sub).status_code, 400)  # 위조 방지 값 없음
            guest = self.client.post('/me/push/subscribe', data={'_csrf': self.csrf(self.client, '/login'), **sub})
            self.assertEqual(guest.status_code, 302); self.assertIn('/login', guest.headers['Location'])  # 회원만
            self.assertEqual(alice.post('/me/push/subscribe', data={'_csrf': token, **dict(sub, endpoint='http://evil.test/x')}).status_code, 400)
            r = alice.post('/me/push/subscribe', data={'_csrf': token, **sub})
            self.assertEqual((r.status_code, r.get_json()), (200, {'ok': True}))
            with self.site.conn() as db:
                self.assertEqual(db.execute('SELECT user_id,p256dh,auth FROM push_subscriptions').fetchall()[0][:], (a_id, sub['p256dh'], sub['auth']))
            # 새 알림이 생기면 그 회원 기기로 푸시 (외부로는 보내지 않고 가짜로 받음). 구독이 끊긴 기기는 지움
            sent = []
            def fake_send(s, payload, log):
                sent.append((s['endpoint'], payload)); return (False, True) if 'gone' in s['endpoint'] else (True, False)
            with self.site.conn() as db:
                q = db.execute("INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created,user_id,kind) VALUES('꿀팁','앨리스','','앨리스 꿀팁','꿀팁 본문입니다 열 글자 넘게','x','2026-10-17T10:00:00',?,'tip')", (a_id,)).lastrowid
                db.execute("INSERT INTO push_subscriptions(user_id,endpoint,p256dh,auth,created) VALUES(?,?,?,?,?)", (a_id, 'https://push.test/gone', 'B' * 87, 'a' * 22, 'x'))
            with patch.object(self.site.appready, 'ASYNC', False), patch.object(self.site.appready, 'webpush_send', fake_send):
                bob.post(f'/board/{q}/comment', data={'_csrf': self.csrf(bob, f'/board/{q}'), 'body': '좋은 정보 고마워요'})
            self.assertEqual(sorted(e for e, _ in sent), ['https://fcm.googleapis.com/fcm/send/abc123', 'https://push.test/gone'])
            payload = sent[0][1]
            self.assertEqual(payload['body'], '내 글에 댓글이 달렸어요: 앨리스 꿀팁'); self.assertTrue(payload['url'].startswith(f'/board/{q}#c'))
            with self.site.conn() as db:
                self.assertEqual([r[0] for r in db.execute('SELECT endpoint FROM push_subscriptions')], [sub['endpoint']])
            # 같은 기기에서 다른 회원이 켜면 그 회원에게 옮김, 끄면 지움
            bob.post('/me/push/subscribe', data={'_csrf': self.csrf(bob, '/me'), **sub})
            with self.site.conn() as db:self.assertEqual(db.execute('SELECT user_id FROM push_subscriptions').fetchall()[0][0], b_id)
            self.assertEqual(bob.post('/me/push/unsubscribe', data={'_csrf': self.csrf(bob, '/me'), 'endpoint': sub['endpoint']}).get_json(), {'ok': True})
            with self.site.conn() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM push_subscriptions').fetchone()[0], 0)
        # pywebpush가 없으면 보내지 않고 기록만
        with patch.dict('sys.modules', {'pywebpush': None}), self.assertLogs(self.site.app.logger, 'WARNING') as logs:
            self.assertEqual(self.site.appready.webpush_send(dict(sub, id=1), {}, self.site.app.logger), (False, False))
        self.assertIn('pywebpush', logs.output[0])

    APP_UA = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) SoboruApp/1.0.0 (ios)'}

    def test_app_bridge_and_app_push(self):
        # 소보루 앱(soboru-app) 안: 웹 탭바 대신 앱 탭, 앱과 잇는 다리 스크립트
        web = self.client.get('/').get_data(as_text=True)
        self.assertIn('sb-tabbar', web); self.assertNotIn('ReactNativeWebView', web)
        app = self.client.get('/', headers=self.APP_UA).get_data(as_text=True)
        self.assertNotIn('class="sb-tabbar"', app); self.assertIn('in-app', app); self.assertIn('ReactNativeWebView', app)
        self.assertIn('member: false', app)
        self.assertIn("focus: !!document.querySelector('.sb-header-min')", app)  # 로그인·글쓰기 화면이면 앱이 아래 탭을 숨김
        self.assertIn('sb-header-min', self.client.get('/login', headers=self.APP_UA).get_data(as_text=True))
        alice, a_id = self.member_client('alice_app', '앱앨리스')
        bob, _ = self.member_client('bob_app', '앱밥')
        page = alice.get('/me/alerts', headers=self.APP_UA).get_data(as_text=True)
        self.assertIn('data-app="push-enable"', page); self.assertNotIn('pushManager', page)  # 웹 푸시 키가 없어도 앱 알림은 켬
        self.assertIn('member: true', page)
        token = self.csrf(alice, '/me')
        expo = 'ExponentPushToken[abcDEF1234567890xyz]'
        self.assertEqual(alice.post('/me/push/app', data={'_csrf': token, 'token': 'https://evil.test'}).status_code, 400)
        self.assertEqual(alice.post('/me/push/app', data={'token': expo}).status_code, 400)  # 위조 방지 값 없음
        self.assertEqual(alice.post('/me/push/app', data={'_csrf': token, 'token': expo}).get_json(), {'ok': True})
        alice.post('/me/push/app', data={'_csrf': token, 'token': expo})  # 같은 기기는 한 줄
        with self.site.conn() as db:
            self.assertEqual([tuple(r) for r in db.execute('SELECT user_id,endpoint FROM push_subscriptions')], [(a_id, 'expo:' + expo)])
            q = db.execute("INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created,user_id,kind) VALUES('꿀팁','앱앨리스','','앱 꿀팁','꿀팁 본문입니다 열 글자 넘게','x','2026-10-17T10:00:00',?,'tip')", (a_id,)).lastrowid
            db.execute("INSERT INTO push_subscriptions(user_id,endpoint,p256dh,auth,created) VALUES(?,?,'','',?)", (a_id, 'expo:ExponentPushToken[goneGONEgone12345]', 'x'))
        sent = []
        def fake_expo(tokens, payload, log):
            sent.append((sorted(tokens), payload)); return [t for t in tokens if 'gone' in t]
        # 웹 푸시 키(VAPID)가 없어도 앱 기기로는 보냄. 앱을 지운 기기는 지움
        with patch.object(self.site.appready, 'ASYNC', False), patch.object(self.site.appready, 'expo_send', fake_expo):
            bob.post(f'/board/{q}/comment', data={'_csrf': self.csrf(bob, f'/board/{q}'), 'body': '앱에서 봤어요 고마워요'})
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], ['ExponentPushToken[abcDEF1234567890xyz]', 'ExponentPushToken[goneGONEgone12345]'])
        self.assertEqual(sent[0][1]['body'], '내 글에 댓글이 달렸어요: 앱 꿀팁'); self.assertTrue(sent[0][1]['url'].startswith(f'/board/{q}#c'))
        with self.site.conn() as db:
            self.assertEqual([r[0] for r in db.execute('SELECT endpoint FROM push_subscriptions')], ['expo:' + expo])
        # 끄기·탈퇴는 웹 푸시와 같은 주소
        self.assertEqual(alice.post('/me/push/unsubscribe', data={'_csrf': token, 'endpoint': 'expo:' + expo}).get_json(), {'ok': True})
        with self.site.conn() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM push_subscriptions').fetchone()[0], 0)

    def test_apple_login_in_ios_app(self):
        import base64, time
        key, env = self.apple_env()
        env.pop('APPLE_SERVICE_ID')  # 앱은 Services ID 없이 번들 ID로
        members = self.site.members
        self.assertEqual(self.client.post('/auth/apple/native', data={'_csrf': self.csrf(self.client, '/login'), 'code': 'x'}).status_code, 404)
        with patch.dict(os.environ, env):
            self.assertNotIn('social-apple', self.client.get('/login').get_data(as_text=True))  # 브라우저에서는 웹 Apple 로그인 설정이 있어야 보임
            login = self.client.get('/login?next=/life', headers=self.APP_UA).get_data(as_text=True)
            self.assertIn('data-app="apple-login" data-next="/life"', login); self.assertIn('Apple로 계속하기', login)
            claims = {'iss': 'https://appleid.apple.com', 'aud': 'kr.co.consumerjebo.soboru', 'exp': int(time.time()) + 600, 'sub': '000777.app.uid',
                      'email': 'me@example.com', 'email_verified': 'true'}
            calls = []
            def fake(method, url, data=None, headers=None, timeout=10):
                calls.append((url, data))
                if url.endswith('/auth/token'):
                    return 200, {'id_token': 'h.' + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=') + '.s', 'refresh_token': 'refresh-app'}
                return 200, {}
            form = {'code': 'app-code', 'user': json.dumps({'name': {'firstName': '보루', 'lastName': '소'}}), 'next': '/life'}
            self.assertEqual(self.client.post('/auth/apple/native', data=form).status_code, 400)  # 위조 방지 값 없음
            with patch.object(members, 'http', fake):
                r = self.client.post('/auth/apple/native', data=dict(form, _csrf=self.csrf(self.client, '/login')), headers=self.APP_UA)
            self.assertEqual(r.headers['Location'], '/auth/join')
            self.assertEqual(calls[0][1]['client_id'], 'kr.co.consumerjebo.soboru'); self.assertNotIn('redirect_uri', calls[0][1])
            body = json.loads(base64.urlsafe_b64decode(calls[0][1]['client_secret'].split('.')[1] + '=='))
            self.assertEqual(body['sub'], 'kr.co.consumerjebo.soboru')
            r = self.post_form(self.client, '/auth/join', self.join_form(self.client))
            with self.site.conn() as db:
                user = db.execute("SELECT * FROM users WHERE real_name='소보루'").fetchone()
                tok = db.execute('SELECT refresh_token,client FROM apple_tokens').fetchone()
            self.assertEqual(user['email'], 'me@example.com')
            self.assertEqual(tuple(tok), ('refresh-app', 'kr.co.consumerjebo.soboru'))
            # 탈퇴하면 앱에서 받은 토큰은 번들 ID로 취소
            calls.clear()
            with patch.object(members, 'http', fake):
                self.client.post('/me/withdraw', data={'_csrf': self.csrf(self.client, '/me'), 'confirm': 'on'})
            revoke = [c for c in calls if c[0].endswith('/auth/revoke')]
            self.assertEqual([(c[1]['client_id'], c[1]['token']) for c in revoke], [('kr.co.consumerjebo.soboru', 'refresh-app')])

    def apple_env(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        return key, {'APPLE_SERVICE_ID': 'kr.co.consumerjebo.soboru.web', 'APPLE_TEAM_ID': 'TEAM123456', 'APPLE_KEY_ID': 'KEY1234567', 'APPLE_PRIVATE_KEY': pem.replace('\n', '\\n')}

    def test_apple_login(self):
        import base64, time
        self.assertNotIn('Apple로 계속하기', self.client.get('/login').get_data(as_text=True))  # 설정이 없으면 버튼도 없음
        self.assertEqual(self.client.get('/auth/apple/start').status_code, 404)
        key, env = self.apple_env()
        members = self.site.members
        with patch.dict(os.environ, env):
            login = self.client.get('/login').get_data(as_text=True)
            self.assertIn('Apple로 계속하기', login); self.assertIn('social-apple', login)
            self.assertNotIn('social-apple', self.client.get('/report').get_data(as_text=True))  # 이름·전화번호를 주지 않아 자동 입력에는 없음
            # client_secret: ES256으로 서명한 JWT
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
            jwt = members.apple_client_secret(1_800_000_000)
            head, body, sig = jwt.split('.')
            dec = lambda s: base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))
            self.assertEqual(json.loads(dec(head)), {'alg': 'ES256', 'kid': 'KEY1234567', 'typ': 'JWT'})
            self.assertEqual(json.loads(dec(body)), {'iss': 'TEAM123456', 'iat': 1_800_000_000, 'exp': 1_800_000_600, 'aud': 'https://appleid.apple.com', 'sub': 'kr.co.consumerjebo.soboru.web'})
            raw = dec(sig)
            key.public_key().verify(encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big')), f'{head}.{body}'.encode(), ec.ECDSA(hashes.SHA256()))
            # 시작: form_post로 이름·이메일 요청
            loc = self.client.get('/auth/apple/start').headers['Location']
            self.assertTrue(loc.startswith('https://appleid.apple.com/auth/authorize?'))
            self.assertIn('response_mode=form_post', loc); self.assertIn('scope=name+email', loc); self.assertIn('client_id=kr.co.consumerjebo.soboru.web', loc)
            state = re.search(r'state=([^&]+)', loc)[1]
            claims = {'iss': 'https://appleid.apple.com', 'aud': 'kr.co.consumerjebo.soboru.web', 'exp': int(time.time()) + 600, 'sub': '000123.apple.uid',
                      'email': 'xyz@privaterelay.appleid.com', 'email_verified': 'true', 'is_private_email': 'true'}
            calls = []
            def fake(method, url, data=None, headers=None, timeout=10):
                calls.append((url, data))
                if url.endswith('/auth/token'):
                    return 200, {'id_token': 'h.' + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=') + '.s', 'refresh_token': 'refresh-abc', 'access_token': 'a'}
                return 200, {}
            form = {'code': 'apple-code', 'state': state, 'user': json.dumps({'name': {'firstName': '길동', 'lastName': '홍'}})}
            # 애플이 다른 사이트에서 POST로 보내면 쿠키가 없어 중계 화면으로 한 번 더 보냄 (쿠키는 건드리지 않음)
            other = self.site.app.test_client()
            with patch.object(members, 'http', fake):
                relay = other.post('/auth/apple/callback', data=form)
            self.assertEqual(relay.status_code, 200)
            self.assertNotIn('Set-Cookie', relay.headers)
            html = relay.get_data(as_text=True)
            self.assertIn('name="relayed" value="1"', html); self.assertIn('value="apple-code"', html)
            self.assertEqual(calls, [])
            self.assertEqual(self.client.post('/auth/kakao/callback', data=form).status_code, 400)  # 다른 로그인은 POST 예외 없음
            with patch.object(members, 'http', fake):
                r = self.client.post('/auth/apple/callback', data=dict(form, relayed='1'))
            self.assertEqual(r.headers['Location'], '/auth/join')
            self.assertEqual(calls[0][1]['client_id'], 'kr.co.consumerjebo.soboru.web')
            self.assertEqual(calls[0][1]['redirect_uri'], 'http://localhost/auth/apple/callback')
            self.assertEqual(calls[0][1]['client_secret'].count('.'), 2)
            self.assertIn('Apple로 가입하기', self.client.get('/auth/join').get_data(as_text=True))
            self.post_form(self.client, '/auth/join', self.join_form(self.client))
            with self.site.conn() as db:
                user = db.execute("SELECT * FROM users WHERE real_name='홍길동'").fetchone()
                ident = db.execute('SELECT * FROM user_identities WHERE user_id=?', (user['id'],)).fetchone()
                token = db.execute('SELECT refresh_token FROM apple_tokens WHERE provider_uid=?', ('000123.apple.uid',)).fetchone()
            self.assertEqual(user['email'], '')  # 애플 중계 주소는 회원 이메일로 쓰지 않음
            self.assertEqual((ident['provider'], ident['email']), ('apple', 'xyz@privaterelay.appleid.com'))
            self.assertEqual(token[0], 'refresh-abc')
            self.assertNotIn('refresh-abc', str(self.client.get_cookie('session').value if self.client.get_cookie('session') else ''))
            # 위조된 state는 거절
            loc = self.client.get('/auth/apple/start?link=1').headers['Location']
            with patch.object(members, 'http', fake):
                self.assertEqual(self.client.post('/auth/apple/callback', data=dict(form, state='forged', relayed='1')).headers['Location'], '/login')
            # 다시 로그인하면 바로 들어오고, 이름은 처음 받은 그대로
            self.client.post('/logout', data={'_csrf': self.csrf(self.client, '/me')})
            state = re.search(r'state=([^&]+)', self.client.get('/auth/apple/start').headers['Location'])[1]
            with patch.object(members, 'http', fake):
                r = self.client.post('/auth/apple/callback', data={'code': 'c2', 'state': state, 'relayed': '1'})
            self.assertEqual(r.headers['Location'], '/')
            # 탈퇴하면 애플에 토큰 취소를 알리고 저장한 토큰을 지움
            calls.clear()
            with patch.object(members, 'http', fake):
                self.client.post('/me/withdraw', data={'_csrf': self.csrf(self.client, '/me'), 'confirm': 'on'})
            revoke = [c for c in calls if c[0].endswith('/auth/revoke')]
            self.assertEqual(len(revoke), 1)
            self.assertEqual((revoke[0][1]['token'], revoke[0][1]['token_type_hint']), ('refresh-abc', 'refresh_token'))
            with self.site.conn() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM apple_tokens').fetchone()[0], 0)
                self.assertIsNone(db.execute("SELECT 1 FROM users WHERE real_name='홍길동'").fetchone())
    # ---- 소보루 레터 (soboru_letter.py) -------------------------------------------
    LETTER_MAIL = {'SMTP_HOST': 'smtp.test', 'SMTP_USER': 'u@test', 'SMTP_PASSWORD': 'pw-test', 'MAIL_FROM': 'letter@consumerjebo.co.kr'}
    LETTER_NAVER = {'OPENAI_API_KEY': 'sk-test-key', 'NAVER_HUB_CLIENT_ID': 'cid-test', 'NAVER_HUB_CLIENT_SECRET': 'secret-test-value'}

    def letter_cleanup(self):
        with self.site.conn() as db:
            for t in ('letters', 'letter_subscribers', 'letter_sends', 'naver_cache', 'naver_usage', 'review_campaigns', 'articles'): db.execute('DELETE FROM ' + t)
            db.execute("DELETE FROM soboru_settings WHERE key LIKE 'letter%'")

    def letter_ai(self, sent, bad=True):
        """가짜 OpenAI: 받은 뉴스마다 우리 말 설명을 씀. bad면 2번에 자료에 없는 숫자, 3번에 기사 제목을 그대로 옮김."""
        def fake(url, headers, body, timeout):
            sent.append(body)
            content = body['messages'][1]['content']
            if '[이번 호 뉴스]' not in content:  # 검토 필요 고치기(autofix) 요청: 여기선 고치지 않음
                return 200, {'choices': [{'message': {'content': json.dumps({'fixes': []})}}]}
            news = json.loads(content.split('[이번 호 뉴스]\n', 1)[1].split('\n[에디터 코멘트 자료]', 1)[0])
            cm = json.loads(content.split('[에디터 코멘트 자료]\n', 1)[1].split('\n[한 줄 뉴스]', 1)[0])
            briefs = json.loads(content.split('[한 줄 뉴스]\n', 1)[1].split('\n[피해 예방 뉴스]', 1)[0])
            harm = json.loads(content.split('[피해 예방 뉴스]\n', 1)[1].split('\n[소비 트렌드 뉴스]', 1)[0])
            buzz = json.loads(content.split('[소비 트렌드 뉴스]\n', 1)[1].split('\n[소보루에', 1)[0])
            items = []
            for x in news:
                n = x['번호']
                text = f'이번 주에 이런 소식이 있었어요. 비슷한 일을 겪은 분이 많대요. 자세한 내용은 기사 원문에서 확인해 보세요.'
                if n == 1: text += ' 관련 상담이 30% 늘었다고 해요.'
                if bad and n == 2: text += ' 작년보다 98765명 늘었대요.'
                if bad and n == 3: text += ' ' + x['제목'] + ' ' + x['요약'] + ' 이런 기사였어요.'
                law = x['법 조문 후보'][0]['id'] if n == 1 and x['법 조문 후보'] else ('9-L9' if n == 2 else '')
                items.append({'no': n, 'title': ['첫째', '둘째', '셋째', '넷째', '다섯째', '여섯째'][n - 1] + ' 소식, 이것만 알면 돼요', 'body': text, 'tip': '이럴 땐 이렇게: 영수증과 대화 기록부터 챙겨 두세요.', 'law': law})
            out = {'subject': '소보루 브리핑: 이번 주 소비자 뉴스, 이것만 보면 끝', 'intro': '안녕하세요, 소보루 레터예요. 이번 주 꼭 알아 둘 소식을 모았어요.', 'outro': '다음 주에 또 만나요.', 'items': items,
                   'number': {'no': 1, 'value': '30%', 'label': '늘어난 상담', 'body': '관련 상담이 그만큼 늘었다는 뜻이에요.'},
                   'harm': {'title': '요즘 늘어난 환불 거절', 'body': '환불을 미루는 일이 늘고 있어요. 대화 기록을 꼭 남겨 두세요.',
                            'steps': ['주문·결제 화면을 캡처해 두세요.', '판매자에게 기록이 남게 요청하세요.', '1372 소비자상담센터에 상담해요.'] + (['14일 안에 꼭 하세요.'] if bad else []),
                            'law': harm[0]['법 조문 후보'][0]['id'] if harm and harm[0]['법 조문 후보'] else ''},
                   'lawbox': {'title': '온라인 쇼핑은 7일 안에 물릴 수 있어요', 'body': '물건을 받은 날부터 7일 안이면 청약철회를 할 수 있어요.', 'point': '받은 날부터 7일, 기억해요.', 'law': 'B-L1'},
                   'comment': {'photo': 'Interest-rate 2026 bank!', 'title': '오늘의 큰 이슈, 무슨 일이야?', 'lead': '요즘 이 소식이 계속 들려요. 내 생활엔 무슨 일이 생길까요?',
                               'what': {'body': '이런 일이 있었어요.', 'points': [{'name': '첫째', 'text': '이런 일이 있었어요.'}, {'name': '', 'text': '이름 없는 건 빼요'}]},
                               'why': {'body': '여러 이유가 겹쳤다고 해요.' + (' 피해액은 777억 원이래요.' if bad else '')},
                               'wallet': {'body': '내 생활에도 영향이 있어요.', 'points': [{'name': '대출', 'text': '이자 부담을 확인해 보세요.'}]}} if cm else None,
                   'buzz': {'title': '요즘 뜨는 소비 트렌드', 'body': '요즘 이런 물건이 잘 팔려요.', 'points': [{'name': '편의점 신상', 'text': '관련 상담이 30% 늘었다고 해요.'}, {'name': '', 'text': '빈 이름'}]} if buzz else None,
                   'briefs': [{'no': b['번호'], 'line': '이런 경제 소식도 있었어요' + (' (작년보다 4321억 원)' if bad and k == 1 else '')} for k, b in enumerate(briefs)] + [{'no': 'B99', 'line': '없는 번호'}]}
            return 200, {'choices': [{'message': {'content': json.dumps(out, ensure_ascii=False)}}]}
        return fake

    def letter_related(self, text, limit=4, laws=None):
        return [{'ref': 'ecom:제17조', 'label': '전자상거래법 제17조', 'title': '청약철회등', 'text': '제17조(청약철회등) 소비자는 계약내용에 관한 서면을 받은 날부터 7일 이내에 청약철회를 할 수 있다.',
                 'law': '전자상거래법', 'source': 'https://www.law.go.kr/법령/전자상거래법/제17조'}]

    def letter_smtp(self, box):
        class FakeSMTP:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def starttls(self): pass
            def login(self, user, pw): pass
            def send_message(self, msg): box.append(msg)
        return FakeSMTP

    def letter_make(self, bad=True, article=None):
        sent, calls = [], []
        market = {'https://m.stock.naver.com/api/index/KOSPI/basic': {'closePrice': '5,937.66', 'compareToPreviousClosePrice': '-74.78', 'fluctuationsRatio': '-1.24', 'compareToPreviousPrice': {'name': 'FALLING'}, 'localTradedAt': '2026-10-30T15:30:00+09:00'},
                  'https://m.stock.naver.com/api/stocks/marketValue/KOSPI?page=1&pageSize=10': {'stocks': [{'stockName': f'종목{k}', 'closePrice': f'{k},000', 'compareToPreviousClosePrice': '100', 'fluctuationsRatio': '1.5', 'compareToPreviousPrice': {'name': 'RISING'}} for k in range(1, 13)] + [{'stockName': '깨진 값'}]},
                  'https://m.stock.naver.com/front-api/marketIndex/productDetail?category=exchange&reutersCode=FX_USDKRW': {'result': {'closePrice': '1,336.80', 'fluctuations': '0.90', 'fluctuationsRatio': '0.07', 'fluctuationsType': {'name': 'RISING'}}}}
        with patch.dict(os.environ, self.LETTER_NAVER), patch.object(self.site.naverhub, 'http', self.writer_naver(calls)), patch.object(self.site.soboru_letter, 'market_call', market.get), patch.object(self.site.soboru_letter, 'TREND_DAYS', tuple(range(7))), \
                patch.object(self.site.companydesk, 'post_json', self.letter_ai(sent, bad)), patch.object(self.site.triage.corpus, 'related', self.letter_related), \
                patch.object(self.site.soboru_letter, 'article_call', article or (lambda url, timeout=8: (200, '<html><article id="dic_area" class="go_trans">본문 첫 줄 30% 늘었다<br>둘째 줄 무단 전재 금지<br>셋째 줄 1만 2000명</article></div></html>'))):
            r = self.site.app.extensions['soboru_letter']['generate']('admin')
        return r, sent

    def letter_post(self, client, data):
        return client.post('/letter/subscribe', data={'_csrf': self.csrf(client, '/letter'), **data})

    def letter_subs(self, rows):
        with self.site.conn() as db:
            for email, status in rows:
                db.execute('INSERT INTO letter_subscribers(email,token,status,created) VALUES(?,?,?,?)', (email, 'tok-' + email.split('@')[0], status, '2026-10-01T09:00:00'))

    def test_signup_optional_letter_consent(self):
        # 가입 화면 '[선택] 레터 받기' (운영자 요청 2026-11-01): 선택 항목이라 체크 안 하면 구독 없음.
        # 직접 친 메일은 확인 메일을 눌러야 구독, 확인된 메일(카카오 등)은 바로 구독 + 수신 동의 안내 메일
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        page = self.client.get('/signup').get_data(as_text=True)
        self.assertIn('name="agree_letter"', page); self.assertNotIn('name="agree_letter" required', page); self.assertIn('[선택]', page)
        mails = []; notify = self.site.notify
        with patch.object(notify, 'email_ready', return_value=True), patch.object(notify, 'send_email', side_effect=lambda *a, **k: mails.append(a)):
            self.signup(self.site.app.test_client(), login_id='no_letter', nickname='레터안받음', email='no@example.com')
            self.signup(self.site.app.test_client(), login_id='yes_letter', nickname='레터받음', email='Yes@Example.com', agree_letter='on')
            with self.site.app.test_request_context('/auth/join'): self.site.app.extensions['soboru_letter']['join']('kakao@example.com', True)
        with self.site.conn() as db:
            rows = {r['email']: (r['status'], r['place']) for r in db.execute('SELECT * FROM letter_subscribers')}
        self.assertEqual(rows, {'yes@example.com': ('pending', 'signup'), 'kakao@example.com': ('active', 'signup')})
        self.assertEqual([m[0] for m in mails], ['yes@example.com', 'kakao@example.com'])
        self.assertIn('구독 확인', mails[0][1]); self.assertIn('수신 동의 안내', mails[1][1])
        self.assertIn('동의한 날', mails[1][2]); self.assertIn('/letter/unsubscribe/', mails[1][2])

    def test_letter_generation_checks_numbers_copy_and_links(self):
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        now = datetime.datetime.now().isoformat(timespec='seconds')
        with self.site.conn() as db:
            for i, (nick, likes, editor) in enumerate([('알뜰한다람쥐', 9, 0), ('에디터', 99, 1), ('꼼꼼소비', 3, 0)]):
                db.execute("INSERT INTO posts(category,nickname,pw_hash,title,body,ip_hash,created,kind,target,rating,likes,editor,pros) VALUES('경험 공유',?,'x',?,'본문','x',?,'review','오소보쇼핑',4,?,?,?)",
                           (nick, f'리뷰 {i} 연락처 010-1234-5678', now, likes, editor, '환불이 빨랐어요'))
            db.execute("INSERT INTO articles(title,summary,status,created,updated,published_at) VALUES('택배 분실 보상 정리','운송장 금액 기준이에요','published',?,?,?)", (now, now, now))
            db.execute("INSERT INTO articles(title,status,created,updated) VALUES('아직 초안','draft',?,?)", (now, now))
            db.execute("INSERT INTO review_campaigns(slug,title,topic,active,created) VALUES('delivery','배달음식 리뷰 모아요','배달',1,?)", (now,))
        r, sent = self.letter_make(bad=True)
        self.assertEqual(r['status'], 'made', r)
        L = self.site.app.extensions['soboru_letter']['get'](r['id'])
        self.assertEqual((L['no'], L['status']), (1, 'draft'))
        self.assertEqual(len(L['items']), 3)  # 오늘의 뉴스 3~6개: 같은 소식 기사가 몰린 게 없으면 최소 3개
        # AI에는 제목·요약 조각만 (기사 주소·연락처는 넘기지 않음), 기사 문장을 옮기지 말라고 함
        prompt = sent[0]['messages'][1]['content']
        self.assertNotIn('news.example.co.kr', prompt); self.assertNotIn('010-5555-6666', prompt)
        self.assertIn('기사 문장을 옮기지 말고', sent[0]['messages'][0]['content'])
        self.assertEqual(sent[0]['response_format'], {'type': 'json_object'})
        it1, it2 = L['items'][0], L['items'][1]
        self.assertIn('30% 늘었다고 해요', it1['body'])
        self.assertTrue(it1['src']['url'].startswith('https://news.example.co.kr/'))
        self.assertEqual(it1['law']['label'], '전자상거래법 제17조')  # 후보 중에서 고름
        self.assertIsNone(it2['law'])  # 후보에 없는 id는 버림
        self.assertEqual(it1['tip'], '영수증과 대화 기록부터 챙겨 두세요.')
        # 검사: 2번의 자료에 없는 숫자, 3번의 기사 제목 그대로 옮기기 → 검토 필요
        self.assertFalse(L['check_ok'])
        self.assertIn({'where': '2번 뉴스', 'numbers': ['98765명']}, [{k: p[k] for k in ('where', 'numbers') if k in p} for p in L['problems']])
        self.assertTrue(any(p.get('copy') and p['where'] == '3번 뉴스' for p in L['problems']))
        self.assertFalse([p for p in L['problems'] if p['where'] == '1번 뉴스'])  # 30%는 요약에 있는 숫자
        # 아래 묶음: 에디터 리뷰는 빼고 공감 순, 연락처는 가림, 게시한 생활정보만, 진행 중인 리뷰 주제
        # 정보성 콘텐츠만 (운영자 2026-11-01): 리뷰·리뷰 주제는 빼고, 숫자·피해 예방·법률·용어 칸과 게시한 매거진 글
        sec = L['sections']
        self.assertNotIn('reviews', sec); self.assertNotIn('campaign', sec)
        self.assertNotIn('010-1234-5678', json.dumps(sec, ensure_ascii=False))
        self.assertEqual([a['title'] for a in sec['life']], ['택배 분실 보상 정리'])
        self.assertEqual((sec['number']['value'], sec['number']['label']), ('30%', '늘어난 상담'))
        self.assertEqual(sec['harm']['law']['label'], '전자상거래법 제17조'); self.assertTrue(sec['harm']['srcs'])
        self.assertEqual(sec['lawbox']['law']['label'], '전자상거래법 제17조'); self.assertEqual(sec['lawbox']['topic'], self.site.soboru_letter.LAW_TOPICS[0][0])
        self.assertEqual(sec['word']['word'], self.site.soboru_tools.DICT[0][0])
        self.assertEqual(L['title'], '이번 주 소비자 뉴스, 이것만 보면 끝')  # '소보루 브리핑' 같은 고정 이름은 뗌
        self.assertIn({'where': '소비자 피해 예방', 'numbers': ['14']}, [{k: p[k] for k in ('where', 'numbers') if k in p} for p in L['problems']])
        self.assertFalse([p for p in L['problems'] if p['where'] in ('숫자로 보는 오늘', '법률·제도')])  # 30%·7일은 자료에 있는 숫자
        c = sec['comment']  # 에디터 코멘트 (뉴닉식): 이름 없는 요점은 빼고, 자료에 없는 숫자는 검토 필요
        self.assertEqual(c['title'], '오늘의 큰 이슈, 무슨 일이야?'); self.assertEqual([p['name'] for p in c['what']['points']], ['첫째']); self.assertTrue(c['srcs'])
        self.assertIn({'where': '에디터 코멘트', 'numbers': ['777']}, [{k: p[k] for k in ('where', 'numbers') if k in p} for p in L['problems']])
        # 메일: HTML(표·인라인)과 글 두 가지, 원문·법령 링크, 해지 링크
        subject, html, text = self.site.app.extensions['soboru_letter']['email_parts'](L, 'tok-x')
        icon = self.site.soboru_letter.TOPIC_ICON[it1['topic']][0]  # 분야를 남겨 분야 그림(토스페이스)을 붙임
        self.assertIn('editor-croissant.png', html)  # 에디터 크로와상 그림
        self.assertLess(html.index('alt="SOBORU 소보루 레터"'), html.index('editor-croissant.png'))  # 머리는 귤색 SOBORU 로고(운영자 2026-11-05), 캐릭터는 아래에서만
        self.assertNotIn('>소보루 레터</span>', html); self.assertTrue(subject.startswith('🍞[소보루 레터]'))
        self.assertIn('이번 주 소비자 뉴스, 이것만 보면 끝', subject)
        for part in (html, text):
            self.assertIn('첫째 소식, 이것만 알면 돼요', part); self.assertIn(it1['src']['url'], part)
            self.assertIn('/letter/unsubscribe/tok-x', part); self.assertIn('https://www.law.go.kr/', part)
        self.assertIn('max-width:680px', html); self.assertIn('원문 보기 ›', html); self.assertNotIn('써 본 사람들이 추천한 리뷰', html)
        for part in (html, text):
            for word in ('이것만 쓱', '⚡', '👀', 'EDITOR\'S COMMENT'):  # 뉴닉 문구·이모지 X (운영자 2026-11-01)
                self.assertNotIn(word, html)
            for word in ('갓 구운 오늘의 뉴스', '오늘의 메인 뉴스', '한 입에 정리하면', '요즘 뜨는 소비 트렌드', '편의점 신상', '5,937.66', '▼ 74.78 (-1.24%)', '▲ 0.90 (+0.07%)', '직전 거래일', '코스피 시가총액 TOP 10', '종목10', '+1.50%', 'by. 에디터 크로와상', '거부하지 않으시면 계속 보내 드릴게요', '숫자로 보는 오늘', '소비자 피해 예방', '알아두면 좋은 법률·제도', '오늘의 경제 용어', '수신거부', 'Unsubscribe', 'SOBORU', '매일 아침'):
                self.assertIn(word, part)
        self.assertLess(html.index('id="n1"'), html.index('id="num"')); self.assertLess(html.index('id="num"'), html.index('id="harm"')); self.assertLess(html.index('id="harm"'), html.index('id="law"'))
        self.assertIn('서울시 강남구', html)  # 보내는 곳 주소 (사이트 하단 정보)
        # 운영자가 고쳐 저장하면 같은 자료로 다시 검사
        admin = self.login_admin()
        page = admin.get(f"/admin/letter/{r['id']}").get_data(as_text=True)
        self.assertIn('srcdoc=', page); self.assertIn('검토 필요', page)
        form = {'title': L['title'], 'intro': L['intro'], 'outro': L['outro'], 'act': 'save'}
        for i, it in enumerate(L['items']): form.update({f'title{i}': it['title'], f'body{i}': it['body'], f'tip{i}': it['tip']})
        form['body1'] = '숫자 없이 고쳤어요.'; form['drop2'] = '1'
        form['harm_steps'] = '주문 화면을 캡처해 두세요.\n1372 소비자상담센터에 상담해요.'; form['drop_number'] = '1'
        form['comment_why'] = '여러 이유가 겹쳤다고 해요.'
        admin.post(f"/admin/letter/{r['id']}", data={'_csrf': self.csrf(admin, f"/admin/letter/{r['id']}"), **form})
        L = self.site.app.extensions['soboru_letter']['get'](r['id'])
        self.assertEqual(len(L['items']), 2); self.assertTrue(L['check_ok'], L['problems'])
        self.assertNotIn('number', L['sections']); self.assertEqual(len(L['sections']['harm']['steps']), 2); self.assertEqual(L['sections']['comment']['why']['body'], '여러 이유가 겹쳤다고 해요.')

    def test_letter_stibee_api_send(self):
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        r, _ = self.letter_make(bad=False)
        admin = self.login_admin()
        admin.post('/admin/letter/settings', data={'_csrf': self.csrf(admin, '/admin/letter'), 'freq': 'daily', 'via': 'stibee', 'stibee_list': '4321',
                                                   'stibee_sender': 'contact@consumerjebo.co.kr', 'stibee_name': '소보루 레터'})
        cfg = self.site.app.extensions['soboru_letter']['settings']()
        self.assertEqual((cfg['via'], cfg['stibee_list'], cfg['stibee_sender']), ('stibee', 4321, 'contact@consumerjebo.co.kr'))
        self.assertIn('스티비로 보내기', admin.get(f"/admin/letter/{r['id']}").get_data(as_text=True))
        calls = []
        def fake(method, path, body=None, ctype='application/json'):
            calls.append((method, path, body, ctype))
            return (200, '{"id": 777}') if path == '/emails' else (200, 'ok')
        send = self.site.app.extensions['soboru_letter']['send']
        with patch.dict(os.environ, {'STIBEE_API_KEY': ''}):
            self.assertIn('API 키', send(r['id'])['reason'])
        with patch.dict(os.environ, {'STIBEE_API_KEY': 'stb-test'}), patch.object(self.site.soboru_letter, 'stibee_call', fake):
            self.assertEqual(send(r['id'])['status'], 'sent')
        self.assertEqual([c[:2] for c in calls], [('POST', '/emails'), ('POST', '/emails/777/content'), ('POST', '/emails/777/send')])
        self.assertEqual(calls[0][2]['listId'], 4321); self.assertTrue(calls[0][2]['subject'].startswith('🍞[소보루 레터]'))
        self.assertEqual(calls[1][3], 'text/html'); self.assertIn('$%unsubscribe%$', calls[1][2]); self.assertIn('<body>', calls[1][2])
        L = self.site.app.extensions['soboru_letter']['get'](r['id'])
        self.assertEqual((L['status'], L['trigger'], L['stibee_id']), ('sent', 'stibee', 777))
        with self.site.conn() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM letter_sends').fetchone()[0], 0)  # 사이트 구독자에게는 안 보냄

    def test_letter_stibee_subscriber_sync(self):
        # 보내는 곳이 스티비면 사이트 구독·해지가 스티비 주소록에도 반영되고, 기존 구독자는 버튼으로 한 번에 옮김 (운영자 2026-11-01)
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        admin = self.login_admin()
        admin.post('/admin/letter/settings', data={'_csrf': self.csrf(admin, '/admin/letter'), 'freq': 'daily', 'via': 'stibee', 'stibee_list': '55',
                                                   'stibee_sender': 'contact@consumerjebo.co.kr', 'stibee_name': '소보루 레터'})
        self.letter_subs([('old1@example.com', 'active'), ('old2@example.com', 'active'), ('wait@example.com', 'pending')])
        calls = []
        def fake(method, path, body=None, ctype='application/json', base=None):
            calls.append((method, (base or '') + path, body))
            return (404, 'no') if base and base.endswith('/v2') else (200, '{"Ok": true}')
        with patch.dict(os.environ, {'STIBEE_API_KEY': 'stb-test'}), patch.object(self.site.soboru_letter, 'stibee_call', fake):
            page = admin.get('/admin/letter').get_data(as_text=True)
            self.assertIn('사이트 구독자 2명 스티비 주소록으로 옮기기', page)
            admin.post('/admin/letter/stibee-sync', data={'_csrf': self.csrf(admin, '/admin/letter')})
            self.assertEqual(calls[-1][:2], ('POST', 'https://api.stibee.com/v1/lists/55/subscribers'))  # v2에 없으면 v1로
            self.assertEqual(sorted(x['email'] for x in calls[-1][2]['subscribers']), ['old1@example.com', 'old2@example.com'])
            self.assertEqual(calls[-1][2]['confirmEmailYN'], 'N')
            calls.clear()
            self.client.get('/letter/confirm/tok-wait')   # 확인 메일을 누르면 스티비에도 추가
            self.assertEqual([c[2]['subscribers'] for c in calls if c[0] == 'POST'][-1], [{'email': 'wait@example.com', 'soboru_sub': 'none'}])  # 구독자는 구독하기 버튼 숨김
            calls.clear()
            self.client.get('/letter/unsubscribe/tok-old1')   # 사이트에서 해지하면 스티비에서도 수신 거부
            self.assertEqual(calls[-1][:3], ('PUT', 'https://api.stibee.com/v1/lists/55/subscribers/unsubscribe', ['old1@example.com']))
        # 주소록에 구독 필드가 없어 거절되면 필드 없이 한 번 더 넣음
        calls.clear()
        def picky(method, path, body=None, ctype='application/json', base=None):
            calls.append((method, (base or '') + path, body))
            return (400, 'unknown field') if 'soboru_sub' in json.dumps(body) else (200, '{"Ok": true}')
        with patch.object(self.site.soboru_letter, 'stibee_call', picky):
            self.assertEqual(self.site.soboru_letter.stibee_subs('55', ['a@example.com']), (True, ''))
        self.assertEqual(calls[-1][2]['subscribers'], [{'email': 'a@example.com'}])
        with patch.dict(os.environ, {'STIBEE_API_KEY': ''}):
            r = admin.post('/admin/letter/stibee-sync', data={'_csrf': self.csrf(admin, '/admin/letter')}, follow_redirects=True)
            self.assertIn('API 키가 없어요', r.get_data(as_text=True))

    def test_letter_stibee_unsubscribe_webhook(self):
        # 스티비에서 수신 거부하면 웹훅으로 사이트 구독자도 해지, 비밀 열쇠 없는 주소는 막음, 구독 추가 알림은 무시 (운영자 2026-11-01)
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        self.letter_subs([('a1@example.com', 'active'), ('a2@example.com', 'active')])
        ext = self.site.app.extensions['soboru_letter']
        url = ext['stibee_hook_url']().split('soboru.co.kr', 1)[-1].split('://', 1)[-1]
        url = url[url.index('/letter/'):]
        self.assertEqual(self.client.post('/letter/stibee-hook/wrong', json={'action': 'unsubscribe', 'email': 'a1@example.com'}).status_code, 404)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url, json={'action': 'subscribe', 'subscribers': [{'email': 'a2@example.com'}]})
        self.client.post(url, json={'event': 'unsubscribe', 'data': {'subscribers': [{'email': 'A1@example.com'}]}})
        with self.site.conn() as db:
            st = dict(db.execute("SELECT token,status FROM letter_subscribers WHERE token IN ('tok-a1','tok-a2')").fetchall())
        self.assertEqual(st, {'tok-a1': 'unsubscribed', 'tok-a2': 'active'})
        r, _ = self.letter_make(bad=False)
        html = ext['email_parts'](ext['get'](r['id']), 'tok-x')[1]
        self.assertIn('id="$stb-htmlv3$"', html)   # 받은편지함 미리보기 문구
        self.assertIn('id="$stb-htmlv3$"', ext['stibee_html'](ext['get'](r['id'])))

    def test_letter_news_become_magazine_articles(self):
        # 갓 구운 오늘의 뉴스 한 꼭지마다 매거진 기사를 쓰고, 레터는 신뢰를 위해 늘 기사 원문으로 이어짐 (운영자 2026-11-01)
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        wr = self.site.app.extensions['soboru_writer']; calls = []
        with self.site.conn() as db:
            ids = [db.execute("INSERT INTO articles(title,summary,body,status,origin,ext_key,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                              (f'풀어 읽기 {k}', '요약', '본문', 'published' if k == 0 else 'draft', 'ai', f'test:issue:{k}', '2026-11-01', '2026-11-01')).lastrowid for k in range(6)]
        def drop():
            with self.site.conn() as db: db.execute("DELETE FROM articles WHERE ext_key LIKE 'test:issue:%'")
        self.addCleanup(drop)
        def fake(kind, trigger='admin', **kw):
            calls.append((kind, trigger, kw)); return {'status': 'made', 'id': ids[len(calls) - 1], 'published': len(calls) == 1}
        self.site.app.config['LETTER_ARTICLES'] = True
        self.addCleanup(self.site.app.config.pop, 'LETTER_ARTICLES', None)
        with patch.dict(wr, {'generate': fake}):
            r, _ = self.letter_make(bad=False)
        ext = self.site.app.extensions['soboru_letter']; L = ext['get'](r['id'])
        self.assertEqual(len(calls), len(L['items']))
        self.assertTrue(all(c[0] == 'issue' and c[1] == 'letter' and '오늘의 뉴스' in c[2]['material']['facts'] for c in calls))
        html = ext['email_parts'](L, 'tok-x')[1]
        self.assertNotIn('소보루에서 자세히 읽기', html)   # 매거진엔 올라가도 레터 링크는 기사 원문
        self.assertEqual(html.count('기사 원문 ›'), len(L['items']))

    def test_letter_reads_article_body(self):
        # 요약 조각만 보면 숫자를 지어내서, 네이버 뉴스 기사 본문까지 AI 자료·숫자 검사에 넣음 (운영자 2026-11-01)
        mod = self.site.soboru_letter
        page = '<div id="newsct_article"><em>사진 설명</em>코스피가 5,730선으로 마쳤다.<br/>&quot;외국인&quot; 매도<br>홍길동 기자 hong@ex.com</div><div>'
        with patch.object(mod, 'article_call', lambda url, timeout=8: (200, page)):
            self.assertEqual(mod.article_body('https://n.news.naver.com/a/1'), '코스피가 5,730선으로 마쳤다. "외국인" 매도')
            self.assertEqual(mod.article_body('https://news.example.co.kr/1'), '')   # 네이버 뉴스 주소만
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        r, sent = self.letter_make(bad=False)
        L = self.site.app.extensions['soboru_letter']['get'](r['id'])
        self.assertIn('셋째 줄 1만 2000명', L['items'][0]['_facts']['기사 본문'])
        self.assertNotIn('무단', L['items'][0]['_facts']['기사 본문'])
        self.assertIn('기사 본문', sent[0]['messages'][-1]['content'] if isinstance(sent[0], dict) else json.dumps(sent[0], ensure_ascii=False))
        W = self.site.soboru_writer
        self.assertEqual(W.check_text('인텔은 52년 만의 최악 주가 폭락을 겪었다', {'기사': '52년'}), [])
        self.assertTrue(W.check_text('최악의 기업이다', {}))
        # 운영자 2026-11-05: 매거진도 언론 — 다른 언론을 출처로 들거나 '자료에 없어 알 수 없다'고 쓰면 검토 필요로
        self.assertTrue(W.check_text('최근 보도에 따르면 여기어때는 상품을 늘렸다.', {}))
        self.assertTrue(W.check_text('자료에는 검색어 트렌드의 실제 수치가 없어 관심이 얼마나 커졌는지는 알 수 없다.', {}))
        self.assertEqual(W.check_text('여행업계에 따르면 상품이 늘었다. 한국소비자원 자료에는 피해 사례가 담겼다.', {}), [])
        self.assertIn('보도에 따르면', W.SYSTEM); self.assertNotIn('자료만으로는 알 수 없다"라고 쓴다', W.SYSTEM)

    def test_letter_autofix_links_number_source(self):
        # 검토 필요를 사람이 안 봐도 되게 (운영자 2026-11-01): 자료에 없는 숫자는 네이버에서 그 숫자가 나온 기사를 찾아 링크(뉴닉처럼), 숫자는 그대로
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        mod = self.site.soboru_letter
        known = set(mod.LETTER_QUERIES + mod.HARM_QUERIES + mod.TREND_QUERIES + mod.ECON_QUERIES + mod.POLICY_QUERIES)
        def call(url, timeout=8):
            q = url.split('n.news.naver.com/', 1)[-1].split('/', 1)[0]
            if q in known: return 200, '<div id="dic_area">상담이 30% 늘었다. 1만 2000명</div><div>'
            return 200, '<div id="dic_area">올해 상담 건수가 98765명으로 집계됐다.</div><div>'
        r, sent = self.letter_make(bad=True, article=call)
        L = self.site.app.extensions['soboru_letter']['get'](r['id'])
        self.assertFalse([p for p in L['problems'] if '98765명' in p.get('numbers', [])])   # 출처를 찾아 통과
        self.assertTrue(any(l['text'].startswith('98765') for l in L['sections']['_links']))
        html = self.site.app.extensions['soboru_letter']['email_parts'](L, 'tok-x')[1]
        self.assertRegex(html, r'<a href="https://[^"]+"[^>]*>98765')   # 본문 속 숫자에 기사 링크

    def test_letter_feedback_votes(self):
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        with self.site.conn() as db: db.execute('DELETE FROM letter_feedback')
        r, _ = self.letter_make(bad=False)
        L = self.site.app.extensions['soboru_letter']
        html = L['email_parts'](L['get'](r['id']), 'tok-x')[1]
        self.assertIn(f"/letter/{r['no']}/fb/good", html); self.assertIn('오늘의 레터는 어땠나요?', html); self.assertIn('소보루 레터 구독하기', html)
        self.assertEqual(self.client.get(f"/letter/{r['no']}/fb/good").status_code, 302)
        self.client.get(f"/letter/{r['no']}/fb/meh")   # 같은 사람은 마지막 표만
        self.assertEqual(self.client.get(f"/letter/{r['no']}/fb/bad").status_code, 404)
        st = L['stats'](r['id'])
        self.assertEqual((st['good'], st['meh']), (0, 1))

    def test_magazine_unsplash_cover(self):
        # 운영자 2026-11-04: 사진을 안 올린 매거진 글은 언스플래시 사진 (키 없으면 글자 표지), 기사 화면에 작가 이름
        with self.site.conn() as db:
            aid = db.execute("INSERT INTO articles(title,summary,body,category,status,created,updated,published_at) VALUES('알뜰폰 고르는 법','요약','본문','통신','published','2026-11-04','2026-11-04','2026-11-04T09:00:00')").lastrowid
        def fake(path, params=None):
            if path.startswith('http'): return 200, {}
            return 200, {'results': [{'id': 'm-%d' % i, 'urls': {'raw': 'https://images.unsplash.com/photo-m%d?ixid=x' % i}, 'user': {'name': '박작가', 'links': {'html': 'https://unsplash.com/@park'}},
                                      'links': {'download_location': 'https://api.unsplash.com/photos/m/download'}} for i in range(40)]}
        c = self.site.app.test_client()
        with patch.object(self.site.soboru_letter, 'unsplash_call', fake), patch.dict(os.environ, {'UNSPLASH_ACCESS_KEY': 'us-test'}):
            c.get('/letter')
            for _ in range(50):
                with self.site.conn() as db:
                    if db.execute('SELECT 1 FROM mag_unsplash2 WHERE article_id=?', (aid,)).fetchone(): break
                threading.Event().wait(0.1)
        page = c.get(f'/life/{aid}', headers={'Host': 'soboru.co.kr'}).get_data(as_text=True)
        self.assertIn('class="ma-page"', page)
        self.assertIn('images.unsplash.com/photo-m', page); self.assertIn('박작가', page)
        lst = c.get('/life?category=통신', headers={'Host': 'soboru.co.kr'})
        self.assertEqual(lst.status_code, 200); self.assertIn('class="ml-page"', lst.get_data(as_text=True))
        r = c.get(f'/life/{aid}', headers={'Host': 'consumerjebo.co.kr'})
        self.assertEqual(r.status_code, 301); self.assertTrue(r.headers['Location'].startswith('https://soboru.co.kr/life/'))
        self.assertIn('mag-favicon.png', page)
        with self.site.conn() as db: db.execute('DELETE FROM mag_unsplash2'); db.execute('DELETE FROM articles WHERE id=?', (aid,))

    def test_magazine_restyle_and_title_photo(self):
        # 운영자 2026-11-05: 올라간 글을 잡지 기사체로 (숫자가 바뀌면 안 바꿈, 되돌리기 가능), 사진은 기사 제목에 맞는 검색어로
        with self.site.conn() as db:
            ok = db.execute("INSERT INTO articles(title,summary,body,category,status,created,updated,published_at) VALUES('택시 호출료, 누구에게 가나요?','호출료가 올랐어요','첫 문단이에요. 3,000원이 들어요.\n\n> 💡 핵심이에요\n\n## 💳 호출 전에 확인해요\n\n- 영수증을 챙겨요','생활','published','2026-11-04','2026-11-04','2026-11-04T09:00:00')").lastrowid
            bad = db.execute("INSERT INTO articles(title,summary,body,category,status,created,updated,published_at) VALUES('전기요금 이야기','요약이에요','요금이 5% 올랐어요. 길게 쓴 본문이에요.','생활','published','2026-11-04','2026-11-04','2026-11-04T09:00:00')").lastrowid
        sent = []
        def ai(url, headers, body, timeout):
            sent.append(body); user = json.loads(body['messages'][1]['content'])
            if isinstance(user, list):  # 사진 검색어
                return 200, {'choices': [{'message': {'content': json.dumps({'q': {str(x['id']): 'taxi city night' for x in user}})}}]}
            if '택시' in user['title']:
                out = {'title': '택시 호출료는 누구에게 가나', 'summary': ['호출료가 올랐다'], 'body': '첫 문단이다. 3,000원이 든다.\n\n## 호출 전에 확인할 것\n\n- 영수증을 챙겨 둔다'}
            else: out = {'title': '전기요금 이야기', 'summary': ['요약'], 'body': '요금이 7% 올랐다. 길게 쓴 본문이다.'}
            return 200, {'choices': [{'message': {'content': json.dumps(out, ensure_ascii=False)}}]}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key'}), patch.object(self.site.companydesk, 'post_json', ai):
            admin = self.login_admin()
            admin.post('/admin/life/ai/restyle', data={'_csrf': self.csrf(admin, '/admin/life/ai')})
            first = sent[0]['messages'][1]['content']
            self.assertNotIn('💡', first); self.assertNotIn('💳', first)  # 핵심 상자·이모지는 AI에 보내기 전에 걷어 냄
            with self.site.conn() as db:
                a = db.execute('SELECT * FROM articles WHERE id=?', (ok,)).fetchone(); b = db.execute('SELECT * FROM articles WHERE id=?', (bad,)).fetchone()
            self.assertEqual(a['title'], '택시 호출료는 누구에게 가나'); self.assertIn('## 호출 전에 확인할 것', a['body'])
            self.assertIn('5%', b['body'])  # 숫자가 달라진 글은 그대로
            page = admin.get('/admin/life/ai').get_data(as_text=True); self.assertIn('숫자가 달라짐', page)
            # 운영자 2026-11-05 (2차): 1차(기사체)로 바꾼 글도 피처 문체로 한 번 더, 되돌리기용 원문은 맨 처음 글 그대로
            with self.site.conn() as db: db.execute('UPDATE life_restyle_ver SET ver=1 WHERE article_id=?', (ok,))
            n = len(sent); admin.post('/admin/life/ai/restyle', data={'_csrf': self.csrf(admin, '/admin/life/ai')})
            self.assertTrue(any('택시' in json.loads(x['messages'][1]['content']).get('title', '') for x in sent[n:] if x['messages'][1]['content'].startswith('{')))
            with self.site.conn() as db:
                self.assertEqual(db.execute('SELECT ver FROM life_restyle_ver WHERE article_id=?', (ok,)).fetchone()[0], 3)
                self.assertEqual(db.execute('SELECT title FROM life_restyle WHERE article_id=?', (ok,)).fetchone()[0], '택시 호출료, 누구에게 가나요?')
            # 운영자 2026-11-05 (3차): '최근 보도에 따르면'·'자료에 없어 알 수 없다' 문장이 있는 글만 다시 AI로, 없는 글은 번호만 올림
            with self.site.conn() as db: db.execute('UPDATE life_restyle_ver SET ver=2 WHERE article_id=?', (ok,))
            n = len(sent); admin.post('/admin/life/ai/restyle', data={'_csrf': self.csrf(admin, '/admin/life/ai')})
            self.assertFalse([x for x in sent[n:] if '택시' in x['messages'][1]['content']])
            with self.site.conn() as db:
                self.assertEqual(db.execute('SELECT ver FROM life_restyle_ver WHERE article_id=?', (ok,)).fetchone()[0], 3)
                db.execute('UPDATE life_restyle_ver SET ver=2 WHERE article_id=?', (ok,)); db.execute("UPDATE articles SET body=body||'\n\n최근 보도에 따르면 요금이 바뀌었다.' WHERE id=?", (ok,))
            n = len(sent); admin.post('/admin/life/ai/restyle', data={'_csrf': self.csrf(admin, '/admin/life/ai')})
            self.assertTrue([x for x in sent[n:] if '택시' in x['messages'][1]['content']])
            self.assertIn('다른 언론을 출처로', sent[-1]['messages'][0]['content'])
            admin.post('/admin/life/ai/restyle', data={'_csrf': self.csrf(admin, '/admin/life/ai'), 'act': 'undo'})
            with self.site.conn() as db: self.assertEqual(db.execute('SELECT title FROM articles WHERE id=?', (ok,)).fetchone()[0], '택시 호출료, 누구에게 가나요?')
            qs = []
            def fake(path, params=None):
                if path.startswith('http'): return 200, {}
                qs.append(params['query'])
                return 200, {'results': [{'id': 't-%d-%d' % (len(qs), i), 'urls': {'raw': 'https://images.unsplash.com/photo-t?x'}, 'user': {'name': '작가', 'links': {'html': 'https://unsplash.com/@a'}}, 'links': {}} for i in range(3)]}
            with patch.object(self.site.soboru_letter, 'unsplash_call', fake), patch.dict(os.environ, {'UNSPLASH_ACCESS_KEY': 'us-test'}):
                admin.post('/admin/art/unsplash', data={'_csrf': self.csrf(admin, '/admin/art'), 'redo': '1'})
            self.assertIn('taxi city night', qs)
        with self.site.conn() as db:
            db.execute('DELETE FROM mag_unsplash2'); db.execute('DELETE FROM life_restyle'); db.execute('DELETE FROM life_restyle_ver'); db.execute('DELETE FROM articles WHERE id IN (?,?)', (ok, bad))

    def test_magazine_admin_space_cms_and_front(self):
        # 운영자 2026-11-05: 관리자 위쪽 전환 버튼(소비자제보센터 ↔ 소보루 매거진), 메뉴 안 겹침, 기사 CMS(대표 사진·본문 사진·예약), 첫 화면 편집
        import io
        from PIL import Image
        def png():
            b = io.BytesIO(); Image.new('RGB', (40, 30), (200, 120, 20)).save(b, 'PNG'); b.seek(0); return b
        admin = self.login_admin()
        jebo = admin.get('/admin').get_data(as_text=True)
        self.assertIn('/admin/choose', jebo)  # 운영자 2026-11-05: 위쪽 전환 버튼 대신 '관리할 곳 바꾸기'
        self.assertIn('ch-mag', admin.get('/admin/choose').get_data(as_text=True))
        self.assertNotIn('>소보루 레터<', jebo)  # 레터는 매거진 쪽으로
        home = admin.get('/admin/magazine').get_data(as_text=True)
        self.assertIn('Magazine Studio', home); self.assertIn('mag-studio', home); self.assertIn('화면 편집', home); self.assertNotIn('제보 처리', home)
        tok = self.csrf(admin, '/admin/life')
        r = admin.post('/admin/life', data={'_csrf': tok, 'title': '예약 기사', 'summary': '요약', 'body': '본문', 'category': '생활', 'act': 'schedule',
                                            'publish_at': '2099-01-01T09:00', 'cover': (png(), 'c.png', 'image/png')}, content_type='multipart/form-data')
        aid = int(re.search(r'/admin/life/(\d+)', r.headers['Location'])[1])
        with self.site.conn() as db:
            a = db.execute('SELECT status,published_at FROM articles WHERE id=?', (aid,)).fetchone()
            self.assertEqual((a['status'], a['published_at']), ('scheduled', '2099-01-01T09:00:00'))
            self.assertTrue(db.execute("SELECT 1 FROM soboru_art WHERE kind='life' AND target_id=? AND file LIKE '%-photo-%'", (aid,)).fetchone())
        self.assertEqual(self.client.get(f'/life/{aid}', headers={'Host': 'soboru.co.kr'}).status_code, 404)  # 예약 글은 아직 안 보임
        j = admin.post('/admin/magazine/photo', data={'_csrf': tok, 'photo': (png(), 'b.png', 'image/png')}, content_type='multipart/form-data').get_json()
        self.assertTrue(j['ok']); self.assertTrue(j['url'].startswith('/art/body/body-'))
        self.assertEqual(admin.get(j['url']).status_code, 200)
        with self.site.app.test_request_context('/'):
            html = str(self.site.app.jinja_env.globals['life_body'](f"앞 문단\n\n[사진 {j['url']} | 시장 풍경]\n\n[사진 javascript:alert(1)]"))
        self.assertIn('<figure class="sb-fig"><img src="' + j['url'], html); self.assertIn('<figcaption>시장 풍경</figcaption>', html); self.assertNotIn('javascript', html.split('</figure>')[0])
        r = admin.post('/admin/magazine/front', data={'_csrf': tok, 'act': 'hero', 'hero': (png(), 'h.png', 'image/png')}, content_type='multipart/form-data')
        self.assertEqual(r.status_code, 302)
        with self.site.conn() as db:
            pid = db.execute("INSERT INTO articles(title,summary,body,category,status,created,updated,published_at) VALUES('고른 글','요약','본문','쇼핑','published','2020-01-01','2020-01-01','2020-01-01T09:00:00')").lastrowid
        admin.post('/admin/magazine/front', data={'_csrf': tok, 'act': 'hot', 'hot1': str(pid)})
        page = self.client.get('/letter').get_data(as_text=True)
        self.assertIn('/art/front/hero-1.webp', page); self.assertIn('고른 글', page)
        self.assertEqual(self.client.get('/art/front/hero.webp').status_code, 200)
        with self.site.conn() as db:
            db.execute("UPDATE articles SET published_at='2000-01-01T00:00:00' WHERE id=?", (aid,))
        import time as _t  # 예약 시각이 지나면 다음 요청 때 게시 (1분에 한 번 확인)
        with patch('mag_admin.time.time', return_value=_t.time() + 120): self.client.get('/letter')
        with self.site.conn() as db:
            self.assertEqual(db.execute('SELECT status FROM articles WHERE id=?', (aid,)).fetchone()[0], 'published')
            db.execute('DELETE FROM articles WHERE id IN (?,?)', (aid, pid)); db.execute("DELETE FROM soboru_settings WHERE key IN ('mag_hot','mag_hero','mag_heroes')")
            db.execute("DELETE FROM soboru_art WHERE kind='life' AND target_id IN (?,?)", (aid, pid))

    def test_magazine_mosaic_on_upload(self):
        # 운영자 2026-11-05: 얼굴 모자이크는 따로 쓰는 도구가 아니라, 기사에 사진·영상·대표 사진을 올릴 때 바로 거침
        admin = self.login_admin()
        self.assertEqual(admin.get('/admin/magazine/mosaic').headers['Location'], '/admin/life?new=1')
        self.assertNotIn('얼굴 모자이크', admin.get('/admin/magazine').get_data(as_text=True))
        page = admin.get('/admin/life?new=1').get_data(as_text=True)
        self.assertIn('mosaic.js', page); self.assertIn('MOSAIC_CFG', page); self.assertIn('vendor/mediapipe/', page); self.assertIn('id="mz-video"', page)
        js = (Path(self.site.__file__).parent / 'static/mosaic.js').read_text()
        for word in ('value="mute"', 'value="low"', '가리지 않고 그대로 넣기', 'vision_bundle.mjs'): self.assertIn(word, js)
        for f in ('vision_bundle.mjs', 'vision_wasm_internal.js', 'vision_wasm_internal.wasm', 'blaze_face_short_range.tflite'):
            self.assertTrue((Path(self.site.__file__).parent / 'static/vendor/mediapipe' / f).is_file(), f)
        # 영상: 나눠 올리고 저장 → [영상 주소 | 설명] 줄이 기사에서 영상으로 보임
        tok = self.csrf(admin, '/admin/life?new=1')
        mp4 = b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 2000
        self.assertEqual(self.client.post('/admin/magazine/video/upload?i=0', data=mp4, content_type='application/octet-stream').status_code, 400)  # CSRF·로그인 없으면 막음
        j = admin.post('/admin/magazine/video/upload?i=0', data=mp4[:1000], headers={'X-CSRFToken': tok}, content_type='application/octet-stream').get_json()
        admin.post(f"/admin/magazine/video/upload?i=1&job={j['job']}", data=mp4[1000:], headers={'X-CSRFToken': tok}, content_type='application/octet-stream')
        url = admin.post(f"/admin/magazine/video/save?job={j['job']}", headers={'X-CSRFToken': tok}).get_json()['url']
        self.assertRegex(url, r'^/art/video/video-\d{14}-\d{3}\.mp4$')
        r = self.client.get(url, headers={'Range': 'bytes=0-9'}); self.assertEqual(r.status_code, 206); self.assertEqual(r.mimetype, 'video/mp4')
        j = admin.post('/admin/magazine/video/upload?i=0', data=b'not a video at all', headers={'X-CSRFToken': tok}, content_type='application/octet-stream').get_json()
        self.assertEqual(admin.post(f"/admin/magazine/video/save?job={j['job']}", headers={'X-CSRFToken': tok}).status_code, 400)
        r = admin.post('/admin/life', data={'_csrf': tok, 'title': '영상 기사', 'summary': 's', 'body': f'첫 문단\n\n[영상 {url} | 매장 앞 모습]\n\n[영상 /etc/passwd | x]', 'category': '쇼핑', 'publish': '1'})
        aid = int(r.headers['Location'].rstrip('/').split('/')[-1])
        self.addCleanup(lambda: admin.post(f'/admin/life/{aid}', data={'_csrf': self.csrf(admin, f'/admin/life/{aid}'), 'title': 'x', 'act': 'delete'}))
        art = self.client.get(f'/life/{aid}', base_url='https://soboru.co.kr').get_data(as_text=True)
        self.assertIn(f'<video src="{url}" controls playsinline', art); self.assertIn('<figcaption>매장 앞 모습</figcaption>', art); self.assertNotIn('<video src="/etc/passwd"', art)

    def test_magazine_write_assist(self):
        # 운영자 2026-11-05: 기사 쓰기 AI 도움 — 초안·다듬기·맞춤법·제목·요약. 원문에 없는 숫자가 나온 답은 버림
        import mag_assist, companydesk
        admin = self.login_admin(); tok = self.csrf(admin, '/admin/life?new=1')
        page = admin.get('/admin/life?new=1').get_data(as_text=True)
        self.assertIn('id="mz-ai-open"', page); self.assertIn('data-act="draft"', page)
        reply, body_sent = {}, []
        def fake(url, headers, body, timeout):
            reply['sys'] = body['messages'][0]['content']; body_sent.append(body['messages'][1]['content'])
            return 200, {'choices': [{'message': {'content': json.dumps(reply['out'], ensure_ascii=False)}}]}
        self.enterContext(patch.object(companydesk, 'post_json', fake)); self.enterContext(patch.dict(os.environ, {'OPENAI_API_KEY': 'k'}))
        body = '치킨 한 마리 값이 3만 원에 가까워졌다. 배달비도 함께 올랐다. 가맹점도 사정이 있다.'
        call = lambda d: admin.post('/admin/magazine/assist', json=d, headers={'X-CSRFToken': tok})
        self.assertEqual(self.client.post('/admin/magazine/assist', json={'act': 'titles'}).status_code, 400)  # 로그인·CSRF 없으면 막음
        reply['out'] = {'titles': ['치킨 3만 원 시대', '치킨 5만 원 시대', '배달비의 셈법']}
        j = call({'act': 'titles', 'title': '', 'summary': '', 'body': body}).get_json()
        self.assertEqual(j['titles'], ['치킨 3만 원 시대', '배달비의 셈법'])  # 지어낸 5만은 빠짐
        self.assertIn('셈이다', reply['sys'])  # 매거진 문체 규칙을 함께 보냄
        reply['out'] = {'text': '치킨값이 7만 원이 된 셈이다.'}
        self.assertEqual(call({'act': 'polish', 'body': body}).status_code, 502)
        reply['out'] = {'text': '치킨 한 마리 값이 3만 원에 다가선 셈이다.'}
        self.assertIn('셈이다', call({'act': 'polish', 'body': body}).get_json()['text'])
        reply['out'] = {'title': '치킨', 'summary': '요약', 'body': '## 치킨에 진심인 나라\n\n2만 원이던 치킨이 3만 원이 됐다.'}
        j = call({'act': 'draft', 'note': '치킨값 3만 원, 배달비 인상, 가맹점 사정 취재 메모입니다.'}).get_json()
        self.assertTrue(j['ok']); self.assertIn('2', j['warn'])
        self.assertEqual(call({'act': 'draft', 'note': '짧음'}).status_code, 400)
        # 운영자 2026-11-05: 기사 하나 주면 우리 매거진 기사로 — 주소면 서버가 기사 글을 읽어 옴, 원 매체 이름·보도 인용은 쓰지 않게
        self.assertIn('data-act="rewrite"', page)
        story = '<html><head><meta property="og:title" content="수원 블랙박스 사고"></head><body><nav>메뉴</nav><div id="article-view-content-div"><p>11월 3일 오후 2시께 수원 오목천동의 한 교차로에서 사고가 났다.</p><p>운전자 A씨는 시속 5km도 안 되게 서행 중이었다고 말했다. 목격자들은 이전에도 비슷한 사고가 있었다고 했다. A씨는 보험사에 고의 사고인지 조사를 요청했다.</p><p>저작권자 © 신문 무단전재</p></div></body></html>'
        self.enterContext(patch('company_web_email.get', lambda u: story if u == 'https://news.example.com/a/1' else ''))
        reply['out'] = {'title': '차 앞으로 다가온 남성', 'summary': '요약', 'body': '## 교차로의 3분\n\n11월 3일 오후 2시께 일이다.'}
        j = call({'act': 'rewrite', 'note': 'https://news.example.com/a/1'}).get_json()
        self.assertTrue(j['ok']); self.assertEqual(j['warn'], ''); self.assertIn('보도에 따르면', reply['sys'])
        self.assertIn('원문 문장을 그대로 옮기지 않는다', reply['sys'])
        self.assertEqual(call({'act': 'rewrite', 'note': 'https://news.example.com/none'}).status_code, 400)
        self.assertEqual(call({'act': 'rewrite', 'note': '짧은 글'}).status_code, 400)
        txt = mag_assist.read_article('https://news.example.com/a/1')
        self.assertTrue(txt.startswith('수원 블랙박스 사고')); self.assertNotIn('저작권자', txt); self.assertNotIn('메뉴', txt)
        # 운영자 2026-11-05: 기사 넣으면 카드뉴스·릴스가 짜이게 — 기사 번호나 주소로, 기사 사진·영상 주소도 함께
        with self.site.conn() as db:
            db.execute("INSERT INTO articles(id,title,summary,body,category,status,created,updated) VALUES(99901,'차 앞으로 다가온 남성','요약','11월 3일 오후 2시께 수원 오목천동 교차로에서 서행하던 차 앞으로 한 남성이 다가왔다. 운전자 A씨는 시속 5km도 안 되게 서행 중이었다고 말했다.\n\n[사진 /art/body/body-20261105120000-001.webp | 사고 장면]\n\n[영상 /art/video/video-20261105120000-001.mp4]\n\n## 보험사에 조사 요청\n\nA씨는 보험사에 고의 사고인지 조사를 요청했다. 목격자들은 이전에도 비슷한 사고가 있었다고 했다.','자동차','published','2026-11-05','2026-11-05')")
        def clean_art():
            with self.site.conn() as db: db.execute('DELETE FROM articles WHERE id=99901')
        self.addCleanup(clean_art)
        # 운영자 2026-11-05 카드뉴스 원칙: 표지 문구 5개(낚시말 거름) · 본문 2~4장 · 마지막 장 저장 유도 + 출처 · 캡션 3줄 + 출처 + 해시태그
        reply['out'] = {'tag': 'CAR', 'big': '시속 5km', 'cover_scene': 'a crossroad at dusk',
                        'covers': [{'text': '이 남성,\n일부러였을까?', 'type': '비밀·희소'}, {'text': '충격적인\n교차로 사고', 'type': '경고·금지'}, {'text': '운전하는 친구한테\n꼭 보내 줘', 'type': '공유형'}],
                        'slides': [{'design': 'body', 'kicker': '무슨 일이 있었나', 'title': '교차로의 오후', 'items': '**11월 3일 오후 2시께** 수원 오목천동', 'num': '', 'scene': 'a car'},
                                   {'design': 'bogus', 'title': '', 'items': ''}, {'design': 'quote', 'title': '시속 5km도 안 되게\n서행 중이었다', 'sub': '운전자 A씨'}],
                        'tips': ['블랙박스 영상 지키기', '보험사에 조사 요청하기', '목격자 연락처 받기', '넷째'], 'caption': '🚗 서행하던 차 앞으로\n💬 운전자는 억울하대요\n🔎 조사 중이에요\n넷째 줄', 'hashtags': ['보험사기', '#블랙박스'],
                        'source_media': '무시', 'source_date': ''}
        j = call({'act': 'cards', 'art': 99901}).get_json()
        self.assertTrue(j['ok']); self.assertEqual(j['tag'], 'CAR'); self.assertEqual([x['design'] for x in j['slides']], ['cover', 'body', 'quote', 'last'])
        self.assertEqual([c['text'] for c in j['covers']], ['이 남성,\n일부러였을까?', '운전하는 친구한테\n꼭 보내 줘'])  # 낚시말 '충격' 거름
        self.assertEqual(j['slides'][0]['title'], '이 남성,\n일부러였을까?'); self.assertEqual(j['slides'][0]['sub'], '시속 5km'); self.assertEqual(j['slides'][1]['tag'], '무슨 일이 있었나')
        last = j['slides'][-1]; self.assertEqual(last['title'], '헷갈리면 저장해 두세요'); self.assertEqual(last['items'].count('\n'), 2); self.assertEqual(last['sub'], '출처: 소보루 매거진 2026.11.05')
        self.assertEqual(j['caption'], '🚗 서행하던 차 앞으로\n💬 운전자는 억울하대요\n🔎 조사 중이에요\n\n출처: 소보루 매거진 2026.11.05\n\n#소보루매거진 #보험사기 #블랙박스')
        self.assertEqual(j['photos'], ['/art/body/body-20261105120000-001.webp']); self.assertFalse(j['draw']); self.assertEqual(j['warn'], '')
        self.assertIn('covers에 정확히 5개', reply['sys']); self.assertIn('공유형', reply['sys']); self.assertNotIn('아이즈', reply['sys']); self.assertIn('[기사]\n차 앞으로 다가온 남성', body_sent[-1])
        reply['out'] = dict(reply['out'], source_media='연합뉴스', source_date='2026.11.04')
        j = call({'act': 'cards', 'note': '차 앞으로 다가온 남성 ' * 12}).get_json()  # 다른 기사: 기사 사진 안 쓰고 AI가 새로 그림, 출처는 그 매체
        self.assertTrue(j['draw']); self.assertEqual(j['photos'], []); self.assertIn('출처: 연합뉴스 2026.11.04', j['caption']); self.assertTrue(j['warn'])
        reply['out'] = {'tag': '블랙박스 이슈 · 수원', 'scenes': [{'design': 'full', 'title': '일부러\n였을까?', 'sub': ': 블랙박스에 찍힌 사고', 'dur': 30}, {'design': 'chat', 'items': '운전자 A씨 : 시속 5km도 안 됐다\n목격자 : 이전에도 7번 있었다', 'dur': 'x'}]}
        j = call({'act': 'reel', 'note': 'https://news.example.com/a/1'}).get_json()
        self.assertTrue(j['ok']); self.assertEqual([x['dur'] for x in j['scenes']], [8, 4]); self.assertIn('7', j['warn'])
        self.assertEqual(call({'act': 'reel', 'art': 4242424}).status_code, 400)
        self.assertEqual(call({'act': 'cards', 'note': '짧은 글'}).status_code, 400)
        page = admin.get('/admin/magazine/maker?mode=reel').get_data(as_text=True)
        self.assertIn('id="mk-ai"', page); self.assertIn('AI로 장면 짜기', page)
        # 운영자 2026-11-05: 레터 하나를 여러 SNS 게시물로 쪼개 반복 홍보 — 레터 꼭지마다 카드·릴스, 끝에 구독 안내 장과 캡션
        items = [{'title': '배달비 또 오른다', 'body': '배달 앱 두 곳이 다음 달부터 배달비를 500원씩 올린다. 소비자 부담은 한 번 주문에 최대 3,000원까지 늘어난다.', 'tip': '포장 주문 할인을 챙기세요', 'src': {'name': '연합뉴스'}}]
        sec = {'number': {'value': '3,000원', 'label': '한 번 주문 배달비', 'body': '배달 앱 두 곳이 배달비를 올리면서 한 번 주문에 최대 3,000원까지 낼 수 있게 됐다.'}}
        with self.site.conn() as db:
            lid = db.execute("INSERT INTO letters(no,title,intro,items,sections,status,created) VALUES(99901,'배달비 또 오른다','안녕하세요, 빵순이·빵돌이님. 오늘은 배달비 소식부터 전해 드려요.',?,?,'sent','2026-11-05')",
                             (json.dumps(items, ensure_ascii=False), json.dumps(sec, ensure_ascii=False))).lastrowid
        def clean_letter():
            with self.site.conn() as db: db.execute('DELETE FROM letters WHERE id=?', (lid,))
        self.addCleanup(clean_letter)
        page = admin.get('/admin/magazine/maker?mode=card').get_data(as_text=True)
        self.assertIn('id="mk-letter"', page); self.assertIn(f'value="L{lid}:news:0"', page); self.assertIn(f'value="L{lid}:number"', page); self.assertIn('id="mk-cap"', page)
        reply['out'] = {'tag': 'MONEY', 'caption': '🛵 배달비가 또 올라요\n💸 한 번 주문에 최대 3,000원', 'covers': [{'text': '배달비\n또 오른다', 'type': '경고·금지'}], 'slides': [{'design': 'body', 'title': '얼마나?', 'items': '최대 **3,000원**'}], 'tips': ['포장 주문']}
        j = call({'act': 'cards', 'letter': f'L{lid}:news:0'}).get_json()
        self.assertTrue(j['ok']); self.assertTrue(j['letter']); self.assertEqual(j['warn'], '')
        self.assertIn('소보루 레터', j['slides'][-1]['title']); self.assertEqual(j['slides'][-1]['design'], 'last'); self.assertEqual(len(j['slides']), 3)
        self.assertTrue(j['caption'].startswith('🛵')); self.assertIn('#소보루레터', j['caption']); self.assertIn('프로필 링크', j['caption'])
        self.assertIn('구독자를 늘리는', reply['sys']); self.assertIn('배달 앱 두 곳이', body_sent[-1])
        reply['out'] = {'tag': '배달비 · 오늘의 숫자', 'scenes': [{'design': 'full', 'title': '3,000원', 'dur': 4}, {'design': 'wide', 'title': '배달비', 'items': '#최대 3,000원', 'dur': 5}]}
        j = call({'act': 'reel', 'letter': f'L{lid}:number'}).get_json()
        self.assertTrue(j['ok']); self.assertTrue(j['letter']); self.assertEqual(len(j['scenes']), 2)  # 릴스는 끝 귤색 화면이 구독 안내
        self.assertEqual(call({'act': 'reel', 'letter': f'L{lid}:harm'}).status_code, 400)  # 없는 꼭지
        self.assertEqual(call({'act': 'reel', 'letter': 'L4242424:all'}).status_code, 400)
        reply['out'] = {'tag': 'CAR', 'covers': [{'text': '차 앞으로\n다가온 남성'}], 'slides': [{'design': 'body', 'title': '교차로의 오후'}]}
        j = call({'act': 'cards', 'art': 99901}).get_json()
        self.assertFalse(j['letter']); self.assertEqual(len(j['slides']), 3); self.assertNotIn('소보루 레터', j['caption'])
        page = admin.get('/admin/magazine/maker?mode=card').get_data(as_text=True)
        self.assertIn('id="mk-theme"', page); self.assertIn('id="mk-covers"', page); self.assertIn('id="mk-draw"', page); self.assertIn('/admin/magazine/maker/draw', page)

    def test_magazine_screen_editor(self):
        # 운영자 2026-11-05: ND 화면편집처럼 — 매거진 화면(메인·기사·목록)을 PC·모바일로 띄워 놓고 그 자리에서 문구·묶음 순서를 고침
        admin = self.login_admin()
        self.assertEqual(self.client.get('/admin/magazine/screen').status_code, 302)
        with self.site.conn() as db:
            aid = db.execute("INSERT INTO articles(title,summary,body,category,status,created,updated,published_at) VALUES('화면 시험 글','요약','본문','쇼핑','published','2020-01-01','2020-01-01','2020-01-01T09:00:00')").lastrowid
        def clean():
            with self.site.conn() as db: db.execute('DELETE FROM articles WHERE id=?', (aid,)); db.execute("DELETE FROM soboru_settings WHERE key='blocks:mag_article'")
        self.addCleanup(clean)
        page = admin.get('/admin/magazine/screen?page=main&device=mobile').get_data(as_text=True)
        self.assertIn('id="sc-if"', page); self.assertIn('src="/letter"', page); self.assertIn('sc-mobile', page); self.assertIn('HOT ISSUE', page)
        self.assertEqual(admin.get('/admin/magazine/screen').headers['X-Frame-Options'], 'SAMEORIGIN')
        self.assertIn('/admin/magazine/screen', admin.get('/admin/magazine/front').headers['Location'])
        # 띄운 화면: 이 주소에서도 매거진 화면이 편집 모드로 (제보센터 머리글·편집 띠 없이), 같은 주소 안에서만 띄움
        r = admin.get('/letter')
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200); self.assertEqual(r.headers['X-Frame-Options'], 'SAMEORIGIN')
        self.assertIn('class="ed"', html); self.assertIn('ed-blockbar', html); self.assertNotIn('class="ed-bar"', html)
        art = admin.get(f'/life/{aid}').get_data(as_text=True)
        self.assertIn('ma-art', art); self.assertIn('data-block="letter"', art)
        # 방문자는 그대로 매거진 주소로
        self.assertEqual(self.client.get('/letter', base_url='https://consumerjebo.co.kr').status_code, 301)
        # 고친 문구는 매거진(soboru.co.kr)에 저장되고 그쪽에 보임
        tok = self.csrf(admin, '/admin/magazine/screen')
        self.assertTrue(admin.post('/admin/inline', data={'_csrf': tok, 'face': 'soboru', 'key': 'letter.mz_hot2', 'value': 'HOT 시험'}).get_json()['ok'])
        self.addCleanup(lambda: admin.post('/admin/inline', data={'_csrf': tok, 'face': 'soboru', 'key': 'letter.mz_hot2', 'value': '', 'reset': '1'}))
        with self.site.conn() as db: self.assertEqual(db.execute("SELECT value FROM site_content WHERE key='letter.mz_hot2'").fetchone()[0], 'HOT 시험')
        # 묶음 순서: 기사 화면의 '레터 구독 띠' 숨기기
        admin.post('/admin/screens', data={'_csrf': tok, 'page': 'mag_article', 'block': 'letter', 'act': 'hide', 'ajax': '1'})
        self.assertNotIn('class="ma-letter"', self.client.get(f'/life/{aid}', base_url='https://soboru.co.kr').get_data(as_text=True))

    def test_auto_content(self):
        # 운영자 2026-11-06: 정해진 시간마다 서버에서 카드뉴스·릴스를 만들어 보관함에 넣고 알림 (auto_content.py)
        import auto_content
        from unittest.mock import patch
        ext = self.site.app.extensions
        env_hot = patch.dict(os.environ, {'AUTO_CONTENT_HOT': '0', 'AUTO_CONTENT_PER_RUN': '1'}); env_hot.start(); self.addCleanup(env_hot.stop)  # 뒤에서 따로 시험
        reply = {'tag': 'MONEY', 'covers': [{'text': '환불 3일 안에\n받을 수 있을까', 'type': '경고'}], 'big': '3일', 'cover_scene': 'desk',
                 'slides': [{'design': 'body', 'kicker': '언제부터', 'title': '3일 안에 돌려받아요', 'items': '판매자는 **3일** 안에 돌려줘요.\n\n늦으면 물어볼 수 있어요.', 'num': '3일'},
                            {'design': 'body', 'kicker': '내가 챙길 것', 'title': '주문 내역을 남겨요', 'items': '내역을 캡처해 두세요.', 'num': ''}],
                 'tips': ['내역 캡처하기', '문자 남기기', '1372 상담하기'], 'caption': '환불이 궁금할 때', 'hashtags': ['환불'], 'source_media': '', 'source_date': ''}
        now = datetime.datetime.now().isoformat(timespec='seconds')
        with self.site.conn() as db:
            db.execute("DELETE FROM articles")
            for i, (title, views) in enumerate((('많이 본 글', 50), ('덜 본 글', 1))):
                db.execute("INSERT INTO articles(id,title,summary,body,status,views,created,updated,published_at) VALUES(?,?,?,?,'published',?,?,?,?)",
                           (99800 + i, title, '요약', '판매자는 3일 안에 환불해야 하고 1372에 상담할 수 있다. ' * 8, views, now, now, now))
            db.execute("INSERT INTO articles(id,title,body,status,views,created,updated) VALUES(99810,'초안','본문','draft',999,?,?)", (now, now))
        sent = []
        env = {'CONTENT_TELEGRAM_BOT_TOKEN': 't', 'CONTENT_TELEGRAM_CHAT_ID': '7'}
        with self.site.app.app_context(), patch.dict(ext, {'mag_assist_chat': lambda *a: reply}), patch.dict(os.environ, env), \
                patch('notify.http_post', lambda u, p, h: sent.append(p) or {'ok': True}), patch('shutil.which', lambda x: None):
            self.assertEqual([a['id'] for a in ext['auto_content']['pick'](5)], [99800, 99801])  # 게시 글만, 조회수 순
            done, failed = ext['auto_content']['run']()
            self.assertEqual((len(done), failed), (1, []))
            self.assertEqual(ext['auto_content']['pick'](5)[0]['id'], 99801)  # 만든 글은 다시 고르지 않음
            with self.site.conn() as db:
                card = db.execute("SELECT * FROM made_items ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual((card['kind'], card['maker'], card['done']), ('card', 'auto', 1))
            self.assertEqual(json.loads(card['files']), ['01.png', '02.png', '03.png', '04.png'])
            self.assertIn('환불', card['caption'])
            self.assertIn('만들어졌어요', sent[0]['text']); self.assertEqual(sent[0]['chat_id'], '7')
            reply['slides'][0]['items'] = '판매자는 999일 안에 돌려줘요.'  # 기사에 없는 숫자는 버림
            done, failed = ext['auto_content']['run']()
            self.assertEqual(done, []); self.assertIn('없는 숫자', failed[0][1])
        # 표지는 실사: 설명에 사람이 있는 언스플래시 사진만 쓰고 사진가를 캡션에 밝힘
        import soboru_letter
        from PIL import Image
        calls = []
        def fake_unsplash(path, params=None):
            calls.append(path)
            if path != '/search/photos': return 200, {}
            return 200, {'results': [{'id': 'land', 'alt_description': 'empty beach', 'urls': {'raw': 'https://x/land'}, 'user': {'name': 'N'}},
                                     {'id': 'p1', 'alt_description': 'a woman looking surprised', 'urls': {'raw': 'https://x/p1'}, 'links': {'download_location': '/dl/p1'}, 'user': {'name': '김작가'}}]}
        reply['slides'][0]['items'] = '판매자는 **3일** 안에 돌려줘요.'
        reply['people_query'] = 'korean woman surprised phone'
        with self.site.conn() as db: db.execute("DELETE FROM auto_content")
        fetched = io.BytesIO(); Image.new('RGB', (800, 1200), 'gray').save(fetched, 'JPEG')
        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with self.site.app.app_context(), patch.dict(ext, {'mag_assist_chat': lambda *a: reply}), patch.dict(os.environ, {'UNSPLASH_ACCESS_KEY': 'k'}), \
                patch.object(soboru_letter, 'unsplash_call', fake_unsplash), patch('urllib.request.urlopen', lambda req, timeout=0: Resp(fetched.getvalue())), patch('shutil.which', lambda x: None):
            done, failed = ext['auto_content']['run'](99800)
            self.assertEqual(failed, [])
            with self.site.conn() as db:
                card = db.execute("SELECT * FROM made_items ORDER BY id DESC LIMIT 1").fetchone()
                self.assertEqual([r[0] for r in db.execute('SELECT photo_id FROM auto_content_photos')], ['p1'])
            self.assertIn('사진: 김작가 / Unsplash', card['caption']); self.assertIn('/dl/p1', calls)
        # 터진 소재: 뉴스 먼저, 분석을 알림에. 커뮤니티 글은 같은 주제의 기사가 있을 때만
        import mag_assist
        sent.clear()
        reply['why_hot'] = {'topic': '환불', 'value': '손해 피하기', 'format': '리스트', 'hook': '아직도?', 'script': '경고→방법'}
        hub = {'search': lambda *a, **k: {'items': [{'title': '다이소 환불 기준 바뀐다 논란', 'naver': 'https://n.news.naver.com/x/1'}, {'title': '전혀 다른 소식', 'naver': 'https://n.news.naver.com/x/2'}]}}
        with self.site.app.app_context(), patch.dict(os.environ, {'AUTO_CONTENT_HOT': '1', 'CONTENT_TELEGRAM_BOT_TOKEN': 't', 'CONTENT_TELEGRAM_CHAT_ID': '7'}), patch.dict(ext, {'mag_assist_chat': lambda *a: reply, 'naverhub': hub}), \
                patch.object(auto_content, 'hot_news', lambda: [{'url': 'https://n.news.naver.com/n/9', 'title': '환불 뉴스', 'comments': 321}]), \
                patch.object(auto_content, 'hot_community', lambda: [{'site': '더쿠', 'title': '[이슈] 다이소 환불 기준 바뀐다.jpg', 'views': 50000}, {'site': '디시', 'title': '오늘 날씨 좋다', 'views': 40000}]), \
                patch.object(mag_assist, 'read_article', lambda u: '판매자는 3일 안에 환불해야 하고 1372에 상담할 수 있다.'), patch('notify.http_post', lambda u, p, h: sent.append(p) or {'ok': True}), patch('shutil.which', lambda x: None):
            done, failed = ext['auto_content']['run']()
            self.assertEqual((done[0][3], failed), ('네이버 뉴스 댓글 321개', []))
            self.assertIn('왜 터졌나', sent[0]['text']); self.assertIn('후킹: 아직도?', sent[0]['text'])
            done, failed = ext['auto_content']['run']()  # 다음 번은 조사한 소재(분야별 최신 소비자 뉴스) 먼저 — 운영자 2026-11-06
            self.assertEqual(done[0][3], '소재 소비자·환불')
            done, failed = ext['auto_content']['run']()  # 그다음은 커뮤니티 먼저
            self.assertEqual(done[0][3], '더쿠 인기글 조회 50,000회')
            reply['skip'] = '연예 폭로'
            done, failed = ext['auto_content']['run']()
            self.assertEqual(done, []); self.assertIn('다루지 않을 소재', failed[0][1])
            del reply['skip']
        self.assertEqual(auto_content.rss_items('<rss><item><title><![CDATA[공정위, &quot;다크패턴&quot; 제재]]></title><link>https://a.kr/1</link></item><item><title>링크 없음</title></item></rss>'),
                         [{'title': '공정위, "다크패턴" 제재', 'url': 'https://a.kr/1'}])
        rows = auto_content.parse_community('<tr class="table_body x<strong class="text_over">글 &amp; 제목</strong><td class="hit"> 18,536 </td>', '루리웹', '<tr class="table_body', auto_content.COMMUNITIES[3][3], auto_content.COMMUNITIES[3][4])
        self.assertEqual(rows, [{'site': '루리웹', 'title': '글 & 제목', 'views': 18536}])
        self.assertTrue(auto_content.same_topic('[이슈] 다이소 환불 기준 바뀐다.jpg', '다이소 환불 기준 바뀐다 논란')); self.assertFalse(auto_content.same_topic('오늘 날씨 좋다', '다이소 환불'))
        for design in ('cover', 'body', 'quote', 'last'):  # 그림 없어도, 긴 글이어도 크기대로 그림
            s = {'design': design, 'tag': '꼬리표', 'title': '아주 긴 제목 ' * 8, 'sub': '12,345원', 'items': '줄 하나\n**굵게** 쓴 글 ' * 12}
            self.assertEqual(auto_content.render(s, None, 1, 4, auto_content.REEL_H).size, (1080, 1920))
            self.assertEqual(auto_content.render(s, None, 1, 4, auto_content.CARD_H).size, (1080, 1350))
        scene = auto_content.scenes_for([{'design': 'cover'}, {'design': 'body'}], 'd')
        self.assertEqual([x['audio'] for x in scene], [False, False])  # 무음

    def test_magazine_maker_narration(self):
        # 운영자 2026-11-06: 앵커 말투 나레이션 — 영상 소리 대신 음성을 넣고, 길면 조금 빠르게
        import mag_maker
        self.assertEqual(mag_maker.fit_tempo(5, 10), 1.0)
        self.assertEqual(mag_maker.fit_tempo(11, 10), 1.1)
        self.assertEqual(mag_maker.fit_tempo(30, 10), mag_maker.TEMPO_MAX)
        scene = {'kind': 'video', 'file': 'a.mp4', 'start': 0, 'dur': 4, 'speed': 1, 'layout': 'full', 'png': 'p.png', 'audio': True}
        cmd = mag_maker.build([dict(scene, voice='n.mp3', tempo=1.2), scene], 'o.png', 'out.mp4')
        filt = cmd[cmd.index('-filter_complex') + 1]
        self.assertIn('n.mp3', cmd)
        self.assertIn('[2:a]asetpts=PTS-STARTPTS,atempo=1.200,', filt)
        self.assertIn('[3:a]asetpts', filt)  # 나레이션 없는 장면은 전처럼 자기 영상 소리
        self.assertNotIn('[0:a]', filt)
        self.assertEqual(cmd[cmd.index('-crf') + 1], '16')  # 운영자 2026-11-06: 화질 좋게

    def test_made_archive(self):
        # 운영자 2026-11-05: 만든 카드뉴스·릴스 보관함 — 관리자 화면 저장 + 자동(토큰)으로 보내기, 목록·보기·내려받기·지우기
        import io, os, zipfile
        from unittest import mock
        from PIL import Image
        admin = self.login_admin()
        self.assertEqual(self.client.get('/admin/magazine/made').status_code, 302)
        tok = self.csrf(admin, '/admin/magazine/made')
        H = {'X-CSRFToken': tok}
        b = io.BytesIO(); Image.new('RGB', (108, 135), 'orange').save(b, 'PNG'); png = b.getvalue()
        j = admin.post('/admin/magazine/made/new', json={'kind': 'card', 'title': '렌즈 직구\n괜찮을까', 'caption': '캡션 줄', 'source': 'https://n.news.naver.com/x'}, headers=H).get_json()
        i = j['id']
        self.assertFalse(admin.post('/admin/magazine/made/%d/file?name=01.png' % i, data=b'not png', headers=H).get_json()['ok'])
        self.assertFalse(admin.post('/admin/magazine/made/%d/file?name=../x.png' % i, data=png, headers=H).get_json()['ok'])
        for n in ('01.png', '02.png'): self.assertTrue(admin.post('/admin/magazine/made/%d/file?name=%s' % (i, n), data=png, headers=H).get_json()['ok'])
        self.assertNotIn('렌즈 직구 괜찮을까', admin.get('/admin/magazine/made').get_data(as_text=True))  # 다 올리기 전엔 안 보임
        self.assertTrue(admin.post('/admin/magazine/made/%d/done' % i, headers=H).get_json()['ok'])
        page = admin.get('/admin/magazine/made').get_data(as_text=True)
        self.assertIn('렌즈 직구 괜찮을까', page); self.assertIn('2장', page); self.assertIn('set-maker-token.sh', page)
        self.assertIn('만든 것 보관함', page)
        view = admin.get('/admin/magazine/made/%d' % i).get_data(as_text=True)
        self.assertIn('캡션 줄', view); self.assertIn('ZIP', view)
        self.assertEqual(admin.get('/admin/magazine/made/%d/01.png' % i).data, png)
        self.assertEqual(self.client.get('/admin/magazine/made/%d/01.png' % i).status_code, 302)  # 관리자만
        z = zipfile.ZipFile(io.BytesIO(admin.get('/admin/magazine/made/%d.zip' % i).data))
        self.assertEqual(sorted(z.namelist()), ['caption.txt', 'soboru-card-%d-01.png' % i, 'soboru-card-%d-02.png' % i])
        # 자동으로 만드는 쪽: 토큰 없으면 막힘, 있으면 CSRF 없이 보냄
        self.assertEqual(self.client.post('/api/maker/items', json={'kind': 'reel'}).status_code, 400)  # 토큰 머리글이 없으면 CSRF로 막힘
        with mock.patch.dict(os.environ, {'MAKER_API_TOKEN': 't' * 32}):
            self.assertEqual(self.client.post('/api/maker/items', json={'kind': 'reel'}, headers={'Authorization': 'Bearer wrong'}).status_code, 401)
            A = {'Authorization': 'Bearer ' + 't' * 32}
            r = self.client.post('/api/maker/items', json={'kind': 'reel', 'title': '블랙박스 이슈', 'caption': 'c'}, headers=A).get_json(); k = r['id']
            mp4 = b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 100
            self.assertTrue(self.client.post('/api/maker/items/%d/file?name=reel.mp4' % k, data=mp4[:50], headers=A).get_json()['ok'])
            self.assertTrue(self.client.post('/api/maker/items/%d/file?name=reel.mp4&part=1' % k, data=mp4[50:], headers=A).get_json()['ok'])
            self.assertFalse(self.client.post('/api/maker/items/%d/file?name=01.png' % k, data=png, headers=A).get_json()['ok'])  # 릴스엔 그림 X
            self.assertTrue(self.client.post('/api/maker/items/%d/done' % k, headers=A).get_json()['ok'])
            items = self.client.get('/api/maker/items', headers=A).get_json()['items']
            self.assertEqual(items[0]['title'], '블랙박스 이슈'); self.assertEqual(items[0]['maker'], 'auto')
        self.assertEqual(admin.get('/admin/magazine/made/%d/reel.mp4' % k).data, mp4)
        page = admin.get('/admin/magazine/made?by=auto').get_data(as_text=True)
        self.assertIn('블랙박스 이슈', page); self.assertNotIn('렌즈 직구', page)
        admin.post('/admin/magazine/made/%d/act' % k, data={'_csrf': tok, 'act': 'reel'})
        with self.site.conn() as db:
            v = db.execute('SELECT video FROM mag_reels WHERE title=?', ('블랙박스 이슈',)).fetchone()[0]
            db.execute('DELETE FROM mag_reels WHERE title=?', ('블랙박스 이슈',))
        self.assertEqual(admin.get(v).status_code, 200)
        (self.site.UPLOAD / 'art' / v.rsplit('/', 1)[1]).unlink(missing_ok=True)
        admin.post('/admin/magazine/made/%d/act' % i, data={'_csrf': tok, 'act': 'save', 'title': '새 제목', 'caption': '새 캡션'})
        self.assertIn('새 캡션', admin.get('/admin/magazine/made/%d' % i).get_data(as_text=True))
        for x in (i, k): admin.post('/admin/magazine/made/%d/act' % x, data={'_csrf': tok, 'act': 'del'})
        self.assertEqual(admin.get('/admin/magazine/made/%d' % i).status_code, 404)
        self.assertFalse((self.site.UPLOAD / 'made' / str(k)).exists())

    def test_magazine_maker(self):
        # 운영자 2026-11-05: 카드뉴스·릴스 만들기 — 브라우저가 그린 글씨 판 + 서버 ffmpeg로 릴스 MP4
        import base64, io, shutil, time, mag_maker
        from PIL import Image
        admin = self.login_admin()
        self.assertEqual(self.client.get('/admin/magazine/maker').status_code, 302)
        page = admin.get('/admin/magazine/maker?mode=reel').get_data(as_text=True)
        self.assertIn('id="mk"', page); self.assertIn('data-mode="reel"', page); self.assertIn('maker.js', page)
        self.assertIn('카드뉴스·릴스 만들기', admin.get('/admin/magazine').get_data(as_text=True))
        # 배치 필터: 흐린 배경 + 가운데 영상, 느리게는 소리 없음
        f = ';'.join(mag_maker.scene_filter(0, 0, 1, 'video', 'wide', 3, 2, True))
        self.assertIn('boxblur', f); self.assertIn('overlay=0:620', f); self.assertIn('setpts=2*', f); self.assertIn('anullsrc', f)
        self.assertIn('color=c=0x15120f', ';'.join(mag_maker.scene_filter(1, 2, 3, 'image', 'chat', 2, 1, False)))
        art = self.site.UPLOAD / 'art'; art.mkdir(parents=True, exist_ok=True)
        photo = 'body-20261105120000-001.webp'; Image.new('RGB', (640, 360), 'orange').save(art / photo, 'WEBP')
        self.addCleanup(lambda: (art / photo).unlink(missing_ok=True))
        b = io.BytesIO(); Image.new('RGBA', (1080, 1920), (0, 0, 0, 0)).save(b, 'PNG'); png = 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()
        tok = self.csrf(admin, '/admin/magazine/maker')
        # 카드뉴스 그림: 기사 사진 대신 장면 설명으로 AI가 새로 그림 (얼굴·로고·글자 없이)
        import companydesk
        sent = {}
        def fake_img(url, headers, body, timeout):
            sent.update(body); b = io.BytesIO(); Image.new('RGB', (64, 96), 'orange').save(b, 'WEBP'); return 200, {'data': [{'b64_json': base64.b64encode(b.getvalue()).decode()}]}
        with patch.object(companydesk, 'post_json', fake_img), patch.dict(os.environ, {'OPENAI_API_KEY': 'k'}):
            draw = lambda d: admin.post('/admin/magazine/maker/draw', json=d, headers={'X-CSRFToken': tok})
            self.assertEqual(draw({'scene': ''}).status_code, 400)
            j = draw({'scene': 'a delivery rider at night'}).get_json()
        self.assertTrue(j['ok']); self.assertIn('a delivery rider at night', sent['prompt']); self.assertIn('never a recognizable face', sent['prompt']); self.assertEqual(sent['size'], '1024x1536')
        self.addCleanup(lambda: (art / j['url'].rsplit('/', 1)[1]).unlink(missing_ok=True))
        self.assertEqual(admin.get(j['url']).status_code, 200)
        # 네이버 경제 뉴스 댓글 많은 순
        sec = ('<a href="https://n.news.naver.com/mnews/article/001/0000000001?sid=101" class="sa_text_title"><strong>배달비 또 오른다, 소비자 부담 커져</strong></a>'
               '<a href="https://n.news.naver.com/mnews/article/015/0000000002"><strong>카드 연회비 돌려받는 길 열린다</strong></a><a href="https://n.news.naver.com/mnews/article/015/0000000002">사진</a>'
               '<a href="https://example.com/x">광고 기사 제목이 길어요</a><a href="https://n.news.naver.com/mnews/article/015/0000000003">" style="display: none;"></a><a href="https://n.news.naver.com/mnews/article/015/0000000004">[인사] 중소벤처기업부</a>')
        def fake_get(url, referer=''):
            if url.endswith('section/101'): return sec
            if 'breakingnews' in url: return '<a href="https://n.news.naver.com/mnews/article/001/0000000001">배달비 또 오른다</a>' if url.endswith('259') else ''
            return 'cb({"result":{"count":{"comment":%d,"total":9}}})' % (12 if '0000000001' in url else 345)
        with patch.object(mag_maker, '_get', fake_get):
            jn = admin.get('/admin/magazine/maker/naver').get_json()
        self.assertTrue(jn['ok']); self.assertEqual([x['comments'] for x in jn['items']], [345, 12])
        self.assertEqual(jn['items'][0], {'url': 'https://n.news.naver.com/mnews/article/015/0000000002', 'title': '카드 연회비 돌려받는 길 열린다', 'comments': 345})
        self.assertIn('id="mk-naver"', admin.get('/admin/magazine/maker').get_data(as_text=True))
        call = lambda d: admin.post('/admin/magazine/maker/render', json=d, headers={'X-CSRFToken': tok})
        if not shutil.which('ffmpeg'):
            self.assertEqual(call({'scenes': []}).status_code, 503); return
        self.assertEqual(call({'scenes': [], 'outro': png}).status_code, 400)
        self.assertEqual(call({'scenes': [{'media': '/etc/passwd', 'png': png, 'dur': 2}], 'outro': png}).status_code, 400)
        self.assertEqual(call({'scenes': [{'media': '/art/body/' + photo, 'png': 'data:image/png;base64,AAAA', 'dur': 2}], 'outro': png}).status_code, 400)
        self.assertEqual(call({'scenes': [{'media': '/art/body/' + photo, 'png': png, 'dur': 99}], 'outro': png}).status_code, 400)
        r = call({'scenes': [{'media': '/art/body/' + photo, 'png': png, 'dur': 1, 'layout': 'wide'}, {'media': '/art/body/' + photo, 'png': png, 'dur': 1, 'layout': 'clean'}], 'outro': png}).get_json()
        self.assertTrue(r['ok']); self.assertEqual(r['seconds'], 4.6)
        for _ in range(240):
            st = admin.get('/admin/magazine/maker/status?job=' + r['job']).get_json()
            if st['state'] != 'running': break
            time.sleep(0.5)
        self.assertEqual(st['state'], 'done', st)
        name = st['url'].rsplit('/', 1)[1]; self.addCleanup(lambda: (art / name).unlink(missing_ok=True))
        self.assertTrue(re.fullmatch(r'video-\d{14}-\d{3}\.mp4', name))
        self.assertEqual(self.client.get(st['url']).status_code, 200)
        self.assertEqual(admin.get('/admin/magazine/maker/status?job=../x').status_code, 404)

    def test_magazine_reels(self):
        # 운영자 2026-11-05: 매거진 첫 화면에 릴스 칸, 관리자에서 영상 올리기
        admin = self.login_admin()
        self.assertEqual(self.client.get('/admin/magazine/reels').status_code, 302)
        def clean():
            with self.site.conn() as db: db.execute('DELETE FROM mag_reels')
        self.addCleanup(clean)
        home = lambda: self.client.get('/', base_url='https://soboru.co.kr').get_data(as_text=True)
        self.assertNotIn('id="reels"', home())  # 없으면 칸도 없음
        tok = self.csrf(admin, '/admin/magazine/reels')
        post = lambda **d: admin.post('/admin/magazine/reels', data={'_csrf': tok, **d})
        post(act='add', video='/etc/passwd', title='x')
        post(act='add', video='/art/video/video-20261105101500-001.mp4', title='나쁜 주소', ig='javascript:alert(1)')
        with self.site.conn() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM mag_reels').fetchone()[0], 0)
        post(act='add', video='/art/video/video-20261105101500-001.mp4', title='먼저 올린 릴스')
        post(act='add', video='/art/video/video-20261105101600-002.mp4', title='나중 릴스', ig='https://www.instagram.com/reel/abc/')
        page = home()
        self.assertIn('id="reels"', page); self.assertIn('https://www.instagram.com/reel/abc/', page)
        self.assertLess(page.index('나중 릴스'), page.index('먼저 올린 릴스'))  # 새 릴스가 앞
        with self.site.conn() as db: rid = db.execute("SELECT id FROM mag_reels WHERE title='나중 릴스'").fetchone()[0]
        post(act='down', id=rid)
        page = home(); self.assertLess(page.index('먼저 올린 릴스'), page.index('나중 릴스'))
        post(act='save', id=rid, title='나중 릴스', ig='')  # 끄기
        self.assertNotIn('나중 릴스', home())
        post(act='del', id=rid)
        with self.site.conn() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM mag_reels').fetchone()[0], 1)

    def test_magazine_manage(self):
        # 운영자 2026-11-05: ND CMS 관리 메뉴처럼 — 광고·환경설정·접수글
        import io
        from PIL import Image
        admin = self.login_admin()
        for u in ('/admin/magazine/ads', '/admin/magazine/settings', '/admin/magazine/inbox'):
            self.assertEqual(self.client.get(u).status_code, 302)
        with self.site.conn() as db:
            aid = db.execute("INSERT INTO articles(title,summary,body,category,status,created,updated,published_at) VALUES('광고 시험 글','요약','본문','쇼핑','published','2020-01-01','2020-01-01','2020-01-01T09:00:00')").lastrowid
        def clean():
            with self.site.conn() as db:
                db.execute('DELETE FROM articles WHERE id=?', (aid,)); db.execute("DELETE FROM soboru_settings WHERE key IN ('mag_conf','mag_ads')"); db.execute('DELETE FROM mag_inbox'); db.execute('DELETE FROM login_attempts')
        self.addCleanup(clean)
        nav = admin.get('/admin/magazine/settings').get_data(as_text=True)
        for w in ('접수글', '광고', '환경설정'): self.assertIn(w, nav)
        # 환경설정: 분야 순서·끄기, SNS
        tok = self.csrf(admin, '/admin/magazine/settings')
        bad = admin.post('/admin/magazine/settings', data={'_csrf': tok, 'aisle': ['쇼핑'], 'sns_instagram': 'javascript:alert(1)'})
        self.assertEqual(bad.status_code, 302)
        admin.post('/admin/magazine/settings', data={'_csrf': tok, 'aisle': ['여행', '쇼핑', '음식'], 'on_여행': '1', 'on_음식': '1', 'inbox': '1', 'email': 'hi@soboru.co.kr', 'sns_instagram': 'https://instagram.com/soboru'})
        home = self.client.get('/', base_url='https://soboru.co.kr').get_data(as_text=True)
        tabs = re.search(r'class="ml-tabs".*?</nav>', self.client.get('/life', base_url='https://soboru.co.kr').get_data(as_text=True), re.S)[0]
        aisles = re.findall(r'>([A-Z]+)</a>', tabs)
        self.assertEqual(aisles[:3], ['ALL', 'TRAVEL', 'FOOD']); self.assertNotIn('SHOPPING', aisles)
        self.assertIn('https://instagram.com/soboru', home); self.assertIn('/letter/contact', home); self.assertIn('hi@soboru.co.kr', home)
        # 광고: 사진·주소를 넣고 켜면 첫 화면에, 누르면 세고 광고 주소로
        buf = io.BytesIO(); Image.new('RGB', (800, 200), 'orange').save(buf, 'PNG'); buf.seek(0)
        tok = self.csrf(admin, '/admin/magazine/ads')
        admin.post('/admin/magazine/ads', data={'_csrf': tok, 'slot': 'main', 'url': 'https://example.com/sale', 'alt': '가을 할인', 'on': '1', 'img': (buf, 'ad.png', 'image/png')}, content_type='multipart/form-data')
        home = self.client.get('/', base_url='https://soboru.co.kr').get_data(as_text=True)
        self.assertIn('class="mad mad-main"', home); self.assertIn('alt="가을 할인"', home)
        img = re.search(r'src="(/art/ad/[^"]+)"', home)[1]
        self.assertEqual(self.client.get(img, base_url='https://soboru.co.kr').status_code, 200)
        go = self.client.get('/letter/ad/main', base_url='https://soboru.co.kr')
        self.assertEqual(go.headers['Location'], 'https://example.com/sale')
        self.assertIn('누른 횟수 <b>1</b>', admin.get('/admin/magazine/ads').get_data(as_text=True))
        admin.post('/admin/magazine/ads', data={'_csrf': tok, 'slot': 'main', 'url': 'https://example.com/sale', 'end': '2020-01-01', 'on': '1'})
        self.assertNotIn('mad-main', self.client.get('/', base_url='https://soboru.co.kr').get_data(as_text=True))  # 기간 지나면 안 보임
        self.assertEqual(self.client.get('/letter/ad/main', base_url='https://soboru.co.kr').status_code, 404)
        admin.post('/admin/magazine/ads', data={'_csrf': tok, 'slot': 'main', 'act': 'del'})
        self.assertEqual(self.client.get(img, base_url='https://soboru.co.kr').status_code, 404)
        # 접수글: 독자가 보내면 관리자에 쌓임
        reader = self.site.app.test_client()
        page = reader.get('/letter/contact', base_url='https://soboru.co.kr')
        self.assertEqual(page.status_code, 200)
        ctok = re.search(r'name="_csrf" value="([^"]+)"', page.get_data(as_text=True))[1]
        send = lambda **d: reader.post('/letter/contact', base_url='https://soboru.co.kr', data={'_csrf': ctok, 'kind': '기사 제보', 'email': 'r@example.com', 'body': '동네 마트 영수증 가격이 진열대와 달라요.', 'agree': '1', **d}).get_data(as_text=True)
        self.assertIn('동의해야', send(agree=''))
        self.assertIn('잘 받았어요', send(name='독자'))
        self.assertEqual(reader.post('/letter/contact', base_url='https://soboru.co.kr', data={'_csrf': ctok, 'website': 'x'}).status_code, 400)
        box = admin.get('/admin/magazine/inbox').get_data(as_text=True)
        self.assertIn('진열대와 달라요', box); self.assertIn('class="ms-badge">1<', box)
        with self.site.conn() as db: mid = db.execute('SELECT id FROM mag_inbox').fetchone()[0]
        tok = self.csrf(admin, '/admin/magazine/inbox')
        admin.post('/admin/magazine/inbox', data={'_csrf': tok, 'id': mid, 'act': 'done'})
        self.assertNotIn('class="ms-badge">1<', admin.get('/admin/magazine/inbox').get_data(as_text=True))
        # 접수를 끄면 바닥글 링크도, 쓰는 화면도 없음
        tok = self.csrf(admin, '/admin/magazine/settings')
        admin.post('/admin/magazine/settings', data={'_csrf': tok, 'aisle': ['쇼핑'], 'on_쇼핑': '1'})
        self.assertEqual(reader.get('/letter/contact', base_url='https://soboru.co.kr').status_code, 404)

    def test_magazine_editors(self):
        # 운영자 2026-11-05: 에디터 계정 — 지금 기사는 에디터 이지우·오후가 번갈아, 에디터는 쓰고 승인 요청만 (게시는 관리자)
        admin = self.login_admin()
        tok = self.csrf(admin, '/admin/life?new=1')
        ids = []
        for t in ('첫째 기사', '둘째 기사'):
            r = admin.post('/admin/life', data={'_csrf': tok, 'title': t, 'summary': 's', 'body': 'b', 'category': '쇼핑', 'publish': '1'})
            ids.append(int(r.headers['Location'].rstrip('/').split('/')[-1]))
        for aid in ids: self.addCleanup(lambda aid=aid: admin.post(f'/admin/life/{aid}', data={'_csrf': self.csrf(admin, f'/admin/life/{aid}'), 'title': 'x', 'act': 'delete'}))
        names = [re.search(r'EDITOR</b> (이지우|오후)', self.client.get(f'/life/{aid}', base_url='https://soboru.co.kr').get_data(as_text=True))[1] for aid in ids]
        self.assertEqual(sorted(names), ['오후', '이지우'])
        self.assertNotIn('소보루 에디터', self.client.get(f'/life/{ids[0]}', base_url='https://soboru.co.kr').get_data(as_text=True))
        # 관리자: 에디터 계정 만들기
        page = admin.get('/admin/magazine/editors').get_data(as_text=True); self.assertIn('이지우', page); self.assertIn('오후', page)
        admin.post('/admin/magazine/editors', data={'_csrf': self.csrf(admin, '/admin/magazine/editors'), 'act': 'add', 'name': '김시험', 'login': 'kimtest', 'password': 'pw-123456'})
        ed = self.site.app.test_client()
        self.assertEqual(ed.get('/admin/magazine/mine').status_code, 302)
        ed.post('/editor/login', data={'_csrf': self.csrf(ed, '/editor/login'), 'login': 'kimtest', 'password': 'pw-123456'})
        self.assertEqual(ed.get('/admin/magazine/mine').status_code, 200)
        self.assertNotEqual(ed.get('/admin/magazine/editors').status_code, 200)  # 에디터는 관리 메뉴에 못 들어감
        self.assertNotEqual(ed.get('/admin').status_code, 200)
        # 관리자로 들어와 있던 브라우저에서 에디터로 들어와도 에디터 메뉴만 (운영자 2026-11-05)
        both = self.login_admin()
        both.post('/editor/login', data={'_csrf': self.csrf(both, '/editor/login'), 'login': 'kimtest', 'password': 'pw-123456'})
        nav = both.get('/admin/magazine/mine').get_data(as_text=True)
        self.assertIn('내 기사', nav)
        for w in ('승인', '화면 편집', '환경설정', '접수글', '광고', '에디터</span>'): self.assertNotIn(w, nav)
        self.assertNotEqual(both.get('/admin/magazine/settings').status_code, 200)
        # 에디터가 '게시'를 눌러도 승인 대기로
        r = ed.post('/admin/life', data={'_csrf': self.csrf(ed, '/admin/life?new=1'), 'title': '에디터 기사', 'summary': 's', 'body': 'b', 'category': '쇼핑', 'publish': '1'})
        with self.site.conn() as db: row = db.execute("SELECT id,status FROM articles WHERE title='에디터 기사'").fetchone()
        self.addCleanup(lambda: admin.post(f"/admin/life/{row['id']}", data={'_csrf': self.csrf(admin, f"/admin/life/{row['id']}"), 'title': 'x', 'act': 'delete'}))
        self.assertEqual(row['status'], 'pending')
        self.assertEqual(self.client.get(f"/life/{row['id']}", base_url='https://soboru.co.kr').status_code, 404)
        self.assertNotEqual(ed.get(f'/admin/life/{ids[0]}').status_code, 200)  # 남의 기사는 못 고침
        # 관리자가 승인하면 게시, 이름은 김시험
        self.assertIn('에디터 기사', admin.get('/admin/magazine/approve').get_data(as_text=True))
        admin.post('/admin/magazine/approve', data={'_csrf': self.csrf(admin, '/admin/magazine/approve'), 'id': row['id'], 'act': 'ok'})
        art = self.client.get(f"/life/{row['id']}", base_url='https://soboru.co.kr').get_data(as_text=True)
        self.assertIn('김시험', art)
        self.assertEqual(admin.get('/admin/magazine/stats').status_code, 200)

    def test_magazine_seo_and_cms(self):
        # 운영자 2026-11-05: 매거진 검색 최적화 + 토스풍 CMS + 바닥글 '관리자'
        admin = self.login_admin()
        r = admin.post('/admin/life', data={'_csrf': self.csrf(admin, '/admin/life'), 'title': '검색 시험 기사', 'summary': '검색 요약', 'body': '본문', 'category': '쇼핑', 'publish': '1'})
        aid = int(r.headers['Location'].rstrip('/').split('/')[-1])
        self.addCleanup(lambda: admin.post(f'/admin/life/{aid}', data={'_csrf': self.csrf(admin, f'/admin/life/{aid}'), 'title': 'x', 'act': 'delete'}))
        lst = admin.get('/admin/life').get_data(as_text=True)
        self.assertIn('새 기사 쓰기', lst); self.assertIn('검색 시험 기사', lst); self.assertNotIn('id="write"', lst)
        self.assertIn('id="mz-body"', admin.get('/admin/life?new=1').get_data(as_text=True))
        self.assertIn('class="mz-ed"', admin.get(f'/admin/life/{aid}').get_data(as_text=True))
        home = self.client.get('/', base_url='https://soboru.co.kr').get_data(as_text=True)
        self.assertIn('<title>SOBORU 소보루 매거진</title>', home)
        self.assertIn('<link rel="canonical" href="https://soboru.co.kr/">', home)
        self.assertIn('<meta property="og:site_name" content="소보루 매거진">', home)
        self.assertIn('SiteNavigationElement', home); self.assertIn('https://soboru.co.kr/rss.xml', home)
        self.assertIn('href="https://consumerjebo.co.kr/admin/magazine"', home)
        self.assertEqual(self.client.get('/admin', base_url='https://soboru.co.kr').headers['Location'], 'https://consumerjebo.co.kr/admin/magazine')
        cat = self.client.get('/life?category=쇼핑', base_url='https://soboru.co.kr').get_data(as_text=True)
        self.assertIn('href="https://soboru.co.kr/life?category=%EC%87%BC%ED%95%91"', cat); self.assertNotIn('noindex', cat)
        art = self.client.get(f'/life/{aid}', base_url='https://soboru.co.kr').get_data(as_text=True)
        self.assertIn(f'<link rel="canonical" href="https://soboru.co.kr/life/{aid}">', art); self.assertIn('BreadcrumbList', art)
        sm = self.client.get('/sitemap.xml', base_url='https://soboru.co.kr').get_data(as_text=True)
        self.assertIn('<loc>https://soboru.co.kr/</loc>', sm); self.assertIn(f'<loc>https://soboru.co.kr/life/{aid}</loc>', sm); self.assertNotIn('consumerjebo', sm)
        self.assertIn('검색 시험 기사', self.client.get('/rss.xml', base_url='https://soboru.co.kr').get_data(as_text=True))
        self.assertIn('Sitemap: https://soboru.co.kr/sitemap.xml', self.client.get('/robots.txt', base_url='https://soboru.co.kr').get_data(as_text=True))
        # 관리자 > 검색 노출: 제목·소유확인 코드 저장
        self.assertEqual(self.client.get('/admin/magazine/seo').status_code, 302)
        admin.post('/admin/magazine/seo', data={'_csrf': self.csrf(admin, '/admin/magazine/seo'), 'title': '소보루 매거진 시험', 'description': '설명', 'naver': '<meta name="naver-site-verification" content="abc123" />', 'google': ''})
        self.addCleanup(lambda: admin.post('/admin/magazine/seo', data={'_csrf': self.csrf(admin, '/admin/magazine/seo'), 'title': '', 'description': '', 'naver': '', 'google': ''}))
        home = self.client.get('/', base_url='https://soboru.co.kr').get_data(as_text=True)
        self.assertIn('<title>소보루 매거진 시험</title>', home); self.assertIn('content="abc123"', home)
        self.assertNotIn('abc123', self.client.get('/', base_url='https://consumerjebo.co.kr').get_data(as_text=True))

    def test_magazine_mosaic_convert(self):
        # 운영자 2026-11-05: 도구가 아이폰·카톡 영상(HEVC)을 못 읽음 → 나눠 올려 서버에서 MP4로 바꿔 돌려줌
        import shutil, subprocess, tempfile, time as _t
        if not shutil.which('ffmpeg'): self.skipTest('ffmpeg 없음')
        admin = self.login_admin(); tok = self.csrf(admin, '/admin/life?new=1')
        src = Path(tempfile.mkdtemp()) / 'a.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=160x120:rate=10', '-t', '1', str(src)], check=True)
        data = src.read_bytes(); half = len(data) // 2
        self.assertEqual(admin.post('/admin/magazine/mosaic/upload?i=0', data=data[:half], content_type='application/octet-stream').status_code, 400)  # CSRF 없으면 막음
        j = admin.post('/admin/magazine/mosaic/upload?i=0', data=data[:half], headers={'X-CSRFToken': tok}, content_type='application/octet-stream').get_json()
        admin.post(f"/admin/magazine/mosaic/upload?i=1&job={j['job']}", data=data[half:], headers={'X-CSRFToken': tok}, content_type='application/octet-stream')
        admin.post(f"/admin/magazine/mosaic/convert?job={j['job']}", headers={'X-CSRFToken': tok})
        for _ in range(60):
            st = admin.get(f"/admin/magazine/mosaic/converted?check=1&job={j['job']}").get_json()['state']
            if st != 'running': break
            _t.sleep(0.2)
        self.assertEqual(st, 'done')
        r = admin.get(f"/admin/magazine/mosaic/converted?job={j['job']}"); self.assertEqual(r.mimetype, 'video/mp4'); self.assertGreater(len(r.data), 500)
        self.assertEqual(self.client.get(f"/admin/magazine/mosaic/converted?job={j['job']}").status_code, 302)

    def test_letter_unsplash_photos(self):
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        calls = []
        def fake(path, params=None):
            calls.append((path, params))
            if path.startswith('http'): return 200, {}
            q = params['query']
            return 200, {'results': [{'id': 'p-' + q, 'urls': {'raw': 'https://images.unsplash.com/photo-' + q.replace(' ', '-') + '?ixid=x'}, 'alt_description': q,
                                      'user': {'name': '김작가', 'links': {'html': 'https://unsplash.com/@kim'}}, 'links': {'download_location': 'https://api.unsplash.com/photos/p/download'}}]}
        with patch.object(self.site.soboru_letter, 'unsplash_call', fake):
            with patch.dict(os.environ, {'UNSPLASH_ACCESS_KEY': ''}):
                r, _ = self.letter_make(bad=False)
            L = self.site.app.extensions['soboru_letter']['get'](r['id'])
            self.assertFalse(calls); self.assertNotIn('photo', L['items'][0])   # 키가 없으면 사진 없이
            with patch.dict(os.environ, {'UNSPLASH_ACCESS_KEY': 'us-test'}):
                r, _ = self.letter_make(bad=False)
        L = self.site.app.extensions['soboru_letter']['get'](r['id'])
        self.assertEqual([c[1]['query'] for c in calls if c[1]], ['interest rate bank'])  # 영어만 남김, 오늘의 뉴스엔 사진 없음
        self.assertEqual(sum(1 for c in calls if c[0].endswith('/download')), 1)   # 고른 사진은 download 알림
        ph = L['sections']['comment']['photo']
        self.assertIn('w=1072', ph['url']); self.assertEqual(ph['credit'], '김작가'); self.assertIn('utm_source=soboru_letter', ph['credit_url'])
        self.assertFalse([it for it in L['items'] if 'photo' in it])
        html = self.site.app.extensions['soboru_letter']['email_parts'](L, 'tok-x')[1]
        self.assertIn('images.unsplash.com/photo-interest-rate-bank', html); self.assertIn('>Unsplash</a>', html); self.assertIn('김작가', html)
        admin = self.login_admin()
        admin.post(f"/admin/letter/{r['id']}", data={'_csrf': self.csrf(admin, f"/admin/letter/{r['id']}"), 'act': 'save', 'comment_nophoto': '1'})
        L = self.site.app.extensions['soboru_letter']['get'](r['id'])
        self.assertNotIn('photo', L['sections']['comment'])
        # 운영자 2026-11-05: 사진을 직접 넣을 수 있게 (JPG로 저장, Unsplash 출처 줄 없음)
        from PIL import Image
        buf = io.BytesIO(); Image.new('RGB', (40, 30), (200, 100, 50)).save(buf, 'PNG'); buf.seek(0)
        admin.post(f"/admin/letter/{r['id']}", data={'_csrf': self.csrf(admin, f"/admin/letter/{r['id']}"), 'act': 'save', 'comment_photo_file': (buf, 'mine.png')}, content_type='multipart/form-data')
        ph = self.site.app.extensions['soboru_letter']['get'](r['id'])['sections']['comment']['photo']
        self.assertTrue(ph['own']); name = ph['url'].rsplit('/', 1)[1]
        got = self.client.get('/letter/photo/' + name); self.assertEqual((got.status_code, got.mimetype), (200, 'image/jpeg'))
        html = self.site.app.extensions['soboru_letter']['email_parts'](self.site.app.extensions['soboru_letter']['get'](r['id']), 'tok-x')[1]
        self.assertIn('/letter/photo/' + name, html); self.assertNotIn('>Unsplash</a>', html.split('/letter/photo/')[1][:600])

    def test_letter_open_click_tracking_and_stibee_html(self):
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        with self.site.conn() as db: db.execute('DELETE FROM letter_events')
        r, _ = self.letter_make(bad=False)
        L = self.site.app.extensions['soboru_letter']
        letter = L['get'](r['id'])
        self.letter_subs([('a@test.kr', 'active'), ('b@test.kr', 'active')])
        box = []
        with patch.dict(os.environ, self.LETTER_MAIL), patch.object(self.site.notify.smtplib, 'SMTP_SSL', self.letter_smtp(box)):
            self.assertEqual(L['send'](r['id'])['status'], 'sent')
        html = box[0].get_body(('html',)).get_content()
        tok = 'tok-' + box[0]['To'].split('@')[0]
        # 열어 봄: 구독자 토큰이 든 1x1 그림, 링크는 서명된 우리 주소를 거쳐 원래 주소로, 수신 거부 링크는 그대로
        self.assertIn(f'/letter/o/1/{tok}.gif', html); self.assertIn(f'/letter/unsubscribe/{tok}"', html)
        click = re.search(r'href="https://[^"]+(/letter/c/1/[^"]+)"', html).group(1).replace('&amp;', '&')
        self.assertIn(tok, click)
        g = self.client.get(f'/letter/o/1/{tok}.gif')
        self.assertEqual((g.status_code, g.mimetype), (200, 'image/gif'))
        self.client.get(f'/letter/o/1/{tok}.gif')  # 두 번 열어도 한 명
        r2 = self.client.get(click)
        self.assertEqual(r2.status_code, 302); self.assertTrue(r2.headers['Location'].startswith('http'))
        self.assertEqual(self.client.get('/letter/c/1/%s?u=https://evil.example&s=bad' % tok).status_code, 404)  # 서명 없으면 안 넘김
        self.client.get('/letter/o/1/nobody.gif')  # 모르는 토큰은 무시
        st = L['stats'](r['id'])
        self.assertEqual((st['sent'], st['open'], st['click'], st['open_pct']), (2, 1, 1, 50))
        admin = self.login_admin()
        self.assertIn('열어 봄 50%', admin.get('/admin/letter').get_data(as_text=True))
        # 스티비: html·body 태그 없이, 수신 거부는 스티비 치환자, 추적 그림·우리 해지 링크 없음
        code = L['stibee_html'](letter)
        self.assertNotIn('<body', code); self.assertNotIn('<html', code); self.assertNotIn('<meta', code)
        self.assertIn('href="$%unsubscribe%$"', code); self.assertNotIn('/letter/o/', code); self.assertNotIn('/letter/unsubscribe/', code)
        self.assertIn('수신거부', code); self.assertNotIn('02-749', code)  # 바닥글에 전화번호 X (운영자 2026-11-01)
        # 맨 위 구독하기 버튼은 아직 구독 안 한 분께만: 스티비는 구독 필드로 숨기고, 사이트 발송(받는 사람 모두 구독자)엔 아예 없음 (운영자 2026-11-01)
        self.assertEqual(code.count('style="display:$%soboru_sub%$;"'), 2); self.assertIn('>구독하기</a>', code)
        self.assertNotIn('>구독하기</a>', L['email_parts'](letter)[1]); self.assertIn('수신 거부하기', L['email_parts'](letter)[1])
        page = admin.get(f"/admin/letter/{r['id']}").get_data(as_text=True)
        self.assertIn('HTML 에디터로 만들기', page); self.assertIn('id="lt-stibee"', page)

    def test_letter_admin_flow_and_settings(self):
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        self.assertEqual(self.client.get('/admin/letter').status_code, 302)  # 관리자만
        admin = self.login_admin()
        with patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith('SMTP')}, clear=True):
            page = admin.get('/admin/letter').get_data(as_text=True)
        self.assertIn('이번 호 만들기', page); self.assertIn('메일 발송 설정(SMTP)이 없어요', page)
        self.assertIn('소보루 레터', admin.get('/admin').get_data(as_text=True))  # 관리 메뉴
        sent, calls = [], []
        with patch.dict(os.environ, self.LETTER_NAVER), patch.object(self.site.naverhub, 'http', self.writer_naver(calls)), \
                patch.object(self.site.companydesk, 'post_json', self.letter_ai(sent)), patch.object(self.site.triage.corpus, 'related', self.letter_related):
            r = admin.post('/admin/letter', data={'_csrf': self.csrf(admin, '/admin/letter')})
        self.assertIn('/admin/letter/', r.headers['Location'])
        lid = int(r.headers['Location'].rsplit('/', 1)[1])
        # 설정: 기본은 자동 보내기 꺼짐·월요일
        self.assertEqual({k: v for k, v in self.site.app.extensions['soboru_letter']['settings']().items() if k in ('auto', 'day', 'freq', 'via')}, {'auto': 0, 'day': 0, 'freq': 'daily', 'via': 'site'})  # 기본은 매일 아침 (운영자 2026-11-01)
        self.assertIn('매일 아침', self.client.get('/letter').get_data(as_text=True))
        admin.post('/admin/letter/settings', data={'_csrf': self.csrf(admin, '/admin/letter'), 'auto': '1', 'day': '3', 'freq': 'weekly'})
        self.assertEqual({k: v for k, v in self.site.app.extensions['soboru_letter']['settings']().items() if k in ('auto', 'day', 'freq')}, {'auto': 1, 'day': 3, 'freq': 'weekly'})
        self.assertIn('매주 목요일 아침', self.client.get('/letter').get_data(as_text=True))
        admin.post('/admin/letter/settings', data={'_csrf': self.csrf(admin, '/admin/letter'), 'day': '3', 'freq': 'nope'})
        self.assertEqual(self.site.app.extensions['soboru_letter']['settings']()['freq'], 'daily')  # 모르는 값은 기본으로
        # 검토 필요가 있으면 확인 체크 없이는 보내지 않음, 메일 설정이 없으면 보내지 못함
        box = []
        self.letter_subs([('a@test.kr', 'active')])
        with patch.dict(os.environ, self.LETTER_MAIL), patch.object(self.site.notify.smtplib, 'SMTP_SSL', self.letter_smtp(box)):
            r = admin.post(f'/admin/letter/{lid}', data={'_csrf': self.csrf(admin, f'/admin/letter/{lid}'), 'act': 'send'}, follow_redirects=True)
            self.assertIn('보내지 않았어요', r.get_data(as_text=True)); self.assertEqual(box, [])
            # 테스트 메일은 적은 주소로 한 통만
            admin.post(f'/admin/letter/{lid}', data={'_csrf': self.csrf(admin, f'/admin/letter/{lid}'), 'act': 'test', 'test_to': 'editor@test.kr'})
        self.assertEqual([m['To'] for m in box], ['editor@test.kr']); self.assertTrue(box[0]['Subject'].startswith('[테스트]'))
        self.assertEqual(self.site.app.extensions['soboru_letter']['get'](lid)['status'], 'draft')
        with patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith('SMTP')}, clear=True):
            self.assertEqual(self.site.app.extensions['soboru_letter']['send'](lid)['status'], 'error')
        # 초안 지우기
        admin.post(f'/admin/letter/{lid}', data={'_csrf': self.csrf(admin, f'/admin/letter/{lid}'), 'act': 'delete'})
        self.assertIsNone(self.site.app.extensions['soboru_letter']['get'](lid))

    def test_letter_main_photo_fits_issue(self):
        # 운영자 2026-11-05: 메인 뉴스 사진이 매번 카트 — 그 뉴스에 맞는 구체적인 검색어부터, 최근 호에 쓴 사진은 건너뜀
        L = self.site.soboru_letter
        self.assertEqual(L.photo_queries(['Food delivery scooter!', 'food delivery scooter', 'rider helmet', 'x y']), ['food delivery scooter', 'rider helmet'])  # 3개까지, 겹치면 하나
        self.assertEqual(L.photo_queries('grocery cart'), ['grocery cart'])
        self.assertNotIn('grocery shopping cart', L.SYSTEM + str(getattr(L, 'USER', '')))
        asked = []
        def fake(path, params=None):
            if path != '/search/photos': return 200, {}
            asked.append(params['query'])
            res = {'scooter one': [], 'rider helmet': [{'id': 'old'}, {'id': 'new'}]}.get(params['query'], [])
            return 200, {'results': [{'id': r['id'], 'urls': {'raw': 'https://images.unsplash.com/' + r['id']}, 'user': {'name': 'A', 'links': {'html': 'https://unsplash.com/@a'}}} for r in res]}
        with patch.object(L, 'unsplash_call', fake), patch.dict(os.environ, {'UNSPLASH_ACCESS_KEY': 'k'}):
            ex = {'comment': {'_photo_q': ['scooter one', 'rider helmet']}}
            L.add_photos([], ex, {'old'})
        self.assertEqual(asked, ['scooter one', 'rider helmet']); self.assertEqual(ex['comment']['photo']['id'], 'new')

    def test_letter_magazine_excerpt(self):
        # 운영자 2026-11-05: 매거진 기사 하나는 레터 안에서 읽게 — 본문 앞부분(사진 줄·마크다운 빼고), 끝에 소제목만 남지 않게
        L = self.site.soboru_letter
        body = '첫 문단 **굵게**.\n\n[사진 /art/body/a.webp | 장면]\n\n## 소제목\n\n' + '가' * 950 + '\n\n## 다음\n\n안 나옴'
        self.assertEqual(L.mag_excerpt(body), [{'p': '첫 문단 굵게.'}, {'h': '소제목'}, {'p': '가' * 950}])
        self.assertEqual(L.mag_excerpt('## 맨 앞 소제목\n\n문단\n\n## 끝'), [{'p': '문단'}])
        # 운영자 2026-11-05: 여러 편 말고 글 하나를 축약본으로 — 글 전체에서 소제목마다 첫 문단 두 문장
        body = '하나. 둘. 셋. 넷.\n\n[사진 /a.webp]\n\n## 첫 소제목\n\n가. 나. 다.\n\n안 나옴.\n\n- 목록 안 나옴\n\n## 둘째 소제목\n\n**라**. 마.\n\n## 빈 소제목'
        self.assertEqual(L.mag_digest(body), [{'p': '하나. 둘.'}, {'h': '첫 소제목'}, {'p': '가.'}, {'h': '둘째 소제목'}, {'p': '라.'}])
        # 소제목 바로 밑에 붙은 목록이 소제목에 섞여 잘리지 않게, 목록만 있는 소제목은 앞 두 줄을 싣기
        self.assertEqual(L.mag_digest('도입.\n\n## 이렇게 대비하자\n- 설명서를 본다.\n- 믿지 않는다.\n- 셋째.'), [{'p': '도입.'}, {'h': '이렇게 대비하자'}, {'p': '설명서를 본다.'}])

    def test_letter_subscribe_confirm_unsubscribe(self):
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        box = []
        for path in ('/letter', '/life', '/'):
            page = self.client.get(path).get_data(as_text=True)
            self.assertIn('action="/letter/subscribe"', page, path); self.assertIn('name="website"', page, path); self.assertNotIn('name="agree"', page, path)
            if path == '/letter': self.assertIn('name="agree_privacy"', page); self.assertIn('name="agree_ad"', page); self.assertIn('id="sub"', page)  # 운영자 2026-11-05: 매거진은 동의 두 개 체크
            else: self.assertIn('동의한 것으로 봐요', page, path)
        with patch.dict(os.environ, self.LETTER_MAIL), patch.object(self.site.notify.smtplib, 'SMTP_SSL', self.letter_smtp(box)):
            r = self.letter_post(self.client, {'email': 'not-an-email', 'agree': '1'})
            self.assertIn('s=email', r.headers['Location'])
            r = self.client.post('/letter/subscribe', data={'_csrf': self.csrf(self.client, '/letter'), 'email': 'reader2@test.kr', 'checks': '1', 'agree_privacy': '1'})
            self.assertIn('s=consent', r.headers['Location'])  # 동의 하나만 체크하면 막음
            self.assertIn('두 가지 동의', self.client.get(r.headers['Location']).get_data(as_text=True))
            r = self.client.post('/letter/subscribe', data={'_csrf': self.csrf(self.client, '/letter'), 'email': 'bot@test.kr', 'agree': '1', 'website': 'http://spam'})
            self.assertIn('s=check', r.headers['Location'])  # 자동 등록 프로그램에도 같은 말, 저장은 안 함
            with self.site.conn() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM letter_subscribers').fetchone()[0], 0)
            self.assertEqual(box, [])
            r = self.client.post('/letter/subscribe', data={'_csrf': self.csrf(self.client, '/letter'), 'email': 'Reader@Test.kr ', 'agree': '1', 'place': 'home'})
            self.assertIn('s=check', r.headers['Location'])
            self.assertIn('확인 메일을 보냈어요', self.client.get(r.headers['Location']).get_data(as_text=True))
        with self.site.conn() as db: sub = db.execute('SELECT * FROM letter_subscribers').fetchone()
        self.assertEqual((sub['email'], sub['status'], sub['place']), ('reader@test.kr', 'pending', 'home'))
        self.assertTrue(sub['ip_hash'])
        self.assertEqual(len(box), 1)
        msg = box[0]
        self.assertEqual(msg['To'], 'reader@test.kr')
        self.assertEqual(msg['List-Unsubscribe'], f"<https://consumerjebo.co.kr/letter/unsubscribe/{sub['token']}>")
        self.assertEqual(msg['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click')
        self.assertIn(f"/letter/confirm/{sub['token']}", msg.get_body(('plain',)).get_content())
        self.assertIn(f"/letter/confirm/{sub['token']}", msg.get_body(('html',)).get_content())
        # 확인 전에는 보내지 않음 → 확인하면 구독
        self.assertIn('구독을 시작했어요', self.client.get(f"/letter/confirm/{sub['token']}").get_data(as_text=True))
        self.assertIn('이미 구독 중', self.client.get(f"/letter/confirm/{sub['token']}").get_data(as_text=True))
        self.assertEqual(self.client.get('/letter/confirm/nope').status_code, 404)
        with self.site.conn() as db: self.assertEqual(db.execute('SELECT status FROM letter_subscribers').fetchone()[0], 'active')
        # 한 번 클릭 해지: 링크(GET)로 바로, 이메일 주소는 지움
        self.assertIn('구독을 해지했어요', self.client.get(f"/letter/unsubscribe/{sub['token']}").get_data(as_text=True))
        with self.site.conn() as db: row = db.execute('SELECT * FROM letter_subscribers').fetchone()
        self.assertEqual(row['status'], 'unsubscribed'); self.assertTrue(row['email'].startswith('x:')); self.assertNotIn('reader', row['email'])
        # 메일 앱의 '구독 취소' 버튼(RFC 8058 POST)은 CSRF 토큰 없이도 됨
        self.letter_subs([('oneclick@test.kr', 'active')])
        r = self.site.app.test_client().post('/letter/unsubscribe/tok-oneclick', data={'List-Unsubscribe': 'One-Click'})
        self.assertEqual(r.status_code, 200)
        with self.site.conn() as db: self.assertEqual(db.execute("SELECT status FROM letter_subscribers WHERE token='tok-oneclick'").fetchone()[0], 'unsubscribed')
        self.assertEqual(self.site.app.test_client().post('/letter/subscribe', data={'email': 'x@test.kr', 'agree': '1'}).status_code, 400)  # 다른 POST는 그대로 CSRF 확인
        # 해지한 주소로 다시 신청하면 확인 메일부터 다시
        with patch.dict(os.environ, self.LETTER_MAIL), patch.object(self.site.notify.smtplib, 'SMTP_SSL', self.letter_smtp(box)):
            self.letter_post(self.client, {'email': 'reader@test.kr', 'agree': '1'})
        with self.site.conn() as db: row = db.execute("SELECT * FROM letter_subscribers WHERE id=?", (sub['id'],)).fetchone()
        self.assertEqual((row['email'], row['status']), ('reader@test.kr', 'pending')); self.assertEqual(len(box), 2)
        # 메일 설정이 없으면 신청을 받지 않음
        with patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith('SMTP')}, clear=True):
            r = self.letter_post(self.client, {'email': 'later@test.kr', 'agree': '1'})
        self.assertIn('s=nomail', r.headers['Location'])
        # 회원은 가입 이메일을 미리 채움
        member = self.site.app.test_client()
        self.signup(member, login_id='letter_m', nickname='레터회원', email='member@test.kr')
        self.assertIn('value="member@test.kr"', member.get('/letter').get_data(as_text=True))

    def test_letter_subscribe_rate_limit(self):
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        box = []
        with patch.dict(os.environ, self.LETTER_MAIL), patch.object(self.site.notify.smtplib, 'SMTP_SSL', self.letter_smtp(box)):
            codes = [self.letter_post(self.client, {'email': f'r{i}@test.kr', 'agree': '1'}).headers['Location'] for i in range(7)]
        self.assertEqual(['s=check' in c for c in codes], [True] * 5 + [False] * 2)
        self.assertIn('s=limit', codes[-1]); self.assertEqual(len(box), 5)

    def test_letter_send_only_active_with_unsubscribe_header_and_archive(self):
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        L = self.site.app.extensions['soboru_letter']
        r, _ = self.letter_make(bad=False)
        self.assertEqual(r['status'], 'made'); self.assertTrue(r['ok'])
        self.letter_subs([('one@test.kr', 'active'), ('two@test.kr', 'active'), ('wait@test.kr', 'pending'), ('x:gone', 'unsubscribed')])
        # 보내기 전: 공개 화면에 없음, 관리자만 웹 버전
        self.assertEqual(self.client.get('/letter/1').status_code, 404)
        self.assertNotIn('/letter/1"', self.client.get('/letter').get_data(as_text=True))
        admin = self.login_admin()
        self.assertEqual(admin.get('/letter/1').status_code, 200)
        box = []
        with patch.dict(os.environ, self.LETTER_MAIL), patch.object(self.site.notify.smtplib, 'SMTP_SSL', self.letter_smtp(box)), patch.object(self.site.soboru_letter, 'SEND_BATCH', 1):
            admin.post(f"/admin/letter/{r['id']}", data={'_csrf': self.csrf(admin, f"/admin/letter/{r['id']}"), 'act': 'send'})
            self.assertEqual(sorted(m['To'] for m in box), ['one@test.kr', 'two@test.kr'])  # 확인을 마친 구독자에게만
            again = L['send'](r['id'])
        self.assertEqual(again['status'], 'error'); self.assertEqual(len(box), 2)  # 두 번 보내지 않음
        for m in box:
            token = 'tok-' + m['To'].split('@')[0]
            self.assertEqual(m['List-Unsubscribe'], f'<https://consumerjebo.co.kr/letter/unsubscribe/{token}>')
            self.assertEqual(m['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click')
            self.assertIn('소보루 레터', m['From'])
            html, text = m.get_body(('html',)).get_content(), m.get_body(('plain',)).get_content()
            self.assertIn(f'/letter/unsubscribe/{token}', html); self.assertIn(f'/letter/unsubscribe/{token}', text)
            self.assertNotIn('__LETTER_UNSUB__', html + text)
            self.assertTrue(m['Subject'].startswith('🍞[소보루 레터]'))
        sent = L['get'](r['id'])
        self.assertEqual((sent['status'], sent['sent_count'], sent['failed']), ('sent', 2, 0)); self.assertTrue(sent['sent_at'])
        # 공개 보관함·웹 버전·사이트맵
        page = self.client.get('/letter').get_data(as_text=True)
        self.assertIn('/letter/1"', page); self.assertIn(sent['title'], page)
        web = self.client.get('/letter/1').get_data(as_text=True)
        self.assertIn(sent['items'][0]['title'], web); self.assertIn(sent['items'][0]['src']['url'], web); self.assertIn('기사 원문 보기', web)
        self.assertIn('전자상거래법 제17조', web)
        self.assertIn('/letter/1</loc>', self.client.get('/sitemap.xml').get_data(as_text=True))
        self.assertEqual(self.client.get('/letter/99').status_code, 404)

    def test_letter_picks_issues_many_outlets_covered(self):
        # 여러 언론이 함께 다룬 이슈가 먼저, 같은 이슈는 하나만, 개수는 기사량 따라 3~6개
        import urllib.parse
        day = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%a, %d %b %Y 09:00:00 +0900')
        heads = {'경제': ['한국은행 기준금리 동결 결정', '한은 기준금리 동결, 시장 예상대로', '기준금리 동결에 대출 금리도 멈춰', '반도체 수출 석 달째 늘어', '중소기업 대출 연체율 올라'],
                 '산업': ['수능 앞두고 교통 대책 발표', '지하철 파업 예고에 출근길 비상', '지하철 파업 협상 결렬 출근길 대란', '지하철 파업 첫날 출근길 혼잡'],
                 '물가': ['배추값 한 달 새 두 배'], '증시': ['코스피 외국인 매도에 하락'],
                 '정부 정책': ['정부 내년 예산안 국회 제출', '청년 월세 지원 대상 넓혀'], '리콜': ['전기밥솥 화재 위험 리콜']}
        def fake(method, url, headers, body, timeout):
            q = dict(urllib.parse.parse_qsl(url.split('?', 1)[1]))['query']
            return 200, {'total': 9, 'items': [{'title': t, 'description': t + ' 요약', 'link': f'https://n.news.naver.com/{abs(hash(t))}', 'originallink': f'https://news.example.co.kr/{abs(hash(t))}',
                                               'pubDate': day} for t in heads.get(q, [])]}
        with patch.dict(os.environ, self.LETTER_NAVER), patch.object(self.site.naverhub, 'http', fake), patch.object(self.site.triage.corpus, 'related', self.letter_related), \
                patch.object(self.site.soboru_letter, 'article_call', lambda url, timeout=8: (404, '')):
            mat = self.site.app.extensions['soboru_letter']['collect']()
        news = mat['news']
        titles = [x['title'] for x in news]
        self.assertEqual({x['kind'] for x in news}, {'econ'})  # 갓 구운 뉴스는 경제 기사만 (정책·제도는 아래 칸)
        self.assertFalse(set(titles) & set(heads['정부 정책']))
        self.assertEqual([x['title'] for x in mat['harm']], ['전기밥솥 화재 위험 리콜'])  # 피해 예방 뉴스는 따로
        self.assertEqual(len(titles), 3)  # 개수 고정 아님: 기사가 몰린 이슈 2개 + 최소 3개를 채울 1개 (운영자 2026-11-01)
        self.assertTrue(mat['comment'] and mat['comment'][0]['title'] == titles[0])  # 에디터 코멘트는 맨 앞 경제 이슈와 같은 이슈 기사들
        self.assertIn(titles[0][:4], ('지하철 ', '한국은행', '한은 기준', '기준금리'))  # 3곳이 다룬 이슈가 맨 앞
        self.assertEqual(sum('파업' in t for t in titles), 1)  # 같은 이슈는 하나만
        self.assertEqual(sum('동결' in t for t in titles), 1)
        self.assertTrue({titles[0][:2], titles[1][:2]} & {'지하'} and {titles[0][:2], titles[1][:2]} & {'한국', '한은', '기준'})  # 여러 곳이 다룬 두 이슈가 앞

    def test_letter_prefers_major_papers(self):
        # 같은 이슈면 매경·한경·서경 등 주요 신문 기사를 대표로, 숫자도 그 기사 본문으로 (운영자 2026-11-01)
        import urllib.parse
        with self.site.conn() as db: db.execute('DELETE FROM naver_cache')
        day = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%a, %d %b %Y 09:00:00 +0900')
        rows = {'금리': [('대출 한은 기준금리 동결 결정', 'news.example.co.kr'), ('시장 한은 기준금리 동결 결정', 'www.hankyung.com'), ('예상대로 한은 기준금리 동결 결정', 'www.blog-news.kr'),
                         ('배경은 한은 기준금리 동결 결정', 'biz.chosun.com')],
                '증시': [('마감 코스피 외국인 매도 하락', 'a.kr'), ('지속 코스피 외국인 매도 하락', 'b.kr'), ('전망 코스피 외국인 매도 하락', 'c.kr'), ('이유 코스피 외국인 매도 하락', 'd.kr')],
                '물가': [('배추값 한 달 새 두 배', 'e.kr'), ('라면 가격 올라', 'f.kr'), ('우유 납품가 협상', 'g.kr')],
                '고용': [('청년 취업자 줄어', 'h.kr'), ('제조업 일자리 감소', 'i.kr'), ('공공기관 채용 확대', 'j.kr')],
                '소비 트렌드': [('편의점 두바이 쫀득쿠키 품절 행렬', 'k.kr'), ('요즘 편의점 두바이 쫀득쿠키 품절', 'www.mk.co.kr'), ('또 편의점 두바이 쫀득쿠키 품절', 'l.kr')]}
        with self.site.conn() as db: db.execute("INSERT OR REPLACE INTO soboru_settings(key,value) VALUES('letter','{\"freq\": \"weekly\"}')")
        def unset():
            with self.site.conn() as db: db.execute("DELETE FROM soboru_settings WHERE key='letter'")
        self.addCleanup(unset)
        def fake(method, url, headers, body, timeout):
            q = dict(urllib.parse.parse_qsl(url.split('?', 1)[1]))['query']
            return 200, {'total': 9, 'items': [{'title': t, 'description': t + ' 요약', 'link': f'https://n.news.naver.com/{abs(hash(t))}', 'originallink': f'https://{h}/{abs(hash(t))}',
                                               'pubDate': day} for t, h in rows.get(q, [])]}
        with patch.dict(os.environ, self.LETTER_NAVER), patch.object(self.site.naverhub, 'http', fake), patch.object(self.site.triage.corpus, 'related', self.letter_related), \
                patch.object(self.site.soboru_letter, 'article_call', lambda url, timeout=8: (200, '<div id="dic_area">기준금리를 연 2.50%로 동결했다.</div><div>')):
            mat = self.site.app.extensions['soboru_letter']['collect']()
        first = mat['news'][0]
        self.assertIn('동결', first['title']); self.assertIn(first['source'], ('한국경제', '조선일보'))   # 주요 신문이 다룬 이슈가 앞, 대표는 주요 신문
        self.assertIn('2.50%', first['text'])
        self.assertTrue(any(o['source'] in ('한국경제', '조선일보') and o.get('text') for o in first['more']))   # 다른 주요 신문 본문도 같이
        self.assertEqual(mat['buzz'][0]['source'], '매일경제')   # 소비 트렌드도 주요 신문 기사를 대표로 (운영자 2026-11-01)

    def test_letter_weekly_schedule_and_auto_send(self):
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        L = self.site.app.extensions['soboru_letter']
        monday = datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())
        with self.site.conn() as db: db.execute("INSERT OR REPLACE INTO soboru_settings(key,value) VALUES('letter','{\"freq\": \"weekdays\"}')")
        self.assertEqual(L['weekly'](monday + datetime.timedelta(days=5))['status'], 'not_today')  # 평일 매일이면 주말에 쉼
        with self.site.conn() as db: db.execute("INSERT OR REPLACE INTO soboru_settings(key,value) VALUES('letter','{\"day\": 0, \"freq\": \"weekly\"}')")
        self.assertEqual(L['weekly'](monday + datetime.timedelta(days=1))['status'], 'not_today')  # 매주면 고른 요일만
        with self.site.conn() as db: db.execute("DELETE FROM soboru_settings WHERE key='letter'")
        self.letter_subs([('one@test.kr', 'active')])
        box, sent, calls = [], [], []
        with patch.dict(os.environ, {**self.LETTER_NAVER, **self.LETTER_MAIL}), patch.object(self.site.naverhub, 'http', self.writer_naver(calls)), \
                patch.object(self.site.companydesk, 'post_json', self.letter_ai(sent, bad=False)), patch.object(self.site.triage.corpus, 'related', self.letter_related), \
                patch.object(self.site.notify.smtplib, 'SMTP_SSL', self.letter_smtp(box)):
            r = L['weekly'](monday)  # 자동 보내기 꺼짐(기본) → 초안만
            self.assertEqual((r['status'], r['sent']), ('made', False)); self.assertEqual(box, [])
            self.assertEqual(L['weekly'](monday)['status'], 'exists')  # 같은 날에는 한 번
            with self.site.conn() as db: db.execute('DELETE FROM letters')
            with self.site.conn() as db: db.execute("INSERT OR REPLACE INTO soboru_settings(key,value) VALUES('letter','{\"auto\": 1, \"day\": 0}')")
            r = L['weekly'](monday)  # 켜면 검사를 통과한 호는 바로 보냄
            self.assertTrue(r['sent']); self.assertEqual([m['To'] for m in box], ['one@test.kr'])
            with self.site.conn() as db: db.execute('DELETE FROM letters')
            with patch.object(self.site.companydesk, 'post_json', self.letter_ai(sent, bad=True)):
                r = L['weekly'](monday)  # 검토 필요가 있으면 자동으로도 보내지 않음
            self.assertEqual((r['status'], r['sent']), ('made', False)); self.assertEqual(len(box), 1)
        # 확인하지 않은 신청은 7일 뒤 지움
        with self.site.conn() as db:
            db.execute("INSERT INTO letter_subscribers(email,token,status,created,asked) VALUES('old@test.kr','tok-old','pending','2000-01-01T00:00:00','2000-01-01T00:00:00')")
        L['weekly'](monday + datetime.timedelta(days=6))
        with self.site.conn() as db: self.assertIsNone(db.execute("SELECT 1 FROM letter_subscribers WHERE email='old@test.kr'").fetchone())

    def test_companies_rank(self):
        """운영자 2026-11-03: 업종별 기업 응대 순위. 전달된 제보가 MIN_N건보다 적은 기업은 안 나옴."""
        html = self.client.get('/companies/rank').get_data(as_text=True)
        self.assertIn('기업 응대 순위', html); self.assertIn('rk-empty', html)
        self.assertEqual(self.client.get('/companies/rank?ind=없는업종').status_code, 200)
        with self.site.conn() as db:
            cid = db.execute("INSERT INTO companies(name,biz_no,status,contact_name,contact_phone,contact_email,created) VALUES('순위테스트몰','','listed','','','','2026-01-01')").lastrowid
            old = (datetime.datetime.now() - datetime.timedelta(days=40)).isoformat(timespec='seconds')
            for i in range(6):
                case = db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,status,created,company_id,reviewed_at,forwarded_at,industry) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                  ('RK%d' % i, 'x', '기타', '순위테스트몰', '제목', '내용', '요청', '기업 전달', old, cid, old, old, '쇼핑·유통')).lastrowid
                if i < 3: db.execute("INSERT INTO messages(case_id,author,body,created,public) VALUES(?,?,?,?,1)", (case, '기업 답변', '답변', old))
        html = self.client.get('/companies/rank').get_data(as_text=True)
        self.assertIn('순위테스트몰', html); self.assertIn('답변 50%', html)

    def test_buy_check_guides(self):
        """운영자 2026-11-03: 사기 전에 확인. AI 초안은 공개 전엔 안 보이고, 공개하면 목록·글·업종 통계가 보임."""
        self.assertIn('곧 업종별 주의 글', self.client.get('/check').get_data(as_text=True))
        admin = self.login_admin()
        token = self.csrf(admin, '/admin/check')
        ind = '쇼핑·유통'
        with self.site.conn() as db:
            db.execute("INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,industry,public_consent,published) VALUES('CK-1','x','[환불] 환불 거절','몰','환불 안 됨','반품했는데 환불이 안 돼요 010-1234-5678','환불',?,?,1,1)",
                       (datetime.datetime.now().isoformat(timespec='seconds'), ind))
        sent = {}
        def fake(url, headers, body, timeout):
            sent['text'] = body['messages'][1]['content']
            return 200, {'choices': [{'message': {'content': '환불, 이것만 확인해요\n\n도입 문장이에요.\n\n## 사기 전에 확인할 것\n- 반품 조건 <b>캡처</b>'}}]}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'k'}), patch.object(self.site.companydesk, '_post_json', side_effect=fake):
            r = admin.post('/admin/check', data={'_csrf': token, 'industry': ind, 'ai': '1'})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('010-1234-5678', sent['text']); self.assertIn('환불: 1', sent['text'])
        with self.site.conn() as db: gid = db.execute('SELECT id FROM buy_guides ORDER BY id DESC').fetchone()[0]
        self.assertEqual(self.client.get('/check/%d' % gid).status_code, 404)
        admin.post('/admin/check/%d' % gid, data={'_csrf': token, 'act': 'save', 'title': '환불, 이것만 확인해요', 'industry': ind, 'status': 'published',
                                                 'body': '도입 문장이에요.\n\n## 사기 전에 확인할 것\n- 반품 조건 <b>캡처</b>'})
        page = self.client.get('/check/%d' % gid).get_data(as_text=True)
        self.assertIn('사기 전에 확인할 것</h2>', page); self.assertIn('&lt;b&gt;캡처', page); self.assertIn('1건', page)
        self.assertIn('환불, 이것만 확인해요', self.client.get('/check').get_data(as_text=True))

    def test_partners_and_report_stages(self):
        """운영자 2026-11-03: 협력 기관 로고·배너(관리자에서 넣기), 제보 목록 단계 탭, 제보하기 버튼 하나."""
        import io
        from PIL import Image
        html = self.client.get('/reports').get_data(as_text=True)
        self.assertIn('rf-partners', html); self.assertIn('alt="공정거래위원회"', html)  # 운영자 2026-11-04: 첫 화면 띠의 기관 8곳이 처음부터 관리자 목록에 들어 있음
        with self.site.conn() as db: db.execute('DELETE FROM partners')
        html = self.client.get('/reports').get_data(as_text=True)
        self.assertIn('rf-tabs', html); self.assertNotIn('reports-head-btns', html); self.assertNotIn('rf-partners', html)
        self.assertEqual(html.count('rf-go2'), 1); self.assertNotIn('누적 제보', html)
        for st in ('new', 'active', 'answer', 'done'): self.assertEqual(self.client.get('/reports?st=' + st).status_code, 200)
        admin = self.site.app.test_client()
        admin.post('/admin/login', data={'_csrf': self.csrf(admin, '/admin/login'), 'password': self.password})
        token = self.csrf(admin, '/admin/partners')
        buf = io.BytesIO(); Image.new('RGBA', (300, 100), (255, 0, 0, 255)).save(buf, 'PNG'); buf.seek(0)
        r = admin.post('/admin/partners', data={'_csrf': token, 'kind': 'partner', 'name': '시험 기관', 'link': 'javascript:alert(1)', 'image': (buf, 'a.png')}, content_type='multipart/form-data')
        self.assertEqual(r.status_code, 302)
        html = self.client.get('/reports').get_data(as_text=True)
        self.assertIn('rf-partners', html); self.assertIn('alt="시험 기관"', html); self.assertNotIn('javascript:', html)
        home = self.client.get('/').get_data(as_text=True)
        if 'hero-wall' in home: self.assertIn('img/orgs/c24.png', home); self.assertIn('foodsafetykorea', home); self.assertNotIn('pt-band', home)  # 운영자 2026-11-03: 홈 사진 아래 띠 대신 로고 4개
        with self.site.conn() as db: db.execute('DELETE FROM partners')

if __name__ == '__main__':
    unittest.main()
