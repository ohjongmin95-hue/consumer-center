// SODA 가르치기 (토스 앱 목록 화면처럼: 흰 바탕, 24 여백, 줄 목록, 구역 사이 16 회색 띠).
// 줄을 누르면 soda-edit 화면에서 한 가지만 한다 (답하기·알려 주기·고치기). 사진·PDF·엑셀은 PC에서 올린다.
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Loading, Notice } from '../components/ui';
import { Glyph } from '../components/Glyph';
import { SodaMark } from '../components/SodaMark';
import { api, Soda, SodaItem } from '../lib/api';
import { useAuth } from '../lib/auth';
import { C, FONT } from '../lib/theme';
import { errText, useLoad } from '../lib/useLoad';

export default function SodaScreen() {
  const { logout } = useAuth();
  const { data, setData, err, token } = useLoad(api.soda);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [bad, setBad] = useState('');
  if (!data)
    return (
      <SafeAreaView style={st.page} edges={[]}>
        {err ? <Notice text={err} /> : <Loading />}
      </SafeAreaView>
    );

  const go = async (key: string, f: Parameters<typeof api.sodaAct>[1]) => {
    setBusy(key);
    setBad('');
    try {
      const d: Soda = await api.sodaAct(token, f);
      setData(d);
      setMsg(d.message ?? '');
    } catch (e) {
      setBad(errText(e, logout));
    } finally {
      setBusy('');
    }
  };
  const open = (p: Record<string, string>) => router.push({ pathname: '/soda-edit', params: p });
  const edit = (r: SodaItem) => open({ mode: 'edit', id: String(r.id), q: r.q, a: r.a });

  return (
    <SafeAreaView style={st.page} edges={[]}>
      <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
        <View style={st.titleRow}>
          <SodaMark size={26} />
          <Text style={st.title}>SODA 가르치기</Text>
        </View>
        {msg ? <Text style={st.msg}>{msg}</Text> : null}
        {bad ? <Text style={[st.msg, { color: C.red }]}>{bad}</Text> : null}

        {data.check.length ? (
          <View style={st.card}>
            <Head title="맞는지 확인해 주세요" n={data.check.length} />
            {data.check.map((r) => (
              <Row key={r.id} title={r.q} sub={r.a} onPress={() => edit(r)} pill="고치기" />
            ))}
            <Pressable onPress={() => go('check', { act: 'check' })} disabled={!!busy} style={({ pressed }) => [st.cta, pressed && { backgroundColor: C.accentPress }]}>
              <Text style={st.ctaText}>{busy === 'check' ? '켜는 중…' : '모두 맞아요, 켜기'}</Text>
            </Pressable>
          </View>
        ) : null}

        <View style={st.card}>
          <Head title="SODA가 물어봐요" n={data.gaps.length} />
          {data.gaps.length ? (
            data.gaps.map((g) => <Row key={g.id} icon="chat" title={g.q} sub={g.n > 1 ? `${g.n}번 물어봤어요` : '고객이 물었어요'} subTone={g.n > 1} onPress={() => open({ mode: 'gap', id: String(g.id), q: g.q })} pill="답하기" />)
          ) : (
            <Text style={st.empty}>{data.ai ? '지금은 물어볼 게 없어요' : 'SODA가 켜지면 모르는 질문을 여기에 모아요'}</Text>
          )}
        </View>

        <View style={st.card}>
          <Head title="한 번에 알려 주기" />
          <Row icon="template" title="말로 알려 주기" sub="적은 말은 바로 배워요" onPress={() => open({ mode: 'text' })} chevron />
          <Row icon="link" title="쇼핑몰 주소로 알려 주기" sub="읽은 답은 확인한 뒤에 써요" onPress={() => open({ mode: 'url', url: data.url })} chevron />
          <Text style={st.foot}>사진 · PDF · 엑셀은 PC에서 올릴 수 있어요</Text>
        </View>

        <View style={st.card}>
          <Head title="SODA가 배운 답" n={data.kb.length} />
          {data.kb.length ? (
            data.kb.map((r) => (
              <Pressable key={r.id} onPress={() => edit(r)} style={({ pressed }) => [st.row, pressed && st.pressed]}>
                <View style={{ flex: 1, gap: 1 }}>
                  <Text style={[st.rowTitle, !r.on && st.off]} numberOfLines={1}>
                    {r.q}
                  </Text>
                  <Text style={[st.rowSub, !r.on && st.off]} numberOfLines={1}>
                    {r.a}
                  </Text>
                </View>
                <Switch value={!!r.on} onValueChange={(v) => go('k' + r.id, { act: 'toggle', id: r.id, on: v })} trackColor={{ true: C.accent, false: C.line }} thumbColor="#fff" {...({ activeThumbColor: '#fff' } as object)} />
              </Pressable>
            ))
          ) : (
            <Text style={st.empty}>고객에게 직접 답을 보내면 여기에 쌓여요</Text>
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function Head({ title, n }: { title: string; n?: number }) {
  return (
    <View style={st.head}>
      <Text style={st.headText}>{title}</Text>
      {n ? <Text style={st.headN}>{n}</Text> : null}
    </View>
  );
}

function Row({ icon, title, sub, subTone, onPress, chevron, pill }: { icon?: string; title: string; sub?: string; subTone?: boolean; onPress: () => void; chevron?: boolean; pill?: string }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [st.row, pressed && st.pressed]}>
      {icon ? (
        <View style={st.ic}>
          <Glyph name={icon} size={22} />
        </View>
      ) : null}
      <View style={{ flex: 1, gap: 1 }}>
        <Text style={st.rowTitle} numberOfLines={1}>
          {title}
        </Text>
        {sub ? (
          <Text style={[st.rowSub, subTone && { color: C.accentInk }]} numberOfLines={1}>
            {sub}
          </Text>
        ) : null}
      </View>
      {pill ? (
        <View style={st.pill}>
          <Text style={st.pillT}>{pill}</Text>
        </View>
      ) : null}
      {chevron ? <Text style={st.chev}>›</Text> : null}
    </Pressable>
  );
}

// 토스 홈처럼: 연회색 바탕 위 흰 카드(둥글기 20, 옆 12), 카드 안 줄은 15/13, 오른쪽 작은 회색 버튼
const st = StyleSheet.create({
  page: { flex: 1, backgroundColor: C.band },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 24, paddingTop: 8, paddingBottom: 14 },
  title: { fontFamily: FONT, fontSize: 22, lineHeight: 31, fontWeight: '700', color: C.fg, letterSpacing: 0 },
  msg: { fontFamily: FONT, fontSize: 14, lineHeight: 21, color: C.green, paddingHorizontal: 24, paddingBottom: 10 },
  card: { backgroundColor: C.card, borderRadius: 20, marginHorizontal: 12, marginBottom: 10, paddingVertical: 8 },
  head: { flexDirection: 'row', alignItems: 'center', gap: 5, paddingHorizontal: 20, paddingTop: 12, paddingBottom: 4 },
  headText: { fontFamily: FONT, fontSize: 15, lineHeight: 22.5, fontWeight: '700', color: C.fg, letterSpacing: 0 },
  headN: { fontFamily: FONT, fontSize: 15, lineHeight: 22.5, fontWeight: '700', color: C.accent, letterSpacing: 0 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 20, paddingVertical: 11 },
  pressed: { backgroundColor: '#F9FAFB' },
  rowTitle: { fontFamily: FONT, fontSize: 15, lineHeight: 22.5, fontWeight: '600', color: C.fg, letterSpacing: 0 },
  rowSub: { fontFamily: FONT, fontSize: 13, lineHeight: 19.5, color: C.fg3, letterSpacing: 0 },
  off: { color: C.fg4 },
  ic: { width: 40, height: 40, borderRadius: 12, backgroundColor: '#F2F4F6', alignItems: 'center', justifyContent: 'center' },
  pill: { height: 30, paddingHorizontal: 11, borderRadius: 8, backgroundColor: C.fill, alignItems: 'center', justifyContent: 'center' },
  pillT: { fontFamily: FONT, fontSize: 13, fontWeight: '600', color: C.fg2 },
  chev: { fontFamily: FONT, fontSize: 18, color: C.fg4 },
  empty: { fontFamily: FONT, fontSize: 14, lineHeight: 21, color: C.fg3, paddingHorizontal: 20, paddingVertical: 10 },
  foot: { fontFamily: FONT, fontSize: 12, lineHeight: 18, color: C.fg3, textAlign: 'center', paddingTop: 6, paddingBottom: 6 },
  cta: { height: 48, borderRadius: 12, backgroundColor: C.accent, alignItems: 'center', justifyContent: 'center', marginHorizontal: 20, marginTop: 8, marginBottom: 8 },
  ctaText: { fontFamily: FONT, fontSize: 15, fontWeight: '700', color: '#fff', letterSpacing: 0 },
});
