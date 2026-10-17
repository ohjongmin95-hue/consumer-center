#!/bin/bash
# 네이버 API HUB(네이버 클라우드) 인증키를 소보루 사이트 서버 설정에 넣고 다시 시작합니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-naver.sh
#   물어보면 Client ID와 Client Secret을 붙여 넣으세요. 입력한 글자는 화면에 보이지 않고, 키는 /etc/soboru.env에만 저장돼요.
set -euo pipefail
ENV_FILE=/etc/soboru.env
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
read -r -s -p "네이버 API HUB Client ID: " CID; echo
read -r -s -p "네이버 API HUB Client Secret: " SECRET; echo
CID="${CID//[$'\r\n\t ']/}"; SECRET="${SECRET//[$'\r\n\t ']/}"
[[ -n $CID && -n $SECRET ]] || { echo "Client ID와 Client Secret을 모두 넣어 주세요."; exit 1; }
TMP=$(mktemp); grep -vE '^NAVER_HUB_CLIENT_(ID|SECRET)=' "$ENV_FILE" > "$TMP" || true
printf 'NAVER_HUB_CLIENT_ID=%s\nNAVER_HUB_CLIENT_SECRET=%s\n' "$CID" "$SECRET" >> "$TMP"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru
echo "저장했어요. 생활정보 > 통합 검색에서 확인해 보세요."
