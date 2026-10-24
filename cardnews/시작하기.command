#!/bin/bash
# 맥: 이 파일을 더블클릭하면 소보루 카드뉴스 만들기가 켜지고 브라우저가 열려요. (리눅스: bash 시작하기.command)
cd "$(dirname "$0")" || exit 1
command -v python3 >/dev/null || { echo "Python이 없어요. https://www.python.org/downloads/ 에서 설치한 뒤 다시 열어 주세요."; read -r; exit 1; }
if [ ! -x .venv/bin/python ]; then
  echo "처음 한 번만 준비하고 있어요 (1~2분)..."
  python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt || { echo "준비하다 멈췄어요. 인터넷 연결을 확인하고 다시 열어 주세요."; read -r; exit 1; }
fi
.venv/bin/pip install -q -r requirements.txt >/dev/null 2>&1
exec .venv/bin/python server.py
