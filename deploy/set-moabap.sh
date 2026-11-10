#!/usr/bin/env bash
# 모아밥(모아배달)을 켭니다. (운영자 2026-11-11)
# 도메인 연결 전에는 https://consumerjebo.co.kr/moabap 에서 열리고, 앱도 이 주소로 시작해요.
# 사용법: sudo bash /opt/soboru/app/deploy/set-moabap.sh ['입금 계좌 안내']
#   예:   sudo bash /opt/soboru/app/deploy/set-moabap.sh '국민은행 000000-00-000000 (예금주 홍길동)'
# 운영자 비밀번호는 처음 한 번 만들어 화면에 보여 줘요. 다시 실행해도 비밀번호·DB는 그대로예요.
set -euo pipefail
ENV_FILE=/etc/soboru.env; DATA=/var/lib/soboru-platform
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없어요."; exit 1; }
get() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- || true; }
set_kv() { local TMP; TMP=$(mktemp); grep -vE "^$1=" "$ENV_FILE" > "$TMP" || true; printf '%s=%s\n' "$1" "$2" >> "$TMP"; cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"; }
mkdir -p "$DATA"
set_kv MOABAP_PREVIEW 1
[[ -n "$(get MOABAP_DB)" ]] || set_kv MOABAP_DB "$DATA/moabap.sqlite3"
PW="$(get MOABAP_ADMIN_PASSWORD)"; NEW=0
if [[ -z $PW ]]; then PW="$(python3 -c 'import secrets;print(secrets.token_urlsafe(9))')"; set_kv MOABAP_ADMIN_PASSWORD "$PW"; NEW=1; fi
[[ -n ${1:-} ]] && set_kv MOABAP_BANK "$1"
systemctl restart soboru
sleep 2
echo "  https://consumerjebo.co.kr/moabap/ → $(curl -s -o /dev/null -w '%{http_code}' -H 'Host: consumerjebo.co.kr' http://127.0.0.1:8000/moabap/)"
echo "다됨: 손님 화면 https://consumerjebo.co.kr/moabap/"
echo "      운영자 화면 https://consumerjebo.co.kr/moabap/admin"
if [[ $NEW == 1 ]]; then echo "      운영자 비밀번호: $PW  (이 화면에서만 보여요. 적어 두세요)"; else echo "      운영자 비밀번호는 전에 만든 그대로예요."; fi
