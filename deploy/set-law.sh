#!/bin/bash
# 법제처 국가법령정보 Open API 인증키(OC)를 소보루 서버 설정에 넣고, 실제로 법령을 받아 와 지는지 확인합니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-law.sh
#   물어보면 open.law.go.kr 마이페이지 > API인증키관리에 있는 인증키(OC)를 붙여 넣으세요.
#   입력한 글자는 화면에 보이지 않고, 키는 /etc/soboru.env에만 저장돼요(채팅·코드에는 넣지 마세요).
set -euo pipefail
ENV_FILE=/etc/soboru.env
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
read -r -s -p "법제처 API 인증키(OC): " OC; echo
OC="${OC//[$'\r\n\t ']/}"
[[ -n $OC ]] || { echo "인증키를 넣어 주세요."; exit 1; }
# 소비자기본법을 한 번 찾아 봐서 키가 통하는지 확인 (키는 화면에 찍지 않음)
RES=''
for BASE in https://www.law.go.kr http://www.law.go.kr; do  # 법제처 안내 주소는 http라 둘 다 시도
  RES=$(curl -s -m 20 -G "$BASE/DRF/lawSearch.do" --data-urlencode "OC=$OC" --data-urlencode 'target=law' --data-urlencode 'type=XML' --data-urlencode 'query=소비자기본법' || true)
  grep -q '<totalCnt>[1-9]' <<<"$RES" && break
done
if grep -q '<totalCnt>[1-9]' <<<"$RES"; then echo "확인: 법제처에서 소비자기본법을 찾았어요."
else
  echo "주의: 법제처 응답에서 법령을 찾지 못했어요."
  echo "     이 서버의 바깥 IP: $(curl -s -m 10 https://api.ipify.org || echo 확인 실패)"
  echo "     응답 앞부분: $(head -c 300 <<<"${RES//$OC/***}" | tr -d '\n')"
  read -r -p "그래도 저장할까요? (y/N) " YES; [[ $YES == y || $YES == Y ]] || exit 1
fi
TMP=$(mktemp); grep -vE '^LAW_OC=' "$ENV_FILE" > "$TMP" || true
printf 'LAW_OC=%s\n' "$OC" >> "$TMP"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru
echo "저장했어요. AI 소비자 상담이 법령 원문과 시행일을 법제처에서 받아 오게 돼요."
