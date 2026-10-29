#!/bin/bash
# 기업 메일 자동 찾기: 공공데이터포털 인증키를 소보루 서버 설정에 넣고, 유명 기업 메일이 찾아지는지 확인합니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-ftc.sh
#   data.go.kr에서 '공정거래위원회_통신판매사업자 등록현황 제공 서비스'와 '…등록상세 제공 서비스' 두 개를 활용신청한 뒤
#   마이페이지 > 개발계정에 있는 일반 인증키(Decoding)를 붙여 넣으세요. 입력한 글자는 화면에 보이지 않아요.
# CSV로 넣기(선택): data.go.kr/data/15083251 에서 지역별 파일을 받아 서버에 올린 뒤
#   sudo bash /opt/soboru/app/deploy/set-ftc.sh 파일1.csv 파일2.csv ...
set -euo pipefail
APP=/opt/soboru/app; ENV_FILE=/etc/soboru.env; PY=/opt/soboru/venv/bin/python
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
run() { systemd-run --wait --pipe -q -p User=soboru -p EnvironmentFile=$ENV_FILE -p WorkingDirectory=$APP "$PY" -m company_mail "$@"; }
if [[ $# -gt 0 ]]; then
  for f in "$@"; do [[ -f $f ]] || { echo "$f 파일이 없어요."; exit 1; }; chmod o+r "$f"; done
  mapfile -t FILES < <(realpath "$@"); run import "${FILES[@]}"; run find 쿠팡; exit 0
fi
read -r -s -p "공공데이터포털 인증키: " KEY; echo
KEY="${KEY//[$'\r\n\t ']/}"
[[ -n $KEY ]] || { echo "인증키를 넣어 주세요."; exit 1; }
TMP=$(mktemp); grep -vE '^FTC_API_KEY=' "$ENV_FILE" > "$TMP" || true
printf 'FTC_API_KEY=%s\n' "$KEY" >> "$TMP"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru
echo "저장했어요. 유명 기업 몇 곳을 찾아볼게요 (활용신청 승인 직후엔 1~2시간 뒤에 될 수 있어요)."
for n in 쿠팡 무신사 컬리; do run find "$n" | head -1; done
