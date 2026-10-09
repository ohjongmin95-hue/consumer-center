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
            for table in ('internal_notes', 'company_invites', 'attachments', 'messages', 'cases', 'site_content'):
                db.execute('DELETE FROM ' + table)

    def csrf(self, client, path):
        response = client.get(path)
        self.assertEqual(response.status_code, 200)
        return re.search(r'name="_csrf" value="([^"]+)"', response.get_data(as_text=True))[1]

    def test_navigation_and_real_form(self):
        for path in ('/', '/guide', '/process', '/types', '/faq', '/report', '/lookup', '/admin/login'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn('class="section-nav"', response.get_data(as_text=True))
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('여러분의 신고가', home)
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
        filtered = self.client.get('/', query_string={'q': '환불', 'category': '배송·환불'}).get_data(as_text=True)
        self.assertIn('공개 환불 요청', filtered)
        self.assertNotIn('공개 계약 문의', filtered)
        empty = self.client.get('/?q=missing').get_data(as_text=True)
        self.assertIn('검색 조건에 맞는 신고 내역이 없습니다.', empty)

    def test_submission_lookup_admin_and_company_response(self):
        token = self.csrf(self.client, '/report')
        self.assertEqual(self.client.post('/report', data={'_csrf': token}).status_code, 400)
        # Validation errors must still offer an enabled submit button.
        invalid = self.client.post('/report', data={'_csrf': token}).get_data(as_text=True)
        self.assertNotIn('disabled title="현재 접수 준비 중"', invalid)
        response = self.client.post('/report', data={
            '_csrf': token, 'category': '배송·환불', 'company': '테스트 업체',
            'subject': '테스트 환불 요청', 'description': '테스트 내용',
            'request_text': '환불 요청', 'consent': 'on', 'public_consent': 'on',
            'share_company': 'on',
        })
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('신고가 접수됐습니다.', html)
        receipt = re.search(r'CJ-\d{6}-[A-F0-9]+', html)[0]
        code = re.search(r'overflow-wrap:anywhere">([^<]+)</p>', html)[1]
        token = self.csrf(self.client, '/lookup')
        response = self.client.post('/lookup', data={'_csrf': token, 'receipt': receipt, 'code': code}, follow_redirects=True)
        self.assertIn('테스트 환불 요청', response.get_data(as_text=True))
        admin = self.site.app.test_client()
        token = self.csrf(admin, '/admin/login')
        response = admin.post('/admin/login', data={'_csrf': token, 'password': self.password}, follow_redirects=True)
        self.assertIn('신고 관리', response.get_data(as_text=True))
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
        self.assertNotIn('여러분의 신고가', home)
        self.assertNotIn('공개에 동의하고 센터의 검토', home)  # optional field left blank hides it
        self.assertIn('신고하기 →', home)  # required field left blank falls back to default
        admin.post('/admin/content', data={'_csrf': token, 'section': 'faq', 'faq.q5': '새 질문', 'faq.a5': '새 답변', 'faq.q1': ''})
        faq = self.client.get('/faq').get_data(as_text=True)
        self.assertIn('새 질문', faq)
        self.assertNotIn('신고하면 바로 해결되나요?', faq)
        admin.post('/admin/content', data={'_csrf': token, 'reset_section': 'home'})
        self.assertIn('여러분의 신고가', self.client.get('/').get_data(as_text=True))
        self.assertIn('새 질문', self.client.get('/faq').get_data(as_text=True))

    def test_disabled_intake_and_csrf(self):
        self.assertEqual(self.client.post('/report', data={}).status_code, 400)
        token = self.csrf(self.client, '/report')
        with patch.dict(os.environ, {'ENABLE_INTAKE': '0'}):
            self.assertEqual(self.client.post('/report', data={'_csrf': token}).status_code, 503)
            self.assertIn('disabled title="현재 접수 준비 중"', self.client.get('/report').get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
