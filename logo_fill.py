"""운영자 2026-11-04: 제보가 들어온 기업 중 공식 로고가 있는 곳은 로고를 자동으로.
홈페이지 주소(도메인)가 없는 기업을 AI에게 물어 공식 홈페이지를 찾고, 그 홈페이지 첫 화면에 기업 이름이 실제로 있을 때만 도메인으로 저장한 뒤
company_logo.fetch로 로고를 받아 둔다. 작은 가게처럼 공식 홈페이지가 없으면 건너뛰고(업종 그림이 대신 보임), 30일 동안 다시 묻지 않는다.

서버에서 한 번에 돌리기:
  sudo systemd-run --wait --pipe -p User=soboru -p EnvironmentFile=/etc/soboru.env -p WorkingDirectory=/opt/soboru/app /opt/soboru/venv/bin/python -m logo_fill
  (30일 안에 못 찾은 곳도 다시 찾으려면 맨 뒤에 again)
"""
import json, logging, re, time

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
    for r in rows:
        name = r['brand'] or r['name']
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
