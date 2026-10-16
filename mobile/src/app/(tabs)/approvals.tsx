// 승인할 일: 웹 '승인할 일'과 같은 화면. 처리 방법을 보고 승인·보류·자료 요청을 바로 누른다.
import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { catTf, Tf, TfTile } from '../../components/Tf';
import { Card, Loading, Notice, PageHead, SmallBtn, StatusPill, TopBar } from '../../components/ui';
import { api, ApiError, BizCase } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { setPending } from '../../lib/badge';
import { C, R, FONT } from '../../lib/theme';

export default function ApprovalsTab() {
  const { session, logout } = useAuth();
  const [rows, setRows] = useState<BizCase[] | null>(null);
  const [comp, setComp] = useState(0);
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const [busy, setBusy] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const token = session?.token ?? '';

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const r = await api.cases(token, 'pending');
      setRows(r.cases);
      setComp(r.counts.comp ?? 0);
      setPending(r.cases.length);
      setErr('');
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return logout();
      setErr((e as Error).message);
    }
  }, [token, logout]);
  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const run = async (key: string, f: () => Promise<{ message?: string }>) => {
    setBusy(key);
    setErr('');
    setOk('');
    try {
      const r = await f();
      setOk(r.message || '처리했습니다');
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return logout();
      setErr((e as Error).message);
    } finally {
      setBusy('');
    }
  };

  const groups = Object.entries((rows ?? []).reduce<Record<string, number>>((m, c) => ((m[c.category] = (m[c.category] ?? 0) + 1), m), {})).filter(([, n]) => n >= 2);

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.band }} edges={['top']}>
      <TopBar />
      <ScrollView
        contentContainerStyle={{ paddingBottom: 24 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => (setRefreshing(true), await load(), setRefreshing(false))} tintColor={C.accent} />}
      >
        {rows === null ? (
          err ? <Notice text={err} /> : <Loading />
        ) : (
          <>
            {rows.length ? <PageHead title="승인할 요청이 " accent={`${rows.length}건`} /> : <PageHead title="승인할 요청을 모두 처리했어요" />}
            <Notice text={err} />
            <Notice text={ok} tone="ok" />
            {comp ? (
              <Pressable onPress={() => router.navigate('/cases?f=comp')} style={st.warn}>
                <TfTile name="gift" />
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={st.warnT}>보상 승인을 기다리는 요청 {comp}건</Text>
                  <Text style={st.warnS}>정해 둔 보상을 확인하고 승인하면 고객에게 알림이 가요</Text>
                </View>
              </Pressable>
            ) : null}
            {groups.length ? (
              <View style={st.bulk}>
                {groups.map(([cat, n]) => (
                  <SmallBtn key={cat} kind="gray" title={`${cat} ${n}건 모두 승인`} busy={busy === 'all:' + cat} onPress={() => run('all:' + cat, () => api.approveMany(token, cat))} />
                ))}
              </View>
            ) : null}
            {rows.map((c) => (
              <Card key={c.id}>
                <Pressable onPress={() => router.push(`/case/${c.id}`)} style={({ pressed }) => pressed && { opacity: 0.6 }}>
                  <View style={st.meta}>
                    <Tf name={catTf(c.category)} size={20} />
                    <Text style={st.metaT}>{c.category}</Text>
                    <View style={{ flex: 1 }} />
                    {c.overdue ? <StatusPill status="unresolved" label="기한 지남" /> : c.due ? <Text style={st.metaT}>{dueText(c.due)}</Text> : null}
                  </View>
                  <Text style={st.title}>{c.title}</Text>
                  {c.want ? <Text style={st.want}>원하는 해결 {c.want}</Text> : null}
                </Pressable>
                {c.plan_title ? (
                  <View style={st.reco}>
                    <Text style={st.recoL}>처리 방법</Text>
                    <Text style={st.recoR}>{c.plan_title}</Text>
                  </View>
                ) : null}
                <View style={st.acts}>
                  <Pressable onPress={() => run('a' + c.id, () => api.act(token, c.id, { act: 'approve' }))} style={({ pressed }) => [st.btn, { backgroundColor: C.accent, flex: 1.4 }, pressed && { opacity: 0.85 }]}>
                    <Text style={[st.btnT, { color: '#fff' }]}>{busy === 'a' + c.id ? '승인 중' : '승인'}</Text>
                  </Pressable>
                  <Pressable onPress={() => run('h' + c.id, () => api.act(token, c.id, { act: 'hold' }))} style={({ pressed }) => [st.btn, pressed && { opacity: 0.7 }]}>
                    <Text style={st.btnT}>보류</Text>
                  </Pressable>
                  <Pressable onPress={() => run('k' + c.id, () => api.act(token, c.id, { act: 'ask' }))} style={({ pressed }) => [st.btn, pressed && { opacity: 0.7 }]}>
                    <Text style={st.btnT}>자료 요청</Text>
                  </Pressable>
                </View>
              </Card>
            ))}
            {!rows.length ? (
              <Card style={{ alignItems: 'center', paddingVertical: 36, gap: 8 }}>
                <Tf name="check" size={52} />
                <Text style={st.title}>새로 들어온 요청이 없어요</Text>
                <Text style={st.want}>새 요청이 오면 알림으로 알려 드려요</Text>
              </Card>
            ) : null}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function dueText(due: string) {
  const d = new Date(due.replace(' ', 'T'));
  return isNaN(d.getTime()) ? '' : `${d.getMonth() + 1}월 ${d.getDate()}일까지`;
}

const st = StyleSheet.create({
  warn: { flexDirection: 'row', gap: 12, alignItems: 'center', backgroundColor: C.card, borderRadius: R.lg, padding: 18, marginHorizontal: 14, marginBottom: 12 },
  warnT: { fontFamily: FONT, fontSize: 15, fontWeight: '700', color: C.fg },
  warnS: { fontFamily: FONT, fontSize: 13, color: C.fg3 },
  bulk: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginHorizontal: 14, marginBottom: 12 },
  meta: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 10 },
  metaT: { fontFamily: FONT, fontSize: 13, fontWeight: '600', color: C.fg3 },
  title: { fontFamily: FONT, fontSize: 18, lineHeight: 26, fontWeight: '700', color: C.fg, letterSpacing: -0.5 },
  want: { fontFamily: FONT, fontSize: 14, color: C.fg3, marginTop: 4 },
  reco: { backgroundColor: C.fill, borderRadius: 14, padding: 14, marginTop: 14, gap: 4 },
  recoL: { fontFamily: FONT, fontSize: 12, fontWeight: '700', color: C.accentInk },
  recoR: { fontFamily: FONT, fontSize: 15, fontWeight: '600', color: C.fg },
  acts: { flexDirection: 'row', gap: 8, marginTop: 14 },
  btn: { flex: 1, height: 48, borderRadius: 14, backgroundColor: C.fill, alignItems: 'center', justifyContent: 'center' },
  btnT: { fontFamily: FONT, fontSize: 16, fontWeight: '700', color: C.fg2 },
});
