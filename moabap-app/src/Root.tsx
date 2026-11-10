// 맨 바깥: 오류 화면(Crash)을 먼저 깔고 앱을 불러온다. 앱을 불러오다 난 오류도 화면에 보이게 require로 늦게 부른다.
import type { ComponentType } from 'react';
import CrashGuard, { report } from './Crash';

let App: ComponentType | null = null;
try {
  App = require('./App').default;
} catch (e) {
  report(e);
}

export default function Root() {
  return <CrashGuard>{App ? <App /> : null}</CrashGuard>;
}
