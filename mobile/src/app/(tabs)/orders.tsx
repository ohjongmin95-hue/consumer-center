import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Card, Loading, Notice } from '../../components/ui';
import { api, ApiError, Orders } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { C, R } from '../../lib/theme';

// 주문 장부: 웹에서 올린 판매처 주문을 앱에서 보고 상태·송장을 처리한다
export default function OrdersTab() {
  const { session, logout } = useAuth();
  const [g, setG] = useState('all');
  const [q, setQ] = useState('');
  const [d, setD] = useState<Orders | null>(null);
  const [err, setErr] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(
    async (group = g, query = q) => {
      if (!session) return;
      try {
        setD(await api.orders(session.token, group, query.trim()));
        setErr('');
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return logout();
        setErr((e as Error).message);
      }
    },
    [session, g, q, logout],
  );
  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.band }} edges={['top']}>
      <View style={st.head}>
        <Text style={st.h1}>주문</Text>
        <TextInput style={st.search} placeholder="주문번호, 구매자, 상품, 송장으로 찾기" placeholderTextColor={C.fg4} value={q} onChangeText={setQ} onSubmitEditing={() => load(g, q)} returnKeyType="search" />
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
          {(d?.groups ?? [{ key: 'all', label: '전체' }]).map(({ key, label }) => {
            const on = key === g;
            return (
              <Pressable key={key} onPress={() => (setG(key), setD(null), load(key, q))} style={[st.chip, on && { backgroundColor: C.fg }]}>
                <Text style={[st.chipText, on && { color: '#fff' }]}>
                  {label} {d?.counts[key] ?? ''}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
      </View>
      <ScrollView
        contentContainerStyle={{ paddingBottom: 24 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => (setRefreshing(true), await load(), setRefreshing(false))} tintColor={C.accent} />}
      >
        <Notice text={err} />
        {d === null ? (
          <Loading />
        ) : (
          <Card>
            {d.orders.length ? (
              d.orders.map((o, i) => (
                <Pressable key={o.id} onPress={() => router.push(`/order/${o.id}`)} style={({ pressed }) => [st.row, i === d.orders.length - 1 && { borderBottomWidth: 0 }, pressed && { backgroundColor: C.band }]}>
                  <View style={{ flex: 1, gap: 2 }}>
                    <Text style={st.t} numberOfLines={1}>
                      {o.product || o.order_no}
                    </Text>
                    <Text style={st.s} numberOfLines={1}>
                      {o.order_no}
                      {o.buyer ? ` · ${o.buyer}` : ''}
                      {o.ordered_on ? ` · ${o.ordered_on}` : ''}
                    </Text>
                  </View>
                  <Text style={st.pill}>{o.status_label}</Text>
                </Pressable>
              ))
            ) : (
              <Text style={st.empty}>{q ? '찾는 주문이 없어요.' : '아직 주문이 없어요. 웹 화면의 주문 메뉴에서 판매처 주문 파일을 올려 주세요.'}</Text>
            )}
          </Card>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  head: { paddingHorizontal: 16, paddingTop: 16, paddingBottom: 12, gap: 12 },
  h1: { fontSize: 24, fontWeight: '700', color: C.fg, letterSpacing: -0.8, paddingHorizontal: 8 },
  search: { height: 48, borderRadius: R.md, backgroundColor: C.card, paddingHorizontal: 16, fontSize: 15, color: C.fg },
  chip: { height: 36, paddingHorizontal: 14, borderRadius: 18, backgroundColor: C.card, justifyContent: 'center' },
  chipText: { fontSize: 14, fontWeight: '600', color: C.fg2 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: C.line },
  t: { fontSize: 16, fontWeight: '600', color: C.fg },
  s: { fontSize: 13, color: C.fg3 },
  pill: { fontSize: 13, fontWeight: '600', color: C.accentInk, backgroundColor: C.accentSoft, borderRadius: 10, paddingHorizontal: 10, paddingVertical: 4, overflow: 'hidden' },
  empty: { fontSize: 15, color: C.fg3, paddingVertical: 8, lineHeight: 22 },
});
