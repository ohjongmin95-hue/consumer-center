"""기업 공식 홈페이지에서 고객센터·홍보팀 메일 찾기 (운영자 요청 2026-11-03: 쿠팡 같은 곳 기업 연결).
기업에 홈페이지 주소(도메인)가 있으면 첫 화면과 고객센터·문의·회사소개·홍보(보도자료) 화면 몇 개를 읽어 메일 주소를 모은다.
- 고객센터 메일 > 홍보팀 메일 > 대표 문의 메일 순으로 하나 골라 공식 메일로 쓴다.
- 관리자가 직접 넣은 메일은 건드리지 않는다. 공정위 신고 메일만 있던 곳은 홈페이지의 고객센터·홍보 메일로 바꾼다.
- 채용·제휴·IR·광고·개인정보 담당 메일, noreply 메일은 쓰지 않는다.
- 회사 도메인 메일만 쓴다(네이버·지메일 같은 메일은 '고객센터' 글 바로 옆에 있을 때만).
- robots.txt가 막은 화면은 읽지 않는다. 한 기업에 화면 10개까지, 30일마다 다시 본다.
명령: python -m company_web_email find coupang.com   /   python -m company_web_email run
"""
import html, json, os, re, sqlite3, sys, threading, time, urllib.parse, urllib.request, urllib.robotparser
from pathlib import Path

from company_logo import UA, public_host

SOURCE = '공식 홈페이지'
MAX_PAGES = 10
MAX_BYTES = 800_000
RETRY_DAYS = 30
EMAIL_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}')
OBFUSCATED = re.compile(r'\s*(?:\[at\]|\(at\)|\{at\}| at |＠|\[@\]|\(@\))\s*', re.I)
FREE_MAIL = ('naver.com', 'gmail.com', 'daum.net', 'hanmail.net', 'kakao.com', 'nate.com', 'hotmail.com', 'outlook.com')
BAD_LOCAL = re.compile(r'no-?reply|donotreply|do-not-reply|mailer|daemon|example|test|sentry|recruit|career|job|hr$|^hr|insa|ir$|^ir|invest|partner|alliance|ad$|^ad|ads|adver|marketing|sales|privacy|개인정보|security|abuse|webmaster|postmaster|admin|dpo|legal|ethic|audit|tax|account', re.I)
BAD_EXT = re.compile(r'\.(png|jpe?g|gif|svg|webp|css|js|ico|woff2?)$', re.I)
CS_LOCAL = re.compile(r'(^|[._-])(cs|help|helpdesk|support|customer|service|care|cx|voc|cscenter|counsel|consumer|cc)([._-]|\d|$)|^(cs|help|support|customer|service|care)', re.I)
PR_LOCAL = re.compile(r'(^|[._-])(pr|press|media|news|newsroom|communication|comms|public)([._-]|\d|$)|^(pr|press|media)', re.I)
CONTACT_LOCAL = re.compile(r'^(info|contact|webinfo|mail|hello|official|master|help)([._-]|\d|$)', re.I)
CS_TEXT = re.compile(r'고객\s*센터|고객\s*지원|고객\s*문의|고객\s*상담|고객\s*만족|소비자\s*상담|상담\s*센터|문의\s*메일|customer|support|CS\s*센터', re.I)
PR_TEXT = re.compile(r'홍보|보도|언론|취재|press|media|PR\s*팀|커뮤니케이션', re.I)
LINK_WORDS = re.compile(r'고객\s*센터|고객\s*지원|고객\s*문의|문의|상담|도움말|회사\s*소개|기업\s*소개|홍보|보도|언론|뉴스룸|newsroom|press|media|contact|support|help|customer|about|company|faq', re.I)
GUESS_PATHS = ('/contact', '/contact-us', '/about', '/company', '/cs', '/customer', '/support', '/help', '/pr', '/press', '/newsroom')
KIND_ORDER = {'cs': 0, 'pr': 1, 'contact': 2}
KIND_NAME = {'cs': '고객센터', 'pr': '홍보팀', 'contact': '대표 문의'}


def get(url):
    host = urllib.parse.urlsplit(url).hostname or ''
    if not url.startswith(('https://', 'http://')) or not public_host(host): return ''
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'ko-KR,ko;q=0.9'})
    with urllib.request.urlopen(req, timeout=8) as r:
        if 'html' not in (r.headers.get('Content-Type') or 'text/html'): return ''
        raw = r.read(MAX_BYTES)
        charset = r.headers.get_content_charset() or ('euc-kr' if re.search(rb'charset=["\']?euc-kr', raw[:3000], re.I) else 'utf-8')
        return raw.decode(charset, 'replace')


def own_host(host, domain):
    host = (host or '').lower()
    return host == domain or host.endswith('.' + domain)


def label(domain):
    """'coupang.com' → 'coupang', 'shinsegae.co.kr' → 'shinsegae'."""
    parts = domain.split('.')
    while len(parts) > 1 and parts[-1] in ('com', 'net', 'kr', 'co', 'or', 'org', 'io', 'ai', 'biz', 'shop', 'store', 'app', 'me', 'jp', 'us'):
        parts = parts[:-1]
    return parts[-1] if parts else domain


def text_of(page):
    page = re.sub(r'(?is)<(script|style|noscript)[^>]*>.*?</\1>', ' ', page)
    page = re.sub(r'(?is)<a[^>]+href=["\']mailto:([^"\'?]+)[^>]*>', r' \1 ', page)
    page = re.sub(r'(?s)<[^>]+>', ' ', page)
    page = html.unescape(page)
    page = OBFUSCATED.sub('@', page)
    return re.sub(r'\s+', ' ', page)


def emails_on(page, domain):
    """[(메일, 종류)] — 종류: cs/pr/contact. 쓸 수 없는 메일은 뺌."""
    out = {}
    txt = text_of(page)
    own = label(domain)
    for m in EMAIL_RE.finditer(txt):
        email = m.group(0).strip('.').lower()
        local, _, dom = email.partition('@')
        if BAD_EXT.search(email) or BAD_LOCAL.search(local): continue
        close = txt[max(0, m.start() - 25):m.start()]  # 메일 바로 앞 글 (고객센터 이메일 : …, 보도자료 문의 …)
        if own not in dom:
            if dom not in FREE_MAIL or not CS_TEXT.search(close): continue  # 다른 회사(대행사·솔루션) 메일은 안 씀
        if PR_LOCAL.search(local): kind = 'pr'
        elif CS_LOCAL.search(local): kind = 'cs'
        elif CONTACT_LOCAL.search(local): kind = 'contact'
        elif PR_TEXT.search(close): kind = 'pr'
        elif CS_TEXT.search(close): kind = 'cs'
        else: continue
        if email not in out or KIND_ORDER[kind] < KIND_ORDER[out[email]]: out[email] = kind
    return list(out.items())


def links_on(page, base, domain):
    found = []
    for m in re.finditer(r'(?is)<a\b[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', page):
        href, inner = m.group(1).strip(), re.sub(r'<[^>]+>', ' ', m.group(2))
        if href.lower().startswith(('mailto:', 'tel:', 'javascript:')): continue
        url = urllib.parse.urljoin(base, href)
        if not own_host(urllib.parse.urlsplit(url).hostname, domain): continue
        if LINK_WORDS.search(inner) or LINK_WORDS.search(urllib.parse.urlsplit(url).path):
            found.append(url.split('#')[0])
    return found


def find(domain, max_pages=MAX_PAGES):
    """도메인 → (고를 메일, 종류, 찾은 화면, 찾은 메일 전부[(메일,종류,화면)])."""
    robots = {}

    def allowed(url):
        parts = urllib.parse.urlsplit(url)
        key = parts.scheme + '://' + parts.netloc
        if key not in robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                rp.parse(get(key + '/robots.txt').splitlines())
            except Exception:
                rp.parse([])
            robots[key] = rp
        return robots[key].can_fetch(UA, url)

    queue, seen, found = [], set(), {}
    for home in ('https://' + domain + '/', 'https://www.' + domain + '/'):
        queue.append(home)
    queue += ['https://www.' + domain + p for p in GUESS_PATHS]
    homes_done = False
    while queue and len(seen) < max_pages:
        url = queue.pop(0)
        if url in seen: continue
        seen.add(url)
        try:
            if not allowed(url): continue
            page = get(url)
        except Exception:
            continue
        if not page: continue
        for email, kind in emails_on(page, domain):
            if email not in found or KIND_ORDER[kind] < KIND_ORDER[found[email][0]]: found[email] = (kind, url)
        if not homes_done:  # 첫 화면에서 고객센터·홍보 링크를 찾아 먼저 봄
            homes_done = True
            queue = [u for u in dict.fromkeys(links_on(page, url, domain)) if u not in seen][:max_pages] + queue
        if any(k == 'cs' for k, _ in found.values()): break
    allm = sorted(((e, k, u) for e, (k, u) in found.items()), key=lambda x: (KIND_ORDER[x[1]], x[0]))
    if not allm: return '', '', '', []
    best = allm[0]
    return best[0], best[1], best[2], allm


def db_path():
    return Path(os.getenv('DATABASE_PATH', str(Path(__file__).resolve().parent / 'cases.sqlite3')))


def ensure_cols(db):
    cols = {r[1] for r in db.execute('PRAGMA table_info(companies)')}
    for c in ('web_emails', 'web_at'):
        if c not in cols: db.execute(f"ALTER TABLE companies ADD COLUMN {c} TEXT NOT NULL DEFAULT ''")


def run(limit=40, finder=find, say=print, force=False):
    """도메인 있는 기업의 홈페이지 메일 찾기. (살펴본 수, 메일 넣은 수)."""
    db = sqlite3.connect(db_path()); db.row_factory = sqlite3.Row
    since = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(time.time() - RETRY_DAYS * 86400))
    seen = filled = 0
    with db:
        ensure_cols(db)
        q = "SELECT * FROM companies WHERE domain!='' AND status IN ('active','listed','pending')"
        rows = db.execute(q + ('' if force else ' AND (web_at=\'\' OR web_at<?)') + ' ORDER BY id LIMIT ?', (() if force else (since,)) + (limit,)).fetchall()
    for co in rows:
        seen += 1
        try:
            email, kind, url, allm = finder(co['domain'])
        except Exception as e:
            email, kind, url, allm = '', '', '', []
            say(f"{co['name']}: 홈페이지를 못 읽었어요 ({e})")
        now = time.strftime('%Y-%m-%dT%H:%M:%S')
        with db:
            db.execute('UPDATE companies SET web_emails=?,web_at=? WHERE id=?',
                       (json.dumps([{'email': e, 'kind': k, 'url': u} for e, k, u in allm], ensure_ascii=False), now, co['id']))
            cur = db.execute('SELECT official_email,email_source,notice_optout,status FROM companies WHERE id=?', (co['id'],)).fetchone()
            # 관리자가 넣은 메일(출처 없음)은 그대로. 비어 있거나 공정위 신고 메일이면 홈페이지 메일로.
            replace = email and (not cur['official_email'] or cur['email_source'])
            if replace and cur['status'] != 'active' and not cur['notice_optout'] and email != cur['official_email']:
                db.execute('UPDATE companies SET official_email=?,email_source=? WHERE id=?', (email, f'{SOURCE}({KIND_NAME[kind]})', co['id']))
                filled += 1
        say(f"{co['name']} ({co['domain']}): " + (f"{email} [{KIND_NAME[kind]}] {url}" if email else '못 찾았어요'))
    db.close()
    return seen, filled


def install(S):
    """배포 뒤 하루에 한 번 천천히 (사이트 뜨는 것과 따로)."""
    with S.conn() as db: ensure_cols(db)

    def found(text):
        try: return [dict(x, name=KIND_NAME.get(x.get('kind'), '')) for x in json.loads(text or '[]')]
        except (ValueError, TypeError): return []
    S.app.jinja_env.filters['web_emails'] = found
    if S.app.config.get('TESTING') or os.getenv('SOBORU_WEB_EMAIL', '1') == '0': return

    def loop():
        time.sleep(60)
        while True:
            try: run(say=lambda *_: None)
            except Exception as e: print('홈페이지 메일 찾기 실패:', e)
            time.sleep(86400)
    threading.Thread(target=loop, daemon=True).start()


if __name__ == '__main__':
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ''), sys.argv[2:]
    if cmd == 'find' and args:
        email, kind, url, allm = find(args[0])
        for e, k, u in allm: print(f'{e}  [{KIND_NAME[k]}]  {u}')
        print(f'고를 메일: {email} [{KIND_NAME[kind]}]' if email else '못 찾았어요 (홈페이지가 막혀 있거나 메일이 안 보여요).')
    elif cmd == 'run':
        seen, filled = run(limit=int(args[0]) if args else 1000, force=True)
        print(f'홈페이지 {seen}곳을 봤고, {filled}곳의 메일을 넣었어요.')
    else:
        print(__doc__)
