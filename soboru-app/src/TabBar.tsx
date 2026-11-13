// 아래 탭 (소보루고발 앱, 운영자 2026-11-11 헤이마오터우쑤처럼): 가운데 고발하기는 📢 이모지(운영자 2026-11-13). 홈·기업 순위·고발하기(가운데 큰 버튼)·둘러보기·내 정보. 앱 안에서는 사이트가 자기 탭바를 숨김 (templates/base.html)
import * as Haptics from 'expo-haptics';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Circle, Path } from 'react-native-svg';

export type Tab = { key: string; label: string; path: string };

export const ORANGE = '#FE9800'; // 운영자 2026-11-13: 버튼·강조 색은 TDS 오렌지 500 (로고만 #EF920E)
const INK = '#1F1A17';
const MUTE = '#9A918A';

export function tabsFor(member: boolean): Tab[] {
  return [
    // 고발하기는 글쓰기 제보(/report, 위에 대화로 제보하기 칸). 알림은 내 정보 안에서 봐요.
    { key: 'home', label: '홈', path: '/' },
    { key: 'rank', label: '기업 순위', path: '/companies/rank' },
    { key: 'report', label: '고발하기', path: '/report' },
    { key: 'explore', label: '둘러보기', path: '/explore' },
    member ? { key: 'my', label: '내 정보', path: '/me' } : { key: 'my', label: '내 정보', path: '/lookup' },
  ];
}

/** 지금 화면 주소(/life/12 등)에 맞는 탭 */
export function activeTab(path: string): string {
  if (path === '/' || path === '' || path.startsWith('/reports')) return 'home';
  if (path.startsWith('/report')) return 'report';
  if (path.startsWith('/companies')) return 'rank';
  if (path.startsWith('/explore')) return 'explore';
  if (path.startsWith('/me') || path.startsWith('/lookup')) return 'my';
  return '';
}

function Icon({ name, color }: { name: string; color: string }) {
  const p = { fill: 'none', stroke: color, strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  return (
    <Svg width={23} height={23} viewBox="0 0 24 24">
      {name === 'home' && <Path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z" {...p} />}
      {name === 'rank' && (<><Path d="M5 20V12M12 20V5M19 20v-6" {...p} strokeWidth={2.4} /><Path d="M3 20.5h18" {...p} /></>)}
      {name === 'explore' && (<><Circle cx={12} cy={12} r={8.5} {...p} /><Path d="M15.5 8.5l-2 5-5 2 2-5z" {...p} /></>)}
      {name === 'my' && (<><Circle cx={12} cy={8.5} r={4} {...p} /><Path d="M4 21c.9-4 4-6 8-6s7.1 2 8 6" {...p} /></>)}
      {name === 'report' && (<><Path d="M12 4.5v9" {...p} strokeWidth={3} /><Circle cx={12} cy={18.5} r={1.4} fill={color} /></>)}
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
              <View style={s.plus}><Text style={s.emoji} allowFontScaling={false}>📢</Text></View>
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
  emoji: { fontSize: 24, lineHeight: 30 },
  plus: { width: 50, height: 50, borderRadius: 25, backgroundColor: ORANGE, alignItems: 'center', justifyContent: 'center', marginTop: -20, borderWidth: 3, borderColor: '#FFFFFF',
    shadowColor: ORANGE, shadowOpacity: 0.32, shadowRadius: 7, shadowOffset: { width: 0, height: 4 }, elevation: 4 },
  label: { fontSize: 11, fontWeight: '600' },
});
