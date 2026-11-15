import datetime, json, tempfile, unittest
from pathlib import Path
from unittest import mock

import news_desk
import public_data as pd

SWAG = {'host': 'apis.data.go.kr', 'basePath': '/1130000/stat', 'paths': {'/getStats': {'get': {'summary': '통계', 'parameters': [
    {'name': 'serviceKey', 'required': True}, {'name': 'pageNo'}, {'name': 'numOfRows'}, {'name': 'resultType', 'description': 'json'},
    {'name': 'yr', 'required': True, 'description': '기준연도(YYYY)'}]}}}}
RECALL = {'host': 'apis.data.go.kr', 'basePath': '/1471000/Recall', 'paths': {'/list': {'get': {'summary': '회수 목록', 'parameters': [
    {'name': 'serviceKey', 'required': True}, {'name': 'pageNo'}, {'name': 'numOfRows'}, {'name': 'type'}]}}}}


class PublicDataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = [mock.patch.object(pd, 'DATA_DIR', Path(self.tmp.name)), mock.patch.object(pd, 'KEY', 'SECRETKEY123'),
                  mock.patch.object(pd, 'APIS', {'stat': ('1', '공정거래위원회_1372 통계', False), 'recall': ('2', '식품의약품안전처_의약품 회수', True)})]
        for x in self.p: x.start()
        self.recalls = [{'PRDUCT': '감기약A', 'ENTRPS': '가제약', 'RTRVL_RESN': '함량 부적합'}]
        self.years = []

    def tearDown(self):
        for x in self.p: x.stop()
        self.tmp.cleanup()

    def fake_get(self, url, timeout=30):
        if 'data.go.kr/data/1/' in url: return 'var swaggerJson = `' + json.dumps(SWAG) + '`;'
        if 'data.go.kr/data/2/' in url: return 'var swaggerJson = `' + json.dumps(RECALL) + '`;'
        if '/getStats' in url:
            yr = url.split('yr=')[1][:4]; self.years.append(yr)
            if yr == '2016': return json.dumps({'response': {'header': {'resultCode': '03', 'resultMsg': 'NODATA_ERROR'}}})
            return json.dumps({'response': {'header': {'resultCode': '00', 'resultMsg': 'OK'}, 'body': {'totalCount': 1, 'items': [{'yr': yr, 'typeNm': '방문판매', 'cnt': '10'}]}}})
        if '/list' in url: return json.dumps({'header': {'resultCode': '00'}, 'body': {'items': self.recalls, 'totalCount': len(self.recalls)}})
        raise AssertionError(url)

    def test_run_fills_year_and_alerts_new_recalls(self):
        with mock.patch.object(pd, 'get', side_effect=self.fake_get):
            out = pd.run()
        this = datetime.date.today().year
        self.assertEqual(self.years, [str(y) for y in range(this - 10, this + 1)])  # 필수 연도 항목을 해마다 채움
        st = out['apis']['stat']
        self.assertEqual(st['rows'], 10)
        self.assertTrue(any('NODATA_ERROR' in e for e in st['errors']))  # JSON 오류도 내용이 보임
        self.assertEqual(out['apis']['recall']['new'], [])  # 처음 받을 때는 알리지 않음
        saved = (Path(self.tmp.name) / 'latest.json').read_text(encoding='utf-8')
        self.assertNotIn('SECRETKEY123', saved)
        self.recalls.append({'PRDUCT': '소화제B', 'ENTRPS': '나제약', 'RTRVL_RESN': '이물 혼입'})
        with mock.patch.object(pd, 'get', side_effect=self.fake_get):
            out = pd.run()
        self.assertEqual(out['apis']['recall']['new'], ['소화제B · 나제약 · 이물 혼입'])
        alerts = pd.fresh_alerts()
        self.assertEqual(alerts[0][1], ['소화제B · 나제약 · 이물 혼입'])
        subject, text, html = news_desk.render(datetime.date.today(), [], [], [], (), alerts)
        self.assertIn('소화제B', html); self.assertIn('새 의약품 회수', text)

    def test_admin_page(self):
        import app as site
        with mock.patch.object(pd, 'get', side_effect=self.fake_get):
            pd.run()
        c = site.app.test_client()
        with c.session_transaction() as s: pass
        self.assertEqual(c.get('/admin/public-data').status_code, 302)  # 로그인 없으면 못 봄
