# 소비자신고센터 · SOBORU.

Flask와 SQLite로 동작하는 소비자 신고 사이트입니다. 실제 메인 화면은
`templates/index.html`, 공통 헤더는 `templates/base.html`, 스타일은
`static/style.css`에 있습니다. `static/soboru-functional-pages.html`은 별도 HTML 시안입니다.

## 개발

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/gunicorn --workers 1 --bind 127.0.0.1:8000 app:app
```

신고 접수는 기본적으로 비활성화됩니다. 테스트는 별도의 임시 데이터베이스에서
접수·조회·관리자 승인·기업 답변과 공개 목록 필터를 검증합니다.

## 기존 Render 서비스 배포

사이트: https://consumer-center.onrender.com/

Render의 기존 `consumer-center` Web Service에서 아래 항목을 확인합니다.
새 서비스를 생성할 필요는 없습니다.

- 연결 저장소: `ohjongmin95-hue/consumer-center`
- 배포 브랜치: `main`
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn --workers 1 --bind 0.0.0.0:$PORT app:app`
- Auto-Deploy가 활성화되어 있으면 `main` 푸시 후 배포됩니다.
- 자동 배포가 꺼져 있으면 `Manual Deploy → Deploy latest commit`을 사용합니다.

배포 완료 후 `/`, `/guide`, `/process`, `/types`, `/faq`, `/report`, `/lookup`을 확인합니다.
메인 화면에는 “여러분의 신고가 권익 보호의 시작입니다.”와 오른쪽 정렬 메뉴가 표시됩니다.

기존 환경변수와 데이터 저장 경로를 유지하세요. `DATABASE_PATH`와 `UPLOAD_DIR`은
SQLite 파일과 첨부파일 경로입니다. 실제 접수 데이터를 유지하려면 Render의 영구 저장소를
사용해야 합니다. 기본 로컬 파일시스템은 재배포 때 유지되지 않을 수 있습니다.
`ENABLE_INTAKE=1`로 접수를 켜려면 `SECRET_KEY`와 `ADMIN_PASSWORD_HASH`가 필요합니다.
비밀 값은 Render 환경변수에만 입력하고 Git에 저장하지 않습니다.
