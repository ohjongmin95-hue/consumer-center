#!/usr/bin/env bash
# soboru.co.kr(+www)에 지금의 소보루 사이트(soboru 서비스, 127.0.0.1:8000)를 연결합니다.
# 기존 nginx 파일(soboru, soboru-platform)과 인증서는 건드리지 않고, 새 파일 하나와 새 인증서 하나만 만듭니다.
# biz.soboru.co.kr·cs.soboru.co.kr(소보루CS)과 consumerjebo.co.kr은 그대로 동작합니다.
#
# 순서 (단계마다 따로 실행):
#   1) 가비아 DNS에 soboru.co.kr, www.soboru.co.kr A 레코드 → 이 서버 IP
#   2) sudo bash /opt/soboru/app/deploy/soboru-main.sh 이메일        # soboru.co.kr 열기 (consumerjebo.co.kr도 그대로)
#   3) sudo bash /opt/soboru/app/deploy/soboru-main.sh --make-main   # 대표 주소를 soboru.co.kr로 (검색엔진·공유 링크·레터)
# 되돌리기:
#   sudo bash /opt/soboru/app/deploy/soboru-main.sh --undo           # 2)·3)을 모두 원래대로
set -euo pipefail

APP_DIR=/opt/soboru/app; ENV_FILE=/etc/soboru.env
NGX=/etc/nginx/sites-available/soboru-main; LINK=/etc/nginx/sites-enabled/soboru-main
MAIN=soboru.co.kr; NOW=$(date +%Y%m%d-%H%M%S); BK=/root/backup-soboru-main-$NOW

[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }

backup() {
  mkdir -p "$BK"; chmod 700 "$BK"
  tar -czf "$BK/nginx.tar.gz" -C /etc nginx
  cp -a "$ENV_FILE" "$BK/soboru.env"
  DB=$(sed -n 's/^DATABASE_PATH=//p' "$ENV_FILE")
  [[ -n $DB && -f $DB ]] && sqlite3 "$DB" ".backup '$BK/soboru.sqlite3'"
  echo "백업: $BK"
}

check() {
  echo "== 확인"
  for H in $MAIN www.$MAIN biz.soboru.co.kr cs.soboru.co.kr consumerjebo.co.kr; do
    C=$(curl -sk -o /dev/null -w '%{http_code} %{redirect_url}' --resolve "$H:443:127.0.0.1" "https://$H/" || echo 실패)
    echo "  https://$H → $C"
  done
}

case "${1:-}" in
--undo)
  backup
  rm -f "$LINK"
  if nginx -t -q; then systemctl reload nginx; echo "soboru.co.kr 연결을 껐어요. (설정 파일은 $NGX 에 남겨 둠)"; else echo "nginx 설정 오류. $BK/nginx.tar.gz 로 되돌려 주세요."; exit 1; fi
  if grep -q '^CANONICAL_HOST=' "$ENV_FILE"; then
    sed -i '/^CANONICAL_HOST=/d' "$ENV_FILE"; systemctl restart soboru; echo "대표 주소를 consumerjebo.co.kr로 되돌렸어요."
  fi
  check; exit 0 ;;
--make-main)
  [[ -L $LINK ]] && grep -q Certbot "$NGX" || { echo "먼저 soboru.co.kr을 열어 주세요: sudo bash $0 이메일"; exit 1; }
  backup
  sed -i '/^CANONICAL_HOST=/d' "$ENV_FILE"; echo "CANONICAL_HOST=$MAIN" >> "$ENV_FILE"
  systemctl restart soboru; sleep 3
  systemctl is-active --quiet soboru || { cp -a "$BK/soboru.env" "$ENV_FILE"; systemctl restart soboru; echo "사이트가 뜨지 않아 되돌렸어요."; exit 1; }
  echo "대표 주소를 https://$MAIN 로 바꿨어요. consumerjebo.co.kr로 들어와도 같은 화면이 뜨고, 검색엔진에는 soboru.co.kr을 대표로 알려요."
  check; exit 0 ;;
-*|"") echo "사용법: sudo bash $0 이메일 | --make-main | --undo"; exit 1 ;;
esac

EMAIL=$1
echo "== 1/4 DNS 확인"
MYIP=$(curl -fsS https://checkip.amazonaws.com || true)
for H in $MAIN www.$MAIN; do
  IP=$(dig +short "$H" A | tail -n1)
  [[ -n $MYIP && $IP == "$MYIP" ]] || { echo "$H 가 아직 이 서버($MYIP)를 가리키지 않아요(지금: ${IP:-없음}). 가비아 DNS에 A 레코드를 넣고 몇 분 뒤 다시 실행해 주세요."; exit 1; }
done
echo "  $MAIN, www.$MAIN → $MYIP"

echo "== 2/4 백업"
backup

echo "== 3/4 웹서버(nginx) 새 설정: $NGX"
if ! grep -q Certbot "$NGX" 2>/dev/null; then
cat > "$NGX" <<NGINX
server {
    listen 80;
    server_name $MAIN www.$MAIN;
    client_max_body_size 16m;
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

echo "== 4/4 HTTPS 인증서 (soboru.co.kr 전용, 기존 인증서와 별개)"
if ! certbot --nginx -n --agree-tos -m "$EMAIL" --redirect --keep-until-expiring --cert-name "$MAIN" -d "$MAIN" -d "www.$MAIN"; then
  echo "인증서 발급에 실패했어요. soboru.co.kr은 http로만 열려 있고, 다른 주소는 영향 없어요. 끄려면: sudo bash $0 --undo"; exit 1
fi
nginx -t -q && systemctl reload nginx
check
echo; echo "완료: https://$MAIN 이 열렸어요. 대표 주소를 바꾸려면: sudo bash $0 --make-main"
