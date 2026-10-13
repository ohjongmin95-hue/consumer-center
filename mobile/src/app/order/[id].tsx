import { useLocalSearchParams, router } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Linking, ScrollView, StyleSheet, Text, View } from 'react-native';
import { CaseRow } from '../../components/CaseRow';
import { Btn, Card, Chips, Field, H2, Loading, Notice } from '../../components/ui';
import { api, ApiError, OrderDetail } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { C } from '../../lib/theme';

export default function OrderScreen() {
  const id = Number(useLocalSearchParams<{ id: string }>().id);
  const { session, meta, logout } = useAuth();
  const [o, setO] = useState<OrderDetail | null>(null);
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const [busy, setBusy] = useState('');
  const [courier, setCourier] = useState('');
  const [invoice, setInvoice] = useState('');
  const [memo, setMemo] = useState('');
  const [sure, setSure] = useState(false);

  const load = useCallback(async () => {
    if (!session) return;
    try {
      const d = await api.order(session.token, id);
      setO(d);
      setCourier(d.courier);
      setInvoice(d.invoice);
      setMemo(d.memo);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return logout();
      setErr((e as Error).message);
    }
  }, [session, id, logout]);
  useEffect(() => {
    load();
  }, [load]);

  const save = async (key: string, f: Record<string, string>) => {
    if (!session) return;
    setBusy(key);
    setErr('');
    setOk('');
    try {
      const d = await api.saveOrder(session.token, id, f);
      setO(d);
      setOk(d.message || '');
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy('');
    }
  };

  if (!o) return err ? <Notice text={err} /> : <Loading />;
  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 32 }}>
      <View style={st.head}>
        <Text style={st.sub}>
          {o.order_no}
          {o.channel ? ` · ${o.channel}` : ''}
        </Text>
        <Text style={st.h1}>{o.product || o.order_no}</Text>
        <Text style={st.sub}>
          {o.status_label}
          {o.qty > 1 ? ` · ${o.qty}개` : ''}
          {o.amount ? ` · ${o.amount.toLocaleString()}원` : ''}
          {o.ordered_on ? ` · ${o.ordered_on} 주문` : ''}
        </Text>
      </View>
      <Notice text={err} />
      <Notice text={ok} tone="ok" />

      <Card>
        <H2>상태</H2>
        <Chips items={o.statuses.map((s) => s.label)} value={o.status_label} onChange={(l) => save('status', { status: o.statuses.find((s) => s.label === l)?.value ?? o.status })} />
      </Card>

      <Card>
        <H2>발송</H2>
        {o.invoice ? (
          <Text style={st.p} onPress={o.link ? () => Linking.openURL(o.link) : undefined}>
            {o.courier} {o.invoice}
            {o.link ? ' · 조회하기' : ''}
          </Text>
        ) : null}
        <View style={{ gap: 10, marginTop: 8 }}>
          <Chips items={[...(meta?.couriers ?? []), '기타']} value={courier} onChange={setCourier} />
          <Field placeholder="송장번호" keyboardType="number-pad" value={invoice} onChangeText={setInvoice} />
          <Btn title={o.invoice ? '송장 고치기' : '송장 넣기'} onPress={() => save('invoice', { courier, invoice })} busy={busy === 'invoice'} disabled={!courier || !invoice} />
        </View>
      </Card>

      <Card>
        <H2>구매자</H2>
        <Text style={st.p}>
          {[o.buyer, o.phone, o.address].filter(Boolean).join('\n') || '구매자 정보가 없어요'}
        </Text>
        <View style={{ gap: 10, marginTop: 12 }}>
          <Field label="메모" value={memo} onChangeText={setMemo} multiline style={{ height: 90 }} />
          <Btn title="메모 저장" kind="gray" onPress={() => save('memo', { memo })} busy={busy === 'memo'} />
        </View>
      </Card>

      <Card>
        <H2>이 주문의 고객 요청</H2>
        {o.cases.length ? o.cases.map((c) => <CaseRow key={c.id} c={c} />) : <Text style={st.p}>아직 이 주문으로 들어온 요청이 없어요.</Text>}
      </Card>

      <View style={{ marginHorizontal: 16, marginTop: 12 }}>
        {sure ? (
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <Btn title="취소" kind="gray" onPress={() => setSure(false)} style={{ flex: 1 }} />
            <Btn
              title="지우기"
              kind="danger"
              style={{ flex: 1 }}
              onPress={async () => {
                if (!session) return;
                await api.saveOrder(session.token, id, { act: 'delete' }).catch(() => null);
                router.back();
              }}
            />
          </View>
        ) : (
          <Btn title="주문 지우기" kind="gray" onPress={() => setSure(true)} />
        )}
      </View>
    </ScrollView>
  );
}

const st = StyleSheet.create({
  head: { paddingHorizontal: 24, paddingTop: 12, paddingBottom: 16, gap: 6 },
  h1: { fontSize: 22, fontWeight: '700', color: C.fg, letterSpacing: -0.6 },
  sub: { fontSize: 14, color: C.fg3 },
  p: { fontSize: 15, lineHeight: 23, color: C.fg2 },
});
