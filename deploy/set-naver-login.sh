#!/bin/bash
# 네이버 로그인(네이버 개발자센터 '네이버 로그인' API) 키를 넣고 네이버 로그인을 켭니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-naver-login.sh
#   물어보면 Client ID와 Client Secret을 붙여 넣으세요. 입력한 글자는 화면에 보이지 않고, 키는 /etc/soboru.env에만 저장돼요.
#   끄기: sudo bash /opt/soboru/app/deploy/set-naver-login.sh off
set -euo pipefail
ENV_FILE=/etc/soboru.env
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
TMP=$(mktemp)
if [[ ${1:-} == off ]]; then
  grep -vE '^ENABLE_NAVER_LOGIN=' "$ENV_FILE" > "$TMP" || true
  echo 'ENABLE_NAVER_LOGIN=0' >> "$TMP"; cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
  systemctl restart soboru; echo "네이버 로그인을 껐어요."; exit 0
fi
read -r -s -p "네이버 로그인 Client ID: " CID; echo
read -r -s -p "네이버 로그인 Client Secret: " SECRET; echo
CID="${CID//[$'\r\n\t ']/}"; SECRET="${SECRET//[$'\r\n\t ']/}"
[[ -n $CID && -n $SECRET ]] || { echo "Client ID와 Client Secret을 모두 넣어 주세요."; rm -f "$TMP"; exit 1; }
grep -vE '^(NAVER_CLIENT_ID|NAVER_CLIENT_SECRET|ENABLE_NAVER_LOGIN)=' "$ENV_FILE" > "$TMP" || true
printf 'NAVER_CLIENT_ID=%s\nNAVER_CLIENT_SECRET=%s\nENABLE_NAVER_LOGIN=1\n' "$CID" "$SECRET" >> "$TMP"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru
echo "저장했어요. 로그인 화면에 '네이버로 시작하기'가 보이는지 확인해 보세요."
