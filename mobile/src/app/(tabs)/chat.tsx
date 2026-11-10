import { router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ChannelIcon } from '../../components/ChannelIcon';
import { Avatar } from '../../components/Avatar';
import { Card, Loading, Notice, TopBar } from '../../components/ui';
import { api, ApiError, ChatRow } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { C, R, FONT } from '../../lib/theme';

// 상담: 웹 상담방처럼 대화방 목록. 카페24·인스타그램·메일 문의가 모두 여기로 들어오고, 결정할 일은 '결정 필요'로 보인다.
const TABS: [string, string][] = [
  ['open', '진행 중'],
  ['hold', '보류'],
  ['done', '종료'],
];

export default function ChatTab() {
  const { session, logout } = useAuth();
  const [tab, setTab] = useState('open');
  const [q, setQ] = useState('');
  const [rows, setRows] = useState<ChatRow[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [err, setErr] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const cur = useRef({ tab, q });
  cur.current = { tab, q };

  const load = useCallback(async () => {
    if (!session) return;
    const { tab: t, q: query } = cur.current;
    try {
      const r = await api.chatList(session.token, t, query.trim());
      if (cur.current.tab !== t) return; // 그새 다른 칸을 눌렀으면 버린다
      setRows(r.rows);
      setCounts(r.counts);
      setErr('');
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return logout();
      setErr((e as Error).message);
    }
  }, [session, logout]);
  // 화면을 보고 있는 동안 10초마다 새 문의를 받아 온다
  useFocusEffect(
    useCallback(() => {
      load();
      const h = setInterval(load, 10000);
      return () => clearInterval(h);
    }, [load]),
  );
  useEffect(() => {
    setRows(null);
    load();
  }, [tab, load]);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.band }} edges={['top']}>
      <TopBar />
      <View style={st.head}>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <Text style={st.h1}>상담</Text>
          <Pressable onPress={() => router.push('/new')} style={({ pressed }) => [st.add, pressed && { opacity: 0.7 }]} accessibilityRole="button">
            <Text style={{ color: C.fg2, fontWeight: '700', fontFamily: FONT, fontSize: 14 }}>+ 직접 등록</Text>
          </Pressable>
        </View>
        <TextInput style={st.search} placeholder="이름, 내용 검색" placeholderTextColor={C.fg4} value={q} onChangeText={setQ} onSubmitEditing={load} returnKeyType="search" />
        <View style={{ flexDirection: 'row', gap: 8 }}>
          {TABS.map(([key, label]) => {
            const on = key === tab;
            return (
              <Pressable key={key} onPress={() => setTab(key)} style={[st.chip, on && { backgroundColor: C.fg }]}>
                <Text style={[st.chipText, on && { color: '#fff' }]}>
                  {label} {counts[key] ?? ''}
                </Text>
              </Pressable>
            );
          })}
        </View>
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
          <Card style={{ paddingVertical: 6 }}>{rows.length ? rows.map((r) => <Room key={r.id} r={r} />) : <Text style={st.empty}>{tab === 'open' ? '지금 진행 중인 상담이 없어요.' : '상담이 없어요.'}</Text>}</Card>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function Room({ r }: { r: ChatRow }) {
  return (
    <Pressable onPress={() => router.push(`/chat/${r.id}`)} style={({ pressed }) => [st.row, pressed && { backgroundColor: C.band }]}>
      <View style={st.av}>
        <Avatar id={r.id} size={40} />
        <View style={st.mk} accessibilityLabel={r.channel}>
          <ChannelIcon mark={r.mark[1]} size={16} />
        </View>
      </View>
      <View style={{ flex: 1, gap: 3 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <Text style={st.name} numberOfLines={1}>
            {r.name}
          </Text>
          <Text style={st.when}>{r.when}</Text>
        </View>
        <Text style={[st.text, r.unread && { color: C.fg, fontWeight: '600' }]} numberOfLines={1}>
          {r.text}
        </Text>
        <View style={{ flexDirection: 'row', gap: 6 }}>
          {r.need ? <Badge label="결정 필요" tone="need" /> : r.ai ? <Badge label={r.ai} tone="ai" /> : null}
          <Badge label={r.cat} />
        </View>
      </View>
      {r.unread ? <View style={st.dot} accessibilityLabel="새 메시지" /> : null}
    </Pressable>
  );
}

function Badge({ label, tone }: { label: string; tone?: 'need' | 'ai' }) {
  const bg = tone === 'need' ? C.accentSoft : tone === 'ai' ? '#E8F3FF' : C.fill;
  const fg = tone === 'need' ? C.accentInk : tone === 'ai' ? '#1B64DA' : C.fg3;
  return (
    <View style={[st.bdg, { backgroundColor: bg }]}>
      <Text style={[st.bdgText, { color: fg }]}>{label}</Text>
    </View>
  );
}

const st = StyleSheet.create({
  add: { height: 32, paddingHorizontal: 12, borderRadius: 8, backgroundColor: C.card, justifyContent: 'center' },
  head: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 12, gap: 12 },
  h1: { fontFamily: FONT, fontSize: 22, lineHeight: 31, fontWeight: '700', color: C.fg, letterSpacing: 0, paddingHorizontal: 4 },
  search: { height: 44, borderRadius: 12, backgroundColor: C.card, paddingHorizontal: 16, fontFamily: FONT, fontSize: 15, color: C.fg },
  chip: { height: 32, paddingHorizontal: 12, borderRadius: 16, backgroundColor: C.card, justifyContent: 'center' },
  chipText: { fontFamily: FONT, fontSize: 13, fontWeight: '600', color: C.fg2 },
  empty: { fontFamily: FONT, fontSize: 15, color: C.fg3, paddingVertical: 14 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 11, paddingHorizontal: 12, marginHorizontal: -12, borderRadius: 12 },
  av: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  avText: { fontFamily: FONT, fontSize: 15, fontWeight: '700', color: '#1B64DA' },
  mk: { position: 'absolute', right: -4, bottom: -4, borderRadius: 13, borderWidth: 2, borderColor: C.card, backgroundColor: C.card },
  name: { flexShrink: 1, fontFamily: FONT, fontSize: 15, fontWeight: '600', color: C.fg, letterSpacing: 0 },
  when: { marginLeft: 'auto', fontFamily: FONT, fontSize: 12, color: C.fg4 },
  text: { fontFamily: FONT, fontSize: 13, lineHeight: 19.5, color: C.fg3 },
  bdg: { height: 20, paddingHorizontal: 6, borderRadius: 6, justifyContent: 'center' },
  bdgText: { fontFamily: FONT, fontSize: 11, fontWeight: '700' },
  dot: { width: 7, height: 7, borderRadius: 4, backgroundColor: C.red },
});
