#!/usr/bin/env bash
# 믿고가게(진짜 후기 가게 평판)을 켭니다. (운영자 2026-11-15)
# 사용법: sudo bash /opt/soboru/app/deploy/set-mitgo.sh
# 운영자 비밀번호는 처음 한 번 만들어 화면에 보여 줘요. 다시 실행해도 비밀번호·DB는 그대로예요.
# 도메인 연결은 set-mitgo-domain.sh. 연결 전에는 consumerjebo.co.kr/mitgo 에서 임시로 열려요.
set -euo pipefail
ENV_FILE=/etc/soboru.env; DATA=/var/lib/soboru
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없어요."; exit 1; }
get() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- || true; }
set_kv() { local TMP; TMP=$(mktemp); grep -vE "^$1=" "$ENV_FILE" > "$TMP" || true; printf '%s=%s\n' "$1" "$2" >> "$TMP"; cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"; }
set_kv MITGO_PREVIEW 1
DB="$(get MITGO_DB)"
# 소보루 서비스(soboru 계정)가 쓸 수 있는 곳에 DB를 둠 (11/11 처음 판은 soboru-platform 폴더라 못 열 수 있었음)
if [[ -z $DB || $DB == /var/lib/soboru-platform/* ]]; then
  NEWDB="$DATA/mitgo.sqlite3"
  [[ -n $DB && -f $DB && ! -f $NEWDB ]] && cp -a "$DB" "$NEWDB"
  DB=$NEWDB; set_kv MITGO_DB "$DB"
fi
mkdir -p "$(dirname "$DB")"; touch "$DB"; chown soboru:soboru "$DB"; chmod 640 "$DB"
PW="$(get MITGO_ADMIN_PASSWORD)"; NEW=0
if [[ -z $PW ]]; then PW="$(python3 -c 'import secrets;print(secrets.token_urlsafe(9))')"; set_kv MITGO_ADMIN_PASSWORD "$PW"; NEW=1; fi
systemctl restart soboru
HOST="$(get MITGO_HOST)"; if [[ -n $HOST ]]; then P=/; else P=/mitgo/; fi
for i in 1 2 3 4 5 6 7 8 9 10; do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: ${HOST:-consumerjebo.co.kr}" -H 'X-Forwarded-Proto: https' "http://127.0.0.1:8000$P" || true)
  [[ $CODE == 200 ]] && break; sleep 1
done
if [[ $CODE != 200 ]]; then
  echo "믿고가게이 아직 안 열려요(응답 $CODE). 아래 기록을 보내 주세요."
  journalctl -u soboru -n 30 --no-pager | grep -i -A3 'mitgo\|error\|Traceback' | tail -20
  exit 1
fi
if [[ -n $HOST ]]; then SITE="https://$HOST"; else SITE="https://consumerjebo.co.kr/mitgo (도메인 연결 전 임시 주소)"; fi
echo "다됨: 손님 화면 $SITE"
echo "      운영자 화면 ${SITE%% *}/admin"
if [[ $NEW == 1 ]]; then echo "      운영자 비밀번호: $PW  (이 화면에서만 보여요. 적어 두세요)"; else echo "      운영자 비밀번호는 전에 만든 그대로예요."; fi
