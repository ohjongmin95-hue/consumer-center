import { Redirect, router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Image, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Footer } from '../components/Footer';
import { Btn, Field, Notice, PwField } from '../components/ui';
import { useAuth } from '../lib/auth';
import { C } from '../lib/theme';

export default function Login() {
  const { session, login, lastId } = useAuth();
  const [id, setId] = useState('');
  useEffect(() => {
    if (lastId) setId((v) => v || lastId);
  }, [lastId]);
  const [pw, setPw] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  if (session) return <Redirect href="/" />;

  const submit = async () => {
    if (!id.trim() || !pw) return setErr('이메일과 비밀번호를 입력해 주세요.');
    setBusy(true);
    setErr('');
    try {
      await login(id.trim(), pw);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.card }} edges={['top', 'bottom']}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={{ flexGrow: 1 }} keyboardShouldPersistTaps="handled">
          <View style={st.top}>
            <View style={st.logo}>
              <Image source={require('../../assets/soboru-char.png')} style={{ width: 44, height: 34 }} resizeMode="contain" />
              <Text style={st.wm}>소보루 CS</Text>
            </View>
            <Text style={st.h1}>
              고객 응대는 <Text style={{ color: C.accent }}>소보루</Text>가,{'\n'}사장님은 확인만
            </Text>
            <Text style={st.sub}>반복되는 문의는 소보루가 대신 처리합니다.{'\n'}판단이 필요한 민원만 승인해 주세요.</Text>
          </View>
          <View style={st.form}>
            <Field placeholder="로그인 이메일" value={id} onChangeText={setId} autoCapitalize="none" autoComplete="email" keyboardType="email-address" textContentType="username" />
            <PwField placeholder="비밀번호" value={pw} onChangeText={setPw} autoComplete="password" textContentType="password" onSubmitEditing={submit} returnKeyType="go" />
            {err ? <Notice text={err} /> : null}
            <Btn title="로그인" onPress={submit} busy={busy} style={{ marginTop: 4 }} />
            <View style={st.links}>
              <Pressable onPress={() => router.push('/forgot')}>
                <Text style={st.link}>비밀번호 찾기</Text>
              </Pressable>
              <Text style={st.dot}>·</Text>
              <Pressable onPress={() => router.push('/signup')}>
                <Text style={[st.link, { color: C.accentInk }]}>가입 신청하기</Text>
              </Pressable>
            </View>
          </View>
          <View style={{ flex: 1 }} />
          <Footer />
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  top: { paddingHorizontal: 24, paddingTop: 28, gap: 14 },
  logo: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 18 },
  wm: { fontSize: 22, fontWeight: '800', color: C.accent, letterSpacing: -0.8 },
  h1: { fontSize: 28, lineHeight: 38, fontWeight: '700', color: C.fg, letterSpacing: -0.9 },
  sub: { fontSize: 15, lineHeight: 23, color: C.fg3 },
  form: { paddingHorizontal: 24, paddingTop: 32, gap: 12 },
  links: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 10, marginTop: 8 },
  link: { fontSize: 14, fontWeight: '600', color: C.fg3, paddingVertical: 6 },
  dot: { color: C.fg4 },
});
