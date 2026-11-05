#!/bin/bash
# 자동으로 만든 카드뉴스·릴스를 서버 '만든 것 보관함'으로 보낼 때 쓰는 열쇠(토큰)를 만듭니다 (mag_made.py).
# 사용법: sudo bash /opt/soboru/app/deploy/set-maker-token.sh        토큰이 없으면 새로 만들고, 있으면 그대로 보여 줘요
#         sudo bash /opt/soboru/app/deploy/set-maker-token.sh new    토큰을 새로 바꿔요 (예전 토큰은 더 못 써요)
set -euo pipefail
ENV_FILE=/etc/soboru.env
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
cur=$(grep -E '^MAKER_API_TOKEN=' $ENV_FILE | tail -1 | cut -d= -f2- || true)
if [[ -z "$cur" || "${1:-}" == "new" ]]; then
  cur=$(openssl rand -hex 24)
  sed -i '/^MAKER_API_TOKEN=/d' $ENV_FILE
  echo "MAKER_API_TOKEN=$cur" >> $ENV_FILE
  systemctl restart soboru
  echo "토큰을 만들고 사이트를 다시 켰어요."
fi
echo
echo "보낼 곳: https://consumerjebo.co.kr/api/maker/items"
echo "머리글: Authorization: Bearer $cur"
echo "이 토큰은 남에게 보이지 않게 보관해 주세요."
