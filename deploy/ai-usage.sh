#!/usr/bin/env bash
# 소보루 OpenAI 사용 현황 보기 (읽기만 함, 키 값은 출력하지 않음)
# 사용법: sudo bash /opt/soboru/app/deploy/ai-usage.sh
set -u
echo "[설정된 모델] 비어 있으면 코드 기본값을 씀"
for f in /etc/soboru.env /etc/soboru-platform.env; do
  [ -f "$f" ] || continue
  grep -E '^(CS_AI_MODEL|OPENAI_MODEL|OPENAI_IMAGE_MODEL|OPENAI_IMAGE_QUALITY|SOBORU_AI_MODEL|CHAT_MODEL|DRAFT_MODEL)=' "$f" | sed "s|^|  $f: |"
  if grep -qE '^OPENAI_API_KEY=.' "$f"; then echo "  $f: OpenAI 키 있음"; else echo "  $f: OpenAI 키 없음"; fi
done
echo "  코드 기본값: 소보루CS AI 상담 gpt-6-luna(운영 > AI 모델에서 바꿈, 실패하면 gpt-4.1-mini), 소보루 글(요청서·분류·법률 질문) gpt-4.1-mini, 그림 gpt-image-1-mini(medium)"
DB="$(grep -E '^DATABASE_PATH=' /etc/soboru.env 2>/dev/null | cut -d= -f2- || true)"; DB="${DB:-/opt/soboru/app/cases.sqlite3}"
[ -f "$DB" ] || { echo "DB를 찾지 못했어요: $DB"; exit 1; }
python3 - "$DB" <<'PY'
import sqlite3, sys, datetime
db = sqlite3.connect('file:%s?mode=ro' % sys.argv[1], uri=True)
since = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat(timespec='seconds')
def show(title, sql):
    print('\n[%s]' % title)
    try: rows = db.execute(sql, (since,)).fetchall()
    except sqlite3.Error: rows = []
    rows = [r for r in rows if r[1]]
    if not rows: print('  기록 없음'); return
    for name, n, n30, err, last in rows:
        print('  %-24s 전체 %4d건 · 최근 30일 %4d건 · 실패 %d건 · 마지막 %s' % (name or '(모델 기록 없음)', n, n30 or 0, err or 0, (last or '')[:16]))
show('기업 입장 요청서 AI 초안', "SELECT model,COUNT(*),SUM(created>=?),SUM(error!=''),MAX(created) FROM company_requests WHERE origin='ai' OR error!='' GROUP BY model")
show('제보 분류·법률 안내 초안', "SELECT model,COUNT(*),SUM(created>=?),SUM(error!=''),MAX(created) FROM case_triage GROUP BY model")
show('AI 일러스트 (종류별, 그림 모델)', "SELECT kind,COUNT(*),SUM(created>=?),0,MAX(created) FROM soboru_art GROUP BY kind")
show('법률 질문 /ask (최근 24시간만 남음)', "SELECT 'OPENAI_MODEL',COUNT(*),SUM(created>=?),0,MAX(created) FROM law_questions")
PY
echo
echo "정확한 요금·토큰은 platform.openai.com > Usage에서 모델별로 볼 수 있어요."
