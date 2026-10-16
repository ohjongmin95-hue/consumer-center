import { useState } from 'react';
import { router } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Icon } from '../../components/Icon';
import { Btn, Card, H2, TopBar } from '../../components/ui';
import { SITE_BASE } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { C, FONT } from '../../lib/theme';

// 전체: 웹 왼쪽 메뉴와 같은 순서. 처음 한 번만 하는 연결·직원 관리는 웹에서 연다
const web = (path: string) => () => WebBrowser.openBrowserAsync(SITE_BASE + path, { toolbarColor: '#FFFFFF' });
const GROUPS: { icon: string; title: string; go: () => void; web?: boolean }[][] = [
  [
    { icon: 'truck', title: '주문·배송', go: () => router.push('/orders') },
    { icon: 'exchange', title: '교환·반품', go: () => router.push('/returns') },
    { icon: 'box', title: '상품정보', go: () => router.push('/products') },
  ],
  [
    { icon: 'bolt', title: '자동 처리', go: () => router.navigate('/auto') },
    { icon: 'macro', title: '답변 템플릿', go: () => router.push('/macros') },
    { icon: 'flow', title: '자동화 규칙', go: web('/automations'), web: true },
  ],
  [
    { icon: 'chart', title: '통계', go: () => router.push('/stats') },
    { icon: 'note', title: '월간 리포트', go: () => router.push('/report') },
  ],
  [
    { icon: 'guide', title: '응대 가이드', go: () => router.push('/guide') },
    { icon: 'search', title: '법·제도 소식', go: () => router.push('/news') },
    { icon: 'reply', title: '이용 안내', go: () => router.push('/howto') },
  ],
  [
    { icon: 'link', title: '서비스 연동', go: web('/connect'), web: true },
    { icon: 'user', title: '팀', go: web('/team'), web: true },
    { icon: 'gear', title: '회사 정보와 알림 설정', go: () => router.push('/settings') },
  ],
];

export default function MoreTab() {
  const { session, logout } = useAuth();
  const [sure, setSure] = useState(false);
  if (!session) return null;
  const co = session.company;
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.band }} edges={['top']}>
      <TopBar />
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
        <View style={st.head}>
          <Text style={st.h1}>{co.name}</Text>
          <Text style={st.sub}>{co.login_id}</Text>
        </View>

        {GROUPS.map((g, i) => (
          <Card key={i} style={{ paddingVertical: 6 }}>
            {g.map((m) => (
              <Pressable key={m.title} onPress={m.go} style={({ pressed }) => [st.row, pressed && { opacity: 0.6 }]}>
                <Icon name={m.icon} size={26} />
                <Text style={st.rowT}>{m.title}</Text>
                {m.web ? <Text style={st.webTag}>웹에서 열기</Text> : null}
                <Text style={st.chev}>›</Text>
              </Pressable>
            ))}
          </Card>
        ))}

        <Card>
          <H2>우리 가게 고객센터 링크</H2>
          <Text style={st.link} selectable>
            {co.link}
          </Text>
          <Btn title="링크 공유하기" onPress={() => Share.share({ message: co.link })} />
        </Card>

        <View style={{ marginHorizontal: 16, marginTop: 4 }}>
          {sure ? (
            <View style={{ flexDirection: 'row', gap: 8 }}>
              <Btn title="취소" kind="gray" onPress={() => setSure(false)} style={{ flex: 1 }} />
              <Btn title="로그아웃" kind="danger" onPress={logout} style={{ flex: 1 }} />
            </View>
          ) : (
            <Btn title="로그아웃" kind="gray" onPress={() => setSure(true)} />
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  head: { paddingHorizontal: 24, paddingTop: 8, paddingBottom: 16, gap: 4 },
  h1: { fontFamily: FONT, fontSize: 24, fontWeight: '700', color: C.fg, letterSpacing: -0.8 },
  sub: { fontFamily: FONT, fontSize: 14, color: C.fg3 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 14 },
  rowT: { flex: 1, fontFamily: FONT, fontSize: 17, fontWeight: '600', color: C.fg, letterSpacing: -0.3 },
  webTag: { fontFamily: FONT, fontSize: 12, fontWeight: '600', color: C.fg3 },
  chev: { fontFamily: FONT, fontSize: 24, color: C.fg4 },
  link: { fontFamily: FONT, fontSize: 15, fontWeight: '600', color: C.accentInk, backgroundColor: C.accentSoft, borderRadius: 12, padding: 14, marginBottom: 12 },
});
