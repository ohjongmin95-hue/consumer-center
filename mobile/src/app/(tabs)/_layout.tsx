import { Redirect, Tabs } from 'expo-router';
import { Platform, View } from 'react-native';
import { Icon } from '../../components/Icon';
import { Loading } from '../../components/ui';
import { useAuth } from '../../lib/auth';
import { C, FONT } from '../../lib/theme';

export default function TabsLayout() {
  const { ready, session } = useAuth();
  if (!ready) return <Loading />;
  if (!session) return <Redirect href="/login" />;
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: C.fg,
        tabBarInactiveTintColor: C.fg4,
        tabBarStyle: { borderTopColor: C.line, backgroundColor: C.card, borderTopLeftRadius: 20, borderTopRightRadius: 20, ...(Platform.OS === 'web' ? { height: 76, paddingBottom: 12, paddingTop: 8 } : { height: 68, paddingTop: 6 }) },
        tabBarLabelStyle: { fontFamily: FONT, fontSize: 12, fontWeight: '600', marginTop: 2 },
      }}
    >
      <Tabs.Screen name="index" options={{ title: '홈', tabBarIcon: ({ focused }) => <Tab name="shield" on={focused} /> }} />
      <Tabs.Screen name="cases" options={{ title: '전체 요청', tabBarIcon: ({ focused }) => <Tab name="list" on={focused} /> }} />
      <Tabs.Screen name="orders" options={{ title: '주문', tabBarIcon: ({ focused }) => <Tab name="truck" on={focused} /> }} />
      <Tabs.Screen name="more" options={{ title: '내 정보', tabBarIcon: ({ focused }) => <Tab name="building" on={focused} /> }} />
    </Tabs>
  );
}

// 고른 탭만 진하게, 나머지는 흐리게 (토스 아래 탭처럼)
function Tab({ name, on }: { name: string; on: boolean }) {
  return (
    <View style={{ opacity: on ? 1 : 0.35 }}>
      <Icon name={name} size={26} />
    </View>
  );
}
