#!/bin/bash
# 인스타그램 DM이 요청으로 안 들어올 때 원인을 봅니다. 읽기만 하고 아무것도 바꾸지 않아요. 비밀 값은 나오지 않아요.
# 사용법: sudo bash /opt/soboru/app/deploy/ig-check.sh
ENV_FILE=/etc/soboru-platform.env
DB=$(grep -E '^PLATFORM_DATABASE_PATH=.' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2-)
DB=${DB:-/opt/soboru/app/platform_app/platform.sqlite3}
echo "== 소보루에 연결된 인스타그램 계정 =="
python3 - "$DB" <<'PY'
import sqlite3,sys
db=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)
for r in db.execute("SELECT l.username,l.ig_id,l.status,l.last_in,l.n_inq,c.member,c.status FROM ig_links l JOIN companies c ON c.id=l.company_id"):
    print('계정 @%s  id=%s  연결=%s  마지막DM=%s  받은요청=%s  입점=%s  회사상태=%s'%r)
PY
echo; echo "== 최근 30분 웹훅 =="
journalctl -u soboru-platform --since "30 min ago" --no-pager | grep -E "hook/instagram|인스타그램 웹훅" | tail -n 12 | sed -E 's/^.*gunicorn\[[0-9]+\]: //'
echo; echo "== 최근 30분 오류 =="
journalctl -u soboru-platform --since "30 min ago" --no-pager | grep -E "^.*: [A-Za-z_.]*(Error|Exception)[: ]" | tail -n 5 | sed -E 's/^.*gunicorn\[[0-9]+\]: //'
