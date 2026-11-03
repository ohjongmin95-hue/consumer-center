"""큰 기업 이름 오타 바로잡기 (운영자 2026-11-03: '큐팡' 같은 건 앞으로 자동으로 '쿠팡'으로).

data/companies_seed.csv의 큰 기업 이름(한글)과 글자 수가 같고 자모 하나만 다르면 그 기업 이름으로 고친다.
예: 큐팡 → 쿠팡, 쿠팽 → 쿠팡, 다이쏘 → 다이소. 후보가 둘 이상이면 고치지 않는다(헷갈리면 그대로 둠).
제보를 받을 때(/report, 대화 제보 초안)와 배포할 때 예전 제보에 한 번씩 쓴다.
"""
import csv
import re
from pathlib import Path

SEED = Path(__file__).resolve().parent / 'data' / 'companies_seed.csv'
CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
JUNG = 'ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ'
JONG = ' ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ'
HANGUL = re.compile(r'^[가-힣0-9]+$')
_names = None


def norm(name):
    name = re.sub(r'\(주\)|㈜|주식회사', '', name or '')
    return re.sub(r'[\s\-_.·,()]', '', name).lower()


def jamo(text):
    out = []
    for ch in text:
        c = ord(ch) - 0xAC00
        if 0 <= c < 11172:
            out += [CHO[c // 588], JUNG[c % 588 // 28]] + ([JONG[c % 28]] if c % 28 else [])
        else:
            out.append(ch)
    return out


def one_edit(a, b):
    """두 자모 줄이 한 글자만 다르면(바꿈·빠짐·더함) True."""
    if a == b or abs(len(a) - len(b)) > 1: return False
    if len(a) == len(b): return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b): a, b = b, a
    return any(a == b[:i] + b[i + 1:] for i in range(len(b)))


def names():
    """[(바른 이름, 비교할 이름들)] — 한글 이름·다른 이름만."""
    global _names
    if _names is None:
        _names = []
        try:
            with open(SEED, encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    alts = [row['이름']] + [a for a in (row.get('다른 이름') or '').split('|') if a]
                    _names.append((row['이름'], [norm(a) for a in alts if HANGUL.match(norm(a))]))
        except OSError:
            pass
    return _names


def fix(typed):
    """오타면 바른 큰 기업 이름, 아니면 적은 그대로."""
    t = norm(typed)
    if len(t) < 2 or not HANGUL.match(t): return typed
    if any(t in alts for _, alts in names()): return typed  # 이미 맞는 이름
    jt = jamo(t)
    hits = {name for name, alts in names() for a in alts if len(a) == len(t) and len(jamo(a)) >= 5 and one_edit(jt, jamo(a))}
    return hits.pop() if len(hits) == 1 else typed


def fix_old_cases(conn, link_company):
    """예전 제보의 업체 이름 오타도 고치고 그 기업에 다시 연결 (배포할 때마다, 고칠 것만)."""
    try:
        with conn() as db:
            for r in db.execute("SELECT id,company FROM cases WHERE company!=''").fetchall():
                good = fix(r['company'])
                if good != r['company']:
                    db.execute('UPDATE cases SET company=?,company_id=NULL WHERE id=?', (good, r['id']))
                    link_company(db, r['id'], good)
    except Exception as e:
        print('업체 이름 오타를 못 고쳤어요:', e)
