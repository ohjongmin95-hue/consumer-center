import { useState } from 'react';
import { router } from 'expo-router';
import { ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Footer } from '../../components/Footer';
import { Btn, Card, H2, MenuRow } from '../../components/ui';
import { useAuth } from '../../lib/auth';
import { C, FONT } from '../../lib/theme';

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

        <Card style={{ paddingVertical: 4 }}>
          <MenuRow title="자동 처리 규칙" sub="어떤 요청을 소보루가 바로 처리할지 정합니다" onPress={() => router.push('/rules')} />
          <MenuRow title="상품정보" sub="상담창이 가격·재고·사용법 문의에 답할 때 봅니다" onPress={() => router.push('/products')} />
          <MenuRow title="요청 직접 등록" sub="전화·쇼핑몰 문의·DM으로 받은 요청 올리기" onPress={() => router.push('/new')} last />
        </Card>
        <Card style={{ paddingVertical: 4 }}>
          <MenuRow title="처리 통계" sub="자동 처리율, 해결률, 주별 요청 수" onPress={() => router.push('/stats')} />
          <MenuRow title="월간 리포트" sub="지난달 요청을 한 장으로" onPress={() => router.push('/report')} last />
        </Card>
        <Card style={{ paddingVertical: 4 }}>
          <MenuRow title="이용 안내" sub="소보루 CS 사용법과 자주 묻는 질문" onPress={() => router.push('/howto')} />
          <MenuRow title="응대 가이드" sub="상황별 법 조항과 예시 답변" onPress={() => router.push('/guide')} />
          <MenuRow title="법·제도 소식" sub="사장님이 알아야 할 바뀐 규정" onPress={() => router.push('/news')} last />
        </Card>
        <Card style={{ paddingVertical: 4 }}>
          <MenuRow title="회사 정보와 알림 설정" sub="연락처, 반품 주소, 알림, 비밀번호" onPress={() => router.push('/settings')} last />
        </Card>

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

const st = StyleSheet.create({
  head: { paddingHorizontal: 24, paddingTop: 20, paddingBottom: 18, gap: 4 },
  h1: { fontFamily: FONT, fontSize: 24, fontWeight: '700', color: C.fg, letterSpacing: -0.8 },
  sub: { fontFamily: FONT, fontSize: 14, color: C.fg3 },
  p: { fontFamily: FONT, fontSize: 15, lineHeight: 23, color: C.fg2, marginBottom: 12 },
  link: { fontFamily: FONT, fontSize: 15, fontWeight: '600', color: C.accentInk, backgroundColor: C.accentSoft, borderRadius: 12, padding: 14, marginBottom: 12 },
});
