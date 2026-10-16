// 처리 통계: 웹 통계 화면과 같은 숫자. 월간 리포트로 이어진다.
import { router } from 'expo-router';
import { StyleSheet, Text, View } from 'react-native';
import { BarLine, Card, H2, Loading, MenuRow, Notice, Screen } from '../components/ui';
import { api } from '../lib/api';
import { C, FONT } from '../lib/theme';
import { useLoad } from '../lib/useLoad';

const pct = (v: number | null | undefined) => (v === null || v === undefined ? '-' : `${v}%`);
const hrs = (v: number | null | undefined) => (v === null || v === undefined ? '-' : `${v}시간`);

export default function Stats() {
  const { data, err } = useLoad(api.stats);
  if (!data) return err ? <Notice text={err} /> : <Loading />;
  const k = data.kpi;
  const maxW = Math.max(1, ...data.weeks.map((w) => w.n));
  const maxC = Math.max(1, ...data.cats.map((w) => w.n));
  const maxH = Math.max(1, ...data.how.map((w) => w.n));
  const cmp = data.compare;
  return (
    <Screen>
      <View style={st.grid}>
        <Big label="받은 요청" v={`${k.n}건`} />
        <Big label="자동 처리율" v={`${k.auto}%`} />
        <Big label="해결률" v={pct(k.res)} />
        <Big label="첫 답변까지" v={hrs(data.reply_h)} />
      </View>
      <Card style={{ paddingVertical: 4 }}>
        <MenuRow title="월간 리포트" sub="지난달 요청을 한 장으로 정리했습니다" onPress={() => router.push('/report')} last />
      </Card>
      <Card>
        <H2>주별 요청</H2>
        <View style={st.weeks}>
          {data.weeks.map((w) => (
            <View key={w.label} style={{ flex: 1, alignItems: 'center', gap: 6 }}>
              <Text style={st.wn}>{w.n}</Text>
              <View style={{ height: 100, justifyContent: 'flex-end', width: '60%' }}>
                <View style={{ height: Math.max(3, (w.n / maxW) * 100), backgroundColor: w.n ? C.accent : C.fill, borderRadius: 4 }} />
              </View>
              <Text style={st.wl}>{w.label}</Text>
            </View>
          ))}
        </View>
      </Card>
      <Card>
        <H2>처리 방식</H2>
        {data.how.map((h) => (
          <BarLine key={h.label} label={h.label} n={h.n} pct={h.pct} max={maxH} />
        ))}
      </Card>
      <Card>
        <H2>유형별</H2>
        {data.cats.map((h) => (
          <BarLine key={h.label} label={h.label} n={h.n} pct={h.pct} max={maxC} />
        ))}
      </Card>
      {cmp ? (
        <Card>
          <H2>같은 업종과 비교 (최근 90일)</H2>
          {cmp.ready ? (
            <View style={{ gap: 10 }}>
              <Text style={st.p}>같은 업종 {cmp.peers}곳의 평균과 비교했습니다.</Text>
              <Cmp label="자동 처리율" mine={pct(cmp.mine.auto)} avg={pct(cmp.avg.auto)} />
              <Cmp label="해결률" mine={pct(cmp.mine.res)} avg={pct(cmp.avg.res)} />
              <Cmp label="첫 답변까지" mine={hrs(cmp.mine.reply_h)} avg={hrs(cmp.avg.reply_h)} />
            </View>
          ) : (
            <Text style={st.p}>
              같은 업종 기업이 {cmp.need}곳 이상 모이면 비교해 드립니다. (지금 {cmp.have}곳)
            </Text>
          )}
        </Card>
      ) : null}
    </Screen>
  );
}

function Big({ label, v }: { label: string; v: string }) {
  return (
    <View style={st.big}>
      <Text style={{ fontFamily: FONT, fontSize: 13, color: C.fg3, fontWeight: '600' }}>{label}</Text>
      <Text style={{ fontFamily: FONT, fontSize: 22, fontWeight: '700', color: C.fg, letterSpacing: -0.6 }}>{v}</Text>
    </View>
  );
}
function Cmp({ label, mine, avg }: { label: string; mine: string; avg: string }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center' }}>
      <Text style={{ flex: 1, fontFamily: FONT, fontSize: 15, color: C.fg2, fontWeight: '600' }}>{label}</Text>
      <Text style={{ fontFamily: FONT, fontSize: 15, fontWeight: '700', color: C.accentInk, width: 80, textAlign: 'right' }}>우리 {mine}</Text>
      <Text style={{ fontFamily: FONT, fontSize: 15, color: C.fg3, width: 90, textAlign: 'right' }}>평균 {avg}</Text>
    </View>
  );
}

const st = StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginHorizontal: 16, marginTop: 8, marginBottom: 12 },
  big: { flexGrow: 1, flexBasis: '45%', backgroundColor: C.card, borderRadius: 16, padding: 16, gap: 6 },
  weeks: { flexDirection: 'row', alignItems: 'flex-end' },
  wn: { fontFamily: FONT, fontSize: 12, fontWeight: '700', color: C.fg2 },
  wl: { fontFamily: FONT, fontSize: 11, color: C.fg3 },
  p: { fontFamily: FONT, fontSize: 15, lineHeight: 22, color: C.fg2 },
});
