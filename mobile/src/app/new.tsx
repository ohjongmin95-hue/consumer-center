// 민원 접수: 웹 접수(c_new.html)처럼 한 화면에 질문 하나씩, 다섯 단계
import * as ImagePicker from 'expo-image-picker';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Image, KeyboardAvoidingView, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { CATS } from '../components/CatGrid';
import { CAT_ICON, Icon } from '../components/Icon';
import { Btn, Field, Notice } from '../components/ui';
import { api, Photo } from '../lib/api';
import { useStore } from '../lib/store';
import { C, R } from '../lib/theme';

const WANTS: [string, string][] = [['교환', 'exchange'], ['환불', 'refund'], ['배송 확인', 'truck'], ['사과·재발 방지', 'chat'], ['수리·A/S', 'shield'], ['기타', 'note']];
const WANT_FOR: Record<string, string> = { '반품·환불': '환불', 교환: '교환', '배송 조회': '배송 확인', '고객 응대': '사과·재발 방지' };
const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

export default function NewCase() {
  const p = useLocalSearchParams<{ company?: string; company_id?: string; category?: string; body?: string }>();
  const { addTokens, meta } = useStore();
  const [step, setStep] = useState(p.company || p.company_id ? 1 : 0);
  const [f, setF] = useState({
    company: p.company ?? '',
    company_id: p.company_id ?? '',
    category: p.category && CATS.includes(p.category) ? p.category : '',
    title: p.body ? p.body.split('\n')[0].slice(0, 80) : '',
    body: p.body ?? '',
    order_no: '',
    product: '',
    received_on: '',
    want: p.category ? WANT_FOR[p.category] ?? '' : '',
    name: '',
    phone: '',
    password: '',
    email: '',
  });
  const [consent, setConsent] = useState(true);
  const [privacy, setPrivacy] = useState(false);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (v: string) => setF((o) => ({ ...o, [k]: v }));

  // 기업 고객센터에서 왔으면 기업 이름을 채운다
  useEffect(() => {
    if (p.company_id && !p.company) api.company(Number(p.company_id)).then((c) => setF((o) => ({ ...o, company: c.name }))).catch(() => {});
  }, [p.company_id, p.company]);
  // 유형을 고르면 원하는 해결을 미리 골라 둔다
  useEffect(() => {
    if (f.category && !f.want && WANT_FOR[f.category]) setF((o) => ({ ...o, want: WANT_FOR[o.category] }));
  }, [f.category, f.want]);

  const needDate = f.category === '교환' || f.category === '반품·환불';
  const check = (): string => {
    if (step === 0 && !f.company.trim()) return '기업 이름을 적어 주세요.';
    if (step === 1 && !f.category) return '어떤 일인지 골라 주세요.';
    if (step === 2) {
      if (!f.title.trim()) return '한 줄 요약을 적어 주세요.';
      if (f.body.trim().length < 10) return '자세한 내용을 10자 이상 적어 주세요.';
      if (needDate && !/^\d{4}-\d{2}-\d{2}$/.test(f.received_on)) return '상품 받은 날을 알려 주세요. 교환·반품 기간(7일) 확인에 써요.';
    }
    if (step === 3 && !f.want) return '원하는 해결을 골라 주세요.';
    if (step === 4) {
      const d = f.phone.replace(/\D/g, '');
      if (d.length < 10 || d.length > 11) return '휴대폰 번호를 정확히 적어 주세요. 내 민원을 찾을 때 써요.';
      if (f.password.length < 4) return '조회 비밀번호를 4자 이상 정해 주세요.';
      if (!privacy) return '개인정보 수집·이용에 동의해야 접수할 수 있어요.';
    }
    return '';
  };

  const pick = async () => {
    const max = meta?.max_files ?? 3;
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], allowsMultipleSelection: true, selectionLimit: max - photos.length, quality: 0.7 });
    if (r.canceled) return;
    const add = r.assets.map((a, i) => ({ uri: a.uri, name: a.fileName ?? `photo${Date.now()}${i}.jpg`, type: a.mimeType ?? 'image/jpeg' }));
    setPhotos((ps) => [...ps, ...add].slice(0, max));
  };

  const next = async () => {
    const e = check();
    setErr(e);
    if (e) return;
    if (step < 4) return setStep(step + 1);
    setBusy(true);
    try {
      const r = await api.submit(
        {
          ...f,
          company_id: f.company_id,
          consent: consent ? '1' : '',
          privacy: '1',
        },
        photos,
      );
      await addTokens([r.token]);
      router.replace({ pathname: '/case/[id]', params: { id: String(r.id), done: '1' } });
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.card }} edges={['bottom']}>
      <Stack.Screen options={{ title: `${step + 1} / 5` }} />
      <View style={st.bar}>
        <View style={[st.barOn, { width: `${((step + 1) / 5) * 100}%` }]} />
      </View>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={st.body} keyboardShouldPersistTaps="handled">
          {step === 0 && (
            <>
              <Text style={st.h1}>어느 기업인가요?</Text>
              <Field value={f.company} onChangeText={(v) => setF((o) => ({ ...o, company: v, company_id: '' }))} placeholder="기업이나 쇼핑몰 이름" maxLength={60} autoFocus style={st.big} />
            </>
          )}
          {step === 1 && (
            <>
              <Text style={st.h1}>어떤 일인가요?</Text>
              <View style={{ gap: 10 }}>
                {CATS.map((c) => (
                  <Opt key={c} icon={CAT_ICON[c]} label={c} on={f.category === c} onPress={() => setF((o) => ({ ...o, category: c, want: WANT_FOR[c] ?? o.want }))} />
                ))}
              </View>
            </>
          )}
          {step === 2 && (
            <>
              <Text style={st.h1}>무슨 일이 있었나요?</Text>
              <View style={{ gap: 12 }}>
                <Field value={f.title} onChangeText={set('title')} placeholder="한 줄 요약" />
                <Field value={f.body} onChangeText={set('body')} placeholder="언제, 무엇을 샀고, 어떤 문제가 있었는지" multiline />
                <Field value={f.order_no} onChangeText={set('order_no')} placeholder="주문번호 (선택)" maxLength={40} />
                <Field value={f.product} onChangeText={set('product')} placeholder="상품 이름 (선택)" maxLength={60} />
                <Field
                  label={needDate ? '상품 받은 날' : '상품 받은 날 (선택 · 반품 기간 확인에 써요)'}
                  value={f.received_on}
                  onChangeText={set('received_on')}
                  placeholder="예: 2026-10-07"
                  keyboardType="numbers-and-punctuation"
                  maxLength={10}
                />
                <View style={{ flexDirection: 'row', gap: 8 }}>
                  {[['오늘', 0], ['어제', 1], ['그저께', 2]].map(([l, n]) => (
                    <Pressable key={l} onPress={() => set('received_on')(ymd(new Date(Date.now() - Number(n) * 864e5)))} style={st.mini}>
                      <Text style={st.miniT}>{l}</Text>
                    </Pressable>
                  ))}
                </View>
                {Platform.OS !== 'web' && (
                  <View style={{ gap: 10 }}>
                    <Text style={st.label}>사진 (선택, {meta?.max_files ?? 3}개까지)</Text>
                    <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
                      {photos.map((ph, i) => (
                        <Pressable key={ph.uri} onPress={() => setPhotos(photos.filter((_, j) => j !== i))}>
                          <Image source={{ uri: ph.uri }} style={st.thumb} />
                        </Pressable>
                      ))}
                      {photos.length < (meta?.max_files ?? 3) && (
                        <Pressable onPress={pick} style={[st.thumb, st.add]}>
                          <Text style={{ fontSize: 28, color: C.fg3 }}>+</Text>
                        </Pressable>
                      )}
                    </View>
                  </View>
                )}
              </View>
            </>
          )}
          {step === 3 && (
            <>
              <Text style={st.h1}>어떻게 해결되면{'\n'}좋을까요?</Text>
              <View style={{ gap: 10 }}>
                {WANTS.map(([w, ic]) => (
                  <Opt key={w} icon={ic} label={w} on={f.want === w} onPress={() => set('want')(w)} />
                ))}
              </View>
            </>
          )}
          {step === 4 && (
            <>
              <Text style={st.h1}>답변 받을 연락처를{'\n'}알려 주세요</Text>
              <View style={{ gap: 14 }}>
                <Field label="이름" value={f.name} onChangeText={set('name')} maxLength={20} />
                <Field label="휴대폰 번호" value={f.phone} onChangeText={set('phone')} placeholder="010-0000-0000" keyboardType="phone-pad" maxLength={20} />
                <Field label="조회 비밀번호 (4자 이상)" value={f.password} onChangeText={set('password')} secureTextEntry maxLength={40} />
                <Field label="이메일 (선택 · 답변 알림)" value={f.email} onChangeText={set('email')} keyboardType="email-address" autoCapitalize="none" maxLength={80} />
                <Check on={consent} onPress={() => setConsent(!consent)} title="기업에 전달 동의" sub="동의하지 않으면 접수만 돼요" />
                <Check on={privacy} onPress={() => setPrivacy(!privacy)} title="개인정보 수집·이용 동의 (필수)" sub="내용 보기" onSub={() => meta && Linking.openURL(meta.privacy_url)} />
              </View>
            </>
          )}
        </ScrollView>
        {!!err && <Notice text={err} />}
        <View style={st.cta}>
          {step > 0 && <Btn title="이전" kind="gray" onPress={() => (setErr(''), setStep(step - 1))} style={{ flex: 1 }} />}
          <Btn title={step < 4 ? '다음' : '접수하기'} onPress={next} busy={busy} style={{ flex: 2 }} />
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Opt({ icon, label, on, onPress }: { icon: string; label: string; on: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[st.opt, on && { borderColor: C.accent, backgroundColor: C.accentSoft }]}>
      <Icon name={icon} size={30} />
      <Text style={[st.optT, on && { color: C.accentInk }]}>{label}</Text>
    </Pressable>
  );
}
function Check({ on, onPress, title, sub, onSub }: { on: boolean; onPress: () => void; title: string; sub: string; onSub?: () => void }) {
  return (
    <Pressable onPress={onPress} style={st.check}>
      <View style={[st.box, on && { backgroundColor: C.accent, borderColor: C.accent }]}>{on && <Text style={{ color: '#fff', fontWeight: '800' }}>✓</Text>}</View>
      <View style={{ flex: 1 }}>
        <Text style={st.checkT}>{title}</Text>
        <Text style={[st.checkS, onSub && { textDecorationLine: 'underline' }]} onPress={onSub}>
          {sub}
        </Text>
      </View>
    </Pressable>
  );
}

const st = StyleSheet.create({
  bar: { height: 3, backgroundColor: C.fill },
  barOn: { height: 3, backgroundColor: C.accent },
  body: { padding: 20, paddingBottom: 32 },
  h1: { fontSize: 26, lineHeight: 36, fontWeight: '700', color: C.fg, letterSpacing: -0.8, marginTop: 8, marginBottom: 28 },
  big: { height: 60, fontSize: 18 },
  label: { fontSize: 15, fontWeight: '600', color: C.fg2 },
  opt: { flexDirection: 'row', alignItems: 'center', gap: 14, height: 64, paddingHorizontal: 18, borderRadius: R.md, borderWidth: 1.5, borderColor: C.line },
  optT: { fontSize: 17, fontWeight: '600', color: C.fg },
  mini: { height: 34, paddingHorizontal: 14, borderRadius: 17, backgroundColor: C.fill, justifyContent: 'center' },
  miniT: { fontSize: 14, fontWeight: '600', color: C.fg2 },
  thumb: { width: 76, height: 76, borderRadius: 14 },
  add: { backgroundColor: C.fill, alignItems: 'center', justifyContent: 'center' },
  check: { flexDirection: 'row', gap: 12, alignItems: 'flex-start', paddingVertical: 4 },
  box: { width: 24, height: 24, borderRadius: 8, borderWidth: 1.5, borderColor: C.fg4, alignItems: 'center', justifyContent: 'center', marginTop: 1 },
  checkT: { fontSize: 16, fontWeight: '700', color: C.fg },
  checkS: { fontSize: 13, color: C.fg3, marginTop: 2 },
  cta: { flexDirection: 'row', gap: 10, paddingHorizontal: 20, paddingTop: 8, paddingBottom: 12 },
});
