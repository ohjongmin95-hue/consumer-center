#!/usr/bin/env bash
# 새 버전을 운영에 올리기 전에 따로 받아서 점검합니다. 운영 코드·DB·서비스는 건드리지 않습니다.
# 사용법: sudo bash /opt/soboru/app/deploy/preview.sh [상품소개서 PDF 경로]
#   새 코드(GitHub main)를 /tmp/soboru-preview에 받고, 운영 DB를 복사한 임시 DB로 화면·AI 상담·PDF 추출을 실제로 돌려 봅니다.
set -euo pipefail
APP=/opt/soboru/app; P=/tmp/soboru-preview; BRANCH="${BRANCH:-main}"
git -C $APP fetch -q origin "$BRANCH"
rm -rf $P; mkdir -p $P
git -C $APP archive "origin/$BRANCH" | tar -x -C $P
echo "점검할 버전: $(git -C $APP log -1 --format='%h %s' "origin/$BRANCH")"
command -v pdftotext >/dev/null || { apt-get install -y -q poppler-utils poppler-data >/dev/null 2>&1 || true; }
/opt/soboru/venv/bin/pip install -q -r $P/requirements.txt
set -a; . /etc/soboru-platform.env; set +a
# AI 키가 소보루 CS 설정에 아직 없으면, AI 서버 설정에서 읽어서 이번 점검에만 씁니다 (화면에 보이지 않음)
if [ -z "${OPENAI_API_KEY:-}" ] && [ -f /opt/soboru-cs/.env ]; then
  OPENAI_API_KEY="$(grep -E '^OPENAI_API_KEY=' /opt/soboru-cs/.env | head -1 | cut -d= -f2- | tr -d '"'"'"' ')"; export OPENAI_API_KEY
fi
PDF="${1:-}"; [ -n "$PDF" ] && PDF="$(readlink -f "$PDF")"
cd $P/platform_app && /opt/soboru/venv/bin/python selftest.py $PDF
