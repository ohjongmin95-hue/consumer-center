#!/bin/bash
# 소보루 레터 사진: 언스플래시(unsplash.com) Access Key를 소보루 서버 설정에 넣습니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-unsplash.sh
#   unsplash.com/oauth/applications 에서 앱을 열고 'Access Key'를 붙여 넣으세요(Secret Key 아님). 입력한 글자는 화면에 보이지 않아요.
set -euo pipefail
ENV_FILE=/etc/soboru.env
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
read -r -s -p "언스플래시 Access Key: " KEY; echo
KEY="${KEY//[$'\r\n\t ']/}"
[[ -n $KEY ]] || { echo "Access Key를 넣어 주세요."; exit 1; }
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Client-ID $KEY" "https://api.unsplash.com/search/photos?query=coffee&per_page=1" || true)
[[ $CODE == 200 ]] && echo "키 확인 완료." || echo "주의: 언스플래시가 $CODE 로 답했어요. Access Key가 맞는지 확인해 주세요. 일단 저장할게요."
TMP=$(mktemp); grep -vE '^UNSPLASH_ACCESS_KEY=' "$ENV_FILE" > "$TMP" || true
printf 'UNSPLASH_ACCESS_KEY=%s\n' "$KEY" >> "$TMP"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru
echo "저장했어요. 다음 호부터 뉴스마다 사진이 붙어요."
