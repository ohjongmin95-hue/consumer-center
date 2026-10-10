"""Exercise the live templates and existing report flow using an isolated database."""
import json, hashlib
import importlib.util
import os
from pathlib import Path
import re
import secrets
import tempfile
import unittest
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

    def setUp(self):
        self.client = self.site.app.test_client()
        with self.site.conn() as db:
            for table in ('internal_notes', 'company_invites', 'attachments', 'messages', 'cases', 'site_content', 'site_lists', 'takedown_requests', 'board_votes', 'comments', 'posts', 'users', 'login_attempts', 'staff', 'case_log', 'admin_settings'):
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
            self.assertIn('class="section-nav"', response.get_data(as_text=True))
        for path in ('/admin/login', '/reporter/login'):
            self.assertIn('noindex', self.client.get(path).get_data(as_text=True))
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('여러분의 제보가', home)
        self.assertIn('<title>소비자제보센터 | 소비자를위한신문</title>', home)
        self.assertIn('<meta property="og:title" content="소비자제보센터 | 소비자를위한신문">', home)
        self.assertIn('class="hero hero-art"', home)
        for side in ('left', 'right'):
            self.assertRegex(home, r'img/hero-%s\.svg\?v=\d+' % side)  # 그림이 바뀌면 주소도 바뀌어 캐시된 예전 그림이 보이지 않음
            self.assertEqual(self.client.get('/static/img/hero-%s.svg' % side).status_code, 200)
        self.assertIn('href="/report"', home)
        self.assertNotIn('localStorage', home)
        report = self.client.get('/report?category=배송·환불').get_data(as_text=True)
        self.assertIn('<option selected>배송·환불</option>', report)

    def test_public_list_filters_only_approved_consented_cases(self):
        with self.site.conn() as db:
            for receipt, subject, category, consent, published in (
                ('one', '공개 환불 요청', '배송·환불', 1, 1),
                ('two', '공개 계약 문의', '서비스·계약', 1, 1),
                ('three', '비공개 접수', '배송·환불', 1, 0),
                ('four', '미동의 접수', '배송·환불', 0, 1),
            ):
                db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (receipt, hashlib.sha256(b'test').hexdigest(), category, '테스트 업체', subject, '비공개 상세 내용', '요청', '2026-10-09', consent, published))
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('공개 환불 요청', home)
        self.assertIn('공개 계약 문의', home)
        for private in ('비공개 접수', '미동의 접수', '비공개 상세 내용'):
            self.assertNotIn(private, home)
        # 메인 카드: 공개 제보만 업체명을 보여 주고, 비공개 제보는 업체명을 가림
        self.assertEqual(home.count('class="rc-company">테스트 업체<'), 2)
        self.assertEqual(home.count('class="rc-company">업체 비공개<'), 2)
        self.assertNotIn('class="report-stats"', home)  # 메인에는 건수·실시간 표시 없음
        self.assertNotIn('live-dot', home)
        # 모든 제보가 목록에 올라오지만, 승인·동의가 없는 제보는 제목을 가림
        self.assertEqual(home.count('비밀글로 접수된 제보예요'), 2)
        self.assertIn('<dt>전체</dt><dd>4</dd>', self.client.get('/reports').get_data(as_text=True))
        self.assertIn('class="rc-status">접수</span>', home)
        filtered_cat = self.client.get('/reports', query_string={'category': '배송·환불'}).get_data(as_text=True)
        self.assertEqual(filtered_cat.count('비밀글</a>'), 2)
        self.assertNotIn('공개 계약 문의', filtered_cat)
        self.assertEqual(self.client.get('/reports?q=비공개').get_data(as_text=True).count('비밀글</a>'), 0)
        filtered = self.client.get('/reports', query_string={'q': '환불', 'category': '배송·환불'}).get_data(as_text=True)
        self.assertIn('공개 환불 요청', filtered)
        self.assertNotIn('공개 계약 문의', filtered)
        empty = self.client.get('/reports?q=missing').get_data(as_text=True)
        self.assertIn('검색 조건에 맞는 제보 내역이 없습니다.', empty)

    def test_submission_lookup_admin_and_company_response(self):
        token = self.csrf(self.client, '/report')
        self.assertEqual(self.client.post('/report', data={'_csrf': token}).status_code, 400)
        # Validation errors must still offer an enabled submit button.
        invalid = self.client.post('/report', data={'_csrf': token}).get_data(as_text=True)
        self.assertNotIn('disabled title="현재 접수 준비 중"', invalid)
        response = self.client.post('/report', data={
            '_csrf': token, 'industry': '쇼핑·유통', 'category': '배송·환불', 'company': '테스트 업체',
            'subject': '테스트 환불 요청', 'description': '테스트 내용',
            'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': '환불 요청', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'use_consent': 'on', 'visibility': 'public',
            'share_company': 'on',
        })
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('제보가 접수됐습니다.', html)
        receipt = re.search(r'CJ-\d{6}-[A-F0-9]+', html)[0]
        self.assertNotIn('조회 코드는 다시 표시되지 않습니다', html)
        token = self.csrf(self.client, '/lookup')
        wrong = self.client.post('/lookup', data={'_csrf': token, 'mode': 'phone', 'phone': '01012345678', 'password': '9999'})
        self.assertEqual(wrong.status_code, 401)
        # 하이픈 없이 넣어도 같은 번호로 찾음
        response = self.client.post('/lookup', data={'_csrf': token, 'mode': 'phone', 'phone': '01012345678', 'password': '1234'}, follow_redirects=True)
        self.assertIn('테스트 환불 요청', response.get_data(as_text=True))
        self.assertIn('aria-current="step"', response.get_data(as_text=True))
        self.assertIn('현재 단계: 접수', response.get_data(as_text=True))
        admin = self.site.app.test_client()
        token = self.csrf(admin, '/admin/login')
        response = admin.post('/admin/login', data={'_csrf': token, 'password': self.password}, follow_redirects=True)
        self.assertIn('관리자 홈', response.get_data(as_text=True))
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

    def login_admin(self):
        admin = self.site.app.test_client()
        token = self.csrf(admin, '/admin/login')
        admin.post('/admin/login', data={'_csrf': token, 'password': self.password})
        return admin

    def test_admin_edits_site_copy(self):
        self.assertEqual(self.client.get('/admin/content').status_code, 302)
        admin = self.login_admin()
        token = self.csrf(admin, '/admin/content')
        response = admin.post('/admin/content', data={
            '_csrf': token, 'section': 'home',
            'home.hero_title': '첫 줄\r\n<b>둘째 줄</b>', 'home.list_note': '', 'home.hero_button': '',
        }, follow_redirects=True)
        self.assertIn('문구를 저장했습니다.', response.get_data(as_text=True))
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('첫 줄<br>&lt;b&gt;둘째 줄&lt;/b&gt;', home)
        self.assertNotIn('여러분의 제보가', home)
        self.assertNotIn('공개에 동의하고 센터의 검토', home)  # optional field left blank hides it
        self.assertIn('제보하기 →', home)  # required field left blank falls back to default
        admin.post('/admin/content', data={'_csrf': token, 'reset_section': 'home'})
        self.assertIn('여러분의 제보가', self.client.get('/').get_data(as_text=True))

    def test_branding_policies_and_takedown(self):
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('<span>소비자</span>제보센터', home)
        self.assertIn('href="/privacy"', home)
        self.assertNotIn('신고센터', home)
        for link in ('href="/terms"', 'href="/privacy"', 'href="/youth"', '권리침해 신고 및 임시조치 안내'):
            self.assertIn(link, home)
        privacy = self.client.get('/privacy').get_data(as_text=True)
        self.assertIn('<h2 id="sec-1">1. 개인정보의 처리 목적</h2>', privacy)
        self.assertIn('<a href="#sec-13">13. 개인정보 처리방침의 변경</a>', privacy)
        self.assertIn('소보루(이하', privacy)  # {운영자} placeholder filled from operator info
        token = self.csrf(self.client, '/report')
        missing_truth = self.client.post('/report', data={'_csrf': token, 'industry': '쇼핑·유통', 'category': '배송·환불', 'company': 'A', 'subject': 'B', 'description': 'C', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': 'D', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234'})
        self.assertEqual(missing_truth.status_code, 400)
        full = {'_csrf': token, 'industry': '쇼핑·유통', 'category': '배송·환불', 'company': 'A', 'subject': 'B', 'description': 'C', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': 'D', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'secret'}
        for required in ('consent', 'share_company', 'use_consent', 'truth'):
            self.assertEqual(self.client.post('/report', data={k: v for k, v in full.items() if k != required}).status_code, 400, required)
        form = self.client.get('/report').get_data(as_text=True)
        for text in ('개인정보 제3자 제공', '저작권 동의', '게시글 작성 시로부터 3년', '제보 대상이 된 해당 사업자'):
            self.assertIn(text, form)
        self.assertNotIn('badge-opt', form)
        token = self.csrf(self.client, '/takedown')
        self.assertEqual(self.client.post('/takedown', data={'_csrf': token, 'requester': '업체'}).status_code, 400)
        done = self.client.post('/takedown', data={'_csrf': token, 'requester': '테스트 업체', 'contact': 'a@example.com', 'target': '제목', 'reason': '<b>사실과 다름</b>', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234'})
        self.assertIn('요청이 접수됐습니다.', done.get_data(as_text=True))
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
        admin.post('/admin/content', data={'_csrf': token, 'section': 'operator', 'operator.name': '새 운영사', 'operator.ceo': '오민주', 'operator.email': 'help@example.com'})
        privacy = self.client.get('/privacy').get_data(as_text=True)
        self.assertIn('새 운영사(이하', privacy)
        footer = self.client.get('/').get_data(as_text=True)
        self.assertIn('<li>이메일. help@example.com</li>', footer)
        self.assertIn('<li>상호. 새 운영사</li>', footer)
        self.assertIn('<li>대표. <a class="ft-quiet" href="/admin/login" rel="nofollow">오</a>민주</li>', footer)
        self.assertNotIn('<li>팩스.', footer)  # 비어 있는 항목은 표시하지 않음
        youth = self.client.get('/youth').get_data(as_text=True)
        self.assertIn('<h1>청소년보호정책</h1>', youth)
        self.assertIn('class="policy-toc"', youth)
        self.assertIn('<h2 id="sec-1">', youth)
        self.assertIn('청소년보호책임자: (운영자 정보 미입력)', youth)
        admin.post('/admin/content', data={'_csrf': self.csrf(admin, '/admin/content'), 'section': 'operator', 'operator.name': '새 운영사', 'operator.privacy_officer': '홍길동'})
        self.assertIn('청소년보호책임자: 홍길동', self.client.get('/youth').get_data(as_text=True))  # 비우면 개인정보 보호책임자로 대신 표시

    def post_form(self, client, path, data):
        token = self.csrf(client, path)
        return client.post(path, data={'_csrf': token, **data})

    def test_consumer_board(self):
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('>소비자게시판</a>', home)
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

    def test_public_and_secret_report_pages(self):
        ids = {}
        for visibility in ('public', 'secret'):
            token = self.csrf(self.client, '/report')
            self.client.post('/report', data={
                '_csrf': token, 'industry': '쇼핑·유통', 'category': '배송·환불', 'company': '공개 업체', 'subject': visibility + ' 제목',
                'description': '연락은 010-1234-5678 또는 me@example.com 으로', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': '환불',
                'contact': 'secret@example.com', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': visibility,
            })
            with self.site.conn() as db:
                ids[visibility] = db.execute('SELECT id FROM cases WHERE subject=?', (visibility + ' 제목',)).fetchone()['id']
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('href="/reports/%d">public 제목</a>' % ids['public'], home)
        self.assertNotIn('secret 제목', home)
        self.assertEqual(home.count('비밀글로 접수된 제보예요'), 1)
        self.assertEqual(self.client.get('/reports').get_data(as_text=True).count('비밀글</a>'), 1)
        page = self.client.get('/reports/%d' % ids['public']).get_data(as_text=True)
        self.assertIn('[전화번호 비공개]', page)
        self.assertIn('[이메일 비공개]', page)
        self.assertNotIn('010-1234-5678', page)
        self.assertNotIn('secret@example.com', page)
        self.assertIn('공개 업체', page)
        self.assertEqual(self.client.get('/reports/%d' % ids['secret']).status_code, 404)
        token = self.csrf(self.client, '/report')
        no_choice = self.client.post('/report', data={'_csrf': token, 'industry': '쇼핑·유통', 'category': '배송·환불', 'company': 'A', 'subject': 'B', 'description': 'C', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': 'D', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on'})
        self.assertEqual(no_choice.status_code, 400)

    def test_lookup_with_password(self):
        base = {'industry': '쇼핑·유통', 'category': '배송·환불', 'company': 'A', 'description': 'C', 'reporter_name': '홍길동', 'phone': '010-5555-1234',
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
        self.assertNotIn('비밀 제보 하나', page)
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
        self.assertEqual(home.count('class="case-link"'), self.site.HOME_LATEST)
        self.assertIn('공개 제보 24', home)
        self.assertNotIn('공개 제보 10<', home)
        self.assertIn('href="/reports">', home)  # 메뉴와 하단 전체 보기 링크
        admin = self.login_admin()
        admin.post('/admin/content', data={'_csrf': self.csrf(admin, '/admin/content'), 'section': 'home', 'home.latest_count': '4'})
        self.assertEqual(self.client.get('/').get_data(as_text=True).count('class="case-link"'), 4)
        admin.post('/admin/content', data={'_csrf': self.csrf(admin, '/admin/content'), 'section': 'home', 'home.latest_count': '이상한값'})
        self.assertEqual(self.client.get('/').get_data(as_text=True).count('class="case-link"'), self.site.HOME_LATEST)
        live = self.client.get('/reports/latest')
        self.assertEqual(live.headers['Cache-Control'], 'no-store')
        self.assertEqual(live.get_data(as_text=True).count('class="case-link"'), self.site.HOME_LATEST)
        page1 = self.client.get('/reports').get_data(as_text=True)
        self.assertEqual(page1.count('class="case-link"'), 20)
        self.assertIn('aria-current="page">소비자 제보 목록</a>', page1)
        page2 = self.client.get('/reports?page=2').get_data(as_text=True)
        self.assertEqual(page2.count('class="case-link"'), 5)
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
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('<meta name="description" content="소비자 피해를 제보하고', home)
        self.assertNotIn('naver-site-verification', home)
        detail = self.client.get('/reports/%d' % public_id).get_data(as_text=True)
        self.assertIn('<meta name="description" content="공개 본문 내용입니다">', detail)
        self.assertIn('<meta property="og:title" content="공개 제목 | 소비자제보센터">', detail)
        admin = self.login_admin()
        admin.post('/admin/content', data={'_csrf': self.csrf(admin, '/admin/content'), 'section': 'seo',
            'seo.naver_verification': '<meta name="naver-site-verification" content="abc123naver" />',
            'seo.google_verification': 'goog-XYZ_789', 'seo.daum_robots': 'DaumWebMasterTool:pin:id'})
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('<meta name="naver-site-verification" content="abc123naver">', home)
        self.assertIn('<meta name="google-site-verification" content="goog-XYZ_789">', home)
        self.assertTrue(self.client.get('/robots.txt').get_data(as_text=True).startswith('#DaumWebMasterTool:pin:id'))
        self.assertIn('noindex', admin.get('/admin').get_data(as_text=True))

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

    def test_menu_and_home_layout_editing(self):
        admin = self.login_admin()
        token = self.csrf(admin, '/admin/lists')
        menu = {'_csrf': token, 'list': 'menu', 'label': ['게시판', '제보하기', '블로그'], 'page': ['board', 'report', 'custom'], 'url': ['', '', 'https://blog.example.com']}
        self.assertEqual(admin.post('/admin/lists', data=menu).status_code, 302)
        home = self.client.get('/').get_data(as_text=True)
        nav = home[home.index('class="section-nav"'):home.index('</nav>')]
        self.assertLess(nav.index('>게시판</a>'), nav.index('>제보하기</a>'))
        self.assertIn('href="https://blog.example.com" target="_blank" rel="noopener">블로그</a>', nav)
        self.assertNotIn('이용 안내', nav)
        self.assertIn('href="/board" class="active"', self.client.get('/board').get_data(as_text=True))
        bad = admin.post('/admin/lists', data={**menu, 'url': ['', '', 'javascript:alert(1)']})
        self.assertEqual(bad.status_code, 400)
        self.assertNotIn('javascript:', self.client.get('/').get_data(as_text=True))
        self.assertEqual(admin.post('/admin/lists', data={**menu, 'page': ['board', 'report', 'nope']}).status_code, 400)
        # 메인 화면 블록: 순서·종류·개수·버튼
        blocks = {'_csrf': token, 'list': 'home_blocks',
                  'kind': ['notice', 'hero', 'faq', 'process', 'board_posts'],
                  'title': ['오픈 안내', '', '궁금해요', '', ''], 'count': ['', '', '2', '', '3'],
                  'body': ['소비자제보센터가 문을 열었어요.', '', '', '', ''],
                  'button_label': ['제보하러 가기', '', '', '', ''], 'button_link': ['/report', '', '', '', '']}
        self.assertEqual(admin.post('/admin/lists', data=blocks).status_code, 302)
        home = self.client.get('/').get_data(as_text=True)
        self.assertLess(home.index('오픈 안내'), home.index('class="hero hero-art"'))
        self.assertIn('<a class="primary" href="/report">제보하러 가기</a>', home)
        self.assertEqual(home.count('class="faq-item"'), 2)
        self.assertIn('class="process-cards"', home)
        self.assertNotIn('data-live-list="', home)  # 최근 제보 블록을 뺐음
        admin.post('/admin/lists', data={**blocks, 'kind': ['notice', 'hero_plain', 'faq', 'process', 'board_posts']})
        plain = self.client.get('/').get_data(as_text=True)
        self.assertIn('<section class="hero">', plain)
        self.assertNotIn('hero-left.svg', plain)
        self.assertEqual(admin.post('/admin/lists', data={**blocks, 'count': ['', '', '두개', '', '']}).status_code, 400)
        self.assertEqual(admin.post('/admin/lists', data={**blocks, 'button_link': ['javascript:x', '', '', '', '']}).status_code, 400)
        admin.post('/admin/lists', data={'_csrf': token, 'list': 'home_blocks', 'kind': ['latest_reports'], 'title': ['지금 들어온 제보'], 'count': ['3'], 'body': [''], 'button_label': [''], 'button_link': ['']})
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('지금 들어온 제보', home)
        self.assertIn('data-live-list="/reports/latest?n=3&amp;view=cards"', home)
        cards = self.client.get('/reports/latest?n=3&view=cards').get_data(as_text=True)
        self.assertIn('class="report-cards"', cards)

    def test_legacy_menu_labels_carry_over(self):
        with self.site.conn() as db:
            db.execute("INSERT INTO site_content(key,value,updated) VALUES('nav.faq','FAQ','x')")
        nav = self.client.get('/').get_data(as_text=True)
        self.assertIn('href="/faq">FAQ</a>', nav)
        self.assertIn('href="/reports">소비자 제보 목록</a>', nav)

    def test_process_page_cards(self):
        page = self.client.get('/process').get_data(as_text=True)
        self.assertEqual(page.count('class="process-card"'), 5)
        self.assertIn('<span class="pc-step">1단계</span>제보 접수', page)
        self.assertIn('<strong class="em">온라인으로 제보</strong>', page)
        self.assertEqual(page.count('class="step-icon"'), 5)
        admin = self.login_admin()
        token = self.csrf(admin, '/admin/lists')
        admin.post('/admin/lists', data={'_csrf': token, 'list': 'process_steps', 'title': ['상담', '끝'], 'icon': ['call', ''], 'body': ['**<i>빠르게</i>** 연락드려요', '']})
        page = self.client.get('/process').get_data(as_text=True)
        self.assertEqual(page.count('class="process-card"'), 2)
        self.assertIn('<strong class="em">&lt;i&gt;빠르게&lt;/i&gt;</strong> 연락드려요', page)
        self.assertEqual(admin.post('/admin/lists', data={'_csrf': token, 'list': 'process_steps', 'title': ['x'], 'icon': ['rocket'], 'body': ['']}).status_code, 400)

    def test_example_cards_fill_only_empty_slots(self):
        home = self.client.get('/').get_data(as_text=True)
        self.assertEqual(home.count('class="report-card is-sample'), self.site.HOME_LATEST)
        self.assertEqual(home.count('class="rc-sample">예시<'), self.site.HOME_LATEST)
        with self.site.conn() as db:
            for i in range(3):
                db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,1,1)',
                           ('E%d' % i, 'x', '기타', '업체', '실제 제보 %d' % i, '내용', '요청', '2026-10-09'))
        home = self.client.get('/').get_data(as_text=True)
        self.assertEqual(home.count('class="case-link"'), 3)
        self.assertEqual(home.count('class="report-card is-sample'), self.site.HOME_LATEST - 3)
        self.assertLess(home.index('실제 제보 2'), home.index('is-sample'))  # 실제 제보가 항상 앞
        self.assertNotIn('is-sample', self.client.get('/reports').get_data(as_text=True))
        self.assertEqual(self.client.get('/reports/latest?n=4&view=cards').get_data(as_text=True).count('is-sample'), 1)
        admin = self.login_admin()
        admin.post('/admin/lists', data={'_csrf': self.csrf(admin, '/admin/lists'), 'list': 'sample_reports', 'title': [''], 'category': [''], 'company': [''], 'status': ['']})
        self.assertNotIn('is-sample', self.client.get('/').get_data(as_text=True))

    def signup(self, client, login_id='sobo_ru', nickname='소보루', password='butter123', **extra):
        data = {'login_id': login_id, 'password': password, 'password2': password, 'nickname': nickname,
                'agree_terms': 'on', 'agree_privacy': 'on', 'agree_age': 'on', **extra}
        return self.post_form(client, '/signup', data)

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
        made = self.signup(self.client)
        self.assertEqual(made.status_code, 302)
        with self.site.conn() as db:
            user = db.execute('SELECT * FROM users').fetchone()
        self.assertNotEqual(user['pw_hash'], 'butter123')
        self.assertEqual(user['terms_version'], self.site.TERMS_VERSION)
        me = self.client.get('/me').get_data(as_text=True)
        self.assertIn('소보루님', me)
        other = self.site.app.test_client()
        dup = self.signup(other, login_id='SOBO_RU', nickname='다른이름')
        self.assertIn('이미 쓰고 있는 아이디', dup.get_data(as_text=True))
        self.assertIn('이미 쓰고 있는 닉네임', self.signup(other, login_id='another', nickname='소보루').get_data(as_text=True))

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
        report = self.post_form(self.client, '/report', {'industry': '쇼핑·유통', 'category': '배송·환불', 'company': '테스트몰', 'subject': '회원 제보', 'description': '배송이 오지 않았어요.', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': '환불', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'truth': 'on', 'visibility': 'secret'})
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
        self.assertIn('<span class="member-badge">회원</span>소보루', page)
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
        for label in ('사이트 편집', '구성 바꾸기', '숨은 문구·설정', '게시판 신고', '제보 처리'):
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
        staff.post(path, data={'_csrf': token, 'form': 'note', 'internal_note': '업체에 확인 필요'})
        staff.post(path, data={'_csrf': token, 'form': 'message', 'message': '확인 중입니다'})
        page = staff.get(path).get_data(as_text=True)
        self.assertIn('진행 단계 변경: 접수 → 검토 중', page)
        self.assertIn('<b>김민지</b>', page)
        self.assertIn('업체에 확인 필요', page)
        self.assertIn('확인 중입니다', page)
        self.assertIn('내 담당 제보', staff.get('/reporter').get_data(as_text=True))
        self.assertIn('배송이 안 와요', staff.get('/reporter?mine=1').get_data(as_text=True))
        self.assertNotIn('배송이 안 와요', staff.get('/reporter?status=종결').get_data(as_text=True))
        self.assertEqual(staff.get('/staff/case/%d' % case_id).headers['Location'], path)
        self.assertEqual(staff.get('/staff/login').headers['Location'], '/reporter/login')
        self.assertEqual(staff.get('/admin/reports/%d' % case_id).status_code, 302)
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
        short = admin.post('/admin/password', data={'_csrf': token, 'current': self.password, 'password': 'short1', 'password2': 'short1'}, follow_redirects=True)
        self.assertIn('12자 이상', short.get_data(as_text=True))
        done = admin.post('/admin/password', data={'_csrf': token, 'current': self.password, 'password': 'NewAdminPass99', 'password2': 'NewAdminPass99'})
        self.assertEqual(done.headers['Location'], '/admin')
        self.assertEqual(admin.get('/admin').status_code, 200)  # 바꾼 화면은 그대로 로그인
        self.assertEqual(other.get('/admin').status_code, 302)  # 다른 기기는 로그아웃
        fresh = self.site.app.test_client()
        old = self.post_form(fresh, '/admin/login', {'password': self.password})
        self.assertNotEqual(old.headers.get('Location'), '/admin')
        new = self.post_form(fresh, '/admin/login', {'password': 'NewAdminPass99'})
        self.assertEqual(new.headers['Location'], '/admin')

    def test_every_screen_text_is_editable(self):
        self.old_guide()
        admin = self.login_admin()
        page = admin.get('/admin/content').get_data(as_text=True)
        for key in ('report.submit', 'common.login', 'board.write_btn', 'member.signup_btn', 'msg.welcome', 'guide.u1'):
            self.assertIn('name="%s"' % key, page)
        token = self.csrf(admin, '/admin/content')
        admin.post('/admin/content', data={'_csrf': token, 'section': 'report', 'report.submit': '지금 제보하기', 'report.c3_title': '콘텐츠 이용 동의'})
        form = self.client.get('/report').get_data(as_text=True)
        self.assertIn('지금 제보하기', form)
        self.assertIn('콘텐츠 이용 동의', form)
        self.assertNotIn('제보 접수하기 ↗', form)
        admin.post('/admin/content', data={'_csrf': token, 'section': 'common', 'common.login': '로그인하기', 'site.name': '소비자제보센터', 'site.logo_rest': '제보센터'})
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
        self.assertTrue(admin.post('/admin/inline', data={'_csrf': token, 'key': 'status.n1', 'value': '접수 완료'}).get_json()['ok'])
        self.assertEqual(admin.post('/admin/inline', data={'_csrf': token, 'key': 'list:guide_basics:0:title', 'value': ''}).status_code, 400)
        self.assertEqual(admin.post('/admin/inline', data={'_csrf': token, 'key': 'list:menu:0:page', 'value': 'x'}).status_code, 400)
        self.assertEqual(admin.post('/admin/inline', data={'_csrf': token, 'key': 'nope', 'value': 'x'}).status_code, 400)
        public = self.client.get('/guide').get_data(as_text=True)
        self.assertIn('첨부 전 체크', public)
        self.assertIn('구매한 날', public)
        self.assertNotIn('data-k=', public)
        self.assertIn('접수 완료', self.client.get('/').get_data(as_text=True))
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
        ok = self.client.post('/report', data={'_csrf': t, 'industry': '쇼핑·유통', 'category': '배송·환불', 'company': 'A', 'subject': '사실확인 없이', 'description': 'C', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': 'D', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'visibility': 'secret'})
        self.assertEqual(ok.status_code, 200)
        # 직접 만든 동의 항목은 필수
        rows = self.site.load_lists()['report_consents'] + [{'kind': 'custom', 'title': '연락 동의', 'body': '확인 연락을 드릴 수 있어요.', 'agree': '연락에 동의해요.'}]
        admin.post('/admin/lists', data={'_csrf': token, 'list': 'report_consents', 'kind': [r['kind'] for r in rows], 'title': [r['title'] for r in rows], 'body': [r['body'] for r in rows], 'agree': [r['agree'] for r in rows]})
        public = self.client.get('/report').get_data(as_text=True)
        self.assertIn('연락 동의', public)
        self.assertIn('name="consent_custom_3"', public)
        base = {'_csrf': t, 'industry': '쇼핑·유통', 'category': '배송·환불', 'company': 'A', 'subject': 'B', 'description': 'C', 'reporter_name': '홍길동', 'phone': '010-1234-5678', 'request_text': 'D', 'consent': 'on', 'lookup_pw': '1234', 'lookup_pw2': '1234', 'share_company': 'on', 'use_consent': 'on', 'visibility': 'secret'}
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
        self.assertNotIn('아래 내용에 모두 동의합니다', self.client.get('/report').get_data(as_text=True))
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
        self.assertIn('<meta property="og:image" content="http://localhost/static/og-image.png', guide)
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
        base = {'_csrf': token, 'industry': '쇼핑·유통', 'category': '배송·환불', 'company': '상세몰', 'subject': '상세 제보', 'description': '내용', 'request_text': '환불',
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


if __name__ == '__main__':
    unittest.main()
