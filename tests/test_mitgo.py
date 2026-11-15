"""믿고가게 (mitgo/): 스티커 방문 인증·낮은 별점 공개 대기·사장님 답글·운영자 잠금·주소 나누기."""
import datetime
import re
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mitgo  # noqa: E402


@pytest.fixture
def mg(tmp_path, monkeypatch):
    monkeypatch.setenv('MITGO_ADMIN_PASSWORD', 'pw')
    db = tmp_path / 'g.sqlite3'
    app = mitgo.create_app(str(db))
    app.config['TESTING'] = True
    c = sqlite3.connect(db)
    c.execute("INSERT INTO stores(code,name,cat,token,created) VALUES('20001','결헤어','미용','tok','2026-11-15 10:00:00')")
    c.commit()
    c.close()
    app.db = db
    return app


def csrf(cl, path='/'):
    return re.search(r'name="_csrf" value="([^"]+)"', cl.get(path).get_data(as_text=True)).group(1)


def write(cl, **kw):
    data = dict(_csrf=csrf(cl, '/s/1/review'), stars='5', chip=['친절해요'], body='설명이 꼼꼼해요', honest='1')
    data.update(kw)
    return cl.post('/s/1/review', data=data)


def test_sticker_scan_gives_visit_badge(mg):
    cl = mg.test_client()
    r = cl.get('/q/20001')
    assert r.status_code == 302 and r.headers['Location'].endswith('/s/1')
    assert '스티커로 들어왔어요' in cl.get('/s/1').get_data(as_text=True)
    assert '바로 올라갔어요' in write(cl).get_data(as_text=True)
    page = cl.get('/s/1').get_data(as_text=True)
    assert '설명이 꼼꼼해요' in page and '방문 인증' in page
    assert sqlite3.connect(mg.db).execute('SELECT visited FROM reviews').fetchone()[0] == 1
    # 일주일에 한 번
    assert '이미 후기를' in write(cl).get_data(as_text=True)


def test_review_without_scan_and_honesty_check(mg):
    cl = mg.test_client()
    assert '대가 없이' in write(cl, honest='').get_data(as_text=True)
    write(cl)
    assert sqlite3.connect(mg.db).execute('SELECT visited FROM reviews').fetchone()[0] == 0


def test_low_star_waits_for_owner_then_reply_publishes(mg):
    cl = mg.test_client()
    assert '48시간 뒤' in write(cl, stars='2', body='기다림이 너무 길었어요').get_data(as_text=True)
    assert '기다림이 너무 길었어요' not in cl.get('/s/1').get_data(as_text=True)
    own = mg.test_client()
    page = own.get('/owner/tok').get_data(as_text=True)
    assert '기다림이 너무 길었어요' in page and '시간 뒤 공개' in page
    tk = re.search(r'name="_csrf" value="([^"]+)"', page).group(1)
    own.post('/owner/tok/reply/1', data={'_csrf': tk, 'reply': '죄송해요. 예약제로 바꿨어요.'})
    page = cl.get('/s/1').get_data(as_text=True)
    assert '기다림이 너무 길었어요' in page and '예약제로 바꿨어요' in page


def test_low_star_public_after_hold_and_private_never(mg):
    cl = mg.test_client()
    write(cl, stars='1', body='오래된 낮은 별점')
    old = (datetime.datetime.now() - datetime.timedelta(hours=49)).strftime('%Y-%m-%d %H:%M:%S')
    c = sqlite3.connect(mg.db)
    c.execute('UPDATE reviews SET created=?, who=?', (old, 'x'))
    c.commit()
    write(mg.test_client(), stars='5', body='사장님께만 하는 말', private='1')
    page = cl.get('/s/1').get_data(as_text=True)
    assert '오래된 낮은 별점' in page and '사장님께만 하는 말' not in page


def test_unregistered_sticker_claim(mg):
    cl = mg.test_client()
    r = cl.get('/q/20002')
    assert r.headers['Location'].endswith('/q/20002/start')
    tk = csrf(cl, '/q/20002/start')
    r = cl.post('/q/20002/start', data={'_csrf': tk, 'name': '깨끗세탁', 'cat': '세탁', 'phone': '010-1111-2222', 'agree': '1'})
    assert '/owner/' in r.headers['Location']
    assert '깨끗세탁' in cl.get('/').get_data(as_text=True)


def test_owner_cannot_delete_and_admin_locked(mg):
    cl = mg.test_client()
    assert cl.get('/admin').headers['Location'].endswith('/admin/login')
    tk = csrf(cl, '/admin/login')
    cl.post('/admin/login', data={'_csrf': tk, 'pw': 'pw'})
    page = cl.get('/admin?tab=conf').get_data(as_text=True)
    assert 'hold_hours' in page
    tk = re.search(r'name="_csrf" value="([^"]+)"', page).group(1)
    cl.post('/admin?tab=conf', data={'_csrf': tk, 'act': 'conf', 'hold_hours': '0', 'hold_below': '3', 'pro_price': '9900', 'area': '광교'})
    u = mg.test_client()
    write(u, stars='2', body='바로 공개되는 낮은 별점')
    assert '바로 공개되는 낮은 별점' in u.get('/s/1').get_data(as_text=True)
    assert '9,900원' in u.get('/join').get_data(as_text=True)
    assert not [r for r in mg.url_map.iter_rules() if 'delete' in r.rule]


def test_mount_by_host_and_preview(monkeypatch, tmp_path):
    monkeypatch.setenv('MITGO_DB', str(tmp_path / 'x.sqlite3'))
    monkeypatch.setenv('MITGO_HOST', 'mitgo.test')
    monkeypatch.setenv('MITGO_PREVIEW', '1')

    def main(environ, start_response):
        start_response('200 OK', [('Content-Type', 'text/plain')])
        return [b'main']
    from werkzeug.test import Client
    app = mitgo.mount(main)
    assert '광고나 이벤트 없는' in Client(app).get('/', headers={'Host': 'mitgo.test'}).get_data(as_text=True)
    assert Client(app).get('/', headers={'Host': 'other.test'}).get_data() == b'main'
    assert Client(app).get('/mitgo/about', headers={'Host': 'other.test'}).headers['Location'] == 'https://mitgo.test/about'
    page = Client(app).get('/', headers={'Host': 'mitgo.test'}).get_data(as_text=True)
    assert '소비자를위한신문' not in page and '신문' not in page and 'by SOBORU' in page


def test_dianping_features_subs_save_helpful_level_pick(mg):
    cl = mg.test_client()
    write(cl, s1='5', s2='4')
    page = cl.get('/s/1').get_data(as_text=True)
    assert '실력' in page and 'Lv.1 새내기' in page
    tk = csrf(cl, '/s/1')
    cl.post('/s/1/save', data={'_csrf': tk})
    assert '결헤어' in cl.get('/my').get_data(as_text=True)
    other = mg.test_client()
    tk2 = csrf(other, '/s/1')
    other.post('/r/1/helpful', data={'_csrf': tk2})
    other.post('/r/1/helpful', data={'_csrf': tk2})
    other.post('/r/1/helpful', data={'_csrf': tk2})
    assert sqlite3.connect(mg.db).execute('SELECT helpful FROM reviews').fetchone()[0] == 1
    c = sqlite3.connect(mg.db)
    c.execute("INSERT OR REPLACE INTO conf(k,v) VALUES('pick_n','1'),('pick_v','0')")
    c.commit()
    assert '믿고 갈 가게' in cl.get('/').get_data(as_text=True)


def test_offers_cannot_require_reviews(mg):
    own = mg.test_client()
    tk = csrf(own, '/owner/tok')
    own.post('/owner/tok/offer', data={'_csrf': tk, 'title': '후기 쓰면 음료 서비스'})
    own.post('/owner/tok/offer', data={'_csrf': tk, 'title': '평일 오전 커트 3,000원 할인'})
    rows = sqlite3.connect(mg.db).execute('SELECT title FROM offers').fetchall()
    assert rows == [('평일 오전 커트 3,000원 할인',)]
    cl = mg.test_client()
    page = cl.get('/s/1').get_data(as_text=True)
    assert '사장님 혜택' in page and '후기를 쓰지 않아도' in page
    tk = csrf(cl, '/s/1')
    r = cl.post('/offer/1', data={'_csrf': tk}).get_data(as_text=True)
    assert '직원에게' in r


def test_sort_near(mg):
    c = sqlite3.connect(mg.db)
    c.execute("INSERT INTO stores(name,cat,token,lat,lng,created) VALUES('먼 가게','미용','t2',37.40,127.10,'2026-11-15 10:00:00')")
    c.execute("UPDATE stores SET lat=37.2886, lng=127.0507 WHERE id=1")
    c.commit()
    page = mg.test_client().get('/?sort=near&lat=37.29&lng=127.05').get_data(as_text=True)
    assert page.index('결헤어') < page.index('먼 가게') and 'km' in page
