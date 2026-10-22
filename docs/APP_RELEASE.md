# 소보루 앱 출시 안내

사이트(consumerjebo.co.kr)를 그대로 감싸는 앱입니다. 안드로이드는 **TWA(Trusted Web Activity)**, 아이폰은 나중에 **Capacitor**로 포장합니다.
화면·기능을 고치면 앱을 다시 올리지 않아도 바로 반영돼요.

> `mobile/` 폴더의 Expo 앱(소보루 CS, `kr.co.soboru.cs`)과는 다른 앱입니다. 이 앱의 패키지 이름은 `kr.co.consumerjebo.soboru`예요.

## 사이트에 이미 들어간 것

| 항목 | 주소·파일 | 비고 |
|---|---|---|
| 앱 설치 정보 | `/static/manifest.webmanifest` | 시작 주소 `/?src=app`, 범위 `/`, 아이콘 192·512 |
| 서비스 워커 | `/sw.js` | 끊기면 `/offline` 안내. 정적 파일만 저장, 회원·관리자 화면은 저장 안 함 |
| 앱 주인 확인 | `/.well-known/assetlinks.json` | 지문을 넣기 전에는 404 (정상) |
| 아이폰 링크 확인 | `/.well-known/apple-app-site-association` | Team ID를 넣기 전에는 404 |
| 신고·차단(UGC) | 글·댓글의 더 보기(…) 메뉴, 내 정보 > 차단한 사용자 | 약관에 무관용·24시간 조치 문구 |
| 알림함·푸시 | 머리글 종, `/me/alerts` | 키를 넣어야 푸시 켜짐 |
| Apple로 로그인 | 로그인 화면 | 키를 넣어야 버튼이 보임 |
| 회원 탈퇴 | 내 정보 > 회원 정보 > 회원 탈퇴 | 앱 안에서 바로 탈퇴 (심사 필수) |

## 서버에서 할 일 (한 번)

```bash
sudo bash /opt/soboru/app/deploy/update.sh     # requirements.txt(pywebpush·cryptography) 설치까지
sudo bash /opt/soboru/app/deploy/set-push.sh   # 웹 푸시 키를 서버에서 새로 만들어 저장
```

## 안드로이드 (지금)

### 1. Play Console 계정
- **조직 계정**으로 만드세요 (play.google.com/console, 등록비 25달러). 사업자 정보와 **D-U-N-S 번호**가 필요해요(없으면 dnb.com에서 무료 신청, 1~2주).
- 2023년 11월 뒤에 만든 개인 계정은 출시 전에 테스터 12명이 14일 동안 비공개 테스트를 해야 해서 조직 계정이 빠릅니다.

### 2. 앱 만들기 — Bubblewrap (추천)
컴퓨터에 Node.js 18 이상과 JDK 17이 있어야 해요. 처음 실행하면 안드로이드 SDK를 알아서 받아요.

```bash
npm i -g @bubblewrap/cli
mkdir soboru-twa && cd soboru-twa
bubblewrap init --manifest https://consumerjebo.co.kr/static/manifest.webmanifest
```

물어보는 값은 이렇게 넣으세요.

| 질문 | 값 |
|---|---|
| Domain | `consumerjebo.co.kr` |
| URL path (start URL) | `/?src=app` |
| Application name / Short name | `소보루` / `소보루` |
| Application ID (패키지 이름) | `kr.co.consumerjebo.soboru` |
| Display mode | `standalone` |
| Status bar / Navigation bar color | `#FFFFFF` |
| Splash screen color | `#FFFFFF` |
| Icon URL / Maskable icon URL | `https://consumerjebo.co.kr/static/soboru-app-512.png` |
| Include support for Play Billing | `No` |
| Request geolocation permission | `No` |
| Enable notifications (알림 위임) | `Yes` — 웹 푸시가 안드로이드 알림으로 와요 |
| Signing key | 새로 만들기 (`android.keystore`, 비밀번호는 따로 안전하게 보관) |

```bash
bubblewrap build          # app-release-bundle.aab 생성
```

**대안 — PWABuilder:** pwabuilder.com에 `https://consumerjebo.co.kr` 입력 → Package for stores → Android → 위 표와 같은 값(Package ID `kr.co.consumerjebo.soboru`) → 받은 zip 안의 `.aab`를 올리고 서명 키 파일은 잘 보관하세요.

### 3. Play Console에 올리기
1. 앱 만들기 → 테스트 > **내부 테스트**에 `.aab` 업로드 (**Play 앱 서명** 사용, 기본값).
2. 설정 > **앱 무결성 > 앱 서명**에서 **앱 서명 키 인증서 SHA-256 지문**을 복사.
   (내 컴퓨터에서 만든 apk도 시험하려면 업로드 키 지문도 함께 — `bubblewrap fingerprint` 또는 `keytool -list -v -keystore android.keystore`)
3. 서버에서 지문 넣기 (여러 개면 쉼표):
   ```bash
   sudo bash /opt/soboru/app/deploy/set-app.sh
   curl -s https://consumerjebo.co.kr/.well-known/assetlinks.json   # 지문이 보이면 끝
   ```
4. 내부 테스트로 설치해 **주소창이 안 보이면** 성공. 주소창이 보이면 지문이 틀린 거예요.
5. 스토어 등록정보: 개인정보처리방침 `https://consumerjebo.co.kr/privacy`, 계정 삭제 안내 `https://consumerjebo.co.kr/me#withdraw`,
   데이터 보안 양식(이름·전화번호·이메일·사용자 콘텐츠·기기 알림 토큰 수집, 전송 중 암호화, 삭제 요청 가능), 콘텐츠 등급 설문(사용자 간 소통 있음).
6. 프로덕션 출시.

## 아이폰 — `soboru-app/` (Expo)

Capacitor 대신 `soboru-app/` Expo 앱(사이트를 웹뷰로 띄움)으로 갑니다. EAS가 클라우드에서 굽고 올려서 **맥이 없어도 돼요.**
앱이 직접 맡는 것(심사 4.2 '웹사이트만 띄운 앱' 대비): 아래 탭, 푸시 알림(Expo → APNs), 기기 Apple 로그인 창, 공유 시트, 당겨서 새로고침, 오프라인 화면.

| 사이트 쪽 | 내용 |
|---|---|
| 앱 알아보기 | 앱이 사용자 에이전트 끝에 `SoboruApp/버전 (ios|android)`를 붙임 → `appready.app_client()`. 앱에선 웹 탭바를 숨기고 `templates/app_bridge.html`을 넣음 |
| 앱 푸시 | `/me/push/app`이 Expo 토큰을 `push_subscriptions`(endpoint `expo:…`)에 저장, 알림은 Expo 푸시 서버로 (서버 키 필요 없음) |
| Apple 로그인 | 아이폰 앱은 기기 창에서 받은 코드를 `/auth/apple/native`로 보냄. client_id = 번들 ID(`IOS_BUNDLE_ID`, 기본 `kr.co.consumerjebo.soboru`). `set-apple.sh`에서 Services ID는 비워도 됨 |
| 유니버설 링크 | `set-app.sh`에 Team ID를 넣으면 AASA가 열림 (앱의 associatedDomains: soboru.co.kr, consumerjebo.co.kr) |

출시 절차·스토어 문구·심사 메모는 프로젝트 폴더 `app-release/soboru/소보루_앱스토어_출시안내.md`에 있어요.

## 확인할 것
- 약관·개인정보 처리방침은 관리자 화면에서 고쳐 저장한 적이 있으면 이번에 바뀐 기본 문구(무관용·차단·푸시·Apple)가 안 보여요. 관리자 > 사이트 문구에서 확인해 주세요.
- 신고(알리기)된 글은 24시간 안에 관리자 > 게시판에서 처리해 주세요(약관에 적은 약속).
