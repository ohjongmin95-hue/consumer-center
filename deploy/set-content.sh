#!/bin/bash
# 소보루 자동 카드뉴스·릴스: 아침 9시·오후 1시·저녁 9시쯤 만드는 예약 작업을 설치하거나 끕니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-content.sh          설치(켜기) 후 지금 한 번 시험
#         sudo bash /opt/soboru/app/deploy/set-content.sh off      끄기
#         sudo bash /opt/soboru/app/deploy/set-content.sh dry      AI·저장 없이 고를 기사만 보기
# 알림: /etc/soboru.env 의 CONTENT_TELEGRAM_BOT_TOKEN·CONTENT_TELEGRAM_CHAT_ID (없으면 TELEGRAM_BOT_TOKEN·TELEGRAM_CHAT_ID)
set -euo pipefail
APP=/opt/soboru/app; ENV_FILE=/etc/soboru.env
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
case "${1:-on}" in
  off) systemctl disable --now soboru-content.timer 2>/dev/null || true; echo "자동 카드뉴스·릴스를 껐어요."; exit 0;;
  dry) runuser -u soboru -- bash -c "set -a; . $ENV_FILE; set +a; cd $APP && exec /opt/soboru/venv/bin/python -m auto_content --dry"; exit 0;;
esac
grep -q '^OPENAI_API_KEY=.' $ENV_FILE || echo "주의: OPENAI_API_KEY가 없어 만들지 못해요."
command -v ffmpeg >/dev/null || echo "주의: ffmpeg가 없어 릴스는 빠지고 카드뉴스만 만들어요."
grep -qE '^(CONTENT_)?TELEGRAM_BOT_TOKEN=.' $ENV_FILE || echo "참고: 텔레그램 토큰이 없어 알림은 가지 않아요."
install -m 644 $APP/deploy/soboru-content.service /etc/systemd/system/soboru-content.service
install -m 644 $APP/deploy/soboru-content.timer /etc/systemd/system/soboru-content.timer
systemctl daemon-reload
systemctl enable --now soboru-content.timer
echo "설치했어요. 아침 9시·오후 1시·저녁 9시쯤 세 편씩 만들어 만든 것 보관함에 넣어요 (AUTO_CONTENT_PER_RUN으로 바꿈)."
echo "지금 한 번 돌려 볼게요 (몇 분 걸려요)..."
systemctl start soboru-content.service || true
journalctl -u soboru-content -n 15 --no-pager -o cat | grep -v -i -E 'key|token|password|secret' || true
