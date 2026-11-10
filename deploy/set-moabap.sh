#!/usr/bin/env bash
# 모아밥(모아배달)을 켭니다. (운영자 2026-11-11)
# 사용법: sudo bash /opt/soboru/app/deploy/set-moabap.sh ['입금 계좌 안내']
#   예:   sudo bash /opt/soboru/app/deploy/set-moabap.sh '국민은행 000000-00-000000 (예금주 홍길동)'
# 운영자 비밀번호는 처음 한 번 만들어 화면에 보여 줘요. 다시 실행해도 비밀번호·DB는 그대로예요.
# 도메인(moabap.com) 연결은 set-moabap-domain.sh. 연결 전에는 consumerjebo.co.kr/moabap 에서 임시로 열려요.
set -euo pipefail
ENV_FILE=/etc/soboru.env; DATA=/var/lib/soboru
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없어요."; exit 1; }
get() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- || true; }
set_kv() { local TMP; TMP=$(mktemp); grep -vE "^$1=" "$ENV_FILE" > "$TMP" || true; printf '%s=%s\n' "$1" "$2" >> "$TMP"; cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"; }
set_kv MOABAP_PREVIEW 1
DB="$(get MOABAP_DB)"
# 소보루 서비스(soboru 계정)가 쓸 수 있는 곳에 DB를 둠 (11/11 처음 판은 soboru-platform 폴더라 못 열 수 있었음)
if [[ -z $DB || $DB == /var/lib/soboru-platform/* ]]; then
  NEWDB="$DATA/moabap.sqlite3"
  [[ -n $DB && -f $DB && ! -f $NEWDB ]] && cp -a "$DB" "$NEWDB"
  DB=$NEWDB; set_kv MOABAP_DB "$DB"
fi
mkdir -p "$(dirname "$DB")"; touch "$DB"; chown soboru:soboru "$DB"; chmod 640 "$DB"
PW="$(get MOABAP_ADMIN_PASSWORD)"; NEW=0
if [[ -z $PW ]]; then PW="$(python3 -c 'import secrets;print(secrets.token_urlsafe(9))')"; set_kv MOABAP_ADMIN_PASSWORD "$PW"; NEW=1; fi
[[ -n ${1:-} ]] && set_kv MOABAP_BANK "$1"
systemctl restart soboru
HOST="$(get MOABAP_HOST)"; if [[ -n $HOST ]]; then P=/; else P=/moabap/; fi
for i in 1 2 3 4 5 6 7 8 9 10; do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: ${HOST:-consumerjebo.co.kr}" -H 'X-Forwarded-Proto: https' "http://127.0.0.1:8000$P" || true)
  [[ $CODE == 200 ]] && break; sleep 1
done
if [[ $CODE != 200 ]]; then
  echo "모아밥이 아직 안 열려요(응답 $CODE). 아래 기록을 보내 주세요."
  journalctl -u soboru -n 30 --no-pager | grep -i -A3 'moabap\|error\|Traceback' | tail -20
  exit 1
fi
if [[ -n $HOST ]]; then SITE="https://$HOST"; else SITE="https://consumerjebo.co.kr/moabap (moabap.com 연결 전 임시 주소)"; fi
echo "다됨: 손님 화면 $SITE"
echo "      운영자 화면 ${SITE%% *}/admin"
if [[ $NEW == 1 ]]; then echo "      운영자 비밀번호: $PW  (이 화면에서만 보여요. 적어 두세요)"; else echo "      운영자 비밀번호는 전에 만든 그대로예요."; fi
