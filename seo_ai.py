# 운영자 2026-11-03 (밤): AI·검색엔진 최적화. 네이버 AI 브리핑·구글 AI 개요·ChatGPT 검색이 '소비자제보센터가 무엇인지'
# 한 문장으로 뽑아 갈 수 있게: 소개 페이지(/about, 정의 문장 + 주요 특징 + 자주 묻는 질문 + 구조화 데이터), /llms.txt.
from flask import abort, render_template, url_for

ABOUT = {
    'lead': '소비자제보센터(by SOBORU)는 소비자가 겪은 피해를 공개로 제보하고, 같은 피해를 겪은 소비자와 함께 목소리를 내는 소비자 제보 플랫폼이에요.',
    'more': '제보는 사진·자료와 함께 공개되고, 공감과 댓글이 모이며, 기업에 전달돼 답변을 받아요. 널리 알려야 할 피해는 기사로 써서 알려요. 2026년 문을 열었고, 소보루(SOBORU)가 운영해요.',
    'features': [
        ('공개 제보와 공감', '환불 거부, 배송 지연, 불량품, 계약 해지 같은 소비자 피해를 누구나 볼 수 있게 올리고, 같은 일을 겪은 소비자가 공감과 댓글로 힘을 보태요.'),
        ('기업 답변 연결', '제보를 해당 기업에 전달하고 기업의 답변과 처리 과정을 공개해요. 답변 속도로 매긴 기업 응대 순위도 볼 수 있어요.'),
        ('기사로 알리기', '여러 소비자에게 되풀이되는 피해나 널리 알려야 할 일은 기사로 써서 알려요.'),
        ('소보루 자문단', '변호사와 교수로 이루어진 소보루 자문단이 제보에 법과 기준을 짚는 의견을 남기고, 소비자의 질문에 답해요. 소개와 연결에 비용을 받지 않아요.'),
        ('AI 상담과 생활 도구', '법령과 소비자분쟁해결기준을 근거로 답하는 AI 상담, 환불·위약금 계산기, 소비자·경제 사전, 사기 전에 확인할 업체 정보를 제공해요.'),
    ],
    'faq': [
        ('소비자제보센터는 어떤 곳인가요?', '소비자 피해를 공개로 제보하고, 기업 답변을 받고, 필요하면 기사로 알리는 민간 소비자 제보 플랫폼이에요. 공공기관은 아니에요.'),
        ('제보는 어떻게 하나요?', '로그인한 뒤 제보하기에서 글로 직접 쓰거나, 대화하듯 이야기하면 AI가 제보 글로 정리해 줘요.'),
        ('이용료가 있나요?', '제보, 기업 답변 연결, 자문단 의견, AI 상담 모두 무료예요.'),
        ('누가 운영하나요?', '소보루(SOBORU)가 운영해요. 소보루는 ‘소비자 권익 보호를 위한 루트’라는 뜻이에요.'),
    ],
}


def install(S):
    app = S.app

    def jebo_only():
        if S.current_face() != 'jebo': abort(404)

    @app.route('/about')
    def about_page():
        jebo_only()
        faq_ld = [{'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in ABOUT['faq']]
        return render_template('about.html', a=ABOUT, faq_ld=faq_ld)

    def jebo_llms():
        """AI 검색·답변 봇이 사이트를 빨리 이해하게 돕는 요약 (llmstxt.org 형식). 소비자제보센터 주소에서는 이 내용으로."""
        base = S.canonical_url('').rstrip('/')
        link = lambda ep, **k: base + url_for(ep, **k)
        lines = ['# 소비자제보센터 (by SOBORU)', '', '> ' + ABOUT['lead'], '', ABOUT['more'], '', '## 주요 특징', '']
        lines += [f'- {t}: {d}' for t, d in ABOUT['features']]
        lines += ['', '## 주요 페이지', '',
                  f'- [서비스 소개]({link("about_page")}): 소비자제보센터가 하는 일과 자주 묻는 질문',
                  f'- [소비자 제보 목록]({link("reports")}): 공개된 소비자 피해 제보',
                  f'- [이용 안내]({base}/guide): 제보하는 두 가지 방법',
                  f'- [처리 절차]({base}/process): 접수부터 기업 답변, 기사화까지']
        for ep, title, desc in (('companies_rank', '기업 응대 순위', '제보에 빨리 답하는 기업과 늦게 답하는 기업'), ('experts_page', '소보루 자문단', '변호사·교수 자문단'),
                                ('explore', '둘러보기', '기업 응대 순위, AI 상담, 생활 도구, 자문단')):
            if ep in app.view_functions: lines.append(f'- [{title}]({link(ep)}): {desc}')
        lines += [f'- [자주 묻는 질문]({base}/faq)', '', '## 자주 묻는 질문', '']
        lines += [f'- {q} {a}' for q, a in ABOUT['faq']]
        lines += ['', '## 안내', '', '- 소비자제보센터는 공공기관이 아닌 민간 플랫폼이에요. 제보는 제보자의 주장이며, 기업 답변을 보장하지 않아요.',
                  f'- 사이트맵: {base}/sitemap.xml', f'- RSS: {base}/rss.xml', '']
        return app.response_class('\n'.join(lines), mimetype='text/plain; charset=utf-8')

    old = app.view_functions.get('llms_txt')
    if old:
        def llms_txt():
            return jebo_llms() if S.current_face() == 'jebo' else old()
        app.view_functions['llms_txt'] = llms_txt
    else:
        app.add_url_rule('/llms.txt', 'llms_txt', jebo_llms)
