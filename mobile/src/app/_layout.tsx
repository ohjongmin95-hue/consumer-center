import * as Notifications from 'expo-notifications';
import { router, Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { Platform } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StoreProvider } from '../lib/store';
import { C } from '../lib/theme';

// 웹 미리보기에서도 한글이 낱말 단위로 줄바꿈되게
if (Platform.OS === 'web' && typeof document !== 'undefined') {
  const el = document.createElement('style');
  el.textContent = '*{word-break:keep-all;overflow-wrap:anywhere}';
  document.head.appendChild(el);
}

export default function RootLayout() {
  // 알림을 누르면 그 민원 화면으로
  useEffect(() => {
    if (Platform.OS === 'web') return;
    const sub = Notifications.addNotificationResponseReceivedListener((r) => {
      const id = (r.notification.request.content.data as { case_id?: number } | undefined)?.case_id;
      if (id) router.push(`/case/${id}`);
    });
    return () => sub.remove();
  }, []);
  return (
    <SafeAreaProvider>
      <StoreProvider>
        <StatusBar style="dark" />
        <Stack
          screenOptions={{
            headerTintColor: C.fg,
            headerShadowVisible: false,
            headerStyle: { backgroundColor: C.card },
            headerTitleStyle: { fontWeight: '700', fontSize: 17 },
            headerBackButtonDisplayMode: 'minimal',
            contentStyle: { backgroundColor: C.band },
          }}
        >
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="company/[id]" options={{ title: '' }} />
          <Stack.Screen name="new" options={{ title: '민원 접수', headerStyle: { backgroundColor: C.card }, contentStyle: { backgroundColor: C.card } }} />
          <Stack.Screen name="case/[id]" options={{ title: '내 접수' }} />
        </Stack>
      </StoreProvider>
    </SafeAreaProvider>
  );
}
