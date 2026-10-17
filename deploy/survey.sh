#!/usr/bin/env bash
# 도메인·서비스 분리 전 서버 현황 조사. 읽기만 하고 아무것도 바꾸거나 다시 시작하지 않습니다.
# 사용법: sudo bash survey.sh   → 결과: /root/soboru-survey.txt (비밀번호·API 키 값은 넣지 않음)
set -uo pipefail
OUT=/root/soboru-survey.txt
DOMAINS="soboru.co.kr www.soboru.co.kr biz.soboru.co.kr cs.soboru.co.kr admin.soboru.co.kr consumerjebo.co.kr www.consumerjebo.co.kr hanq.consumerjebo.co.kr business.consumerjebo.co.kr"
say(){ echo; echo "===== $* ====="; }
{
say "시간·서버"; date; hostname; uname -sr; . /etc/os-release 2>/dev/null && echo "$PRETTY_NAME"
echo "공인 IP: $(curl -fsS -m 8 https://checkip.amazonaws.com 2>/dev/null)"
say "자원"; nproc; free -h; df -h / /var /opt 2>/dev/null | sort -u
say "서비스"; systemctl list-units --type=service --all --no-pager 2>/dev/null | grep -Ei 'nginx|soboru|docker|gunicorn|certbot' 
say "타이머·cron"; systemctl list-timers --all --no-pager 2>/dev/null | grep -Ei 'soboru|certbot'; ls -la /etc/cron.d /etc/cron.daily /etc/cron.hourly 2>/dev/null | grep -Ei 'soboru|certbot'
say "열린 포트"; ss -ltnp 2>/dev/null
say "systemd 실행 명령"; for u in /etc/systemd/system/soboru*.service; do [ -f "$u" ] && { echo "[$u]"; grep -E '^(WorkingDirectory|EnvironmentFile|ExecStart|User)=' "$u"; }; done
say "nginx: 주소 → 연결 대상"
for f in /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do [ -f "$f" ] || continue; echo "[$f]"
  grep -nE '^\s*(server_name|listen|proxy_pass|root|return|ssl_certificate)\b' "$f" | sed 's/^/  /'; done
nginx -t 2>&1 | tail -2
say "HTTPS 인증서"; certbot certificates 2>/dev/null | grep -E 'Certificate Name|Domains|Expiry'
say "DNS (이 서버 기준)"
for d in $DOMAINS; do printf '%-30s A=%s CNAME=%s\n' "$d" "$(dig +short "$d" A | tr '\n' ' ')" "$(dig +short "$d" CNAME | tr '\n' ' ')"; done
for d in soboru.co.kr consumerjebo.co.kr; do echo "$d NS=$(dig +short $d NS | tr '\n' ' ') MX=$(dig +short $d MX | tr '\n' ' ')"; echo "$d TXT=$(dig +short $d TXT | tr '\n' ' ' | cut -c1-200)"; done
say "주소별 응답 (이 서버 nginx에 직접, 제목만)"
for d in $DOMAINS; do for s in http https; do
  R=$(curl -sk -m 8 -o /tmp/.sv -w '%{http_code} %{redirect_url}' --resolve "$d:80:127.0.0.1" --resolve "$d:443:127.0.0.1" "$s://$d/" 2>/dev/null)
  T=$(grep -oiE '<title>[^<]{0,80}' /tmp/.sv 2>/dev/null | head -1 | sed 's/<title>//I'); printf '%-5s %-30s %s | %s\n' "$s" "$d" "$R" "$T"; done; done; rm -f /tmp/.sv
say "Docker"; docker ps --format '{{.Names}}  {{.Image}}  {{.Ports}}  {{.Status}}' 2>/dev/null || echo "docker 없음"
for p in /opt/*/docker-compose.yml /opt/*/compose.yml /opt/*/compose.yaml /opt/*/docker-compose.yaml; do [ -f "$p" ] && { echo "[$p]"; grep -nE '^\s*(image|build|ports|volumes|container_name|env_file):|^\s*- ' "$p" | head -40; }; done
say "/opt 폴더와 코드 상태"; ls -la /opt
for d in /opt/*/ /opt/soboru/app; do [ -d "$d/.git" ] && { echo "[$d] $(git -C "$d" remote get-url origin 2>/dev/null) $(git -C "$d" log -1 --format='%h %ci %s' 2>/dev/null)"; git -C "$d" status --short 2>/dev/null | head -10; }; done
say "설정 파일 (이름만, 값 숨김)"
for f in /etc/soboru.env /etc/soboru-platform.env /opt/*/.env /opt/*/backend/.env; do [ -f "$f" ] && { echo "[$f]"; grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$f" | sed 's/=$//' | tr '\n' ' '; echo; grep -E '^(CONSUMER_HOST|BUSINESS_HOST|SITE_URL|DOMAIN|BASE_URL|ALLOWED_HOSTS|CORS_ORIGINS|COOKIE_DOMAIN)=' "$f"; }; done
say "DB 파일 (크기만)"; find /opt /var/lib /srv -maxdepth 5 \( -name '*.db' -o -name '*.sqlite3' -o -name '*.sqlite' \) -exec ls -la {} \; 2>/dev/null | head -20
command -v psql >/dev/null && echo "PostgreSQL 클라이언트 있음"; command -v mysql >/dev/null && echo "MySQL 클라이언트 있음"
say "백업 폴더"; ls -la /var/lib/soboru-platform/backups 2>/dev/null | tail -5; find / -xdev -maxdepth 4 -type d -name 'pre-update' 2>/dev/null | head
say "외부 연동 주소 흔적 (콜백·웹훅)"; grep -rhoE 'https?://[a-z0-9.-]*soboru\.co\.kr[^"'"'"' ]*' /etc/nginx /opt/*/.env /etc/soboru*.env 2>/dev/null | sort -u | head -20
} > "$OUT" 2>&1
sed -i -E 's/(sk-(ant-)?)[A-Za-z0-9_-]{16,}/\1***/g' "$OUT"
echo "조사 결과를 만들었어요: $OUT"
echo "내용을 복사해서 채팅에 붙여 주세요:  sudo cat $OUT"
