"""운영자 2026-11-04: 제보가 들어온 기업 중 공식 로고가 있는 곳은 로고를 자동으로.
홈페이지 주소(도메인)가 없는 기업을 네이버 웹문서 검색으로 먼저 찾고(운영자 2026-11-04), 없으면 AI에게 물어 공식 홈페이지를 찾고, 그 홈페이지 첫 화면에 기업 이름이 실제로 있을 때만 도메인으로 저장한 뒤
company_logo.fetch로 로고를 받아 둔다. 작은 가게처럼 공식 홈페이지가 없으면 건너뛰고(업종 그림이 대신 보임), 30일 동안 다시 묻지 않는다.

서버에서 한 번에 돌리기:
  sudo systemd-run --wait --pipe -p User=soboru -p EnvironmentFile=/etc/soboru.env -p WorkingDirectory=/opt/soboru/app /opt/soboru/venv/bin/python -m logo_fill
  (30일 안에 못 찾은 곳도 다시 찾으려면 맨 뒤에 again)
"""
import json, logging, os, re, time, urllib.parse, urllib.request

import company_logo
import companydesk

LOG = logging.getLogger(__name__)
RETRY_DAYS = 30
PROMPT = ('한국 소비자가 제보한 업체 이름을 받아, 그 업체의 공식 홈페이지 도메인을 알려 주세요. '
          'JSON만: {"domain": "coupang.com", "names": ["쿠팡", "coupang"], "sure": true}. '
          '널리 알려진 기업·브랜드의 공식 사이트일 때만 sure=true. 개인 가게, 이름이 흔해 어느 곳인지 모를 때, 확실하지 않을 때는 {"domain": "", "names": [], "sure": false}. '
          '쇼핑몰 입점 판매자는 판매자 자체 사이트가 없으면 빈 값. 도메인만 (https://, www., 경로 없이). '
          '소비자가 적은 이름이라 대소문자·띄어쓰기·주식회사 표기가 틀리거나 줄여 쓴 경우가 많아요. 어느 회사인지 분명하면 바르게 알아듣고 답하세요 '
          '(예: "Db손해보험" → {"domain": "idbins.com", "names": ["DB손해보험", "DB"], "sure": true}). names에는 한글 이름과 영문 이름을 함께.')


def ask(name):
    """업체 이름 → (도메인, 확인용 이름들). 모르면 ('', [])."""
    key = companydesk.ai_key_for('logo_fill')
    if not key: return '', []
    body = {'model': companydesk.ai_model(), 'temperature': 0, 'response_format': {'type': 'json_object'},
            'messages': [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': name[:80]}]}
    st, res = companydesk.post_json('https://api.openai.com/v1/chat/completions', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, 30)
    if st != 200: return '', []
    try: out = json.loads(res['choices'][0]['message']['content'])
    except Exception: return '', []
    if not out.get('sure'): return '', []
    return company_logo.clean_domain(out.get('domain') or ''), [str(x) for x in (out.get('names') or []) if str(x).strip()][:5]


SKIP = ('naver.', 'daum.', 'kakao.', 'google.', 'tistory.', 'wikipedia.', 'namu.wiki', 'youtube.', 'instagram.', 'facebook.', 'blog.', 'news', 'jobkorea.', 'saramin.',
        'coupang.com', '11st.', 'gmarket.', 'auction.', 'smartstore', 'wanted.', 'catch.', 'thevc.', 'nicebizinfo', 'dart.fss')


GENERIC = set("""치과 병원 의원 한의원 피부과 성형외과 안과 정형외과 약국 학원 어학원 헬스장 피트니스 필라테스 요가 pt 미용실 네일 네일샵 피부관리실 카페 식당 음식점 술집 치킨 피자
    쇼핑몰 온라인쇼핑몰 인터넷쇼핑몰 오픈마켓 마트 편의점 슈퍼 백화점 부동산 중개사무소 공인중개사 이사 이삿짐센터 이사업체 택배 택배사 배달 배달앱 은행 카드사 보험 보험사 통신사
    렌탈 렌터카 중고차 중고나라 중고거래 당근 숙소 호텔 모텔 펜션 리조트 여행사 항공사 인테리어 인테리어업체 세탁소 정비소 카센터 공방 스튜디오 사진관 웨딩홀 예식장 상조
    업체 회사 가게 판매자 개인 개인판매자 모름 기타 없음 불명 사업자 쇼핑 앱 어플 사이트 홈페이지 고객센터 대리점 매장 지점 본사""".split())


def generic(name):
    """운영자 2026-11-04: '치과'처럼 업종 이름만 있으면 어느 업체인지 모름 → 로고를 받지 않음."""
    k = squash(name)
    return len(k) < 2 or k in GENERIC or re.fullmatch(r'(동네|우리|어느|모르는|그)?(' + '|'.join(sorted(GENERIC, key=len, reverse=True)) + r')\d*', k) is not None


def naver_keys():
    """네이버 검색 키: 개발자센터(NAVER_SEARCH_ID·SECRET) 먼저, 없으면 API HUB(NAVER_HUB_CLIENT_ID·SECRET)."""
    a, b = os.getenv('NAVER_SEARCH_ID', '').strip(), os.getenv('NAVER_SEARCH_SECRET', '').strip()
    if a and b: return 'https://openapi.naver.com/v1/search/webkr.json', {'X-Naver-Client-Id': a, 'X-Naver-Client-Secret': b}
    a, b = os.getenv('NAVER_HUB_CLIENT_ID', '').strip(), os.getenv('NAVER_HUB_CLIENT_SECRET', '').strip()
    if a and b: return 'https://naverapihub.apigw.ntruss.com/search/v1/webkr', {'X-NCP-APIGW-API-KEY-ID': a, 'X-NCP-APIGW-API-KEY': b}
    return '', {}


def naver_get(url, headers):
    """(상태 코드, JSON). 테스트에서 바꿔 끼운다."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=8) as r: return r.status, json.loads(r.read().decode() or '{}')
    except Exception:
        return 0, {}


def naver_find(name):
    """운영자 2026-11-04: 네이버에서 검색하면 공식 홈페이지가 나옴 → 웹문서 검색 결과 중 제목에 업체 이름이 있는 사이트의 도메인. 못 찾으면 ''."""
    base, headers = naver_keys()
    if not base: return ''
    st, res = naver_get(base + '?' + urllib.parse.urlencode({'query': name[:60] + ' 공식 홈페이지', 'display': 10}), headers)
    if st != 200: return ''
    key = squash(name)
    for it in res.get('items') or []:
        head = re.split(r'\s[-|:·]\s|\||:', re.sub(r'<[^>]+>', '', it.get('title') or ''))[0]  # 사이트 제목의 앞부분이 업체 이름일 때만 ('100세치과'는 '치과'가 아님)
        dom = company_logo.clean_domain(it.get('link') or '')
        if len(key) >= 2 and dom and squash(head) in (key, key + '공식홈페이지', key + '공식몰') and not any(x in dom for x in SKIP): return dom
    return ''


def squash(t): return re.sub(r'[\s()\[\]㈜·.,\-_/]|주식회사|\(주\)', '', (t or '').lower())


def confirmed(domain, names):
    """그 홈페이지 첫 화면(제목·본문 앞부분)에 업체 이름이 실제로 있는지."""
    for home in ('https://' + domain + '/', 'https://www.' + domain + '/'):
        try:
            html = squash(company_logo.get(home, 400_000).decode('utf-8', 'replace'))
        except Exception:
            continue
        if any(len(squash(n)) >= 2 and squash(n) in html for n in names): return True
    # 운영자 2026-11-04: 다이소몰처럼 홈페이지가 프로그램(봇)을 막는 곳 → 도메인 자체에 영문 이름이 들어 있으면 인정 (daiso → daisomall.co.kr)
    base = domain.split('.')[0]
    return any(re.fullmatch(r'[a-z0-9]{4,}', squash(n)) and squash(n) in base for n in names)


def run(S, limit=40, log=print, again=False):
    """도메인 없는 기업(공개 제보가 있는 곳 먼저) → 공식 홈페이지 찾기 → 로고 받기. 받은 수를 돌려줌."""
    conn = S.conn; folder = S.UPLOAD / 'logos'; folder.mkdir(parents=True, exist_ok=True)
    since = '9999' if again else time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(time.time() - RETRY_DAYS * 86400))  # again: 30일 기다리지 않고 다시
    with conn() as db:
        rows = db.execute("""SELECT co.id, co.name, co.brand, COUNT(c.id) AS n FROM companies co JOIN cases c ON c.company_id=co.id
                             WHERE co.domain='' AND co.status IN ('active','listed') AND (co.logo_at='' OR co.logo_at<?)
                             GROUP BY co.id ORDER BY MAX(c.public_consent*c.published) DESC, n DESC LIMIT ?""", (since, limit)).fetchall()
    got = 0
    with conn() as db:  # 예전에 업종 이름만으로 잘못 받은 로고 지우기
        for g in db.execute("SELECT id,name,brand,logo FROM companies WHERE logo!=''").fetchall():
            if generic(g['brand'] or g['name']):
                (folder / g['logo']).unlink(missing_ok=True) if re.fullmatch(r'\d+\.png', g['logo']) else None
                db.execute("UPDATE companies SET domain='',logo='',logo_at=? WHERE id=?", (S.now(), g['id'])); log(f"{g['name']}: 업종 이름뿐이라 로고 지움")
    # 운영자 2026-11-04: 도메인은 있는데 로고가 없는 곳(쿠팡처럼 처음에 못 받은 곳)도 다시 받기 + 이름이 같은 기업끼리 로고 나눠 쓰기
    with conn() as db:
        known = db.execute("SELECT id,name,brand,domain,logo FROM companies WHERE domain!='' AND logo='' AND (logo_at='' OR logo_at<?) LIMIT ?", (since, limit)).fetchall()
    for k in known:
        if generic(k['brand'] or k['name']): continue
        png = company_logo.fetch(k['domain'])
        with conn() as db:
            if png:
                (folder / f"{k['id']}.png").write_bytes(png); db.execute("UPDATE companies SET logo=?,logo_at=? WHERE id=?", (f"{k['id']}.png", S.now(), k['id'])); got += 1
            else: db.execute("UPDATE companies SET logo_at=? WHERE id=?", (S.now(), k['id']))
        log(f"{k['name']}: {'로고 받음' if png else '로고를 못 받음'} ({k['domain']})")
    with conn() as db:
        have = {}
        for c in db.execute("SELECT id,name,brand,domain,logo,logo_at FROM companies WHERE logo!=''"):
            for n in (c['name'], c['brand']):
                if n and not generic(n): have.setdefault(squash(n), c)
        for c in db.execute("SELECT id,name,brand FROM companies WHERE logo=''").fetchall():
            src = next((have[squash(n)] for n in (c['brand'], c['name']) if n and squash(n) in have), None)
            if src and (folder / src['logo']).is_file():
                (folder / f"{c['id']}.png").write_bytes((folder / src['logo']).read_bytes())
                db.execute("UPDATE companies SET domain=CASE WHEN domain='' THEN ? ELSE domain END,logo=?,logo_at=? WHERE id=?", (src['domain'], f"{c['id']}.png", S.now(), c['id']))
                got += 1; log(f"{c['name']}: 같은 이름 기업 로고 씀")
    for r in rows:
        name = r['brand'] or r['name']
        if generic(name):
            with conn() as db: db.execute("UPDATE companies SET logo_at=? WHERE id=?", (S.now(), r['id']))
            log(f"{r['name']}: 업종 이름뿐이라 건너뜀"); continue
        domain = naver_find(name) or (naver_find(r['name']) if r['brand'] else '')
        if domain: ok = True  # 네이버 검색 결과 제목에 이름이 있는 사이트 = 확인됨
        else:
            domain, names = ask(name)
            ok = bool(domain) and confirmed(domain, names + [r['name'], r['brand'] or ''])
        png = company_logo.fetch(domain) if ok else b''
        with conn() as db:
            if png:
                (folder / f"{r['id']}.png").write_bytes(png)
                db.execute("UPDATE companies SET domain=?,logo=?,logo_at=? WHERE id=? AND domain=''", (domain, f"{r['id']}.png", S.now(), r['id']))
                got += 1
            else:
                db.execute("UPDATE companies SET logo_at=? WHERE id=? AND domain=''", (S.now(), r['id']))  # 30일 동안 다시 묻지 않음
        log(f"{r['name']}: {'로고 받음 (' + domain + ')' if png else ('홈페이지 확인 안 됨 (' + domain + ')' if domain else '공식 홈페이지 없음')}")
    return got


if __name__ == '__main__':
    import sys
    import app as site
    n = run(site, limit=500, again='again' in sys.argv[1:])
    print(f'로고를 새로 받은 기업: {n}곳')
