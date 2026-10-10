"""이용 안내 페이지 만화 3컷(static/img/guide-cut1~3.svg)을 다시 그리는 스크립트.
메인 화면 일러스트와 같은 그림체. 실행: python3 tools/guide_illustrations.py"""
from pathlib import Path
NAVY='#2b3a55';SAGE='#8dbf9e';PEACH='#ffc38f';ORANGE='#ef7300';RED='#e5484d';GREY='#9aa6b8'
def L(d,c=NAVY,w=2.2,f='none'):return f'<path d="{d}" fill="{f}" stroke="{c}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>'

def head(x,y,mood='plain',hair='short',hc=NAVY):
    h=[]
    if hair=='long':h.append(f'<path d="M{x-27} {y+30} Q{x-30} {y-30} {x} {y-30} Q{x+30} {y-30} {x+27} {y+30} Z" fill="{hc}"/>')
    h.append(f'<ellipse cx="{x}" cy="{y}" rx="21" ry="23" fill="#fff" stroke="{NAVY}" stroke-width="2"/>')
    if hair=='short':h.append(f'<path d="M{x-21} {y-4} Q{x-22} {y-26} {x} {y-25} Q{x+22} {y-26} {x+21} {y-4} Q{x+8} {y-16} {x-21} {y-4} Z" fill="{hc}"/>')
    if hair=='long':h.append(f'<path d="M{x-21} {y-2} Q{x-18} {y-25} {x+2} {y-24} Q{x+20} {y-23} {x+21} {y-2} Q{x+4} {y-12} {x-6} {y-20} Q{x-12} {y-6} {x-21} {y-2} Z" fill="{hc}"/>')
    ey=y+1
    if mood=='shock':
        h+= [f'<circle cx="{x-8}" cy="{ey}" r="3" fill="{NAVY}"/>',f'<circle cx="{x+8}" cy="{ey}" r="3" fill="{NAVY}"/>',
             f'<ellipse cx="{x}" cy="{y+13}" rx="3.6" ry="4.6" fill="{NAVY}"/>',L(f'M{x-13} {ey-9} L{x-4} {ey-7}',w=2),L(f'M{x+13} {ey-9} L{x+4} {ey-7}',w=2)]
    elif mood=='focus':
        h+= [f'<circle cx="{x-8}" cy="{ey}" r="2.4" fill="{NAVY}"/>',f'<circle cx="{x+8}" cy="{ey}" r="2.4" fill="{NAVY}"/>',
             L(f'M{x-5} {y+13} L{x+5} {y+12}',w=2),L(f'M{x-12} {ey-7} L{x-4} {ey-8}',w=2),L(f'M{x+12} {ey-7} L{x+4} {ey-8}',w=2)]
    else:  # happy
        h+= [L(f'M{x-11} {ey} Q{x-8} {ey-4} {x-5} {ey}',w=2),L(f'M{x+5} {ey} Q{x+8} {ey-4} {x+11} {ey}',w=2),
             L(f'M{x-6} {y+11} Q{x} {y+17} {x+6} {y+11}',w=2),f'<circle cx="{x-13}" cy="{y+8}" r="3" fill="#ffb4a8" opacity=".7"/>',f'<circle cx="{x+13}" cy="{y+8}" r="3" fill="#ffb4a8" opacity=".7"/>']
    return ''.join(h)
def body(x,y,c,bottom):
    return (f'<rect x="{x-7}" y="{y+19}" width="14" height="12" fill="#fff" stroke="{NAVY}" stroke-width="1.8"/>'
            f'<path d="M{x-44} {bottom} Q{x-46} {y+36} {x-16} {y+30} L{x+16} {y+30} Q{x+46} {y+36} {x+44} {bottom} Z" fill="{c}"/>'
            + L(f'M{x-9} {y+30} L{x} {y+40} L{x+9} {y+30}',c='#00000033',w=2))
def arm(pts,c):
    d='M'+' L'.join(f'{a} {b}' for a,b in pts)
    return L(d,c=c,w=17)+f'<circle cx="{pts[-1][0]}" cy="{pts[-1][1]}" r="7.5" fill="#fff" stroke="{NAVY}" stroke-width="1.8"/>'
def spark(x,y,s=1,c=ORANGE):return f'<path transform="translate({x} {y}) scale({s})" d="M0 -9 Q1 -1 9 0 Q1 1 0 9 Q-1 1 -9 0 Q-1 -1 0 -9Z" fill="{c}"/>'
def panel(inner,bg):
    return f'<svg viewBox="0 0 300 220" xmlns="http://www.w3.org/2000/svg"><rect width="300" height="220" rx="14" fill="{bg}"/><g>{inner}</g></svg>'


# 컷1: 영수증 확인
p1=[body(118,112,SAGE,222),
    '<g transform="translate(186 112) rotate(7)">'
    f'<path d="M-32 -56 L32 -56 L32 50 L24 56 L16 50 L8 56 L0 50 L-8 56 L-16 50 L-24 56 L-32 50 Z" fill="#fff" stroke="{NAVY}" stroke-width="2"/>'
    f'<text x="0" y="-37" text-anchor="middle" font-size="11" font-weight="800" fill="{NAVY}" font-family="sans-serif">영수증</text>'
    + L('M-22 -24 L10 -24',c=GREY,w=2)+f'<text x="22" y="-20" text-anchor="end" font-size="8" fill="{ORANGE}" font-weight="800" font-family="sans-serif">날짜</text>'
    + L('M-22 -10 L4 -10',c=GREY,w=2)+f'<text x="22" y="-6" text-anchor="end" font-size="8" fill="{ORANGE}" font-weight="800" font-family="sans-serif">상품</text>'
    + L('M-22 4 L8 4',c=GREY,w=2)+L('M-22 30 L22 30',c=NAVY,w=1.5)
    + f'<text x="0" y="24" text-anchor="middle" font-size="12" font-weight="900" fill="{NAVY}" font-family="sans-serif">₩ 59,000</text></g>',
    arm([(150,152),(160,184),(164,174)],SAGE), head(118,90,'focus'),
    spark(46,46,1)+spark(258,40,.7,'#ffc38f')]
# 컷2: 겪은 일을 순서대로 (말풍선 속 1-2-3)
bub=('<g>'+f'<path d="M138 26 H276 a10 10 0 0 1 10 10 V138 a10 10 0 0 1 -10 10 H160 L140 164 L146 148 H138 a10 10 0 0 1 -10 -10 V36 a10 10 0 0 1 10 -10 Z" fill="#fff" stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round"/>'
     + L('M152 52 L152 120',c='#e3e5e8',w=2))
for i,(t,c) in enumerate([('문제',RED),('요청',NAVY),('답변',ORANGE)]):
    y=52+i*34
    bub+=(f'<circle cx="152" cy="{y}" r="9" fill="{c}"/><text x="152" y="{y+4}" text-anchor="middle" font-size="10" font-weight="900" fill="#fff" font-family="sans-serif">{i+1}</text>'
          f'<text x="170" y="{y+4}" font-size="11" font-weight="800" fill="{NAVY}" font-family="sans-serif">{t}</text>'+L(f'M204 {y} L{268-i*14} {y}',c=GREY,w=2))
p2=[body(84,118,PEACH,222),head(84,96,'happy','long','#7a4b2a'),bub+'</g>',spark(36,40,.9)]
# 컷3: 자료 캡처
p3=[body(92,112,NAVY,222),head(92,90,'focus','short','#3a2a1e'),arm([(126,152),(146,178),(160,176)],NAVY),
    '<g transform="translate(200 112)">'
    f'<rect x="-40" y="-74" width="80" height="148" rx="12" fill="{NAVY}"/><rect x="-34" y="-64" width="68" height="128" rx="5" fill="#fff"/>'
    f'<rect x="-26" y="-54" width="52" height="40" rx="4" fill="#eef6f0"/><circle cx="-12" cy="-40" r="5" fill="{SAGE}"/><path d="M-26 -18 L-8 -32 L4 -24 L14 -32 L26 -20 V-14 H-26Z" fill="{SAGE}"/>'
    + ''.join(L(f'M-24 {yy} L{20-k*10} {yy}',c=GREY,w=2) for k,yy in enumerate((0,10,20)))
    + f'<ellipse cx="0" cy="40" rx="20" ry="9" fill="none" stroke="{RED}" stroke-width="2"/>'+L('M-12 40 L12 40',c=NAVY,w=2)
    + ''.join(L(d,c=ORANGE,w=3) for d in ('M-44 -60 L-44 -78 L-26 -78','M26 -78 L44 -78 L44 -60','M-44 60 L-44 78 L-26 78','M26 78 L44 78 L44 60'))+'</g>',
    f'<circle cx="160" cy="176" r="7.5" fill="#fff" stroke="{NAVY}" stroke-width="1.8"/>',
    f'<g transform="translate(262 30)"><rect x="-26" y="-13" width="52" height="26" rx="13" fill="{ORANGE}"/><text x="0" y="5" text-anchor="middle" font-size="12" font-weight="900" fill="#fff" font-family="sans-serif">찰칵!</text></g>']
panels=[panel(''.join(p1),'#eef6f0'),panel(''.join(p2),'#fff2e6'),panel(''.join(p3),'#f1f3f7')]

IMG=Path(__file__).resolve().parent.parent/'static'/'img'
for i,svg in enumerate(panels,1):(IMG/f'guide-cut{i}.svg').write_text(svg+'\n',encoding='utf-8')
print('saved',len(panels),'illustrations to',IMG)
