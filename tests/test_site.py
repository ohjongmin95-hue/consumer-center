"""Exercise the live templates and existing report flow using an isolated database."""
import hashlib
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
            for table in ('internal_notes', 'company_invites', 'attachments', 'messages', 'cases', 'site_content', 'takedown_requests', 'board_votes', 'comments', 'posts'):
                db.execute('DELETE FROM ' + table)

    def csrf(self, client, path):
        response = client.get(path)
        self.assertEqual(response.status_code, 200)
        return re.search(r'name="_csrf" value="([^"]+)"', response.get_data(as_text=True))[1]

    def test_navigation_and_real_form(self):
        for path in ('/', '/reports', '/guide', '/process', '/types', '/faq', '/report', '/lookup', '/admin/login', '/terms', '/privacy', '/takedown', '/board', '/board/write'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn('class="section-nav"', response.get_data(as_text=True))
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('여러분의 제보가', home)
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
        for private in ('비공개 접수', '미동의 접수', '비공개 상세 내용', '테스트 업체'):
            self.assertNotIn(private, home)
        # 모든 제보가 목록에 올라오지만, 승인·동의가 없는 제보는 제목을 가림
        self.assertEqual(home.count('비밀글</span>'), 2)
        self.assertIn('<dt>전체</dt><dd>4</dd>', home)
        self.assertIn('class="step-badge">접수</span>', home)
        filtered_cat = self.client.get('/reports', query_string={'category': '배송·환불'}).get_data(as_text=True)
        self.assertEqual(filtered_cat.count('비밀글</span>'), 2)
        self.assertNotIn('공개 계약 문의', filtered_cat)
        self.assertEqual(self.client.get('/reports?q=비공개').get_data(as_text=True).count('비밀글</span>'), 0)
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
            '_csrf': token, 'category': '배송·환불', 'company': '테스트 업체',
            'subject': '테스트 환불 요청', 'description': '테스트 내용',
            'request_text': '환불 요청', 'consent': 'on', 'truth': 'on', 'use_consent': 'on', 'visibility': 'public',
            'share_company': 'on',
        })
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('제보가 접수됐습니다.', html)
        receipt = re.search(r'CJ-\d{6}-[A-F0-9]+', html)[0]
        code = re.search(r'overflow-wrap:anywhere">([^<]+)</p>', html)[1]
        token = self.csrf(self.client, '/lookup')
        response = self.client.post('/lookup', data={'_csrf': token, 'receipt': receipt, 'code': code}, follow_redirects=True)
        self.assertIn('테스트 환불 요청', response.get_data(as_text=True))
        self.assertIn('aria-current="step"', response.get_data(as_text=True))
        self.assertIn('현재 단계: 접수', response.get_data(as_text=True))
        admin = self.site.app.test_client()
        token = self.csrf(admin, '/admin/login')
        response = admin.post('/admin/login', data={'_csrf': token, 'password': self.password}, follow_redirects=True)
        self.assertIn('제보 관리', response.get_data(as_text=True))
        with self.site.conn() as db:
            case_id = db.execute('SELECT id FROM cases WHERE receipt=?', (receipt,)).fetchone()['id']
        path = '/admin/case/' + str(case_id)
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
        admin.post('/admin/content', data={'_csrf': token, 'section': 'faq', 'faq.q5': '새 질문', 'faq.a5': '새 답변', 'faq.q1': ''})
        faq = self.client.get('/faq').get_data(as_text=True)
        self.assertIn('새 질문', faq)
        self.assertNotIn('제보하면 바로 해결되나요?', faq)
        admin.post('/admin/content', data={'_csrf': token, 'reset_section': 'home'})
        self.assertIn('여러분의 제보가', self.client.get('/').get_data(as_text=True))
        self.assertIn('새 질문', self.client.get('/faq').get_data(as_text=True))

    def test_branding_policies_and_takedown(self):
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('<span>소비자</span>제보센터', home)
        self.assertIn('href="/privacy"', home)
        self.assertNotIn('신고', home)
        privacy = self.client.get('/privacy').get_data(as_text=True)
        self.assertIn('<h2>1. 개인정보의 처리 목적</h2>', privacy)
        self.assertIn('소보루(이하', privacy)  # {운영자} placeholder filled from operator info
        token = self.csrf(self.client, '/report')
        missing_truth = self.client.post('/report', data={'_csrf': token, 'category': '배송·환불', 'company': 'A', 'subject': 'B', 'description': 'C', 'request_text': 'D', 'consent': 'on'})
        self.assertEqual(missing_truth.status_code, 400)
        token = self.csrf(self.client, '/takedown')
        self.assertEqual(self.client.post('/takedown', data={'_csrf': token, 'requester': '업체'}).status_code, 400)
        done = self.client.post('/takedown', data={'_csrf': token, 'requester': '테스트 업체', 'contact': 'a@example.com', 'target': '제목', 'reason': '<b>사실과 다름</b>', 'consent': 'on'})
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
        admin.post('/admin/content', data={'_csrf': token, 'section': 'operator', 'operator.name': '새 운영사', 'operator.email': 'help@example.com'})
        privacy = self.client.get('/privacy').get_data(as_text=True)
        self.assertIn('새 운영사(이하', privacy)
        self.assertIn('이메일 help@example.com', self.client.get('/').get_data(as_text=True))

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
                '_csrf': token, 'category': '배송·환불', 'company': '공개 업체', 'subject': visibility + ' 제목',
                'description': '연락은 010-1234-5678 또는 me@example.com 으로', 'request_text': '환불',
                'contact': 'secret@example.com', 'consent': 'on', 'truth': 'on', 'visibility': visibility,
            })
            with self.site.conn() as db:
                ids[visibility] = db.execute('SELECT id FROM cases WHERE subject=?', (visibility + ' 제목',)).fetchone()['id']
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('href="/reports/%d">public 제목</a>' % ids['public'], home)
        self.assertNotIn('secret 제목', home)
        self.assertEqual(home.count('비밀글</span>'), 1)
        page = self.client.get('/reports/%d' % ids['public']).get_data(as_text=True)
        self.assertIn('[전화번호 비공개]', page)
        self.assertIn('[이메일 비공개]', page)
        self.assertNotIn('010-1234-5678', page)
        self.assertNotIn('secret@example.com', page)
        self.assertIn('공개 업체', page)
        self.assertEqual(self.client.get('/reports/%d' % ids['secret']).status_code, 404)
        token = self.csrf(self.client, '/report')
        no_choice = self.client.post('/report', data={'_csrf': token, 'category': '배송·환불', 'company': 'A', 'subject': 'B', 'description': 'C', 'request_text': 'D', 'consent': 'on', 'truth': 'on'})
        self.assertEqual(no_choice.status_code, 400)

    def test_home_shows_latest_and_reports_page_lists_all(self):
        with self.site.conn() as db:
            for i in range(25):
                db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,1,1)',
                           ('R%d' % i, 'x', '기타', '업체', '공개 제보 %02d' % i, '내용', '요청', '2026-10-09'))
        home = self.client.get('/').get_data(as_text=True)
        self.assertEqual(home.count('class="case-link"'), self.site.HOME_LATEST)
        self.assertIn('공개 제보 24', home)
        self.assertNotIn('공개 제보 10<', home)
        self.assertIn('href="/reports">', home)  # 메뉴와 전체 보기 링크
        live = self.client.get('/reports/latest')
        self.assertEqual(live.headers['Cache-Control'], 'no-store')
        self.assertEqual(live.get_data(as_text=True).count('class="case-link"'), self.site.HOME_LATEST)
        page1 = self.client.get('/reports').get_data(as_text=True)
        self.assertEqual(page1.count('class="case-link"'), 20)
        self.assertIn('aria-current="page">제보 목록</a>', page1)
        page2 = self.client.get('/reports?page=2').get_data(as_text=True)
        self.assertEqual(page2.count('class="case-link"'), 5)
        self.assertIn('공개 제보 00', page2)

    def test_disabled_intake_and_csrf(self):
        self.assertEqual(self.client.post('/report', data={}).status_code, 400)
        token = self.csrf(self.client, '/report')
        with patch.dict(os.environ, {'ENABLE_INTAKE': '0'}):
            self.assertEqual(self.client.post('/report', data={'_csrf': token}).status_code, 503)
            self.assertIn('disabled title="현재 접수 준비 중"', self.client.get('/report').get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
