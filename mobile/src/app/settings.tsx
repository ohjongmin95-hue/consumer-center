// 회사 정보와 알림 설정: 웹 설정 화면의 네 묶음(회사 정보·반품 안내·알림·비밀번호)을 그대로.
import { router } from 'expo-router';
import { ReactNode, useEffect, useState } from 'react';
import { Text, View } from 'react-native';
import { Btn, Card, Chips, Field, H2, Loading, Notice, PwField, Screen, Toggle } from '../components/ui';
import { api, Settings } from '../lib/api';
import { useAuth } from '../lib/auth';
import { C, FONT } from '../lib/theme';
import { errText, useLoad } from '../lib/useLoad';

export default function SettingsScreen() {
  const { data, setData, err } = useLoad(api.settings);
  if (!data) return err ? <Notice text={err} /> : <Loading />;
  return (
    <Screen>
      <Info s={data} onSaved={setData} />
      <Return s={data} onSaved={setData} />
      <Notify s={data} onSaved={setData} />
      <Password />
      <View style={{ marginHorizontal: 16, marginTop: 4 }}>
        <Btn title="회원 탈퇴" kind="gray" onPress={() => router.push('/leave')} />
      </View>
    </Screen>
  );
}

// 묶음마다 저장 버튼과 결과 문구
function useSave(onSaved?: (s: Settings) => void) {
  const { session, logout, setToken } = useAuth();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState({ t: '', ok: false });
  const save = async (f: Record<string, string | boolean>) => {
    if (!session) return false;
    setBusy(true);
    setMsg({ t: '', ok: false });
    try {
      const s = await api.saveSettings(session.token, f);
      if (s.token) await setToken(s.token);
      onSaved?.(s);
      setMsg({ t: s.message ?? '저장했습니다', ok: true });
      return true;
    } catch (e) {
      setMsg({ t: errText(e, logout), ok: false });
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { busy, msg, save };
}

function Section({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return (
    <Card style={{ gap: 14 }}>
      <View style={{ gap: 4 }}>
        <H2>{title}</H2>
        {sub ? <Text style={{ fontFamily: FONT, fontSize: 14, lineHeight: 21, color: C.fg3, marginTop: -10 }}>{sub}</Text> : null}
      </View>
      {children}
    </Card>
  );
}
const Label = ({ children }: { children: ReactNode }) => <Text style={{ fontFamily: FONT, fontSize: 15, fontWeight: '600', color: C.fg2 }}>{children}</Text>;

function Info({ s, onSaved }: { s: Settings; onSaved: (s: Settings) => void }) {
  const [f, setF] = useState({ contact: s.contact, notify_email: s.notify_email, industry: s.industry, tone: s.tone });
  const { busy, msg, save } = useSave(onSaved);
  const toneLabel = s.tones.find((t) => t.value === f.tone)?.label ?? '';
  return (
    <Section title="회사 정보" sub={`${s.name} · ${s.login_id}`}>
      <Field label="고객에게 안내할 연락처" value={f.contact} onChangeText={(v) => setF({ ...f, contact: v })} placeholder="예: 02-123-4567" />
      <Field label="알림 받을 이메일" value={f.notify_email} onChangeText={(v) => setF({ ...f, notify_email: v })} autoCapitalize="none" keyboardType="email-address" />
      <Label>업종</Label>
      <Chips items={s.industries} value={f.industry} onChange={(v) => setF({ ...f, industry: v })} />
      <Label>답변 말투</Label>
      <Chips items={s.tones.map((t) => t.label)} value={toneLabel} onChange={(l) => setF({ ...f, tone: s.tones.find((t) => t.label === l)?.value ?? 'polite' })} />
      {msg.t ? <Notice text={msg.t} tone={msg.ok ? 'ok' : 'error'} flat /> : null}
      <Btn title="저장" onPress={() => save(f)} busy={busy} />
    </Section>
  );
}

function Return({ s, onSaved }: { s: Settings; onSaved: (s: Settings) => void }) {
  const [f, setF] = useState({ return_address: s.return_address, return_courier: s.return_courier, return_memo: s.return_memo });
  const { busy, msg, save } = useSave(onSaved);
  return (
    <Section title="반품 안내" sub="반품·교환 요청에 이 주소와 택배사를 고객에게 안내합니다">
      <Field label="반품 받을 주소" value={f.return_address} onChangeText={(v) => setF({ ...f, return_address: v })} placeholder="예: 서울시 강남구 … 3층 물류팀" />
      <Label>이용 택배사</Label>
      <Chips items={s.couriers} value={f.return_courier} onChange={(v) => setF({ ...f, return_courier: v === f.return_courier ? '' : v })} />
      <Field label="함께 안내할 말 (선택)" value={f.return_memo} onChangeText={(v) => setF({ ...f, return_memo: v })} placeholder="예: 상품 택을 떼지 말고 보내 주세요" />
      {s.return_guide ? (
        <View style={{ backgroundColor: C.fill, borderRadius: 12, padding: 12 }}>
          <Text style={{ fontFamily: FONT, fontSize: 13, color: C.fg3, marginBottom: 6, fontWeight: '600' }}>고객에게 이렇게 보입니다</Text>
          <Text style={{ fontFamily: FONT, fontSize: 14, lineHeight: 21, color: C.fg2 }}>{s.return_guide}</Text>
        </View>
      ) : null}
      {msg.t ? <Notice text={msg.t} tone={msg.ok ? 'ok' : 'error'} flat /> : null}
      <Btn title="저장" onPress={() => save({ act: 'return', ...f })} busy={busy} />
    </Section>
  );
}

function Notify({ s, onSaved }: { s: Settings; onSaved: (s: Settings) => void }) {
  const [f, setF] = useState({ phone: s.phone, kakao: s.kakao, report_mail: s.report_mail });
  const { busy, msg, save } = useSave(onSaved);
  return (
    <Section title="알림" sub="새 요청은 이 앱 알림으로 바로 알려 드립니다">
      <Toggle title="카카오 알림톡" sub={s.kakao_ready ? '새 요청이 오면 알림톡으로도 알려 드립니다' : '알림톡은 준비 중입니다'} value={f.kakao} onChange={(v) => setF({ ...f, kakao: v })} disabled={!s.kakao_ready && !f.kakao} />
      {f.kakao ? <Field label="알림톡 받을 휴대폰" value={f.phone} onChangeText={(v) => setF({ ...f, phone: v })} keyboardType="phone-pad" /> : null}
      <Toggle title="월간 리포트 메일" sub="매달 1일 지난달 리포트를 이메일로 보내 드립니다" value={f.report_mail} onChange={(v) => setF({ ...f, report_mail: v })} />
      {msg.t ? <Notice text={msg.t} tone={msg.ok ? 'ok' : 'error'} flat /> : null}
      <Btn title="저장" onPress={() => save({ act: 'notify', ...f })} busy={busy} />
    </Section>
  );
}

function Password() {
  const [old, setOld] = useState('');
  const [nw, setNw] = useState('');
  const { busy, msg, save } = useSave();
  useEffect(() => {
    if (msg.ok) (setOld(''), setNw(''));
  }, [msg.ok]);
  return (
    <Section title="비밀번호 바꾸기">
      <PwField label="지금 비밀번호" value={old} onChangeText={setOld} autoComplete="password" />
      <PwField label="새 비밀번호" value={nw} onChangeText={setNw} hint="10자 이상" autoComplete="new-password" />
      {msg.t ? <Notice text={msg.t} tone={msg.ok ? 'ok' : 'error'} flat /> : null}
      <Btn title="비밀번호 바꾸기" kind="soft" onPress={() => save({ act: 'password', old, new: nw })} busy={busy} />
    </Section>
  );
}
