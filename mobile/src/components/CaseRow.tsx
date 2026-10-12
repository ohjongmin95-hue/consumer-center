import { router } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { CaseSummary, fmtDate } from '../lib/api';
import { C, R } from '../lib/theme';
import { StatusPill } from './ui';

export function CaseRow({ c }: { c: CaseSummary }) {
  return (
    <Pressable onPress={() => router.push(`/case/${c.id}`)} style={({ pressed }) => [st.row, pressed && { backgroundColor: C.band }]}>
      <View style={{ flex: 1, gap: 6 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <StatusPill status={c.status} label={c.status_label} />
          <Text style={st.co} numberOfLines={1}>
            {c.company_name}
          </Text>
        </View>
        <Text style={st.title} numberOfLines={1}>
          {c.title}
        </Text>
        <Text style={st.meta}>
          {c.category} · {fmtDate(c.updated)}
        </Text>
      </View>
      <Text style={st.chev}>›</Text>
    </Pressable>
  );
}

const st = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 14, paddingHorizontal: 12, marginHorizontal: -12, borderRadius: R.md },
  co: { fontSize: 14, color: C.fg3, fontWeight: '600', flexShrink: 1 },
  title: { fontSize: 17, fontWeight: '600', color: C.fg, letterSpacing: -0.4 },
  meta: { fontSize: 13, color: C.fg3 },
  chev: { fontSize: 24, color: C.fg4, marginLeft: 8 },
});
