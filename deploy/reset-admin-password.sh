#!/usr/bin/env bash
# 관리자 비밀번호를 잊었을 때 서버에서 새로 정합니다.
# 사용법: sudo bash /opt/soboru/app/deploy/reset-admin-password.sh
set -euo pipefail
ENV_FILE=/etc/soboru.env; VENV=/opt/soboru/venv
[[ $EUID -eq 0 ]] || { echo "sudo로 실행해 주세요: sudo bash $0"; exit 1; }
DB=$(grep -E '^DATABASE_PATH=' "$ENV_FILE" | cut -d= -f2-)
[[ -n $DB && -f $DB ]] || { echo "DB 파일을 찾지 못했습니다: ${DB:-(DATABASE_PATH 없음)}"; exit 1; }
while true; do
  read -rsp "새 관리자 비밀번호 (영문+숫자 12자 이상): " PW </dev/tty; echo
  read -rsp "한 번 더 입력: " PW2 </dev/tty; echo
  if [[ $PW != "$PW2" ]]; then echo "두 비밀번호가 다릅니다."; continue; fi
  if [[ ${#PW} -lt 12 || ! $PW =~ [A-Za-z] || ! $PW =~ [0-9] ]]; then echo "영문과 숫자를 섞어 12자 이상으로 정해 주세요."; continue; fi
  break
done
PW="$PW" DB="$DB" "$VENV/bin/python" - <<'PY'
import os, sqlite3, datetime
from werkzeug.security import generate_password_hash
db = sqlite3.connect(os.environ['DB'])
now = datetime.datetime.now().isoformat(timespec='seconds')
db.execute('CREATE TABLE IF NOT EXISTS admin_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated TEXT NOT NULL)')
row = db.execute("SELECT value FROM admin_settings WHERE key='session_ver'").fetchone()
ver = str(int(row[0]) + 1) if row else '2'
for key, value in (('password_hash', generate_password_hash(os.environ['PW'])), ('session_ver', ver)):
    db.execute('INSERT INTO admin_settings(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated', (key, value, now))
db.commit(); db.close()
PY
echo "완료: 새 비밀번호로 관리자 로그인하세요. 기존에 로그인해 있던 관리자 화면은 모두 로그아웃됩니다."
