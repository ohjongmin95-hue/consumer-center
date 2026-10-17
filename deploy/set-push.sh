#!/bin/bash
# 웹 푸시(앱 알림) VAPID 키를 소보루 사이트 서버 설정에 넣고 다시 시작합니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-push.sh          ← 서버에서 새 키를 만들어 저장 (처음 한 번)
#         sudo bash /opt/soboru/app/deploy/set-push.sh --paste  ← 이미 있는 키를 붙여 넣기 (입력한 글자는 화면에 안 보여요)
#   키를 바꾸면 그동안 알림을 켠 기기는 '푸시 알림 받기'를 다시 눌러야 해요. 키는 /etc/soboru.env에만 저장하고 화면에 보여 주지 않아요.
set -euo pipefail
ENV_FILE=/etc/soboru.env; PY=/opt/soboru/venv/bin/python
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
"$PY" -c 'import pywebpush' 2>/dev/null || { echo "pywebpush가 없습니다. 먼저 update.sh로 requirements.txt를 설치해 주세요."; exit 1; }
if grep -qE '^VAPID_PRIVATE_KEY=.+' "$ENV_FILE" && [[ ${1:-} != --paste ]]; then
  read -r -p "이미 키가 있어요. 새로 만들면 켜 둔 기기마다 다시 켜야 해요. 새로 만들까요? (y/N): " YES
  [[ $YES == y || $YES == Y ]] || { echo "그대로 둘게요."; exit 0; }
fi
if [[ ${1:-} == --paste ]]; then
  read -r -s -p "VAPID 공개 키 (base64url): " PUB; echo
  read -r -s -p "VAPID 비밀 키 (base64url): " PRIV; echo
else
  KEYS=$("$PY" -c '
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
k=ec.generate_private_key(ec.SECP256R1()); b=lambda x:base64.urlsafe_b64encode(x).rstrip(b"=").decode()
print(b(k.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)), b(k.private_numbers().private_value.to_bytes(32,"big")))')
  PUB="${KEYS%% *}"; PRIV="${KEYS##* }"; unset KEYS
fi
PUB="${PUB//[$'\r\n\t ']/}"; PRIV="${PRIV//[$'\r\n\t ']/}"
[[ $PUB =~ ^[A-Za-z0-9_-]{80,100}$ && $PRIV =~ ^[A-Za-z0-9_-]{40,50}$ ]] || { echo "키 모양이 아닙니다. 공개 키는 87자, 비밀 키는 43자 안팎의 base64url 글자예요."; exit 1; }
read -r -p "알림 보내는 곳 연락 이메일 (푸시 서비스가 문제 있을 때 연락, 예: help@consumerjebo.co.kr): " MAIL
MAIL="${MAIL//[$'\r\n\t ']/}"; [[ $MAIL =~ ^[^@]+@[^@]+\.[^@]+$ ]] || { echo "이메일을 확인해 주세요."; exit 1; }
TMP=$(mktemp); grep -vE '^VAPID_(PUBLIC_KEY|PRIVATE_KEY|SUBJECT)=' "$ENV_FILE" > "$TMP" || true
printf 'VAPID_PUBLIC_KEY=%s\nVAPID_PRIVATE_KEY=%s\nVAPID_SUBJECT=mailto:%s\n' "$PUB" "$PRIV" "$MAIL" >> "$TMP"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"; unset PRIV
systemctl restart soboru
echo "저장했어요. 내 정보 > 알림에서 '푸시 알림 받기'를 눌러 확인해 보세요."
