"""공공데이터포털 API 명세 확인 (운영자 요청 2026-10-30: 승인받은 공정위·식약처·소비자원 API를 소보루에서 쓰기).
포털 문서는 주소·항목 이름이 그림으로만 보여서, 서버에서 각 API 안내 페이지의 명세(swagger)를 읽어 한 번에 정리한다.
실행(서버): sudo systemd-run --wait --pipe -q -p User=soboru -p EnvironmentFile=/etc/soboru.env \
              -p WorkingDirectory=/opt/soboru/app /opt/soboru/venv/bin/python tools/public_data_probe.py
결과는 화면과 /tmp/public_data_probe.txt 에 남는다. 인증키는 'KEY'로 가려서 찍는다.
"""
import json, os, re, sys, urllib.parse, urllib.request

NAMES = [
    '공정거래위원회_통신판매사업자 등록현황 제공 서비스',
    '공정거래위원회_통신판매사업자 등록상세 제공 서비스',
    '공정거래위원회_가맹정보 주요 업종별 가맹점수, 개폐점률 현황 제공 서비스',
    '공정거래위원회_가맹정보_브랜드별 브랜드 개요 통계 제공 서비스',
    '공정거래위원회_가맹정보_가맹본부 등록 목록 정보 제공 서비스',
    '공정거래위원회_방문판매사업자 등록현황',
    '공정거래위원회_1372 소비자상담',
    '공정거래위원회_소비자 온라인 상거래 소비자상담 내역',
    '한국소비자원_소비자상담 표준답변',
    '식품의약품안전처_의약품 회수·판매중지 정보',
    '식품의약품안전처_수입식품 회수판매중지 제품 정보',
    '식품의약품안전처_검사부적합',
    '식품의약품안전처_건강기능식품정보',
    '식품의약품안전처_식품영양성분DB정보',
    '식품의약품안전처_의약품 제품 허가정보',
    '식품의약품안전처_의약품안전사용서비스(DUR)품목정보',
    '식품의약품안전처_의약품 낱알식별 정보',
    '식품의약품안전처_안전상비의약품 정보',
    '식품의약품안전처_의약품공급부족 정보',
    '식품의약품안전처_의약품 행정처분 정보',
    '식품의약품안전처_식품제조 이력추적제품 생산정보',
]
UA = {'User-Agent': 'Mozilla/5.0 (soboru public-data probe)'}
OUT = '/tmp/public_data_probe.txt'
KEY = (os.getenv('FTC_API_KEY') or os.getenv('DATA_GO_KR_KEY') or '').strip()
lines = []


def say(*a):
    s = ' '.join(str(x) for x in a).replace(KEY, 'KEY') if KEY else ' '.join(str(x) for x in a)
    print(s); lines.append(s)


def get(url, timeout=15):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')


def find_id(name):
    q = urllib.parse.urlencode({'dType': 'API', 'keyword': name})
    html = get('https://www.data.go.kr/tcs/dss/selectDataSetList.do?' + q)
    ids = re.findall(r'/data/(\d+)/openapi\.do', html)
    return ids[0] if ids else ''


def swagger(html):
    for pat in (r'swaggerJson\s*=\s*`(.*?)`', r"swaggerJson\s*=\s*'(.*?)'\s*;", r'swaggerJson\s*=\s*"(.*?)"\s*;'):
        m = re.search(pat, html, re.S)
        if m and m.group(1).strip():
            try: return json.loads(m.group(1))
            except Exception:
                try: return json.loads(m.group(1).encode().decode('unicode_escape'))
                except Exception: pass
    return None


def props(spec, schema, depth=0):
    if not isinstance(schema, dict) or depth > 6: return []
    ref = schema.get('$ref')
    if ref:
        node = spec
        for part in ref.lstrip('#/').split('/'): node = node.get(part, {}) if isinstance(node, dict) else {}
        return props(spec, node, depth + 1)
    out = []
    for k, v in (schema.get('properties') or {}).items():
        sub = props(spec, v, depth + 1) or props(spec, (v or {}).get('items') or {}, depth + 1)
        out += sub if sub and k in ('response', 'body', 'items', 'item', 'header') else [k] + sub
    return out + props(spec, schema.get('items') or {}, depth + 1)


def describe(spec):
    base = ''
    if spec.get('host'): base = 'https://' + spec['host'] + (spec.get('basePath') or '')
    elif spec.get('servers'): base = spec['servers'][0].get('url', '')
    ops = []
    for path, methods in (spec.get('paths') or {}).items():
        for m, op in (methods or {}).items():
            if not isinstance(op, dict): continue
            params = [p.get('name') for p in op.get('parameters') or [] if isinstance(p, dict) and p.get('name')]
            resp = (op.get('responses') or {}).get('200') or {}
            schema = resp.get('schema') or ((resp.get('content') or {}).get('application/json') or {}).get('schema') or {}
            fields = [f for f in dict.fromkeys(props(spec, schema)) if f not in ('resultCode', 'resultMsg', 'numOfRows', 'pageNo', 'totalCount')]
            ops.append((path, op.get('summary') or '', params, fields))
    return base, ops


def try_call(base, path, params):
    q = {'serviceKey': KEY, 'pageNo': 1, 'numOfRows': 1}
    if 'type' in params: q['type'] = 'json'
    if 'resultType' in params or not params: q['resultType'] = 'json'
    try: return get(base + path + '?' + urllib.parse.urlencode(q), timeout=10)[:400].replace('\n', ' ')
    except Exception as e: return f'오류 {e}'


def main():
    names = sys.argv[1:] or NAMES
    say(f'인증키: {"있음" if KEY else "없음 (FTC_API_KEY)"}')
    for name in names:
        say('\n■', name)
        try:
            pid = find_id(name)
            if not pid: say('  포털에서 못 찾음'); continue
            html = get(f'https://www.data.go.kr/data/{pid}/openapi.do')
            say(f'  id {pid}')
            spec = swagger(html)
            if not spec:
                urls = sorted(set(re.findall(r'https?://apis\.data\.go\.kr/[\w/]+', html)))
                say('  명세 없음. 페이지 속 주소:', ', '.join(urls) or '없음'); continue
            base, ops = describe(spec)
            say('  주소', base)
            for path, summary, params, fields in ops:
                say(f'  - {path} {summary}')
                say('    요청:', ', '.join(params))
                say('    응답:', ', '.join(fields[:40]))
            if KEY and ops: say('    시험:', try_call(base, ops[0][0], ops[0][2]))
        except Exception as e:
            say('  오류', e)
    try:
        with open(OUT, 'w', encoding='utf-8') as f: f.write('\n'.join(lines))
        print(f'\n결과를 {OUT} 에도 남겼어요.')
    except Exception: pass


if __name__ == '__main__':
    main()
