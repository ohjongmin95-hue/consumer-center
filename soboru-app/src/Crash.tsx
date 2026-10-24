// 앱이 꺼지는 대신 오류 내용을 화면에 보여 준다 (화면을 찍어 보내면 원인을 바로 알 수 있게).
// 화면 그리기 오류는 ErrorBoundary가, 그 밖의 자바스크립트 오류는 전역 처리기가 받는다.
import { Component, type ReactNode, useEffect, useState } from 'react';
import * as SplashScreen from 'expo-splash-screen';
import { Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

type Listener = (e: Error) => void;
let last: Error | null = null;
const listeners = new Set<Listener>();

export function report(e: unknown) {
  last = e instanceof Error ? e : new Error(String(e));
  listeners.forEach((l) => l(last as Error));
}

// RN 기본 처리기는 치명 오류에서 앱을 닫으므로, 치명 오류는 화면에 띄우고 닫지 않는다
const g = globalThis as { ErrorUtils?: { getGlobalHandler: () => (e: unknown, fatal?: boolean) => void; setGlobalHandler: (h: (e: unknown, fatal?: boolean) => void) => void } };
if (g.ErrorUtils) {
  const prev = g.ErrorUtils.getGlobalHandler();
  g.ErrorUtils.setGlobalHandler((e, fatal) => {
    if (fatal) report(e);
    else prev(e, fatal);
  });
}

function Screen({ error, onRetry }: { error: Error; onRetry: () => void }) {
  useEffect(() => { SplashScreen.hideAsync().catch(() => {}); }, []);
  return (
    <View style={s.wrap}>
      <Text style={s.title}>앱에 문제가 생겼어요</Text>
      <Text style={s.body}>이 화면을 찍어서 보내 주시면 바로 고칠게요.</Text>
      <ScrollView style={s.box}>
        <Text style={s.code} selectable>{`${Platform.OS} ${Platform.Version}\n${error.name}: ${error.message}\n\n${(error.stack || '').slice(0, 1500)}`}</Text>
      </ScrollView>
      <Pressable style={s.btn} onPress={onRetry} accessibilityRole="button">
        <Text style={s.btnText}>다시 시도</Text>
      </Pressable>
    </View>
  );
}

class Boundary extends Component<{ children: ReactNode; onError: (e: Error) => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e: Error) { this.props.onError(e); }
  render() { return this.state.failed ? null : this.props.children; }
}

export default function CrashGuard({ children }: { children: ReactNode }) {
  const [error, setError] = useState<Error | null>(last);
  const [key, setKey] = useState(0);
  useEffect(() => {
    const l: Listener = (e) => setError(e);
    listeners.add(l);
    return () => { listeners.delete(l); };
  }, []);
  if (error) return <Screen error={error} onRetry={() => { last = null; setError(null); setKey((k) => k + 1); }} />;
  return <Boundary key={key} onError={report}>{children}</Boundary>;
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: '#FFFFFF', padding: 24, paddingTop: 72 },
  title: { fontSize: 20, fontWeight: '700', color: '#1F1A17', marginBottom: 8 },
  body: { fontSize: 15, color: '#6B625B', marginBottom: 16 },
  box: { flex: 1, backgroundColor: '#F6F3F0', borderRadius: 12, padding: 12, marginBottom: 16 },
  code: { fontSize: 12, color: '#3A332E', fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },
  btn: { backgroundColor: '#EF7300', borderRadius: 12, paddingVertical: 14, alignItems: 'center', marginBottom: 24 },
  btnText: { color: '#FFFFFF', fontSize: 16, fontWeight: '700' },
});
