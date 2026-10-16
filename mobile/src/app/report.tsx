// 월간 리포트: 달을 고르면 그 달 요청 요약. 문구를 그대로 공유할 수 있다.
import { useState } from 'react';
import { Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { BarLine, Btn, Card, H2, Loading, Notice, Screen } from '../components/ui';
import { api, Report } from '../lib/api';
import { useAuth } from '../lib/auth';
import { C, FONT } from '../lib/theme';
import { errText, useLoad } from '../lib/useLoad';

const ymLabel = (ym: string) => `${ym.slice(0, 4)}년 ${Number(ym.slice(5))}월`;

export default function ReportScreen() {
  const { logout } = useAuth();
  const { data, setData, err, setErr, token } = useLoad<Report>((t) => api.report(t));
  const [busy, setBusy] = useState('');
  if (!data) return err ? <Notice text={err} /> : <Loading />;
  const pick = async (ym: string) => {
    setBusy(ym);
    try {
      setData(await api.report(token, ym));
    } catch (e) {
      setErr(errText(e, logout));
    } finally {
      setBusy('');
    }
  };
  const maxC = Math.max(1, ...data.cats.map((c) => c.n));
  const diff = data.n - data.prev_n;
  return (
    <Screen>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingHorizontal: 16, paddingVertical: 8 }}>
        {data.months.map((m) => (
          <Pressable key={m} onPress={() => pick(m)} style={[st.chip, m === data.ym && { backgroundColor: C.fg }]}>
            <Text style={[st.chipT, m === data.ym && { color: '#fff' }]}>{busy === m ? '…' : ymLabel(m)}</Text>
          </Pressable>
        ))}
      </ScrollView>
      <View style={{ paddingHorizontal: 24, paddingVertical: 14, gap: 6 }}>
        <Text style={st.h1}>{ymLabel(data.ym)} CS 리포트</Text>
        <Text style={st.p}>
          받은 요청 {data.n}건 · 지난달보다 {diff === 0 ? '같아요' : diff > 0 ? `${diff}건 많아요` : `${-diff}건 적어요`}
        </Text>
      </View>
      <Notice text={err} />
      <Card>
        <Line label="자동 처리율" v={`${data.auto}%`} />
        <Line label="해결률" v={data.res === null ? '-' : `${data.res}%`} />
        <Line label="첫 답변까지 (중간값)" v={data.reply_h === null ? '-' : `${data.reply_h}시간`} />
        <Line label="답변 목표일을 넘긴 요청" v={`${data.late}건`} last />
      </Card>
      <Card>
        <H2>유형별</H2>
        {data.cats.map((c) => (
          <BarLine key={c.label} label={c.label} n={c.n} max={maxC} />
        ))}
      </Card>
      {data.top_products.length ? (
        <Card>
          <H2>요청이 많았던 상품</H2>
          {data.top_products.map((p) => (
            <Line key={p.label} label={p.label} v={`${p.n}건`} />
          ))}
        </Card>
      ) : null}
      {data.by_channel.length ? (
        <Card>
          <H2>들어온 곳</H2>
          {data.by_channel.map((p) => (
            <Line key={p.label} label={p.label} v={`${p.n}건`} />
          ))}
        </Card>
      ) : null}
      <View style={{ marginHorizontal: 16 }}>
        <Btn title="리포트 공유하기" kind="soft" onPress={() => Share.share({ message: data.text })} />
      </View>
    </Screen>
  );
}

function Line({ label, v, last }: { label: string; v: string; last?: boolean }) {
  return (
    <View style={[{ flexDirection: 'row', paddingVertical: 10 }, !last && { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.line }]}>
      <Text style={{ flex: 1, fontFamily: FONT, fontSize: 15, color: C.fg2 }}>{label}</Text>
      <Text style={{ fontFamily: FONT, fontSize: 15, fontWeight: '700', color: C.fg }}>{v}</Text>
    </View>
  );
}

const st = StyleSheet.create({
  h1: { fontFamily: FONT, fontSize: 23, fontWeight: '700', color: C.fg, letterSpacing: -0.7 },
  p: { fontFamily: FONT, fontSize: 15, color: C.fg3 },
  chip: { height: 38, paddingHorizontal: 14, borderRadius: 19, backgroundColor: C.card, justifyContent: 'center' },
  chipT: { fontFamily: FONT, fontSize: 14, fontWeight: '600', color: C.fg2 },
});
