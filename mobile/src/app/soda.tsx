// SODA 가르치기: 웹 'SODA 가르치기'와 같다. 모르는 질문에 한 줄 답, 말·주소로 한 번에 알려 주기, 자료에서 읽은 답 확인, 배운 답 끄기.
// 사진·PDF·엑셀은 웹에서 올린다 (앱에는 아직 사진 고르기가 없다).
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Btn, Card, Field, H2, Loading, Notice, Screen, Toggle } from '../components/ui';
import { api, Soda } from '../lib/api';
import { useAuth } from '../lib/auth';
import { C, FONT } from '../lib/theme';
import { errText, useLoad } from '../lib/useLoad';

type Act = Parameters<typeof api.sodaAct>[1];

export default function SodaScreen() {
  const { logout } = useAuth();
  const { data, setData, err, token, reload } = useLoad(api.soda);
  const [ans, setAns] = useState<Record<number, string>>({});
  const [text, setText] = useState('');
  const [url, setUrl] = useState<string | null>(null);
  const [edit, setEdit] = useState<{ id: number; q: string; a: string } | null>(null);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [bad, setBad] = useState('');
  if (!data) return <Screen>{err ? <Notice text={err} /> : <Loading />}</Screen>;

  const go = async (key: string, f: Act, after?: () => void) => {
    setBusy(key);
    setBad('');
    setMsg('');
    try {
      const d: Soda = await api.sodaAct(token, f);
      setData(d);
      setMsg(d.message ?? '');
      after?.();
    } catch (e) {
      setBad(errText(e, logout));
    } finally {
      setBusy('');
    }
  };
  const u = url ?? data.url;

  return (
    <Screen onRefresh={reload}>
      <Notice text={msg} tone="ok" />
      <Notice text={bad} />
      {data.check.length ? (
        <>
          <Card>
            <H2>맞는지 확인해 주세요</H2>
            <View style={{ gap: 14 }}>
              <Text style={st.meta}>자료에서 읽은 답이에요. 틀린 건 눌러서 고치거나 지우고, 나머지는 한 번에 켜 주세요.</Text>
              {data.check.map((r) => (
                <Pressable key={r.id} onPress={() => setEdit({ id: r.id, q: r.q, a: r.a })}>
                  <Text style={st.q}>{r.q}</Text>
                  <Text style={st.a}>{r.a}</Text>
                </Pressable>
              ))}
              <Btn title="모두 맞아요, 켜기" busy={busy === 'c'} onPress={() => go('c', { act: 'check' })} />
            </View>
          </Card>
        </>
      ) : null}

      <Card>
        <H2>SODA가 몰라서 물어봐요</H2>
        {data.gaps.length ? (
          data.gaps.map((g, i) => (
            <View key={g.id} style={[{ gap: 10 }, i > 0 && st.sep]}>
              <Text style={st.q}>{g.q}</Text>
              {g.n > 1 ? <Text style={st.meta}>{g.n}번 물어봤어요</Text> : null}
              <Field value={ans[g.id] ?? ''} onChangeText={(v) => setAns({ ...ans, [g.id]: v })} placeholder="한 줄로 답해 주세요" maxLength={1000} />
              <Btn title="알려 주기" busy={busy === 'g' + g.id} disabled={!(ans[g.id] ?? '').trim()} onPress={() => go('g' + g.id, { act: 'gap', id: g.id, a: ans[g.id] })} />
              <Pressable onPress={() => go('s' + g.id, { act: 'skip', id: g.id })} hitSlop={8}>
                <Text style={st.link}>이건 넘어갈게요</Text>
              </Pressable>
            </View>
          ))
        ) : (
          <Text style={st.meta}>{data.ai ? '지금은 물어볼 게 없어요. SODA가 모르는 질문을 받으면 여기에 모아 둘게요.' : 'SODA가 켜지면 모르는 질문을 여기에 모아 둘게요.'}</Text>
        )}
      </Card>

      <Card>
        <H2>한 번에 알려 주기</H2>
        <View style={{ gap: 12 }}>
          <Field label="말로 알려 주기" value={text} onChangeText={setText} multiline maxLength={5000} placeholder="예: 평일 오후 2시 전 주문은 당일 보내요. 주말엔 쉬어요." hint="키보드의 마이크를 누르면 말로 적을 수 있어요. 직접 적은 말은 바로 배워요." />
          <Field label="쇼핑몰 주소" value={u} onChangeText={setUrl} autoCapitalize="none" keyboardType="url" maxLength={500} placeholder="예: smartstore.naver.com/우리가게" hint="주소에서 읽은 답은 확인한 뒤에 써요. 사진·PDF·엑셀은 웹에서 올릴 수 있어요." />
          <Btn title="SODA에게 알려 주기" busy={busy === 't'} disabled={!text.trim() && !u.trim()} onPress={() => go('t', { act: 'teach', text, url: text.trim() ? '' : u }, () => setText(''))} />
        </View>
      </Card>

      {edit ? (
        <Card>
          <View style={{ gap: 12 }}>
            <Field label="질문" value={edit.q} onChangeText={(v) => setEdit({ ...edit, q: v })} maxLength={200} />
            <Field label="답" value={edit.a} onChangeText={(v) => setEdit({ ...edit, a: v })} multiline maxLength={1000} />
            <Btn title="저장" busy={busy === 'e'} onPress={() => go('e', { act: 'edit', id: edit.id, q: edit.q, a: edit.a }, () => setEdit(null))} />
            <Pressable onPress={() => go('d', { act: 'del', id: edit.id }, () => setEdit(null))} hitSlop={8}>
              <Text style={[st.link, { color: C.red }]}>이 답 지우기</Text>
            </Pressable>
          </View>
        </Card>
      ) : null}

      <Card>
        <H2>SODA가 배운 답</H2>
        {data.kb.length ? (
          data.kb.map((r, i) => (
            <View key={r.id} style={[st.row, i > 0 && st.line]}>
              <Pressable style={{ flex: 1 }} onPress={() => setEdit({ id: r.id, q: r.q, a: r.a })}>
                <Toggle title={r.q} sub={r.a} value={!!r.on} onChange={(v) => go('k' + r.id, { act: 'toggle', id: r.id, on: v })} />
              </Pressable>
            </View>
          ))
        ) : (
          <Text style={st.meta}>아직 배운 답이 없어요. 고객에게 직접 답을 보내면 '다음에도 이렇게 답하기'가 떠요.</Text>
        )}
      </Card>
    </Screen>
  );
}

const st = StyleSheet.create({
  q: { fontFamily: FONT, fontSize: 16, fontWeight: '700', color: C.fg },
  a: { fontFamily: FONT, fontSize: 15, lineHeight: 22, color: C.fg2, marginTop: 4 },
  meta: { fontFamily: FONT, fontSize: 14, lineHeight: 20, color: C.fg3 },
  link: { fontFamily: FONT, fontSize: 14, fontWeight: '600', color: C.fg3 },
  row: { paddingVertical: 4 },
  sep: { marginTop: 18, paddingTop: 18, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: C.line },
  line: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: C.line },
});
