#!/bin/bash
# 안드로이드 앱(TWA)·아이폰 앱이 소보루 사이트 주인임을 확인하는 값을 서버 설정에 넣고 다시 시작합니다.
#   /.well-known/assetlinks.json            ← ANDROID_PACKAGE, ANDROID_SHA256 (안드로이드)
#   /.well-known/apple-app-site-association ← APPLE_TEAM_ID, IOS_BUNDLE_ID (아이폰, 나중에)
# 사용법: sudo bash /opt/soboru/app/deploy/set-app.sh
#   SHA-256 지문은 Play Console > 앱 무결성 > 앱 서명에 있는 'SHA-256 인증서 지문'을 붙여 넣으세요(여러 개면 쉼표로).
#   비밀 값은 아니지만 다른 설정 스크립트처럼 /etc/soboru.env에만 저장하고, 비워 두면 지금 값을 그대로 둡니다.
set -euo pipefail
ENV_FILE=/etc/soboru.env
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
cur() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }
read -r -p "안드로이드 패키지 이름 (지금: $(cur ANDROID_PACKAGE), 비어 있으면 kr.co.consumerjebo.soboru, 그대로면 엔터): " PKG
read -r -p "Play 앱 서명 SHA-256 지문 (AA:BB:… 32쌍, 여러 개면 쉼표, 그대로면 엔터): " FPS
read -r -p "Apple Team ID (10자리, 아이폰 앱이 없으면 엔터): " TEAM
read -r -p "iOS 번들 ID (기본 kr.co.consumerjebo.soboru, 그대로면 엔터): " BUNDLE
PKG="${PKG//[$'\r\n\t ']/}"; FPS="${FPS//[$'\r\n\t ']/}"; TEAM="${TEAM//[$'\r\n\t ']/}"; BUNDLE="${BUNDLE//[$'\r\n\t ']/}"
FPS="${FPS^^}"; TEAM="${TEAM^^}"
[[ -z $PKG || $PKG =~ ^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$ ]] || { echo "패키지 이름 모양이 아닙니다 (예: kr.co.consumerjebo.soboru)."; exit 1; }
[[ -z $BUNDLE || $BUNDLE =~ ^[a-zA-Z0-9.-]+$ ]] || { echo "번들 ID 모양이 아닙니다."; exit 1; }
[[ -z $TEAM || $TEAM =~ ^[A-Z0-9]{10}$ ]] || { echo "Team ID는 영문 대문자·숫자 10자리입니다."; exit 1; }
if [[ -n $FPS ]]; then
  IFS=',' read -ra LIST <<< "$FPS"
  for f in "${LIST[@]}"; do [[ $f =~ ^([0-9A-F]{2}:){31}[0-9A-F]{2}$ ]] || { echo "SHA-256 지문 모양이 아닙니다: AA:BB:…(32쌍)"; exit 1; }; done
fi
[[ -n $PKG$FPS$TEAM$BUNDLE ]] || { echo "바꾼 값이 없습니다."; exit 0; }
TMP=$(mktemp); cp "$ENV_FILE" "$TMP"
put() { grep -vE "^$1=" "$TMP" > "$TMP.n" || true; printf '%s=%s\n' "$1" "$2" >> "$TMP.n"; mv "$TMP.n" "$TMP"; }
[[ -n $PKG ]] && put ANDROID_PACKAGE "$PKG"
[[ -n $FPS ]] && put ANDROID_SHA256 "$FPS"
[[ -n $TEAM ]] && put APPLE_TEAM_ID "$TEAM"
[[ -n $BUNDLE ]] && put IOS_BUNDLE_ID "$BUNDLE"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru
echo "저장했어요. 확인: curl -s https://consumerjebo.co.kr/.well-known/assetlinks.json"
