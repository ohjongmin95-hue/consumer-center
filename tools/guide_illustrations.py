"""이용 안내 그림을 다시 그리는 스크립트 (사람 없이 사물 위주, 메인 일러스트와 같은 선·색).
- static/img/guide-cut1~3.svg : "이 세 가지만 담아 주세요" 3컷
- static/img/guide-ind-<이름>.svg : 업종별 그림. 주황 번호(1·2·3)가 화면의 챙길 점 번호와 짝을 이룸
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


# ---------- 업종별 (330x200, 왼쪽부터 1·2·3) ----------
def ind_telecom():
    plan = (T(24, 16, '요금제', 8.5, 800, GREY) + T(24, 38, '59,000', 12, 900) + T(24, 54, '약정 24개월', 7.5, 700, NAVY) + hl(4, 64, 40, 8) + lines(6, 84, [34, 26], 9))
    b = [phone(30, 44, 58, 112, plan), mark(30, 44, 1),
         receipt(130, 40, 72, 112, '청구서'), lines(140, 72, [40, 30, 44]), L('M140 104 h28', c=RED, w=2.4), L('M178 104 h14', c=RED, w=2.4),
         oval(166, 104, 34, 10, RED), lines(140, 120, [44, 30]), mark(130, 40, 2),
         f'<g transform="translate(268 96)"><path d="M0 26 C-24 0 -18 -30 0 -30 C18 -30 24 0 0 26Z" fill="#fff" stroke="{NAVY}" stroke-width="2.2"/><circle cy="-8" r="7" fill="{ORANGE}"/></g>',
         ''.join(f'<rect x="{248 + i * 10}" y="{150 - (i + 1) * 7}" width="6" height="{(i + 1) * 7}" rx="1" fill="{NAVY if i < 1 else LIGHT}"/>' for i in range(4)),
         T(286, 148, '12:40', 9, 800), mark(244, 60, 3)]
    return svg(330, 200, '#f1f3f7', ''.join(b))


def ind_mobile():
    back = f'<rect x="8" y="6" width="18" height="22" rx="5" fill="{LIGHT}"/>' + T(24, 90, '모델명', 7.5, 800, GREY)
    err = f'<circle cx="24" cy="36" r="13" fill="#ffe9e9"/>' + T(24, 41, '!', 15, 900, RED) + lines(8, 62, [32, 24], 9) + f'<circle cx="38" cy="86" r="4" fill="{RED}"/>'
    b = [phone(28, 44, 58, 112, back), hl(36, 104, 42, 13), T(57, 114, 'SM-A123', 8, 800), mark(28, 44, 1),
         phone(136, 44, 58, 112, err), mark(136, 44, 2), camera_corners(128, 36, 74, 128, 12),
         receipt(248, 48, 62, 100, '수리 내역'), lines(256, 80, [40, 32, 44, 28]),
         L('M266 128 l12 -12 m-2 -4 a6 6 0 1 0 8 8', c=ORANGE, w=2.4), mark(248, 48, 3)]
    return svg(330, 200, '#f1f3f7', ''.join(b))


def ind_appliance():
    b = [R(24, 40, 82, 112, 8), L('M24 62 H106', w=2), f'<circle cx="65" cy="106" r="28" fill="{LIGHT}" stroke="{NAVY}" stroke-width="2.2"/>',
         f'<circle cx="65" cy="106" r="18" fill="#fff" stroke="{NAVY}" stroke-width="1.6"/>', R(34, 47, 22, 9, 3, PEACH, NAVY, 1.4),
         f'<path d="M84 152 q6 10 0 14 q-6 -4 0 -14Z" fill="#8ec5ff" stroke="{NAVY}" stroke-width="1.4"/>', ring(86, 160, 13), mark(24, 40, 1),
         doc(134, 44, 70, 104, '계약서'), lines(142, 74, [44, 36]), hl(140, 92, 54, 12), T(167, 101, '약정 36개월', 8.5, 800), lines(142, 118, [46, 30]), mark(134, 44, 2),
         calendar(248, 66, '9/14'), L('M262 134 l7 7 l14 -14', c=GREEN, w=3), T(276, 160, '점검·수리', 9, 800), mark(244, 56, 3)]
    return svg(330, 200, '#eef6f0', ''.join(b))


def ind_car():
    car = (f'<path d="M12 116 L22 92 Q28 82 42 80 L70 78 Q82 66 98 64 H126 Q142 66 152 80 L166 84 Q178 88 178 104 V116 Z" fill="{PEACH}" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>'
           + L('M80 80 L100 68 H124 L136 80 Z', w=2, f='#fff') + f'<circle cx="48" cy="118" r="14" fill="{NAVY}"/><circle cx="48" cy="118" r="5" fill="#fff"/>'
           + f'<circle cx="146" cy="118" r="14" fill="{NAVY}"/><circle cx="146" cy="118" r="5" fill="#fff"/>')
    b = [f'<g transform="translate(-4 8) scale(.92)">{car}</g>', ring(130, 117, 18), magnifier(118, 54, 18, L('M110 50 l8 6 l6 -8', c=RED, w=2.2)),
         L('M126 66 L130 98', c=ORANGE, w=1.6, extra=' stroke-dasharray="3 3"'), mark(18, 70, 1),
         doc(184, 46, 62, 100, '정비'), lines(192, 76, [40, 30, 44]), L('M196 118 l10 -10 m-2 -4 a6 6 0 1 0 8 8', c=ORANGE, w=2.4), mark(184, 46, 2),
         R(262, 52, 52, 40, 5), T(288, 76, '이용 전', 8.5, 800), R(262, 104, 52, 40, 5), T(288, 128, '이용 후', 8.5, 800), L('M300 112 l6 10', c=RED, w=2.4), mark(262, 52, 3)]
    return svg(330, 200, '#fff2e6', ''.join(b))


def ind_food():
    b = [f'<path d="M26 54 H104 L98 156 H32 Z" fill="#fff" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>', R(26, 40, 78, 16, 4, ORANGE, NAVY, 2),
         T(65, 90, '고소한 과자', 10, 900), lines(42, 104, [46, 38]), hl(36, 128, 58, 14), T(65, 138, '소비기한 26.10.12', 7.5, 800), mark(26, 40, 1),
         f'<path d="M140 104 H222 Q220 146 181 148 Q142 146 140 104Z" fill="{LIGHT}" stroke="{NAVY}" stroke-width="2.2"/>', L('M136 104 H226', w=2.4),
         f'<circle cx="196" cy="114" r="3" fill="{NAVY}"/>', ring(196, 114, 10), magnifier(212, 62, 18, f'<circle cx="212" cy="62" r="4" fill="{NAVY}"/>'), mark(140, 96, 2),
         R(252, 60, 62, 76, 6, '#fffbe6', NAVY, 2), T(283, 82, '개봉 전', 9.5, 800, NAVY), L('M262 92 h42', c=LIGHT, w=1.5),
         T(283, 110, '10/3 저녁', 9.5, 800, ORANGE), T(283, 126, '발견', 9, 700, GREY), mark(252, 60, 3)]
    return svg(330, 200, '#fff2e6', ''.join(b))


def ind_commerce():
    page = (R(20, 44, 116, 104, 8) + L('M20 60 H136', w=2) + ''.join(f'<circle cx="{30 + i * 8}" cy="52" r="2.2" fill="{GREY}"/>' for i in range(3))
            + f'<rect x="30" y="70" width="40" height="40" rx="4" fill="{SAGE}"/>' + lines(78, 74, [44, 34], 10)
            + hl(76, 96, 50, 12) + T(101, 105, '새 상품·정품', 8.5, 800) + R(78, 118, 46, 16, 4, ORANGE, ORANGE, 1) + T(101, 129, '구매', 8.5, 900, '#fff'))
    b = [page, mark(20, 44, 1), T(165, 106, '≠', 30, 900, RED),
         box(188, 98, 70, 50, True), f'<rect x="204" y="80" width="34" height="34" rx="4" fill="{SAGE}" stroke="{NAVY}" stroke-width="2"/>',
         L('M212 88 l10 12 l-6 6', c=RED, w=2.4), ring(222, 96, 20), mark(188, 70, 2),
         R(270, 64, 50, 30, 10, '#fff', NAVY, 1.8), T(295, 83, '환불요청', 8.5, 800), T(295, 108, '3/5', 10, 900, ORANGE), mark(274, 58, 3)]
    return svg(330, 200, '#f1f3f7', ''.join(b))


def ind_fashion():
    b = [f'<path d="M28 64 L52 48 Q66 58 80 48 L104 64 L94 82 L86 78 V150 H46 V78 L38 82 Z" fill="{PEACH}" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>',
         f'<ellipse cx="72" cy="112" rx="8" ry="6" fill="#b88b6a" opacity=".8"/>', ring(72, 112, 14), mark(28, 50, 1),
         f'<path d="M150 58 H210 V138 L180 150 L150 138 Z" fill="#fff" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>',
         T(180, 76, '세탁 방법', 9, 800), L('M162 92 h14 l-2 10 h-10z', w=1.8), T(196, 102, '30°', 9, 800),
         L('M164 116 l10 10 m0 -10 l-10 10', w=1.8), L('M188 118 h14 l-7 10z', w=1.8), mark(150, 58, 2),
         R(256, 72, 46, 80, 8, '#fff', NAVY, 2.2), R(266, 56, 26, 18, 3, ORANGE, NAVY, 2), T(279, 96, 'SERUM', 8, 900),
         hl(260, 108, 38, 26), lines(264, 114, [30, 22, 28], 7, NAVY), mark(256, 56, 3)]
    return svg(330, 200, '#fff2e6', ''.join(b))


def ind_travel():
    ticket = (R(18, 60, 120, 76, 8) + f'<rect x="19.1" y="61.1" width="117.8" height="16" rx="7" fill="{NAVY}"/>' + T(78, 73, '예약 확정', 9, 800, '#fff')
              + T(40, 98, 'ICN', 13, 900) + T(116, 98, 'NRT', 13, 900) + L('M60 94 h36 m-6 -4 l6 4 l-6 4', c=GREY, w=2) + hl(26, 110, 104, 14) + T(78, 120, '취소 규정: 3일 전 무료', 8.5, 800))
    sms = (T(24, 18, '문자', 8.5, 800, GREY) + R(4, 28, 44, 50, 8, LIGHT, LIGHT, 1) + T(26, 46, '결항', 10, 900, RED) + T(26, 62, '안내', 9, 800) + lines(6, 92, [36, 26], 8))
    b = [ticket, mark(18, 56, 1), phone(158, 46, 58, 110, sms), mark(158, 46, 2),
         R(240, 56, 76, 84, 6), f'<path d="M248 132 V96 L266 84 L284 96 V132 Z" fill="{PEACH}" stroke="{NAVY}" stroke-width="1.8"/>',
         R(290, 90, 18, 42, 2, LIGHT, NAVY, 1.6), f'<circle cx="300" cy="72" r="6" fill="{ORANGE}"/>', camera_corners(234, 50, 88, 96, 11), mark(240, 50, 3)]
    return svg(330, 200, '#eef6f0', ''.join(b))


def ind_platform():
    app = (T(24, 18, '구독 관리', 8.5, 800, GREY) + R(4, 28, 44, 34, 6, CREAM, CREAM, 1) + T(26, 42, '이용 중', 8.5, 800, ORANGE) + T(26, 56, '9,900/월', 8.5, 900)
           + lines(6, 76, [36, 28], 8))
    b = [phone(28, 44, 58, 112, app), mark(28, 44, 1),
         box(138, 96, 74, 52), f'<g transform="translate(206 84)"><circle r="18" fill="#fff" stroke="{NAVY}" stroke-width="2.2"/>' + L('M0 -10 V0 L8 6', w=2.4) + '</g>',
         T(175, 170, '배송 지연', 9, 800, RED), mark(138, 70, 2),
         R(244, 70, 72, 34, 8, ORANGE, ORANGE, 1), T(280, 92, '해지 신청', 10, 900, '#fff'), L('M262 120 l7 7 l14 -14', c=GREEN, w=3),
         T(296, 128, '4/1', 10, 900, NAVY), mark(244, 64, 3)]
    return svg(330, 200, '#f1f3f7', ''.join(b))


def ind_finance():
    b = [doc(22, 40, 84, 116, '약관'), lines(32, 72, [56, 44]), hl(30, 90, 68, 22), lines(34, 96, [56, 44], 8, NAVY), lines(32, 124, [56, 40]), mark(22, 40, 1),
         doc(146, 52, 60, 84, ''), lines(154, 74, [38, 30, 40, 26]), camera_corners(136, 42, 80, 104, 12), mark(136, 42, 2),
         R(236, 50, 80, 104, 6), L('M236 70 H316', w=2), T(276, 64, '거래 내역', 8.5, 800),
         ''.join(L(f'M244 {84 + i * 16} h30', c=GREY, w=2) + L(f'M284 {84 + i * 16} h22', c=RED if i == 2 else GREY, w=2.2) for i in range(4)),
         oval(276, 116, 38, 9, RED), mark(236, 50, 3)]
    return svg(330, 200, '#eef6f0', ''.join(b))


def ind_building():
    room = (f'<path d="M18 46 L58 66 V150 L18 166 Z" fill="#f6efe6" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>'
            + f'<path d="M58 66 H132 V150 H58" fill="#fffaf3" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>'
            + R(76, 80, 34, 26, 2, '#dcecff', NAVY, 1.8) + L('M93 80 V106', w=1.6)
            + L('M118 98 l-6 10 l5 6 l-6 12', c=RED, w=2.4))
    b = [room, ring(114, 112, 18), mark(18, 46, 1),
         calendar(176, 74, '5/20'), T(204, 148, '처음 발견', 9, 800), mark(172, 64, 2),
         doc(250, 46, 64, 104, '견적서'), lines(258, 76, [40, 30, 44]), L('M258 118 h28', w=1.6), T(306, 134, '₩320,000', 8.5, 900, NAVY, 'end'), mark(250, 46, 3)]
    return svg(330, 200, '#fff2e6', ''.join(b))


def ind_other():
    b = [box(30, 92, 74, 54), receipt(46, 42, 44, 52, ''), lines(54, 58, [26, 20, 28], 8), mark(26, 56, 1),
         R(140, 58, 70, 40, 12), T(175, 84, '무슨 일?', 10, 900), L('M154 98 l-4 10 l12 -10', w=2, f='#fff'),
         R(150, 112, 70, 34, 12, CREAM, NAVY, 2), T(185, 134, '원하는 해결', 9, 900, ORANGE), mark(140, 52, 2),
         f'<path d="M244 72 H272 L280 80 H316 V148 H244 Z" fill="#f6d9b4" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>',
         R(256, 62, 40, 48, 3, '#fff', NAVY, 1.6), R(266, 58, 40, 48, 3, '#fff', NAVY, 1.6), lines(272, 72, [26, 20], 8),
         f'<path d="M244 94 H316 V148 H244 Z" fill="#f0c48f" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>', mark(244, 62, 3)]
    return svg(330, 200, '#f1f3f7', ''.join(b))


INDUSTRY_ART = {
    'telecom': ind_telecom, 'mobile': ind_mobile, 'appliance': ind_appliance, 'car': ind_car, 'food': ind_food, 'commerce': ind_commerce,
    'fashion': ind_fashion, 'travel': ind_travel, 'platform': ind_platform, 'finance': ind_finance, 'building': ind_building, 'other': ind_other,
}

if __name__ == '__main__':
    img = Path(__file__).resolve().parent.parent / 'static' / 'img'
    for i, f in enumerate((cut1, cut2, cut3), 1):
        (img / f'guide-cut{i}.svg').write_text(f(), encoding='utf-8')
    for name, f in INDUSTRY_ART.items():
        (img / f'guide-ind-{name}.svg').write_text(f(), encoding='utf-8')
    print('saved', 3 + len(INDUSTRY_ART), 'illustrations to', img)
