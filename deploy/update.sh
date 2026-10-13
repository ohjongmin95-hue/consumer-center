#!/usr/bin/env bash
# 최신 코드를 받아 앱을 다시 시작합니다. 사용법: sudo bash /opt/soboru/app/deploy/update.sh
set -euo pipefail
# 기본값: 서버에 현재 설치된 브랜치를 그대로 유지
BRANCH="${BRANCH:-$(git -C /opt/soboru/app rev-parse --abbrev-ref HEAD)}"
git -C /opt/soboru/app fetch -q origin "$BRANCH"
git -C /opt/soboru/app checkout -q -B "$BRANCH" "origin/$BRANCH"
/opt/soboru/venv/bin/pip install -q -r /opt/soboru/app/requirements.txt
systemctl restart soboru
# SOBORU 플랫폼(한큐 + 소보루 비즈)이 설치돼 있으면 같이 다시 시작
if [ -f /etc/systemd/system/soboru-platform.service ]; then
  # 소비자제보센터에 넣어 둔 메일 설정을 소보루 CS에도 똑같이 넣음 (비밀번호 찾기·알림 메일)
  if [ -f /etc/soboru.env ] && [ -f /etc/soboru-platform.env ] && grep -q '^SMTP_HOST=.' /etc/soboru.env && ! grep -q '^SMTP_HOST=.' /etc/soboru-platform.env; then
    grep -E '^SMTP_(HOST|PORT|USER|PASSWORD|FROM)=' /etc/soboru.env >> /etc/soboru-platform.env
  fi
  systemctl restart soboru-platform
  if grep -q '^SMTP_HOST=.' /etc/soboru-platform.env 2>/dev/null; then echo "소보루 CS 메일: 켜져 있어요"
  else echo "소보루 CS 메일: 꺼져 있어요. 켜려면 set-mail.sh를 한 번 실행해 주세요."; fi
  # 답변 지연 알림 · 불량 경보 · 월간 리포트 (한 시간마다, 같은 알림은 한 번만)
  cat > /etc/cron.hourly/soboru-platform-late <<'CRON'
#!/bin/sh
set -a; . /etc/soboru-platform.env; set +a
cd /opt/soboru/app/platform_app && runuser -u soboru -- /opt/soboru/venv/bin/python notify_late.py >/dev/null 2>&1
CRON
  chmod 755 /etc/cron.hourly/soboru-platform-late
fi
sleep 2
systemctl is-active --quiet soboru && echo "업데이트 완료: $(git -C /opt/soboru/app log -1 --format='%h %s')" || { journalctl -u soboru -n 30 --no-pager; exit 1; }
