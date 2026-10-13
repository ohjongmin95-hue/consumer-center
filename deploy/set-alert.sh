#!/bin/bash
# 새 제보 알림(카카오톡·문자)을 받을 운영자 휴대폰 번호를 정하고 사이트를 다시 시작합니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-alert.sh 010-1234-5678   (여러 번호는 쉼표로: 010-1111-2222,010-3333-4444)
set -euo pipefail
ENV_FILE=/etc/soboru.env
VALUE="${1:-}"
VALUE="${VALUE//[^0-9,]/}"
[[ $VALUE =~ ^01[0-9]{8,9}(,01[0-9]{8,9})*$ ]] || { echo "사용법: sudo bash $0 010-1234-5678"; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
TMP=$(mktemp); grep -v "^ADMIN_ALERT_PHONE=" "$ENV_FILE" > "$TMP" || true; printf 'ADMIN_ALERT_PHONE=%s\n' "$VALUE" >> "$TMP"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru
echo "저장했습니다: ADMIN_ALERT_PHONE=$VALUE"
grep -q '^KAKAO_TPL_ADMIN=.' "$ENV_FILE" || echo "참고: 카카오톡으로 받으려면 솔라피 설정과 운영자 알림 템플릿(KAKAO_TPL_ADMIN)이 더 필요합니다."
