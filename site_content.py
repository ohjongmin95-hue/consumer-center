"""관리자 화면에서 수정할 수 있는 사이트 문구.

각 항목은 (키, 이름, 기본값, 옵션) 형식입니다. 옵션의 'multiline'은 줄바꿈을 허용하고,
'optional'은 빈 값으로 저장해 해당 문구를 숨길 수 있게 합니다. 그 밖의 항목은 비워 저장하면
기본값으로 돌아갑니다.
"""
from pathlib import Path


def _policy(name):
    return (Path(__file__).with_name('policies') / (name + '.txt')).read_text(encoding='utf-8').strip()


FAQ_DEFAULTS = [
    ('제보하면 바로 해결되나요?', '제보 접수만으로 환불이나 보상이 확정되지는 않습니다. 내용에 따라 후속 검토가 이루어질 수 있습니다.'),
    ('어떤 자료를 첨부하면 좋나요?', '영수증, 주문 내역, 업체와 주고받은 메시지 등 사실관계를 확인할 수 있는 자료가 도움이 됩니다.'),
    ('제보 내용이 공개되나요?', '제보할 때 공개와 비밀글 중에서 고를 수 있습니다. 공개를 고르면 제목과 내용을 누구나 볼 수 있고, 비밀글은 센터 담당자만 봅니다. 어느 경우든 연락처와 첨부파일은 공개되지 않습니다.'),
    ('공식 분쟁조정이나 피해구제도 가능한가요?', '이 센터는 법정 피해구제기관이 아닙니다. 공식적인 상담·피해구제는 1372 소비자상담센터 등 관련 기관을 이용해 주세요.'),
]
# 예전 고정 칸(faq.q1~, process.step1~)에 저장된 값을 새 목록으로 옮길 때 쓰는 기본값
PROCESS_DEFAULTS = [
    ('제보 접수', '제보자가 피해 내용을 작성하고 관련 자료를 제출합니다.'),
    ('내용 검토', '제출된 내용의 사실관계와 자료를 검토합니다. 필요한 경우 추가 자료를 요청할 수 있습니다.'),
    ('후속 검토', '사안에 따라 업체 의견 확인 또는 취재 여부를 검토할 수 있습니다. 모든 제보가 취재·공개되는 것은 아닙니다.'),
]

ML = {'multiline': True}
OPT = {'optional': True}
OPT_ML = {'optional': True, 'multiline': True}

SECTIONS = [
    ('common', '공통 (헤더·푸터)', [
        ('site.name', '사이트 이름 (브라우저 탭 등)', '소비자제보센터', {}),
        ('site.logo_accent', '로고 앞부분 (주황색)', '소비자', OPT),
        ('site.logo_rest', '로고 뒷부분', '제보센터', {}),
    ]),
    ('seo', '검색 노출 (네이버·구글)', [
        ('seo.home_title', '메인 화면 제목 (브라우저 탭·검색 결과·카톡 미리보기 제목)', '소비자제보센터 | SOBORU', {}),
        ('seo.description', '사이트 설명 (검색 결과에 보이는 문장)', '소비자 피해를 제보하고 진행 상황을 확인하세요. 비슷한 경험을 나누는 소비자게시판도 있어요.', {}),
        ('seo.naver_verification', '네이버 서치어드바이저 소유확인 코드', '', OPT),
        ('seo.google_verification', '구글 서치 콘솔 소유확인 코드', '', OPT),
        ('seo.daum_robots', '다음 웹마스터도구 robots.txt 줄', '', OPT),
    ]),
    ('operator', '하단 정보 (푸터): 사업자 정보·저작권 · 약관에도 표시', [
        ('operator.name', '상호 (운영자)', '소보루', {}),
        ('operator.ceo', '대표자', '', OPT),
        ('operator.biz_no', '사업자등록번호', '', OPT),
        ('operator.address', '소재지(주소)', '', OPT),
        ('operator.email', '대표 이메일', '', OPT),
        ('operator.phone', '대표 전화', '', OPT),
        ('operator.fax', '팩스', '', OPT),
        ('operator.privacy_officer', '개인정보 보호책임자', '', OPT),
        ('operator.privacy_contact', '개인정보 보호책임자 연락처', '', OPT),
        ('operator.youth_officer', '청소년보호책임자 (비우면 개인정보 보호책임자와 같음)', '', OPT),
        ('operator.youth_contact', '청소년보호책임자 연락처 (비우면 개인정보 보호책임자 연락처)', '', OPT),
        ('operator.notice', '민간 운영 안내', '소비자제보센터는 민간이 운영하는 소비자 제보 창구로, 국가기관이나 한국소비자원과 관련이 없습니다. 공식 상담과 피해구제는 1372 소비자상담센터(국번 없이 1372)를 이용해 주세요.', OPT_ML),
        ('footer.text', '저작권 문구 (맨 아래)', '© SOBORU All rights reserved.', ML),
    ]),
    ('home', '메인 화면', [
        ('home.hero_title', '메인 문구', '여러분의 제보가\n권익 보호의 시작입니다.', ML),
        ('home.hero_button', '제보 버튼', '제보하기 →', {}),
        ('home.latest_title', '메인 최근 제보 제목 (비우면 제목 없이 카드만)', '', OPT),
        ('home.latest_count', '메인에 보여줄 최근 제보 수 (3~20, 4의 배수가 깔끔해요)', '8', {}),
        ('home.list_title', '제보 목록 페이지 제목', '소비자 제보 목록', {}),
        ('home.search_placeholder', '검색창 안내 문구', '제보 제목 검색', {}),
        ('home.empty', '목록이 비었을 때', '표시할 제보 내역이 없습니다.', {}),
        ('home.empty_search', '검색 결과가 없을 때', '검색 조건에 맞는 제보 내역이 없습니다.', {}),
        ('home.list_note', '목록 아래 안내', '', OPT_ML),
        ('home.lookup_link', '내 제보 조회 링크', '내 제보 조회 →', {}),
    ]),
    ('report', '제보하기 화면', [
        ('report.title', '페이지 제목', '소비자 피해 제보하기', {}),
        ('report.intro', '소개 문구', '', OPT_ML),
        ('report.notes', '제보 전 꼭 읽어 주세요 (한 줄에 하나씩)', '업체명과 제보 유형을 정확히 골라 주시면 더 빨리 확인할 수 있어요.\n공개로 올린 제보는 누구나 볼 수 있어요. 본문에는 이름, 전화번호, 주소 같은 개인정보를 적지 마세요. 연락이 필요하면 이메일 칸만 써 주세요.\n영수증, 계약서, 사진, 업체와 나눈 대화처럼 사실을 확인할 수 있는 자료를 첨부하면 큰 도움이 돼요.\n접수 후 나오는 접수번호와 조회 코드는 꼭 따로 보관해 주세요. 다시 보여 드릴 수 없어요.\n접수된 제보는 직접 고치거나 지울 수 없어요. 삭제를 원하면 운영자 이메일로 요청해 주세요.\n비방, 욕설, 명예를 훼손하는 표현, 광고성 내용은 공개되지 않거나 삭제될 수 있어요.\n상대방의 개인정보를 그대로 드러낸 글은 예고 없이 비공개 처리될 수 있어요.', OPT_ML),
        ('report.privacy_items', '[필수] 개인정보 수집·이용: 수집 항목', '필수: 이름, 전화번호, 제보 유형, 업체명, 제보 제목과 내용, 원하는 해결 방법\n선택: 이메일, 지역, 성별, 연령대, 첨부파일(사진·문서·영상)', ML),
        ('report.privacy_purpose', '[필수] 개인정보 수집·이용: 이용 목적', '제보에 따른 본인 확인 및 원활한 의사소통 경로 확보', ML),
        ('report.privacy_period', '[필수] 개인정보 수집·이용: 보유 기간', '게시글 작성 시로부터 3년', ML),
        ('report.refusal_note', '[필수] 개인정보 수집·이용: 거부 권리 안내', '위와 같이 개인정보를 수집·이용하는 데 동의를 거부할 권리가 있습니다. 그러나 동의를 거부할 경우 제보 접수 및 일부 서비스 제공을 받으실 수 없습니다.', ML),
        ('report.share_recipient', '[필수] 개인정보 제3자 제공: 제공받는 자', '제보 대상이 된 해당 사업자', ML),
        ('report.share_items', '[필수] 개인정보 제3자 제공: 제공 항목', '제보 제목, 업체명, 피해 내용, 원하는 해결 방법', ML),
        ('report.share_purpose', '[필수] 개인정보 제3자 제공: 이용 목적', '제보(민원)의 처리 및 중재 요청', ML),
        ('report.share_period', '[필수] 개인정보 제3자 제공: 보유 기간', '게시글 작성 시로부터 3년', ML),
        ('report.share_refusal', '[필수] 개인정보 제3자 제공: 거부 권리 안내', '위와 같이 개인정보를 제공하는 데 동의를 거부할 권리가 있습니다. 그러나 동의를 거부할 경우 제보 접수 및 일부 서비스 제공을 받으실 수 없습니다.', ML),
        ('report.visibility_public', '공개 설정: 공개 설명', '제목과 내용을 누구나 볼 수 있어요. 업체명도 함께 표시돼요. 연락처와 첨부파일은 공개되지 않아요.', ML),
        ('report.visibility_secret', '공개 설정: 비밀글 설명', '센터 담당자만 볼 수 있어요. 목록에는 비밀글로만 표시돼요.', ML),
        ('report.public_notice', '공개 제보 하단 안내', '이 제보는 제보자 개인의 경험과 주장이며, 센터가 사실관계를 확인한 내용이 아닙니다. 이 글로 권리를 침해받았다면 게시중단을 요청해 주세요.', OPT_ML),
        ('report.use_text', '[필수] 저작권 동의: 내용', '제보해 주신 글과 사진, 영상은 또 다른 소비자 피해를 막기 위해 제작되는 소보루 기사와 관련 유튜브 및 SNS 콘텐츠 제작에 사용될 수 있습니다. 이러한 저작권 이용에 동의를 거부할 권리가 있습니다. 그러나 동의를 거부할 경우 제보 접수 및 일부 서비스 제공을 받으실 수 없습니다.', ML),
        ('report.use_withdraw', '[필수] 저작권 동의: 철회 안내 (하단 정보의 대표 이메일이 뒤에 붙어요)', '제공하신 동의를 철회하려면 담당자에게 연락해 주세요. 바로 처리해 드립니다.', ML),
        ('report.consent_truth', '[필수] 사실 작성 확인: 내용', '사실에 근거해 작성했습니다. 허위 사실이나 타인의 명예를 훼손하는 내용을 적으면 법적 책임이 따를 수 있음을 확인합니다.', ML),
    ]),
    ('member', '회원가입·로그인·내 정보', [
        ('member.privacy_items', '회원가입 개인정보: 수집 항목', '필수: 아이디, 비밀번호(암호화 저장), 닉네임\n선택: 이메일', ML),
        ('member.privacy_purpose', '회원가입 개인정보: 이용 목적', '회원 식별과 로그인\n내 제보·글 모아 보기\n이메일: 비밀번호 분실 등 문의 시 본인 확인', ML),
        ('member.privacy_period', '회원가입 개인정보: 보유 기간', '회원 탈퇴 시 즉시 파기\n단, 법령에서 보관을 정한 경우 그 기간까지', ML),
        ('member.privacy_refusal', '회원가입 개인정보: 거부 권리 안내', '동의하지 않을 수 있으며, 이 경우 회원가입은 할 수 없지만 비회원으로 제보·게시판을 이용할 수 있어요.', ML),
    ]),
    ('guide', '이용 안내', [
        ('guide.eyebrow', '상단 작은 제목', '', OPT),
        ('guide.title', '페이지 제목', '이용 안내', {}),
        ('guide.intro', '소개 문구', '', OPT_ML),
        ('guide.s1_title', '01 제목', '언제, 어디서, 얼마에 구매했나요?', {}),
        ('guide.s1_desc', '01 설명', '서비스를 이용했다면 구매일 대신 계약일이나 가입일을 적어 주세요.', OPT_ML),
        ('guide.s2_title', '02 제목', '겪은 일을 순서대로 알려 주세요', {}),
        ('guide.s2_desc', '02 설명', '어려운 표현은 필요 없어요. 아래 세 가지가 드러나면 내용을 이해하기 쉬워집니다.', OPT_ML),
        ('guide.s3_title', '03 제목', '어떤 자료를 남겨야 할까요?', {}),
        ('guide.s4_title', '04 제목', '내 상황에 맞는 자료를 준비해 주세요', {}),
        ('guide.s4_desc', '04 설명', '해당하는 분야를 눌러 확인해 보세요. 모든 자료를 갖출 필요는 없어요. 지금 갖고 있는 것부터 정리해 주세요.', OPT_ML),
        ('guide.bottom_title', '하단 안내 제목', '준비한 내용을 남겨 주세요', {}),
        ('guide.bottom_text', '하단 안내 문구', '접수 후에는 접수번호와 비밀 조회 코드로 진행 상황을 확인할 수 있습니다.', OPT_ML),
        ('guide.bottom_button', '하단 버튼', '제보 작성하기 →', {}),
    ]),
    ('board', '소비자게시판', [
        ('board.title', '페이지 제목', '소비자게시판', {}),
        ('board.intro', '소개 문구', '', OPT_ML),
        ('board.rules', '글쓰기 약속 (한 줄에 하나씩)', '경험한 사실을 중심으로 써 주세요. 추측이나 단정은 피해 주세요.\n이름, 전화번호, 주소, 주문번호처럼 누군가를 알아볼 수 있는 정보는 적지 마세요.\n특정인을 향한 욕설, 비방, 조롱은 삼가 주세요.\n광고, 홍보, 같은 글 반복 등록은 삭제돼요.\n여러 분이 부적절하다고 알린 글은 자동으로 숨겨지고 운영자가 확인해요.', OPT_ML),
        ('board.empty', '글이 없을 때 문구', '아직 글이 없어요. 첫 이야기를 들려주세요.', {}),
    ]),
    ('status', '진행 단계 설명 (내 제보 조회 화면)', [
        ('status.1', '1. 접수', '제보가 접수됐어요. 곧 담당자가 내용을 확인해요.', ML),
        ('status.2', '2. 검토 중', '담당자가 제보 내용과 자료를 살펴보고 있어요.', ML),
        ('status.3', '3. 추가 확인', '확인을 위해 추가 자료나 설명이 필요해요. 아래 메시지를 확인해 주세요.', ML),
        ('status.4', '4. 기업 답변 대기', '업체에 내용을 전달하고 답변을 기다리고 있어요.', ML),
        ('status.5', '5. 조정 진행', '업체 답변을 바탕으로 해결 방법을 조율하고 있어요.', ML),
        ('status.6', '6. 종결', '처리가 마무리됐어요. 함께해 주셔서 고마워요.', ML),
    ]),
    ('process', '처리 절차', [
        ('process.title', '페이지 제목', '처리 절차', {}),
        ('process.intro', '소개 문구', '', OPT_ML),
        ('process.note', '하단 안내', '접수번호와 비밀 조회 코드로 내 제보의 진행 상황을 확인할 수 있습니다.', OPT_ML),
    ]),
    ('types', '제보 유형', [
        ('types.title', '페이지 제목', '제보 유형', {}),
        ('types.intro', '소개 문구', '', OPT_ML),
        ('types.link', '유형별 버튼', '이 유형으로 제보 →', {}),
    ]),
    ('faq', '자주 묻는 질문', [
        ('faq.title', '페이지 제목', '자주 묻는 질문', {}),
        ('faq.intro', '소개 문구', '', OPT_ML),
    ]),
]

POLICY_HINT = '줄 맨 앞에 "## "를 쓰면 소제목(목차에도 표시), "- "를 쓰면 목록이 됩니다. {운영자}, {대표자}, {이메일}, {전화}, {주소}, {보호책임자}, {보호책임자연락처}, {청소년보호책임자}, {청소년보호책임자연락처}, {시행일}은 운영자 정보로 자동 바뀝니다.'

SECTIONS += [
    ('policy', '약관·개인정보 처리방침·게시중단', [
        ('policy.effective_date', '시행일', '2026년 10월 9일', {}),
        ('policy.terms', '이용약관', _policy('terms'), {'multiline': True, 'doc': True}),
        ('policy.privacy', '개인정보 처리방침', _policy('privacy'), {'multiline': True, 'doc': True}),
        ('policy.youth', '청소년보호정책', _policy('youth'), {'multiline': True, 'doc': True}),
        ('policy.takedown', '권리침해 신고 및 임시조치 안내', _policy('takedown'), {'multiline': True, 'doc': True}),
    ]),
]

# 관리자 '항목 관리'에서 추가·삭제·순서 변경하는 목록: (키, 이름, 설명, 필드[(이름, 라벨, 옵션)], 최소 개수)
_LIST_DEFAULTS = __import__('json').loads(Path(__file__).with_name('list_defaults.json').read_text(encoding='utf-8'))
REPORT_CATEGORY_DEFAULTS = ['상품·품질', '배송·환불', '구독·결제', '금융·통신', '여행·숙박', '서비스·계약', '개인정보', '기타']
# 업종: (이름, 아이콘, 예시, 꼭 적을 것, 있으면 좋은 자료, 한 줄 팁). 제보하기 업종 칸과 이용 안내 업종 카드가 같은 이름을 씀
INDUSTRIES = [
    ('식품·외식', 'food', '가공식품, 배달·음식점, 건강기능식품',
     '산 날·주문한 날, 제품명 또는 가게 이름, 결제 금액, 이상을 알아챈 때(개봉 전·먹는 중·먹은 뒤), 몸에 나타난 증상',
     '포장 전체·소비기한 사진, 이물·변질 부위 사진, 영수증·배달앱 주문 내역, 진료 기록(병원에 갔다면)',
     '이물은 버리지 말고 지퍼백에 따로 담아 두세요.'),
    ('의약·의료', 'medical', '의약품, 의료기기, 병원·피부·치과 시술',
     '약·기기 이름 또는 시술명, 처방·구입·시술 날짜, 증상과 시작된 때, 병원·약국 이름, 낸 비용',
     '증상 부위 사진(날짜별), 처방전·약 봉투, 진단서·소견서, 시술 동의서·진료비 영수증',
     '같은 자리·같은 조명에서 날짜별로 찍으면 변화가 잘 보여요.'),
    ('쇼핑·유통', 'commerce', '온라인몰, 대형마트, 홈쇼핑, 의류·화장품',
     '주문일·주문번호, 판매처와 상품명, 결제 금액, 안내와 달랐던 점, 반품·환불을 요청한 날',
     '상품 상세·행사 화면 캡처, 받은 상품 사진, 주문·결제 내역, 판매자 문의 기록',
     '상품 페이지는 바뀌거나 사라질 수 있으니 먼저 캡처해 두세요.'),
    ('가전·전자기기', 'appliance', '생활가전, 스마트폰·노트북, 정수기 등 렌탈',
     '산 날과 산 곳, 제품명·모델명, 구입 가격(렌탈은 월 요금·약정 기간), 증상(작동 불량·파손·소음)과 처음 나타난 때, 수리받은 횟수',
     '증상이 보이는 짧은 영상, 오류 화면 캡처, 모델명 라벨 사진, 수리·점검 내역서, 렌탈 계약서',
     '소음이나 작동 불량은 사진보다 영상이 잘 전해져요.'),
    ('자동차', 'car', '신차·중고차, 정비·타이어, 렌터카',
     '차종·연식·주행거리, 구입·이용한 날과 금액, 판매·정비한 곳, 문제가 생긴 부위와 증상',
     '문제 부위 사진·영상, 정비 명세서·견적서, 매매·임대 계약서, 성능·상태 점검기록부(중고차)',
     '같은 고장이 반복되면 정비 날짜별 명세서를 모아 주세요.'),
    ('통신·인터넷', 'telecom', '휴대폰 요금제, 인터넷·IPTV, 알뜰폰',
     '가입한 경로(매장·온라인·전화), 가입일·약정 기간, 안내받은 요금·혜택, 실제 청구된 금액',
     '가입 계약서, 문제 항목에 표시한 청구서, 상담 녹취·안내 문자, 판매점 명함',
     ''),
    ('금융·보험', 'finance', '은행, 카드, 대출, 증권, 보험',
     '가입일, 금융사·상품명, 설명받은 조건(수수료·보장 내용 등), 피해 금액',
     '계약서·약관·상품설명서, 거래·청구 내역, 상담 녹취, 보험금 지급 거절 안내문',
     '계좌·카드번호는 끝 네 자리만 보이게 가려 주세요.'),
    ('게임·앱', 'game', '게임 아이템, 앱 결제, OTT·웹툰 구독',
     '게임·앱 이름, 계정 아이디와 서버, 결제일·결제 금액, 이용 제한이나 미지급 내용',
     '앱마켓 결제 영수증, 아이템·확률 안내 화면, 제재·오류 안내 화면, 고객센터 문의 기록',
     '비밀번호는 절대 적지 마세요.'),
    ('건설·인테리어', 'building', '아파트 분양·입주, 인테리어·리모델링',
     '계약일과 입주·완공일, 시공사·단지명, 하자가 생긴 위치, 처음 발견한 날, 공사 금액',
     '분양·공사 계약서, 하자 부위 사진(위치가 보이게 + 가까이), 보수 요청 기록, 견적서',
     '고치기 전에 처음 상태부터 찍어 두세요.'),
    ('기타', 'other', '여행·숙박, 학원·헬스장 등 위에 없는 분야',
     '무엇을 사거나 계약했는지, 언제·어디서·얼마에, 문제가 된 내용, 원하는 해결 방법',
     '계약서·결제 내역, 관련 사진, 업체와 주고받은 기록',
     ''),
]
REPORT_INDUSTRY_DEFAULTS = [(n, e) for n, _, e, *_ in INDUSTRIES]
BOARD_CATEGORY_DEFAULTS = ['경험 공유', '질문해요', '꿀팁', '칭찬해요', '자유']
PROCESS_ICONS = [('write', '제보 작성 (휴대폰)'), ('search', '검토 (돋보기)'), ('chat', '업체 확인 (말풍선)'), ('scale', '조율 (저울)'),
                 ('check', '완료 (체크 문서)'), ('bell', '안내 (알림)'), ('shield', '보호 (방패)'), ('call', '상담 (헤드셋)')]
GUIDE_STEP_ICONS = [('write', '작성 (문서와 펜)'), ('attach', '첨부 (사진과 클립)'), ('ticket', '접수번호 (번호표)'), ('search', '확인 (돋보기)'), ('chat', '대화 (말풍선)'), ('check', '완료 (체크)')]
GUIDE_STEPS = [('제보 작성', 'write'), ('자료 첨부', 'attach'), ('접수번호 받기', 'ticket'), ('진행 확인', 'search')]
INDUSTRY_ART = [('food', '식품 (포장·이물·발견 메모)'), ('medical', '의약 (약 봉투·날짜별 사진·소견서)'), ('commerce', '쇼핑 (상품 화면 ≠ 받은 상품·요청일)'),
                ('appliance', '가전 (오류 화면·모델명·수리 내역)'), ('car', '자동차 (차량 부위·정비 내역·전후 사진)'), ('telecom', '통신 (요금제·청구서·위치)'),
                ('finance', '금융 (약관·한 장씩 촬영·거래 내역)'), ('game', '게임 (아이템 화면·결제 영수증·이용 제한)'), ('building', '건설 (방 안 하자·발견일·견적서)'),
                ('other', '기타 (구매 내역·해결·자료 모음)'), ('', '그림 없음')]
PROCESS_STEPS = [
    ('제보 접수', 'write', '피해 내용과 자료를 **온라인으로 제보**하면 접수번호와 조회 코드가 발급돼요.'),
    ('내용 검토', 'search', '담당자가 **사실관계와 첨부 자료**를 확인해요. 필요하면 추가 자료를 요청해요.'),
    ('업체 확인', 'chat', '제보자가 동의한 경우 **업체에 내용을 전달**하고 답변을 받아요.'),
    ('해결 조율', 'scale', '업체 답변을 바탕으로 **해결 방법을 함께 조율**해요. 사안에 따라 취재를 검토할 수 있어요.'),
    ('결과 안내', 'check', '처리 결과를 **내 제보 조회**에서 안내하고 제보를 마무리해요.'),
]
STATUSES = ['접수', '검토 중', '추가 확인', '기업 답변 대기', '조정 진행', '종결']
SAMPLE_REPORTS = [
    ('반품 접수 후 2주째 환불이 안 돼요', '배송·환불', '○○쇼핑', '검토 중'),
    ('해지했는데 다음 달 요금이 또 결제됐어요', '구독·결제', '○○뮤직', '기업 답변 대기'),
    ('중도 해지 위약금을 과하게 청구해요', '서비스·계약', '○○피트니스', '추가 확인'),
    ('수리 후에도 같은 고장이 반복돼요', '상품·품질', '○○가전', '접수'),
    ('숙소 취소 수수료가 안내와 달라요', '여행·숙박', '○○투어', '조정 진행'),
    ('가입하지 않은 부가서비스 요금이 나왔어요', '금융·통신', '○○텔레콤', '종결'),
    ('파손된 상품의 교환을 거부해요', '배송·환불', '○○마켓', '접수'),
    ('무료체험 후 자동결제 안내가 없었어요', '구독·결제', '○○TV', '검토 중'),
]
MENU_PAGES = [
    ('reports', '제보 목록'), ('guide', '이용 안내'), ('process', '처리 절차'), ('board', '소비자게시판'),
    ('faq', '자주 묻는 질문'), ('report', '제보하기'), ('lookup', '내 제보 조회'), ('types', '제보 유형'),
    ('home', '홈 (메인 화면)'), ('terms', '이용약관'), ('privacy', '개인정보 처리방침'), ('takedown', '게시중단 요청'),
    ('custom', '직접 입력한 주소'),
]
HOME_BLOCKS = [
    ('hero', '메인 문구 + 제보하기 버튼 + 사람들 일러스트'), ('hero_plain', '메인 문구 + 제보하기 버튼 (일러스트 없이)'), ('latest_reports', '최근 제보 (실시간)'), ('board_posts', '최근 게시판 글'),
    ('notice', '공지·안내 박스'), ('process', '처리 절차 요약'), ('faq', '자주 묻는 질문 미리보기'),
]
LEGACY_NAV = [('nav.home', 'reports', '소비자 제보 목록'), ('nav.guide', 'guide', '이용 안내'), ('nav.process', 'process', '처리 절차'),
              ('nav.board', 'board', '소비자게시판'), ('nav.faq', 'faq', '자주 묻는 질문')]
LISTS = [
    ('menu', '상단 메뉴', '사이트 맨 위 메뉴예요. 이름, 순서, 연결할 페이지를 정할 수 있고 외부 주소(블로그 등)도 넣을 수 있어요.',
     [('label', '메뉴 이름', {}), ('page', '연결할 페이지', {'choices': MENU_PAGES}), ('url', '직접 입력한 주소 ("직접 입력한 주소"를 골랐을 때만, 예: https://blog.naver.com/...)', {})], 1),
    ('home_blocks', '메인 화면 구성', '메인 화면에 위에서부터 차례로 보여요. 블록 종류마다 쓰는 칸이 달라요: 제목은 모든 블록, 개수는 최근 제보·게시판 글·질문 미리보기, 내용과 버튼은 공지·안내 박스에 쓰여요. 비운 칸은 기본값을 써요.',
     [('kind', '블록 종류', {'choices': HOME_BLOCKS}), ('title', '제목', {}), ('count', '보여줄 개수', {}), ('body', '내용', ML),
      ('button_label', '버튼 글자', {}), ('button_link', '버튼 주소 (예: /report 또는 https://...)', {})], 1),
    ('report_categories', '제보 유형', '제보하기 화면, 제보 목록 필터, 유형 페이지에 쓰여요. 이미 접수된 제보의 유형은 바뀌지 않아요.', [('name', '유형 이름', {})], 1),
    ('report_industries', '제보 업종', '제보하기 화면의 업종 선택 칸이에요. 예시는 고를 때 이름 옆에 흐리게 보여요. 이미 접수된 제보의 업종은 바뀌지 않아요.',
     [('name', '업종 이름', {}), ('examples', '예시 (예: 이동통신, 인터넷·IPTV)', {})], 1),
    ('board_categories', '소비자게시판 분류', '글쓰기 분류와 게시판 탭에 쓰여요. 6번째부터는 색이 처음부터 반복돼요.', [('name', '분류 이름', {})], 1),
    ('sample_reports', '메인 예시 제보 카드', '실제 제보가 메인 카드 개수보다 적을 때 남는 자리를 "예시" 표시와 함께 채워요. 실제 제보가 늘면 하나씩 빠지고, 목록을 비우면 예시 카드는 나오지 않아요. 제보 목록 페이지에는 나오지 않아요.',
     [('title', '제목', {}), ('category', '분류', {}), ('company', '업체 표시 (예: ○○쇼핑)', {}), ('status', '진행 단계', {'choices': [(s, s) for s in STATUSES]})], 0),
    ('faq', '자주 묻는 질문', '자주 묻는 질문 페이지에 순서대로 보여요.', [('q', '질문', {}), ('a', '답변', ML)], 0),
    ('process_steps', '처리 절차 단계', '처리 절차 페이지와 메인 "처리 절차 요약"의 단계 카드예요. 번호는 자동으로 매겨져요.', [('title', '단계 이름', {}), ('icon', '아이콘', {'choices': PROCESS_ICONS}), ('body', '설명 (**강조할 말**처럼 별표 두 개로 감싸면 주황색으로 강조돼요)', ML)], 0),
    ('guide_steps', '이용 안내 · 한눈에 보는 제보 방법', '이용 안내 맨 위 단계 카드예요. 번호는 자동으로 매겨져요.', [('title', '단계 이름', {}), ('icon', '아이콘', {'choices': GUIDE_STEP_ICONS})], 0),
    ('guide_industries', '이용 안내 · 업종별 꼭 적을 내용', '업종 카드로 보이는 안내예요. 업종 이름은 제보하기 화면의 업종과 맞춰 두면 좋아요.',
     [('name', '업종 이름', {}), ('icon', '그림', {'choices': INDUSTRY_ART}), ('examples', '예시 (예: 가공식품, 배달·음식점)', {}),
      ('must', '꼭 적어 주세요 (쉼표로 구분)', ML), ('materials', '있으면 좋은 자료 (쉼표로 구분)', ML), ('tip', '한 줄 팁 (비워도 돼요)', {})], 0),
    ('guide_basics', '이용 안내 01 · 구매 정보 카드', '"언제, 어디서, 얼마에 구매했나요?" 아래 카드예요.', [('title', '제목', {}), ('body', '설명', ML)], 0),
    ('guide_writing', '이용 안내 02 · 작성 방법', '"겪은 일을 순서대로 알려 주세요" 아래 번호 목록이에요.', [('title', '질문', {}), ('body', '설명', ML)], 0),
    ('guide_topics', '이용 안내 04 · 분야별 준비자료', '분야 이름을 누르면 펼쳐지는 안내예요.', [('name', '분야 이름', {}), ('heading', '펼쳤을 때 제목', {}), ('steps', '준비 순서 (한 줄에 하나씩)', ML), ('info', '함께 적을 정보', ML), ('materials', '도움이 되는 자료', {})], 0),
]
_BLANK_BLOCK = {'title': '', 'count': '', 'body': '', 'button_label': '', 'button_link': ''}

# 페이지별 섹션 구성: 기본 섹션의 순서를 바꾸거나 빼고, 글 상자·안내 박스를 원하는 곳에 끼워 넣음
PAGE_SECTIONS = {
    'guide': ('이용 안내', [('guide_steps', '한눈에 보는 제보 방법 (단계 카드)'), ('guide_three', '이 세 가지만 담아 주세요 (만화 3컷 + 팁)'), ('guide_industry', '업종별 꼭 적을 내용 (업종 카드)'),
                           ('guide_basics', '(예전) 구매 정보 카드'), ('guide_writing', '(예전) 작성 방법 (번호 목록 + 예시)'), ('guide_evidence', '(예전) 자료 남기는 방법 (그림 안내)'),
                           ('guide_topics', '(예전) 분야별 준비자료 (펼침 목록 + 첨부 안내)'), ('guide_bottom', '하단 제보하기 버튼')]),
    'process': ('처리 절차', [('process_cards', '처리 절차 단계 카드'), ('process_note', '하단 안내 (내 제보 조회 링크)')]),
    'faq': ('자주 묻는 질문', [('faq_list', '질문 목록')]),
    'types': ('제보 유형', [('types_list', '제보 유형 목록 (유형별 제보 버튼)')]),
}
GENERIC_SECTIONS = [('heading', '소제목'), ('text', '글 상자 (제목 + 내용)'), ('notice', '안내 박스 (제목 + 내용 + 버튼)')]
for _page, (_title, _sections) in PAGE_SECTIONS.items():
    LISTS.append(('layout_' + _page, _title + ' 페이지 구성',
                  '위에서부터 차례로 보여요. 기본 섹션은 순서를 바꾸거나 지울 수 있고(문장은 사이트 화면이나 사이트 문구에서 고쳐요), 소제목·글 상자·안내 박스를 원하는 자리에 넣을 수 있어요. 제목·내용·버튼 칸은 소제목·글 상자·안내 박스에만 쓰여요.',
                  [('kind', '섹션 종류', {'choices': _sections + GENERIC_SECTIONS}), ('title', '제목', {}), ('body', '내용 (**강조할 말**처럼 별표 두 개로 감싸면 강조돼요)', ML),
                   ('button_label', '버튼 글자', {}), ('button_link', '버튼 주소 (예: /report 또는 https://...)', {})], 0))
CONSENT_KINDS = [('privacy', '개인정보 수집·이용'), ('share', '개인정보 제3자 제공 (기업 전달)'), ('copyright', '저작권 동의'), ('truth', '사실 작성 확인'), ('custom', '직접 만든 동의 항목')]
LISTS.append(('report_consents', '제보하기 동의 항목', '제보하기 화면의 동의 항목이에요. 모두 필수로 받아요. 지우면 화면에서 빠지고 체크하지 않아도 접수돼요. 표와 문장은 사이트 화면이나 사이트 문구에서 고쳐요. "직접 만든 동의 항목"은 아래 제목·내용·체크 문구 칸을 써요. 개인정보 수집·이용 동의는 법상 필요한 경우가 많으니 지우지 않는 걸 권해요.',
              [('kind', '항목 종류', {'choices': CONSENT_KINDS}), ('title', '제목 (직접 만든 항목만)', {}), ('body', '내용 (직접 만든 항목만)', ML), ('agree', '체크 문구 (직접 만든 항목만)', {})], 0))
LISTS.append(('custom_pages', '새 페이지', '원하는 페이지를 직접 만들어요. 주소는 consumerjebo.co.kr/p/영문주소 가 되고, 메뉴에 넣으려면 상단 메뉴에서 "직접 입력한 주소"를 고르고 /p/영문주소 를 적어요. 내용은 약관처럼 줄 맨 앞에 "## "를 쓰면 소제목, "- "를 쓰면 목록이 돼요.',
              [('slug', '영문 주소 (소문자·숫자·하이픈, 예: about)', {}), ('title', '페이지 제목', {}), ('body', '내용', ML)], 0))
LIST_DEFAULTS = {
    'menu': [{'label': label, 'page': page, 'url': ''} for _, page, label in LEGACY_NAV],
    'home_blocks': [dict(_BLANK_BLOCK, kind='hero'), dict(_BLANK_BLOCK, kind='latest_reports')],
    'report_categories': [{'name': n} for n in REPORT_CATEGORY_DEFAULTS],
    'report_industries': [{'name': n, 'examples': e} for n, e in REPORT_INDUSTRY_DEFAULTS],
    'board_categories': [{'name': n} for n in BOARD_CATEGORY_DEFAULTS],
    'faq': [{'q': q, 'a': a} for q, a in FAQ_DEFAULTS],
    'sample_reports': [{'title': t, 'category': c, 'company': co, 'status': st} for t, c, co, st in SAMPLE_REPORTS],
    'process_steps': [{'title': t, 'icon': i, 'body': b} for t, i, b in PROCESS_STEPS],
    'guide_steps': [{'title': t, 'icon': i} for t, i in GUIDE_STEPS],
    'guide_industries': [{'name': n, 'icon': i, 'examples': e, 'must': mu, 'materials': ma, 'tip': t} for n, i, e, mu, ma, t in INDUSTRIES],
    **_LIST_DEFAULTS,
}
for _page, (_title, _sections) in PAGE_SECTIONS.items():
    LIST_DEFAULTS['layout_' + _page] = [dict(_BLANK_BLOCK, kind=k) for k, _ in _sections]
for _blank in LIST_DEFAULTS.values():
    for _row in _blank:
        if 'kind' in _row and _row['kind'] in dict(GENERIC_SECTIONS) | {k: 1 for _, (_, ss) in PAGE_SECTIONS.items() for k, _ in ss}:
            _row.pop('count', None)
LIST_DEFAULTS['layout_guide'] = [dict(_BLANK_BLOCK, kind=k) for k in ('guide_steps', 'guide_three', 'guide_industry', 'guide_bottom')]
for _row in LIST_DEFAULTS['layout_guide']:_row.pop('count', None)
LIST_DEFAULTS['custom_pages'] = []
LIST_DEFAULTS['report_consents'] = [{'kind': k, 'title': '', 'body': '', 'agree': ''} for k in ('privacy', 'share', 'copyright', 'truth')]
LIST_MAX_ITEMS = 60

# ---- 화면 곳곳의 버튼·안내 문구 ----------------------------------------------
# 템플릿에 {{ ui('report.submit', '제보 접수하기') }}처럼 적으면, 여기서 그 키와 기본 문구를 찾아
# 관리자 '사이트 문구'에 자동으로 칸을 만들어 줌. 새 문구를 넣을 때 이 파일을 따로 고칠 필요가 없음.
import re as _re
_UI_CALL = _re.compile(r"""\bui(?:_text|_rich)?\(\s*'([a-z0-9_.]+)'\s*,\s*'([^'\n]*)'""")
UI_GROUPS = {
    'common': '공통 (헤더·푸터)', 'home': '메인 화면', 'reports': '제보 목록·공개 제보', 'report': '제보하기 화면',
    'done': '제보 완료 화면', 'lookup': '내 제보 조회', 'guide': '이용 안내', 'process': '처리 절차', 'types': '제보 유형',
    'faq': '자주 묻는 질문', 'board': '소비자게시판', 'member': '회원가입·로그인·내 정보', 'takedown': '권리침해 신고',
    'policy': '약관·개인정보 처리방침·게시중단', 'company': '기업 답변 화면', 'msg': '알림 메시지 (입력 오류 등)',
}
def _scan_ui():
    found = {}
    root = Path(__file__).parent
    for path in sorted((root / 'templates').glob('*.html')) + [root / 'app.py']:
        for key, default in _UI_CALL.findall(path.read_text(encoding='utf-8')):
            found.setdefault(key, default)
    return found
UI_TEXTS = _scan_ui()
_section_ids = {sid for sid, _, _ in SECTIONS}
for _key, _default in UI_TEXTS.items():
    _group = _key.split('.')[0]
    _sid = _group if _group in _section_ids else 'ui_' + _group
    if _sid not in _section_ids:
        SECTIONS.append((_sid, UI_GROUPS.get(_group, _group) + ' · 버튼·안내 문구', []))
        _section_ids.add(_sid)
    _items = next(items for sid, _, items in SECTIONS if sid == _sid)
    _label = '화면 문구: ' + (_default if len(_default) <= 40 else _default[:40] + '…')
    _items.append((_key, _label, _default, ML if len(_default) > 70 else {}))

FIELDS = {key: {'label': label, 'default': default, 'section': sid, **opts}
          for sid, _, items in SECTIONS for key, label, default, opts in items}
MAX_LENGTH = 2000
DOC_MAX_LENGTH = 30000
