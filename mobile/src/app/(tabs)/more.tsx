import { useState } from 'react';
import { Linking, Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Footer } from '../../components/Footer';
import { Btn, Card, H2 } from '../../components/ui';
import { useAuth } from '../../lib/auth';
import { C } from '../../lib/theme';

const BIZ = 'https://biz.soboru.co.kr';

export default function MoreTab() {
  const { session, logout } = useAuth();
  const [sure, setSure] = useState(false);
  if (!session) return null;
  const co = session.company;
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.band }} edges={['top']}>
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
        <View style={st.head}>
          <Text style={st.h1}>{co.name}</Text>
          <Text style={st.sub}>{co.login_id}</Text>
        </View>

        <Card>
          <H2>우리 가게 고객센터 링크</H2>
          <Text style={st.p}>쇼핑몰 상세페이지나 카카오톡 채널에 이 링크를 걸어 두면, 고객 문의가 소보루로 들어와 대신 응대합니다.</Text>
          <Text style={st.link} selectable>
            {co.link}
          </Text>
          <Btn title="링크 공유하기" kind="soft" onPress={() => Share.share({ message: co.link })} />
        </Card>

        <Card style={{ paddingVertical: 8 }}>
          <Row title="자동 처리 규칙" sub="어떤 민원을 소보루가 바로 처리할지 정합니다" url={`${BIZ}/rules`} />
          <Row title="처리 통계" sub="자동 처리율, 해결률, 주별 민원 수" url={`${BIZ}/stats`} />
          <Row title="회사 정보와 알림 설정" sub="연락처, 반품 주소, 알림톡" url={`${BIZ}/settings`} />
          <Row title="이용 안내" sub="소보루 CS 사용법" url={`${BIZ}/guide`} last />
        </Card>
        <Text style={st.note}>위 메뉴는 기업 사이트에서 열립니다. 처음 한 번은 사이트에 로그인해 주세요.</Text>

        <View style={{ marginHorizontal: 16, marginTop: 12 }}>
          {sure ? (
            <View style={{ flexDirection: 'row', gap: 8 }}>
              <Btn title="취소" kind="gray" onPress={() => setSure(false)} style={{ flex: 1 }} />
              <Btn title="로그아웃" kind="danger" onPress={logout} style={{ flex: 1 }} />
            </View>
          ) : (
            <Btn title="로그아웃" kind="gray" onPress={() => setSure(true)} />
          )}
        </View>
        <Footer />
      </ScrollView>
    </SafeAreaView>
  );
}

function Row({ title, sub, url, last }: { title: string; sub: string; url: string; last?: boolean }) {
  return (
    <Pressable onPress={() => Linking.openURL(url)} style={({ pressed }) => [st.row, !last && st.rowLine, pressed && { opacity: 0.6 }]}>
      <View style={{ flex: 1, gap: 3 }}>
        <Text style={st.rowTitle}>{title}</Text>
        <Text style={st.rowSub}>{sub}</Text>
      </View>
      <Text style={st.chev}>›</Text>
    </Pressable>
  );
}

const st = StyleSheet.create({
  head: { paddingHorizontal: 24, paddingTop: 20, paddingBottom: 18, gap: 4 },
  h1: { fontSize: 24, fontWeight: '700', color: C.fg, letterSpacing: -0.8 },
  sub: { fontSize: 14, color: C.fg3 },
  p: { fontSize: 15, lineHeight: 23, color: C.fg2, marginBottom: 12 },
  link: { fontSize: 15, fontWeight: '600', color: C.accentInk, backgroundColor: C.accentSoft, borderRadius: 12, padding: 14, marginBottom: 12 },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 14 },
  rowLine: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.line },
  rowTitle: { fontSize: 16, fontWeight: '600', color: C.fg },
  rowSub: { fontSize: 13, color: C.fg3 },
  chev: { fontSize: 24, color: C.fg4 },
  note: { fontSize: 13, color: C.fg3, marginHorizontal: 24, marginTop: 2 },
});
