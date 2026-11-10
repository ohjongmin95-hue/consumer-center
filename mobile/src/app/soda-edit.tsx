// SODA 가르치기에서 한 가지만 하는 화면 (토스처럼: 큰 질문 제목, 칸 하나, 아래 꽉 찬 버튼 하나).
// mode: gap(모르는 질문에 답) · edit(배운 답 고치기) · text(말로 알려 주기) · url(쇼핑몰 주소)
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { api } from '../lib/api';
import { useAuth } from '../lib/auth';
import { C, FONT } from '../lib/theme';
import { errText } from '../lib/useLoad';

const COPY: Record<string, { eyebrow: string; title?: string; cta: string; ph: string }> = {
  gap: { eyebrow: '고객이 물었어요', cta: '알려 주기', ph: '한 줄로 답해 주세요' },
  edit: { eyebrow: '배운 답 고치기', cta: '저장하기', ph: '답' },
  text: { eyebrow: '말로 알려 주기', title: 'SODA에게 무엇을\n알려 줄까요?', cta: 'SODA에게 알려 주기', ph: '예: 평일 오후 2시 전 주문은 당일 보내요. 주말엔 쉬어요.' },
  url: { eyebrow: '쇼핑몰 주소로 알려 주기', title: '쇼핑몰 주소를\n알려 주세요', cta: '읽어 보기', ph: 'smartstore.naver.com/우리가게' },
};

export default function SodaEdit() {
  const p = useLocalSearchParams<{ mode: string; id?: string; q?: string; a?: string; url?: string }>();
  const mode = COPY[p.mode] ? p.mode : 'text';
  const copy = COPY[mode];
  const { session, logout } = useAuth();
  const [q, setQ] = useState(p.q ?? '');
  const [v, setV] = useState(mode === 'edit' ? p.a ?? '' : mode === 'url' ? p.url ?? '' : '');
  const [busy, setBusy] = useState('');
  const [bad, setBad] = useState('');
  const id = Number(p.id || 0);

  const run = async (key: string, f: Parameters<typeof api.sodaAct>[1]) => {
    if (!session) return;
    setBusy(key);
    setBad('');
    try {
      await api.sodaAct(session.token, f);
      router.back();
    } catch (e) {
      setBad(errText(e, logout));
    } finally {
      setBusy('');
    }
  };
  const save = () =>
    mode === 'gap' ? run('save', { act: 'gap', id, a: v }) : mode === 'edit' ? run('save', { act: 'edit', id, q, a: v }) : mode === 'url' ? run('save', { act: 'teach', url: v }) : run('save', { act: 'teach', text: v });
  const ready = v.trim().length > 0 && (mode !== 'edit' || q.trim().length > 0);

  return (
    <SafeAreaView style={st.page} edges={['bottom']}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={{ paddingBottom: 24 }} keyboardShouldPersistTaps="handled">
          <Text style={st.eyebrow}>{copy.eyebrow}</Text>
          {mode === 'edit' ? (
            <TextInput value={q} onChangeText={setQ} style={st.titleInput} multiline maxLength={200} placeholder="질문" placeholderTextColor={C.fg4} />
          ) : (
            <Text style={st.title}>{copy.title ?? p.q}</Text>
          )}
          <TextInput
            value={v}
            onChangeText={setV}
            placeholder={copy.ph}
            placeholderTextColor={C.fg4}
            multiline={mode !== 'url'}
            autoFocus={mode !== 'edit'}
            autoCapitalize="none"
            keyboardType={mode === 'url' ? 'url' : 'default'}
            maxLength={mode === 'text' ? 5000 : 1000}
            style={[st.input, mode !== 'url' && st.area]}
          />
          {mode === 'text' ? <Text style={st.hint}>키보드의 마이크를 누르면 말로 적을 수 있어요</Text> : null}
          {mode === 'url' ? <Text style={st.hint}>읽은 답은 '맞는지 확인해 주세요'에 모여요. 확인한 뒤에 SODA가 써요</Text> : null}
          {bad ? <Text style={[st.hint, { color: C.red }]}>{bad}</Text> : null}
          {mode === 'gap' ? (
            <Pressable onPress={() => run('skip', { act: 'skip', id })} hitSlop={8} style={st.textBtn}>
              <Text style={st.textBtnT}>이건 넘어갈게요</Text>
            </Pressable>
          ) : null}
          {mode === 'edit' ? (
            <Pressable onPress={() => run('del', { act: 'del', id })} hitSlop={8} style={st.textBtn}>
              <Text style={[st.textBtnT, { color: C.red }]}>이 답 지우기</Text>
            </Pressable>
          ) : null}
        </ScrollView>
        <View style={st.bottom}>
          <Pressable onPress={save} disabled={!ready || !!busy} style={({ pressed }) => [st.cta, (!ready || !!busy) && { opacity: 0.4 }, pressed && { backgroundColor: C.accentPress }]}>
            <Text style={st.ctaText}>{busy === 'save' ? (mode === 'url' ? '읽는 중…' : '보내는 중…') : copy.cta}</Text>
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

// TDS: 옆 여백 24, 제목 26/35, 칸은 회색 채움, 아래 버튼 옆 20·높이 56·둥글기 16·아래 20
const st = StyleSheet.create({
  page: { flex: 1, backgroundColor: C.card },
  eyebrow: { fontFamily: FONT, fontSize: 14, lineHeight: 21, fontWeight: '600', color: C.accentInk, paddingHorizontal: 24, paddingTop: 20 },
  title: { fontFamily: FONT, fontSize: 22, lineHeight: 31, fontWeight: '700', color: C.fg, letterSpacing: 0, paddingHorizontal: 24, paddingTop: 6, paddingBottom: 24 },
  titleInput: { fontFamily: FONT, fontSize: 20, lineHeight: 29, fontWeight: '700', color: C.fg, letterSpacing: 0, marginHorizontal: 24, marginTop: 6, marginBottom: 20, paddingVertical: 6, borderBottomWidth: 2, borderBottomColor: C.line },
  input: { marginHorizontal: 24, minHeight: 52, borderRadius: 14, backgroundColor: C.fill, paddingHorizontal: 16, paddingVertical: 14, fontFamily: FONT, fontSize: 16, lineHeight: 24, color: C.fg },
  area: { minHeight: 140, textAlignVertical: 'top' },
  hint: { fontFamily: FONT, fontSize: 13, lineHeight: 19.5, color: C.fg3, paddingHorizontal: 24, paddingTop: 10 },
  textBtn: { alignSelf: 'flex-start', marginLeft: 24, marginTop: 20, paddingVertical: 6 },
  textBtnT: { fontFamily: FONT, fontSize: 14, fontWeight: '600', color: '#6B7684' },
  bottom: { paddingHorizontal: 20, paddingBottom: 20, paddingTop: 8, backgroundColor: C.card },
  cta: { height: 54, borderRadius: 16, backgroundColor: C.accent, alignItems: 'center', justifyContent: 'center' },
  ctaText: { fontFamily: FONT, fontSize: 16, fontWeight: '700', color: '#fff', letterSpacing: 0 },
});
