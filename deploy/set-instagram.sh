#!/bin/bash
# 인스타그램 DM 받기를 켭니다. 메타 개발자 앱의 Instagram 앱 ID와 시크릿을 넣으면, 웹훅 확인 토큰을 만들어 함께 저장하고 소보루 CS를 다시 시작합니다.
# 앱 ID·시크릿 위치: developers.facebook.com > 내 앱 > Instagram > API setup with Instagram business login
# 사용법: sudo bash /opt/soboru/app/deploy/set-instagram.sh   (앱 ID와 시크릿은 실행하면 물어봅니다. 시크릿은 화면에 보이지 않아요)
set -euo pipefail
ENV_FILE=/etc/soboru-platform.env
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 platform-setup.sh로 설치해 주세요."; exit 1; }
read -rp "Instagram 앱 ID: " APP_ID; APP_ID="${APP_ID// /}"
read -rsp "Instagram 앱 시크릿 (입력해도 화면에 안 보여요): " APP_SECRET; echo; APP_SECRET="${APP_SECRET// /}"
[[ $APP_ID =~ ^[0-9]{5,30}$ ]] || { echo "앱 ID는 숫자로만 되어 있어요. 다시 확인해 주세요."; exit 1; }
[[ $APP_SECRET =~ ^[A-Za-z0-9]{16,64}$ ]] || { echo "앱 시크릿 모양이 맞지 않아요. 다시 확인해 주세요."; exit 1; }
VERIFY=$(grep -E '^IG_VERIFY_TOKEN=.' "$ENV_FILE" | head -1 | cut -d= -f2- || true)
[[ -n $VERIFY ]] || VERIFY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')
TMP=$(mktemp); grep -vE '^(IG_APP_ID|IG_APP_SECRET|IG_VERIFY_TOKEN)=' "$ENV_FILE" > "$TMP" || true
printf 'IG_APP_ID=%s\nIG_APP_SECRET=%s\nIG_VERIFY_TOKEN=%s\n' "$APP_ID" "$APP_SECRET" "$VERIFY" >> "$TMP"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru-platform
BIZ=$(grep -E '^BUSINESS_HOST=.' "$ENV_FILE" | head -1 | cut -d= -f2- || true)
echo
echo "저장했어요. 메타 개발자 화면의 '웹훅 구성'에 아래 두 값을 넣고 확인 및 저장을 누르세요."
echo "  콜백 URL : https://${BIZ:-biz.soboru.co.kr}/hook/instagram"
echo "  확인 토큰: $VERIFY"
echo "그다음 웹훅 필드에서 messages 를 구독(Subscribe)으로 켜 주세요."
