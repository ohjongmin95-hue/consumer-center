"""Exercise the live templates and existing report flow using an isolated database."""
import datetime, json, hashlib, io
import importlib.util
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
_REAL_THREAD = threading.Thread
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

    def test_www_redirects_to_bare_domain(self):
        r = self.client.get('/reports?page=2', base_url='https://www.consumerjebo.co.kr')
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r.headers['Location'], 'https://consumerjebo.co.kr/reports?page=2')
        self.assertEqual(self.client.get('/', base_url='https://consumerjebo.co.kr').status_code, 200)

    def test_process_disclaimer(self):
        # 법률 자문 안 함 안내는 하단이 아니라 처리 절차 페이지 맨 아래에만
        self.assertIn('법률 상담·자문', self.client.get('/process').get_data(as_text=True))
        self.assertNotIn('법률 상담·자문', self.client.get('/').get_data(as_text=True))

    def test_search_meta_tags(self):
        import json, re
        def ld(html):
            return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('<title>소보루(SOBORU)</title>', home)
        self.assertIn('<meta name="title" content="소보루(SOBORU)">', home)
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

    def setUp(self):
        self.client = self.site.app.test_client()
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
            self.assertIn('class="sb-header"', response.get_data(as_text=True))  # 소보루 머리글 하나뿐 (예전 소비자제보센터 머리글은 뺌)
            self.assertNotIn('class="section-nav"', response.get_data(as_text=True))
        for path in ('/admin/login', '/reporter/login'):
            self.assertIn('noindex', self.client.get(path).get_data(as_text=True))
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('nn-intro', home)
        self.assertIn('<title>소보루(SOBORU)</title>', home)
        self.assertIn('<meta property="og:title" content="소보루(SOBORU)">', home)
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
                           (receipt, hashlib.sha256(b'test').hexdigest(), category, '테스트 업체', subject, '비공개 상세 내용', '요청', '2026-10-09', consent, published))
            db.execute("UPDATE cases SET reviewed_at='2026-10-10T10:00:00' WHERE receipt='three'")  # 운영자가 보고 공개하지 않기로 둔 제보
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('공개 환불 요청', home)
        self.assertIn('공개 계약 문의', home)
        # 비밀글·공개 전 제보도 제목·업체명은 보이고(눌러도 비밀번호 창), 본문은 안 보임
        self.assertIn('미동의 접수', home)
        self.assertIn('비공개 접수', home)
        live = home.split('class="nn-sec nn-live')[1].split('</section>')[0]  # 방금 들어온 제보: 제목·업체만, 본문 없음
        self.assertNotIn('비공개 상세 내용', live)
        self.assertEqual(live.count('테스트 업체 ·'), 4)
        self.assertNotIn('nn-stats', home)  # 메인에는 건수 현황 없음
        self.assertNotIn('비공개 처리된 제보예요', home)
        self.assertNotIn('비밀글로 접수된 제보예요', home)
        self.assertIn('<dt>전체</dt><dd>4</dd>', self.client.get('/reports').get_data(as_text=True))
        self.assertIn('>접수</span>', live)
        filtered_cat = self.client.get('/reports', query_string={'category': '배송·교환·환불'}).get_data(as_text=True)
        self.assertIn('미동의 접수</a>', filtered_cat)
        self.assertIn('비공개 접수</a>', filtered_cat)
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
        self.assertIn('검색 조건에 맞는 제보 내역이 없습니다.', empty)

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

    def test_soboru_brand_switch_and_life(self):
        # 소보루 하나만: 설정 없이도 방문자·관리자 모두 소보루 화면 (예전 ?brand= 미리보기는 뺌)
        self.assertIn('sb-header', self.client.get('/').get_data(as_text=True))
        admin = self.login_admin()
        page = admin.get('/?brand=off').get_data(as_text=True)
        self.assertIn('sb-header', page)
        self.assertNotIn('미리보기 중', page)
        self.assertIn('<title>소보루(SOBORU)</title>', page)
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
        self.assertIn('<span class="sb-h-emo" aria-hidden="true">📌</span>소제목</h2>', art)  # 이모지 없는 예전 글도 이모지 칸
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
            order = lambda html: [k for k in ('nn-intro', 'nn-quick', 'nn-live', 'nn-pick', 'nn-answer', 'lt-card') if k in html]
            self.assertEqual(order(home), ['nn-intro', 'nn-quick', 'nn-live', 'nn-pick', 'nn-answer', 'lt-card'])
            self.assertLess(home.index('nn-intro'), home.index('nn-live'))
            self.assertIn('생활정보 카드 제목', home)
            self.assertIn('공개 제보 카드 제목', home)
            self.assertIn('소비자의 소리', home); self.assertLess(home.index('nn-live'), home.index('id="letter-sub"'))  # 제보 목록 바로 밑에 레터 구독
            self.assertNotIn('nn-stats', home)  # 맨 위 건수 현황은 뺌
            self.assertIn('🔒 비밀 제보 카드 제목', home)  # 비밀글도 제목·업체는 보이고 본문만 잠금
            self.assertIn('소보루 픽', home)  # 메뉴 이름 (커뮤니티 → 소보루 픽)
            self.assertIn('AI 학습 이용을 금지', home)  # 하단 무단 이용 금지 문구
            self.assertIn('User-agent: GPTBot', self.client.get('/robots.txt').get_data(as_text=True))
            self.assertIn('자주 묻는 질문', home); self.assertNotIn('피해 유형별 안내', home)  # 피해 유형별 안내는 메뉴에서 뺌(운영자 요청)
            self.assertNotIn('010-1234-5678', home)
            self.assertNotIn('ed-blockbar', home)  # 손님 화면에는 편집 막대 없음
            # 화면 편집: 예전 '메인 화면 순서' 주소는 화면 편집으로
            self.assertIn('/admin/screens#page-home', admin.get('/admin/home-plan').headers['Location'])
            page = admin.get('/admin/screens').get_data(as_text=True)
            for name in ('화면 편집', '홈', '생활정보', '소보루 픽', '제보', '기업', '법률 질문', '소보루 레터', '공통 머리글·바닥글', '소비자의 소리', '이 페이지 문구 모두 보기'):
                self.assertIn(name, page)
            token = self.csrf(admin, '/admin/screens')
            # 순서표 통째로: 레터를 맨 위로, 기업 답변 기록은 숨김
            r = admin.post('/admin/screens', data={'_csrf': token, 'page': 'home', 'act': 'order', 'block': ['letter', 'intro', 'quick', 'live', 'life', 'pick', 'answer'],
                                                   'show_letter': '1', 'show_intro': '1', 'show_quick': '1', 'show_live': '1', 'show_life': '1', 'show_pick': '1'})
            self.assertEqual(r.status_code, 302)
            home = self.client.get('/').get_data(as_text=True)
            self.assertEqual(order(home), ['nn-intro', 'nn-quick', 'nn-live', 'nn-pick', 'lt-card'])
            self.assertLess(home.index('lt-card'), home.index('nn-intro'))
            self.assertNotIn('nn-answer', home)
            # 한 칸씩: 레터 아래로, 기업 답변 다시 보이기, 소개 숨기기 (편집 모드 막대가 쓰는 주소)
            self.assertEqual(admin.post('/admin/screens', data={'_csrf': token, 'page': 'home', 'block': 'letter', 'act': 'down', 'ajax': '1'}).get_json(), {'ok': True})
            admin.post('/admin/screens', data={'_csrf': token, 'page': 'home', 'block': 'answer', 'act': 'show', 'ajax': '1'})
            admin.post('/admin/screens', data={'_csrf': token, 'page': 'home', 'block': 'intro', 'act': 'hide', 'ajax': '1'})
            home = self.client.get('/').get_data(as_text=True)
            self.assertNotIn('nn-intro', home)
            self.assertIn('nn-answer', home)
            self.assertLess(home.index('lt-card'), home.index('nn-quick'))
            with self.site.app.test_request_context('/'):
                self.assertEqual(self.site.app.extensions['soboru']['page_blocks']('home')[:3], [['intro', 0], ['letter', 1], ['quick', 1]])
            # 이상한 값은 무시하고, 모르는 묶음은 빠지고 빠진 묶음은 뒤에 붙음
            self.assertEqual(admin.post('/admin/screens', data={'_csrf': token, 'page': 'nope', 'block': 'x', 'act': 'up'}).status_code, 400)
            self.assertEqual(self.site.soboru.clean_blocks('letter', [['archive', 1], ['zzz', 1]]), [['archive', 1], ['hero', 1], ['feats', 1]])
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
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test'}), patch.object(self.site.companydesk, 'post_json', fake):
                page = admin.get('/admin/art').get_data(as_text=True)
                self.assertIn('AI 일러스트', page)
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
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test'}), patch.object(self.site.companydesk, 'post_json', fake):
                r = admin.post('/admin/life', data={'_csrf': self.csrf(admin, '/admin/life'), 'title': '헬스장 환불 받는 법', 'summary': '요약', 'body': '본문', 'category': '쇼핑', 'publish': '1'})
            aid = int(r.headers['Location'].rstrip('/').split('/')[-1])
            self.assertIn('헬스장 환불 받는 법', sent[-1]['prompt'])
            self.assertEqual(visitor.get(f'/art/life/{aid}.webp').status_code, 200)
            self.assertIn(f'/art/life/{aid}.webp', visitor.get(f'/life/{aid}').get_data(as_text=True))
            # 공개 제보는 게시되면 자동으로 그림 (내린 그림은 그대로 둠), 그림 없는 글은 한 번에 채우기
            with self.site.conn() as db:
                cid2 = db.execute('INSERT INTO cases(receipt,lookup_hash,category,company,subject,description,request_text,created,public_consent,published) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                  ('art2', 'x', '배송·교환·환불', '가게', '택배가 안 와요', '본문', '배송', '2026-10-09T10:00:00', 1, 0)).lastrowid
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test'}), patch.object(self.site.companydesk, 'post_json', fake):
                admin.post('/admin/art/fill', data={'_csrf': self.csrf(admin, '/admin/art'), 'kind': 'report'})
                self.assertEqual(visitor.get(f'/art/report/{cid2}.webp').status_code, 404)  # 게시 전이라 안 그림
                self.assertEqual(visitor.get(f'/art/report/{cid}.webp').status_code, 404)  # 내린 그림은 그대로
                with self.site.app.test_request_context('/'):
                    self.site.app.extensions['soboru_art']['auto']('report', cid2)  # 게시 전 제보는 그릴 글이 없어 조용히 넘어감
                with self.site.conn() as db: db.execute('UPDATE cases SET published=1 WHERE id=?', (cid2,))
                admin.post('/admin/art/fill', data={'_csrf': self.csrf(admin, '/admin/art'), 'kind': 'report'})
            self.assertEqual(visitor.get(f'/art/report/{cid2}.webp').status_code, 200)
            self.assertEqual(sent[-1]['quality'], 'medium')
            # 옛 그림체 그림은 한 번에 새 그림체로 (게시 중이면 게시 상태 그대로)
            with self.site.conn() as db: db.execute("UPDATE soboru_art SET style=1 WHERE kind='report' AND target_id=?", (cid2,))
            n = len(sent)
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test'}), patch.object(self.site.companydesk, 'post_json', fake):
                self.assertIn('옛 그림체 1개', admin.get('/admin/art').get_data(as_text=True))
                admin.post('/admin/art/fill', data={'_csrf': self.csrf(admin, '/admin/art'), 'kind': 'report', 'mode': 'old'})
            self.assertEqual(len(sent), n + 1)
            with self.site.conn() as db:
                r = db.execute("SELECT * FROM soboru_art WHERE kind='report' AND target_id=?", (cid2,)).fetchone()
            self.assertEqual((r['style'], r['status']), (self.site.soboru_art.STYLE_V, 'live'))
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test'}):
                self.assertNotIn('새 그림체로 다시 그리기', admin.get('/admin/art').get_data(as_text=True))
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
        self.assertIn('문구를 저장했습니다.', response.get_data(as_text=True))
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('첫 줄<br>&lt;b&gt;둘째 줄&lt;/b&gt;', home)
        self.assertIn('&lt;script&gt;x&lt;/script&gt;소보루!', home)
        self.assertNotIn('<script>x</script>', home)
        self.assertIn('<strong>굵게</strong> &lt;i&gt;기울임&lt;/i&gt;', home)
        self.assertIn('지금 막 온 제보', home)
        self.assertNotIn('억울한 일은 제보하고', home)
        self.assertIn('>제보하기</a><a class="nn-intro-link"', home)  # required field left blank falls back to default
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
        admin.post('/admin/content', data={'_csrf': token, 'section': 'operator', 'operator.name': '새 운영사', 'operator.manager': '홍민주', 'operator.email': 'help@example.com'})
        privacy = self.client.get('/privacy').get_data(as_text=True)
        self.assertIn('새 운영사(이하', privacy)
        footer = self.client.get('/').get_data(as_text=True)
        self.assertNotIn('<li>이메일.', footer)  # 푸터는 상호·주소·사업자등록번호·관리자만 표시
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

    def test_consumer_board(self):
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('>소보루 픽</a>', home)
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
        self.assertIn('data-kind="tip"', self.client.get('/board/write?type=tip').get_data(as_text=True))
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
            self.assertIn('cp-card', self.client.get('/').get_data(as_text=True))
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
        self.assertIn('pub-chip is-on', listing)
        self.assertIn('rv-chip rv-new">미검토', listing)
        # 운영자가 사후에 게시를 내리면 목록에는 '비공개'로 제목만, 누르면 조회 비밀번호 창
        self.post_form(admin, '/admin/reports/%d' % ids['public'], {'form': 'publish_review', 'decision': 'hold'})
        self.assertEqual(self.client.get('/reports/%d' % ids['public']).status_code, 404)
        listing = self.client.get('/reports').get_data(as_text=True)
        self.assertIn('href="/reports/%d/mine" title="센터가 개인정보를 확인한 뒤 내용이 공개돼요">public 제목</a>' % ids['public'], listing)
        self.assertIn('pending-tag">비공개', listing)
        self.assertNotIn('연락은 010', listing)
        self.assertEqual(self.post_form(admin, '/admin/reports/%d' % ids['secret'], {'form': 'publish_review', 'decision': 'approve'}).status_code, 400)
        self.post_form(admin, '/admin/reports/%d' % ids['public'], {'form': 'publish_review', 'decision': 'approve'})
        home = self.client.get('/').get_data(as_text=True)
        self.assertIn('href="/reports/%d">' % ids['public'], home)
        self.assertIn('public 제목', home)
        self.assertIn('href="/reports/%d/mine"' % ids['secret'], home)  # 비밀글은 제목이 보여도 비밀번호 창으로
        self.assertIn('secret 제목', home)
        listing = self.client.get('/reports').get_data(as_text=True)
        self.assertIn('secret 제목</a>', listing)
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
        with patch.object(notify, 'http_post', side_effect=lambda *a: kakao.append(a) or {}), patch.object(notify, 'send_email', side_effect=lambda *a: mails.append(a)):
            self.post_form(self.client, '/report', base)
        self.assertEqual((kakao, mails), ([], []))
        keys = {'SOLAPI_API_KEY': 'k', 'SOLAPI_API_SECRET': 's', 'SOLAPI_PFID': 'pf', 'KAKAO_TPL_RECEIVED': 'T1', 'KAKAO_TPL_STATUS': 'T2', 'KAKAO_TPL_MESSAGE': 'T3',
                'SMTP_HOST': 'smtp.example.com', 'SMTP_USER': 'bot@example.com', 'SMTP_PASSWORD': 'pw'}
        with patch.dict(os.environ, keys), patch.object(notify, 'http_post', side_effect=lambda *a: kakao.append(a) or {'statusCode': '2000'}), \
             patch.object(notify, 'send_email', side_effect=lambda *a: mails.append(a)):
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
            with patch.object(notify, 'http_post', side_effect=OSError('down')):
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
        with patch.dict(os.environ, keys), patch.object(notify, 'http_post', side_effect=lambda *a: sms.append(a) or {'statusCode': '2000'}), \
             patch.object(notify, 'send_email', side_effect=lambda *a: mails.append(a)):
            self.post_form(self.client, '/report', base)
        self.assertEqual([m[0] for m in mails], ['boss@example.com', 'ops@example.com'])
        self.assertIn('새 제보: 운영자 알림 제보', mails[0][1])
        self.assertIn('/admin/reports/', mails[0][2])
        self.assertIn('김소비 (010-2222-3333)', mails[0][2])
        self.assertEqual(sms[0][0], 'https://api.telegram.org/bot123:abc/sendMessage')
        self.assertEqual(sms[0][1]['chat_id'], '-1001')
        self.assertIn('김소비 (010-2222-3333)', sms[0][1]['text'])
        del sms[0]
        self.assertEqual(sms[0][1]['message']['to'], '01099998888')
        self.assertEqual(sms[0][1]['message']['from'], '021234567')
        self.assertIn('알림상점', sms[0][1]['message']['text'])
        self.assertIn('김소비 010-2222-3333', sms[0][1]['message']['text'])
        # 알림톡 템플릿이 있으면 카카오톡으로 (실패하면 문자로 대신)
        with patch.dict(os.environ, dict(keys, SOLAPI_PFID='pf', KAKAO_TPL_ADMIN='TA')), patch.object(notify, 'http_post', side_effect=lambda *a: sms.append(a) or {'statusCode': '2000'}), \
             patch.object(notify, 'send_email', side_effect=lambda *a: mails.append(a)):
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
        with patch.dict(os.environ, keys), patch.object(notify, 'http_post', side_effect=lambda *a: sms.append(a) or {}), \
             patch.object(notify, 'send_email', side_effect=lambda *a: mails.append(a)):
            self.post_form(admin, '/admin/reports/%d' % case_id, {'form': 'settings', 'status': '검토 중', 'assignee': ''})
        self.assertEqual(len(mails), 2)
        self.assertEqual(len(sms), 1)
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
             patch.object(notify, 'send_email', side_effect=lambda *a: mails.append(a)):
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
        self.assertEqual(live.count('<li><a href="/reports/'), 6)  # 방금 들어온 제보 6건
        self.assertIn('공개 제보 24', home)
        self.assertNotIn('공개 제보 04<', home)
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
        self.assertEqual(self.client.get('/faq').get_data(as_text=True).count('class="faq-item"'), 3)
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
        self.assertEqual(self.client.get('/faq').get_data(as_text=True).count('class="faq-item"'), 3)

    def test_legacy_fixed_slots_carry_over(self):
        with self.site.conn() as db:
            db.execute("INSERT INTO site_content(key,value,updated) VALUES('faq.q2','바뀐 두번째 질문','x'),('faq.q5','추가했던 다섯번째','x'),('faq.a5','답','x'),('process.step3_title','','x')")
        faq = self.client.get('/faq').get_data(as_text=True)
        self.assertIn('바뀐 두번째 질문', faq)
        self.assertIn('추가했던 다섯번째', faq)
        self.assertEqual(faq.count('class="faq-item"'), 4)
        process = self.client.get('/process').get_data(as_text=True)
        self.assertEqual(process.count('class="process-card"'), 2)

    def test_screen_editor_edits_every_soboru_text(self):
        # 화면 편집: 소보루 화면 글자(홈 큰 문구·머리글 메뉴·아래 탭·레터·생활정보·소보루 픽)를 편집 모드에서 눌러 고치고, 페이지별 문구 목록에서도 고침
        admin = self.login_admin()
        token = self.csrf(admin, '/admin/screens')
        admin.post('/admin/edit-mode', data={'_csrf': token, 'on': '1', 'next': '/'})
        pages = {'/': ('home.intro_title', 'home.live_title', 'home.pick_title', 'home.answer_eyebrow', 'sb.nav_home', 'sb.tab_home', 'common.ft_why', 'letter.card_title'),
                 '/life': ('life.title', 'life.cat_all', 'letter.subscribe'), '/board': ('cm.title', 'cm.pick_title'), '/letter': ('letter.h1', 'letter.f2', 'letter.archive_title'),
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
        self.assertIn('name="letter.h1"', page)
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
                self.assertNotIn('원문 비공개 내용', rows)
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
        self.assertIn('href="/admin/content?face=jebo"', content)  # 관리자 메뉴의 소비자제보센터 칸
        self.assertIn('소비자제보센터 ↗', content)  # 사이트 보기에서 어느 사이트로 갈지 고름
        jcontent = admin.get('/admin/content?face=jebo').get_data(as_text=True)
        self.assertIn('name="jebo.site_name"', jcontent); self.assertNotIn('name="seo.naver_verification"', jcontent)
        self.assertIn('소비자제보센터를 고치는 중', jcontent)
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
                page = c.get('/signup', base_url=J).get_data(as_text=True)
                self.assertIn('class="site-header"', page)  # 가입 화면은 소비자제보센터 화면 그대로
                token = re.search(r'name="_csrf" value="([^"]+)"', page)[1]
                r = c.post('/signup', base_url=J, data={'_csrf': token, 'login_id': 'jebo_user', 'password': 'butter123', 'password2': 'butter123', 'nickname': '제보회원',
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
            self.assertNotIn('name="nickname"', page)  # 닉네임은 묻지 않고 자동으로 정함
            self.assertEqual(self.post_form(self.client, '/auth/join', {}).status_code, 400)
            joined = self.post_form(self.client, '/auth/join', {'agree_terms': 'on', 'agree_privacy': 'on', 'agree_age': 'on'})
            self.assertEqual(joined.status_code, 302)
            with self.site.conn() as db:
                user = db.execute("SELECT * FROM users WHERE real_name='김실명'").fetchone()
                ident = db.execute('SELECT * FROM user_identities WHERE user_id=?', (user['id'],)).fetchone()
            self.assertRegex(user['nickname'], r'^소비자\d{4}$')  # 카카오 닉네임(실명일 수 있음)은 게시판에 쓰지 않음
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
            self.assertEqual(self.post_form(self.client, '/auth/join', {'agree_terms': 'on', 'agree_privacy': 'on', 'agree_age': 'on'}).status_code, 302)
            with self.site.conn() as db:
                u = db.execute("SELECT * FROM users WHERE real_name='박실명'").fetchone()
            self.assertRegex(u['nickname'], r'^소비자\d{4}$')
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
        self.assertIn('<span class="tri-chip tri-auto">자동</span>', listing)
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
        self.assertIn('소보루<span class="cm-member">회원</span>', page)
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
        self.assertIn('접수 완료', self.client.get('/reports').get_data(as_text=True))
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
        self.assertIn('아직 공개된 제보가 없어요', page)
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
        self.assertIsNone(other['company_id'])
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
             patch.object(notify, 'send_email', side_effect=lambda *a: mails.append(a)):
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
        self.assertIn('class="st-legend"', self.client.get('/reports').get_data(as_text=True))

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
        self.assertIn('승인을 기다리던 공개 제보가 1건', admin.get('/admin/reports').get_data(as_text=True))
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
        self.assertIn('<li class="st-5"><i aria-hidden="true"></i>처리 중</li>', reports)
        self.assertIn('<span class="step-badge">처리 중</span>', reports)
        self.assertNotIn('기업 답변 대기', reports)
        self.post_form(self.client, '/lookup', {'mode': 'phone', 'phone': '010-8181-3030', 'password': '4321'})
        case = self.client.get('/case').get_data(as_text=True)
        self.assertIn('aria-current="step"><span class="stepper-dot">3</span><span class="stepper-label">기업 전달', case)
        self.assertIn('현재 단계: 기업 전달</b> 해당 기업에 민원 전달', case)
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

    def test_ops_review_notice_requests_stats(self):
        # 3차: 심사 확인(개인정보 의심·중복 후보), 보완 요청, 추가 자료, 기업 안내 메일(빈도 제한·수신 거부), 정정·삭제·이의 신청, 운영 통계
        notify = self.site.notify
        notify.ASYNC = False
        self.addCleanup(setattr, notify, 'ASYNC', True)
        mails = []
        env = {'SMTP_HOST': 'smtp.example.com', 'SMTP_USER': 'bot@example.com', 'SMTP_PASSWORD': 'pw', 'ADMIN_ALERT_EMAIL': 'ops@example.com'}
        patcher = patch.dict(os.environ, env); patcher.start(); self.addCleanup(patcher.stop)
        mailer = patch.object(notify, 'send_email', side_effect=lambda *a: mails.append(a)); mailer.start(); self.addCleanup(mailer.stop)
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
        self.assertIn('이미 환불을 끝냈습니다', company.get(link).get_data(as_text=True))
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
                   'sections': [{'heading': '무슨 일이에요?', 'paragraphs': [f'자료를 보면 {nums[0]}이라는 숫자가 나와요.' + extra, '자료만으로는 원인을 알 수 없어요.']}],
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
            self.assertEqual(len(a['summary'].split('\n')), 3); self.assertIn('## ✅ 이렇게 하세요', a['body'])
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
            self.assertEqual(w['settings'](), {'auto': 0, 'per_run': 1, 'per_day': 3, 'publish': 0})
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
            self.assertEqual(w['settings'](), {'auto': 1, 'per_run': 1, 'per_day': 3, 'publish': 1})
            self.assertIn('자동 게시 중이에요', admin.get('/admin/life/ai').get_data(as_text=True))
            admin.post('/admin/life/ai/settings', data={'_csrf': self.csrf(admin, '/admin/life/ai'), 'act': 'stop'})
            self.assertEqual(w['settings'](), {'auto': 1, 'per_run': 1, 'per_day': 3, 'publish': 0})
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
        self.assertIn('[분량] 종합 기사', prompt); self.assertIn('최근 관련 뉴스', prompt)

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

    def test_writer_many_deep_articles_by_topic(self):
        self.writer_cleanup(); self.addCleanup(self.writer_cleanup)
        w = self.site.app.extensions['soboru_writer']; hub = self.site.naverhub
        sent, calls = [], []
        env = {'OPENAI_API_KEY': 'sk-test-key', 'NAVER_HUB_CLIENT_ID': 'cid-test', 'NAVER_HUB_CLIENT_SECRET': 'secret-test-value'}
        with patch.dict(os.environ, env), patch.object(hub, 'http', self.writer_naver(calls)), patch.object(self.site.companydesk, 'post_json', self.writer_ai(sent)), \
                patch.object(self.site.jebo, 'MIN_N', 10 ** 6):
            out = w['daily'](now=datetime.datetime(2026, 10, 20, 7, 30))  # 아침 5개: 순서표(검색 추이·뉴스·쇼핑) 다음 기획 기사·주제별 글로 채움
            made = [r for r in out if r['status'] == 'made']
            self.assertEqual([r['kind'] for r in made][3:], ['feature', 'rights'])
            out = w['daily'](now=datetime.datetime(2026, 10, 20, 19, 30))  # 저녁에 돌면 오후 몫까지 채워 하루 15개
            made += [r for r in out if r['status'] == 'made']
            self.assertEqual(len(made), 15)
            self.assertEqual([r['kind'] for r in made][5:8], ['word', 'feature', 'shopcat'])
            with self.site.conn() as db:
                feats = db.execute("SELECT a.title,a.category,a.ext_key,x.facts FROM articles a JOIN ai_articles x ON x.article_id=a.id WHERE x.kind='feature'").fetchall()
                titles = [r[0] for r in db.execute("SELECT title FROM articles WHERE origin='ai'")]
            self.assertGreaterEqual(len(feats), 4)
            self.assertEqual(len({r['category'] for r in feats}), len(feats))  # 기획 기사는 글이 적은 분야부터: 분야가 겹치지 않게
            self.assertEqual(len(set(titles)), len(titles))  # 같은 제목은 다시 안 씀
            f = json.loads(feats[0]['facts'])
            self.assertIn('최근 관련 뉴스(제목·요약만)', f); self.assertIn('검색 추이(네이버 데이터랩)', f)
            self.assertIn('[분량] 잡지 기획 기사', json.dumps(sent, ensure_ascii=False))
            with self.site.conn() as db:
                rows = {}
                for r in db.execute("SELECT a.ext_key,x.kind,x.facts FROM articles a JOIN ai_articles x ON x.article_id=a.id ORDER BY a.id"): rows.setdefault(r['kind'], r)  # 종류별 첫 글
            self.assertTrue(rows['rights']['ext_key'].startswith('ai:rights:온라인 쇼핑 청약철회:'))
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
        self.rag_setup()
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
        self.assertEqual(len(rows), len(lawrag.TEST_QUESTIONS)); self.assertEqual(len(rows), 20)
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
            self.post_form(self.client, '/auth/join', {'agree_terms': 'on', 'agree_privacy': 'on', 'agree_age': 'on'})
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
            news = json.loads(body['messages'][1]['content'].split('[이번 호 뉴스]\n', 1)[1])
            items = []
            for x in news:
                n = x['번호']
                text = f'이번 주에 이런 소식이 있었어요. 비슷한 일을 겪은 분이 많대요. 자세한 내용은 기사 원문에서 확인해 보세요.'
                if n == 1: text += ' 관련 상담이 30% 늘었다고 해요.'
                if bad and n == 2: text += ' 작년보다 98765명 늘었대요.'
                if bad and n == 3: text += ' ' + x['제목'] + ' ' + x['요약'] + ' 이런 기사였어요.'
                law = x['법 조문 후보'][0]['id'] if n == 1 and x['법 조문 후보'] else ('9-L9' if n == 2 else '')
                items.append({'no': n, 'title': ['첫째', '둘째', '셋째', '넷째', '다섯째'][n - 1] + ' 소식, 이것만 알면 돼요', 'body': text, 'tip': '이럴 땐 이렇게: 영수증과 대화 기록부터 챙겨 두세요.', 'law': law})
            out = {'subject': '이번 주 소비자 뉴스, 이것만 보면 끝', 'intro': '안녕하세요, 소보루 레터예요. 이번 주 꼭 알아 둘 소식을 모았어요.', 'outro': '다음 주에 또 만나요.', 'items': items}
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

    def letter_make(self, bad=True):
        sent, calls = [], []
        with patch.dict(os.environ, self.LETTER_NAVER), patch.object(self.site.naverhub, 'http', self.writer_naver(calls)), \
                patch.object(self.site.companydesk, 'post_json', self.letter_ai(sent, bad)), patch.object(self.site.triage.corpus, 'related', self.letter_related):
            r = self.site.app.extensions['soboru_letter']['generate']('admin')
        return r, sent

    def letter_post(self, client, data):
        return client.post('/letter/subscribe', data={'_csrf': self.csrf(client, '/letter'), **data})

    def letter_subs(self, rows):
        with self.site.conn() as db:
            for email, status in rows:
                db.execute('INSERT INTO letter_subscribers(email,token,status,created) VALUES(?,?,?,?)', (email, 'tok-' + email.split('@')[0], status, '2026-10-01T09:00:00'))

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
        self.assertEqual(len(L['items']), 5)  # 3~5개
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
        sec = L['sections']
        self.assertEqual([x['nick'] for x in sec['reviews']], ['알뜰**', '꼼꼼**'])
        self.assertNotIn('010-1234-5678', json.dumps(sec, ensure_ascii=False))
        self.assertEqual([a['title'] for a in sec['life']], ['택배 분실 보상 정리'])
        self.assertEqual(sec['campaign']['url'], '/pick/delivery')
        # 메일: HTML(표·인라인)과 글 두 가지, 원문·법령 링크, 해지 링크
        subject, html, text = self.site.app.extensions['soboru_letter']['email_parts'](L, 'tok-x')
        icon = self.site.soboru_letter.TOPIC_ICON[it1['topic']][0]  # 분야를 남겨 분야 그림(토스페이스)을 붙임
        self.assertIn(f'/static/img/tf/{icon}.png', html); self.assertIn('오늘의 메인뉴스', html)
        self.assertLess(html.index('soboru-wordmark.png'), html.index('soboru-character-hero.png'))  # 머리는 소보루 레터 그림과 글자 로고, 캐릭터는 아래에서만
        self.assertIn('이번 주 소비자 뉴스, 이것만 보면 끝', subject)
        for part in (html, text):
            self.assertIn('첫째 소식, 이것만 알면 돼요', part); self.assertIn(it1['src']['url'], part)
            self.assertIn('/letter/unsubscribe/tok-x', part); self.assertIn('https://www.law.go.kr/', part)
        self.assertIn('max-width:600px', html); self.assertIn('원문 보기 ›', html); self.assertIn('써 본 사람들이 추천한 리뷰', html)
        self.assertIn('서울시 강남구', html)  # 보내는 곳 주소 (사이트 하단 정보)
        # 운영자가 고쳐 저장하면 같은 자료로 다시 검사
        admin = self.login_admin()
        page = admin.get(f"/admin/letter/{r['id']}").get_data(as_text=True)
        self.assertIn('srcdoc=', page); self.assertIn('검토 필요', page)
        form = {'title': L['title'], 'intro': L['intro'], 'outro': L['outro'], 'act': 'save'}
        for i, it in enumerate(L['items']): form.update({f'title{i}': it['title'], f'body{i}': it['body'], f'tip{i}': it['tip']})
        form['body1'] = '숫자 없이 고쳤어요.'; form['drop2'] = '1'
        admin.post(f"/admin/letter/{r['id']}", data={'_csrf': self.csrf(admin, f"/admin/letter/{r['id']}"), **form})
        L = self.site.app.extensions['soboru_letter']['get'](r['id'])
        self.assertEqual(len(L['items']), 4); self.assertTrue(L['check_ok'], L['problems'])

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
        self.assertEqual(self.site.app.extensions['soboru_letter']['settings'](), {'auto': 0, 'day': 0, 'freq': 'weekdays'})  # 기본은 평일 아침마다
        self.assertIn('평일 아침마다', self.client.get('/letter').get_data(as_text=True))
        admin.post('/admin/letter/settings', data={'_csrf': self.csrf(admin, '/admin/letter'), 'auto': '1', 'day': '3', 'freq': 'weekly'})
        self.assertEqual(self.site.app.extensions['soboru_letter']['settings'](), {'auto': 1, 'day': 3, 'freq': 'weekly'})
        self.assertIn('매주 목요일 아침', self.client.get('/letter').get_data(as_text=True))
        admin.post('/admin/letter/settings', data={'_csrf': self.csrf(admin, '/admin/letter'), 'day': '3', 'freq': 'nope'})
        self.assertEqual(self.site.app.extensions['soboru_letter']['settings']()['freq'], 'weekdays')  # 모르는 값은 기본으로
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

    def test_letter_subscribe_confirm_unsubscribe(self):
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        box = []
        for path in ('/letter', '/life', '/'):
            page = self.client.get(path).get_data(as_text=True)
            self.assertIn('action="/letter/subscribe"', page, path); self.assertIn('name="website"', page, path); self.assertIn('name="agree"', page, path)
        with patch.dict(os.environ, self.LETTER_MAIL), patch.object(self.site.notify.smtplib, 'SMTP_SSL', self.letter_smtp(box)):
            r = self.letter_post(self.client, {'email': 'not-an-email', 'agree': '1'})
            self.assertIn('s=email', r.headers['Location'])
            r = self.letter_post(self.client, {'email': 'reader@test.kr'})
            self.assertIn('s=consent', r.headers['Location'])
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
            self.assertTrue(m['Subject'].startswith('[소보루 레터]'))
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
        # 여러 언론이 함께 다룬 이슈가 먼저, 같은 이슈는 하나만, 한 분야는 2개까지
        import urllib.parse
        day = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%a, %d %b %Y 09:00:00 +0900')
        heads = {'경제': ['한국은행 기준금리 동결 결정', '한은 기준금리 동결, 시장 예상대로', '기준금리 동결에 대출 금리도 멈춰', '반도체 수출 석 달째 늘어', '중소기업 대출 연체율 올라'],
                 '사회': ['수능 앞두고 교통 대책 발표', '지하철 파업 예고에 출근길 비상', '지하철 파업 협상 결렬 출근길 대란', '지하철 파업 첫날 출근길 혼잡'],
                 '국제': ['미국 대선 후보 첫 토론', '일본 엔화 약세 계속']}
        def fake(method, url, headers, body, timeout):
            q = dict(urllib.parse.parse_qsl(url.split('?', 1)[1]))['query']
            return 200, {'total': 9, 'items': [{'title': t, 'description': t + ' 요약', 'link': f'https://n.news.naver.com/{abs(hash(t))}', 'originallink': f'https://news.example.co.kr/{abs(hash(t))}',
                                               'pubDate': day} for t in heads.get(q, [])]}
        with patch.dict(os.environ, self.LETTER_NAVER), patch.object(self.site.naverhub, 'http', fake), patch.object(self.site.triage.corpus, 'related', self.letter_related):
            news = self.site.app.extensions['soboru_letter']['collect']()
        titles = [x['title'] for x in news]
        self.assertEqual(len(titles), 5)
        self.assertIn(titles[0][:4], ('지하철 ', '한국은행', '한은 기준', '기준금리'))  # 3곳이 다룬 이슈가 맨 앞
        self.assertEqual(sum('파업' in t for t in titles), 1)  # 같은 이슈는 하나만
        self.assertEqual(sum('동결' in t for t in titles), 1)
        self.assertLessEqual(sum(t in heads['경제'] for t in titles), 2)  # 한 분야 2개까지

    def test_letter_weekly_schedule_and_auto_send(self):
        self.letter_cleanup(); self.addCleanup(self.letter_cleanup)
        L = self.site.app.extensions['soboru_letter']
        monday = datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())
        self.assertEqual(L['weekly'](monday + datetime.timedelta(days=5))['status'], 'not_today')  # 기본(평일 매일)은 주말에 쉼
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

if __name__ == '__main__':
    unittest.main()
