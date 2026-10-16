import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Image, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CaseRow } from '../../components/CaseRow';
import { Footer } from '../../components/Footer';
import { Icon } from '../../components/Icon';
import { Card, H2, LinkBar, Loading, Notice, StatRow } from '../../components/ui';
import { api, ApiError, BizCase, Home } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { C, R, FONT } from '../../lib/theme';

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
        <Card style={{ paddingVertical: 10 }}>
          <Pressable onPress={() => router.push('/more')} style={({ pressed }) => [st.coRow, pressed && { opacity: 0.6 }]}>
            <Text style={st.coName}>{home.company.name}</Text>
            <Text style={st.coChev}>›</Text>
          </Pressable>
          <StatRow
            icon={<Icon name="shield" size={26} />}
            value={`${home.counts.pending}건`}
            sub="사장님 승인을 기다려요"
            tone={home.counts.pending ? 'acc' : undefined}
            action="확인"
            onPress={() => router.push('/cases?f=pending')}
          />
          <StatRow icon={<Icon name="reply" size={26} />} value={`${home.counts.open}건`} sub="소보루가 처리하고 있어요" action="보기" onPress={() => router.push('/cases?f=open')} />
          {home.counts.late ? (
            <StatRow icon={<Icon name="note" size={26} />} value={`${home.counts.late}건`} sub="답변 기한이 지났어요" tone="red" action="보기" onPress={() => router.push('/cases?f=bad')} />
          ) : null}
          <LinkBar
            items={[
              { title: '직접 등록', onPress: () => router.push('/new') },
              { title: '자동 규칙', onPress: () => router.push('/rules') },
            ]}
            more={{ title: '모두보기', onPress: () => router.push('/cases') }}
          />
        </Card>

        <Card style={{ paddingVertical: 10 }}>
          <StatRow icon={<Icon name="search" size={26} />} value={`${k.auto}%`} sub="자동으로 처리했어요" action="통계" onPress={() => router.push('/stats')} />
          <StatRow icon={<Icon name="list" size={26} />} value={`${home.counts.all}건`} sub="지금까지 받은 요청" action="리포트" onPress={() => router.push('/report')} />
        </Card>

        <Notice text={err} />
        <Notice text={ok} tone="ok" />

        {home.counts.comp ? (
          <Pressable onPress={() => router.push('/cases?f=comp')} style={st.warn}>
            <Text style={{ fontFamily: FONT, fontSize: 18 }}>🎁</Text>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={{ fontFamily: FONT, fontSize: 15, fontWeight: '700', color: C.fg }}>보상 승인을 기다리는 요청 {home.counts.comp}건</Text>
              <Text style={{ fontFamily: FONT, fontSize: 13, color: C.fg3 }}>정해 둔 보상을 확인하고 승인하면 고객에게 알림이 갑니다</Text>
            </View>
          </Pressable>
        ) : null}

        {(home.alerts ?? []).map((w) => (
          <Pressable key={w.kind + w.label} onPress={() => router.push(`/cases?q=${encodeURIComponent(w.kind === 'product' ? w.label : '')}`)} style={st.warn}>
            <Text style={{ fontFamily: FONT, fontSize: 18 }}>⚠️</Text>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={{ fontFamily: FONT, fontSize: 15, fontWeight: '700', color: C.fg }}>
                {w.kind === 'product' ? `'${w.label}' 관련 요청이 최근 7일 ${w.n}건` : `${w.label} 요청이 최근 7일 ${w.n}건`}
              </Text>
              <Text style={{ fontFamily: FONT, fontSize: 13, color: C.fg3 }}>같은 문제가 반복되는지 확인해 보세요 · {w.cats.join(', ')}</Text>
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
          <H2>최근 요청</H2>
          {home.recent.length ? home.recent.map((c) => <CaseRow key={c.id} c={c} />) : <Text style={st.empty}>아직 들어온 요청이 없습니다.</Text>}
        </Card>
        {home.news?.length ? (
          <Card style={{ paddingVertical: 14 }}>
            <Pressable onPress={() => router.push('/news')} style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
              <Text style={[st.groupTitle, { flex: 1, fontFamily: FONT, fontSize: 17 }]}>법·제도 소식</Text>
              <Text style={{ fontFamily: FONT, fontSize: 14, color: C.fg3 }}>전체 ›</Text>
            </Pressable>
            {home.news.map((n) => (
              <Pressable key={n.id} onPress={() => router.push('/news')} style={{ paddingVertical: 8 }}>
                <Text style={{ fontFamily: FONT, fontSize: 15, color: C.fg2 }} numberOfLines={1}>
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

function SmallBtn({ title, onPress, kind = 'primary' }: { title: string; onPress: () => void; kind?: 'primary' | 'soft' | 'gray' }) {
  const bg = { primary: C.accent, soft: C.accentSoft, gray: C.fill }[kind];
  const fg = { primary: '#fff', soft: C.accentInk, gray: C.fg2 }[kind];
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [st.small, { backgroundColor: bg, opacity: pressed ? 0.8 : 1 }]}>
      <Text style={{ color: fg, fontWeight: '700', fontFamily: FONT, fontSize: 14 }}>{title}</Text>
    </Pressable>
  );
}

const st = StyleSheet.create({
  warn: { flexDirection: 'row', gap: 12, alignItems: 'center', backgroundColor: C.card, borderRadius: R.lg, padding: 18, marginHorizontal: 14, marginBottom: 12 },
  head: { flexDirection: 'row', alignItems: 'center', gap: 5, paddingHorizontal: 22, paddingTop: 14, paddingBottom: 14 },
  wm: { fontFamily: FONT, fontSize: 19, fontWeight: '800', color: C.brand, letterSpacing: -0.6 },
  coRow: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingTop: 10, paddingBottom: 6 },
  coName: { fontFamily: FONT, fontSize: 17, fontWeight: '700', color: C.fg2, letterSpacing: -0.4 },
  coChev: { fontFamily: FONT, fontSize: 22, color: C.fg4, marginTop: -2 },
  groupHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 },
  groupTitle: { fontFamily: FONT, fontSize: 20, fontWeight: '700', color: C.fg, letterSpacing: -0.5 },
  confirm: { fontFamily: FONT, fontSize: 14, color: C.fg2, marginTop: 4 },
  small: { height: 36, paddingHorizontal: 14, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  empty: { fontFamily: FONT, fontSize: 15, color: C.fg3, paddingVertical: 8 },
});
