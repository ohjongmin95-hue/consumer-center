import json, unittest
from types import SimpleNamespace
from unittest import mock
import logo_fill


class LogoFillTest(unittest.TestCase):
    def test_only_confirmed_official_site_counts(self):
        res = {'choices': [{'message': {'content': json.dumps({'domain': 'https://www.coupang.com/np', 'names': ['쿠팡', 'Coupang'], 'sure': True})}}]}
        with mock.patch.object(logo_fill.companydesk, 'ai_key_for', return_value='k'), mock.patch.object(logo_fill.companydesk, 'post_json', return_value=(200, res)):
            self.assertEqual(logo_fill.ask('쿠팡'), ('coupang.com', ['쿠팡', 'Coupang']))
        unsure = {'choices': [{'message': {'content': json.dumps({'domain': 'x.com', 'sure': False})}}]}
        with mock.patch.object(logo_fill.companydesk, 'ai_key_for', return_value='k'), mock.patch.object(logo_fill.companydesk, 'post_json', return_value=(200, unsure)):
            self.assertEqual(logo_fill.ask('동네가게'), ('', []))
        with mock.patch.object(logo_fill.company_logo, 'get', return_value='<title>쿠팡!</title>'.encode()):
            self.assertTrue(logo_fill.confirmed('coupang.com', ['쿠팡']))
        with mock.patch.object(logo_fill.company_logo, 'get', return_value=b'<title>other</title>'):
            self.assertFalse(logo_fill.confirmed('coupang.com', ['쿠팡']))
        with mock.patch.object(logo_fill.company_logo, 'get', side_effect=OSError('403')):  # 봇을 막는 홈페이지: 도메인에 영문 이름이 있으면 인정
            self.assertTrue(logo_fill.confirmed('daisomall.co.kr', ['다이소몰', 'Daiso']))
            self.assertFalse(logo_fill.confirmed('daisomall.co.kr', ['다이소몰']))
            self.assertFalse(logo_fill.confirmed('mall.co.kr', ['DB', 'ab']))


if __name__ == '__main__':
    unittest.main()
