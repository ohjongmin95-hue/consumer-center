#!/bin/bash
# 새 제보 알림 메일을 켭니다. 보내는 메일 계정(지메일·네이버)과 받을 주소를 서버 설정에 넣고 사이트를 다시 시작합니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-mail.sh 보내는주소@gmail.com '앱비밀번호' 받을주소1,받을주소2
#   앱 비밀번호: 지메일은 구글 계정 > 보안 > 2단계 인증 > 앱 비밀번호(16자리), 네이버는 메일 환경설정 > POP3/SMTP 사용 후 네이버 비밀번호(또는 애플리케이션 비밀번호)
# 메일이 켜지면 제보 때 이메일을 적은 제보자에게도 접수·진행 메일이 갑니다.
set -euo pipefail
ENV_FILE=/etc/soboru.env
FROM="${1:-}"; PW="${2:-}"; TO="${3:-}"
PW="${PW// /}"; TO="${TO// /}"
if [[ ! $FROM =~ ^[^@[:space:]]+@[^@[:space:]]+$ || -z $PW || ! $TO =~ @ ]]; then
  echo "사용법: sudo bash $0 보내는주소@gmail.com '앱비밀번호' 받을주소1,받을주소2"; exit 1
fi
case "${FROM##*@}" in
  gmail.com) HOST=smtp.gmail.com;; naver.com) HOST=smtp.naver.com;; daum.net|hanmail.net) HOST=smtp.daum.net;;
  *) echo "지메일, 네이버, 다음 메일 주소로 보내 주세요."; exit 1;;
esac
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
TMP=$(mktemp)
grep -vE '^(SMTP_HOST|SMTP_PORT|SMTP_USER|SMTP_PASSWORD|ADMIN_ALERT_EMAIL)=' "$ENV_FILE" > "$TMP" || true
printf 'SMTP_HOST=%s\nSMTP_PORT=465\nSMTP_USER=%s\nSMTP_PASSWORD=%s\nADMIN_ALERT_EMAIL=%s\n' "$HOST" "$FROM" "$PW" "$TO" >> "$TMP"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru
# 소보루 CS가 설치돼 있으면 같은 메일 계정을 거기에도 넣음 (사장님 비밀번호 찾기·알림 메일)
PENV=/etc/soboru-platform.env
if [[ -f $PENV ]]; then
  TMP=$(mktemp)
  grep -vE '^#? ?SMTP_(HOST|PORT|USER|PASSWORD|FROM)=' "$PENV" > "$TMP" || true
  printf 'SMTP_HOST=%s\nSMTP_PORT=465\nSMTP_USER=%s\nSMTP_PASSWORD=%s\n' "$HOST" "$FROM" "$PW" >> "$TMP"
  cat "$TMP" > "$PENV"; rm -f "$TMP"
  systemctl restart soboru-platform 2>/dev/null || true
  echo "소보루 CS에도 같은 메일 계정을 넣었습니다."
fi
echo "저장했습니다. 이제 새 제보가 들어오면 $TO 로 메일이 갑니다."
