#!/bin/bash
# 소보루 CS 사장님 알림톡(솔라피)을 켭니다. AI가 사장님 결정이 필요한 문의를 넘길 때 휴대폰 카카오톡으로 알려요.
# 사용법: sudo bash /opt/soboru/app/deploy/set-kakao-cs.sh
#   솔라피 키·pfId는 소보루(set-kakao.sh)에 넣은 값을 그대로 쓸 수 있어요(엔터). 템플릿 심사가 나중에 끝나면 다시 실행해서 그 ID만 넣으면 돼요.
#   키와 시크릿은 화면에 보이지 않고 /etc/soboru-platform.env에만 저장돼요(채팅·코드에는 넣지 마세요).
#   고객에게 가는 알림톡(CS_KAKAO_TPL_REPLY)은 켜지 않아요. 템플릿 문구는 docs/platform.md
#   사장님마다 소보루 CS 설정 > 알림에서 '알림톡'을 켜고 휴대폰 번호를 넣어야 받아요.
set -euo pipefail
ENV_FILE=/etc/soboru-platform.env
SITE_ENV=/etc/soboru.env
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 platform-setup.sh로 설치해 주세요."; exit 1; }
cur() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }
site() { [[ -f $SITE_ENV ]] && grep -E "^$1=" "$SITE_ENV" | tail -1 | cut -d= -f2- || true; }
declare -A NEW
ask() {  # ask 이름 설명 [hide]  — 비우면 지금 값, 없으면 소보루에 넣은 값
  local v old from=''; old=$(cur "$1")
  if [[ -z $old && $1 == SOLAPI_* ]]; then old=$(site "$1"); [[ -n $old ]] && from=' (소보루와 같은 값 있음, 엔터면 그대로)'; fi
  [[ -n $old && -z $from ]] && from=$([[ ${3:-} == hide ]] && echo ' (있음, 엔터면 그대로)' || echo " (지금: $old, 엔터면 그대로)")
  if [[ ${3:-} == hide ]]; then read -r -s -p "$2$from: " v; echo
  else read -r -p "$2$from: " v; fi
  v="${v//[$'\r\n\t ']/}"
  NEW[$1]="${v:-$old}"
}
echo "솔라피 콘솔 > 개발/연동 > API Key (소보루와 같은 키를 쓰면 엔터)"
ask SOLAPI_API_KEY "API Key" hide
ask SOLAPI_API_SECRET "API Secret" hide
echo "솔라피 콘솔 > 카카오 > 채널/그룹에 보이는 pfId (KA01PF...)"
ask SOLAPI_PFID "pfId"
echo "심사를 통과한 '승인할 문의' 알림톡 템플릿 ID (아직 없으면 엔터)"
ask BIZ_KAKAO_TPL_NEW "승인할 문의"
[[ -n ${NEW[SOLAPI_API_KEY]} && -n ${NEW[SOLAPI_API_SECRET]} && -n ${NEW[SOLAPI_PFID]} ]] || { echo "API Key·Secret·pfId는 꼭 있어야 해요."; exit 1; }
[[ ${NEW[SOLAPI_PFID]} == KA01PF* ]] || { echo "pfId는 KA01PF로 시작해요. 다시 확인해 주세요."; exit 1; }
[[ -z ${NEW[BIZ_KAKAO_TPL_NEW]} || ${NEW[BIZ_KAKAO_TPL_NEW]} =~ ^[A-Za-z0-9_-]+$ ]] || { echo "템플릿 ID에 이상한 글자가 있어요. 솔라피 템플릿 목록의 ID만 넣어 주세요."; exit 1; }
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
chown root:soboru "$ENV_FILE"; chmod 640 "$ENV_FILE"
systemctl restart soboru-platform
echo "저장했어요."
if [[ -n ${NEW[BIZ_KAKAO_TPL_NEW]} ]]; then echo "  켜짐: 승인할 문의 알림톡. 사장님은 소보루 CS 설정 > 알림에서 '알림톡'을 켜고 휴대폰 번호를 넣어 주세요."
else echo "  아직: BIZ_KAKAO_TPL_NEW (템플릿 심사 뒤 다시 실행해서 넣어 주세요)"; fi
