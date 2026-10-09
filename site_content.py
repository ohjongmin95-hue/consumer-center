"""관리자 화면에서 수정할 수 있는 사이트 문구.

각 항목은 (키, 이름, 기본값, 옵션) 형식입니다. 옵션의 'multiline'은 줄바꿈을 허용하고,
'optional'은 빈 값으로 저장해 해당 문구를 숨길 수 있게 합니다. 그 밖의 항목은 비워 저장하면
기본값으로 돌아갑니다.
"""

FAQ_DEFAULTS = [
    ('신고하면 바로 해결되나요?', '신고 접수만으로 환불이나 보상이 확정되지는 않습니다. 내용에 따라 후속 검토가 이루어질 수 있습니다.'),
    ('어떤 자료를 첨부하면 좋나요?', '영수증, 주문 내역, 업체와 주고받은 메시지 등 사실관계를 확인할 수 있는 자료가 도움이 됩니다.'),
    ('신고 내용이 공개되나요?', '공개에 동의한 신고 중 센터가 승인한 제목·분류·상태만 목록에 표시됩니다. 상세 내용과 연락처는 공개되지 않습니다.'),
    ('공식 분쟁조정이나 피해구제도 가능한가요?', '이 센터는 법정 피해구제기관이 아닙니다. 공식적인 상담·피해구제는 1372 소비자상담센터 등 관련 기관을 이용해 주세요.'),
]
FAQ_SLOTS = 8

ML = {'multiline': True}
OPT = {'optional': True}
OPT_ML = {'optional': True, 'multiline': True}

SECTIONS = [
    ('common', '공통 (헤더·푸터)', [
        ('nav.home', '메뉴: 신고 목록', '신고 목록', {}),
        ('nav.guide', '메뉴: 신고 이용안내', '신고 이용안내', {}),
        ('nav.process', '메뉴: 처리 절차', '처리 절차', {}),
        ('nav.types', '메뉴: 신고 유형', '신고 유형', {}),
        ('nav.faq', '메뉴: 자주 묻는 질문', '자주 묻는 질문', {}),
        ('footer.text', '푸터 문구', 'by SOBORU.', ML),
    ]),
    ('home', '메인 화면', [
        ('home.hero_title', '메인 문구', '여러분의 신고가\n권익 보호의 시작입니다.', ML),
        ('home.hero_button', '신고 버튼', '신고하기 →', {}),
        ('home.list_title', '목록 제목', '신고 목록', {}),
        ('home.search_placeholder', '검색창 안내 문구', '신고 제목 검색', {}),
        ('home.empty', '목록이 비었을 때', '표시할 신고 내역이 없습니다.', {}),
        ('home.empty_search', '검색 결과가 없을 때', '검색 조건에 맞는 신고 내역이 없습니다.', {}),
        ('home.list_note', '목록 아래 안내', '공개에 동의하고 센터의 검토를 거친 신고만 표시됩니다.', OPT_ML),
        ('home.lookup_link', '내 신고 조회 링크', '내 신고 조회 →', {}),
    ]),
    ('guide', '신고 이용안내', [
        ('guide.eyebrow', '상단 작은 제목', '신고 전 확인해 주세요', OPT),
        ('guide.title', '페이지 제목', '신고 이용안내', {}),
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
        ('guide.bottom_button', '하단 버튼', '신고 작성하기 →', {}),
    ]),
    ('process', '처리 절차', [
        ('process.title', '페이지 제목', '처리 절차', {}),
        ('process.intro', '소개 문구', '신고 내용의 확인 및 검토 과정에 대한 안내입니다.', OPT_ML),
        ('process.step1_title', '1단계 제목', '신고 접수', OPT),
        ('process.step1_body', '1단계 설명', '신고자가 피해 내용을 작성하고 관련 자료를 제출합니다.', OPT_ML),
        ('process.step2_title', '2단계 제목', '내용 검토', OPT),
        ('process.step2_body', '2단계 설명', '제출된 내용의 사실관계와 자료를 검토합니다. 필요한 경우 추가 자료를 요청할 수 있습니다.', OPT_ML),
        ('process.step3_title', '3단계 제목', '후속 검토', OPT),
        ('process.step3_body', '3단계 설명', '사안에 따라 업체 의견 확인 또는 취재 여부를 검토할 수 있습니다. 모든 신고가 취재·공개되는 것은 아닙니다.', OPT_ML),
        ('process.step4_title', '4단계 제목', '', OPT),
        ('process.step4_body', '4단계 설명', '', OPT_ML),
        ('process.note', '하단 안내', '접수번호와 비밀 조회 코드로 내 신고의 진행 상황을 확인할 수 있습니다.', OPT_ML),
    ]),
    ('types', '신고 유형', [
        ('types.title', '페이지 제목', '신고 유형', {}),
        ('types.intro', '소개 문구', '해당하는 유형을 선택해 피해 내용을 작성할 수 있습니다.', OPT_ML),
        ('types.link', '유형별 버튼', '이 유형으로 신고 →', {}),
    ]),
    ('faq', '자주 묻는 질문', [
        ('faq.title', '페이지 제목', '자주 묻는 질문', {}),
        ('faq.intro', '소개 문구', '신고 전 확인하면 좋은 내용을 정리했습니다.', OPT_ML),
    ] + [
        item
        for i in range(FAQ_SLOTS)
        for item in (
            (f'faq.q{i + 1}', f'질문 {i + 1}', FAQ_DEFAULTS[i][0] if i < len(FAQ_DEFAULTS) else '', OPT),
            (f'faq.a{i + 1}', f'답변 {i + 1}', FAQ_DEFAULTS[i][1] if i < len(FAQ_DEFAULTS) else '', OPT_ML),
        )
    ]),
]

FIELDS = {key: {'label': label, 'default': default, 'section': sid, **opts}
          for sid, _, items in SECTIONS for key, label, default, opts in items}
MAX_LENGTH = 2000
