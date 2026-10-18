// 알림: 들어온 알림 목록(열면 모두 읽음)과 종류별로 받을 곳(앱 알림·이메일). 웹의 /alerts와 같은 내용.
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Btn, Card, H2, Loading, Notice, Screen, Toggle } from '../components/ui';
import { AlertPrefs, Alerts, api, fmtDate } from '../lib/api';
import { useAuth } from '../lib/auth';
import { setAlerts } from '../lib/badge';
import { C, FONT } from '../lib/theme';
import { errText, useLoad } from '../lib/useLoad';

export default function AlertsScreen() {
  const { data, setData, err } = useLoad(api.alerts);
  useEffect(() => {
    if (data) setAlerts(0); // 열면 서버에서 모두 읽음으로 바뀐다
  }, [data]);
  if (!data) return err ? <Notice text={err} /> : <Loading />;
  return (
    <Screen>
      <Card style={{ gap: 0, paddingVertical: 6 }}>
        {data.items.length ? (
          data.items.map((a, i) => (
            <Pressable
              key={a.id}
              onPress={() => (a.case_id ? router.push(`/chat/${a.case_id}`) : undefined)}
              style={({ pressed }) => [st.row, i > 0 && st.line, pressed && a.case_id ? { opacity: 0.6 } : null]}
            >
              <View style={[st.dot, a.new && { backgroundColor: C.accent }]} />
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={[st.title, a.new && { fontWeight: '700' }]}>{a.title}</Text>
                {a.body ? (
                  <Text style={st.body} numberOfLines={1}>
                    {a.body}
                  </Text>
                ) : null}
              </View>
              <Text style={st.time}>{fmtDate(a.created)}</Text>
            </Pressable>
          ))
        ) : (
          <Text style={[st.body, { paddingVertical: 24, textAlign: 'center' }]}>아직 알림이 없어요. 새 문의가 오거나 AI가 답하면 여기에 쌓여요.</Text>
        )}
      </Card>
      <Prefs a={data} onSaved={setData} />
    </Screen>
  );
}

function Prefs({ a, onSaved }: { a: Alerts; onSaved: (a: Alerts) => void }) {
  const { session, logout } = useAuth();
  const [p, setP] = useState<AlertPrefs>(a.prefs);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState({ t: '', ok: false });
  const set = (k: string, ch: 'push' | 'email', v: boolean) => setP({ ...p, [k]: { ...p[k], [ch]: v ? 1 : 0 } });
  const save = async () => {
    if (!session) return;
    setBusy(true);
    setMsg({ t: '', ok: false });
    const f: Record<string, boolean> = {};
    for (const k of Object.keys(p)) for (const ch of ['push', 'email'] as const) if (p[k][ch]) f[`${k}.${ch}`] = true;
    try {
      const r = await api.saveAlerts(session.token, f);
      onSaved(r);
      setP(r.prefs);
      setMsg({ t: r.message || '저장했어요', ok: true });
    } catch (e) {
      setMsg({ t: errText(e, logout), ok: false });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card style={{ gap: 14 }}>
      <View style={{ gap: 4 }}>
        <H2>알림 받을 곳</H2>
        <Text style={st.sub}>알림은 모두 위 목록에 남아요. 고른 것만 앱 알림과 이메일로도 보내요.</Text>
      </View>
      {a.kinds.map((k) => (
        <View key={k.key} style={{ gap: 2 }}>
          <Text style={st.kind}>{k.label}</Text>
          <Text style={st.sub}>{k.sub}</Text>
          <Toggle title="앱 알림" value={!!p[k.key]?.push} onChange={(v) => set(k.key, 'push', v)} />
          <Toggle title="이메일" value={!!p[k.key]?.email} onChange={(v) => set(k.key, 'email', v)} />
        </View>
      ))}
      <Text style={st.sub}>카카오 알림톡은 회사 정보와 알림 설정에서 켜요. 승인할 문의만 보내요.</Text>
      {msg.t ? <Notice text={msg.t} tone={msg.ok ? 'ok' : 'error'} flat /> : null}
      <Btn title="저장" onPress={save} busy={busy} />
    </Card>
  );
}

const st = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, paddingVertical: 14 },
  line: { borderTopWidth: 1, borderTopColor: C.line },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 7 },
  title: { fontFamily: FONT, fontSize: 15, fontWeight: '600', color: C.fg },
  body: { fontFamily: FONT, fontSize: 14, color: C.fg2 },
  time: { fontFamily: FONT, fontSize: 12, color: C.fg3, marginTop: 2 },
  kind: { fontFamily: FONT, fontSize: 16, fontWeight: '700', color: C.fg },
  sub: { fontFamily: FONT, fontSize: 14, lineHeight: 21, color: C.fg3 },
});
