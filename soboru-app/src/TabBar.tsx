// 아래 탭: 홈·제보 목록·제보하기·알림·내 제보 (소보루제보 앱). 앱 안에서는 사이트가 자기 탭바를 숨김 (templates/base.html)
import * as Haptics from 'expo-haptics';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Circle, Path } from 'react-native-svg';

export type Tab = { key: string; label: string; path: string };

export const ORANGE = '#EF7300';
const INK = '#1F1A17';
const MUTE = '#9A918A';

export function tabsFor(member: boolean): Tab[] {
  return [
    // 소보루제보 앱 (운영자 2026-11-03): 소비자제보센터(consumerjebo.co.kr)를 띄우고, 제보하기는 글쓰기 제보(/report, 위에 대화로 제보하기 칸)
    { key: 'home', label: '홈', path: '/' },
    { key: 'board', label: '제보 목록', path: '/reports' },
    { key: 'report', label: '제보하기', path: '/report' },
    { key: 'life', label: '알림', path: member ? '/me/alerts' : '/login?next=/me/alerts' },
    member ? { key: 'my', label: '내 제보', path: '/me' } : { key: 'my', label: '내 제보', path: '/lookup' },
  ];
}

/** 지금 화면 주소(/life/12 등)에 맞는 탭 */
export function activeTab(path: string): string {
  if (path === '/' || path === '') return 'home';
  if (path.startsWith('/me/alerts')) return 'life';
  if (path.startsWith('/report') && !path.startsWith('/reports')) return 'report';
  if (['/reports', '/companies', '/board'].some((x) => path.startsWith(x))) return 'board';
  if (path.startsWith('/me') || path.startsWith('/lookup')) return 'my';
  return '';
}

function Icon({ name, color }: { name: string; color: string }) {
  const p = { fill: 'none', stroke: color, strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  return (
    <Svg width={23} height={23} viewBox="0 0 24 24">
      {name === 'home' && <Path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z" {...p} />}
      {name === 'life' && (<><Path d="M6 16V11a6 6 0 0112 0v5l1.5 2h-15z" {...p} /><Path d="M10 20.5a2 2 0 004 0" {...p} /></>)}
      {name === 'board' && (<><Path d="M5 4h14v16H5z" {...p} /><Path d="M8.5 9h7M8.5 13h7M8.5 17h4" {...p} /></>)}
      {name === 'my' && (<><Circle cx={12} cy={8.5} r={4} {...p} /><Path d="M4 21c.9-4 4-6 8-6s7.1 2 8 6" {...p} /></>)}
      {name === 'report' && <Path d="M12 5v14M5 12h14" {...p} strokeWidth={2.6} />}
    </Svg>
  );
}

export default function TabBar({ tabs, active, onPress }: { tabs: Tab[]; active: string; onPress: (t: Tab) => void }) {
  const insets = useSafeAreaInsets();
  return (
    <View style={[s.bar, { paddingBottom: Math.max(insets.bottom, 6) }]} accessibilityRole="tablist">
      {tabs.map((t) => {
        const on = t.key === active;
        const plus = t.key === 'report';
        return (
          <Pressable
            key={t.key}
            style={({ pressed }) => [s.tab, pressed && { transform: [{ scale: 0.94 }] }]}
            accessibilityRole="tab"
            accessibilityState={{ selected: on }}
            accessibilityLabel={t.label}
            onPress={() => { Haptics.selectionAsync().catch(() => {}); onPress(t); }}
          >
            {plus ? (
              <View style={s.plus}><Icon name="report" color="#FFFFFF" /></View>
            ) : (
              <Icon name={t.key} color={on ? INK : MUTE} />
            )}
            <Text style={[s.label, { color: on || plus ? INK : MUTE }]}>{t.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const s = StyleSheet.create({
  bar: { flexDirection: 'row', backgroundColor: '#FFFFFF', borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: '#E8E2DC', paddingTop: 6 },
  tab: { flex: 1, alignItems: 'center', justifyContent: 'flex-end', gap: 3, minHeight: 50 },
  plus: { width: 38, height: 38, borderRadius: 14, backgroundColor: ORANGE, alignItems: 'center', justifyContent: 'center', marginTop: -6,
    shadowColor: ORANGE, shadowOpacity: 0.32, shadowRadius: 7, shadowOffset: { width: 0, height: 4 }, elevation: 4 },
  label: { fontSize: 11, fontWeight: '600' },
});
