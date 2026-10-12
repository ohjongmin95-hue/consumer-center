import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CaseRow } from '../../components/CaseRow';
import { Btn, Field, Notice } from '../../components/ui';
import { api, ApiError, CaseSummary } from '../../lib/api';
import { useStore } from '../../lib/store';
import { C, R } from '../../lib/theme';

export default function Mine() {
  const { tokens, ready, addTokens, forget } = useStore();
  const [rows, setRows] = useState<CaseSummary[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [phone, setPhone] = useState('');
  const [pw, setPw] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; tone: 'ok' | 'error' } | null>(null);

  const load = useCallback(async () => {
    if (!tokens.length) return setRows([]);
    try {
      setRows((await api.mine(tokens)).cases);
    } catch (e) {
      setMsg({ text: (e as Error).message, tone: 'error' });
    }
  }, [tokens]);
  useFocusEffect(
    useCallback(() => {
      if (ready) load();
    }, [ready, load]),
  );

  const lookup = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.lookup(phone, pw);
      await addTokens(r.cases.map((c) => c.token!).filter(Boolean));
      setMsg({ text: `민원 ${r.cases.length}건을 찾았어요.`, tone: 'ok' });
      setPw('');
    } catch (e) {
      setMsg({ text: e instanceof ApiError ? e.message : '잠시 후 다시 시도해 주세요.', tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.band }} edges={['top']}>
      <ScrollView
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => (setRefreshing(true), await load(), setRefreshing(false))} />}
      >
        <View style={st.head}>
          <Text style={st.h1}>내 접수</Text>
          <Text style={st.sub}>이 휴대폰에서 접수하거나 찾은 내역이에요</Text>
        </View>
        {msg && <Notice text={msg.text} tone={msg.tone} />}
        <View style={st.card}>
          {rows === null ? (
            <Text style={st.empty}>불러오는 중이에요</Text>
          ) : rows.length ? (
            rows.map((c) => <CaseRow key={c.id} c={c} />)
          ) : (
            <Text style={st.empty}>아직 접수한 내역이 없어요</Text>
          )}
        </View>

        <View style={[st.card, { paddingVertical: 22, gap: 12 }]}>
          <Text style={st.h2}>휴대폰 번호로 찾기</Text>
          <Text style={st.sub}>다른 기기나 웹에서 접수했다면 접수할 때 정한 조회 비밀번호로 찾을 수 있어요.</Text>
          <Field value={phone} onChangeText={setPhone} placeholder="010-0000-0000" keyboardType="phone-pad" />
          <Field value={pw} onChangeText={setPw} placeholder="조회 비밀번호" secureTextEntry />
          <Btn title="찾기" onPress={lookup} busy={busy} disabled={!phone || !pw} />
        </View>

        {tokens.length > 0 && (
          <Pressable onPress={() => forget().then(() => setRows([]))} style={{ alignSelf: 'center', padding: 12 }}>
            <Text style={{ color: C.fg3, fontSize: 14, textDecorationLine: 'underline' }}>이 휴대폰에서 내 접수 목록 지우기</Text>
          </Pressable>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  head: { paddingHorizontal: 20, paddingTop: 24, paddingBottom: 20, gap: 6 },
  h1: { fontSize: 28, fontWeight: '800', color: C.fg, letterSpacing: -0.9 },
  h2: { fontSize: 19, fontWeight: '700', color: C.fg, letterSpacing: -0.6 },
  sub: { fontSize: 15, lineHeight: 22, color: C.fg3 },
  card: { backgroundColor: C.card, borderRadius: R.lg, paddingHorizontal: 20, paddingVertical: 6, marginHorizontal: 16, marginBottom: 12 },
  empty: { textAlign: 'center', color: C.fg3, fontSize: 15, paddingVertical: 28 },
});
