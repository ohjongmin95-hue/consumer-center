@echo off
rem 윈도우: 이 파일을 더블클릭하면 소보루 카드뉴스 만들기가 켜지고 브라우저가 열려요.
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul || (echo Python이 없어요. https://www.python.org/downloads/ 에서 설치할 때 "Add python.exe to PATH"를 체크해 주세요. & pause & exit /b 1)
if not exist .venv\Scripts\python.exe (
  echo 처음 한 번만 준비하고 있어요 ^(1~2분^)...
  py -3 -m venv .venv || (pause & exit /b 1)
  .venv\Scripts\python -m pip install -q --upgrade pip
  .venv\Scripts\python -m pip install -q -r requirements.txt || (echo 준비하다 멈췄어요. 인터넷 연결을 확인해 주세요. & pause & exit /b 1)
)
.venv\Scripts\python -m pip install -q -r requirements.txt >nul 2>nul
.venv\Scripts\python server.py
pause
