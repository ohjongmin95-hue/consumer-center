#!/usr/bin/env bash
# Ubuntu 22.04/24.04 서버 한 대에 소비자제보센터를 설치합니다.
# 사용법: sudo bash setup.sh 도메인 이메일   (예: sudo bash setup.sh example.kr me@example.com)
# 다시 실행해도 안전합니다. 기존 데이터와 설정은 유지됩니다.
set -euo pipefail

DOMAIN="${1:-}"; EMAIL="${2:-}"
REPO="${REPO:-https://github.com/ohjongmin95-hue/consumer-center.git}"
BRANCH="${BRANCH:-main}"
APP_DIR=/opt/soboru/app; VENV=/opt/soboru/venv; DATA=/var/lib/soboru; ENV_FILE=/etc/soboru.env

[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요: sudo bash setup.sh 도메인 이메일"; exit 1; }
[[ -n $DOMAIN && -n $EMAIL ]] || { echo "사용법: sudo bash setup.sh 도메인 이메일"; exit 1; }
DOMAIN="${DOMAIN#www.}"

echo "== 1/6 패키지 설치"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
# IPv6가 꺼진 서버(네이버 클라우드 등)에서는 nginx 기본 설정의 [::]:80 때문에 설치가 실패하므로 제거 후 마무리합니다.
if ! apt-get install -y -q git python3-venv nginx certbot python3-certbot-nginx sqlite3 dnsutils; then
  sed -i '/listen \[::\]/d' /etc/nginx/sites-available/default 2>/dev/null || true
  dpkg --configure -a
  apt-get install -y -q git python3-venv nginx certbot python3-certbot-nginx sqlite3 dnsutils
fi

echo "== 2/6 소스 내려받기 ($BRANCH)"
id soboru >/dev/null 2>&1 || useradd --system --home /opt/soboru --shell /usr/sbin/nologin soboru
mkdir -p /opt/soboru "$DATA/uploads" "$DATA/backups"
if [[ -d $APP_DIR/.git ]]; then
  git -C "$APP_DIR" fetch -q origin "$BRANCH" && git -C "$APP_DIR" checkout -q -B "$BRANCH" "origin/$BRANCH"
else
  git clone -q --branch "$BRANCH" "$REPO" "$APP_DIR"
fi
[[ -d $VENV ]] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"
chown -R soboru:soboru "$DATA"; chmod 750 "$DATA"

echo "== 3/6 설정 파일 ($ENV_FILE)"
if [[ ! -f $ENV_FILE ]]; then
  while true; do
    read -rsp "관리자 비밀번호(12자 이상): " PW </dev/tty; echo
    read -rsp "한 번 더 입력: " PW2 </dev/tty; echo
    [[ $PW == "$PW2" && ${#PW} -ge 12 ]] && break
    echo "비밀번호가 다르거나 12자보다 짧습니다."
  done
  HASH=$(PW="$PW" "$VENV/bin/python" -c 'import os;from werkzeug.security import generate_password_hash as g;print(g(os.environ["PW"]))')
  cat > "$ENV_FILE" <<CONF
SECRET_KEY=$(openssl rand -hex 32)
ADMIN_PASSWORD_HASH=$HASH
DATABASE_PATH=$DATA/cases.sqlite3
UPLOAD_DIR=$DATA/uploads
TRUST_PROXY=1
HTTPS_ONLY=0
# 개인정보 처리방침 등 준비가 끝나면 1로 바꾸고: sudo systemctl restart soboru
ENABLE_INTAKE=0
# 소비자게시판 글쓰기·공감·댓글. 켜려면 1로 바꾸고: sudo systemctl restart soboru
ENABLE_BOARD=0
CONF
fi
chown root:soboru "$ENV_FILE"; chmod 640 "$ENV_FILE"

echo "== 4/6 앱 서비스 등록"
cat > /etc/systemd/system/soboru.service <<UNIT
[Unit]
Description=소비자제보센터
After=network.target

[Service]
User=soboru
Group=soboru
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$VENV/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 --access-logfile - app:app
Restart=always
NoNewPrivileges=true
ProtectSystem=full
ReadWritePaths=$DATA

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable -q soboru
systemctl restart soboru

echo "== 5/6 웹서버(nginx)와 매일 백업"
# HTTPS가 이미 설정됐다면(certbot이 수정한 설정) 덮어쓰지 않습니다.
if ! grep -q Certbot /etc/nginx/sites-available/soboru 2>/dev/null; then
cat > /etc/nginx/sites-available/soboru <<NGINX
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;
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
ln -sf /etc/nginx/sites-available/soboru /etc/nginx/sites-enabled/soboru
rm -f /etc/nginx/sites-enabled/default
nginx -t -q && systemctl reload nginx

cat > /etc/cron.daily/soboru-backup <<BACKUP
#!/bin/sh
# 매일 DB와 첨부파일을 백업하고 14일이 지난 백업은 지웁니다.
set -e
D=\$(date +%Y%m%d)
sqlite3 $DATA/cases.sqlite3 ".backup '$DATA/backups/cases-\$D.sqlite3'"
tar -czf $DATA/backups/uploads-\$D.tar.gz -C $DATA uploads
find $DATA/backups -type f -mtime +14 -delete
BACKUP
chmod 755 /etc/cron.daily/soboru-backup

echo "== 6/6 HTTPS 인증서"
MYIP=$(curl -fsS https://checkip.amazonaws.com || true)
DNSIP=$(dig +short "$DOMAIN" A | tail -n1)
if [[ -n $MYIP && $MYIP == "$DNSIP" ]]; then
  CERT_DOMAINS=(-d "$DOMAIN")
  [[ $(dig +short "www.$DOMAIN" A | tail -n1) == "$MYIP" ]] && CERT_DOMAINS+=(-d "www.$DOMAIN") || echo "www.$DOMAIN 은 아직 연결되지 않아 제외합니다."
  certbot --nginx -n --agree-tos -m "$EMAIL" --redirect --keep-until-expiring "${CERT_DOMAINS[@]}"
  sed -i 's/^HTTPS_ONLY=.*/HTTPS_ONLY=1/' "$ENV_FILE"
  systemctl restart soboru
  echo; echo "완료: https://$DOMAIN  (관리자: https://$DOMAIN/admin/login)"
else
  echo; echo "도메인($DOMAIN)이 아직 이 서버($MYIP)를 가리키지 않습니다 (현재: ${DNSIP:-없음})."
  echo "가비아 DNS 설정이 반영된 뒤 같은 명령을 다시 실행하면 HTTPS가 설정됩니다."
  echo "지금은 http://$MYIP 로 확인할 수 있습니다."
fi
