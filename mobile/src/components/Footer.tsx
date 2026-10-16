// 하단 사업자 정보 (웹 하단과 같은 내용). 평소엔 로고·∨·저작권 한 줄만, 누르면 방침 링크와 사업자 정보를 펼친다
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useAuth } from '../lib/auth';
import { C, FONT } from '../lib/theme';

const FALLBACK = { name: '소보루', ceo: '오규섭', biz_no: '129-14-81596', address: '서울시 강남구 논현로 310-1 4층(역삼동, 정송빌딩)', manager: '오민주' };

export function Footer() {
  const { meta } = useAuth();
  const o = meta?.operator ?? FALLBACK;
  const [open, setOpen] = useState(false);
  return (
    <View style={st.wrap}>
      <Pressable style={st.head} onPress={() => setOpen((v) => !v)} hitSlop={8} accessibilityRole="button" accessibilityLabel={open ? '회사 정보 접기' : '회사 정보 펼치기'} accessibilityState={{ expanded: open }}>
        <Text style={st.wm}>소보루 CS</Text>
        <View style={[st.chev, open && { transform: [{ rotate: '-135deg' }], marginTop: 6 }]} />
      </Pressable>
      {open ? (
        <View style={{ marginTop: 14 }}>
          <Pressable style={{ marginBottom: 10, alignSelf: 'flex-start' }} onPress={() => WebBrowser.openBrowserAsync(meta?.privacy ?? 'https://cs.soboru.co.kr/privacy', { toolbarColor: '#FFFFFF' })}>
            <Text style={[st.t, { fontWeight: '700', color: C.fg2 }]}>개인정보 처리방침</Text>
          </Pressable>
          <Text style={st.t}>상호. {o.name}</Text>
          <Text style={st.t}>사업자등록번호. {o.biz_no}</Text>
          <Text style={st.t}>소재지. {o.address}</Text>
          <Text style={st.t}>관리자. {o.manager}</Text>
          <Text style={[st.t, { marginTop: 6, color: C.fg4 }]}>이 서비스에는 토스(비바리퍼블리카)가 제공한 Tossface가 적용되어 있습니다</Text>
        </View>
      ) : null}
      <Text style={st.copy}>© 2026 SOBORU. All rights reserved.</Text>
    </View>
  );
}

const st = StyleSheet.create({
  wrap: { marginHorizontal: 20, marginTop: 24, paddingTop: 22, paddingBottom: 16, borderTopWidth: 1, borderTopColor: C.line },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  wm: { fontFamily: FONT, fontSize: 17, fontWeight: '800', color: C.brand, letterSpacing: -0.6 },
  chev: { width: 10, height: 10, borderRightWidth: 2, borderBottomWidth: 2, borderColor: C.fg, transform: [{ rotate: '45deg' }], marginTop: -5, marginRight: 4 },
  t: { fontFamily: FONT, fontSize: 12, lineHeight: 19, color: C.fg3 },
  copy: { fontFamily: FONT, fontSize: 12, fontWeight: '600', color: C.fg3, marginTop: 12 },
});
