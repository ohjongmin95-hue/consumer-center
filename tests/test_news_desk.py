import datetime
import unittest
from unittest import mock

import news_desk

SAMPLE = '''<table class="board_list"><tbody>
<tr><td>1530</td><td class="title"><a href="/home/sub.do?menukey=4002&amp;mode=view&amp;no=1003900001&amp;page=1">온라인 구독 서비스 해지 방해, 10곳 중 4곳</a></td><td>2026-11-15</td><td>12</td></tr>
<tr><td>1529</td><td class="title"><a href="javascript:void(0)" onclick="fn_view('1003900000')">어린이 장난감 유해물질 기준 초과 제품 확인</a></td><td>2026.11.13</td></tr>
<tr><td><a href="/home/sub.do?menukey=4002&amp;page=2">2</a></td></tr>
</tbody></table>'''


class KcaTest(unittest.TestCase):
    def test_parse_list(self):
        got = news_desk.kca_parse(SAMPLE)
        self.assertEqual([g['title'] for g in got], ['온라인 구독 서비스 해지 방해, 10곳 중 4곳', '어린이 장난감 유해물질 기준 초과 제품 확인'])
        self.assertEqual(got[0]['date'], datetime.date(2026, 11, 15))
        self.assertTrue(got[0]['url'].startswith('https://www.kca.go.kr/home/sub.do?menukey=4002&mode=view&no=1003900001'))
        self.assertIn('no=1003900000', got[1]['url'])

    def test_mail_lists_new_releases(self):
        today = datetime.date(2026, 11, 15)
        kca = [it for it in [dict(title=g['title'], url=g['url'], summary='', read=g['url'], source=news_desk.KCA_SOURCE, outlets=0, also=[], wire=False, kca=True,
                                  when=datetime.datetime(g['date'].year, g['date'].month, g['date'].day, 9)) for g in news_desk.kca_parse(SAMPLE)] if it['when'].date() >= today]
        subject, text, html = news_desk.render(today, [], [], [], kca)
        self.assertIn('소비자원 보도자료 1', subject)
        self.assertIn('온라인 구독 서비스 해지 방해', html); self.assertNotIn('어린이 장난감', html)
        self.assertIn('한국소비자원 새 보도자료', text)

    def test_run_puts_releases_first_without_outlet_rule(self):
        sent = []
        rel = [dict(title='해외직구 이불 세탁 후 변형 많아', summary='', url='https://www.kca.go.kr/x', read='https://www.kca.go.kr/x', source=news_desk.KCA_SOURCE,
                    when=datetime.datetime(2026, 11, 15, 9, tzinfo=datetime.timezone.utc), outlets=0, also=[], wire=False, kca=True)]
        news = [dict(title=f'뉴스 {i} 소비자 물가 오름', summary='', url=f'https://n/{i}', read='', source='a', when=datetime.datetime(2026, 11, 15, tzinfo=datetime.timezone.utc), outlets=2, also=[], wire=False) for i in range(5)]
        seen = {}
        def fake_chat(system, user, n):
            seen['user'] = user
            return {'issues': [{'ids': [1], 'title': '해외직구 이불', 'category': '생활', 'fact': '변형이 많다.'}]}
        with mock.patch.object(news_desk, 'gather', return_value=news), mock.patch.object(news_desk, 'kca_releases', return_value=rel), \
             mock.patch.object(news_desk, 'chat', side_effect=fake_chat), mock.patch.dict('os.environ', {'NEWS_DESK_TO': 'a@b.c'}):
            news_desk.run(0, today=datetime.date(2026, 11, 15), send=lambda *a, **k: sent.append((a, k)))
        self.assertTrue(seen['user'].split('\n')[1].startswith('1. 해외직구 이불 세탁 후 변형 많아 (소비자원 보도자료)'))
        self.assertIn('소비자원 보도자료 1', sent[0][0][1])


if __name__ == '__main__':
    unittest.main()
