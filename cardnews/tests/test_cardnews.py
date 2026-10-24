"""카드뉴스 만들기 시험: Claude·네이버·기사 읽기는 가짜로 바꿔 끼우고, 임시 data 폴더에서 돌린다."""
import importlib, json, os, re, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
TMP = tempfile.TemporaryDirectory()
os.environ['CARDNEWS_DATA'] = TMP.name
os.environ.pop('ANTHROPIC_API_KEY', None)
import cards, kakao, server  # noqa: E402

PAGE = ('<html><head><meta property="og:title" content="온라인몰 환불 지연하면 하루 0.1% 배상금"><meta property="og:site_name" content="소보루일보">'
        '<meta property="article:published_time" content="2026-10-22T09:00:00+09:00"></head><body><nav>메뉴 메뉴 메뉴 메뉴 메뉴 메뉴 메뉴 메뉴</nav><article>'
        '<p>공정거래위원회는 22일 온라인 쇼핑몰이 환불을 3영업일 넘게 미루면 지연 배상금을 물리는 개정안을 발표했다고 밝혔다.</p>'
        '<p>배상금은 늦어진 하루마다 환불액의 0.1%이며, 개정안은 2027년 1월 1일부터 시행된다고 공정위 관계자는 설명했다.</p>'
        '<p>지난해 한국소비자원에 접수된 환불 지연 피해는 1만2000건으로 전년보다 크게 늘었다는 통계도 함께 공개됐다.</p>'
        '<p>공정위는 소비자가 환불을 요청한 날짜를 남겨 두면 나중에 배상금을 받을 때 도움이 된다고 안내했다.</p>'
        '<p>ⓒ 소보루일보 무단전재 및 재배포 금지</p></article></body></html>')
OTHER = PAGE.replace('소보루일보', '다른일보').replace('공정거래위원회는 22일', '공정위가 22일 발표한 내용에 따르면')

def pages(url, timeout=10, limit=0):
    return {'https://news.test/a/1': PAGE, 'https://other.test/b/2': OTHER, 'https://news.test/a/2': PAGE}.get(url, '')


def fake_claude(sent, copy=False, bait=False, number='3영업일'):
    def fake(cfg, system, user, schema, max_tokens, effort='medium'):
        sent.append(user)
        body = '공정위가 22일 온라인 쇼핑몰이 환불을 3영업일 넘게 미루면 지연 배상금을 물리는 개정안을 발표했다고 밝혔다' if copy else f'환불이 {number} 넘게 늦어지면 배상금이 붙어요.'
        return {'topic': '환불 | 늦어지면 배상금 붙어요', 'emoji': '💸',
                'covers': [{'line1': '충격! 환불 늦으면?' if bait and i == 0 else '환불 늦어지면?' + 'ㄱㄴㄷㄹㅁ'[i], 'line2': '하루 0.1% 배상'} for i in range(5)],
                'cover_tags': [{'text': '피해 1만2000건', 'dir': 'up'}], 'cover_scene': 'a parcel box and a calendar',
                'cards': [{'kicker': '언제부터', 'title': '2027년 1월 1일부터', 'body': body, 'tags': [], 'scene': 'calendar'},
                          {'kicker': '그래서 나한테 뭐가 달라지는데?', 'title': '기다리지 마세요', 'body': '환불 날짜를 꼭 적어 두세요.', 'tags': [{'text': '하루 0.1%', 'dir': ''}], 'scene': 'receipt'}],
                'tips': ['환불 요청한 날짜 캡처해 두기', '3영업일 지나면 판매자에게 다시 묻기', '1372 소비자상담센터에 물어보기'], 'share_line': '온라인 쇼핑 자주 하는 친구한테',
                'caption': '환불이 늦어지면 이제 배상금이 붙어요.', 'hashtags': ['#환불', '소보루'], 'source_media': '', 'source_date': '',
                'facts_used': ['3영업일', '0.1%'], 'confirm_needed': []}
    return fake


class CardNewsTest(unittest.TestCase):
    def setUp(self):
        server.app.config['TESTING'] = True
        self.client = server.app.test_client()
        with server.conn() as db: db.execute('DELETE FROM cards'); db.execute('DELETE FROM log')
        server.save_config(dict(server.DEFAULTS, key='sk-ant-test-key-1234567890', web_search=0))

    def token(self, path='/settings'):
        return re.search(r'name="_csrf" value="([^"]+)"', self.client.get(path).get_data(as_text=True))[1]

    def make(self, url='https://news.test/a/1', **kw):
        sent = []
        with patch.object(cards, 'claude', fake_claude(sent, **kw)), patch.object(cards, 'fetch_page', pages), \
             patch.object(cards, 'naver_news', lambda cfg, q, display=10, sort='sim': [{'title': '같은 뉴스', 'url': 'https://other.test/b/2', 'summary': '', 'date': '2026-10-22'}] if cfg.get('naver_id') else []):
            r = self.client.post('/', data={'_csrf': self.token(), 'url': url})
        m = re.search(r'/card/(\d+)', r.headers.get('Location', ''))
        return (int(m[1]) if m else None), sent, r

    def row(self, cid):
        with server.conn() as db: r = db.execute('SELECT * FROM cards WHERE id=?', (cid,)).fetchone()
        return json.loads(r['data']), {k['label'][:2]: k for k in json.loads(r['checks'])}, r

    def test_make_and_checks(self):
        server.save_config(dict(server.config(), naver_id='id', naver_secret='secret'))
        cid, sent, _ = self.make()
        self.assertIn('소보루일보', sent[0]); self.assertNotIn('무단전재', sent[0])  # 본문만 보내고 저작권 꼬리 줄은 뺌
        self.assertIn('다른일보', sent[0])  # 네이버로 찾은 다른 기사도 같이 보냄
        d, checks, row = self.row(cid)
        self.assertEqual((d['source']['media'], d['source']['date']), ('소보루일보', '2026.10.22'))  # Claude가 비워도 기사에서 채움
        self.assertEqual((d['hashtags'], d['end'], d['share_line']), (['환불', '소보루'], 'save', '온라인 쇼핑 자주 하는 친구한테'))
        self.assertEqual(len(sent), 1)  # 이미지는 힉스필드 몫: Claude에는 원고만 부탁함
        self.assertEqual((d['cover_img'], d['cards'][0]['img']['style']), ({'photo': '', 'style': 'photo'}, 'illust'))  # 기본: 표지 사진, 본문 일러스트
        self.assertIs(checks['사실']['ok'], True); self.assertIs(checks['숫자']['ok'], True); self.assertIs(checks['글:']['ok'], True); self.assertIs(checks['표지']['ok'], True)
        self.assertEqual(row['status'], 'ready')
        page = self.client.get(f'/card/{cid}').get_data(as_text=True)
        self.assertIn('cn-stage', page); self.assertNotIn('아직 내려받을 수 없어요', page); self.assertNotIn('<script>alert', page)

    def test_without_other_article_needs_check_and_edit_rechecks(self):
        cid, _, _ = self.make()  # 네이버 키 없음 + 웹 검색 꺼짐 → 다른 기사로 맞춰 보지 못함
        d, checks, row = self.row(cid)
        self.assertIs(checks['사실']['ok'], False); self.assertEqual(row['status'], 'check')
        self.assertIn('아직 내려받을 수 없어요', self.client.get(f'/card/{cid}').get_data(as_text=True))
        d['cards'][0]['body'] = '환불이 7일 넘게 늦어지면 배상금이 붙어요.'; d['cover_pick'] = 2; d['cover_img'] = {'photo': '../x.jpg', 'style': 'illust'}; d['end'] = 'share'
        self.client.post(f'/card/{cid}', data={'_csrf': self.token(f'/card/{cid}'), 'data': json.dumps(d), 'confirmed': '1'})
        d2, checks, row = self.row(cid)
        self.assertEqual((d2['cover_pick'], d2['end'], d2['cards'][0]['body'][:6]), (2, 'share', '환불이 7일'))
        self.assertEqual(d2['cover_img'], {'photo': '', 'style': 'illust'})  # 스타일만 바꿀 수 있고 파일 이름은 화면에서 못 바꿈
        self.assertIs(checks['숫자']['ok'], False); self.assertIn('7', checks['숫자']['note']); self.assertEqual(row['confirmed'], 1)
        self.assertNotIn('아직 내려받을 수 없어요', self.client.get(f'/card/{cid}').get_data(as_text=True))

    def test_copy_and_bait_are_caught_and_delete(self):
        cid, _, _ = self.make(copy=True, bait=True)
        _, checks, _ = self.row(cid)
        self.assertIs(checks['글:']['ok'], False); self.assertIs(checks['표지']['ok'], False); self.assertIn('충격', checks['표지']['note'])
        self.client.post(f'/card/{cid}', data={'_csrf': self.token(f'/card/{cid}'), 'act': 'delete'})
        self.assertEqual(self.client.get(f'/card/{cid}').status_code, 404)

    def test_guards_key_and_settings(self):
        # 다른 웹사이트에서 보낸 요청(토큰 없음)·다른 주소로 들어온 요청은 막음
        self.assertEqual(self.client.post('/', data={'url': 'https://news.test/a/1'}).status_code, 400)
        self.assertEqual(self.client.get('/', headers={'Host': 'evil.test'}).status_code, 403)
        server.save_config(dict(server.DEFAULTS))
        page = self.client.get('/').get_data(as_text=True)  # 키가 없어도 바로 쓸 수 있고, 자동은 꺼져 있음
        self.assertIn('claude.ai', page); self.assertIn('네이버 키 넣기', page); self.assertRegex(page, r'value="auto" disabled')
        with patch.object(cards, 'claude', fake_claude(sent := [])), patch.object(cards, 'fetch_page', pages):
            r = self.client.post('/', data={'_csrf': self.token(), 'url': 'https://news.test/a/1', 'mode': 'auto'}, follow_redirects=True)
        self.assertEqual(sent, []); self.assertIn('Claude API 키가 없어요', r.get_data(as_text=True))
        self.assertEqual(self.client.post('/quit', data={'_csrf': self.token('/settings')}).status_code, 200)
        t = self.token('/settings')
        self.client.post('/settings', data={'_csrf': t, 'key': 'sk-ant-abcdefghijklmnopqrstuvwxyz', 'naver_id': 'nid', 'naver_secret': 'nsec', 'naver_kind': 'hub', 'auto': '1', 'per_day': '2', 'hour': '9', 'model': 'claude-sonnet-5-5'})
        c = server.config()
        self.assertEqual((c['key'][:7], c['naver_kind'], c['auto'], c['per_day'], c['hour'], c['model'], c['web_search']), ('sk-ant-', 'hub', 1, 2, 9, 'claude-sonnet-5-5', 0))
        page = self.client.get('/settings').get_data(as_text=True)
        self.assertNotIn('abcdefghijklmnopqrstuvwxyz', page); self.assertNotIn('nsec', page)  # 저장한 키는 다시 안 보여 줌
        self.client.post('/settings', data={'_csrf': t, 'key': '', 'per_day': '2', 'hour': '9'})  # 비워 두면 그대로
        self.assertTrue(server.config()['key'].startswith('sk-ant-abc'))
        self.client.post('/settings', data={'_csrf': t, 'key': 'wrong-key', 'per_day': '2', 'hour': '9'})
        self.assertTrue(server.config()['key'].startswith('sk-ant-abc'))  # 모양이 틀린 키는 저장 안 함

    def test_daily_and_helpers(self):
        server.save_config(dict(server.config(), per_day=1))
        with patch.object(cards, 'claude', fake_claude([])), patch.object(cards, 'fetch_page', pages), \
             patch.object(cards, 'find_news', lambda cfg, n, avoid=(): ['https://news.test/a/2']):
            server.daily(); server.daily()  # 하루 몫(1개)을 채우면 더 안 만듦
        with server.conn() as db: self.assertEqual([tuple(r) for r in db.execute('SELECT url,trigger FROM cards')], [('https://news.test/a/2', 'daily')])
        self.assertEqual(cards.search_words('[단독] 온라인몰 "환불 지연" 배상금 (종합) - 소보루일보'), '온라인몰 환불 지연 배상금')
        self.assertEqual(cards.odd_numbers('하루 0.10% · 1,200건 · 1372 · 7일', ['0.1% 1200건']), ['7'])
        self.assertEqual(cards.caption_full({'caption': '본문', 'hashtags': ['환불'], 'source': {'media': '소보루일보', 'date': '2026.10.22', 'url': 'https://news.test/a/1'}}),
                         '본문\n\n출처: 소보루일보 2026.10.22 보도\nhttps://news.test/a/1\n\n#환불')
        self.assertEqual(cards.json_in('찾았어요\n```json\n{"others": [1]}\n```'), {'others': [1]})
        self.assertFalse(cards._public_host('http://127.0.0.1/x'))  # 내 컴퓨터 주소는 열지 않음

    def test_auto_pick_from_naver_news(self):
        # 링크 없이 '알아서 골라 만들기' → 네이버 뉴스에서 아직 안 만든 기사를 골라 끝까지 / 목록에서 고른 기사로 만들기
        import datetime
        today = datetime.date.today().isoformat()
        nn = lambda cfg, q, display=10, sort='sim': [{'title': q + ' 기사', 'url': 'https://news.test/a/1' if q == '소비자 피해' else 'https://other.test/b/2', 'summary': '', 'date': today}] if cfg.get('naver_id') else []
        server.save_config(dict(server.config(), naver_id='nid', naver_secret='nsec'))
        with patch.object(cards, 'claude', fake_claude([])), patch.object(cards, 'fetch_page', pages), patch.object(cards, 'naver_news', nn):
            got = self.client.get('/news?fresh=1').get_json()
            self.assertTrue(got['ok']); self.assertEqual(got['items'][0]['url'], 'https://news.test/a/1'); self.assertEqual(got['items'][0]['host'], 'news.test')
            self.assertEqual(len({i['url'] for i in got['items']}), len(got['items']))
            server.auto_pick()
            with server.conn() as db: self.assertEqual([r[0] for r in db.execute('SELECT url FROM cards')], ['https://news.test/a/1'])
            self.assertTrue(self.client.get('/news').get_json()['items'][0]['made'])
            r = self.client.post('/', data={'_csrf': self.token(), 'mode': 'manual', 'pick': 'https://news.test/a/2', 'url': ''})
            self.assertIn('/card/', r.headers['Location'])
            with server.conn() as db: self.assertEqual(db.execute('SELECT url FROM cards ORDER BY id DESC').fetchone()[0], 'https://news.test/a/2')
        server.save_config(dict(server.config(), naver_id='', naver_secret=''))
        with patch.object(cards, 'naver_news', nn):
            r = self.client.post('/', data={'_csrf': self.token(), 'mode': 'paste'}, follow_redirects=True)
        self.assertIn('네이버 뉴스에서 고를 기사를 찾지 못했어요', r.get_data(as_text=True))
        self.assertFalse(self.client.get('/news').get_json()['ok'])

    def test_blocked_site_reads_naver_copy(self):
        # 언론사 페이지를 못 읽으면 네이버 뉴스에 실린 같은 기사로 읽고, 출처는 언론사 주소·이름 그대로
        naver_page = PAGE.replace('<meta property="og:site_name" content="소보루일보">', '<meta property="og:article:author" content="소보루일보 | 네이버">')
        cards.NAVER_LINK['https://blocked.test/a/9'] = 'https://n.news.naver.com/mnews/article/001/1'
        fetch = lambda url, timeout=10, limit=0: {'https://n.news.naver.com/mnews/article/001/1': naver_page}.get(url, '')
        with patch.object(cards, 'fetch_page', fetch), patch.object(cards, 'naver_news', lambda *a, **k: []):
            got, why = cards.read({}, 'https://blocked.test/a/9')
        self.assertEqual(why, ''); self.assertEqual(got[0]['url'], 'https://blocked.test/a/9'); self.assertEqual(got[0]['media'], '소보루일보')
        self.assertIn('0.1%', got[0]['text'])
        self.assertTrue(cards.JUNK.search("'캐시닥 용돈퀴즈' 10월 24일 정답")); self.assertFalse(cards.JUNK.search('편의점 도시락 가격 올라'))

    def test_photos_higgsfield_upload_and_modes(self):
        import io
        from PIL import Image
        def png(color):
            b = io.BytesIO(); Image.new('RGB', (40, 30), color).save(b, 'PNG'); return b.getvalue()
        server.save_config(dict(server.config(), hf_id='hid', hf_secret='hsec', hf_auto=1, img_style='mix'))
        asked = []
        with patch.object(cards, 'higgsfield_photo', lambda cfg, scene, style='photo': asked.append((scene, style)) or png('orange')):
            cid, _, _ = self.make()
            d, checks, _ = self.row(cid)
            self.assertEqual(asked, [('a parcel box and a calendar', 'photo'), ('calendar', 'illust'), ('receipt', 'illust')])  # 자동 켜짐: 표지 사진·본문 일러스트
            self.assertEqual((d['cover_img']['style'], d['cover_img']['src']), ('photo', 'hf'))
            self.assertIsNone(checks['이미']['ok']); self.assertIn('캡션에', checks['이미']['note'])  # AI 사진 표시는 캡션에 직접
            name = d['cover_img']['photo']; self.assertRegex(name, r'^[0-9a-f]{16}\.jpg$')
            r = self.client.get('/img/' + name); self.assertEqual((r.status_code, r.data[:2]), (200, b'\xff\xd8')); r.close()  # JPEG로 다시 저장
            self.assertEqual(self.client.get('/img/../config.json').status_code, 404)
            page = self.client.get(f'/card/{cid}').get_data(as_text=True)
            self.assertIn('힉스필드로 바로 만들기', page); self.assertIn('Photorealistic', page); self.assertIn('Flat vector illustration', page)  # 장마다 사진·일러스트 설명
            # 1장을 사진으로 바꿔 다시 만들기 (화면에서 막 고른 스타일로)
            self.client.post(f'/card/{cid}', data={'_csrf': self.token(), 'act': 'hf', 'slot': 'card0', 'style': 'photo'})
            d, _, _ = self.row(cid); self.assertEqual(d['cards'][0]['img']['style'], 'photo'); self.assertEqual(asked[-1], ('calendar', 'photo'))
        # 직접 올리기: 사진이 아니면 거절, 사진이면 넣고 '직접 올린 사진' 확인 항목이 생김
        r = self.client.post(f'/card/{cid}', data={'_csrf': self.token(), 'act': 'upload', 'slot': 'card1', 'photo': (io.BytesIO(b'not an image'), 'x.png')},
                             content_type='multipart/form-data', follow_redirects=True)
        self.assertIn('사진 파일이 아니에요', r.get_data(as_text=True))
        self.client.post(f'/card/{cid}', data={'_csrf': self.token(), 'act': 'upload', 'slot': 'card1', 'photo': (io.BytesIO(png('blue')), 'x.png')}, content_type='multipart/form-data')
        d, checks, _ = self.row(cid)
        self.assertEqual(d['cards'][1]['img']['src'], 'upload')
        self.assertIsNone(checks['이미']['ok']); self.assertIn('힉스필드로 만든 것', checks['이미']['note'])
        # 구독으로 만든 이미지 여러 장 한 번에: 파일 이름 순서대로 표지 → 2번째 장
        self.client.post(f'/card/{cid}', data={'_csrf': self.token(), 'act': 'upload_many', 'photos': [(io.BytesIO(png('red')), '2.png'), (io.BytesIO(png('green')), '1.png')]},
                         content_type='multipart/form-data')
        d, _, _ = self.row(cid)
        self.assertEqual((d['cover_img']['src'], d['cards'][0]['img']['src']), ('upload', 'upload'))
        # 저장으로 스타일 바꾸기 (이상한 값은 무시)
        d['cover_img']['style'] = 'illust'; d['cards'][1]['img']['style'] = 'oil-painting'
        self.client.post(f'/card/{cid}', data={'_csrf': self.token(), 'data': json.dumps(d)})
        d2, _, _ = self.row(cid)
        self.assertEqual((d2['cover_img']['style'], d2['cards'][1]['img']['style']), ('illust', 'illust'))
        self.assertTrue(d2['cards'][0]['img']['photo'].endswith('.jpg'))

    def test_higgsfield_photo_uses_sdk(self):
        import higgsfield_client as hf
        calls = {}
        class Job:
            def poll_request_status(self, delay=0): yield hf.Queued(); yield hf.Completed()
            def get(self): return {'images': [{'url': 'https://cdn.test/p.png'}]}
        class Client:
            def __init__(self, api_key=None, timeout=0): calls['key'] = api_key
            def submit(self, model, arguments): calls['model'], calls['args'] = model, arguments; return Job()
        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self, n): return b'PNGDATA'
        cfg = {'hf_id': 'hid', 'hf_secret': 'hsec', 'hf_model': cards.HF_MODELS[0][0]}
        with patch.object(hf, 'SyncClient', Client), patch.object(cards.urllib.request, 'urlopen', lambda req, timeout=0: Resp()):
            self.assertEqual(cards.higgsfield_photo(cfg, 'a receipt on a table'), b'PNGDATA')
        self.assertEqual(calls['key'], 'hid:hsec'); self.assertEqual(calls['model'], 'bytedance/seedream/v4/text-to-image')
        self.assertIn('a receipt on a table', calls['args']['prompt']); self.assertIn('no logos', calls['args']['prompt'])
        self.assertEqual(cards.hf_key({'hf_id': 'abfa-one-key', 'hf_secret': ''}), 'abfa-one-key')  # 요즘 힉스필드 키는 한 줄
        self.assertTrue(cards.hf_ready({'hf_id': 'abfa-one-key', 'hf_secret': ''}))
        class NsfwJob(Job):
            def poll_request_status(self, delay=0): yield hf.NSFW()
        with patch.object(hf, 'SyncClient', type('C', (Client,), {'submit': lambda self, m, arguments: NsfwJob()})):
            with self.assertRaisesRegex(RuntimeError, '안전 기준'): cards.higgsfield_photo(cfg, 'x')
        with self.assertRaisesRegex(RuntimeError, '키가 없어요'): cards.higgsfield_photo({}, 'x')

    def test_keyless_paste_manual_and_art_paste(self):
        server.save_config(dict(server.DEFAULTS))  # 키 없음
        with patch.object(cards, 'fetch_page', pages), patch.object(cards, 'claude', lambda *a, **k: self.fail('키 없이 Claude API를 부르면 안 됨')):
            r = self.client.post('/', data={'_csrf': self.token(), 'url': 'https://news.test/a/1', 'mode': 'paste'})
            cid = int(re.search(r'/card/(\d+)/paste', r.headers['Location'])[1])
            page = self.client.get(f'/card/{cid}').get_data(as_text=True)  # 답을 넣기 전에는 붙여넣기 화면으로
            page = self.client.get(f'/card/{cid}/paste').get_data(as_text=True)
            self.assertIn('요청 글 복사', page); self.assertIn('저작권 규칙', page); self.assertIn('3영업일', page); self.assertIn('&#34;covers&#34;', page)
            self.assertIn('claude.ai 답 기다림', self.client.get('/').get_data(as_text=True))
            r = self.client.post(f'/card/{cid}/paste', data={'_csrf': self.token(), 'answer': '음…'}, follow_redirects=True)
            self.assertIn('원고(JSON)를 찾지 못했어요', r.get_data(as_text=True))
            answer = '네, 만들었어요!\n```json\n' + json.dumps(fake_claude([])(None, '', '', cards.WRITE_SCHEMA, 0), ensure_ascii=False) + '\n```\n필요하면 더 말씀해 주세요.'
            self.client.post(f'/card/{cid}/paste', data={'_csrf': self.token(), 'answer': answer})
            d, checks, row = self.row(cid)
            self.assertNotIn('pending', d); self.assertEqual(len(d['covers']), 5); self.assertEqual(d['source']['media'], '소보루일보')
            self.assertIs(checks['숫자']['ok'], True); self.assertIsNone(checks['이미']['ok'])  # 그림이 아직 없음
            page = self.client.get(f'/card/{cid}').get_data(as_text=True)
            self.assertIn('>설명 복사<', page); self.assertIn('>이미지 올리기<', page); self.assertIn('한 번에 올리기', page); self.assertRegex(page, r'value="hf" disabled')  # 키 없으면 바로 만들기는 꺼짐
            # 직접 쓰기 + 기사 글 직접 붙여 넣기 (링크 없이)
            text = '\n'.join(re.sub(r'<[^>]+>', '', x) for x in re.findall(r'<p>(.*?)</p>', PAGE)[:4])
            r = self.client.post('/', data={'_csrf': self.token(), 'mode': 'manual', 'text': text, 'title': '환불 지연 배상금', 'media': '우리일보', 'date': '2026.10.23'})
            cid2 = int(re.search(r'/card/(\d+)$', r.headers['Location'])[1])
            d, checks, row = self.row(cid2)
            self.assertEqual((d['source']['media'], d['source']['date'], d['source']['url'], len(d['covers']), len(d['cards'])), ('우리일보', '2026.10.23', '', 5, 3))
            self.assertEqual(row['status'], 'check')  # 빈 원고는 표지·출처 등 검사에서 걸림 → 채우고 확인해야 내려받기
            r = self.client.post('/', data={'_csrf': self.token(), 'mode': 'manual', 'text': '짧음'}, follow_redirects=True)
            self.assertIn('너무 짧아요', r.get_data(as_text=True))

    def test_save_files_to_folder(self):
        import io
        server.save_config(dict(server.config(), naver_id='id', naver_secret='secret'))
        cid, _, _ = self.make()  # 체크리스트 통과
        png = b'\x89PNG\r\n\x1a\n' + b'0' * 50
        data = {'_csrf': self.token(), 'caption': '본문\n\n출처: 소보루일보', 'png': [(io.BytesIO(png), 'a.png'), (io.BytesIO(png), 'b.png')]}
        r = self.client.post(f'/card/{cid}/files', data=data, content_type='multipart/form-data')
        self.assertEqual(r.status_code, 200)
        folder = Path(r.get_json()['folder'])
        self.assertEqual(folder.parent, server.OUT); self.assertRegex(folder.name, r'^\d{3}_환불 늦어지면')
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['caption.txt', 'soboru-card-01.png', 'soboru-card-02.png'])
        self.assertEqual((folder / 'caption.txt').read_text(encoding='utf-8-sig'), '본문\n\n출처: 소보루일보')
        self.assertIn('저장된 곳', self.client.get(f'/card/{cid}').get_data(as_text=True))
        self.assertEqual(self.client.post(f'/card/{cid}/open', data={'_csrf': self.token()}).status_code, 204)
        bad = {'_csrf': self.token(), 'png': [(io.BytesIO(b'GIF89a'), 'x.png')]}
        self.assertEqual(self.client.post(f'/card/{cid}/files', data=bad, content_type='multipart/form-data').status_code, 400)  # PNG만
        self.assertEqual(self.client.post(f'/card/{cid}/files', data={'png': [(io.BytesIO(png), 'a.png')]}, content_type='multipart/form-data').status_code, 400)  # 토큰 없으면 막음
        cid2, _, _ = self.make(bait=True)  # 체크리스트에 걸리고 확인 안 한 카드는 저장 안 됨
        data = {'_csrf': self.token(), 'png': [(io.BytesIO(png), 'a.png')]}
        self.assertEqual(self.client.post(f'/card/{cid2}/files', data=data, content_type='multipart/form-data').status_code, 400)

    def test_kakao_send_to_me(self):
        import io, time as _t
        calls = []
        def fake_http(method, url, data=None, headers=None, body=None, timeout=20):
            calls.append((url.split('kakao.com')[1], dict(data or {}), dict(headers or {})))
            if url.endswith('/oauth/token'): return 200, {'access_token': 'acc-' + data['grant_type'], 'expires_in': 21599, 'refresh_token': 'ref-1'}
            if url.endswith('/image/upload'): return 200, {'infos': {'original': {'url': 'https://k.kakaocdn.net/cover.png'}}}
            if url.endswith('/memo/default/send'): return 200, {'result_code': 0}
            return 404, {}
        server.save_config(dict(server.config(), naver_id='id', naver_secret='secret', kakao_key='rest-key'))
        cid, _, _ = self.make()
        with patch.object(kakao, 'http', fake_http):
            r = self.client.get('/kakao/login'); self.assertIn('kauth.kakao.com/oauth/authorize', r.headers['Location']); self.assertIn('scope=talk_message', r.headers['Location'])
            state = re.search(r'state=([^&]+)', r.headers['Location'])[1]
            self.assertEqual(self.client.get('/kakao/callback?code=c1&state=wrong').status_code, 400)  # 다른 곳에서 꾸민 응답은 막음
            with self.client.session_transaction() as ss: ss['kakao_state'] = state
            self.client.get(f'/kakao/callback?code=c1&state={state}')
            tok = server.config()['kakao_token']; self.assertEqual((tok['access'], tok['refresh']), ('acc-authorization_code', 'ref-1'))
            self.assertIn('연결됐어요', json.loads(calls[-1][1]['template_object'])['text'])  # 시험 메시지
            self.assertIn('연결됨', self.client.get('/settings').get_data(as_text=True))
            png = b'\x89PNG\r\n\x1a\n' + b'0' * 40
            r = self.client.post(f'/card/{cid}/kakao', data={'_csrf': self.token(), 'png': (io.BytesIO(png), 'cover.png')}, content_type='multipart/form-data')
            self.assertEqual(r.get_json(), {'ok': True, 'image': True})
            up, feed, cap = calls[-3:]
            self.assertEqual(up[0], '/v2/api/talk/message/image/upload'); self.assertEqual(up[2]['Authorization'], 'KakaoAK rest-key')
            t = json.loads(feed[1]['template_object']); self.assertEqual((t['object_type'], t['content']['image_url']), ('feed', 'https://k.kakaocdn.net/cover.png'))
            self.assertEqual(feed[2]['Authorization'], 'Bearer acc-authorization_code')
            self.assertIn('출처: 소보루일보', json.loads(cap[1]['template_object'])['text'])
            # 토큰이 만료되면 리프레시 토큰으로 새로 받음
            c = server.config(); c['kakao_token']['expires'] = int(_t.time()) - 5; server.save_config(c)
            self.client.post(f'/card/{cid}/kakao', data={'_csrf': self.token()}, content_type='multipart/form-data')
            self.assertEqual(server.config()['kakao_token']['access'], 'acc-refresh_token')
            self.assertEqual(json.loads(calls[-1][1]['template_object'])['object_type'], 'text')  # 이미지가 없으면 글로만
        server.save_config(dict(server.config(), kakao_token={}))
        r = self.client.post(f'/card/{cid}/kakao', data={'_csrf': self.token()}, content_type='multipart/form-data')
        self.assertEqual(r.status_code, 400); self.assertIn('연결되지 않았어요', r.get_json()['error'])


if __name__ == '__main__':
    unittest.main()
