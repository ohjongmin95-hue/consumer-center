// 응대 가이드: 상황마다 지켜야 할 법 조항과 예시 답변. 조항 원문은 눌러서 펼친다.
import * as Clipboard from 'expo-clipboard';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Btn, Card, Loading, Notice, Screen } from '../components/ui';
import { api, GuideItem } from '../lib/api';
import { C } from '../lib/theme';
import { useLoad } from '../lib/useLoad';

export default function Guide() {
  const { data, err } = useLoad(api.guide);
  const [open, setOpen] = useState('');
  if (!data) return err ? <Notice text={err} /> : <Loading />;
  return (
    <Screen>
      <View style={{ paddingHorizontal: 24, paddingTop: 8, paddingBottom: 14 }}>
        <Text style={st.p}>자주 받는 요청 상황마다 지켜야 할 법 조항과 예시 답변을 모았습니다. 조항은 국가법령정보센터 원문 그대로이고, 쉬운 설명과 예시 문구는 법률 자문이 아닙니다.</Text>
      </View>
      {data.guide.map((g) => (
        <Item key={g.id} g={g} open={open === g.id} onToggle={() => setOpen(open === g.id ? '' : g.id)} />
      ))}
      <Card style={{ gap: 10 }}>
        <Text style={st.h2}>품목별 소비자분쟁해결기준</Text>
        <Text style={st.p}>수리·교환·환불 기준은 공정거래위원회 고시의 품목별 기준을 따릅니다. 내용이 길고 자주 바뀌어 공식 원문에서 확인해 주세요.</Text>
        <Btn title="원문 보기" kind="gray" onPress={() => WebBrowser.openBrowserAsync(data.kca)} />
      </Card>
    </Screen>
  );
}

function Item({ g, open, onToggle }: { g: GuideItem; open: boolean; onToggle: () => void }) {
  const [copied, setCopied] = useState(false);
  const [law, setLaw] = useState(-1);
  return (
    <Card>
      <Pressable onPress={onToggle} style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <Text style={[st.h2, { flex: 1 }]}>{g.title}</Text>
        <Text style={{ fontSize: 20, color: C.fg4 }}>{open ? '⌃' : '⌄'}</Text>
      </Pressable>
      {open ? (
        <View style={{ gap: 12, marginTop: 14 }}>
          <Text style={st.ph}>이렇게 확인하세요</Text>
          {g.points.map((p, i) => (
            <View key={i} style={{ flexDirection: 'row', gap: 8 }}>
              <Text style={{ color: C.accent, fontWeight: '800' }}>•</Text>
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={st.body}>{p.text}</Text>
                <Text style={st.ref}>{p.label}</Text>
              </View>
            </View>
          ))}
          <Text style={st.ph}>예시 문구</Text>
          <Text style={st.sample} selectable>
            {g.sample}
          </Text>
          <Btn
            title={copied ? '복사했습니다' : '예시 문구 복사'}
            kind="soft"
            onPress={async () => {
              await Clipboard.setStringAsync(g.sample);
              setCopied(true);
            }}
          />
          <Text style={st.ph}>관련 조항 원문</Text>
          {g.laws.map((l, i) => (
            <Pressable key={i} onPress={() => setLaw(law === i ? -1 : i)} style={st.law}>
              <Text style={{ fontSize: 14, fontWeight: '700', color: C.fg }}>
                {l.label} <Text style={{ fontWeight: '500', color: C.fg3 }}>{l.title}</Text>
              </Text>
              {law === i ? <Text style={[st.body, { marginTop: 8, fontSize: 14 }]}>{l.text}</Text> : null}
            </Pressable>
          ))}
        </View>
      ) : null}
    </Card>
  );
}

const st = StyleSheet.create({
  p: { fontSize: 15, lineHeight: 23, color: C.fg2 },
  h2: { fontSize: 17, fontWeight: '700', color: C.fg, letterSpacing: -0.4 },
  ph: { fontSize: 13, fontWeight: '700', color: C.fg3, marginTop: 4 },
  body: { fontSize: 15, lineHeight: 23, color: C.fg },
  ref: { fontSize: 12, color: C.fg3 },
  sample: { fontSize: 15, lineHeight: 23, color: C.fg2, backgroundColor: C.accentSoft, borderRadius: 12, padding: 14 },
  law: { backgroundColor: C.fill, borderRadius: 12, padding: 12 },
});
