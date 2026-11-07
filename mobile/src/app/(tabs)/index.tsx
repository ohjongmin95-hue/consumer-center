import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Image, Pressable, RefreshControl, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';
import { CaseRow } from '../../components/CaseRow';
import { Footer } from '../../components/Footer';
import { Loading, Notice, TopBar } from '../../components/ui';
import { api, ApiError, ChatRow, Home } from '../../lib/api';
import { ChannelIcon } from '../../components/ChannelIcon';
import { Avatar } from '../../components/Avatar';
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
  const [tab, setTab] = useState('all');
  const [page, setPage] = useState(0);
  const { width } = useWindowDimensions();
  const shopName = (session?.company?.name ?? '').replace(/\s*\(.*?\)\s*/g, '').trim();
  const boardH = Math.round(Math.min(width - 24, 520) * 0.62);
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
  const needN = chats?.rows.filter((r) => r.need).length ?? 0;
  const rows = chats?.rows ?? [];
  const boards = [
    {
      key: 'chat',
      small: `진행 중인 상담 ${chats?.open ?? 0}건`,
      big: needN ? `사장님 결정이 필요한\n상담이 ${needN}건 있어요` : 'SODA가 상담을\n잘 이어가고 있어요',
      img: require('../../../assets/board/chat.webp'),
      from: '#FFE6C0',
      to: '#FFF9F1',
      go: () => router.navigate('/chat'),
    },
    {
      key: 'ok',
      small: `승인 기다리는 요청 ${n.pending}건`,
      big: n.pending ? '교환·반품 요청을\n한 번에 승인해 보세요' : '지금은 승인할\n요청이 없어요',
      img: require('../../../assets/board/ok.webp'),
      from: '#FFDDB0',
      to: '#FFF7EC',
      go: () => router.navigate('/approvals'),
    },
    {
      key: 'soda',
      small: 'SODA 가르치기',
      big: gaps ? `SODA가 모르는 질문\n${gaps}개에 답해 주세요` : '사장님 답을 배워서\n다음엔 SODA가 답해요',
      img: require('../../../assets/board/soda.webp'),
      from: '#CFF2E6',
      to: '#EEF8FF',
      go: () => router.push('/soda'),
    },
  ];
  const shown = tab === 'need' ? rows.filter((r) => r.need) : tab === 'new' ? rows.filter((r) => r.unread) : rows;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: BG }} edges={['top']}>
      <TopBar />
      <ScrollView
        style={{ backgroundColor: BG }}
        contentContainerStyle={{ paddingBottom: 28, paddingTop: 4 }}
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
        {/* 토스 홈처럼 (OH 11/07): 옅은 회색 바탕 위에 흰 둥근 카드. 카드 안 행 = 아이콘 + 굵은 숫자 + 회색 설명 + 오른쪽 회색 버튼 */}

        {/* 메인 보드: 실물 같은 3D 그림, 한 장씩 넘겨요. 카드는 좌우 여백 안에 딱 */}
        <ScrollView
          horizontal
          pagingEnabled
          showsHorizontalScrollIndicator={false}
          onScroll={(e) => setPage(Math.min(boards.length - 1, Math.max(0, Math.round(e.nativeEvent.contentOffset.x / width))))}
          scrollEventThrottle={32}
        >
          {boards.map((x) => (
            <View key={x.key} style={{ width, paddingHorizontal: 12 }}>
              <Pressable onPress={x.go} style={({ pressed }) => [st.card, st.board, { height: boardH }, pressed && st.cardOn]}>
                {/* 토스 쇼핑 홈 배너처럼 (OH 11/07): 은은한 그라데이션 + 큰 제목 + 오른쪽 아래 비스듬한 3D 오브젝트 하나 */}
                <Svg style={StyleSheet.absoluteFill} width="100%" height="100%">
                  <Defs>
                    <LinearGradient id={`bg${x.key}`} x1="0" y1="0" x2="1" y2="1">
                      <Stop offset="0" stopColor={x.from} />
                      <Stop offset="1" stopColor={x.to} />
                    </LinearGradient>
                  </Defs>
                  <Rect width="100%" height="100%" fill={`url(#bg${x.key})`} />
                </Svg>
                <Text style={st.boardT}>{x.big}</Text>
                <Text style={st.boardK}>{x.small}</Text>
                <Image source={x.img} style={[st.boardImg, { width: boardH * 0.68, height: boardH * 0.68 }]} resizeMode="contain" />
                <View style={st.boardPage}>
                  <Text style={st.boardPageT}>
                    {page + 1} | {boards.length}
                  </Text>
                </View>
              </Pressable>
            </View>
          ))}
        </ScrollView>

        {/* 바로가기 다섯 칸: 흰 카드 안에 화면 폭을 똑같이 나눠요 */}
        <View style={[st.card, st.shorts]}>
          {SHORTS.map((x) => (
            <Pressable key={x.label} onPress={() => router.push(x.href as never)} style={({ pressed }) => [st.short, pressed && { opacity: 0.5 }]}>
              {x.icon === 'soda' ? <SodaMark size={30} /> : <Glyph name={x.icon} size={30} />}
              <Text style={st.shortT} numberOfLines={1}>
                {x.label}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* 오늘 할 일 카드 */}
        <View style={[st.card, { paddingBottom: 10 }]}>
          <Pressable onPress={() => router.navigate('/cases')} style={({ pressed }) => [st.cardHead, pressed && { opacity: 0.6 }]}>
            <Text style={st.cardHeadB}>오늘 {n.today ?? 0}건</Text>
            <View style={st.vbar} />
            <Text style={[st.cardHeadT, n.late ? { color: C.red } : null]} numberOfLines={1}>
              {n.late ? `기한 지난 요청 ${n.late}건` : '새로 들어온 요청'}
            </Text>
            <Text style={st.chev}>›</Text>
          </Pressable>
          <Act icon="chat" big={`${chats?.open ?? 0}건`} sub={needN ? `진행 중인 상담 · 결정 필요 ${needN}` : '진행 중인 상담'} btn="보기" onPress={() => router.navigate('/chat')} />
          <Act icon="check" big={`${n.pending}건`} sub="승인 기다리는 요청" btn="승인" primary={n.pending > 0} onPress={() => router.navigate('/approvals')} />
          <Act soda big={`${gaps}개`} sub="SODA가 모르는 질문" btn="답하기" onPress={() => router.push('/soda')} />
        </View>

        {/* 자동 처리 카드 */}
        <View style={[st.card, { paddingVertical: 6 }]}>
          <Act icon="chart" big={`${k.auto}%`} sub="SODA가 자동으로 처리한 비율" btn="통계" onPress={() => router.push('/stats')} />
        </View>

        {/* 진행 중인 상담 */}
        <View style={st.card}>
          <Text style={st.cardTitle}>진행 중인 상담</Text>
          <View style={st.tabs}>
            {TABS.map((t) => (
              <Pressable key={t.key} onPress={() => setTab(t.key)} style={st.tab} hitSlop={4}>
                <Text style={[st.tabT, tab === t.key && st.tabOn]}>{t.label}</Text>
                {tab === t.key ? <View style={st.tabBar} /> : null}
              </Pressable>
            ))}
          </View>
          <View style={{ paddingHorizontal: 20, paddingTop: 6 }}>
            {tab === 'ok' ? (
              pend.length ? (
                pend.slice(0, 6).map((c) => (
                  <View key={c.id} style={st.row}>
                    <Pressable onPress={() => router.push(`/chat/${c.id}`)} style={({ pressed }) => [{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 14 }, pressed && { opacity: 0.6 }]}>
                      <View style={st.sq}>
                        <Glyph name={catGlyph(c.category)} size={24} />
                      </View>
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
                ))
              ) : (
                <Text style={st.empty}>승인 기다리는 요청이 없어요</Text>
              )
            ) : shown.length ? (
              shown.slice(0, 5).map((r) => <Room key={r.id} r={r} />)
            ) : (
              <Text style={st.empty}>{tab === 'need' ? '결정이 필요한 상담이 없어요' : tab === 'new' ? '안 읽은 상담이 없어요' : '진행 중인 상담이 없어요'}</Text>
            )}
            <Notice text={err} flat />
            <Notice text={ok} tone="ok" flat />
          </View>
          <Pressable onPress={() => router.navigate(tab === 'ok' ? '/approvals' : '/chat')} style={({ pressed }) => [st.cardFoot, pressed && { backgroundColor: '#F9FAFB' }]}>
            <Text style={st.linkT}>더 보기</Text>
          </Pressable>
        </View>

        {n.comp || (home.alerts ?? []).length ? (
          <View style={[st.card, st.pad]}>
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
        ) : null}

        <View style={[st.card, st.pad]}>
          <Head title="최근 요청" more="전체" onPress={() => router.navigate('/cases')} />
          {home.recent.length ? home.recent.map((c) => <CaseRow key={c.id} c={c} />) : <Text style={st.empty}>아직 들어온 요청이 없어요</Text>}
        </View>

        <View style={[st.card, st.pad]}>
          <Value icon="report" label="지금까지 받은 요청" value={`${n.all}건`} onPress={() => router.push('/report')} />
          <Value icon="plus" label="요청 직접 등록하기" onPress={() => router.push('/new')} />
        </View>

        {home.brief?.length ? (
          <View style={[st.card, st.pad]}>
            {/* 토스 "○○님을 위한 추천 상품"처럼 (OH 11/07) */}
            <Head title={shopName.length && shopName.length <= 8 ? `${shopName} 사장님을 위한 브리핑` : '사장님을 위한 오늘 브리핑'} />
            {home.brief.map((line) => (
              <Text key={line} style={st.brief}>
                {line}
              </Text>
            ))}
          </View>
        ) : null}

        {home.news?.length ? (
          <View style={[st.card, st.pad]}>
            <Head title="법·제도 소식" more="전체" onPress={() => router.push('/news')} />
            {home.news.map((x) => (
              <Pressable key={x.id} onPress={() => router.push('/news')} style={({ pressed }) => [{ paddingVertical: 9 }, pressed && { opacity: 0.6 }]}>
                <Text style={st.newsT} numberOfLines={1}>
                  {x.title}
                </Text>
              </Pressable>
            ))}
          </View>
        ) : null}
        <Footer />
      </ScrollView>
    </SafeAreaView>
  );
}

// 카드 안 한 줄 (토스 홈 계좌 줄처럼): 아이콘 + 굵은 숫자 + 회색 설명 + 오른쪽 회색 버튼
function Act({ icon, soda, big, sub, btn, primary, onPress }: { icon?: string; soda?: boolean; big: string; sub: string; btn: string; primary?: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [st.act, pressed && { backgroundColor: '#F9FAFB' }]}>
      <View style={st.actIc}>{soda ? <SodaMark size={26} /> : <Glyph name={icon || 'chat'} size={26} />}</View>
      <View style={{ flex: 1, gap: 1 }}>
        <Text style={st.actBig}>{big}</Text>
        <Text style={st.actSub} numberOfLines={1}>
          {sub}
        </Text>
      </View>
      <View style={[st.actBtn, primary && { backgroundColor: C.accentSoft }]}>
        <Text style={[st.actBtnT, primary && { color: C.accent }]}>{btn}</Text>
      </View>
    </Pressable>
  );
}

function Head({ title, more, onPress, small }: { title: string; more?: string; onPress?: () => void; small?: boolean }) {
  return (
    <View style={st.head}>
      <Text style={[small ? st.headSmall : st.headT, { flexShrink: 1 }]} numberOfLines={1}>
        {title}
      </Text>
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
        <Avatar id={r.id} size={44} />
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

const BG = '#F2F4F6'; // 토스 홈 바탕 (옅은 회색)

const TABS = [
  { key: 'all', label: '전체' },
  { key: 'need', label: '결정 필요' },
  { key: 'new', label: '안 읽음' },
  { key: 'ok', label: '승인 대기' },
];

const SHORTS = [
  { label: '상담', icon: 'chat', href: '/chat' },
  { label: '승인', icon: 'check', href: '/approvals' },
  { label: '주문·배송', icon: 'truck', href: '/orders' },
  { label: '교환·반품', icon: 'exchange', href: '/returns' },
  { label: 'SODA', icon: 'soda', href: '/soda' },
];

// 토스증권 홈처럼: 흰 바탕, 옆 24, 구역 사이 12 회색 띠, 그림 없이 글자와 숫자만
const st = StyleSheet.create({
  card: { backgroundColor: C.card, borderRadius: 24, marginHorizontal: 12, marginTop: 12, overflow: 'hidden' },
  cardOn: { backgroundColor: '#F9FAFB' },
  pad: { paddingHorizontal: 20, paddingTop: 20, paddingBottom: 10 },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 24, paddingTop: 22, paddingBottom: 6 },
  cardHeadB: { fontFamily: FONT, fontSize: 17, fontWeight: '700', color: C.fg, letterSpacing: 0 },
  cardHeadT: { flex: 1, fontFamily: FONT, fontSize: 17, fontWeight: '500', color: C.fg2, letterSpacing: 0 },
  cardTitle: { fontFamily: FONT, fontSize: 18, fontWeight: '700', color: C.fg, letterSpacing: 0, paddingHorizontal: 24, paddingTop: 22 },
  cardFoot: { height: 52, borderTopWidth: 1, borderTopColor: '#F2F4F6', alignItems: 'center', justifyContent: 'center', marginTop: 6 },
  vbar: { width: 1.5, height: 16, backgroundColor: C.line },
  vbarS: { width: 1, height: 14, backgroundColor: C.line, marginHorizontal: 14 },
  act: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingHorizontal: 24, paddingVertical: 12 },
  actIc: { width: 44, height: 44, borderRadius: 22, backgroundColor: '#F2F4F6', alignItems: 'center', justifyContent: 'center' },
  actBig: { fontFamily: FONT, fontSize: 19, lineHeight: 26, fontWeight: '700', color: C.fg, letterSpacing: 0 },
  actSub: { fontFamily: FONT, fontSize: 14, lineHeight: 20, color: C.fg3, letterSpacing: 0 },
  actBtn: { height: 36, paddingHorizontal: 14, borderRadius: 10, backgroundColor: '#F2F4F6', alignItems: 'center', justifyContent: 'center' },
  actBtnT: { fontFamily: FONT, fontSize: 14, fontWeight: '600', color: C.fg2, letterSpacing: 0 },
  links: { flexDirection: 'row', alignItems: 'center', borderTopWidth: 1, borderTopColor: '#F2F4F6', marginTop: 8, paddingHorizontal: 24, height: 54 },
  link: { paddingVertical: 4 },
  linkT: { fontFamily: FONT, fontSize: 15, fontWeight: '500', color: C.fg2, letterSpacing: 0 },
  sec: { paddingHorizontal: 24, paddingTop: 20, paddingBottom: 14 },
  band: { height: 20 },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 },
  headT: { fontFamily: FONT, fontSize: 20, lineHeight: 28, fontWeight: '700', color: C.fg, letterSpacing: 0 },
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
  row: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 12 },
  rowTitle: { fontFamily: FONT, fontSize: 16, lineHeight: 23, fontWeight: '500', color: C.fg, letterSpacing: 0 },
  rowSub: { fontFamily: FONT, fontSize: 14, lineHeight: 20, color: C.fg3, letterSpacing: 0 },
  pill: { height: 30, paddingHorizontal: 12, borderRadius: 8, backgroundColor: C.fill, alignItems: 'center', justifyContent: 'center' },
  pillT: { fontFamily: FONT, fontSize: 13, fontWeight: '600', color: C.fg2 },
  val: { fontFamily: FONT, fontSize: 15, fontWeight: '600', color: C.fg, letterSpacing: 0 },
  chev: { fontFamily: FONT, fontSize: 18, color: C.fg4 },
  brief: { fontFamily: FONT, fontSize: 14, lineHeight: 22, color: C.fg2, paddingVertical: 4, letterSpacing: 0 },
  newsT: { fontFamily: FONT, fontSize: 14, lineHeight: 21, color: C.fg2, letterSpacing: 0 },
  av: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  avT: { fontFamily: FONT, fontSize: 15, fontWeight: '700', color: '#1B64DA' },
  mk: { position: 'absolute', right: -3, bottom: -3, borderRadius: 10, borderWidth: 2, borderColor: C.card, backgroundColor: C.card },
  need: { fontFamily: FONT, fontSize: 11, fontWeight: '700', color: C.accentInk, backgroundColor: C.accentSoft, paddingHorizontal: 6, paddingVertical: 1, borderRadius: 6, overflow: 'hidden' },
  when: { marginLeft: 'auto', fontFamily: FONT, fontSize: 12, color: C.fg4 },
  dot: { width: 7, height: 7, borderRadius: 4, backgroundColor: C.red },
  board: { marginHorizontal: 0, marginTop: 8, paddingHorizontal: 26, paddingTop: 28 },
  boardT: { fontFamily: FONT, fontSize: 24, lineHeight: 33, fontWeight: '700', color: C.fg, letterSpacing: -0.3 },
  boardK: { fontFamily: FONT, fontSize: 15, lineHeight: 22, fontWeight: '500', color: C.fg3, letterSpacing: 0, marginTop: 8 },
  boardImg: { position: 'absolute', right: 6, bottom: -6 },
  boardPage: { position: 'absolute', right: 14, bottom: 14, backgroundColor: 'rgba(0,21,42,0.32)', borderRadius: 14, paddingHorizontal: 10, paddingVertical: 3 },
  boardPageT: { fontFamily: FONT, fontSize: 13, fontWeight: '600', color: '#fff', letterSpacing: 0 },
  titleRow: { flexDirection: 'row', alignItems: 'baseline', gap: 8, paddingHorizontal: 24, paddingTop: 12, paddingBottom: 18 },
  title: { fontFamily: FONT, fontSize: 26, lineHeight: 34, fontWeight: '700', color: C.fg, letterSpacing: 0, marginRight: 4 },
  titleK: { fontFamily: FONT, fontSize: 16, fontWeight: '500', color: C.fg3, letterSpacing: 0 },
  titleV: { fontFamily: FONT, fontSize: 18, fontWeight: '700', color: C.accentInk, letterSpacing: 0 },
  shorts: { flexDirection: 'row', paddingHorizontal: 8, paddingVertical: 18 },
  short: { flex: 1, alignItems: 'center', gap: 8 },
  shortT: { fontFamily: FONT, fontSize: 13, fontWeight: '500', color: C.fg2, letterSpacing: 0 },
  split: { flexDirection: 'row', alignItems: 'center', gap: 18, marginHorizontal: 24, marginTop: 28 },
  splitBar: { width: 1, height: 36, backgroundColor: C.line },
  splitK: { fontFamily: FONT, fontSize: 13, color: C.fg3, letterSpacing: 0 },
  splitV: { fontFamily: FONT, fontSize: 16, fontWeight: '700', color: C.fg, letterSpacing: 0 },
  strip: { flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: 20, marginTop: 26, height: 52, borderRadius: 16, borderWidth: 1.5, borderColor: '#FFD9A8', backgroundColor: C.card, paddingHorizontal: 16 },
  stripK: { fontFamily: FONT, fontSize: 15, fontWeight: '700', color: C.accentInk, letterSpacing: 0 },
  stripT: { flex: 1, fontFamily: FONT, fontSize: 15, fontWeight: '500', color: C.fg, letterSpacing: 0, marginLeft: 4 },
  bigHead: { fontFamily: FONT, fontSize: 22, lineHeight: 30, fontWeight: '700', color: C.fg, letterSpacing: 0 },
  tabs: { flexDirection: 'row', gap: 22, paddingHorizontal: 24, marginTop: 14, borderBottomWidth: 1, borderBottomColor: '#F2F4F6' },
  tab: { paddingBottom: 10 },
  tabT: { fontFamily: FONT, fontSize: 16, fontWeight: '600', color: C.fg4, letterSpacing: 0 },
  tabOn: { color: C.fg, fontWeight: '700' },
  tabBar: { position: 'absolute', left: 0, right: 0, bottom: -1, height: 2.5, borderRadius: 2, backgroundColor: C.fg },
  sq: { width: 44, height: 44, borderRadius: 14, backgroundColor: '#F4F5F7', alignItems: 'center', justifyContent: 'center' },
  moreBtn: { marginTop: 8, height: 44, borderRadius: 12, backgroundColor: '#F4F5F7', alignItems: 'center', justifyContent: 'center' },
  moreBtnT: { fontFamily: FONT, fontSize: 14, fontWeight: '600', color: C.fg2, letterSpacing: 0 },
  empty: { fontFamily: FONT, fontSize: 14, color: C.fg3, paddingVertical: 8 },
});
