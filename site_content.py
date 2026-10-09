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
    ('제보 내용이 공개되나요?', '공개에 동의한 제보 중 센터가 승인한 제목·분류·상태만 목록에 표시됩니다. 상세 내용과 연락처는 공개되지 않습니다.'),
    ('공식 분쟁조정이나 피해구제도 가능한가요?', '이 센터는 법정 피해구제기관이 아닙니다. 공식적인 상담·피해구제는 1372 소비자상담센터 등 관련 기관을 이용해 주세요.'),
]
FAQ_SLOTS = 8

ML = {'multiline': True}
OPT = {'optional': True}
OPT_ML = {'optional': True, 'multiline': True}

SECTIONS = [
    ('common', '공통 (헤더·푸터)', [
        ('site.name', '사이트 이름 (브라우저 탭 등)', '소비자제보센터', {}),
        ('site.logo_accent', '로고 앞부분 (주황색)', '소비자', OPT),
        ('site.logo_rest', '로고 뒷부분', '제보센터', {}),
        ('nav.home', '메뉴: 제보 목록', '제보 목록', {}),
        ('nav.guide', '메뉴: 이용 안내', '이용 안내', {}),
        ('nav.process', '메뉴: 처리 절차', '처리 절차', {}),
        ('nav.board', '메뉴: 소비자게시판', '소비자게시판', {}),
        ('nav.faq', '메뉴: 자주 묻는 질문', '자주 묻는 질문', {}),
        ('footer.text', '푸터 맨 아래 문구', '© SOBORU. All rights reserved.', ML),
    ]),
    ('operator', '운영자 정보 (푸터·약관에 표시)', [
        ('operator.name', '운영자(상호)', '소보루', {}),
        ('operator.ceo', '대표자', '', OPT),
        ('operator.biz_no', '사업자등록번호', '', OPT),
        ('operator.address', '주소', '', OPT),
        ('operator.email', '대표 이메일', '', OPT),
        ('operator.phone', '대표 전화', '', OPT),
        ('operator.privacy_officer', '개인정보 보호책임자', '', OPT),
        ('operator.privacy_contact', '개인정보 보호책임자 연락처', '', OPT),
        ('operator.notice', '민간 운영 안내', '소비자제보센터는 민간이 운영하는 소비자 제보 창구로, 국가기관이나 한국소비자원과 관련이 없습니다. 공식 상담과 피해구제는 1372 소비자상담센터(국번 없이 1372)를 이용해 주세요.', OPT_ML),
    ]),
    ('home', '메인 화면', [
        ('home.hero_title', '메인 문구', '여러분의 제보가\n권익 보호의 시작입니다.', ML),
        ('home.hero_button', '제보 버튼', '제보하기 →', {}),
        ('home.list_title', '목록 제목', '제보 목록', {}),
        ('home.search_placeholder', '검색창 안내 문구', '제보 제목 검색', {}),
        ('home.empty', '목록이 비었을 때', '표시할 제보 내역이 없습니다.', {}),
        ('home.empty_search', '검색 결과가 없을 때', '검색 조건에 맞는 제보 내역이 없습니다.', {}),
        ('home.list_note', '목록 아래 안내', '공개에 동의하고 센터의 검토를 거친 제보만 표시됩니다.', OPT_ML),
        ('home.lookup_link', '내 제보 조회 링크', '내 제보 조회 →', {}),
    ]),
    ('report', '제보하기 화면', [
        ('report.title', '페이지 제목', '소비자 피해 제보하기', {}),
        ('report.intro', '소개 문구', '필수 정보를 입력하면 접수번호와 비밀 조회 코드가 발급됩니다. 제보 내용은 공개되지 않습니다.', OPT_ML),
        ('report.notes', '제보 전 꼭 읽어 주세요 (한 줄에 하나씩)', '업체명과 제보 유형을 정확히 골라 주시면 더 빨리 확인할 수 있어요.\n본문에는 이름, 전화번호, 주소 같은 개인정보를 적지 마세요. 연락이 필요하면 이메일 칸만 써 주세요.\n영수증, 계약서, 사진, 업체와 나눈 대화처럼 사실을 확인할 수 있는 자료를 첨부하면 큰 도움이 돼요.\n접수 후 나오는 접수번호와 조회 코드는 꼭 따로 보관해 주세요. 다시 보여 드릴 수 없어요.\n접수된 제보는 직접 고치거나 지울 수 없어요. 삭제를 원하면 운영자 이메일로 요청해 주세요.\n비방, 욕설, 명예를 훼손하는 표현, 광고성 내용은 공개되지 않거나 삭제될 수 있어요.\n상대방의 개인정보를 그대로 드러낸 글은 예고 없이 비공개 처리될 수 있어요.', OPT_ML),
        ('report.privacy_items', '[필수] 개인정보 수집·이용: 항목', '제보 유형, 업체·서비스명, 제보 제목과 내용, 원하는 해결 방법\n(선택) 이메일, 첨부파일', ML),
        ('report.privacy_purpose', '[필수] 개인정보 수집·이용: 목적', '제보 접수와 사실관계 확인, 처리 경과 안내', ML),
        ('report.privacy_period', '[필수] 개인정보 수집·이용: 보유 기간', '제보 처리 종결 후 1년\n(삭제 요청 시 바로 파기)', ML),
        ('report.refusal_note', '동의 거부 안내', '동의를 거부할 수 있어요. 다만 필수 항목에 동의하지 않으면 제보를 접수할 수 없어요.', ML),
        ('report.share_recipient', '[선택] 기업 전달: 제공받는 곳', '제보 대상 기업', ML),
        ('report.share_items', '[선택] 기업 전달: 제공 항목', '제보 제목, 업체명, 피해 내용, 원하는 해결 방법\n(연락처·첨부파일은 전달하지 않아요)', ML),
        ('report.share_purpose', '[선택] 기업 전달: 목적', '사실관계 확인과 기업 답변 요청', ML),
        ('report.share_period', '[선택] 기업 전달: 보유 기간', '기업의 답변 처리가 끝날 때까지', ML),
        ('report.consent_public', '[선택] 공개 목록 표시 동의 문구', '센터가 개인정보와 업체를 특정할 수 있는 표현을 검토한 뒤, 제보 제목·분류·진행 상태를 공개 목록에 표시하는 데 동의합니다.', ML),
        ('report.use_text', '[선택] 제보 내용 활용 동의 문구', '보내 주신 글과 사진은 개인정보를 가린 뒤 소비자 피해 예방을 위한 콘텐츠(기사, 카드뉴스, SNS 게시물 등)에 활용될 수 있어요. 동의하지 않아도 제보는 똑같이 접수되고, 동의한 뒤에도 운영자 이메일로 언제든 철회할 수 있어요.', ML),
        ('report.consent_truth', '[필수] 사실 작성 확인 문구', '사실에 근거해 작성했습니다. 허위 사실이나 타인의 명예를 훼손하는 내용을 적으면 법적 책임이 따를 수 있음을 확인합니다.', ML),
    ]),
    ('guide', '이용 안내', [
        ('guide.eyebrow', '상단 작은 제목', '제보 전 확인해 주세요', OPT),
        ('guide.title', '페이지 제목', '이용 안내', {}),
        ('guide.intro', '소개 문구', '어디서부터 써야 할지 막막하신가요?\n구매 정보, 겪은 일, 원하는 해결 방법을 차례로 적어 주세요.', OPT_ML),
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
        ('board.intro', '소개 문구', '사고, 쓰고, 계약하면서 겪은 일을 편하게 나눠요.\n비슷한 경험이 있다면 공감을 눌러 주세요.', OPT_ML),
        ('board.rules', '글쓰기 약속 (한 줄에 하나씩)', '경험한 사실을 중심으로 써 주세요. 추측이나 단정은 피해 주세요.\n이름, 전화번호, 주소, 주문번호처럼 누군가를 알아볼 수 있는 정보는 적지 마세요.\n특정인을 향한 욕설, 비방, 조롱은 삼가 주세요.\n광고, 홍보, 같은 글 반복 등록은 삭제돼요.\n여러 분이 부적절하다고 알린 글은 자동으로 숨겨지고 운영자가 확인해요.', OPT_ML),
        ('board.empty', '글이 없을 때 문구', '아직 글이 없어요. 첫 이야기를 들려주세요.', {}),
    ]),
    ('process', '처리 절차', [
        ('process.title', '페이지 제목', '처리 절차', {}),
        ('process.intro', '소개 문구', '제보 내용의 확인 및 검토 과정에 대한 안내입니다.', OPT_ML),
        ('process.step1_title', '1단계 제목', '제보 접수', OPT),
        ('process.step1_body', '1단계 설명', '제보자가 피해 내용을 작성하고 관련 자료를 제출합니다.', OPT_ML),
        ('process.step2_title', '2단계 제목', '내용 검토', OPT),
        ('process.step2_body', '2단계 설명', '제출된 내용의 사실관계와 자료를 검토합니다. 필요한 경우 추가 자료를 요청할 수 있습니다.', OPT_ML),
        ('process.step3_title', '3단계 제목', '후속 검토', OPT),
        ('process.step3_body', '3단계 설명', '사안에 따라 업체 의견 확인 또는 취재 여부를 검토할 수 있습니다. 모든 제보가 취재·공개되는 것은 아닙니다.', OPT_ML),
        ('process.step4_title', '4단계 제목', '', OPT),
        ('process.step4_body', '4단계 설명', '', OPT_ML),
        ('process.note', '하단 안내', '접수번호와 비밀 조회 코드로 내 제보의 진행 상황을 확인할 수 있습니다.', OPT_ML),
    ]),
    ('types', '제보 유형', [
        ('types.title', '페이지 제목', '제보 유형', {}),
        ('types.intro', '소개 문구', '해당하는 유형을 선택해 피해 내용을 작성할 수 있습니다.', OPT_ML),
        ('types.link', '유형별 버튼', '이 유형으로 제보 →', {}),
    ]),
    ('faq', '자주 묻는 질문', [
        ('faq.title', '페이지 제목', '자주 묻는 질문', {}),
        ('faq.intro', '소개 문구', '제보 전 확인하면 좋은 내용을 정리했습니다.', OPT_ML),
    ] + [
        item
        for i in range(FAQ_SLOTS)
        for item in (
            (f'faq.q{i + 1}', f'질문 {i + 1}', FAQ_DEFAULTS[i][0] if i < len(FAQ_DEFAULTS) else '', OPT),
            (f'faq.a{i + 1}', f'답변 {i + 1}', FAQ_DEFAULTS[i][1] if i < len(FAQ_DEFAULTS) else '', OPT_ML),
        )
    ]),
]

POLICY_HINT = '줄 맨 앞에 "## "를 쓰면 소제목, "- "를 쓰면 목록이 됩니다. {운영자}, {대표자}, {이메일}, {전화}, {주소}, {보호책임자}, {보호책임자연락처}, {시행일}은 운영자 정보로 자동 바뀝니다.'

SECTIONS += [
    ('policy', '약관·개인정보 처리방침·게시중단', [
        ('policy.effective_date', '시행일', '2026년 10월 9일', {}),
        ('policy.terms', '이용약관', _policy('terms'), {'multiline': True, 'doc': True}),
        ('policy.privacy', '개인정보 처리방침', _policy('privacy'), {'multiline': True, 'doc': True}),
        ('policy.takedown', '게시중단 요청 안내', _policy('takedown'), {'multiline': True, 'doc': True}),
    ]),
]

FIELDS = {key: {'label': label, 'default': default, 'section': sid, **opts}
          for sid, _, items in SECTIONS for key, label, default, opts in items}
MAX_LENGTH = 2000
DOC_MAX_LENGTH = 30000
