"""카드뉴스 만들기 시험: Claude·네이버·기사 읽기는 가짜로 바꿔 끼우고, 임시 data 폴더에서 돌린다."""
import importlib, json, os, re, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
TMP = tempfile.TemporaryDirectory()
os.environ['CARDNEWS_DATA'] = TMP.name
os.environ.pop('ANTHROPIC_API_KEY', None)
import cards, server  # noqa: E402

PAGE = ('<html><head><meta property="og:title" content="온라인몰 환불 지연하면 하루 0.1% 배상금"><meta property="og:site_name" content="소보루일보">'
        '<meta property="article:published_time" content="2026-10-22T09:00:00+09:00"></head><body><nav>메뉴 메뉴 메뉴 메뉴 메뉴 메뉴 메뉴 메뉴</nav><article>'
        '<p>공정거래위원회는 22일 온라인 쇼핑몰이 환불을 3영업일 넘게 미루면 지연 배상금을 물리는 개정안을 발표했다고 밝혔다.</p>'
        '<p>배상금은 늦어진 하루마다 환불액의 0.1%이며, 개정안은 2027년 1월 1일부터 시행된다고 공정위 관계자는 설명했다.</p>'
        '<p>지난해 한국소비자원에 접수된 환불 지연 피해는 1만2000건으로 전년보다 크게 늘었다는 통계도 함께 공개됐다.</p>'
        '<p>공정위는 소비자가 환불을 요청한 날짜를 남겨 두면 나중에 배상금을 받을 때 도움이 된다고 안내했다.</p>'
        '<p>ⓒ 소보루일보 무단전재 및 재배포 금지</p></article></body></html>')
OTHER = PAGE.replace('소보루일보', '다른일보').replace('공정거래위원회는 22일', '공정위가 22일 발표한 내용에 따르면')
BAD_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" onload="alert(1)"><script>alert(1)</script><defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/>'
           '</linearGradient></defs><rect width="10" height="10" fill="url(#g)"/><image href="https://evil.test/x.png"/><text>글자</text><circle cx="5" cy="5" r="3" fill="url(https://evil.test/a)"/></svg>')


def pages(url, timeout=10, limit=0):
    return {'https://news.test/a/1': PAGE, 'https://other.test/b/2': OTHER, 'https://news.test/a/2': PAGE}.get(url, '')


def fake_claude(sent, copy=False, bait=False, number='3영업일'):
    def fake(cfg, system, user, schema, max_tokens, effort='medium'):
        sent.append(user)
        if 'svgs' in schema['properties']: return {'svgs': [BAD_SVG] * user.count('Scene:')}
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

    def token(self, path='/'):
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

    def test_make_checks_and_clean_art(self):
        server.save_config(dict(server.config(), naver_id='id', naver_secret='secret'))
        cid, sent, _ = self.make()
        self.assertIn('소보루일보', sent[0]); self.assertNotIn('무단전재', sent[0])  # 본문만 보내고 저작권 꼬리 줄은 뺌
        self.assertIn('다른일보', sent[0])  # 네이버로 찾은 다른 기사도 같이 보냄
        d, checks, row = self.row(cid)
        self.assertEqual((d['source']['media'], d['source']['date']), ('소보루일보', '2026.10.22'))  # Claude가 비워도 기사에서 채움
        self.assertEqual((d['hashtags'], d['end'], d['share_line']), (['환불', '소보루'], 'save', '온라인 쇼핑 자주 하는 친구한테'))
        for bad in ('script', 'onload', 'evil.test', '<image', '<text', '글자'): self.assertNotIn(bad, d['cover_art'])
        self.assertIn('viewBox="0 0 1080 720"', d['cover_art']); self.assertRegex(d['cover_art'], r'id="a[0-9a-f]{6}-g"'); self.assertRegex(d['cover_art'], r'url\(#a[0-9a-f]{6}-g\)')
        self.assertIs(checks['사실']['ok'], True); self.assertIs(checks['숫자']['ok'], True); self.assertIs(checks['글:']['ok'], True); self.assertIs(checks['표지']['ok'], True)
        self.assertEqual(row['status'], 'ready')
        page = self.client.get(f'/card/{cid}').get_data(as_text=True)
        self.assertIn('cn-stage', page); self.assertNotIn('아직 내려받을 수 없어요', page); self.assertNotIn('<script>alert', page)

    def test_without_other_article_needs_check_and_edit_rechecks(self):
        cid, _, _ = self.make()  # 네이버 키 없음 + 웹 검색 꺼짐 → 다른 기사로 맞춰 보지 못함
        d, checks, row = self.row(cid)
        self.assertIs(checks['사실']['ok'], False); self.assertEqual(row['status'], 'check')
        self.assertIn('아직 내려받을 수 없어요', self.client.get(f'/card/{cid}').get_data(as_text=True))
        d['cards'][0]['body'] = '환불이 7일 넘게 늦어지면 배상금이 붙어요.'; d['cover_pick'] = 2; d['cover_art'] = '<svg onload="x"/>'; d['end'] = 'share'
        self.client.post(f'/card/{cid}', data={'_csrf': self.token(f'/card/{cid}'), 'data': json.dumps(d), 'confirmed': '1'})
        d2, checks, row = self.row(cid)
        self.assertEqual((d2['cover_pick'], d2['end'], d2['cards'][0]['body'][:6]), (2, 'share', '환불이 7일'))
        self.assertNotIn('onload', d2['cover_art'])  # 그림은 화면에서 못 바꿈
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
        cid, sent, r = self.make()
        self.assertIsNone(cid); self.assertEqual(sent, [])
        self.assertIn('Claude API 키가 없어요', self.client.get('/').get_data(as_text=True))
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


if __name__ == '__main__':
    unittest.main()
