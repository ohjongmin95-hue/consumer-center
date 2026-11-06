// 색 있는 납작한 아이콘 (토스 메뉴처럼 앞에 하나씩). 이모지가 아니라 우리 그림: 바탕은 은은한 그라데이션 한 색, 안쪽은 흰 선/면.
import type { ReactElement } from 'react';
import Svg, { Circle, Defs, LinearGradient, Path, Rect, Stop } from 'react-native-svg';
import { SodaMark } from './SodaMark';

const COL: Record<string, [string, string]> = {
  blue: ['#6AA8FF', '#2F6FF0'],
  green: ['#4ADBA0', '#0FA968'],
  red: ['#FF8A93', '#EE3A4B'],
  orange: ['#FFC861', '#F58A00'],
  purple: ['#B7A6FF', '#7356F0'],
  teal: ['#5FDCE0', '#13A6B8'],
  grey: ['#C5CCD4', '#8B95A1'],
  yellow: ['#FFE07A', '#F7B500'],
};
const W = '#fff';

// 이름 → [색, 그림]
const G: Record<string, [string, (f: string) => ReactElement]> = {
  chat: ['blue', (f) => (<><Path d="M4 6.5A3.5 3.5 0 0 1 7.5 3h9A3.5 3.5 0 0 1 20 6.5v6a3.5 3.5 0 0 1-3.5 3.5H11l-4.2 3.4c-.5.4-1.1 0-1.1-.6V16A3.5 3.5 0 0 1 4 12.5z" fill={f} /><Circle cx="8.6" cy="9.6" r="1.25" fill={W} /><Circle cx="12" cy="9.6" r="1.25" fill={W} /><Circle cx="15.4" cy="9.6" r="1.25" fill={W} /></>)],
  check: ['green', (f) => (<><Circle cx="12" cy="12" r="9" fill={f} /><Path d="M7.8 12.3l2.8 2.8 5.6-5.8" stroke={W} strokeWidth={2.2} fill="none" strokeLinecap="round" strokeLinejoin="round" /></>)],
  clock: ['red', (f) => (<><Circle cx="12" cy="12.5" r="8.5" fill={f} /><Path d="M12 8v4.8l3 1.8" stroke={W} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" /></>)],
  inbox: ['purple', (f) => (<><Path d="M6.2 4h11.6l3.2 9v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5z" fill={f} /><Path d="M3.4 13H8l1.3 2.4h5.4L16 13h4.6" stroke={W} strokeWidth={1.8} fill="none" strokeLinejoin="round" /></>)],
  truck: ['blue', (f) => (<><Rect x="2" y="5" width="12.5" height="11" rx="2" fill={f} /><Path d="M14.5 8.5h3.6l3.4 3.7V16h-7z" fill={f} opacity={0.75} /><Circle cx="7" cy="17.5" r="2.3" fill="#333D48" /><Circle cx="17.5" cy="17.5" r="2.3" fill="#333D48" /></>)],
  exchange: ['teal', (f) => (<><Circle cx="12" cy="12" r="9" fill={f} /><Path d="M7.5 10h8.5l-2.4-2.4M16.5 14H8l2.4 2.4" stroke={W} strokeWidth={1.9} fill="none" strokeLinecap="round" strokeLinejoin="round" /></>)],
  doc: ['blue', (f) => (<><Path d="M6.5 2.5h7.2l4.8 4.8v12.2a2 2 0 0 1-2 2h-10a2 2 0 0 1-2-2V4.5a2 2 0 0 1 2-2z" fill={f} /><Path d="M8 11.5h8M8 15h5.5" stroke={W} strokeWidth={1.8} strokeLinecap="round" /></>)],
  bolt: ['yellow', (f) => (<Path d="M13.6 2.2L4.8 13.4h6.1l-1.4 8.4 8.9-11.5h-6.2z" fill={f} />)],
  template: ['orange', (f) => (<><Rect x="4" y="3" width="16" height="18" rx="3" fill={f} /><Path d="M8 8.5h8M8 12h8M8 15.5h4.5" stroke={W} strokeWidth={1.8} strokeLinecap="round" /></>)],
  flow: ['purple', (f) => (<><Rect x="2.5" y="3" width="9" height="7" rx="2" fill={f} /><Rect x="12.5" y="14" width="9" height="7" rx="2" fill={f} /><Path d="M7 10v4.5h10.5" stroke="#B7A6FF" strokeWidth={2} fill="none" strokeLinecap="round" /></>)],
  chart: ['green', (f) => (<><Rect x="3.5" y="12" width="4.2" height="8.5" rx="1.4" fill={f} opacity={0.6} /><Rect x="9.9" y="6.5" width="4.2" height="14" rx="1.4" fill={f} /><Rect x="16.3" y="3.5" width="4.2" height="17" rx="1.4" fill={f} opacity={0.8} /></>)],
  report: ['purple', (f) => (<><Rect x="4" y="3" width="16" height="18" rx="3" fill={f} /><Path d="M8 15.5v-2.5M12 15.5V9M16 15.5v-4.5" stroke={W} strokeWidth={2} strokeLinecap="round" /></>)],
  book: ['green', (f) => (<><Path d="M2.5 5.2c3-1.3 6.2-1 9 1v14c-2.8-2-6-2.3-9-1z" fill={f} /><Path d="M21.5 5.2c-3-1.3-6.2-1-9 1v14c2.8-2 6-2.3 9-1z" fill={f} opacity={0.75} /></>)],
  search: ['blue', (f) => (<><Circle cx="10.5" cy="10.5" r="7" fill={f} /><Circle cx="10.5" cy="10.5" r="3.8" fill={W} opacity={0.35} /><Path d="M15.6 15.6l4.6 4.6" stroke="#333D48" strokeWidth={2.6} strokeLinecap="round" /></>)],
  shield: ['green', (f) => (<><Path d="M12 2.5l8 3v6c0 5-3.4 8.6-8 10-4.6-1.4-8-5-8-10v-6z" fill={f} /><Path d="M8.6 12l2.4 2.4 4.4-4.6" stroke={W} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" /></>)],
  link: ['teal', (f) => (<><Circle cx="12" cy="12" r="9" fill={f} /><Path d="M10.6 13.4l2.8-2.8M11.2 8.6l1.2-1.2a2.6 2.6 0 0 1 3.7 3.7l-1.2 1.2M12.8 15.4l-1.2 1.2a2.6 2.6 0 0 1-3.7-3.7l1.2-1.2" stroke={W} strokeWidth={1.8} fill="none" strokeLinecap="round" /></>)],
  team: ['orange', (f) => (<><Circle cx="9" cy="8" r="3.6" fill={f} /><Path d="M2.5 19.5c.6-3.6 3.2-5.6 6.5-5.6s5.9 2 6.5 5.6z" fill={f} /><Circle cx="16.5" cy="9" r="2.8" fill={f} opacity={0.6} /><Path d="M16 14c3 0 5 1.6 5.5 4.6H17" fill={f} opacity={0.6} /></>)],
  gift: ['red', (f) => (<><Rect x="3.5" y="9" width="17" height="11.5" rx="2" fill={f} /><Rect x="2.5" y="6.5" width="19" height="4" rx="1.4" fill={f} opacity={0.75} /><Path d="M12 6.5v14" stroke={W} strokeWidth={1.8} /></>)],
  warn: ['yellow', (f) => (<><Path d="M10.3 3.6a2 2 0 0 1 3.4 0l7.7 13.3a2 2 0 0 1-1.7 3H4.3a2 2 0 0 1-1.7-3z" fill={f} /><Path d="M12 9v4.3" stroke={W} strokeWidth={2.2} strokeLinecap="round" /><Circle cx="12" cy="16.6" r="1.25" fill={W} /></>)],
  plus: ['grey', (f) => (<><Circle cx="12" cy="12" r="9" fill={f} /><Path d="M12 8v8M8 12h8" stroke={W} strokeWidth={2} strokeLinecap="round" /></>)],
  bell: ['yellow', (f) => (<><Path d="M6 16.5v-5.5a6 6 0 0 1 12 0v5.5l1.6 2H4.4z" fill={f} /><Path d="M10 20.2a2.2 2.2 0 0 0 4 0" stroke="#F7B500" strokeWidth={1.8} fill="none" strokeLinecap="round" /></>)],
  gear: ['grey', (f) => (<><Circle cx="12" cy="12" r="8.5" fill={f} /><Circle cx="12" cy="12" r="3" fill={W} /></>)],
};

export function Glyph({ name, size = 22 }: { name: string; size?: number }) {
  if (name === 'soda') return <SodaMark size={size} />;
  const [col, draw] = G[name] ?? G.doc;
  const [a, b] = COL[col];
  const id = 'gl-' + col;
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      <Defs>
        <LinearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <Stop offset="0" stopColor={a} />
          <Stop offset="1" stopColor={b} />
        </LinearGradient>
      </Defs>
      {draw(`url(#${id})`)}
    </Svg>
  );
}

const CAT: Record<string, string> = { '배송 조회': 'truck', '주문 취소': 'doc', '주문 변경': 'doc', 교환: 'exchange', '반품·환불': 'exchange', '제품 불량': 'warn', '고객 응대': 'chat' };
export const catGlyph = (cat: string) => CAT[cat] ?? 'inbox';

// 연회색 둥근 칸 안의 아이콘 (토스 메뉴 줄 앞)
import { View } from 'react-native';
export function GlyphBox({ name, box = 40, size = 22 }: { name: string; box?: number; size?: number }) {
  return (
    <View style={{ width: box, height: box, borderRadius: box * 0.3, backgroundColor: '#F2F4F6', alignItems: 'center', justifyContent: 'center' }}>
      <Glyph name={name} size={size} />
    </View>
  );
}
