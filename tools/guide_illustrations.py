"""이용 안내 그림을 다시 그리는 스크립트 (사람 없이 사물 위주, 메인 일러스트와 같은 선·색).
- static/img/guide-cut1~3.svg : "이 세 가지만 담아 주세요" 3컷
- static/img/guide-ind-<이름>.svg : 업종 카드 위쪽 그림 (이름은 업종의 '그림' 칸 값)
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


# ---------- 업종별 (330x200): 카드 위쪽 그림. 그 업종에서 꼭 남길 자료를 사물로 보여 줌 ----------
def ind_food():
    b = [f'<path d="M26 54 H104 L98 156 H32 Z" fill="#fff" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>', R(26, 40, 78, 16, 4, ORANGE, NAVY, 2),
         T(65, 90, '고소한 과자', 10, 900), lines(42, 104, [46, 38]), hl(36, 128, 58, 14), T(65, 138, '소비기한 26.10.12', 7.5, 800),
         f'<path d="M140 104 H222 Q220 146 181 148 Q142 146 140 104Z" fill="{LIGHT}" stroke="{NAVY}" stroke-width="2.2"/>', L('M136 104 H226', w=2.4),
         f'<circle cx="196" cy="114" r="3" fill="{NAVY}"/>', ring(196, 114, 10), magnifier(212, 62, 18, f'<circle cx="212" cy="62" r="4" fill="{NAVY}"/>'),
         R(252, 60, 62, 76, 6, '#fffbe6', NAVY, 2), T(283, 82, '개봉 전', 9.5, 800, NAVY), L('M262 92 h42', c=LIGHT, w=1.5),
         T(283, 110, '10/3 저녁', 9.5, 800, ORANGE), T(283, 126, '발견', 9, 700, GREY)]
    return svg(330, 200, '#fff2e6', ''.join(b))


def ind_commerce():
    page = (R(20, 44, 116, 104, 8) + L('M20 60 H136', w=2) + ''.join(f'<circle cx="{30 + i * 8}" cy="52" r="2.2" fill="{GREY}"/>' for i in range(3))
            + f'<rect x="30" y="70" width="40" height="40" rx="4" fill="{SAGE}"/>' + lines(78, 74, [44, 34], 10)
            + hl(76, 96, 50, 12) + T(101, 105, '새 상품·정품', 8.5, 800) + R(78, 118, 46, 16, 4, ORANGE, ORANGE, 1) + T(101, 129, '구매', 8.5, 900, '#fff'))
    b = [page, T(165, 106, '≠', 30, 900, RED),
         box(188, 98, 70, 50, True), f'<rect x="204" y="80" width="34" height="34" rx="4" fill="{SAGE}" stroke="{NAVY}" stroke-width="2"/>',
         L('M212 88 l10 12 l-6 6', c=RED, w=2.4), ring(222, 96, 20),
         R(270, 64, 50, 30, 10, '#fff', NAVY, 1.8), T(295, 83, '환불요청', 8.5, 800), T(295, 108, '3/5', 10, 900, ORANGE)]
    return svg(330, 200, '#f1f3f7', ''.join(b))


def ind_car():
    car = (f'<path d="M12 116 L22 92 Q28 82 42 80 L70 78 Q82 66 98 64 H126 Q142 66 152 80 L166 84 Q178 88 178 104 V116 Z" fill="{PEACH}" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>'
           + L('M80 80 L100 68 H124 L136 80 Z', w=2, f='#fff') + f'<circle cx="48" cy="118" r="14" fill="{NAVY}"/><circle cx="48" cy="118" r="5" fill="#fff"/>'
           + f'<circle cx="146" cy="118" r="14" fill="{NAVY}"/><circle cx="146" cy="118" r="5" fill="#fff"/>')
    b = [f'<g transform="translate(-4 8) scale(.92)">{car}</g>', ring(130, 117, 18), magnifier(118, 54, 18, L('M110 50 l8 6 l6 -8', c=RED, w=2.2)),
         L('M126 66 L130 98', c=ORANGE, w=1.6, extra=' stroke-dasharray="3 3"'),
         doc(184, 46, 62, 100, '정비'), lines(192, 76, [40, 30, 44]), L('M196 118 l10 -10 m-2 -4 a6 6 0 1 0 8 8', c=ORANGE, w=2.4),
         R(262, 52, 52, 40, 5), T(288, 76, '이용 전', 8.5, 800), R(262, 104, 52, 40, 5), T(288, 128, '이용 후', 8.5, 800), L('M300 112 l6 10', c=RED, w=2.4)]
    return svg(330, 200, '#fff2e6', ''.join(b))


def ind_telecom():
    plan = (T(24, 16, '요금제', 8.5, 800, GREY) + T(24, 38, '59,000', 12, 900) + T(24, 54, '약정 24개월', 7.5, 700, NAVY) + hl(4, 64, 40, 8) + lines(6, 84, [34, 26], 9))
    b = [phone(30, 44, 58, 112, plan),
         receipt(130, 40, 72, 112, '청구서'), lines(140, 72, [40, 30, 44]), L('M140 104 h28', c=RED, w=2.4), L('M178 104 h14', c=RED, w=2.4),
         oval(166, 104, 34, 10, RED), lines(140, 120, [44, 30]),
         f'<g transform="translate(268 96)"><path d="M0 26 C-24 0 -18 -30 0 -30 C18 -30 24 0 0 26Z" fill="#fff" stroke="{NAVY}" stroke-width="2.2"/><circle cy="-8" r="7" fill="{ORANGE}"/></g>',
         ''.join(f'<rect x="{248 + i * 10}" y="{150 - (i + 1) * 7}" width="6" height="{(i + 1) * 7}" rx="1" fill="{NAVY if i < 1 else LIGHT}"/>' for i in range(4)),
         T(286, 148, '12:40', 9, 800)]
    return svg(330, 200, '#f1f3f7', ''.join(b))


def ind_finance():
    b = [doc(22, 40, 84, 116, '약관'), lines(32, 72, [56, 44]), hl(30, 90, 68, 22), lines(34, 96, [56, 44], 8, NAVY), lines(32, 124, [56, 40]),
         doc(146, 52, 60, 84, ''), lines(154, 74, [38, 30, 40, 26]), camera_corners(136, 42, 80, 104, 12),
         R(236, 50, 80, 104, 6), L('M236 70 H316', w=2), T(276, 64, '거래 내역', 8.5, 800),
         ''.join(L(f'M244 {84 + i * 16} h30', c=GREY, w=2) + L(f'M284 {84 + i * 16} h22', c=RED if i == 2 else GREY, w=2.2) for i in range(4)),
         oval(276, 116, 38, 9, RED)]
    return svg(330, 200, '#eef6f0', ''.join(b))


def ind_building():
    room = (f'<path d="M18 46 L58 66 V150 L18 166 Z" fill="#f6efe6" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>'
            + f'<path d="M58 66 H132 V150 H58" fill="#fffaf3" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>'
            + R(76, 80, 34, 26, 2, '#dcecff', NAVY, 1.8) + L('M93 80 V106', w=1.6)
            + L('M118 98 l-6 10 l5 6 l-6 12', c=RED, w=2.4))
    b = [room, ring(114, 112, 18),
         calendar(176, 74, '5/20'), T(204, 148, '처음 발견', 9, 800),
         doc(250, 46, 64, 104, '견적서'), lines(258, 76, [40, 30, 44]), L('M258 118 h28', w=1.6), T(306, 134, '₩320,000', 8.5, 900, NAVY, 'end')]
    return svg(330, 200, '#fff2e6', ''.join(b))


def ind_other():
    b = [box(30, 92, 74, 54), receipt(46, 42, 44, 52, ''), lines(54, 58, [26, 20, 28], 8),
         R(140, 58, 70, 40, 12), T(175, 84, '무슨 일?', 10, 900), L('M154 98 l-4 10 l12 -10', w=2, f='#fff'),
         R(150, 112, 70, 34, 12, CREAM, NAVY, 2), T(185, 134, '원하는 해결', 9, 900, ORANGE),
         f'<path d="M244 72 H272 L280 80 H316 V148 H244 Z" fill="#f6d9b4" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>',
         R(256, 62, 40, 48, 3, '#fff', NAVY, 1.6), R(266, 58, 40, 48, 3, '#fff', NAVY, 1.6), lines(272, 72, [26, 20], 8),
         f'<path d="M244 94 H316 V148 H244 Z" fill="#f0c48f" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>']
    return svg(330, 200, '#f1f3f7', ''.join(b))




def ind_appliance():
    tv = (R(18, 50, 110, 72, 6, NAVY, NAVY) + '<rect x="24" y="56" width="98" height="60" rx="3" fill="#fff"/>'
          + f'<circle cx="73" cy="80" r="12" fill="#ffe9e9"/>' + T(73, 85, '!', 14, 900, RED) + T(73, 108, '오류 E-04', 8.5, 800, RED)
          + L('M58 122 l-8 18 M88 122 l8 18 M44 140 h58', w=2.2))
    label = (R(156, 58, 70, 46, 5) + T(191, 74, '모델명', 8, 800, GREY) + hl(164, 82, 54, 13) + T(191, 92, 'TV-55Q7', 9, 900)
             + magnifier(212, 118, 14, '') + f'<circle cx="212" cy="118" r="4" fill="{ORANGE}"/>')
    rec = (f'<circle cx="290" cy="56" r="7" fill="{RED}"/>' + T(304, 60, 'REC', 8, 900, RED, 'start')
           + receipt(254, 76, 62, 92, '수리 내역') + lines(262, 108, [40, 32, 44]) + T(285, 156, '3회째', 9.5, 900, ORANGE))
    b = [tv, camera_corners(10, 42, 126, 108, 12), label, rec]
    return svg(330, 200, '#f1f3f7', ''.join(b))


def ind_medical():
    bag = (f'<path d="M22 56 H100 V156 H22 Z" fill="#fff" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>'
           + f'<rect x="23.1" y="57.1" width="75.8" height="18" fill="{SAGE}"/>' + T(61, 70, '약 봉투', 9.5, 900, '#fff')
           + lines(32, 90, [56, 40]) + hl(30, 108, 62, 13) + T(61, 118, '하루 3번 · 5일분', 8, 800)
           + R(36, 128, 22, 12, 6, PEACH, NAVY, 1.6) + R(64, 128, 22, 12, 6, '#fff', NAVY, 1.6))
    photos = ''.join(R(130 + i * 50, 66, 42, 54, 5) + f'<circle cx="{151 + i * 50}" cy="90" r="{6 + i * 4}" fill="#f2a7a0" opacity=".85"/>'
                     + T(151 + i * 50, 136, d, 9, 900, ORANGE) for i, d in enumerate(('3/2', '3/9')))
    paper = doc(244, 44, 70, 108, '소견서') + lines(254, 74, [48, 36, 44]) + L('M254 114 h28', w=1.6) + f'<circle cx="292" cy="132" r="10" fill="none" stroke="{RED}" stroke-width="2"/>'
    b = [bag, photos, L('M222 94 h-6', c='#c4c9d2', w=2), arrow(176, 154, 196), paper]
    return svg(330, 200, '#eef6f0', ''.join(b))


def ind_game():
    screen = (f'<rect x="0" y="0" width="48" height="40" fill="{LIGHT}"/>' + f'<path d="M24 8 l10 10 l-10 10 l-10 -10z" fill="{ORANGE}" stroke="{NAVY}" stroke-width="1.4"/>'
              + T(24, 54, '전설 상자', 8, 900) + T(24, 68, '확률 1%', 8, 800, RED) + R(6, 76, 36, 14, 4, NAVY, NAVY, 1) + T(24, 86, '구매', 8, 900, '#fff'))
    b = [phone(26, 44, 58, 112, screen), ring(55, 113, 24),
         receipt(118, 48, 76, 104, '결제 영수증'), lines(128, 80, [44, 34]), hl(126, 98, 60, 13), T(156, 108, '₩33,000', 9.5, 900), lines(128, 124, [50, 30]),
         R(218, 64, 96, 64, 8), f'<rect x="219.1" y="65.1" width="93.8" height="16" rx="7" fill="{RED}"/>', T(266, 77, '이용 제한', 9, 900, '#fff'),
         T(266, 100, 'ID: hero***', 9, 800), T(266, 116, '서버: 바람', 9, 800, GREY)]
    return svg(330, 200, '#f1f3f7', ''.join(b))


INDUSTRY_ART = {
    'food': ind_food, 'medical': ind_medical, 'commerce': ind_commerce, 'appliance': ind_appliance, 'car': ind_car,
    'telecom': ind_telecom, 'finance': ind_finance, 'game': ind_game, 'building': ind_building, 'other': ind_other,
}


if __name__ == '__main__':
    img = Path(__file__).resolve().parent.parent / 'static' / 'img'
    for i, f in enumerate((cut1, cut2, cut3), 1):
        (img / f'guide-cut{i}.svg').write_text(f(), encoding='utf-8')
    for name, f in INDUSTRY_ART.items():
        (img / f'guide-ind-{name}.svg').write_text(f(), encoding='utf-8')
    print('saved', 3 + len(INDUSTRY_ART), 'illustrations to', img)
