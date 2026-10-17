# 예전 소비자제보센터 화면 보관·복원 안내

2026-10-17 운영자 요청으로 사이트를 **소보루 하나**로 정리하면서 예전 "소비자제보센터" 브랜드 화면을 뺐습니다.
지운 코드는 사라진 것이 아니라 git 태그에 그대로 남아 있습니다.

## 보관 위치

- 태그: **`jebo-center-final`** (커밋 `7353589`, 2026-10-17 main)
- 이 태그에는 브랜드를 고르던 시절의 완성본이 통째로 들어 있습니다. `site.brand`를 비우면 소비자제보센터, "소보루"라고 적으면 소보루 화면이 나오던 코드입니다.
- 같은 커밋을 가리키는 가지(branch) **`jebo-center-final-snapshot`** 도 올려 둠. 태그가 원격에 없으면 `origin/jebo-center-final-snapshot` 으로 바꿔 쓰면 됨 (`git fetch origin jebo-center-final-snapshot`)

## 보는 법

```sh
git fetch origin --tags
git show jebo-center-final:templates/index.html          # 파일 하나 내용 보기
git diff jebo-center-final -- templates/base.html         # 지금과 무엇이 달라졌는지 보기
git checkout jebo-center-final                            # 예전 사이트 전체를 잠깐 띄워 보기 (끝나면 git checkout main)
```

## 되살리는 법

파일 하나만 되살리기:

```sh
git checkout jebo-center-final -- templates/index.html
```

예전 브랜드 바꾸기까지 통째로 되살리려면 아래 파일을 태그에서 가져오고(`git checkout jebo-center-final -- 파일들`) 테스트를 돌려 맞춥니다.
`soboru.py`(brand·is_soboru·apply_brand·home), `site_content.py`(site.brand·로고 칸·menu·home_blocks·sample_reports), `app.py`(home·menu_href·sample_fill·home_latest), `templates/base.html`, 아래 "뺀 것"의 템플릿.

## 뺀 것

| 무엇 | 어디 |
|---|---|
| 예전 메인 화면 (사람들 일러스트 + "여러분의 제보가 권익 보호의 시작입니다") | `templates/index.html` |
| 소보루 예전 홈 비교 화면 (`/?look=old`), 맨 위 큰 카드 돌리기 | `templates/soboru_home.html`, soboru.py `pick_top`·`plan_tick` |
| 예전 메인 최근 제보 카드(영수증 모양)·예시 카드 | `templates/report_cards.html`, `/reports/latest?view=cards`, 목록 `sample_reports` |
| 메인 화면 순서 화면 | `templates/admin_home_plan.html` (주소 `/admin/home-plan`은 화면 편집으로 넘어감) |
| 예전 머리글(주황 "소비자" + "제보센터" 글자 로고, 상단 메뉴)·바닥글 로고 | `templates/base.html` |
| 예전 게시판·글 보기·글쓰기·공개 제보 화면 (소보루가 아닐 때 쓰던 부분) | `board.html`, `board_post.html`, `board_write.html`, `public_case.html`의 `else` 부분 |
| 관리자 설정: 브랜드(`site.brand`), 로고 앞·뒤·작은 글씨(`site.logo_*`), 메인 문구(`home.hero_title`), 메인 최근 제보 수·제목 | `site_content.py` |
| 관리자 > 구성 바꾸기: 상단 메뉴(`menu`), 메인 화면 구성(`home_blocks`), 메인 예시 제보 카드(`sample_reports`) | `site_content.py` LISTS |
| 관리자 미리보기 `?brand=soboru` / `?brand=off` | soboru.py `apply_brand` |
| 로그인·관리자·기업 화면의 예전 글자 로고 | `auth_logo.html`, `console.html`, `biz_base.html`, `biz_signup.html` |

## 남겨 둠 (소보루도 쓰거나, 빼면 위험해서)

- 제보 기능 전체(제보하기·제보 목록·공개 제보·내 제보 조회·기업 답변·이용 안내·처리 절차·FAQ·약관): 소보루도 그대로 씀
- 저장된 문구 속 "소비자제보센터"는 화면에 낼 때 "소보루"로 바꿔 보여 줌 (약관 원문 `policies/*.txt`, AI 초안 문구 `triage.py`·`companydesk.py`, `notify.py`)
- `static/style.css`의 예전 머리글·카드 모양, `static/img/hero-left.svg`·`hero-right.svg`, `tools/make_hero_art.py`: 지워도 되지만 소보루 화면이 같은 CSS 파일을 같이 써서 손대지 않음
- app.py `home_groups`, `recent_posts`, `block_count`, `GUIDE_ICONS`(이용 안내 아이콘 고르기): 다른 화면이나 관리자 칸이 같이 씀
- 관리자 화면 이용 안내·처리 절차·FAQ 페이지 구성(`layout_*`): 소보루 제보 메뉴에서 그대로 씀
- `tools/site_vrt_server.py`의 `VRT_BRAND`: 넣어도 아무 일 없음 (예전 설정값은 무시)
- DB의 예전 설정값: 한 번만 지움(`soboru_settings.brand_only`). 소보루 시절 화면에 안 보이던 값(브랜드·로고 글자·사이트 이름·메인 제목·사이트 설명·게시판 제목)만

## 2026-10-17 되살림: 주소별 화면

운영자 요청으로 소비자제보센터 화면을 다시 넣었습니다. 이번에는 관리자 설정이 아니라 **들어온 주소**로 화면이 정해집니다.

- 서버 설정 `JEBO_HOST=consumerjebo.co.kr`이면 그 주소는 소비자제보센터 화면(예전 메인·머리글·게시판), 나머지(soboru.co.kr)는 소보루 화면
- 제보·회원·게시판·관리자는 하나라서 어느 쪽에서 접수해도 두 사이트에 같이 보임 (공개 규칙은 같음)
- 이름·제목은 관리자 > 숨은 문구 > "소비자제보센터 화면" (`jebo.*`, `site.logo_*`), 메뉴·메인 구성은 관리자 > 구성 바꾸기
- 관리자는 `/?face=jebo`로 미리 보고 `/?face=off`로 끔
- 켜고 끄기: `deploy/soboru-main.sh --jebo-on` / `--jebo-off`
