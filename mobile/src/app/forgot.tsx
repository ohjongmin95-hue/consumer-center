// 비밀번호 찾기: 로그인 이메일로 재설정 링크를 보낸다.
import { router } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Btn, Field, Notice } from '../components/ui';
import { api } from '../lib/api';
import { useAuth } from '../lib/auth';
import { C, FONT } from '../lib/theme';

export default function Forgot() {
  const { lastId } = useAuth();
  const [id, setId] = useState(lastId);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const submit = async () => {
    if (!id.trim()) return setErr('로그인 이메일을 적어 주세요.');
    setBusy(true);
    setErr('');
    try {
      setOk((await api.forgot(id.trim())).message);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <View style={{ flex: 1, backgroundColor: C.card, paddingTop: 8 }}>
      <View style={{ paddingHorizontal: 24, gap: 8, marginBottom: 24 }}>
        <Text style={st.h1}>비밀번호 찾기</Text>
        <Text style={st.p}>가입한 이메일로 비밀번호를 새로 정하는 링크를 보내 드립니다. 링크는 1시간 동안 열립니다.</Text>
      </View>
      <View style={{ paddingHorizontal: 24, gap: 12 }}>
        <Field placeholder="로그인 이메일" value={id} onChangeText={setId} autoCapitalize="none" keyboardType="email-address" autoComplete="email" onSubmitEditing={submit} />
      </View>
      <View style={{ marginTop: 12 }}>
        <Notice text={err} />
        <Notice text={ok} tone="ok" />
      </View>
      <View style={{ paddingHorizontal: 24 }}>{ok ? <Btn title="로그인 화면으로" onPress={() => router.back()} /> : <Btn title="재설정 메일 받기" onPress={submit} busy={busy} />}</View>
    </View>
  );
}

const st = StyleSheet.create({
  h1: { fontFamily: FONT, fontSize: 24, fontWeight: '700', color: C.fg, letterSpacing: -0.8 },
  p: { fontFamily: FONT, fontSize: 15, lineHeight: 23, color: C.fg3 },
});
