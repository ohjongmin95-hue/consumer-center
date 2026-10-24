"""동네일자리 (운영자 요청 2026-10-24): 지역 기반 무료 구인·구직. 기존 기능과 따로 도는 모듈.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다. 표는 jobs_* 이름으로만 만들고 다른 표는 건드리지 않는다.
- 공고 찾기(/jobs): 시·도 → 시·군·구 → 읍·면·동(글자), 낱말, 업종·급여 형태·최소 시급·시간대·요일·단기/장기·출처 필터. 자체 공고와 외부(공공) 공고를 한 목록에.
- 공고 보기(/jobs/<번호>): 자체 공고는 간편 지원·관심 저장·신고. 외부 공고는 출처를 밝히고 원문 지원 링크만 준다(지원은 원문에서).
- 사장님: 사업자 인증(/jobs/biz) → 무료 공고 올리기(/jobs/new)·고치기·마감 → 공고·지원자 관리(/jobs/manage, /jobs/<번호>/applicants).
  인증: 사업자번호 검사 숫자 확인 + 국세청 사업자 진위확인 API(환경변수 NTS_API_KEY가 있을 때). 키가 없으면 관리자가 확인해 승인한다.
- 구직자: 내 지원·관심 공고(/jobs/my). 지원서는 이름·연락처·한마디만 받고, 공고를 올린 사장님만 본다. 공고 마감 90일 뒤 지운다.
- 신고: 회원 1명당 공고마다 1번. 3번 쌓이면 바로 가리고 관리자가 확인(/admin/jobs).
- 외부 공고(PROVIDERS): 키는 환경변수로만(예: WORK24_API_KEY). 키가 없으면 수집하지 않고 자체 공고만 정상으로 돈다.
  6시간마다(요청이 들어올 때 뒤에서) 또는 관리자가 누르면 가져온다. 허용된 칸(ALLOWED)만 저장하고 연락처는 저장하지 않는다.
  같은 공고는 (출처, 원래 번호)로, 출처가 달라도 회사·제목·지역이 같으면 한 번만 보인다. 마감일이 지나면 마감, 마감 30일 뒤 지운다.
- 하지 않는 것: AI 매칭, 긴급 대타, 인력풀, 근태·급여, 유료 채용.
"""
import datetime, hashlib, json, logging, os, re, threading, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from flask import abort, flash, g, redirect, render_template, request, url_for

LOG = logging.getLogger(__name__)
PAGE = 20
MIN_WAGE = {2025: 10030, 2026: 10320}          # 최저임금(시급). 새해 고시가 나오면 한 줄 더
REPORT_HIDE = 3
APP_KEEP_DAYS = 90                             # 지원서: 공고 마감 뒤 보관 일수
EXT_KEEP_DAYS = 30                             # 외부 공고: 마감 뒤 보관 일수
SYNC_EVERY = 6 * 3600

REGIONS = {
    '서울': '강남구 강동구 강북구 강서구 관악구 광진구 구로구 금천구 노원구 도봉구 동대문구 동작구 마포구 서대문구 서초구 성동구 성북구 송파구 양천구 영등포구 용산구 은평구 종로구 중구 중랑구',
    '경기': '가평군 고양시 과천시 광명시 광주시 구리시 군포시 김포시 남양주시 동두천시 부천시 성남시 수원시 시흥시 안산시 안성시 안양시 양주시 양평군 여주시 연천군 오산시 용인시 의왕시 의정부시 이천시 파주시 평택시 포천시 하남시 화성시',
    '인천': '강화군 검단구 계양구 남동구 미추홀구 부평구 서구 연수구 영종구 옹진군 제물포구',
    '부산': '강서구 금정구 기장군 남구 동구 동래구 부산진구 북구 사상구 사하구 서구 수영구 연제구 영도구 중구 해운대구',
    '대구': '군위군 남구 달서구 달성군 동구 북구 서구 수성구 중구',
    '광주': '광산구 남구 동구 북구 서구',
    '대전': '대덕구 동구 서구 유성구 중구',
    '울산': '남구 동구 북구 울주군 중구',
    '세종': '세종시',
    '강원': '강릉시 고성군 동해시 삼척시 속초시 양구군 양양군 영월군 원주시 인제군 정선군 철원군 춘천시 태백시 평창군 홍천군 화천군 횡성군',
    '충북': '괴산군 단양군 보은군 영동군 옥천군 음성군 제천시 증평군 진천군 청주시 충주시',
    '충남': '계룡시 공주시 금산군 논산시 당진시 보령시 부여군 서산시 서천군 아산시 예산군 천안시 청양군 태안군 홍성군',
    '전북': '고창군 군산시 김제시 남원시 무주군 부안군 순창군 완주군 익산시 임실군 장수군 전주시 정읍시 진안군',
    '전남': '강진군 고흥군 곡성군 광양시 구례군 나주시 담양군 목포시 무안군 보성군 순천시 신안군 여수시 영광군 영암군 완도군 장성군 장흥군 진도군 함평군 해남군 화순군',
    '경북': '경산시 경주시 고령군 구미시 김천시 문경시 봉화군 상주시 성주군 안동시 영덕군 영양군 영주시 영천시 예천군 울릉군 울진군 의성군 청도군 청송군 칠곡군 포항시',
    '경남': '거제시 거창군 고성군 김해시 남해군 밀양시 사천시 산청군 양산시 의령군 진주시 창녕군 창원시 통영시 하동군 함안군 함양군 합천군',
    '제주': '서귀포시 제주시',
}
REGIONS = {k: v.split() for k, v in REGIONS.items()}
SIDO_ALIAS = {'서울특별시': '서울', '부산광역시': '부산', '대구광역시': '대구', '인천광역시': '인천', '광주광역시': '광주', '대전광역시': '대전', '울산광역시': '울산',
              '세종특별자치시': '세종', '경기도': '경기', '강원도': '강원', '강원특별자치도': '강원', '충청북도': '충북', '충청남도': '충남', '전라북도': '전북',
              '전북특별자치도': '전북', '전라남도': '전남', '경상북도': '경북', '경상남도': '경남', '제주특별자치도': '제주', '제주도': '제주'}
INDUSTRIES = [('food', '음식점·카페', '🍜'), ('store', '편의점·마트·매장', '🛒'), ('service', '미용·숙박·서비스', '💇'), ('delivery', '배달·운전', '🛵'),
              ('logistics', '물류·생산', '📦'), ('office', '사무·회계', '💼'), ('edu', '교육·강사', '✏️'), ('care', '돌봄·간호', '🩺'),
              ('it', 'IT·디자인', '💻'), ('site', '건설·현장', '🦺'), ('etc', '기타', '✨')]
IND = {k: (n, e) for k, n, e in INDUSTRIES}
IND_Z = {k: i for i, (k, n, e) in enumerate(INDUSTRIES)}   # 간판·차양 색 번호 (soboru.css .jb-shop.z0~z10)
PAY_TYPES = ['시급', '일급', '주급', '월급', '연봉', '건당']
DAYS = ['월', '화', '수', '목', '금', '토', '일']
TIMES = [('morning', '오전', 6, 12), ('afternoon', '오후', 12, 18), ('evening', '저녁', 18, 24), ('night', '새벽', 0, 6)]
TERMS = [('short', '단기 (1개월 이하)'), ('long', '장기 (1개월 넘게)')]
REPORT_REASONS = ['허위·과장 공고', '최저임금보다 적은 급여', '성별·나이 차별', '다단계·불법 영업', '개인정보·돈을 먼저 요구', '연락이 안 되거나 이미 마감', '기타']
APP_STATES = [('new', '새 지원'), ('seen', '확인함'), ('contact', '연락함'), ('hired', '채용'), ('no', '이번엔 함께 못 해요')]
APP_STATE = dict(APP_STATES)
# 차별·불법 문구 (남녀고용평등법 제7조, 고령자고용법 제4조의4, 직업안정법 제34조): 이런 말이 있으면 올리지 않는다
BAD_WORDS = [(re.compile(r'(남자|여자|남성|여성)\s*(만|only)\b'), '성별을 정해 뽑는 표현'), (re.compile(r'\d{2}\s*(세|살)\s*(이하|미만|까지|이상만)'), '나이를 정해 뽑는 표현'),
             (re.compile(r'(교육비|가입비|보증금|등록비)\s*(입금|선입금|먼저)'), '돈을 먼저 내게 하는 표현'), (re.compile(r'(통장|신분증\s*사본|체크카드)\s*(보내|전달|맡)'), '통장·신분증을 요구하는 표현')]

# ---- 외부(공공) 채용정보 ----------------------------------------------------------------
# key: 출처 이름, env: 키 환경변수, url: 기본 주소(환경변수 <PREFIX>_API_URL로 바꿀 수 있음), item: 공고 한 개의 XML 태그,
# fields: 우리 칸 ← 원본 칸. 여기 적은 칸만 저장한다(ALLOWED). 연락처·담당자 이름은 받아도 버린다.
PROVIDERS = [
    {'key': 'work24', 'name': '고용24', 'env': 'WORK24_API_KEY', 'url_env': 'WORK24_API_URL',
     'url': 'https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L01.do', 'item': 'wanted',
     'params': {'callTp': 'L', 'returnType': 'XML', 'display': 100}, 'key_param': 'authKey', 'page_param': 'startPage',
     'home': 'https://www.work24.go.kr', 'terms': '고용24(한국고용정보원) 채용정보 Open API',
     'fields': {'ext_id': 'wantedAuthNo', 'company': 'company', 'title': 'title', 'pay_type': 'salTpNm', 'pay_text': 'sal', 'pay_min': 'minSal',
                'pay_max': 'maxSal', 'region': 'region', 'holiday': 'holidayTpNm', 'career': 'career', 'edu': 'minEdubg', 'reg': 'regDt',
                'close': 'closeDt', 'link': 'wantedInfoUrl', 'mlink': 'wantedMobileInfoUrl', 'addr': 'basicAddr', 'emp_type': 'empTpNm'}},
]
PROVIDER = {p['key']: p for p in PROVIDERS}
ALLOWED = {f for p in PROVIDERS for f in p['fields']}


def now(): return datetime.datetime.now().isoformat(timespec='seconds')
def today(): return datetime.date.today().isoformat()
def min_wage(year=None): return MIN_WAGE.get(year or datetime.date.today().year) or MIN_WAGE[max(MIN_WAGE)]
def provider_key(p): return os.getenv(p['env'], '').strip()
def mask_key(k): return (k[:3] + '•' * 6 + k[-2:]) if len(k) > 6 else ('•' * len(k))


def biz_no_ok(no):
    """사업자등록번호 10자리 검사 숫자."""
    d = re.sub(r'\D', '', no or '')
    if len(d) != 10: return False
    w = [1, 3, 7, 1, 3, 7, 1, 3, 5]; s = sum(int(d[i]) * w[i] for i in range(9)) + int(d[8]) * 5 // 10
    return (10 - s % 10) % 10 == int(d[9])


def bad_words(text):
    return [why for rx, why in BAD_WORDS if rx.search(text or '')]


def norm_sido(s): s = (s or '').strip(); return SIDO_ALIAS.get(s, s if s in REGIONS else '')


def split_region(text):
    """'서울 강남구', '경기 수원시 장안구', '서울특별시 강남구 역삼동 ...' → (시·도, 시·군·구, 동)."""
    parts = re.split(r'[\s,]+', (text or '').strip()); sido = norm_sido(parts[0]) if parts else ''
    sgg = parts[1] if len(parts) > 1 and sido and parts[1] in REGIONS.get(sido, []) else ''
    if sido == '세종': sgg = '세종시'
    dong = next((p for p in parts[2:] if re.fullmatch(r'[가-힣0-9]+(동|읍|면|가)', p)), '')
    return sido, sgg, dong


def parse_date(text):
    """'26-11-30', '2026-11-30', '채용시까지 26-11-30', '20261130' → '2026-11-30' (없으면 '')."""
    m = re.search(r'(20\d{2}|\d{2})[-./]?(\d{1,2})[-./]?(\d{1,2})', text or '')
    if not m: return ''
    y = int(m.group(1)); y = y + 2000 if y < 100 else y
    try: return datetime.date(y, int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError: return ''


def to_int(v):
    v = re.sub(r'[^\d]', '', str(v or ''))
    return int(v) if v else 0


def dkey(company, title, sido, sgg):
    k = re.sub(r'\W', '', f'{company}|{title}|{sido}|{sgg}'.lower())
    return hashlib.sha1(k.encode()).hexdigest()[:16]


def fetch(p, page, timeout=20):
    """외부 API 한 쪽을 받아 [원본 dict]. 허용된 칸만 남긴다."""
    url = os.getenv(p['url_env'], '').strip() or p['url']
    q = dict(p['params']); q[p['key_param']] = provider_key(p); q[p['page_param']] = page
    req = urllib.request.Request(url + '?' + urllib.parse.urlencode(q), headers={'User-Agent': 'soboru-jobs/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r: body = r.read()
    return parse_items(p, body)


def parse_items(p, body):
    root = ET.fromstring(body)
    err = root.findtext('.//message') or root.findtext('.//error') or ''
    items = root.iter(p['item'])
    out = []
    for it in items:
        raw = {ours: (it.findtext(theirs) or '').strip() for ours, theirs in p['fields'].items()}
        if raw.get('ext_id') and raw.get('title'): out.append(raw)
    if not out and err and 'total' not in err.lower(): raise RuntimeError(err[:160])
    return out


def to_row(p, raw):
    """원본 → jobs 표 한 줄 (허용된 칸만)."""
    sido, sgg, dong = split_region(raw.get('region') or raw.get('addr'))
    if not dong: dong = split_region(raw.get('addr'))[2]
    pt = next((t for t in PAY_TYPES if t in (raw.get('pay_type') or '')), '협의' if not raw.get('pay_type') else raw['pay_type'][:6])
    pay = to_int(raw.get('pay_min')) or to_int(raw.get('pay_text')); pay_max = to_int(raw.get('pay_max'))
    if pay_max and pay_max < pay: pay_max = 0
    close = parse_date(raw.get('close'))
    text = ' '.join(x for x in (raw.get('emp_type'), raw.get('holiday'), raw.get('career'), raw.get('edu')) if x)
    term = 'short' if re.search(r'단기|일용|기간제|계약직\(1개월', text) else 'long'
    days = '토,일' if '주말' in text else ''
    link = raw.get('link') or ''
    return {'src': p['key'], 'ext_id': raw['ext_id'][:60], 'title': raw['title'][:80], 'company': (raw.get('company') or '')[:60], 'sido': sido, 'sigungu': sgg,
            'dong': dong, 'addr': (raw.get('addr') or raw.get('region') or '')[:120], 'industry': 'etc', 'pay_type': pt, 'pay': pay, 'pay_max': pay_max,
            'term': term, 'days': days, 'start_t': '', 'end_t': '', 'body': text[:300], 'apply_url': link if link.startswith('https://') or link.startswith('http://') else '',
            'close_date': close, 'dkey': dkey(raw.get('company'), raw['title'], sido, sgg)}


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,src TEXT NOT NULL DEFAULT 'own',ext_id TEXT NOT NULL DEFAULT '',user_id INTEGER,
        title TEXT NOT NULL,company TEXT NOT NULL DEFAULT '',sido TEXT NOT NULL DEFAULT '',sigungu TEXT NOT NULL DEFAULT '',dong TEXT NOT NULL DEFAULT '',addr TEXT NOT NULL DEFAULT '',
        industry TEXT NOT NULL DEFAULT 'etc',pay_type TEXT NOT NULL DEFAULT '시급',pay INTEGER NOT NULL DEFAULT 0,pay_max INTEGER NOT NULL DEFAULT 0,
        term TEXT NOT NULL DEFAULT 'long',days TEXT NOT NULL DEFAULT '',start_t TEXT NOT NULL DEFAULT '',end_t TEXT NOT NULL DEFAULT '',time_nego INTEGER NOT NULL DEFAULT 0,
        headcount INTEGER NOT NULL DEFAULT 1,body TEXT NOT NULL DEFAULT '',apply_url TEXT NOT NULL DEFAULT '',close_date TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open',hidden INTEGER NOT NULL DEFAULT 0,reports INTEGER NOT NULL DEFAULT 0,views INTEGER NOT NULL DEFAULT 0,dkey TEXT NOT NULL DEFAULT '',
        seen TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,updated TEXT NOT NULL)''')
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS jobs_ext ON jobs(src,ext_id) WHERE src!='own'")
    db.execute('CREATE INDEX IF NOT EXISTS jobs_list ON jobs(status,hidden,sido,sigungu)')
    db.execute('CREATE INDEX IF NOT EXISTS jobs_dkey ON jobs(dkey)')
    db.execute('''CREATE TABLE IF NOT EXISTS jobs_biz(user_id INTEGER PRIMARY KEY,biz_no TEXT NOT NULL,name TEXT NOT NULL,owner TEXT NOT NULL,open_date TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT 'pending',how TEXT NOT NULL DEFAULT '',note TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,decided TEXT NOT NULL DEFAULT '')''')
    db.execute('''CREATE TABLE IF NOT EXISTS jobs_apps(id INTEGER PRIMARY KEY,job_id INTEGER NOT NULL,user_id INTEGER NOT NULL,name TEXT NOT NULL,phone TEXT NOT NULL,
        msg TEXT NOT NULL DEFAULT '',state TEXT NOT NULL DEFAULT 'new',created TEXT NOT NULL,UNIQUE(job_id,user_id))''')
    db.execute('CREATE TABLE IF NOT EXISTS jobs_saves(user_id INTEGER NOT NULL,job_id INTEGER NOT NULL,created TEXT NOT NULL,PRIMARY KEY(user_id,job_id))')
    db.execute('CREATE TABLE IF NOT EXISTS jobs_reports(job_id INTEGER NOT NULL,user_id INTEGER NOT NULL,reason TEXT NOT NULL,created TEXT NOT NULL,PRIMARY KEY(job_id,user_id))')
    db.execute('CREATE TABLE IF NOT EXISTS jobs_sync(src TEXT PRIMARY KEY,at TEXT NOT NULL DEFAULT \'\',ok INTEGER NOT NULL DEFAULT 0,added INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL DEFAULT 0,closed INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT \'\')')


def save_external(db, rows, stamp=None):
    """외부 공고 넣기·고치기. (넣음, 고침, 겹쳐서 뺌)."""
    stamp = stamp or now(); added = updated = dup = 0
    for r in rows:
        old = db.execute('SELECT id FROM jobs WHERE src=? AND ext_id=?', (r['src'], r['ext_id'])).fetchone()
        if old:
            db.execute('UPDATE jobs SET title=?,company=?,sido=?,sigungu=?,dong=?,addr=?,pay_type=?,pay=?,pay_max=?,term=?,days=?,body=?,apply_url=?,close_date=?,dkey=?,seen=?,updated=?,'
                       "status=CASE WHEN status='closed' AND (?='' OR ?>=?) THEN 'open' ELSE status END WHERE id=?",
                       (r['title'], r['company'], r['sido'], r['sigungu'], r['dong'], r['addr'], r['pay_type'], r['pay'], r['pay_max'], r['term'], r['days'], r['body'],
                        r['apply_url'], r['close_date'], r['dkey'], stamp, stamp, r['close_date'], r['close_date'], today(), old['id'])); updated += 1; continue
        if db.execute("SELECT 1 FROM jobs WHERE dkey=? AND status='open' AND hidden=0", (r['dkey'],)).fetchone(): dup += 1; continue
        db.execute('INSERT INTO jobs(src,ext_id,title,company,sido,sigungu,dong,addr,industry,pay_type,pay,pay_max,term,days,start_t,end_t,body,apply_url,close_date,dkey,seen,created,updated) '
                   'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (r['src'], r['ext_id'], r['title'], r['company'], r['sido'], r['sigungu'], r['dong'], r['addr'], r['industry'], r['pay_type'], r['pay'], r['pay_max'],
                    r['term'], r['days'], r['start_t'], r['end_t'], r['body'], r['apply_url'], r['close_date'], r['dkey'], stamp, stamp, stamp)); added += 1
    return added, updated, dup


def close_expired(db):
    """마감일이 지난 공고는 마감, 오래된 외부 공고와 지원서는 지움. 마감한 수."""
    t = today()
    n = db.execute("UPDATE jobs SET status='closed',updated=? WHERE status='open' AND close_date!='' AND close_date<?", (now(), t)).rowcount
    old = (datetime.date.today() - datetime.timedelta(days=EXT_KEEP_DAYS)).isoformat()
    db.execute("DELETE FROM jobs WHERE src!='own' AND status='closed' AND updated<?", (old,))
    # 외부 공고가 30일 넘게 목록에 다시 안 나오면 원문에서 내려간 것으로 보고 마감
    db.execute("UPDATE jobs SET status='closed',updated=? WHERE src!='own' AND status='open' AND seen<?", (now(), old))
    app_old = (datetime.date.today() - datetime.timedelta(days=APP_KEEP_DAYS)).isoformat()
    db.execute("DELETE FROM jobs_apps WHERE job_id IN (SELECT id FROM jobs WHERE status='closed' AND updated<?)", (app_old,))
    db.execute('DELETE FROM jobs_saves WHERE job_id NOT IN (SELECT id FROM jobs)')
    db.execute('DELETE FROM jobs_apps WHERE job_id NOT IN (SELECT id FROM jobs)')
    return n


def install(S):
    app = S.app; conn = S.conn
    with conn() as db: migrate(db)
    state = {'running': False, 'checked': 0.0}
    lock = threading.Lock()

    # ---- 외부 공고 가져오기 ----------------------------------------------------------
    def sync(src=None, pages=None, fetcher=None):
        """키가 있는 출처마다 몇 쪽씩 받아 저장. {출처: (넣음, 고침, 겹침, 오류)}."""
        out = {}
        pages = pages or int(os.getenv('JOBS_SYNC_PAGES', '5') or 5)
        for p in PROVIDERS:
            if src and p['key'] != src: continue
            if not provider_key(p) and not fetcher: continue
            added = upd = dup = 0; err = ''
            try:
                for page in range(1, pages + 1):
                    raws = (fetcher or fetch)(p, page)
                    if not raws: break
                    with conn() as db:
                        a, u, d = save_external(db, [to_row(p, r) for r in raws]); added += a; upd += u; dup += d
                    if len(raws) < p['params'].get('display', 100): break
            except Exception as e:
                err = str(e)[:200].replace(provider_key(p) or '@@', '***') if provider_key(p) else str(e)[:200]
                LOG.warning('외부 공고 가져오기 실패 (%s): %s', p['key'], err)
            with conn() as db:
                closed = close_expired(db)
                db.execute('INSERT INTO jobs_sync(src,at,ok,added,updated,closed,error) VALUES(?,?,?,?,?,?,?) ON CONFLICT(src) DO UPDATE SET at=excluded.at,ok=excluded.ok,'
                           'added=excluded.added,updated=excluded.updated,closed=excluded.closed,error=excluded.error', (p['key'], now(), 0 if err else 1, added, upd, closed, err))
            out[p['key']] = (added, upd, dup, err)
        return out

    def sync_bg():
        with lock:
            if state['running']: return False
            state['running'] = True
        def run():
            try: sync()
            finally: state['running'] = False
        threading.Thread(target=run, daemon=True).start(); return True

    @app.before_request
    def jobs_tick():
        # 6시간마다 한 번: 마감 처리, 키가 있으면 외부 공고 가져오기 (손님 요청을 기다리게 하지 않음)
        if not request.path.startswith('/jobs') or time.time() - state['checked'] < SYNC_EVERY: return
        state['checked'] = time.time()
        if app.config.get('TESTING') and not app.config.get('JOBS_SYNC_IN_TEST'): return
        try:
            with conn() as db:
                close_expired(db)
                last = {r['src']: r['at'] for r in db.execute('SELECT src,at FROM jobs_sync')}
            stale = any(provider_key(p) and last.get(p['key'], '') < (datetime.datetime.now() - datetime.timedelta(seconds=SYNC_EVERY)).isoformat() for p in PROVIDERS)
            if stale: sync_bg()
        except Exception as e: LOG.warning('동네일자리 정리 실패: %s', str(e)[:160])

    # ---- 읽기 도우미 ---------------------------------------------------------------
    def biz_of(uid):
        if not uid: return None
        with conn() as db: return db.execute('SELECT * FROM jobs_biz WHERE user_id=?', (uid,)).fetchone()

    def saved_ids():
        if 'job_saves' not in g:
            g.job_saves = set()
            if g.user:
                with conn() as db: g.job_saves = {r[0] for r in db.execute('SELECT job_id FROM jobs_saves WHERE user_id=?', (g.user['id'],))}
        return g.job_saves

    def view(r):
        r = dict(r)
        r['ind_name'], r['ind_emoji'] = IND.get(r['industry'], IND['etc'])
        r['place'] = ' '.join(x for x in (r['sigungu'] or r['sido'], r['dong']) if x) or '지역 미정'
        if r['pay']:
            r['pay_label'] = f"{r['pay_type']} {r['pay']:,}원" + (f" ~ {r['pay_max']:,}원" if r['pay_max'] else '')
        else: r['pay_label'] = '급여 협의' if r['pay_type'] in ('협의', '') else r['pay_type']
        r['days_list'] = [d for d in (r['days'] or '').split(',') if d]
        dl = r['days_list']
        r['days_label'] = ('월~금' if dl == DAYS[:5] else '주말' if dl == ['토', '일'] else '매일' if dl == DAYS else '·'.join(dl)) if dl else ''
        r['time_label'] = '시간 협의' if r['time_nego'] else (f"{r['start_t']}~{r['end_t']}" if r['start_t'] and r['end_t'] else '')
        r['term_label'] = '단기' if r['term'] == 'short' else '장기'
        r['source'] = PROVIDER[r['src']]['name'] if r['src'] in PROVIDER else ('사장님 직접' if r['src'] == 'own' else r['src'])
        r['own'] = r['src'] == 'own'
        r['zi'] = IND_Z.get(r['industry'], 10) if r['own'] else 10
        if r['close_date']:
            left = (datetime.date.fromisoformat(r['close_date']) - datetime.date.today()).days
            r['dday'] = '오늘 마감' if left == 0 else (f'D-{left}' if left > 0 else '마감')
        else: r['dday'] = '상시'
        if r['status'] == 'closed': r['dday'] = '마감'
        r['new'] = r['created'] >= (datetime.datetime.now() - datetime.timedelta(days=2)).isoformat()
        r['saved'] = r['id'] in saved_ids()
        return r

    def time_hit(r, slots):
        if not slots: return True
        if not r['start_t'] or not r['end_t']: return bool(r['time_nego'])
        try: s = int(r['start_t'][:2]); e = int(r['end_t'][:2]) or 24
        except ValueError: return True
        hours = set(range(s, e)) if e > s else set(range(s, 24)) | set(range(0, e))
        return any(hours & set(range(a, b)) for k, n, a, b in TIMES if k in slots)

    def search(a, page=1, per=PAGE):
        where, args = ["status='open'", 'hidden=0'], []
        sido = a.get('sido', ''); sido = sido if sido in REGIONS else ''
        sgg = a.get('sgg', ''); sgg = sgg if sido and sgg in REGIONS[sido] else ''
        dong = re.sub(r'[^가-힣0-9]', '', a.get('dong', ''))[:10]
        if sido: where.append('sido=?'); args.append(sido)
        if sgg: where.append('sigungu=?'); args.append(sgg)
        if dong: where.append('(dong LIKE ? OR addr LIKE ?)'); args += [f'%{dong}%', f'%{dong}%']
        q = ' '.join(a.get('q', '').split())[:40]
        for w in q.split()[:4]:
            like = '%' + w.replace('%', '').replace('_', '') + '%'
            where.append('(title LIKE ? OR company LIKE ? OR body LIKE ?)'); args += [like, like, like]
        inds = [x for x in a.getlist('ind') if x in IND]
        if inds: where.append('industry IN (%s)' % ','.join('?' * len(inds))); args += inds
        pts = [x for x in a.getlist('pay') if x in PAY_TYPES]
        if pts: where.append('pay_type IN (%s)' % ','.join('?' * len(pts))); args += pts
        wage = to_int(a.get('wage'))
        if wage: where.append("pay_type='시급' AND pay>=?"); args.append(wage)
        term = a.get('term', ''); term = term if term in dict(TERMS) else ''
        if term: where.append('term=?'); args.append(term)
        dsel = a.get('days', '')
        if dsel == 'weekday': where.append("(days LIKE '%월%' OR days LIKE '%화%' OR days LIKE '%수%' OR days LIKE '%목%' OR days LIKE '%금%')")
        elif dsel == 'weekend': where.append("(days LIKE '%토%' OR days LIKE '%일%')")
        src = a.get('src', ''); src = src if src in ('own', 'ext') else ''
        if src == 'own': where.append("src='own'")
        elif src == 'ext': where.append("src!='own'")
        sort = a.get('sort', 'new'); sort = sort if sort in ('new', 'pay', 'close') else 'new'
        order = {'new': "src='own' DESC, created DESC", 'pay': "pay_type='시급' DESC, pay DESC", 'close': "close_date='' , close_date ASC"}[sort]
        slots = [x for x in a.getlist('time') if x in {t[0] for t in TIMES}]
        with conn() as db:
            sql = 'SELECT * FROM jobs WHERE ' + ' AND '.join(where) + ' ORDER BY ' + order
            if slots:   # 시간대는 글자로 저장해서 파이썬에서 거름
                rows = [r for r in db.execute(sql + ' LIMIT 2000', args).fetchall() if time_hit(r, slots)]
                total = len(rows); rows = rows[(page - 1) * per: page * per]
            else:
                total = db.execute('SELECT COUNT(*) FROM jobs WHERE ' + ' AND '.join(where), args).fetchone()[0]
                rows = db.execute(sql + ' LIMIT ? OFFSET ?', args + [per, (page - 1) * per]).fetchall()
        f = {'sido': sido, 'sgg': sgg, 'dong': dong, 'q': q, 'ind': inds, 'pay': pts, 'wage': wage, 'term': term, 'days': dsel if dsel in ('weekday', 'weekend') else '',
             'src': src, 'sort': sort, 'time': slots}
        return [view(r) for r in rows], total, f

    def qs(f, **change):
        d = {k: v for k, v in f.items() if v}; d.update(change)
        return {k: v for k, v in d.items() if v not in (None, '', [], 0)}

    app.jinja_env.globals.update(JOB_REGIONS=REGIONS, JOB_INDUSTRIES=INDUSTRIES, JOB_PAY_TYPES=PAY_TYPES, JOB_DAYS=DAYS, JOB_TIMES=TIMES, JOB_TERMS=TERMS,
                                 job_qs=qs, JOB_MIN_WAGE=min_wage, JOB_REASONS=REPORT_REASONS, JOB_APP_STATES=APP_STATES, JOB_APP_STATE=APP_STATE)

    # ---- 공고 찾기 --------------------------------------------------------------
    @app.route('/jobs')
    def jobs():
        a = request.args
        if not any(k in a for k in ('sido', 'q', 'ind', 'pay', 'wage', 'term', 'days', 'src', 'time', 'page', 'sort')) and request.cookies.get('job_region'):
            sido, _, sgg = request.cookies.get('job_region', '').partition('|')   # 지난번 고른 동네
            if sido in REGIONS: return redirect(url_for('jobs', sido=sido, sgg=sgg if sgg in REGIONS[sido] else None))
        page = max(1, a.get('page', 1, type=int))
        rows, total, f = search(a, page)
        pages = max(1, -(-total // PAGE))
        with conn() as db:
            counts = {'own': db.execute("SELECT COUNT(*) FROM jobs WHERE status='open' AND hidden=0 AND src='own'").fetchone()[0],
                      'ext': db.execute("SELECT COUNT(*) FROM jobs WHERE status='open' AND hidden=0 AND src!='own'").fetchone()[0],
                      'new': db.execute("SELECT COUNT(*) FROM jobs WHERE status='open' AND hidden=0 AND created>=?", ((datetime.datetime.now() - datetime.timedelta(days=1)).isoformat(),)).fetchone()[0],
                      'shops': db.execute("SELECT COUNT(DISTINCT user_id) FROM jobs WHERE status='open' AND hidden=0 AND src='own'").fetchone()[0]}
        n_filter = len(f['ind']) + len(f['pay']) + len(f['time']) + bool(f['wage']) + bool(f['term']) + bool(f['days']) + bool(f['src'])
        resp = app.make_response(render_template('soboru_jobs.html', rows=rows, total=total, page=page, pages=pages, f=f, counts=counts, n_filter=n_filter,
                                                 ext_on=any(provider_key(p) for p in PROVIDERS), biz=biz_of(g.user['id']) if g.user else None))
        if f['sido']: resp.set_cookie('job_region', f"{f['sido']}|{f['sgg']}", max_age=180 * 86400, samesite='Lax', secure=request.is_secure)
        return resp

    def get_job(job_id, allow_hidden=False):
        with conn() as db: r = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not r: abort(404)
        mine = g.user and r['user_id'] == g.user['id']
        if r['hidden'] and not (allow_hidden or mine or S.admin_active()): abort(404)
        return r

    @app.route('/jobs/<int:job_id>')
    def job(job_id):
        r = get_job(job_id)
        with conn() as db:
            db.execute('UPDATE jobs SET views=views+1 WHERE id=?', (job_id,))
            applied = g.user and db.execute('SELECT state,created FROM jobs_apps WHERE job_id=? AND user_id=?', (job_id, g.user['id'])).fetchone()
            reported = g.user and db.execute('SELECT 1 FROM jobs_reports WHERE job_id=? AND user_id=?', (job_id, g.user['id'])).fetchone()
            n_apps = db.execute('SELECT COUNT(*) FROM jobs_apps WHERE job_id=?', (job_id,)).fetchone()[0]
            near = [view(x) for x in db.execute("SELECT * FROM jobs WHERE status='open' AND hidden=0 AND id!=? AND sido=? AND sigungu=? ORDER BY src='own' DESC, created DESC LIMIT 4",
                                                (job_id, r['sido'], r['sigungu'])).fetchall()] if r['sigungu'] else []
        return render_template('soboru_job.html', j=view(r), applied=applied, reported=reported, n_apps=n_apps, near=near,
                               mine=bool(g.user and r['user_id'] == g.user['id']), provider=PROVIDER.get(r['src']))

    @app.route('/jobs/<int:job_id>/save', methods=['POST'])
    @S.member_only
    def job_save(job_id):
        get_job(job_id)
        with conn() as db:
            if db.execute('DELETE FROM jobs_saves WHERE user_id=? AND job_id=?', (g.user['id'], job_id)).rowcount: flash(S.ui_text('jobs.unsaved', '관심 공고에서 뺐어요.'))
            else: db.execute('INSERT INTO jobs_saves(user_id,job_id,created) VALUES(?,?,?)', (g.user['id'], job_id, now())); flash(S.ui_text('jobs.saved', '관심 공고에 담았어요.'))
        return redirect(S.safe_next('jobs') if request.form.get('next') else url_for('job', job_id=job_id))

    @app.route('/jobs/<int:job_id>/apply', methods=['GET', 'POST'])
    @S.member_only
    def job_apply(job_id):
        r = get_job(job_id)
        if r['src'] != 'own':
            return redirect(r['apply_url']) if r['apply_url'] else redirect(url_for('job', job_id=job_id))
        if r['status'] != 'open': flash(S.ui_text('jobs.closed', '마감된 공고예요.')); return redirect(url_for('job', job_id=job_id))
        if r['user_id'] == g.user['id']: flash(S.ui_text('jobs.own_apply', '내가 올린 공고에는 지원할 수 없어요.')); return redirect(url_for('job', job_id=job_id))
        f = request.form
        if request.method == 'POST':
            name = ' '.join(f.get('name', '').split())[:20]; phone = re.sub(r'[^\d]', '', f.get('phone', ''))[:11]; msg = f.get('msg', '').strip()[:300]
            err = None
            if f.get('agree') != '1': err = S.ui_text('jobs.e_agree', '개인정보 제공에 동의해야 지원할 수 있어요.')
            elif not 2 <= len(name) <= 20: err = S.ui_text('jobs.e_name', '이름을 적어 주세요.')
            elif not re.fullmatch(r'01[016789]\d{7,8}', phone): err = S.ui_text('jobs.e_phone', '휴대폰 번호를 다시 확인해 주세요.')
            if err: flash(err); return render_template('soboru_job_apply.html', j=view(r), f=f), 400
            with conn() as db:
                if db.execute('SELECT 1 FROM jobs_apps WHERE job_id=? AND user_id=?', (job_id, g.user['id'])).fetchone():
                    flash(S.ui_text('jobs.already', '이미 지원한 공고예요.')); return redirect(url_for('job', job_id=job_id))
                db.execute('INSERT INTO jobs_apps(job_id,user_id,name,phone,msg,created) VALUES(?,?,?,?,?,?)', (job_id, g.user['id'], name, phone, msg, now()))
                S.member_alert(db, r['user_id'], 'job', S.ui_text('jobs.alert_new', '새 지원자가 있어요') + f": {r['title'][:40]}", url_for('job_applicants', job_id=job_id))
            flash(S.ui_text('jobs.applied', '지원했어요. 사장님이 확인하면 알려 드릴게요.'))
            return redirect(url_for('job', job_id=job_id))
        return render_template('soboru_job_apply.html', j=view(r), f={'name': ''})

    @app.route('/jobs/<int:job_id>/report', methods=['POST'])
    @S.member_only
    def job_report(job_id):
        r = get_job(job_id); reason = request.form.get('reason', '')
        if reason not in REPORT_REASONS: abort(400)
        with conn() as db:
            if not db.execute('SELECT 1 FROM jobs_reports WHERE job_id=? AND user_id=?', (job_id, g.user['id'])).fetchone():
                db.execute('INSERT INTO jobs_reports(job_id,user_id,reason,created) VALUES(?,?,?,?)', (job_id, g.user['id'], reason, now()))
                db.execute('UPDATE jobs SET reports=reports+1 WHERE id=?', (job_id,))
                n = db.execute('SELECT reports FROM jobs WHERE id=?', (job_id,)).fetchone()[0]
                if n >= REPORT_HIDE: db.execute('UPDATE jobs SET hidden=1 WHERE id=?', (job_id,))
        flash(S.ui_text('jobs.reported', '신고했어요. 운영자가 확인할게요.'))
        return redirect(url_for('job', job_id=job_id) if not r['hidden'] else url_for('jobs'))

    # ---- 구직자: 내 지원·관심 ------------------------------------------------------
    @app.route('/jobs/my')
    @S.member_only
    def jobs_my():
        tab = request.args.get('t', 'apps'); tab = tab if tab in ('apps', 'saved') else 'apps'
        with conn() as db:
            apps = db.execute('SELECT a.state,a.created AS applied,j.* FROM jobs_apps a JOIN jobs j ON j.id=a.job_id WHERE a.user_id=? ORDER BY a.id DESC', (g.user['id'],)).fetchall()
            saved = db.execute('SELECT j.* FROM jobs_saves s JOIN jobs j ON j.id=s.job_id WHERE s.user_id=? AND j.hidden=0 ORDER BY s.created DESC', (g.user['id'],)).fetchall()
        return render_template('soboru_jobs_my.html', tab=tab, apps=[dict(view(r), app_state=r['state'], applied=r['applied']) for r in apps], saved=[view(r) for r in saved])

    # ---- 사장님: 사업자 인증 -----------------------------------------------------------
    def nts_check(no, owner, open_date):
        """국세청 사업자등록정보 진위확인. (결과 'ok'|'no'|'', 메모). 키가 없거나 실패하면 ''(관리자 확인)."""
        key = os.getenv('NTS_API_KEY', '').strip()
        if not key: return '', ''
        body = json.dumps({'businesses': [{'b_no': no, 'start_dt': open_date.replace('-', ''), 'p_nm': owner}]}).encode()
        try:
            req = urllib.request.Request('https://api.odcloud.kr/api/nts-businessman/v1/validate?serviceKey=' + urllib.parse.quote(key), data=body,
                                         headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as res: d = json.loads(res.read().decode())
            item = (d.get('data') or [{}])[0]
            if item.get('valid') != '01': return 'no', '국세청 정보와 맞지 않음'
            st = (item.get('status') or {}).get('b_stt_cd', '')
            return ('ok', '국세청 확인') if st in ('01', '') else ('no', '휴업·폐업 사업자')
        except Exception as e:
            LOG.warning('사업자 진위확인 실패: %s', str(e)[:120].replace(key, '***')); return '', '국세청 확인 실패, 관리자 확인'

    @app.route('/jobs/biz', methods=['GET', 'POST'])
    @S.member_only
    def jobs_biz():
        b = biz_of(g.user['id']); f = request.form
        if request.method == 'POST':
            if b and b['state'] == 'ok': return redirect(url_for('job_new'))
            no = re.sub(r'\D', '', f.get('biz_no', '')); name = ' '.join(f.get('name', '').split())[:40]; owner = ' '.join(f.get('owner', '').split())[:20]
            od = f.get('open_date', '')
            err = None
            if not biz_no_ok(no): err = S.ui_text('jobs.e_bizno', '사업자등록번호 10자리를 다시 확인해 주세요.')
            elif not name or not owner: err = S.ui_text('jobs.e_bizname', '상호와 대표자 이름을 적어 주세요.')
            elif not re.fullmatch(r'\d{4}-\d{2}-\d{2}', od): err = S.ui_text('jobs.e_bizdate', '개업일을 골라 주세요.')
            elif f.get('agree') != '1': err = S.ui_text('jobs.e_bizagree', '확인 내용에 동의해 주세요.')
            if err: flash(err); return render_template('soboru_jobs_biz.html', b=b, f=f, nts=bool(os.getenv('NTS_API_KEY'))), 400
            res, note = nts_check(no, owner, od)
            st = 'ok' if res == 'ok' else ('rejected' if res == 'no' else 'pending')
            with conn() as db:
                db.execute('INSERT INTO jobs_biz(user_id,biz_no,name,owner,open_date,state,how,note,created,decided) VALUES(?,?,?,?,?,?,?,?,?,?) '
                           'ON CONFLICT(user_id) DO UPDATE SET biz_no=excluded.biz_no,name=excluded.name,owner=excluded.owner,open_date=excluded.open_date,state=excluded.state,'
                           'how=excluded.how,note=excluded.note,created=excluded.created,decided=excluded.decided',
                           (g.user['id'], no, name, owner, od, st, 'nts' if res else 'admin', note, now(), now() if res else ''))
            flash({'ok': S.ui_text('jobs.biz_ok', '사업자 인증을 마쳤어요. 이제 공고를 올릴 수 있어요.'),
                   'rejected': S.ui_text('jobs.biz_no', '국세청 정보와 맞지 않아요. 번호·대표자·개업일을 다시 확인해 주세요.'),
                   'pending': S.ui_text('jobs.biz_wait', '인증 신청을 받았어요. 운영자가 확인하면 알려 드릴게요.')}[st])
            return redirect(url_for('job_new') if st == 'ok' else url_for('jobs_biz'))
        return render_template('soboru_jobs_biz.html', b=b, f={}, nts=bool(os.getenv('NTS_API_KEY')))

    # ---- 사장님: 공고 올리기·고치기 ----------------------------------------------------------
    def form_job(f, b):
        title = ' '.join(f.get('title', '').split())[:60]; ind = f.get('industry', ''); body = f.get('body', '').strip()[:2000]
        sido = f.get('sido', ''); sgg = f.get('sgg', ''); dong = re.sub(r'[^가-힣0-9]', '', f.get('dong', ''))[:12]; addr = ' '.join(f.get('addr', '').split())[:80]
        pt = f.get('pay_type', ''); pay = to_int(f.get('pay')); days = [d for d in DAYS if d in f.getlist('days')]
        st = f.get('start_t', ''); et = f.get('end_t', ''); nego = f.get('time_nego') == '1'; term = f.get('term', '')
        head = max(1, min(99, to_int(f.get('headcount')) or 1)); close = f.get('close_date', '')
        err = None
        if not 4 <= len(title) <= 60: err = '제목을 4~60자로 적어 주세요.'
        elif ind not in IND: err = '업종을 골라 주세요.'
        elif sido not in REGIONS or sgg not in REGIONS[sido]: err = '근무 지역(시·도, 시·군·구)을 골라 주세요.'
        elif pt not in PAY_TYPES: err = '급여 형태를 골라 주세요.'
        elif not pay: err = '급여를 적어 주세요.'
        elif pt == '시급' and pay < min_wage(): err = f'시급은 올해 최저임금 {min_wage():,}원보다 적을 수 없어요.'
        elif term not in dict(TERMS): err = '근무 기간을 골라 주세요.'
        elif not days: err = '근무 요일을 하나 이상 골라 주세요.'
        elif not nego and not (re.fullmatch(r'\d{2}:\d{2}', st) and re.fullmatch(r'\d{2}:\d{2}', et)): err = '근무 시간을 적거나 ‘시간 협의’를 골라 주세요.'
        elif close and (not re.fullmatch(r'\d{4}-\d{2}-\d{2}', close) or close < today()): err = '마감일은 오늘이나 그 뒤로 골라 주세요.'
        elif not 20 <= len(body) <= 2000: err = '하는 일·우대 사항 같은 상세 내용을 20자 넘게 적어 주세요.'
        elif bad_words(title + ' ' + body): err = '이 표현은 쓸 수 없어요: ' + ', '.join(bad_words(title + ' ' + body)) + ' (성별·나이 차별, 돈·통장 요구 금지)'
        row = {'title': title, 'company': b['name'], 'industry': ind, 'body': body, 'sido': sido, 'sigungu': sgg, 'dong': dong, 'addr': addr, 'pay_type': pt, 'pay': pay,
               'days': ','.join(days), 'start_t': '' if nego else st, 'end_t': '' if nego else et, 'time_nego': int(nego), 'term': term, 'headcount': head, 'close_date': close}
        return row, err

    def need_biz():
        b = biz_of(g.user['id'])
        if not b or b['state'] != 'ok':
            flash(S.ui_text('jobs.need_biz', '공고는 사업자 인증을 마친 사장님만 올릴 수 있어요.')); return None
        return b

    @app.route('/jobs/new', methods=['GET', 'POST'])
    @S.member_only
    def job_new():
        b = need_biz()
        if not b: return redirect(url_for('jobs_biz'))
        if request.method == 'POST':
            row, err = form_job(request.form, b)
            if not err:
                with conn() as db:
                    if db.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND created>=?", (g.user['id'], today())).fetchone()[0] >= 5: err = '공고는 하루에 5개까지 올릴 수 있어요.'
            if err: flash(err); return render_template('soboru_job_form.html', f=request.form, b=b, edit=None), 400
            with conn() as db:
                cols = list(row) + ['src', 'user_id', 'dkey', 'created', 'updated']
                vals = list(row.values()) + ['own', g.user['id'], dkey(row['company'], row['title'], row['sido'], row['sigungu']), now(), now()]
                jid = db.execute(f"INSERT INTO jobs({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals).lastrowid
            flash(S.ui_text('jobs.posted', '공고를 올렸어요.'))
            return redirect(url_for('job', job_id=jid))
        return render_template('soboru_job_form.html', f={'sido': (request.cookies.get('job_region') or '|').split('|')[0], 'sgg': (request.cookies.get('job_region') or '|').split('|')[-1]}, b=b, edit=None)

    def my_job(job_id):
        r = get_job(job_id, allow_hidden=True)
        if r['src'] != 'own' or not g.user or r['user_id'] != g.user['id']: abort(403)
        return r

    @app.route('/jobs/<int:job_id>/edit', methods=['GET', 'POST'])
    @S.member_only
    def job_edit(job_id):
        r = my_job(job_id); b = need_biz()
        if not b: return redirect(url_for('jobs_biz'))
        if request.method == 'POST':
            row, err = form_job(request.form, b)
            if err: flash(err); return render_template('soboru_job_form.html', f=request.form, b=b, edit=r), 400
            with conn() as db:
                db.execute('UPDATE jobs SET ' + ','.join(f'{k}=?' for k in row) + ',updated=?,status=? WHERE id=?', list(row.values()) + [now(), 'open', job_id])
            flash(S.ui_text('jobs.edited', '공고를 고쳤어요.')); return redirect(url_for('job', job_id=job_id))
        f = dict(r); f['sgg'] = r['sigungu']; f['days'] = r['days'].split(',')
        return render_template('soboru_job_form.html', f=f, b=b, edit=r)

    @app.route('/jobs/<int:job_id>/close', methods=['POST'])
    @S.member_only
    def job_close(job_id):
        r = my_job(job_id); open_ = request.form.get('open') == '1'
        with conn() as db:
            if open_ and r['close_date'] and r['close_date'] < today(): db.execute("UPDATE jobs SET close_date='' WHERE id=?", (job_id,))
            db.execute('UPDATE jobs SET status=?,updated=? WHERE id=?', ('open' if open_ else 'closed', now(), job_id))
        flash(S.ui_text('jobs.reopened', '공고를 다시 열었어요.') if open_ else S.ui_text('jobs.closed_ok', '공고를 마감했어요.'))
        return redirect(S.safe_next('jobs_manage'))

    @app.route('/jobs/manage')
    @S.member_only
    def jobs_manage():
        b = biz_of(g.user['id'])
        with conn() as db:
            rows = db.execute("SELECT j.*,(SELECT COUNT(*) FROM jobs_apps a WHERE a.job_id=j.id) AS n_apps,(SELECT COUNT(*) FROM jobs_apps a WHERE a.job_id=j.id AND a.state='new') AS n_new "
                              "FROM jobs j WHERE j.user_id=? AND j.src='own' ORDER BY j.status='open' DESC, j.id DESC", (g.user['id'],)).fetchall()
        return render_template('soboru_jobs_manage.html', b=b, rows=[dict(view(r), n_apps=r['n_apps'], n_new=r['n_new']) for r in rows])

    @app.route('/jobs/<int:job_id>/applicants', methods=['GET', 'POST'])
    @S.member_only
    def job_applicants(job_id):
        r = my_job(job_id)
        with conn() as db:
            if request.method == 'POST':
                aid = request.form.get('app', type=int); st = request.form.get('state', '')
                if st not in APP_STATE: abort(400)
                a = db.execute('SELECT * FROM jobs_apps WHERE id=? AND job_id=?', (aid, job_id)).fetchone()
                if not a: abort(404)
                db.execute('UPDATE jobs_apps SET state=? WHERE id=?', (st, aid))
                if st != a['state'] and st in ('contact', 'hired', 'no'):
                    S.member_alert(db, a['user_id'], 'job', S.ui_text('jobs.alert_state', '지원 결과가 바뀌었어요') + f" ({APP_STATE[st]}): {r['title'][:40]}", url_for('jobs_my'))
                flash(S.ui_text('jobs.state_ok', '지원 상태를 바꿨어요.'))
                return redirect(url_for('job_applicants', job_id=job_id))
            apps = db.execute('SELECT * FROM jobs_apps WHERE job_id=? ORDER BY id DESC', (job_id,)).fetchall()
            db.execute("UPDATE jobs_apps SET state='seen' WHERE job_id=? AND state='new'", (job_id,))
        return render_template('soboru_job_applicants.html', j=view(r), apps=apps)

    # ---- 관리자 --------------------------------------------------------------
    @app.route('/admin/jobs', methods=['GET', 'POST'])
    @S.admin_only
    def admin_jobs():
        if request.method == 'POST':
            act = request.form.get('act'); jid = request.form.get('job', type=int); uid = request.form.get('user', type=int)
            with conn() as db:
                if act == 'sync': flash('외부 공고를 가져오기 시작했어요. 잠시 뒤 새로고침해 주세요.' if sync_bg() else '이미 가져오고 있어요.')
                elif act in ('hide', 'show') and jid:
                    db.execute('UPDATE jobs SET hidden=? WHERE id=?', (1 if act == 'hide' else 0, jid))
                    if act == 'show': db.execute('UPDATE jobs SET reports=0 WHERE id=?', (jid,)); db.execute('DELETE FROM jobs_reports WHERE job_id=?', (jid,))
                    flash('공고를 가렸어요.' if act == 'hide' else '공고를 다시 보이게 했어요.')
                elif act == 'delete' and jid:
                    db.execute('DELETE FROM jobs WHERE id=?', (jid,)); db.execute('DELETE FROM jobs_apps WHERE job_id=?', (jid,)); db.execute('DELETE FROM jobs_reports WHERE job_id=?', (jid,))
                    flash('공고를 지웠어요.')
                elif act in ('biz_ok', 'biz_no') and uid:
                    st = 'ok' if act == 'biz_ok' else 'rejected'
                    db.execute('UPDATE jobs_biz SET state=?,how=?,decided=? WHERE user_id=?', (st, 'admin', now(), uid))
                    S.member_alert(db, uid, 'job', '사업자 인증을 마쳤어요. 이제 동네일자리에 공고를 올릴 수 있어요.' if st == 'ok' else '사업자 인증이 승인되지 않았어요. 정보를 다시 확인해 주세요.', url_for('jobs_biz'))
                    flash('승인했어요.' if st == 'ok' else '반려했어요.')
            return redirect(url_for('admin_jobs'))
        with conn() as db:
            k = {'own': db.execute("SELECT COUNT(*) FROM jobs WHERE src='own' AND status='open' AND hidden=0").fetchone()[0],
                 'ext': db.execute("SELECT COUNT(*) FROM jobs WHERE src!='own' AND status='open' AND hidden=0").fetchone()[0],
                 'apps': db.execute('SELECT COUNT(*) FROM jobs_apps').fetchone()[0], 'hidden': db.execute('SELECT COUNT(*) FROM jobs WHERE hidden=1').fetchone()[0]}
            sync_rows = {r['src']: r for r in db.execute('SELECT * FROM jobs_sync')}
            pending = db.execute("SELECT b.*,u.nickname FROM jobs_biz b LEFT JOIN users u ON u.id=b.user_id WHERE b.state='pending' ORDER BY b.created").fetchall()
            reported = db.execute("SELECT j.*,(SELECT GROUP_CONCAT(reason,' · ') FROM jobs_reports r WHERE r.job_id=j.id) AS why FROM jobs j WHERE j.reports>0 OR j.hidden=1 ORDER BY j.hidden DESC,j.reports DESC LIMIT 50").fetchall()
            recent = db.execute("SELECT * FROM jobs WHERE src='own' ORDER BY id DESC LIMIT 20").fetchall()
        provs = [{'p': p, 'key': provider_key(p), 'masked': mask_key(provider_key(p)), 'sync': sync_rows.get(p['key'])} for p in PROVIDERS]
        return render_template('admin_jobs.html', k=k, provs=provs, pending=pending, reported=reported, recent=recent, running=state['running'], nts=bool(os.getenv('NTS_API_KEY')))

    # ---- 탈퇴: 지원서·관심·인증 지움, 올린 공고는 마감 ------------------------------------------
    def on_delete(db, uid):
        db.execute('DELETE FROM jobs_apps WHERE user_id=?', (uid,)); db.execute('DELETE FROM jobs_saves WHERE user_id=?', (uid,))
        db.execute('DELETE FROM jobs_reports WHERE user_id=?', (uid,)); db.execute('DELETE FROM jobs_biz WHERE user_id=?', (uid,))
        db.execute("UPDATE jobs SET status='closed',hidden=1,updated=? WHERE user_id=? AND src='own'", (now(), uid))
    if hasattr(S, 'MEMBER_DELETE_HOOKS'): S.MEMBER_DELETE_HOOKS.append(on_delete)

    app.extensions['soboru_jobs'] = {'sync': sync, 'search': search, 'close_expired': close_expired}
