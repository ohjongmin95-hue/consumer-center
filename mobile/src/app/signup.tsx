// 가입 신청: 웹과 같은 항목. 신청하면 운영팀이 확인하고 승인 메일을 보낸다.
import { router } from 'expo-router';
import { useState } from 'react';
import * as WebBrowser from 'expo-web-browser';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Btn, Card, Chips, Field, Notice, PwField } from '../components/ui';
import { api, SITE_BASE } from '../lib/api';
import { useAuth } from '../lib/auth';
import { C } from '../lib/theme';

const FALLBACK_IND = ['패션·잡화', '뷰티', '식품', '생활·주방', '가전·디지털', '가구·인테리어', '유아·출산', '스포츠·레저', '반려동물', '도서·문구', '서비스', '기타'];

export default function Signup() {
  const { meta } = useAuth();
  const [f, setF] = useState({ name: '', biz_no: '', owner_name: '', phone: '', login_id: '', password: '', contact: '', industry: '' });
  const [terms, setTerms] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [done, setDone] = useState('');
  const set = (k: keyof typeof f) => (v: string) => setF({ ...f, [k]: v });

  const submit = async () => {
    setBusy(true);
    setErr('');
    try {
      const r = await api.signup({ ...f, terms: terms ? '1' : '' });
      setDone(r.name);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (done)
    return (
      <View style={{ flex: 1, backgroundColor: C.card, padding: 24, paddingTop: 48, gap: 14 }}>
        <Text style={st.big}>🎉</Text>
        <Text style={st.h1}>가입 신청을 받았습니다</Text>
        <Text style={st.p}>
          {done}의 신청을 운영팀이 확인하고 있습니다. 승인되면 {f.login_id}로 메일을 보내 드리고, 그때부터 이 앱에 로그인할 수 있습니다.
        </Text>
        <Btn title="로그인 화면으로" onPress={() => router.back()} style={{ marginTop: 12 }} />
      </View>
    );

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={{ paddingBottom: 40 }} keyboardShouldPersistTaps="handled">
        <View style={{ paddingHorizontal: 24, paddingTop: 8, paddingBottom: 18, gap: 8 }}>
          <Text style={st.h1}>소보루 CS 가입 신청</Text>
          <Text style={st.p}>신청하면 운영팀이 사업자 정보를 확인하고 승인합니다. 무료로 시작할 수 있습니다.</Text>
        </View>
        <Card style={{ gap: 14 }}>
          <Field label="회사 이름" value={f.name} onChangeText={set('name')} placeholder="예: 달빛화장품" />
          <Field label="사업자등록번호" value={f.biz_no} onChangeText={set('biz_no')} placeholder="숫자 10자리" keyboardType="number-pad" maxLength={12} />
          <Field label="대표자 이름" value={f.owner_name} onChangeText={set('owner_name')} />
          <Field label="휴대폰 번호" value={f.phone} onChangeText={set('phone')} placeholder="승인 안내와 알림용" keyboardType="phone-pad" />
          <View style={{ gap: 8 }}>
            <Text style={st.label}>업종</Text>
            <Chips items={meta?.industries ?? FALLBACK_IND} value={f.industry} onChange={set('industry')} />
          </View>
        </Card>
        <Card style={{ gap: 14 }}>
          <Field label="로그인 이메일" value={f.login_id} onChangeText={set('login_id')} autoCapitalize="none" keyboardType="email-address" autoComplete="email" />
          <PwField label="비밀번호" value={f.password} onChangeText={set('password')} hint="10자 이상" autoComplete="new-password" />
          <Field label="고객에게 안내할 연락처 (선택)" value={f.contact} onChangeText={set('contact')} placeholder="예: 02-123-4567 또는 카카오톡 채널" />
        </Card>
        <Pressable onPress={() => setTerms(!terms)} style={st.agree} accessibilityRole="checkbox" accessibilityState={{ checked: terms }}>
          <View style={[st.box, terms && { backgroundColor: C.accent, borderColor: C.accent }]}>{terms ? <Text style={{ color: '#fff', fontWeight: '800' }}>✓</Text> : null}</View>
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={{ fontSize: 16, fontWeight: '700', color: C.fg }}>
              이용약관 동의 (필수){'  '}
              <Text onPress={() => WebBrowser.openBrowserAsync(SITE_BASE + '/terms')} style={{ fontSize: 14, fontWeight: '600', color: C.fg3, textDecorationLine: 'underline' }} accessibilityRole="link">보기</Text>
            </Text>
            <Text style={{ fontSize: 13, color: C.fg3 }}>가입 여부는 소비자 민원 처리 결과에 영향을 주지 않습니다</Text>
          </View>
        </Pressable>
        <Notice text={err} />
        <View style={{ marginHorizontal: 16 }}>
          <Btn title="가입 신청하기" onPress={submit} busy={busy} disabled={!terms} />
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const st = StyleSheet.create({
  h1: { fontSize: 24, lineHeight: 33, fontWeight: '700', color: C.fg, letterSpacing: -0.8 },
  p: { fontSize: 15, lineHeight: 23, color: C.fg3 },
  big: { fontSize: 44 },
  label: { fontSize: 15, fontWeight: '600', color: C.fg2 },
  agree: { flexDirection: 'row', gap: 12, alignItems: 'center', marginHorizontal: 16, marginBottom: 12, backgroundColor: C.card, borderRadius: 20, padding: 18 },
  box: { width: 26, height: 26, borderRadius: 8, borderWidth: 2, borderColor: C.line, alignItems: 'center', justifyContent: 'center' },
});
