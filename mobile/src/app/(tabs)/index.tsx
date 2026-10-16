import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CaseRow } from '../../components/CaseRow';
import { Footer } from '../../components/Footer';
import { Icon } from '../../components/Icon';
import { catTf, TfTile } from '../../components/Tf';
import { Card, H2, LinkBar, Loading, Notice, SmallBtn, StatRow, Tile, TopBar } from '../../components/ui';
import { api, ApiError, Home } from '../../lib/api';
import { setPending } from '../../lib/badge';
import { useAuth } from '../../lib/auth';
import { C, R, FONT } from '../../lib/theme';

export default function HomeTab() {
  const { session, logout } = useAuth();
  const [home, setHome] = useState<Home | null>(null);
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const [busyId, setBusyId] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!session) return;
    try {
      const h = await api.home(session.token);
      setHome(h);
      setPending(h.counts.pending);
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

  const approveOne = async (id: number) => {
    if (!session) return;
    setBusyId(id);
    setOk('');
    try {
      const r = await api.act(session.token, id, { act: 'approve' });
      setOk(r.message || '승인했습니다');
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return logout();
      setErr((e as Error).message);
    } finally {
      setBusyId(0);
    }
  };

  if (!home) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: C.band }} edges={['top']}>
        <TopBar />
        {err ? <Notice text={err} /> : <Loading />}
      </SafeAreaView>
    );
  }
  const k = home.kpi;
  const pend = home.pending;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.band }} edges={['top']}>
      <TopBar />
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
        <Card>
          <Text style={st.hello}>
            {home.hello ?? '안녕하세요'},{'\n'}
            {home.company.name} 사장님
          </Text>
          <View style={{ flexDirection: 'row', marginTop: 14 }}>
            <SmallBtn title="+ 직접 등록" kind="soft" onPress={() => router.push('/new')} />
          </View>
        </Card>

        <View style={st.tiles}>
          <Tile icon="inbox" label="오늘 들어온 요청" value={home.counts.today ?? 0} onPress={() => router.navigate('/cases')} />
          <Tile icon="check" label="승인 대기" value={home.counts.pending} tone="acc" onPress={() => router.navigate('/approvals')} />
          <Tile icon="speech" label="답변할 요청" value={home.counts.open} onPress={() => router.navigate('/cases?f=open')} />
          <Tile icon="clock" label="기한 지난 요청" value={home.counts.late} tone="red" onPress={() => router.navigate('/cases?f=bad')} />
        </View>

        <Card>
          <Text style={st.groupTitle}>
            {pend.length ? (
              <>
                승인할 요청이 <Text style={{ color: C.accent }}>{pend.length}건</Text> 있습니다
              </>
            ) : (
              '승인할 요청을 모두 처리했어요'
            )}
          </Text>
          {pend.slice(0, 5).map((c) => (
            <View key={c.id} style={st.pRow}>
              <Pressable onPress={() => router.push(`/case/${c.id}`)} style={({ pressed }) => [{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 12 }, pressed && { opacity: 0.6 }]}>
                <TfTile name={catTf(c.category)} size={24} box={44} />
                <View style={{ flex: 1, gap: 3 }}>
                  <Text style={st.pTitle} numberOfLines={1}>
                    {c.title}
                  </Text>
                  <Text style={st.pMeta} numberOfLines={2}>
                    {c.category}
                    {c.plan_title ? ` · 처리 방법 ${c.plan_title}` : ''}
                  </Text>
                </View>
              </Pressable>
              <SmallBtn title="승인" busy={busyId === c.id} onPress={() => approveOne(c.id)} />
            </View>
          ))}
          {pend.length ? (
            <LinkBar items={[{ title: '직접 등록', onPress: () => router.push('/new') }, { title: '자동 처리', onPress: () => router.navigate('/auto') }]} more={{ title: '모두보기', onPress: () => router.navigate('/approvals') }} />
          ) : null}
        </Card>

        {home.brief?.length ? (
          <Card>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 10 }}>
              <TfTile name="bulb" size={22} box={38} />
              <Text style={st.groupTitle}>소보루 브리핑</Text>
            </View>
            {home.brief.map((line) => (
              <Text key={line} style={st.brief}>
                · {line}
              </Text>
            ))}
          </Card>
        ) : null}

        <Card style={{ paddingVertical: 10 }}>
          <StatRow icon={<Icon name="chart" size={26} />} value={`${k.auto}%`} sub="자동으로 처리했어요" action="통계" onPress={() => router.push('/stats')} />
          <StatRow icon={<Icon name="list" size={26} />} value={`${home.counts.all}건`} sub="지금까지 받은 요청" action="리포트" onPress={() => router.push('/report')} />
        </Card>

        <Notice text={err} />
        <Notice text={ok} tone="ok" />

        {home.counts.comp ? (
          <Pressable onPress={() => router.push('/cases?f=comp')} style={st.warn}>
            <TfTile name="gift" />
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={{ fontFamily: FONT, fontSize: 15, fontWeight: '700', color: C.fg }}>보상 승인을 기다리는 요청 {home.counts.comp}건</Text>
              <Text style={{ fontFamily: FONT, fontSize: 13, color: C.fg3 }}>정해 둔 보상을 확인하고 승인하면 고객에게 알림이 갑니다</Text>
            </View>
          </Pressable>
        ) : null}

        {(home.alerts ?? []).map((w) => (
          <Pressable key={w.kind + w.label} onPress={() => router.push(`/cases?q=${encodeURIComponent(w.kind === 'product' ? w.label : '')}`)} style={st.warn}>
            <TfTile name="warn" />
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={{ fontFamily: FONT, fontSize: 15, fontWeight: '700', color: C.fg }}>
                {w.kind === 'product' ? `'${w.label}' 관련 요청이 최근 7일 ${w.n}건` : `${w.label} 요청이 최근 7일 ${w.n}건`}
              </Text>
              <Text style={{ fontFamily: FONT, fontSize: 13, color: C.fg3 }}>같은 문제가 반복되는지 확인해 보세요 · {w.cats.join(', ')}</Text>
            </View>
          </Pressable>
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

const st = StyleSheet.create({
  warn: { flexDirection: 'row', gap: 12, alignItems: 'center', backgroundColor: C.card, borderRadius: R.lg, padding: 18, marginHorizontal: 14, marginBottom: 12 },
  brief: { fontFamily: FONT, fontSize: 15, lineHeight: 23, color: C.fg2, marginTop: 4 },
  hello: { fontFamily: FONT, fontSize: 22, lineHeight: 31, fontWeight: '700', color: C.fg, letterSpacing: -0.7 },
  tiles: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginHorizontal: 14, marginBottom: 12 },
  pRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 12 },
  pTitle: { fontFamily: FONT, fontSize: 16, fontWeight: '600', color: C.fg, letterSpacing: -0.3 },
  pMeta: { fontFamily: FONT, fontSize: 13, lineHeight: 18, color: C.fg3 },
  groupHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 },
  groupTitle: { fontFamily: FONT, fontSize: 20, fontWeight: '700', color: C.fg, letterSpacing: -0.5 },
  empty: { fontFamily: FONT, fontSize: 15, color: C.fg3, paddingVertical: 8 },
});
