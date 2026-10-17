"""크로와상: 뉴닉식 뉴스레터. 기본은 평일 아침마다 그날의 주요 이슈(여러 언론이 함께 다룬 뉴스) 3~5개를 AI가 우리 말로 풀고, 소보루 픽 리뷰·리뷰 주제·생활정보를 붙여 메일로 보낸다.

app.py 맨 끝에서 install(사이트 모듈의 이름공간)을 불러 붙인다 (soboru_writer.py와 같은 방식).
- 호 만들기: 네이버 뉴스 검색(분야별 LETTER_QUERIES, 제목·요약 조각만)에서 지난 하루(월요일은 주말 포함, 매주면 7일) 뉴스를 모아
  여러 기사가 함께 다룬 이슈부터 3~5개(비슷한 기사는 하나로, 한 분야 2개까지) 고르면 → AI(companydesk.post_json)가
  해요체로 짧은 제목·3~5문장 설명·'이럴 땐 이렇게' 한 줄·관련 법 조문(넘겨 준 후보 중에서만)을 쓴다. 기사 문장은 옮기지 않게 하고,
  코드로도 원문과 6어절 넘게 겹치는지, 숫자가 그 뉴스 자료에 있는지(soboru_writer.check_text) 검사해 '검토 필요'로 표시한다.
  각 뉴스에는 기사 원문(언론사) 링크와 법령 출처를 붙인다. 아래 묶음(소보루 픽 인기 리뷰, 진행 중인 리뷰 주제, 새 생활정보)은 DB에서.
- 보내기: 관리자 > 크로와상에서 운영자가 '보내기'를 누르거나, '자동 보내기'를 켜 두면 검사를 통과한 호만 만든 뒤 바로 보낸다.
  메일은 notify.send_email(SMTP, deploy/set-mail.sh)로 확인을 마친(active) 구독자에게만, 작은 묶음으로 쉬어 가며 뒤에서 보낸다.
  보낸 기록은 letter_sends에 남겨 같은 사람에게 두 번 보내지 않는다(중간에 끊겨도 다시 누르면 남은 사람에게만).
- 구독: 이메일 + 수집·이용 동의 → 확인 메일(/letter/confirm/<token>)을 눌러야 구독(이중 확인). 모든 메일에 한 번에 해지하는
  /letter/unsubscribe/<token> 링크와 List-Unsubscribe 머리글. 해지하면 이메일 주소는 복원할 수 없는 값으로 바꿔 지운다.
  확인하지 않은 신청은 7일 뒤 지운다.
- 예약: deploy/soboru-letter.timer가 매일 아침 7시 30분 `python soboru_letter.py weekly`를 부르면, 관리자가 고른 주기(평일 매일·매일·매주 한 요일)에 맞을 때만 한 호를 만든다.
"""
import datetime, hashlib, json, os, re, secrets, sys, threading, time
from flask import abort, flash, g, redirect, render_template, request, url_for
from markupsafe import Markup
import soboru_writer as W

SITE = W.SITE
NAME = '크로와상'
DAYS = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']
ITEMS = (3, 5)            # 한 호에 뉴스 몇 개
NEWS_DAYS = 7             # 매주 보낼 때 뉴스 기간
# 분야별 토스페이스 그림 (메일은 글꼴을 못 받으므로 static/img/tf/*.png 그림으로, 웹은 같은 이모지 글자로)
TOPIC_ICON = {'경제': ('money', '💰'), '물가': ('cart', '🛒'), '금리': ('chart', '📈'), '부동산': ('house', '🏠'), '정부 정책': ('speaker', '📢'),
              '국회': ('bank', '🏦'), '사회': ('mega', '📣'), '국제': ('plane', '✈️'), 'IT 과학': ('laptop', '💻'), '소비자': ('shield', '🛡️'), '리콜': ('siren', '🚨')}
FREQS = {'weekdays': '평일 매일', 'daily': '매일', 'weekly': '매주 한 번'}
# 뉴닉처럼 분야를 고루: 분야마다 최근 기사를 모아 여러 언론이 함께 다룬 이슈부터 고름
LETTER_QUERIES = ['경제', '물가', '금리', '부동산', '정부 정책', '국회', '사회', '국제', 'IT 과학', '소비자', '리콜']
PER_QUERY = 30            # 분야마다 가져올 기사 수
PER_TOPIC = 2             # 한 분야에서 고를 수 있는 이슈 수
COMMON_SHARE = 0.4        # 모은 기사 제목의 이만큼 넘게 나오는 낱말은 이슈를 가르는 데 안 씀
REVIEW_DAYS = 14
SEND_BATCH = 20           # 한 번에 보내는 메일 수
SEND_PAUSE = 3.0          # 묶음 사이 쉬는 시간(초)
SUB_LIMIT = 5             # 같은 접속지에서 10분 동안 구독 신청 횟수
PENDING_DAYS = 7          # 확인 안 한 신청은 7일 뒤 지움
COPY_WORDS = 6            # 기사 원문과 이만큼 어절이 그대로 겹치면 '검토 필요'
AI_TIMEOUT = 120
EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')
UNSUB_MARK = '__LETTER_UNSUB__'

SYSTEM = ('너는 소보루(소비자 정보 플랫폼)의 뉴스레터 "크로와상" 에디터다. 뉴닉처럼 그날의 주요 이슈를 바쁜 사람도 5분이면 따라잡게 정리한다. 뉴닉처럼 친구에게 말하듯 친근한 해요체(~요)로, 어려운 말은 풀어서 쓴다.\n'
          '지켜야 할 것:\n'
          '- 뉴스마다 제목과 요약 조각만 준다. 기사 문장을 옮기지 말고 반드시 네 말로 새로 풀어 쓴다. 기사에서 그대로 따오는 말은 몇 낱말을 넘지 않게 하고, 따옴표로 인용하지 않는다.\n'
          '- 그 뉴스의 [제목]·[요약]·[법 조문 후보]에 있는 사실과 숫자만 쓴다. 없는 숫자(날짜·금액·비율·건수·기간 모두)는 쓰지 않고, 숫자를 새로 계산하지 않는다.\n'
          '- 요약이 말하지 않는 원인·전망·뒷이야기는 짐작하지 않는다. 더 알 수 없으면 "자세한 내용은 기사 원문에서 확인해 보세요"처럼 쓴다.\n'
          '- 기업을 좋다·나쁘다 평가하거나 비난하지 않는다. 정치 이슈는 어느 편도 들지 않고 누가 무엇을 했는지 사실만 쓴다. 사람 이름·연락처 같은 개인정보는 쓰지 않는다(공인이 한 공식 발표는 기관 이름으로 쓴다).\n'
          '- 법 조문은 그 뉴스의 [법 조문 후보] id 가운데 정말 관련 있는 것 하나만 고르고, 맞는 것이 없으면 빈 문자열로 둔다. 법 이야기는 "~할 수 있어요"처럼 단정하지 않게 쓴다. 법률 자문이 아니다.\n'
          '- 링크·출처·주소·HTML·마크다운 기호는 쓰지 않는다(화면에서 따로 붙인다). 목록이나 팁 개수를 숫자로 세지 않는다.\n'
          'JSON 객체 하나로만 답한다: {"subject": 메일 제목 30자 안팎(이번 호에서 가장 눈길 끄는 소식), "intro": 첫인사 3~4문장 — "소보루 이웃님,"으로 시작해 오늘 가장 큰 소식을 공감하듯 꺼내고, 오늘 무엇을 같이 읽어 볼지 말한 뒤 "그 밖에 ~ 소식도 정리해봤어요"처럼 나머지 소식을 한 문장으로 묶는다. 언론·기사·보도·매체 이야기는 하지 않는다, "outro": 맺음말 1~2문장, '
          '"items": [{"no": 뉴스 번호, "title": 25자 안팎 짧고 눈길 끄는 제목, "body": 3~5문장 설명, "tip": 이 소식이 내 생활·지갑에 어떤 의미인지 또는 할 일 한 줄(60자 이내, 마땅치 않으면 ""), "law": 고른 조문 id 또는 ""}]}')


class Skip(Exception):
    """지금은 호를 만들 수 없음 (자료 없음·키 없음). 운영자에게 보여 줄 쉬운 말."""


def stamp(): return datetime.datetime.now().isoformat(timespec='seconds')


def site_url(path=''): return (os.getenv('SITE_URL', '').strip() or SITE).rstrip('/') + path


def words(text): return [w for w in re.sub(r'[^\w%]+', ' ', text or '').split() if w]


def copied(text, source, n=COPY_WORDS):
    """AI 글에 기사 제목·요약과 n어절 넘게 그대로 겹치는 부분이 있으면 그 부분."""
    src = words(source); have = {tuple(src[i:i + n]) for i in range(len(src) - n + 1)}
    mine = words(text)
    for i in range(len(mine) - n + 1):
        if tuple(mine[i:i + n]) in have: return ' '.join(mine[i:i + n])
    return ''


def iso_day(s):
    """'2026.10.16' → '2026-10-16' (숫자 검사에서 10·16이 따로 잡히게)."""
    m = re.match(r'(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})', s or '')
    return '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3))) if m else (s or '')


def mask_nick(nick):
    nick = (nick or '').strip() or '익명'
    return nick[:2] + '**' if len(nick) > 2 else nick[:1] + '*'


def gone_email(email): return 'x:' + hashlib.sha256(email.encode()).hexdigest()


def kdate(iso):
    try: d = datetime.date.fromisoformat((iso or '')[:10])
    except ValueError: return ''
    return f"{d.year}. {d.month}. {d.day}. ({DAYS[d.weekday()][0]})"


def install(S):
    app = S.app; conn = S.conn; desk = S.companydesk; notify = S.notify
    corpus = S.triage.corpus
    with conn() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS letters(id INTEGER PRIMARY KEY,no INTEGER NOT NULL UNIQUE,title TEXT NOT NULL,intro TEXT NOT NULL DEFAULT '',
            outro TEXT NOT NULL DEFAULT '',items TEXT NOT NULL DEFAULT '[]',sections TEXT NOT NULL DEFAULT '{}',status TEXT NOT NULL DEFAULT 'draft',
            created TEXT NOT NULL,updated TEXT NOT NULL DEFAULT '',sent_at TEXT,check_ok INTEGER NOT NULL DEFAULT 0,problems TEXT NOT NULL DEFAULT '[]',
            trigger TEXT NOT NULL DEFAULT 'admin',sent_count INTEGER NOT NULL DEFAULT 0,failed INTEGER NOT NULL DEFAULT 0)''')
        db.execute('''CREATE TABLE IF NOT EXISTS letter_subscribers(id INTEGER PRIMARY KEY,email TEXT NOT NULL UNIQUE,token TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending',created TEXT NOT NULL,confirmed TEXT,ip_hash TEXT NOT NULL DEFAULT '',asked TEXT,unsubscribed TEXT,
            place TEXT NOT NULL DEFAULT '')''')
        db.execute('''CREATE TABLE IF NOT EXISTS letter_sends(letter_id INTEGER NOT NULL,sub_id INTEGER NOT NULL,status TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',
            at TEXT NOT NULL,PRIMARY KEY(letter_id,sub_id))''')

    def naver(): return app.extensions.get('naverhub') or {}
    def testing(): return bool(app.config.get('TESTING'))

    # ---- 설정 ---------------------------------------------------------------
    def setting(key, default):
        with conn() as db: row = db.execute('SELECT value FROM soboru_settings WHERE key=?', (key,)).fetchone()
        try: return json.loads(row[0]) if row else default
        except ValueError: return default

    def put(key, value):
        with conn() as db: db.execute('INSERT OR REPLACE INTO soboru_settings(key,value) VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))

    def settings():
        s = setting('letter', {})
        return {'auto': 1 if s.get('auto') == 1 else 0, 'day': s.get('day') if s.get('day') in range(7) else 0,
                'freq': s.get('freq') if s.get('freq') in FREQS else 'weekdays'}

    def news_days(today=None):
        # 매일 보내면 지난 하루치(평일만 보내면 월요일은 주말까지), 매주면 7일치
        cfg = settings(); today = today or datetime.date.today()
        if cfg['freq'] == 'weekly': return NEWS_DAYS
        return 3 if cfg['freq'] == 'weekdays' and today.weekday() == 0 else 1

    def log(entry):
        put('letter_log', ([dict(entry, at=stamp())] + setting('letter_log', []))[:30])

    # ---- 자료 모으기 ----------------------------------------------------------
    def collect_news():
        nv = naver()
        if not nv or not nv['ready'](): raise Skip('네이버 API HUB 키가 없어요 (deploy/set-naver.sh)')
        days = news_days()
        since = datetime.date.today() - datetime.timedelta(days=days)
        pool, seen, heads = [], set(), set()
        try:
            for q in LETTER_QUERIES:
                for it in nv['search']('news', q, display=PER_QUERY, sort='date')['items']:
                    try: day = datetime.date(*map(int, it['date'].split('.')))
                    except (ValueError, TypeError): continue
                    head = re.sub(r'\W', '', it['title'])[:14]
                    if day < since or it['url'] in seen or head in heads: continue
                    seen.add(it['url']); heads.add(head); pool.append(dict(it, topic=q))
        except Exception as e:  # 네이버 오류 문구(NaverError)는 그대로, 그 밖은 이름만 (키가 섞이지 않게)
            raise Skip(str(e)[:120] if type(e).__name__ == 'NaverError' else f'뉴스를 가져오지 못했어요 ({type(e).__name__})')
        items = pick_issues(pool)
        if len(items) < ITEMS[0]: raise Skip(f'최근 {days}일 주요 뉴스가 {ITEMS[0]}건보다 적어요')
        scrub = lambda t: W.clean_personal(desk.scrub, t)
        out = []
        for n, it in enumerate(items, 1):
            title, summary = scrub(it['title']), scrub(it['summary'])
            hits = corpus.related(title + ' ' + summary, limit=3)
            cands = [{'id': f'{n}-L{k}', 'label': h['label'], 'law': h.get('law', ''), 'text': corpus.clip(h['text'], 500), 'url': h.get('source') or ''} for k, h in enumerate(hits, 1)]
            out.append({'no': n, 'title': title, 'summary': summary, 'source': it['source'], 'date': iso_day(it['date']), 'url': it['url'], 'cands': cands, 'topic': it.get('topic', '')})
        return out

    def pick_issues(pool):
        # 주요 이슈 = 여러 기사가 함께 다룬 소식. 제목 낱말이 2개 넘게 겹치는 기사가 많을수록 앞에 둠.
        # 거의 모든 제목에 나오는 낱말(속보·단독 같은 말)은 빼고 셈. 같은 이슈는 하나만, 한 분야는 PER_TOPIC개까지.
        stem = lambda w: w[:-1] if len(w) >= 3 and w[-1] in '은는이가을를의에도로와과만' else w  # '금리가'·'금리는' → '금리'
        bags = [{stem(w) for w in words(it['title']) if len(w) >= 2 and not w.isdigit()} for it in pool]
        df = {}
        for b in bags:
            for w in b: df[w] = df.get(w, 0) + 1
        common = {w for w, n in df.items() if len(pool) >= 5 and n > len(pool) * COMMON_SHARE}
        bags = [b - common for b in bags]
        same = lambda a, b: len(a & b) >= 2
        score = [sum(1 for j, o in enumerate(bags) if j != i and same(b, o)) for i, b in enumerate(bags)]
        picked, per, order = [], {}, sorted(range(len(pool)), key=lambda i: -score[i])  # 점수가 같으면 분야 순서·최신 순 그대로
        for cap in (PER_TOPIC, ITEMS[1]):  # 분야를 고루 고르고, 모자라면 한 분야에서 더
            for i in order:
                t = pool[i]['topic']
                if len(picked) == ITEMS[1]: break
                if i in picked or per.get(t, 0) >= cap or any(same(bags[i], bags[k]) for k in picked): continue
                picked.append(i); per[t] = per.get(t, 0) + 1
        return [pool[i] for i in sorted(picked, key=order.index)]

    def ai_facts(news):
        return [{'번호': x['no'], '제목': x['title'], '요약': x['summary'], '언론사': x['source'], '날짜': x['date'],
                 '법 조문 후보': [{'id': c['id'], '조문': c['label'], '원문': c['text']} for c in x['cands']]} for x in news]

    def ask_ai(news, no):
        key = os.getenv('OPENAI_API_KEY', '').strip()
        if not key: raise RuntimeError('OpenAI API 키가 없어요')
        user = (f"[이번 호] {NAME} {no}호 ({datetime.date.today().isoformat()})\n[이번 호 뉴스]\n"
                f"{json.dumps(ai_facts(news), ensure_ascii=False, indent=1)}")
        body = {'model': desk.ai_model(), 'temperature': 0.5, 'response_format': {'type': 'json_object'}, 'max_tokens': 2600,
                'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}]}
        st, res = desk.post_json('https://api.openai.com/v1/chat/completions', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, AI_TIMEOUT)
        if st != 200: raise RuntimeError(f'AI 응답 오류 ({st}) ' + str((res.get('error') or {}).get('message', ''))[:120].replace(key, '***'))
        try: return json.loads(res['choices'][0]['message']['content'])
        except (KeyError, IndexError, TypeError, ValueError): raise RuntimeError('AI 응답을 읽지 못했어요')

    def item_facts(x, law):
        f = {'제목': x['title'], '요약': x['summary'], '날짜': x['date'], '소비자상담센터 전화번호': '1372'}
        if law: f['법 조문'] = law['label'] + ' ' + law['text']
        return f

    def assemble(out, news):
        if not isinstance(out, dict) or not isinstance(out.get('items'), list): raise RuntimeError('AI 응답 형식이 달라요')
        by_no = {x['no']: x for x in news}
        items = []
        for i, it in enumerate(out['items'][:ITEMS[1]]):
            if not isinstance(it, dict): continue
            x = by_no.get(it.get('no')) if isinstance(it.get('no'), int) else None
            x = x or (news[i] if i < len(news) else None)
            if not x or any(y['src']['url'] == x['url'] for y in items): continue
            title, body = W._plain(it.get('title'), 80), W._plain(it.get('body'), 900)
            tip = re.sub(r'^\s*(이럴 땐 이렇게\s*[:：]?\s*)', '', W._plain(it.get('tip'), 160))
            if not title or not body: continue
            law = next((c for c in x['cands'] if c['id'] == it.get('law')), None)
            items.append({'title': title, 'body': body, 'tip': tip, 'topic': x.get('topic', ''),
                          'law': {'label': law['label'], 'url': law['url'], 'text': law['text']} if law else None,
                          'src': {'name': x['source'], 'url': x['url'], 'date': x['date'], 'headline': x['title']},
                          '_facts': item_facts(x, law), '_source': x['title'] + ' ' + x['summary']})
        if len(items) < ITEMS[0]: raise RuntimeError('AI가 뉴스를 채우지 못했어요')
        subject = W._plain(out.get('subject'), 80) or items[0]['title']
        intro, outro = W._plain(out.get('intro'), 600), W._plain(out.get('outro'), 400)
        return subject, intro, outro, items

    def check(title, intro, outro, items, no):
        """[{where, line, numbers|words|copy}] — 자료에 없는 숫자, 기업 평가로 읽힐 말, 기사 원문을 그대로 옮긴 부분."""
        problems = []
        every = {'뉴스': [it.get('_facts', {}) for it in items], '호': no, '오늘': datetime.date.today().isoformat(), '소비자상담센터 전화번호': '1372'}
        for where, text in (('메일 제목', title), ('첫인사', intro), ('맺음말', outro)):
            problems += [dict(p, where=where) for p in W.check_text(text, every)]
        for i, it in enumerate(items, 1):
            where = f'{i}번 뉴스'
            text = '\n'.join([it['title'], it['body'], it['tip']])
            problems += [dict(p, where=where) for p in W.check_text(text, it.get('_facts', {}))]
            same = copied(text, it.get('_source', ''))
            if same: problems.append({'where': where, 'line': same, 'copy': True})
        return problems

    def sections():
        since = (datetime.datetime.now() - datetime.timedelta(days=REVIEW_DAYS)).isoformat(timespec='seconds')
        mp = S.mask_personal
        with conn() as db:
            rows = db.execute("""SELECT id,nickname,title,target,rating,likes,comments,pros,summary FROM posts WHERE kind='review' AND hidden=0 AND editor=0 AND created>=?
                ORDER BY likes DESC,comments DESC,id DESC LIMIT 3""", (since,)).fetchall()
            arts = db.execute("SELECT id,title,summary,emoji,category FROM articles WHERE status='published' ORDER BY COALESCE(published_at,created) DESC,id DESC LIMIT 3").fetchall()
        reviews = [{'id': r['id'], 'nick': mask_nick(r['nickname']), 'title': mp(r['title'])[:80], 'target': mp(r['target'])[:40], 'rating': r['rating'] or 0,
                    'likes': r['likes'] or 0, 'line': mp(r['pros'] or r['summary'] or '')[:90], 'url': f"/board/{r['id']}"} for r in rows]
        c = S.current_campaign()
        camp = {'title': c['title'], 'topic': c['topic'], 'intro': ' '.join((c['intro'] or '').split())[:140], 'ends': c['ends'], 'reward': bool(c['reward_on']),
                'url': f"/pick/{c['slug']}"} if c else None
        life = [{'id': a['id'], 'title': a['title'], 'summary': ' '.join((a['summary'] or '').split())[:90], 'emoji': a['emoji'] or '📰', 'category': a['category'],
                 'url': f"/life/{a['id']}"} for a in arts]
        return {'reviews': reviews, 'campaign': camp, 'life': life}

    # ---- 만들기 -----------------------------------------------------------------
    def row_info(r):
        d = dict(r)
        for k, dflt in (('items', []), ('sections', {}), ('problems', [])):
            try: d[k] = json.loads(d[k])
            except (TypeError, ValueError): d[k] = dflt
        return d

    def get(lid=None, no=None):
        with conn() as db:
            r = db.execute('SELECT * FROM letters WHERE ' + ('id=?' if lid is not None else 'no=?'), (lid if lid is not None else no,)).fetchone()
        return row_info(r) if r else None

    def generate(trigger='admin'):
        """{status: made|skip|error, id, no, reason}. 만든 호는 초안(draft)."""
        if not desk.ai_ready(): res = {'status': 'skip', 'reason': 'OpenAI API 키가 없어요'}; log(dict(res, trigger=trigger)); return res
        with conn() as db: no = (db.execute('SELECT MAX(no) FROM letters').fetchone()[0] or 0) + 1
        try:
            news = collect_news()
            title, intro, outro, items = assemble(ask_ai(news, no), news)
        except Skip as e: res = {'status': 'skip', 'reason': str(e)}; log(dict(res, trigger=trigger)); return res
        except RuntimeError as e: res = {'status': 'error', 'reason': str(e)}; log(dict(res, trigger=trigger)); return res
        scrub = lambda t: W.clean_personal(desk.scrub, t)
        title, intro, outro = scrub(title), scrub(intro), scrub(outro)
        for it in items: it.update(title=scrub(it['title']), body=scrub(it['body']), tip=scrub(it['tip']))
        problems = check(title, intro, outro, items, no)
        with conn() as db:
            lid = db.execute('INSERT INTO letters(no,title,intro,outro,items,sections,status,created,updated,check_ok,problems,trigger) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                             (no, title, intro, outro, json.dumps(items, ensure_ascii=False), json.dumps(sections(), ensure_ascii=False), 'draft', stamp(), stamp(),
                              0 if problems else 1, json.dumps(problems, ensure_ascii=False), trigger)).lastrowid
        res = {'status': 'made', 'id': lid, 'no': no, 'reason': '검토 필요 %d곳' % len(problems) if problems else '', 'ok': not problems}
        log(dict(res, trigger=trigger))
        return res

    def save_edit(lid, form):
        L = get(lid)
        if not L: return None
        items = []
        for i, it in enumerate(L['items']):
            if form.get(f'drop{i}'): continue
            it = dict(it, title=W._plain(form.get(f'title{i}', it['title']), 80), body=' '.join(form.get(f'body{i}', it['body']).split())[:1200],
                      tip=W._plain(form.get(f'tip{i}', it['tip']), 160))
            if form.get(f'nolaw{i}'):
                it['law'] = None; it['_facts'] = {k: v for k, v in it.get('_facts', {}).items() if k != '법 조문'}
            if it['title'] and it['body']: items.append(it)
        title = W._plain(form.get('title', L['title']), 80) or L['title']
        intro, outro = ' '.join(form.get('intro', L['intro']).split())[:800], ' '.join(form.get('outro', L['outro']).split())[:600]
        problems = check(title, intro, outro, items, L['no'])
        with conn() as db:
            db.execute('UPDATE letters SET title=?,intro=?,outro=?,items=?,check_ok=?,problems=?,updated=? WHERE id=?',
                       (title, intro, outro, json.dumps(items, ensure_ascii=False), 0 if problems else 1, json.dumps(problems, ensure_ascii=False), stamp(), lid))
        return problems

    # ---- 메일 -----------------------------------------------------------------
    def operator():
        c = S.load_content()
        return {'name': c.get('operator.name') or '소보루', 'address': c.get('operator.address') or '', 'biz_no': c.get('operator.biz_no') or '',
                'email': c.get('operator.email') or ''}

    def logo_url():
        for name in ('img/soboru-logo-orange.png', 'img/soboru-logo.png'):
            if os.path.exists(os.path.join(app.static_folder, name)): return site_url('/static/' + name)
        return ''

    def mail_ctx(L, token):
        tf = lambda name: site_url(f'/static/img/tf/{name}.png')
        icons = [tf(TOPIC_ICON.get(it.get('topic', ''), ('news', ''))[0]) for it in L['items']]
        return {'L': L, 'items': L['items'], 'sec': L['sections'], 'site': site_url(), 'op': operator(), 'logo': logo_url(), 'date': kdate(L.get('sent_at') or L['created']),
                'tf': tf, 'icons': icons, 'mark': site_url('/static/img/soboru-wordmark.png') if os.path.exists(os.path.join(app.static_folder, 'img/soboru-wordmark.png')) else '', 'hero': site_url('/static/img/soboru-character-hero.png'), 'cfg': letter_cfg(),
                'unsub': site_url(f'/letter/unsubscribe/{token}'), 'web': site_url(f"/letter/{L['no']}"), 'name': NAME}

    def email_parts(L, token=UNSUB_MARK):
        ctx = mail_ctx(L, token)
        html = app.jinja_env.get_template('letter_email.html').render(**ctx)
        text = app.jinja_env.get_template('letter_email.txt').render(**ctx)
        return f"[{NAME}] {L['title']}", html, text

    def mail_headers(token):
        return {'List-Unsubscribe': f'<{site_url("/letter/unsubscribe/" + token)}>', 'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'}

    def send_one(to, subject, html, text, token):
        notify.send_email(to, subject, text, html=html, headers=mail_headers(token), from_name=os.getenv('LETTER_FROM_NAME', '').strip() or NAME)

    def send_confirm(email, token):
        ctx = {'site': site_url(), 'op': operator(), 'logo': logo_url(), 'name': NAME,
               'confirm': site_url(f'/letter/confirm/{token}'), 'unsub': site_url(f'/letter/unsubscribe/{token}')}
        html = app.jinja_env.get_template('letter_confirm_email.html').render(**ctx)
        text = (f"{NAME} 구독 신청을 받았어요.\n\n아래 주소를 눌러 메일 주소를 확인하면 구독이 시작돼요.\n{ctx['confirm']}\n\n"
                f"직접 신청하지 않았다면 이 메일은 지워 주세요. 확인하지 않으면 구독되지 않고, 신청 정보는 {PENDING_DAYS}일 뒤 지워져요.\n"
                f"신청 취소: {ctx['unsub']}\n\n{ctx['op']['name']} {ctx['op']['address']}")
        job = lambda: send_one(email, f'[{NAME}] 구독 확인을 눌러 주세요', html, text, token)
        if testing(): job()
        else: threading.Thread(target=lambda: _quiet(job), daemon=True).start()

    def _quiet(job):
        try: job()
        except Exception: pass  # 확인 메일 실패는 사용자가 다시 신청하면 됨

    def send_issue(lid, trigger='admin', wait=False):
        """확인을 마친 구독자에게 보냄. 이미 보낸 사람은 건너뜀. {status: sending|sent|error, reason}"""
        L = get(lid)
        if not L: return {'status': 'error', 'reason': '없는 호예요'}
        if L['status'] == 'sent': return {'status': 'error', 'reason': '이미 보낸 호예요'}
        if not notify.email_ready(): return {'status': 'error', 'reason': '메일 발송 설정(SMTP)이 없어요 (deploy/set-mail.sh)'}
        with conn() as db: db.execute("UPDATE letters SET status='scheduled',updated=? WHERE id=?", (stamp(), lid))
        subject, html, text = email_parts(L)

        def run():
            while True:
                with conn() as db:
                    batch = db.execute("""SELECT id,email,token FROM letter_subscribers s WHERE status='active'
                        AND NOT EXISTS(SELECT 1 FROM letter_sends x WHERE x.letter_id=? AND x.sub_id=s.id) ORDER BY id LIMIT ?""", (lid, SEND_BATCH)).fetchall()
                if not batch: break
                for s in batch:
                    try:
                        send_one(s['email'], subject, html.replace(UNSUB_MARK, s['token']), text.replace(UNSUB_MARK, s['token']), s['token'])
                        st, detail = 'sent', ''
                    except Exception as e:  # 한 명 실패는 기록만 하고 계속
                        st, detail = 'failed', str(e)[:200]
                    with conn() as db:
                        db.execute('INSERT OR REPLACE INTO letter_sends(letter_id,sub_id,status,detail,at) VALUES(?,?,?,?,?)', (lid, s['id'], st, detail, stamp()))
                if len(batch) == SEND_BATCH and SEND_PAUSE and not testing(): time.sleep(SEND_PAUSE)
            with conn() as db:
                n = dict(db.execute('SELECT status,COUNT(*) FROM letter_sends WHERE letter_id=? GROUP BY status', (lid,)).fetchall())
                db.execute("UPDATE letters SET status='sent',sent_at=COALESCE(sent_at,?),sent_count=?,failed=?,updated=? WHERE id=?",
                           (stamp(), n.get('sent', 0), n.get('failed', 0), stamp(), lid))
            log({'status': 'sent', 'no': L['no'], 'trigger': trigger, 'reason': f"{n.get('sent', 0)}명에게 보냄" + (f", 실패 {n['failed']}명" if n.get('failed') else '')})

        if wait or testing(): run(); return {'status': 'sent', 'reason': ''}
        threading.Thread(target=run, daemon=True).start()
        return {'status': 'sending', 'reason': ''}

    def cleanup():
        old = (datetime.datetime.now() - datetime.timedelta(days=PENDING_DAYS)).isoformat(timespec='seconds')
        with conn() as db: db.execute("DELETE FROM letter_subscribers WHERE status='pending' AND COALESCE(asked,created)<?", (old,))

    def weekly(today=None, force=False):
        """매일 아침 예약 작업: 고른 주기에 맞는 날이면 한 호를 만들고, 자동 보내기가 켜져 있고 검사를 통과하면 보냄."""
        cfg = settings(); today = today or datetime.date.today()
        cleanup()
        if not force and cfg['freq'] == 'weekly' and today.weekday() != cfg['day']: return {'status': 'not_today', 'reason': f"보내는 날은 {DAYS[cfg['day']]}이에요"}
        if not force and cfg['freq'] == 'weekdays' and today.weekday() >= 5: return {'status': 'not_today', 'reason': '주말에는 쉬어요'}
        start = (today - datetime.timedelta(days=today.weekday())) if cfg['freq'] == 'weekly' else today
        with conn() as db: old = db.execute('SELECT id FROM letters WHERE created>=? ORDER BY id DESC', (start.isoformat(),)).fetchone()
        if old and not force: return {'status': 'exists', 'id': old['id'], 'reason': '이번 주 호가 이미 있어요' if cfg['freq'] == 'weekly' else '오늘 호가 이미 있어요'}
        r = generate('weekly')
        if r['status'] != 'made': return r
        if not cfg['auto']: return dict(r, sent=False, reason=(r['reason'] + ' · ' if r['reason'] else '') + '자동 보내기가 꺼져 있어 운영자를 기다려요')
        if not r['ok']: log({'status': 'held', 'no': r['no'], 'trigger': 'weekly', 'reason': '검토 필요가 있어 자동으로 보내지 않았어요'}); return dict(r, sent=False)
        s = send_issue(r['id'], 'weekly', wait=True)
        return dict(r, sent=s['status'] == 'sent', reason=s['reason'] or r['reason'])

    def counts():
        with conn() as db:
            return dict(db.execute('SELECT status,COUNT(*) FROM letter_subscribers GROUP BY status').fetchall())

    # ---- 공개 화면 -----------------------------------------------------------
    def body_lines(text):
        # 설명은 한 덩어리로 오므로 문장 2~3개씩 문단으로 나눔
        sents = [s for s in re.split(r'(?<=[.!?])\s+', (text or '').strip()) if s]
        return [' '.join(sents[i:i + 2]) for i in range(0, len(sents), 2)] or [text]
    def letter_cfg():
        # 화면 문구용: when='평일 아침마다'·'매일 아침'·'매주 월요일 아침', span='오늘'·'이번 주'
        cfg = settings(); day = DAYS[cfg['day']]
        when = {'weekdays': '평일 아침마다', 'daily': '매일 아침', 'weekly': f'매주 {day} 아침'}[cfg['freq']]
        return dict(cfg, day_name=day, when=when, span='이번 주' if cfg['freq'] == 'weekly' else '오늘')
    app.jinja_env.globals.update(letter_counts=counts, letter_kdate=kdate, letter_cfg=letter_cfg, letter_icon=lambda t: TOPIC_ICON.get(t or '', ('', ''))[1])
    app.jinja_env.filters['letter_paras'] = body_lines

    @app.route('/letter')
    def letter_home():
        with conn() as db:
            rows = [row_info(r) for r in db.execute("SELECT * FROM letters WHERE status='sent' ORDER BY no DESC LIMIT 60")]
        return render_template('letter.html', rows=rows, state=request.args.get('s', ''))

    @app.route('/letter/<int:no>')
    def letter_issue(no):
        L = get(no=no)
        if not L or (L['status'] != 'sent' and not S.admin_active()): abort(404)
        with conn() as db:
            near = {k: db.execute(f"SELECT no,title FROM letters WHERE status='sent' AND no{op}? ORDER BY no {o} LIMIT 1", (no,)).fetchone()
                    for k, op, o in (('prev', '<', 'DESC'), ('next', '>', 'ASC'))}
        return render_template('letter_issue.html', L=L, near=near)

    def back(code):
        return redirect(url_for('letter_home', s=code) + '#sub')

    @app.route('/letter/subscribe', methods=['POST'])
    def letter_subscribe():
        f = request.form
        if f.get('website'): return back('check')  # 사람 눈에 안 보이는 칸을 채우면 자동 등록 프로그램
        email = (f.get('email') or '').strip().lower()
        if len(email) > 254 or not EMAIL_RE.match(email): return back('email')
        if not f.get('agree'): return back('consent')
        since = (datetime.datetime.now() - datetime.timedelta(minutes=10)).isoformat(timespec='seconds')
        with conn() as db:
            n = db.execute("SELECT COUNT(*) FROM login_attempts WHERE kind='letter' AND ip_hash=? AND created>=?", (S.ip_hash(), since)).fetchone()[0]
            if n >= SUB_LIMIT: return back('limit')
            db.execute("INSERT INTO login_attempts(kind,ip_hash,created) VALUES('letter',?,?)", (S.ip_hash(), stamp()))
        if not notify.email_ready(): return back('nomail')
        place = (f.get('place') or '')[:20]
        with conn() as db:
            row = db.execute('SELECT * FROM letter_subscribers WHERE email IN (?,?)', (email, gone_email(email))).fetchone()
            if row and row['status'] == 'active': return back('check')  # 이미 구독 중이어도 같은 말 (주소가 있는지 알려 주지 않음)
            if row and row['status'] == 'pending' and (row['asked'] or '') > since: return back('check')  # 확인 메일은 10분에 한 번
            token = secrets.token_urlsafe(24)
            if row:
                db.execute("UPDATE letter_subscribers SET email=?,token=?,status='pending',asked=?,ip_hash=?,place=?,unsubscribed=NULL WHERE id=?",
                           (email, token, stamp(), S.ip_hash(), place, row['id']))
            else:
                db.execute("INSERT INTO letter_subscribers(email,token,status,created,ip_hash,asked,place) VALUES(?,?,'pending',?,?,?,?)",
                           (email, token, stamp(), S.ip_hash(), stamp(), place))
        try: send_confirm(email, token)
        except Exception: return back('fail')
        return back('check')

    def msg(kind, **kw):
        return render_template('letter_msg.html', kind=kind, **kw)

    @app.route('/letter/confirm/<token>')
    def letter_confirm(token):
        with conn() as db:
            row = db.execute('SELECT * FROM letter_subscribers WHERE token=?', (token[:64],)).fetchone()
            if not row or row['status'] == 'unsubscribed': return msg('bad'), 404
            if row['status'] == 'active': return msg('already')
            db.execute("UPDATE letter_subscribers SET status='active',confirmed=? WHERE id=?", (stamp(), row['id']))
        return msg('confirmed', email=notify.mask(row['email']))

    @app.route('/letter/unsubscribe/<token>', methods=['GET', 'POST'])
    def letter_unsubscribe(token):
        # 메일 속 링크 한 번(GET)으로, 메일 앱의 '구독 취소' 버튼(RFC 8058 POST)으로도 바로 해지. 이메일 주소는 지움
        with conn() as db:
            row = db.execute('SELECT * FROM letter_subscribers WHERE token=?', (token[:64],)).fetchone()
            if not row: return msg('bad')
            if row['status'] != 'unsubscribed':
                db.execute("UPDATE letter_subscribers SET status='unsubscribed',unsubscribed=?,email=? WHERE id=?",
                           (stamp(), row['email'] if row['email'].startswith('x:') else gone_email(row['email']), row['id']))
        if request.method == 'POST': return 'unsubscribed', 200
        return msg('unsubscribed')

    # 메일 앱이 보내는 한 번 클릭 해지(POST)는 우리 화면에서 온 게 아니라 CSRF 토큰이 없음 → 이 주소만 확인을 건너뜀 (토큰을 아는 사람만 해지 가능)
    funcs = app.before_request_funcs.setdefault(None, [])
    for i, fn in enumerate(funcs):
        if fn.__name__ == 'protect':
            def protect(_orig=fn):
                if request.path.startswith('/letter/unsubscribe/'): return None
                return _orig()
            funcs[i] = protect

    # 사이트맵에 크로와상(목록·보낸 호)을 더함
    if 'sitemap_xml' in app.view_functions:
        old_map = app.view_functions['sitemap_xml']
        def sitemap_xml():
            resp = old_map()
            with conn() as db: rows = db.execute("SELECT no,sent_at FROM letters WHERE status='sent' ORDER BY no DESC LIMIT 500").fetchall()
            base = S.canonical_url('')
            extra = ''.join('<url><loc>%s</loc>%s</url>' % (base + u, '<lastmod>%s</lastmod>' % d if d else '')
                            for u, d in [('/letter', None)] + [(f"/letter/{r['no']}", (r['sent_at'] or '')[:10]) for r in rows])
            resp.set_data(resp.get_data(as_text=True).replace('</urlset>', extra + '</urlset>'))
            return resp
        app.view_functions['sitemap_xml'] = sitemap_xml

    # ---- 관리자 화면 -----------------------------------------------------------
    def job_state(): return setting('letter_job', {})

    def admin_ctx():
        with conn() as db:
            rows = [row_info(r) for r in db.execute('SELECT * FROM letters ORDER BY no DESC LIMIT 40')]
            subs = db.execute("SELECT id,email,status,created,confirmed,unsubscribed,place FROM letter_subscribers ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END,id DESC LIMIT 200").fetchall()
        return dict(rows=rows, subs=subs, counts=counts(), cfg=settings(), days=DAYS, freqs=FREQS, ai_ready=desk.ai_ready(), naver_ready=bool(naver()) and naver()['ready'](),
                    mail_ready=notify.email_ready(), logs=setting('letter_log', [])[:10])

    @app.route('/admin/letter', methods=['GET', 'POST'])
    @S.admin_only
    def admin_letter():
        if request.method == 'POST':
            if not desk.ai_ready(): flash('OpenAI API 키가 없어서 레터를 만들 수 없어요.'); return redirect(url_for('admin_letter'))
            if testing(): return made(generate('admin'))
            j = job_state()
            if j.get('state') == 'running' and j.get('at', '') > (datetime.datetime.now() - datetime.timedelta(minutes=5)).isoformat():
                flash('이번 호를 만들고 있어요. 잠시 뒤 다시 눌러 주세요.'); return redirect(url_for('admin_letter_job'))
            put('letter_job', {'state': 'running', 'at': stamp()})
            def run():
                try: r = generate('admin')
                except Exception as e: r = {'status': 'error', 'reason': f'레터를 만들지 못했어요 ({type(e).__name__})'}
                put('letter_job', dict(r, state='done', at=stamp()))
            threading.Thread(target=run, daemon=True).start()  # AI가 1분 넘게 걸릴 수 있어 뒤에서
            return redirect(url_for('admin_letter_job'))
        return render_template('admin_letter.html', **admin_ctx())

    def made(r):
        if r['status'] == 'made':
            flash(f"{r['no']}호 초안을 만들었어요. 내용을 확인하고 보내 주세요." + (f" ({r['reason']})" if r.get('reason') else ''))
            return redirect(url_for('admin_letter_edit', lid=r['id']))
        flash(('지금은 만들 수 없어요: ' if r['status'] == 'skip' else '레터를 만들지 못했어요: ') + r.get('reason', ''))
        return redirect(url_for('admin_letter'))

    @app.route('/admin/letter/job')
    @S.admin_only
    def admin_letter_job():
        j = job_state()
        if j.get('state') == 'done': put('letter_job', {}); return made(j)
        if j.get('state') != 'running': return redirect(url_for('admin_letter'))
        return render_template('admin_letter.html', waiting=True, **admin_ctx())

    @app.route('/admin/letter/settings', methods=['POST'])
    @S.admin_only
    def admin_letter_settings():
        day, freq = request.form.get('day', type=int), request.form.get('freq', '')
        put('letter', {'auto': 1 if request.form.get('auto') else 0, 'day': day if day in range(7) else 0, 'freq': freq if freq in FREQS else 'weekdays'})
        flash('레터 설정을 저장했어요.')
        return redirect(url_for('admin_letter'))

    @app.route('/admin/letter/subscribers', methods=['POST'])
    @S.admin_only
    def admin_letter_subs():
        sid = request.form.get('id', type=int)
        with conn() as db:
            row = db.execute('SELECT * FROM letter_subscribers WHERE id=?', (sid,)).fetchone()
            if row and row['status'] != 'unsubscribed':
                db.execute("UPDATE letter_subscribers SET status='unsubscribed',unsubscribed=?,email=? WHERE id=?",
                           (stamp(), row['email'] if row['email'].startswith('x:') else gone_email(row['email']), sid))
                flash(f"{notify.mask(row['email'])} 구독을 해지했어요.")
        return redirect(url_for('admin_letter') + '#subs')

    @app.route('/admin/letter/<int:lid>', methods=['GET', 'POST'])
    @S.admin_only
    def admin_letter_edit(lid):
        L = get(lid)
        if not L: abort(404)
        if request.method == 'POST':
            act = request.form.get('act', 'save')
            if act == 'delete':
                if L['status'] == 'sent': flash('보낸 호는 지울 수 없어요.')
                else:
                    with conn() as db: db.execute('DELETE FROM letters WHERE id=?', (lid,)); db.execute('DELETE FROM letter_sends WHERE letter_id=?', (lid,))
                    flash(f"{L['no']}호 초안을 지웠어요."); return redirect(url_for('admin_letter'))
                return redirect(url_for('admin_letter_edit', lid=lid))
            if L['status'] == 'draft' and act in ('save', 'test', 'send'):
                problems = save_edit(lid, request.form)
                if act == 'save': flash('저장했어요.' + (f' 검토 필요 {len(problems)}곳이 있어요.' if problems else ' 숫자·문장 검사를 통과했어요.'))
                L = get(lid)
            if act == 'test':
                to = (request.form.get('test_to') or '').strip()
                if not EMAIL_RE.match(to): flash('테스트 메일을 받을 주소를 바르게 적어 주세요.')
                elif not notify.email_ready(): flash('메일 발송 설정(SMTP)이 없어 보낼 수 없어요.')
                else:
                    subject, html, text = email_parts(L, 'test')
                    try: send_one(to, '[테스트] ' + subject, html, text, 'test'); flash(f'{to}로 테스트 메일을 보냈어요.')
                    except Exception as e: flash(f'테스트 메일을 보내지 못했어요 ({type(e).__name__})')
            elif act == 'send':
                if L['status'] == 'sent': flash('이미 보낸 호예요.')
                elif L['problems'] and not request.form.get('ack'):
                    flash(f"검토 필요 {len(L['problems'])}곳이 있어 보내지 않았어요. 고치거나, 직접 확인했다면 '직접 확인했어요'에 체크하고 보내 주세요.")
                else:
                    r = send_issue(lid, 'admin')
                    flash({'sent': '구독자에게 보냈어요.', 'sending': '보내기 시작했어요. 구독자가 많으면 몇 분 걸려요.'}.get(r['status'], '보내지 못했어요: ' + r['reason']))
            return redirect(url_for('admin_letter_edit', lid=lid))
        subject, html, _ = email_parts(L, 'preview')
        html = html.replace(site_url('/static/'), request.host_url.rstrip('/') + '/static/')  # 미리보기 그림은 지금 서버에서 (운영 메일은 운영 주소)
        with conn() as db:
            sends = dict(db.execute('SELECT status,COUNT(*) FROM letter_sends WHERE letter_id=? GROUP BY status', (lid,)).fetchall())
        return render_template('admin_letter_edit.html', L=L, preview=html, subject=subject, mail_ready=notify.email_ready(), counts=counts(), sends=sends,
                               test_to=os.getenv('ADMIN_ALERT_EMAIL', '').split(',')[0].strip())

    app.extensions['soboru_letter'] = {'generate': generate, 'weekly': weekly, 'send': send_issue, 'collect': collect_news, 'settings': settings,
                                      'email_parts': email_parts, 'get': get, 'check': check, 'sections': sections}


def main(argv):
    """서버 예약 작업: python soboru_letter.py weekly [--force] [--dry]. --dry는 뉴스·법 조문 후보만 모아 보여 줌(AI·저장·발송 없음)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import app as site
    import soboru_letter as mod  # app.py가 붙인 모듈 (이 파일을 바로 부르면 __main__이라 Skip이 다른 클래스)
    L = site.app.extensions['soboru_letter']
    with site.app.app_context():
        if '--dry' in argv:
            try: print(json.dumps(L['collect'](), ensure_ascii=False, indent=1)[:4000])
            except mod.Skip as e: print('건너뜀:', e)
            print('설정:', L['settings']())
            return 0
        if not argv or argv[0] != 'weekly':
            print(main.__doc__); return 1
        r = L['weekly'](force='--force' in argv)
    print(r.get('status'), r.get('no', ''), '보냄' if r.get('sent') else '', r.get('reason', ''))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
