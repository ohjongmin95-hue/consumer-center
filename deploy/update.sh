#!/usr/bin/env bash
# 최신 코드를 받아 앱을 다시 시작합니다. 사용법: sudo bash /opt/soboru/app/deploy/update.sh
set -euo pipefail
# 기본값: 서버에 현재 설치된 브랜치를 그대로 유지
BRANCH="${BRANCH:-$(git -C /opt/soboru/app rev-parse --abbrev-ref HEAD)}"
APP=/opt/soboru/app; DATA=/var/lib/soboru-platform; NOW="$(date +%Y%m%d-%H%M%S)"
git -C $APP fetch -q origin "$BRANCH"
PREV="$(git -C $APP rev-parse HEAD)"
# 서버에서 직접 고친 내용이 있으면 지우지 않고 따로 보관한 뒤 업데이트 (예전처럼 업데이트가 멈추지 않게)
KEEP=/root/soboru-before-update-$NOW
if [ -n "$(git -C $APP status --porcelain --untracked-files=no)" ]; then
  mkdir -p $KEEP; git -C $APP diff > $KEEP/local-changes.diff; git -C $APP stash push -q -m "update.sh $NOW"
  echo "서버에서 고친 내용을 보관했어요: $KEEP/local-changes.diff (git stash에도 있어요)"
fi
# 새 버전에 같은 이름의 파일이 들어오면, 서버에만 있던 파일은 보관 폴더로 옮김
for f in $(git -C $APP diff --name-only --diff-filter=A HEAD "origin/$BRANCH"); do
  if [ -e "$APP/$f" ] && ! git -C $APP ls-files --error-unmatch "$f" >/dev/null 2>&1; then
    mkdir -p "$KEEP/$(dirname "$f")"; mv "$APP/$f" "$KEEP/$f"; echo "서버에만 있던 $f 를 $KEEP 로 옮겼어요"
  fi
done
# 업데이트 직전 DB 백업 (최근 10개만 남김)
if [ -f $DATA/platform.sqlite3 ]; then
  mkdir -p $DATA/backups
  python3 -c 'import sqlite3,sys;d=sqlite3.connect(sys.argv[2]);sqlite3.connect(sys.argv[1]).backup(d);d.close()' $DATA/platform.sqlite3 $DATA/backups/pre-update-$NOW.sqlite3
  chmod 600 $DATA/backups/pre-update-$NOW.sqlite3
  ls -1t $DATA/backups/pre-update-*.sqlite3 2>/dev/null | tail -n +11 | xargs -r rm -f
fi
# 소비자제보센터 DB도 업데이트 직전에 백업 (최근 10개만 남김, 첨부는 매일 백업에 있음). 복구 방법은 deploy/rollback.sh 맨 위 설명
JEBO_DB="$(grep -E '^DATABASE_PATH=' /etc/soboru.env 2>/dev/null | cut -d= -f2- || true)"
if [ -n "$JEBO_DB" ] && [ -f "$JEBO_DB" ]; then
  JB="$(dirname "$JEBO_DB")/pre-update"; mkdir -p "$JB"; chmod 700 "$JB"
  python3 -c 'import sqlite3,sys;d=sqlite3.connect(sys.argv[2]);sqlite3.connect(sys.argv[1]).backup(d);d.close()' "$JEBO_DB" "$JB/cases-$NOW.sqlite3"
  chmod 600 "$JB/cases-$NOW.sqlite3"
  ls -1t "$JB"/cases-*.sqlite3 2>/dev/null | tail -n +11 | xargs -r rm -f
  echo "제보센터 DB 백업: $JB/cases-$NOW.sqlite3"
fi
git -C $APP checkout -q -B "$BRANCH" "origin/$BRANCH"
[ -d $DATA ] && echo "$PREV" > $DATA/prev-commit
chmod -R u+rwX,go+rX $APP  # 서비스 계정이 읽지 못하는 파일 때문에 멈추는 일(502)이 없게
/opt/soboru/venv/bin/pip install -q -r /opt/soboru/app/requirements.txt
systemctl restart soboru
# AI 분석 기사 예약 작업을 설치해 뒀으면(set-writer.sh) 새 설정으로 바꿔 둠
if [ -f /etc/systemd/system/soboru-writer.timer ]; then install -m 644 $APP/deploy/soboru-writer.service $APP/deploy/soboru-writer.timer /etc/systemd/system/ && systemctl daemon-reload; fi
if [ -f /etc/systemd/system/soboru-letter.timer ]; then install -m 644 $APP/deploy/soboru-letter.service $APP/deploy/soboru-letter.timer /etc/systemd/system/ && systemctl daemon-reload; fi  # 크로와상(set-letter.sh)
# SOBORU 플랫폼(한큐 + 소보루 비즈)이 설치돼 있으면 같이 다시 시작
if [ -f /etc/systemd/system/soboru-platform.service ]; then
  # 소비자제보센터에 넣어 둔 메일 설정을 소보루 CS에도 똑같이 넣음 (비밀번호 찾기·알림 메일)
  if [ -f /etc/soboru.env ] && [ -f /etc/soboru-platform.env ] && grep -q '^SMTP_HOST=.' /etc/soboru.env && ! grep -q '^SMTP_HOST=.' /etc/soboru-platform.env; then
    grep -E '^SMTP_(HOST|PORT|USER|PASSWORD|FROM)=' /etc/soboru.env >> /etc/soboru-platform.env
  fi
  # 판매처 연결 안내에 보여 줄 이 서버의 공인 IP (사장님이 스마트스토어·쿠팡에 등록)
  if [ -f /etc/soboru-platform.env ] && ! grep -q '^SERVER_IP=.' /etc/soboru-platform.env; then
    IP="$(curl -fsS -m 5 https://api.ipify.org || true)"
    if echo "$IP" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$'; then echo "SERVER_IP=$IP" >> /etc/soboru-platform.env; fi
  fi
  # AI 상담 키(OpenAI): 이미 서버의 AI 서비스 설정에 있으면 소보루 CS 설정에도 복사 (화면·채팅에 키를 적지 않아도 됨)
  if [ -f /opt/soboru-cs/.env ] && [ -f /etc/soboru-platform.env ]; then
    for k in OPENAI_API_KEY SOBORU_AI_MODEL; do
      if grep -q "^$k=." /opt/soboru-cs/.env && ! grep -q "^$k=." /etc/soboru-platform.env; then grep -m1 "^$k=" /opt/soboru-cs/.env >> /etc/soboru-platform.env; echo "$k 설정을 AI 서버에서 가져왔어요"; fi
    done
  fi
  # PDF 상품 등록에 필요한 프로그램 (PDF 글자 읽기, 한글 포함)
  command -v pdftotext >/dev/null || apt-get install -y -q poppler-utils poppler-data >/dev/null 2>&1 || echo "pdftotext 설치 실패: sudo apt-get install -y poppler-utils poppler-data"
  # AI 상담은 인터넷 검색까지 하면 30초를 넘길 수 있어서 응답 대기 시간을 늘리고, 동시에 여러 고객을 받게 함
  U=/etc/systemd/system/soboru-platform.service
  if [ -f $U ] && ! grep -q -- '--timeout' $U; then sed -i 's#gunicorn --workers 2 #gunicorn --workers 2 --threads 4 --timeout 90 #' $U; systemctl daemon-reload; fi
  systemctl restart soboru-platform
  # 새 버전이 안 뜨면 바로 전 버전으로 자동 복구
  sleep 3
  H="$(grep -E '^BUSINESS_HOST=' /etc/soboru-platform.env 2>/dev/null | cut -d= -f2- || true)"
  if [ -n "$H" ]; then CODE="$(curl -s -o /dev/null -m 10 -w '%{http_code}' -H "Host: $H" http://127.0.0.1:8100/login || true)"
  else CODE="$(curl -s -o /dev/null -m 10 -w '%{http_code}' http://127.0.0.1:8100/biz/login || true)"; fi
  if ! systemctl is-active --quiet soboru-platform || [ "$CODE" != "200" ]; then
    echo "새 버전이 정상으로 뜨지 않아(응답 $CODE) 전 버전으로 되돌려요"; journalctl -u soboru-platform -n 30 --no-pager | grep -v -i -E 'key|token|password' || true
    git -C $APP checkout -q -B "$BRANCH" "$PREV"; systemctl restart soboru soboru-platform; sleep 3
    echo "되돌림 완료: $(git -C $APP log -1 --format='%h %s')"; exit 1
  fi
  echo "소보루 CS 응답: $CODE (정상)"
  if grep -q '^SMTP_HOST=.' /etc/soboru-platform.env 2>/dev/null; then echo "소보루 CS 메일: 켜져 있어요"
  else echo "소보루 CS 메일: 꺼져 있어요. 켜려면 set-mail.sh를 한 번 실행해 주세요."; fi
  # 답변 지연 알림 · 불량 경보 · 월간 리포트 (한 시간마다, 같은 알림은 한 번만)
  cat > /etc/cron.hourly/soboru-platform-late <<'CRON'
#!/bin/sh
set -a; . /etc/soboru-platform.env; set +a
cd /opt/soboru/app/platform_app && runuser -u soboru -- /opt/soboru/venv/bin/python notify_late.py >/dev/null 2>&1
CRON
  chmod 755 /etc/cron.hourly/soboru-platform-late
  # 스마트스토어·쿠팡 문의와 주문 가져오기 (10분마다, 연결한 기업만)
  cat > /etc/cron.d/soboru-platform-shops <<'CRON'
*/10 * * * * root set -a; . /etc/soboru-platform.env; set +a; cd /opt/soboru/app/platform_app && runuser -u soboru -- /opt/soboru/venv/bin/python shops.py >/dev/null 2>&1
CRON
  chmod 644 /etc/cron.d/soboru-platform-shops
fi
sleep 2
systemctl is-active --quiet soboru && echo "업데이트 완료: $(git -C /opt/soboru/app log -1 --format='%h %s')" || { journalctl -u soboru -n 30 --no-pager; exit 1; }
