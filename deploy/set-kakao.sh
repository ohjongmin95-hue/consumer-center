#!/bin/bash
# 제보자 카카오 알림톡을 켭니다. 보내는 업체(솔라피 또는 알리고)를 고르고, 그 업체의 키·채널·템플릿 코드를 소보루 서버 설정에 넣은 뒤 사이트를 다시 시작합니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-kakao.sh
#   하나씩 물어봐요. 비워 두고 엔터를 누르면 지금 값을 그대로 둬요(템플릿 심사가 나중에 끝나면 다시 실행해서 그 코드만 넣으면 돼요).
#   업체별 값은 따로 저장돼요. 두 업체를 다 넣어 두면 다시 실행해서 업체만 바꿔도 돼요.
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
NOW=$(cur MSG_VENDOR); [[ $NOW == aligo ]] && NOW_NAME=알리고 || NOW_NAME=솔라피
read -r -p "어느 업체로 보낼까요? 1) 솔라피  2) 알리고 (지금: $NOW_NAME, 엔터면 그대로): " PICK
case "${PICK:-}" in 1) VENDOR=solapi ;; 2) VENDOR=aligo ;; "") [[ $NOW == aligo ]] && VENDOR=aligo || VENDOR=solapi ;; *) echo "1이나 2를 눌러 주세요."; exit 1 ;; esac
NEW[MSG_VENDOR]=$VENDOR

if [[ $VENDOR == aligo ]]; then
  P=ALIGO_  # 알리고 템플릿 코드는 ALIGO_KAKAO_TPL_... 이름으로 따로 저장
  echo "알리고 > 마이페이지 > API Key 발급 에서 확인해요. 같은 화면에서 서버 IP 211.233.198.1 을 등록해 주세요."
  ask ALIGO_API_KEY "API Key" hide
  ask ALIGO_USER_ID "알리고 아이디"
  echo "알리고 > 카카오톡 > 채널 관리에 보이는 발신프로필 키(senderkey)"
  ask ALIGO_SENDER_KEY "발신프로필 키"
  echo "알리고에 등록한 발신번호 (알리고는 알림톡에도 꼭 있어야 해요, 예: 027497515)"
  ask ALIGO_SENDER "발신번호"
  [[ -n ${NEW[ALIGO_API_KEY]} && -n ${NEW[ALIGO_USER_ID]} && -n ${NEW[ALIGO_SENDER_KEY]} && -n ${NEW[ALIGO_SENDER]} ]] || { echo "API Key·아이디·발신프로필 키·발신번호는 꼭 있어야 해요."; exit 1; }
  echo "심사를 통과한 알림톡 템플릿 코드 (알리고 > 카카오톡 > 템플릿 관리, 아직 없으면 엔터)"
else
  P=
  echo "솔라피 콘솔 > 개발/연동 > API Key 에서 확인해요."
  ask SOLAPI_API_KEY "API Key" hide
  ask SOLAPI_API_SECRET "API Secret" hide
  echo "솔라피 콘솔 > 카카오 > 채널 연동에 보이는 pfId (KA01PF...)"
  ask SOLAPI_PFID "pfId"
  [[ -n ${NEW[SOLAPI_API_KEY]} && -n ${NEW[SOLAPI_API_SECRET]} && -n ${NEW[SOLAPI_PFID]} ]] || { echo "API Key·Secret·pfId는 꼭 있어야 해요."; exit 1; }
  echo "심사를 통과한 알림톡 템플릿 ID (아직 없으면 엔터)"
fi
TPLS="KAKAO_TPL_RECEIVED KAKAO_TPL_STATUS KAKAO_TPL_MESSAGE KAKAO_TPL_COMPANY KAKAO_TPL_SUPPLEMENT KAKAO_TPL_SEEN KAKAO_TPL_ADMIN"
ask ${P}KAKAO_TPL_RECEIVED "① 제보 접수"
ask ${P}KAKAO_TPL_STATUS "② 진행 단계 변경"
ask ${P}KAKAO_TPL_MESSAGE "③ 센터 답변"
ask ${P}KAKAO_TPL_COMPANY "④ 기업 답변"
ask ${P}KAKAO_TPL_SUPPLEMENT "⑤ 보완 요청"
ask ${P}KAKAO_TPL_SEEN "⑥ 기업 확인"
ask ${P}KAKAO_TPL_ADMIN "⑦ 운영자 새 제보 알림 (받는 번호는 set-alert.sh)"
if [[ $VENDOR == solapi ]]; then
  echo "문자로 대신 보낼 발신번호 (솔라피에 등록한 번호, 없으면 엔터)"
  ask SOLAPI_SENDER "발신번호"
fi

# 키가 맞는지 잔액 조회로 확인 (키는 화면에 찍지 않음)
OK=$(V="$VENDOR" K="${NEW[SOLAPI_API_KEY]:-${NEW[ALIGO_API_KEY]:-}}" S="${NEW[SOLAPI_API_SECRET]:-}" U="${NEW[ALIGO_USER_ID]:-}" python3 - <<'PY' || true
import datetime, hashlib, hmac, json, os, secrets, urllib.parse, urllib.request
try:
    if os.environ['V'] == 'aligo':
        data = urllib.parse.urlencode({'key': os.environ['K'], 'user_id': os.environ['U']}).encode()
        with urllib.request.urlopen(urllib.request.Request('https://apis.aligo.in/remain/', data=data), timeout=15) as r: b = json.loads(r.read().decode() or '{}')
        print(('잔액 단문 ' + str(b.get('SMS_CNT', '?')) + '건 분량') if str(b.get('result_code')) == '1' else 'ERR ' + str(b.get('message', ''))[:80])
    else:
        date = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'); salt = secrets.token_hex(16)
        sig = hmac.new(os.environ['S'].encode(), (date + salt).encode(), hashlib.sha256).hexdigest()
        req = urllib.request.Request('https://api.solapi.com/cash/v1/balance', headers={'Authorization': f"HMAC-SHA256 apiKey={os.environ['K']}, date={date}, salt={salt}, signature={sig}"})
        with urllib.request.urlopen(req, timeout=15) as r: b = json.loads(r.read().decode() or '{}'); print('잔액 ' + str(b.get('balance', '?')) + '원')
except Exception as e:
    print('ERR ' + type(e).__name__ + ' ' + str(getattr(e, 'code', '')))
PY
)
[[ $VENDOR == aligo ]] && NAME=알리고 || NAME=솔라피
if [[ $OK == 잔액* ]]; then echo "확인: ${NAME}에 연결됐어요 ($OK)."
else
  echo "주의: ${NAME}에 연결하지 못했어요 ($OK). 키·아이디를 다시 확인해 주세요.${P:+ 알리고는 서버 IP 등록도 확인해 주세요.}"
  read -r -p "그래도 저장할까요? (y/N) " YES; [[ $YES == y || $YES == Y ]] || exit 1
fi
TMP=$(mktemp); grep -vE "^($(IFS='|'; echo "${!NEW[*]}"))=" "$ENV_FILE" > "$TMP" || true
for k in "${!NEW[@]}"; do [[ -n ${NEW[$k]} ]] && printf '%s=%s\n' "$k" "${NEW[$k]}" >> "$TMP"; done
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru
echo "저장했어요. 이제 ${NAME}로 보내요. 템플릿 코드를 넣은 알림부터 제보자 휴대폰으로 카카오톡이 가요."
for k in $TPLS; do
  [[ -n ${NEW[$P$k]} ]] && echo "  켜짐: $k" || echo "  아직: $k (템플릿 심사 뒤 다시 실행해서 넣어 주세요)"
done
[[ -n ${NEW[${P}KAKAO_TPL_ADMIN]} ]] && ! grep -q '^ADMIN_ALERT_PHONE=.' "$ENV_FILE" && echo "참고: 운영자 알림을 받을 번호는 sudo bash /opt/soboru/app/deploy/set-alert.sh 010-0000-0000 으로 넣어 주세요." || true
echo "참고: 개인정보 처리방침의 '처리 위탁'에 ${NAME}가 적혀 있는지 확인해 주세요 (관리자 > 약관 편집)."
