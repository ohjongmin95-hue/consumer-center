// 유형 6칸: 회색·연주황이 번갈아 드는 큰 아이콘 버튼 (웹 링크 페이지와 같은 모양)
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { C } from '../lib/theme';
import { CAT_ICON, Icon } from './Icon';

export const CATS = ['배송 조회', '교환', '반품·환불', '제품 불량', '고객 응대', '기타'];

export function CatGrid({ onPick }: { onPick: (cat: string) => void }) {
  return (
    <View style={st.grid}>
      {CATS.map((cat, i) => (
        <Pressable key={cat} onPress={() => onPick(cat)} style={st.cell}>
          {({ pressed }) => (
            <>
              <View style={[st.sq, { backgroundColor: i % 2 ? C.accentSoft : C.fill, transform: [{ scale: pressed ? 0.95 : 1 }] }]}>
                <Icon name={CAT_ICON[cat]} size={36} />
              </View>
              <Text style={st.label}>{cat}</Text>
            </>
          )}
        </Pressable>
      ))}
    </View>
  );
}

const st = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', rowGap: 18 },
  cell: { width: '33.333%', alignItems: 'center', gap: 8 },
  sq: { width: 88, height: 88, borderRadius: 26, alignItems: 'center', justifyContent: 'center' },
  label: { fontSize: 14, fontWeight: '500', color: C.fg2 },
});
