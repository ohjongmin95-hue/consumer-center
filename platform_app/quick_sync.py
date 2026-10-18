"""1분마다 도는 빠른 가져오기: 카페24 주문·문의 게시판, 이메일 문의, 그리고 AI 자동 답변.

사장님이 '지금 가져오기'를 누르지 않아도 새 문의가 1분 안에 들어오고 AI가 답하게 한다.
상품(6시간)과 지난 14일 주문 다시 보기(1시간)는 cafe24.sync_all 안에서 따로 간격을 지킨다.
스마트스토어·쿠팡, 인스타그램 토큰 갱신, 웹훅, 요금 결제는 10분 cron(shops.py)이 그대로 맡는다.
두 cron이 겹치지 않게 같은 잠금 파일(flock)을 쓴다 (deploy/update.sh).
사용법: cd platform_app && python quick_sync.py
"""
import core, cafe24, mailin, chatbot

if __name__=='__main__':
    core.MAIL_ASYNC=False
    print(f'카페24 {cafe24.sync_all()}건, 이메일 문의 {mailin.sync_all()}건, AI 자동 답변 {chatbot.auto_reply_all()}건')
