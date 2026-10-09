#!/usr/bin/env bash
# 최신 코드를 받아 앱을 다시 시작합니다. 사용법: sudo bash /opt/soboru/app/deploy/update.sh
set -euo pipefail
BRANCH="${BRANCH:-main}"
git -C /opt/soboru/app fetch -q origin "$BRANCH"
git -C /opt/soboru/app checkout -q -B "$BRANCH" "origin/$BRANCH"
/opt/soboru/venv/bin/pip install -q -r /opt/soboru/app/requirements.txt
systemctl restart soboru
sleep 2
systemctl is-active --quiet soboru && echo "업데이트 완료: $(git -C /opt/soboru/app log -1 --format='%h %s')" || { journalctl -u soboru -n 30 --no-pager; exit 1; }
