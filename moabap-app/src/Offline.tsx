// 화면을 못 불러왔을 때 (인터넷 끊김·서버 점검)
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';

export default function Offline({ onRetry }: { onRetry: () => void }) {
  return (
    <View style={s.wrap}>
      <Image source={require('../assets/splash.png')} style={s.img} resizeMode="contain" />
      <Text style={s.title}>연결이 잠시 끊겼어요</Text>
      <Text style={s.body}>인터넷 연결을 확인한 뒤 다시 시도해 주세요.</Text>
      <Pressable style={({ pressed }) => [s.btn, pressed && { opacity: 0.8 }]} onPress={onRetry} accessibilityRole="button">
        <Text style={s.btnText}>다시 시도</Text>
      </Pressable>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: '#F7F5FA', alignItems: 'center', justifyContent: 'center', padding: 32 },
  img: { width: 96, height: 96, marginBottom: 24 },
  title: { fontSize: 19, fontWeight: '700', color: '#191F28', marginBottom: 8 },
  body: { fontSize: 15, color: '#4E5968', textAlign: 'center', marginBottom: 24 },
  btn: { backgroundColor: '#B57BFF', borderRadius: 14, paddingHorizontal: 28, paddingVertical: 14 },
  btnText: { color: '#FFFFFF', fontSize: 16, fontWeight: '700' },
});
