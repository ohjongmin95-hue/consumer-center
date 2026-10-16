// 토스처럼 납작하고 둥근 기본 부품. 색은 소보루 주황.
import { router } from 'expo-router';
import { ReactNode, useEffect, useState } from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, StyleProp, StyleSheet, Switch, Text, TextInput, TextInputProps, View, ViewStyle } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useAuth } from '../lib/auth';
import { api } from '../lib/api';
import { pendingKnown, setPending } from '../lib/badge';
import { C, R, STATUS_TONE, FONT } from '../lib/theme';
import { Tf, TfName } from './Tf';

// 웹 머리글과 같은 줄: 왼쪽 소보루 CS 로고, 오른쪽 승인할 일 종(숫자)과 회사 이름
export function TopBar() {
  const { session } = useAuth();
  const name = session?.company.name ?? '';
  // 홈을 거치지 않고 다른 탭부터 열었으면 승인 탭 숫자를 한 번 받아 온다
  useEffect(() => {
    if (session && !pendingKnown()) api.cases(session.token, 'pending').then((r) => setPending(r.cases.length), () => {});
  }, [session]);
  return (
    <View style={s.top}>
      <Pressable onPress={() => router.navigate('/')} style={s.logo} hitSlop={6}>
        <Image source={require('../../assets/soboru-char.png')} style={{ width: 34, height: 26 }} resizeMode="contain" />
        <Text style={s.logoText}>소보루 CS</Text>
      </Pressable>
      <Pressable onPress={() => router.push('/settings')} style={({ pressed }) => [s.coChip, { marginLeft: 'auto' }, pressed && { opacity: 0.7 }]}>
        <View style={s.coDot}>
          <Text style={s.coDotText}>{name.slice(0, 1)}</Text>
        </View>
        <Text style={s.coName} numberOfLines={1}>
          {name}
        </Text>
      </Pressable>
    </View>
  );
}

// 화면 큰 제목 (웹의 h1). 오른쪽에 주황 버튼 하나를 둘 수 있다
export function PageHead({ title, accent, action }: { title: string; accent?: string; action?: { title: string; onPress: () => void } }) {
  return (
    <View style={s.phead}>
      <Text style={s.pheadText}>
        {title}
        {accent ? <Text style={{ color: C.accent }}>{accent}</Text> : null}
      </Text>
      {action ? <SmallBtn title={action.title} onPress={action.onPress} /> : null}
    </View>
  );
}

// 작은 둥근 버튼 (웹 .btn.sm)
export function SmallBtn({ title, onPress, kind = 'primary', busy }: { title: string; onPress: () => void; kind?: 'primary' | 'soft' | 'gray'; busy?: boolean }) {
  const bg = { primary: C.accent, soft: C.accentSoft, gray: C.fill }[kind];
  const fg = { primary: '#fff', soft: C.accentInk, gray: C.fg2 }[kind];
  return (
    <Pressable onPress={onPress} disabled={busy} style={({ pressed }) => [s.small, { backgroundColor: bg, opacity: pressed || busy ? 0.75 : 1 }]} accessibilityRole="button">
      {busy ? <ActivityIndicator color={fg} size="small" /> : <Text style={[s.smallText, { color: fg }]}>{title}</Text>}
    </Pressable>
  );
}

// 홈 숫자 칸 (웹 홈의 '오늘 들어온 요청 · 승인 대기 · 답변할 요청 · 기한 지난 요청')
export function Tile({ icon, label, value, tone, onPress }: { icon: TfName; label: string; value: number; tone?: 'acc' | 'red'; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [s.tile, pressed && { opacity: 0.7 }]}>
      <Tf name={icon} size={32} />
      <Text style={s.tileLabel}>{label}</Text>
      <Text style={[s.tileValue, tone === 'acc' && value ? { color: C.accent } : null, tone === 'red' && value ? { color: C.red } : null]}>{value}</Text>
    </Pressable>
  );
}

export function Screen({ children, bg = C.band, edges }: { children: ReactNode; bg?: string; edges?: ('top' | 'bottom')[] }) {
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: bg }} edges={edges ?? []}>
      <ScrollView contentContainerStyle={{ paddingBottom: 40 }} keyboardShouldPersistTaps="handled">
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[s.card, style]}>{children}</View>;
}

export function H1({ children }: { children: ReactNode }) {
  return <Text style={s.h1}>{children}</Text>;
}
export function H2({ children }: { children: ReactNode }) {
  return <Text style={s.h2}>{children}</Text>;
}
export function Sub({ children, style }: { children: ReactNode; style?: object }) {
  return <Text style={[s.sub, style]}>{children}</Text>;
}

export function Btn({ title, onPress, kind = 'primary', busy, disabled, style }: { title: string; onPress: () => void; kind?: 'primary' | 'soft' | 'gray' | 'danger'; busy?: boolean; disabled?: boolean; style?: StyleProp<ViewStyle> }) {
  const bg = { primary: C.accent, soft: C.accentSoft, gray: C.fill, danger: C.redSoft }[kind];
  const fg = { primary: '#fff', soft: C.accentInk, gray: C.fg2, danger: C.red }[kind];
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={busy || disabled}
      style={({ pressed }) => [s.btn, { backgroundColor: bg, opacity: disabled ? 0.45 : 1, transform: [{ scale: pressed ? 0.98 : 1 }] }, style]}
    >
      {busy ? <ActivityIndicator color={fg} /> : <Text style={[s.btnText, { color: fg }]}>{title}</Text>}
    </Pressable>
  );
}

export function Field({ label, hint, ...p }: TextInputProps & { label?: string; hint?: string }) {
  return (
    <View style={{ gap: 8 }}>
      {label ? <Text style={s.label}>{label}</Text> : null}
      <TextInput placeholderTextColor={C.fg4} {...p} style={[s.input, p.multiline && { height: 140, paddingTop: 14, textAlignVertical: 'top' }, p.style]} />
      {hint ? <Text style={s.hint}>{hint}</Text> : null}
    </View>
  );
}

// 비밀번호 칸: 오른쪽 '보기'로 입력한 글자를 확인
export function PwField({ label, hint, ...p }: TextInputProps & { label?: string; hint?: string }) {
  const [show, setShow] = useState(false);
  return (
    <View style={{ gap: 8 }}>
      {label ? <Text style={s.label}>{label}</Text> : null}
      <View>
        <TextInput placeholderTextColor={C.fg4} autoCapitalize="none" autoCorrect={false} {...p} secureTextEntry={!show} style={[s.input, { paddingRight: 64 }]} />
        <Pressable onPress={() => setShow(!show)} hitSlop={8} style={s.eye} accessibilityRole="button">
          <Text style={{ fontFamily: FONT, fontSize: 14, fontWeight: '600', color: C.fg3 }}>{show ? '숨기기' : '보기'}</Text>
        </Pressable>
      </View>
      {hint ? <Text style={s.hint}>{hint}</Text> : null}
    </View>
  );
}

export function Toggle({ title, sub, value, onChange, disabled }: { title: string; sub?: string; value: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <View style={s.toggle}>
      <View style={{ flex: 1, gap: 3 }}>
        <Text style={s.rowTitle}>{title}</Text>
        {sub ? <Text style={s.rowSub}>{sub}</Text> : null}
      </View>
      <Switch value={value} onValueChange={onChange} disabled={disabled} trackColor={{ true: C.accent, false: C.line }} thumbColor="#fff" {...({ activeThumbColor: '#fff' } as object)} />
    </View>
  );
}

export function MenuRow({ title, sub, onPress, last, right }: { title: string; sub?: string; onPress: () => void; last?: boolean; right?: string }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [s.row, !last && s.rowLine, pressed && { opacity: 0.6 }]}>
      <View style={{ flex: 1, gap: 3 }}>
        <Text style={s.rowTitle}>{title}</Text>
        {sub ? <Text style={s.rowSub}>{sub}</Text> : null}
      </View>
      {right ? <Text style={{ fontFamily: FONT, fontSize: 15, fontWeight: '700', color: C.accentInk, marginRight: 6 }}>{right}</Text> : null}
      <Text style={s.chev}>›</Text>
    </Pressable>
  );
}

// 가로 막대 하나 (통계)
// 토스 홈의 한 줄: 왼쪽 동그란 아이콘, 큰 숫자와 회색 설명, 오른쪽 회색 버튼
export function StatRow({ icon, value, sub, action, onPress, tone }: { icon: ReactNode; value: string; sub: string; action?: string; onPress?: () => void; tone?: 'red' | 'acc' }) {
  return (
    <Pressable onPress={onPress} disabled={!onPress} style={({ pressed }) => [s.stat, pressed && { opacity: 0.7 }]}>
      <View style={s.statIc}>{icon}</View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={[s.statValue, tone === 'red' && { color: C.red }, tone === 'acc' && { color: C.accentInk }]}>{value}</Text>
        <Text style={s.statSub}>{sub}</Text>
      </View>
      {action ? (
        <View style={s.pillBtn}>
          <Text style={s.pillBtnText}>{action}</Text>
        </View>
      ) : null}
    </Pressable>
  );
}

// 카드 아래 바로가기 줄 (계좌 | 대출 | 카드 ... 모두보기)
export function LinkBar({ items, more }: { items: { title: string; onPress: () => void }[]; more?: { title: string; onPress: () => void } }) {
  return (
    <View style={s.linkBar}>
      {items.map((it, i) => (
        <View key={it.title} style={{ flexDirection: 'row', alignItems: 'center' }}>
          {i ? <View style={s.linkSep} /> : null}
          <Pressable onPress={it.onPress} hitSlop={8} style={({ pressed }) => pressed && { opacity: 0.5 }}>
            <Text style={s.linkText}>{it.title}</Text>
          </Pressable>
        </View>
      ))}
      {more ? (
        <Pressable onPress={more.onPress} hitSlop={8} style={({ pressed }) => [{ marginLeft: 'auto' }, pressed && { opacity: 0.5 }]}>
          <Text style={s.linkText}>{more.title}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export function BarLine({ label, n, pct, max, unit = '건' }: { label: string; n: number; pct?: number; max: number; unit?: string }) {
  const w = max ? Math.max(2, Math.round((n / max) * 100)) : 0;
  return (
    <View style={{ gap: 6, marginBottom: 12 }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
        <Text style={{ fontFamily: FONT, fontSize: 15, color: C.fg2, fontWeight: '600' }}>{label}</Text>
        <Text style={{ fontFamily: FONT, fontSize: 15, color: C.fg, fontWeight: '700', fontVariant: ['tabular-nums'] }}>
          {n}
          {unit}
          {pct !== undefined ? <Text style={{ color: C.fg3, fontWeight: '500' }}> · {pct}%</Text> : null}
        </Text>
      </View>
      <View style={{ height: 8, borderRadius: 4, backgroundColor: C.fill }}>
        <View style={{ width: `${w}%`, height: 8, borderRadius: 4, backgroundColor: n ? C.accent : 'transparent' }} />
      </View>
    </View>
  );
}

export function Chips({ items, value, onChange }: { items: string[]; value: string; onChange: (v: string) => void }) {
  return (
    <View style={s.chips}>
      {items.map((it) => {
        const on = it === value;
        return (
          <Pressable key={it} onPress={() => onChange(it)} style={[s.chip, on && { backgroundColor: C.accent }]}>
            <Text style={[s.chipText, on && { color: '#fff' }]}>{it}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function StatusPill({ status, label }: { status: string; label: string }) {
  const t = STATUS_TONE[status] ?? STATUS_TONE.received;
  return (
    <View style={[s.pill, { backgroundColor: t.bg }]}>
      <Text style={[s.pillText, { color: t.fg }]}>{label}</Text>
    </View>
  );
}

export function Notice({ text, tone = 'error', flat }: { text: string; tone?: 'error' | 'ok'; flat?: boolean }) {
  if (!text) return null;
  return (
    <View style={[s.notice, flat && { marginHorizontal: 0, marginBottom: 0 }, { backgroundColor: tone === 'error' ? C.redSoft : C.greenSoft }]}>
      <Text style={{ color: tone === 'error' ? C.red : C.green, fontFamily: FONT, fontSize: 15, fontWeight: '600' }}>{text}</Text>
    </View>
  );
}

export function Loading() {
  return (
    <View style={{ padding: 48, alignItems: 'center' }}>
      <ActivityIndicator color={C.accent} />
    </View>
  );
}

export const s = StyleSheet.create({
  top: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 18, paddingTop: 10, paddingBottom: 10 },
  logo: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  logoText: { fontFamily: FONT, fontSize: 19, fontWeight: '800', color: C.brand, letterSpacing: -0.6 },
  coChip: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 36, paddingLeft: 4, paddingRight: 12, borderRadius: 18, backgroundColor: C.card, maxWidth: 150 },
  coDot: { width: 28, height: 28, borderRadius: 14, backgroundColor: C.accent, alignItems: 'center', justifyContent: 'center' },
  coDotText: { fontFamily: FONT, fontSize: 13, fontWeight: '700', color: '#fff' },
  coName: { fontFamily: FONT, fontSize: 14, fontWeight: '600', color: C.fg2, flexShrink: 1 },
  phead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, paddingHorizontal: 22, paddingTop: 10, paddingBottom: 14 },
  pheadText: { flex: 1, fontFamily: FONT, fontSize: 24, lineHeight: 33, fontWeight: '700', color: C.fg, letterSpacing: -0.8 },
  small: { height: 36, minWidth: 56, paddingHorizontal: 14, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  smallText: { fontFamily: FONT, fontSize: 14, fontWeight: '700' },
  tile: { flexBasis: '47%', flexGrow: 1, backgroundColor: C.card, borderRadius: R.lg, padding: 18, gap: 6 },
  tileLabel: { fontFamily: FONT, fontSize: 14, fontWeight: '600', color: C.fg2, marginTop: 6 },
  tileValue: { fontFamily: FONT, fontSize: 26, fontWeight: '700', color: C.fg, letterSpacing: -0.6, fontVariant: ['tabular-nums'] },
  card: { backgroundColor: C.card, borderRadius: R.lg, padding: 22, marginHorizontal: 14, marginBottom: 12 },
  stat: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 12 },
  statIc: { width: 44, height: 44, borderRadius: 22, backgroundColor: C.fill, alignItems: 'center', justifyContent: 'center' },
  statValue: { fontFamily: FONT, fontSize: 21, fontWeight: '700', color: C.fg, letterSpacing: -0.6, fontVariant: ['tabular-nums'] },
  statSub: { fontFamily: FONT, fontSize: 15, color: C.fg3, letterSpacing: -0.2 },
  pillBtn: { height: 38, paddingHorizontal: 16, borderRadius: 12, backgroundColor: C.fill, alignItems: 'center', justifyContent: 'center' },
  pillBtnText: { fontFamily: FONT, fontSize: 15, fontWeight: '600', color: C.fg2 },
  linkBar: { flexDirection: 'row', alignItems: 'center', gap: 14, marginTop: 10, marginHorizontal: -22, paddingHorizontal: 22, paddingTop: 16, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: C.line },
  linkSep: { width: 1, height: 14, backgroundColor: C.line, marginRight: 14 },
  linkText: { fontFamily: FONT, fontSize: 15, fontWeight: '500', color: C.fg2 },
  h1: { fontFamily: FONT, fontSize: 26, lineHeight: 36, fontWeight: '700', color: C.fg, letterSpacing: -0.8 },
  h2: { fontFamily: FONT, fontSize: 20, fontWeight: '700', color: C.fg, letterSpacing: -0.6, marginBottom: 14 },
  sub: { fontFamily: FONT, fontSize: 15, lineHeight: 22, color: C.fg3 },
  btn: { height: 54, borderRadius: R.md, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 20 },
  btnText: { fontFamily: FONT, fontSize: 17, fontWeight: '700', letterSpacing: -0.3 },
  label: { fontFamily: FONT, fontSize: 15, fontWeight: '600', color: C.fg2 },
  hint: { fontFamily: FONT, fontSize: 13, color: C.fg3 },
  input: { height: 54, borderRadius: R.md, backgroundColor: C.fill, paddingHorizontal: 16, fontFamily: FONT, fontSize: 16, color: C.fg },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { height: 40, paddingHorizontal: 16, borderRadius: 20, backgroundColor: C.fill, justifyContent: 'center' },
  chipText: { fontFamily: FONT, fontSize: 15, fontWeight: '600', color: C.fg2 },
  pill: { alignSelf: 'flex-start', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  pillText: { fontFamily: FONT, fontSize: 13, fontWeight: '700' },
  eye: { position: 'absolute', right: 14, top: 0, bottom: 0, justifyContent: 'center' },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 16 },
  rowLine: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.line },
  rowTitle: { fontFamily: FONT, fontSize: 17, fontWeight: '600', color: C.fg, letterSpacing: -0.3 },
  rowSub: { fontFamily: FONT, fontSize: 14, lineHeight: 20, color: C.fg3 },
  chev: { fontFamily: FONT, fontSize: 24, color: C.fg4 },
  notice: { borderRadius: R.sm, padding: 14, marginHorizontal: 16, marginBottom: 12 },
});
