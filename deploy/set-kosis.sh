#!/bin/bash
# 통계청 KOSIS 오픈API 인증키를 소보루 서버 설정에 넣고, 실제로 통계를 받아 와 지는지 확인합니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-kosis.sh
#   물어보면 kosis.kr/openapi > 마이페이지 > 인증키 관리(활용신청 현황)에 있는 인증키를 붙여 넣으세요.
#   입력한 글자는 화면에 보이지 않고, 키는 /etc/soboru.env에만 저장돼요(채팅·코드에는 넣지 마세요).
set -euo pipefail
APP=/opt/soboru/app; ENV_FILE=/etc/soboru.env
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
read -r -s -p "KOSIS 인증키: " KEY; echo
KEY="${KEY//[$'\r\n\t ']/}"
[[ -n $KEY ]] || { echo "인증키를 넣어 주세요."; exit 1; }
# 품목별 소비자물가지수 최근 한 달을 받아 봐서 키가 통하는지 확인 (키는 화면에 찍지 않음)
RES=$(curl -s -m 20 "https://kosis.kr/openapi/Param/statisticsParameterData.do?method=getList&apiKey=$KEY&format=json&jsonVD=Y&orgId=101&tblId=DT_1J22003&itmId=ALL&objL1=ALL&prdSe=M&newEstPrdCnt=1" || true)
if grep -q '"C1_NM"' <<<"$RES"; then echo "확인: 통계청에서 소비자물가지수를 받아 왔어요."
else
  echo "주의: KOSIS 응답에서 통계를 찾지 못했어요."
  echo "     응답 앞부분: $(head -c 300 <<<"${RES//$KEY/***}" | tr -d '\n')"
  read -r -p "그래도 저장할까요? (y/N) " YES; [[ $YES == y || $YES == Y ]] || exit 1
fi
TMP=$(mktemp); grep -vE '^KOSIS_API_KEY=' "$ENV_FILE" > "$TMP" || true
printf 'KOSIS_API_KEY=%s\n' "$KEY" >> "$TMP"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru
echo "저장했어요. 이제 생활정보 AI 글이 주제에 맞는 통계청 통계를 찾아 함께 써요."
echo "'외식비'로 찾아지는 통계를 한 번 볼게요..."
runuser -u soboru -- bash -c "set -a; . $ENV_FILE; set +a; cd $APP && /opt/soboru/venv/bin/python -m soboru_writer --kosis 외식비" 2>&1 | head -40 | sed "s/$KEY/***/g" || true
