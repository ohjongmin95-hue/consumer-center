// 교환·반품: 웹 '교환·반품'과 같은 단계별 보기 (새로 접수 → 회수 중 → 다음 처리 대기 → 처리 완료)
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { CaseRow } from '../components/CaseRow';
import { Card, Loading, Notice, Screen } from '../components/ui';
import { api } from '../lib/api';
import { C, R, FONT } from '../lib/theme';
import { useLoad } from '../lib/useLoad';

export default function Returns() {
  const [stage, setStage] = useState('');
  const { data, err, reload } = useLoad((t) => api.returns(t));
  if (!data) return <Screen>{err ? <Notice text={err} /> : <Loading />}</Screen>;
  const rows = data.cases.filter((c) => !stage || c.stage === stage);
  return (
    <Screen onRefresh={reload}>
      <View style={st.grid}>
        {data.stages.map((s) => (
          <Pressable key={s.key} onPress={() => setStage(stage === s.key ? '' : s.key)} style={({ pressed }) => [st.tile, stage === s.key && st.tileOn, pressed && { opacity: 0.7 }]}>
            <Text style={st.tileL}>{s.label}</Text>
            <Text style={st.tileV}>{s.n}</Text>
          </Pressable>
        ))}
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingHorizontal: 14, paddingBottom: 12 }}>
        {[{ key: '', label: '전체', n: data.cases.length }, ...data.stages].map((s) => {
          const on = s.key === stage;
          return (
            <Pressable key={s.key || 'all'} onPress={() => setStage(s.key)} style={[st.chip, on && { backgroundColor: C.fg }]}>
              <Text style={[st.chipT, on && { color: '#fff' }]}>
                {s.label} {s.n}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>
      <Card>
        {rows.length ? rows.map((c) => <CaseRow key={c.id} c={{ ...c, status_label: c.stage_label }} />) : <Text style={st.empty}>여기에 해당하는 요청이 없어요</Text>}
      </Card>
    </Screen>
  );
}

const st = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, margin: 14, marginBottom: 12 },
  tile: { flexBasis: '47%', flexGrow: 1, backgroundColor: C.card, borderRadius: R.lg, padding: 18, gap: 8 },
  tileOn: { borderWidth: 2, borderColor: C.accent, padding: 16 },
  tileL: { fontFamily: FONT, fontSize: 14, fontWeight: '600', color: C.fg2 },
  tileV: { fontFamily: FONT, fontSize: 26, fontWeight: '700', color: C.fg, fontVariant: ['tabular-nums'] },
  chip: { height: 38, paddingHorizontal: 14, borderRadius: 19, backgroundColor: C.card, justifyContent: 'center' },
  chipT: { fontFamily: FONT, fontSize: 14, fontWeight: '600', color: C.fg2 },
  empty: { fontFamily: FONT, fontSize: 15, color: C.fg3, paddingVertical: 8 },
});
