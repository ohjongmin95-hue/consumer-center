# 소비자제보센터 · SOBORU.

Flask와 SQLite로 동작하는 소비자 제보 사이트입니다. 사이트 문구, 운영자 정보, 이용약관, 개인정보 처리방침은 관리자 화면(`/admin/content`)에서 수정합니다. 실제 메인 화면은
`templates/index.html`, 공통 헤더는 `templates/base.html`, 스타일은
`static/style.css`에 있습니다. `static/soboru-functional-pages.html`은 별도 HTML 시안입니다.

## 개발

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/gunicorn --workers 1 --bind 127.0.0.1:8000 app:app
```

제보 접수는 기본적으로 비활성화됩니다. 테스트는 별도의 임시 데이터베이스에서
접수·조회·관리자 승인·기업 답변과 공개 목록 필터를 검증합니다.

## 서버 배포 (AWS Lightsail 서울 · Ubuntu)

서버 한 대에 앱, SQLite 데이터, 첨부파일, 매일 백업, HTTPS를 함께 둡니다.

1. Lightsail에서 서울 리전 Ubuntu 24.04 인스턴스를 만들고 고정 IP(Static IP)를 연결합니다.
   네트워킹 탭 방화벽에 HTTPS(443)를 추가합니다.
2. 가비아 DNS에 `A @ → 고정 IP`, `A www → 고정 IP` 레코드를 추가합니다.
3. 브라우저 SSH에서 실행합니다.

```sh
curl -fsSL https://raw.githubusercontent.com/ohjongmin95-hue/consumer-center/main/deploy/setup.sh -o setup.sh
sudo bash setup.sh 도메인 이메일
```

- 관리자 비밀번호를 묻고, 비밀 값은 `/etc/soboru.env`에만 저장합니다.
- 데이터: `/var/lib/soboru` (DB, 첨부파일, `backups/`에 14일치 매일 백업)
- DNS가 반영되기 전이면 HTTPS를 건너뜁니다. 반영된 뒤 같은 명령을 다시 실행합니다.
- 코드 업데이트: `sudo bash /opt/soboru/app/deploy/update.sh`
- 로그: `sudo journalctl -u soboru -f`
- 제보 접수는 `/etc/soboru.env`의 `ENABLE_INTAKE=1`로 켜고 `sudo systemctl restart soboru`로 적용합니다.
