// 토스처럼 납작하고 둥근 기본 부품. 색은 소보루 주황.
import { ReactNode, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleProp, StyleSheet, Switch, Text, TextInput, TextInputProps, View, ViewStyle } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { C, R, STATUS_TONE } from '../lib/theme';

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
          <Text style={{ fontSize: 14, fontWeight: '600', color: C.fg3 }}>{show ? '숨기기' : '보기'}</Text>
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
      {right ? <Text style={{ fontSize: 15, fontWeight: '700', color: C.accentInk, marginRight: 6 }}>{right}</Text> : null}
      <Text style={s.chev}>›</Text>
    </Pressable>
  );
}

// 가로 막대 하나 (통계)
export function BarLine({ label, n, pct, max, unit = '건' }: { label: string; n: number; pct?: number; max: number; unit?: string }) {
  const w = max ? Math.max(2, Math.round((n / max) * 100)) : 0;
  return (
    <View style={{ gap: 6, marginBottom: 12 }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
        <Text style={{ fontSize: 15, color: C.fg2, fontWeight: '600' }}>{label}</Text>
        <Text style={{ fontSize: 15, color: C.fg, fontWeight: '700', fontVariant: ['tabular-nums'] }}>
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
      <Text style={{ color: tone === 'error' ? C.red : C.green, fontSize: 15, fontWeight: '600' }}>{text}</Text>
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
  card: { backgroundColor: C.card, borderRadius: R.lg, padding: 20, marginHorizontal: 16, marginBottom: 12 },
  h1: { fontSize: 26, lineHeight: 36, fontWeight: '700', color: C.fg, letterSpacing: -0.8 },
  h2: { fontSize: 19, fontWeight: '700', color: C.fg, letterSpacing: -0.6, marginBottom: 14 },
  sub: { fontSize: 15, lineHeight: 22, color: C.fg3 },
  btn: { height: 54, borderRadius: R.md, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 20 },
  btnText: { fontSize: 17, fontWeight: '700', letterSpacing: -0.3 },
  label: { fontSize: 15, fontWeight: '600', color: C.fg2 },
  hint: { fontSize: 13, color: C.fg3 },
  input: { height: 54, borderRadius: R.md, backgroundColor: C.fill, paddingHorizontal: 16, fontSize: 16, color: C.fg },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { height: 40, paddingHorizontal: 16, borderRadius: 20, backgroundColor: C.fill, justifyContent: 'center' },
  chipText: { fontSize: 15, fontWeight: '600', color: C.fg2 },
  pill: { alignSelf: 'flex-start', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  pillText: { fontSize: 13, fontWeight: '700' },
  eye: { position: 'absolute', right: 14, top: 0, bottom: 0, justifyContent: 'center' },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 14 },
  rowLine: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.line },
  rowTitle: { fontSize: 16, fontWeight: '600', color: C.fg },
  rowSub: { fontSize: 13, lineHeight: 19, color: C.fg3 },
  chev: { fontSize: 24, color: C.fg4 },
  notice: { borderRadius: R.sm, padding: 14, marginHorizontal: 16, marginBottom: 12 },
});
