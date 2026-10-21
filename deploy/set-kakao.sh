#!/bin/bash
# 제보자 카카오 알림톡(솔라피)을 켭니다. 솔라피 키·채널 pfId·템플릿 ID를 소보루 서버 설정에 넣고 사이트를 다시 시작합니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-kakao.sh
#   하나씩 물어봐요. 비워 두고 엔터를 누르면 지금 값을 그대로 둬요(템플릿 심사가 나중에 끝나면 다시 실행해서 그 ID만 넣으면 돼요).
#   키와 시크릿은 화면에 보이지 않고 /etc/soboru.env에만 저장돼요(채팅·코드에는 넣지 마세요).
#   소보루 CS(/etc/soboru-platform.env)는 건드리지 않아요. 템플릿 문구는 docs/notifications.md
set -euo pipefail
ENV_FILE=/etc/soboru.env
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
cur() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }
declare -A NEW
ask() {  # ask 이름 설명 [hide]
  local v old; old=$(cur "$1")
  if [[ ${3:-} == hide ]]; then read -r -s -p "$2${old:+ (있음, 엔터면 그대로)}: " v; echo
  else read -r -p "$2${old:+ (지금: $old, 엔터면 그대로)}: " v; fi
  v="${v//[$'\r\n\t ']/}"
  NEW[$1]="${v:-$old}"
}
echo "솔라피 콘솔 > 개발/연동 > API Key 에서 확인해요."
ask SOLAPI_API_KEY "API Key" hide
ask SOLAPI_API_SECRET "API Secret" hide
echo "솔라피 콘솔 > 카카오 > 채널 연동에 보이는 pfId (KA01PF...)"
ask SOLAPI_PFID "pfId"
echo "심사를 통과한 알림톡 템플릿 ID (아직 없으면 엔터)"
ask KAKAO_TPL_RECEIVED "① 제보 접수"
ask KAKAO_TPL_STATUS "② 진행 단계 변경"
ask KAKAO_TPL_MESSAGE "③ 센터 답변"
ask KAKAO_TPL_COMPANY "④ 기업 답변"
ask KAKAO_TPL_SUPPLEMENT "⑤ 보완 요청"
ask KAKAO_TPL_SEEN "⑥ 기업 확인"
echo "문자로 대신 보낼 발신번호 (솔라피에 등록한 번호, 없으면 엔터)"
ask SOLAPI_SENDER "발신번호"
[[ -n ${NEW[SOLAPI_API_KEY]} && -n ${NEW[SOLAPI_API_SECRET]} && -n ${NEW[SOLAPI_PFID]} ]] || { echo "API Key·Secret·pfId는 꼭 있어야 해요."; exit 1; }
# 키가 맞는지 솔라피 잔액 조회로 확인 (키는 화면에 찍지 않음)
OK=$(K="${NEW[SOLAPI_API_KEY]}" S="${NEW[SOLAPI_API_SECRET]}" python3 - <<'PY' || true
import datetime, hashlib, hmac, json, os, secrets, urllib.request
date = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'); salt = secrets.token_hex(16)
sig = hmac.new(os.environ['S'].encode(), (date + salt).encode(), hashlib.sha256).hexdigest()
req = urllib.request.Request('https://api.solapi.com/cash/v1/balance', headers={'Authorization': f"HMAC-SHA256 apiKey={os.environ['K']}, date={date}, salt={salt}, signature={sig}"})
try:
    with urllib.request.urlopen(req, timeout=15) as r: b = json.loads(r.read().decode() or '{}'); print('잔액 ' + str(b.get('balance', '?')) + '원')
except Exception as e: print('ERR ' + type(e).__name__ + ' ' + str(getattr(e, 'code', '')))
PY
)
if [[ $OK == 잔액* ]]; then echo "확인: 솔라피에 연결됐어요 ($OK)."
else
  echo "주의: 솔라피에 연결하지 못했어요 ($OK). 키·시크릿을 다시 확인해 주세요."
  read -r -p "그래도 저장할까요? (y/N) " YES; [[ $YES == y || $YES == Y ]] || exit 1
fi
TMP=$(mktemp); grep -vE "^($(IFS='|'; echo "${!NEW[*]}"))=" "$ENV_FILE" > "$TMP" || true
for k in "${!NEW[@]}"; do [[ -n ${NEW[$k]} ]] && printf '%s=%s\n' "$k" "${NEW[$k]}" >> "$TMP"; done
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru
echo "저장했어요. 템플릿 ID를 넣은 알림부터 제보자 휴대폰으로 카카오톡이 가요."
for k in KAKAO_TPL_RECEIVED KAKAO_TPL_STATUS KAKAO_TPL_MESSAGE KAKAO_TPL_COMPANY KAKAO_TPL_SUPPLEMENT KAKAO_TPL_SEEN; do
  [[ -n ${NEW[$k]} ]] && echo "  켜짐: $k" || echo "  아직: $k (템플릿 심사 뒤 다시 실행해서 넣어 주세요)"
done
