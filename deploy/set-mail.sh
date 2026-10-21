#!/bin/bash
# 새 제보 알림 메일을 켭니다. 보내는 메일 계정(지메일·네이버)과 받을 주소를 서버 설정에 넣고 사이트를 다시 시작합니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-mail.sh 보내는주소@gmail.com 받을주소1,받을주소2
#   앱 비밀번호는 실행하면 화면에 안 보이게 물어봄 (명령어·기록에 남지 않게). 예전처럼 둘째 칸에 넣어도 됨.
#   소보루 CS(/etc/soboru-platform.env)는 따로 설정하므로 건드리지 않음. 같은 계정을 넣으려면 맨 끝에 --cs
#   회사 주소(구글 워크스페이스): sudo bash .../set-mail.sh letter@consumerjebo.co.kr 받을주소
#   다른 회사 메일: sudo MAIL_HOST=smtp.example.com bash .../set-mail.sh ...
#   앱 비밀번호: 지메일은 구글 계정 > 보안 > 2단계 인증 > 앱 비밀번호(16자리), 네이버는 메일 환경설정 > POP3/SMTP 사용 후 네이버 비밀번호(또는 애플리케이션 비밀번호)
# 메일이 켜지면 제보 때 이메일을 적은 제보자에게도 접수·진행 메일이 갑니다.
set -euo pipefail
ENV_FILE=/etc/soboru.env
CS=0; ARGS=()
for a in "$@"; do [[ $a == --cs ]] && CS=1 || ARGS+=("$a"); done
FROM="${ARGS[0]:-}"
if [[ ${#ARGS[@]} -ge 3 ]]; then PW="${ARGS[1]}"; TO="${ARGS[2]}"; else PW=''; TO="${ARGS[1]:-}"; fi
TO="${TO// /}"
if [[ ! $FROM =~ ^[^@[:space:]]+@[^@[:space:]]+$ || ! $TO =~ @ ]]; then
  echo "사용법: sudo bash $0 보내는주소@gmail.com 받을주소1,받을주소2"; exit 1
fi
if [[ -z $PW ]]; then read -rsp "$FROM 의 앱 비밀번호 (입력해도 화면에 안 보여요): " PW; echo; fi
PW="${PW// /}"
[[ -n $PW ]] || { echo "비밀번호가 비어 있어요."; exit 1; }
case "${FROM##*@}" in
  gmail.com) HOST=smtp.gmail.com;; naver.com) HOST=smtp.naver.com;; daum.net|hanmail.net) HOST=smtp.daum.net;;
  *) HOST="${MAIL_HOST:-smtp.gmail.com}"  # 회사 주소(@consumerjebo.co.kr 등)는 구글 워크스페이스로 봄. 하이웍스 등은 MAIL_HOST=smtps.hiworks.com 처럼 앞에 붙여 실행
     echo "회사 메일 주소로 보고 $HOST 로 보냅니다.";;
esac
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
TMP=$(mktemp)
grep -vE '^(SMTP_HOST|SMTP_PORT|SMTP_USER|SMTP_PASSWORD|ADMIN_ALERT_EMAIL)=' "$ENV_FILE" > "$TMP" || true
printf 'SMTP_HOST=%s\nSMTP_PORT=465\nSMTP_USER=%s\nSMTP_PASSWORD=%s\nADMIN_ALERT_EMAIL=%s\n' "$HOST" "$FROM" "$PW" "$TO" >> "$TMP"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru
# 소보루 CS가 설치돼 있으면 같은 메일 계정을 거기에도 넣음 (사장님 비밀번호 찾기·알림 메일)
PENV=/etc/soboru-platform.env
if [[ $CS == 1 && -f $PENV ]]; then
  TMP=$(mktemp)
  grep -vE '^#? ?SMTP_(HOST|PORT|USER|PASSWORD|FROM)=' "$PENV" > "$TMP" || true
  printf 'SMTP_HOST=%s\nSMTP_PORT=465\nSMTP_USER=%s\nSMTP_PASSWORD=%s\n' "$HOST" "$FROM" "$PW" >> "$TMP"
  cat "$TMP" > "$PENV"; rm -f "$TMP"
  systemctl restart soboru-platform 2>/dev/null || true
  echo "소보루 CS에도 같은 메일 계정을 넣었습니다."
fi
echo "저장했습니다. 이제 새 제보가 들어오면 $TO 로 메일이 갑니다."
echo "기업 자동 전달 메일과 제보자 진행 알림 메일도 이 계정으로 나갑니다."
