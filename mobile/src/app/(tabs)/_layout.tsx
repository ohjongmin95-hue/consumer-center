import { Redirect, Tabs } from 'expo-router';
import { Platform, Text, View } from 'react-native';
import { Icon } from '../../components/Icon';
import { Loading } from '../../components/ui';
import { useAuth } from '../../lib/auth';
import { usePending } from '../../lib/badge';
import { C, FONT } from '../../lib/theme';

// 아래 탭은 휴대폰 웹(소보루 CS 홈페이지)과 같은 다섯 칸: 홈 · 요청 · 승인 · 자동 응대 · 전체
export default function TabsLayout() {
  const { ready, session } = useAuth();
  const n = usePending();
  if (!ready) return <Loading />;
  if (!session) return <Redirect href="/login" />;
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: C.fg,
        tabBarInactiveTintColor: C.fg3,
        tabBarStyle: { borderTopColor: C.line, backgroundColor: C.card, borderTopLeftRadius: 20, borderTopRightRadius: 20, ...(Platform.OS === 'web' ? { height: 76, paddingBottom: 12, paddingTop: 8 } : { height: 68, paddingTop: 6 }) },
        tabBarLabelStyle: { fontFamily: FONT, fontSize: 12, fontWeight: '600', marginTop: 2 },
      }}
    >
      <Tabs.Screen name="index" options={{ title: '홈', tabBarIcon: ({ focused }) => <Tab name="home" on={focused} /> }} />
      <Tabs.Screen name="cases" options={{ title: '요청', tabBarIcon: ({ focused }) => <Tab name="list" on={focused} /> }} />
      <Tabs.Screen name="approvals" options={{ title: '승인', tabBarIcon: ({ focused }) => <Tab name="check" on={focused} n={n} /> }} />
      <Tabs.Screen name="auto" options={{ title: '자동 응대', tabBarIcon: ({ focused }) => <Tab name="bolt" on={focused} /> }} />
      <Tabs.Screen name="more" options={{ title: '전체', tabBarIcon: ({ focused }) => <Tab name="menu" on={focused} /> }} />
    </Tabs>
  );
}

// 고른 탭만 진하게, 나머지는 흐리게. 승인 탭에는 웹처럼 주황 숫자
function Tab({ name, on, n }: { name: string; on: boolean; n?: number }) {
  return (
    <View>
      <View style={{ opacity: on ? 1 : 0.4 }}>
        <Icon name={name} size={26} />
      </View>
      {n ? (
        <View style={{ position: 'absolute', top: -4, right: -10, minWidth: 18, height: 18, paddingHorizontal: 5, borderRadius: 9, backgroundColor: C.accent, alignItems: 'center', justifyContent: 'center' }}>
          <Text style={{ fontFamily: FONT, fontSize: 11, fontWeight: '700', color: '#fff' }}>{n > 99 ? '99+' : n}</Text>
        </View>
      ) : null}
    </View>
  );
}
