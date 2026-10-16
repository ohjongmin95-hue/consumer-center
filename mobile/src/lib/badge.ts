// 승인할 요청 수: 홈·승인 화면이 불러올 때마다 바꾸고, 위 종 모양과 아래 '승인' 탭이 같이 본다 (웹 머리글의 종과 같은 숫자)
import { useSyncExternalStore } from 'react';

let n = 0;
let known = false;
const subs = new Set<() => void>();
export const pendingKnown = () => known;
export function setPending(v: number) {
  known = true;
  if (v === n) return;
  n = v;
  subs.forEach((f) => f());
}
export function usePending() {
  return useSyncExternalStore(
    (f) => (subs.add(f), () => subs.delete(f)),
    () => n,
    () => n,
  );
}
