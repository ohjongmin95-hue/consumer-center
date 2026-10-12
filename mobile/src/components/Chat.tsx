// 상담창(자동응답): 웹 상담창(platform_app/templates/_chat.html)과 같은 흐름과 문구
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { api, ChatAnswer } from '../lib/api';
import { C, R } from '../lib/theme';
import { CATS } from './CatGrid';

type Msg = { who: 'bot' | 'me'; text: string };
type Chip = { label: string; pri?: boolean; fn: () => void };

export function Chat({ companyId, greet }: { companyId: number | null; greet: string }) {
  const [log, setLog] = useState<Msg[]>([]);
  const [chips, setChips] = useState<Chip[]>([]);
  const [text, setText] = useState('');
  const said = useRef<string[]>([]);
  const cat = useRef<string | null>(null);
  const info = useRef<ChatAnswer | null>(null);

  const say = (m: string, who: Msg['who'] = 'bot') => setLog((l) => [...l, { who, text: m }]);
  const later = (fn: () => void, ms = 450) => setTimeout(fn, ms);
  const catChips = () => setChips(CATS.map((c) => ({ label: c, fn: () => (say(c, 'me'), ask({ category: c })) })));

  const goNew = () => {
    const params: Record<string, string> = {};
    if (companyId) params.company_id = String(companyId);
    if (cat.current) params.category = cat.current;
    if (said.current.length) params.body = said.current.join('\n');
    router.push({ pathname: '/new', params });
  };
  const endChips = () => {
    const i = info.current;
    const file = i?.member ? (i.auto && !i.cond ? '접수하면 바로 처리돼요' : '담당자에게 바로 전달돼요') : '';
    setChips([
      { label: '접수할게요', pri: true, fn: () => (api.chat(companyId, { outcome: 'filed', category: cat.current ?? '' }).catch(() => {}), say('접수할게요', 'me'), later(() => (say((file ? file + '. ' : '') + '적어 주신 내용을 이어서 쓸 수 있게 해 둘게요.'), later(goNew, 700)))) },
      { label: '해결됐어요', fn: () => (api.chat(companyId, { outcome: 'solved', category: cat.current ?? '' }).catch(() => {}), say('해결됐어요', 'me'), later(() => say('도움이 됐다니 다행이에요. 또 궁금한 게 생기면 언제든 적어 주세요.'))) },
      { label: '다른 걸 물어볼게요', fn: () => (say('다른 걸 물어볼게요', 'me'), (said.current = []), (cat.current = null), later(() => (say('네, 편하게 적어 주세요.'), catChips()))) },
    ]);
  };
  const days = () =>
    setChips([
      { label: '7일 이내예요', fn: () => (say('7일 이내예요', 'me'), later(() => (say('그럼 단순 변심이어도 신청할 수 있어요. 단순 변심일 때 돌려보내는 배송비는 고객님 부담이에요.' + (info.current?.member && info.current?.auto ? '\n접수하실 때 상품 받은 날을 적어 주시면 바로 처리돼요.' : '')), endChips()))) },
      { label: '7일 지났어요', fn: () => (say('7일 지났어요', 'me'), later(() => (say('단순 변심 기간(7일)은 지났어요. 다만 상품이 광고나 주문 내용과 다르면 받은 날부터 3개월, 그 사실을 안 날부터 30일 안에 신청할 수 있어요. 사진과 함께 접수해 주세요.'), endChips()))) },
      { label: '아직 못 받았어요', fn: () => (say('아직 못 받았어요', 'me'), ask({ category: '배송 조회' })) },
    ]);
  const ask = (data: Record<string, string>) => {
    setChips([]);
    api
      .chat(companyId, data)
      .then((r) => {
        if (r.error) return later(() => say(r.error!));
        if (!r.category) return later(() => (say('제가 정확히 알아들었는지 모르겠어요. 가장 가까운 걸 골라 주시겠어요?'), catChips()));
        cat.current = r.category;
        info.current = r;
        later(() => {
          say(r.category === '기타' ? '네, 확인했어요.' : r.category + ' 문의시군요.');
          later(() => {
            say(r.faq ?? '');
            if (r.ask_days) later(() => (say('상품을 받으신 지 7일이 지났나요?'), days()));
            else endChips();
          }, 500);
        });
      })
      .catch(() => later(() => say('연결이 잠시 불안정해요. 아래에서 직접 골라 접수해 주세요.')));
  };
  const send = () => {
    const t = text.trim();
    if (!t) return;
    setText('');
    say(t, 'me');
    said.current.push(t);
    ask({ text: t });
  };

  useEffect(() => {
    say('안녕하세요, ' + greet + '.\n어떤 일인지 편하게 적어 주시거나 아래에서 골라 주세요.');
    catChips();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <View style={{ gap: 10 }}>
      {log.map((m, i) => (
        <View key={i} style={[st.bubble, m.who === 'me' ? st.me : st.bot]}>
          <Text style={[st.bt, m.who === 'me' && { color: '#fff' }]}>{m.text}</Text>
        </View>
      ))}
      {chips.length > 0 && (
        <View style={st.chips}>
          {chips.map((c) => (
            <Pressable key={c.label} onPress={c.fn} style={[st.chip, c.pri && { backgroundColor: C.accent, borderColor: C.accent }]}>
              <Text style={[st.ct, c.pri && { color: '#fff' }]}>{c.label}</Text>
            </Pressable>
          ))}
        </View>
      )}
      <View style={st.inRow}>
        <TextInput value={text} onChangeText={setText} onSubmitEditing={send} placeholder="예: 주문한 게 아직 안 왔어요" placeholderTextColor={C.fg4} style={st.input} maxLength={500} returnKeyType="send" />
        <Pressable onPress={send} style={st.send}>
          <Text style={{ color: '#fff', fontWeight: '700', fontSize: 16 }}>보내기</Text>
        </Pressable>
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  bubble: { maxWidth: '86%', paddingHorizontal: 16, paddingVertical: 11, borderRadius: 20 },
  bot: { backgroundColor: C.fill, alignSelf: 'flex-start', borderTopLeftRadius: 6 },
  me: { backgroundColor: C.accent, alignSelf: 'flex-end', borderTopRightRadius: 6 },
  bt: { fontSize: 16, lineHeight: 24, color: C.fg },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { height: 38, paddingHorizontal: 15, borderRadius: 19, borderWidth: 1, borderColor: C.line, backgroundColor: C.card, justifyContent: 'center' },
  ct: { fontSize: 15, fontWeight: '600', color: C.fg2 },
  inRow: { flexDirection: 'row', gap: 8, marginTop: 4 },
  input: { flex: 1, height: 52, borderRadius: 26, backgroundColor: C.fill, paddingHorizontal: 20, fontSize: 16, color: C.fg },
  send: { height: 52, borderRadius: 26, backgroundColor: C.accent, paddingHorizontal: 22, justifyContent: 'center' },
});
