"""소비자 상담 공공데이터 받아서 기획기사 재료로 정리 (운영자 2026-11-15: 넥스트 카트 'AI 쇼핑 시대' 기획).
서버에 있는 공공데이터포털 인증키(FTC_API_KEY 또는 DATA_GO_KR_KEY)로 승인받은 상담 API 3개를 부른다.
포털 안내 페이지의 명세(swagger)에서 주소·요청 항목·응답 항목을 읽고, 날짜 항목이 있으면 최근 3년을 달마다 나눠 받는다.

실행(서버):
  sudo systemd-run --wait --pipe -q -p User=soboru -p EnvironmentFile=/etc/soboru.env \
       -p WorkingDirectory=/opt/soboru/app /opt/soboru/venv/bin/python tools/consumer_data_pull.py
결과: /tmp/soboru_data/ 폴더와 /tmp/soboru_data.zip
  spec.txt          API 주소·요청 항목·응답 항목·받은 건수 (기사 출처용)
  <api>.jsonl       받은 원자료 (한 줄에 한 건)
  summary.json      월별 건수, 항목별 상위 값, 키워드별 연도 추이, 키워드 사례
인증키는 어떤 파일에도 쓰지 않는다.
"""
import calendar, collections, datetime, json, os, re, shutil, sys, time, urllib.parse, urllib.request
from pathlib import Path

NAMES = {
    'ccn1372': '공정거래위원회_1372 소비자상담',
    'online': '공정거래위원회_소비자 온라인 상거래 소비자상담 내역',
    'kca_answer': '한국소비자원_소비자상담 표준답변',
}
KEYWORDS = ['AI', '인공지능', '추천', '챗봇', '알고리즘', '라이브커머스', '라이브 방송', '해외직구', '구매대행', '알리', '테무', '구독', '정기결제', '자동결제',
            '청약철회', '배송', '계약해지', '허위', '과장광고', '다크패턴', '오픈마켓', 'SNS', '인스타그램']
OUT = Path('/tmp/soboru_data')
UA = {'User-Agent': 'Mozilla/5.0 (soboru data pull)'}
KEY = (os.getenv('FTC_API_KEY') or os.getenv('DATA_GO_KR_KEY') or '').strip()
MAX_CALLS = int(os.getenv('PULL_MAX_CALLS', '1500'))  # 개발 계정 하루 호출 한도 안에서
ROWS = 1000
calls = 0
log_lines = []


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
        except Exception as e:
            if i == 2: raise
            time.sleep(2 * (i + 1))


def find_id(name):
    html = get('https://www.data.go.kr/tcs/dss/selectDataSetList.do?' + urllib.parse.urlencode({'dType': 'API', 'keyword': name}))
    ids = re.findall(r'/data/(\d+)/openapi\.do', html)
    return ids[0] if ids else ''


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
    if start:
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
                info['errors'].append(f'{w} p{page}: {str(e)[:150]}'); break
            info['calls'] += 1
            for r in got:
                if w: r.setdefault('_window', w[0])
            rows += got
            if page == 1 and total: info['total_reported'] += total
            if not got or len(got) < ROWS or (total and page * ROWS >= total): break
            page += 1
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


def main():
    if not KEY: say('인증키가 없어요 (FTC_API_KEY 또는 DATA_GO_KR_KEY)'); sys.exit(1)
    shutil.rmtree(OUT, ignore_errors=True); OUT.mkdir(parents=True)
    spec_lines, summary = [], {'made': datetime.datetime.now().isoformat(timespec='minutes'), 'apis': {}}
    for key, name in NAMES.items():
        say('\n■', name)
        spec_lines.append(f'■ {name}')
        try:
            pid = find_id(name)
            if not pid: say('  포털에서 못 찾음'); spec_lines.append('  포털에서 못 찾음'); continue
            src = f'https://www.data.go.kr/data/{pid}/openapi.do'
            spec = swagger(get(src))
            spec_lines.append(f'  출처 {src}')
            if not spec: say('  명세 없음'); spec_lines.append('  명세(swagger) 없음'); continue
            base, ops = ops_of(spec)
            spec_lines.append(f'  주소 {base}')
            all_rows = []
            for op in ops:
                say(f'  - {op["path"]} {op["summary"]}')
                spec_lines.append(f'  - {op["path"]} {op["summary"]}')
                spec_lines.append('    요청: ' + ', '.join(f'{n}{"*" if req else ""}({d})' for n, req, d in op['params']))
                rows, info = fetch(base, op, key)
                for r in rows: r['_op'] = op['path']
                all_rows += rows
                fields = sorted({k for r in rows for k in r if not k.startswith('_')})
                spec_lines.append(f'    응답 항목: {", ".join(fields) or "(받은 건 없음)"}')
                spec_lines.append(f'    받은 건수 {len(rows)} / API가 알려 준 전체 {info["total_reported"]} / 호출 {info["calls"]}번')
                for e in info['errors'][:5]: spec_lines.append(f'    오류: {e}')
                say(f'    {len(rows)}건 받음' + (f', 오류 {len(info["errors"])}개' if info['errors'] else ''))
            with open(OUT / f'{key}.jsonl', 'w', encoding='utf-8') as f:
                for r in all_rows: f.write(json.dumps(r, ensure_ascii=False) + '\n')
            summary['apis'][key] = dict(name=name, source=src, **summarize(all_rows))
        except Exception as e:
            say('  오류', str(e)[:200]); spec_lines.append(f'  오류 {str(e)[:200]}')
    clean = lambda t: t.replace(KEY, 'KEY')
    (OUT / 'spec.txt').write_text(clean('\n'.join(spec_lines)), encoding='utf-8')
    (OUT / 'summary.json').write_text(clean(json.dumps(summary, ensure_ascii=False, indent=1)), encoding='utf-8')
    (OUT / 'log.txt').write_text(clean('\n'.join(log_lines)), encoding='utf-8')
    for p in OUT.glob('*.jsonl'): p.write_text(clean(p.read_text(encoding='utf-8')), encoding='utf-8')
    shutil.make_archive('/tmp/soboru_data', 'zip', OUT)
    os.chmod('/tmp/soboru_data.zip', 0o644)
    say(f'\n다 됐어요. /tmp/soboru_data.zip (호출 {calls}번)')


if __name__ == '__main__':
    main()
