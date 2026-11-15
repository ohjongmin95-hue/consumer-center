"""공공데이터를 서버가 알아서 받아 두고 관리자·아침 데스크에서 쓰기 (운영자 2026-11-15: "다운로드 말고 서버에서 받아서 쓰게 체계를").
서버 공공데이터포털 키(FTC_API_KEY 또는 DATA_GO_KR_KEY)로 승인된 API를 매일 아침(soboru-publicdata.timer, 8시 20분) 받아
DATA_DIR/latest.json(요약·요청 항목·오류)과 <api>.jsonl(원자료)로 둔다. 키는 어떤 파일에도 쓰지 않는다.
- 관리자 > 콘텐츠 > 공공데이터: 받은 결과·오류·기사 재료, '지금 받기'
- 아침 데스크: 지난번에 없던 의약품 회수·부적합 식품을 메일 위에 알림
포털 안내 페이지 명세(swagger)로 주소·요청 항목을 읽고, 날짜 범위면 최근 36개월을 달마다, 연도 항목이면 최근 10년을 해마다 받는다.
직접 돌리기: python -m public_data  (결과를 화면에 찍음)
"""
import calendar, collections, datetime, hashlib, json, os, re, sys, threading, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

# (포털 id, 이름, 새 건 알림) — id는 2026-11-15 서버 키 --scan 결과에서 확인
APIS = {
    'ccn1372': ('15127089', '공정거래위원회_1372 소비자상담 상술유형별 접수통계 서비스', False),
    'franchise': ('15157660', '공정거래위원회_가맹정보 주요 업종별 가맹점수, 개폐점률 현황 제공 서비스', False),
    'drug_recall': ('15059114', '식품의약품안전처_의약품 회수·판매중지 정보', True),
    'food_bad': ('15056516', '식품의약품안전처_검사 부적합 식품정보', True),
}
KEYWORDS = ['AI', '인공지능', '추천', '챗봇', '알고리즘', '라이브커머스', '라이브 방송', '해외직구', '구매대행', '알리', '테무', '구독', '정기결제', '자동결제',
            '청약철회', '배송', '계약해지', '허위', '과장광고', '다크패턴', '오픈마켓', 'SNS', '인스타그램']
DATA_DIR = Path(os.getenv('PUBLIC_DATA_DIR') or (Path(os.getenv('DATABASE_PATH', str(Path(__file__).resolve().parent / 'cases.sqlite3'))).parent / 'public_data'))
UA = {'User-Agent': 'Mozilla/5.0 (soboru data pull)'}
KEY = (os.getenv('FTC_API_KEY') or os.getenv('DATA_GO_KR_KEY') or '').strip()
MAX_CALLS = int(os.getenv('PULL_MAX_CALLS', '600'))  # 개발 계정 하루 호출 한도(보통 1,000) 안에서
MAX_PAGES = 30  # 목록형(회수·부적합)은 최신 3만 건까지
ROWS = 1000
calls = 0
log_lines = []
_lock = threading.Lock()


def say(*a):
    s = ' '.join(str(x) for x in a)
    if KEY: s = s.replace(KEY, 'KEY').replace(urllib.parse.quote(KEY, safe=''), 'KEY')
    print(s, flush=True); log_lines.append(s)


def get(url, timeout=30):
    global calls
    calls += 1
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:  # 운영자 2026-11-15: 오류 내용이 안 보여서 원인을 몰랐음 -> 응답 본문까지 올림
            try: body = e.read().decode('utf-8', 'replace')[:300]
            except Exception: body = ''
            if e.code < 500 or i == 2: raise RuntimeError(f'HTTP {e.code} {re.sub(chr(10), " ", body)}')
            time.sleep(2 * (i + 1))
        except Exception as e:
            if i == 2: raise
            time.sleep(2 * (i + 1))


def swagger(html):
    for pat in (r'swaggerJson\s*=\s*`(.*?)`', r"swaggerJson\s*=\s*'(.*?)'\s*;", r'swaggerJson\s*=\s*"(.*?)"\s*;'):
        m = re.search(pat, html, re.S)
        if m and m.group(1).strip():
            for t in (m.group(1), m.group(1).encode().decode('unicode_escape', 'ignore')):
                try: return json.loads(t)
                except Exception: pass
    return None


def ops_of(spec):
    base = 'https://' + spec['host'] + (spec.get('basePath') or '') if spec.get('host') else ((spec.get('servers') or [{}])[0].get('url', ''))
    out = []
    for path, methods in (spec.get('paths') or {}).items():
        for m, op in (methods or {}).items():
            if isinstance(op, dict):
                ps = [p for p in op.get('parameters') or [] if isinstance(p, dict) and p.get('name')]
                out.append({'path': path, 'summary': op.get('summary') or '', 'params': [(p['name'], bool(p.get('required')), p.get('description') or '') for p in ps]})
    return base.replace('http://', 'https://'), out


def items_of(text):
    """JSON이나 XML 응답에서 (건 목록, 전체 건수)"""
    text = text.strip()
    if text.startswith('{') or text.startswith('['):
        d = json.loads(text)
        hdr = json.dumps(d, ensure_ascii=False)[:600]
        m = re.search(r'"(?:resultCode|returnReasonCode|code)"\s*:\s*"?([A-Za-z0-9-]+)"?.{0,80}?"(?:resultMsg|returnAuthMsg|message)"\s*:\s*"([^"]*)"', hdr)
        if m and m.group(1) not in ('00', '0', '000', 'INFO-000', '200'): raise RuntimeError(f'API 오류 {m.group(1)} {m.group(2)}')
        total = None
        def walk(o):
            nonlocal total
            if isinstance(o, dict):
                for k, v in o.items():
                    if k.lower() == 'totalcount':
                        try: total = int(v)
                        except Exception: pass
                for k in ('items', 'item', 'data', 'list', 'row'):
                    v = o.get(k)
                    if isinstance(v, list) and v and isinstance(v[0], dict): return v
                    if isinstance(v, dict):
                        r = walk(v)
                        if r is not None: return r
                for v in o.values():
                    r = walk(v)
                    if r is not None: return r
            elif isinstance(o, list) and o and isinstance(o[0], dict) and not any(isinstance(x, (dict, list)) for x in o[0].values()):
                return o
            return None
        rows = walk(d) or []
        return rows, total
    import xml.etree.ElementTree as ET
    root = ET.fromstring(text)
    code = root.findtext('.//resultCode') or root.findtext('.//returnReasonCode')
    msg = root.findtext('.//resultMsg') or root.findtext('.//returnAuthMsg')
    if code and code not in ('00', '0', '000', 'INFO-000') and not root.findall('.//item'): raise RuntimeError(f'API 오류 {code} {msg}')
    rows = [{c.tag: (c.text or '').strip() for c in it} for it in root.findall('.//item')]
    t = root.findtext('.//totalCount')
    return rows, int(t) if t and t.isdigit() else None


DATE_P = re.compile(r'(bgng|start|strt|from|st|beg).*?(de|dt|date|ymd|ym)|(de|dt|date|ymd|ym).*?(bgng|start|strt|from)', re.I)
DATE_E = re.compile(r'(end|to|fns|ed).*?(de|dt|date|ymd|ym)|(de|dt|date|ymd|ym).*?(end|to|fns)', re.I)


def months(n=36):
    d = datetime.date.today().replace(day=1)
    out = []
    for _ in range(n):
        d = (d - datetime.timedelta(days=1)).replace(day=1)
        out.append(d)
    return sorted(out)


def fetch(base, op, label):
    names = [p[0] for p in op['params']]
    q0 = {'serviceKey': KEY, 'numOfRows': ROWS, 'pageNo': 1}
    for k in ('type', 'resultType', '_type', 'dataType', 'returnType'):
        if k in names: q0[k] = 'json'
    start = next((n for n in names if DATE_P.search(n)), None)
    end = next((n for n in names if n != start and DATE_E.search(n)), None)
    windows = [None]
    fixed = {}
    # 필수 항목 중 날짜 범위가 아닌 것: 연도면 최근 10년을 한 해씩, 예시 값이 있으면 그 값 (1372 통계·가맹 개폐점률은 연도를 꼭 받음)
    year = None
    for n, req, d in op['params']:
        if n in q0 or n in ('serviceKey', 'pageNo', 'numOfRows') or n in (start, end): continue
        if re.search(r'(yr|year|yy|baseyear|연도|년도|기준년)', n + ' ' + d, re.I) and not re.search(r'(ym|월)', n, re.I): year = year or n; continue
        if req:
            m = re.search(r'(?:예|ex|e\.g)[^0-9A-Za-z가-힣]*([0-9A-Za-z가-힣]+)', d, re.I) or re.search(r'\b(\d{2,8})\b', d)
            if m: fixed[n] = m.group(1)
    if fixed: say(f'    필수 항목 예시 값으로 채움: {fixed}')
    q0.update(fixed)
    if year and not start:
        this = datetime.date.today().year
        windows = [(str(y), str(y)) for y in range(this - 10, this + 1)]; start = year
        say(f'    연도 항목 {year} 로 {this - 10}~{this}년을 한 해씩 받아요')
    if start and windows == [None]:
        fmt = '%Y%m' if re.search(r'ym$', start, re.I) and not re.search(r'ymd$', start, re.I) else '%Y%m%d'
        windows = [(m.strftime(fmt), m.replace(day=calendar.monthrange(m.year, m.month)[1]).strftime(fmt)) for m in months()]
        say(f'    날짜 항목 {start}~{end or "-"} 로 최근 36개월을 달마다 받아요')
    rows, info = [], {'calls': 0, 'total_reported': 0, 'errors': []}
    for w in windows:
        page = 1
        while calls < MAX_CALLS:
            q = dict(q0, pageNo=page)
            if w: q[start] = w[0]; q.update({end: w[1]} if end else {})
            try:
                got, total = items_of(get(base + op['path'] + '?' + urllib.parse.urlencode(q)))
            except Exception as e:
                msg = f'{w} p{page}: {str(e)[:200]}'
                if len(info['errors']) < 3: say('    오류', msg)
                info['errors'].append(msg); break
            info['calls'] += 1
            for r in got:
                if w: r.setdefault('_window', w[0])
            rows += got
            if page == 1 and total: info['total_reported'] += total
            if not got or len(got) < ROWS or (total and page * ROWS >= total): break
            page += 1
            if page > MAX_PAGES: break
    if calls >= MAX_CALLS: info['errors'].append('호출 한도에 닿아 멈춤 (PULL_MAX_CALLS)')
    return rows, info


def text_of(r): return ' '.join(str(v) for v in r.values() if isinstance(v, str))


def date_of(r):
    for k, v in r.items():
        if isinstance(v, str) and re.fullmatch(r'(19|20)\d{2}[-./]?\d{2}([-./]?\d{2})?.*', v.strip()) and re.search(r'(de|dt|date|ymd|ym|일자|날짜|월)', k, re.I):
            d = re.sub(r'\D', '', v)[:6]
            return d[:4] + '-' + d[4:6]
    w = r.get('_window')
    return (w[:4] + '-' + w[4:6]) if w else ''


def summarize(rows):
    s = {'rows': len(rows), 'by_month': {}, 'top_values': {}, 'keywords': {}, 'examples': {}}
    s['by_month'] = dict(sorted(collections.Counter(date_of(r) for r in rows if date_of(r)).items()))
    fields = collections.Counter(k for r in rows for k in r)
    for k in fields:
        vals = [str(r.get(k, '')).strip() for r in rows if str(r.get(k, '')).strip()]
        distinct = set(vals)
        if vals and 1 < len(distinct) <= 300 and max(len(v) for v in distinct) <= 60:  # 분류처럼 보이는 항목만
            s['top_values'][k] = collections.Counter(vals).most_common(30)
    for kw in KEYWORDS:
        pat = re.compile(r'(?<![A-Za-z])AI(?![A-Za-z])') if kw == 'AI' else re.compile(re.escape(kw), re.I)  # email 같은 영어 단어 속 ai는 빼고
        hit = [r for r in rows if pat.search(text_of(r))]
        if not hit: continue
        s['keywords'][kw] = {'count': len(hit), 'by_year': dict(sorted(collections.Counter(date_of(r)[:4] for r in hit if date_of(r)).items()))}
        s['examples'][kw] = [{k: (v[:300] if isinstance(v, str) else v) for k, v in r.items()} for r in hit[:20]]
    return s


def row_id(r):
    return hashlib.sha1(json.dumps({k: v for k, v in r.items() if not k.startswith('_')}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def title_of(r):
    """회수·부적합 한 건을 한 줄로 (제품명 · 업체 · 사유)"""
    pick = lambda *ks: next((str(r[k]).strip() for k in r for kk in ks if kk.lower() in k.lower() and str(r[k]).strip()), '')
    name = pick('PRDT_NM', 'PRDLST_NM', 'ITEM_NAME', 'PRDUCT', 'prduct', 'itemName', 'PRDT', '제품')
    who = pick('ENTRPS', 'BSSH_NM', 'ENTP_NAME', 'MNFTR', 'entrps', 'bssh', '업체')
    why = pick('RTRVL_RESN', 'TEST_ITMNM', 'RECALL_REASON', 'rtrvl', 'resn', 'REASON', '사유')
    return ' · '.join(x[:60] for x in (name, who, why) if x) or text_of(r)[:120]


def load():
    try: return json.loads((DATA_DIR / 'latest.json').read_text(encoding='utf-8'))
    except Exception: return {}


def run():
    """모든 API를 받아 DATA_DIR에 저장. 이미 돌고 있으면 바로 돌아감."""
    global calls
    if not _lock.acquire(blocking=False): return load()
    try:
        calls = 0; log_lines.clear()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        prev = load()
        out = {'started': datetime.datetime.now().isoformat(timespec='minutes'), 'key': bool(KEY), 'apis': {}}
        (DATA_DIR / 'running').write_text(out['started'])
        if not KEY: say('인증키가 없어요 (FTC_API_KEY 또는 DATA_GO_KR_KEY)')
        for key, (pid, name, alert) in APIS.items():
            say('\n■', name)
            src = f'https://www.data.go.kr/data/{pid}/openapi.do'
            a = {'name': name, 'source': src, 'ops': [], 'rows': 0, 'errors': [], 'new': []}
            out['apis'][key] = a
            if not KEY: continue
            try:
                spec = swagger(get(src))
                if not spec: a['errors'].append('포털 명세(swagger)를 못 읽었어요'); say('  명세 없음'); continue
                base, ops = ops_of(spec)
                a['base'] = base
                all_rows = []
                for op in ops:
                    say(f'  - {op["path"]} {op["summary"]}')
                    say('    요청 항목: ' + ', '.join(f'{n}{"*" if req else ""}({d[:40]})' for n, req, d in op['params']))
                    rows, info = fetch(base, op, key)
                    for r in rows: r['_op'] = op['path']
                    all_rows += rows
                    a['ops'].append({'path': op['path'], 'summary': op['summary'], 'params': op['params'], 'rows': len(rows), 'calls': info['calls'],
                                     'total': info['total_reported'], 'errors': info['errors'][:5], 'fields': sorted({k for r in rows for k in r if not k.startswith('_')})})
                    a['errors'] += [f'{op["path"]} {e}' for e in info['errors'][:3]]
                    say(f'    {len(rows)}건 받음' + (f', 오류 {len(info["errors"])}개' if info['errors'] else ''))
                a['rows'] = len(all_rows)
                if all_rows:
                    with open(DATA_DIR / f'{key}.jsonl', 'w', encoding='utf-8') as f:
                        for r in all_rows: f.write(json.dumps(r, ensure_ascii=False) + '\n')
                    a['summary'] = summarize(all_rows)
                    old = set((prev.get('apis', {}).get(key) or {}).get('ids') or [])
                    ids = [row_id(r) for r in all_rows]
                    a['ids'] = ids[:5000]
                    if alert and old:  # 처음 받을 때는 전부 '새 것'이라 알리지 않음
                        a['new'] = [title_of(r) for r, i in zip(all_rows, ids) if i not in old][:30]
                    if a['new']: a['new_at'] = out['started']
                elif (prev.get('apis', {}).get(key) or {}).get('ids'):  # 이번에 못 받았으면 지난번 것을 남겨 둠
                    a['ids'] = prev['apis'][key]['ids']; a['summary'] = prev['apis'][key].get('summary'); a['stale'] = True
            except Exception as e:
                a['errors'].append(str(e)[:300]); say('  오류', str(e)[:300])
        out['finished'] = datetime.datetime.now().isoformat(timespec='minutes'); out['calls'] = calls
        out['log'] = log_lines[-200:]
        txt = json.dumps(out, ensure_ascii=False, indent=1)
        if KEY: txt = txt.replace(KEY, 'KEY')
        tmp = DATA_DIR / 'latest.json.tmp'; tmp.write_text(txt, encoding='utf-8'); tmp.replace(DATA_DIR / 'latest.json')
        say(f'\n다 됐어요. 호출 {calls}번 · {DATA_DIR}/latest.json')
        return out
    finally:
        try: (DATA_DIR / 'running').unlink()
        except Exception: pass
        _lock.release()


def fresh_alerts(hours=30):
    """아침 데스크용: 최근 받기에서 새로 나온 회수·부적합 (이름, [줄])"""
    d = load(); out = []
    try: when = datetime.datetime.fromisoformat(d.get('started', ''))
    except Exception: return out
    if datetime.datetime.now() - when > datetime.timedelta(hours=hours): return out
    for key, a in (d.get('apis') or {}).items():
        if a.get('new'): out.append((a['name'].split('_', 1)[-1], a['new'][:10], a['source']))
    return out


def install(S):
    from flask import render_template, request, redirect, url_for, flash
    app = S.app

    @app.route('/admin/public-data', methods=['GET', 'POST'])
    @S.admin_only
    def admin_public_data():
        if request.method == 'POST':
            if (DATA_DIR / 'running').exists(): flash('지금 받는 중이에요. 몇 분 뒤 새로 고쳐 보세요.')
            else:
                threading.Thread(target=run, daemon=True).start(); flash('받기 시작했어요. 몇 분 걸려요. 잠시 뒤 새로 고쳐 보세요.')
            return redirect(url_for('admin_public_data'))
        d = load()
        return render_template('admin_public_data.html', d=d, running=(DATA_DIR / 'running').exists(), has_key=bool(KEY), apis=APIS)


if __name__ == '__main__':
    run()
