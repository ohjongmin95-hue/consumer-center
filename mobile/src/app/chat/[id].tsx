import { router, Stack, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Loading, Notice, SmallBtn } from '../../components/ui';
import { api, ApiError, ChatMsg, ChatRoom } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { C, R, FONT } from '../../lib/theme';

// 대화방: 고객 말·AI 답·사장님 답이 말풍선으로 이어지고, 결정할 일은 대화 안의 카드로 뜬다.
// 보내기는 누르는 즉시 말풍선이 생기고(카페24·DM·메일로는 서버가 뒤에서 보낸다), 3초마다 새 말을 받아 온다.
export default function ChatRoomScreen() {
  const id = Number(useLocalSearchParams<{ id: string }>().id);
  const { session, logout } = useAuth();
  const [room, setRoom] = useState<ChatRoom | null>(null);
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [text, setText] = useState('');
  const [note, setNote] = useState(false);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const last = useRef(0);
  const need = useRef<boolean | null>(null);
  const scroll = useRef<ScrollView>(null);
  const token = session?.token ?? '';

  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) return logout();
      setErr((e as Error).message);
    },
    [logout],
  );
  const take = (d: ChatRoom) => {
    setRoom(d);
    setMsgs(d.msgs);
    last.current = d.last;
    need.current = d.need;
  };
  // 새 말만 받아 붙인다. 결정 카드가 생기거나 사라졌으면 전체를 다시 받는다
  const poll = useCallback(async () => {
    if (!token) return;
    try {
      const d = await api.chat(token, id, last.current);
      if (need.current !== null && d.need !== need.current) return take(await api.chat(token, id));
      setRoom(d);
      if (d.msgs.length) {
        setMsgs((m) => [...m.filter((x) => !x.tmp && !d.msgs.some((n) => n.id === x.id)), ...d.msgs]);
        last.current = d.last;
      }
    } catch (e) {
      fail(e);
    }
  }, [token, id, fail]);
  useFocusEffect(
    useCallback(() => {
      if (!token) return;
      api.chat(token, id).then(take, fail);
      const h = setInterval(poll, 3000);
      return () => clearInterval(h);
    }, [token, id, poll, fail]),
  );

  const send = async (act: 'reply' | 'approve' | 'hold' | 'note', body = '') => {
    if (!token || busy) return;
    if ((act === 'reply' || act === 'note') && !body.trim()) return;
    setErr('');
    setOk('');
    setBusy(act);
    if (act === 'reply' || act === 'note') {
      // 누르자마자 말풍선을 띄운다 (서버 답을 기다리지 않음)
      setMsgs((m) => [...m, { id: -Date.now(), who: act === 'note' ? 'note' : 'co', by: '나', text: body.trim(), at: '보내는 중', ts: '', tmp: true }]);
      setText('');
    }
    try {
      const d = await api.chatAct(token, id, { act, text: body.trim() });
      take(d);
      if (act === 'approve' || act === 'hold') setOk(d.message || '');
    } catch (e) {
      setMsgs((m) => m.filter((x) => !x.tmp));
      if (act === 'reply' || act === 'note') setText(body);
      fail(e);
    } finally {
      setBusy('');
    }
  };

  if (!room) {
    return (
      <>
        <Stack.Screen options={{ title: '상담' }} />
        <Notice text={err} />
        {err ? null : <Loading />}
      </>
    );
  }
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.band }} edges={['bottom']}>
      <Stack.Screen
        options={{
          title: room.name,
          headerRight: () => (
            <Pressable onPress={() => router.push(`/case/${id}`)} hitSlop={8} accessibilityRole="button">
              <Text style={st.more}>자세히 처리</Text>
            </Pressable>
          ),
        }}
      />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}>
        <Text style={st.sub}>{[room.channel, room.category, room.status_label].join(' · ')}</Text>
        <ScrollView ref={scroll} contentContainerStyle={st.list} onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: false })} keyboardShouldPersistTaps="handled">
          {msgs.map((m) => (
            <Bubble key={m.id} m={m} />
          ))}
          {room.need ? (
            <View style={st.dec}>
              <Text style={st.decH}>사장님 결정이 필요해요 · {room.category}</Text>
              {room.why ? <Text style={st.why}>{room.why}</Text> : null}
              {room.draft ? (
                <View style={st.draft}>
                  <Text style={st.draftH}>승인하면 보낼 답</Text>
                  <Text style={st.draftT}>{room.draft}</Text>
                </View>
              ) : null}
              <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
                <SmallBtn title={room.draft ? '이대로 보내기' : '승인'} onPress={() => send('approve')} busy={busy === 'approve'} />
                {room.draft ? <SmallBtn title="고쳐서 보내기" kind="gray" onPress={() => setText(room.draft)} /> : null}
                <SmallBtn title="보류" kind="gray" onPress={() => send('hold')} busy={busy === 'hold'} />
                <SmallBtn title="환불·교환 처리" kind="gray" onPress={() => router.push(`/case/${id}`)} />
              </View>
            </View>
          ) : null}
        </ScrollView>
        <Notice text={err} />
        <Notice text={ok} tone="ok" />
        {room.can_reply ? (
          <View style={st.comp}>
            <Pressable onPress={() => setNote((v) => !v)} style={[st.noteBtn, note && { backgroundColor: '#FFF6D6' }]} accessibilityLabel={note ? '메모 쓰는 중' : '메모로 바꾸기'}>
              <Text style={[st.noteText, note && { color: '#8A6A00' }]}>메모</Text>
            </Pressable>
            <TextInput
              style={[st.input, note && { backgroundColor: '#FFFBEA' }]}
              value={text}
              onChangeText={setText}
              placeholder={note ? '팀에게 남길 메모 (고객에게 안 보여요)' : `${room.name}님에게 답하기${room.send_via ? ' · ' + room.send_via : ''}`}
              placeholderTextColor={C.fg4}
              multiline
              maxLength={3000}
            />
            <Pressable onPress={() => send(note ? 'note' : 'reply', text)} disabled={!text.trim()} style={({ pressed }) => [st.send, (!text.trim() || pressed) && { opacity: 0.5 }]} accessibilityRole="button">
              <Text style={st.sendText}>{note ? '남기기' : '보내기'}</Text>
            </Pressable>
          </View>
        ) : null}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Bubble({ m }: { m: ChatMsg }) {
  if (m.who === 'sys') return <Text style={st.sys}>{`${m.text} · ${m.at}`}</Text>;
  const mine = m.who !== 'me';
  const bg = m.who === 'me' ? C.card : m.who === 'ai' ? C.accentSoft : m.who === 'note' ? '#FFF6D6' : C.accent;
  const fg = m.who === 'co' ? '#fff' : C.fg;
  return (
    <View style={{ alignItems: mine ? 'flex-end' : 'flex-start', gap: 3, opacity: m.tmp ? 0.7 : 1 }}>
      <Text style={st.by}>{m.who === 'note' ? `${m.by} · 메모 (고객에게 안 보임)` : m.by}</Text>
      <View style={[st.bub, { backgroundColor: bg }, mine ? { borderTopRightRadius: 6 } : { borderTopLeftRadius: 6 }]}>
        <Text style={[st.bubText, { color: fg }]}>{m.text}</Text>
      </View>
      <Text style={st.at}>{m.at}</Text>
    </View>
  );
}

const st = StyleSheet.create({
  more: { fontFamily: FONT, fontSize: 14, fontWeight: '700', color: C.accentInk, paddingHorizontal: 8 },
  sub: { fontFamily: FONT, fontSize: 13, color: C.fg3, paddingHorizontal: 20, paddingBottom: 6 },
  list: { padding: 16, gap: 12 },
  sys: { alignSelf: 'center', fontFamily: FONT, fontSize: 12, color: C.fg3, backgroundColor: C.fill, borderRadius: 10, paddingHorizontal: 10, paddingVertical: 4, overflow: 'hidden', textAlign: 'center' },
  by: { fontFamily: FONT, fontSize: 12, fontWeight: '600', color: C.fg3, paddingHorizontal: 4 },
  bub: { maxWidth: '82%', borderRadius: 18, paddingHorizontal: 14, paddingVertical: 10 },
  bubText: { fontFamily: FONT, fontSize: 15, lineHeight: 22 },
  at: { fontFamily: FONT, fontSize: 11, color: C.fg4, paddingHorizontal: 4 },
  dec: { backgroundColor: C.card, borderRadius: R.lg, borderWidth: 2, borderColor: C.accent, padding: 16, gap: 10 },
  decH: { fontFamily: FONT, fontSize: 16, fontWeight: '700', color: C.fg },
  why: { fontFamily: FONT, fontSize: 14, color: C.fg2, lineHeight: 20 },
  draft: { backgroundColor: C.band, borderRadius: R.sm, padding: 12, gap: 4 },
  draftH: { fontFamily: FONT, fontSize: 12, fontWeight: '700', color: C.fg3 },
  draftT: { fontFamily: FONT, fontSize: 14, color: C.fg, lineHeight: 20 },
  comp: { flexDirection: 'row', alignItems: 'flex-end', gap: 8, padding: 10, backgroundColor: C.card, borderTopWidth: 1, borderTopColor: C.line },
  noteBtn: { height: 44, paddingHorizontal: 10, borderRadius: 12, backgroundColor: C.fill, justifyContent: 'center' },
  noteText: { fontFamily: FONT, fontSize: 13, fontWeight: '700', color: C.fg3 },
  input: { flex: 1, minHeight: 44, maxHeight: 140, borderRadius: 14, backgroundColor: C.band, paddingHorizontal: 14, paddingTop: 11, paddingBottom: 11, fontFamily: FONT, fontSize: 15, color: C.fg },
  send: { height: 44, paddingHorizontal: 16, borderRadius: 12, backgroundColor: C.accent, justifyContent: 'center' },
  sendText: { fontFamily: FONT, fontSize: 15, fontWeight: '700', color: '#fff' },
});
