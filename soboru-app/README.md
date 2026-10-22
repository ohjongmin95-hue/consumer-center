# 소보루 앱 (soboru-app)

소비자용 소보루 사이트(https://soboru.co.kr)를 담은 아이폰·안드로이드 앱. 번들/패키지 ID `kr.co.consumerjebo.soboru`.
사장님용 소보루 CS 앱(`mobile/`, `kr.co.soboru.cs`)과는 다른 앱이에요.

- 화면은 사이트 그대로(웹뷰). 사이트를 고치면 앱을 다시 올리지 않아도 바로 반영돼요.
- 앱이 직접 하는 일: 아래 탭(`src/TabBar.tsx`), 푸시 알림(`src/push.ts`), 아이폰 Apple 로그인, 공유 시트, 오프라인 화면(`src/Offline.tsx`),
  사이트 밖 주소는 앱 안 브라우저로·`kakaotalk://` 같은 주소는 그 앱으로(`src/links.ts`), 안드로이드 뒤로 가기.
- 사이트와 주고받기: 사이트가 앱에서 열리면 `templates/app_bridge.html`의 `window.SoboruApp`이 생기고, 앱은 `postMessage`로 받고 `injectJavaScript`로 답해요.

```bash
npm ci
npx eas-cli@latest init                                   # 처음 한 번 (app.json에 projectId가 들어감)
npx eas-cli@latest build -p ios --profile production       # 아이폰 (.ipa)
npx eas-cli@latest submit -p ios --latest                  # App Store Connect(TestFlight)로 올리기
npx eas-cli@latest build -p android --profile production   # 안드로이드 (.aab)
```

`npx tsc --noEmit`으로 타입 검사.
