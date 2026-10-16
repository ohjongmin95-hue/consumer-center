// 답변 템플릿: 웹 '답변 템플릿'과 같은 목록. 요청 화면의 답변하기에서 골라 넣는다.
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Btn, Card, Field, Loading, Notice, Screen, SmallBtn } from '../components/ui';
import { api, Macro } from '../lib/api';
import { useAuth } from '../lib/auth';
import { C, FONT } from '../lib/theme';
import { errText, useLoad } from '../lib/useLoad';

export default function Macros() {
  const { logout } = useAuth();
  const { data, setData, err, token } = useLoad(api.macros);
  const [edit, setEdit] = useState<Partial<Macro> | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [bad, setBad] = useState('');
  if (!data) return <Screen>{err ? <Notice text={err} /> : <Loading />}</Screen>;

  const save = async (f: Parameters<typeof api.saveMacro>[1]) => {
    setBusy(true);
    setBad('');
    try {
      const d = await api.saveMacro(token, f);
      setData(d);
      setMsg(d.message ?? '');
      setEdit(null);
    } catch (e) {
      setBad(errText(e, logout));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <View style={{ flexDirection: 'row', paddingHorizontal: 16, paddingBottom: 12 }}>
        {edit ? null : <SmallBtn title="+ 새 템플릿" onPress={() => (setMsg(''), setEdit({ name: '', body: '', tags: '' }))} />}
      </View>
      <Notice text={msg} tone="ok" />
      {edit ? (
        <Card>
          <View style={{ gap: 12 }}>
            <Field label="이름" value={edit.name} onChangeText={(v) => setEdit({ ...edit, name: v })} maxLength={30} placeholder="예: 배송 지연 사과" />
            <Field label="답변 내용" value={edit.body} onChangeText={(v) => setEdit({ ...edit, body: v })} multiline maxLength={3000} />
            <View style={st.vars}>
              {data.vars.map((v) => (
                <Pressable key={v} onPress={() => setEdit({ ...edit, body: (edit.body ?? '') + v })} style={st.var}>
                  <Text style={st.varT}>{v}</Text>
                </Pressable>
              ))}
            </View>
            <Field label="자동으로 붙일 태그" value={edit.tags} onChangeText={(v) => setEdit({ ...edit, tags: v })} placeholder="쉼표로 나눠 적기 (없어도 돼요)" />
            <Notice text={bad} flat />
            <View style={{ flexDirection: 'row', gap: 8 }}>
              <Btn title="취소" kind="gray" onPress={() => (setEdit(null), setBad(''))} style={{ flex: 1 }} />
              <Btn title="저장" busy={busy} onPress={() => save({ id: edit.id, name: edit.name, body: edit.body, tags: edit.tags })} style={{ flex: 2 }} />
            </View>
            {edit.id ? <Btn title="이 템플릿 지우기" kind="danger" onPress={() => save({ id: edit.id, act: 'delete' })} /> : null}
          </View>
        </Card>
      ) : null}
      {data.macros.length ? (
        data.macros.map((m) => (
          <Card key={m.id}>
            <Pressable onPress={() => (setMsg(''), setEdit(m))} style={({ pressed }) => pressed && { opacity: 0.6 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                <Text style={st.name}>{m.name}</Text>
                <Text style={st.used}>{m.used}번 씀</Text>
              </View>
              <Text style={st.body} numberOfLines={3}>
                {m.body}
              </Text>
              {m.tags ? <Text style={st.used}># {m.tags.split(',').join(' # ')}</Text> : null}
            </Pressable>
          </Card>
        ))
      ) : edit ? null : (
        <Card style={{ alignItems: 'center', paddingVertical: 32, gap: 6 }}>
          <Text style={st.name}>아직 만든 템플릿이 없어요</Text>
          <Text style={st.used}>자주 보내는 답변을 만들어 두세요</Text>
        </Card>
      )}
    </Screen>
  );
}

const st = StyleSheet.create({
  vars: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  var: { height: 32, paddingHorizontal: 10, borderRadius: 10, backgroundColor: C.accentSoft, justifyContent: 'center' },
  varT: { fontFamily: FONT, fontSize: 13, fontWeight: '600', color: C.accentInk },
  name: { flex: 1, fontFamily: FONT, fontSize: 17, fontWeight: '700', color: C.fg, letterSpacing: -0.4 },
  used: { fontFamily: FONT, fontSize: 13, color: C.fg3, marginTop: 4 },
  body: { fontFamily: FONT, fontSize: 15, lineHeight: 22, color: C.fg2, marginTop: 8 },
});
