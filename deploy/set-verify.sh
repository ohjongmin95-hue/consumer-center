#!/bin/bash
# 검색 사이트 소유확인 코드를 소보루 CS 서버 설정에 넣고 다시 시작합니다.
# 사용법: sudo bash /opt/soboru/app/deploy/set-verify.sh 이름 '코드'
#   이름: naver-biz, google-biz, daum-biz (사장님 사이트) / naver-cs, google-cs, daum-cs (고객 사이트)
#   코드: 사이트가 준 코드만 넣어도 되고, <meta ...> 태그를 통째로 붙여 넣어도 됩니다.
set -euo pipefail
ENV_FILE=/etc/soboru-platform.env
case "${1:-}" in
  naver-biz) KEY=NAVER_SITE_VERIFICATION_BIZ;; google-biz) KEY=GOOGLE_SITE_VERIFICATION_BIZ;; daum-biz) KEY=DAUM_WEBMASTER_BIZ;;
  naver-cs) KEY=NAVER_SITE_VERIFICATION;; google-cs) KEY=GOOGLE_SITE_VERIFICATION;; daum-cs) KEY=DAUM_WEBMASTER;;
  *) echo "사용법: sudo bash $0 naver-biz '코드'  (이름: naver-biz google-biz daum-biz naver-cs google-cs daum-cs)"; exit 1;;
esac
VALUE="${2:-}"
[[ -n $VALUE ]] || { echo "코드를 따옴표로 감싸 함께 적어 주세요."; exit 1; }
# <meta ... content="코드"> 를 통째로 붙여 넣었으면 content 값만 꺼냄
if [[ $VALUE =~ content=[\"\']([^\"\']+) ]]; then VALUE="${BASH_REMATCH[1]}"; fi
VALUE="${VALUE//$'\r'/}"
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 platform-setup.sh로 설치해 주세요."; exit 1; }
TMP=$(mktemp); grep -v "^$KEY=" "$ENV_FILE" > "$TMP" || true; printf '%s=%s\n' "$KEY" "$VALUE" >> "$TMP"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru-platform
echo "저장했습니다: $KEY=$VALUE"
