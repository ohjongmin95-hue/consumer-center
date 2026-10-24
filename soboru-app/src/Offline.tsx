// 사이트를 못 불러왔을 때 (인터넷 끊김·서버 점검)
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';
import { ORANGE } from './TabBar';

export default function Offline({ onRetry }: { onRetry: () => void }) {
  return (
    <View style={s.wrap}>
      <Image source={require('../assets/wordmark.png')} style={s.img} resizeMode="contain" />
      <Text style={s.title}>연결이 잠시 끊겼어요</Text>
      <Text style={s.body}>인터넷 연결을 확인한 뒤 다시 시도해 주세요.</Text>
      <Pressable style={({ pressed }) => [s.btn, pressed && { opacity: 0.8 }]} onPress={onRetry} accessibilityRole="button">
        <Text style={s.btnText}>다시 시도</Text>
      </Pressable>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center', padding: 32 },
  img: { width: 160, height: 32, marginBottom: 28 },
  title: { fontSize: 19, fontWeight: '700', color: '#1F1A17', marginBottom: 8 },
  body: { fontSize: 15, color: '#6B625B', textAlign: 'center', marginBottom: 24 },
  btn: { backgroundColor: ORANGE, borderRadius: 12, paddingHorizontal: 28, paddingVertical: 13 },
  btnText: { color: '#FFFFFF', fontSize: 16, fontWeight: '700' },
});
