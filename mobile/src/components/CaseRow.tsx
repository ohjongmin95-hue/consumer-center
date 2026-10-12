import { router } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { BizCase, fmtDate } from '../lib/api';
import { C, R } from '../lib/theme';
import { CAT_ICON, Icon } from './Icon';
import { StatusPill } from './ui';

export function CaseRow({ c }: { c: BizCase }) {
  return (
    <Pressable onPress={() => router.push(`/case/${c.id}`)} style={({ pressed }) => [st.row, pressed && { backgroundColor: C.band }]}>
      <View style={st.ic}>
        <Icon name={CAT_ICON[c.category] ?? 'note'} size={26} />
      </View>
      <View style={{ flex: 1, gap: 5 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          {c.pending ? <StatusPill status="forwarded" label="승인 대기" /> : <StatusPill status={c.status} label={c.status_label} />}
          {c.overdue ? <StatusPill status="unresolved" label="기한 지남" /> : null}
        </View>
        <Text style={st.title} numberOfLines={1}>
          {c.title}
        </Text>
        <Text style={st.meta} numberOfLines={1}>
          {[c.name, c.category, fmtDate(c.updated)].filter(Boolean).join(' · ')}
        </Text>
      </View>
      <Text style={st.chev}>›</Text>
    </Pressable>
  );
}

const st = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 14, paddingHorizontal: 12, marginHorizontal: -12, borderRadius: R.md },
  ic: { width: 46, height: 46, borderRadius: 14, backgroundColor: C.fill, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 16, fontWeight: '600', color: C.fg, letterSpacing: -0.4 },
  meta: { fontSize: 13, color: C.fg3 },
  chev: { fontSize: 24, color: C.fg4, marginLeft: 4 },
});
