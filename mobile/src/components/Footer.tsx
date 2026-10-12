// 하단 사업자 정보 (웹 하단과 같은 내용)
import * as WebBrowser from 'expo-web-browser';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useAuth } from '../lib/auth';
import { C } from '../lib/theme';

const FALLBACK = { name: '소보루', ceo: '오규섭', biz_no: '129-14-81596', address: '서울시 강남구 논현로 310-1 4층(역삼동, 정송빌딩)', manager: '오민주' };

export function Footer() {
  const { meta } = useAuth();
  const o = meta?.operator ?? FALLBACK;
  return (
    <View style={st.wrap}>
      <View style={{ flexDirection: 'row', gap: 16, marginBottom: 12 }}>
        <Pressable onPress={() => WebBrowser.openBrowserAsync(meta?.privacy ?? 'https://cs.soboru.co.kr/privacy', { toolbarColor: '#FFFFFF' })}>
          <Text style={[st.t, { fontWeight: '700', color: C.fg2 }]}>개인정보 처리방침</Text>
        </Pressable>
      </View>
      <Text style={st.t}>상호. {o.name}</Text>
      <Text style={st.t}>사업자등록번호. {o.biz_no}</Text>
      <Text style={st.t}>소재지. {o.address}</Text>
      <Text style={st.t}>관리자. {o.manager}</Text>
      <Text style={[st.t, { marginTop: 10 }]}>© 2026 SOBORU. All rights reserved.</Text>
    </View>
  );
}

const st = StyleSheet.create({
  wrap: { paddingHorizontal: 24, paddingTop: 28, paddingBottom: 12 },
  t: { fontSize: 12, lineHeight: 19, color: C.fg3 },
});
