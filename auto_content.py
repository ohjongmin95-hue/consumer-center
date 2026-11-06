"""소보루 자동 콘텐츠 (운영자 2026-11-06: 정해진 시간마다 서버에서 카드뉴스·릴스를 만들어 보관함에 넣고 텔레그램으로 알림).

deploy/soboru-content.timer가 아침 9시·오후 1시·저녁 9시쯤 `python -m auto_content`를 부른다. 한 번에 AUTO_CONTENT_PER_RUN편(기본 3).
- 소재 (운영자 2026-11-06: 터진 것 위주로, 커뮤니티 것도, 조사한 분야별 소재도 — TOPIC_QUERIES·AUTO_CONTENT_RSS): 네이버 뉴스 댓글 많은 기사와 커뮤니티 인기글을 번갈아 먼저 봄. 커뮤니티 글은 사실 확인 전이라
  같은 주제의 뉴스 기사를 찾았을 때만 그 기사로 만듦. 없으면 최근 게시된 매거진 기사 중 조회수가 큰 순서. 이미 만든 것은 건너뜀.
- 글: 매거진 AI 도움의 카드뉴스 지시문(mag_assist)을 그대로 씀. 기사에 없는 숫자가 들어간 답, 다루지 않을 소재는 버리고 다음으로 넘어감.
- 분석: 왜 터졌는지 주제·가치·포맷·후킹·원고 5가지로 나눠 텔레그램 알림에 적음.
- 표지 (운영자 2026-11-06: AI 말고 실사 이미지): 언스플래시에서 상황에 맞는 인물 실사 사진을 찾음(놀라는 표정 등, AI는 검색어만 짬).
  못 찾으면 기사 사진(직접 올린 사진 또는 언스플래시), 그것도 없으면 글자 표지. 언스플래시 사진은 캡션에 사진가를 밝힘.
- 카드: 1080x1350 PNG. 릴스: 1080x1920 전체 화면(위아래 띠 없음), 무음, 장면을 PNG로 그려 mag_maker.build로 합침.
- 저장: 만든 것 보관함(maker='auto'). 게시는 하지 않음. 끝나면 텔레그램으로 알림.
브라우저 없이 그려서 관리자 화면(static/maker.js)의 소보루 디자인과 조금 다를 수 있음.

쓰는 법: python -m auto_content [--dry] [--article 번호]   (--dry: AI·저장 없이 터진 소재와 고를 기사만 보여 줌)
"""
import datetime
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, CARD_H, REEL_H = 1080, 1350, 1920
X, TW = 90, 900
OR, ORD, BR = '#EF920E', '#CE6719', '#652D1C'
PAPER = '#FAFAF7'
FONT_DIR = Path(__file__).resolve().parent / 'static' / 'fonts' / 'pretendard'
LOGO = Path(__file__).resolve().parent / 'static' / 'img' / 'soboru-wordmark.png'
WEIGHTS = {500: 'Medium', 700: 'Bold', 800: 'ExtraBold', 900: 'Black'}
SITE = 'consumerjebo.co.kr'
LOOKBACK_DAYS = 3
PEOPLE_ASK = ('\n[사람 표지] JSON에 "people_query"도 넣는다: 표지에 쓸 언스플래시 검색어, 영어 3~5단어. 기사 상황에 맞는 평범한 사람의 표정이나 행동을 '
              '구체적으로 쓰고 "korean"을 넣는다(예: "korean woman surprised phone", "korean man shocked receipt", "korean couple worried bills"). '
              '기사의 당사자로 오해할 만한 장면, 범죄·사고 장면, 실존 인물, 회사·브랜드 이름은 쓰지 않는다.\n'
              '[왜 터졌나] JSON에 "why_hot"도 넣는다: {"topic": 주제, "value": 사람들이 얻는 가치, "format": 어울리는 형식, "hook": 첫 문장, "script": 장면 순서}, 각 40자 안.\n'
              '[안 다룰 소재] 사망·범죄 피해의 자세한 내용, 개인 사생활·연예 폭로, 정치 공방, 특정 종목 매수·매도 권유, 확인되지 않은 소문이 중심이면 "skip": "이유"만 답한다.')
PERSON = re.compile(r'\b(person|people|woman|women|man|men|girl|boy|guy|lady|couple|face|portrait|student|worker)\b', re.I)
HOT_SECTIONS = ['https://news.naver.com/section/102', 'https://news.naver.com/section/103']  # 사회·생활 (경제는 mag_maker)
HOT_SKIP = re.compile(r'ㅇㅎ|ㅎㅂ|후방|19금|\[(?:인사|부고|게시판|알림|포토|화보)|성폭|살해|숨져|사망|시신|열애|불륜|이혼|탄핵|여당|야당|대통령')
HOT_NOISE = re.compile(r'\[[^\]]{1,8}\]|\.(?:jpg|gif|png|mp4)|\([^)]{0,12}\)|[^\w\s가-힣]', re.I)
COMMUNITY_MIN = 3000
COMMUNITY_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36'
# robots.txt가 허용한 인기글 목록만 (네이트판·에펨코리아는 전체 금지, 클리앙은 정렬 주소 금지라 뺌)
COMMUNITIES = [('뽐뿌', 'https://www.ppomppu.co.kr/zboard/zboard.php?id=freeboard&hotlist_flag=999', '<tr align="center" class="baseList ',
                r'class="baseList-title\s*"\s+href="[^"]+"[^>]*>(.*?)</a>', r'baseList-views"[^>]*>([\d,]+)'),
               ('보배드림', 'https://www.bobaedream.co.kr/list?code=best', '<tr', r'class="bsubject"[^>]*>(.*?)</a>', r'<td class="count"[^>]*>\s*([\d,]+)'),
               ('더쿠', 'https://theqoo.net/hot', '<tr', r'<td class="title">\s*<a href="[^"]+"[^>]*>(.*?)</a>', r'<td class="m_no">\s*([\d,]+)\s*</td>\s*</tr>|<td class="m_no">\s*([\d,]+)'),
               ('루리웹', 'https://bbs.ruliweb.com/best/humor_only', '<tr class="table_body', r'<strong class="text_over">(.*?)</strong>', r'class="hit">\s*([\d,]+)'),
               ('디시', 'https://gall.dcinside.com/board/lists/?id=dcbest', '<tr class="ub-content', r'gall_tit[^>]*>\s*<a\s+href="[^"]+"[^>]*>(.*?)</a>', r'gall_count">([\d,]+)')]
# 소재 (운영자 2026-11-06: 조사한 소재로 왜 안 만드냐) — 소비자에게 바로 닿는 분야별 최신 뉴스. 네이버 뉴스 검색(최신순).
# AUTO_CONTENT_RSS 에 RSS 주소(쉼표로 여러 개)를 넣으면 그 글도 소재로 씀.
TOPIC_QUERIES = [('소비자·환불', '소비자 환불'), ('소비자·환불', '소비자 피해'), ('공정위·제재', '공정위 제재'), ('공정위·제재', '과징금 부과'),
                 ('리콜·안전', '리콜'), ('가격·요금', '가격 인상'), ('다크패턴·약관', '다크패턴')]
SCENE_SEC = {'cover': 3.0, 'body': 4.5, 'quote': 4.0, 'last': 4.5}


def font(weight, size):
    return ImageFont.truetype(str(FONT_DIR / f'Pretendard-{WEIGHTS[weight]}.otf'), size)


def plain(text):
    return re.sub(r'\*\*', '', str(text or ''))


def wrap(draw, text, fnt, width):
    """한 문단을 줄로 나눔. 띄어쓰기에서 끊고, 한 낱말이 너무 길면 글자에서 끊음."""
    lines = []
    for para in str(text or '').split('\n'):
        cur = ''
        for word in para.split(' '):
            trial = (cur + ' ' + word) if cur else word
            if draw.textlength(plain(trial), font=fnt) <= width:
                cur = trial
                continue
            if cur: lines.append(cur)
            cur = ''
            for ch in word:
                if draw.textlength(plain(cur + ch), font=fnt) > width and cur:
                    lines.append(cur)
                    cur = ''
                cur += ch
        lines.append(cur)
    return lines


def draw_rich(draw, x, y, line, size, ink, bold_ink, state):
    """**굵게** 표시를 귤색 굵은 글씨로. state는 줄을 넘어가는 굵게 표시를 기억."""
    for i, part in enumerate(line.split('**')):
        if i: state['bold'] = not state['bold']
        if not part: continue
        f = font(800 if state['bold'] else 500, size)
        draw.text((x, y), part, font=f, fill=bold_ink if state['bold'] else ink)
        x += draw.textlength(part, font=f)


def logo(canvas, white, y, height=38):
    try:
        mark = Image.open(LOGO).convert('RGBA')
    except OSError:
        return
    mark = mark.resize((round(mark.width * height / mark.height), height), Image.LANCZOS)
    ink = Image.new('RGBA', mark.size, '#FFFFFF' if white else BR)
    ink.putalpha(mark.getchannel('A'))
    canvas.alpha_composite(ink, ((W - mark.width) // 2, y))


def cover_fit(img, h):
    r = max(W / img.width, h / img.height)
    im = img.resize((round(img.width * r), round(img.height * r)), Image.LANCZOS)
    left, top = (im.width - W) // 2, (im.height - h) // 2
    return im.crop((left, top, left + W, top + h))


def gradient(canvas, y0, y1, a0, a1):
    h = max(1, y1 - y0)
    strip = Image.new('L', (1, h))
    for i in range(h): strip.putpixel((0, i), round(255 * (a0 + (a1 - a0) * i / h)))
    layer = Image.new('RGBA', (W, h), (0, 0, 0, 0))
    layer.putalpha(strip.resize((W, h)))
    canvas.alpha_composite(layer, (0, y0))


def page_no(draw, n, total, ink):
    if total < 2: return
    text = f'{n} / {total}'
    f = font(700, 26)
    draw.text((990 - draw.textlength(text, font=f), 54), text, font=f, fill=ink)


def fit_font(draw, text, weight, size, width, least=28):
    while size > least and draw.textlength(plain(text), font=font(weight, size)) > width: size -= 2
    return font(weight, size), size


def draw_cover(canvas, s, img, n, total, h):
    if img is not None:
        canvas.paste(cover_fit(img.convert('RGB'), h))
    else:
        canvas.paste(Image.new('RGB', (W, h), '#3a2a20'))
    gradient(canvas, 0, 260, .3, 0)
    gradient(canvas, round(h * .36), h, 0, .86)
    logo(canvas, True, 46)
    draw = ImageDraw.Draw(canvas)
    page_no(draw, n, total, '#FFFFFF')
    size = 84 if h == CARD_H else 92
    f = font(900, size)
    lines = wrap(draw, s.get('title'), f, TW)[:4]
    lh = round(size * 1.24)
    bottom = h - (110 if h == CARD_H else 300)  # 릴스는 인스타 아래 글자에 가리지 않게
    y = bottom - lh * len(lines)
    for i, line in enumerate(lines): draw.text((X, y + i * lh), line, font=f, fill='#FFFFFF')
    if s.get('sub'):
        nf, nsize = fit_font(draw, s['sub'], 900, 64, TW - 60)
        pill_w = draw.textlength(s['sub'], font=nf) + 64
        top = y - nsize - 72
        draw.rounded_rectangle((X, top, X + pill_w, top + nsize + 44), 22, fill=OR)
        draw.text((X + 32, top + 14), s['sub'], font=nf, fill='#FFFFFF')
        y = top
    if s.get('tag'):
        draw.text((X + 4, y - 50), s['tag'], font=font(800, 26), fill='#FFFFFF')


def foot(draw, h):
    y = h - 86
    draw.rectangle((X, y, X + TW, y + 2), fill='#111111')
    f = font(700, 26)
    draw.text((X, y + 20), '소보루 매거진', font=f, fill=ORD)
    draw.text((990 - draw.textlength(SITE, font=f), y + 20), SITE, font=f, fill=ORD)


def draw_body(canvas, s, n, total, h):
    canvas.paste(Image.new('RGB', (W, h), PAPER))
    logo(canvas, False, 46)
    draw = ImageDraw.Draw(canvas)
    page_no(draw, n, total, ORD)
    foot(draw, h)
    area_top, area_bottom = 160, h - 120
    avail = area_bottom - area_top
    tsize = 72 if h == CARD_H else 84
    tf = font(900, tsize)
    tlines = wrap(draw, s.get('title'), tf, TW)
    tlh = round(tsize * 1.22)
    nf, nsize = (None, 0)
    if s.get('sub'): nf, nsize = fit_font(draw, s['sub'], 900, 120 if h == CARD_H else 140, TW)
    head = (76 if s.get('tag') else 0) + (nsize + 28 if nf else 0) + tlh * len(tlines)
    start = 52 if h == CARD_H else 60
    for bsize in range(start, 32, -2):
        bf = font(500, bsize)
        lines = wrap(draw, s.get('items'), bf, TW)
        blh = round(bsize * 1.62)
        total_h = head + 44 + sum(blh if l else round(blh * .55) for l in lines)
        if total_h <= avail: break
    y = area_top + max(0, (avail - total_h) * (.3 if h == CARD_H else .42))
    if s.get('tag'):
        draw.text((X, y), s['tag'], font=font(800, 30), fill=ORD)
        y += 76
    if nf:
        draw.text((X, y), s['sub'], font=nf, fill=OR)
        y += nsize + 28
    for line in tlines:
        draw.text((X, y), line, font=tf, fill='#111111')
        y += tlh
    y += 44
    state = {'bold': False}
    for line in lines:
        if not line:
            y += round(blh * .55)
            continue
        draw_rich(draw, X, y, line, bsize, '#2A2A2A', ORD, state)
        y += blh


def draw_quote(canvas, s, n, total, h):
    canvas.paste(Image.new('RGB', (W, h), '#000000'))
    logo(canvas, True, 46)
    draw = ImageDraw.Draw(canvas)
    page_no(draw, n, total, '#EEEEEE')
    size = 80
    f = font(900, size)
    lines = wrap(draw, s.get('title'), f, TW)[:6]
    lh = round(size * 1.3)
    y = max(420, (h - lh * len(lines)) // 2)
    draw.text((X - 8, y - 260), '“', font=font(900, 240), fill=OR)
    for line in lines:
        draw.text((X, y), line, font=f, fill='#FFFFFF')
        y += lh
    if s.get('sub'): draw.text((X, y + 40), '— ' + s['sub'], font=font(700, 42), fill='#EEEEEE')


def draw_last(canvas, s, n, total, h):
    canvas.paste(Image.new('RGB', (W, h), PAPER))
    logo(canvas, False, 46)
    draw = ImageDraw.Draw(canvas)
    page_no(draw, n, total, ORD)
    tf = font(900, 76)
    tlines = wrap(draw, s.get('title') or '헷갈리면 저장해 두세요', tf, TW)
    tlh = 96
    tips = [t for t in str(s.get('items') or '').split('\n') if t.strip()][:4]
    boxes = [wrap(draw, t, font(700, 44), TW - 170) for t in tips]
    heights = [max(150, len(b) * 60 + 70) for b in boxes]
    block = 96 + tlh * len(tlines) + 56 + sum(heights) + 26 * max(0, len(heights) - 1)
    y = max(150, (h - 120 - block) // 2)
    tag = s.get('tag') or '이것만 챙겨요'
    tag_f = font(800, 32)
    tag_w = draw.textlength(tag, font=tag_f)
    draw.rounded_rectangle((X, y, X + tag_w + 36, y + 56), 14, fill=OR)
    draw.text((X + 18, y + 8), tag, font=tag_f, fill='#FFFFFF')
    y += 96
    for line in tlines:
        w = draw.textlength(line, font=tf)
        draw.rectangle((X - 8, y + 44, X + w + 8, y + 84), fill='#FFD99E')
        draw.text((X, y), line, font=tf, fill='#111111')
        y += tlh
    y += 56
    for k, (box, bh) in enumerate(zip(boxes, heights)):
        draw.rounded_rectangle((X, y, X + TW, y + bh), 28, fill='#FFFFFF', outline='#EADFCF', width=3)
        cy = y + bh // 2
        draw.ellipse((X + 28, cy - 34, X + 96, cy + 34), fill=OR)
        num = str(k + 1)
        nf = font(900, 36)
        draw.text((X + 62 - draw.textlength(num, font=nf) / 2, cy - 23), num, font=nf, fill='#FFFFFF')
        ty = cy - len(box) * 30
        for line in box:
            draw.text((X + 120, ty), line, font=font(700, 44), fill='#111111')
            ty += 60
        y += bh + 26
    if s.get('sub'): draw.text((X, h - 110), s['sub'], font=font(700, 26), fill=ORD)


def render(s, img, n, total, h):
    """장 하나를 그림. s: {design, tag, title, sub, items}, img: 표지 그림(PIL) 또는 None."""
    canvas = Image.new('RGBA', (W, h), PAPER)
    design = s.get('design')
    if design == 'cover': draw_cover(canvas, s, img, n, total, h)
    elif design == 'quote': draw_quote(canvas, s, n, total, h)
    elif design == 'last': draw_last(canvas, s, n, total, h)
    else: draw_body(canvas, s, n, total, h)
    return canvas.convert('RGB')


def outro_png(path):
    """릴스 끝 귤색 화면의 글씨 판(투명)."""
    canvas = Image.new('RGBA', (W, REEL_H), (0, 0, 0, 0))
    logo(canvas, True, 620, 108)
    draw = ImageDraw.Draw(canvas)
    f = font(800, 46)
    text = '소보루 매거진'
    draw.text(((W - draw.textlength(text, font=f)) / 2, 780), text, font=f, fill='#FFFFFF')
    f = font(700, 44)
    text = '억울한 소비자 피해, 제보해 주세요'
    w = draw.textlength(text, font=f)
    draw.rounded_rectangle(((W - w) / 2 - 36, 1150, (W + w) / 2 + 36, 1250), 44, fill='#FFFFFF')
    draw.text(((W - w) / 2, 1174), text, font=f, fill='#111111')
    f = font(900, 44)
    w = draw.textlength(SITE, font=f)
    draw.rectangle(((W - w) / 2 - 36, 1272, (W + w) / 2 + 36, 1372), fill='#FFFFFF', outline='#111111', width=4)
    draw.text(((W - w) / 2, 1296), SITE, font=f, fill='#111111')
    canvas.save(path, 'PNG')


def clear_png(path):
    Image.new('RGBA', (W, REEL_H), (0, 0, 0, 0)).save(path, 'PNG')


def scenes_for(plan, folder):
    """전체 화면 장면 PNG를 만들고 mag_maker.build가 쓰는 장면 목록을 돌려줌. 무음."""
    return [{'kind': 'image', 'file': Path(folder) / f's{i}.png', 'start': 0, 'dur': SCENE_SEC.get(s.get('design'), 4.5),
             'speed': 1, 'layout': 'clean', 'png': Path(folder) / 'clear.png', 'audio': False} for i, s in enumerate(plan)]


def hot_news(limit=25):
    """네이버 경제·사회·생활 기사 중 댓글 많은 순. [{url, title, comments}]"""
    from concurrent.futures import ThreadPoolExecutor
    import mag_maker as M
    def page(u):
        try: return M.naver_section_articles(M._get(u))
        except Exception: return []
    with ThreadPoolExecutor(8) as ex: pages = list(ex.map(page, [M.NAVER_SECTION] + M.NAVER_SUBS + HOT_SECTIONS))
    arts, seen = [], set()
    for pg in pages:
        for x in pg:
            if (x[0], x[1]) not in seen and not HOT_SKIP.search(x[2]):
                seen.add((x[0], x[1])); arts.append(x)
    arts = arts[:150]
    with ThreadPoolExecutor(10) as ex: counts = list(ex.map(lambda x: M.naver_comment_count(x[0], x[1]), arts))
    rows = [{'url': f'https://n.news.naver.com/mnews/article/{o}/{a}', 'title': t[:80], 'comments': c} for (o, a, t), c in zip(arts, counts) if c > 0]
    return sorted(rows, key=lambda r: -r['comments'])[:limit]


def parse_community(html_text, name, splitter, title_re, views_re):
    import html as H
    rows = []
    for row in html_text.split(splitter)[1:]:
        if 'class="notice' in row or 'icon_notice' in row or 'icon_n_survey' in row: continue
        t = re.search(title_re, row, re.S)
        v = re.search(views_re, row, re.S)
        if not t or not v: continue
        title = ' '.join(H.unescape(re.sub(r'<[^>]+>', ' ', t[1])).split())
        views = int(re.sub(r'\D', '', next(g for g in v.groups() if g)) or 0)
        if title: rows.append({'site': name, 'title': title[:80], 'views': views})
    return rows


def hot_community():
    """커뮤니티 인기글 중 조회수 큰 순. 다루지 않을 글은 뺌. [{site, title, views}]"""
    rows = []
    for name, url, splitter, title_re, views_re in COMMUNITIES:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': COMMUNITY_UA, 'Accept-Language': 'ko-KR'})
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read(3_000_000)
                text = raw.decode('euc-kr' if 'euc-kr' in (r.headers.get('content-type') or '').lower() else 'utf-8', 'replace')
            rows += parse_community(text, name, splitter, title_re, views_re)
        except Exception:
            continue
    rows = [r for r in rows if r['views'] >= COMMUNITY_MIN and not HOT_SKIP.search(r['title'])]
    return sorted(rows, key=lambda r: -r['views'])


def rss_items(text):
    """RSS 글 목록 [{title, url}] (제목·링크만)."""
    import html as H
    rows = []
    for it in re.findall(r'(?is)<item\b.*?</item>', text or '')[:60]:
        t = re.search(r'(?is)<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', it)
        u = re.search(r'(?is)<link>(?:<!\[CDATA\[)?\s*(https?://[^<\s\]]+)', it)
        if t and u:
            title = ' '.join(H.unescape(H.unescape(re.sub(r'<[^>]+>', ' ', t[1]))).split())
            if title: rows.append({'title': title[:100], 'url': u[1].strip()})
    return rows


def words(text):
    return {w for w in HOT_NOISE.sub(' ', text or '').split() if len(w) >= 2}


def same_topic(a, b):
    """커뮤니티 글 제목과 기사 제목이 같은 소식인지: 낱말이 두 개 이상, 짧은 쪽의 40% 이상 겹침."""
    x, y = words(a), words(b)
    n = len(x & y)
    return n >= 2 and n >= 0.4 * max(1, min(len(x), len(y)))


def install(S):
    app, conn = S.app, S.conn
    art_dir = S.UPLOAD / 'art'
    with conn() as db:
        db.execute('CREATE TABLE IF NOT EXISTS auto_content_photos(photo_id TEXT PRIMARY KEY,created TEXT NOT NULL)')
        db.execute("CREATE TABLE IF NOT EXISTS auto_content_topics(key TEXT PRIMARY KEY,status TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',created TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS auto_content(article_id INTEGER PRIMARY KEY,status TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',"
                   "card_id INTEGER,reel_id INTEGER,created TEXT NOT NULL)")

    def log(article_id, status, note='', card_id=None, reel_id=None):
        with conn() as db:
            db.execute('INSERT OR REPLACE INTO auto_content(article_id,status,note,card_id,reel_id,created) VALUES(?,?,?,?,?,?)',
                       (article_id, status, str(note)[:300], card_id, reel_id, datetime.datetime.now().isoformat(timespec='seconds')))

    def pick(limit, article_id=None):
        with conn() as db:
            if article_id: return db.execute('SELECT * FROM articles WHERE id=?', (article_id,)).fetchall()
            since = (datetime.datetime.now() - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat(timespec='seconds')
            return db.execute("SELECT a.* FROM articles a WHERE a.status='published' AND COALESCE(a.published_at,a.created)>=? "
                              'AND a.id NOT IN (SELECT article_id FROM auto_content) ORDER BY a.views DESC,a.id DESC LIMIT ?', (since, limit)).fetchall()

    def fetch_image(url):
        req = urllib.request.Request(url, headers={'User-Agent': 'soboru-auto-content'})
        with urllib.request.urlopen(req, timeout=30) as r: data = r.read()
        with Image.open(io.BytesIO(data)) as im: return im.convert('RGB')

    def people_cover(query):
        """언스플래시 인물 실사 사진. (그림, 사진가) 또는 (None, ''). 못 찾아도 멈추지 않음."""
        if not query or not os.getenv('UNSPLASH_ACCESS_KEY', '').strip(): return None, ''
        import soboru_letter as L
        try:
            with conn() as db: used = {r[0] for r in db.execute('SELECT photo_id FROM auto_content_photos')}
            for q in dict.fromkeys((query, re.sub(r'\bkorean\b', 'asian', query, flags=re.I))):
                st, res = L.unsplash_call('/search/photos', {'query': q, 'orientation': 'portrait', 'per_page': 30, 'content_filter': 'high'})
                if st != 200 or not isinstance(res, dict): return None, ''
                photos = [p for p in res.get('results') or [] if p.get('id') not in used]
                # 설명에 사람이 나온다고 적힌 사진만 (풍경이 잘못 걸리지 않게)
                photos = [p for p in photos if PERSON.search(' '.join(str(p.get(k) or '') for k in ('alt_description', 'description')))]
                for ph in photos[:5]:
                    try:
                        img = fetch_image(ph['urls']['raw'] + ('&' if '?' in ph['urls']['raw'] else '?') + 'w=1600&q=85&fm=jpg&fit=max')
                    except Exception:
                        continue
                    with conn() as db:
                        db.execute('INSERT OR IGNORE INTO auto_content_photos VALUES(?,?)', (ph['id'], datetime.datetime.now().isoformat(timespec='seconds')))
                    dl = (ph.get('links') or {}).get('download_location')
                    if dl: L.unsplash_call(dl)  # 언스플래시 규칙: 쓰기로 고른 사진은 download 주소를 한 번 부름
                    user = ph.get('user') or {}
                    return img, str(user.get('name') or user.get('username') or '')[:60]
        except Exception as e:
            app.logger.warning('자동 콘텐츠 사람 표지 실패: %s', str(e)[:160])
        return None, ''

    def article_image(article_id):
        """기사에 쓰는 사진: 직접 올린 그림, 없으면 기사의 언스플래시 사진. (그림, 사진가)"""
        with conn() as db:
            r = db.execute("SELECT file FROM soboru_art WHERE kind='life' AND target_id=? AND status='live'", (article_id,)).fetchone()
            try: u = db.execute('SELECT url,credit FROM mag_unsplash2 WHERE article_id=?', (article_id,)).fetchone()
            except Exception: u = None
        path = art_dir / r['file'] if r else None
        try:
            if path and path.is_file():
                with Image.open(path) as im: return im.convert('RGB'), ''
            if u: return fetch_image(u['url'] + ('&' if '?' in u['url'] else '?') + 'w=1600&q=85&fm=jpg&fit=max'), u['credit']
        except Exception as e:
            app.logger.warning('자동 콘텐츠 기사 사진 실패: %s', str(e)[:160])
        return None, ''

    def cover_image(article_id, query):
        """실사 사진만. (그림, 캡션에 덧붙일 말)"""
        img, who = people_cover(query)
        if img is None and article_id: img, who = article_image(article_id)
        return img, f'사진: {who} / Unsplash' if who else ''

    def plan_for(item):
        import mag_assist
        src = item['src'][:mag_assist.LIMIT]
        out = app.extensions['mag_assist_chat'](mag_assist.ASKS['cards'] + '\n' + mag_assist.NUMS + PEOPLE_ASK, '[기사]\n' + src, 3000)
        if out.get('skip'): raise ValueError('다루지 않을 소재: ' + str(out['skip'])[:60])
        source = item.get('source') or ' '.join(x for x in (mag_assist._clip(out.get('source_media'), 30), mag_assist._clip(out.get('source_date'), 12)) if x) or '네이버 뉴스'
        plan, covers = mag_assist.card_plan(out, source)
        if len(plan) < 3 or not plan[0]['title']: raise ValueError('구성을 짜지 못했어요')
        head, tags = mag_assist.card_caption(out, source)
        said = ' '.join(p['title'] + ' ' + p['sub'] + ' ' + p['items'] for p in plan) + ' ' + head
        extra = sorted(mag_assist.numbers(said) - mag_assist.numbers(src) - mag_assist.numbers(source))
        if extra: raise ValueError('기사에 없는 숫자: ' + ', '.join(extra[:5]))
        why = out.get('why_hot') if isinstance(out.get('why_hot'), dict) else {}
        return plan, head + '\n\n' + tags, source, ' '.join(str(out.get('people_query') or '').split())[:60], why

    def make(item):
        """소재 하나로 카드뉴스와 릴스를 만들어 보관함에 저장. (카드 번호, 릴스 번호, 제목, 분석)"""
        import mag_maker
        made = app.extensions['made_api']
        plan, caption, source, query, why = plan_for(item)
        title = plain(plan[0]['title']).replace('\n', ' ')
        img, credit = cover_image(item.get('article_id'), query)
        if credit: caption += '\n\n' + credit
        total = len(plan)
        with tempfile.TemporaryDirectory(prefix='soboru-auto-') as tmp:
            card_id = made['create']('card', title, caption, source, 'auto')
            for i, s in enumerate(plan):
                f = Path(tmp) / f'c{i}.png'
                render(s, img, i + 1, total, CARD_H).save(f, 'PNG')
                err = made['add_file'](card_id, f'{i + 1:02d}.png', f.read_bytes())
                if err: raise RuntimeError(err)
            err = made['finish'](card_id)
            if err: raise RuntimeError(err)
            if not shutil.which('ffmpeg'): return card_id, None, title, why
            try:  # 릴스만 실패해도 카드뉴스는 남기고, 같은 기사로 카드를 또 만들지 않음
                for i, s in enumerate(plan): render(s, img, i + 1, total, REEL_H).save(Path(tmp) / f's{i}.png', 'PNG')
                clear_png(Path(tmp) / 'clear.png')
                outro_png(Path(tmp) / 'outro.png')
                out = Path(tmp) / 'reel.mp4'
                r = subprocess.run(mag_maker.build(scenes_for(plan, tmp), Path(tmp) / 'outro.png', out), capture_output=True, timeout=1800)
                if r.returncode or not out.is_file(): raise RuntimeError(r.stderr.decode('utf-8', 'replace')[-300:])
                reel_id = app.extensions['made_save_reel'](out, '[슬라이드] ' + title, caption, source, maker='auto')
            except Exception as e:
                app.logger.warning('자동 릴스 실패 %s: %s', item['key'], e)
                reel_id = None
        return card_id, reel_id, title, why

    def notify_done(lines):
        import notify
        token = notify.env('CONTENT_TELEGRAM_BOT_TOKEN') or notify.env('TELEGRAM_BOT_TOKEN')
        chats = notify.env('CONTENT_TELEGRAM_CHAT_ID') or notify.env('TELEGRAM_CHAT_ID')
        if not token or not chats: return False
        text = '\n'.join(lines)
        for chat in chats.replace(' ', '').split(','):
            if chat: notify.http_post(f'https://api.telegram.org/bot{token}/sendMessage', {'chat_id': chat, 'text': text, 'disable_web_page_preview': True}, {})
        return True

    def seen_topics():
        with conn() as db: return {r[0] for r in db.execute('SELECT key FROM auto_content_topics')}

    def mark(item, status, note=''):
        if item.get('article_id'):
            log(item['article_id'], status, note, *(item.get('ids') or (None, None)))
            return
        with conn() as db:
            db.execute('INSERT OR REPLACE INTO auto_content_topics(key,status,note,created) VALUES(?,?,?,?)',
                       (item['key'], status, str(note)[:300], datetime.datetime.now().isoformat(timespec='seconds')))

    def news_items():
        import mag_assist
        seen = seen_topics()
        for n in hot_news():
            key = 'news:' + n['url']
            if key in seen: continue
            src = mag_assist.read_article(n['url'])
            if src: yield {'key': key, 'title': n['title'], 'src': src, 'hot': f"네이버 뉴스 댓글 {n['comments']:,}개"}

    def community_items():
        import mag_assist
        hub = app.extensions.get('naverhub') or {}
        if not hub.get('search'): return
        seen = seen_topics()
        for p in hot_community()[:15]:
            key = 'community:' + re.sub(r'\W', '', p['title'])[:30]
            if key in seen: continue
            q = ' '.join(sorted(words(p['title']), key=len, reverse=True)[:4])
            try: found = hub['search']('news', q, display=5, sort='sim')['items'] if q else []
            except Exception: found = []
            hit = next((f for f in found if f.get('naver') and same_topic(p['title'], f.get('title'))), None)
            if not hit: continue  # 뉴스로 확인되지 않은 글은 쓰지 않음
            src = mag_assist.read_article(hit['naver'])
            if src: yield {'key': key, 'title': hit['title'], 'src': src, 'hot': f"{p['site']} 인기글 조회 {p['views']:,}회"}

    def topic_items():
        """조사한 소재: 분야별 최신 소비자 뉴스(네이버 뉴스 검색)와 AUTO_CONTENT_RSS 글. 하루 안 된 것, 다루지 않을 제목은 뺌."""
        import mag_assist
        seen = seen_topics()
        hub = app.extensions.get('naverhub') or {}
        found = []
        if hub.get('search'):
            for label, q in TOPIC_QUERIES:
                try: rows = hub['search']('news', q, display=10, sort='date')['items']
                except Exception: rows = []
                found += [{'title': r['title'], 'url': r.get('naver') or r['url'], 'label': label, 'media': r.get('source') or ''} for r in rows]
        for url in [u.strip() for u in os.getenv('AUTO_CONTENT_RSS', '').split(',') if u.strip()]:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': COMMUNITY_UA})
                with urllib.request.urlopen(req, timeout=15) as r: text = r.read(2_000_000).decode('utf-8', 'replace')
                found += [dict(x, label='RSS', media='') for x in rss_items(text)]
            except Exception:
                continue
        titles = []
        for f in found:
            key = 'topic:' + re.sub(r'\W', '', f['title'])[:30]
            if key in seen or HOT_SKIP.search(f['title']) or any(same_topic(f['title'], t) for t in titles): continue
            titles.append(f['title']); seen.add(key)
            src = mag_assist.read_article(f['url'])
            if src: yield {'key': key, 'title': f['title'], 'src': src, 'hot': f"소재 {f['label']}" + (f" · {f['media']}" if f['media'] else '')}

    def article_items(limit, article_id=None):
        for a in pick(limit, article_id):
            date = (a['published_at'] or a['created'] or '')[:10].replace('-', '.')
            yield {'key': 'article:%d' % a['id'], 'article_id': a['id'], 'title': a['title'], 'source': '소보루 매거진 ' + date, 'hot': f"매거진 조회 {a['views']:,}회",
                   'src': a['title'] + '\n' + (a['summary'] or '') + '\n' + re.sub(r'\[사진[^\]]*\]', '', a['body'] or '')}

    def candidates(limit, article_id=None):
        """뉴스와 커뮤니티를 번갈아 먼저 보고, 없으면 매거진 기사."""
        if article_id:
            yield from article_items(limit, article_id)
            return
        if os.getenv('AUTO_CONTENT_HOT', '1') != '0':
            with conn() as db:
                n = db.execute("SELECT COUNT(*) FROM auto_content_topics WHERE status='made'").fetchone()[0]
            order = (news_items, topic_items, community_items)
            for gen in order[n % 3:] + order[:n % 3]:
                try: yield from gen()
                except Exception as e: app.logger.warning('자동 콘텐츠 수집 실패: %s', str(e)[:160])
        yield from article_items(limit)

    def run(article_id=None, per_run=None):
        """한 번 돌리기. 한 소재가 안 되면 다음으로 넘어가고, 몫을 채우거나 시도 수를 넘으면 멈춤."""
        want = per_run or int(os.getenv('AUTO_CONTENT_PER_RUN', '3') or 3)  # 운영자 2026-11-06: 조사만 하고 안 만들지 않게 한 번에 3편
        done, failed, tries = [], [], 0
        for item in candidates(want + 5, article_id):
            if len(done) >= want or tries >= want + 3: break  # AI 비용이 끝없이 들지 않게
            tries += 1
            try:
                card_id, reel_id, title, why = make(item)
                item['ids'] = (card_id, reel_id)
                mark(item, 'made')
                done.append((title, card_id, reel_id, item['hot'], why))
            except ValueError as e:  # 이 소재로는 안 됨(없는 숫자, 안 다룰 소재 등): 다시 고르지 않고 다음으로
                app.logger.warning('자동 콘텐츠 건너뜀 %s: %s', item['key'], e)
                mark(item, 'skip', e)
                failed.append((item['title'][:30], str(e)[:80]))
            except Exception as e:  # 일시적 문제(AI 응답 등): 기록하지 않아 다음 번에 다시 시도하고, 여기서 멈춰 비용을 아낌
                app.logger.warning('자동 콘텐츠 실패 %s: %s', item['key'], e)
                failed.append((item['title'][:30], str(e)[:80]))
                break
        if done or failed:
            base = 'https://' + SITE + '/admin/magazine/made/'
            lines = ['소보루 카드뉴스·릴스가 자동으로 만들어졌어요'] if done else ['소보루 자동 콘텐츠를 만들지 못했어요']
            for title, card_id, reel_id, hot, why in done:
                lines += ['', title, '터진 곳: ' + hot, '카드뉴스 ' + base + str(card_id)] + (['릴스 ' + base + str(reel_id)] if reel_id else ['릴스는 못 만들었어요'])
                names = (('topic', '주제'), ('value', '가치'), ('format', '포맷'), ('hook', '후킹'), ('script', '원고'))
                parts = [f'{label}: {str(why.get(k))[:60]}' for k, label in names if why.get(k)]
                if parts: lines += ['', '왜 터졌나'] + parts
            if failed: lines += ['', '건너뛴 소재 ' + str(len(failed)) + '건: ' + failed[0][1]]
            lines += ['', '게시는 하지 않았어요. 확인 뒤 올려 주세요.']
            try: notify_done(lines)
            except Exception as e: app.logger.warning('자동 콘텐츠 알림 실패: %s', e)
        return done, failed

    app.extensions['auto_content'] = {'run': run, 'pick': pick, 'make': make}


def main(argv):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import app as site
    tools = site.app.extensions['auto_content']
    aid = int(argv[argv.index('--article') + 1]) if '--article' in argv else None
    with site.app.app_context():
        if '--dry' in argv:
            for n in hot_news(10): print('뉴스', n['comments'], n['title'])
            for c in hot_community()[:10]: print('커뮤니티', c['site'], c['views'], c['title'])
            hub = site.app.extensions.get('naverhub') or {}
            for label, q in TOPIC_QUERIES:
                try: rows = hub['search']('news', q, display=3, sort='date')['items'] if hub.get('search') else []
                except Exception: rows = []
                for r in rows: print('소재', label, r['title'])
            for a in tools['pick'](5, aid): print('매거진', a['id'], a['views'], a['title'])
            return 0
        done, failed = tools['run'](aid)
    for title, card_id, reel_id, hot, why in done: print('만듦:', title, card_id, reel_id, hot)
    for title, why in failed: print('건너뜀:', title, why)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
