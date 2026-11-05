"""데일리 숏폼 소재 조사: 유튜브 쇼츠에서 반응 터진 경제·소비자·브랜드·이슈·사회 영상을 모음.

운영자 2026-11-05: '매일 아침 AI가 반응 터진 콘텐츠만 한 페이지로 모아 줘' — 예약 작업이 매일 이 스크립트를 돌림.
- 인스타·스레드는 로그인 없이는 조회수가 안 보여서, 같은 영상이 함께 올라가는 유튜브 쇼츠로 찾음.
- 검색 필터: 이번 주 업로드 + 4분 미만(sp=EgQIAxgB). 하루 평균 조회수(조회수 ÷ 올린 지 며칠)로 줄 세움.

쓰는 법: python3 tools/daily_shorts.py out.json [--min 30000]
"""
import json
import re
import subprocess
import sys
import urllib.parse

QUERIES = {
    '경제': ['물가', '월급 현실', '부동산', '환율', '금리', '재테크', '자영업 현실', '연봉'],
    '소비자': ['소비자 피해', '환불', '가격 꼼수', '다이소', '코스트코', '호구', '사기 수법', '할인 꿀팁'],
    '브랜드': ['브랜드 망한 이유', '기업 전략', '편의점', '쿠팡', '배민', '프랜차이즈', '마케팅 비밀'],
    '이슈': ['논란', '불매', '갑질', '리콜', '과징금', '공정위'],
    '사회': ['MZ 현실', '20대 현실', '저출산', '노인 빈곤', '취업 현실', '직장인 현실'],
}
SP_THIS_WEEK_SHORT = 'EgQIAxgB'


def views(t):
    m = re.search(r'조회수\s*([\d.,]+)\s*(천|만|억)?\s*회', t or '')
    if not m:
        return 0
    return int(float(m.group(1).replace(',', '')) * {None: 1, '천': 1e3, '만': 1e4, '억': 1e8}[m.group(2)])


def days(t):
    m = re.search(r'(\d+)\s*(초|분|시간|일|주|개월|년)', t or '')
    if not m:
        return 7.0
    n = int(m.group(1))
    return max(0.5, n * {'초': 0, '분': 0, '시간': 1 / 24, '일': 1, '주': 7, '개월': 30, '년': 365}[m.group(2)])


def text(o):
    if not isinstance(o, dict):
        return ''
    return o.get('simpleText') or ''.join(r.get('text', '') for r in o.get('runs', []))


def walk(o, key):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                yield v
            else:
                yield from walk(v, key)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v, key)


def search(q):
    url = ('https://www.youtube.com/results?search_query=' + urllib.parse.quote(q + ' #shorts')
           + '&sp=' + SP_THIS_WEEK_SHORT)
    h = subprocess.run(['curl', '-sS', '-m', '25', '-A', 'Mozilla/5.0', '-H', 'Accept-Language: ko-KR', url],
                       capture_output=True, text=True).stdout
    m = re.search(r'var ytInitialData\s*=\s*(\{.+?\});</script>', h)
    if not m:
        return []
    data = json.loads(m.group(1))
    out = []
    for v in walk(data, 'videoRenderer'):
        vid = v.get('videoId')
        sec = text(v.get('lengthText'))
        out.append(dict(
            id=vid, title=text(v.get('title')), channel=text(v.get('ownerText')),
            views=views(text(v.get('viewCountText'))), published=text(v.get('publishedTimeText')),
            length=sec, url=f'https://youtube.com/shorts/{vid}'))
    return out


def main():
    dst = sys.argv[1] if len(sys.argv) > 1 else 'daily_shorts.json'
    floor = int(sys.argv[sys.argv.index('--min') + 1]) if '--min' in sys.argv else 30000
    seen = {}
    for cat, qs in QUERIES.items():
        for q in qs:
            for r in search(q):
                if not r['id'] or r['views'] < floor:
                    continue
                r['per_day'] = int(r['views'] / days(r['published']))
                r['cat'], r['query'] = cat, q
                if r['id'] not in seen or seen[r['id']]['views'] < r['views']:
                    seen[r['id']] = r
    rows = sorted(seen.values(), key=lambda x: -x['per_day'])
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    for r in rows[:60]:
        print(f"{r['per_day']:>9,}/일 {r['views']:>10,} {r['published']:>6} [{r['cat']}] {r['title'][:60]} | {r['channel']} {r['url']}")


if __name__ == '__main__':
    main()
