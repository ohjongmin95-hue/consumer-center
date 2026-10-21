"""보안·개인정보 안내 (Gorgias의 Security 페이지에 해당). 지금 코드와 서버 설정에 실제로 있는 것만 적는다."""
from flask import Blueprint, render_template
import core

bp=Blueprint('sec',__name__)
# (제목, 설명) - 코드 근거: hanq.py 쿠키 설정, core.check_csrf, werkzeug scrypt, shops.seal, team.can, core.purge_old, deploy/platform-setup.sh
HTTPS_ITEM=('접속 암호화','서비스 주소는 HTTPS로만 열리고, http로 들어오면 https로 넘겨요. 로그인 쿠키는 HTTPS에서만 오가고 화면 스크립트가 읽을 수 없게 해 두었어요.')
ITEMS=[('비밀번호','비밀번호는 원문을 저장하지 않고 scrypt 방식의 해시로만 저장해요. 운영자도 비밀번호를 볼 수 없어요. 로그인·가입·비밀번호 찾기는 짧은 시간에 여러 번 시도하면 잠시 막아요.'),
       ('판매처 키 보관','판매처에서 받은 연결 키(토큰)는 서버의 비밀 키로 암호화하고 위·변조 검사값을 붙여 저장해요. 화면에는 다시 보여 주지 않아요.'),
       ('요청 위조 방지','모든 저장·변경 버튼에 화면마다 다른 확인 값(CSRF 토큰)을 붙여, 다른 사이트에서 몰래 보내는 요청을 막아요.'),
       ('직원 권한','대표·관리자·상담원·보기 전용 역할로 나눠, 설정·판매처 연결·직원 관리는 대표와 관리자만 할 수 있어요. 누가 답하고 처리했는지 기록이 남아요.'),
       ('데모와 실제 데이터 분리','데모 작업 공간의 견본 문의는 실제 고객 데이터와 섞이지 않고, 고객에게 알림을 보내지 않아요.'),
       ('보관 기간과 파기','마지막 처리일부터 3년이 지난 문의와 첨부 파일, 같은 기간이 지난 주문·메일 기록은 매일 자동으로 파기해요. 마케팅 분석용 방문 기록에는 IP·이름·연락처를 남기지 않아요.'),
       ('백업','데이터베이스와 첨부 파일을 매일 백업하고 14일 동안 보관해요.')]
AI_NOTE=('AI 상담을 켜면 고객이 상담창에 쓴 질문과 회사가 넣어 둔 안내 정보가 답변을 만들기 위해 AI 서비스(OpenAI, 키가 없을 때 Anthropic)로 전송돼요. '
         'AI 상담을 끄면 전송하지 않아요.')
NOT_YET=['정보보호 관리체계(ISMS·ISO 27001 등) 인증은 아직 받지 않았어요.','외부 보안 점검(모의 해킹)은 아직 받지 않았어요. 외부 연동 API는 보안 점검을 마친 뒤 공개할 예정이에요.',
         '백업은 서비스와 같은 서버에 보관해요. 다른 장소 보관은 준비 중이에요.']

@bp.route('/security')
def page():
    import os
    items=([HTTPS_ITEM] if os.getenv('HTTPS_ONLY')=='1' else [])+ITEMS  # 서버에 HTTPS가 켜졌을 때만 적는다
    return render_template('m_security.html',items=items,ai_note=AI_NOTE,not_yet=NOT_YET,tab='sec.page')
