// 기업 고객센터: 웹 링크 페이지(/to/<id>)와 같은 구성
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CatGrid } from '../../components/CatGrid';
import { Chat } from '../../components/Chat';
import { Icon } from '../../components/Icon';
import { Btn, Loading, Notice } from '../../components/ui';
import { api, Company } from '../../lib/api';
import { C, R } from '../../lib/theme';

export default function CompanyPage() {
  const id = Number(useLocalSearchParams<{ id: string }>().id);
  const [co, setCo] = useState<Company | null>(null);
  const [err, setErr] = useState('');
  const [openRet, setOpenRet] = useState(false);
  useEffect(() => {
    api.company(id).then(setCo).catch((e) => setErr(e.message));
  }, [id]);
  if (err) return <Notice text={err} />;
  if (!co) return <Loading />;
  const newWith = (params: Record<string, string> = {}) => router.push({ pathname: '/new', params: { company_id: String(co.id), ...params } });

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.band }} edges={['bottom']}>
      <Stack.Screen options={{ title: co.name }} />
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }} keyboardShouldPersistTaps="handled">
        <View style={st.top}>
          <Text style={st.h1}>
            {co.name}에{'\n'}무엇을 도와드릴까요?
          </Text>
          <Text style={st.sub}>{co.member ? '담당자에게 바로 전달돼요' : `소보루 CS가 ${co.name}의 공식 연락처로 전달해 드려요`}</Text>
          <Text style={st.h2}>직접 골라서 접수하기</Text>
          <CatGrid onPick={(cat) => newWith({ category: cat })} />
        </View>
        <View style={st.band}>
          <View style={st.card}>
            <Chat companyId={co.id} greet={co.name + ' 고객센터예요'} />
          </View>
          <Text style={[st.h2, { marginHorizontal: 4 }]}>이런 것도 할 수 있어요</Text>
          <Pressable style={st.more} onPress={() => router.push('/mine')}>
            <View style={st.ic}>
              <Icon name="search" size={24} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={st.mt}>내 접수 확인</Text>
              <Text style={st.ms}>진행 상황과 답변을 봐요</Text>
            </View>
          </Pressable>
          {!!co.contact && (
            <View style={st.more}>
              <View style={st.ic}>
                <Icon name="phone" size={24} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={st.mt}>전화 문의</Text>
                <Text style={st.ms} selectable>
                  {co.contact}
                </Text>
              </View>
            </View>
          )}
          {!!co.ret_guide && (
            <Pressable style={[st.more, { flexDirection: 'column', alignItems: 'stretch' }]} onPress={() => setOpenRet(!openRet)}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
                <View style={st.ic}>
                  <Icon name="truck" size={24} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={st.mt}>반품 보내실 곳</Text>
                  <Text style={st.ms}>접수 후 안내에 따라 보내 주세요</Text>
                </View>
              </View>
              {openRet && <Text style={st.ret}>{co.ret_guide}</Text>}
            </Pressable>
          )}
        </View>
      </ScrollView>
      <View style={st.cta}>
        <Btn title={`${co.name}에 접수하기`} onPress={() => newWith()} style={{ borderRadius: 28 }} />
      </View>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  top: { backgroundColor: C.card, paddingHorizontal: 20, paddingTop: 12, paddingBottom: 32 },
  h1: { fontSize: 28, lineHeight: 39, fontWeight: '700', color: C.fg, letterSpacing: -1 },
  sub: { fontSize: 16, color: C.fg3, marginTop: 10 },
  h2: { fontSize: 20, fontWeight: '700', color: C.fg, letterSpacing: -0.6, marginTop: 32, marginBottom: 16 },
  band: { paddingHorizontal: 16, paddingTop: 24 },
  card: { backgroundColor: C.card, borderRadius: R.lg, padding: 20 },
  more: { backgroundColor: C.card, borderRadius: R.lg, padding: 18, flexDirection: 'row', alignItems: 'center', gap: 14, marginBottom: 10 },
  ic: { width: 44, height: 44, borderRadius: 14, backgroundColor: C.accentSoft, alignItems: 'center', justifyContent: 'center' },
  mt: { fontSize: 17, fontWeight: '700', color: C.fg, letterSpacing: -0.4 },
  ms: { fontSize: 14, color: C.fg3, marginTop: 2 },
  ret: { fontSize: 15, lineHeight: 23, color: C.fg2, backgroundColor: C.fill, borderRadius: R.sm, padding: 14, marginTop: 14 },
  cta: { paddingHorizontal: 20, paddingTop: 10, paddingBottom: 12, backgroundColor: C.band },
});
