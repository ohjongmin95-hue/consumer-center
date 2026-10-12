"""정기 알림. 서버의 cron이 한 시간마다 실행한다.
  · 답변 목표일이 지난 민원 알림
  · 불량 조기 경보 (기업별 하루 한 번)
  · 월간 CS 리포트 (매달 1일, 기업별 한 번)
사용법: cd platform_app && python notify_late.py
"""
import core, insights

if __name__=='__main__':
    core.MAIL_ASYNC=False
    print(f'지연 알림 {core.notify_late()}건 · 경보 {insights.send_alerts()}건 · 월간 리포트 {insights.send_monthly_reports()}건')
