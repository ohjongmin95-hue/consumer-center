#!/usr/bin/env bash
# letter.soboru.co.kr(소보루 레터 구독 페이지)을 이 서버에 연결합니다. (운영자 2026-11-04)
# 기존 nginx 파일·인증서는 건드리지 않고, 새 파일 하나와 새 인증서 하나만 만듭니다.
#   1) 가비아 DNS: 호스트 letter, 타입 A, 값 = 이 서버 IP
#   2) sudo bash /opt/soboru/app/deploy/set-letter-domain.sh 이메일
# 끄기: sudo bash /opt/soboru/app/deploy/set-letter-domain.sh --undo
set -euo pipefail
APP_DIR=/opt/soboru/app; H=letter.soboru.co.kr
NGX=/etc/nginx/sites-available/soboru-letter; LINK=/etc/nginx/sites-enabled/soboru-letter
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
if [[ ${1:-} == --undo ]]; then rm -f "$LINK"; nginx -t -q && systemctl reload nginx; echo "$H 연결을 껐어요."; exit 0; fi
[[ -n ${1:-} && ${1:-} != -* ]] || { echo "사용법: sudo bash $0 이메일 | --undo"; exit 1; }
EMAIL=$1

echo "== 1/3 DNS 확인"
MYIP=$(curl -fsS https://checkip.amazonaws.com || true)
AUTH=$(dig +short NS soboru.co.kr @8.8.8.8 | head -n1); AUTH=${AUTH:-ns.gabia.co.kr}
IP=$(dig +short "$H" A @"$AUTH" | tail -n1)
[[ -n $MYIP && $IP == "$MYIP" ]] || { echo "$H 가 아직 이 서버($MYIP)를 가리키지 않아요(지금: ${IP:-없음}). 가비아 DNS에 호스트 letter, A 레코드 $MYIP 를 넣고 몇 분 뒤 다시 실행해 주세요."; exit 1; }
echo "  $H → $MYIP"

echo "== 2/3 웹서버(nginx) 설정: $NGX"
if ! grep -q Certbot "$NGX" 2>/dev/null; then
cat > "$NGX" <<NGINX
server {
    listen 80;
    server_name $H;
    client_max_body_size 4m;
    location /static/ { alias $APP_DIR/static/; expires 7d; }
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

echo "== 3/3 HTTPS 인증서 ($H 전용)"
certbot --nginx -n --agree-tos -m "$EMAIL" --redirect --keep-until-expiring --cert-name "$H" -d "$H" || { echo "인증서 발급에 실패했어요. 다른 주소는 영향 없어요. 끄려면: sudo bash $0 --undo"; exit 1; }
nginx -t -q && systemctl reload nginx
echo "  https://$H → $(curl -sk -o /dev/null -w '%{http_code} %{redirect_url}' --resolve "$H:443:127.0.0.1" "https://$H/")"
echo "완료: https://$H 에서 소보루 레터 구독 페이지가 열려요."
