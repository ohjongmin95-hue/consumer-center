#!/usr/bin/env bash
# SOBORU 플랫폼(한큐 + SOBORU Business)을 소비자제보센터와 같은 서버에 별도 서비스로 설치합니다.
# 먼저 setup.sh로 소비자제보센터가 설치돼 있어야 합니다(같은 소스 폴더를 씁니다).
# 사용법: sudo bash /opt/soboru/app/deploy/platform-setup.sh 소비자용도메인 기업용도메인 이메일
#   예: sudo bash platform-setup.sh hanq.example.kr business.example.kr me@example.com
# 다시 실행해도 안전합니다. 기존 데이터와 설정은 유지됩니다.
set -euo pipefail

CONSUMER="${1:-}"; BUSINESS="${2:-}"; EMAIL="${3:-}"
APP_DIR=/opt/soboru/app; VENV=/opt/soboru/venv; DATA=/var/lib/soboru-platform; ENV_FILE=/etc/soboru-platform.env

[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요."; exit 1; }
[[ -n $CONSUMER && -n $BUSINESS && -n $EMAIL ]] || { echo "사용법: sudo bash platform-setup.sh 소비자용도메인 기업용도메인 이메일"; exit 1; }
[[ -d $APP_DIR/platform_app ]] || { echo "$APP_DIR 에 platform_app이 없습니다. 먼저 sudo bash $APP_DIR/deploy/update.sh 로 최신 코드를 받아 주세요."; exit 1; }

echo "== 1/5 데이터 폴더"
mkdir -p "$DATA/uploads" "$DATA/backups"
chown -R soboru:soboru "$DATA"; chmod 750 "$DATA"
"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "== 2/5 설정 파일 ($ENV_FILE)"
if [[ ! -f $ENV_FILE ]]; then
  while true; do
    read -rsp "운영 화면 비밀번호(12자 이상): " PW </dev/tty; echo
    read -rsp "한 번 더 입력: " PW2 </dev/tty; echo
    [[ $PW == "$PW2" && ${#PW} -ge 12 ]] && break
    echo "비밀번호가 다르거나 12자보다 짧습니다."
  done
  HASH=$(PW="$PW" "$VENV/bin/python" -c 'import os;from werkzeug.security import generate_password_hash as g;print(g(os.environ["PW"]))')
  cat > "$ENV_FILE" <<CONF
SECRET_KEY=$(openssl rand -hex 32)
OPS_PASSWORD_HASH=$HASH
CONSUMER_HOST=$CONSUMER
BUSINESS_HOST=$BUSINESS
PLATFORM_DATABASE_PATH=$DATA/platform.sqlite3
PLATFORM_UPLOAD_DIR=$DATA/uploads
TRUST_PROXY=1
HTTPS_ONLY=0
# 기업 가입 신청 알림을 받을 운영자 이메일
OPS_EMAIL=$EMAIL
# pilot: 화면 위에 '시범 운영 중' 띠 표시. 개인정보 처리방침 검토가 끝나면 live로 바꾸고: sudo systemctl restart soboru-platform
PLATFORM_MODE=pilot
# 메일 알림(새 민원·답변). 소비자제보센터와 같은 계정을 써도 됩니다.
# SMTP_HOST=
# SMTP_PORT=465
# SMTP_USER=
# SMTP_PASSWORD=
# SMTP_FROM=
CONF
else
  sed -i "s/^CONSUMER_HOST=.*/CONSUMER_HOST=$CONSUMER/; s/^BUSINESS_HOST=.*/BUSINESS_HOST=$BUSINESS/" "$ENV_FILE"
fi
chown root:soboru "$ENV_FILE"; chmod 640 "$ENV_FILE"

echo "== 3/5 앱 서비스 등록 (soboru-platform)"
cat > /etc/systemd/system/soboru-platform.service <<UNIT
[Unit]
Description=SOBORU 플랫폼 (한큐 + SOBORU Business)
After=network.target

[Service]
User=soboru
Group=soboru
WorkingDirectory=$APP_DIR/platform_app
EnvironmentFile=$ENV_FILE
ExecStart=$VENV/bin/gunicorn --workers 2 --bind 127.0.0.1:8100 --access-logfile - hanq:app
Restart=always
NoNewPrivileges=true
ProtectSystem=full
ReadWritePaths=$DATA

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable -q soboru-platform
systemctl restart soboru-platform

echo "== 4/5 웹서버(nginx)와 매일 백업"
if ! grep -q Certbot /etc/nginx/sites-available/soboru-platform 2>/dev/null; then
cat > /etc/nginx/sites-available/soboru-platform <<NGINX
server {
    listen 80;
    server_name $CONSUMER $BUSINESS;
    client_max_body_size 16m;
    location /static/ { alias $APP_DIR/platform_app/static/; expires 7d; }
    location / {
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
    }
}
NGINX
fi
ln -sf /etc/nginx/sites-available/soboru-platform /etc/nginx/sites-enabled/soboru-platform
nginx -t -q && systemctl reload nginx

cat > /etc/cron.daily/soboru-platform-backup <<BACKUP
#!/bin/sh
# 매일 DB와 첨부파일을 백업하고 14일이 지난 백업은 지웁니다.
set -e
D=\$(date +%Y%m%d)
sqlite3 $DATA/platform.sqlite3 ".backup '$DATA/backups/platform-\$D.sqlite3'"
tar -czf $DATA/backups/uploads-\$D.tar.gz -C $DATA uploads
find $DATA/backups -type f -mtime +14 -delete
BACKUP
chmod 755 /etc/cron.daily/soboru-platform-backup

echo "== 5/5 HTTPS 인증서"
MYIP=$(curl -fsS https://checkip.amazonaws.com || true)
OK=()
for D in "$CONSUMER" "$BUSINESS"; do
  if [[ -n $MYIP && $(dig +short "$D" A | tail -n1) == "$MYIP" ]]; then OK+=(-d "$D"); else echo "$D 는 아직 이 서버($MYIP)를 가리키지 않아 제외합니다."; fi
done
if [[ ${#OK[@]} -eq 4 ]]; then
  certbot --nginx -n --agree-tos -m "$EMAIL" --redirect --keep-until-expiring "${OK[@]}"
  sed -i 's/^HTTPS_ONLY=.*/HTTPS_ONLY=1/' "$ENV_FILE"
  systemctl restart soboru-platform
  echo; echo "완료"
  echo "  한큐:             https://$CONSUMER"
  echo "  SOBORU Business:  https://$BUSINESS"
  echo "  운영 화면:        https://$BUSINESS/ops"
else
  echo; echo "두 도메인의 DNS가 모두 이 서버를 가리키면 같은 명령을 다시 실행해 주세요. 그때 HTTPS가 설정됩니다."
fi
