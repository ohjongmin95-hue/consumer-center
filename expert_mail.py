# 운영자 2026-11-03 (밤): 관리자 '자문단 섭외 메일'. 로펌마다 이름만 넣으면 하이웍스에 붙일 HTML 코드가 나옴.
# 문구는 관리자에서 고쳐 저장 (soboru_settings 'expert_mail'). 메일 안 링크·사진은 consumerjebo.co.kr 주소 그대로라 전달해도 작동.
import html, json, re

from flask import flash, redirect, render_template, request, url_for

KEY = 'expert_mail'
BASE = 'https://consumerjebo.co.kr'
FIRM = '○○ 법무법인'
F = "font-family:'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif;"

DEFAULTS = {
    'subject': '[소비자제보센터] 소속 변호사님께 ‘소보루 자문단’ 참여를 제안드립니다',
    'kick': '소보루 자문단 모집',
    'title': FIRM + ' 귀중\n소속 변호사님께 전해 주세요',
    'intro': '안녕하세요. 소비자 피해 제보 플랫폼 ‘소비자제보센터 by SOBORU’ 대표 오종민입니다. 갑작스러운 연락에 양해 부탁드립니다.\n\n'
             '저희는 올해 문을 열었습니다. 소비자 피해는 혼자서 기업을 상대하기 어렵습니다. 고객센터에 몇 번을 물어도 답이 없거나, 같은 피해가 여러 사람에게 되풀이되는데도 서로 모른 채 묻히는 일이 많습니다. '
             '소보루는 **‘소비자 권익 보호를 위한 루트’**라는 뜻으로, 이런 피해를 공개로 모아 함께 목소리를 내고 기업이 답하게 만들자는 취지로 시작했습니다.',
    'flow_title': '제보는 이렇게 해결돼요',
    'flow': '공개 제보 | 소비자가 겪은 일을 사진·자료와 함께 올려요.\n공감과 의견 | 같은 피해를 겪은 사람과 자문단이 힘을 보태요.\n'
            '기업 답변 | 제보를 기업에 전달하고, 답변을 공개해요.\n기사화 | 널리 알려야 할 일은 기사로 써요.',
    'ask': '소비자가 도움을 한곳에서 구하고 필요할 때 바로 자문받을 수 있도록, 함께해 주실 변호사님을 **‘소보루 자문단’**으로 모집하고 있습니다. '
           '소비자 분쟁, 전자상거래, 약관, 개인정보, 금융 분야에 관심 있는 변호사님께 이 메일을 전해 주시면 감사하겠습니다.',
    'do_title': '자문단은 이런 일을 해요',
    'do': '제보에 전문가 의견 | 어떤 법과 기준이 적용되는지, 소비자가 무엇을 요구할 수 있는지 짧게 남겨 주세요.\n'
          '소비자 질문에 답변 | 제보자와 공감한 소비자의 궁금증에 답해 주세요.\n'
          '기사 속 전문가 코멘트 | 기사로 나가는 제보에 의견이 이름과 소속 법인과 함께 실려요.\n'
          '같은 피해가 모인 사건 자문 | 여러 소비자가 같은 기업에 겪은 피해의 대응 방향을 함께 살펴 주세요.',
    'get_title': '함께하시면',
    'get': '변호사님마다 사진·이력·소속 법인을 담은 소개 페이지가 생기고, 남긴 의견이 그 페이지에 쌓여요.\n'
           '새 제보를 매일 저녁 6시에 메일로 받아, 원하는 제보에만 의견을 남기시면 돼요. 의무는 없어요.\n'
           '소비자의 상담 신청을 메일로 바로 받으세요. 소개와 연결에 저희는 어떤 비용도 받지 않아요.',
    'sample': '1',
    'note': '참여는 변호사님 개인별로 받아요. 여러 분이 함께하시면 모두 같은 법인 소속으로 소개돼요.',
    'cta': '자문단 참여하기',
    'cta_sub': '변호사님별로 소속·분야·사진·변호사 등록증만 올리면 돼요 (3분)',
    'sign': '전달해 주시는 것만으로도 큰 힘이 됩니다. 궁금한 점은 이 메일로 답장 주세요.\n감사합니다.\n\n**오종민 드림**\n소비자제보센터 by SOBORU 대표',
}
_LABELS = [('subject', '메일 제목', 1), ('kick', '맨 위 작은 글씨', 1), ('title', '큰 제목 (○○ 법무법인 자리에 이름이 들어가요)', 2),
          ('intro', '인사·소개 (빈 줄로 문단을 나눠요)', 8), ('flow_title', '해결 과정 제목', 1), ('flow', '해결 과정 (한 줄에 하나, 제목 | 설명)', 4),
          ('ask', '모집 안내', 4), ('do_title', '하는 일 제목', 1), ('do', '하는 일 (한 줄에 하나, 제목 | 설명)', 4),
          ('get_title', '좋은 점 제목', 1), ('get', '좋은 점 (한 줄에 하나)', 3), ('note', '참여 안내', 2),
          ('cta', '버튼 글자', 1), ('cta_sub', '버튼 밑 작은 글씨', 1), ('sign', '맺음말·서명', 5)]
SAMPLES = (('a1', '김서연', '소보루 법률사무소', '환불 분쟁을 주로 다뤄요'), ('a2', '박성훈', '법무법인 소보루', '중고차 계약 문제를 도와요'))


def _t(s, strong='#191f28'):
    """글자를 HTML로: 이스케이프, **굵게**, 줄바꿈."""
    s = html.escape(s or '', quote=False)
    parts = s.split('**')
    s = ''.join(p if i % 2 == 0 else f'<b style="color:{strong}">{p}</b>' for i, p in enumerate(parts))
    return s.replace('\n', '<br>')


def _pairs(s):
    out = []
    for line in (s or '').splitlines():
        if not line.strip(): continue
        a, _, b = line.partition('|')
        out.append((a.strip(), b.strip()))
    return out


def build(c, firm=''):
    """하이웍스에 붙일 메일 HTML (표 + 인라인 스타일, 버튼은 bgcolor 칸 안의 평범한 링크)."""
    firm = (firm or '').strip() or FIRM
    sub = lambda s: (s or '').replace(FIRM, firm)
    url = BASE + '/expert/apply'
    pp = lambda x: f'<p style="margin:0 0 16px;font-size:16px;line-height:27px;color:#4e5968;{F}">{_t(x)}</p>'
    h3 = lambda x, m='28px': f'<p style="margin:{m} 0 12px;font-size:17px;font-weight:700;color:#191f28;{F}">{_t(x)}</p>'
    li = lambda x: (f'<tr><td width="18" valign="top" style="padding:3px 8px 10px 0;color:#EF920E;font-size:15px;font-weight:700;{F}">✓</td>'
                    f'<td style="padding:0 0 10px;font-size:15px;line-height:23px;color:#4e5968;{F}">{x}</td></tr>')
    step = lambda n, t, d: (f'<tr><td width="28" valign="top" style="padding:0 12px 14px 0"><div style="width:28px;height:28px;line-height:28px;border-radius:14px;background:#EF920E;color:#ffffff;text-align:center;font-size:13px;font-weight:700;{F}">{n}</div></td>'
                            f'<td valign="top" style="padding:0 0 14px;font-size:15px;line-height:23px;color:#4e5968;{F}"><b style="color:#191f28">{_t(t)}</b><br>{_t(d)}</td></tr>')
    card = lambda a, n, o, i: (f'<td width="50%" valign="top" style="padding:0 6px"><table width="100%" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #e5e8eb;border-radius:20px;background:#ffffff">'
                               f'<tr><td style="padding:0;background:#e9e7e4;border-radius:20px 20px 0 0"><img src="{BASE}/static/img/advisors/{a}.jpg" width="260" alt="{n} 예시 사진" style="display:block;width:100%;max-width:260px;height:auto;border:0;border-radius:20px 20px 0 0"></td></tr>'
                               f'<tr><td style="padding:14px 16px 18px;{F}"><p style="margin:0 0 4px;font-size:13px;color:#6b7684;{F}">{o}</p>'
                               f'<p style="margin:0 0 6px;font-size:18px;font-weight:700;color:#191f28;{F}">{n} <span style="display:inline-block;padding:2px 8px;border-radius:8px;background:#e8f3ff;color:#1b64da;font-size:12px;font-weight:600;vertical-align:2px">자문단 · 변호사</span></p>'
                               f'<p style="margin:0;font-size:14px;line-height:21px;color:#4e5968;{F}">{i}</p></td></tr></table></td>')
    cards = ''
    if c.get('sample') == '1':
        cards = (f'<p style="margin:28px 0 6px;font-size:17px;font-weight:700;color:#191f28;{F}">자문단 소개는 이렇게 보여요 <span style="display:inline-block;margin-left:4px;padding:2px 8px;border-radius:6px;background:#4e5968;color:#ffffff;font-size:12px;font-weight:600;vertical-align:2px">예시</span></p>'
                 f'<p style="margin:0 0 14px;font-size:14px;line-height:22px;color:#6b7684;{F}">사진을 누르면 이력과 남긴 의견, 상담 신청이 담긴 변호사님 소개 페이지로 이어져요.</p>'
                 f'<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>{"".join(card(*s) for s in SAMPLES)}</tr></table>')
    intro = ''.join(pp(sub(p)) for p in (c.get('intro') or '').split('\n\n') if p.strip())
    flow = _pairs(c.get('flow'))
    flow_box = (f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:28px 0;background:#f9fafb;border-radius:20px"><tr><td style="padding:24px 24px 10px">'
                f'<p style="margin:0 0 16px;font-size:17px;font-weight:700;color:#191f28;{F}">{_t(c.get("flow_title"))}</p>'
                f'<table cellpadding="0" cellspacing="0" border="0">{"".join(step(i + 1, t, d) for i, (t, d) in enumerate(flow))}</table></td></tr></table>') if flow else ''
    does = ''.join(li(f'<b style="color:#191f28">{_t(t)}</b> {_t(d)}') for t, d in _pairs(c.get('do')))
    gets = ''.join(li(_t(g)) for g in (c.get('get') or '').splitlines() if g.strip())
    return f'''<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f2f4f6;padding:24px 0"><tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:24px;{F}">
<tr><td style="padding:40px 32px 36px">
<p style="margin:0 0 40px;font-size:22px;line-height:28px;font-weight:800;letter-spacing:-0.5px;color:#191f28;{F}"><span style="color:#EF920E">소비자</span>제보센터<span style="font-size:11px;font-weight:700;letter-spacing:0;color:#4e5968">&nbsp;&nbsp;by <span style="color:#652D1C;font-size:13px">SOBORU</span></span></p>
<p style="margin:0 0 8px;font-size:15px;font-weight:700;color:#CE6719;{F}">{_t(c.get('kick'))}</p>
<h1 style="margin:0 0 20px;font-size:28px;line-height:38px;font-weight:700;color:#191f28;{F}">{_t(sub(c.get('title')))}</h1>
{intro}{flow_box}{pp(sub(c.get('ask'))) if (c.get('ask') or '').strip() else ''}
{h3(c.get('do_title')) if does else ''}<table cellpadding="0" cellspacing="0" border="0">{does}</table>
{h3(c.get('get_title'), '20px') if gets else ''}<table cellpadding="0" cellspacing="0" border="0">{gets}</table>
{cards}
<p style="margin:16px 0 0;font-size:14px;line-height:22px;color:#4e5968;{F}">{_t(sub(c.get('note')))}</p>
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:32px 0 10px"><tr><td align="center" bgcolor="#EF920E" style="background:#EF920E;border-radius:16px;padding:17px 16px;{F}"><a href="{url}" target="_blank" style="color:#ffffff;font-size:17px;font-weight:700;text-decoration:none">{_t(c.get('cta'))}&nbsp;&rsaquo;</a></td></tr></table>
<p style="margin:0;text-align:center;font-size:13px;color:#8b95a1;{F}">{_t(c.get('cta_sub'))}</p>
<p style="margin:32px 0 0;font-size:15px;line-height:24px;color:#4e5968;{F}">{_t(sub(c.get('sign')))}</p>
</td></tr>
<tr><td style="padding:24px 32px 28px;background:#f9fafb;border-radius:0 0 24px 24px;font-size:12px;line-height:19px;color:#8b95a1;{F}">소비자제보센터 by SOBORU · <a href="{BASE}" target="_blank" style="color:#4e5968">consumerjebo.co.kr</a><br>contact@consumerjebo.co.kr · 서울시 강남구 논현로 310-1 4층<br>이 메일은 자문단 참여를 제안드리기 위해 한 번 보내 드렸어요.</td></tr>
</table></td></tr></table>'''


def install(S):
    app, conn = S.app, S.conn
    with conn() as db: db.execute('CREATE TABLE IF NOT EXISTS soboru_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')

    def load():
        with conn() as db: row = db.execute('SELECT value FROM soboru_settings WHERE key=?', (KEY,)).fetchone()
        try: saved = json.loads(row[0]) if row else {}
        except ValueError: saved = {}
        return saved if isinstance(saved, dict) else {}

    def clean_html(h):
        """관리자가 메일 화면에서 바로 고친 HTML. 스크립트·이벤트 속성만 걷어 냄."""
        h = re.sub(r'(?is)<(script|style|iframe|object|embed)\b.*?(</\1>|$)', '', h or '')
        h = re.sub(r'(?i)\s+on[a-z]+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', '', h)
        h = re.sub(r'(?i)\s+contenteditable\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', '', h)
        return re.sub(r'(?i)javascript:', '', h)[:200000]

    @app.route('/admin/experts/mail', methods=['GET', 'POST'])
    @S.admin_only
    def admin_expert_mail():
        if request.method == 'POST':
            act = request.form.get('act')
            with conn() as db:
                if act == 'reset':
                    db.execute('DELETE FROM soboru_settings WHERE key=?', (KEY,)); flash('처음 메일로 되돌렸어요.')
                else:
                    c = {'subject': ' '.join((request.form.get('subject') or '').split())[:200] or DEFAULTS['subject'],
                         'html': clean_html(request.form.get('html'))}
                    db.execute('INSERT OR REPLACE INTO soboru_settings(key,value) VALUES(?,?)', (KEY, json.dumps(c, ensure_ascii=False)))
                    flash('저장했어요.')
            return redirect(url_for('admin_expert_mail'))
        saved = load()
        tpl = saved.get('html') or build(DEFAULTS, FIRM)
        return render_template('admin_expert_mail.html', placeholder=FIRM, mail_template=tpl, subject=saved.get('subject') or DEFAULTS['subject'])
