"""소비자를위한신문 아침 데스크 (운영자 요청 2026-11-10): 매일 아침 경제·소비자 이슈를 골라 기사 초안까지 메일로 보낸다.

python -m news_desk            오늘 이슈 정리(뉴스레터 모양, 원문 링크·더할 방향)를 메일로 보냄 (soboru-newsdesk.timer가 아침 6시 30분에 부름)
python -m news_desk --dry      AI·메일 없이 모은 뉴스 제목만 보여 줌 (연결 확인용)
python -m news_desk --n 2      초안 수를 바꿈

- 뉴스: 네이버 API HUB 뉴스 검색(키가 있으면) → 없거나 모자라면 구글 뉴스 RSS. 최근 하루치 제목·요약.
- 고르기: AI가 기사로 다시 쓸 만한 이슈 10개를 고름 (소비자 피해·물가·금융·통신·유통·공정위·소비자원 등).
- 초안(--n 4로 켤 때만): 고른 이슈 위 4개를 원문(제목·요약·본문 앞부분)만 보고 경기일보 오민주 기자 문체로 1300자 안팎 새로 씀.
  문장은 처음부터 새로 쓰고, 지어낸 인터뷰는 【가안】 표시 (운영자가 실제로 바꿈). 숫자는 원문에 있는 것만.
- 원문과 문장이 너무 비슷하면(네이버 자체기사 기준: 90% 비슷한 문장) 메일에 표시.
- 받는 사람: 서버 설정 NEWS_DESK_TO (쉼표로 여럿), 없으면 OPS_EMAIL.
- AI 비용: GPT-6 Luna 하루 다섯 번쯤 부름 (관리자 > AI 사용량 '기사 데스크'에서 확인).
"""
import datetime
import difflib
import html as htmlmod
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

MODEL = 'gpt-6-luna'
DRAFTS = 0  # 운영자 2026-11-10: 초안 말고 이슈 정리만 (--n 4로 초안도 붙일 수 있음)
PICKS = 10
QUERIES = ['소비자 피해', '소비자원', '공정위', '리콜', '환불', '가격 인상', '물가', '소비자물가', '금리', '대출',
           '카드사', '보험료', '통신요금', '배달앱', '쿠팡', '플랫폼 수수료', '프랜차이즈', '식품 이물', '전세 사기',
           '보이스피싱', '구독 해지', '항공권 환불', '중고거래', '국정감사 소비자']
CATS = ['소비자의 소리', '산업', '경제', '머니', '생활', '테크', '트렌드', '이슈']
KO_WEEK = '월화수목금토일'


def env(k, d=''): return (os.getenv(k) or d).strip()


def clean(s):
    s = htmlmod.unescape(re.sub(r'<[^>]+>', '', s or ''))
    return ' '.join(s.split())


# ---- 뉴스 모으기 --------------------------------------------------------------
def naver_news(q, display=20):
    cid, sec = env('NAVER_HUB_CLIENT_ID'), env('NAVER_HUB_CLIENT_SECRET')
    if not (cid and sec): return []
    import naverhub
    url = naverhub.BASE + '/search/v1/news?' + urllib.parse.urlencode({'query': q, 'display': display, 'sort': 'date'})
    req = urllib.request.Request(url, headers={'X-NCP-APIGW-API-KEY-ID': cid, 'X-NCP-APIGW-API-KEY': sec})
    try:
        with urllib.request.urlopen(req, timeout=10) as r: res = json.loads(r.read().decode() or '{}')
    except Exception: return []
    out = []
    for it in res.get('items') or []:
        try: when = datetime.datetime.strptime(it.get('pubDate', ''), '%a, %d %b %Y %H:%M:%S %z')
        except ValueError: continue
        link = it.get('originallink') or it.get('link') or ''
        nl = it.get('link') or ''
        out.append({'title': clean(it.get('title')), 'summary': clean(it.get('description')), 'url': link,
                    'read': nl if 'news.naver.com' in nl else link, 'source': urllib.parse.urlparse(link).hostname or '', 'when': when})
    return out


def google_news(q):
    url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': q + ' when:1d', 'hl': 'ko', 'gl': 'KR', 'ceid': 'KR:ko'})
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; soboru-newsdesk)'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r: root = ET.fromstring(r.read())
    except Exception: return []
    out = []
    for it in root.iter('item'):
        try: when = datetime.datetime.strptime(it.findtext('pubDate', ''), '%a, %d %b %Y %H:%M:%S %Z').replace(tzinfo=datetime.timezone.utc)
        except ValueError: continue
        title = clean(it.findtext('title'))
        src = clean(it.findtext('source')) or ''
        if src and title.endswith(' - ' + src): title = title[:-len(src) - 3]
        out.append({'title': title, 'summary': clean(it.findtext('description'))[:300], 'url': it.findtext('link') or '',
                    'read': it.findtext('link') or '', 'source': src, 'when': when})
    return out


WIRES = ('yna.co.kr', 'news1.kr', 'newsis.com', '연합뉴스', '뉴스1', '뉴시스')  # 통신사 기사는 한 곳만 써도 받음


def is_wire(it): return any(w in (it.get('source') or '') or w in (it.get('url') or '') for w in WIRES)


def gather(hours=30):
    """최근 뉴스를 같은 일끼리 묶음. 운영자 2026-11-10: 한 언론만 낸 기사(단독·자체 취재)는 받지 않음 →
    두 곳 넘는 언론이 같이 썼거나 연합뉴스·뉴스1·뉴시스가 쓴 것만 남김."""
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    groups = []
    use_naver = bool(env('NAVER_HUB_CLIENT_ID'))
    for q in QUERIES:
        got = naver_news(q) if use_naver else []
        if len(got) < 3: got += google_news(q)
        for it in got:
            if it['when'] < since or not it['title']: continue
            key = re.sub(r'\W', '', it['title'])
            g = next((g for g in groups if difflib.SequenceMatcher(None, key, g['key']).ratio() > .55
                      or len(set(it['title'].split()) & set(g['first']['title'].split())) >= 4), None)
            if g is None: groups.append({'key': key, 'first': it, 'all': [it]})
            elif it['url'] not in {x['url'] for x in g['all']}: g['all'].append(it)
    items = []
    for g in groups:
        outlets = {x['source'] for x in g['all'] if x['source']}
        wires = [x for x in g['all'] if is_wire(x)]
        if len(outlets) < 2 and not wires: continue
        lead = (wires or g['all'])[0]
        items.append(dict(lead, outlets=len(outlets), also=[x for x in g['all'] if x is not lead][:4], wire=bool(wires)))
    items.sort(key=lambda i: (i['outlets'], i['when']), reverse=True)
    return items[:120]


def page_text(url, limit=3500):
    """기사 본문 앞부분 (초안 쓸 때 사실 확인용). 못 읽으면 ''."""
    try:
        from soboru_writer import fetch_page
        raw = fetch_page(url)
    except Exception: raw = ''
    if not raw: return ''
    m = re.search(r'<article[^>]*id="dic_area"[^>]*>(.*?)</article>', raw, re.S) or re.search(r'<article[^>]*>(.*?)</article>', raw, re.S)
    body = m.group(1) if m else raw
    body = re.sub(r'<(script|style|figure|figcaption|table)[^>]*>.*?</\1>', ' ', body, flags=re.S | re.I)
    body = re.sub(r'<br\s*/?>|</p>', '\n', body, flags=re.I)
    lines = [clean(x) for x in body.split('\n')]
    lines = [x for x in lines if len(x) > 30 and not re.search(r'무단|저작권|기자\s*\S+@|Copyright', x)]
    return '\n'.join(lines)[:limit]


# ---- AI ----------------------------------------------------------------------
def chat(system, user, max_tokens):
    key = env('OPENAI_API_KEY_NEWS_DESK') or env('OPENAI_API_KEY')
    if not key: raise RuntimeError('OpenAI API 키가 없어요')
    model = env('NEWS_DESK_MODEL') or MODEL
    opts = {'max_completion_tokens': max_tokens + 1500, 'reasoning_effort': 'low'} if re.match(r'(gpt-([5-9]|\d\d)|o\d)', model) else {'max_tokens': max_tokens, 'temperature': 0.5}
    body = {'model': model, 'response_format': {'type': 'json_object'}, **opts,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
    import companydesk  # 관리자 'AI 사용량'에 '기사 데스크'로 쌓임
    st, res = companydesk.post_json('https://api.openai.com/v1/chat/completions', {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, body, 180)
    if st != 200: raise RuntimeError(f'AI 응답 오류 ({st}) ' + str((res.get('error') or {}).get('message', ''))[:120].replace(key, '***'))
    return json.loads(res['choices'][0]['message']['content'])


PICK_SYSTEM = ('너는 소비자 전문 일간지 「소비자를위한신문」의 편집국장이다. 지난 하루 뉴스 목록에서 우리 신문이 오늘 받아 쓸(우라까이) 만한 '
               '경제·소비자 이슈를 ' + str(PICKS) + '개 고른다.\n'
               '- 기준: 소비자 지갑·피해·권리에 직접 닿는 것, 숫자(통계·금액·건수)가 있는 것, 공정위·소비자원·금융당국 등 행정 비판거리, 기업 실명이 나오는 것.\n'
               '- 연예·정치 공방·사건사고 단신·주가 시황·해외 단순 소식은 뺀다. 같은 일을 다룬 뉴스는 하나로 묶는다.\n'
               '- 분야가 한쪽에 몰리지 않게 한다. category는 ' + ', '.join(CATS) + ' 가운데 하나. 가장 중요한 것부터.\n'
               '- ids: 그 이슈를 다룬 뉴스 번호들(1~4개). title: 뉴스레터 제목처럼 짧고 구체적으로(숫자 있으면 넣기).\n'
               '- fact: 목록에 있는 내용만으로 핵심 사실 2~3문장(~다 체). 목록에 없는 숫자는 쓰지 않는다.\n'
               '- angle: 받아 쓰는 기사에 우리가 더할 수 있는 방향 한 문장 (소비자 입장, 직접 비교·계산, 국내 영향, 행정 허점 등).\n'
               '- more: 더 찾아볼 공개 자료 한 줄 (국감 자료, 통계, 공시, 보도자료). people: 인터뷰할 사람 한 줄.\n'
               'JSON으로만: {"issues": [{"ids": [..], "title": "..", "category": "..", "fact": "..", "angle": "..", "more": "..", "people": ".."}]}')

WRITE_SYSTEM = ('너는 「소비자를위한신문」 기자다. 아래 원문 뉴스를 바탕으로 우리 신문 기사를 새로 쓴다. 경기일보 오민주 기자 문체를 따른다.\n'
                '[형식]\n'
                "- title: 주체+사안 '핵심어'…\"인용 또는 수치\" 꼴 (예: 경기도 '똑버스'의 배신…\"예산 수백억 쓰는데 30분 대기\"). 35자 이내.\n"
                '- deck: 부제 2줄 배열. 숫자 대비 / 문제…대안 필요 식, 명사형으로 끝.\n'
                '- body: 문단 8~11개, 문단마다 1~3문장, 문단 사이 빈 줄. 소제목 없음. 전체 1,200~1,400자(공백 포함).\n'
                '  1문단(리드) 한 문장: "~하고 있지만 정작 ~하지 못하고 있는 것으로 나타났다." 또는 "~하면서 ~에 나섰다." 꼴.\n'
                '  2문단은 "{d}일 소비자를위한신문 취재를 종합하면,"으로 시작해 숫자를 제시.\n'
                '  중간에 한 문장 전환 문단 "문제는 ~다." 하나.\n'
                '  중후반: 시민 인터뷰 "서울시의 한 직장인 A씨(34)는 【가안】 "…"며 "…"고 전했다." (지역·직업·나이는 이슈에 맞게).\n'
                '  전문가: "전문가들은 【가안】 ~해야 한다고 지적했다." 와 교수·변호사 한 명 【가안】 인용.\n'
                '  마지막 문단: 해당 기업 또는 기관 관계자 반론·대책 "이에 대해 ○○ 관계자는 【가안】 "…"고 말했다."\n'
                '  맨 끝 줄: *이 기사는 공개 자료 조사와 통계 정리에 AI를 활용했습니다.*\n'
                '[규칙]\n'
                '- 원문 문장을 옮기지 말고 문장 구조부터 새로 쓴다. 원문과 같은 어절이 8개 이상 이어지면 안 된다. 원문에 없는 각도(소비자 입장, 반복 문제, 제도 허점)로 다시 짠다.\n'
                '- 숫자·기관·기업·날짜는 원문에 있는 것만 쓴다. 숫자는 1만8천104건, 1억1천100만원, 439억원처럼 쓰고 배수·비율 비교를 넣는다. 연도는 첫 언급에 "지난해(2025년)"처럼 밝힌다.\n'
                '- "○○일보에 따르면", "보도에 따르면"처럼 다른 언론을 출처로 쓰지 않는다. 말한 주체(기관·기업·의원실)를 출처로 쓴다.\n'
                '- 지어낸 인터뷰·반론에는 반드시 【가안】을 붙인다. 해요체 금지, ~했다·~것으로 나타났다·~셈이다·~지적이다·~방침이다로 끝낸다.\n'
                '- needs: 기자가 채울 것(실제 인터뷰 대상, 확인할 숫자, 찾을 공개 자료) 3~5개.\n'
                'JSON으로만: {"title": "..", "deck": ["..", ".."], "category": "..", "body": "..", "needs": [".."]}')


def overlap(body, sources):
    """원문과 90% 이상 비슷한 문장 비율 (네이버 자체기사 기준 참고용)."""
    src = [s for t in sources for s in re.split(r'(?<=[.?!다])\s+', t) if len(s) > 15]
    mine = [s for s in re.split(r'(?<=[.?!다])\s+', body) if len(s) > 15 and '【가안】' not in s]
    if not mine or not src: return 0.0
    hit = sum(1 for s in mine if max(difflib.SequenceMatcher(None, s, x).ratio() for x in src) >= .9)
    return hit / len(mine)


def write_draft(issue, items, today):
    picked = [items[i - 1] for i in issue.get('ids', []) if 0 < i <= len(items)][:3]
    if not picked: return None
    texts = []
    for it in picked:
        body = page_text(it.get('read') or it['url'])
        texts.append(body or it['summary'])
    user = (f'[이슈] {issue.get("issue", "")}\n[우리 각도] {issue.get("angle", "")}\n[분야] {issue.get("category", "")}\n'
            + '\n\n'.join(f'[원문 {n}] {it["title"]}\n{t}' for n, (it, t) in enumerate(zip(picked, texts), 1)))
    out = chat(WRITE_SYSTEM.replace('{d}', str(today.day)), user, 2500)
    body = (out.get('body') or '').strip()
    out['chars'] = len(re.sub(r'\*이 기사는.*', '', body).strip())
    out['similar'] = overlap(body, [it['title'] + '. ' + t for it, t in zip(picked, texts)])
    out['sources'] = picked
    return out


# ---- 메일 --------------------------------------------------------------------
def e(s): return htmlmod.escape(str(s or ''))


def render(today, issues, items, drafts):
    d = f'{today.month}월 {today.day}일({KO_WEEK[today.weekday()]})'
    wrap = 'font-family:Pretendard,Apple SD Gothic Neo,Malgun Gothic,sans-serif;color:#191f28;line-height:1.7;word-break:keep-all;max-width:680px;margin:0 auto;padding:24px 16px;background:#F6F2EC'
    card = 'background:#fff;border-radius:16px;padding:20px;margin:0 0 14px'
    h = [f'<div style="{wrap}"><div style="border-bottom:3px solid #191f28;padding-bottom:12px">'
         f'<div style="color:#EF920E;font-weight:800;font-size:13px">소비자를위한신문 · 아침 데스크</div>'
         f'<div style="font-size:26px;font-weight:800;margin:4px 0 2px">{d} 경제·소비자 이슈 {len(issues)}</div>'
         '<div style="color:#4e5968">어제와 오늘 나온 뉴스 가운데 우리가 받아 쓸 만한 것만 골랐어요.</div></div>',
         f'<div style="{card};margin-top:18px"><b>오늘 목차</b><ol style="margin:6px 0 0;padding-left:20px;color:#4e5968">'
         + ''.join(f'<li>{e(i.get("title") or i.get("issue"))}</li>' for i in issues) + '</ol></div>']
    for n, i in enumerate(issues, 1):
        arts = [a for k in i.get('ids', []) if isinstance(k, int) and 0 < k <= len(items) for a in [items[k - 1]] + items[k - 1].get('also', [])][:5]
        links = ''.join(f'<a href="{e(a["url"])}" style="color:#8b95a1;margin-right:12px">{e(a["source"] or "원문")}</a>' for a in arts)
        row = lambda lab, v: f'<tr><td style="color:#CE6719;font-weight:700;white-space:nowrap;width:1%;vertical-align:top;padding:3px 14px 3px 0">{lab}</td><td style="color:#4e5968;padding:3px 0">{e(v)}</td></tr>' if v else ''
        h.append(f'<div style="{card}"><div style="font-size:13px"><b style="color:#EF920E">{n:02d}</b> '
                 f'<span style="background:#FFF4E6;color:#CE6719;font-weight:700;padding:2px 9px;border-radius:999px">{e(i.get("category"))}</span></div>'
                 f'<div style="font-size:19px;font-weight:800;line-height:1.4;margin:8px 0">{e(i.get("title") or i.get("issue"))}</div>'
                 f'<div style="margin:0 0 10px">{e(i.get("fact") or i.get("why"))}</div>'
                 '<table style="border-top:1px solid #E8E1D7;width:100%;font-size:15px;padding-top:6px;border-collapse:collapse">'
                 + row('더할 방향', i.get('angle')) + row('더 찾을 것', i.get('more')) + row('인터뷰', i.get('people')) +
                 f'</table><div style="font-size:13px;margin-top:10px">{links}</div></div>')
    for n, dr in enumerate(drafts, 1):
        if not dr: continue
        body = ''.join(f'<p style="margin:0 0 12px">{e(p)}</p>' for p in dr.get('body', '').split('\n') if p.strip())
        h.append(f'<div style="{card}"><div style="color:#EF920E;font-weight:700">초안 {n} · {e(dr.get("category"))} · {dr["chars"]:,}자</div>'
                 f'<div style="font-size:19px;font-weight:800;margin:6px 0">{e(dr.get("title"))}</div>'
                 + ''.join(f'<div style="color:#4e5968;font-weight:600">{e(x)}</div>' for x in dr.get('deck') or []) + f'<div style="margin-top:14px">{body}</div></div>')
    h.append('<div style="color:#8b95a1;font-size:13px;margin-top:20px">매일 아침 6시 30분에 와요. 고른 기준: 소비자 지갑·피해에 닿고 숫자나 기업 실명이 있는 것.</div></div>')
    text = f'{d} 경제·소비자 이슈\n\n' + '\n\n'.join(
        f'{n}. [{i.get("category")}] {i.get("title") or i.get("issue")}\n{i.get("fact", "")}\n- 더할 방향: {i.get("angle", "")}\n- 더 찾을 것: {i.get("more", "")}\n- 인터뷰: {i.get("people", "")}\n'
        + '\n'.join('  ' + items[k - 1]['url'] for k in i.get('ids', []) if isinstance(k, int) and 0 < k <= len(items)) for n, i in enumerate(issues, 1))
    return f'[아침 데스크] {d} 경제·소비자 이슈 {len(issues)}', text, ''.join(h)


def run(n_drafts=DRAFTS, dry=False, today=None, send=None):
    today = today or datetime.date.today()
    items = gather()
    if dry:
        for n, it in enumerate(items, 1): print(n, it['when'].strftime('%m-%d %H:%M'), it['source'], it['title'])
        return {'items': len(items)}
    if len(items) < 5: raise RuntimeError(f'모은 뉴스가 {len(items)}개뿐이에요')
    listing = '\n'.join(f'{n}. {it["title"]} ({it["outlets"]}개 언론{", 통신사" if it.get("wire") else ""}) — {it["summary"][:120]}' for n, it in enumerate(items, 1))
    issues = [i for i in (chat(PICK_SYSTEM, '[지난 하루 뉴스]\n' + listing, 3000).get('issues') or []) if isinstance(i, dict)][:PICKS]
    drafts = []
    for i in issues[:n_drafts]:
        try: drafts.append(write_draft(i, items, today))
        except Exception as ex: print('초안 실패:', i.get('issue'), ex); drafts.append(None)
    subject, text, html = render(today, issues, items, drafts)
    to = [x.strip() for x in (env('NEWS_DESK_TO') or env('OPS_EMAIL')).split(',') if x.strip()]
    if not to: raise RuntimeError('받는 사람(NEWS_DESK_TO 또는 OPS_EMAIL)이 없어요')
    if send is None:
        import notify
        send = notify.send_email
    for addr in to: send(addr, subject, text, html=html, from_name='소비자를위한신문 데스크')
    return {'items': len(items), 'issues': len(issues), 'drafts': len([d for d in drafts if d]), 'to': len(to)}


def main(argv):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try: import app  # noqa: F401  AI 사용량 기록 연결 (관리자 > AI 사용량 '기사 데스크')
    except Exception as ex: print('사이트 설정을 못 읽었어요 (AI 사용량 기록 없이 진행):', ex)
    n = int(argv[argv.index('--n') + 1]) if '--n' in argv else DRAFTS
    print(json.dumps(run(n, dry='--dry' in argv), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
