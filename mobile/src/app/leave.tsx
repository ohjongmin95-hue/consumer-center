// 회원 탈퇴 요청: 비밀번호를 확인하고 운영팀에 요청을 보낸다.
import { useState } from 'react';
import { Text, View } from 'react-native';
import { Btn, Card, Notice, PwField, Screen } from '../components/ui';
import { api } from '../lib/api';
import { useAuth } from '../lib/auth';
import { C } from '../lib/theme';
import { errText } from '../lib/useLoad';

export default function Leave() {
  const { session, logout } = useAuth();
  const [pw, setPw] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [ok, setOk] = useState('');
  const submit = async () => {
    if (!session) return;
    setBusy(true);
    setErr('');
    try {
      setOk((await api.leave(session.token, pw)).message);
    } catch (e) {
      setErr(errText(e, logout));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Screen>
      <Card style={{ gap: 14 }}>
        <Text style={{ fontSize: 20, fontWeight: '700', color: C.fg }}>회원 탈퇴</Text>
        <Text style={{ fontSize: 15, lineHeight: 23, color: C.fg2 }}>
          탈퇴하면 고객센터 링크가 닫히고 더는 민원을 받지 않습니다. 이미 받은 민원 기록은 소비자 보호 법령에 따라 정해진 기간 동안 보관한 뒤 지웁니다. 운영팀이 확인하고 처리한 뒤 이메일로 알려 드립니다.
        </Text>
        {ok ? (
          <>
            <Notice text={ok} tone="ok" flat />
            <Btn title="로그아웃" kind="gray" onPress={logout} />
          </>
        ) : (
          <>
            <PwField label="비밀번호 확인" value={pw} onChangeText={setPw} />
            <Notice text={err} flat />
            <View>
              <Btn title="탈퇴 요청하기" kind="danger" onPress={submit} busy={busy} disabled={!pw} />
            </View>
          </>
        )}
      </Card>
    </Screen>
  );
}
