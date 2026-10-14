#!/usr/bin/env bash
# 서버 진단: 서비스 상태, 502 원인, 서버에만 있는 코드와 백업을 한 파일로 모읍니다. 아무것도 지우거나 바꾸지 않습니다.
# 사용법: sudo bash /opt/soboru/app/deploy/diagnose.sh
# 결과: /root/soboru-diag.tar.gz (DB, .env, 업로드 파일은 넣지 않고, API 키처럼 보이는 글자는 가립니다)
set -uo pipefail
APP=/opt/soboru/app
OUT=/root/soboru-diag; rm -rf "$OUT"; mkdir -p "$OUT/code"
R="$OUT/report.txt"
say(){ echo; echo "===== $* ====="; }
{
say "시간"; date
say "서비스 상태"; for s in nginx soboru soboru-platform docker; do printf '%-16s %s\n' "$s" "$(systemctl is-active $s 2>&1)"; done
say "soboru-platform 최근 기록"; journalctl -u soboru-platform -n 60 --no-pager 2>&1
say "nginx 최근 오류"; tail -n 40 /var/log/nginx/error.log 2>&1
say "포트"; ss -ltnp 2>&1 | grep -E ':(80|443|8000|8100|18080)\b'
say "내부 접속"; for u in http://127.0.0.1:8100/biz/ http://127.0.0.1:8000/ http://127.0.0.1:18080/ http://127.0.0.1:18080/health; do printf '%-36s %s\n' "$u" "$(curl -s -o /dev/null -m 8 -w '%{http_code}' "$u")"; done
say "외부 접속"; for u in https://biz.soboru.co.kr/ https://cs.soboru.co.kr/to/2; do printf '%-36s %s\n' "$u" "$(curl -s -o /dev/null -m 8 -w '%{http_code}' "$u")"; done
say "nginx 설정 검사"; nginx -t 2>&1
say "Docker (AI 서비스)"; (cd /opt/soboru-cs 2>/dev/null && docker compose ps 2>&1 && docker compose logs --tail 40 2>&1) || echo "/opt/soboru-cs 없음"
say "앱 코드(git) 상태"; git -C $APP log --oneline -5 2>&1; git -C $APP status --short 2>&1; echo "- stash:"; git -C $APP stash list 2>&1
say "서버에만 있는 파일 (git에 없는 것)"; git -C $APP ls-files --others --exclude-standard 2>&1 | grep -v -E '\.(db|sqlite3?)$|__pycache__' | head -100
say "환경 설정 이름 (값은 숨김)"; for f in /etc/soboru-platform.env /etc/soboru.env /opt/soboru-cs/.env /opt/soboru-cs/backend/.env; do [ -f "$f" ] && { echo "[$f]"; grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$f" | sed 's/=$//'; }; done
say "백업과 설치 파일 위치"; for p in /opt/soboru-product-backup-* /opt/soboru-chat-backup-* /tmp/soboru-ai-source.tar.gz /tmp/soboru-product-pdf /opt/soboru-cs; do [ -e "$p" ] && { du -sh "$p" 2>/dev/null; find "$p" -maxdepth 3 -not -path '*/node_modules*' -not -path '*/__pycache__*' -not -path '*/.git/*' | head -60; } || true; done
say "DB 파일 (지우지 않음, 크기만)"; find /opt /var/lib -maxdepth 4 \( -name '*.db' -o -name '*.sqlite3' \) -exec ls -la {} \; 2>/dev/null | head
} > "$R" 2>&1

# 코드 모으기: 지금 앱 코드, AI 서비스, 백업, PDF 설치 파일, nginx 설정. DB·.env·업로드·의존성 폴더는 뺍니다.
EX=(--exclude='*.db' --exclude='*.sqlite3' --exclude='*.env' --exclude='.env*' --exclude='node_modules' --exclude='__pycache__' --exclude='.git' --exclude='venv' --exclude='.venv' --exclude='uploads' --exclude='*.pem' --exclude='*.key')
copy(){ [ -e "$1" ] && mkdir -p "$OUT/code/$2" && tar -C "$(dirname "$1")" "${EX[@]}" -cf - "$(basename "$1")" 2>/dev/null | tar -C "$OUT/code/$2" -xf - ; }
copy $APP/platform_app now
copy /opt/soboru-cs ai
for p in /opt/soboru-product-backup-* /opt/soboru-chat-backup-*; do [ -e "$p" ] && copy "$p" backups; done
[ -f /tmp/soboru-ai-source.tar.gz ] && { mkdir -p "$OUT/code/ai-source"; tar -xzf /tmp/soboru-ai-source.tar.gz -C "$OUT/code/ai-source" "${EX[@]}" 2>/dev/null; }
copy /tmp/soboru-product-pdf pdf-installer
mkdir -p "$OUT/code/nginx"; cp /etc/nginx/sites-enabled/* "$OUT/code/nginx/" 2>/dev/null
git -C $APP stash show -p > "$OUT/code/stash.patch" 2>/dev/null
cp /root/business-local-backup.diff "$OUT/code/" 2>/dev/null
# 원본 PDF는 상품 테스트에 필요하므로 따로 이름만 적어 둡니다 (파일은 넣지 않음)
find / -xdev -name '*.pdf' -newermt '2026-10-01' -not -path '/proc/*' 2>/dev/null | head -20 > "$OUT/pdf-files.txt"
# API 키처럼 보이는 글자 가리기
grep -rlE 'sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{16,}' "$OUT" 2>/dev/null | while read -r f; do sed -i -E 's/sk-(ant-)?[A-Za-z0-9_-]{16,}/sk-***가림***/g' "$f"; done
tar -C /root -czf /root/soboru-diag.tar.gz soboru-diag
echo "진단 파일을 만들었어요: /root/soboru-diag.tar.gz ($(du -h /root/soboru-diag.tar.gz | cut -f1))"
echo "요약:"; sed -n '/===== 서비스 상태/,/===== soboru-platform/p' "$R" | head -8; sed -n '/===== 외부 접속/,/===== nginx 설정/p' "$R" | head -4
