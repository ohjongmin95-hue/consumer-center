#!/bin/bash
# Apple로 로그인(Sign in with Apple) 키를 소보루 사이트 서버 설정에 넣고 다시 시작합니다.
# 준비 (Apple Developer > Certificates, IDs & Profiles):
#   1) Identifiers에서 App ID에 'Sign in with Apple'을 켜고, Services ID(예: kr.co.consumerjebo.soboru.web)를 만들어
#      Domains: consumerjebo.co.kr / Return URLs: https://consumerjebo.co.kr/auth/apple/callback 을 넣기
#   2) Keys에서 'Sign in with Apple' 키를 만들어 .p8 파일을 받고 Key ID를 적어 두기 (.p8은 한 번만 받을 수 있어요)
#   3) .p8 파일을 서버로 올리기:  scp AuthKey_XXXXXXXXXX.p8 서버:/tmp/
# 사용법: sudo bash /opt/soboru/app/deploy/set-apple.sh /tmp/AuthKey_XXXXXXXXXX.p8
#   Services ID·Team ID·Key ID를 물어봐요. 입력한 글자는 화면에 보이지 않아요.
#   .p8은 /etc/soboru-apple.p8(관리자와 사이트만 읽기)로 옮기고 올린 파일은 지워요. 키 내용은 화면이나 기록에 남기지 않아요.
set -euo pipefail
ENV_FILE=/etc/soboru.env; KEY_FILE=/etc/soboru-apple.p8
SRC="${1:-}"
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
[[ -n $SRC && -f $SRC ]] || { echo "사용법: sudo bash $0 /tmp/AuthKey_XXXXXXXXXX.p8"; exit 1; }
grep -q -- '-----BEGIN PRIVATE KEY-----' "$SRC" || { echo "Apple에서 받은 .p8 키 파일이 아닙니다."; exit 1; }
read -r -s -p "Services ID (예: kr.co.consumerjebo.soboru.web): " SID; echo
read -r -s -p "Team ID (10자리): " TEAM; echo
read -r -s -p "Key ID (10자리): " KID; echo
SID="${SID//[$'\r\n\t ']/}"; TEAM="${TEAM//[$'\r\n\t ']/}"; KID="${KID//[$'\r\n\t ']/}"
[[ $SID =~ ^[A-Za-z0-9.-]+$ ]] || { echo "Services ID를 확인해 주세요."; exit 1; }
[[ ${TEAM^^} =~ ^[A-Z0-9]{10}$ && ${KID^^} =~ ^[A-Z0-9]{10}$ ]] || { echo "Team ID와 Key ID는 영문 대문자·숫자 10자리입니다."; exit 1; }
install -m 640 -o root -g soboru "$SRC" "$KEY_FILE"; shred -u "$SRC" 2>/dev/null || rm -f "$SRC"
/opt/soboru/venv/bin/python -c 'import sys;from cryptography.hazmat.primitives.serialization import load_pem_private_key as l;l(open(sys.argv[1],"rb").read(),None)' "$KEY_FILE" \
  || { echo "키를 읽지 못했습니다. requirements.txt 설치(update.sh)를 먼저 해 주세요."; exit 1; }
TMP=$(mktemp); grep -vE '^APPLE_(SERVICE_ID|TEAM_ID|KEY_ID|PRIVATE_KEY)=' "$ENV_FILE" > "$TMP" || true
printf 'APPLE_SERVICE_ID=%s\nAPPLE_TEAM_ID=%s\nAPPLE_KEY_ID=%s\nAPPLE_PRIVATE_KEY=%s\n' "$SID" "${TEAM^^}" "${KID^^}" "$KEY_FILE" >> "$TMP"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru
echo "저장했어요. 로그인 화면에 'Apple로 계속하기' 버튼이 보이는지 확인해 주세요."
