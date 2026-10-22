import { Redirect, router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Image, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Footer } from '../components/Footer';
import { Btn, Field, Notice, PwField } from '../components/ui';
import { useAuth } from '../lib/auth';
import { C, FONT } from '../lib/theme';

export default function Login() {
  const { ready, session, meta, login, guest, lastId, stayOnLogin } = useAuth();
  const [id, setId] = useState('');
  useEffect(() => {
    if (lastId) setId((v) => v || lastId);
  }, [lastId]);
  const [pw, setPw] = useState('');
  const [busy, setBusy] = useState(false);
  const [tour, setTour] = useState(false);
  const [err, setErr] = useState('');
  const [autoTried, setAutoTried] = useState(false);
  // 비공개 테스트 동안(서버 auto_guest): 앱을 열면 로그인 없이 견본 상점으로 바로 들어간다. 로그아웃하면 이 화면에 머문다
  const auto = !!meta?.auto_guest && ready && !session && !stayOnLogin && !autoTried;
  useEffect(() => {
    if (!auto) return;
    setAutoTried(true);
    browse();
  }, [auto]); // eslint-disable-line react-hooks/exhaustive-deps
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

  // 로그인 없이 둘러보기: 견본 상점으로 화면을 미리 써 본다
  const browse = async () => {
    setTour(true);
    setErr('');
    try {
      await guest();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setTour(false);
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
            <Text style={st.sub}>반복되는 문의는 소보루가 대신 처리합니다.{'\n'}판단이 필요한 요청만 승인해 주세요.</Text>
          </View>
          <View style={st.form}>
            <Field placeholder="로그인 이메일" value={id} onChangeText={setId} autoCapitalize="none" autoComplete="email" keyboardType="email-address" textContentType="username" />
            <PwField placeholder="비밀번호" value={pw} onChangeText={setPw} autoComplete="password" textContentType="password" onSubmitEditing={submit} returnKeyType="go" />
            {err ? <Notice text={err} /> : null}
            <Btn title="로그인" onPress={submit} busy={busy} disabled={tour} style={{ marginTop: 4 }} />
            <Btn title="로그인 없이 둘러보기" kind="soft" onPress={browse} busy={tour} disabled={busy} />
            <Text style={st.cap}>견본 상점으로 미리 써 볼 수 있어요</Text>
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
  wm: { fontFamily: FONT, fontSize: 22, fontWeight: '800', color: C.brand, letterSpacing: -0.8 },
  h1: { fontFamily: FONT, fontSize: 28, lineHeight: 38, fontWeight: '700', color: C.fg, letterSpacing: -0.9 },
  sub: { fontFamily: FONT, fontSize: 15, lineHeight: 23, color: C.fg3 },
  form: { paddingHorizontal: 24, paddingTop: 32, gap: 12 },
  links: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 10, marginTop: 8 },
  link: { fontFamily: FONT, fontSize: 14, fontWeight: '600', color: C.fg3, paddingVertical: 6 },
  dot: { color: C.fg4 },
  cap: { fontFamily: FONT, fontSize: 13, color: C.fg3, textAlign: 'center', marginTop: -4 },
});
