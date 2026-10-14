#!/usr/bin/env bash
# 바로 전 버전으로 되돌립니다. update.sh가 업데이트할 때마다 직전 버전을 적어 둡니다.
# 사용법: sudo bash /opt/soboru/app/deploy/rollback.sh
#   DB는 그대로 둡니다 (새 버전은 표를 더하기만 해서 예전 버전도 그대로 열려요).
#   DB까지 되돌려야 하면 /var/lib/soboru-platform/backups/ 의 업데이트 직전 백업(pre-update-*.sqlite3)을 쓰세요.
set -euo pipefail
APP=/opt/soboru/app; PREV_FILE=/var/lib/soboru-platform/prev-commit
[ -s $PREV_FILE ] || { echo "되돌릴 버전 기록이 없어요"; exit 1; }
PREV="$(cat $PREV_FILE)"; BRANCH="$(git -C $APP rev-parse --abbrev-ref HEAD)"
echo "지금: $(git -C $APP log -1 --format='%h %s')"
git -C $APP checkout -q -B "$BRANCH" "$PREV"
chmod -R u+rwX,go+rX $APP
systemctl restart soboru soboru-platform
sleep 3
H="$(grep -E '^BUSINESS_HOST=' /etc/soboru-platform.env 2>/dev/null | cut -d= -f2- || true)"
if [ -n "$H" ]; then CODE="$(curl -s -o /dev/null -m 10 -w '%{http_code}' -H "Host: $H" http://127.0.0.1:8100/login || true)"
else CODE="$(curl -s -o /dev/null -m 10 -w '%{http_code}' http://127.0.0.1:8100/biz/login || true)"; fi
echo "되돌림: $(git -C $APP log -1 --format='%h %s') · 소보루 CS 응답 $CODE"
