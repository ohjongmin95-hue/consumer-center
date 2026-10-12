import { Platform } from 'react-native';
import { Tabs } from 'expo-router';
import { Icon } from '../../components/Icon';
import { C } from '../../lib/theme';

export default function TabsLayout() {
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
      <Tabs.Screen name="index" options={{ title: '홈', tabBarIcon: () => <Icon name="building" size={24} /> }} />
      <Tabs.Screen name="mine" options={{ title: '내 접수', tabBarIcon: () => <Icon name="list" size={24} /> }} />
    </Tabs>
  );
}
