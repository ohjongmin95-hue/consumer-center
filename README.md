# 소비자제보센터 (consumerjebo.co.kr)

소비자 피해를 제보받고, 진행 단계를 알려 주고, 소비자끼리 경험을 나누는 사이트입니다.
Python(Flask) 한 개 앱과 SQLite 파일 하나로 돌아가서, 리눅스 서버 한 대만 있으면 어디서든 운영할 수 있습니다.

- [주요 기능](#주요-기능)
- [폴더 구조](#폴더-구조)
- [내 컴퓨터에서 실행하기](#내-컴퓨터에서-실행하기)
- [새 서버에 설치하기](#새-서버에-설치하기)
- [코드 업데이트](#코드-업데이트)
- [설정값](#설정값-etcsoboruenv)
- [백업과 복원, 서버 옮기기](#백업과-복원-서버-옮기기)
- [관리자 화면](#관리자-화면)
- [자주 하는 작업](#자주-하는-작업)

## 주요 기능

| 기능 | 주소 | 설명 |
| --- | --- | --- |
| 메인 화면 | `/` | 일러스트 히어로, 최신 제보 카드(30초마다 갱신), 게시판 글, 처리 절차, FAQ. 블록 순서·표시 개수는 관리자에서 변경 |
| 제보하기 | `/report` | 동의(필수·선택) 후 접수, 공개/비밀글 선택, 증빙 1개 첨부. 접수번호와 비밀 조회 코드 발급 |
| 소비자 제보 목록 | `/reports` | 모든 제보를 진행 단계와 함께 표시. 공개 제보만 열람 가능(전화번호·이메일 자동 가림) |
| 내 제보 조회 | `/lookup` | 접수번호 + 조회 코드로 진행 상황 확인, 추가 메시지 |
| 이용 안내 · 처리 절차 · 제보 유형 · FAQ | `/guide` `/process` `/types` `/faq` | 문구·항목 모두 관리자에서 수정 |
| 소비자게시판 | `/board` | 글·댓글·공감·부적절 알림(5건 쌓이면 자동 숨김). 비회원은 닉네임+삭제 비밀번호 |
| 회원 | `/signup` `/login` `/me` | 약관·개인정보·만 14세 동의 후 가입, 내 제보·내 글 모아 보기, 비밀번호 변경, 탈퇴 |
| 정책 | `/terms` `/privacy` `/youth` `/takedown` | 이용약관, 개인정보 처리방침, 청소년보호정책, 권리침해 신고(게시중단 요청) |
| 기업 답변 | `/company/...` | 기자가 만든 1회용 링크로 기업이 답변 (제보자가 기업 전달에 동의한 경우만) |
| 관리자 · 기자실 | `/admin` `/reporter` | 사이트 관리(대표)와 제보 처리(기자) 화면 |
| 검색 등록 | `/robots.txt` `/sitemap.xml` | 네이버·구글·다음 사이트 확인 코드는 관리자에서 입력 |

## 폴더 구조

```
app.py               모든 화면(주소)과 기능. 제보·게시판·회원·관리자
site_content.py      관리자에서 고칠 수 있는 문구·목록의 목록과 기본값
list_defaults.json   이용 안내 페이지 목록의 기본값
policies/            이용약관·개인정보 처리방침·청소년보호·권리침해 안내 기본 문구
templates/           화면(HTML). base.html = 공통 머리·바닥글
static/style.css     디자인 전체
static/img/          메인 일러스트(tools/make_hero_art.py), 이용 안내 만화 3컷(tools/guide_illustrations.py)
tests/test_site.py   자동 테스트 (임시 DB 사용, 실제 데이터에 영향 없음)
deploy/setup.sh      새 서버 설치 스크립트
deploy/update.sh     코드 업데이트 스크립트
.env.example         서버 설정값 예시
preview/             예전 디자인 시안 (사이트에는 쓰이지 않음)
docs/ROADMAP.md      앞으로 할 일과 아이디어 메모
```

실제 데이터(DB, 첨부파일)는 코드와 따로 서버의 `/var/lib/soboru`에 있고, 저장소(GitHub)에는 올라가지 않습니다.

## 내 컴퓨터에서 실행하기

Python 3.10 이상이 필요합니다.

```sh
git clone https://github.com/ohjongmin95-hue/consumer-center.git
cd consumer-center
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 테스트
.venv/bin/python -m unittest discover -s tests -v

# 실행 → http://127.0.0.1:8000
SECRET_KEY=dev ADMIN_PASSWORD_HASH="$(.venv/bin/python -c "from werkzeug.security import generate_password_hash as g;print(g('admin1234'))")" \
ENABLE_INTAKE=1 ENABLE_BOARD=1 .venv/bin/gunicorn --bind 127.0.0.1:8000 app:app
```

관리자는 `http://127.0.0.1:8000/admin/login`, 비밀번호는 위에서 정한 `admin1234`입니다.
내 컴퓨터에서는 DB가 폴더 안 `cases.sqlite3`로 만들어집니다.

## 새 서버에 설치하기

Ubuntu 22.04/24.04 서버 한 대 기준입니다 (지금은 네이버 클라우드 `soboru-web`, 공인 IP 211.233.198.1).

1. 서버 방화벽(네이버 클라우드는 ACG)에서 80, 443 포트를 열고, 22(SSH)는 내 IP만 허용합니다.
2. 가비아 DNS에 `A @ → 서버 공인 IP`, `A www → 서버 공인 IP`를 넣습니다.
3. 서버에 접속해 실행합니다.

```sh
curl -fsSL https://raw.githubusercontent.com/ohjongmin95-hue/consumer-center/main/deploy/setup.sh -o setup.sh
sudo bash setup.sh consumerjebo.co.kr 연락받을이메일@example.com
```

- 중간에 관리자 비밀번호(12자 이상)를 묻습니다. 비밀 값은 `/etc/soboru.env`에만 저장됩니다.
- `main`이 아닌 브랜치를 설치하려면 `sudo BRANCH=브랜치이름 bash setup.sh ...`
- DNS가 아직 반영 전이면 HTTPS를 건너뜁니다. 반영된 뒤 같은 명령을 다시 실행하면 됩니다. 다시 실행해도 데이터와 설정은 유지됩니다.
- 설치 직후 제보 접수와 게시판은 꺼져 있습니다. 아래 [설정값](#설정값-etcsoboruenv)에서 켭니다.

## 코드 업데이트

GitHub에 새 코드가 올라간 뒤 서버에서:

```sh
sudo bash /opt/soboru/app/deploy/update.sh
```

서버에 설치된 브랜치의 최신 코드를 받아 앱을 다시 시작합니다. 오류가 나면 최근 로그를 보여 줍니다.
로그 계속 보기: `sudo journalctl -u soboru -f`

## 설정값 (`/etc/soboru.env`)

| 이름 | 뜻 |
| --- | --- |
| `SECRET_KEY` | 로그인 쿠키 서명 비밀키. 바꾸면 모든 로그인이 풀립니다 |
| `ADMIN_PASSWORD_HASH` | 관리자 비밀번호의 해시값 |
| `DATABASE_PATH`, `UPLOAD_DIR` | DB 파일, 첨부파일 폴더 위치 |
| `TRUST_PROXY=1` | nginx 뒤에서 실행 중임을 알림 |
| `HTTPS_ONLY=1` | HTTPS 인증서가 붙은 뒤 켬 (setup.sh가 자동 설정) |
| `ENABLE_INTAKE=1` | 제보 접수 켜기 |
| `ENABLE_BOARD=1` | 게시판 글쓰기·공감·댓글 켜기 |

회원가입·로그인은 `SECRET_KEY`가 있으면 자동으로 켜집니다. 예시는 `.env.example`에 있습니다.

```sh
sudo nano /etc/soboru.env         # 고치고 저장 (Ctrl+O, Enter, Ctrl+X)
sudo systemctl restart soboru     # 적용
```

**관리자 비밀번호 바꾸기**

- 평소: 관리자 화면 오른쪽 위 **비밀번호 변경** → 지금 비밀번호, 새 비밀번호(영문+숫자 12자 이상) 입력. 다른 기기의 관리자 로그인은 자동으로 끊깁니다.
- 잊어버렸을 때: 서버에 접속해 `sudo bash /opt/soboru/app/deploy/reset-admin-password.sh` 를 실행하고 새 비밀번호를 두 번 입력합니다.

## 백업과 복원, 서버 옮기기

- 매일 자동 백업: `/var/lib/soboru/backups/` (DB `cases-날짜.sqlite3`, 첨부 `uploads-날짜.tar.gz`, 14일치 보관)
- 지금 바로 백업: `sudo /etc/cron.daily/soboru-backup`

**다른 서버로 옮기기**

1. 새 서버에서 [새 서버에 설치하기](#새-서버에-설치하기)를 그대로 진행합니다.
2. 예전 서버에서 데이터를 묶습니다.
   ```sh
   sudo systemctl stop soboru
   sudo tar -czf ~/soboru-data.tar.gz -C /var/lib/soboru cases.sqlite3 uploads
   sudo cp /etc/soboru.env ~/soboru.env
   ```
3. 두 파일을 새 서버로 복사한 뒤(예: `scp`) 새 서버에서 풉니다.
   ```sh
   sudo systemctl stop soboru
   sudo tar -xzf ~/soboru-data.tar.gz -C /var/lib/soboru
   sudo cp ~/soboru.env /etc/soboru.env
   sudo chown -R soboru:soboru /var/lib/soboru
   sudo systemctl start soboru
   ```
   `soboru.env`를 그대로 옮기면 관리자 비밀번호와 회원 로그인이 그대로 유지됩니다.
4. 가비아 DNS의 IP를 새 서버로 바꾸고, 반영 후 `sudo bash setup.sh 도메인 이메일`을 한 번 더 실행해 HTTPS를 붙입니다.

## 관리자 화면과 제보 처리 화면

화면이 둘로 나뉘어 있습니다.

**관리자 (대표)** `https://consumerjebo.co.kr/admin/login` (하단 "대표. 오○○"의 첫 글자를 눌러도 들어갑니다)

| 메뉴 | 하는 일 |
| --- | --- |
| 홈 | 새 제보·처리 중 제보·회원·확인할 게시글·게시중단 요청 현황, 단계별 제보 수 |
| 제보 처리 | 관리자 화면 안의 제보 목록·상세 (기자실과 같은 기능, 처리 기록에는 "대표"로 남음) |
| 사이트 문구 | 모든 문구, 하단 정보(상호·대표·연락처 등), 약관·처리방침 본문, 검색 확인 코드 |
| 메뉴·항목 | 메뉴 이름·순서, 메인 화면 블록 배치, 제보 유형, 게시판 분류, FAQ, 처리 절차 등 |
| 게시판 | 알림 들어온 글·댓글 숨기기, 다시 보이기, 삭제 |
| 회원 | 회원 검색, 이용 정지·해제, 삭제 |
| 게시중단 요청 | 권리침해 신고 처리 상태 기록 |
| 기자 계정 | 기자 계정 만들기, 비밀번호 재설정, 사용 중지, 삭제 |

**소보루 기자실 (기자 전용)** `https://consumerjebo.co.kr/reporter/login`

- 관리자 화면과 주소·화면·로그인이 완전히 따로입니다. 관리자로 로그인해 있어도 기자실은 기자 아이디로 따로 로그인해야 하고, 관리자 메뉴는 보이지 않습니다.

- 대표가 "기자 계정"에서 만든 아이디로 로그인합니다. 관리자 메뉴는 볼 수 없습니다.
- 제보 목록: 단계별 보기, 검색, 내 담당 제보 보기
- 제보 상세: 진행 단계·담당 기자·공개 여부 변경, 제보자에게 메시지, 내부 메모(작성자 표시), 기업 답변 링크 만들기, 첨부파일 받기, 처리 기록(누가 언제 무엇을 바꿨는지)
- 비밀번호는 기자가 "비밀번호 변경"에서 직접 바꿉니다. 잊으면 대표가 재설정합니다.

문구는 비워 두거나 기본값과 같게 저장하면 기본 문구로 돌아갑니다.

관리자 홈의 **사이트에서 바로 고치기**를 누르면 사이트 화면에서 점선 문장을 눌러 바로 고칠 수 있고, 아래 막대의 '페이지 이동'으로 모든 페이지를 돌아볼 수 있습니다. 이용 안내·처리 절차·FAQ·제보 유형 페이지의 섹션 순서·삭제·글 상자 추가는 **메뉴·항목 > ○○ 페이지 구성**, 새 페이지(`/p/영문주소`)는 **메뉴·항목 > 새 페이지**에서 합니다.

사이트에 보이는 버튼·안내·알림 문구는 모두 관리자 **사이트 문구**에서 바꿀 수 있습니다(위쪽 검색창으로 찾기). 개발할 때 새 문구는 템플릿에 `{{ ui('키', '기본 문구') }}`로 적으면 관리자 화면에 자동으로 칸이 생깁니다. 굵게가 필요한 문구는 `ui_rich`, 파이썬 코드의 알림은 `ui_text`를 씁니다.

## 자주 하는 작업

- **메인 일러스트 다시 만들기**: `python3 tools/make_hero_art.py` → `static/img/`의 SVG가 바뀝니다 (방문자 브라우저 캐시는 자동으로 갱신)
- **이용 안내 만화 3컷 다시 그리기**: `python3 tools/guide_illustrations.py` → `static/img/guide-cut1~3.svg`가 바뀝니다. 컷 아래 문장, 단계 카드, 업종별 안내는 사이트 편집 모드나 **구성 바꾸기 > 이용 안내 · …**에서 고칩니다.
- **약관 기본 문구 고치기**: `policies/*.txt` 수정. 단, 관리자에서 직접 고쳐 저장한 적이 있으면 그 내용이 우선합니다
- **디자인 수정**: `static/style.css`. 수정 후 `app.py`의 `css_v` 숫자를 올리면 방문자에게 바로 반영됩니다
- **수정 후 확인**: `python3 -m unittest discover -s tests` 가 모두 OK인지 확인한 뒤 올립니다
