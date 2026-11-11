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
    c.execute("INSERT INTO shops(name,hygiene,token,owner,biz_no) VALUES('오늘제육','위생등급 우수','tok','김사장','123-45-67890')")
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
    assert '판매자 정보' in s and '123-45-67890' in s and '통신판매중개자' in s
    assert '통신판매중개자' in h
    assert cl.get('/set/99').status_code == 404
    assert cl.get('/privacy').status_code == 200
    r = cl.get('/refund').get_data(as_text=True)
    assert '취소·환불 정책' in r and '주문 마감 전' in r


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
    cl.post('/admin/menu', data={'_csrf': t, 'kind': 'shop', 'id': '1', 'name': '오늘제육', 'owner': '이대표', 'biz_no': '222-33-44444', 'address': '수원시 영통구'})
    assert '이대표' in cl.get('/admin/menu?eshop=1').get_data(as_text=True)
    assert '222-33-44444' in cl.get('/set/1').get_data(as_text=True)
    cl.post('/admin/menu', data={'_csrf': t, 'kind': 'company', 'name': '소비자를위한신문', 'owner': '오종민', 'bizno': '111-22-33333', 'mailorder': '제2026-서울강남-0001호', 'addr': '서울시 강남구', 'tel': '02-000-0000'})
    foot = cl.get('/').get_data(as_text=True)
    assert '111-22-33333' in foot and '제2026-서울강남-0001호' in foot and '02-000-0000' in foot
    cl.post('/admin/menu', data={'_csrf': t, 'kind': 'coord', 'id': '1', 'coord': '127.051470, 37.288612'})
    with moa.conn() as db:
        r = db.execute('SELECT lat,lng FROM places WHERE id=1').fetchone()
    assert (r['lat'], r['lng']) == (37.288612, 127.05147)
    cl.get('/pick')
    assert 'id="loc"' in cl.get('/').get_data(as_text=True)
    import io
    from PIL import Image
    buf = io.BytesIO(); Image.new('RGB', (1600, 1200), (240, 120, 40)).save(buf, 'PNG'); buf.seek(0)
    cl.post('/admin/menu', data={'_csrf': t, 'kind': 'set', 'id': '1', 'shop_id': '1', 'name': '제육 도시락', 'price': '5900', 'orig': '9500', 'cat': '한식', 'photo': (buf, 'a.png')}, content_type='multipart/form-data')
    with moa.conn() as db:
        ph = db.execute('SELECT photo FROM sets WHERE id=1').fetchone()['photo']
    assert ph.endswith('.jpg') and ph in cl.get('/').get_data(as_text=True)
    im = cl.get('/img/' + ph)
    assert im.status_code == 200 and Image.open(io.BytesIO(im.data)).size == (1200, 900)
    assert cl.get('/img/../x').status_code == 404
    cl.post('/admin/menu', data={'_csrf': t, 'kind': 'seo', 'naver': '<meta name="naver-site-verification" content="abc123def" />', 'google': 'g-XYZ_9'})
    h = cl.get('/').get_data(as_text=True)
    assert 'name="naver-site-verification" content="abc123def"' in h and 'content="g-XYZ_9"' in h and 'og:image' in h
    assert 'Disallow: /admin' in cl.get('/robots.txt').get_data(as_text=True)
    sm = cl.get('/sitemap.xml').get_data(as_text=True)
    assert '/set/1</loc>' in sm and '/about</loc>' in sm
    assert '힐스테이트 정문' in cl.get('/admin/menu?tab=place').get_data(as_text=True)
    page = cl.get('/admin/menu').get_data(as_text=True)
    assert '김치찌개' in page and 'role="switch"' in page
    for tab in ('set', 'shop', 'place', 'slot', 'applied', 'company', 'seo', 'nope'):
        assert cl.get(f'/admin/menu?tab={tab}').status_code == 200
    r = cl.post('/admin/menu', data={'_csrf': t, 'kind': 'toggle', 'table': 'places', 'id': '1'})
    assert r.location.endswith('tab=place')


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
    monkeypatch.setenv('MOABAP_HOST', 'moabap.com')
    c = Client(moabap.mount(main))
    assert '모아밥' in c.get('/', headers={'Host': 'www.moabap.com'}).get_data(as_text=True)
    r = c.get('/moabap/set/1?src=app')
    assert r.status_code == 302 and r.headers['Location'] == 'https://moabap.com/set/1?src=app'


def test_join_apply_shows_in_admin(moa):
    cl = moa.test_client()
    t = csrf(cl, '/join')
    r = cl.post('/join', data={'_csrf': t, 'shop': '광교김밥', 'phone': '031-123-4567', 'agree': '1', 'menu': '참치김밥'})
    assert '신청을 받았어요' in r.get_data(as_text=True)
    cl.post('/admin/login', data={'_csrf': t, 'pw': 'pw'})
    assert '광교김밥' in cl.get('/admin/menu?tab=applied').get_data(as_text=True)
    assert '<em>1</em>' in cl.get('/admin').get_data(as_text=True)  # 메뉴에 새 신청 수


def test_home_without_sets_has_no_price_promise(tmp_path):
    app = moabap.create_app(str(tmp_path / 'e.sqlite3'))
    h = app.test_client().get('/').get_data(as_text=True)
    assert '첫 세트를 준비하고 있어요' in h and '5,900원부터' not in h and 'class="timer"' not in h


def test_building_link_group_discount_and_referral(moa):
    with moa.conn() as db:
        db.execute("UPDATE places SET slug='tower' WHERE id=1")
    a = moa.test_client()
    a.get('/b/tower')
    assert '중앙타워 로비' in a.get('/').get_data(as_text=True)
    r = order(a, phone='01011110000')
    page = a.get(r.location).get_data(as_text=True)
    assert '같이 시키기 링크' in page and '/b/tower?r=' in page
    code = r.location.rsplit('/', 1)[1]
    # 동료가 링크로 들어와 처음 시킴 → 입금 확인되면 공유한 사람에게 보상
    b = moa.test_client()
    b.get(f'/b/tower?r={code}')
    with moa.conn() as db:
        db.execute("UPDATE sets SET cap=50")
    order(b, phone='01022220000')
    with moa.conn() as db:
        assert db.execute("SELECT ref FROM orders WHERE phone='01022220000'").fetchone()[0] == code
        db.execute("UPDATE orders SET status='paid'")
    # 5명 모이면 1,000원 + 추천 1,000원이 다음 주문에서 빠짐
    for i in range(3):
        order(moa.test_client(), phone=f'0103333000{i}')
    with moa.conn() as db:
        db.execute("UPDATE orders SET status='paid'")
    r3 = order(a, phone='01011110000')
    with moa.conn() as db:
        o = db.execute('SELECT credit,amount FROM orders WHERE code=?', (r3.location.rsplit('/', 1)[1],)).fetchone()
    assert o['credit'] == 2000 and o['amount'] == 3900
    assert '모아 할인 적립금' in a.get(r3.location).get_data(as_text=True)
