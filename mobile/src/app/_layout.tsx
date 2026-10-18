import { router, Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Animated, Image, Platform, StyleSheet, Text, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { AuthProvider, useAuth } from '../lib/auth';
import { Notifications } from '../lib/push';
import { C, FONT } from '../lib/theme';

// 웹 미리보기에서도 한글이 낱말 단위로 줄바꿈되게
if (Platform.OS === 'web' && typeof document !== 'undefined') {
  const el = document.createElement('style');
  el.textContent = '*{word-break:keep-all;overflow-wrap:anywhere}';
  document.head.appendChild(el);
  // 앱에 넣은 프리텐다드는 휴대폰용이라, 웹 미리보기는 같은 글꼴을 공개 배포처에서 읽는다
  const font = document.createElement('link');
  font.rel = 'stylesheet';
  font.href = 'https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/static/pretendard.css';
  document.head.appendChild(font);
}

// 앱을 켜면 하얀 바탕에 소보루 캐릭터(기본 시작 화면) → 같은 자리에 '소보루 CS' 로고 화면 → 로그인 확인이 끝나면 부드럽게 사라진다
SplashScreen.preventAutoHideAsync().catch(() => {});

function Intro() {
  const { ready } = useAuth();
  const [minDone, setMinDone] = useState(false);
  const [gone, setGone] = useState(false);
  const fade = useRef(new Animated.Value(1)).current;
  useEffect(() => {
    const t = setTimeout(() => setMinDone(true), 1000);
    return () => clearTimeout(t);
  }, []);
  useEffect(() => {
    if (ready && minDone) Animated.timing(fade, { toValue: 0, duration: 260, useNativeDriver: Platform.OS !== 'web' }).start(() => setGone(true));
  }, [ready, minDone, fade]);
  if (gone) return null;
  return (
    <Animated.View style={[StyleSheet.absoluteFill, st.intro, { opacity: fade }]} onLayout={() => SplashScreen.hideAsync().catch(() => {})}>
      <Image source={require('../../assets/soboru-char.png')} style={{ width: 120, height: 92 }} resizeMode="contain" />
      <Text style={st.wm}>소보루 CS</Text>
      <Text style={st.sub}>사장님 전용</Text>
      <ActivityIndicator color={C.accent} style={{ marginTop: 36 }} />
      <Text style={st.foot}>고객 응대는 소보루가, 사장님은 확인만</Text>
    </Animated.View>
  );
}

export default function RootLayout() {
  // 알림을 누르면 그 상담 대화방으로
  useEffect(() => {
    if (!Notifications) return;
    const sub = Notifications.addNotificationResponseReceivedListener((r) => {
      const id = (r.notification.request.content.data as { case_id?: number } | undefined)?.case_id;
      router.push(id ? `/chat/${id}` : '/alerts'); // 연결 끊김처럼 요청이 없는 알림은 알림 화면으로
    });
    return () => sub.remove();
  }, []);
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <StatusBar style="dark" />
        <Stack
          screenOptions={{
            headerTintColor: C.fg,
            headerShadowVisible: false,
            headerStyle: { backgroundColor: C.band },
            headerTitleStyle: { fontWeight: '700', fontFamily: FONT, fontSize: 17 },
            headerBackButtonDisplayMode: 'minimal',
            contentStyle: { backgroundColor: C.band },
          }}
        >
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="login" options={{ headerShown: false, contentStyle: { backgroundColor: C.card } }} />
          <Stack.Screen name="chat/[id]" options={{ title: '상담' }} />
          <Stack.Screen name="case/[id]" options={{ title: '요청 처리' }} />
          <Stack.Screen name="order/[id]" options={{ title: '주문' }} />
          <Stack.Screen name="signup" options={{ title: '가입 신청', headerStyle: { backgroundColor: C.band } }} />
          <Stack.Screen name="forgot" options={{ title: '', headerStyle: { backgroundColor: C.card }, contentStyle: { backgroundColor: C.card } }} />
          <Stack.Screen name="rules" options={{ title: '자동 처리 규칙' }} />
          <Stack.Screen name="products" options={{ title: '상품정보' }} />
          <Stack.Screen name="stats" options={{ title: '처리 통계' }} />
          <Stack.Screen name="report" options={{ title: '월간 리포트' }} />
          <Stack.Screen name="alerts" options={{ title: '알림' }} />
          <Stack.Screen name="settings" options={{ title: '회사 정보와 알림 설정' }} />
          <Stack.Screen name="leave" options={{ title: '회원 탈퇴' }} />
          <Stack.Screen name="guide" options={{ title: '응대 가이드' }} />
          <Stack.Screen name="howto" options={{ title: '이용 안내' }} />
          <Stack.Screen name="news" options={{ title: '법·제도 소식' }} />
          <Stack.Screen name="new" options={{ title: '요청 직접 등록' }} />
          <Stack.Screen name="orders" options={{ title: '주문·배송' }} />
          <Stack.Screen name="returns" options={{ title: '교환·반품' }} />
          <Stack.Screen name="macros" options={{ title: '답변 템플릿' }} />
        </Stack>
        <Intro />
      </AuthProvider>
    </SafeAreaProvider>
  );
}

const st = StyleSheet.create({
  intro: { backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center', zIndex: 10 },
  wm: { fontFamily: FONT, fontSize: 30, fontWeight: '800', color: C.brand, letterSpacing: -1, marginTop: 14 },
  sub: { fontFamily: FONT, fontSize: 15, fontWeight: '600', color: C.fg3, marginTop: 6 },
  foot: { position: 'absolute', bottom: 48, fontFamily: FONT, fontSize: 13, color: C.fg4 },
});
