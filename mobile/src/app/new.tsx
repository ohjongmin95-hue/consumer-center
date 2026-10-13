// 요청 직접 등록: 전화·쇼핑몰 문의·DM으로 받은 요청을 앱에 올려 같은 방식으로 처리한다.
import { router } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Text, View } from 'react-native';
import { Btn, Card, Chips, Field, Loading, Notice, Screen } from '../components/ui';
import { api } from '../lib/api';
import { useAuth } from '../lib/auth';
import { C } from '../lib/theme';
import { errText, useLoad } from '../lib/useLoad';

export default function NewCase() {
  const { logout } = useAuth();
  const { data, err, token } = useLoad(api.newForm);
  const [f, setF] = useState({ channel: '전화', category: '', title: '', body: '', want: '', order_no: '', product: '', received_on: '', name: '', phone: '', email: '' });
  const [busy, setBusy] = useState(false);
  const [e2, setE2] = useState('');
  if (!data) return err ? <Notice text={err} /> : <Loading />;
  const set = (k: keyof typeof f) => (v: string) => setF({ ...f, [k]: v });
  const submit = async () => {
    setBusy(true);
    setE2('');
    try {
      const r = await api.newCase(token, f);
      router.replace(`/case/${r.id}`);
    } catch (e) {
      setE2(errText(e, logout));
    } finally {
      setBusy(false);
    }
  };
  const L = ({ t }: { t: string }) => <Text style={{ fontSize: 15, fontWeight: '600', color: C.fg2 }}>{t}</Text>;
  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen>
        <View style={{ paddingHorizontal: 24, paddingTop: 8, paddingBottom: 14 }}>
          <Text style={{ fontSize: 15, lineHeight: 23, color: C.fg2 }}>다른 곳으로 받은 요청도 여기 올리면 추천 처리, 답변 초안, 기록 관리를 똑같이 쓸 수 있습니다.</Text>
        </View>
        <Card style={{ gap: 12 }}>
          <L t="어디로 받았나요" />
          <Chips items={data.channels} value={f.channel} onChange={set('channel')} />
          <L t="유형" />
          <Chips items={data.cats} value={f.category} onChange={set('category')} />
          {f.category && data.hints[f.category] ? <Text style={{ fontSize: 13, color: C.fg3 }}>{data.hints[f.category]}</Text> : null}
          <L t="원하는 해결" />
          <Chips items={data.wants} value={f.want} onChange={set('want')} />
        </Card>
        <Card style={{ gap: 14 }}>
          <Field label="한 줄 요약" value={f.title} onChangeText={set('title')} placeholder="예: 받은 니트 사이즈 교환 요청" />
          <Field label="내용" value={f.body} onChangeText={set('body')} multiline placeholder="고객이 말한 내용을 적어 주세요" />
          <Field label="상품 (선택)" value={f.product} onChangeText={set('product')} />
          <Field label="주문번호 (선택)" value={f.order_no} onChangeText={set('order_no')} />
          <Field label="상품 받은 날 (선택)" value={f.received_on} onChangeText={set('received_on')} placeholder="예: 2026-10-10" keyboardType="numbers-and-punctuation" />
        </Card>
        <Card style={{ gap: 14 }}>
          <Field label="고객 이름 (선택)" value={f.name} onChangeText={set('name')} />
          <Field label="고객 연락처 (선택)" value={f.phone} onChangeText={set('phone')} keyboardType="phone-pad" />
          <Field label="고객 이메일 (선택)" value={f.email} onChangeText={set('email')} autoCapitalize="none" keyboardType="email-address" />
        </Card>
        <Notice text={e2} />
        <View style={{ marginHorizontal: 16 }}>
          <Btn title="등록하기" onPress={submit} busy={busy} />
        </View>
      </Screen>
    </KeyboardAvoidingView>
  );
}
