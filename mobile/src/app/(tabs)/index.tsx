import { router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Image, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ScrollView } from 'react-native';
import { CaseRow } from '../../components/CaseRow';
import { CatGrid } from '../../components/CatGrid';
import { Btn } from '../../components/ui';
import { api, CaseSummary, Company } from '../../lib/api';
import { useStore } from '../../lib/store';
import { C, R } from '../../lib/theme';

export default function Home() {
  const { tokens, ready } = useStore();
  const [q, setQ] = useState('');
  const [found, setFound] = useState<Company[] | null>(null);
  const [recent, setRecent] = useState<CaseSummary[]>([]);

  // 회사 이름으로 찾기 (입력이 멈추면)
  useEffect(() => {
    const t = q.trim();
    if (!t) return setFound(null);
    const h = setTimeout(() => api.companies(t).then(setFound).catch(() => setFound([])), 250);
    return () => clearTimeout(h);
  }, [q]);

  useFocusEffect(
    useCallback(() => {
      if (!ready || !tokens.length) return setRecent([]);
      api.mine(tokens).then((r) => setRecent(r.cases.slice(0, 3))).catch(() => {});
    }, [ready, tokens]),
  );

  const openCompany = (c: Company) => router.push(c.member ? `/company/${c.id}` : { pathname: '/new', params: { company_id: String(c.id), company: c.name } });

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.card }} edges={['top']}>
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingBottom: 32, backgroundColor: C.band, flexGrow: 1 }}>
        <View style={st.top}>
          <View style={st.brand}>
            <Image source={require('../../../assets/soboru-char.png')} style={{ width: 34, height: 26 }} />
            <Text style={st.wm}>소보루 CS</Text>
          </View>

          <Text style={st.h1}>
            불편한 일,{'\n'}
            <Text style={{ color: C.accent }}>한 번에</Text> 해결해요
          </Text>
          <Text style={st.sub}>회사 이름을 찾으면{'\n'}그 회사 고객센터로 바로 연결해 드려요</Text>

          <TextInput value={q} onChangeText={setQ} placeholder="회사나 쇼핑몰 이름" placeholderTextColor={C.fg4} style={st.search} returnKeyType="search" />
          {found && (
            <View style={st.results}>
              {found.map((c) => (
                <Pressable key={c.id} onPress={() => openCompany(c)} style={({ pressed }) => [st.res, pressed && { backgroundColor: C.band }]}>
                  <View style={st.av}>
                    <Text style={st.avText}>{c.name[0]}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={st.resName}>{c.name}</Text>
                    <Text style={st.resSub}>{c.member ? '고객센터로 연결' : '접수로 이어가기'}</Text>
                  </View>
                </Pressable>
              ))}
              <Pressable onPress={() => router.push({ pathname: '/new', params: { company: q.trim() } })} style={({ pressed }) => [st.res, pressed && { backgroundColor: C.band }]}>
                <View style={{ flex: 1 }}>
                  <Text style={st.resName}>찾는 회사가 없어요</Text>
                  <Text style={st.resSub}>‘{q.trim()}’(으)로 바로 접수하기</Text>
                </View>
              </Pressable>
            </View>
          )}
          {!found && (
            <View style={{ flexDirection: 'row', gap: 10, marginTop: 14 }}>
              <Btn title="접수하기" onPress={() => router.push('/new')} style={{ flex: 1 }} />
              <Btn title="내 접수 확인" kind="gray" onPress={() => router.push('/mine')} style={{ flex: 1 }} />
            </View>
          )}

          <Text style={st.h2}>직접 골라서 접수하기</Text>
          <CatGrid onPick={(cat) => router.push({ pathname: '/new', params: { category: cat } })} />
        </View>

        {recent.length > 0 && (
          <View style={st.section}>
            <View style={st.shead}>
              <Text style={[st.h2, { marginTop: 0, marginBottom: 0 }]}>내 접수</Text>
              <Pressable onPress={() => router.push('/mine')}>
                <Text style={st.more}>전체보기</Text>
              </Pressable>
            </View>
            <View style={st.card}>
              {recent.map((c) => (
                <CaseRow key={c.id} c={c} />
              ))}
            </View>
          </View>
        )}

        <View style={st.section}>
          <Text style={[st.h2, { marginTop: 0 }]}>이렇게 진행돼요</Text>
          {[
            ['한 번만 접수', '기업과 불편한 일, 원하는 해결을 적어요'],
            ['기업이 답변', '입점 기업 담당자가 바로 확인하고 답변해요'],
            ['해결 확인', '해결되지 않으면 공식 피해구제로 안내해요'],
          ].map(([t, d], i) => (
            <View key={t} style={[st.card, st.step]}>
              <View style={st.num}>
                <Text style={st.numText}>{i + 1}</Text>
              </View>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={st.stepT}>{t}</Text>
                <Text style={st.stepD}>{d}</Text>
              </View>
            </View>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  top: { backgroundColor: C.card, paddingHorizontal: 20, paddingBottom: 32 },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 6, height: 56 },
  wm: { fontSize: 19, fontWeight: '800', color: C.accent, letterSpacing: -0.8 },
  h1: { fontSize: 30, lineHeight: 41, fontWeight: '800', color: C.fg, letterSpacing: -1, marginTop: 20 },
  sub: { fontSize: 16, lineHeight: 24, color: C.fg2, marginTop: 12 },
  search: { height: 56, borderRadius: R.md, backgroundColor: C.fill, paddingHorizontal: 18, fontSize: 16, color: C.fg, marginTop: 24 },
  results: { backgroundColor: C.card, borderRadius: R.md, marginTop: 8, borderWidth: 1, borderColor: C.line, overflow: 'hidden' },
  res: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 12 },
  av: { width: 40, height: 40, borderRadius: 14, backgroundColor: C.accentSoft, alignItems: 'center', justifyContent: 'center' },
  avText: { fontSize: 17, fontWeight: '700', color: C.accentInk },
  resName: { fontSize: 16, fontWeight: '600', color: C.fg },
  resSub: { fontSize: 13, color: C.fg3, marginTop: 2 },
  h2: { fontSize: 20, fontWeight: '700', color: C.fg, letterSpacing: -0.6, marginTop: 36, marginBottom: 18 },
  section: { paddingHorizontal: 16, paddingTop: 28 },
  shead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14, paddingHorizontal: 4 },
  more: { fontSize: 15, color: C.fg3, fontWeight: '600' },
  card: { backgroundColor: C.card, borderRadius: R.lg, paddingHorizontal: 20, paddingVertical: 6 },
  step: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 18, marginBottom: 10 },
  num: { width: 40, height: 40, borderRadius: 20, backgroundColor: C.accentSoft, alignItems: 'center', justifyContent: 'center' },
  numText: { fontSize: 17, fontWeight: '700', color: C.accentInk },
  stepT: { fontSize: 17, fontWeight: '700', color: C.fg },
  stepD: { fontSize: 14, color: C.fg3 },
});
