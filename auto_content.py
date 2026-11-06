"""소보루 자동 콘텐츠 (운영자 2026-11-06: 정해진 시간마다 서버에서 카드뉴스·릴스를 만들어 보관함에 넣고 텔레그램으로 알림).

deploy/soboru-content.timer가 아침 9시·오후 1시·저녁 9시쯤 `python -m auto_content`를 부른다. 한 번에 AUTO_CONTENT_PER_RUN편(기본 1).
- 소재: 최근 게시된 매거진 기사 중 조회수가 큰 순서. 이미 만든 기사는 건너뜀(auto_content 표).
- 글: 매거진 AI 도움의 카드뉴스 지시문(mag_assist)을 그대로 씀. 기사에 없는 숫자가 들어간 답은 버리고 다음 기사로 넘어감.
- 표지 (운영자 2026-11-06: AI로 만들 때는 한국인이 나와도 되고, 언스플래시는 풍경이어도 됨): 세 번 중 두 번은 OpenAI로 상황에 맞는 한국인을 그림
  (놀라는 표정 등, 가상 인물). 나머지와 그리지 못했을 때는 기사 사진(직접 올린 그림 또는 언스플래시). 그것도 없으면 글자 표지.
  언스플래시 사진은 캡션에 사진가를, AI 그림은 AI 이미지임을 밝힘.
- 카드: 1080x1350 PNG. 릴스: 1080x1920 전체 화면(위아래 띠 없음), 무음, 장면을 PNG로 그려 mag_maker.build로 합침.
- 저장: 만든 것 보관함(maker='auto'). 게시는 하지 않음. 끝나면 텔레그램으로 알림.
브라우저 없이 그려서 관리자 화면(static/maker.js)의 소보루 디자인과 조금 다를 수 있음.

쓰는 법: python -m auto_content [--dry] [--article 번호]   (--dry: AI·저장 없이 고를 기사만 보여 줌)
"""
import base64
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
PEOPLE_ASK = ('\n[사람 표지] JSON에 "people_scene"도 넣는다: 표지 그림 장면을 영어 한 문장으로. 기사 상황에 맞는 평범한 한국인 한두 명의 표정과 행동을 '
              '구체적으로 쓴다(예: "a young Korean woman on a sofa looking shocked at her phone"). 범죄·사고 장면, 기사 당사자로 오해할 만한 장면, 실존 인물, 회사·브랜드, 글자는 넣지 않는다.')
PERSON_DRAW = ('Photorealistic candid editorial photo for a Korean consumer magazine cover, natural light, portrait, lifestyle look. Scene: {scene}. '
               'The people are fictional ordinary Korean people with natural, clearly visible expressions, not any real or famous person. '
               'Keep the lower third calm for a headline. No text, no letters, no numbers, no logos, no brand names, no watermarks.')
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


def install(S):
    app, conn = S.app, S.conn
    art_dir = S.UPLOAD / 'art'
    with conn() as db:
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

    def want_people():
        """세 번 중 두 번은 사람 표지, 한 번은 기사 사진 (늘 같은 느낌이 되지 않게)."""
        with conn() as db: n = db.execute("SELECT COUNT(*) FROM auto_content WHERE status='made'").fetchone()[0]
        return n % 3 != 2

    def person_cover(scene):
        """OpenAI로 상황에 맞는 한국인을 그림. 그림 또는 None. 못 그려도 멈추지 않음."""
        scene = ' '.join(str(scene or '').split())[:400]
        if len(scene) < 3: return None
        import companydesk as desk, soboru_art
        key = desk.ai_key_for('mag_maker')
        if not key: return None
        body = {'model': soboru_art.image_model(), 'prompt': PERSON_DRAW.format(scene=scene), 'size': '1024x1536', 'quality': soboru_art.image_quality(), 'output_format': 'jpeg', 'n': 1}
        try:
            st, res = desk.post_json('https://api.openai.com/v1/images/generations', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, 150)
            if st != 200: return None
            with Image.open(io.BytesIO(base64.b64decode(res['data'][0]['b64_json']))) as im: return im.convert('RGB')
        except Exception as e:
            app.logger.warning('자동 콘텐츠 사람 표지 실패: %s', str(e)[:160])
            return None

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

    def cover_image(article_id, scene):
        """(그림, 캡션에 덧붙일 말)"""
        img = person_cover(scene) if want_people() else None
        if img is not None: return img, 'AI로 만든 이미지예요.'
        img, who = article_image(article_id)
        return img, f'사진: {who} / Unsplash' if who else ''

    def plan_for(article):
        import mag_assist
        src = (article['title'] + '\n' + (article['summary'] or '') + '\n' + re.sub(r'\[사진[^\]]*\]', '', article['body'] or ''))[:mag_assist.LIMIT]
        out = app.extensions['mag_assist_chat'](mag_assist.ASKS['cards'] + '\n' + mag_assist.NUMS + PEOPLE_ASK, '[기사]\n' + src, 3000)
        date = (article['published_at'] or article['created'] or '')[:10].replace('-', '.')
        source = '소보루 매거진 ' + date
        plan, covers = mag_assist.card_plan(out, source)
        if len(plan) < 3 or not plan[0]['title']: raise ValueError('구성을 짜지 못했어요')
        head, tags = mag_assist.card_caption(out, source)
        said = ' '.join(p['title'] + ' ' + p['sub'] + ' ' + p['items'] for p in plan) + ' ' + head
        extra = sorted(mag_assist.numbers(said) - mag_assist.numbers(src) - mag_assist.numbers(source))
        if extra: raise ValueError('기사에 없는 숫자: ' + ', '.join(extra[:5]))
        return plan, head + '\n\n' + tags, source, str(out.get('people_scene') or '')

    def make(article):
        """기사 한 편으로 카드뉴스와 릴스를 만들어 보관함에 저장. (카드 번호, 릴스 번호, 제목)"""
        import mag_maker
        made = app.extensions['made_api']
        plan, caption, source, scene = plan_for(article)
        title = plain(plan[0]['title']).replace('\n', ' ')
        img, credit = cover_image(article['id'], scene)
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
            if not shutil.which('ffmpeg'): return card_id, None, title
            try:  # 릴스만 실패해도 카드뉴스는 남기고, 같은 기사로 카드를 또 만들지 않음
                for i, s in enumerate(plan): render(s, img, i + 1, total, REEL_H).save(Path(tmp) / f's{i}.png', 'PNG')
                clear_png(Path(tmp) / 'clear.png')
                outro_png(Path(tmp) / 'outro.png')
                out = Path(tmp) / 'reel.mp4'
                r = subprocess.run(mag_maker.build(scenes_for(plan, tmp), Path(tmp) / 'outro.png', out), capture_output=True, timeout=1800)
                if r.returncode or not out.is_file(): raise RuntimeError(r.stderr.decode('utf-8', 'replace')[-300:])
                reel_id = app.extensions['made_save_reel'](out, '[슬라이드] ' + title, caption, source, maker='auto')
            except Exception as e:
                app.logger.warning('자동 릴스 실패 %s: %s', article['id'], e)
                reel_id = None
        return card_id, reel_id, title

    def notify_done(lines):
        import notify
        token = notify.env('CONTENT_TELEGRAM_BOT_TOKEN') or notify.env('TELEGRAM_BOT_TOKEN')
        chats = notify.env('CONTENT_TELEGRAM_CHAT_ID') or notify.env('TELEGRAM_CHAT_ID')
        if not token or not chats: return False
        text = '\n'.join(lines)
        for chat in chats.replace(' ', '').split(','):
            if chat: notify.http_post(f'https://api.telegram.org/bot{token}/sendMessage', {'chat_id': chat, 'text': text, 'disable_web_page_preview': True}, {})
        return True

    def run(article_id=None, per_run=None):
        """한 번 돌리기. 한 편이 실패해도 다음 기사로 넘어가고, 몫을 채우면 멈춤."""
        want = per_run or int(os.getenv('AUTO_CONTENT_PER_RUN', '1') or 1)
        done, failed = [], []
        for article in pick(want + 5, article_id):
            if len(done) >= want: break
            try:
                card_id, reel_id, title = make(article)
                log(article['id'], 'made', '', card_id, reel_id)
                done.append((title, card_id, reel_id))
            except ValueError as e:  # 이 기사로는 안 됨(없는 숫자 등): 다시 고르지 않고 다음 기사로
                app.logger.warning('자동 콘텐츠 건너뜀 %s: %s', article['id'], e)
                log(article['id'], 'skip', e)
                failed.append((article['title'][:30], str(e)[:80]))
            except Exception as e:  # 일시적 문제(AI 응답 등): 기록하지 않아 다음 번에 다시 시도하고, 여기서 멈춰 비용을 아낌
                app.logger.warning('자동 콘텐츠 실패 %s: %s', article['id'], e)
                failed.append((article['title'][:30], str(e)[:80]))
                break
        if done or failed:
            base = 'https://' + SITE + '/admin/magazine/made/'
            lines = ['소보루 카드뉴스·릴스가 자동으로 만들어졌어요'] if done else ['소보루 자동 콘텐츠를 만들지 못했어요']
            for title, card_id, reel_id in done:
                lines += ['', title, '카드뉴스 ' + base + str(card_id)] + (['릴스 ' + base + str(reel_id)] if reel_id else ['릴스는 못 만들었어요'])
            if failed: lines += ['', '건너뛴 기사 ' + str(len(failed)) + '편: ' + failed[0][1]]
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
            for a in tools['pick'](5, aid): print(a['id'], a['views'], a['title'])
            return 0
        done, failed = tools['run'](aid)
    for title, card_id, reel_id in done: print('만듦:', title, card_id, reel_id)
    for title, why in failed: print('건너뜀:', title, why)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
