import { useState } from 'react';
import { router } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Glyph } from '../../components/Glyph';
import { SITE_BASE } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { C, FONT } from '../../lib/theme';

// 전체: 웹 왼쪽 메뉴와 같은 순서. 처음 한 번만 하는 연결·직원 관리는 웹에서 연다
const web = (path: string) => () => WebBrowser.openBrowserAsync(SITE_BASE + path, { toolbarColor: '#FFFFFF' });
const MENU: { icon: string; title: string; sub: string; go: () => void }[] = [
  { icon: 'truck', title: '주문·배송', sub: '주문 조회 · 배송', go: () => router.push('/orders') },
  { icon: 'exchange', title: '교환·반품', sub: '접수 · 회수 · 환불', go: () => router.push('/returns') },
  { icon: 'doc', title: '상품정보', sub: '상품 · 안내문', go: () => router.push('/products') },
  { icon: 'bolt', title: '자동 처리', sub: '처리 방법 · 승인', go: () => router.navigate('/auto') },
  { icon: 'soda', title: 'SODA 가르치기', sub: '모르는 질문 · 배운 답', go: () => router.push('/soda') },
  { icon: 'template', title: '답변 템플릿', sub: '자주 쓰는 답', go: () => router.push('/macros') },
  { icon: 'flow', title: '자동화 규칙', sub: '웹에서 열기', go: web('/automations') },
  { icon: 'chart', title: '통계', sub: '처리율 · 응답 시간', go: () => router.push('/stats') },
  { icon: 'report', title: '월간 리포트', sub: '이번 달 요약', go: () => router.push('/report') },
  { icon: 'book', title: '응대 가이드', sub: '상황별 답변', go: () => router.push('/guide') },
  { icon: 'search', title: '법·제도 소식', sub: '전자상거래 · 분쟁', go: () => router.push('/news') },
  { icon: 'shield', title: '이용 안내', sub: '처음 쓰는 법', go: () => router.push('/howto') },
  { icon: 'link', title: '서비스 연동', sub: '웹에서 열기', go: web('/connect') },
  { icon: 'team', title: '팀', sub: '웹에서 열기', go: web('/team') },
];

// 전체 (토스 '전체' 탭처럼): 위에 가게 이름과 오른쪽 회색 '설정', 연회색 바탕 위 흰 판 하나에 메뉴 줄
export default function MoreTab() {
  const { session, logout } = useAuth();
  const [sure, setSure] = useState(false);
  if (!session) return null;
  const co = session.company;
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.band }} edges={['top']}>
      <ScrollView contentContainerStyle={{ paddingBottom: 32 }}>
        <View style={st.head}>
          <Text style={st.name} numberOfLines={1}>
            {co.name}
          </Text>
          <Pressable onPress={() => router.push('/settings')} hitSlop={8}>
            <Text style={st.headLink}>설정</Text>
          </Pressable>
        </View>

        <View style={st.panel}>
          {MENU.map((m) => (
            <Pressable key={m.title} onPress={m.go} style={({ pressed }) => [st.row, pressed && { backgroundColor: C.band }]}>
              <View style={st.ic}>
                <Glyph name={m.icon} size={22} />
              </View>
              <Text style={st.rowT} numberOfLines={1}>
                {m.title}
              </Text>
              <Text style={st.rowS} numberOfLines={1}>
                {m.sub}
              </Text>
            </Pressable>
          ))}
        </View>

        <View style={[st.panel, { paddingHorizontal: 24, paddingVertical: 20 }]}>
          <Text style={st.linkLabel}>우리 가게 고객센터 링크</Text>
          <Text style={st.link} selectable numberOfLines={1}>
            {co.link}
          </Text>
          <Pressable onPress={() => Share.share({ message: co.link })} style={({ pressed }) => [st.pill, pressed && { backgroundColor: C.line }]}>
            <Text style={st.pillT}>링크 공유하기</Text>
          </Pressable>
        </View>

        <Pressable onPress={() => (sure ? logout() : setSure(true))} style={st.out} hitSlop={8}>
          <Text style={[st.outT, sure && { color: C.red }]}>{sure ? '한 번 더 누르면 로그아웃해요' : '로그아웃'}</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  head: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 24, paddingTop: 22, paddingBottom: 16 },
  name: { flex: 1, fontFamily: FONT, fontSize: 20, lineHeight: 29, fontWeight: '700', color: C.fg, letterSpacing: 0 },
  headLink: { fontFamily: FONT, fontSize: 15, fontWeight: '500', color: C.fg3 },
  panel: { backgroundColor: C.card, borderRadius: 20, marginHorizontal: 12, marginBottom: 10, paddingVertical: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 20, paddingVertical: 10 },
  ic: { width: 40, height: 40, borderRadius: 12, backgroundColor: '#F2F4F6', alignItems: 'center', justifyContent: 'center' },
  rowT: { fontFamily: FONT, fontSize: 16, lineHeight: 24, fontWeight: '500', color: C.fg, letterSpacing: 0, flexShrink: 0 },
  rowS: { flex: 1, textAlign: 'right', fontFamily: FONT, fontSize: 13, color: C.fg3, letterSpacing: 0 },
  linkLabel: { fontFamily: FONT, fontSize: 13, fontWeight: '600', color: C.fg3 },
  link: { fontFamily: FONT, fontSize: 15, fontWeight: '600', color: C.fg, marginTop: 4, marginBottom: 12 },
  pill: { alignSelf: 'flex-start', height: 32, paddingHorizontal: 12, borderRadius: 8, backgroundColor: C.fill, alignItems: 'center', justifyContent: 'center' },
  pillT: { fontFamily: FONT, fontSize: 13, fontWeight: '600', color: C.fg2 },
  out: { alignSelf: 'center', marginTop: 14, paddingVertical: 8 },
  outT: { fontFamily: FONT, fontSize: 13, color: C.fg3 },
});
