"""메인 화면 양옆 일러스트(static/img/hero-left.svg, hero-right.svg)를 만든다.

사용법: python tools/make_hero_art.py  (저장소 루트에서 실행)
그림체: 상반신 위주로 모여 선 사람들, 피부는 흰 면 + 가는 남색 선, 옷·머리는 단색 면.
왼쪽은 피해(파손 상자·영수증·환불 거절), 오른쪽은 제보와 해결(확성기·제보 봉투·상담원).
"""
from pathlib import Path

LINE = '#2b3a55'
ORANGE, APRICOT, SAGE, NAVY, CREAM, HAIR, HAIR2, WHITE = '#ef7300', '#ffc48f', '#8dbf9e', '#2b3a55', '#fff1e3', '#262a36', '#6b3f2a', '#ffffff'


def p(d, fill='none', stroke=None, w=0, extra=''):
    s = f' stroke="{stroke}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"' if stroke else ''
    return f'<path d="{d}" fill="{fill}"{s}{extra}/>'


def poly(pts):
    return 'M' + ' L'.join(f'{x} {y}' for x, y in pts)


def tube(pts, w, fill=WHITE):
    """선으로 테두리를 두른 굵은 팔 (흰 피부 + 가는 외곽선)."""
    d = poly(pts)
    return p(d, stroke=LINE, w=w + 3.6) + p(d, stroke=fill, w=w)


def sleeve(pts, color, w=22):
    return p(poly(pts), stroke=color, w=w)


def hand(x, y, r=8):
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{WHITE}" stroke="{LINE}" stroke-width="1.8"/>'


def brows(kind, dx=0):
    # worry: 안쪽 끝이 올라간 걱정 눈썹, angry: 안쪽 끝이 내려간 속상한 눈썹
    if kind == 'worry':
        return p(f'M{-13 + dx} -9 L{-4 + dx} -12', stroke=LINE, w=2) + p(f'M{4 + dx} -12 L{13 + dx} -9', stroke=LINE, w=2)
    if kind == 'angry':
        return p(f'M{-13 + dx} -12 L{-4 + dx} -8', stroke=LINE, w=2.2) + p(f'M{4 + dx} -8 L{13 + dx} -12', stroke=LINE, w=2.2)
    return ''


def face(eyes=(-8, 8), y=0, mouth='smile', dx=0):
    m = {'smile': f'M{-6 + dx} {14 + y} q6 5 12 0', 'open': f'M{-4 + dx} {13 + y} q4 6 8 0 z', 'line': f'M{-4 + dx} {15 + y} l8 0', 'o': '',
         'sad': f'M{-6 + dx} {17 + y} q6 -5 12 0', 'shout': f'M{-6 + dx} {11 + y} q6 10 12 0 z'}[mouth]
    out = ''.join(f'<circle cx="{e + dx}" cy="{y}" r="2.3" fill="{LINE}"/>' for e in eyes)
    out += p(f'M{1 + dx} {4 + y} q4 4 0 7', stroke=LINE, w=1.6)
    if mouth == 'o':
        out += f'<ellipse cx="{dx}" cy="{16 + y}" rx="3" ry="3.6" fill="{LINE}"/>'
    else:
        out += p(m, fill=LINE if mouth in ('open', 'shout') else 'none', stroke=LINE, w=1.8)
    return out


def head_shape():
    return (f'<rect x="-8" y="18" width="16" height="22" fill="{WHITE}" stroke="{LINE}" stroke-width="1.8"/>'
            f'<ellipse cx="0" cy="0" rx="22" ry="25" fill="{WHITE}" stroke="{LINE}" stroke-width="2"/>')


def torso(color, w=46):
    return p(f'M{-w} 78 Q{-w - 2} 44 -20 38 L20 38 Q{w + 2} 44 {w} 78 L{w + 6} 330 L{-w - 6} 330 Z', color)


def group(x, y, s, parts, flip=False):
    sx = -s if flip else s
    return f'<g transform="translate({x} {y}) scale({sx} {s})">{"".join(parts)}</g>'


# ---- 소품 (선 그림) ----
def bulb(x, y, s=1.0):
    rays = ''.join(p(poly([(x + dx * .64 * s, y + dy * .64 * s), (x + dx * s, y + dy * s)]), stroke=LINE, w=2.6) for dx, dy in [(-38, -6), (-28, -30), (0, -42), (28, -30), (38, -6)])
    return (rays + f'<circle cx="{x}" cy="{y}" r="{19 * s}" fill="#fff4d9" stroke="{LINE}" stroke-width="2.2"/>'
            + p(f'M{x - 6 * s} {y + 12 * s} L{x - 3 * s} {y - 2 * s} L{x} {y + 4 * s} L{x + 3 * s} {y - 2 * s} L{x + 6 * s} {y + 12 * s}', stroke=ORANGE, w=2.2)
            + f'<rect x="{x - 9 * s}" y="{y + 16 * s}" width="{18 * s}" height="{13 * s}" rx="{3 * s}" fill="{NAVY}"/>'
            + p(poly([(x - 9 * s, y + 21 * s), (x + 9 * s, y + 21 * s)]), stroke=WHITE, w=1.6) + p(poly([(x - 9 * s, y + 25 * s), (x + 9 * s, y + 25 * s)]), stroke=WHITE, w=1.6))


def bubble(x, y, w, h, inner, tail='left'):
    tx = x - w / 2 + 18 if tail == 'left' else x + w / 2 - 18
    tip = tx - 6 if tail == 'left' else tx + 6
    return (p(f'M{tx - 8} {y + h / 2 - 2} L{tip} {y + h / 2 + 15} L{tx + 8} {y + h / 2 - 2}', WHITE, LINE, 2.2)
            + f'<rect x="{x - w / 2}" y="{y - h / 2}" width="{w}" height="{h}" rx="{h / 2}" fill="{WHITE}" stroke="{LINE}" stroke-width="2.2"/>'
            + f'<rect x="{tx - 7}" y="{y + h / 2 - 4}" width="14" height="5" fill="{WHITE}"/>' + inner)


def dots3(x, y):
    return ''.join(f'<circle cx="{x + d}" cy="{y}" r="3.6" fill="{LINE}"/>' for d in (-12, 0, 12))


def bang(x, y, s=1.0, c=ORANGE):
    return p(f'M{x - 5 * s} {y - 34 * s} L{x + 7 * s} {y - 34 * s} L{x + 3 * s} {y} L{x - 3 * s} {y} Z', c) + f'<circle cx="{x + .5 * s}" cy="{y + 10 * s}" r="{5 * s}" fill="{c}"/>'


def paper(x, y, w, h, rot=0, n=4, fill=WHITE):
    ls = ''.join(p(poly([(-w / 2 + 6, -h / 2 + 9 + i * 7), (w / 2 - 6 - (i % 2) * 7, -h / 2 + 9 + i * 7)]), stroke=ORANGE if i == 0 else '#9aa6b8', w=2) for i in range(n))
    return f'<g transform="translate({x} {y}) rotate({rot})"><rect x="{-w / 2}" y="{-h / 2}" width="{w}" height="{h}" rx="3" fill="{fill}" stroke="{LINE}" stroke-width="2"/>{ls}</g>'


RED = '#e5484d'


def broken_box(x, y, rot=0):
    return (f'<g transform="translate({x} {y}) rotate({rot})"><rect x="-34" y="-26" width="68" height="50" rx="3" fill="#e3b27c" stroke="{LINE}" stroke-width="2"/>'
            + p('M-34 -14 L34 -14', stroke=LINE, w=1.6) + f'<rect x="-8" y="-26" width="16" height="12" fill="#f3d3a8"/>'
            + p('M-6 -14 L2 -2 L-4 6 L6 24', stroke=LINE, w=2.4)
            + f'<circle cx="20" cy="6" r="9" fill="{ORANGE}"/>' + p('M20 0 L20 7 M20 11 L20 11.5', stroke=WHITE, w=2.6) + '</g>')


def receipt_long(x, y, rot=0):
    zig = ' '.join(f'L{20 - i * 5} {32 + (4 if i % 2 else 0)}' for i in range(9))
    return (f'<g transform="translate({x} {y}) rotate({rot})">' + p(f'M-20 -34 L20 -34 {zig} Z', WHITE, LINE, 2)
            + ''.join(p(f'M-13 {-24 + i * 8} L{9 - (i % 2) * 6} {-24 + i * 8}', stroke='#9aa6b8', w=2) for i in range(4))
            + f'<ellipse cx="0" cy="17" rx="16" ry="8" fill="none" stroke="{RED}" stroke-width="2.4"/>' + p('M-9 17 L9 17', stroke=LINE, w=2.6) + '</g>')


def phone_refused(x, y, rot=0):
    return (f'<g transform="translate({x} {y}) rotate({rot})"><rect x="-15" y="-26" width="30" height="52" rx="6" fill="{NAVY}"/>'
            f'<rect x="-11" y="-20" width="22" height="38" rx="2" fill="{WHITE}"/><rect x="-8" y="-15" width="13" height="7" rx="3" fill="#dfe4ec"/>'
            f'<circle cx="2" cy="6" r="8" fill="{RED}"/>' + p('M-1.5 2.5 L5.5 9.5 M5.5 2.5 L-1.5 9.5', stroke=WHITE, w=2.2) + '</g>')


def megaphone(x, y, rot=0):
    waves = ''.join(p(f'M{62 + i * 9} {-14 - i * 4} q8 {14 + i * 4} 0 {28 + i * 8}', stroke=ORANGE, w=2.4) for i in range(3))
    return (f'<g transform="translate({x} {y}) rotate({rot})">' + p('M0 -8 L50 -24 L50 24 L0 8 Z', ORANGE, LINE, 2)
            + f'<rect x="48" y="-26" width="8" height="52" rx="3" fill="{NAVY}"/><rect x="-9" y="-8" width="11" height="16" rx="3" fill="{NAVY}"/>'
            + f'<rect x="14" y="6" width="9" height="20" rx="3" fill="{NAVY}"/>' + waves + '</g>')


def envelope(x, y, rot=0):
    return (f'<g transform="translate({x} {y}) rotate({rot})"><rect x="-26" y="-18" width="52" height="36" rx="3" fill="{WHITE}" stroke="{LINE}" stroke-width="2"/>'
            + p('M-26 -16 L0 4 L26 -16', stroke=LINE, w=2) + f'<circle cx="14" cy="8" r="9" fill="{ORANGE}"/>'
            + f'<text x="14" y="11.5" text-anchor="middle" font-family="sans-serif" font-size="8" font-weight="800" fill="{WHITE}">제보</text></g>')


def squiggle(x, y, c=LINE):
    return p(f'M{x} {y} q7 -9 14 0 t14 0 t14 0', stroke=c, w=2.2)


def ticks(x, y, flip=False, c=LINE):
    sg = -1 if flip else 1
    return ''.join(p(poly([(x + sg * a, y + b), (x + sg * (a + 7), y + b + c2)]), stroke=c, w=2.2) for a, b, c2 in [(0, -12, -6), (3, 0, 0), (0, 12, 6)])


def spark(x, y, s=1.0, c=ORANGE):
    return p(f'M{x} {y - 9 * s} L{x + 2.4 * s} {y - 2.4 * s} L{x + 9 * s} {y} L{x + 2.4 * s} {y + 2.4 * s} L{x} {y + 9 * s} L{x - 2.4 * s} {y + 2.4 * s} L{x - 9 * s} {y} L{x - 2.4 * s} {y - 2.4 * s} Z', c)


# ---- 사람들 (머리 중심이 원점, 아래로 몸이 이어지고 화면 밖에서 잘림) ----
def woman_bob_pointing(x, y, s):
    """단발머리 여성: 남색 재킷 + 흰 칼라, 오른손으로 가운데를 가리키며 이야기."""
    return group(x, y, s, [
        p('M-27 -6 Q-29 -36 0 -36 Q29 -36 27 -6 L28 26 L14 26 L14 -4 L-14 -4 L-14 26 L-28 26 Z', HAIR),
        torso(NAVY, 48),
        p('M-14 38 L0 66 L14 38 Z', WHITE, LINE, 1.8), p('M-20 40 L-6 90 L-22 140', stroke='#4a5a7a', w=2) + p('M20 40 L6 90 L22 140', stroke='#4a5a7a', w=2),
        sleeve([(-38, 56), (-46, 114)], NAVY), tube([(-46, 114), (-28, 132)], 12),
        sleeve([(38, 56), (46, 114)], NAVY), tube([(46, 114), (28, 132)], 12),
        broken_box(0, 128, -4), hand(-28, 134), hand(28, 132),
        head_shape(),
        p('M-23 -8 Q-16 -30 4 -30 Q20 -29 24 -10 Q10 -22 -23 -8 Z', HAIR),
        brows('worry', 2), face(mouth='sad', dx=2),
    ])


def man_presenting(x, y, s):
    """짧은 머리 남성: 세이지 셔츠, 한 손은 손바닥을 펴 보이고 한 손은 서류를 가슴에 듦."""
    return group(x, y, s, [
        torso(SAGE, 50),
        p('M-12 38 L0 54 L12 38', stroke='#5f9677', w=2.4) + p('M0 54 L0 330', stroke='#76aa8b', w=1.6),
        sleeve([(-40, 56), (-50, 116)], SAGE), tube([(-50, 116), (-14, 126)], 12),
        sleeve([(40, 56), (50, 118)], SAGE), tube([(50, 118), (18, 126)], 12),
        receipt_long(2, 100, -4), hand(16, 128), hand(-12, 128),
        head_shape(),
        p('M-23 -6 Q-26 -36 2 -37 Q24 -36 23 -12 Q18 -6 16 -14 Q8 -24 -8 -22 Q-18 -20 -23 -6 Z', HAIR),
        brows('angry', -2), face(mouth='line', dx=-2),
    ])


def woman_thinking(x, y, s):
    """포니테일 여성: 살구색 블라우스, 턱에 손을 대고 생각."""
    return group(x, y, s, [
        p('M16 -26 Q40 -30 40 2 Q38 22 28 30 Q32 6 18 -8 Z', HAIR2),
        torso(APRICOT, 44),
        p('M-8 38 Q0 48 8 38', stroke='#e59e63', w=2.2),
        sleeve([(36, 56), (52, 100)], APRICOT), tube([(52, 100), (40, 52)], 12), phone_refused(40, 30, 8), hand(40, 52),
        sleeve([(-36, 56), (-30, 104)], APRICOT), tube([(-30, 104), (-8, 34)], 12), hand(-6, 30, 8.5), tube([(-6, 30), (2, 14)], 4.5),
        head_shape(),
        p('M-23 -6 Q-20 -34 2 -34 Q22 -33 23 -10 Q12 -22 -4 -22 Q-16 -20 -23 -6 Z', HAIR2),
        brows('worry', 3), face(mouth='sad', dx=3),
    ])


def man_paper_up(x, y, s):
    """곱슬머리 남성: 주황 니트, 서류를 들어 보이며 설명."""
    return group(x, y, s, [
        torso(ORANGE, 50),
        p('M-14 40 Q0 52 14 40', stroke='#cf6200', w=3),
        sleeve([(-40, 56), (-52, 124)], ORANGE), tube([(-52, 124), (-34, 166)], 12), hand(-32, 170),
        sleeve([(40, 56), (62, 84)], ORANGE), tube([(62, 84), (36, 34)], 12),
        megaphone(28, 18, -64), hand(36, 36),
        head_shape(),
        ''.join(f'<circle cx="{cx}" cy="{cy}" r="10" fill="{HAIR}"/>' for cx, cy in [(-16, -22), (-4, -30), (10, -28), (20, -16), (-22, -8)]),
        brows('angry', 3), face(mouth='shout', dx=3),
    ])


def woman_long_hair(x, y, s):
    """긴 머리 여성: 남색 니트, 손을 들어 '그렇구나!' 하는 표정."""
    return group(x, y, s, [
        p('M-28 -4 Q-30 -38 0 -38 Q30 -38 28 -4 L34 74 L-34 74 Z', HAIR2),
        torso(NAVY, 46),
        p('M-10 38 Q0 50 10 38', stroke='#4a5a7a', w=2.4),
        sleeve([(-38, 56), (-62, 84)], NAVY), tube([(-62, 84), (-70, 30)], 12),
        envelope(-72, 4, -10), hand(-70, 30),
        sleeve([(38, 56), (46, 124)], NAVY), tube([(46, 124), (30, 164)], 12), hand(28, 168),
        head_shape(),
        p('M-24 -6 Q-18 -32 4 -32 Q22 -30 24 -8 Q4 -20 -24 -6 Z', HAIR2),
        face(mouth='o', dx=-2),
    ])


def man_clipboard(x, y, s):
    """안경 쓴 상담원: 세이지 카디건 + 흰 셔츠, 체크리스트를 들고 엄지를 세움."""
    clip = (f'<g transform="translate(-30 104) rotate(-8)"><rect x="-20" y="-28" width="40" height="54" rx="4" fill="{APRICOT}" stroke="{LINE}" stroke-width="2"/>'
            f'<rect x="-14" y="-20" width="28" height="40" rx="2" fill="{WHITE}"/>'
            + p('M-9 -10 l4 4 8 -8 M-9 4 l4 4 8 -8', stroke='#2e9d5b', w=2.6) + f'<rect x="-8" y="-32" width="16" height="8" rx="2" fill="{NAVY}"/></g>')
    return group(x, y, s, [
        torso(SAGE, 50),
        p('M-14 38 L0 70 L14 38 Z', WHITE, LINE, 1.8) + p('M0 70 L0 330', stroke='#5f9677', w=2),
        sleeve([(-40, 56), (-54, 112)], SAGE), clip, tube([(-54, 112), (-36, 120)], 12), hand(-32, 120),
        sleeve([(40, 56), (66, 86)], SAGE), tube([(66, 86), (70, 50)], 12),
        p('M62 52 Q60 38 70 38 L72 26 Q78 22 80 30 L78 40 Q86 42 84 52 Z', WHITE, LINE, 1.8),
        head_shape(),
        p('M-23 -8 Q-24 -36 0 -36 Q24 -36 23 -8 Q14 -24 0 -24 Q-14 -24 -23 -8 Z', '#8a8f99'),
        f'<circle cx="-8" cy="0" r="7" fill="none" stroke="{LINE}" stroke-width="2"/><circle cx="8" cy="0" r="7" fill="none" stroke="{LINE}" stroke-width="2"/>' + p('M-1 0 L1 0', stroke=LINE, w=2),
        face(mouth='smile'),
    ])


CLIP = '<clipPath id="{id}"><rect x="0" y="0" width="360" height="380"/></clipPath>'


def side_left():
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 380">' + '<defs>' + CLIP.format(id='cl') + '</defs><g clip-path="url(#cl)">'
            + man_presenting(208, 168, .98)
            + woman_thinking(294, 214, .92)
            + woman_bob_pointing(96, 196, 1.04)
            + bubble(282, 92, 76, 40, f'<text x="282" y="99" text-anchor="middle" font-family="sans-serif" font-size="19" font-weight="800" fill="{RED}">환불?</text>', tail='left')
            + bubble(120, 80, 62, 40, dots3(120, 80), tail='right')
            + ticks(60, 110, flip=True) + squiggle(14, 300) + spark(30, 60, 1.1) + spark(160, 34, .8, APRICOT)
            + '</g></svg>')


def side_right():
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 380">' + '<defs>' + CLIP.format(id='cr') + '</defs><g clip-path="url(#cr)">'
            + man_clipboard(66, 214, .96)
            + woman_long_hair(184, 168, .96)
            + man_paper_up(282, 206, 1.0)
            + bang(110, 110, 1.0)
            + ticks(232, 128) + squiggle(20, 160) + spark(150, 40, 1.1) + spark(30, 90, .9, APRICOT)
            + '</g></svg>')


if __name__ == '__main__':
    out = Path(__file__).resolve().parents[1] / 'static' / 'img'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'hero-left.svg').write_text(side_left() + '\n', encoding='utf-8')
    (out / 'hero-right.svg').write_text(side_right() + '\n', encoding='utf-8')
    print('saved', out / 'hero-left.svg', out / 'hero-right.svg')
