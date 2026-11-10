"""검색 노출 (소보루 CX 소개 사이트, OH 11/07: 일반 검색과 AI 검색 모두에 나오게).

  · 자주 묻는 질문은 화면과 구조화 데이터(FAQPage)가 같은 목록을 쓴다.
  · /llms.txt: ChatGPT·Perplexity·Claude 같은 AI 검색이 읽기 좋은 서비스 요약 (llmstxt.org 형식).
  · robots.txt는 일반·AI 검색 로봇 모두 허용한다 (로그인 뒤 화면만 막음).
"""
import core, billing

FAQ=[('무료는 정말 계속 무료예요?', '네. 상담창·카톡·톡톡·인스타 연결과 상담은 계속 무료예요. SODA 답만 한 달 50번까지이고, 더 쓰고 싶을 때 요금제를 올리면 돼요.'), ('카카오톡 채널과 네이버 톡톡도 받을 수 있나요?', '네. 서비스 연동에서 주소를 만들어 카카오 챗봇 관리자센터와 톡톡 파트너센터에 넣으면 돼요. 들어온 문의는 다른 채널과 같은 화면에 떠요.'), ('카페24 말고 자사몰도 되나요?', '네. 쇼핑몰 HTML에 스크립트 한 줄을 넣으면 문의 버튼이 생기고, 메일과 인스타그램 DM도 같은 화면에서 받아요.'), ('카페24 비밀번호를 알려 줘야 하나요?', '아니요. 카페24 관리자로 로그인해 권한에 동의하는 방식(OAuth)이라 비밀번호는 받지 않아요.'), ('SODA가 마음대로 환불해 주면 어떡하죠?', 'SODA는 환불·보상·취소를 약속하거나 실행하지 않아요. 방법은 안내하고, 결정은 사장님 승인 뒤에만 나가요.'), ('SODA가 모르는 걸 지어내지 않나요?', '가격·재고·배송·반품 정책은 넣어 둔 정보로만 답해요. 없으면 지어내지 않고 담당자 확인을 안내해요.')]

KEYWORDS='쇼핑몰 AI 상담원, 쇼핑몰 CS, 고객 문의 자동 답변, 카페24 CS, 카카오톡 상담, 네이버 톡톡, 쇼핑몰 챗봇, 1인 쇼핑몰, 소상공인 고객센터, 채널톡 대안'

def ld(url_root):
    """첫 화면 구조화 데이터: 서비스·요금·운영사·자주 묻는 질문."""
    t=billing.tiers()
    offers=[dict({'@type':'Offer','name':'무료','price':'0','priceCurrency':'KRW'})]+[{'@type':'Offer','name':x['name'],'price':str(x['price']),'priceCurrency':'KRW'} for x in t]
    return [
      {'@context':'https://schema.org','@type':'SoftwareApplication','name':core.BNAME,'alternateName':['SOBORU CX','소보루CX','SODA AI 상담원'],
       'applicationCategory':'BusinessApplication','operatingSystem':'Web, Android','url':url_root,'inLanguage':'ko','description':core.DESCRIPTION['biz'],
       'keywords':KEYWORDS,'offers':offers,'publisher':{'@type':'Organization','name':core.OPERATOR['name'] if isinstance(core.OPERATOR,dict) else core.BNAME}},
      {'@context':'https://schema.org','@type':'Organization','name':core.BNAME,'url':url_root,'logo':url_root.rstrip('/')+'/static/soboru-touch.png'},
      {'@context':'https://schema.org','@type':'FAQPage','mainEntity':[{'@type':'Question','name':q,'acceptedAnswer':{'@type':'Answer','text':a}} for q,a in FAQ]}]

def llms_txt():
    t=billing.tiers();u=lambda p:core.site_url('biz',p)
    price=', '.join(f"{x['name']} 월 {x['price']:,}원(상담 {x['tickets']:,}건)" for x in t)
    lines=[f'# {core.BNAME} (SOBORU CX)','',
      f'> 1인·소규모 쇼핑몰 사장님을 위한 AI 상담원 서비스. AI 상담원 SODA가 카카오톡·네이버 톡톡·쇼핑몰 상담창·카페24 게시판·인스타그램 DM·메일 문의에 24시간 먼저 답하고, 환불·교환 같은 결정은 사장님이 폰으로 승인해요. 무료(월 0원)로 시작해요.','',
      '## 핵심','- 사람을 뽑지 않고 반복 문의(배송·교환·사이즈·사용법)를 SODA가 쇼핑몰 정보로 바로 답해요.',
      '- 돈이 걸린 일(환불·보상)은 SODA가 약속하지 않고 사장님 승인 뒤에만 진행해요.',
      '- 쇼핑몰 주소만 넣으면 SODA가 상품·정책을 읽고 3분이면 시작해요. 카드 등록 없이 무료.',
      f'- 요금: 무료 월 0원(SODA 답 한 달 {billing.FREE_SODA}번), {price}. 부가세 포함, 약정·위약금 없음.','',
      '## 페이지',f'- [소개]({u("/")})',f'- [요금]({u("/pricing")})',f'- [제품 둘러보기]({u("/tour")})',f'- [판매처 연결: 카페24·자사몰]({u("/for")})',f'- [도움말]({u("/help")})',f'- [보안]({u("/security")})',f'- [이용약관]({u("/terms")})','',
      '## 자주 묻는 질문']+[f'- {q} {a}' for q,a in FAQ]
    return '\n'.join(lines)+'\n'


def register(app):
    app.add_url_rule('/llms.txt','llms_txt',lambda:app.response_class(llms_txt(),mimetype='text/plain; charset=utf-8'))
    app.jinja_env.globals.update(LANDING_FAQ=FAQ,seo_ld=ld,SEO_KEYWORDS=KEYWORDS)
