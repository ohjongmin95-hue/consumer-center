"""AI 기사 쓰기 (운영자 2026-11-17: "우리 관리자 페이지에 기사 작성 너도 이렇게 해줄 수 있어? 경기일보 오민주 기자의 기사를 다 학습해.")
관리자 > 기사·콘텐츠 > 기사 쓰기.
- 보도자료·원문을 붙이거나 주소를 넣으면 오민주 기자 문체로 새로 씀. 종류: 보도자료 기사 / 속보 / 기획
- 원문과 90% 넘게 비슷한 문장 비율을 재고(네이버 자체기사 기준), 높으면 한 번 더 고쳐 씀
- 검색용 제목 3개·키워드도 같이 만듦 (포털·검색 노출)
- 다 쓰면 기사 초안함(article_drafts)에 '초안'으로 들어감. 쓰는 동안은 초안 화면이 저절로 새로고침
- 문체 학습: 서버가 경기일보 기자 페이지(writerList?id=democracy555@kyeonggi.com)에서 기사를 모아
  제목·본문을 쌓고(writer_samples), AI가 문체 규칙을 정리해 둠(writer_style). 쓸 때 규칙 + 예시 2편을 같이 줌
- 서버 일은 서버가 함: 오래 걸리는 일(학습·쓰기)은 뒤에서 돌고, 화면은 바로 돌아옴 (gunicorn 90초 제한)
"""
import datetime
import html as htmlmod
import json
import re
import threading
import urllib.parse

from flask import flash, redirect, render_template, request, url_for

WRITER_ID = 'democracy555@kyeonggi.com'
WRITER_NAME = '오민주'
LIST_URL = 'https://www.kyeonggi.com/writerList?id=' + WRITER_ID
SITE = 'https://www.kyeonggi.com'
MAX_SAMPLES = 120
WORKING = '(AI가 기사를 쓰고 있어요. 1~2분 걸려요.)'
KINDS = {
    'release': ('보도자료 기사', '1,000~1,300자', '문단 7~10개'),
    'flash': ('속보', '400~600자', '문단 3~5개'),
    'feature': ('기획', '1,200~1,400자', '문단 8~12개'),
}

STYLE_SYSTEM = ('너는 신문사 데스크다. 아래는 경기일보 오민주 기자가 쓴 기사들이다. 이 기자의 문체를 다른 기자가 그대로 따라 쓸 수 있게 규칙으로 정리한다.\n'
                '- 제목 짜는 법(구두점·따옴표·말줄임 쓰임), 부제, 리드 문장 꼴, 둘째 문단 여는 말, 문단 길이·개수, 전환 문장, 숫자 표기, 인용 넣는 자리와 꼴, 끝맺음 말, 자주 쓰는 표현을 구체적으로.\n'
                '- 기사 내용(사실)은 옮기지 말고 꼴만. 각 규칙에 짧은 예시 표현을 붙인다(한 줄 이내, 기사 문장을 통째로 옮기지 않음).\n'
                'JSON으로만: {"guide": "규칙을 줄마다 - 로 시작해 15~25줄"}')

BASE_RULES = ('[규칙]\n'
              '- 원문 문장을 옮기지 말고 문장 구조부터 새로 쓴다. 원문과 같은 어절이 8개 이상 이어지면 안 된다. 원문에 없는 각도(소비자 입장, 반복 문제, 제도 허점)로 다시 짠다.\n'
              '- 숫자·기관·기업·날짜는 원문에 있는 것만 쓴다. 숫자는 1만8천104건, 1억1천100만원, 439억원처럼 쓴다. 연도는 첫 언급에 "지난해(2025년)"처럼 밝힌다.\n'
              '- "○○일보에 따르면", "보도에 따르면"처럼 다른 언론을 출처로 쓰지 않는다. 말한 주체(기관·기업·의원실)를 출처로 쓴다.\n'
              '- 지어낸 인터뷰·반론에는 반드시 【가안】을 붙인다. 해요체 금지, ~했다·~것으로 나타났다·~셈이다·~지적이다·~방침이다로 끝낸다.\n'
              '- 문체 예시 기사는 꼴만 참고한다. 예시의 문장·사실은 절대 옮기지 않는다.\n')

KIND_RULES = {
    'release': ('- 보도자료를 그대로 받아 쓰지 말고 소비자에게 무엇이 달라지는지부터 쓴다. 리드 한 문장에 핵심(누가·무엇을·왜)을 담는다.\n'
                '- 보도자료를 낸 기관·기업 관계자 인용은 보도자료에 있는 말만 쓰고, 없으면 "【가안】"으로 표시한다.\n'),
    'flash': ('- 속보다. 첫 문장에 무슨 일이 언제 일어났는지 바로 쓴다. 배경 설명은 짧게, 인터뷰는 넣지 않는다.\n'
              '- 제목은 사실 그대로 짧게(25자 이내), 따옴표 인용은 원문에 있을 때만.\n'),
    'feature': ('- 중간에 한 문장 전환 문단 "문제는 ~다." 하나. 2문단은 "{d}일 소비자를위한신문 취재를 종합하면,"으로 시작해 숫자를 제시.\n'
                '- 중후반: 시민 인터뷰 "○○시의 한 직장인 A씨(34)는 【가안】 "…"며 "…"고 전했다." 전문가 【가안】 인용 하나. 마지막 문단은 기업·기관 관계자 반론 【가안】.\n'
                '- 맨 끝 줄: *이 기사는 공개 자료 조사와 통계 정리에 AI를 활용했습니다.*\n'),
}

OUT_SPEC = ('JSON으로만: {"title": "기사 제목", "titles": ["포털·검색용 제목 후보 3개, 핵심 검색어를 앞쪽에"], "deck": ["부제 1", "부제 2"], '
            '"category": "소비자의 소리|산업|경제|머니|생활|테크|트렌드|이슈 중 하나", "body": "문단 사이 빈 줄", '
            '"keywords": ["검색 키워드 5~8개"], "needs": ["기자가 채울 것 2~5개"]}')

DEFAULT_GUIDE = ("- 제목: 주체+사안 '핵심어'…\"인용 또는 수치\" 꼴 (예: 경기도 '똑버스'의 배신…\"예산 수백억 쓰는데 30분 대기\"). 35자 이내.\n"
                 '- 부제 2줄: 숫자 대비 / 문제…대안 필요 식, 명사형으로 끝.\n'
                 '- 리드 한 문장: "~하고 있지만 정작 ~하지 못하고 있는 것으로 나타났다." 또는 "~하면서 ~에 나섰다."\n'
                 '- 문단마다 1~3문장, 소제목 없음.\n'
                 '- 인용: "지역 시민 A씨는 "…"며 "…"고 전했다." / "○○ 관계자는 "…"고 말했다."로 마무리.\n'
                 '- 끝맺음: ~했다, ~것으로 나타났다, ~그쳤다, ~셈이다, ~지적이다, ~전망이다, ~방침이다.')


def install(S):
    app = S.app
    with S.conn() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS writer_samples(id INTEGER PRIMARY KEY, url TEXT UNIQUE, title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '', published TEXT NOT NULL DEFAULT '', created TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS writer_style(id INTEGER PRIMARY KEY CHECK(id=1), guide TEXT NOT NULL DEFAULT '',
            n INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT '', updated TEXT NOT NULL DEFAULT '')''')
        db.execute("INSERT OR IGNORE INTO writer_style(id,guide,n,state,updated) VALUES(1,'',0,'','')")
    S.ai_writer_learn = lambda: learn(S)
    S.ai_writer_write = lambda did, kind, src, url, memo: write(S, did, kind, src, url, memo)

    @app.route('/admin/write', methods=['GET', 'POST'])
    @S.admin_only
    def admin_writer():
        if request.method == 'POST':
            f = request.form
            if f.get('do') == 'learn':
                with S.conn() as db: db.execute("UPDATE writer_style SET state='learning' WHERE id=1")
                threading.Thread(target=learn, args=(S,), daemon=True).start()
                flash('오민주 기자 기사를 모으고 있어요. 몇 분 뒤 새로고침하면 학습한 기사 수가 바뀌어요.')
                return redirect(url_for('admin_writer'))
            kind = f.get('kind') if f.get('kind') in KINDS else 'release'
            src, url, memo = (f.get('source') or '').strip()[:20000], (f.get('url') or '').strip()[:500], (f.get('memo') or '').strip()[:500]
            if url and not re.match(r'https?://', url): url = ''
            if len(src) < 40 and not url:
                flash('보도자료나 원문을 붙여 넣거나 기사 주소를 넣어 주세요.')
                return render_template('admin_writer.html', st=style_state(S), kinds=KINDS, form=f)
            now = S.now()
            with S.conn() as db:
                did = db.execute('INSERT INTO article_drafts(key,section,cut,title,body,source,note,origin,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                 ('ai-' + now + '-' + str(threading.get_ident() % 1000), '', KINDS[kind][0], (memo or src[:40] or url)[:60] + ' (쓰는 중)',
                                  WORKING, url, '', 'AI 기사 쓰기', now, now)).lastrowid
            threading.Thread(target=write, args=(S, did, kind, src, url, memo), daemon=True).start()
            return redirect(url_for('admin_draft', did=did))
        st = style_state(S)
        if not st['n'] and st['state'] not in ('learning', 'fail'):  # 처음 열면 서버가 알아서 학습 시작
            with S.conn() as db: db.execute("UPDATE writer_style SET state='learning' WHERE id=1")
            threading.Thread(target=learn, args=(S,), daemon=True).start(); st['state'] = 'learning'
        return render_template('admin_writer.html', st=st, kinds=KINDS, form={})


def style_state(S):
    with S.conn() as db:
        r = db.execute('SELECT * FROM writer_style WHERE id=1').fetchone()
        n = db.execute('SELECT COUNT(*) FROM writer_samples').fetchone()[0]
    return {'guide': r['guide'] if r else '', 'n': n, 'state': r['state'] if r else '', 'updated': (r['updated'] if r else '')[:16].replace('T', ' ')}


# ---- 문체 학습 ------------------------------------------------------------------
def _fetch(url):
    from soboru_writer import fetch_page
    return fetch_page(url, timeout=12)


def list_links(raw):
    """기자 페이지·검색 결과 HTML → 경기일보 기사 주소들 (중복 없이, 나온 순서대로)"""
    out = []
    for h in re.findall(r'href="([^"]*?/article/\d{8,}[^"#]*)"', raw or ''):
        u = urllib.parse.urljoin(SITE + '/', htmlmod.unescape(h)).split('?')[0]
        if u not in out: out.append(u)
    return out


def article_parts(raw):
    """경기일보 기사 HTML → (제목, 본문, 날짜). 본문은 문단 사이 빈 줄. 오민주 기자 글이 아니면 ('', '', '')"""
    if not raw or WRITER_NAME not in raw: return '', '', ''
    m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', raw) or re.search(r'<title>([^<]+)</title>', raw)
    title = htmlmod.unescape(m.group(1)).split(' - ')[0].split('|')[0].strip() if m else ''
    m = re.search(r'<meta[^>]+property="article:published_time"[^>]+content="([^"]+)"', raw)
    pub = m.group(1)[:10] if m else ''
    # 본문 칸 시작부터 넉넉히 잘라 문단(<p>)만 모음. 칸 안에 사진 <div>가 있어도 끊기지 않게
    m = (re.search(r'<(?:div|article)[^>]+(?:id|class|itemprop)="[^"]*(?:articleBody|article[-_]?(?:body|view|txt|cont)|news[-_]?(?:body|content)|view[-_]?(?:con|text))[^"]*"', raw, re.I)
         or re.search(r'<article[^>]*>', raw))
    body = raw[m.start():m.start() + 60000] if m else raw
    body = re.split(r'(?i)<footer|class="[^"]*(?:copyright|article[-_]?copy|relate|reporter[-_]?info)', body)[0]
    ps = re.findall(r'(?is)<p[^>]*>(.*?)</p>', body)
    if len(ps) >= 3: body = '</p>'.join(ps)
    body = re.sub(r'(?is)<(script|style|figure|figcaption|table|aside|button)[^>]*>.*?</\1>', ' ', body)
    body = re.sub(r'(?i)<br\s*/?>|</p>|</div>', '\n', body)
    lines = [' '.join(htmlmod.unescape(re.sub(r'<[^>]+>', ' ', x)).split()) for x in body.split('\n')]
    lines = [x for x in lines if len(x) > 25 and not re.search(r'무단|저작권|Copyright|@kyeonggi|기자\s*$|구독|댓글|관련기사', x)]
    return title, '\n\n'.join(lines)[:6000], pub


def gather_links(pages=8):
    links = []
    for p in range(1, pages + 1):
        raw = _fetch(LIST_URL + ('&page=%d' % p if p > 1 else ''))
        got = [u for u in list_links(raw) if u not in links]
        if not got: break
        links += got
        if len(links) >= MAX_SAMPLES: break
    if len(links) < 10:  # 기자 페이지를 못 읽으면 네이버 뉴스 검색으로
        try:
            import news_desk
            for q in ('경기일보 오민주 기자', '오민주 기자 경기일보', WRITER_ID):
                for it in news_desk.naver_news(q, 100):
                    u = it['url']
                    if 'kyeonggi.com' in u and u not in links: links.append(u)
        except Exception as e: print('기사 쓰기 학습: 네이버 검색 실패', e)
    return links[:MAX_SAMPLES]


def learn(S):
    """오민주 기자 기사를 모으고 문체 규칙을 정리해 둔다. 한 번 모은 기사는 다시 받지 않음"""
    try:
        links = gather_links()
        with S.conn() as db:
            have = {r[0] for r in db.execute('SELECT url FROM writer_samples')}
        n_new = 0
        for u in links:
            if u in have: continue
            title, body, pub = article_parts(_fetch(u))
            if not title or len(body) < 300: continue
            with S.conn() as db:
                db.execute('INSERT OR IGNORE INTO writer_samples(url,title,body,published,created) VALUES(?,?,?,?,?)', (u, title, body, pub, S.now()))
            n_new += 1
        with S.conn() as db:
            rows = db.execute('SELECT title,body FROM writer_samples ORDER BY published DESC, id DESC LIMIT 14').fetchall()
            n = db.execute('SELECT COUNT(*) FROM writer_samples').fetchone()[0]
        guide = ''
        if rows:
            import news_desk
            user = '\n\n'.join(f'[기사 {i}] 제목: {r["title"]}\n{r["body"][:1800]}' for i, r in enumerate(rows, 1))
            guide = (news_desk.chat(STYLE_SYSTEM, user, 2000).get('guide') or '').strip()
        with S.conn() as db:
            if guide: db.execute("UPDATE writer_style SET guide=?,n=?,state='',updated=? WHERE id=1", (guide, n, S.now()))
            else: db.execute("UPDATE writer_style SET state=?,updated=? WHERE id=1", ('fail' if not n else '', S.now()))
        print(f'기사 쓰기 학습: 새 기사 {n_new}건, 모두 {n}건')
    except Exception as e:
        print('기사 쓰기 학습 실패:', e)
        with S.conn() as db: db.execute("UPDATE writer_style SET state='fail' WHERE id=1")


# ---- 쓰기 ---------------------------------------------------------------------
def system_prompt(S, kind, day):
    st = style_state(S)
    with S.conn() as db:
        ex = db.execute('SELECT title,body FROM writer_samples ORDER BY RANDOM() LIMIT 2').fetchall()
    label, size, paras = KINDS[kind]
    s = (f'너는 「소비자를위한신문」 기자다. 아래 원문을 바탕으로 우리 신문 {label}를 새로 쓴다. 경기일보 오민주 기자 문체를 따른다.\n'
         f'[분량] 본문 {size}(공백 포함), {paras}, 문단마다 1~3문장, 문단 사이 빈 줄, 소제목 없음.\n'
         '[오민주 기자 문체]\n' + (st['guide'] or DEFAULT_GUIDE) + '\n'
         + BASE_RULES + KIND_RULES[kind].replace('{d}', str(day)))
    if ex:
        s += '\n[문체 예시: 꼴만 보고 문장·사실은 옮기지 않는다]\n' + '\n\n'.join(
            f'(예시 {i}) {r["title"]}\n' + '\n\n'.join(r['body'].split('\n\n')[:4])[:900] for i, r in enumerate(ex, 1))
    return s + '\n' + OUT_SPEC


def similar_lines(body, sources):
    """원문과 90% 넘게 비슷한 내 문장들 (네이버 자체기사 기준)"""
    import difflib
    src = [s for t in sources for s in re.split(r'(?<=[.?!다])\s+', t) if len(s) > 15]
    mine = [s for s in re.split(r'(?<=[.?!다])\s+', body) if len(s) > 15 and '【가안】' not in s and not s.startswith('*')]
    hit = [s for s in mine if src and max(difflib.SequenceMatcher(None, s, x).ratio() for x in src) >= .9]
    return hit, len(mine)


def write(S, did, kind, src, url, memo):
    import news_desk
    try:
        texts = []
        if src: texts.append(src)
        if url:
            t = news_desk.page_text(url, 6000)
            if t: texts.append(t)
        if not texts: raise RuntimeError('원문을 읽지 못했어요. 주소 대신 본문을 붙여 넣어 주세요.')
        today = datetime.date.today()
        system = system_prompt(S, kind, today.day)
        user = (f'[우리 각도] {memo}\n' if memo else '') + '\n\n'.join(f'[원문 {i}]\n{t}' for i, t in enumerate(texts, 1))
        out = news_desk.chat(system, user, 2600)
        body = (out.get('body') or '').strip()
        hit, total = similar_lines(body, texts)
        if total and len(hit) / total > .1:  # 원문과 비슷한 문장이 많으면 한 번 더 고쳐 씀
            out2 = news_desk.chat(system, user + '\n\n[이전 초안]\n' + body + '\n\n[원문과 너무 비슷한 문장: 구조부터 새로 써라]\n' + '\n'.join('- ' + h for h in hit), 2600)
            b2 = (out2.get('body') or '').strip()
            h2, t2 = similar_lines(b2, texts)
            if b2 and (not t2 or len(h2) / t2 < len(hit) / total): out, body, hit, total = out2, b2, h2, t2
        deck = [d for d in (out.get('deck') or []) if d][:2]
        full = ('\n\n'.join(deck) + '\n\n' if deck else '') + body
        pct = round(100 * (1 - len(hit) / total)) if total else 100
        note = [f'원문과 다른 문장 {pct}% (90% 넘게 비슷한 문장 {len(hit)}개 / {total}개)']
        if out.get('titles'): note.append('검색용 제목: ' + ' / '.join(out['titles'][:3]))
        if out.get('keywords'): note.append('키워드: ' + ', '.join(out['keywords'][:8]))
        if out.get('needs'): note.append('채울 것: ' + ' · '.join(out['needs'][:5]))
        if hit: note.append('비슷한 문장: ' + ' / '.join(h[:60] for h in hit[:3]))
        with S.conn() as db:
            db.execute('UPDATE article_drafts SET title=?,section=?,body=?,note=?,updated=? WHERE id=? AND body=?',
                       ((out.get('title') or '제목 없음')[:300], (out.get('category') or '')[:20], full[:50000], '\n'.join(note)[:4000], S.now(), did, WORKING))
    except Exception as e:
        print('AI 기사 쓰기 실패:', e)
        with S.conn() as db:
            db.execute('UPDATE article_drafts SET title=?,body=?,updated=? WHERE id=? AND body=?',
                       ('기사를 못 썼어요', f'기사를 쓰다가 멈췄어요. 다시 해 주세요.\n\n({str(e)[:200]})', S.now(), did, WORKING))
