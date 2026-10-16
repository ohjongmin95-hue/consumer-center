// 토스페이스 이모지 그림 (웹 static/tf 와 같은 파일, 토스 Tossface 라이선스). 웹 홈·목록과 같은 자리에 쓴다.
import { Image, View } from 'react-native';
import { C } from '../lib/theme';

const TF = {
  bulb: require('../../assets/tf/bulb.png'),
  check: require('../../assets/tf/check.png'),
  clock: require('../../assets/tf/clock.png'),
  gift: require('../../assets/tf/gift.png'),
  hand: require('../../assets/tf/hand.png'),
  inbox: require('../../assets/tf/inbox.png'),
  link: require('../../assets/tf/link.png'),
  memo: require('../../assets/tf/memo.png'),
  money: require('../../assets/tf/money.png'),
  pencil: require('../../assets/tf/pencil.png'),
  repeat: require('../../assets/tf/repeat.png'),
  speech: require('../../assets/tf/speech.png'),
  tools: require('../../assets/tf/tools.png'),
  truck: require('../../assets/tf/truck.png'),
  warn: require('../../assets/tf/warn.png'),
};
export type TfName = keyof typeof TF;
export const CAT_TF: Record<string, TfName> = { '배송 조회': 'truck', '주문 취소': 'hand', '주문 변경': 'pencil', 교환: 'repeat', '반품·환불': 'money', '제품 불량': 'tools', '고객 응대': 'speech', 기타: 'memo' };

export function Tf({ name, size = 28 }: { name: TfName; size?: number }) {
  return <Image source={TF[name] ?? TF.memo} style={{ width: size, height: size }} resizeMode="contain" />;
}
// 연회색 둥근 칸 안의 이모지 (웹 .tft)
export function TfTile({ name, size = 26, box = 46 }: { name: TfName; size?: number; box?: number }) {
  return (
    <View style={{ width: box, height: box, borderRadius: box * 0.32, backgroundColor: C.fill, alignItems: 'center', justifyContent: 'center' }}>
      <Tf name={name} size={size} />
    </View>
  );
}
export const catTf = (cat: string): TfName => CAT_TF[cat] ?? 'memo';
