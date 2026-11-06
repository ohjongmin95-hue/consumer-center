import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CaseRow } from '../../components/CaseRow';
import { Footer } from '../../components/Footer';
import { Loading, Notice, TopBar } from '../../components/ui';
import { api, ApiError, ChatRow, Home } from '../../lib/api';
import { ChannelIcon } from '../../components/ChannelIcon';
import { catGlyph, GlyphBox } from '../../components/Glyph';
import { setAlerts, setPending } from '../../lib/badge';
import { useAuth } from '../../lib/auth';
import { C, FONT } from '../../lib/theme';

export default function HomeTab() {
  const { session, logout } = useAuth();
  const [home, setHome] = useState<Home | null>(null);
  const [chats, setChats] = useState<{ rows: ChatRow[]; open: number } | null>(null);
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const [busyId, setBusyId] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!session) return;
    try {
      const [h, cl] = await Promise.all([api.home(session.token), api.chatList(session.token, 'open').catch(() => null)]);
      setHome(h);
      if (cl) setChats({ rows: cl.rows, open: cl.counts.open ?? cl.rows.length });
      setPending(h.counts.pending);
      setAlerts(h.counts.alerts ?? 0);
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
      setOk(r.message || '승인했어요');
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
      <SafeAreaView style={{ flex: 1, backgroundColor: C.card }} edges={['top']}>
        <TopBar />
        {err ? <Notice text={err} /> : <Loading />}
      </SafeAreaView>
    );
  }
  const k = home.kpi;
  const pend = home.pending;
  const n = home.counts;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.card }} edges={['top']}>
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
        {/* 요청 현황: 작은 회색 칸 둘 + 큰 숫자 하나 (토스증권 '내 계좌'·'내 투자'처럼) */}
        <View style={st.sec}>
          <Head title="오늘" />
          <View style={st.boxes}>
            <Box label="오늘 들어온 요청" value={`${n.today ?? 0}건`} onPress={() => router.navigate('/chat')} />
            <Box label="답변할 요청" value={`${n.open}건`} onPress={() => router.navigate('/chat')} />
          </View>
          <Pressable onPress={() => router.navigate('/chat')} style={({ pressed }) => [{ marginTop: 26 }, pressed && { opacity: 0.6 }]}>
            <Text style={st.bigLabel}>진행 중인 상담</Text>
            <Text style={st.big}>
              {chats?.open ?? 0}건 <Text style={st.bigChev}>›</Text>
            </Text>
            {chats?.rows.some((r) => r.need) ? (
              <Text style={[st.bigSub, { color: C.accentInk }]}>사장님 결정이 필요한 상담 {chats.rows.filter((r) => r.need).length}건</Text>
            ) : (
              <Text style={st.bigSub}>SODA가 {k.auto}%를 자동으로 처리했어요</Text>
            )}
          </Pressable>
          {chats?.rows.length ? (
            <View style={{ marginTop: 14 }}>
              {chats.rows.slice(0, 4).map((r) => (
                <Room key={r.id} r={r} />
              ))}
            </View>
          ) : null}
        </View>

        <View style={st.band} />
        <View style={st.sec}>
          <Head title="확인할 요청" more="전체" onPress={() => router.navigate('/cases')} />
          {n.late ? <Line icon="clock" title={`기한 지난 요청 ${n.late}건`} sub="먼저 봐 주세요" tone={C.red} onPress={() => router.push('/cases?f=bad')} /> : null}
          {pend.length ? (
            <View style={{ marginTop: 6 }}>
              <Head title={`승인 기다리는 요청 ${n.pending}건`} small more="모두 보기" onPress={() => router.navigate('/approvals')} />
              {pend.slice(0, 5).map((c) => (
                <View key={c.id} style={st.row}>
                  <Pressable onPress={() => router.push(`/chat/${c.id}`)} style={({ pressed }) => [{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 12 }, pressed && { opacity: 0.6 }]}>
                    <GlyphBox name={catGlyph(c.category)} />
                    <View style={{ flex: 1, gap: 2 }}>
                    <Text style={st.rowTitle} numberOfLines={1}>
                      {c.title}
                    </Text>
                    <Text style={st.rowSub} numberOfLines={1}>
                      {c.plan_title ? c.plan_title : c.category}
                    </Text>
                    </View>
                  </Pressable>
                  <Pressable onPress={() => approveOne(c.id)} disabled={!!busyId} style={({ pressed }) => [st.pill, pressed && { backgroundColor: C.line }]}>
                    <Text style={st.pillT}>{busyId === c.id ? '…' : '승인'}</Text>
                  </Pressable>
                </View>
              ))}
            </View>
          ) : null}
          <Notice text={err} flat />
          <Notice text={ok} tone="ok" flat />
        </View>

        {n.comp || (home.alerts ?? []).length ? (
          <>
            <View style={st.band} />
            <View style={st.sec}>
              <Head title="살펴볼 일" />
              {n.comp ? <Line icon="gift" title={`보상 승인을 기다리는 요청 ${n.comp}건`} sub="확인하고 승인하면 고객에게 알림이 가요" onPress={() => router.push('/cases?f=comp')} /> : null}
              {(home.alerts ?? []).map((w) => (
                <Line
                  icon="warn"
                  key={w.kind + w.label}
                  title={w.kind === 'product' ? `'${w.label}' 요청이 최근 7일 ${w.n}건` : `${w.label} 요청이 최근 7일 ${w.n}건`}
                  sub={`같은 문제가 반복되는지 확인해 보세요 · ${w.cats.join(', ')}`}
                  onPress={() => router.push(`/cases?q=${encodeURIComponent(w.kind === 'product' ? w.label : '')}`)}
                />
              ))}
            </View>
          </>
        ) : null}

        <View style={st.band} />
        <View style={st.sec}>
          <Head title="최근 요청" more="전체" onPress={() => router.navigate('/cases')} />
          {home.recent.length ? home.recent.map((c) => <CaseRow key={c.id} c={c} />) : <Text style={st.empty}>아직 들어온 요청이 없어요</Text>}
        </View>

        <View style={st.band} />
        <View style={st.sec}>
          <Head title="한눈에 보기" />
          <Value icon="chart" label="자동으로 처리한 비율" value={`${k.auto}%`} onPress={() => router.push('/stats')} />
          <Value icon="report" label="지금까지 받은 요청" value={`${n.all}건`} onPress={() => router.push('/report')} />
          <Value icon="plus" label="요청 직접 등록하기" onPress={() => router.push('/new')} />
        </View>

        {home.brief?.length ? (
          <>
            <View style={st.band} />
            <View style={st.sec}>
              <Head title="소보루 브리핑" />
              {home.brief.map((line) => (
                <Text key={line} style={st.brief}>
                  {line}
                </Text>
              ))}
            </View>
          </>
        ) : null}

        {home.news?.length ? (
          <>
            <View style={st.band} />
            <View style={st.sec}>
              <Head title="법·제도 소식" more="전체" onPress={() => router.push('/news')} />
              {home.news.map((x) => (
                <Pressable key={x.id} onPress={() => router.push('/news')} style={({ pressed }) => [{ paddingVertical: 9 }, pressed && { opacity: 0.6 }]}>
                  <Text style={st.newsT} numberOfLines={1}>
                    {x.title}
                  </Text>
                </Pressable>
              ))}
            </View>
          </>
        ) : null}
        <Footer />
      </ScrollView>
    </SafeAreaView>
  );
}

function Head({ title, more, onPress, small }: { title: string; more?: string; onPress?: () => void; small?: boolean }) {
  return (
    <View style={st.head}>
      <Text style={small ? st.headSmall : st.headT}>{title}</Text>
      {more && onPress ? (
        <Pressable onPress={onPress} hitSlop={8}>
          <Text style={st.headMore}>{more} ›</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function Box({ label, value, onPress }: { label: string; value: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [st.box, pressed && { backgroundColor: C.line }]}>
      <Text style={st.boxL}>{label}</Text>
      <Text style={st.boxV}>{value}</Text>
    </Pressable>
  );
}

function Line({ icon, title, sub, onPress, tone }: { icon: string; title: string; sub: string; onPress: () => void; tone?: string }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [st.row, pressed && { opacity: 0.6 }]}>
      <GlyphBox name={icon} />
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={[st.rowTitle, tone ? { color: tone } : null]} numberOfLines={1}>
          {title}
        </Text>
        <Text style={st.rowSub} numberOfLines={1}>
          {sub}
        </Text>
      </View>
      <Text style={st.chev}>›</Text>
    </Pressable>
  );
}

function Value({ icon, label, value, onPress }: { icon: string; label: string; value?: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [st.row, pressed && { opacity: 0.6 }]}>
      <GlyphBox name={icon} />
      <Text style={[st.rowTitle, { flex: 1 }]}>{label}</Text>
      {value ? <Text style={st.val}>{value}</Text> : null}
      <Text style={st.chev}>›</Text>
    </Pressable>
  );
}

// 상담방 한 줄 (채널톡처럼): 이름 첫 글자 동그라미 + 들어온 곳 표시, 마지막 말, 시간, 안 읽음 점
function Room({ r }: { r: ChatRow }) {
  return (
    <Pressable onPress={() => router.push(`/chat/${r.id}`)} style={({ pressed }) => [st.row, pressed && { opacity: 0.6 }]}>
      <View style={st.av}>
        <Text style={st.avT}>{r.name.slice(0, 1)}</Text>
        <View style={st.mk}>
          <ChannelIcon mark={r.mark[1]} size={16} />
        </View>
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <Text style={[st.rowTitle, { flexShrink: 1, fontWeight: '600' }]} numberOfLines={1}>
            {r.name}
          </Text>
          {r.need ? <Text style={st.need}>결정 필요</Text> : null}
          <Text style={st.when}>{r.when}</Text>
        </View>
        <Text style={[st.rowSub, r.unread && { color: C.fg, fontWeight: '600' }]} numberOfLines={1}>
          {r.text}
        </Text>
      </View>
      {r.unread ? <View style={st.dot} /> : null}
    </Pressable>
  );
}

// 토스증권 홈처럼: 흰 바탕, 옆 24, 구역 사이 12 회색 띠, 그림 없이 글자와 숫자만
const st = StyleSheet.create({
  sec: { paddingHorizontal: 24, paddingTop: 20, paddingBottom: 14 },
  band: { height: 12, backgroundColor: C.fill },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 },
  headT: { fontFamily: FONT, fontSize: 17, lineHeight: 25.5, fontWeight: '700', color: C.fg, letterSpacing: 0 },
  headSmall: { fontFamily: FONT, fontSize: 13, lineHeight: 19.5, fontWeight: '600', color: C.fg3, letterSpacing: 0 },
  headMore: { fontFamily: FONT, fontSize: 13, color: C.fg3, letterSpacing: 0 },
  boxes: { flexDirection: 'row', gap: 8 },
  box: { flex: 1, backgroundColor: C.fill, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, gap: 2 },
  boxL: { fontFamily: FONT, fontSize: 12, lineHeight: 18, color: C.fg3, letterSpacing: 0 },
  boxV: { fontFamily: FONT, fontSize: 15, lineHeight: 22.5, fontWeight: '700', color: C.fg, letterSpacing: 0 },
  bigLabel: { fontFamily: FONT, fontSize: 14, lineHeight: 21, fontWeight: '600', color: C.fg2, letterSpacing: 0 },
  big: { fontFamily: FONT, fontSize: 26, lineHeight: 35, fontWeight: '700', color: C.fg, letterSpacing: 0, marginTop: 2 },
  bigChev: { fontSize: 22, color: C.fg3, fontWeight: '400' },
  bigSub: { fontFamily: FONT, fontSize: 13, lineHeight: 19.5, color: C.fg3, letterSpacing: 0, marginTop: 2 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 11 },
  rowTitle: { fontFamily: FONT, fontSize: 15, lineHeight: 22.5, fontWeight: '500', color: C.fg, letterSpacing: 0 },
  rowSub: { fontFamily: FONT, fontSize: 13, lineHeight: 19.5, color: C.fg3, letterSpacing: 0 },
  pill: { height: 30, paddingHorizontal: 12, borderRadius: 8, backgroundColor: C.fill, alignItems: 'center', justifyContent: 'center' },
  pillT: { fontFamily: FONT, fontSize: 13, fontWeight: '600', color: C.fg2 },
  val: { fontFamily: FONT, fontSize: 15, fontWeight: '600', color: C.fg, letterSpacing: 0 },
  chev: { fontFamily: FONT, fontSize: 18, color: C.fg4 },
  brief: { fontFamily: FONT, fontSize: 14, lineHeight: 22, color: C.fg2, paddingVertical: 4, letterSpacing: 0 },
  newsT: { fontFamily: FONT, fontSize: 14, lineHeight: 21, color: C.fg2, letterSpacing: 0 },
  av: { width: 40, height: 40, borderRadius: 20, backgroundColor: '#E8F3FF', alignItems: 'center', justifyContent: 'center' },
  avT: { fontFamily: FONT, fontSize: 15, fontWeight: '700', color: '#1B64DA' },
  mk: { position: 'absolute', right: -3, bottom: -3, borderRadius: 10, borderWidth: 2, borderColor: C.card, backgroundColor: C.card },
  need: { fontFamily: FONT, fontSize: 11, fontWeight: '700', color: C.accentInk, backgroundColor: C.accentSoft, paddingHorizontal: 6, paddingVertical: 1, borderRadius: 6, overflow: 'hidden' },
  when: { marginLeft: 'auto', fontFamily: FONT, fontSize: 12, color: C.fg4 },
  dot: { width: 7, height: 7, borderRadius: 4, backgroundColor: C.red },
  empty: { fontFamily: FONT, fontSize: 14, color: C.fg3, paddingVertical: 8 },
});
