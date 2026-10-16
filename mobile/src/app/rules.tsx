// 자동 처리 규칙: 유형마다 소보루가 바로 처리할지, 어떤 답변을 보낼지 정한다.
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Icon, CAT_ICON } from '../components/Icon';
import { Btn, Card, Chips, Field, Loading, Notice, Screen, Toggle } from '../components/ui';
import { api, Rule } from '../lib/api';
import { useAuth } from '../lib/auth';
import { C, FONT } from '../lib/theme';
import { errText, useLoad } from '../lib/useLoad';

export default function Rules() {
  const { data, setData, err, token } = useLoad(api.rules);
  const [ok, setOk] = useState('');
  if (!data) return err ? <Notice text={err} /> : <Loading />;
  const c = data.chat;
  return (
    <Screen>
      <View style={st.head}>
        <Text style={st.p}>켜 둔 유형의 요청은 사장님 확인 없이 소보루가 아래 답변으로 바로 처리합니다. 꺼 두면 사장님이 승인한 뒤에 답변합니다.</Text>
      </View>
      <Card>
        <Text style={st.h2}>이번 달 상담 챗봇</Text>
        <View style={{ flexDirection: 'row', gap: 8 }}>
          <Stat label="물어본 고객" v={c.asked} />
          <Stat label="챗봇으로 해결" v={c.solved} />
          <Stat label="요청 접수" v={c.filed} />
        </View>
      </Card>
      <Notice text={ok} tone="ok" />
      {data.rules.map((r) => (
        <RuleCard key={r.category} r={r} conds={data.conds} token={token} onSaved={(d, m) => (setData(d), setOk(m))} />
      ))}
    </Screen>
  );
}

function Stat({ label, v }: { label: string; v: number }) {
  return (
    <View style={{ flex: 1, backgroundColor: C.fill, borderRadius: 14, padding: 12, gap: 4 }}>
      <Text style={{ fontFamily: FONT, fontSize: 12, color: C.fg3, fontWeight: '600' }}>{label}</Text>
      <Text style={{ fontFamily: FONT, fontSize: 18, fontWeight: '700', color: C.fg }}>{v}건</Text>
    </View>
  );
}

function RuleCard({ r, conds, token, onSaved }: { r: Rule; conds: { value: string; label: string }[]; token: string; onSaved: (d: Awaited<ReturnType<typeof api.rules>>, msg: string) => void }) {
  const { logout } = useAuth();
  const [reply, setReply] = useState(r.reply);
  const [faq, setFaq] = useState(r.faq);
  const [comp, setComp] = useState(r.comp ?? '');
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const save = async (f: Partial<Rule>) => {
    setBusy(true);
    setErr('');
    try {
      const d = await api.saveRule(token, { category: r.category, ...f });
      onSaved(d, `${r.category} 규칙을 저장했습니다`);
      setOpen(false);
    } catch (e) {
      setErr(errText(e, logout));
    } finally {
      setBusy(false);
    }
  };
  const condLabel = conds.find((x) => x.value === r.cond)?.label ?? '항상';
  return (
    <Card>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
        <Icon name={CAT_ICON[r.category] ?? 'note'} size={30} />
        <View style={{ flex: 1 }}>
          <Toggle title={r.category} sub={r.auto ? `자동 처리 · ${condLabel}` : '사장님 승인 후 답변'} value={r.auto} onChange={(v) => save({ auto: v })} disabled={busy} />
        </View>
      </View>
      {r.cond_ok && r.auto ? (
        <View style={{ gap: 8, marginTop: 6 }}>
          <Text style={st.label}>자동 처리 조건</Text>
          <Chips items={conds.map((x) => x.label)} value={condLabel} onChange={(l) => save({ cond: conds.find((x) => x.label === l)?.value ?? '' })} />
        </View>
      ) : null}
      {open ? (
        <View style={{ gap: 12, marginTop: 14 }}>
          <Field label="고객에게 보낼 답변" value={reply} onChangeText={setReply} multiline />
          <Field label="챗봇이 먼저 안내할 내용" value={faq} onChangeText={setFaq} multiline hint="고객이 요청을 넣기 전에 챗봇이 이 내용으로 먼저 답합니다" />
          <Field label="보상" value={comp} onChangeText={setComp} maxLength={100} placeholder="예: 적립금 3,000원" hint="비워 두면 추천하지 않아요. 승인을 눌러야 고객에게 갑니다" />
          <Notice text={err} flat />
          <View style={{ flexDirection: 'row', gap: 8 }}>
            <Btn title="취소" kind="gray" onPress={() => (setOpen(false), setReply(r.reply), setFaq(r.faq), setComp(r.comp ?? ''))} style={{ flex: 1 }} />
            <Btn title="저장" onPress={() => save({ reply, faq, comp })} busy={busy} style={{ flex: 2 }} />
          </View>
        </View>
      ) : (
        <View style={{ marginTop: 10, gap: 10 }}>
          <View style={st.reply}>
            <Text style={st.replyT} numberOfLines={3}>
              {r.reply}
            </Text>
          </View>
          {r.comp ? <Text style={st.p}>추천 보상: {r.comp}</Text> : null}
          <Notice text={err} flat />
          <Btn title="답변 문구 고치기" kind="gray" onPress={() => setOpen(true)} />
        </View>
      )}
    </Card>
  );
}

const st = StyleSheet.create({
  head: { paddingHorizontal: 24, paddingTop: 8, paddingBottom: 16 },
  p: { fontFamily: FONT, fontSize: 15, lineHeight: 23, color: C.fg2 },
  h2: { fontFamily: FONT, fontSize: 17, fontWeight: '700', color: C.fg, marginBottom: 12 },
  label: { fontFamily: FONT, fontSize: 14, fontWeight: '600', color: C.fg2 },
  reply: { backgroundColor: C.fill, borderRadius: 12, padding: 12 },
  replyT: { fontFamily: FONT, fontSize: 14, lineHeight: 21, color: C.fg2 },
});
