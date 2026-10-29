"""기업 메일 자동 찾기 (운영자 요청 2026-10-29: 유명 기업은 메일을 일일이 넣지 않아도 자동으로 보내기).
공정위 '통신판매사업자' 공개 자료에서 상호·사업자번호로 신고된 전자우편을 찾는다.
1) 공공데이터포털 API (환경변수 FTC_API_KEY, 없으면 DATA_GO_KR_KEY·NTS_API_KEY — 같은 포털 인증키, 두 서비스 활용신청 필요)
   - 등록현황(상호명으로 찾기): MllBs_2Service/getMllBsInfo_2 → 사업자번호
   - 등록상세(사업자번호로 찾기): MllBsDtl_3Service → 전자우편
2) 공정위 통신판매사업자 정보파일(CSV, data.go.kr/data/15083251)을 내려받아 넣어 둔 목록 (python -m company_mail import 파일.csv ...)
같은 이름이 여럿이고 메일이 서로 다르면 고르지 않음(엉뚱한 곳에 보내지 않게). 폐업·취소된 곳은 뺌.
명령: python -m company_mail find 쿠팡 [사업자번호]  /  python -m company_mail import a.csv b.csv
"""
import csv, json, os, re, sqlite3, sys, urllib.parse, urllib.request
from pathlib import Path

LIST_URL = 'https://apis.data.go.kr/1130000/MllBs_2Service/getMllBsInfo_2'
DETAIL_BASE = 'https://apis.data.go.kr/1130000/MllBsDtl_3Service'
DETAIL_OPS = ('getMllBsInfoDetail_3', 'getMllBsDtlInfo_3', 'getMllBsInfo_3')  # 포털 문서에 오퍼레이션 이름이 안 보여서 차례로 시도
EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
CLOSED = ('폐업', '취소', '말소', '직권')
SOURCE = '공정위 통신판매 신고 정보'
TIMEOUT = 6


def api_key():
    return (os.getenv('FTC_API_KEY') or os.getenv('DATA_GO_KR_KEY') or os.getenv('NTS_API_KEY') or '').strip()


def dir_path():
    db = Path(os.getenv('DATABASE_PATH', str(Path(__file__).resolve().parent / 'cases.sqlite3')))
    return Path(os.getenv('SELLER_DIR_PATH', str(db.parent / 'seller_dir.sqlite3')))


def norm(name):
    name = re.sub(r'\(주\)|㈜|주식회사|\(유\)|유한회사', '', name or '')
    return re.sub(r'[\s\-_.·,()]', '', name).lower()


def digits(s):
    return re.sub(r'\D', '', s or '')


# ---- 공공데이터포털 API ---------------------------------------------------------
def fetch(url, params):
    q = urllib.parse.urlencode({**params, 'serviceKey': api_key(), 'resultType': 'json'})
    with urllib.request.urlopen(url + '?' + q, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode('utf-8', 'replace') or '{}')


def items(data):
    """응답 모양이 조금 달라도 'item' 목록을 꺼냄."""
    if isinstance(data, list): return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict): return []
    for k in ('items', 'item'):
        if k in data:
            got = items(data[k])
            if got or isinstance(data[k], list): return got
            if isinstance(data[k], dict) and not ({'items', 'item'} & set(data[k])): return [data[k]]
    for k in ('response', 'body'):
        if k in data: return items(data[k])
    return []


def pick(item, *keys):
    low = {k.lower(): v for k, v in item.items()}
    for k in keys:
        v = low.get(k.lower())
        if v not in (None, ''): return str(v).strip()
    return ''


def emails_in(item):
    out = []
    for k, v in item.items():
        if isinstance(v, str) and ('mail' in k.lower() or 'eml' in k.lower() or EMAIL_RE.fullmatch(v.strip())):
            out += [m.group(0).lower() for m in EMAIL_RE.finditer(v)]
    return list(dict.fromkeys(out))


def item_name(item):
    return pick(item, 'bzmnNm', 'conmNm', 'mllBsNm', 'entrpsNm', 'corpNm', 'bsshNm', 'cmpnyNm')


def item_closed(item):
    st = ' '.join(str(v) for k, v in item.items() if 'sttus' in k.lower() or 'stts' in k.lower() or 'oper' in k.lower())
    return any(w in st for w in CLOSED)


def api_detail(brno):
    for op in DETAIL_OPS:
        try: rows = items(fetch(f'{DETAIL_BASE}/{op}', {'pageNo': 1, 'numOfRows': 10, 'brno': brno}))
        except Exception: continue
        mails = [e for r in rows if not item_closed(r) for e in emails_in(r)]
        if rows: return list(dict.fromkeys(mails))
    return []


def api_find(names, brno=''):
    if not api_key(): return ''
    try:
        if not brno:
            want = {norm(n) for n in names if norm(n)}
            found = set(); mails = []
            for n in names:
                if not n: continue
                rows = items(fetch(LIST_URL, {'pageNo': 1, 'numOfRows': 100, 'bzmnNm': n}))
                for r in rows:
                    if norm(item_name(r)) in want and not item_closed(r):
                        b = digits(pick(r, 'brno', 'bizrno', 'bsnmRgstNo'))
                        if b: found.add(b)
                        mails += emails_in(r)
            mails = list(dict.fromkeys(mails))
            if len(found) != 1: return mails[0] if len(mails) == 1 and not found else ''
            brno = found.pop()
        got = api_detail(brno)
        return got[0] if len(got) == 1 else ''
    except Exception:
        return ''


# ---- 내려받은 CSV 목록 -------------------------------------------------------------
COLS = {'name': ('상호',), 'brno': ('사업자등록번호',), 'email': ('전자우편', '이메일'), 'status': ('업소상태', '운영상태'),
        'corp': ('법인여부',), 'domain': ('인터넷도메인',)}


def connect():
    db = sqlite3.connect(dir_path())
    db.execute('CREATE TABLE IF NOT EXISTS sellers(nname TEXT, name TEXT, brno TEXT, email TEXT, status TEXT, corp TEXT, domain TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS sellers_nname ON sellers(nname)')
    db.execute('CREATE INDEX IF NOT EXISTS sellers_brno ON sellers(brno)')
    return db


def read_rows(path):
    raw = Path(path).read_bytes()
    for enc in ('utf-8-sig', 'cp949'):
        try: text = raw.decode(enc); break
        except UnicodeDecodeError: continue
    else: text = raw.decode('cp949', 'replace')
    rd = csv.reader(text.splitlines())
    head = [h.strip() for h in next(rd, [])]
    at = {k: next((i for i, h in enumerate(head) if h in names), None) for k, names in COLS.items()}
    if at['name'] is None or at['email'] is None: raise ValueError(f'{path}: 상호·전자우편 칸이 없어요 (첫 줄: {head[:8]})')
    for row in rd:
        get = lambda k: row[at[k]].strip() if at[k] is not None and at[k] < len(row) else ''
        email = (EMAIL_RE.search(get('email')) or [None])[0] if get('email') else None
        if not email or any(w in get('status') for w in CLOSED): continue
        yield (norm(get('name')), get('name'), digits(get('brno')), email.lower(), get('status'), get('corp'), get('domain'))


def import_csv(paths):
    db = connect(); n = 0
    with db:
        for p in paths:
            rows = list(read_rows(p)); n += len(rows)
            db.executemany('INSERT INTO sellers VALUES(?,?,?,?,?,?,?)', rows)
    db.close()
    return n


def dir_find(names, brno=''):
    if not dir_path().exists(): return ''
    db = connect()
    try:
        rows = db.execute('SELECT email,corp FROM sellers WHERE brno=?', (brno,)).fetchall() if brno else []
        if not rows:
            keys = [k for k in {norm(n) for n in names} if k]
            if keys: rows = db.execute('SELECT email,corp FROM sellers WHERE nname IN (%s)' % ','.join('?' * len(keys)), keys).fetchall()
    finally: db.close()
    corp = [r for r in rows if '법인' in (r[1] or '')]
    mails = list(dict.fromkeys(r[0] for r in (corp or rows)))
    return mails[0] if len(mails) == 1 else ''


def find(names, brno=''):
    """(메일, 출처) — 못 찾았거나 하나로 정할 수 없으면 ('', '')."""
    names = [n for n in names if n and n.strip()]; brno = digits(brno)
    if len(brno) != 10: brno = ''
    email = dir_find(names, brno) or api_find(names, brno)
    return (email, SOURCE) if email else ('', '')


if __name__ == '__main__':
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ''), sys.argv[2:]
    if cmd == 'import' and args:
        print(f'{import_csv(args)}곳을 넣었어요 ({dir_path()}).')
    elif cmd == 'find' and args:
        email, src = find([args[0]], args[1] if len(args) > 1 else '')
        print(f'{args[0]}: {email} ({src})' if email else f'{args[0]}: 찾지 못했어요 (이름이 같은 곳이 여럿이거나 신고된 메일이 없어요).')
        print('API 키: ' + ('있음' if api_key() else '없음') + ' · 내려받은 목록: ' + ('있음' if dir_path().exists() else '없음'))
    else:
        print(__doc__)
