"""AI 소비자 상담(새 버전)의 법령 모음: 국가법령정보 Open API 현행 법령, 소비자분쟁해결기준 별표, 검색용 임베딩.

사이트(lawrag.py)와 매일 도는 deploy/law-sync.sh가 같이 쓴다. 저장은 서버 데이터 폴더 UPLOAD/laws/ 아래 파일만:
- synced_laws.json : Open API로 받은 현행 법령 원문 (law_corpus.json과 같은 꼴, 법령마다 synced 시각)
- law_status.json  : 법령마다 현행 시행일과 마지막 확인 시각 (PDF로 올린 법령이 옛 판인지 가릴 때)
- appendix.json    : 관리자가 올린 소비자분쟁해결기준 별표 PDF를 품목·분쟁유형·해결기준 한 줄씩 나눈 것
- emb_index.json / emb_vectors.bin : 조문마다 임베딩(숫자 묶음). 글이 바뀐 조문만 다시 만든다.
이 파일들은 새 버전 상담의 모음(corpus_v2)에만 들어간다. AI 제보 분류(triage)는 지금처럼 기본 모음과 올린 법령만 쓴다.

Open API 인증키는 환경변수 LAW_OC에서만 읽고, 주소·오류 글에 섞이면 ***로 지운다(로그·화면에 남기지 않음).
사용법(서버): sudo bash deploy/law-sync.sh  (안에서 python lawsync.py 를 서비스 계정으로 돌림)
"""
import array, datetime, hashlib, importlib.util, json, logging, math, os, re, subprocess, sys, tempfile, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

LOG = logging.getLogger(__name__)
ROOT = Path(__file__).parent
API = 'http://www.law.go.kr/DRF/'
EMBED_MODEL = os.getenv('ASK_EMBED_MODEL', '').strip() or 'text-embedding-3-small'
EMBED_DIM = 512            # 임베딩 길이 (짧게 받아 파일·계산을 가볍게)
EMBED_BATCH = 96           # 한 번에 보내는 조문 수
EMBED_CHARS = 1500         # 조문마다 임베딩에 넣는 글자 수
CHECK_DAYS = 3             # 마지막 확인이 이보다 오래면 '현행 여부 미확인'
# 매일 받는 법령: (key, 법령 이름, 짧은 이름, 대상). law는 원문까지, admrul(행정규칙)은 시행일만 확인.
# key가 기본 모음(law_corpus.json)과 같으면 새 버전 상담에서는 받은 현행 원문이 기본 모음 대신 쓰인다.
SYNC_LAWS = [('basic', '소비자기본법', '소비자기본법', 'law'),
             ('ecom', '전자상거래 등에서의 소비자보호에 관한 법률', '전자상거래법', 'law'),
             ('ecom_dec', '전자상거래 등에서의 소비자보호에 관한 법률 시행령', '전자상거래법 시행령', 'law'),
             ('terms', '약관의 규제에 관한 법률', '약관법', 'law'),
             ('door', '방문판매 등에 관한 법률', '방문판매법', 'law'),
             ('installment', '할부거래에 관한 법률', '할부거래법', 'law'),
             ('pl', '제조물 책임법', '제조물책임법', 'law'),
             ('fincon', '금융소비자 보호에 관한 법률', '금융소비자보호법', 'law'),
             ('food', '식품위생법', '식품위생법', 'law'),
             ('food_rule', '식품위생법 시행규칙', '식품위생법 시행규칙', 'law'),
             ('adlabel', '표시ㆍ광고의 공정화에 관한 법률', '표시광고법', 'law'),
             ('foodlabel', '식품 등의 표시ㆍ광고에 관한 법률', '식품표시광고법', 'law'),
             ('cosmetics', '화장품법', '화장품법', 'law'),
             ('kca', '소비자분쟁해결기준', '소비자분쟁해결기준', 'admrul'),
             # 제보가 많은 분야 (2026-10 추가)
             ('civil', '민법', '민법', 'law'),
             ('telecom', '전기통신사업법', '전기통신사업법', 'law'),
             ('sports', '체육시설의 설치ㆍ이용에 관한 법률', '체육시설법', 'law'),
             ('academy', '학원의 설립ㆍ운영 및 과외교습에 관한 법률', '학원법', 'law'),
             ('aviation', '항공사업법', '항공사업법', 'law'),
             ('tourism', '관광진흥법', '관광진흥법', 'law'),
             ('car', '자동차관리법', '자동차관리법', 'law'),
             ('efin', '전자금융거래법', '전자금융거래법', 'law'),
             ('privacy', '개인정보 보호법', '개인정보보호법', 'law'),
             ('marriage', '결혼중개업의 관리에 관한 법률', '결혼중개업법', 'law'),
             ('commerce', '상법', '상법(운송)', 'law')]
OPTIONAL_LAWS = []
# 조문이 아주 많은 법은 소비자 피해와 닿는 부분만 (key: (첫 조, 끝 조))
ARTICLE_RANGE = {'commerce': (125, 150)}   # 상법 제2편 제9장 운송업 (택배 분실·파손)
APPENDIX_KEY = 'kca_appx'
APPENDIX_SOURCE = 'https://www.law.go.kr/행정규칙/소비자분쟁해결기준'
TAG = re.compile(r'\s*<(?:개정|신설|전문개정|본조신설|제목개정|타법개정)[^>]*>')


def now(): return datetime.datetime.now().isoformat(timespec='seconds')
def norm_name(s): return re.sub(r'[\sㆍ·・]', '', s or '')
def ymd(s):
    s = re.sub(r'\D', '', s or '')
    return f'{s[:4]}-{s[4:6]}-{s[6:8]}' if len(s) >= 8 else ''


# ---- 저장 파일 ---------------------------------------------------------------
class Store:
    def __init__(self, folder):
        self.dir = Path(folder); self.dir.mkdir(parents=True, exist_ok=True)
        self.extra = self.dir / 'extra_laws.json'      # 관리자 > 법령 학습에서 올린 PDF (lawask.py)
        self.synced = self.dir / 'synced_laws.json'
        self.status = self.dir / 'law_status.json'
        self.appendix = self.dir / 'appendix.json'
        self.emb_index = self.dir / 'emb_index.json'
        self.emb_vec = self.dir / 'emb_vectors.bin'
        self.learned = self.dir / 'learned_laws.json'  # 질문으로 법제처에서 찾아 모아 둔 법 (다음부터 매일 받음)
        self.api_use = self.dir / 'api_use.json'       # 질문 때 쓴 법제처 호출 수 (하루 한도)

    def read(self, path, default=None):
        try: return json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError): return {} if default is None else default

    def write(self, path, data):
        path = Path(path); tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        os.replace(tmp, path)


def default_store():
    return Store(Path(os.getenv('UPLOAD_DIR', str(ROOT / 'private_uploads'))) / 'laws')


def corpus_v2(store):
    """새 버전 상담 전용 법령 모음 (law_corpus.py를 따로 한 번 더 읽어 triage의 모음과 섞이지 않게).
    순서: 기본 모음 < 올린 PDF < Open API 현행 원문 < 분쟁해결기준 별표."""
    spec = importlib.util.spec_from_file_location('jebo_law_corpus_v2_' + hashlib.sha1(str(store.dir).encode()).hexdigest()[:6], ROOT / 'platform_app' / 'law_corpus.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    for p in (store.extra, store.synced, store.appendix): mod.add_extra(p)
    return mod


# ---- 국가법령정보 Open API ------------------------------------------------------
def http_get(url, timeout=25):
    """(상태 코드, 글). 테스트에서 바꿔 끼운다. 연결 실패는 예외."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 soboru'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e: return e.code, ''


def oc(): return os.getenv('LAW_OC', '').strip()
def hide(text, key=None):
    key = key if key is not None else oc()
    return (text or '').replace(key, '***') if key else (text or '')


def api_get(path, timeout=25, **params):
    key = oc()
    if not key: raise RuntimeError('LAW_OC가 없어요 (deploy/set-law.sh로 넣어 주세요)')
    url = API + path + '?' + urllib.parse.urlencode(dict(OC=key, type='XML', **params))
    try: st, body = http_get(url, timeout)
    except Exception as e: raise RuntimeError(hide(f'법제처 연결 실패: {type(e).__name__}'))
    if st != 200 or not body.strip(): raise RuntimeError(f'법제처 응답 {st}')
    try: return ET.fromstring(body.strip())
    except ET.ParseError: raise RuntimeError('법제처 응답을 읽지 못했어요: ' + hide(re.sub(r'\s+', ' ', body)[:120], key))


def t(el, *names):
    for n in names:
        x = el.find(n) if el is not None else None
        if x is not None and (x.text or '').strip(): return x.text.strip()
    return ''


def search_law(name, target='law'):
    """이름이 똑같은 현행 법령 {mst, id, name, effective, kind}. 없으면 None."""
    root = api_get('lawSearch.do', target=target, query=name, display=20)
    tag = 'law' if target == 'law' else 'admrul'
    for el in root.iter(tag):
        nm = t(el, '법령명한글', '행정규칙명', '법령명')
        if norm_name(nm) == norm_name(name):
            return {'mst': t(el, '법령일련번호', '행정규칙일련번호'), 'id': t(el, '법령ID', '행정규칙ID'), 'name': nm,
                    'effective': ymd(t(el, '시행일자')), 'kind': t(el, '법령구분명', '행정규칙종류')}
    return None


def _join_text(*parts): return '\n'.join(p for p in parts if p)


def parse_law_xml(root):
    """lawService.do 응답 -> (기본정보, {제N조: {title, text}})"""
    info = root.find('기본정보')
    meta = {'name': t(info, '법령명_한글', '법령명한글'), 'effective': ymd(t(info, '시행일자')), 'promulgated': ymd(t(info, '공포일자')),
            'no': t(info, '공포번호'), 'kind': t(info, '법종구분') or t(info, '법령구분명')}
    arts = {}
    for u in root.iter('조문단위'):
        if t(u, '조문여부') and t(u, '조문여부') != '조문': continue   # 장·절 제목
        no = t(u, '조문번호'); br = t(u, '조문가지번호')
        if not no: continue
        art = f'제{no}조' + (f'의{br}' if br and br != '0' else '')
        title = t(u, '조문제목'); head = t(u, '조문내용')
        # '제17조(청약철회등) ① …' 에서 머리를 떼고 본문만
        head = re.sub(r'^제\d+조(?:의\d+)?\s*(?:\([^)]*\))?\s*', '', head)
        lines = [head] if head else []
        for h in u.findall('항'):
            lines.append(t(h, '항내용'))
            for ho in h.findall('호'):
                lines.append(t(ho, '호내용'))
                lines += [t(m, '목내용') for m in ho.findall('목')]
        for ho in u.findall('호'):   # 항 없이 바로 호
            lines.append(t(ho, '호내용')); lines += [t(m, '목내용') for m in ho.findall('목')]
        text = '\n'.join(TAG.sub('', re.sub(r'[ \t]+', ' ', l)).strip() for l in lines if l and l.strip())
        if title == '삭제' or text.startswith('삭제'): continue
        if art in arts: continue   # 같은 번호가 두 번(옛 조문) 나오면 앞의 것
        arts[art] = {'title': title, 'text': text}
    return meta, arts


def fetch_law(found, timeout=25):
    root = api_get('lawService.do', timeout, target='law', MST=found['mst']) if found.get('mst') else api_get('lawService.do', timeout, target='law', ID=found['id'])
    return parse_law_xml(root)


def art_no(art):
    m = re.match(r'제(\d+)조', art); return int(m.group(1)) if m else 0


def in_range(key, arts):
    lo_hi = ARTICLE_RANGE.get(key)
    return {a: x for a, x in arts.items() if lo_hi[0] <= art_no(a) <= lo_hi[1]} if lo_hi else arts


def all_laws(store):
    """매일 받는 법: 정해 둔 목록 + 질문으로 찾아 모아 둔 법"""
    fixed = SYNC_LAWS + OPTIONAL_LAWS; names = {norm_name(n) for _, n, _, _ in fixed}
    learned = [(k, x['name'], x.get('short') or x['name'], 'law') for k, x in store.read(store.learned).items() if norm_name(x.get('name')) not in names]
    return fixed + learned


def law_source(name, kind=''):
    return ('https://www.law.go.kr/행정규칙/' if kind == 'admrul' or '고시' in kind else 'https://www.law.go.kr/법령/') + name.replace(' ', '')


def sync(store, laws=None, log=print):
    """설정한 법령의 현행 시행일을 확인하고, 바뀌었거나 처음이면 원문을 받아 synced_laws.json에 넣는다.
    돌려주는 값: [{key, name, ok, changed, effective, error}]. 하나가 실패해도 나머지는 계속."""
    laws = laws or all_laws(store)
    synced = store.read(store.synced); status = store.read(store.status); out = []
    for key, name, short, target in laws:
        row = {'key': key, 'name': name, 'ok': False, 'changed': False, 'effective': '', 'error': ''}
        try:
            found = search_law(name, target)
            if not found: raise RuntimeError('법제처에서 같은 이름의 현행 법령을 찾지 못했어요')
            row['effective'] = found['effective']
            st = {'name': name, 'short': short, 'current': found['effective'], 'checked': now(), 'mst': found['mst'], 'target': target}
            if target == 'law':
                old = synced.get(key) or {}
                if old.get('effective') != found['effective'] or old.get('mst') != found['mst'] or not old.get('articles'):
                    meta, arts = fetch_law(found)
                    arts = in_range(key, arts)
                    if not arts: raise RuntimeError('조문을 받지 못했어요')
                    synced[key] = {'key': key, 'name': meta['name'] or name, 'short': short, 'kind': meta['kind'] or found['kind'] or '법률',
                                   'no': meta['no'], 'effective': meta['effective'] or found['effective'], 'promulgated': meta['promulgated'],
                                   'source': law_source(meta['name'] or name), 'articles': arts, 'mst': found['mst'], 'synced': now()}
                    row['changed'] = True
                else: synced[key]['checked'] = now()
            status[key] = st; row['ok'] = True
            log(f"  {short}: 시행 {found['effective'].replace('-', '.')}" + (' · 새로 받음' if row['changed'] else ' · 그대로'))
        except Exception as e:
            row['error'] = hide(str(e))[:200]
            status.setdefault(key, {'name': name, 'short': short, 'current': '', 'checked': '', 'target': target})['error'] = row['error']
            status[key]['error_at'] = now()
            log(f'  {short}: 실패 - {row["error"]}')
        out.append(row)
    store.write(store.synced, synced); store.write(store.status, status)
    return out


# ---- 질문으로 법 찾기 (모아 둔 법에서 못 찾을 때) ------------------------------------------
API_PER_DAY = int(os.getenv('LAW_API_PER_DAY', '300'))   # 질문 때 쓰는 법제처 호출 하루 한도
API_TIMEOUT = 6           # 손님이 기다리니 짧게
FIND_LAWS = 2             # 한 질문에 원문까지 받아 보는 법 수
MISS_DAYS = 1             # 찾아도 쓸 만한 법이 없던 낱말은 이만큼 다시 찾지 않음
LAW_KINDS = ('법률', '대통령령', '총리령', '부령')
ENDING = re.compile(r'(?:으로는|에서는|에게서|한테서|으로|에서|에게|한테|까지|부터|이랑|하고|처럼|보다|이나|은|는|이|가|을|를|에|의|도|로|와|과|만|요)$')
VERB = re.compile(r'(?:했더니|하려는데|하려고|했는데|하는데|했어요|해서|하면|해도|하고|했어|했다|됐는데|됐어요|되는데|됐어|되나|되는|됐|된|한)$')
QSTOP = {'어떻게', '어떤', '얼마나', '그런데', '근데', '혹시', '이거', '그거', '저거', '이런', '그런', '있나요', '없나요', '되나요', '하나요', '했어요', '했는데',
         '해요', '있어요', '없어요', '싶어요', '받을', '받을수', '수있나요', '가능한가요', '가능할까요', '문의', '질문', '제가', '저는', '우리', '너무', '정말', '진짜',
         '지금', '오늘', '어제', '이번', '다시', '계속', '그냥', '좀', '많이', '조금', '같아요', '같은데', '어요', '아요', '나요', '건가요', '할까요', '될까요', '하려는데', '하는데', '했더니'}


def keywords(question, n=3):
    """질문에서 법령 본문 검색에 쓸 낱말 (한글 두 글자 이상, 조사·말끝 뗀 것). 숫자·영문은 넣지 않는다(개인정보 줄이기)."""
    out = []
    for w in re.findall(r'[가-힣]{2,}', question or ''):
        w = VERB.sub('', w) if len(w) > 2 else w
        w = ENDING.sub('', w) if len(w) > 2 else w
        if len(w) < 2 or w in QSTOP or any(w.endswith(x) for x in ('어요', '아요', '나요', '는데', '해요', '세요', '까요', '했어', '니다', '었어', '았어', '났어')): continue
        if w not in out: out.append(w)
    out.sort(key=lambda w: -len(w))   # 긴 낱말이 대개 더 뜻이 좁다
    return out[:n]


def api_budget(store, n=1):
    """오늘 한도 안이면 n만큼 쓰고 True"""
    use = store.read(store.api_use); day = datetime.date.today().isoformat()
    if use.get('day') != day: use = {'day': day, 'n': 0, 'miss': use.get('miss', {})}
    if use['n'] + n > API_PER_DAY: return False
    use['n'] += n; store.write(store.api_use, use); return True


def missed(store, words):
    m = store.read(store.api_use).get('miss', {}).get(' '.join(words), '')
    try: return (datetime.datetime.now() - datetime.datetime.fromisoformat(m)).days < MISS_DAYS
    except ValueError: return False


def mark_miss(store, words):
    use = store.read(store.api_use); miss = use.get('miss', {})
    cut = (datetime.datetime.now() - datetime.timedelta(days=MISS_DAYS)).isoformat(timespec='seconds')
    miss = {k: v for k, v in miss.items() if v >= cut}; miss[' '.join(words)] = now()
    use['miss'] = miss; store.write(store.api_use, use)


def search_text(query, timeout=API_TIMEOUT):
    """법령 본문 검색(search=2) -> 현행 법령 [{mst, id, name, effective, kind}] (법률·시행령·시행규칙만)"""
    root = api_get('lawSearch.do', timeout, target='law', query=query, search=2, display=20)
    out = []
    for el in root.iter('law'):
        nm = t(el, '법령명한글', '법령명'); kind = t(el, '법령구분명')
        if not nm or (kind and kind not in LAW_KINDS): continue
        out.append({'mst': t(el, '법령일련번호'), 'id': t(el, '법령ID'), 'name': nm, 'effective': ymd(t(el, '시행일자')), 'kind': kind})
    return out


def learned_key(name): return 'api_' + hashlib.sha1(norm_name(name).encode()).hexdigest()[:8]


def short_name(name): return name   # 줄임말을 지어내지 않음 (정해 둔 법만 줄임말이 있다)


def discover(store, question, known=(), log=lambda s: None):
    """모아 둔 법에 없는 법을 법제처 본문 검색으로 찾아 원문까지 받는다 -> [(key, 법령 dict)].
    아직 저장하지 않음 (lawrag가 이번 답에 쓸 만한지 본 뒤 remember로 남긴다)."""
    if not oc(): return []
    words = keywords(question)
    if not words or missed(store, words): return []
    known = {norm_name(n) for n in known}; found = []
    for q in ([' '.join(words[:2])] + ([words[0]] if len(words) > 1 else [])):
        if not api_budget(store): log('하루 한도'); break
        try: rows = search_text(q)
        except RuntimeError as e: log(hide(str(e))); break
        rows = [r for r in rows if norm_name(r['name']) not in known]
        rows.sort(key=lambda r: LAW_KINDS.index(r['kind']) if r['kind'] in LAW_KINDS else 9)   # 법률 먼저
        if rows: found = rows; break
    out = []
    for r in found[:FIND_LAWS]:
        if not api_budget(store): break
        try: meta, arts = fetch_law(r, API_TIMEOUT)
        except RuntimeError as e: log(hide(str(e))); continue
        if not arts: continue
        name = meta['name'] or r['name']; key = learned_key(name)
        out.append((key, {'key': key, 'name': name, 'short': short_name(name), 'kind': meta['kind'] or r['kind'] or '법률', 'no': meta['no'],
                          'effective': meta['effective'] or r['effective'], 'promulgated': meta['promulgated'], 'source': law_source(name),
                          'articles': arts, 'mst': r['mst'], 'synced': now(), 'api': True}))
    if not out: mark_miss(store, words)
    return out


def remember(store, key, law, dtype=''):
    """쓸 만했던 법을 모아 두기: 원문은 synced_laws.json, 이름은 learned_laws.json (다음부터 매일 받음)"""
    learned = store.read(store.learned); row = learned.get(key) or {'name': law['name'], 'short': law['short'], 'found': now(), 'uses': 0, 'dtype': dtype}
    row['uses'] += 1; row['last'] = now(); learned[key] = row; store.write(store.learned, learned)
    status = store.read(store.status)
    status[key] = {'name': law['name'], 'short': law['short'], 'current': law['effective'], 'checked': now(), 'mst': law.get('mst', ''), 'target': 'law'}
    store.write(store.status, status)


def forget(store, key):
    """모아 둔 법 빼기 (관리자)"""
    for path in (store.learned, store.synced, store.status):
        data = store.read(path)
        if data.pop(key, None) is not None: store.write(path, data)


# ---- 현행 여부 -------------------------------------------------------------------
CURRENT, OUTDATED, UNKNOWN = '현행', '개정됨, 확인 필요', '현행 여부 미확인'

def fresh(checked):
    try: return (datetime.datetime.now() - datetime.datetime.fromisoformat(checked[:19])).days < CHECK_DAYS
    except (TypeError, ValueError): return False


def status_of(law, status):
    """법령 하나(law_corpus 꼴)의 현행 여부 -> (상태, 확인 날짜). 받은 현행 원문은 '현행'."""
    st = status.get(law.get('key')) or next((s for s in status.values() if norm_name(s.get('name')) == norm_name(law.get('name'))), None)
    if law.get('key') == APPENDIX_KEY: st = status.get('kca')
    if not st or not st.get('current') or not fresh(st.get('checked')): return UNKNOWN, ''
    day = st['checked'][:10]
    return (OUTDATED if (law.get('effective') or '') < st['current'] else CURRENT), day


def pdf_flags(store):
    """올린 PDF 중 현행보다 옛 판인 것 [{key, name, effective, current}]."""
    status = store.read(store.status); out = []
    for key, law in store.read(store.extra).items():
        s, _ = status_of(dict(law, key=key), status)
        cur = (status.get(key) or next((x for x in status.values() if norm_name(x.get('name')) == norm_name(law.get('name'))), {})).get('current', '')
        if s == OUTDATED: out.append({'key': key, 'name': law.get('name'), 'effective': law.get('effective'), 'current': cur})
    return out


# ---- 소비자분쟁해결기준 별표 PDF ---------------------------------------------------------
def pdf_layout_text(raw):
    """쪽마다 칸 위치를 살린 글 [쪽1, 쪽2, …]. pdftotext -layout, 없으면 pypdf. 못 읽으면 ValueError."""
    with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
        f.write(raw); f.flush()
        try:
            r = subprocess.run(['pdftotext', '-layout', '-enc', 'UTF-8', f.name, '-'], capture_output=True, timeout=120)
            if r.returncode != 0: raise ValueError('PDF를 열지 못했어요. 암호가 걸려 있거나 손상된 파일인지 확인해 주세요.')
            return r.stdout.decode('utf-8', 'replace').split('\f')
        except FileNotFoundError: pass
        except subprocess.TimeoutExpired: raise ValueError('PDF가 너무 커서 읽지 못했어요.')
    try:
        import io, pypdf
        return [p.extract_text(extraction_mode='layout') or '' for p in pypdf.PdfReader(io.BytesIO(raw)).pages]
    except ImportError: raise ValueError('서버에 PDF 읽기 프로그램(pdftotext)이 없어요. deploy/update.sh를 다시 돌려 주세요.')
    except Exception: raise ValueError('PDF를 열지 못했어요. 암호가 걸려 있거나 손상된 파일인지 확인해 주세요.')


def is_appendix(pages):
    text = '\n'.join(pages)
    return '분쟁유형' in re.sub(r'\s', '', text) and '해결기준' in text


ITEM = re.compile(r'^(\d{1,3})\.\s*(\S.{0,70})$')          # '3. 가전제품(29개 품목)' 같은 업종·품목 머리
ROW = re.compile(r'^(?:\d{1,2}\)|[①-⑳]|[가-하]\.|\(\d{1,2}\))\s*')   # 분쟁유형 칸 첫머리
APPX = re.compile(r'\[\s*별표\s*([0-9ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+)\s*\]')
SKIP = re.compile(r'^(법제처\s*\d+\s*국가법령정보센터|-\s*\d+\s*-|\d+)$')


def _segments(line):
    """칸 사이 빈칸(2칸 이상)으로 자른 [(시작 위치, 글)]"""
    return [(m.start(), m.group().strip()) for m in re.finditer(r'\S+(?: \S+)*', line)]


def parse_appendix(pages, doc=''):
    """별표 PDF 쪽 글 -> {'appendix': '별표 Ⅱ', 'effective': 'YYYY-MM-DD', 'rows': [{item, dispute, rule, note, page, appendix}]}.
    표 머리(분쟁유형·해결기준·비고) 위치로 칸을 나누고, '1)'·'①'·'가.'로 시작하면 새 줄, 아니면 앞 줄에 이어 붙인다.
    표가 아닌 '3. 가전제품'은 품목 머리로 본다. 못 나누면 ValueError."""
    text = '\n'.join(pages)
    m = re.search(r'\[시행\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\]', text)
    eff = f'{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}' if m else ''
    appx = ''; cols = None; item = ''; rows = []; cur = None
    def flush():
        nonlocal cur
        if cur and cur['dispute'] and cur['rule']:
            rows.append({k: re.sub(r'\s+', ' ', v).strip() if isinstance(v, str) else v for k, v in cur.items()})
        cur = None
    for pno, page in enumerate(pages, 1):
        for line in page.split('\n'):
            if not line.strip() or SKIP.match(line.strip()): continue
            a = APPX.search(line)
            if a: appx = '별표 ' + a[1]
            segs = _segments(line); flat = re.sub(r'\s', '', line)
            if '분쟁유형' in flat and '해결기준' in flat:  # 표 머리: 칸 경계를 새로 잡음
                heads = [(s, w) for s, w in segs]
                pos = {}
                for s, w in heads:
                    ww = re.sub(r'\s', '', w)
                    for name in ('분쟁유형', '해결기준', '비고'):
                        if name in ww and name not in pos: pos[name] = (s, s + len(w))
                if '분쟁유형' in pos and '해결기준' in pos:
                    order = sorted(pos.items(), key=lambda x: x[1][0])
                    cols = [(name, (order[i - 1][1][1] + p[0]) // 2 if i else -1) for i, (name, p) in enumerate(order)]
                continue
            s0, w0 = segs[0]
            if len(segs) == 1 and ITEM.match(w0) and not ROW.match(w0) and (not cols or s0 <= cols[1][1]):
                flush(); item = re.sub(r'\s+', ' ', ITEM.match(w0)[2]).strip(); continue
            if not cols: continue
            if re.match(r'^(대상\s*품목|품목)\s*[:：]', w0) and len(segs) == 1:
                item = (item + ' · ' if item else '') + re.sub(r'^(대상\s*품목|품목)\s*[:：]\s*', '', w0); continue
            got = {}
            for s, w in segs:
                name = [n for n, b in cols if s >= b][-1] if any(s >= b for n, b in cols) else cols[0][0]
                got[name] = (got.get(name, '') + ' ' + w).strip()
            first = got.get('분쟁유형', '')
            if first and ROW.match(first) or (cur is None and first):
                flush()
                cur = {'item': item, 'dispute': ROW.sub('', first) if ROW.match(first) else first, 'rule': got.get('해결기준', ''), 'note': got.get('비고', ''),
                       'page': pno, 'appendix': appx}
            elif cur is not None:
                for name, key in (('분쟁유형', 'dispute'), ('해결기준', 'rule'), ('비고', 'note')):
                    if got.get(name): cur[key] = (cur[key] + ' ' + got[name]).strip()
    flush()
    if not rows: raise ValueError('표에서 분쟁유형·해결기준 줄을 찾지 못했어요. 국가법령정보센터에서 받은 소비자분쟁해결기준 별표 PDF인지 확인해 주세요.')
    return {'appendix': appx or '별표', 'effective': eff, 'rows': rows, 'doc': doc}


def appendix_law(parts):
    """올린 별표들 [{doc, appendix, effective, rows, file, added}] -> law_corpus 꼴 법령 하나 (조문 = 별표 한 줄)."""
    arts = {}; eff = ''
    for p in parts:
        eff = max(eff, p.get('effective') or '')
        tag = re.sub(r'\s', '', p.get('appendix') or '별표')
        for i, r in enumerate(p['rows'], 1):
            text = f"품목: {r['item'] or '(공통)'}\n분쟁유형: {r['dispute']}\n해결기준: {r['rule']}" + (f"\n비고: {r['note']}" if r.get('note') else '')
            arts[f'{tag}-{i}'] = {'title': ' · '.join(x for x in (r['item'], r['dispute'][:40]) if x), 'text': text, 'item': r['item'], 'page': r['page'],
                                  'appendix': p.get('appendix') or '별표', 'doc': p.get('doc') or '소비자분쟁해결기준'}
    return {'key': APPENDIX_KEY, 'name': '소비자분쟁해결기준 별표 (품목별 해결기준)', 'short': '분쟁해결기준', 'kind': '고시 별표', 'no': '', 'effective': eff,
            'promulgated': '', 'source': APPENDIX_SOURCE, 'articles': arts}


def save_appendix(store, parts):
    store.write(store.appendix, {APPENDIX_KEY: appendix_law(parts), '_parts': parts} if parts else {})


def appendix_parts(store):
    data = store.read(store.appendix)
    return data.get('_parts') or [] if isinstance(data, dict) else []


# ---- 임베딩 (질문과 뜻이 가까운 조문 찾기) ---------------------------------------------------
def embed_text(d, label):
    return (label + '\n' + d['text'])[:EMBED_CHARS]


def text_hash(s): return hashlib.sha1((EMBED_MODEL + str(EMBED_DIM) + s).encode()).hexdigest()[:20]


def embed(texts, post, key=None):
    """[글] -> ([[숫자]], 쓴 토큰 수). post(url, headers, body, timeout) -> (상태, JSON). 실패는 RuntimeError (키는 글에 안 넣음)."""
    key = key or os.getenv('OPENAI_API_KEY', '').strip()
    if not key: raise RuntimeError('OpenAI API 키가 없어요')
    st, res = post('https://api.openai.com/v1/embeddings', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                   {'model': EMBED_MODEL, 'input': texts, 'dimensions': EMBED_DIM}, 60)
    if st != 200: raise RuntimeError(f'임베딩 응답 오류 ({st}) ' + str(((res or {}).get('error') or {}).get('message', ''))[:120].replace(key, '***'))
    data = sorted((res.get('data') or []), key=lambda x: x.get('index', 0))
    if len(data) != len(texts): raise RuntimeError('임베딩 응답 수가 달라요')
    return [unit(x['embedding']) for x in data], int((res.get('usage') or {}).get('total_tokens') or 0)


def unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class Embeddings:
    """조문 임베딩 파일. 글 해시로 찾아서, 모음이 바뀌면 바뀐 조문만 다시 만든다."""
    def __init__(self, store):
        self.store = store; self._sig = None; self.index = {}; self.vec = array.array('f')

    def load(self):
        try: sig = (self.store.emb_index.stat().st_mtime_ns, self.store.emb_vec.stat().st_mtime_ns)
        except OSError: self.index, self.vec, self._sig = {}, array.array('f'), None; return self
        if sig == self._sig: return self
        idx = self.store.read(self.store.emb_index); vec = array.array('f')
        try: vec.frombytes(self.store.emb_vec.read_bytes())
        except OSError: idx = {}
        if idx.get('dim') != EMBED_DIM or idx.get('model') != EMBED_MODEL or len(vec) != len(idx.get('rows', {})) * EMBED_DIM: idx, vec = {}, array.array('f')
        self.index, self.vec, self._sig = idx.get('rows', {}), vec, sig
        return self

    def get(self, h):
        i = self.index.get(h)
        return None if i is None else self.vec[i * EMBED_DIM:(i + 1) * EMBED_DIM]

    def missing(self, docs):
        self.load(); return [d for d in docs if d['hash'] not in self.index]

    def build(self, docs, post, limit=None, key=None):
        """docs: [{ref, hash, text}] -> (새로 만든 수, 토큰 수). 지금 모음에 없는 조문 줄은 버린다."""
        self.load(); have = {d['hash']: self.get(d['hash']) for d in docs if d['hash'] in self.index}
        todo = [d for d in docs if d['hash'] not in have]
        if limit is not None: todo = todo[:limit]
        tokens = 0
        for i in range(0, len(todo), EMBED_BATCH):
            part = todo[i:i + EMBED_BATCH]
            vecs, n = embed([d['text'] for d in part], post, key); tokens += n
            for d, v in zip(part, vecs): have[d['hash']] = array.array('f', v)
        rows = {}; vec = array.array('f')
        for h, v in have.items():
            if v is None: continue
            rows[h] = len(rows); vec.extend(v)
        tmp = self.store.emb_vec.with_suffix('.tmp'); tmp.write_bytes(vec.tobytes()); os.replace(tmp, self.store.emb_vec)
        self.store.write(self.store.emb_index, {'model': EMBED_MODEL, 'dim': EMBED_DIM, 'rows': rows, 'built': now()})
        self._sig = None; self.load()
        return len(todo), tokens

    def search(self, qv, docs, limit=40):
        """[(코사인, doc)] 높은 순. 임베딩이 없는 조문은 건너뜀."""
        self.load(); out = []
        for d in docs:
            v = self.get(d['hash'])
            if v is None: continue
            out.append((sum(a * b for a, b in zip(qv, v)), d))
        out.sort(key=lambda x: -x[0])
        return out[:limit]


def corpus_docs(rc):
    """임베딩할 조문 [{ref, key, hash, text}] (모음에서 '삭제' 조문은 이미 빠져 있음)."""
    db = rc._load(); out = []
    for d in db['docs']:
        s = embed_text(d, rc.label(d['ref']))
        out.append({'ref': d['ref'], 'key': d['key'], 'hash': text_hash(s), 'text': s})
    return out


# ---- 명령줄 (deploy/law-sync.sh) -------------------------------------------------------
def post_json(url, headers, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode(), method='POST', headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode() or '{}')
        except Exception: return e.code, {}


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    store = default_store(); code = 0
    if '--embed-only' not in argv:
        print('[법령 받기] 국가법령정보 Open API')
        if not oc(): print('  LAW_OC가 없어 건너뛰어요. sudo bash deploy/set-law.sh 로 인증키를 넣어 주세요.'); code = 1
        else:
            rows = sync(store)
            if any(not r['ok'] for r in rows): code = 1
        flags = pdf_flags(store)
        for f in flags: print(f"  주의: 올린 PDF '{f['name']}'(시행 {f['effective']})가 현행({f['current']})보다 옛 판이에요. 개정됨, 확인 필요")
    print('[임베딩] 바뀐 조문만 다시 만들어요')
    if not os.getenv('OPENAI_API_KEY', '').strip(): print('  OpenAI 키가 없어 건너뛰어요.'); return code
    rc = corpus_v2(store); docs = corpus_docs(rc); emb = Embeddings(store)
    try:
        n, tok = emb.build(docs, post_json)
        print(f'  조문 {len(docs):,}개 중 새로 {n:,}개 (토큰 {tok:,})')
    except RuntimeError as e:
        print('  실패: ' + str(e)[:200]); code = 1
    return code


if __name__ == '__main__':
    sys.exit(main())
