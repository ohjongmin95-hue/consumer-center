import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CaseRow } from '../../components/CaseRow';
import { Card, Loading, Notice } from '../../components/ui';
import { api, ApiError, BizCase } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { C, R } from '../../lib/theme';

const FILTERS: [string, string][] = [
  ['all', '전체'],
  ['pending', '승인 대기'],
  ['open', '처리 중'],
  ['done', '답변 완료'],
  ['bad', '주의'],
];

export default function CasesTab() {
  const { session, logout } = useAuth();
  const [f, setF] = useState('all');
  const param = useLocalSearchParams<{ q?: string }>();
  const [q, setQ] = useState(param.q ?? '');
  const [rows, setRows] = useState<BizCase[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [err, setErr] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(
    async (fil = f, query = q) => {
      if (!session) return;
      try {
        const r = await api.cases(session.token, fil, query.trim());
        setRows(r.cases);
        setCounts(r.counts);
        setErr('');
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return logout();
        setErr((e as Error).message);
      }
    },
    [session, f, q, logout],
  );
  // 홈의 경보를 누르면 그 상품 이름으로 찾은 목록을 연다
  useEffect(() => {
    if (param.q !== undefined) {
      setQ(param.q);
      setF('all');
      load('all', param.q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [param.q]);
  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.band }} edges={['top']}>
      <View style={st.head}>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <Text style={st.h1}>전체 민원</Text>
          <Pressable onPress={() => router.push('/new')} style={({ pressed }) => [st.add, pressed && { opacity: 0.7 }]} accessibilityRole="button">
            <Text style={{ color: C.accentInk, fontWeight: '700', fontSize: 14 }}>+ 직접 등록</Text>
          </Pressable>
        </View>
        <TextInput
          style={st.search}
          placeholder="고객 이름, 접수번호, 내용으로 찾기"
          placeholderTextColor={C.fg4}
          value={q}
          onChangeText={setQ}
          onSubmitEditing={() => load(f, q)}
          returnKeyType="search"
        />
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
          {FILTERS.map(([key, label]) => {
            const on = key === f;
            return (
              <Pressable
                key={key}
                onPress={() => {
                  setF(key);
                  setRows(null);
                  load(key, q);
                }}
                style={[st.chip, on && { backgroundColor: C.fg }]}
              >
                <Text style={[st.chipText, on && { color: '#fff' }]}>
                  {label} {counts[key] ?? ''}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
      </View>
      <ScrollView
        contentContainerStyle={{ paddingBottom: 24 }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={async () => {
              setRefreshing(true);
              await load();
              setRefreshing(false);
            }}
            tintColor={C.accent}
          />
        }
      >
        <Notice text={err} />
        {rows === null ? (
          <Loading />
        ) : (
          <Card>{rows.length ? rows.map((c) => <CaseRow key={c.id} c={c} />) : <Text style={st.empty}>해당하는 민원이 없습니다.</Text>}</Card>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  add: { height: 36, paddingHorizontal: 14, borderRadius: 18, backgroundColor: C.accentSoft, justifyContent: 'center' },
  head: { paddingHorizontal: 16, paddingTop: 16, paddingBottom: 12, gap: 12 },
  h1: { fontSize: 24, fontWeight: '700', color: C.fg, letterSpacing: -0.8, paddingHorizontal: 8 },
  search: { height: 48, borderRadius: R.md, backgroundColor: C.card, paddingHorizontal: 16, fontSize: 15, color: C.fg },
  chip: { height: 36, paddingHorizontal: 14, borderRadius: 18, backgroundColor: C.card, justifyContent: 'center' },
  chipText: { fontSize: 14, fontWeight: '600', color: C.fg2 },
  empty: { fontSize: 15, color: C.fg3, paddingVertical: 8 },
});
