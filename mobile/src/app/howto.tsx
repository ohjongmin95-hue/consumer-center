// 소보루 CS 이용 안내: 홈페이지(cs.soboru.co.kr/guide)의 이용 안내를 앱 안에서. 사장님이 쓰는 순서를 먼저 보여 준다.
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Icon } from '../components/Icon';
import { Card, H2, Screen } from '../components/ui';
import { C } from '../lib/theme';

const OWNER: [string, string, string][] = [
  ['building', '고객센터 링크 걸기', '내 정보의 우리 가게 고객센터 링크를 쇼핑몰 상세페이지나 카카오톡 채널에 걸어 두세요.'],
  ['chat', '소보루가 먼저 응대', '고객 문의는 챗봇이 먼저 안내하고, 자동 처리를 켜 둔 유형은 사장님 확인 없이 바로 답변합니다.'],
  ['shield', '판단이 필요한 요청만 승인', '새 요청이 오면 앱 알림으로 알려 드립니다. 추천 처리 방법을 보고 승인만 누르면 답변과 조치까지 이어집니다.'],
  ['list', '통계와 리포트로 점검', '자동 처리율, 해결률, 많이 나온 상품을 보고 반복되는 문제를 줄여 보세요.'],
];
const STEPS: [string, string, string][] = [
  ['note', '접수', '기업, 유형, 내용, 원하는 해결, 연락처를 적어요'],
  ['truck', '전달', '동의한 경우에만 기업에 전달돼요'],
  ['search', '확인', '기업이 내용을 확인했는지 보여 드려요'],
  ['reply', '답변·조치', '답변과 교환·회수·환불 같은 조치가 기록돼요'],
  ['shield', '해결 확인', '해결됐는지 알려 주시면 마무리돼요'],
];
const RELIEF: [string, string, string][] = [
  ['1372 소비자상담센터', '전화 1372 또는 온라인으로 상담해요', 'https://www.ccn.go.kr'],
  ['한국소비자원 피해구제', '상담 뒤 피해구제를 신청해요', 'https://www.kca.go.kr'],
  ['소비자분쟁조정위원회', '합의가 안 되면 조정을 요청해요', 'https://www.kca.go.kr'],
];
const FAQ: [string, string][] = [
  ['고객 연락처는 어떻게 받나요?', '고객이 기업 전달에 동의한 경우에만 이름과 연락처, 접수 내용이 사장님께 전달됩니다.'],
  ['자동 처리는 언제 답변하나요?', '자동 처리 규칙에서 켜 둔 유형은 접수되자마자 정해 둔 답변이 나갑니다. 교환·반품은 받은 지 7일 이내일 때만 자동 처리하도록 정할 수도 있습니다.'],
  ['전화나 쇼핑몰로 받은 요청도 관리할 수 있나요?', '요청 직접 등록으로 올리면 추천 처리와 기록 관리를 똑같이 쓸 수 있습니다.'],
];

export default function HowTo() {
  const [open, setOpen] = useState(-1);
  return (
    <Screen>
      <View style={{ paddingHorizontal: 24, paddingTop: 8, paddingBottom: 16, gap: 6 }}>
        <Text style={st.h1}>고객 응대는 소보루가,{'\n'}사장님은 확인만</Text>
        <Text style={st.p}>어느 기업이든 한 번 접수하면 답변과 해결까지 이어서 챙깁니다.</Text>
      </View>

      <Card>
        <H2>사장님은 이렇게 씁니다</H2>
        <View style={{ gap: 18 }}>
          {OWNER.map(([ic, t, s], i) => (
            <View key={t} style={{ flexDirection: 'row', gap: 14 }}>
              <View style={st.ic}>
                <Icon name={ic} size={26} />
              </View>
              <View style={{ flex: 1, gap: 3 }}>
                <Text style={st.k}>{i + 1}단계</Text>
                <Text style={st.t}>{t}</Text>
                <Text style={st.s}>{s}</Text>
              </View>
            </View>
          ))}
        </View>
      </Card>

      <Card>
        <H2>입점 기업과 비입점 기업</H2>
        <View style={{ gap: 14 }}>
          <View style={st.box}>
            <Text style={st.t}>입점 기업</Text>
            <Text style={st.s}>소보루 CS를 쓰는 기업입니다. 담당자 화면으로 바로 전달되고, 배송 조회처럼 정해진 유형은 접수 즉시 처리되기도 합니다.</Text>
          </View>
          <View style={st.box}>
            <Text style={st.t}>비입점 기업</Text>
            <Text style={st.s}>센터가 기업의 공식 연락처로 전달을 시도하고 회신을 기록합니다. 회신이 없으면 공식 피해구제 절차를 안내합니다.</Text>
          </View>
        </View>
      </Card>

      <Card>
        <H2>고객에게 보이는 진행 단계</H2>
        <View style={{ gap: 14 }}>
          {STEPS.map(([ic, t, s], i) => (
            <View key={t} style={{ flexDirection: 'row', gap: 12, alignItems: 'center' }}>
              <Icon name={ic} size={28} />
              <View style={{ flex: 1 }}>
                <Text style={st.t}>
                  <Text style={{ color: C.accent }}>{i + 1}</Text> {t}
                </Text>
                <Text style={st.s}>{s}</Text>
              </View>
            </View>
          ))}
        </View>
      </Card>

      <Card>
        <H2>해결되지 않으면</H2>
        <Text style={[st.s, { marginTop: -6, marginBottom: 12 }]}>답변이 늦어지거나 고객이 미해결로 응답하면 아래 기관을 안내합니다.</Text>
        {RELIEF.map(([t, s, u], i) => (
          <Pressable key={t} onPress={() => WebBrowser.openBrowserAsync(u)} style={[st.row, i < RELIEF.length - 1 && st.line]}>
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={st.t}>{t}</Text>
              <Text style={st.s}>{s}</Text>
            </View>
            <Text style={{ fontSize: 22, color: C.fg4 }}>›</Text>
          </Pressable>
        ))}
      </Card>

      <Card>
        <H2>자주 묻는 질문</H2>
        {FAQ.map(([q, a], i) => (
          <Pressable key={q} onPress={() => setOpen(open === i ? -1 : i)} style={[st.row, { flexDirection: 'column', alignItems: 'stretch', gap: 8 }, i < FAQ.length - 1 && st.line]}>
            <View style={{ flexDirection: 'row', alignItems: 'center' }}>
              <Text style={[st.t, { flex: 1 }]}>{q}</Text>
              <Text style={{ fontSize: 18, color: C.fg4 }}>{open === i ? '⌃' : '⌄'}</Text>
            </View>
            {open === i ? <Text style={st.s}>{a}</Text> : null}
          </Pressable>
        ))}
      </Card>
    </Screen>
  );
}

const st = StyleSheet.create({
  h1: { fontSize: 24, lineHeight: 34, fontWeight: '700', color: C.fg, letterSpacing: -0.8 },
  p: { fontSize: 15, lineHeight: 23, color: C.fg3 },
  ic: { width: 48, height: 48, borderRadius: 14, backgroundColor: C.accentSoft, alignItems: 'center', justifyContent: 'center' },
  k: { fontSize: 12, fontWeight: '700', color: C.accentInk },
  t: { fontSize: 16, fontWeight: '700', color: C.fg, letterSpacing: -0.3 },
  s: { fontSize: 14, lineHeight: 21, color: C.fg2 },
  box: { backgroundColor: C.fill, borderRadius: 14, padding: 14, gap: 4 },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 12 },
  line: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.line },
});
