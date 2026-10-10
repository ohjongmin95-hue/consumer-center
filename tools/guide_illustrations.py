"""이용 안내 그림을 다시 그리는 스크립트 (사람 없이 사물 위주, 메인 일러스트와 같은 선·색).
- static/img/guide-cut1~3.svg : "이 세 가지만 담아 주세요" 3컷
실행: python3 tools/guide_illustrations.py
"""
from pathlib import Path

NAVY = '#2b3a55'; ORANGE = '#ef7300'; RED = '#e5484d'; GREY = '#9aa6b8'; LIGHT = '#e9ecf1'
SAGE = '#8dbf9e'; PEACH = '#ffc38f'; CREAM = '#fff4e8'; GREEN = '#2f9e6b'
FONT = "Pretendard,'Noto Sans KR','Apple SD Gothic Neo',sans-serif"


def L(d, c=NAVY, w=2.2, f='none', extra=''):
    return f'<path d="{d}" fill="{f}" stroke="{c}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"{extra}/>'


def R(x, y, w, h, rx=6, f='#fff', c=NAVY, sw=2.2):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{f}" stroke="{c}" stroke-width="{sw}"/>'


def T(x, y, s, size=10, weight=800, fill=NAVY, anchor='middle'):
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" font-weight="{weight}" fill="{fill}" font-family="{FONT}">{s}</text>'


def lines(x, y, widths, gap=9, c=GREY):
    return ''.join(L(f'M{x} {y + i * gap} h{w}', c=c, w=2) for i, w in enumerate(widths))


def mark(x, y, n):
    """주황 번호 표시: 화면의 1·2·3번 설명과 짝."""
    return f'<circle cx="{x}" cy="{y}" r="11" fill="{ORANGE}" stroke="#fff" stroke-width="2.5"/>' + T(x, y + 4, n, 11.5, 900, '#fff')


def ring(cx, cy, r, c=RED):
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{c}" stroke-width="2.4" stroke-dasharray="4 3"/>'


def oval(cx, cy, rx, ry, c=RED):
    return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="none" stroke="{c}" stroke-width="2.2"/>'


def hl(x, y, w, h=9):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2" fill="#ffd9ad"/>'


def spark(x, y, s=1, c=ORANGE):
    return f'<path transform="translate({x} {y}) scale({s})" d="M0 -8 Q1 -1 8 0 Q1 1 0 8 Q-1 1 -8 0 Q-1 -1 0 -8Z" fill="{c}"/>'


def svg(w, h, bg, body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"><rect width="{w}" height="{h}" rx="14" fill="{bg}"/>{body}</svg>\n'


# ---------- 공용 소품 ----------
def receipt(x, y, w=64, h=92, title='영수증'):
    zig = ''.join(f' L{x + w - i * 8 - 4} {y + h + (4 if i % 2 == 0 else 0)}' for i in range(w // 8))
    return (f'<path d="M{x} {y} H{x + w} V{y + h}{zig} L{x} {y + h} Z" fill="#fff" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>'
            + T(x + w / 2, y + 16, title, 9.5))


def phone(x, y, w=58, h=104, screen=''):
    return (R(x, y, w, h, 10, NAVY, NAVY) + f'<rect x="{x + 5}" y="{y + 9}" width="{w - 10}" height="{h - 18}" rx="4" fill="#fff"/>'
            + f'<g transform="translate({x + 5} {y + 9})">{screen}</g>')


def doc(x, y, w=64, h=84, title=''):
    return (f'<path d="M{x} {y} H{x + w - 14} L{x + w} {y + 14} V{y + h} H{x} Z" fill="#fff" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>'
            + L(f'M{x + w - 14} {y} V{y + 14} H{x + w}', w=2) + (T(x + w / 2 - 4, y + 18, title, 9.5) if title else ''))


def calendar(x, y, day='12'):
    return (R(x, y, 56, 52, 7) + f'<rect x="{x + 1.1}" y="{y + 1.1}" width="53.8" height="13" rx="6" fill="{ORANGE}"/>'
            + L(f'M{x + 14} {y - 5} v10 M{x + 42} {y - 5} v10', w=2.4) + T(x + 28, y + 41, day, 19, 900))


def box(x, y, w=74, h=52, open_=False):
    top = (f'<path d="M{x} {y} L{x - 12} {y - 14} M{x + w} {y} L{x + w + 12} {y - 14}" stroke="{NAVY}" stroke-width="2.2" stroke-linecap="round"/>' if open_ else
           f'<path d="M{x + w / 2 - 9} {y} v18 h18 v-18" fill="#f6d9b4" stroke="{NAVY}" stroke-width="1.8" stroke-linejoin="round"/>')
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" fill="#f0c48f" stroke="{NAVY}" stroke-width="2.2"/>' + top


def magnifier(cx, cy, r=18, inner=''):
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#fff" stroke="{NAVY}" stroke-width="2.6"/>{inner}'
            + L(f'M{cx + r * .72} {cy + r * .72} l{r * .6} {r * .6}', w=5))


def arrow(x1, y, x2):
    return L(f'M{x1} {y} H{x2} M{x2 - 6} {y - 5} L{x2} {y} L{x2 - 6} {y + 5}', c='#c4c9d2', w=2.4)


def camera_corners(x, y, w, h, s=12):
    return ''.join(L(d, c=ORANGE, w=3) for d in (
        f'M{x} {y + s} V{y} H{x + s}', f'M{x + w - s} {y} H{x + w} V{y + s}',
        f'M{x} {y + h - s} V{y + h} H{x + s}', f'M{x + w - s} {y + h} H{x + w} V{y + h - s}'))


# ---------- 이 세 가지만 담아 주세요 (300x220) ----------
def cut1():
    b = [receipt(108, 34, 84, 132, '영수증'),
         T(116, 72, '2026.03.02', 9, 700, NAVY, 'start'), hl(114, 63, 0),
         L('M116 86 h44', c=GREY, w=2), T(116, 100, '무선 이어폰', 9, 700, NAVY, 'start'), L('M116 112 h52', c=GREY, w=2),
         L('M116 128 h68', w=1.6), T(184, 147, '₩89,000', 12, 900, NAVY, 'end'),
         oval(150, 70, 40, 11, ORANGE), oval(146, 97, 36, 11, ORANGE), oval(158, 143, 32, 12, RED),
         mark(84, 70, 1), mark(84, 97, 2), mark(216, 143, 3),
         spark(240, 52, 1), spark(62, 150, .7, '#ffc38f')]
    return svg(300, 220, '#eef6f0', ''.join(b))


def cut2():
    def bubble(x, y, w, text, mine):
        fill = '#fff3e6' if mine else '#fff'
        tail = f'M{x + w - 10} {y + 26} l8 7 l-1 -9' if mine else f'M{x + 10} {y + 26} l-8 7 l1 -9'
        return R(x, y, w, 26, 10, fill, NAVY, 1.8) + L(tail, w=1.8, f=fill) + T(x + w / 2, y + 17, text, 9.5, 700)
    scr = (T(46, 15, '고객센터', 8.5, 800, GREY) + L('M6 22 H86', c=LIGHT, w=1.5)
           + bubble(18, 32, 66, '소리가 안 나요', True) + bubble(14, 74, 66, '교환해 주세요', True) + bubble(4, 116, 68, '확인 후 연락', False))
    b = [phone(104, 22, 102, 176, scr), mark(88, 67, 1), mark(222, 109, 2), mark(92, 151, 3),
         T(88, 88, '문제', 9, 800, ORANGE), T(232, 130, '요청', 9, 800, ORANGE), T(92, 172, '답변', 9, 800, ORANGE),
         spark(246, 46, .9), spark(52, 40, .6, '#ffc38f')]
    return svg(300, 220, '#fff2e6', ''.join(b))


def kettle(x, y, s=1):
    return (f'<g transform="translate({x} {y}) scale({s})"><path d="M-22 -18 Q-26 22 -20 26 H20 Q26 22 22 -18 Z" fill="{SAGE}" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>'
            + L('M22 -10 Q36 -8 34 8 Q32 18 22 16', w=2.6) + R(-16, -26, 32, 9, 4, '#fff') + L('M-26 26 H26', w=2.6)
            + R(-10, 2, 20, 9, 2, '#fff', NAVY, 1.4) + '</g>')


def cut3():
    frame = lambda x: R(x, 52, 76, 96, 8, '#fff', NAVY, 2)
    b = [frame(14), frame(112), frame(210),
         kettle(52, 102, .95), T(52, 166, '전체 모습', 10, 800),
         f'<g transform="translate(150 100)"><circle r="30" fill="{SAGE}" stroke="{NAVY}" stroke-width="2"/>'
         + L('M-14 -14 L-2 -4 L-8 6 L6 18', c=RED, w=2.6) + '</g>', ring(150, 100, 34, ORANGE), T(150, 166, '문제 부위', 10, 800),
         doc(222, 64, 52, 72, ''), lines(230, 82, [30, 22, 34, 18], 10), oval(244, 122, 14, 8, RED), T(248, 166, '거래 기록', 10, 800),
         arrow(93, 100, 108), arrow(191, 100, 206),
         camera_corners(8, 46, 88, 108, 12), mark(16, 46, 1), mark(114, 46, 2), mark(212, 46, 3)]
    return svg(300, 220, '#f1f3f7', ''.join(b))


if __name__ == '__main__':
    img = Path(__file__).resolve().parent.parent / 'static' / 'img'
    for i, f in enumerate((cut1, cut2, cut3), 1):
        (img / f'guide-cut{i}.svg').write_text(f(), encoding='utf-8')
    print('saved 3 illustrations to', img)
