// 요청 한 줄 (토스 목록처럼: 그림 없이 제목 15 · 설명 13, 오른쪽에 상태 글자만)
import { router } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { BizCase, fmtDate } from '../lib/api';
import { C, FONT, STATUS_TONE } from '../lib/theme';

export function CaseRow({ c }: { c: BizCase }) {
  const tone = c.overdue ? C.red : c.pending ? C.accentInk : (STATUS_TONE[c.status]?.fg ?? C.fg3);
  const label = c.overdue ? '기한 지남' : c.pending ? '승인 대기' : c.status_label;
  return (
    <Pressable onPress={() => router.push(`/case/${c.id}`)} style={({ pressed }) => [st.row, pressed && { backgroundColor: C.band }]}>
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={st.title} numberOfLines={1}>
          {c.title}
        </Text>
        <Text style={st.meta} numberOfLines={1}>
          {[c.name, c.category, fmtDate(c.updated)].filter(Boolean).join(' · ')}
        </Text>
      </View>
      <Text style={[st.state, { color: tone }]}>{label}</Text>
    </Pressable>
  );
}

const st = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12, paddingHorizontal: 12, marginHorizontal: -12, borderRadius: 12 },
  title: { fontFamily: FONT, fontSize: 15, lineHeight: 22.5, fontWeight: '500', color: C.fg, letterSpacing: 0 },
  meta: { fontFamily: FONT, fontSize: 13, lineHeight: 19.5, color: C.fg3, letterSpacing: 0 },
  state: { fontFamily: FONT, fontSize: 13, fontWeight: '600', letterSpacing: 0 },
});
