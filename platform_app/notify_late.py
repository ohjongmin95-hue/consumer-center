"""답변 목표일이 지난 민원을 알린다. 서버의 cron이 한 시간마다 실행한다.
사용법: cd platform_app && python notify_late.py
"""
import core

if __name__=='__main__':
    core.MAIL_ASYNC=False
    print(f'알림 {core.notify_late()}건')
