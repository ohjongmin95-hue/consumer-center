import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Image, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CaseRow } from '../../components/CaseRow';
import { Footer } from '../../components/Footer';
import { Card, H2, Loading, Notice } from '../../components/ui';
import { api, ApiError, BizCase, Home } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { C, R } from '../../lib/theme';

export default function HomeTab() {
  const { session, logout } = useAuth();
  const [home, setHome] = useState<Home | null>(null);
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const [busyCat, setBusyCat] = useState('');
  const [confirmCat, setConfirmCat] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!session) return;
    try {
      setHome(await api.home(session.token));
      setErr('');
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return logout();
      setErr((e as Error).message);
    }
  }, [session, logout]);
  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const approveAll = async (cat: string) => {
    if (!session) return;
    setBusyCat(cat);
    try {
      const r = await api.approveMany(session.token, cat);
      setOk(r.message);
      setConfirmCat('');
      await load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusyCat('');
    }
  };

  if (!home) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: C.band }} edges={['top']}>
        {err ? <Notice text={err} /> : <Loading />}
      </SafeAreaView>
    );
  }
  const groups = home.pending.reduce<Record<string, BizCase[]>>((m, c) => ((m[c.category] ??= []).push(c), m), {});
  const k = home.kpi;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.band }} edges={['top']}>
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
        <View style={st.head}>
          <Image source={require('../../../assets/soboru-char.png')} style={{ width: 36, height: 28 }} resizeMode="contain" />
          <Text style={st.wm}>소보루 CS</Text>
        </View>
        <View style={st.hero}>
          <Text style={st.coName}>{home.company.name}</Text>
          {home.counts.pending ? (
            <Text style={st.h1}>
              사장님 확인이 필요한 민원이{'\n'}
              <Text style={{ color: C.accent }}>{home.counts.pending}건</Text> 있어요
            </Text>
          ) : (
            <Text style={st.h1}>
              지금은 확인할 민원이 없어요.{'\n'}
              <Text style={{ color: C.accent }}>소보루</Text>가 응대하고 있어요
            </Text>
          )}
        </View>

        <View style={st.kpis}>
          <Kpi label="승인 대기" value={`${home.counts.pending}건`} tone={home.counts.pending ? 'acc' : undefined} />
          <Kpi label="처리 중" value={`${home.counts.open}건`} />
          <Kpi label="자동 처리" value={`${k.auto}%`} />
          <Kpi label="기한 지남" value={`${home.counts.late}건`} tone={home.counts.late ? 'red' : undefined} />
        </View>

        <Notice text={err} />
        <Notice text={ok} tone="ok" />

        {(home.alerts ?? []).map((w) => (
          <Pressable key={w.kind + w.label} onPress={() => router.push(`/cases?q=${encodeURIComponent(w.kind === 'product' ? w.label : '')}`)} style={st.warn}>
            <Text style={{ fontSize: 18 }}>⚠️</Text>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={{ fontSize: 15, fontWeight: '700', color: C.fg }}>
                {w.kind === 'product' ? `'${w.label}' 관련 민원이 최근 7일 ${w.n}건` : `${w.label} 민원이 최근 7일 ${w.n}건`}
              </Text>
              <Text style={{ fontSize: 13, color: C.fg3 }}>같은 문제가 반복되는지 확인해 보세요 · {w.cats.join(', ')}</Text>
            </View>
          </Pressable>
        ))}

        {Object.entries(groups).map(([cat, list]) => (
          <Card key={cat}>
            <View style={st.groupHead}>
              <Text style={st.groupTitle}>
                {cat} <Text style={{ color: C.accent }}>{list.length}</Text>
              </Text>
              {list.length > 1 ? (
                confirmCat === cat ? (
                  <View style={{ flexDirection: 'row', gap: 6 }}>
                    <SmallBtn title="취소" onPress={() => setConfirmCat('')} kind="gray" />
                    <SmallBtn title={busyCat === cat ? '승인 중' : `${list.length}건 승인`} onPress={() => approveAll(cat)} />
                  </View>
                ) : (
                  <SmallBtn title="모두 승인" onPress={() => setConfirmCat(cat)} kind="soft" />
                )
              ) : null}
            </View>
            {confirmCat === cat ? <Text style={st.confirm}>추천 처리대로 {list.length}건에 한 번에 답변합니다.</Text> : null}
            {list.map((c) => (
              <CaseRow key={c.id} c={c} />
            ))}
          </Card>
        ))}

        <Card>
          <H2>최근 민원</H2>
          {home.recent.length ? home.recent.map((c) => <CaseRow key={c.id} c={c} />) : <Text style={st.empty}>아직 들어온 민원이 없습니다.</Text>}
        </Card>
        {home.news?.length ? (
          <Card style={{ paddingVertical: 14 }}>
            <Pressable onPress={() => router.push('/news')} style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
              <Text style={[st.groupTitle, { flex: 1, fontSize: 17 }]}>법·제도 소식</Text>
              <Text style={{ fontSize: 14, color: C.fg3 }}>전체 ›</Text>
            </Pressable>
            {home.news.map((n) => (
              <Pressable key={n.id} onPress={() => router.push('/news')} style={{ paddingVertical: 8 }}>
                <Text style={{ fontSize: 15, color: C.fg2 }} numberOfLines={1}>
                  {n.title}
                </Text>
              </Pressable>
            ))}
          </Card>
        ) : null}
        <Footer />
      </ScrollView>
    </SafeAreaView>
  );
}

function Kpi({ label, value, tone }: { label: string; value: string; tone?: 'acc' | 'red' }) {
  return (
    <View style={st.kpi}>
      <Text style={st.kpiLabel}>{label}</Text>
      <Text style={[st.kpiValue, tone === 'acc' && { color: C.accent }, tone === 'red' && { color: C.red }]}>{value}</Text>
    </View>
  );
}

function SmallBtn({ title, onPress, kind = 'primary' }: { title: string; onPress: () => void; kind?: 'primary' | 'soft' | 'gray' }) {
  const bg = { primary: C.accent, soft: C.accentSoft, gray: C.fill }[kind];
  const fg = { primary: '#fff', soft: C.accentInk, gray: C.fg2 }[kind];
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [st.small, { backgroundColor: bg, opacity: pressed ? 0.8 : 1 }]}>
      <Text style={{ color: fg, fontWeight: '700', fontSize: 14 }}>{title}</Text>
    </Pressable>
  );
}

const st = StyleSheet.create({
  warn: { flexDirection: 'row', gap: 12, alignItems: 'center', backgroundColor: '#FFF8EC', borderRadius: R.md, padding: 16, marginHorizontal: 16, marginBottom: 12 },
  head: { flexDirection: 'row', alignItems: 'center', gap: 5, paddingHorizontal: 20, paddingTop: 12 },
  wm: { fontSize: 19, fontWeight: '800', color: C.accent, letterSpacing: -0.6 },
  hero: { paddingHorizontal: 24, paddingTop: 22, paddingBottom: 20, gap: 8 },
  coName: { fontSize: 15, fontWeight: '600', color: C.fg3 },
  h1: { fontSize: 25, lineHeight: 35, fontWeight: '700', color: C.fg, letterSpacing: -0.8 },
  kpis: { flexDirection: 'row', gap: 8, marginHorizontal: 16, marginBottom: 12 },
  kpi: { flex: 1, backgroundColor: C.card, borderRadius: R.md, paddingVertical: 14, paddingHorizontal: 10, gap: 6 },
  kpiLabel: { fontSize: 12, fontWeight: '600', color: C.fg3 },
  kpiValue: { fontSize: 18, fontWeight: '700', color: C.fg, letterSpacing: -0.5 },
  groupHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 },
  groupTitle: { fontSize: 18, fontWeight: '700', color: C.fg, letterSpacing: -0.5 },
  confirm: { fontSize: 14, color: C.fg2, marginTop: 4 },
  small: { height: 36, paddingHorizontal: 14, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  empty: { fontSize: 15, color: C.fg3, paddingVertical: 8 },
});
