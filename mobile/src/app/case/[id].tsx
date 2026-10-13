import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import * as Print from 'expo-print';
import * as Sharing from 'expo-sharing';
import * as WebBrowser from 'expo-web-browser';
import { Linking, Platform, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { CAT_ICON, Icon } from '../../components/Icon';
import { Btn, Card, Chips, Field, H2, Loading, Notice, StatusPill } from '../../components/ui';
import { api, ApiError, BizDetail, fmtDate } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { C, R } from '../../lib/theme';

type Mode = '' | 'ask' | 'reply';

export default function CaseScreen() {
  const id = Number(useLocalSearchParams<{ id: string }>().id);
  const { session, meta, logout } = useAuth();
  const [c, setC] = useState<BizDetail | null>(null);
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const [busy, setBusy] = useState('');
  const [mode, setMode] = useState<Mode>('');
  const [ask, setAsk] = useState('');
  const [msg, setMsg] = useState('');
  const [courier, setCourier] = useState('');
  const [tracking, setTracking] = useState('');
  const [comp, setComp] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!session) return;
    try {
      setC(await api.case(session.token, id));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return logout();
      setErr((e as Error).message);
    }
  }, [session, id, logout]);
  useEffect(() => {
    load();
  }, [load]);
  const reco = c?.comp?.reco ?? '';
  useEffect(() => setComp(reco), [reco]);

  const act = async (fields: Record<string, string>) => {
    if (!session) return;
    setBusy(fields.act);
    setErr('');
    setOk('');
    try {
      const d = await api.act(session.token, id, fields);
      setC(d);
      setOk(d.message || '');
      setMode('');
      setMsg('');
      setAsk('');
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy('');
    }
  };
  const draft = async () => {
    if (!session) return;
    setBusy('draft');
    try {
      const r = await api.draft(session.token, id);
      if (r.text) setMsg(r.text);
      else setErr(r.error || '초안을 만들지 못했어요.');
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy('');
    }
  };

  if (!c) return err ? <Notice text={err} /> : <Loading />;
  const can = c.can;
  const anyOpen = can.approve || can.ask || can.reply;

  return (
    <ScrollView
      contentContainerStyle={{ paddingTop: 4, paddingBottom: 40 }}
      keyboardShouldPersistTaps="handled"
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
      <Notice text={ok} tone="ok" />
      <Notice text={err} />

      <Card>
        <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
          {c.pending ? <StatusPill status="forwarded" label="승인 대기" /> : <StatusPill status={c.status} label={c.status_label} />}
          {c.overdue ? <StatusPill status="unresolved" label="기한 지남" /> : null}
        </View>
        <View style={{ flexDirection: 'row', gap: 12, alignItems: 'center' }}>
          <View style={st.ic}>
            <Icon name={CAT_ICON[c.category] ?? 'note'} size={28} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={st.cat}>{c.category}</Text>
            <Text style={st.title}>{c.title}</Text>
          </View>
        </View>
        <View style={st.kv}>
          <KV k="고객" v={c.name || '이름 없음'} />
          <KV k="접수번호" v={c.no} />
          <KV k="접수일" v={fmtDate(c.created)} />
          {c.due ? <KV k="답변 기한" v={c.due.slice(0, 10)} red={c.overdue} /> : null}
          {c.decision_label && !c.pending ? <KV k="처리 방식" v={c.decision_label} /> : null}
        </View>
      </Card>

      {can.approve ? (
        <Card style={{ borderWidth: 2, borderColor: C.accent }}>
          <Text style={st.eyebrow}>소보루 추천 처리</Text>
          <Text style={st.planTitle}>{c.plan.title}</Text>
          {c.cancel_blocked && c.order ? <Notice flat text={`이미 발송된 주문이에요 (${c.order.status_label}) · 취소 대신 받으신 뒤 반품으로 안내해 주세요`} /> : null}
          <View style={{ gap: 6, marginVertical: 12 }}>
            {c.plan.steps.map((s, i) => (
              <Text key={s} style={st.step}>
                <Text style={{ color: C.accent, fontWeight: '700' }}>{i + 1} </Text>
                {s}
              </Text>
            ))}
          </View>
          {c.plan.reply ? (
            <View style={st.quote}>
              <Text style={st.quoteLabel}>고객에게 보낼 답변</Text>
              <Text style={st.quoteText}>{c.plan.reply}</Text>
            </View>
          ) : null}
          <Btn title="승인하고 답변 보내기" onPress={() => act({ act: 'approve' })} busy={busy === 'approve'} style={{ marginTop: 14 }} />
        </Card>
      ) : null}

      {anyOpen ? (
        <Card>
          <H2>{can.approve ? '다르게 처리하기' : '처리하기'}</H2>
          <View style={{ flexDirection: 'row', gap: 8 }}>
            {can.reply ? <ModeBtn on={mode === 'reply'} title="직접 답변" onPress={() => setMode(mode === 'reply' ? '' : 'reply')} /> : null}
            {can.ask ? <ModeBtn on={mode === 'ask'} title="자료 요청" onPress={() => setMode(mode === 'ask' ? '' : 'ask')} /> : null}
            {can.hold ? <ModeBtn on={false} title={busy === 'hold' ? '보류 중' : '보류'} onPress={() => act({ act: 'hold' })} /> : null}
          </View>
          {mode === 'reply' ? (
            <View style={{ gap: 10, marginTop: 14 }}>
              <Field multiline placeholder="고객에게 보낼 답변을 적어 주세요" value={msg} onChangeText={setMsg} />
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <Btn title={busy === 'draft' ? '만드는 중' : '초안 만들기'} kind="soft" onPress={draft} busy={busy === 'draft'} style={{ flex: 1 }} />
                <Btn title="보내기" onPress={() => act({ act: 'reply', msg })} busy={busy === 'reply'} disabled={!msg.trim()} style={{ flex: 1 }} />
              </View>
            </View>
          ) : null}
          {mode === 'ask' ? (
            <View style={{ gap: 10, marginTop: 14 }}>
              <Field multiline placeholder="비워 두면 주문번호와 사진을 요청합니다" value={ask} onChangeText={setAsk} style={{ height: 100 }} />
              <Btn title="고객에게 요청하기" onPress={() => act({ act: 'ask', ask })} busy={busy === 'ask'} />
            </View>
          ) : null}
        </Card>
      ) : null}

      {can.comp ? (
        <Card>
          <H2>보상</H2>
          <Text style={st.p}>{c.comp?.reco ? '정해 둔 보상을 추천합니다. 승인하면 고객에게 사과와 함께 알림이 갑니다.' : '보상을 하려면 내용을 적고 승인해 주세요. 자동 처리 규칙에서 유형별 보상을 정해 둘 수 있습니다.'}</Text>
          <View style={{ gap: 10, marginTop: 8 }}>
            <Field placeholder={`예: ${c.comp?.examples?.[0] ?? '적립금 3,000원'}`} value={comp} onChangeText={setComp} maxLength={100} />
            <View style={{ flexDirection: 'row', gap: 8 }}>
              <Btn title="보상 안 함" kind="gray" onPress={() => act({ act: 'comp_skip' })} busy={busy === 'comp_skip'} style={{ flex: 1 }} />
              <Btn title="보상 승인" onPress={() => act({ act: 'comp', comp })} busy={busy === 'comp'} disabled={!comp.trim()} style={{ flex: 2 }} />
            </View>
          </View>
        </Card>
      ) : c.comp?.status === 'given' ? (
        <Card>
          <H2>보상</H2>
          <Text style={st.p}>{c.comp.given} · 고객에게 알렸습니다</Text>
        </Card>
      ) : null}

      {c.tracks?.length || can.ship_track ? (
        <Card>
          <H2>배송 상태</H2>
          {(c.tracks ?? []).map((t) => (
            <Text key={t.kind} style={st.p}>
              {t.label}: {t.courier} {t.invoice}
              {t.status ? ` · ${t.status}${t.place ? ' · ' + t.place : ''}${t.time ? ' · ' + t.time.slice(5, 16) : ''}` : t.live ? ' · 확인 중' : ''}
            </Text>
          ))}
          {can.ship_track ? (
            <View style={{ gap: 10, marginTop: 8 }}>
              <Text style={st.p}>보낸 택배사와 송장번호를 넣으면 고객에게 바로 알리고, 배송 상태가 바뀔 때마다 자동으로 알려 줍니다.</Text>
              <Chips items={[...(meta?.couriers ?? []), '기타']} value={courier} onChange={setCourier} />
              <Field placeholder="송장번호" keyboardType="number-pad" value={tracking} onChangeText={setTracking} />
              <Btn title="고객에게 송장 알리기" onPress={() => act({ act: 'ship_track', courier, tracking })} busy={busy === 'ship_track'} disabled={!courier || !tracking} />
            </View>
          ) : null}
        </Card>
      ) : null}

      {can.ret_received || can.out_ship || can.refund_done || c.ret.status ? (
        <Card>
          <H2>반품·교환·환불</H2>
          {c.ret.tracking ? <Text style={st.p}>고객 발송: {c.ret.courier} {c.ret.tracking}</Text> : null}
          {c.ret.out_tracking ? <Text style={st.p}>새 상품 발송: {c.ret.out_courier} {c.ret.out_tracking}</Text> : null}
          {can.ret_received ? <Btn title="반품 상품 받았어요" kind="soft" onPress={() => act({ act: 'ret_received' })} busy={busy === 'ret_received'} style={{ marginTop: 8 }} /> : null}
          {can.out_ship ? (
            <View style={{ gap: 10, marginTop: 8 }}>
              <Text style={st.label}>새 상품 보낸 택배사</Text>
              <Chips items={[...(meta?.couriers ?? []), '기타']} value={courier} onChange={setCourier} />
              <Field placeholder="송장번호" keyboardType="number-pad" value={tracking} onChangeText={setTracking} />
              <Btn title="고객에게 송장 알리기" onPress={() => act({ act: 'out_ship', courier, tracking })} busy={busy === 'out_ship'} disabled={!courier || !tracking} />
            </View>
          ) : null}
          {can.refund_done ? (
            <View style={{ gap: 10, marginTop: 8 }}>
              {c.refund.account ? (
                <Text style={st.p} selectable>
                  환불 계좌: {c.refund.bank} {c.refund.account} ({c.refund.holder})
                </Text>
              ) : (
                <Text style={st.p}>결제하신 수단으로 환불해 주세요.</Text>
              )}
              <Btn title="환불 완료했어요" kind="soft" onPress={() => act({ act: 'refund_done' })} busy={busy === 'refund_done'} />
            </View>
          ) : null}
        </Card>
      ) : null}

      <Card>
        <H2>고객 요청 내용</H2>
        <Text style={st.body} selectable>
          {c.body}
        </Text>
        <View style={st.kv}>
          {c.want ? <KV k="원하는 해결" v={c.want} /> : null}
          {c.order_no ? <KV k="주문번호" v={c.order_no} /> : null}
          {c.order ? <KV k="주문" v={`${c.order.product || c.order.order_no} · ${c.order.status_label}`} onPress={() => router.push(`/order/${c.order!.id}`)} /> : null}
          {c.product ? <KV k="상품" v={c.product} /> : null}
          {c.received_on ? <KV k="받은 날" v={c.received_on} /> : null}
          {c.phone ? <KV k="연락처" v={c.phone} onPress={() => Linking.openURL('tel:' + c.phone.replace(/\D/g, ''))} /> : null}
          {c.email ? <KV k="이메일" v={c.email} /> : null}
        </View>
        {c.files.length ? (
          <View style={{ gap: 6, marginTop: 12 }}>
            {c.files.map((f) => (
              <Pressable key={f.id} onPress={() => WebBrowser.openBrowserAsync(f.url)}>
                <Text style={st.file}>📎 {f.name}</Text>
              </Pressable>
            ))}
          </View>
        ) : null}
      </Card>

      <Card>
        <H2>처리 기록</H2>
        <View style={{ gap: 16 }}>
          {[...c.events].reverse().map((e) => (
            <View key={e.id} style={{ flexDirection: 'row', gap: 12 }}>
              <View style={[st.dot, { backgroundColor: e.kind === 'co' ? C.accent : e.kind === 'me' ? C.fg2 : C.fg4 }]} />
              <View style={{ flex: 1, gap: 4 }}>
                <Text style={st.evText}>
                  {e.kind === 'me' ? '고객 · ' : e.kind === 'co' ? '우리 회사 · ' : ''}
                  {e.text}
                </Text>
                {e.reply ? <Text style={st.evReply}>{e.reply}</Text> : null}
                {e.files.map((f) => (
                  <Pressable key={f.id} onPress={() => WebBrowser.openBrowserAsync(f.url)}>
                    <Text style={st.file}>📎 {f.name}</Text>
                  </Pressable>
                ))}
                <Text style={st.evTime}>{fmtDate(e.created)}</Text>
              </View>
            </View>
          ))}
        </View>
      </Card>
      <View style={{ marginHorizontal: 16 }}>
        <RecordBtn id={c.id} />
      </View>
    </ScrollView>
  );
}

// 처리 기록 한 장을 PDF로 만들어 저장·공유 (분쟁 조정이나 보관용)
function RecordBtn({ id }: { id: number }) {
  const { session } = useAuth();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const go = async () => {
    if (!session) return;
    setBusy(true);
    setErr('');
    try {
      const r = await api.record(session.token, id);
      if (Platform.OS === 'web') await Print.printAsync({ html: r.html });
      else {
        const { uri } = await Print.printToFileAsync({ html: r.html });
        await Sharing.shareAsync(uri, { mimeType: 'application/pdf', dialogTitle: `요청 처리 기록 ${r.no}`, UTI: 'com.adobe.pdf' });
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <View style={{ gap: 8 }}>
      <Notice text={err} flat />
      <Btn title="처리 기록 PDF로 저장" kind="gray" onPress={go} busy={busy} />
    </View>
  );
}

function KV({ k, v, red, onPress }: { k: string; v: string; red?: boolean; onPress?: () => void }) {
  return (
    <View style={{ flexDirection: 'row', gap: 12 }}>
      <Text style={st.k}>{k}</Text>
      <Text style={[st.v, red && { color: C.red }, onPress && { color: C.accentInk, textDecorationLine: 'underline' }]} onPress={onPress} selectable={!onPress}>
        {v}
      </Text>
    </View>
  );
}

function ModeBtn({ title, on, onPress }: { title: string; on: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[st.mode, on && { backgroundColor: C.fg }]}>
      <Text style={[st.modeText, on && { color: '#fff' }]}>{title}</Text>
    </Pressable>
  );
}

const st = StyleSheet.create({
  ic: { width: 52, height: 52, borderRadius: 16, backgroundColor: C.fill, alignItems: 'center', justifyContent: 'center' },
  cat: { fontSize: 14, fontWeight: '600', color: C.fg3, marginBottom: 2 },
  title: { fontSize: 19, fontWeight: '700', color: C.fg, letterSpacing: -0.5, lineHeight: 26 },
  kv: { gap: 8, marginTop: 16, paddingTop: 16, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: C.line },
  k: { width: 76, fontSize: 14, color: C.fg3 },
  v: { flex: 1, fontSize: 14, fontWeight: '600', color: C.fg },
  eyebrow: { fontSize: 13, fontWeight: '700', color: C.accentInk, marginBottom: 6 },
  planTitle: { fontSize: 19, fontWeight: '700', color: C.fg, letterSpacing: -0.5 },
  step: { fontSize: 15, color: C.fg2 },
  quote: { backgroundColor: C.band, borderRadius: R.md, padding: 14, gap: 6 },
  quoteLabel: { fontSize: 13, fontWeight: '700', color: C.fg3 },
  quoteText: { fontSize: 15, lineHeight: 23, color: C.fg },
  mode: { flex: 1, height: 44, borderRadius: R.sm, backgroundColor: C.fill, alignItems: 'center', justifyContent: 'center' },
  modeText: { fontSize: 15, fontWeight: '700', color: C.fg2 },
  label: { fontSize: 15, fontWeight: '600', color: C.fg2 },
  p: { fontSize: 15, lineHeight: 22, color: C.fg2 },
  body: { fontSize: 16, lineHeight: 25, color: C.fg },
  file: { fontSize: 14, fontWeight: '600', color: C.accentInk },
  dot: { width: 9, height: 9, borderRadius: 5, marginTop: 7 },
  evText: { fontSize: 15, fontWeight: '600', color: C.fg },
  evReply: { fontSize: 15, lineHeight: 23, color: C.fg2, backgroundColor: C.band, borderRadius: R.sm, padding: 12 },
  evTime: { fontSize: 13, color: C.fg3 },
});
