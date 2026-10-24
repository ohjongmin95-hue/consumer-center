#!/usr/bin/env bash
# SOBORU 플랫폼(소보루 비즈 고객센터 + 소보루 비즈)을 소비자제보센터와 같은 서버에 별도 서비스로 설치합니다.
# 먼저 setup.sh로 소비자제보센터가 설치돼 있어야 합니다(같은 소스 폴더를 씁니다).
# 사용법: sudo bash /opt/soboru/app/deploy/platform-setup.sh 소비자용도메인 기업용도메인 이메일
#   예: sudo bash platform-setup.sh cs.soboru.co.kr biz.soboru.co.kr me@example.com
# 다시 실행해도 안전합니다. 기존 데이터와 설정은 유지됩니다.
# 도메인을 바꿀 때도 새 도메인으로 다시 실행하면 됩니다. 예전 주소로 들어오면 새 주소로 넘겨 줘서 이미 나눠 준 링크도 계속 동작합니다.
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
OLD_C=""; OLD_B=""
if [[ -f $ENV_FILE ]]; then
  OLD_C=$(sed -n 's/^CONSUMER_HOST=//p' "$ENV_FILE"); OLD_B=$(sed -n 's/^BUSINESS_HOST=//p' "$ENV_FILE")
fi
MOVED=0
[[ ( -n $OLD_C && $OLD_C != "$CONSUMER" ) || ( -n $OLD_B && $OLD_B != "$BUSINESS" ) ]] && MOVED=1
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
# 운영 모드(현재 화면 차이 없음)
PLATFORM_MODE=pilot
# 메일 알림(새 민원·답변). 소비자제보센터와 같은 계정을 써도 됩니다.
# 네이버 서치어드바이저 소유확인 코드 (한큐, 소보루 비즈)
# NAVER_SITE_VERIFICATION=
# NAVER_SITE_VERIFICATION_BIZ=
# SMTP_HOST=
# SMTP_PORT=465
# SMTP_USER=
# SMTP_PASSWORD=
# SMTP_FROM=
# 답변 초안을 AI로 (없으면 기본 문구로 초안)
# ANTHROPIC_API_KEY=
# 새 민원 카카오 알림톡 (솔라피, 템플릿은 docs/platform.md)
# SOLAPI_API_KEY=
# SOLAPI_API_SECRET=
# SOLAPI_PFID=
# SOLAPI_SENDER=
# 알리고로 보내려면 (더 쌈, bizmsg.py): MSG_VENDOR=aligo, 템플릿 코드는 앞에 ALIGO_ (예: ALIGO_BIZ_KAKAO_TPL_NEW)
# MSG_VENDOR=
# ALIGO_API_KEY=
# ALIGO_USER_ID=
# ALIGO_SENDER_KEY=
# ALIGO_SENDER=
# BIZ_KAKAO_TPL_NEW=
CONF
else
  sed -i "s/^CONSUMER_HOST=.*/CONSUMER_HOST=$CONSUMER/; s/^BUSINESS_HOST=.*/BUSINESS_HOST=$BUSINESS/" "$ENV_FILE"
  # 도메인을 바꾸면 새 도메인에 인증서가 붙기 전까지 http로 로그인할 수 있게 둔다 (5단계에서 다시 켬)
  [[ $MOVED == 1 ]] && sed -i 's/^HTTPS_ONLY=.*/HTTPS_ONLY=0/' "$ENV_FILE"
fi
chown root:soboru "$ENV_FILE"; chmod 640 "$ENV_FILE"

echo "== 3/5 앱 서비스 등록 (soboru-platform)"
cat > /etc/systemd/system/soboru-platform.service <<UNIT
[Unit]
Description=SOBORU 플랫폼 (한큐 + 소보루 비즈)
After=network.target

[Service]
User=soboru
Group=soboru
WorkingDirectory=$APP_DIR/platform_app
EnvironmentFile=$ENV_FILE
ExecStart=$VENV/bin/gunicorn --workers 2 --threads 4 --timeout 90 --bind 127.0.0.1:8100 --access-logfile - hanq:app
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
NGX=/etc/nginx/sites-available/soboru-platform
if [[ $MOVED == 1 && -f $NGX ]]; then
  cp "$NGX" "$NGX.bak-$(date +%Y%m%d%H%M%S)"; echo "도메인 변경: $OLD_C, $OLD_B → $CONSUMER, $BUSINESS (기존 설정은 $NGX.bak-* 로 보관)"
fi
if [[ $MOVED == 1 ]] || ! grep -q Certbot "$NGX" 2>/dev/null; then
cat > "$NGX" <<NGINX
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
# 예전 도메인으로 들어오면 같은 경로의 새 도메인으로 넘긴다 (이미 나눠 준 기업 고객센터 링크 등).
# 예전 도메인은 $DATA/old-hosts에 'c 주소'(소비자용)·'b 주소'(기업용)로 쌓아 두고, 설정을 다시 쓸 때마다 모두 넣는다.
[[ $MOVED == 1 && -n $OLD_C && $OLD_C != "$CONSUMER" ]] && echo "c $OLD_C" >> "$DATA/old-hosts"
[[ $MOVED == 1 && -n $OLD_B && $OLD_B != "$BUSINESS" ]] && echo "b $OLD_B" >> "$DATA/old-hosts"
if [[ -f $DATA/old-hosts ]]; then
  sort -u "$DATA/old-hosts" | while read -r ROLE FROM; do
    [[ -n $FROM && $FROM != "$CONSUMER" && $FROM != "$BUSINESS" ]] || continue
    TO=$CONSUMER; [[ $ROLE == b ]] && TO=$BUSINESS
    printf 'server {\n    listen 80;\n    server_name %s;\n    return 301 http://%s$request_uri;\n}\n' "$FROM" "$TO" >> "$NGX"
  done
fi
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

cat > /etc/cron.hourly/soboru-platform-late <<'CRON'
#!/bin/sh
# 답변 목표일이 지난 민원을 소비자와 기업에 알립니다.
set -a; . /etc/soboru-platform.env; set +a
cd /opt/soboru/app/platform_app && runuser -u soboru -- /opt/soboru/venv/bin/python notify_late.py >/dev/null 2>&1
CRON
chmod 755 /etc/cron.hourly/soboru-platform-late

echo "== 5/5 HTTPS 인증서"
MYIP=$(curl -fsS https://checkip.amazonaws.com || true)
OK=()
for D in "$CONSUMER" "$BUSINESS"; do
  if [[ -n $MYIP && $(dig +short "$D" A | tail -n1) == "$MYIP" ]]; then OK+=(-d "$D"); else echo "$D 는 아직 이 서버($MYIP)를 가리키지 않아 제외합니다."; fi
done
if [[ ${#OK[@]} -eq 4 ]]; then
  # 예전 도메인도 https로 들어왔을 때 넘겨 줄 수 있게 같은 인증서에 넣는다 (아직 이 서버를 가리킬 때만)
  if [[ -f $DATA/old-hosts ]]; then
    for D in $(awk '{print $2}' "$DATA/old-hosts" | sort -u); do
      [[ $D == "$CONSUMER" || $D == "$BUSINESS" ]] && continue
      [[ -n $MYIP && $(dig +short "$D" A | tail -n1) == "$MYIP" ]] && OK+=(-d "$D")
    done
  fi
  certbot --nginx -n --agree-tos -m "$EMAIL" --redirect --expand --keep-until-expiring "${OK[@]}"
  sed -i 's/^HTTPS_ONLY=.*/HTTPS_ONLY=1/' "$ENV_FILE"
  systemctl restart soboru-platform
  echo; echo "완료"
  echo "  소보루 비즈 고객센터: https://$CONSUMER"
  echo "  소보루 비즈:          https://$BUSINESS"
  echo "  운영 화면:            https://$BUSINESS/ops"
else
  echo; echo "두 도메인의 DNS가 모두 이 서버를 가리키면 같은 명령을 다시 실행해 주세요. 그때 HTTPS가 설정됩니다."
fi
