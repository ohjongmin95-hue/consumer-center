#!/bin/bash
# 새 제보 알림을 텔레그램으로 받습니다(무료). 봇 토큰을 넣으면 봇에게 말을 건 대화방을 찾아 저장하고 사이트를 다시 시작합니다.
# 준비: 텔레그램에서 @BotFather 에게 /newbot 으로 봇을 만들고 토큰을 받기 → 알림 받을 단톡방에 그 봇을 초대하고 아무 말이나 한 번 보내기
# 사용법: sudo bash /opt/soboru/app/deploy/set-telegram.sh '봇토큰'
set -euo pipefail
ENV_FILE=/etc/soboru.env
TOKEN="${1:-}"; TOKEN="${TOKEN// /}"
[[ $TOKEN =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] || { echo "사용법: sudo bash $0 '봇토큰'  (토큰은 123456789:ABC... 모양입니다)"; exit 1; }
[[ -f $ENV_FILE ]] || { echo "$ENV_FILE 이 없습니다. 먼저 setup.sh로 설치해 주세요."; exit 1; }
# 봇이 받은 메시지에서 대화방 번호를 모음 (단톡방이 있으면 단톡방만)
CHATS=$(curl -fsS "https://api.telegram.org/bot$TOKEN/getUpdates" | python3 -c '
import json,sys
d=json.load(sys.stdin); seen={}
for u in d.get("result",[]):
    m=u.get("message") or u.get("my_chat_member") or u.get("channel_post") or {}
    c=m.get("chat") or {}
    if "id" in c: seen[c["id"]]=c.get("type")
groups=[i for i,t in seen.items() if t in ("group","supergroup")]
print(",".join(str(i) for i in (groups or list(seen))))') || { echo "토큰을 확인해 주세요. 텔레그램에 연결하지 못했습니다."; exit 1; }
[[ -n $CHATS ]] || { echo "봇이 받은 메시지가 없습니다. 단톡방에 봇을 초대하고 아무 말이나 보낸 뒤 다시 실행해 주세요."; exit 1; }
TMP=$(mktemp); grep -vE '^(TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)=' "$ENV_FILE" > "$TMP" || true
printf 'TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n' "$TOKEN" "$CHATS" >> "$TMP"
cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"
systemctl restart soboru
curl -fsS -o /dev/null "https://api.telegram.org/bot$TOKEN/sendMessage" --data-urlencode "chat_id=${CHATS%%,*}" --data-urlencode "text=소비자제보센터 새 제보 알림이 연결됐습니다." || true
echo "저장했습니다. 텔레그램에 연결 확인 메시지가 왔는지 봐 주세요."
