#!/bin/bash
# 소보루 AI 분석 기사: 아침·오후·저녁 기사를 쓰는 예약 작업(systemd 타이머)을 설치하거나 끕니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-writer.sh          설치(켜기) 후 지금 한 번 시험으로 돌림
#         sudo bash /opt/soboru/app/deploy/set-writer.sh off      예약 작업 끄기
#         sudo bash /opt/soboru/app/deploy/set-writer.sh dry      AI·저장 없이 자료만 모아 보기 (키 연결 확인용)
# 필요한 것: /etc/soboru.env 의 OPENAI_API_KEY. 있으면 더 쓰는 것: NAVER_HUB_CLIENT_ID·SECRET(set-naver.sh), LAW_OC(set-law.sh)
set -euo pipefail
APP=/opt/soboru/app; ENV_FILE=/etc/soboru.env
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
case "${1:-on}" in
  off) systemctl disable --now soboru-writer.timer 2>/dev/null || true; echo "AI 기사 자동 쓰기를 껐어요."; exit 0 ;;
  dry) runuser -u soboru -- bash -c "set -a; . $ENV_FILE; set +a; cd $APP && exec /opt/soboru/venv/bin/python -m soboru_writer --dry"; exit 0 ;;
esac
grep -q '^OPENAI_API_KEY=.' $ENV_FILE || echo "주의: OPENAI_API_KEY가 없어 AI 기사를 쓰지 못해요. 넣은 뒤 다시 실행해 주세요."
grep -q '^NAVER_HUB_CLIENT_ID=.' $ENV_FILE || echo "참고: 네이버 API HUB 키가 없어 검색 추이·쇼핑·뉴스 기사는 건너뛰어요 (set-naver.sh)."
grep -q '^LAW_OC=.' $ENV_FILE || echo "참고: 법제처 인증키가 없어 '법 바뀐 것' 기사는 건너뛰어요 (set-law.sh)."
install -m 644 $APP/deploy/soboru-writer.service /etc/systemd/system/soboru-writer.service
install -m 644 $APP/deploy/soboru-writer.timer /etc/systemd/system/soboru-writer.timer
systemctl daemon-reload
systemctl enable --now soboru-writer.timer
echo "설치했어요. 아침 7시·오후 1시·저녁 7시쯤(한국 시각) 기사를 몇 편씩 써요 (관리자에서 개수를 바꿀 수 있어요)."
echo "지금 한 번 돌려 볼게요 (몇 분 걸려요)..."
systemctl start soboru-writer.service || true
journalctl -u soboru-writer -n 15 --no-pager -o cat | grep -v -i -E 'key|token|password|secret' || true
echo "관리자 > 생활정보 글 > AI 기사 만들기에서 초안과 기록을 볼 수 있어요."
