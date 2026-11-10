"""모아밥 (moabap/): 주문·첫 주문 할인·수량 한도·운영자 잠금·가게 화면·주소 나누기."""
import os
import re
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import moabap  # noqa: E402


@pytest.fixture
def moa(tmp_path, monkeypatch):
    monkeypatch.setenv('MOABAP_ADMIN_PASSWORD', 'pw')
    db = tmp_path / 'm.sqlite3'
    app = moabap.create_app(str(db))
    app.config['TESTING'] = True
    c = sqlite3.connect(db)
    c.execute("INSERT INTO shops(name,hygiene,token) VALUES('오늘제육','위생등급 우수','tok')")
    c.execute("INSERT INTO sets(shop_id,name,price,orig,supply,cap) VALUES(1,'제육 도시락',5900,9500,4500,3)")
    c.execute("INSERT INTO places(name) VALUES('중앙타워 로비')")
    c.commit()
    c.close()
    return app


def csrf(cl, path='/set/1'):
    return re.search(r'name="_csrf" value="([^"]+)"', cl.get(path).get_data(as_text=True)).group(1)


def first_slot(cl):
    return re.search(r'name="slot" value="([^"]+)"', cl.get('/set/1').get_data(as_text=True)).group(1)


def order(cl, **kw):
    data = dict(_csrf=csrf(cl), set_id='1', slot=first_slot(cl), place_id='1', qty='1', name='김민지', phone='010-1234-5678', agree='1')
    data.update(kw)
    return cl.post('/order', data=data)


def test_home_and_set(moa):
    cl = moa.test_client()
    h = cl.get('/').get_data(as_text=True)
    assert '제육 도시락' in h and '5,900원' in h and '배달비 0원' in h
    s = cl.get('/set/1').get_data(as_text=True)
    assert '매장 가격보다 3,600원 싸요' in s and '중앙타워 로비' in s
    assert cl.get('/set/99').status_code == 404
    assert cl.get('/privacy').status_code == 200


def test_order_first_coupon_then_full_price(moa):
    cl = moa.test_client()
    r = order(cl)
    assert r.status_code == 302 and '/o/' in r.location
    page = cl.get(r.location).get_data(as_text=True)
    assert '첫 주문 할인' in page and '3,900원' in page  # 5,900 - 2,000
    r2 = order(cl)
    assert '첫 주문 할인' not in cl.get(r2.location).get_data(as_text=True)
    assert cl.get('/orders').get_data(as_text=True).count('제육 도시락') == 2


def test_order_needs_agree_and_phone(moa):
    cl = moa.test_client()
    assert '/set/1' in order(cl, agree='').location
    assert '/set/1' in order(cl, phone='123').location
    with moa.conn() as db:
        assert db.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0


def test_capacity(moa):
    cl = moa.test_client()
    order(cl, qty='3')
    r = order(cl, phone='01099998888')
    assert '/set/1' in r.location  # 시간당 3개 한도
    with moa.conn() as db:
        assert db.execute('SELECT COALESCE(SUM(qty),0) FROM orders').fetchone()[0] == 3


def test_csrf_required(moa):
    cl = moa.test_client()
    cl.get('/')
    assert cl.post('/order', data={'set_id': '1'}).status_code == 400


def test_admin_flow_and_shop(moa):
    cl = moa.test_client()
    order(cl)
    assert '/admin/login' in cl.get('/admin').location
    t = csrf(cl, '/admin/login')
    assert cl.post('/admin/login', data={'_csrf': t, 'pw': 'no'}).status_code == 200
    assert cl.post('/admin/login', data={'_csrf': t, 'pw': 'pw'}).status_code == 302
    with moa.conn() as db:
        o = db.execute('SELECT id,day,slot FROM orders').fetchone()
    a = cl.get(f'/admin?day={o["day"]}').get_data(as_text=True)
    assert '중앙타워 로비' in a and '김민지' in a
    cl.post('/admin', data={'_csrf': t, 'day': o['day'], 'act': 'paid', 'id': str(o['id'])})
    shop = moa.test_client().get(f'/s/tok?day={o["day"]}').get_data(as_text=True)
    assert '제육 도시락' in shop and '김민지' not in shop  # 가게 화면엔 개인정보 없음
    assert moa.test_client().get('/s/wrong').status_code == 404
    sc = moa.test_client()
    st = csrf(sc, f'/s/tok?day={o["day"]}')
    sc.post('/s/tok', data={'_csrf': st, 'day': o['day'], 'slot': o['slot']})
    with moa.conn() as db:
        assert db.execute('SELECT status FROM orders').fetchone()[0] == 'ready'


def test_admin_menu_adds(moa):
    cl = moa.test_client()
    t = csrf(cl, '/admin/login')
    cl.post('/admin/login', data={'_csrf': t, 'pw': 'pw'})
    cl.post('/admin/menu', data={'_csrf': t, 'kind': 'place', 'name': '힐스테이트 정문', 'pkind': '아파트'})
    cl.post('/admin/menu', data={'_csrf': t, 'kind': 'set', 'shop_id': '1', 'name': '김치찌개', 'price': '7900', 'cat': '한식'})
    page = cl.get('/admin/menu').get_data(as_text=True)
    assert '힐스테이트 정문' in page and '김치찌개' in page


def test_mount_host_and_preview(monkeypatch, tmp_path):
    monkeypatch.setenv('MOABAP_DB', str(tmp_path / 'x.sqlite3'))

    def main(environ, start):
        start('200 OK', [('Content-Type', 'text/plain')])
        return [b'MAIN']

    from werkzeug.test import Client
    monkeypatch.delenv('MOABAP_HOST', raising=False)
    monkeypatch.delenv('MOABAP_PREVIEW', raising=False)
    assert moabap.mount(main) is main
    monkeypatch.setenv('MOABAP_PREVIEW', '1')
    c = Client(moabap.mount(main))
    assert c.get('/').get_data() == b'MAIN'
    assert '모아밥' in c.get('/moabap/').get_data(as_text=True)
    monkeypatch.setenv('MOABAP_HOST', 'moabap.co.kr')
    c = Client(moabap.mount(main))
    assert '모아밥' in c.get('/', headers={'Host': 'www.moabap.co.kr'}).get_data(as_text=True)
    r = c.get('/moabap/set/1?src=app')
    assert r.status_code == 302 and r.headers['Location'] == 'https://moabap.co.kr/set/1?src=app'
