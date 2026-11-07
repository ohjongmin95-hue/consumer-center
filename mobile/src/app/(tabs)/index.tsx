import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CaseRow } from '../../components/CaseRow';
import { Footer } from '../../components/Footer';
import { Loading, Notice, TopBar } from '../../components/ui';
import { api, ApiError, ChatRow, Home } from '../../lib/api';
import { ChannelIcon } from '../../components/ChannelIcon';
import { catGlyph, Glyph, GlyphBox } from '../../components/Glyph';
import { SodaMark } from '../../components/SodaMark';
import { setAlerts, setPending } from '../../lib/badge';
import { useAuth } from '../../lib/auth';
import { C, FONT } from '../../lib/theme';

export default function HomeTab() {
  const { session, logout } = useAuth();
  const [home, setHome] = useState<Home | null>(null);
  const [chats, setChats] = useState<{ rows: ChatRow[]; open: number } | null>(null);
  const [gaps, setGaps] = useState(0);
  const { width } = useWindowDimensions();
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const [busyId, setBusyId] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!session) return;
    try {
      const [h, cl, sd] = await Promise.all([api.home(session.token), api.chatList(session.token, 'open').catch(() => null), api.soda(session.token).catch(() => null)]);
      if (sd) setGaps(sd.gaps.length);
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
  const bw = width - 40;
  const needN = chats?.rows.filter((r) => r.need).length ?? 0;
  const banners = [
    {
      key: 'chat',
      small: '진행 중인 상담',
      big: `${chats?.open ?? 0}건`,
      sub: needN ? `사장님 결정이 필요한 상담 ${needN}건` : `SODA가 ${k.auto}%를 자동으로 처리했어요`,
      bg: '#E8F3FF',
      ink: '#1B64DA',
      art: <Glyph name="chat" size={56} />,
      go: () => router.navigate('/chat'),
    },
    {
      key: 'ok',
      small: '승인 기다리는 요청',
      big: `${n.pending}건`,
      sub: n.pending ? '눌러서 한 번에 승인할 수 있어요' : '지금은 기다리는 요청이 없어요',
      bg: '#FFF3E4',
      ink: C.accentInk,
      art: <Glyph name="check" size={56} />,
      go: () => router.navigate('/approvals'),
    },
    {
      key: 'soda',
      small: 'SODA 가르치기',
      big: gaps ? `질문 ${gaps}개` : '다 배웠어요',
      sub: gaps ? 'SODA가 답을 몰랐던 질문이에요' : '새 질문이 생기면 알려 드릴게요',
      bg: '#EAF8F3',
      ink: '#2F7D66',
      art: <SodaMark size={60} />,
      go: () => router.push('/soda'),
    },
  ];

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
        {/* 토스 쇼핑 홈처럼: 찾기 칸 → 큰 배너 한 장씩 넘기기 → 바로가기 아이콘 줄 → 구역들 */}
        <Pressable onPress={() => router.navigate('/cases')} style={({ pressed }) => [st.search, pressed && { backgroundColor: C.line }]}>
          <Glyph name="search" size={18} />
          <Text style={st.searchT}>상담·요청 찾기</Text>
        </Pressable>

        <ScrollView
          horizontal
          snapToInterval={bw + 10}
          decelerationRate="fast"
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ paddingHorizontal: 20, gap: 10 }}
        >
          {banners.map((x, i) => (
            <Pressable key={x.key} onPress={x.go} style={({ pressed }) => [st.banner, { width: bw, backgroundColor: x.bg }, pressed && { opacity: 0.85 }]}>
              <View style={{ flex: 1, gap: 6 }}>
                <Text style={st.bnSmall}>{x.small}</Text>
                <Text style={st.bnBig}>{x.big}</Text>
                <Text style={[st.bnSub, { color: x.ink }]}>{x.sub}</Text>
              </View>
              <View style={st.bnArt}>{x.art}</View>
              <View style={st.bnPage}>
                <Text style={st.bnPageT}>
                  {i + 1} / {banners.length}
                </Text>
              </View>
            </Pressable>
          ))}
        </ScrollView>

        <View style={st.shorts}>
          {SHORTS.map((x) => (
            <Pressable key={x.label} onPress={() => router.push(x.href as never)} style={({ pressed }) => [st.short, pressed && { opacity: 0.6 }]}>
              <View style={st.shortIc}>{x.icon === 'soda' ? <SodaMark size={30} /> : <Glyph name={x.icon} size={28} />}</View>
              <Text style={st.shortT} numberOfLines={1}>
                {x.label}
              </Text>
            </Pressable>
          ))}
        </View>

        {chats?.rows.length ? (
          <View style={st.sec}>
            <Head title="진행 중인 상담" more="전체" onPress={() => router.navigate('/chat')} />
            {chats.rows.slice(0, 4).map((r) => (
              <Room key={r.id} r={r} />
            ))}
          </View>
        ) : null}

        {pend.length ? (
          <View style={{ paddingTop: 20, paddingBottom: 14 }}>
            <View style={{ paddingHorizontal: 24 }}>
              <Head title={`승인 기다리는 요청 ${n.pending}건`} more="전체" onPress={() => router.navigate('/approvals')} />
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 20, gap: 10 }}>
              {pend.slice(0, 8).map((c) => (
                <View key={c.id} style={st.pc}>
                  <Pressable onPress={() => router.push(`/chat/${c.id}`)} style={({ pressed }) => [{ gap: 10 }, pressed && { opacity: 0.6 }]}>
                    <View style={st.pcIc}>
                      <Glyph name={catGlyph(c.category)} size={26} />
                    </View>
                    <Text style={st.pcT} numberOfLines={2}>
                      {c.title}
                    </Text>
                    <Text style={st.rowSub} numberOfLines={1}>
                      {c.plan_title ? c.plan_title : c.category}
                    </Text>
                  </Pressable>
                  <Pressable onPress={() => approveOne(c.id)} disabled={!!busyId} style={({ pressed }) => [st.pcBtn, pressed && { backgroundColor: C.line }]}>
                    <Text style={st.pcBtnT}>{busyId === c.id ? '…' : '승인'}</Text>
                  </Pressable>
                </View>
              ))}
            </ScrollView>
          </View>
        ) : null}
        {err || ok || n.late ? (
          <View style={[st.sec, { paddingTop: 4 }]}>
            {n.late ? <Line icon="clock" title={`기한 지난 요청 ${n.late}건`} sub="먼저 봐 주세요" tone={C.red} onPress={() => router.push('/cases?f=bad')} /> : null}
            <Notice text={err} flat />
            <Notice text={ok} tone="ok" flat />
          </View>
        ) : null}

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

const SHORTS = [
  { label: '상담', icon: 'chat', href: '/chat' },
  { label: '승인', icon: 'check', href: '/approvals' },
  { label: '주문·배송', icon: 'truck', href: '/orders' },
  { label: '교환·반품', icon: 'exchange', href: '/returns' },
  { label: 'SODA', icon: 'soda', href: '/soda' },
];

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
  search: { marginHorizontal: 20, marginTop: 4, marginBottom: 16, height: 44, borderRadius: 14, backgroundColor: C.fill, flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 14 },
  searchT: { fontFamily: FONT, fontSize: 15, color: C.fg3, letterSpacing: 0 },
  banner: { height: 148, borderRadius: 22, paddingHorizontal: 22, paddingVertical: 20, flexDirection: 'row', alignItems: 'center', overflow: 'hidden' },
  bnSmall: { fontFamily: FONT, fontSize: 14, fontWeight: '600', color: C.fg2, letterSpacing: 0 },
  bnBig: { fontFamily: FONT, fontSize: 26, lineHeight: 34, fontWeight: '700', color: C.fg, letterSpacing: 0 },
  bnSub: { fontFamily: FONT, fontSize: 13, lineHeight: 19, fontWeight: '600', letterSpacing: 0 },
  bnArt: { width: 72, height: 72, borderRadius: 22, backgroundColor: 'rgba(255,255,255,0.7)', alignItems: 'center', justifyContent: 'center' },
  bnPage: { position: 'absolute', right: 14, bottom: 12, backgroundColor: 'rgba(0,0,0,0.12)', borderRadius: 10, paddingHorizontal: 8, paddingVertical: 2 },
  bnPageT: { fontFamily: FONT, fontSize: 11, fontWeight: '600', color: '#fff', letterSpacing: 0 },
  shorts: { flexDirection: 'row', justifyContent: 'space-between', paddingHorizontal: 20, paddingTop: 20, paddingBottom: 8 },
  short: { alignItems: 'center', gap: 6, width: 62 },
  shortIc: { width: 52, height: 52, borderRadius: 18, backgroundColor: C.fill, alignItems: 'center', justifyContent: 'center' },
  shortT: { fontFamily: FONT, fontSize: 12, fontWeight: '500', color: C.fg2, letterSpacing: 0 },
  pc: { width: 156, backgroundColor: C.fill, borderRadius: 18, padding: 14, gap: 12, justifyContent: 'space-between' },
  pcIc: { width: 44, height: 44, borderRadius: 14, backgroundColor: C.card, alignItems: 'center', justifyContent: 'center' },
  pcT: { fontFamily: FONT, fontSize: 15, lineHeight: 21, fontWeight: '600', color: C.fg, letterSpacing: 0, minHeight: 42 },
  pcBtn: { height: 36, borderRadius: 10, backgroundColor: C.card, alignItems: 'center', justifyContent: 'center' },
  pcBtnT: { fontFamily: FONT, fontSize: 14, fontWeight: '700', color: C.accentInk },
  empty: { fontFamily: FONT, fontSize: 14, color: C.fg3, paddingVertical: 8 },
});
