#!/bin/bash
# 소보루 레터: 매주 레터를 만드는 예약 작업(systemd 타이머)을 설치하거나 끕니다. 요일·자동 보내기는 관리자 > 소보루 레터에서 정해요.
# 사용법: sudo bash /opt/soboru/app/deploy/set-letter.sh          설치(켜기). 매일 아침 7시 30분에 깨어 고른 요일에만 한 호를 만들어요
#         sudo bash /opt/soboru/app/deploy/set-letter.sh off      예약 작업 끄기
#         sudo bash /opt/soboru/app/deploy/set-letter.sh dry      AI·저장·발송 없이 뉴스와 법 조문 후보만 모아 보기 (키 연결 확인용)
# 필요한 것: /etc/soboru.env 의 OPENAI_API_KEY, NAVER_HUB_CLIENT_ID·SECRET(set-naver.sh), 메일 발송 SMTP_*(set-mail.sh)
set -euo pipefail
APP=/opt/soboru/app; ENV_FILE=/etc/soboru.env
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
case "${1:-on}" in
  off) systemctl disable --now soboru-letter.timer 2>/dev/null || true; echo "소보루 레터 예약 작업을 껐어요. 이미 만든 레터와 구독자는 그대로예요."; exit 0 ;;
  dry) runuser -u soboru -- bash -c "set -a; . $ENV_FILE; set +a; cd $APP && exec /opt/soboru/venv/bin/python soboru_letter.py weekly --dry"; exit 0 ;;
esac
grep -q '^OPENAI_API_KEY=.' $ENV_FILE || echo "주의: OPENAI_API_KEY가 없어 레터를 쓰지 못해요. 넣은 뒤 다시 실행해 주세요."
grep -q '^NAVER_HUB_CLIENT_ID=.' $ENV_FILE || echo "주의: 네이버 API HUB 키가 없어 뉴스를 모으지 못해요 (set-naver.sh)."
grep -q '^SMTP_HOST=.' $ENV_FILE || echo "주의: 메일 발송 설정(SMTP)이 없어 구독 신청을 받거나 레터를 보내지 못해요 (set-mail.sh)."
install -m 644 $APP/deploy/soboru-letter.service /etc/systemd/system/soboru-letter.service
install -m 644 $APP/deploy/soboru-letter.timer /etc/systemd/system/soboru-letter.timer
systemctl daemon-reload
systemctl enable --now soboru-letter.timer
echo "설치했어요. 매일 아침 7시 30분(한국 시각)에 깨어, 관리자 > 소보루 레터에서 고른 요일에만 한 호를 만들어요."
echo "자동 보내기가 꺼져 있으면(기본) 초안만 만들고 운영자가 '보내기'를 누를 때까지 기다려요."
systemctl list-timers soboru-letter.timer --no-pager || true
