#!/usr/bin/env bash
# 모아밥 도메인(moabap.com, 운영자 2026-11-11 구매)을 이 서버에 연결합니다. (운영자 2026-11-11)
# 기존 nginx 파일·인증서는 건드리지 않고, 새 파일 하나와 새 인증서 하나만 만듭니다.
#   1) 도메인 산 곳 DNS: 호스트 @ 와 www, 타입 A, 값 = 이 서버 IP
#   2) sudo bash /opt/soboru/app/deploy/set-moabap-domain.sh moabap.com 이메일
# 연결하면 consumerjebo.co.kr/moabap 주소(앱 첫 화면 포함)는 새 도메인으로 넘어가요. 앱은 다시 빌드할 필요 없어요.
# 끄기: sudo bash /opt/soboru/app/deploy/set-moabap-domain.sh --undo
set -euo pipefail
APP_DIR=/opt/soboru/app; ENV_FILE=/etc/soboru.env
NGX=/etc/nginx/sites-available/moabap; LINK=/etc/nginx/sites-enabled/moabap
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
set_kv() { local TMP; TMP=$(mktemp); grep -vE "^$1=" "$ENV_FILE" > "$TMP" || true; if [[ -n $2 ]]; then printf '%s=%s\n' "$1" "$2" >> "$TMP"; fi; cat "$TMP" > "$ENV_FILE"; rm -f "$TMP"; }
if [[ ${1:-} == --undo ]]; then rm -f "$LINK"; set_kv MOABAP_HOST ''; nginx -t -q && systemctl reload nginx; systemctl restart soboru; echo "모아밥 도메인 연결을 껐어요."; exit 0; fi
H=${1:-}; EMAIL=${2:-}
[[ $H =~ ^[a-z0-9.-]+\.[a-z]+$ && -n $EMAIL ]] || { echo "사용법: sudo bash $0 moabap.com 이메일 | --undo"; exit 1; }

echo "== 1/4 DNS 확인"
MYIP=$(curl -fsS https://checkip.amazonaws.com || true)
for d in "$H" "www.$H"; do
  IP=$(dig +short "$d" A @8.8.8.8 | tail -n1)
  [[ -n $MYIP && $IP == "$MYIP" ]] || { echo "$d 가 아직 이 서버($MYIP)를 가리키지 않아요(지금: ${IP:-없음}). DNS에 A 레코드 $MYIP 를 넣고 몇 분 뒤 다시 실행해 주세요."; exit 1; }
  echo "  $d → $MYIP"
done

echo "== 2/4 웹서버(nginx) 설정: $NGX"
if ! grep -q Certbot "$NGX" 2>/dev/null; then
cat > "$NGX" <<NGINX
server {
    listen 80;
    server_name $H www.$H;
    client_max_body_size 2m;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
    }
}
NGINX
fi
ln -sf "$NGX" "$LINK"
if ! nginx -t -q; then rm -f "$LINK"; echo "nginx 설정 오류라 새 파일을 껐어요. 기존 사이트는 그대로예요."; exit 1; fi
systemctl reload nginx

echo "== 3/4 HTTPS 인증서 ($H, www.$H)"
certbot --nginx -n --agree-tos -m "$EMAIL" --redirect --keep-until-expiring --cert-name "$H" -d "$H" -d "www.$H" || { echo "인증서 발급에 실패했어요. 다른 주소는 영향 없어요. 끄려면: sudo bash $0 --undo"; exit 1; }
nginx -t -q && systemctl reload nginx

echo "== 4/4 모아밥에 주소 알려 주기"
set_kv MOABAP_HOST "$H"
grep -qE '^MOABAP_PREVIEW=1' "$ENV_FILE" || bash "$APP_DIR/deploy/set-moabap.sh" >/dev/null || true  # 켜기를 안 했으면 같이 (DB·비밀번호)
systemctl restart soboru
for i in 1 2 3 4 5 6 7 8 9 10; do CODE=$(curl -sk -o /dev/null -w '%{http_code}' --resolve "$H:443:127.0.0.1" "https://$H/" || true); [[ $CODE == 200 ]] && break; sleep 1; done
echo "  https://$H → $CODE"
[[ $CODE == 200 ]] || { echo "아직 안 열려요. 아래 기록을 보내 주세요."; journalctl -u soboru -n 30 --no-pager | grep -i -A3 'moabap\|error\|Traceback' | tail -20; exit 1; }
echo "다됨: https://$H 에서 모아밥이 열려요. 운영자 화면은 https://$H/admin"
