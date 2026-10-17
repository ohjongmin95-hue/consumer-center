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
# 법제처 주소 형식 몇 가지를 차례로 시도 (http·https, 주소에 바로 붙이기, 검색어 없이 목록만)
Q='%EC%86%8C%EB%B9%84%EC%9E%90%EA%B8%B0%EB%B3%B8%EB%B2%95'  # 소비자기본법
RES=''; N=0
for URL in "http://www.law.go.kr/DRF/lawSearch.do?OC=$OC&target=law&type=XML&query=$Q" \
           "https://www.law.go.kr/DRF/lawSearch.do?OC=$OC&target=law&type=XML&query=$Q" \
           "http://www.law.go.kr/DRF/lawSearch.do?OC=$OC&target=law&type=XML" \
           "https://www.law.go.kr/DRF/lawSearch.do?OC=$OC&target=law&type=XML"; do
  N=$((N+1))
  RES=$(curl -s -L -m 20 -A 'Mozilla/5.0 soboru' "$URL" || true)
  if grep -q '<totalCnt>[1-9]' <<<"$RES"; then echo "  방법 $N: 성공"; break; fi
  echo "  방법 $N: $(grep -oE '<(result|msg)>[^<]*' <<<"$RES" | sed 's/<[a-z]*>//' | tr '\n' ' ' | head -c 120)"
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
