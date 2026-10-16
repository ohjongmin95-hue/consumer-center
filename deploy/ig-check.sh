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
print()
print('== 최근 인스타그램 DM 요청 (답장 보낼 상대가 있어야 DM으로 가요) ==')
for r in db.execute("SELECT c.no,c.status,c.created,c.company_id=COALESCE(l.company_id,-1),(SELECT COUNT(*) FROM shop_seen s WHERE s.case_id=c.id AND s.shop='instagram' AND s.ext_id LIKE 'u:%%'),(SELECT COUNT(*) FROM shop_seen s WHERE s.case_id=c.id),(SELECT COUNT(*) FROM events e WHERE e.case_id=c.id AND e.text LIKE '인스타그램 DM을 가져왔어요%%') FROM cases c LEFT JOIN ig_links l ON l.company_id=c.company_id WHERE c.channel='인스타그램 DM' ORDER BY c.id DESC LIMIT 6"):
    print('%s  상태=%s  접수=%s  연결된회사=%s  답장상대=%s  가져온기록=%s  DM에서생성=%s'%(r[0],r[1],r[2][:16],'예' if r[3] else '아니오',r[4],r[5],'예' if r[6] else '아니오(직접 등록)'))
PY
echo; echo "== 서버 코드 버전 =="; git -C /opt/soboru/app log -1 --format='%h %s' 2>/dev/null
echo; echo "== 최근 30분 웹훅 =="
journalctl -u soboru-platform --since "30 min ago" --no-pager | grep -E "hook/instagram|인스타그램 웹훅" | tail -n 12 | sed -E 's/^.*gunicorn\[[0-9]+\]: //'
echo; echo "== 최근 30분 오류 =="
journalctl -u soboru-platform --since "30 min ago" --no-pager | grep -E "^.*: [A-Za-z_.]*(Error|Exception)[: ]" | tail -n 5 | sed -E 's/^.*gunicorn\[[0-9]+\]: //'
echo; echo "== 마지막 오류 자세히 (비밀 값 없이 코드 줄만) =="
journalctl -u soboru-platform --since "2 hours ago" --no-pager | sed -E 's/^.*gunicorn\[[0-9]+\]: //' | grep -A 40 "ERROR in app: Exception" | tail -n 40 | grep -E "ERROR in app|File \"/opt|^[A-Za-z_.]*(Error|Exception)" | tail -n 14
