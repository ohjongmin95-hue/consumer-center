import { Redirect, Tabs } from 'expo-router';
import { Platform } from 'react-native';
import { Icon } from '../../components/Icon';
import { Loading } from '../../components/ui';
import { useAuth } from '../../lib/auth';
import { C } from '../../lib/theme';

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
        tabBarStyle: { borderTopColor: C.line, backgroundColor: C.card, ...(Platform.OS === 'web' ? { height: 64, paddingBottom: 8 } : null) },
        tabBarLabelStyle: { fontSize: 12, fontWeight: '600' },
      }}
    >
      <Tabs.Screen name="index" options={{ title: '홈', tabBarIcon: () => <Icon name="shield" size={24} /> }} />
      <Tabs.Screen name="cases" options={{ title: '전체 민원', tabBarIcon: () => <Icon name="list" size={24} /> }} />
      <Tabs.Screen name="more" options={{ title: '내 정보', tabBarIcon: () => <Icon name="building" size={24} /> }} />
    </Tabs>
  );
}
