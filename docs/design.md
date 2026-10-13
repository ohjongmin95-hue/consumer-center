# 소보루 디자인 규격

사장님 화면은 모두 같은 규격을 써요. 본사 관리자 화면에도 이 규격을 그대로 쓰면 돼요.
규격은 `platform_app/static/hanq.css` 맨 아래 "소보루 디자인 규격" 묶음에 있어요.

## 색 (기존 값 그대로)
| 변수 | 쓰는 곳 |
|---|---|
| `--accent` 귤색 | 주 버튼, 선택된 메뉴, 강조 숫자 |
| `--accent-soft` / `--accent-ink` | 선택된 메뉴 배경과 글자, 브리핑 카드 |
| `--brand` 갈색 | 로고 글자 |
| `--bg` 밝은 회색 | 화면 배경 |
| `--card` 흰색 | 카드, 표, 메뉴 |
| `--fg` `--fg2` `--fg3` | 제목, 본문, 보조 설명 |
| `--green` `--red` `--blue` (+ `-soft`) | 상태 배지 |

## 크기 변수 (`--ds-*`)
| 변수 | PC | 휴대폰(760px 미만) |
|---|---|---|
| `--ds-side` 왼쪽 메뉴 폭 | 224px | 없음 (아래 고정 메뉴) |
| `--ds-max` 본문 최대 폭 | 1200px, 남는 공간에서 가운데 | 화면 폭 |
| `--ds-pad` 본문 좌우 여백 | 32px | 16px |
| `--ds-gap` 카드 간격 | 16px | 12px |
| `--ds-card-pad` 카드 안 여백 | 22px | 18px |
| `--ds-r-card` / `--ds-r-ctl` 모서리 | 16px / 12px | 같음 |
| `--ds-h-btn` / `--ds-h-btn-sm` 버튼 높이 | 44px / 36px | 48px / 36px |
| `--ds-fs-title` `--ds-fs-h2` `--ds-fs-body` `--ds-fs-sub` | 26 / 18 / 15 / 13.5px | 22 / 18 / 15 / 13.5px |
| `--ds-fs-num` 숫자 카드 | 24px | 22px |
| `--ds-fs-badge` 상태 배지 | 12.5px | 같음 |

## 공통 부품 (클래스)
- 버튼: `.btn` (주), `.btn.gray` (보조), `.btn.sm` (작은 버튼)
- 입력창: `.inp` (input, select, textarea 공통)
- 카드·패널: `.panel` + 제목 `.ph`, 목록 카드 `.list` > `.li`, 상세 2단 `.cols` (본문 + 오른쪽 340px)
- 숫자 카드: `.sumrow` > `a` (`span` 설명, `b` 숫자)
- 상태 배지: `.pill` + `.acc` `.ok` `.bad` `.gray` `.blue`
- 검색·필터: `.searchbar`, `.tabs` > `a.on`
- 표: `.tbl-wrap` > `.tbl2` (행 높이 52px, `tr[data-href]` 누르면 상세로)
- 알림창: `.flash.ok` / `.flash.error`, 주의 배너 `.warn`
- 빈 화면: `.empty-card`, 카드 안 빈 상태 `.hempty`
- 메뉴: PC `.bside`, 휴대폰 아래 고정 메뉴 `.mbar` (홈 / 요청 / 승인 / 자동 응대 / 전체), 위쪽 알림 `.bell`

## 화면 폭
360, 390, 768, 1024, 1440, 1920px에서 가로 스크롤이 없는지 확인해요.
- 1024px 이상: 왼쪽 메뉴
- 1024px 미만: 위쪽 알림 + 아래 고정 메뉴
- 1200px 미만: 요청 상세의 오른쪽 패널이 본문 아래로 내려가요.
