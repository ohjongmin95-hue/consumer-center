// 민원 보기: 웹 민원 화면(c_case.html)과 같은 내용과 동작
import * as ImagePicker from 'expo-image-picker';
import { useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Icon } from '../../components/Icon';
import { Btn, Chips, Field, Loading, Notice, StatusPill } from '../../components/ui';
import { api, CaseDetail, fmtDate, Photo } from '../../lib/api';
import { useStore } from '../../lib/store';
import { C, R } from '../../lib/theme';

const HEADS: Record<string, string> = {
  received: '접수했어요', forwarded: '기업에 전달했어요', seen: '기업이 확인하고 있어요', info: '추가 자료가 필요해요', answered: '답변이 도착했어요',
  resolved: '해결됐어요', unresolved: '아직 해결되지 않았어요', closed: '종료됐어요', withdrawn: '접수를 취소했어요',
};
const TRACK = ['접수', '전달', '확인', '답변', '완료'];
const RELIEF: [string, string, string, string][] = [
  ['phone', '1372 소비자상담센터', '전화 1372 또는 온라인으로 상담해요', 'https://www.ccn.go.kr'],
  ['building', '한국소비자원 피해구제', '상담 뒤 피해구제를 신청해요', 'https://www.kca.go.kr'],
  ['shield', '소비자분쟁조정위원회', '합의가 안 되면 조정을 요청해요', 'https://www.kca.go.kr'],
];

export default function CaseView() {
  const { id: rawId, done } = useLocalSearchParams<{ id: string; done?: string }>();
  const id = Number(rawId);
  const { tokens, ready, meta } = useStore();
  const [token, setToken] = useState('');
  const [c, setC] = useState<CaseDetail | null>(null);
  const [err, setErr] = useState('');
  const [ok, setOk] = useState(done ? '접수했어요. 진행 상황은 여기서 볼 수 있어요.' : '');
  const [busy, setBusy] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [msg, setMsg] = useState('');
  const [again, setAgain] = useState('');
  const [courier, setCourier] = useState('');
  const [tracking, setTracking] = useState('');
  const [bank, setBank] = useState('');
  const [account, setAccount] = useState('');
  const [holder, setHolder] = useState('');
  const [infoMsg, setInfoMsg] = useState('');
  const [infoPhotos, setInfoPhotos] = useState<Photo[]>([]);
  const [cancelOpen, setCancelOpen] = useState(false);

  // 이 민원의 토큰 찾기
  useEffect(() => {
    if (!ready) return;
    api
      .mine(tokens)
      .then((r) => {
        const t = r.cases.find((x) => x.id === id)?.token;
        if (t) setToken(t);
        else setErr('이 휴대폰에서 열 수 없는 민원이에요. 내 접수에서 휴대폰 번호로 찾아 주세요.');
      })
      .catch((e) => setErr(e.message));
  }, [ready, tokens, id]);
  const load = useCallback(async () => {
    if (!token) return;
    try {
      setC(await api.case(id, token));
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [id, token]);
  useEffect(() => {
    load();
  }, [load]);

  const act = async (key: string, fields: Record<string, string>, photos: Photo[] = []) => {
    setBusy(key);
    setErr('');
    setOk('');
    try {
      const r = await api.act(id, token, fields, photos);
      setC(r);
      if (r.message) setOk(r.message);
      return true;
    } catch (e) {
      setErr((e as Error).message);
      return false;
    } finally {
      setBusy('');
    }
  };

  if (!c) return err ? <Notice text={err} /> : <Loading />;
  const last = [...c.events].reverse().find((e) => e.kind === 'co' && e.reply);
  const head = c.overdue ? '답변이 늦어지고 있어요' : HEADS[c.status] ?? '접수했어요';

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.band }} edges={['bottom']}>
      <ScrollView
        contentContainerStyle={{ paddingVertical: 16, paddingBottom: 40 }}
        keyboardShouldPersistTaps="handled"
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => (setRefreshing(true), await load(), setRefreshing(false))} />}
      >
        {!!ok && <Notice text={ok} tone="ok" />}
        {!!err && <Notice text={err} />}

        <View style={st.card}>
          <View style={st.tag}>
            <View style={st.av}>
              <Text style={st.avT}>{c.company_name[0]}</Text>
            </View>
            <Text style={st.co}>{c.company_name}</Text>
            <StatusPill status={c.member ? 'answered' : 'received'} label={c.member ? '입점' : '비입점'} />
          </View>
          <Text style={st.h1}>{head}</Text>
          {c.member && !!c.due && ['forwarded', 'seen'].includes(c.status) && <Text style={st.sub}>담당자가 확인하고 있어요</Text>}
          <View style={st.track}>
            {TRACK.map((t, i) => (
              <View key={t} style={{ flex: 1, gap: 8 }}>
                <View style={[st.seg, i <= c.step && { backgroundColor: C.accent }]} />
                <Text style={[st.segT, i === c.step && { color: C.fg, fontWeight: '700' }]}>{t}</Text>
              </View>
            ))}
          </View>
        </View>

        {last && (
          <View style={st.card}>
            <View style={st.tag}>
              <View style={st.av}>
                <Text style={st.avT}>{c.company_name[0]}</Text>
              </View>
              <Text style={st.co}>{c.company_name}</Text>
              <Text style={[st.cap, { marginLeft: 'auto' }]}>{fmtDate(last.created)}</Text>
            </View>
            <Text style={st.reply}>{last.reply}</Text>
          </View>
        )}

        {c.can.rate && (
          <View style={st.card}>
            <Text style={st.h2}>해결됐나요?</Text>
            <Text style={st.sub}>알려 주시면 기업과 센터가 다음 조치를 정해요</Text>
            <View style={st.row}>
              <Btn title="아직이에요" kind="gray" busy={busy === 'un'} onPress={() => act('un', { act: 'rate', v: 'unresolved' })} style={{ flex: 1 }} />
              <Btn title="해결됐어요" busy={busy === 'ok'} onPress={() => act('ok', { act: 'rate', v: 'resolved' })} style={{ flex: 1 }} />
            </View>
          </View>
        )}

        {c.can.info && (
          <View style={st.card}>
            <Text style={st.h2}>자료를 보내 주세요</Text>
            <Text style={st.sub}>{c.info_ask}</Text>
            <View style={{ gap: 10, marginTop: 14 }}>
              <Field value={infoMsg} onChangeText={setInfoMsg} multiline />
              <Btn
                title={infoPhotos.length ? `사진 ${infoPhotos.length}장 골랐어요` : '사진 고르기'}
                kind="soft"
                onPress={async () => {
                  const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], allowsMultipleSelection: true, selectionLimit: meta?.max_files ?? 3, quality: 0.7 });
                  if (!r.canceled) setInfoPhotos(r.assets.map((a, i) => ({ uri: a.uri, name: a.fileName ?? `photo${i}.jpg`, type: a.mimeType ?? 'image/jpeg' })));
                }}
              />
              <Btn title="보내기" busy={busy === 'info'} disabled={!infoMsg.trim()} onPress={async () => (await act('info', { act: 'info', msg: infoMsg }, infoPhotos)) && (setInfoMsg(''), setInfoPhotos([]))} />
            </View>
          </View>
        )}

        {!!c.ret.status && (
          <View style={st.card}>
            <Text style={st.h2}>반품 보내기</Text>
            {c.ret.status === 'received' ? (
              <Text style={st.sub}>
                {c.company_name}이(가) 보내신 상품을 받았어요.{c.ret.out_tracking ? `\n새 상품을 보냈어요: ${c.ret.out_courier} ${c.ret.out_tracking}` : ''}
              </Text>
            ) : c.ret.status === 'sent' ? (
              <Text style={st.sub}>
                {c.ret.courier} {c.ret.tracking} 로 보냈다고 알렸어요. 회사가 받으면 알려 드려요.
              </Text>
            ) : (
              <View style={{ gap: 12 }}>
                <Text style={st.sub}>답변의 반품 안내대로 보내신 뒤 택배사와 송장번호를 알려 주세요.</Text>
                <Chips items={[...(meta?.couriers ?? []), '기타']} value={courier} onChange={setCourier} />
                <Field value={tracking} onChangeText={setTracking} placeholder="송장번호" keyboardType="number-pad" maxLength={30} />
                <Btn title="송장번호 알리기" busy={busy === 'ship'} onPress={() => act('ship', { act: 'ship', courier, tracking })} />
              </View>
            )}
          </View>
        )}

        {c.refund.possible && (
          <View style={st.card}>
            <Text style={st.h2}>환불 받을 계좌</Text>
            {c.refund.status === 'done' ? (
              <Text style={st.sub}>{c.company_name}이(가) 환불을 완료했어요. 등록하신 계좌 정보는 지웠어요.</Text>
            ) : (
              <View style={{ gap: 12 }}>
                <Text style={st.sub}>
                  {c.refund.status === 'requested'
                    ? `${c.refund.bank} ${c.refund.account} (${c.refund.holder}) 으로 등록했어요. 바꾸려면 다시 입력해 주세요.`
                    : '계좌이체나 무통장으로 결제하셨다면 환불 받을 계좌를 알려 주세요. 카드 결제는 결제 취소로 환불돼서 등록하지 않아도 돼요.'}
                </Text>
                <Chips items={meta?.banks ?? []} value={bank} onChange={setBank} />
                <Field value={account} onChangeText={setAccount} placeholder="계좌번호 (숫자만)" keyboardType="number-pad" maxLength={20} />
                <Field value={holder} onChangeText={setHolder} placeholder="예금주" maxLength={20} />
                <Btn title={c.refund.status === 'requested' ? '계좌 바꾸기' : '계좌 등록하기'} busy={busy === 'refund'} onPress={() => act('refund', { act: 'refund', bank, account, holder })} />
                <Text style={st.cap}>환불이 끝나면 계좌 정보는 바로 지워요.</Text>
              </View>
            )}
          </View>
        )}

        {!c.member && ['received', 'forwarded', 'seen'].includes(c.status) && (
          <View style={st.card}>
            <Text style={st.h2}>비입점 기업이에요</Text>
            <Text style={st.sub}>센터가 공식 연락처로 전달하고 회신을 기록해요</Text>
            {!!c.contact && (
              <Text style={[st.sub, { marginTop: 10, color: C.fg }]} selectable>
                고객센터 {c.contact}
              </Text>
            )}
          </View>
        )}

        {c.can.again && (
          <View style={st.card}>
            <Text style={st.h2}>기업에 다시 요청할까요?</Text>
            <Text style={st.sub}>{c.overdue ? '답변이 늦어지고 있어요. 다시 요청하면 기업에 한 번 더 알려요.' : '해결되지 않은 내용을 덧붙여 한 번 더 보내요.'}</Text>
            <View style={{ gap: 10, marginTop: 14 }}>
              <Field value={again} onChangeText={setAgain} placeholder="덧붙일 말 (선택)" maxLength={2000} />
              <Btn title="다시 요청" busy={busy === 'again'} onPress={async () => (await act('again', { act: 'again', msg: again })) && setAgain('')} />
            </View>
          </View>
        )}

        {(c.status === 'unresolved' || c.overdue) && (
          <View style={{ marginHorizontal: 16, marginBottom: 12 }}>
            <Text style={[st.h2, { marginHorizontal: 4, marginTop: 8 }]}>공식 피해구제</Text>
            {RELIEF.map(([ic, t, d, u]) => (
              <Pressable key={t} onPress={() => Linking.openURL(u)} style={st.relief}>
                <Icon name={ic} size={32} />
                <View style={{ flex: 1 }}>
                  <Text style={st.rt}>{t}</Text>
                  <Text style={st.cap}>{d}</Text>
                </View>
              </Pressable>
            ))}
          </View>
        )}

        <View style={st.card}>
          <Text style={st.h2}>진행 기록</Text>
          {[...c.events].reverse().map((e) => (
            <View key={e.id} style={st.ev}>
              <View style={[st.dot, e.kind === 'co' && { backgroundColor: C.accent }, e.kind === 'sys' && { backgroundColor: C.fg4 }]} />
              <View style={{ flex: 1, gap: 4 }}>
                <Text style={st.evT}>{e.text}</Text>
                {!!e.reply && <Text style={st.evR}>{e.reply}</Text>}
                {e.files.map((fl) => (
                  <Text key={fl.id} style={st.file} onPress={() => Linking.openURL(fl.url)}>
                    📎 {fl.name}
                  </Text>
                ))}
                <Text style={st.cap}>{fmtDate(e.created)}</Text>
              </View>
            </View>
          ))}
          {c.can.add && (
            <View style={{ flexDirection: 'row', gap: 8, marginTop: 8 }}>
              <View style={{ flex: 1 }}>
                <Field value={msg} onChangeText={setMsg} placeholder="덧붙일 내용" />
              </View>
              <Btn title="보내기" kind="gray" busy={busy === 'add'} disabled={!msg.trim()} onPress={async () => (await act('add', { act: 'add', msg })) && setMsg('')} />
            </View>
          )}
        </View>

        <View style={st.card}>
          <Text style={st.h2}>접수 내용</Text>
          <Text style={st.tt}>{c.title}</Text>
          <Text style={st.bodyT}>{c.body}</Text>
          {c.files.map((fl) => (
            <Text key={fl.id} style={st.file} onPress={() => Linking.openURL(fl.url)}>
              📎 {fl.name}
            </Text>
          ))}
          <View style={st.hr} />
          {[
            ['접수번호', c.no],
            ['유형', c.category],
            ['원하는 해결', c.want],
            ['접수일', fmtDate(c.created)],
          ].map(([k, v]) => (
            <View key={k} style={st.kv}>
              <Text style={st.k}>{k}</Text>
              <Text style={st.v} selectable>
                {v}
              </Text>
            </View>
          ))}
        </View>

        {c.can.cancel && (
          <View style={st.card}>
            <Pressable onPress={() => setCancelOpen(!cancelOpen)}>
              <Text style={[st.h2, { marginBottom: 0, fontSize: 16, color: C.fg2 }]}>접수 취소하기</Text>
            </Pressable>
            {cancelOpen && (
              <View style={{ gap: 12, marginTop: 12 }}>
                <Text style={st.sub}>이미 해결됐거나 잘못 접수했다면 취소해 주세요. 취소하면 기업에도 알려요.</Text>
                <Btn title="접수 취소" kind="danger" busy={busy === 'cancel'} onPress={() => act('cancel', { act: 'cancel' })} />
              </View>
            )}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  card: { backgroundColor: C.card, borderRadius: R.lg, padding: 20, marginHorizontal: 16, marginBottom: 12 },
  tag: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  av: { width: 28, height: 28, borderRadius: 10, backgroundColor: C.accentSoft, alignItems: 'center', justifyContent: 'center' },
  avT: { fontSize: 13, fontWeight: '700', color: C.accentInk },
  co: { fontSize: 15, fontWeight: '700', color: C.fg },
  h1: { fontSize: 24, fontWeight: '700', color: C.fg, letterSpacing: -0.8, marginTop: 16 },
  h2: { fontSize: 18, fontWeight: '700', color: C.fg, letterSpacing: -0.5, marginBottom: 6 },
  sub: { fontSize: 15, lineHeight: 22, color: C.fg3 },
  cap: { fontSize: 13, color: C.fg3 },
  track: { flexDirection: 'row', gap: 4, marginTop: 20 },
  seg: { height: 6, borderRadius: 3, backgroundColor: C.fill },
  segT: { fontSize: 12, color: C.fg3, textAlign: 'center' },
  reply: { fontSize: 16, lineHeight: 25, color: C.fg, marginTop: 12 },
  row: { flexDirection: 'row', gap: 10, marginTop: 14 },
  relief: { backgroundColor: C.card, borderRadius: R.lg, padding: 18, flexDirection: 'row', alignItems: 'center', gap: 14, marginBottom: 10 },
  rt: { fontSize: 16, fontWeight: '700', color: C.fg },
  ev: { flexDirection: 'row', gap: 12, paddingVertical: 10 },
  dot: { width: 10, height: 10, borderRadius: 5, backgroundColor: C.fg2, marginTop: 6 },
  evT: { fontSize: 15, color: C.fg, fontWeight: '600' },
  evR: { fontSize: 15, lineHeight: 23, color: C.fg2, backgroundColor: C.fill, borderRadius: R.sm, padding: 12 },
  file: { fontSize: 15, color: C.accentInk, fontWeight: '600', paddingVertical: 4 },
  tt: { fontSize: 17, fontWeight: '700', color: C.fg, marginTop: 4 },
  bodyT: { fontSize: 15, lineHeight: 23, color: C.fg2, marginTop: 8 },
  hr: { height: 1, backgroundColor: C.line, marginVertical: 16 },
  kv: { flexDirection: 'row', paddingVertical: 4 },
  k: { width: 96, fontSize: 14, color: C.fg3 },
  v: { flex: 1, fontSize: 14, color: C.fg, fontWeight: '600' },
});
