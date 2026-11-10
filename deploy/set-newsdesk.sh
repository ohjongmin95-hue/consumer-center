#!/bin/bash
# 소비자를위한신문 아침 데스크 메일 (매일 오전 9시·오후 2시) 켜기·끄기 (운영자 2026-11-10)
# 사용법: sudo bash /opt/soboru/app/deploy/set-newsdesk.sh [받는 메일]   켜고 지금 한 번 보냄
#         sudo bash /opt/soboru/app/deploy/set-newsdesk.sh off           끄기
set -euo pipefail
APP=/opt/soboru/app; ENV_FILE=/etc/soboru.env
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
if [[ ${1:-} == off ]]; then systemctl disable --now soboru-newsdesk.timer 2>/dev/null || true; echo "아침 데스크 메일을 껐어요."; exit 0; fi
if [[ -n ${1:-} ]]; then
  grep -q '^NEWS_DESK_TO=' $ENV_FILE && sed -i "s|^NEWS_DESK_TO=.*|NEWS_DESK_TO=$1|" $ENV_FILE || echo "NEWS_DESK_TO=$1" >> $ENV_FILE
fi
install -m 644 $APP/deploy/soboru-newsdesk.service /etc/systemd/system/soboru-newsdesk.service
install -m 644 $APP/deploy/soboru-newsdesk.timer /etc/systemd/system/soboru-newsdesk.timer
systemctl daemon-reload
systemctl enable --now soboru-newsdesk.timer
echo "켰어요. 매일 오전 9시·오후 2시에 메일이 가요. 지금 한 번 보내 볼게요 (2~3분)..."
systemctl start soboru-newsdesk.service || true
journalctl -u soboru-newsdesk -n 8 --no-pager -o cat | grep -v -i -E 'key|token|password|secret' || true
