#!/bin/bash
# 소보루 레터를 스티비로 보내기: 스티비 API 키를 소보루 서버 설정에 넣습니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-stibee.sh
#   스티비 > 워크스페이스 설정 > API 키에서 새 키를 만들어 붙여 넣으세요(프로 요금제부터). 입력한 글자는 화면에 보이지 않아요.
#   그다음 관리자 > 소보루 레터 > 보내는 곳을 '스티비로'로 바꾸고 주소록 번호·발신자 이메일을 넣으세요.
set -euo pipefail
ENV_FILE=/etc/soboru.env
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
read -r -s -p "스티비 API 키: " KEY; echo
KEY="${KEY//[$'\r\n\t ']/}"
[[ -n $KEY ]] || { echo "API 키를 넣어 주세요."; exit 1; }
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "AccessToken: $KEY" "https://api.stibee.com/v2/emails?limit=1" || true)
[[ $CODE == 200 ]] && echo "키 확인 완료." || echo "주의: 스티비가 $CODE 로 답했어요. 키나 요금제(프로부터)를 확인해 주세요. 일단 저장할게요."
TMP=$(mktemp); grep -vE '^STIBEE_API_KEY=' "$ENV_FILE" > "$TMP" || true
printf 'STIBEE_API_KEY=%s\n' "$KEY" >> "$TMP"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru
echo "저장했어요. 관리자 > 소보루 레터에서 '보내는 곳'을 스티비로 바꾸고 주소록 번호·발신자를 저장한 뒤, '구독자' 칸의 '스티비 주소록으로 옮기기'를 한 번 눌러 주세요."
