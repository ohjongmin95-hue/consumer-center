"""메인 화면 양옆 일러스트(static/img/hero-left.svg, hero-right.svg)를 만든다.

사용법: python tools/make_hero_art.py  (저장소 루트에서 실행)
사람·소품 모양을 바꾸려면 아래 함수를 고친 뒤 다시 실행하면 된다.
"""
from pathlib import Path

SKIN = ['#f6c9a8', '#eab48f', '#f9d6bd', '#d99c76', '#f3c1a0']
INK = '#2b3a55'


def legs(pants, shoe='#1e2a40', skirt=None):
    if skirt:
        return (f'<rect x="-17" y="-70" width="13" height="70" rx="6" fill="{SKIN[2]}"/>'
                f'<rect x="4" y="-70" width="13" height="70" rx="6" fill="{SKIN[2]}"/>'
                f'<path d="M-34 -100 L34 -100 L42 -58 Q0 -50 -42 -58 Z" fill="{skirt}"/>'
                f'<ellipse cx="-11" cy="-3" rx="13" ry="6" fill="{shoe}"/><ellipse cx="11" cy="-3" rx="13" ry="6" fill="{shoe}"/>')
    return (f'<rect x="-21" y="-100" width="18" height="100" rx="9" fill="{pants}"/>'
            f'<rect x="3" y="-100" width="18" height="100" rx="9" fill="{pants}"/>'
            f'<ellipse cx="-13" cy="-3" rx="14" ry="6" fill="{shoe}"/><ellipse cx="13" cy="-3" rx="14" ry="6" fill="{shoe}"/>')


def torso(color):
    return f'<path d="M-36 -178 Q-38 -206 -14 -210 L14 -210 Q38 -206 36 -178 L32 -98 Q0 -92 -32 -98 Z" fill="{color}"/>'


def arm(d, color, hand, skin):
    x, y = hand
    return (f'<path d="{d}" fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<circle cx="{x}" cy="{y}" r="8" fill="{skin}"/>')


def head(skin, hair_back='', hair_front='', glasses=False, mood='smile'):
    face = (f'<circle cx="-9" cy="-246" r="2.8" fill="{INK}"/><circle cx="9" cy="-246" r="2.8" fill="{INK}"/>'
            f'<circle cx="-16" cy="-236" r="4.5" fill="#f29a7e" opacity=".45"/><circle cx="16" cy="-236" r="4.5" fill="#f29a7e" opacity=".45"/>')
    face += {
        'smile': f'<path d="M-6 -235 Q0 -229 6 -235" fill="none" stroke="{INK}" stroke-width="2.6" stroke-linecap="round"/>',
        'open': f'<path d="M-6 -236 Q0 -226 6 -236 Z" fill="{INK}"/>',
        'calm': f'<path d="M-5 -234 L5 -234" stroke="{INK}" stroke-width="2.6" stroke-linecap="round"/>',
    }[mood]
    if glasses:
        face += (f'<circle cx="-9" cy="-246" r="7" fill="none" stroke="{INK}" stroke-width="2"/>'
                 f'<circle cx="9" cy="-246" r="7" fill="none" stroke="{INK}" stroke-width="2"/><path d="M-2 -246 L2 -246" stroke="{INK}" stroke-width="2"/>')
    return (hair_back + f'<rect x="-8" y="-222" width="16" height="16" rx="5" fill="{skin}"/>'
            f'<circle cx="0" cy="-246" r="27" fill="{skin}"/>' + hair_front + face)


def person(x, y, scale, parts):
    return f'<g transform="translate({x} {y}) scale({scale})">{"".join(parts)}</g>'


def receipt(x, y, rot=0):
    return (f'<g transform="translate({x} {y}) rotate({rot})"><path d="M-18 -26 h36 v52 l-6 -4 -6 4 -6 -4 -6 4 -6 -4 -6 4 z" fill="#fff" stroke="#e3cdb8" stroke-width="2"/>'
            f'<rect x="-11" y="-17" width="22" height="4" rx="2" fill="#ef7300"/><rect x="-11" y="-7" width="16" height="4" rx="2" fill="#e5ddd4"/>'
            f'<rect x="-11" y="2" width="19" height="4" rx="2" fill="#e5ddd4"/></g>')


def bubble(x, y, inner, w=64, h=44, tail='left'):
    tx = x - w / 2 + 14 if tail == 'left' else x + w / 2 - 14
    return (f'<g><rect x="{x - w / 2}" y="{y - h / 2}" width="{w}" height="{h}" rx="{h / 2}" fill="#fff" stroke="#f6c79c" stroke-width="2.5"/>'
            f'<path d="M{tx - 6} {y + h / 2 - 2} L{tx} {y + h / 2 + 12} L{tx + 7} {y + h / 2 - 2}" fill="#fff" stroke="#f6c79c" stroke-width="2.5" stroke-linejoin="round"/>'
            f'<rect x="{tx - 8}" y="{y + h / 2 - 5}" width="16" height="5" fill="#fff"/>{inner}</g>')


def bang(x, y):
    return f'<rect x="{x - 3.5}" y="{y - 13}" width="7" height="17" rx="3.5" fill="#ef7300"/><circle cx="{x}" cy="{y + 10}" r="4" fill="#ef7300"/>'


def dots(x, y):
    return ''.join(f'<circle cx="{x + dx}" cy="{y}" r="4" fill="{INK}"/>' for dx in (-12, 0, 12))


def heart(x, y, s=1.0, color='#ef7300'):
    return f'<path transform="translate({x} {y}) scale({s})" d="M0 12 C-16 2 -16 -12 -7 -12 C-3 -12 -1 -9 0 -7 C1 -9 3 -12 7 -12 C16 -12 16 2 0 12 Z" fill="{color}"/>'


def thumb(x, y):
    return f'<path transform="translate({x} {y})" d="M-9 10 V-2 H-14 V10 Z M-6 10 H8 C11 10 13 7 12 4 L9 -6 C8 -8 6 -9 4 -9 H0 L2 -16 C2 -19 0 -21 -3 -21 L-6 -9 Z" fill="#ef7300"/>'


def check_shield(x, y, s=1.0):
    return (f'<g transform="translate({x} {y}) scale({s})"><path d="M0 -40 L32 -29 V-4 C32 20 18 36 0 43 C-18 36 -32 20 -32 -4 V-29 Z" fill="#fff" stroke="#ef7300" stroke-width="5" stroke-linejoin="round"/>'
            f'<path d="M-13 1 L-3 11 L15 -9" fill="none" stroke="#2e9d5b" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></g>')


def sparkle(x, y, s=1.0, color='#ef7300', op=.55):
    return f'<path transform="translate({x} {y}) scale({s})" d="M0 -11 L3 -3 L11 0 L3 3 L0 11 L-3 3 L-11 0 L-3 -3 Z" fill="{color}" opacity="{op}"/>'


# 1. 영수증을 들고 손을 든 사람 (목소리를 내는 소비자)
def p_receipt(x, y, s=1.0):
    sk = SKIN[0]
    return person(x, y, s, [
        legs('#2b3a55'), torso('#ef7300'),
        arm('M30 -192 Q46 -160 30 -140', '#ef7300', (30, -138), sk),
        arm('M-30 -194 Q-52 -232 -46 -276', '#ef7300', (-46, -280), sk),
        receipt(-46, -312, -8),
        head(sk, hair_back='<path d="M-30 -250 C-32 -286 32 -286 30 -250 L34 -196 L-34 -196 Z" fill="#5b3a2c"/>',
             hair_front='<path d="M-27 -252 C-24 -278 22 -282 28 -252 C14 -262 -6 -266 -27 -252 Z" fill="#5b3a2c"/>', mood='open'),
    ])


# 2. 휴대폰으로 제보하는 사람
def p_phone(x, y, s=1.0):
    sk = SKIN[1]
    return person(x, y, s, [
        legs('#4b6fa8'), torso('#7cc49a'),
        '<path d="M-14 -210 L0 -194 L14 -210" fill="none" stroke="#5aa57b" stroke-width="4" stroke-linecap="round"/>',
        arm('M-30 -192 Q-40 -160 -8 -158', '#7cc49a', (-6, -160), sk),
        arm('M30 -192 Q42 -164 14 -164', '#7cc49a', (12, -166), sk),
        f'<rect x="-14" y="-196" width="24" height="40" rx="5" fill="{INK}"/><rect x="-11" y="-192" width="18" height="30" rx="2" fill="#fff7ef"/>'
        '<rect x="-8" y="-187" width="12" height="3" rx="1.5" fill="#ef7300"/><rect x="-8" y="-180" width="9" height="3" rx="1.5" fill="#f2c9a1"/>',
        head(sk, hair_front='<path d="M-28 -248 C-30 -280 26 -284 28 -252 C18 -262 -2 -262 -10 -256 C-16 -262 -24 -256 -28 -248 Z" fill="#2b3a55"/>', mood='smile'),
    ])


# 3. 쇼핑백을 든 어르신
def p_elder(x, y, s=1.0):
    sk = SKIN[2]
    return person(x, y, s, [
        legs('#5d6b82'), torso('#f49a7a'),
        '<path d="M-6 -208 L-6 -100 M6 -208 L6 -100" stroke="#e07f5f" stroke-width="3"/>'
        '<circle cx="0" cy="-170" r="2.6" fill="#fff"/><circle cx="0" cy="-150" r="2.6" fill="#fff"/><circle cx="0" cy="-130" r="2.6" fill="#fff"/>',
        arm('M-30 -192 Q-44 -150 -40 -112', '#f49a7a', (-40, -108), sk),
        '<path d="M-60 -110 h40 l6 52 h-52 z" fill="#ffd2a6"/><path d="M-50 -110 v-8 c0-8 6-12 10-12 s10 4 10 12 v8" fill="none" stroke="#e08a3c" stroke-width="3.5"/>'
        '<rect x="-50" y="-92" width="30" height="5" rx="2.5" fill="#fff" opacity=".7"/>',
        arm('M30 -192 Q44 -170 30 -150', '#f49a7a', (28, -148), sk),
        head(sk, hair_back='<circle cx="0" cy="-276" r="12" fill="#c9ccd3"/>',
             hair_front='<path d="M-28 -244 C-30 -280 28 -280 28 -244 C24 -258 10 -266 0 -262 C-10 -266 -24 -258 -28 -244 Z" fill="#c9ccd3"/>',
             glasses=True, mood='smile'),
    ])


# 4. 보호 배지를 든 사람 (가운데)
def p_shield(x, y, s=1.0):
    sk = SKIN[3]
    return person(x, y, s, [
        legs('#2b3a55'), torso('#ffd27a'),
        arm('M-30 -192 Q-40 -160 -22 -150', '#ffd27a', (-22, -150), sk),
        arm('M30 -192 Q40 -160 22 -150', '#ffd27a', (22, -150), sk),
        check_shield(0, -150, 1.05),
        head(sk, hair_back='<path d="M-28 -252 C-30 -284 30 -284 28 -252 L30 -222 L-30 -222 Z" fill="#1f1b2e"/>',
             hair_front='<path d="M-27 -250 C-26 -276 26 -280 27 -250 C10 -266 -10 -266 -27 -250 Z" fill="#1f1b2e"/>', mood='smile'),
    ])


# 5. 클립보드를 들고 엄지를 든 상담원
def p_staff(x, y, s=1.0):
    sk = SKIN[4]
    return person(x, y, s, [
        legs('#2b3a55', skirt='#2b3a55'), torso('#8db7ee'),
        '<path d="M-12 -208 L0 -176 L12 -208" fill="none" stroke="#fff" stroke-width="3"/><rect x="-9" y="-176" width="18" height="22" rx="3" fill="#fff"/><rect x="-6" y="-170" width="12" height="3" rx="1.5" fill="#ef7300"/>',
        arm('M-30 -192 Q-46 -160 -26 -140', '#8db7ee', (-24, -140), sk),
        '<rect x="-56" y="-176" width="36" height="48" rx="5" fill="#ffd2a6"/><rect x="-51" y="-169" width="26" height="36" rx="3" fill="#fff"/>'
        '<path d="M-46 -160 l3 3 6 -6 M-46 -148 l3 3 6 -6" fill="none" stroke="#2e9d5b" stroke-width="2.5" stroke-linecap="round"/><rect x="-44" y="-180" width="12" height="7" rx="3" fill="#2b3a55"/>',
        arm('M30 -192 Q50 -220 44 -250', '#8db7ee', (44, -254), sk),
        '<rect x="40" y="-276" width="8" height="16" rx="4" fill="' + sk + '"/>',
        head(sk, hair_back='<path d="M-30 -250 C-34 -290 34 -290 30 -250 L32 -214 L-32 -214 Z" fill="#7a4b33"/>',
             hair_front='<path d="M-28 -248 C-24 -282 28 -282 28 -248 C14 -270 -10 -270 -28 -248 Z" fill="#7a4b33"/>', mood='smile'),
    ])


def side_left():
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 330 360">'
            '<path d="M20 330 C0 220 60 110 170 100 C280 90 330 190 320 330 Z" fill="#fff1e3"/><ellipse cx="170" cy="338" rx="150" ry="13" fill="#f3dcc6"/>'
            + sparkle(36, 110, 1.0) + sparkle(290, 70, 1.1) + '<g fill="#ffc994"><circle cx="30" cy="250" r="6"/><circle cx="300" cy="170" r="5"/></g>'
            + p_receipt(105, 332, 1.0) + p_phone(240, 332, .97)
            + bubble(160, 46, bang(160, 44), w=52) + bubble(288, 90, dots(288, 90), w=70, tail='right') + '</svg>')


def side_right():
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 330 360">'
            '<path d="M10 330 C0 190 70 100 170 100 C280 100 330 200 320 330 Z" fill="#fff1e3"/><ellipse cx="165" cy="338" rx="155" ry="13" fill="#f3dcc6"/>'
            + sparkle(40, 80, 1.1) + '<g fill="#ffc994"><circle cx="310" cy="240" r="6"/><circle cx="30" cy="200" r="5"/></g>'
            + p_elder(70, 332, .9) + p_staff(270, 332, .95) + p_shield(170, 340, 1.0)
            + bubble(72, 42, heart(72, 43, .9, '#f49a7a'), w=54) + bubble(276, 34, thumb(278, 40), w=54, tail='right') + '</svg>')



if __name__ == '__main__':
    out = Path(__file__).resolve().parents[1] / 'static' / 'img'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'hero-left.svg').write_text(side_left() + '\n', encoding='utf-8')
    (out / 'hero-right.svg').write_text(side_right() + '\n', encoding='utf-8')
    print('saved', out / 'hero-left.svg', out / 'hero-right.svg')
