#!/usr/bin/env bash
# 최신 코드를 받아 앱을 다시 시작합니다. 사용법: sudo bash /opt/soboru/app/deploy/update.sh
set -euo pipefail
# 기본값: 서버에 현재 설치된 브랜치를 그대로 유지
BRANCH="${BRANCH:-$(git -C /opt/soboru/app rev-parse --abbrev-ref HEAD)}"
git -C /opt/soboru/app fetch -q origin "$BRANCH"
git -C /opt/soboru/app checkout -q -B "$BRANCH" "origin/$BRANCH"
/opt/soboru/venv/bin/pip install -q -r /opt/soboru/app/requirements.txt
systemctl restart soboru
# SOBORU 플랫폼(한큐 + SOBORU Business)이 설치돼 있으면 같이 다시 시작
if [ -f /etc/systemd/system/soboru-platform.service ]; then
  systemctl restart soboru-platform
  # 답변 목표일이 지난 민원 알림 (한 시간마다)
  cat > /etc/cron.hourly/soboru-platform-late <<'CRON'
#!/bin/sh
set -a; . /etc/soboru-platform.env; set +a
cd /opt/soboru/app/platform_app && runuser -u soboru -- /opt/soboru/venv/bin/python notify_late.py >/dev/null 2>&1
CRON
  chmod 755 /etc/cron.hourly/soboru-platform-late
fi
sleep 2
systemctl is-active --quiet soboru && echo "업데이트 완료: $(git -C /opt/soboru/app log -1 --format='%h %s')" || { journalctl -u soboru -n 30 --no-pager; exit 1; }
