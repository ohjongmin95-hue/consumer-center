"""기업 메일 자동 찾기 (운영자 요청 2026-10-29: 유명 기업은 메일을 일일이 넣지 않아도 자동으로 보내기).
공정위 '통신판매사업자' 공개 자료에서 상호·사업자번호로 신고된 전자우편을 찾는다.
1) 공공데이터포털 API (환경변수 FTC_API_KEY, 없으면 DATA_GO_KR_KEY·NTS_API_KEY — 같은 포털 인증키, 두 서비스 활용신청 필요)
   - 등록현황(상호명으로 찾기): MllBs_2Service/getMllBsInfo_2 → 사업자번호
   - 등록상세(사업자번호로 찾기): MllBsDtl_3Service → 전자우편
2) 공정위 통신판매사업자 정보파일(CSV, data.go.kr/data/15083251)을 내려받아 넣어 둔 목록 (python -m company_mail import 파일.csv ...)
같은 이름이 여럿이고 메일이 서로 다르면 고르지 않음(엉뚱한 곳에 보내지 않게). 폐업·취소된 곳은 뺌.
명령: python -m company_mail find 쿠팡 [사업자번호]  /  python -m company_mail import a.csv b.csv
      python -m company_mail seed  → data/companies_seed.csv의 큰 기업(이름·법인명·다른 이름)을 미리 등록하고, 메일이 비어 있으면 찾아 채움
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


# ---- 큰 기업 미리 등록 (운영자 요청 2026-10-29: 연락처를 미리 넣어 두기) ----------------------------
SEED = Path(__file__).resolve().parent / 'data' / 'companies_seed.csv'


def seed(path=SEED, lookup=True):
    """(새로 등록, 메일 채움) 수. 같은 이름(다른 이름 포함)이 이미 있으면 다른 이름만 보탬. 공개 제보가 생겨야 기업 페이지가 열림."""
    import datetime
    db = sqlite3.connect(Path(os.getenv('DATABASE_PATH', str(Path(__file__).resolve().parent / 'cases.sqlite3'))))
    db.row_factory = sqlite3.Row
    now = datetime.datetime.now().isoformat(timespec='seconds'); added = filled = 0
    with db:
        cos = db.execute("SELECT * FROM companies WHERE status IN ('active','listed','pending')").fetchall()
        names = lambda c: [c['name'], c['brand'], c['biz_name']] + (c['aliases'] or '').split(',')
        for row in csv.DictReader(Path(path).read_text(encoding='utf-8-sig').splitlines()):
            name, legal = row['이름'].strip(), row['법인명'].strip()
            alias = [a.strip() for a in row['다른 이름'].split('|') if a.strip()]
            keys = {norm(n) for n in [name] + alias if norm(n)}
            hit = next((c for c in cos if keys & {norm(n) for n in names(c) if n and norm(n)}), None)
            if hit:
                have = [a.strip() for a in (hit['aliases'] or '').split(',') if a.strip()]
                more = [a for a in alias if norm(a) not in {norm(n) for n in names(hit) if n}]
                if more: db.execute('UPDATE companies SET aliases=? WHERE id=?', (', '.join(have + more)[:300], hit['id']))
                if legal and not hit['biz_name']: db.execute('UPDATE companies SET biz_name=? WHERE id=?', (legal, hit['id']))
                cid = hit['id']
            else:
                cid = db.execute("INSERT INTO companies(name,biz_no,status,contact_name,contact_phone,contact_email,created,biz_name,aliases) VALUES(?,'','listed','','','',?,?,?)",
                                 (name, now, legal, ', '.join(alias)[:300])).lastrowid
                added += 1
            dom = (row.get('도메인') or '').strip().lower()
            if dom: db.execute("UPDATE companies SET domain=? WHERE id=? AND domain=''", (dom, cid))  # 로고는 company_logo.py가 받아 둠
            co = db.execute('SELECT * FROM companies WHERE id=?', (cid,)).fetchone()
            if lookup and not co['official_email'] and not co['notice_optout'] and co['status'] != 'active':
                email, src = find([n for n in names(co) if n], co['biz_no'])
                if email: db.execute('UPDATE companies SET official_email=?,email_source=? WHERE id=?', (email, src, cid)); filled += 1
            cos = db.execute("SELECT * FROM companies WHERE status IN ('active','listed','pending')").fetchall()
    db.close()
    return added, filled


def auto(site):
    """처음 배포할 때 한 번만 큰 기업을 미리 등록 (메일 찾기는 오래 걸릴 수 있어 set-ftc.sh에서)."""
    if os.getenv('SOBORU_COMPANY_SEED', '1') == '0': return 0
    import datetime
    with site.conn() as db:
        db.execute('CREATE TABLE IF NOT EXISTS soboru_flags(key TEXT PRIMARY KEY,created TEXT NOT NULL)')
        first = db.execute("INSERT OR IGNORE INTO soboru_flags(key,created) VALUES('company_seed_v1',?)", (datetime.datetime.now().isoformat(timespec='seconds'),)).rowcount
    if not first: return 0
    try: return seed(lookup=False)[0]
    except Exception as e:  # 기업 목록 때문에 사이트가 안 뜨면 안 됨
        print('큰 기업 목록을 넣지 못했어요:', e); return 0


if __name__ == '__main__':
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ''), sys.argv[2:]
    if cmd == 'import' and args:
        print(f'{import_csv(args)}곳을 넣었어요 ({dir_path()}).')
    elif cmd == 'seed':
        added, filled = seed(args[0] if args else SEED, lookup=bool(api_key() or dir_path().exists()))
        print(f'큰 기업 {added}곳을 새로 등록했고, {filled}곳의 메일을 공정위 자료에서 찾아 채웠어요.')
    elif cmd == 'find' and args:
        email, src = find([args[0]], args[1] if len(args) > 1 else '')
        print(f'{args[0]}: {email} ({src})' if email else f'{args[0]}: 찾지 못했어요 (이름이 같은 곳이 여럿이거나 신고된 메일이 없어요).')
        print('API 키: ' + ('있음' if api_key() else '없음') + ' · 내려받은 목록: ' + ('있음' if dir_path().exists() else '없음'))
    else:
        print(__doc__)
